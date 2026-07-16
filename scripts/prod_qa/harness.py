#!/usr/bin/env python3
"""Core plumbing for the worldview prod-QA harness.

This module is the shared runtime the per-service check modules build on. It is
deliberately **stdlib-only** (no pip deps) so it runs anywhere `kubectl` +
`curl` are on PATH and `KUBECONFIG` points at the prod cluster — exactly like
the sibling `scripts/prod_e2e_smoke.py`, whose philosophy this suite extends.

Responsibilities
----------------
* PASS / WARN / FAIL result plumbing (`Report`, `Status`).
* Shell / kubectl helpers with timeouts.
* Postgres access: `psql_scalar` (one query) and `psql_many` (BATCHED — one
  `kubectl exec` per DB for N queries; the network round-trip per exec is the
  dominant cost against a tunnelled prod cluster, so batching matters).
* Kafka helpers (consumer-group health, topic offsets).
* Pod / deployment inspection.
* The `Ctx` object every check receives: namespaces, a memoised `api` result
  blob from the in-pod prober, and typed helpers.

Everything here is READ-ONLY against prod. No check in this suite writes,
mutates, or deletes cluster or DB state.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field

# ── Namespaces / well-known handles ──────────────────────────────────────────
NS = "worldview"  # application services (S1-S10)
INFRA_NS = "infra"  # postgres, kafka, minio, schema-registry, valkey, gliner
MON_NS = "monitoring"
PUBLIC_HOST = "api.worldview-labs.com"
NODE_IP = "116.203.198.118"
POSTGRES_POD = "postgres-0"
POSTGRES_CONTAINER = "postgres"  # the pod also has an init container
KAFKA_POD = "kafka-broker-0"
KAFKA_CONTAINER = "kafka"
GATEWAY_LABEL = "app.kubernetes.io/name=api-gateway"

# ── Result plumbing ──────────────────────────────────────────────────────────
PASS, WARN, FAIL = "PASS", "WARN", "FAIL"
_C = {PASS: "\033[32m", WARN: "\033[33m", FAIL: "\033[31m", "END": "\033[0m"}


@dataclass
class Report:
    """Collects (service, name, status, detail) rows and prints them live."""

    rows: list[tuple[str, str, str, str]] = field(default_factory=list)
    quiet: bool = False

    def add(self, service: str, name: str, status: str, detail: str = "") -> None:
        self.rows.append((service, name, status, detail))
        if not self.quiet:
            c = _C.get(status, "")
            print(f"  {c}{status:4}{_C['END']}  [{service}] {name}" + (f" — {detail}" if detail else ""))

    # Convenience wrappers so check code reads declaratively.
    def ok(self, service: str, name: str, detail: str = "") -> None:
        self.add(service, name, PASS, detail)

    def warn(self, service: str, name: str, detail: str = "") -> None:
        self.add(service, name, WARN, detail)

    def fail(self, service: str, name: str, detail: str = "") -> None:
        self.add(service, name, FAIL, detail)

    def check(self, service: str, name: str, condition: bool, detail: str = "", *, soft: bool = False) -> bool:
        """Assert `condition`; PASS if true, else WARN (soft) / FAIL (hard)."""
        self.add(service, name, PASS if condition else (WARN if soft else FAIL), detail)
        return condition

    def floor(
        self, service: str, name: str, value: float | int, floor: float | int, *, soft: bool = True, unit: str = ""
    ) -> bool:
        """Assert value >= floor. Coverage/volume floors default to WARN (soft)."""
        okv = value >= floor
        detail = f"{value}{unit} (floor {floor}{unit})"
        self.add(service, name, PASS if okv else (WARN if soft else FAIL), detail)
        return okv

    def counts(self) -> dict[str, int]:
        out = {PASS: 0, WARN: 0, FAIL: 0}
        for _, _, s, _ in self.rows:
            out[s] = out.get(s, 0) + 1
        return out


# ── Shell / kubectl ──────────────────────────────────────────────────────────
def sh(cmd: str, timeout: int = 60) -> tuple[int, str]:
    """Run a shell command; return (exit_code, combined stdout+stderr).

    `shell=True` is intentional and safe here: every command is assembled from
    module constants and this harness's own SQL/prober text, never from network
    or user input.
    """
    try:
        p = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)  # noqa: S602
        return p.returncode, (p.stdout + p.stderr).strip()
    except subprocess.TimeoutExpired:
        return 124, "timeout"


def kubectl(args: str, timeout: int = 60) -> tuple[int, str]:
    return sh(f"kubectl {args}", timeout)


# ── Postgres ─────────────────────────────────────────────────────────────────
def _bash_sq(s: str) -> str:
    """Escape a string for embedding inside a single-quoted bash word."""
    return s.replace("'", "'\"'\"'")


def psql_scalar(db: str, sql: str, timeout: int = 40) -> str:
    """Run one query; return the first meaningful line (stripped) or ''.

    Filters psql chatter lines (`could not`, `error`, container-default notice)
    so a scalar count comes back clean.
    """
    _, out = kubectl(
        f'-n {INFRA_NS} exec {POSTGRES_POD} -c {POSTGRES_CONTAINER} -- psql -U postgres -d {db} -tAc "{sql}"',
        timeout,
    )
    for ln in out.splitlines():
        s = ln.strip()
        low = s.lower()
        if s and "could not" not in low and "default" not in low and "error" not in low and "context:" not in low:
            return s
    return ""


def psql_many(db: str, queries: dict[str, str], timeout: int = 90) -> dict[str, str]:
    """Run many single-row queries against ONE DB in a single `kubectl exec`.

    Each query MUST return a single line (use aggregates / string_agg). Results
    come back as `KEY\\x1f<value>` lines. Missing tables → the psql error is
    swallowed and that key maps to '' (so a check can treat absent-table as
    skip/warn rather than crash the whole run).
    """
    sep = "\x1f"
    parts: list[str] = []
    for name, sql in queries.items():
        q = _bash_sq(sql)
        # Print KEY, sep, then the query result with newlines stripped, then a real newline.
        parts.append(
            f"printf '%s' '{name}{sep}'; "
            f"psql -U postgres -d {db} -tAc '{q}' 2>/dev/null | tr -d '\\n'; "
            f"printf '\\n'"
        )
    script = _bash_sq(" ; ".join(parts))
    _, out = kubectl(f"-n {INFRA_NS} exec {POSTGRES_POD} -c {POSTGRES_CONTAINER} -- bash -c '{script}'", timeout)
    result: dict[str, str] = {name: "" for name in queries}
    for ln in out.splitlines():
        if sep in ln:
            k, _, v = ln.partition(sep)
            if k in result:
                result[k] = v.strip()
    return result


def as_int(s: str, default: int = -1) -> int:
    try:
        return int(s)
    except (ValueError, TypeError):
        return default


def as_float(s: str, default: float = float("nan")) -> float:
    try:
        return float(s)
    except (ValueError, TypeError):
        return default


def pct(num: str | int, den: str | int) -> float:
    n, d = as_int(str(num)), as_int(str(den))
    if d <= 0 or n < 0:
        return -1.0
    return round(100 * n / d, 1)


# ── Kafka ────────────────────────────────────────────────────────────────────
def kafka_topic_offsets(topics: list[str]) -> dict[str, int]:
    """Total high-watermark offset per topic (used for DLQ-empty checks)."""
    out_map: dict[str, int] = {}
    for t in topics:
        _, out = kubectl(
            f"-n {INFRA_NS} exec {KAFKA_POD} -c {KAFKA_CONTAINER} -- sh -c "
            f"'kafka-run-class.sh kafka.tools.GetOffsetShell --broker-list localhost:9092 --topic {t} 2>/dev/null'"
        )
        total = 0
        for ln in out.splitlines():
            parts = ln.split(":")
            if len(parts) == 3 and parts[2].strip().isdigit():
                total += int(parts[2])
        out_map[t] = total
    return out_map


def kafka_groups() -> list[str]:
    _, out = kubectl(
        f"-n {INFRA_NS} exec {KAFKA_POD} -c {KAFKA_CONTAINER} -- sh -c "
        f"'kafka-consumer-groups.sh --bootstrap-server localhost:9092 --list 2>/dev/null'"
    )
    return [g.strip() for g in out.splitlines() if g.strip()]


def kafka_group_describe(group: str) -> tuple[int, int, int]:
    """Return (partition_rows, total_lag, live_members) for a consumer group."""
    _, desc = kubectl(
        f"-n {INFRA_NS} exec {KAFKA_POD} -c {KAFKA_CONTAINER} -- sh -c "
        f"'kafka-consumer-groups.sh --bootstrap-server localhost:9092 --describe --group {group} 2>/dev/null'"
    )
    lag, members, rows = 0, 0, 0
    for ln in desc.splitlines()[1:]:
        f = ln.split()
        if len(f) >= 6 and f[5].isdigit():
            rows += 1
            lag += int(f[5])
            if len(f) >= 7 and f[6] != "-":
                members += 1
    return rows, lag, members


# ── Pods / deployments ───────────────────────────────────────────────────────
def pods(ns: str) -> list[tuple[str, str, str, str]]:
    """Return (name, ready, status, restarts) for every pod in a namespace."""
    _, out = kubectl(f"-n {ns} get pods --no-headers")
    result = []
    for ln in out.splitlines():
        f = ln.split()
        if len(f) >= 4:
            result.append((f[0], f[1], f[2], f[3]))
    return result


def job_pod_names(ns: str) -> set[str]:
    """Pods owned by a Job/CronJob — transient, excluded from readiness checks."""
    _, owners = kubectl(
        f"-n {ns} get pods -o custom-columns=NAME:.metadata.name,OWNER:.metadata.ownerReferences[0].kind --no-headers"
    )
    return {ln.split()[0] for ln in owners.splitlines() if ln.split()[1:] == ["Job"]}


def running_pod(label: str, ns: str = NS) -> str:
    _, out = kubectl(f"-n {ns} get pods -l {label} --no-headers")
    for ln in out.splitlines():
        f = ln.split()
        if len(f) >= 3 and f[2] == "Running":
            return f[0]
    return ""


def pod_by_prefix(ns: str, prefix: str) -> str:
    """First Running pod in `ns` whose name starts with `prefix` (or exact match)."""
    _, out = kubectl(f"-n {ns} get pods --no-headers")
    for ln in out.splitlines():
        f = ln.split()
        if len(f) >= 3 and f[2] == "Running" and (f[0] == prefix or f[0].startswith(prefix)):
            return f[0]
    return ""


def df_bytes(ns: str, pod: str, container: str, mount: str) -> tuple[int, int, int]:
    """Return (total, used, avail) bytes for `mount` inside a pod's filesystem.

    Uses `df -B1` (1-byte blocks) and takes the last data line so a wrapped
    Filesystem column does not desync the field offsets. Returns (-1,-1,-1) on
    any failure so the caller can WARN-skip rather than crash.
    """
    cflag = f"-c {container} " if container else ""
    _, out = kubectl(f"-n {ns} exec {pod} {cflag}-- df -B1 {mount}", timeout=30)
    for ln in reversed(out.splitlines()):
        f = ln.split()
        # df output: FS 1B-blocks Used Avail Use% Mounted — total/used/avail are the last-4-before-mount ints.
        nums = [x for x in f if x.isdigit()]
        if len(nums) >= 3:
            return int(nums[0]), int(nums[1]), int(nums[2])
    return -1, -1, -1


def gateway_pod() -> str:
    return running_pod(GATEWAY_LABEL)


# ── Shared context passed to every check ─────────────────────────────────────
@dataclass
class Ctx:
    report: Report
    api: dict = field(default_factory=dict)  # in-pod prober results (see prober.py)
    aapl_entity_id: str = ""  # resolved once; unified instrument/entity id (ADR-F-16)

    def api_row(self, key: str) -> dict | None:
        return self.api.get(key)
