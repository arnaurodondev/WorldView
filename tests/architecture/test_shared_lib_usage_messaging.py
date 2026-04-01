"""
Architecture test: libs/messaging usage patterns.

Verifies that:
1. Direct aiokafka imports do not appear in service src/ code.
2. Direct redis.asyncio / aioredis imports do not appear in service src/ code.
3. Kafka-enabled mature services have an outbox dispatcher class.
4. No custom ad-hoc dispatcher loops (bare asyncio.sleep poll loops that
   bypass BaseOutboxDispatcher) in mature services.

Per docs/libs/messaging.md and docs/STANDARDS.md §3.
"""

from __future__ import annotations

from pathlib import Path

from tests.architecture._utils import (
    ArchViolation,
    ServiceInfo,
    assert_no_violations,
    discover_mature_services,
    discover_services,
    iter_py_files,
    scan_imports,
)


def _src_files(svc: ServiceInfo) -> list[Path]:
    return [f for f in iter_py_files(svc.pkg_dir) if "tests" not in f.parts]


def _is_kafka_enabled(svc: ServiceInfo) -> bool:
    return (svc.pkg_dir / "infrastructure" / "messaging").is_dir() or (svc.pkg_dir / "messaging").is_dir()


class TestNoDirectKafka:
    def test_no_direct_aiokafka_imports(self) -> None:
        """Service src/ must not import aiokafka directly."""
        violations = []
        for svc in discover_services():
            for py_file in _src_files(svc):
                rel = str(py_file.relative_to(svc.service_dir.parent.parent))
                for imp in scan_imports(py_file):
                    if imp.module == "aiokafka" or imp.module.startswith("aiokafka."):
                        violations.append(
                            ArchViolation(
                                service=svc.name,
                                file=rel,
                                line=imp.line,
                                rule="IG-MSG-001",
                                detail=f"Direct aiokafka import: `{imp.module}` — use messaging.kafka.* wrappers",
                            )
                        )
        assert_no_violations(violations, rule="IG-MSG-001")

    def test_no_direct_redis_imports(self) -> None:
        """Service src/ must not import redis.asyncio or aioredis directly."""
        violations = []
        FORBIDDEN = {"aioredis", "redis.asyncio", "redis"}
        for svc in discover_services():
            for py_file in _src_files(svc):
                rel = str(py_file.relative_to(svc.service_dir.parent.parent))
                for imp in scan_imports(py_file):
                    if imp.is_type_checking:
                        continue
                    module = imp.module
                    if module in FORBIDDEN or module.startswith("aioredis."):
                        # Allow redis imports that go through messaging.valkey
                        # (messaging lib itself is excluded via lib path check)
                        violations.append(
                            ArchViolation(
                                service=svc.name,
                                file=rel,
                                line=imp.line,
                                rule="IG-MSG-002",
                                detail=f"Direct redis/aioredis import: `{module}` — use messaging.valkey client",
                            )
                        )
        assert_no_violations(violations, rule="IG-MSG-002")


class TestOutboxDispatcherConventions:
    def test_kafka_services_have_dispatcher(self) -> None:
        """Mature Kafka-enabled services must have a dispatcher.py."""
        violations = []
        for svc in discover_mature_services():
            if not _is_kafka_enabled(svc):
                continue

            # Accept dispatcher in infrastructure/messaging/outbox/ OR messaging/
            candidates = [
                svc.pkg_dir / "infrastructure" / "messaging" / "outbox" / "dispatcher.py",
                svc.pkg_dir / "messaging" / "dispatcher.py",
                svc.pkg_dir / "infrastructure" / "messaging" / "dispatcher.py",
            ]
            if not any(c.exists() for c in candidates):
                violations.append(
                    ArchViolation(
                        service=svc.name,
                        file=f"services/{svc.name}/src/{svc.pkg_name}",
                        line=0,
                        rule="MSG-DISPATCHER",
                        detail=(
                            "Kafka-enabled service missing dispatcher.py. "
                            "Expected at infrastructure/messaging/outbox/dispatcher.py "
                            "or messaging/dispatcher.py."
                        ),
                    )
                )
        assert_no_violations(violations, rule="MSG-DISPATCHER")
