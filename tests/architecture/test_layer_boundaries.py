"""
Architecture test: layer boundary enforcement.

Verifies that the hexagonal layer dependency rules from docs/STANDARDS.md §1.2
are respected across all mature services:

  domain ← application ← api
  domain ← application ← infrastructure

Specifically:
  - domain must NOT import from application, api, or infrastructure
  - application must NOT import from api or infrastructure (uses interfaces only)
  - api must NOT import infrastructure internals directly

Only mature (non-scaffolded) services are checked.
"""

from __future__ import annotations

from tests.architecture._utils import (
    ArchViolation,
    ServiceInfo,
    assert_no_violations,
    discover_mature_services,
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
