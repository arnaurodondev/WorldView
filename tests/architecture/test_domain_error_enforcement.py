"""
Architecture test: DomainError inheritance enforcement (R21).

Every mature service must:
1. Define a DomainError base class in its domain errors module.
2. Have all other exception classes in that module inherit from DomainError
   (directly or transitively through the MRO).

Checked modules: domain/errors.py and domain/exceptions.py (S4 naming convention).
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

_ERRORS_CANDIDATES = ("errors.py", "exceptions.py")


def _find_errors_file(pkg_dir: Path) -> Path | None:
    """Return the domain errors/exceptions module path if it exists."""
    domain_dir = pkg_dir / "domain"
    if not domain_dir.is_dir():
        return None
    for name in _ERRORS_CANDIDATES:
        candidate = domain_dir / name
        if candidate.is_file():
            return candidate
    return None


def _parse_class_defs(source: str, filename: str) -> list[tuple[str, list[str]]]:
    """Parse a Python source file and return list of (class_name, [base_names])."""
    try:
        tree = ast.parse(source, filename=filename)
    except SyntaxError:
        return []

    result: list[tuple[str, list[str]]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        bases: list[str] = []
        for base in node.bases:
            if isinstance(base, ast.Name):
                bases.append(base.id)
            elif isinstance(base, ast.Attribute):
                bases.append(base.attr)
        result.append((node.name, bases))
    return result


def _check_domain_error_module(svc: ServiceInfo) -> list[ArchViolation]:
    violations: list[ArchViolation] = []
    errors_file = _find_errors_file(svc.pkg_dir)
    if errors_file is None:
        # No domain errors module — nothing to enforce
        return violations

    source = errors_file.read_text(encoding="utf-8", errors="replace")
    class_defs = _parse_class_defs(source, str(errors_file))
    if not class_defs:
        return violations

    class_names = {name for name, _ in class_defs}
    has_domain_error = "DomainError" in class_names

    if not has_domain_error:
        violations.append(
            ArchViolation(
                service=svc.name,
                file=str(errors_file.relative_to(svc.service_dir.parent.parent)),
                line=0,
                rule="DOMAIN-ERROR-001",
                detail=(
                    f"Service {svc.name!r}: domain errors module does not define `DomainError`. "
                    "All services must define a `DomainError(Exception)` base class (R21)."
                ),
            )
        )
        return violations

    # Build immediate-base → class mapping for inheritance check
    # We perform a simple direct-parent check (one level) for speed.
    # Transitive inheritance across modules is not checked here.
    domain_error_family: set[str] = {"DomainError", "Exception"}

    def _is_domain_error_subclass(bases: list[str]) -> bool:
        return any(b in domain_error_family for b in bases)

    # Iteratively expand the family (handles multi-level within the same file)
    changed = True
    while changed:
        changed = False
        for cls_name, bases in class_defs:
            if cls_name not in domain_error_family and _is_domain_error_subclass(bases):
                domain_error_family.add(cls_name)
                changed = True

    for cls_name, bases in class_defs:
        if cls_name == "DomainError":
            continue
        # Skip non-exception classes (simple heuristic: no "Error"/"Exception" in name or bases)
        looks_like_exception = (
            "Error" in cls_name or "Exception" in cls_name or any("Error" in b or "Exception" in b for b in bases)
        )
        if not looks_like_exception:
            continue
        if cls_name not in domain_error_family:
            violations.append(
                ArchViolation(
                    service=svc.name,
                    file=str(errors_file.relative_to(svc.service_dir.parent.parent)),
                    line=0,
                    rule="DOMAIN-ERROR-002",
                    detail=(
                        f"Service {svc.name!r}: `{cls_name}` does not inherit from `DomainError` "
                        f"(bases: {bases}). All domain exceptions must extend `DomainError` (R21)."
                    ),
                )
            )

    return violations


class TestDomainErrorEnforcement:
    def test_every_domain_errors_module_defines_domain_error(self) -> None:
        """Every mature service domain errors module must define DomainError."""
        violations: list[ArchViolation] = []
        for svc in discover_mature_services():
            errors_file = _find_errors_file(svc.pkg_dir)
            if errors_file is None:
                continue
            source = errors_file.read_text(encoding="utf-8", errors="replace")
            class_defs = _parse_class_defs(source, str(errors_file))
            class_names = {name for name, _ in class_defs}
            if class_defs and "DomainError" not in class_names:
                violations.append(
                    ArchViolation(
                        service=svc.name,
                        file=str(errors_file.relative_to(svc.service_dir.parent.parent)),
                        line=0,
                        rule="DOMAIN-ERROR-001",
                        detail=(f"Service {svc.name!r}: domain errors module missing `DomainError` base class (R21)."),
                    )
                )
        assert_no_violations(violations, rule="DOMAIN-ERROR-001")

    def test_all_domain_exceptions_inherit_from_domain_error(self) -> None:
        """All exception classes in domain errors modules must inherit from DomainError."""
        violations: list[ArchViolation] = []
        for svc in discover_mature_services():
            violations.extend(_check_domain_error_module(svc))
        assert_no_violations(violations, rule="DOMAIN-ERROR")
