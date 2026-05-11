"""
Architecture test: layer boundary enforcement.

Verifies that the hexagonal layer dependency rules from docs/STANDARDS.md §1.2
are respected across all mature services:

  domain ← application ← api
  domain ← application ← infrastructure

Specifically:
  - domain must NOT import from application, api, or infrastructure
  - application must NOT import from api or infrastructure (uses interfaces only)
  - api must NOT have MODULE-LEVEL imports from infrastructure (D-1 / IG-LAYER-002)
    (function-body lazy imports are acceptable as an established DI pattern)

Only mature (non-scaffolded) services are checked.
"""

from __future__ import annotations

import ast

from tests.architecture._utils import (
    ArchViolation,
    ServiceInfo,
    assert_no_violations,
    discover_mature_services,
    discover_services,
    iter_py_files,
    layer_of,
    scan_imports,
)

# ---------------------------------------------------------------------------
# Layer import rules
# ---------------------------------------------------------------------------

# Maps layer → set of layers it must NOT import from
FORBIDDEN_LAYER_IMPORTS: dict[str, set[str]] = {
    "domain": {"application", "api", "infrastructure"},
    "application": {"api", "infrastructure"},
    "api": set(),  # api may import infrastructure for DI — checked separately
}


def _check_layer_boundaries(svc: ServiceInfo) -> list[ArchViolation]:
    violations: list[ArchViolation] = []
    pkg_dir = svc.pkg_dir

    for py_file in iter_py_files(pkg_dir):
        src_layer = layer_of(py_file, pkg_dir)
        if src_layer not in FORBIDDEN_LAYER_IMPORTS:
            continue

        forbidden_targets = FORBIDDEN_LAYER_IMPORTS[src_layer]
        if not forbidden_targets:
            continue

        for imp in scan_imports(py_file):
            # Skip TYPE_CHECKING-only imports — annotation-only, no runtime dep
            if imp.is_type_checking:
                continue

            # Only flag imports from the same package
            pkg_prefix = svc.pkg_name + "."
            module = imp.module
            if not module.startswith(pkg_prefix):
                continue

            # Determine target layer from the import path
            # e.g. portfolio.infrastructure.db → infrastructure
            rest = module[len(pkg_prefix) :]
            target_layer = rest.split(".")[0] if rest else ""

            if target_layer in forbidden_targets:
                violations.append(
                    ArchViolation(
                        service=svc.name,
                        file=str(py_file.relative_to(svc.service_dir.parent.parent)),
                        line=imp.line,
                        rule="LAYER-BOUNDARY",
                        detail=(
                            f"{src_layer}/ imports from {target_layer}/ "
                            f"(`{imp.module}`). "
                            f"{src_layer.capitalize()} layer must not depend on {target_layer}."
                        ),
                    )
                )

    return violations


class TestLayerBoundaries:
    def test_domain_does_not_import_outward_layers(self) -> None:
        """Domain layer must not import application, api, or infrastructure."""
        violations = []
        for svc in discover_mature_services():
            violations.extend(_check_layer_boundaries(svc))
        assert_no_violations(violations, rule="LAYER-BOUNDARY")

    def test_application_does_not_import_api_or_infrastructure(self) -> None:
        """Application layer must not import api or infrastructure directly."""
        violations = []
        for svc in discover_mature_services():
            pkg_dir = svc.pkg_dir
            pkg_prefix = svc.pkg_name + "."

            for py_file in iter_py_files(pkg_dir):
                src_layer = layer_of(py_file, pkg_dir)
                if src_layer != "application":
                    continue

                for imp in scan_imports(py_file):
                    if imp.is_type_checking:
                        continue
                    module = imp.module
                    if not module.startswith(pkg_prefix):
                        continue
                    rest = module[len(pkg_prefix) :]
                    target_layer = rest.split(".")[0] if rest else ""
                    if target_layer in {"api", "infrastructure"}:
                        violations.append(
                            ArchViolation(
                                service=svc.name,
                                file=str(py_file.relative_to(svc.service_dir.parent.parent)),
                                line=imp.line,
                                rule="LAYER-APP-ISOLATION",
                                detail=(
                                    f"application/ imports from {target_layer}/ "
                                    f"(`{module}`). "
                                    "Application must only depend on domain and use port interfaces."
                                ),
                            )
                        )

        assert_no_violations(violations, rule="LAYER-APP-ISOLATION")

    def test_api_no_module_level_infrastructure_imports(self) -> None:
        """API layer files must not have module-level (top-level) imports from
        infrastructure/.  Lazy imports inside function bodies are allowed because
        they follow the established DI pattern (portfolio reference implementation)
        and don't load infrastructure at module-import time.

        Violation pattern (D-1 / IG-LAYER-002):
            # BAD — top of file
            from portfolio.infrastructure.db.repositories.foo import FooRepo
            ...
            def get_foo(session: Session) -> FooUseCase:
                return FooUseCase(FooRepo(session))

        Acceptable alternative (deferred):
            def get_foo(session: Session) -> FooUseCase:
                from portfolio.infrastructure.db.repositories.foo import FooRepo  # lazy
                return FooUseCase(FooRepo(session))
        """
        violations: list[ArchViolation] = []

        # Check all services (including scaffolded) — this rule has no exclusions
        for svc in discover_services(include_scaffolded=True):
            api_dir = svc.pkg_dir / "api"
            if not api_dir.is_dir():
                continue

            for py_file in iter_py_files(api_dir):
                try:
                    source = py_file.read_text(encoding="utf-8", errors="replace")
                    tree = ast.parse(source, filename=str(py_file))
                except (SyntaxError, OSError):
                    continue

                # Only examine top-level statements (direct children of Module)
                for node in tree.body:
                    if not isinstance(node, ast.Import | ast.ImportFrom):
                        continue
                    module = node.module if isinstance(node, ast.ImportFrom) else ""
                    if not module:
                        continue

                    pkg_infra_prefix = svc.pkg_name + ".infrastructure"
                    if not module.startswith(pkg_infra_prefix):
                        continue

                    violations.append(
                        ArchViolation(
                            service=svc.name,
                            file=str(py_file.relative_to(svc.service_dir.parent.parent)),
                            line=node.lineno,
                            rule="API-MODULE-LEVEL-INFRA",
                            detail=(
                                f"api/ has a module-level import from infrastructure/ "
                                f"(`{module}`). "
                                "Move to a function-body lazy import (D-1 / IG-LAYER-002). "
                                "Example: `from <pkg>.infrastructure... import X` inside "
                                "the dependency function, not at the top of the file."
                            ),
                        )
                    )

        assert_no_violations(violations, rule="API-MODULE-LEVEL-INFRA")
