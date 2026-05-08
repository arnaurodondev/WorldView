"""
Architecture test: all unit test files must use module-level pytestmark.
Per STANDARDS.md §20 (TI-8): pytest markers must be declared at module level,
not per function.

Rationale
---------
When markers are declared per-function, -m "unit" filtering silently skips
functions that are missing the decorator. Module-level pytestmark applies
the marker to every test in the file so filtering is reliable and consistent.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

pytestmark = pytest.mark.unit


def _get_unit_test_files() -> list[pathlib.Path]:
    # __file__ is tests/architecture/test_pytest_marker_enforcement.py
    # parent = tests/architecture/, parent.parent = tests/, parent.parent.parent = repo_root
    repo_root = pathlib.Path(__file__).parent.parent.parent
    return list(repo_root.glob("services/*/tests/unit/**/*.py")) + list(repo_root.glob("libs/*/tests/unit/**/*.py"))


def _has_module_pytestmark(tree: ast.Module) -> bool:
    """Check for module-level ``pytestmark = ...`` at top level only.

    Uses ``tree.body`` instead of ``ast.walk`` so that a ``pytestmark``
    assignment inside a nested function or class body does NOT satisfy the
    requirement (F-A010).
    """
    for node in tree.body:  # only top-level module statements
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "pytestmark":
                    return True
    return False


_REPO_ROOT = pathlib.Path(__file__).parent.parent.parent


@pytest.mark.parametrize(
    "test_file",
    _get_unit_test_files(),
    ids=lambda p: str(p.relative_to(_REPO_ROOT)),
)
def test_unit_test_files_have_module_level_pytestmark(test_file: pathlib.Path) -> None:
    """Every unit test file must declare pytestmark at module level (TI-8)."""
    # Skip non-test files: __init__.py and conftest.py do not need pytestmark
    if test_file.name in ("__init__.py", "conftest.py"):
        return

    source = test_file.read_text()
    tree = ast.parse(source)

    # Skip files that don't contain any test functions
    has_tests = any(
        isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name.startswith("test_")
        for node in ast.walk(tree)
    )
    if not has_tests:
        return

    assert _has_module_pytestmark(tree), (
        f"{test_file}: missing module-level `pytestmark = pytest.mark.unit`. "
        "Add `pytestmark = pytest.mark.unit` at the top of the file (after imports). "
        "See STANDARDS.md §20 (TI-8)."
    )
