"""
Architecture test: application/ports/ directory enforcement.

Every fully mature service (domain + application + ports) must have:
  - an application/ports/ directory
  - at least one non-init Python file defining port ABCs

Services that have application/ but no ports/ yet are flagged as violations
so that they appear in the report and can be tracked toward compliance.
"""

from __future__ import annotations

import ast
from pathlib import Path

from tests.architecture._utils import (
    ArchViolation,
    ServiceInfo,
    assert_no_violations,
    discover_mature_services,
)


def _has_abc_class(py_file: Path) -> bool:
    """Return True if the file defines at least one class with ABC or Protocol in bases."""
    try:
        source = py_file.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(source, filename=str(py_file))
    except (SyntaxError, OSError):
        return False

    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        for base in node.bases:
            base_name = ""
            if isinstance(base, ast.Name):
                base_name = base.id
            elif isinstance(base, ast.Attribute):
                base_name = base.attr
            if base_name in {"ABC", "Protocol"}:
                return True
    return False


def _check_ports_structure(svc: ServiceInfo) -> list[ArchViolation]:
    violations: list[ArchViolation] = []
    app_dir = svc.pkg_dir / "application"

    if not app_dir.is_dir():
        return violations  # no application layer — not relevant

    ports_dir = app_dir / "ports"
    if not ports_dir.is_dir():
        violations.append(
            ArchViolation(
                service=svc.name,
                file=str((app_dir / "ports").relative_to(svc.service_dir.parent.parent)),
                line=0,
                rule="PORTS-001",
                detail=(
                    f"Service {svc.name!r} has application/ but no application/ports/. "
                    "Every service must define port ABCs in application/ports/ (STANDARDS.md §1)."
                ),
            )
        )
        return violations

    # ports/ exists — verify it has at least one non-init file
    port_files = [f for f in ports_dir.iterdir() if f.suffix == ".py" and f.name != "__init__.py"]
    if not port_files:
        violations.append(
            ArchViolation(
                service=svc.name,
                file=str(ports_dir.relative_to(svc.service_dir.parent.parent)),
                line=0,
                rule="PORTS-002",
                detail=(
                    f"Service {svc.name!r}: application/ports/ exists but has no port definition files. "
                    "Add at least one file with ABC/Protocol definitions."
                ),
            )
        )
    return violations


def _check_ports_have_abcs(svc: ServiceInfo) -> list[ArchViolation]:
    """For each service with ports/, verify at least one ABC/Protocol class exists."""
    violations: list[ArchViolation] = []
    ports_dir = svc.pkg_dir / "application" / "ports"
    if not ports_dir.is_dir():
        return violations

    port_files = [f for f in ports_dir.iterdir() if f.suffix == ".py" and f.name != "__init__.py"]
    has_abc = any(_has_abc_class(f) for f in port_files)

    if port_files and not has_abc:
        violations.append(
            ArchViolation(
                service=svc.name,
                file=str(ports_dir.relative_to(svc.service_dir.parent.parent)),
                line=0,
                rule="PORTS-003",
                detail=(
                    f"Service {svc.name!r}: application/ports/ has files but none define an ABC or Protocol class. "
                    "Port files must declare abstract interfaces."
                ),
            )
        )
    return violations


class TestPortsEnforcement:
    def test_every_mature_service_with_application_has_ports_directory(self) -> None:
        """Every mature service with application/ must also have application/ports/."""
        violations: list[ArchViolation] = []
        for svc in discover_mature_services():
            violations.extend(_check_ports_structure(svc))
        assert_no_violations(violations, rule="PORTS")

    def test_all_ports_directories_have_abc_definitions(self) -> None:
        """Every application/ports/ directory must contain at least one ABC/Protocol."""
        violations: list[ArchViolation] = []
        for svc in discover_mature_services():
            violations.extend(_check_ports_have_abcs(svc))
        assert_no_violations(violations, rule="PORTS-ABC")
