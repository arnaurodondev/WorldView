"""Test: critical compose services declare ``restart: unless-stopped``.

PLAN-0093 Wave A-1 T-A-1-01 / audit ref F-LOG-INFRA-001.

Background
----------
Several core containers (ollama, schema-registry, market-data) were missing a
``restart:`` directive in ``infra/compose/docker-compose.yml``.  When the host
docker daemon restarted (e.g. system reboot, ``Docker.app`` restart on macOS),
those containers stayed down while the rest of the platform came back up,
leading to silent data outages (no LLM, no Avro decoding, no quotes).

This test pins the contract: every container in ``_CRITICAL_SERVICES`` must
declare exactly ``restart: unless-stopped``.  ``always`` is explicitly NOT
allowed because it ignores ``docker stop`` and prevents the dev workflow
``make dev-down`` from cleanly halting the platform.

Adding a new critical infra container?
    Append its compose key to ``_CRITICAL_SERVICES`` below.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

# Resolve infra/compose/docker-compose.yml relative to this file so the test
# is independent of pytest's cwd (it can be invoked from the service dir, repo
# root, or via `make test`).
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_COMPOSE_FILE = _REPO_ROOT / "infra" / "compose" / "docker-compose.yml"

# The set of containers that MUST auto-recover from host restarts.  This is
# intentionally a small, curated list — the test enforces a hard floor, not a
# universal policy (some containers, e.g. one-shot ``*-init`` and ``*-migrate``
# jobs, intentionally use ``restart: "no"``).
#
# Cross-reference (PLAN-0093 Phase 5 QA-3, 2026-05-24)
# ----------------------------------------------------
# This 6-entry list is the **historical Sub-Plan A baseline anchor** cited in
# the wave A-1 commit message and intentionally frozen here.  The full
# SUPERSET (now 18 entries: this list + ``minio`` + 11 API/UI/ML containers)
# lives in ``tests/validation/test_restart_policy.py:_CRITICAL_SERVICES``.
# Both tests share ``_load_compose_services`` semantics so they stay aligned;
# any new long-running infra/API container should be added to the superset
# file, NOT here, so this file remains the immutable Sub-Plan A audit trail.
_CRITICAL_SERVICES: tuple[str, ...] = (
    # Core data infra.
    "postgres",
    "kafka",
    "valkey",
    # PLAN-0093 T-A-1-01 — the three gaps the audit identified.
    "ollama",
    "schema-registry",
    "market-data",
)

# The only policy we accept.  ``always`` is rejected because it overrides
# ``docker stop`` and breaks ``make dev-down``.  ``on-failure`` is acceptable
# for workers but not for these long-running infra services where we want
# unconditional recovery on host bounces.
_REQUIRED_POLICY = "unless-stopped"


def _load_compose_services() -> dict[str, dict]:
    """Parse docker-compose.yml and return the ``services`` mapping.

    Kept as a module-level helper so multiple tests can reuse it without
    repeating the file-existence boilerplate.
    """
    assert _COMPOSE_FILE.exists(), f"compose file missing at {_COMPOSE_FILE}"
    # ``yaml.safe_load`` returns ``Any`` per stub; the cast is implicit via the
    # explicit dict assertion below.
    raw = yaml.safe_load(_COMPOSE_FILE.read_text())
    assert isinstance(raw, dict), "compose root must be a mapping"
    services = raw.get("services")
    assert isinstance(services, dict), "compose 'services' section must be a mapping"
    return services


@pytest.mark.unit
def test_critical_services_have_restart_policy() -> None:
    """Every service in ``_CRITICAL_SERVICES`` must set ``restart: unless-stopped``.

    Fails loudly with a per-service diagnostic so it's obvious which container
    regressed.  We collect ALL violations before asserting so a single test
    run surfaces every problem instead of stopping at the first one.
    """
    services = _load_compose_services()

    missing: list[str] = []
    wrong_policy: list[tuple[str, str]] = []

    for name in _CRITICAL_SERVICES:
        if name not in services:
            # Renamed/removed service is a stronger signal than a wrong policy —
            # the test catalogue itself needs updating in that case.
            missing.append(name)
            continue

        block = services[name]
        # ``restart`` may be absent (treated as compose default == "no") or
        # explicitly set to a different policy.  Both are violations.
        policy = block.get("restart")
        if policy != _REQUIRED_POLICY:
            wrong_policy.append((name, repr(policy)))

    # Build a single rich error message — easier to read than N separate fails.
    errors: list[str] = []
    if missing:
        errors.append(f"unknown services in compose (catalogue needs update): {missing}")
    if wrong_policy:
        errors.append(
            "services missing 'restart: unless-stopped': "
            + ", ".join(f"{name}={policy}" for name, policy in wrong_policy)
        )

    assert not errors, "\n".join(errors)
