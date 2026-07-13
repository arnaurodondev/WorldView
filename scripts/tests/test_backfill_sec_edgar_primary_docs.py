"""Tests for scripts/ops/backfill_sec_edgar_primary_docs.py — UA resolution (issue #4)."""

from __future__ import annotations

import importlib.util
import os
import sys

import pytest

pytestmark = pytest.mark.unit

_SCRIPT_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "ops", "backfill_sec_edgar_primary_docs.py"),
)
_spec = importlib.util.spec_from_file_location("backfill_sec_edgar_primary_docs", _SCRIPT_PATH)
assert _spec is not None and _spec.loader is not None
backfill = importlib.util.module_from_spec(_spec)
sys.modules["backfill_sec_edgar_primary_docs"] = backfill
_spec.loader.exec_module(backfill)


def test_prefixed_var_is_used() -> None:
    assert (
        backfill.resolve_user_agent({"CONTENT_INGESTION_SEC_EDGAR_USER_AGENT": "worldview/1.0 a@b.com"})
        == "worldview/1.0 a@b.com"
    )


def test_prefixed_wins_over_unprefixed() -> None:
    assert (
        backfill.resolve_user_agent(
            {"CONTENT_INGESTION_SEC_EDGAR_USER_AGENT": "primary", "SEC_EDGAR_USER_AGENT": "fallback"}
        )
        == "primary"
    )


def test_unprefixed_fallback() -> None:
    assert backfill.resolve_user_agent({"SEC_EDGAR_USER_AGENT": "fallback-ua"}) == "fallback-ua"


def test_blank_prefixed_falls_through_and_value_is_stripped() -> None:
    assert (
        backfill.resolve_user_agent({"CONTENT_INGESTION_SEC_EDGAR_USER_AGENT": "   ", "SEC_EDGAR_USER_AGENT": "real"})
        == "real"
    )
    assert backfill.resolve_user_agent({"CONTENT_INGESTION_SEC_EDGAR_USER_AGENT": "  spaced  "}) == "spaced"


def test_missing_returns_empty_string() -> None:
    assert backfill.resolve_user_agent({}) == ""
