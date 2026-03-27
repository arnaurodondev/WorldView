"""
Architecture test: Kafka consumer enforcement (R20).

Verifies:
1. No service code outside libs/messaging imports confluent_kafka.Consumer directly
   (all consumers must extend BaseKafkaConsumer from libs/messaging).
2. Every consumer class found in infrastructure/ extends BaseKafkaConsumer.

Rationale: BaseKafkaConsumer provides standardised idempotency, retry, DLQ, and
metrics. Direct confluent_kafka.Consumer usage bypasses all of these guarantees.
"""

from __future__ import annotations

import ast
from pathlib import Path

from tests.architecture._utils import (
    ArchViolation,
    ServiceInfo,
    assert_no_violations,
    discover_services,
    iter_py_files,
    scan_imports,
)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
LIBS_MESSAGING_DIR = REPO_ROOT / "libs" / "messaging"


def _check_no_direct_confluent_consumer(svc: ServiceInfo) -> list[ArchViolation]:
    """No service file may import confluent_kafka.Consumer directly."""
    violations: list[ArchViolation] = []
    for py_file in iter_py_files(svc.pkg_dir):
        for imp in scan_imports(py_file):
            if imp.is_type_checking:
                continue
            # Flag: from confluent_kafka import Consumer
            if imp.module == "confluent_kafka" and "Consumer" in imp.names:
                violations.append(
                    ArchViolation(
                        service=svc.name,
                        file=str(py_file.relative_to(svc.service_dir.parent.parent)),
                        line=imp.line,
                        rule="CONSUMER-001",
                        detail=(
                            f"Direct `from confluent_kafka import Consumer` in {py_file.name}. "
                            "All consumers must extend BaseKafkaConsumer from libs/messaging (R20)."
                        ),
                    )
                )
    return violations


def _find_consumer_classes(svc: ServiceInfo) -> list[tuple[Path, str, list[str]]]:
    """Find all classes named *Consumer (not *Config) in the service's infrastructure/ dir."""
    infra_dir = svc.pkg_dir / "infrastructure"
    if not infra_dir.is_dir():
        return []

    result: list[tuple[Path, str, list[str]]] = []
    for py_file in iter_py_files(infra_dir):
        try:
            source = py_file.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(source, filename=str(py_file))
        except (SyntaxError, OSError):
            continue

        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            name = node.name
            if not name.endswith("Consumer"):
                continue
            if name.endswith("Config"):
                continue
            bases: list[str] = []
            for base in node.bases:
                if isinstance(base, ast.Name):
                    bases.append(base.id)
                elif isinstance(base, ast.Attribute):
                    bases.append(base.attr)
                elif isinstance(base, ast.Subscript):
                    # Handle Generic[T] subscripts like BaseKafkaConsumer[dict]
                    if isinstance(base.value, ast.Name):
                        bases.append(base.value.id)
                    elif isinstance(base.value, ast.Attribute):
                        bases.append(base.value.attr)
            result.append((py_file, name, bases))
    return result


def _check_consumers_extend_base(svc: ServiceInfo) -> list[ArchViolation]:
    """Every *Consumer class in infrastructure/ must extend BaseKafkaConsumer."""
    violations: list[ArchViolation] = []
    for py_file, cls_name, bases in _find_consumer_classes(svc):
        if "BaseKafkaConsumer" not in bases:
            violations.append(
                ArchViolation(
                    service=svc.name,
                    file=str(py_file.relative_to(svc.service_dir.parent.parent)),
                    line=0,
                    rule="CONSUMER-002",
                    detail=(
                        f"Class `{cls_name}` in {py_file.name} does not extend `BaseKafkaConsumer` "
                        f"(bases: {bases}). All Kafka consumers must extend BaseKafkaConsumer (R20)."
                    ),
                )
            )
    return violations


class TestConsumerEnforcement:
    def test_no_direct_confluent_consumer_import_in_services(self) -> None:
        """Service code must not import confluent_kafka.Consumer directly."""
        violations: list[ArchViolation] = []
        # Check ALL services (including scaffolded) — this rule applies everywhere
        for svc in discover_services(include_scaffolded=True):
            violations.extend(_check_no_direct_confluent_consumer(svc))
        assert_no_violations(violations, rule="CONSUMER-001")

    def test_all_consumer_classes_extend_base_kafka_consumer(self) -> None:
        """Every *Consumer class in infrastructure/ must extend BaseKafkaConsumer."""
        violations: list[ArchViolation] = []
        for svc in discover_services(include_scaffolded=True):
            violations.extend(_check_consumers_extend_base(svc))
        assert_no_violations(violations, rule="CONSUMER-002")
