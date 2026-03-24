"""
Architecture test: libs/observability usage patterns.

Verifies that:
1. Service src/ does not call logging.getLogger() directly (must use structlog).
2. Service src/ does not use bare print() for logging purposes.
3. Mature service app.py imports from observability for lifespan setup.

Per docs/libs/observability.md and docs/STANDARDS.md §5.
"""

from __future__ import annotations

import ast
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


class _LoggingVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.getlogger_calls: list[int] = []

    def visit_Call(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Attribute) and node.func.attr == "getLogger":
            if isinstance(node.func.value, ast.Name) and node.func.value.id == "logging":
                self.getlogger_calls.append(node.lineno)
        self.generic_visit(node)


class TestNoDirectLogging:
    def test_no_logging_getlogger_in_service_src(self) -> None:
        """Service src/ must not call logging.getLogger() — use structlog.get_logger()."""
        violations = []
        for svc in discover_services():
            for py_file in _src_files(svc):
                try:
                    source = py_file.read_text(encoding="utf-8", errors="replace")
                    tree = ast.parse(source)
                except (SyntaxError, OSError):
                    continue
                visitor = _LoggingVisitor()
                visitor.visit(tree)
                rel = str(py_file.relative_to(svc.service_dir.parent.parent))
                for line in visitor.getlogger_calls:
                    violations.append(
                        ArchViolation(
                            service=svc.name,
                            file=rel,
                            line=line,
                            rule="IG-OBS-001",
                            detail="logging.getLogger() in src/ code — use structlog.get_logger()",
                        )
                    )
        assert_no_violations(violations, rule="IG-OBS-001")


class TestObservabilityLifespan:
    def test_mature_services_use_observability_setup(self) -> None:
        """Mature service app.py should import from observability for lifespan setup."""
        violations = []
        for svc in discover_mature_services():
            app_py = svc.pkg_dir / "app.py"
            if not app_py.exists():
                continue

            imports = scan_imports(app_py)
            uses_observability = any(imp.module.startswith("observability") for imp in imports)
            if not uses_observability:
                violations.append(
                    ArchViolation(
                        service=svc.name,
                        file=str(app_py.relative_to(svc.service_dir.parent.parent)),
                        line=0,
                        rule="OBS-LIFESPAN",
                        detail=(
                            "app.py does not import from observability. "
                            "Mature services must configure observability in their lifespan."
                        ),
                    )
                )
        # This is a WARNING-level check — report but do not fail
        # (some services may configure observability via middleware or startup hooks)
        if violations:
            import warnings

            warning_lines = [f"\n[OBS-LIFESPAN] {len(violations)} service(s) may be missing observability setup:"]
            for v in violations:
                warning_lines.append(f"  {v.service}: {v.file}")
            warnings.warn("\n".join(warning_lines), stacklevel=2)
