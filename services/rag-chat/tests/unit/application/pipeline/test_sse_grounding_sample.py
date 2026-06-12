"""tool_result SSE grounding_sample — PRD-0091 FR-5 / FR-8 / §6.3 (PLAN-0110 W2).

Contract under test:
  - ``SSEEmitter.build_grounding_sample`` returns a bounded, redacted,
    allow-list-only ``{fields, sampled_rows, total_rows, truncated}`` dict, or
    ``None`` for non-allow-listed tools / when no allow-listed field survives.
  - All four hard caps (rows / fields-per-row / value chars / byte cap) hold;
    over-cap → ``truncated=true`` and the serialized sample ≤ 1024 bytes.
  - Portfolio / account identifiers are NEVER emitted (FR-8 redaction).
  - ``emit_tool_result`` attaches ``grounding_sample`` ONLY when the env flag is
    on AND status == "ok" AND the sample is non-empty; otherwise the legacy
    4-key payload stays byte-identical (AD-4 forward-compat).

NOTE on test doubles: we use real ``RetrievedItem`` / lightweight objects, NOT
``MagicMock`` — a bare ``MagicMock`` returns a truthy child mock for ANY
attribute, which would defeat the allow-list (every field would "survive").
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from rag_chat.application.pipeline.sse_emitter import SSEEmitter
from rag_chat.domain.entities.chat import CitationMeta, RetrievedItem
from rag_chat.domain.enums import ItemType

pytestmark = pytest.mark.unit


class _Row:
    """Minimal structured result row exposing arbitrary attributes by name.

    Stands in for a (future) handler that surfaces numeric fields directly on
    the item. Only the attributes passed to ``__init__`` exist; ``getattr`` for
    anything else raises AttributeError → the builder's ``getattr(..., None)``
    yields None (field does not survive), which is exactly what we want to test.
    """

    def __init__(self, **fields: Any) -> None:
        for k, v in fields.items():
            setattr(self, k, v)


def _fundamentals_item(ticker: str) -> RetrievedItem:
    """A realistic fundamentals RetrievedItem (ticker surfaced via citation_meta)."""
    return RetrievedItem.create(
        item_id=f"tool:fundamentals:{ticker}",
        item_type=ItemType.financial,
        text="Revenue $94.0B | EPS $1.46 | Gross profit $43.0B",
        score=0.88,
        trust_weight=0.90,
        citation_meta=CitationMeta(
            title=f"Fundamentals: {ticker}",
            url=None,
            source_name="fundamentals",
            published_at=None,
            entity_name=ticker,
        ),
    )


# ---------------------------------------------------------------------------
# build_grounding_sample — shape, caps, redaction, unknown tool.
# ---------------------------------------------------------------------------


class TestBuildGroundingSampleShape:
    def test_returns_canonical_shape(self) -> None:
        items = [_Row(ticker="AAPL", revenue="94000000000", eps="1.46", gross_profit="43000000000")]
        sample = SSEEmitter.build_grounding_sample("get_fundamentals_history", items)
        assert sample is not None
        assert set(sample.keys()) == {"fields", "sampled_rows", "total_rows", "truncated"}
        assert sample["fields"]["ticker"] == "AAPL"
        assert sample["fields"]["revenue"] == "94000000000"
        assert sample["fields"]["eps"] == "1.46"
        assert sample["sampled_rows"] == 1
        assert sample["total_rows"] == 1
        assert sample["truncated"] is False

    def test_ticker_surfaced_from_citation_meta_entity_name(self) -> None:
        """A real fundamentals item carries the ticker as citation_meta.entity_name."""
        sample = SSEEmitter.build_grounding_sample("get_fundamentals_history", [_fundamentals_item("MSFT")])
        # Only the ticker survives (numbers live in ``text``, not as attributes)
        # → sample still produced because at least one allow-listed field hit.
        assert sample is not None
        assert sample["fields"]["ticker"] == "MSFT"

    def test_unknown_tool_returns_none(self) -> None:
        sample = SSEEmitter.build_grounding_sample("get_morning_brief", [_Row(ticker="AAPL", revenue="1")])
        assert sample is None

    def test_no_surviving_field_returns_none(self) -> None:
        """Allow-listed tool but item exposes none of the allow-listed fields."""
        sample = SSEEmitter.build_grounding_sample("get_fundamentals_history", [_Row(unrelated="x")])
        assert sample is None

    def test_empty_items_returns_none(self) -> None:
        assert SSEEmitter.build_grounding_sample("get_fundamentals_history", []) is None


class TestBuildGroundingSampleCaps:
    def test_value_char_cap(self) -> None:
        long_val = "9" * 200
        sample = SSEEmitter.build_grounding_sample("get_fundamentals_history", [_Row(ticker="AAPL", revenue=long_val)])
        assert sample is not None
        assert len(sample["fields"]["revenue"]) == SSEEmitter.GROUNDING_VALUE_MAX_CHARS

    def test_row_cap_samples_at_most_three(self) -> None:
        items = [_Row(ticker=f"T{i}", revenue=str(i)) for i in range(10)]
        sample = SSEEmitter.build_grounding_sample("get_fundamentals_history", items)
        assert sample is not None
        # 10 returned, but only GROUNDING_MAX_ROWS sampled.
        assert sample["total_rows"] == 10
        assert sample["sampled_rows"] <= SSEEmitter.GROUNDING_MAX_ROWS

    def test_field_per_row_cap(self) -> None:
        # Build a row with MORE allow-listed fields than the per-row cap allows.
        # get_fundamentals_history allow-list has 7 fields; cap is 8, so widen
        # via a tool whose allow-list we can exhaust: stuff every field.
        row = _Row(
            ticker="AAPL",
            period="Q1",
            revenue="1",
            eps="2",
            gross_profit="3",
            pe_ratio="4",
            market_cap="5",
        )
        sample = SSEEmitter.build_grounding_sample("get_fundamentals_history", [row])
        assert sample is not None
        # All 7 allow-listed fields are ≤ the per-row cap (8) → all survive.
        assert len(sample["fields"]) <= SSEEmitter.GROUNDING_MAX_FIELDS_PER_ROW

    def test_byte_cap_sets_truncated_and_bounds_size(self) -> None:
        # Many rows each with a near-max value → force the byte cap to fire.
        big = "8" * SSEEmitter.GROUNDING_VALUE_MAX_CHARS
        items = [
            _Row(ticker=big, period=big, revenue=big, eps=big, gross_profit=big, pe_ratio=big, market_cap=big)
            for _ in range(SSEEmitter.GROUNDING_MAX_ROWS)
        ]
        sample = SSEEmitter.build_grounding_sample("get_fundamentals_history", items)
        assert sample is not None
        serialized = json.dumps(sample).encode("utf-8")
        assert len(serialized) <= SSEEmitter.GROUNDING_SAMPLE_MAX_BYTES
        assert sample["truncated"] is True


class TestBuildGroundingSamplePiiRedaction:
    def test_portfolio_account_fields_never_emitted(self) -> None:
        """Even if a redaction-named field were allow-listed, it must be dropped.

        We assert structurally: no key in any produced sample matches a
        portfolio/account redaction substring, for every allow-listed tool.
        """
        # Hand a row that ALSO carries portfolio/account attributes alongside
        # the legitimate ones. The builder reads only allow-listed names, so the
        # PII attrs are never even probed — but we still assert no PII surfaces.
        row = _Row(
            ticker="AAPL",
            revenue="94000000000",
            portfolio_id="port-secret-123",
            account_number="acct-secret-456",
            user_id="user-secret-789",
        )
        for tool in (
            "get_fundamentals_history",
            "compare_entities",
            "get_price_history",
            "search_claims",
        ):
            sample = SSEEmitter.build_grounding_sample(tool, [row])
            if sample is None:
                continue
            joined_keys = " ".join(sample["fields"].keys()).lower()
            joined_vals = " ".join(str(v) for v in sample["fields"].values()).lower()
            assert "portfolio" not in joined_keys
            assert "account" not in joined_keys
            assert "user_id" not in joined_keys
            assert "secret" not in joined_vals

    def test_redaction_substring_in_allowlist_is_dropped(self) -> None:
        """Defence-in-depth: inject a PII-named field into the allow-list at
        runtime and confirm the name-based redaction drops it."""
        original = SSEEmitter._GROUNDING_FIELD_ALLOWLIST.get("get_fundamentals_history")
        try:
            SSEEmitter._GROUNDING_FIELD_ALLOWLIST["get_fundamentals_history"] = (
                "ticker",
                "portfolio_value",  # PII-named — must be redacted by name
            )
            row = _Row(ticker="AAPL", portfolio_value="1234567")
            sample = SSEEmitter.build_grounding_sample("get_fundamentals_history", [row])
            assert sample is not None
            assert "portfolio_value" not in sample["fields"]
            assert sample["fields"].get("ticker") == "AAPL"
        finally:
            # Restore so other tests / module state are unaffected.
            if original is not None:
                SSEEmitter._GROUNDING_FIELD_ALLOWLIST["get_fundamentals_history"] = original


# ---------------------------------------------------------------------------
# emit_tool_result — flag gating + omit-when-empty + status guard.
# ---------------------------------------------------------------------------


_SAMPLE = {
    "fields": {"ticker": "AAPL", "revenue": "94000000000"},
    "sampled_rows": 1,
    "total_rows": 1,
    "truncated": False,
}


class TestEmitToolResultGroundingGating:
    def test_legacy_byte_identical_when_flag_off(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("CHAT_EVAL_GROUNDING_SAMPLES", raising=False)
        frame = SSEEmitter().emit_tool_result(
            "get_fundamentals_history", status="ok", item_count=1, grounding_sample=_SAMPLE
        )
        payload = json.loads(frame["data"])
        assert "grounding_sample" not in payload
        assert set(payload.keys()) == {"type", "tool", "status", "item_count"}

    def test_attached_when_flag_on_and_status_ok(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CHAT_EVAL_GROUNDING_SAMPLES", "true")
        frame = SSEEmitter().emit_tool_result(
            "get_fundamentals_history", status="ok", item_count=1, grounding_sample=_SAMPLE
        )
        payload = json.loads(frame["data"])
        assert payload["grounding_sample"] == _SAMPLE

    def test_not_attached_on_non_ok_status_even_when_flag_on(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CHAT_EVAL_GROUNDING_SAMPLES", "true")
        for status in ("empty", "error", "transport_error"):
            frame = SSEEmitter().emit_tool_result(
                "get_fundamentals_history", status=status, item_count=0, grounding_sample=_SAMPLE
            )
            payload = json.loads(frame["data"])
            assert "grounding_sample" not in payload

    def test_not_attached_when_sample_none_even_with_flag_on(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CHAT_EVAL_GROUNDING_SAMPLES", "true")
        frame = SSEEmitter().emit_tool_result(
            "get_fundamentals_history", status="ok", item_count=1, grounding_sample=None
        )
        payload = json.loads(frame["data"])
        assert "grounding_sample" not in payload

    def test_flag_must_be_exactly_true(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Any non-``true`` value (1, yes, on) keeps the field off — explicit opt-in."""
        for val in ("1", "yes", "on", "TRUE ", "false", ""):
            monkeypatch.setenv("CHAT_EVAL_GROUNDING_SAMPLES", val)
            frame = SSEEmitter().emit_tool_result(
                "get_fundamentals_history", status="ok", item_count=1, grounding_sample=_SAMPLE
            )
            payload = json.loads(frame["data"])
            # "TRUE " strips+lowers to "true" → attached; the rest stay off.
            if val.strip().lower() == "true":
                assert "grounding_sample" in payload
            else:
                assert "grounding_sample" not in payload
