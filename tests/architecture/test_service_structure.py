"""
Architecture test: canonical service directory structure.

Verifies that every FastAPI service follows the hexagonal layout defined in
docs/STANDARDS.md §1. Scaffolded services are checked for the subset of rules
that apply to stubs.

These tests are intentionally lightweight (filesystem checks only) and must
complete in seconds.
"""

from __future__ import annotations

from tests.architecture._utils import (
    ArchViolation,
    ServiceInfo,
    assert_no_violations,
    discover_mature_services,
    discover_services,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _check_path(svc: ServiceInfo, path: str, rule: str, description: str) -> ArchViolation | None:
    full_path = svc.service_dir / path
    if not full_path.exists():
        return ArchViolation(
            service=svc.name,
            file=str(full_path.relative_to(svc.service_dir.parent.parent)),
            line=0,
            rule=rule,
            detail=f"Missing required path: {path} — {description}",
        )
    return None


# ---------------------------------------------------------------------------
# Entry file checks (all services)
# ---------------------------------------------------------------------------


class TestEntryFiles:
    def test_init_exists(self) -> None:
        """Every service package must have __init__.py."""
        violations = []
        for svc in discover_services():
            v = _check_path(
                svc,
                f"src/{svc.pkg_name}/__init__.py",
                "STR-001",
                "Package __init__.py is required",
            )
            if v:
                violations.append(v)
        assert_no_violations(violations, rule="STR-001")

    def test_app_py_exists(self) -> None:
        """Every service must have app.py (FastAPI factory + lifespan)."""
        violations = []
        for svc in discover_services():
            v = _check_path(
                svc,
                f"src/{svc.pkg_name}/app.py",
                "STR-002",
                "app.py with FastAPI factory is required",
            )
            if v:
                violations.append(v)
        assert_no_violations(violations, rule="STR-002")

    def test_config_py_exists(self) -> None:
        """Every service must have config.py (Settings class)."""
        violations = []
        for svc in discover_services():
            v = _check_path(
                svc,
                f"src/{svc.pkg_name}/config.py",
                "STR-003",
                "config.py with Settings class is required",
            )
            if v:
                violations.append(v)
        assert_no_violations(violations, rule="STR-003")


# ---------------------------------------------------------------------------
# Layer folder checks (mature services only)
# ---------------------------------------------------------------------------


class TestLayerFolders:
    def test_domain_layer_exists(self) -> None:
        violations = []
        for svc in discover_mature_services():
            v = _check_path(
                svc,
                f"src/{svc.pkg_name}/domain",
                "STR-004",
                "domain/ layer is required in non-scaffolded services",
            )
            if v:
                violations.append(v)
        assert_no_violations(violations, rule="STR-004")

    def test_application_layer_exists(self) -> None:
        violations = []
        for svc in discover_mature_services():
            v = _check_path(
                svc,
                f"src/{svc.pkg_name}/application",
                "STR-005",
                "application/ layer is required in non-scaffolded services",
            )
            if v:
                violations.append(v)
        assert_no_violations(violations, rule="STR-005")

    def test_api_layer_exists(self) -> None:
        violations = []
        for svc in discover_mature_services():
            v = _check_path(
                svc,
                f"src/{svc.pkg_name}/api",
                "STR-006",
                "api/ layer is required in non-scaffolded services",
            )
            if v:
                violations.append(v)
        assert_no_violations(violations, rule="STR-006")

    def test_infrastructure_layer_exists(self) -> None:
        violations = []
        for svc in discover_mature_services():
            v = _check_path(
                svc,
                f"src/{svc.pkg_name}/infrastructure",
                "STR-007",
                "infrastructure/ layer is required in non-scaffolded services",
            )
            if v:
                violations.append(v)
        assert_no_violations(violations, rule="STR-007")


# ---------------------------------------------------------------------------
# Messaging schemas (mature Kafka-enabled services)
# ---------------------------------------------------------------------------


def _is_kafka_enabled(svc: ServiceInfo) -> bool:
    """Heuristic: service has infrastructure/messaging or messaging directory."""
    return (svc.pkg_dir / "infrastructure" / "messaging").is_dir() or (svc.pkg_dir / "messaging").is_dir()


class TestMessagingSchemas:
    def test_messaging_schemas_folder_exists(self) -> None:
        """Kafka-enabled services must have an Avro schemas directory."""
        violations = []
        for svc in discover_mature_services():
            if not _is_kafka_enabled(svc):
                continue
            # Accept schemas at infrastructure/messaging/schemas/ OR messaging/schemas/
            # (portfolio uses the legacy messaging/ location — tracked by STR-008 exception)
            infra_schemas = svc.pkg_dir / "infrastructure" / "messaging" / "schemas"
            legacy_schemas = svc.pkg_dir / "messaging" / "schemas"
            if not (infra_schemas.is_dir() or legacy_schemas.is_dir()):
                violations.append(
                    ArchViolation(
                        service=svc.name,
                        file=f"services/{svc.name}/src/{svc.pkg_name}/infrastructure/messaging/schemas",
                        line=0,
                        rule="STR-008",
                        detail="Missing Avro schemas directory for Kafka-enabled service",
                    )
                )
        assert_no_violations(violations, rule="STR-008")


# ---------------------------------------------------------------------------
# Test directory structure
# ---------------------------------------------------------------------------


class TestTestDirectories:
    def test_unit_test_dir_exists(self) -> None:
        violations = []
        for svc in discover_services():
            v = _check_path(svc, "tests/unit", "STR-009", "tests/unit/ directory is required")
            if v:
                violations.append(v)
        assert_no_violations(violations, rule="STR-009")

    def test_integration_test_dir_exists(self) -> None:
        violations = []
        for svc in discover_services():
            v = _check_path(svc, "tests/integration", "STR-010", "tests/integration/ directory is required")
            if v:
                violations.append(v)
        assert_no_violations(violations, rule="STR-010")

    def test_contract_test_dir_exists(self) -> None:
        violations = []
        for svc in discover_services():
            v = _check_path(svc, "tests/contract", "STR-011", "tests/contract/ directory is required")
            if v:
                violations.append(v)
        assert_no_violations(violations, rule="STR-011")


# ---------------------------------------------------------------------------
# Alembic
# ---------------------------------------------------------------------------


class TestAlembicStructure:
    def test_alembic_versions_dir_exists(self) -> None:
        """Services with alembic.ini must have alembic/versions/."""
        violations = []
        for svc in discover_services():
            if not (svc.service_dir / "alembic.ini").exists():
                continue
            v = _check_path(svc, "alembic/versions", "STR-012", "alembic/versions/ required for DB-owning services")
            if v:
                violations.append(v)
        assert_no_violations(violations, rule="STR-012")
