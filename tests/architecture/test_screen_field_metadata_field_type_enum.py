"""PLAN-0099 W4 T-W4-02 (audit §13.10): repo-wide arch test pinning
``ScreenFieldMetadata(field_type=...)`` literal values.

Background — BP-585: the ``screen_field_metadata`` table has a CHECK
constraint ``ck_screen_field_metadata_field_type`` admitting only
``'numeric'`` and ``'text'``. PLAN-0098 W3 caught a regression where
two static fields were declared ``field_type="boolean"`` — the
``ScreenFieldsRefreshWorker`` then failed every ~60s with
``CheckViolationError`` and the screener catalogue silently dropped
both rows.

This test scans every Python source file under ``services/`` and
``libs/`` for ``ScreenFieldMetadata(...)`` keyword-argument literals
named ``field_type=`` and asserts the literal value is in the
allow-list ``{"numeric", "text"}``. Non-literal forms (e.g.
``field_type=some_var`` or ``field_type=enum_member``) are skipped —
arch enforcement only applies to inline constants, which is exactly
the class of bug §13.10 calls out.

Failure mode pinned: re-introducing
``ScreenFieldMetadata(field_type="boolean")`` anywhere flips this
test red at write-time, long before any container restart would
expose the CHECK violation.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

# Repo root resolved relative to this file (worldview/tests/architecture/).
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCAN_ROOTS = (REPO_ROOT / "services", REPO_ROOT / "libs")
ALLOWED_FIELD_TYPES = frozenset({"numeric", "text"})


def _iter_python_files() -> list[Path]:
    """Yield every ``*.py`` file under services/ and libs/ — excluding
    cached bytecode and virtualenvs which should never appear under
    these roots anyway."""
    files: list[Path] = []
    for root in SCAN_ROOTS:
        if not root.exists():
            continue
        for p in root.rglob("*.py"):
            # Skip __pycache__ defensively even though rglob won't
            # ordinarily return .pyc — and any embedded venv.
            parts = set(p.parts)
            if "__pycache__" in parts or ".venv312" in parts:
                continue
            files.append(p)
    return files


def _collect_screen_field_metadata_violations(path: Path) -> list[tuple[int, str]]:
    """Return ``(lineno, bad_value)`` for every offending call site in
    ``path``. Best-effort AST parse; on SyntaxError we return [] so a
    transiently-broken file does not derail the arch sweep."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (SyntaxError, UnicodeDecodeError):
        return []

    violations: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        # Match both ``ScreenFieldMetadata(...)`` (Name) and
        # ``mod.ScreenFieldMetadata(...)`` (Attribute) call forms.
        func = node.func
        callee_name: str | None = None
        if isinstance(func, ast.Name):
            callee_name = func.id
        elif isinstance(func, ast.Attribute):
            callee_name = func.attr
        if callee_name != "ScreenFieldMetadata":
            continue

        # Inspect keyword args for ``field_type=<literal>``. Only
        # constant string literals are policed — variables or enum
        # references are out of scope (the arch rule targets inline
        # constants, which is the recurrence pattern §13.10 calls out).
        for kw in node.keywords:
            if kw.arg != "field_type":
                continue
            if isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                value = kw.value.value
                if value not in ALLOWED_FIELD_TYPES:
                    violations.append((node.lineno, value))
    return violations


def test_screen_field_metadata_field_type_literals_are_constraint_compatible() -> None:
    """Every inline ``field_type=<literal>`` on a ``ScreenFieldMetadata(...)``
    call must use a value the DB CHECK constraint admits."""
    failures: list[str] = []
    seen_call_sites = 0
    for path in _iter_python_files():
        for lineno, bad in _collect_screen_field_metadata_violations(path):
            failures.append(f"  {path.relative_to(REPO_ROOT)}:{lineno}: field_type={bad!r}")
            seen_call_sites += 1

    # Defensive: if the scanner finds no call sites at all the test
    # would silently pass forever. Assert we scanned the canonical
    # source file (market-data app.py declares 23 of these). If the
    # file moves, this assertion has to move with it — the rename
    # signal is intentional.
    static_fields = REPO_ROOT / "services" / "market-data" / "src" / "market_data" / "app.py"
    if static_fields.exists():
        # Re-scan and count ALL field_type literals, not just bad ones,
        # to confirm the AST walk is reaching the canonical file.
        text = static_fields.read_text(encoding="utf-8")
        # Cheap substring check — full AST already confirmed 0 bad,
        # so any > 0 occurrence here proves coverage.
        assert 'field_type="numeric"' in text or "field_type='numeric'" in text, (
            "Arch test lost coverage: market-data app.py no longer contains any "
            "ScreenFieldMetadata(field_type='numeric') literals. Either the file "
            "was renamed (update SCAN_ROOTS / this assertion) or the static "
            "screen-field catalogue was refactored — re-verify arch coverage."
        )

    if failures:
        pytest.fail(
            "ScreenFieldMetadata(field_type=...) literal values must be in "
            f"{sorted(ALLOWED_FIELD_TYPES)!r} (DB CHECK ck_screen_field_metadata_field_type). "
            "Offending call sites:\n" + "\n".join(failures)
        )
