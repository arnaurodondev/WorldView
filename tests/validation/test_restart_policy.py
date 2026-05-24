"""T-G-2-01: Restart-policy + retry-worker dependency reachability test.

PLAN-0093 Wave G-2 / audit ref F-LOG-INFRA-001.

Why this test exists
--------------------
The 21:40 Docker daemon event uncovered two silent-failure classes that the
remediation plan (Sub-Plan A) addressed:

1. **Missing ``restart`` policies** on critical infra (ollama, schema-registry,
   market-data, minio).  When the host docker daemon restarted, those
   containers stayed down — silently breaking LLM calls, Avro decoding,
   quote serving, and silver-bucket reads.
2. **Missing ``depends_on`` health gates** on the three retry workers
   (path-insight, embedding-retry, unresolved-resolution).  Those workers
   booted before their backing services (postgres / valkey / ollama) were
   healthy and entered ``sys.exit(1)`` → 60-second restart loops until the
   deps came up.

This test is the SLO that the hardening from Sub-Plan A (waves A-1/A-2) stays
in place.

Relationship to ``tests/infra/test_compose_restart_policy.py``
--------------------------------------------------------------
That earlier (Sub-Plan A) test asserts the **restart-policy** half of the
contract for a subset of services (postgres/kafka/valkey/ollama/
schema-registry/market-data).  This test is a **superset**:

* Adds ``minio`` to the restart-policy critical list (the gap T-G-2-01 closed).
* Adds the three retry workers' ``depends_on`` health-gate assertions, which
  the earlier test did not cover.

Keeping both files is intentional — A-1's test is the historical anchor cited
in the Sub-Plan A wave commits, and this file is the broader G-2 SLO.  They
share the same compose-parsing helper to keep them aligned.

Skip strategy
-------------
This test is pure filesystem + YAML parsing — no DB, no Kafka, no Docker.  It
always runs.  PyYAML is already a dev dependency.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml  # type: ignore[import-untyped]  # PyYAML ships no stubs; types-PyYAML not pinned in venv

# ---------------------------------------------------------------------------
# Repo-relative path resolution.  ``tests/validation/`` lives at repo root,
# so three parents back lands us in the repo root regardless of pytest cwd.
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_COMPOSE_FILE = _REPO_ROOT / "infra" / "compose" / "docker-compose.yml"

# The SUPERSET critical list.
#
# Layer 1 — original PLAN-0093 Wave G-2 T-G-2-01 baseline:
#   postgres, kafka, valkey, ollama, schema-registry, market-data, minio (7)
#
# Layer 2 — PLAN-0093 Phase 5 QA-3 expansion (audit annex A.3, 2026-05-24):
#   The QA-3 adversarial agent found 11 long-running API / UI / ML containers
#   missing any ``restart:`` directive entirely (compose defaults to ``no``).
#   When the host docker daemon restarts those containers stay down silently,
#   producing the exact "every health probe green / nothing works" failure
#   pattern that triggered F-LOG-INFRA-001 originally.  Each entry below was
#   justified individually in annex A.3 (FastAPI ingress, ML inference, or
#   Next.js production frontend) — none are one-shot or worker containers.
#
# Adding a new long-running API/UI/ML container?  Append it here AND add
# ``restart: unless-stopped`` to its compose block.  ``always`` is rejected
# repo-wide because it overrides ``docker stop`` (breaks ``make dev-down``).
_CRITICAL_SERVICES: tuple[str, ...] = (
    # ── Layer 1 (G-2 baseline, 7 entries) ────────────────────────────────────
    "postgres",
    "kafka",
    "valkey",
    "ollama",
    "schema-registry",
    "market-data",
    "minio",
    # ── Layer 2 (QA-3 expansion, 11 entries) ─────────────────────────────────
    "alert",  # S10 alert API (port 8010) — silent alerting outage is security-relevant
    "api-gateway",  # S9 — sole platform ingress; downtime breaks frontend + backend JWKS
    "content-ingestion",  # S3 RSS/EODHD source registration API (port 8004)
    "content-store",  # S5 silver-bucket storage API (port 8005)
    "gliner-server",  # ML inference (10-min start_period); NLP halts if it dies
    "knowledge-graph",  # S7 AGE graph / RAG context API (port 8007)
    "market-ingestion",  # S2 ingestion API (port 8002)
    "nlp-pipeline",  # S6 enrichment API (port 8006)
    "portfolio",  # S1 portfolio API (port 8001)
    "rag-chat",  # S8 chat WebSocket service (port 8008)
    "worldview-web",  # Canonical Next.js 15 frontend (port 3001)
)

# The only policy we accept for critical infra.  ``always`` is rejected
# because it overrides ``docker stop`` and breaks ``make dev-down``;
# ``on-failure`` is acceptable for workers (and many use it) but not for
# long-running infra services where we want unconditional host-bounce
# recovery.
_REQUIRED_POLICY = "unless-stopped"

# Retry workers that MUST gate on the listed backing services with
# ``condition: service_healthy``.  Compose-service names match the keys in
# ``infra/compose/docker-compose.yml``.  Required-deps come from the
# Sub-Plan A wave A-1 task notes (see compose comments referencing
# F-NPL-002 / F-LOG-002).
_RETRY_WORKER_HEALTH_DEPS: dict[str, frozenset[str]] = {
    # path-insight worker (F-LOG-002).  Needs postgres + valkey + ollama
    # healthy before its first LLM/DB call to avoid sys.exit(1).
    "knowledge-graph-path-insight-worker": frozenset({"postgres", "valkey", "ollama"}),
    # embedding-retry worker (F-NPL-002).  Same set — when ollama is the
    # fallback embedding provider it must be healthy.
    "nlp-pipeline-embedding-retry-worker": frozenset({"postgres", "valkey", "ollama"}),
    # unresolved-resolution worker (F-NPL-002).  Same dep set; the worker
    # calls Ollama for LLM-based name resolution.
    "nlp-pipeline-unresolved-resolution-worker": frozenset({"postgres", "valkey", "ollama"}),
}


def _load_compose_services() -> dict[str, dict[str, Any]]:
    """Parse the canonical compose file and return its ``services`` mapping.

    Kept as a module-level helper so multiple tests reuse the same parsing
    boilerplate.  Raises an ``AssertionError`` (not a skip) if the file is
    missing — the compose file is a hard prerequisite of the whole repo.
    """
    assert _COMPOSE_FILE.exists(), f"compose file missing at {_COMPOSE_FILE}"
    raw = yaml.safe_load(_COMPOSE_FILE.read_text())
    assert isinstance(raw, dict), "compose root must be a mapping"
    services = raw.get("services")
    assert isinstance(services, dict), "compose 'services' section must be a mapping"
    return services


@pytest.mark.unit
def test_critical_services_have_restart_policy() -> None:
    """Every service in ``_CRITICAL_SERVICES`` must declare ``restart: unless-stopped``.

    Collects ALL violations before asserting so a single run surfaces every
    drift — easier than fix-one-rerun-find-another.
    """
    services = _load_compose_services()

    missing: list[str] = []
    wrong_policy: list[tuple[str, str]] = []

    for name in _CRITICAL_SERVICES:
        if name not in services:
            # Renamed/removed service is the bigger signal — the catalogue
            # itself needs updating in that case.
            missing.append(name)
            continue

        block = services[name]
        policy = block.get("restart")
        if policy != _REQUIRED_POLICY:
            wrong_policy.append((name, repr(policy)))

    errors: list[str] = []
    if missing:
        errors.append(f"unknown services in compose (catalogue needs update): {missing}")
    if wrong_policy:
        errors.append(
            "services missing 'restart: unless-stopped': "
            + ", ".join(f"{name}={policy}" for name, policy in wrong_policy)
        )

    assert not errors, "\n".join(errors)


@pytest.mark.unit
def test_retry_workers_gate_on_healthy_deps() -> None:
    """Each retry worker must list its required deps with ``condition: service_healthy``.

    Compose accepts both short-form (``depends_on: [foo, bar]``) and long-form
    (``depends_on: {foo: {condition: service_healthy}}``).  The short form
    only waits for the dep container to START (not to be healthy), which is
    exactly the failure mode F-NPL-002 / F-LOG-002 caught.  Therefore we
    require the long form AND ``service_healthy`` for every dep in the
    contract.

    Collects per-worker violations and asserts once at the end so a single
    run surfaces every drift.
    """
    services = _load_compose_services()

    errors: list[str] = []

    for worker_name, required_deps in _RETRY_WORKER_HEALTH_DEPS.items():
        if worker_name not in services:
            errors.append(f"retry worker {worker_name!r} missing from compose — catalogue needs update")
            continue

        block = services[worker_name]
        depends_on = block.get("depends_on")
        if depends_on is None:
            errors.append(f"{worker_name}: missing 'depends_on' block entirely")
            continue
        if not isinstance(depends_on, dict):
            # Short-form list — no per-dep conditions possible.  Hard fail.
            errors.append(
                f"{worker_name}: 'depends_on' is short-form (list) — "
                "must be long-form mapping with 'condition: service_healthy'"
            )
            continue

        # Long-form mapping: validate every required dep is present with the
        # right condition.
        for dep in sorted(required_deps):
            entry = depends_on.get(dep)
            if entry is None:
                errors.append(f"{worker_name}: missing required dep {dep!r}")
                continue
            if not isinstance(entry, dict):
                errors.append(f"{worker_name}: dep {dep!r} entry must be a mapping, got {entry!r}")
                continue
            condition = entry.get("condition")
            if condition != "service_healthy":
                errors.append(
                    f"{worker_name}: dep {dep!r} has condition={condition!r}; "
                    "expected 'service_healthy' to avoid sys.exit(1) restart loops"
                )

    assert not errors, "retry-worker dependency contract violations:\n" + "\n".join(f"  - {e}" for e in errors)
