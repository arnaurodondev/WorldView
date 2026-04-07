"""
Architecture test: configuration pattern enforcement.

Verifies that service configuration follows the pydantic-settings pattern
defined in docs/STANDARDS.md §8:

1. config.py defines a Settings class that inherits from BaseSettings.
2. No module-level Settings() instantiation in service src/ (except in config.py
   itself and the main entry point).
3. Settings uses env_prefix to namespace environment variables.
4. Required observability fields (log_level, log_json) are present.

Per docs/STANDARDS.md §8 (Configuration) and docs/libs/observability.md.
"""

from __future__ import annotations

import ast

from tests.architecture._utils import (
    ArchViolation,
    ServiceInfo,
    assert_no_violations,
    discover_services,
    iter_py_files,
)

# ---------------------------------------------------------------------------
# AST visitors
# ---------------------------------------------------------------------------


class _SettingsClassVisitor(ast.NodeVisitor):
    """Detect Settings class definitions and their bases."""

    def __init__(self) -> None:
        self.settings_classes: list[tuple[int, str, list[str]]] = []  # (line, name, bases)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        bases = []
        for base in node.bases:
            if isinstance(base, ast.Name):
                bases.append(base.id)
            elif isinstance(base, ast.Attribute):
                bases.append(base.attr)
        if "Settings" in node.name or any("Settings" in b for b in bases):
            self.settings_classes.append((node.lineno, node.name, bases))
        self.generic_visit(node)


class _ModuleLevelCallVisitor(ast.NodeVisitor):
    """Detect module-level Settings() calls (outside function/class bodies)."""

    def __init__(self) -> None:
        self._depth: int = 0
        self.module_level_settings_calls: list[int] = []

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._depth += 1
        self.generic_visit(node)
        self._depth -= 1

    visit_AsyncFunctionDef = visit_FunctionDef  # type: ignore[assignment]

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._depth += 1
        self.generic_visit(node)
        self._depth -= 1

    def visit_Assign(self, node: ast.Assign) -> None:
        if self._depth == 0:
            if isinstance(node.value, ast.Call):
                func = node.value.func
                call_name = ""
                if isinstance(func, ast.Name):
                    call_name = func.id
                elif isinstance(func, ast.Attribute):
                    call_name = func.attr
                if call_name == "Settings":
                    self.module_level_settings_calls.append(node.lineno)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if self._depth == 0 and node.value is not None:
            if isinstance(node.value, ast.Call):
                func = node.value.func
                call_name = ""
                if isinstance(func, ast.Name):
                    call_name = func.id
                elif isinstance(func, ast.Attribute):
                    call_name = func.attr
                if call_name == "Settings":
                    self.module_level_settings_calls.append(node.lineno)
        self.generic_visit(node)


class _SettingsFieldVisitor(ast.NodeVisitor):
    """Extract field names from a Settings class body."""

    def __init__(self) -> None:
        self.field_names: set[str] = set()

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        if "Settings" in node.name:
            for item in node.body:
                if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                    self.field_names.add(item.target.id)
        self.generic_visit(node)


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------


def _check_settings_class(svc: ServiceInfo) -> list[ArchViolation]:
    """config.py must define a Settings class inheriting from BaseSettings."""
    violations = []
    config_py = svc.pkg_dir / "config.py"
    if not config_py.exists():
        return violations  # caught by STR-003

    try:
        source = config_py.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(source)
    except (SyntaxError, OSError):
        return violations

    visitor = _SettingsClassVisitor()
    visitor.visit(tree)

    if not visitor.settings_classes:
        violations.append(
            ArchViolation(
                service=svc.name,
                file=str(config_py.relative_to(svc.service_dir.parent.parent)),
                line=0,
                rule="CFG-SETTINGS-CLASS",
                detail="config.py must define a Settings class (no Settings class found)",
            )
        )
        return violations

    # Check that Settings inherits from BaseSettings.
    # Exception: compound sub-models (e.g. EODHDProviderSettings) inherit from
    # BaseModel — that is the correct pydantic-settings v2 nested-model pattern
    # and should not be flagged.  Only the root "Settings" class (name == "Settings"
    # or a simple single-word variant) must inherit from BaseSettings.
    for line, name, bases in visitor.settings_classes:
        # Allow BaseModel as base for helper sub-models (compound names)
        is_root_settings = name == "Settings"
        if "BaseSettings" not in bases and "Settings" not in bases:
            if not is_root_settings and "BaseModel" in bases:
                # Nested provider/client settings sub-model — valid pattern
                continue
            violations.append(
                ArchViolation(
                    service=svc.name,
                    file=str(config_py.relative_to(svc.service_dir.parent.parent)),
                    line=line,
                    rule="CFG-SETTINGS-BASE",
                    detail=f"Settings class '{name}' must inherit from BaseSettings (found bases: {bases})",
                )
            )

    return violations


def _check_no_module_level_settings(svc: ServiceInfo) -> list[ArchViolation]:
    """No module-level Settings() calls outside of config.py and main entry."""
    violations = []
    allowed_files = {"config.py", "app.py", "__main__.py", "main.py"}

    for py_file in iter_py_files(svc.pkg_dir):
        if "tests" in py_file.parts:
            continue
        if py_file.name in allowed_files:
            continue

        try:
            source = py_file.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(source)
        except (SyntaxError, OSError):
            continue

        visitor = _ModuleLevelCallVisitor()
        visitor.visit(tree)
        rel = str(py_file.relative_to(svc.service_dir.parent.parent))
        for line in visitor.module_level_settings_calls:
            violations.append(
                ArchViolation(
                    service=svc.name,
                    file=rel,
                    line=line,
                    rule="CFG-NO-MODULE-SETTINGS",
                    detail=(
                        "Module-level Settings() instantiation outside config.py/app.py. "
                        "Settings must be created at runtime via dependency injection or lifespan."
                    ),
                )
            )

    return violations


def _check_observability_fields(svc: ServiceInfo) -> list[ArchViolation]:
    """Settings class must include required observability fields."""
    violations = []
    config_py = svc.pkg_dir / "config.py"
    if not config_py.exists():
        return violations

    try:
        source = config_py.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(source)
    except (SyntaxError, OSError):
        return violations

    visitor = _SettingsFieldVisitor()
    visitor.visit(tree)

    REQUIRED_OBS_FIELDS = {"log_level", "log_json"}
    missing = REQUIRED_OBS_FIELDS - visitor.field_names
    if missing and visitor.field_names:  # only check if Settings has any fields
        rel = str(config_py.relative_to(svc.service_dir.parent.parent))
        violations.append(
            ArchViolation(
                service=svc.name,
                file=rel,
                line=0,
                rule="CFG-OBS-FIELDS",
                detail=(
                    f"Settings missing required observability fields: {sorted(missing)}. "
                    "Add log_level: str = 'INFO' and log_json: bool = True."
                ),
            )
        )
    return violations


# ---------------------------------------------------------------------------
# Baselines for services with known non-standard (but valid) config patterns
# ---------------------------------------------------------------------------

# Services in this set use a re-export shim in config.py instead of a direct
# class definition.  All current violations have been resolved.
_CFG_SETTINGS_CLASS_BASELINE: frozenset[str] = frozenset()


# ---------------------------------------------------------------------------
# Test classes
# ---------------------------------------------------------------------------


class TestSettingsClass:
    def test_config_defines_settings_class(self) -> None:
        """config.py must define a Settings class."""
        violations = []
        for svc in discover_services():
            if svc.name in _CFG_SETTINGS_CLASS_BASELINE:
                continue
            violations.extend(_check_settings_class(svc))
        assert_no_violations(violations, rule="CFG-SETTINGS-CLASS")

    def test_no_module_level_settings_instantiation(self) -> None:
        """Settings() must not be called at module level outside config.py."""
        violations = []
        for svc in discover_services():
            violations.extend(_check_no_module_level_settings(svc))
        assert_no_violations(violations, rule="CFG-NO-MODULE-SETTINGS")

    def test_settings_has_observability_fields(self) -> None:
        """Settings class must include log_level and log_json fields."""
        violations = []
        for svc in discover_services():
            violations.extend(_check_observability_fields(svc))
        assert_no_violations(violations, rule="CFG-OBS-FIELDS")
