"""Chat-quality D-series fix regressions (2026-07-06 plan Section D).

Covers four orchestrator defects fixed on ``chat_orchestrator.py``:

  * D1 — the empty-pool numeric gate must EXEMPT a successful write-action
    (``create_alert`` → status="ok" + pending_action) whose confirmation carries
    a number ("$400") but contributes ZERO groundable rows, while a REAL
    empty-pool numeric answer still refuses. Both gate sites are covered:
    :meth:`_run_grounding_validation` (:~5643) and
    :meth:`_run_combined_grounding_validation` (:~5064).
  * D6 — bare-name ``entity_id`` is coerced to the resolved UUID before entity
    tools run, and a relationship/supplier query has a graph-traversal fallback.
  * D9 — a transport_error / status=error tool result is retried EXACTLY ONCE,
    and an all-errored turn on a RESOLVED entity is NOT rendered as a
    resolution-miss ("I couldn't find a match for 'AAPL'") string.
  * D4 — gpt-oss commentary-channel leaks (``【commentary row 0】`` /
    ``[**tool row N**]``) are stripped from the delivered answer.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.unit


# ── Shared fakes ─────────────────────────────────────────────────────────────


@dataclass
class _FakeEntity:
    entity_id: str
    canonical_name: str
    ticker: str | None = None
    matched_text: str | None = None


class _FakeToolCall:
    """Minimal stand-in for ToolUseBlock (``.name`` + mutable ``.input`` dict)."""

    def __init__(self, name: str, tool_input: dict[str, Any]) -> None:
        self.name = name
        self.input = tool_input


def _make_orchestrator() -> Any:
    from rag_chat.application.use_cases.chat_orchestrator import ChatOrchestratorUseCase

    return ChatOrchestratorUseCase(pipeline=MagicMock(), tool_executor_factory=MagicMock())


def _make_budget() -> Any:
    b = MagicMock()
    b.max_tokens_final = 256
    return b


# ── D1 — empty-pool gate write-action exemption ──────────────────────────────


class TestD1EmptyPoolWriteActionExemption:
    _CONFIRMATION = "Done — I'll alert you when NVDA drops below $400."

    def _empty_pool(self) -> list[Any]:
        return []

    def test_grounding_validation_write_action_bypasses_empty_pool_gate(self) -> None:
        """:meth:`_run_grounding_validation` — a status=ok write action with a
        numeric confirmation + EMPTY pool is NOT clobbered by the gate."""
        from rag_chat.application.use_cases.chat_orchestrator import _EMPTY_POOL_REFUSAL

        orch = _make_orchestrator()
        with patch(
            "rag_chat.application.services.numeric_grounding.NumericGroundingValidator",
        ) as v_cls:
            v_cls.return_value.validate.return_value = MagicMock(passed=True, unsupported=())
            text, passed = asyncio.run(
                orch._run_grounding_validation(
                    p=MagicMock(),
                    response=self._CONFIRMATION,
                    tool_items=self._empty_pool(),
                    messages=[],
                    budget=_make_budget(),
                    write_action_succeeded=True,
                )
            )
        assert text == self._CONFIRMATION
        assert passed is True
        assert text != _EMPTY_POOL_REFUSAL

    def test_grounding_validation_real_empty_pool_still_refuses(self) -> None:
        """No write action → a numeric answer over an EMPTY pool still refuses."""
        from rag_chat.application.use_cases.chat_orchestrator import _EMPTY_POOL_REFUSAL

        orch = _make_orchestrator()
        text, passed = asyncio.run(
            orch._run_grounding_validation(
                p=MagicMock(),
                response="Apple Q3 revenue was $181.5B.",
                tool_items=[],
                messages=[],
                budget=_make_budget(),
                write_action_succeeded=False,
            )
        )
        assert text == _EMPTY_POOL_REFUSAL
        assert passed is False

    def test_combined_validation_write_action_bypasses_empty_pool_gate(self) -> None:
        """:meth:`_run_combined_grounding_validation` — same exemption at the
        twin gate site."""
        from rag_chat.application.use_cases.chat_orchestrator import _EMPTY_POOL_REFUSAL

        orch = _make_orchestrator()
        with (
            patch(
                "rag_chat.application.services.numeric_grounding.NumericGroundingValidator",
            ) as v_cls,
            patch(
                "rag_chat.application.services.numeric_grounding.numeric_grounding_effectively_passed",
                return_value=True,
            ),
            patch(
                "rag_chat.application.services.numeric_grounding.material_unsupported_numbers",
                return_value=(),
            ),
        ):
            v_cls.return_value.validate.return_value = MagicMock(passed=True, unsupported=())
            text, passed = asyncio.run(
                orch._run_combined_grounding_validation(
                    p=MagicMock(),
                    response=self._CONFIRMATION,
                    tool_items=[],
                    resolved_entities=[],
                    messages=[],
                    budget=_make_budget(),
                    called_tool_names=None,
                    run_entity_pass=False,
                    write_action_succeeded=True,
                )
            )
        assert text == self._CONFIRMATION
        assert passed is True
        assert text != _EMPTY_POOL_REFUSAL

    def test_combined_validation_real_empty_pool_still_refuses(self) -> None:
        from rag_chat.application.use_cases.chat_orchestrator import _EMPTY_POOL_REFUSAL

        orch = _make_orchestrator()
        text, passed = asyncio.run(
            orch._run_combined_grounding_validation(
                p=MagicMock(),
                response="Apple Q3 revenue was $181.5B.",
                tool_items=[],
                resolved_entities=[],
                messages=[],
                budget=_make_budget(),
                called_tool_names=None,
                run_entity_pass=False,
                write_action_succeeded=False,
            )
        )
        assert text == _EMPTY_POOL_REFUSAL
        assert passed is False


# ── D6 — bare-name entity_id → UUID coercion + relationship fallback ─────────


class TestD6EntityIdCoercion:
    _UUID = "018f8f42-1234-7abc-8def-0123456789ab"

    def _apple(self) -> _FakeEntity:
        return _FakeEntity(entity_id=self._UUID, canonical_name="Apple Inc.", ticker="AAPL")

    def test_bare_name_entity_id_coerced_to_uuid(self) -> None:
        from rag_chat.application.use_cases.chat_orchestrator import _coerce_entity_ids_to_uuids

        tc = _FakeToolCall("get_entity_intelligence", {"entity_id": "Apple Inc."})
        coerced = _coerce_entity_ids_to_uuids([tc], [self._apple()], None)
        assert coerced == 1
        assert tc.input["entity_id"] == self._UUID

    def test_bare_ticker_entity_id_coerced_to_uuid(self) -> None:
        from rag_chat.application.use_cases.chat_orchestrator import _coerce_entity_ids_to_uuids

        tc = _FakeToolCall("get_entity_intelligence", {"entity_id": "AAPL"})
        assert _coerce_entity_ids_to_uuids([tc], [self._apple()], None) == 1
        assert tc.input["entity_id"] == self._UUID

    def test_already_uuid_is_left_untouched(self) -> None:
        from rag_chat.application.use_cases.chat_orchestrator import _coerce_entity_ids_to_uuids

        tc = _FakeToolCall("get_entity_intelligence", {"entity_id": self._UUID})
        assert _coerce_entity_ids_to_uuids([tc], [self._apple()], None) == 0
        assert tc.input["entity_id"] == self._UUID

    def test_unknown_name_left_untouched(self) -> None:
        from rag_chat.application.use_cases.chat_orchestrator import _coerce_entity_ids_to_uuids

        tc = _FakeToolCall("get_entity_intelligence", {"entity_id": "Nonexistent Corp"})
        assert _coerce_entity_ids_to_uuids([tc], [self._apple()], None) == 0
        assert tc.input["entity_id"] == "Nonexistent Corp"

    def test_non_uuid_tool_not_coerced(self) -> None:
        from rag_chat.application.use_cases.chat_orchestrator import _coerce_entity_ids_to_uuids

        # search_documents is NOT in the UUID-id tool set — leave its args alone.
        tc = _FakeToolCall("search_documents", {"entity_id": "Apple Inc."})
        assert _coerce_entity_ids_to_uuids([tc], [self._apple()], None) == 0
        assert tc.input["entity_id"] == "Apple Inc."

    def test_relationship_query_routes_to_graph_traversal(self) -> None:
        """An empty ``get_entity_intelligence`` falls back to the KG relation
        search (D6 supplier/relationship routing)."""
        from rag_chat.application.use_cases.chat_orchestrator import (
            _FALLBACK_MAP,
            _project_entity_intelligence_to_search_relations,
        )

        assert "search_entity_relations" in _FALLBACK_MAP["get_entity_intelligence"]
        ctx = MagicMock()
        ctx.name = "Apple Inc."
        ctx.ticker = "AAPL"
        args = _project_entity_intelligence_to_search_relations({"entity_id": self._UUID}, ctx)
        assert args == {"entity_name": "Apple Inc."}


# ── D9 — retry-once on transient failure + tool-error vs resolution-miss ─────


class TestD9RetryTransient:
    def _executor(self, batches: list[list[Any]]) -> Any:
        """A tool_executor whose ``execute_all`` returns successive *batches*."""
        ex = MagicMock()
        calls: list[Any] = []

        async def _execute_all(tool_calls: list[Any]) -> list[Any]:
            calls.append(list(tool_calls))
            return batches[len(calls) - 1]

        ex.execute_all = _execute_all
        ex._calls = calls
        return ex

    def test_transport_error_retried_once_then_recovers(self) -> None:
        from rag_chat.application.pipeline.transport_error import TransportErrorMarker
        from rag_chat.application.use_cases.chat_orchestrator import _retry_transient_tool_failures

        def _marker() -> Any:
            return TransportErrorMarker(tool_name="query_fundamentals", reason="upstream_timeout", elapsed_ms=100)

        tc = _FakeToolCall("query_fundamentals", {"ticker": "TSLA"})
        recovered = [MagicMock()]  # a real (non-None) result on retry
        fresh_results: list[Any] = [_marker()]
        ex = self._executor(batches=[recovered])

        retried = asyncio.run(_retry_transient_tool_failures(ex, [tc], fresh_results))
        assert retried == 1
        # Exactly ONE retry batch was issued.
        assert len(ex._calls) == 1
        # The transient failure was replaced with the recovered result.
        assert fresh_results[0] is recovered[0]

    def test_persistent_error_keeps_original_marker_and_retries_once(self) -> None:
        from rag_chat.application.pipeline.transport_error import TransportErrorMarker
        from rag_chat.application.use_cases.chat_orchestrator import _retry_transient_tool_failures

        def _marker() -> Any:
            return TransportErrorMarker(tool_name="query_fundamentals", reason="upstream_timeout", elapsed_ms=100)

        tc = _FakeToolCall("query_fundamentals", {"ticker": "TSLA"})
        fresh_results: list[Any] = [_marker()]
        # Retry ALSO fails → keep the original marker; still only ONE retry.
        ex = self._executor(batches=[[_marker()]])

        retried = asyncio.run(_retry_transient_tool_failures(ex, [tc], fresh_results))
        assert retried == 1
        assert len(ex._calls) == 1
        assert isinstance(fresh_results[0], TransportErrorMarker)

    def test_empty_result_is_not_retried(self) -> None:
        from rag_chat.application.use_cases.chat_orchestrator import _retry_transient_tool_failures

        tc = _FakeToolCall("query_fundamentals", {"ticker": "TSLA"})
        fresh_results: list[Any] = [[]]  # status="empty" — legitimate, no retry
        ex = self._executor(batches=[])

        retried = asyncio.run(_retry_transient_tool_failures(ex, [tc], fresh_results))
        assert retried == 0
        assert len(ex._calls) == 0
        assert fresh_results[0] == []

    def test_tool_error_on_resolved_entity_is_not_resolution_miss(self) -> None:
        from rag_chat.application.use_cases.chat_orchestrator import _build_all_errored_message

        apple = _FakeEntity(entity_id="uuid", canonical_name="Apple Inc.", ticker="AAPL")
        msg = _build_all_errored_message([apple], ticker_hint="AAPL")
        assert "couldn't find a match" not in msg.lower()
        assert "Apple Inc." in msg
        assert "trouble retrieving" in msg.lower()

    def test_genuine_resolution_miss_uses_couldnt_find_string(self) -> None:
        from rag_chat.application.use_cases.chat_orchestrator import _build_all_errored_message

        msg = _build_all_errored_message([], ticker_hint="ZZZQQQ")
        assert "couldn't find a match for 'ZZZQQQ'" in msg


# ── D4 — commentary-channel leak strip ───────────────────────────────────────


class TestD4CommentaryChannelStrip:
    def test_fullwidth_commentary_channel_stripped(self) -> None:
        from rag_chat.application.use_cases.chat_orchestrator import _strip_commentary_channel_leak

        out = _strip_commentary_channel_leak("Apple's P/E is 37.32 【commentary row 0】 today.")
        assert "【commentary row 0】" not in out
        assert "commentary" not in out
        assert "37.32" in out

    def test_fullwidth_tool_row_tag_stripped(self) -> None:
        from rag_chat.application.use_cases.chat_orchestrator import _strip_commentary_channel_leak

        out = _strip_commentary_channel_leak("Revenue was $181.5B 【search_events row 1】.")
        assert "【search_events row 1】" not in out
        assert "$181.5B" in out

    def test_ascii_channel_tag_stripped(self) -> None:
        from rag_chat.application.use_cases.chat_orchestrator import _strip_commentary_channel_leak

        out = _strip_commentary_channel_leak("The P/E is 37.32 [commentary row 0].")
        assert "[commentary row 0]" not in out
        assert "37.32" in out

    def test_bold_provenance_tag_unwrapped_not_dropped(self) -> None:
        from rag_chat.application.use_cases.chat_orchestrator import _strip_commentary_channel_leak

        # A BOLD provenance tag on a real tool is unwrapped to the plain form so
        # the downstream [tool row N] → [N] citation promotion still fires.
        out = _strip_commentary_channel_leak("Revenue $181.5B [**query_fundamentals row 2**].")
        assert "[**query_fundamentals row 2**]" not in out
        assert "[query_fundamentals row 2]" in out

    def test_clean_answer_is_noop(self) -> None:
        from rag_chat.application.use_cases.chat_orchestrator import _strip_commentary_channel_leak

        clean = "Apple's Q3 revenue was $181.5B [1] and EPS was $7.14 [2]."
        assert _strip_commentary_channel_leak(clean) == clean

    def test_legit_ascii_tool_row_tag_preserved(self) -> None:
        from rag_chat.application.use_cases.chat_orchestrator import _strip_commentary_channel_leak

        # The plain (non-bold, non-channel) provenance tag must survive for the
        # downstream citation promotion.
        text = "Revenue was $181.5B [query_fundamentals row 0]."
        assert _strip_commentary_channel_leak(text) == text
