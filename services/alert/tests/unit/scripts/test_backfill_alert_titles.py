"""Unit tests for the alert title backfill script (PLAN-0049 T-C-3-01 / F-QAC-08).

The backfill script duplicates the title-derivation logic from
``AlertFanoutUseCase`` (it imports the helpers ``_derive_signal_label`` +
``_compose_alert_title``).  Without these tests, a refactor of
``_derive_for_row`` could silently drift from the live enrichment path —
backfilled rows would not match natively-enriched rows, and the only
detection signal would be operators noticing weird titles in production.

These tests pin the four-rung fallback ladder against representative
payloads so any contract drift trips a failing assertion.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from alert.scripts.backfill_alert_titles import _derive_for_row


def _make_row(
    *,
    alert_type: str = "SIGNAL",
    severity: str = "medium",
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a fake ``asyncpg.Record``-shaped mapping for the derivation logic.

    ``_derive_for_row`` only indexes by string keys (``row["payload"]``,
    ``row["severity"]``, ``row["alert_type"]``, ``row["alert_id"]``) so a
    plain ``dict`` is interchangeable with the real Record type.
    """
    return {
        "alert_id": uuid4(),
        "alert_type": alert_type,
        "severity": severity,
        "payload": payload or {},
    }


@pytest.mark.unit
class TestDeriveForRow:
    """Pin each rung of the 4-level fallback ladder."""

    def test_rung1_signal_label_in_payload(self) -> None:
        """Best case: payload carries claim_type+polarity matching the lookup table."""
        # WHY ``forward_guidance``+``positive``: those are the actual keys in
        # ``_SIGNAL_LABEL_TABLE`` at alert_fanout.py:93. A test using the
        # wrong shape would silently fall back to "{SEVERITY} signal" and
        # green-light a regression where backfill drifts from live derivation.
        row = _make_row(
            payload={
                "claim_type": "forward_guidance",
                "polarity": "positive",
                "entity_name": "Apple Inc.",
                "ticker": "AAPL",
            },
        )
        title, signal_label, entity_name, ticker = _derive_for_row(row)

        # ``signal_label`` derives from claim_type+polarity; the lookup yields
        # "Bullish guidance" — NOT a bare "{SEVERITY} signal" fallback.
        assert signal_label == "Bullish guidance"
        assert "AAPL" in title or "Apple" in title
        assert ticker == "AAPL"
        assert entity_name == "Apple Inc."

    def test_rung2_entity_name_only(self) -> None:
        """No claim/polarity, but entity_name present — title still informative."""
        row = _make_row(
            severity="high",
            payload={"entity_name": "Microsoft Corp."},
        )
        title, _signal_label, entity_name, ticker = _derive_for_row(row)

        assert "Microsoft" in title
        assert entity_name == "Microsoft Corp."
        assert ticker is None

    def test_rung3_alert_type_humanised(self) -> None:
        """No payload context — title falls through to humanised alert_type."""
        row = _make_row(alert_type="EARNINGS_BEAT", severity="low", payload={})
        title, _signal_label, entity_name, ticker = _derive_for_row(row)

        # F-D-006 contract: title MUST NEVER be a bare "{SEVERITY} signal" string.
        assert title not in {"LOW signal", "MEDIUM signal", "HIGH signal", "CRITICAL signal"}
        assert title  # non-empty
        assert entity_name is None
        assert ticker is None

    def test_rung4_unknown_severity_does_not_crash(self) -> None:
        """An unrecognised severity value collapses to MEDIUM (no exception)."""
        row = _make_row(severity="ULTRA_MEGA", alert_type="UNKNOWN", payload={})
        # Must not raise.
        title, _signal_label, _entity_name, _ticker = _derive_for_row(row)
        assert title

    def test_handles_empty_payload(self) -> None:
        """``payload=None`` (rare but possible on legacy rows) is treated as ``{}``."""
        # asyncpg's set_type_codec turns NULL JSONB into ``None``; the script
        # coerces with ``payload or {}``.  Confirms that no AttributeError
        # leaks through when payload is missing entirely.
        row: dict[str, Any] = {
            "alert_id": uuid4(),
            "alert_type": "SIGNAL",
            "severity": "medium",
            "payload": None,
        }
        title, _signal_label, _entity_name, _ticker = _derive_for_row(row)
        assert title

    def test_payload_with_falsy_entity_name_returns_none(self) -> None:
        """Empty-string / falsy entity_name should NOT propagate as a literal "" — must collapse to None.

        Otherwise the UPDATE would clobber a NULL entity_name with an empty
        string which is worse than the original NULL (breaks the
        ``COALESCE(entity_name, $4)`` policy).
        """
        row = _make_row(payload={"entity_name": "", "ticker": ""})
        _title, _signal_label, entity_name, ticker = _derive_for_row(row)

        assert entity_name is None
        assert ticker is None
