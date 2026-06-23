"""Architecture/regression test: all *-migrate compose services declare
restart: on-failure:5 so a stale sidecar after image rebuild auto-recovers
(F-INFRA-008/009 root cause; BP-591)."""

from pathlib import Path

import yaml

COMPOSE_PATH = Path(__file__).parent.parent.parent / "infra/compose/docker-compose.yml"


def test_all_migrate_services_have_restart_policy() -> None:
    compose = yaml.safe_load(COMPOSE_PATH.read_text())
    services = compose.get("services", {})
    migrate_services = [name for name in services if name.endswith("-migrate")]
    assert len(migrate_services) >= 5, f"Expected at least 5 migrate services, found {len(migrate_services)}"
    for name in migrate_services:
        policy = services[name].get("restart")
        assert policy == "on-failure:5", (
            f"Service {name}: expected restart='on-failure:5', got {policy!r}. " f"See BP-591 / iter-13 follow-up."
        )
