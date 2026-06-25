"""Test: dev consumer services carry stable, distinct static-membership ids.

PLAN-0113 Wave 3 T-A-3-03 (PRD-0113 FR-8/FR-11, §7 AD-2, §11 Infra Tests).

Background
----------
Wave 3 replaces the anonymous ``deploy.replicas: 2`` article fleet with two
explicit numbered services (``nlp-pipeline-article-consumer-0`` / ``-1``) so each
member can carry a distinct, restart-stable ``group.instance.id`` (Kafka KIP-345
static membership). The id is supplied via a ``*_KAFKA_*_CONSUMER_INSTANCE_ID``
``environment:`` override on top of the shared ``env_file`` (whose default is
empty). Single-replica heavy consumers also get a stable id so a container
restart skips the consumer-group rebalance.

Failure mode this guards against
--------------------------------
Two members of the same consumer group sharing one ``group.instance.id`` makes
Kafka fence one of them with ``FencedInstanceIdException`` — a silent stall where
one member never consumes. These tests pin two invariants:

  1. every ``…-consumer-N`` numbered service sets a *distinct*
     ``*_CONSUMER_INSTANCE_ID`` (the direct guard against fencing); and
  2. no static-membership consumer still uses ``deploy.replicas`` (anonymous
     replicas cannot be given distinct ids).

They assert PRESENCE of the numbered services so a regression that collapses
them back to a replicated service fails the suite.
"""

from __future__ import annotations

from pathlib import Path

import yaml  # type: ignore[import-untyped]  # PyYAML ships no stubs; types-PyYAML not pinned in venv

# Resolve infra/compose/docker-compose.yml relative to this file so the test is
# independent of pytest's cwd (repo root, service dir, or `make test`).
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_COMPOSE_FILE = _REPO_ROOT / "infra" / "compose" / "docker-compose.yml"

# The two numbered article-consumer services Wave 3 introduces (OQ-2 count = 2).
_NUMBERED_ARTICLE_SERVICES: tuple[str, ...] = (
    "nlp-pipeline-article-consumer-0",
    "nlp-pipeline-article-consumer-1",
)


def _load_compose_services() -> dict[str, dict]:
    """Parse docker-compose.yml and return the ``services`` mapping."""
    assert _COMPOSE_FILE.exists(), f"compose file missing at {_COMPOSE_FILE}"
    raw = yaml.safe_load(_COMPOSE_FILE.read_text())
    assert isinstance(raw, dict), "compose root must be a mapping"
    services = raw.get("services")
    assert isinstance(services, dict), "compose 'services' section must be a mapping"
    return services


def _environment_map(service: dict) -> dict[str, str]:
    """Return a service's ``environment:`` as a {KEY: value} mapping.

    Compose accepts ``environment`` as either a mapping or a ``KEY=value`` list;
    normalise both to a dict so callers don't branch on the YAML form.
    """
    env = service.get("environment")
    if env is None:
        return {}
    if isinstance(env, dict):
        # Values may be int/bool in YAML; coerce to str for uniform comparison.
        return {str(k): str(v) for k, v in env.items()}
    # List form: ["KEY=value", "KEY2=value2"].
    out: dict[str, str] = {}
    for item in env:
        key, _, value = str(item).partition("=")
        out[key] = value
    return out


def _instance_id_of(service: dict) -> str | None:
    """Return the single ``*_CONSUMER_INSTANCE_ID`` value set on a service, if any.

    Each consumer service sets exactly one instance-id env override (one knob per
    consumer scope), so we return the first/only match.
    """
    for key, value in _environment_map(service).items():
        if key.endswith("_CONSUMER_INSTANCE_ID"):
            return value
    return None


def test_compose_numbered_consumers_have_distinct_instance_ids() -> None:
    """Each numbered ``…-consumer-N`` service sets a unique ``*_INSTANCE_ID``.

    Two members of one consumer group sharing an id triggers Kafka's
    ``FencedInstanceIdException``; this is the direct guard (T-A-3-03, §9).
    """
    services = _load_compose_services()

    # Both numbered article services must exist (PRESENCE — not just absence of
    # a parse error). A regression that re-collapses them to one replicated
    # service fails here.
    for name in _NUMBERED_ARTICLE_SERVICES:
        assert name in services, f"expected numbered consumer service '{name}' in compose"

    # Each numbered article service must declare a non-empty instance id.
    article_ids: list[str] = []
    for name in _NUMBERED_ARTICLE_SERVICES:
        instance_id = _instance_id_of(services[name])
        assert instance_id, f"'{name}' must set a non-empty *_CONSUMER_INSTANCE_ID env override"
        article_ids.append(instance_id)

    # The numbered fleet's ids must be pairwise distinct (the fencing guard).
    assert len(set(article_ids)) == len(
        article_ids
    ), f"numbered article-consumer instance ids must be distinct, got {article_ids}"

    # Belt-and-braces: every instance id set anywhere in the compose file must be
    # globally unique, so no two consumer services can ever fence each other.
    all_ids = [
        instance_id
        for svc in services.values()
        if isinstance(svc, dict) and (instance_id := _instance_id_of(svc)) is not None
    ]
    duplicates = {i for i in all_ids if all_ids.count(i) > 1}
    assert not duplicates, f"duplicate *_CONSUMER_INSTANCE_ID values across compose: {sorted(duplicates)}"


def test_compose_no_replicas_on_static_consumers() -> None:
    """No service that carries a static-membership id uses ``deploy.replicas``.

    Anonymous replicas share one rendered config and cannot each carry a distinct
    ``group.instance.id``, so a static-membership consumer must be modelled as
    numbered services instead (AD-2). This also confirms the article fleet's old
    ``deploy.replicas: 2`` block is gone.
    """
    services = _load_compose_services()

    # The numbered article services specifically must not use deploy.replicas.
    for name in _NUMBERED_ARTICLE_SERVICES:
        deploy = services[name].get("deploy") or {}
        assert "replicas" not in deploy, f"'{name}' must not use deploy.replicas (use numbered services)"

    # Generalised: any service that sets a static-membership instance id must not
    # also request replicas (the two are mutually exclusive — replicas would
    # share the id and fence each other).
    for name, svc in services.items():
        if not isinstance(svc, dict):
            continue
        if _instance_id_of(svc) is None:
            continue
        deploy = svc.get("deploy") or {}
        assert "replicas" not in deploy, f"'{name}' sets a static-membership instance id but also uses deploy.replicas"
