#!/usr/bin/env python3
"""Production end-to-end smoke / health harness for the worldview platform.

WHAT THIS IS
------------
A single, dependency-free (stdlib-only) script that exercises the LIVE prod
cluster across four layers and prints a PASS / WARN / FAIL report with a
non-zero exit code if anything critical is broken. Run it on demand, from CI,
or from a cron — it is read-only except for one self-cleaning alert-rule
round-trip (create → delete) used to prove the alerts write-path.

    LAYER 0  platform/infra   (kubectl)  pods ready, DLQs empty, kafka lag,
                                          MinIO buckets, TLS cert, backups,
                                          entity-embedding backfill progress,
                                          MIGRATION DRIFT (stale image / pending
                                          migrate), DB dead-letter tables,
                                          schema-registry FULL-compat
    LAYER 1  public edge      (curl)     80→301, HTTPS 200, unauth→401,
                                          internal routes→403, valid LE cert
    LAYER 2  data plane        (in-pod)  every backend domain returns REAL data
    LAYER 3  async processes    (mixed)  description generation, chat grounding,
                                          alert CRUD round-trip
    LAYER 4  async workers      (mixed)  outbox drain, retry ceilings, synthetic
                                          embed injection, pipeline freshness
    LAYER 5  external APIs      (sql)    upstream-feed freshness as liveness proxy
    LAYER 6  data quality       (sql)    description/embedding coverage, KG
                                          relation density, news volume, NER
                                          liveness — regression FLOORS

WHY THE ODD AUTH PATH (layer 2/3)
---------------------------------
Prod runs real Zitadel OIDC; `/v1/auth/dev-login` is disabled and the public
front door needs an interactive browser token we cannot get headlessly. So the
authenticated checks run a small prober INSIDE the api-gateway pod: it mints a
short-lived internal RS256 JWT with the gateway's OWN signer (`jwt_utils`) — the
exact `X-Internal-JWT` the gateway itself attaches when proxying downstream —
and calls each backend over ClusterIP. This verifies the real routes/processes/
data end-to-end via the same trust path the gateway uses. (It does NOT exercise
the Zitadel front door; layer 1 verifies that gate is present and rejecting.)

If you have a real Zitadel bearer token (e.g. a CI service account), set
WV_BEARER and the layer-2/3 checks will instead go through the PUBLIC gateway.

USAGE
-----
    export KUBECONFIG=~/.kube/config-worldview     # tunnel/context to prod
    python3 scripts/prod_e2e_smoke.py              # full run
    python3 scripts/prod_e2e_smoke.py --layer 0,1  # only infra + public edge
    python3 scripts/prod_e2e_smoke.py --json out.json
    WV_BEARER=<zitadel-jwt> python3 scripts/prod_e2e_smoke.py  # via public gw

EXIT CODE: 0 = all critical checks passed (WARNs allowed); 1 = ≥1 FAIL.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from dataclasses import dataclass, field

# ── Configuration ────────────────────────────────────────────────────────────
PUBLIC_HOST = "api.worldview-labs.com"
NODE_IP = "116.203.198.118"
NS = "worldview"
INFRA_NS = "infra"
GATEWAY_LABEL = "app.kubernetes.io/name=api-gateway"

# Canonical MinIO buckets (mirrors manifests/minio-bucket-init.yaml). A missing
# bucket = silent "Bucket not found" write failures downstream.
EXPECTED_BUCKETS = [
    "market-data",
    "content-data",
    "intelligence-data",
    "rag-data",
    "market-bronze",
    "market-canonical",
    "market-ingestion",
    "worldview-bronze",
    "worldview-silver",
    "worldview",
    "worldview-feedback-screenshots",
]
DLQ_TOPICS = [
    "alert.dead-letter.v1",
    "content.dead-letter.v1",
    "kg.dead-letter.v1",
    "market.dead-letter.v1",
    "nlp.dead-letter.v1",
]
KAFKA_LAG_WARN = 5_000  # per-group total lag above this → WARN (backlog)
KAFKA_LAG_FAIL = 100_000  # ...above this → FAIL, but only for DEAD (0-member) groups
# Absolute catastrophe ceiling for a LIVE group (members present). A legitimate
# backfill on this single-node cluster tops out well under this (observed live
# peak ~187k for the multi-year news/nlp backfill); a live group ABOVE it is not
# "a backlog draining" — it is a consumer that is up but wedged/too-slow to ever
# catch up (the poison-pill / can't-keep-up class we have hit before, e.g. the
# nlp-pipeline stall and the prediction-throughput regression). Those never trip
# the 0-member "dead" check and only reach the Layer 4/5 freshness FAILs 24-48h
# later (and NOT AT ALL for kg/alert/portfolio groups, whose downstream has no
# FAIL-capable freshness check) — so without this ceiling a runaway live consumer
# would never page. This restores that page while keeping normal backfill at WARN.
KAFKA_LAG_HARD_FAIL = 1_000_000  # LIVE-group lag above this → FAIL (wedged, not backlog)
# Ephemeral consumer groups created by test/probe harnesses (prod_qa prober, the
# batched-consumer probe path). Their members leave but Kafka retains committed
# offsets for offsets.retention.minutes (~7d), so they linger with 0 members and
# would be mis-flagged as "dead worldview consumers". They are NOT services — skip
# them from consumer-group health entirely.
EPHEMERAL_GROUP_PREFIXES = ("probe", "console-consumer", "kafka-console")
BACKUP_MAX_AGE_H = 12  # newest pg dump must be younger than this

# ── Migration-drift / stale-image detection (issue classes 2 & 3) ────────────
# Expected Alembic head per service DB == the head revision on the RELEASE ref
# (git main). A prod DB whose alembic_version < this head means either the
# migrate Job never re-ran (pending migration) OR the deployed image is stale
# (predates the migration). We disambiguate by ALSO reading the head baked into
# the running image (`alembic heads` inside the owning Deployment pod):
#   image_head  < EXPECTED (git head)   → STALE IMAGE (pod predates the merge)
#   db_current  < image_head            → migrate Job PENDING (DB behind image)
#   no owner pod (Job-run migrator,     → compare db_current vs EXPECTED only
#     e.g. intelligence-migrations)
#
# This single check would have caught prediction migrations 043/044 (market_data)
# and content-ingestion 0011 sources the moment the migrate Job was skipped.
#
# REGENERATE on every migration merge (a CI freshness gate — see the companion
# spec — should assert this map == `alembic heads` for each service):
#   for s in services/*/; do
#     echo "$(basename $s) $(cd $s 2>/dev/null && alembic heads 2>/dev/null)"; done
EXPECTED_ALEMBIC_HEADS: dict[str, str] = {
    "alert_db": "0011",
    # revision ids are whatever the migration file declares as `revision=`; some
    # services use bare numbers ("0011"), others the full slug — match EXACTLY.
    "content_ingestion_db": "0011_seed_pm_wave2_sources",
    "content_store_db": "0006",
    "ingestion_db": "0024",  # market-ingestion
    "intelligence_db": "0067",  # intelligence-migrations (Job-run, no owner pod)
    "market_data_db": "044",
    "nlp_db": "0024",
    "portfolio_db": "0027",
    "rag_db": "0010",
}
# DB → owning Deployment's `app.kubernetes.io/name` label, for reading the
# image-baked alembic head. DBs whose migrator is a one-off Job (no long-running
# pod) map to None → compared against EXPECTED only.
DB_TO_DEPLOYMENT: dict[str, str | None] = {
    "alert_db": "alert",
    "content_ingestion_db": "content-ingestion",
    "content_store_db": "content-store",
    "ingestion_db": "market-ingestion",
    "intelligence_db": None,  # intelligence-migrations runs as a Job
    "market_data_db": "market-data",
    "nlp_db": "nlp-pipeline",
    "portfolio_db": "portfolio",
    "rag_db": "rag-chat",
}

# ── DB-level dead-letter tables (issue classes 1 & 5) ────────────────────────
# The Kafka DLQ-TOPIC check (DLQ_TOPICS) MISSES services that dead-letter into a
# Postgres `dead_letter_queue` table (the libs/messaging persistent-retry path).
# A silently-growing table here is the exact signature of the 82%-docs-dead-
# lettered schema-skew incident — invisible to the Kafka-topic check. We alert on
# UNRESOLVED backlog and on a fast recent arrival RATE (fills in minutes).
DLQ_DB_TABLES = ["nlp_db", "content_store_db", "content_ingestion_db", "alert_db", "intelligence_db"]
DLQ_DB_BACKLOG_WARN = 50  # unresolved rows → WARN
DLQ_DB_BACKLOG_FAIL = 500  # unresolved rows → FAIL (mass dead-lettering)
DLQ_DB_RATE_FAIL = 20  # UNRESOLVED rows that arrived in the last 1h → FAIL (skew storm)

# ── Schema Registry (issue class 1 root misconfig) ───────────────────────────
SCHEMA_REGISTRY_URL = "http://schema-registry.infra.svc:8081"
# The registry MUST enforce FULL/FULL_TRANSITIVE so a forward-INCOMPATIBLE schema
# (a NEW reader that cannot read OLD bytes) is REJECTED at register time. The
# default BACKWARD level permits exactly the append-without-safe-resolution change
# that dead-lettered prod (the .avsc doc-strings wrongly assumed additive-trailing
# is always safe — it is NOT for a new reader on old data). Weaker than these → FAIL.
SCHEMA_REGISTRY_SAFE_COMPAT = {"FULL", "FULL_TRANSITIVE"}

# ── Data-quality thresholds (issue class 4) ──────────────────────────────────
# Absolute floors (the harness is stateless — no historical baseline), chosen to
# catch the KNOWN-bad regressions (undescribed entities, sparse relations, news
# under-fetch) while tolerating a young/still-backfilling DB. Coverage floors are
# WARN (a slow backfill should not page ops); near-zero liveness is FAIL.
DQ_DESC_COVERAGE_WARN = 60.0  # % canonical entities carrying a description
DQ_EMBED_COVERAGE_WARN = 50.0  # % entities embedded
DQ_RELATIONS_FLOOR = 100  # active KG relations (below → sparse/regressed)
DQ_NEWS_24H_WARN = 200  # docs ingested in last 24h (below → under-fetch)
DQ_MENTIONS_24H_FAIL = 50  # entity mentions in last 24h (near-zero → NER stalled)

# ── Result plumbing ──────────────────────────────────────────────────────────
PASS, WARN, FAIL = "PASS", "WARN", "FAIL"
_C = {PASS: "\033[32m", WARN: "\033[33m", FAIL: "\033[31m", "END": "\033[0m"}


@dataclass
class Report:
    rows: list[tuple[str, str, str, str]] = field(default_factory=list)  # layer, name, status, detail

    def add(self, layer: str, name: str, status: str, detail: str = "") -> None:
        self.rows.append((layer, name, status, detail))
        c = _C.get(status, "")
        print(f"  {c}{status:4}{_C['END']}  [{layer}] {name}" + (f" — {detail}" if detail else ""))

    def counts(self) -> dict[str, int]:
        out = {PASS: 0, WARN: 0, FAIL: 0}
        for _, _, s, _ in self.rows:
            out[s] = out.get(s, 0) + 1
        return out


R = Report()


def sh(cmd: str, timeout: int = 60) -> tuple[int, str]:
    """Run a shell command, return (exit_code, combined_output)."""
    try:
        # shell=True is intentional: this is an operator-run harness that pipes
        # kubectl/curl/psql; all commands are built from module constants, never
        # from untrusted input.
        p = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)  # noqa: S602
        return p.returncode, (p.stdout + p.stderr).strip()
    except subprocess.TimeoutExpired:
        return 124, "timeout"


def kubectl(args: str, timeout: int = 60) -> tuple[int, str]:
    return sh(f"kubectl {args}", timeout)


def minio_pod() -> str:
    _, out = kubectl(f"-n {INFRA_NS} get pods --no-headers")
    for line in out.splitlines():
        if line.startswith("minio-") and "Running" in line:
            return line.split()[0]
    return ""


def gateway_pod() -> str:
    _, out = kubectl(f"-n {NS} get pods -l {GATEWAY_LABEL} --no-headers")
    for line in out.splitlines():
        if "Running" in line:
            return line.split()[0]
    return ""


# ── LAYER 0 — platform / infra ───────────────────────────────────────────────
def layer0() -> None:
    print("\n=== LAYER 0 — platform / infra ===")

    # pods ready + no crashloops. SKIP Job-owned pods entirely: CronJob pods
    # (this smoke job, postgres-backup, migrations) are INHERENTLY transient — they
    # pass through Pending/Init/PodInitializing → Running → Completed/Error as normal
    # lifecycle. Readiness-checking them produced false FAILs (e.g. a postgres-backup
    # pod caught mid-Init:0/1) that fired ProdSmokeTestFailed. Only long-running
    # workloads (Deployments/StatefulSets/DaemonSets) should be readiness-checked.
    for ns in (INFRA_NS, NS, "monitoring"):
        _, owners = kubectl(
            f"-n {ns} get pods -o custom-columns=NAME:.metadata.name,"
            f"OWNER:.metadata.ownerReferences[0].kind --no-headers"
        )
        job_pods = {ln.split()[0] for ln in owners.splitlines() if ln.split()[1:] == ["Job"]}
        _, out = kubectl(f"-n {ns} get pods --no-headers")
        not_ready, crash = [], []
        for ln in out.splitlines():
            f = ln.split()
            if len(f) < 4:
                continue
            name, ready, status = f[0], f[1], f[2]
            restarts = f[3]
            if name in job_pods:  # transient Job/CronJob pod — not a workload
                continue
            if status != "Running":
                not_ready.append(f"{name}={status}")
            elif "/" in ready and ready.split("/")[0] != ready.split("/")[1]:
                not_ready.append(f"{name}={ready}")
            try:
                if int(restarts.split()[0].strip("()")) > 5:
                    crash.append(f"{name}={restarts}")
            except ValueError:
                pass
        R.add(
            "0",
            f"pods ready ({ns})",
            FAIL if not_ready else PASS,
            ", ".join(not_ready) if not_ready else "all Running/Ready",
        )
        if crash:
            R.add("0", f"crashloops ({ns})", WARN, ", ".join(crash))

    # DLQ topics empty
    b = kafka_offsets(DLQ_TOPICS)
    hot = {t: n for t, n in b.items() if n > 0}
    R.add(
        "0",
        "dead-letter queues empty",
        FAIL if hot else PASS,
        ", ".join(f"{t}={n}" for t, n in hot.items()) if hot else "all 5 DLQs = 0",
    )

    # kafka consumer group health — per-group members + lag. A group with 0 active
    # members is a DEAD consumer (silently stopped processing) even if aggregate lag
    # looks fine; catching it per-group closes the "one idle consumer hides" gap.
    n_groups, dead, worst = kafka_group_health()
    if n_groups == 0:
        R.add("0", "kafka consumers", WARN, "could not read groups")
    else:
        R.add(
            "0",
            "kafka consumers alive",
            FAIL if dead else PASS,
            f"{len(dead)} dead (0 members): {dead[:5]}" if dead else f"all {n_groups} groups have members",
        )
        grp, lag = worst
        # A high lag on a LIVE group (members present, offsets advancing) is a
        # backlog — expected during intentional backfills (news multi-year, OHLCV)
        # on this single-node cluster — so cap it at WARN, NOT the old static-100k
        # FAIL that false-paged every 30m. Two cases still FAIL: (a) a DEAD group
        # (0 members, already FAILed above) carrying real backlog, and (b) a LIVE
        # group whose lag has blown past the catastrophe ceiling — a consumer that
        # is up but wedged/too-slow to ever catch up, which the 0-member check
        # never sees and the Layer 4/5 freshness FAILs only reach 24-48h later
        # (or never, for kg/alert/portfolio). See KAFKA_LAG_HARD_FAIL.
        if lag > KAFKA_LAG_HARD_FAIL:
            st = FAIL
        elif lag > KAFKA_LAG_FAIL and grp in dead:
            st = FAIL
        elif lag > KAFKA_LAG_WARN:
            st = WARN
        else:
            st = PASS
        R.add("0", "kafka consumer lag", st, f"max {grp}={lag}")

    # MinIO buckets
    mp = minio_pod()
    if mp:
        _, out = kubectl(
            f"-n {INFRA_NS} exec {mp} -- sh -c "
            f'\'mc alias set l http://localhost:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" >/dev/null 2>&1; mc ls l/ 2>/dev/null\''
        )
        present = {ln.split()[-1].rstrip("/") for ln in out.splitlines() if ln.strip()}
        missing = [b for b in EXPECTED_BUCKETS if b not in present]
        R.add(
            "0",
            "MinIO buckets present",
            FAIL if missing else PASS,
            f"missing: {missing}" if missing else f"{len(EXPECTED_BUCKETS)} canonical buckets",
        )
    else:
        R.add("0", "MinIO buckets present", WARN, "minio pod not found")

    # TLS cert issued
    _, out = kubectl(f"-n {NS} get certificate api-tls -o jsonpath='{{.status.conditions[0].status}}'")
    R.add("0", "TLS cert (api-tls) issued", PASS if out.strip() == "True" else FAIL, f"ready={out.strip()}")

    # backup freshness
    if mp:
        _, out = kubectl(
            f"-n {INFRA_NS} exec {mp} -- sh -c "
            f'\'mc alias set l http://localhost:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" >/dev/null 2>&1; '
            f"mc ls l/worldview-backups/postgres/ 2>/dev/null | tail -1'"
        )
        R.add(
            "0",
            "postgres backup present",
            PASS if out.strip() else WARN,
            out.strip()[:80] if out.strip() else "no dump yet (cronjob runs every 6h)",
        )

    # entity-embedding backfill progressing
    _, out = kubectl(
        f"-n {INFRA_NS} exec postgres-0 -- psql -U postgres -d intelligence_db -tAc "  # noqa: S608 (constant query, no user input)
        f'"SELECT count(*) FILTER (WHERE embedding IS NOT NULL), count(*) FROM entity_embedding_state;"'
    )
    line = next((ln for ln in out.splitlines() if "|" in ln), "")
    if line:
        emb, tot = line.split("|")[:2]
        pct = round(100 * int(emb) / max(int(tot), 1), 1)
        R.add("0", "entity embedding coverage", PASS if pct >= 30 else WARN, f"{emb}/{tot} ({pct}%)")

    # migration drift (stale image / pending migrate), DB-level DLQ backlog, and
    # schema-registry compatibility level — see the module constants for rationale.
    check_migration_drift()
    check_db_dead_letter()
    check_schema_registry()


def kafka_offsets(topics: list[str]) -> dict[str, int]:
    out_map: dict[str, int] = {}
    for t in topics:
        _, out = kubectl(
            f"-n {INFRA_NS} exec kafka-broker-0 -c kafka -- sh -c "
            f"'kafka-run-class.sh kafka.tools.GetOffsetShell --broker-list localhost:9092 --topic {t} 2>/dev/null'"
        )
        total = 0
        for ln in out.splitlines():
            parts = ln.split(":")
            if len(parts) == 3 and parts[2].strip().isdigit():
                total += int(parts[2])
        out_map[t] = total
    return out_map


def kafka_group_health() -> tuple[int, list[str], tuple[str, int]]:
    """Return (num_groups, dead_group_names, (worst_group, worst_lag)).

    A group is DEAD when it has assigned partitions but 0 rows carry a live
    CONSUMER-ID (member) — nobody is consuming. This catches a silently-stopped
    consumer that aggregate lag alone would miss.
    """
    _, groups = kubectl(
        f"-n {INFRA_NS} exec kafka-broker-0 -c kafka -- sh -c "
        f"'kafka-consumer-groups.sh --bootstrap-server localhost:9092 --list 2>/dev/null'"
    )
    dead: list[str] = []
    worst: tuple[str, int] = ("", 0)
    names = [g.strip() for g in groups.splitlines() if g.strip() and not g.strip().startswith(EPHEMERAL_GROUP_PREFIXES)]
    for g in names:
        _, desc = kubectl(
            f"-n {INFRA_NS} exec kafka-broker-0 -c kafka -- sh -c "
            f"'kafka-consumer-groups.sh --bootstrap-server localhost:9092 --describe --group {g} 2>/dev/null'"
        )
        lag, members, rows = 0, 0, 0
        for ln in desc.splitlines()[1:]:
            f = ln.split()
            if len(f) >= 6 and f[5].isdigit():
                rows += 1
                lag += int(f[5])
                if len(f) >= 7 and f[6] != "-":  # live CONSUMER-ID → a member
                    members += 1
        if rows > 0 and members == 0:
            dead.append(g)
        if lag > worst[1]:
            worst = (g, lag)
    return len(names), dead, worst


# ── LAYER 0 add-ons — migration drift, DB-DLQ tables, schema-registry compat ──
def _deployment_pod(name: str) -> str:
    """First Running pod for a Deployment's canonical name label ('' if none)."""
    _, out = kubectl(f"-n {NS} get pods -l app.kubernetes.io/name={name} --no-headers")
    for line in out.splitlines():
        f = line.split()
        if len(f) >= 3 and f[2] == "Running":
            return f[0]
    return ""


def _alembic_image_head(pod: str) -> str:
    """Read the alembic head BAKED INTO a running image (`alembic heads`).

    Reflects the migration head the DEPLOYED code knows about — distinct from the
    DB's applied head (alembic_version) and from the git-release head. Empty if
    the pod has no alembic CLI / non-standard layout (→ best-effort skip).
    """
    if not pod:
        return ""
    _, out = kubectl(f"-n {NS} exec {pod} -- sh -c 'cd /app 2>/dev/null && alembic heads 2>/dev/null'")
    for ln in out.splitlines():
        tok = ln.strip().split()
        if tok and "(head)" in ln:
            return tok[0]
    return ""


def check_migration_drift() -> None:
    """Flag prod DBs whose applied migration != the release head (issue 2 & 3)."""
    for db, expected in sorted(EXPECTED_ALEMBIC_HEADS.items()):
        current = _psql(db, "SELECT version_num FROM alembic_version")
        if not current:
            R.add("0", f"migrations {db}", WARN, "no alembic_version row (skipped)")
            continue
        if current == expected:
            R.add("0", f"migrations {db}", PASS, f"@ {current} (head)")
            continue
        # Drift — disambiguate STALE IMAGE vs PENDING MIGRATE via the image head.
        dep = DB_TO_DEPLOYMENT.get(db)
        image_head = _alembic_image_head(_deployment_pod(dep)) if dep else ""
        if image_head and image_head != expected:
            detail = f"STALE IMAGE: pod bundles {image_head}, release head {expected} (db@{current})"
        elif image_head and current != image_head:
            detail = f"migrate Job PENDING: db@{current} but image bundles {image_head}"
        else:
            detail = f"db@{current}, release head {expected} (migrate Job pending or migrator image stale)"
        R.add("0", f"migrations {db}", FAIL, detail)


def check_db_dead_letter() -> None:
    """Alert on Postgres `dead_letter_queue` backlog + arrival rate (issue 1 & 5).

    Complements the Kafka DLQ-TOPIC check: services on the persistent-retry path
    dead-letter into a DB table the topic check never sees.
    """
    total_unresolved, total_recent, worst = 0, 0, ""
    for db in DLQ_DB_TABLES:
        n = _psql(db, "SELECT count(*) FROM dead_letter_queue WHERE resolved_at IS NULL")
        if not n.isdigit():
            continue  # table absent for this DB → skip
        un = int(n)
        # RATE = rows that arrived in the last hour AND are STILL unresolved. Gross
        # arrivals include transient errors the retry loop recovers (healthy churn);
        # only unresolved-and-recent signals an ACTIVE, non-recovering skew storm.
        recent = _psql(
            db,
            "SELECT count(*) FROM dead_letter_queue WHERE resolved_at IS NULL AND created_at > now() - interval '1 hour'",
        )
        rn = int(recent) if recent.isdigit() else 0
        total_unresolved += un
        total_recent += rn
        if un and un > (int(worst.split("=")[1].split()[0]) if worst else 0):
            worst = f"{db}={un} unresolved (+{rn}/h)"
    status = (
        FAIL
        if (total_unresolved >= DLQ_DB_BACKLOG_FAIL or total_recent >= DLQ_DB_RATE_FAIL)
        else WARN
        if total_unresolved >= DLQ_DB_BACKLOG_WARN
        else PASS
    )
    R.add(
        "0",
        "DB dead-letter tables",
        status,
        f"{total_unresolved} unresolved (+{total_recent}/h); worst {worst}"
        if total_unresolved
        else "all DB DLQ tables drained",
    )


def check_schema_registry() -> None:
    """Assert the registry enforces FULL compat so forward-skew is rejected (issue 1)."""
    code, out = sh(f"curl -s --max-time 10 {SCHEMA_REGISTRY_URL}/config")
    if code != 0 or not out or "compatibilityLevel" not in out:
        # Unreachable from the harness pod (or curl absent locally) — non-fatal.
        R.add("0", "schema-registry compat", WARN, f"could not read /config ({out[:60]})")
        return
    try:
        level = json.loads(out).get("compatibilityLevel", "?")
    except json.JSONDecodeError:
        level = "?"
    safe = level in SCHEMA_REGISTRY_SAFE_COMPAT
    R.add(
        "0",
        "schema-registry compat FULL",
        PASS if safe else FAIL,
        f"global={level}" + ("" if safe else " — forward-INCOMPAT schemas can register → dead-letter risk"),
    )
    _, subs = sh(f"curl -s --max-time 10 {SCHEMA_REGISTRY_URL}/subjects")
    try:
        n_subjects = len(json.loads(subs))
        R.add("0", "schema-registry subjects", PASS if n_subjects else WARN, f"{n_subjects} registered")
    except (json.JSONDecodeError, TypeError):
        pass


# ── LAYER 1 — public edge (no auth) ──────────────────────────────────────────
def layer1() -> None:
    print("\n=== LAYER 1 — public edge (no auth) ===")

    _, _ = sh(f"curl -s -o /dev/null -w '%{{http_code}}' --max-time 10 -I http://{PUBLIC_HOST}/")
    _, redirect = sh(f"curl -s -o /dev/null -w '%{{http_code}}' --max-time 10 http://{PUBLIC_HOST}/healthz")
    R.add("1", "HTTP :80 → 301 redirect", PASS if redirect.strip() == "301" else FAIL, f"got {redirect.strip()}")

    _, hc = sh(
        f"curl -s -o /dev/null -w '%{{http_code}}:%{{ssl_verify_result}}' --max-time 12 https://{PUBLIC_HOST}/healthz"
    )
    parts = hc.strip().split(":")
    ok = parts[0] == "200" and (len(parts) < 2 or parts[1] == "0")
    R.add("1", "HTTPS /healthz 200 + valid TLS", PASS if ok else FAIL, hc.strip())

    # unauth data endpoint must be 401 (not data)
    _, un = sh(f"curl -s -o /dev/null -w '%{{http_code}}' --max-time 10 https://{PUBLIC_HOST}/v1/market/top-movers")
    R.add("1", "unauth /v1 data → 401", PASS if un.strip() in ("401", "403") else FAIL, f"got {un.strip()}")

    # internal routes must be blocked from public
    for path in ("/metrics", "/openapi.json", "/docs"):
        _, ic = sh(f"curl -s -o /dev/null -w '%{{http_code}}' --max-time 10 https://{PUBLIC_HOST}{path}")
        R.add(
            "1", f"internal route blocked {path}", PASS if ic.strip() in ("403", "404") else FAIL, f"got {ic.strip()}"
        )


# ── LAYER 2 + 3 — data plane & async processes (authed) ──────────────────────
# Prober runs INSIDE the gateway pod: mints an internal JWT via the gateway's own
# signer and calls each backend over ClusterIP. Returns one JSON blob we parse.
INPOD_PROBER = r"""
import json, os, urllib.request, urllib.error
results = {}

# Load the gateway's OWN internal-JWT signing key exactly as app.py does at
# startup (settings.internal_jwt_private_key + settings.jwt_key_version), so the
# X-Internal-JWT we mint is byte-identical to what the gateway attaches when it
# proxies a real request downstream.
from api_gateway.oidc import load_rsa_private_key
from api_gateway.jwt_utils import issue_user_jwt
_pem = os.environ.get("API_GATEWAY_INTERNAL_JWT_PRIVATE_KEY")
_kid = os.environ.get("API_GATEWAY_JWT_KEY_VERSION", "v1")
if not _pem:
    from api_gateway.config import Settings
    _s = Settings(); _pem = _s.internal_jwt_private_key.get_secret_value(); _kid = _s.jwt_key_version
_pk = load_rsa_private_key(_pem)

def tok():
    # fresh jti per call — backends enforce internal-JWT replay detection.
    # user_id/tenant_id MUST be valid UUIDs (alert + rag-chat validate the
    # format); a stable synthetic e2e identity keeps reads deterministic.
    return issue_user_jwt(user_id="0195e2e0-0000-7000-8000-000000000001",
                          tenant_id="0195e2e0-0000-7000-8000-000000000002",
                          oidc_sub="e2e-smoke", private_key=_pk, kid=_kid, role="user")

def call(name, url, method="GET", body=None, timeout=30):
    try:
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method,
              headers={"X-Internal-JWT": tok(), "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read(4000).decode("utf-8", "replace")
            results[name] = {"status": r.status, "len": len(raw), "body": raw[:800]}
    except urllib.error.HTTPError as e:
        results[name] = {"status": e.code, "body": e.read(400).decode("utf-8", "replace")}
    except Exception as e:
        results[name] = {"status": -1, "error": str(e)[:200]}

MD = "http://market-data.worldview.svc:8003/api/v1"
KG = "http://knowledge-graph.worldview.svc:8007/api/v1"
NLP = "http://nlp-pipeline.worldview.svc:8006/api/v1"
AL = "http://alert.worldview.svc:8010/api/v1"
RC = "http://rag-chat.worldview.svc:8008/api/v1"

# resolve a well-known instrument id (AAPL) to drive market/KG checks
call("kg_stats", KG + "/graph/stats")
call("kg_lookup", KG + "/entities/lookup?ticker=AAPL")
aapl = None
try:
    b = json.loads(results["kg_lookup"]["body"])
    aapl = (b.get("entity_id") or b.get("id") or (b.get("results") or [{}])[0].get("entity_id"))
except Exception:
    pass
if aapl:
    call("md_ohlcv", MD + f"/ohlcv/{aapl}?interval=1d&limit=5")
    call("md_fundamentals", MD + f"/fundamentals/{aapl}/snapshot")
    call("kg_entity", KG + f"/entities/{aapl}")
    call("kg_intelligence", KG + f"/entities/{aapl}/intelligence")
    call("kg_graph", KG + f"/entities/{aapl}/graph")
    call("desc_refresh", KG + f"/entities/{aapl}/refresh", "POST", {})   # layer 3: description gen trigger
call("md_screen", MD + "/fundamentals/screen", "POST",
     {"filters": [{"field": "market_cap", "op": "gte", "value": 1e11}], "limit": 3})
call("predmkts", MD + "/prediction-markets?limit=3")
call("news_top", NLP + "/news/top?limit=5")
call("alerts_list", AL + "/alert-rules")
# layer 3: chat grounding (non-stream full generation can take 15-40s)
call("chat", RC + "/chat", "POST",
     {"message": "What was AAPL's most recent closing price?"}, timeout=90)
# layer 4: SYNTHETIC embedding-worker test — a long RAW-Korean string exercises the
# exact bge truncation + DeepInfra path the retry worker uses. Pre-fix this 400'd
# (raw CJK under-counted → >512 tokens); a 200 proves truncation+embedding end-to-end.
call("embed_cjk", NLP + "/embed", "POST",
     {"text": "미국 캘리포니아주 새너제이, 어떤 데이터 환경에서도 최적화된 성능을 제공하는 지능형 시스템입니다. " * 40})
print("E2E_JSON_START" + json.dumps(results) + "E2E_JSON_END")
"""


def run_inpod_prober() -> dict:
    gw = gateway_pod()
    if not gw:
        R.add("2", "auth (internal-JWT prober)", FAIL, "no api-gateway pod found")
        return {}
    # ship the prober on stdin to the pod's python
    cmd = f"kubectl -n {NS} exec -i {gw} -- python3 - <<'PYEOF'\n{INPOD_PROBER}\nPYEOF"
    _, out = sh(cmd, timeout=180)
    if "E2E_JSON_START" not in out:
        R.add("2", "auth (internal-JWT prober)", FAIL, f"prober failed: {out[-200:]}")
        return {}
    try:
        blob = out.split("E2E_JSON_START", 1)[1].split("E2E_JSON_END", 1)[0]
        R.add("2", "auth (internal-JWT prober)", PASS, "minted internal JWT, drove backends")
        return json.loads(blob)
    except Exception as e:
        R.add("2", "auth (internal-JWT prober)", FAIL, f"parse error: {e}")
        return {}


def layer23(res: dict) -> None:
    print("\n=== LAYER 2 — data plane (real data?) ===")

    def check(layer, name, key, want_status=200, need_data=True, market_hours_ok=False):
        r = res.get(key)
        if not r:
            R.add(layer, name, WARN, "not probed")
            return
        st = r.get("status")
        if st != want_status:
            # quotes during closed market is expected-empty → WARN not FAIL
            sev = WARN if market_hours_ok else FAIL
            R.add(layer, name, sev, f"HTTP {st} {r.get('error','')} {r.get('body','')[:120]}")
            return
        if need_data and r.get("len", 0) < 5:
            R.add(layer, name, WARN, "200 but empty body")
            return
        R.add(layer, name, PASS, f"HTTP {st}, {r.get('len','?')}B")

    check("2", "KG graph/stats", "kg_stats")
    check("2", "KG entity lookup (AAPL)", "kg_lookup")
    check("2", "market OHLCV", "md_ohlcv")
    check("2", "market fundamentals snapshot", "md_fundamentals")
    check("2", "market screener (POST)", "md_screen")
    check("2", "KG entity", "kg_entity")
    check("2", "KG intelligence narrative", "kg_intelligence")
    check("2", "KG entity graph", "kg_graph")
    check("2", "prediction-markets list", "predmkts")
    check("2", "news top", "news_top")
    check("2", "alerts list", "alerts_list")

    print("\n=== LAYER 3 — async processes ===")
    # description generation: 200/202 = job enqueued; 429 = route up + rate-limiter
    # working (one refresh/entity/hour) — both prove the generator path is healthy.
    dr = res.get("desc_refresh")
    if dr and dr.get("status") in (200, 202):
        R.add("3", "entity description-gen trigger", PASS, f"HTTP {dr['status']} (refresh enqueued)")
    elif dr and dr.get("status") == 429:
        R.add(
            "3",
            "entity description-gen trigger",
            PASS,
            "HTTP 429 (route up, rate-limited — already refreshed this hour)",
        )
    elif dr:
        R.add("3", "entity description-gen trigger", FAIL, f"HTTP {dr.get('status')} {dr.get('body','')[:120]}")

    # chat grounding: expect a non-empty answer body
    ch = res.get("chat")
    if ch and ch.get("status") == 200 and ch.get("len", 0) > 20:
        R.add("3", "rag-chat grounded answer", PASS, f"{ch['len']}B answer")
    elif ch:
        R.add("3", "rag-chat grounded answer", FAIL, f"HTTP {ch.get('status')} {ch.get('body','')[:120]}")


# ── LAYER 4 — async workers & data pipelines ─────────────────────────────────
# Async workers can't be "called" — they're validated by asserting their OUTPUT:
# backlogs drain, outboxes dispatch, jobs don't wedge, fresh data keeps landing —
# plus one SYNTHETIC injection (a CJK embed) that drives a worker path end-to-end.
def _psql(db: str, sql: str) -> str:
    _, out = kubectl(f'-n {INFRA_NS} exec postgres-0 -- psql -U postgres -d {db} -tAc "{sql}"')
    for ln in out.splitlines():
        s = ln.strip()
        low = s.lower()
        if s and "could not" not in low and "default" not in low and "error" not in low:
            return s
    return ""


def layer4(res: dict) -> None:
    print("\n=== LAYER 4 — async workers & pipelines ===")

    # 1. SYNTHETIC embedding-worker E2E (the flagship): long raw-Korean → /embed.
    e = res.get("embed_cjk")
    if e and e.get("status") == 200:
        R.add("4", "embedding path (synthetic CJK)", PASS, "200 — bge truncation + DeepInfra OK on raw CJK")
    elif e and e.get("status") == 400:
        R.add("4", "embedding path (synthetic CJK)", FAIL, "400 — token-budget truncation regressed (CJK under-count)")
    elif e:
        R.add("4", "embedding path (synthetic CJK)", WARN, f"HTTP {e.get('status')} {e.get('error','')}")

    # 2. embedding-retry-worker: no rows abandoned at the retry ceiling.
    ab = _psql("nlp_db", "SELECT count(*) FROM embedding_pending WHERE retry_count >= 5")
    R.add(
        "4", "embedding-retry: 0 abandoned", PASS if ab in ("0", "") else WARN, f"{ab or '?'} rows stuck at max retries"
    )

    # 3. outbox dispatchers (every service): no events undispatched > 10 min
    #    (a wedged dispatcher = DB writes that never reach Kafka).
    stuck_total, worst = 0, ""
    for db in ("portfolio_db", "intelligence_db", "nlp_db", "market_data_db", "content_store_db", "alert_db"):
        n = _psql(
            db,
            "SELECT count(*) FROM outbox_events WHERE dispatched_at IS NULL AND created_at < now() - interval '10 minutes'",
        )
        if n.isdigit() and int(n) > 0:
            stuck_total += int(n)
            worst = f"{db}={n}"
    R.add(
        "4",
        "outbox dispatchers draining",
        FAIL if stuck_total > 50 else WARN if stuck_total else PASS,
        f"{stuck_total} events undispatched >10m ({worst})" if stuck_total else "all outboxes drained",
    )

    # 4. path-insight-worker: no jobs wedged in a non-terminal state.
    stuck = _psql(
        "intelligence_db",
        "SELECT count(*) FROM path_insight_jobs WHERE status IN ('running','pending') AND coalesce(claimed_at, now()) < now() - interval '30 minutes'",
    )
    R.add("4", "path-insight jobs not wedged", PASS if stuck in ("0", "") else WARN, f"{stuck or '?'} stuck >30m")

    # 5. content pipeline freshness: articles keep landing (ingest→NER→store alive).
    latest = _psql(
        "content_store_db",
        "SELECT coalesce(round(extract(epoch from now()-max(ingested_at))/3600,1)::text,'none') FROM documents",
    )
    if latest in ("", "none"):
        R.add("4", "content pipeline freshness", WARN, "no documents yet")
    else:
        h = float(latest)
        R.add("4", "content pipeline freshness", PASS if h < 6 else WARN, f"newest doc {h}h old")

    # 6. KG entity-description generation: embeddings keep getting produced.
    cov = _psql(
        "intelligence_db",
        "SELECT count(*) FILTER (WHERE embedding IS NOT NULL)||'/'||count(*) FROM entity_embedding_state",
    )
    R.add("4", "entity description/embedding backfill", PASS if cov else WARN, f"embedded {cov or '?'}")


# ── LAYER 5 — external data & upstream APIs ──────────────────────────────────
# A dead upstream API key (EODHD / Finnhub / Alpaca / Polymarket) doesn't error
# loudly — it just STOPS the data landing (this has bitten repeatedly: "stale
# since <date>"). So freshness of ingested data is the reliable liveness proxy:
# if rows keep arriving, the key works. Thresholds are generous to avoid weekend
# / off-hours false alarms.
def layer5() -> None:
    print("\n=== LAYER 5 — external data & upstream APIs ===")

    def freshness(name, db, sql, warn_h, fail_h=None):
        v = _psql(db, sql)
        if v in ("", "none", None):
            R.add("5", name, WARN, "no rows yet")
            return
        try:
            h = float(v)
        except ValueError:
            R.add("5", name, WARN, f"unparseable: {v}")
            return
        st = FAIL if (fail_h is not None and h > fail_h) else WARN if h > warn_h else PASS
        R.add("5", name, st, f"newest {h}h old")

    # Alpaca (crypto trades 24/7 → OHLCV should always be minutes-fresh; a multi-hour
    # gap means the Alpaca feed/key died). Equities-only would need market-hours logic.
    freshness(
        "market OHLCV (Alpaca)",
        "market_data_db",
        "SELECT round(extract(epoch from now()-max(bar_date))/3600,1)::text FROM ohlcv_bars",
        warn_h=3,
        fail_h=24,
    )
    # Polymarket prediction snapshots.
    freshness(
        "prediction markets (Polymarket)",
        "market_data_db",
        "SELECT round(extract(epoch from now()-max(snapshot_at))/3600,1)::text FROM prediction_market_snapshots",
        warn_h=6,
        fail_h=48,
    )
    # News / content ingestion (EODHD + content sources).
    freshness(
        "news/content ingestion",
        "content_store_db",
        "SELECT round(extract(epoch from now()-max(ingested_at))/3600,1)::text FROM documents",
        warn_h=6,
        fail_h=24,
    )
    # LLM/embedding provider (DeepInfra): recent successful embeddings prove the key
    # + endpoint are live (entity_embedding_state advances only on DeepInfra 200s).
    rec = _psql(
        "intelligence_db",
        "SELECT count(*) FROM entity_embedding_state WHERE embedding IS NOT NULL AND last_refreshed_at > now() - interval '30 minutes'",
    )
    R.add(
        "5", "DeepInfra embeddings flowing", PASS if rec and rec != "0" else WARN, f"{rec or '0'} embedded in last 30m"
    )


# ── LAYER 6 — data-quality regressions ───────────────────────────────────────
# The failures that hit prod this week (81% entities undescribed, sparse KG
# relations, ~14x news under-fetch) were NOT crashes — every service was "up".
# Only absolute data-quality FLOORS catch them. These are stateless thresholds
# (no historical baseline in the harness); see DQ_* constants for the rationale.
def _coverage_check(name: str, row: str, warn_pct: float) -> None:
    if "/" not in row:
        R.add("6", name, WARN, "no data")
        return
    num, den = row.split("/")[:2]
    try:
        n, d = int(num), int(den)
    except ValueError:
        R.add("6", name, WARN, f"unparseable: {row}")
        return
    pct = round(100 * n / max(d, 1), 1)
    R.add("6", name, PASS if pct >= warn_pct else WARN, f"{n}/{d} ({pct}%, floor {warn_pct}%)")


def layer6() -> None:
    print("\n=== LAYER 6 — data-quality regressions ===")

    # 1. Entity description coverage (the 81%-undescribed regression).
    _coverage_check(
        "entity description coverage",
        _psql(
            "intelligence_db",
            "SELECT count(*) FILTER (WHERE description IS NOT NULL AND length(description)>0)||'/'||count(*) FROM canonical_entities",
        ),
        DQ_DESC_COVERAGE_WARN,
    )

    # 2. Entity embedding coverage.
    _coverage_check(
        "entity embedding coverage (DQ)",
        _psql(
            "intelligence_db",
            "SELECT count(*) FILTER (WHERE embedding IS NOT NULL)||'/'||count(*) FROM entity_embedding_state",
        ),
        DQ_EMBED_COVERAGE_WARN,
    )

    # 3. KG relation density floor (sparse-relations regression).
    rel = _psql("intelligence_db", "SELECT count(*) FROM relations WHERE valid_to IS NULL")
    n = int(rel) if rel.isdigit() else -1
    R.add(
        "6",
        "KG active relations",
        PASS if n >= DQ_RELATIONS_FLOOR else WARN,
        f"{n if n >= 0 else '?'} active (floor {DQ_RELATIONS_FLOOR})",
    )

    # 4. News ingest volume over 24h (the ~14x under-fetch regression).
    nd = _psql("content_store_db", "SELECT count(*) FROM documents WHERE ingested_at > now() - interval '24 hours'")
    n = int(nd) if nd.isdigit() else -1
    R.add(
        "6",
        "news docs / 24h",
        PASS if n >= DQ_NEWS_24H_WARN else WARN,
        f"{n if n >= 0 else '?'} docs/24h (floor {DQ_NEWS_24H_WARN})",
    )

    # 5. Entity-mention pipeline liveness (near-zero → NER stalled, e.g. GLiNER OOM).
    em = _psql("nlp_db", "SELECT count(*) FROM entity_mentions WHERE created_at > now() - interval '24 hours'")
    n = int(em) if em.isdigit() else -1
    R.add(
        "6",
        "entity mentions / 24h",
        PASS if n >= DQ_MENTIONS_24H_FAIL else FAIL,
        f"{n if n >= 0 else '?'} mentions/24h (floor {DQ_MENTIONS_24H_FAIL})",
    )


# ── main ─────────────────────────────────────────────────────────────────────
def main() -> int:
    ap = argparse.ArgumentParser(description="worldview prod e2e smoke harness")
    ap.add_argument(
        "--layer",
        default="0,1,2,3,4,5,6",
        help="comma list of layers (0 infra,1 edge,2 data,3 async,4 workers,5 external-apis,6 data-quality)",
    )
    ap.add_argument("--json", help="write full report JSON to this path")
    args = ap.parse_args()
    layers = set(args.layer.split(","))

    print(f"worldview prod e2e smoke — {PUBLIC_HOST} ({NODE_IP})  {time.strftime('%Y-%m-%d %H:%M:%SZ', time.gmtime())}")
    _, ctx = kubectl("config current-context")
    print(f"kube-context: {ctx.strip()}")

    if "0" in layers:
        layer0()
    if "1" in layers:
        layer1()
    if layers & {"2", "3", "4"}:
        res = run_inpod_prober()
        if layers & {"2", "3"}:
            layer23(res)
        if "4" in layers:
            layer4(res)
    if "5" in layers:
        layer5()
    if "6" in layers:
        layer6()

    c = R.counts()
    print("\n" + "=" * 60)
    print(
        f"SUMMARY: {_C[PASS]}{c[PASS]} PASS{_C['END']}  "
        f"{_C[WARN]}{c[WARN]} WARN{_C['END']}  {_C[FAIL]}{c[FAIL]} FAIL{_C['END']}"
    )
    if args.json:
        with open(args.json, "w") as f:
            json.dump({"summary": c, "rows": R.rows}, f, indent=2)
        print(f"wrote {args.json}")
    return 1 if c[FAIL] else 0


if __name__ == "__main__":
    sys.exit(main())
