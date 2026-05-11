"""Regression guard: init_sentry is wired into app lifespan (PLAN-0065 Wave C T-C-03)."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit


def test_lifespan_calls_init_sentry_with_service_name() -> None:
    """lifespan() must call init_sentry(service_name=...) — PLAN-0065 T-C-03 guard."""
    app_py = Path(__file__).parent.parent.parent / "src" / "portfolio" / "app.py"
    source = app_py.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(app_py))

    found = False
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (isinstance(func, ast.Name) and func.id == "init_sentry"):
            continue
        for kw in node.keywords:
            if kw.arg == "service_name":
                found = True
                break

    assert found, "init_sentry(service_name=...) not found in portfolio/app.py"
