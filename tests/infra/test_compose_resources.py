"""Test: ML containers are CPU-capped and the event backbone is reserved.

PLAN-0113 Wave 1 T-A-1-03 (PRD-0113 FR-10, §11 Integration/Infra Tests).

Background
----------
On a single dev host the heavy ML inference containers (``gliner-server`` NER
and ``ollama`` LLM/embeddings) could pin every CPU core and starve the event
backbone (``kafka``) and primary datastore (``postgres``), causing Kafka
heartbeat/election storms and DB stalls.  Wave 1 adds:

  - ``deploy.resources.limits`` (CPU + memory) to gliner-server and ollama —
    a hard CAP so inference cannot consume the whole host;
  - ``deploy.resources.reservations`` (CPU + memory) to kafka and postgres —
    a GUARANTEE of baseline capacity.

These tests pin that contract.  They assert PRESENCE (not just absence of a
parse error) so removing a resource block fails the suite, and they assert the
``reservation <= limit`` invariant for any service that declares both.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml  # type: ignore[import-untyped]  # PyYAML ships no stubs; types-PyYAML not pinned in venv

# Resolve infra/compose/docker-compose.yml relative to this file so the test is
# independent of pytest's cwd (repo root, service dir, or `make test`).
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_COMPOSE_FILE = _REPO_ROOT / "infra" / "compose" / "docker-compose.yml"

# Services that must declare a deploy.resources block this wave.
#   - capped (limits): the ML inference containers.
#   - reserved (reservations): the event backbone + datastore.
_CAPPED_SERVICES: tuple[str, ...] = ("gliner-server", "ollama")
_RESERVED_SERVICES: tuple[str, ...] = ("kafka", "postgres")
_ALL_RESOURCE_SERVICES: tuple[str, ...] = _CAPPED_SERVICES + _RESERVED_SERVICES


def _load_compose_services() -> dict[str, dict]:
    """Parse docker-compose.yml and return the ``services`` mapping."""
    assert _COMPOSE_FILE.exists(), f"compose file missing at {_COMPOSE_FILE}"
    raw = yaml.safe_load(_COMPOSE_FILE.read_text())
    assert isinstance(raw, dict), "compose root must be a mapping"
    services = raw.get("services")
    assert isinstance(services, dict), "compose 'services' section must be a mapping"
    return services


def _cpus_to_float(value: object) -> float:
    """Coerce a compose CPU value (string like ``"2.0"`` or number) to float."""
    return float(value)  # type: ignore[arg-type]


def _mem_to_bytes(value: object) -> int:
    """Coerce a compose memory string (e.g. ``512M``, ``6G``, ``1024``) to bytes.

    Compose accepts an integer (bytes) or a string with a unit suffix
    (b, k, m, g — case-insensitive).  This mirrors that subset.
    """
    if isinstance(value, int):
        return value
    text = str(value).strip()
    units = {"b": 1, "k": 1024, "m": 1024**2, "g": 1024**3}
    suffix = text[-1].lower()
    if suffix in units:
        return int(float(text[:-1]) * units[suffix])
    # No suffix → bytes.
    return int(float(text))


@pytest.mark.unit
def test_compose_resources_present() -> None:
    """gliner-server/ollama have limits; kafka/postgres have reservations.

    Collects every violation before asserting so one run surfaces all gaps.
    """
    services = _load_compose_services()

    errors: list[str] = []

    for name in _ALL_RESOURCE_SERVICES:
        if name not in services:
            errors.append(f"service '{name}' missing from compose (catalogue needs update)")
            continue
        resources = services[name].get("deploy", {}).get("resources")
        if not isinstance(resources, dict):
            errors.append(f"service '{name}' missing deploy.resources block")
            continue

        # Capped ML containers MUST have limits with both cpus and memory.
        if name in _CAPPED_SERVICES:
            limits = resources.get("limits")
            if not isinstance(limits, dict):
                errors.append(f"capped service '{name}' missing deploy.resources.limits")
            else:
                if "cpus" not in limits:
                    errors.append(f"capped service '{name}' limits missing cpus")
                if "memory" not in limits:
                    errors.append(f"capped service '{name}' limits missing memory")

        # Reserved backbone/datastore MUST have reservations with both.
        if name in _RESERVED_SERVICES:
            reservations = resources.get("reservations")
            if not isinstance(reservations, dict):
                errors.append(f"reserved service '{name}' missing deploy.resources.reservations")
            else:
                if "cpus" not in reservations:
                    errors.append(f"reserved service '{name}' reservations missing cpus")
                if "memory" not in reservations:
                    errors.append(f"reserved service '{name}' reservations missing memory")

    assert not errors, "\n".join(errors)


@pytest.mark.unit
def test_compose_reservations_le_limits() -> None:
    """For any service declaring BOTH, reservation must be <= limit.

    A reservation greater than its limit is a misconfiguration the scheduler
    cannot satisfy.  We check every resource service even if it currently only
    declares one side (those are simply skipped).
    """
    services = _load_compose_services()

    errors: list[str] = []

    for name in _ALL_RESOURCE_SERVICES:
        resources = services.get(name, {}).get("deploy", {}).get("resources")
        if not isinstance(resources, dict):
            continue
        limits = resources.get("limits")
        reservations = resources.get("reservations")
        if not (isinstance(limits, dict) and isinstance(reservations, dict)):
            continue

        if "cpus" in limits and "cpus" in reservations:
            if _cpus_to_float(reservations["cpus"]) > _cpus_to_float(limits["cpus"]):
                errors.append(f"service '{name}': cpu reservation > limit")
        if "memory" in limits and "memory" in reservations:
            if _mem_to_bytes(reservations["memory"]) > _mem_to_bytes(limits["memory"]):
                errors.append(f"service '{name}': memory reservation > limit")

    assert not errors, "\n".join(errors)
