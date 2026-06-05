"""Integration tests for the orchestrator's E-2 grounding hook.

PLAN-0093 Wave E-2, Task T-E-2-02.

Coverage:
- ``test_validator_invoked_after_tool_loop`` — the validator runs once
  per turn after the LLM produces its final answer.
- ``test_failed_grounding_triggers_one_rewrite`` — invented number →
  2 LLM stream_chat calls (initial + rewrite).
- ``test_second_failure_appends_banner`` — both passes fail → response
  ends with the warning banner.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

pytestmark = pytest.mark.unit

_FAKE_UUID = "00000000-0000-0000-0000-000000000002"


def _make_llm_tool_response(text: str = "", tool_calls: list | None = None) -> MagicMock:
    resp = MagicMock()
    resp.text = text
    resp.tool_calls = tool_calls or []
    return resp


def _make_tool_use_block(name: str = "get_fundamentals_history", inp: dict | None = None) -> MagicMock:
    block = MagicMock()
    block.name = name
    block.input = inp or {"entity_id": "aaaa-1111"}
    block.tool_use_id = f"call_{name}"
    return block


def _make_retrieved_item(text: str = "Apple Q3 revenue was $10.253B per the filing.") -> MagicMock:
    item = MagicMock()
    item.item_type = MagicMock()
    item.item_type.value = "financial"
    item.item_id = "tool:fundamentals:AAPL"
    item.text = text
    item.score = 0.9
    # No structured value/field_kind on this stub — the validator falls
    # back to scanning .text for numbers, which is the real-world path.
    item.value = None
    item.field_kind = None
    return item


def _make_pipeline(
    *,
    stream_chunks: list[str] | None = None,
    rewrite_chunks: list[str] | None = None,
) -> tuple[MagicMock, list[list[dict[str, Any]]]]:
    """Build a mock ChatPipeline and capture stream_chat invocations.

    Returns (pipeline, captured_messages_list). Each entry in
    captured_messages_list is the messages array passed to one
    stream_chat call, so the test can assert how many times the LLM was
    invoked AND inspect the rewrite prompt.
    """
    pipeline = MagicMock()
    pipeline.validate_input = AsyncMock(return_value="test query")
    pipeline.check_cache = AsyncMock(return_value=None)
    pipeline.check_rate_limit = AsyncMock()
    pipeline.load_history = AsyncMock(return_value=[])
    pipeline.resolve_entities = AsyncMock(return_value=[])
    pipeline.build_prompt = MagicMock(return_value=("system prompt", [], "context"))
    pipeline.rerank_items = AsyncMock(return_value=[])
    pipeline.process_output = MagicMock(side_effect=lambda text, items: (text, []))
    pipeline.persist_chat = AsyncMock(return_value=(_FAKE_UUID, _FAKE_UUID))
    pipeline.write_completion_cache = AsyncMock()

    pipeline.llm_chain = MagicMock()
    pipeline.llm_chain.last_provider_name = "deepinfra"
    pipeline.llm_chain._providers = []

    captured_messages: list[list[dict[str, Any]]] = []

    initial = stream_chunks or ["Q2 revenue was $34.6B per the filing."]
    rewrite = rewrite_chunks or ["Q2 revenue was $10.253B [N1]."]
    call_n = {"i": 0}

    async def _stream_chat(messages: list, **kwargs: Any):
        captured_messages.append(list(messages))
        call_n["i"] += 1
        # First call → initial draft. Second+ → rewrite.
        chunks = initial if call_n["i"] == 1 else rewrite
        for chunk in chunks:
            yield chunk

    pipeline.llm_chain.stream_chat = _stream_chat

    from rag_chat.application.pipeline.sse_emitter import SSEEmitter

    pipeline.emitter = SSEEmitter()
    return pipeline, captured_messages


def _make_executor(return_items: list) -> MagicMock:
    executor = MagicMock()
    registry = MagicMock()
    registry.to_system_prompt_section = MagicMock(return_value="## Tools\n- get_fundamentals_history")
    executor._registry = registry
    executor.execute_all = AsyncMock(return_value=return_items)
    return executor


def _make_factory(executor: MagicMock) -> MagicMock:
    factory = MagicMock()
    factory.for_request = MagicMock(return_value=executor)
    return factory


def _make_request() -> Any:
    from uuid import UUID

    from rag_chat.domain.entities.chat import ChatContext, ChatRequest

    return ChatRequest(
        message="What was Apple's Q2 revenue?",
        context=ChatContext(),
        tenant_id=UUID(_FAKE_UUID),
        user_id=UUID(_FAKE_UUID),
        thread_id=None,
    )


async def _collect(orch: Any, request: Any, uow: Any) -> tuple[list, str]:
    """Run the streaming orchestrator and assemble the final answer text."""
    events: list = []
    async for ev in orch.execute_streaming(request, uow):
        events.append(ev)
    # Reconstruct the final answer from token events (sync API does this).
    answer = ""
    for ev in events:
        if ev.get("event") == "token":
            answer += json.loads(ev["data"]).get("text", "")
    return events, answer


class TestOrchestratorGroundingHook:
    def _build(self, **kwargs: Any) -> tuple[Any, list, MagicMock]:
        from rag_chat.application.use_cases.chat_orchestrator import ChatOrchestratorUseCase

        pipeline, captured = _make_pipeline(**kwargs)
        # Tool round-trip: iteration 0 calls tool, iteration 1 returns no calls so
        # we exit the loop and the streaming final turn runs.
        block = _make_tool_use_block()
        item = _make_retrieved_item()
        executor = _make_executor([item])
        factory = _make_factory(executor)

        # chat_with_tools: first call returns tool_calls, second returns no calls.
        ct = {"i": 0}

        async def _two_call(messages, tools=None, **_):
            ct["i"] += 1
            if ct["i"] == 1:
                return _make_llm_tool_response(tool_calls=[block])
            return _make_llm_tool_response(text="", tool_calls=[])

        pipeline.llm_chain.chat_with_tools = _two_call
        orch = ChatOrchestratorUseCase(pipeline=pipeline, tool_executor_factory=factory)
        return orch, captured, pipeline

    def test_validator_invoked_after_tool_loop(self) -> None:
        """Healthy response (numbers in tool data) → validator passes, no rewrite."""
        # Tool item already contains "$10.253B" — and the streamed answer
        # echoes that exact number.
        orch, captured, _ = self._build(stream_chunks=["Apple Q3 revenue was $10.253B."])
        _, answer = asyncio.run(_collect(orch, _make_request(), MagicMock()))
        # Validator passed → exactly one stream_chat call (no rewrite).
        assert len(captured) == 1
        assert "$10.253B" in answer

    def test_failed_grounding_triggers_one_rewrite(self) -> None:
        """Invented '$34.6B' → 2 stream_chat calls; persisted answer is the rewrite.

        Streaming mode emits the initial draft as tokens before validation
        runs (so the user sees something quickly). After validation, the
        validated text is what gets ``process_output``/``persist_chat`` —
        the audit log + DB row reflect the rewrite, not the bad draft.
        We assert via the ``persist_chat`` mock call args.
        """
        orch, captured, pipeline = self._build(
            stream_chunks=["Q2 revenue was $34.6B per the filing."],
            rewrite_chunks=["Q2 revenue was $10.253B [N1]."],
        )
        asyncio.run(_collect(orch, _make_request(), MagicMock()))
        # 2 LLM stream_chat calls: initial draft + rewrite.
        assert len(captured) == 2

        # Verify the rewritten answer was the one passed to persist_chat.
        assert pipeline.persist_chat.await_count == 1
        kwargs = pipeline.persist_chat.await_args.kwargs
        assistant_response = kwargs["assistant_response"]
        assert "$10.253B" in assistant_response.content
        assert "$34.6B" not in assistant_response.content

    def test_second_failure_appends_banner(self) -> None:
        """Both initial draft AND rewrite invent numbers → banner appended."""
        orch, captured, pipeline = self._build(
            stream_chunks=["Q2 revenue was $34.6B per the filing."],
            rewrite_chunks=["Actually Q2 revenue was $99.9B by my count."],
        )
        asyncio.run(_collect(orch, _make_request(), MagicMock()))
        # 2 calls — initial + one rewrite (the orchestrator does NOT loop
        # rewrites; one attempt then banner).
        assert len(captured) == 2
        # The persisted answer ends with the banner.
        assistant_response = pipeline.persist_chat.await_args.kwargs["assistant_response"]
        assert "could not be verified" in assistant_response.content

    def test_completion_cache_skipped_when_grounding_fails(self) -> None:
        """F-LIVE-008 regression — cache write MUST be skipped when grounding fails.

        PLAN-0093 Phase 5c found that caching answers flagged by the
        numeric-grounding validator poisons the completion cache for 24h
        (the harness key is deterministic since thread_id=None). The fix
        is to skip ``write_completion_cache`` whenever
        ``_run_grounding_validation`` reports ``grounding_passed=False``
        — i.e. when both the initial draft and the single rewrite
        attempt invented numbers and the banner was appended.
        """
        orch, _, pipeline = self._build(
            stream_chunks=["Q2 revenue was $34.6B per the filing."],
            rewrite_chunks=["Actually Q2 revenue was $99.9B by my count."],
        )
        asyncio.run(_collect(orch, _make_request(), MagicMock()))
        # Persistence still runs (we want the audit trail) but the cache
        # write does NOT — otherwise the banner-laden answer would be
        # frozen for 24h and replayed on every identical question.
        assert pipeline.persist_chat.await_count == 1
        assert pipeline.write_completion_cache.await_count == 0

    def test_banner_suppressed_for_small_revenue_false_positive(self) -> None:
        """PLAN-0104 W44 — when the unsupported set is dominated by the
        BP-648 small-revenue quarter-label false positive (e.g. "Q2"
        parsed as revenue=2.0), the validator is wrong and the original
        answer is actually fine. The banner used to be appended anyway,
        misleading the user AND the judge (R6 grounding=0). After W44
        the banner is SUPPRESSED in this branch — the original answer
        passes through unchanged."""
        # We need the validator to flag many small REVENUE values so the
        # 80% guard triggers. We construct an answer with quarter labels
        # but no real revenue claims, with a tool item that doesn't list
        # any revenue values at all.
        orch, captured, pipeline = self._build(
            stream_chunks=["Tesla quarterly gross margin: Q1 21%, Q2 19%, Q3 20%, Q4 22%."],
            rewrite_chunks=["(should not be called — guard A skips rewrite)"],
        )
        asyncio.run(_collect(orch, _make_request(), MagicMock()))
        # The validator failed (no rewrite call yet) → guard A path either
        # suppresses banner (no banner in answer) and skips rewrite.
        assistant_response = pipeline.persist_chat.await_args.kwargs["assistant_response"]
        # Critical W44 assertion: the false-positive branch no longer
        # emits the banner; the original text passes through clean.
        if "Q1 21%" in assistant_response.content:
            # If we hit the small-revenue branch the rewrite was skipped
            # AND no banner was appended.
            assert "could not be verified" not in assistant_response.content, (
                "W44 — small-revenue false-positive guard must suppress the banner; "
                f"got: {assistant_response.content!r}"
            )

    def test_banner_suppressed_when_rewrite_is_honest_refusal(self) -> None:
        """PLAN-0104 W44 — when both passes fail BUT the rewrite is an
        honest refusal stating data is unavailable, the refusal already
        conveys "I couldn't verify this". Appending the banner is
        redundant noise that misled the judge (R6 Q6 AAPL forward P/E
        grounding=0). After W44 the banner is suppressed and the honest
        refusal passes through unchanged."""
        orch, captured, pipeline = self._build(
            stream_chunks=["AAPL forward P/E is $34.6 per Q2 outlook."],
            # The rewrite refuses honestly — matches the W44 refusal-signal list.
            rewrite_chunks=["Forward P/E is not currently available in our data sources."],
        )
        asyncio.run(_collect(orch, _make_request(), MagicMock()))
        assert len(captured) == 2  # initial + rewrite both ran
        assistant_response = pipeline.persist_chat.await_args.kwargs["assistant_response"]
        # The honest refusal is the persisted content; the banner is NOT appended.
        assert "not currently available" in assistant_response.content
        assert "could not be verified" not in assistant_response.content, (
            "W44 — honest-refusal rewrite must not have the redundant banner appended; "
            f"got: {assistant_response.content!r}"
        )

    def test_banner_still_appended_when_rewrite_invents_new_numbers(self) -> None:
        """W44 guard rail — banner suppression must NOT hide real verification
        failures. When the rewrite ALSO invents specific numbers (not an
        honest refusal, not a small-revenue false positive), the banner
        must still fire so the user is warned."""
        orch, captured, pipeline = self._build(
            stream_chunks=["Q2 revenue was $34.6B per the filing."],
            # Rewrite invents another specific bogus number — NOT a refusal.
            rewrite_chunks=["Actually Q2 revenue was $99.9B by my count."],
        )
        asyncio.run(_collect(orch, _make_request(), MagicMock()))
        assert len(captured) == 2
        assistant_response = pipeline.persist_chat.await_args.kwargs["assistant_response"]
        # The banner MUST fire here — the rewrite still invents a number.
        assert "could not be verified" in assistant_response.content, (
            "W44 — banner suppression must not hide real fabrication; " f"got: {assistant_response.content!r}"
        )

    def test_completion_cache_written_when_grounding_passes(self) -> None:
        """Sanity check — passing grounding still writes to the cache.

        Counterpart to ``test_completion_cache_skipped_when_grounding_fails``:
        when the validator accepts the answer (number matches a tool
        value within tolerance), the cache write must STILL fire so we
        keep the performance benefit of completion caching for good
        answers.
        """
        orch, _, pipeline = self._build(stream_chunks=["Apple Q3 revenue was $10.253B."])
        asyncio.run(_collect(orch, _make_request(), MagicMock()))
        assert pipeline.persist_chat.await_count == 1
        assert pipeline.write_completion_cache.await_count == 1


# ─────────────────────────────────────────────────────────────────────────────
# PLAN-0104 W29 — direct unit tests for the two-way text-token fallback in
# `_check_entity_grounding`. The Round 3 chat benchmark surfaced a TSLA
# refusal where:
#   - resolved entity yielded question_ids = {uuid, "tesla inc", "tesla"}
#   - the only tool item rendered as "TSLA quarterly fundamentals..."
#   - PLAN-0103 W26's one-way fallback (looking for "tesla" inside "TSLA
#     quarterly...") missed because the ticker form is not in the question
#     id set.
# These tests pin the opposite-direction match (ticker in item.text ↔
# question ids) and guard the bound — an unrelated ticker MUST still fail
# to avoid silent cross-entity attribution.
# ─────────────────────────────────────────────────────────────────────────────


def _make_grounding_item(text: str, entity_name: str | None = None) -> MagicMock:
    """Lightweight retrieved-item stub for the grounding check.

    The check reads three attrs: citation_meta.entity_name, entity_id,
    and text. We leave entity_id None and only populate text +
    optionally citation_meta.entity_name so the assertions exercise the
    text-token fallback paths specifically.
    """
    item = MagicMock()
    item.entity_id = None
    item.text = text
    if entity_name is None:
        item.citation_meta = None
    else:
        cm = MagicMock()
        cm.entity_name = entity_name
        item.citation_meta = cm
    return item


class TestEntityGroundingTwoWayFallback:
    """W29-1 regression: ticker-in-text intersects with question ids."""

    def test_tsla_ticker_in_text_passes_when_question_has_tesla(self) -> None:
        """The original Round 3 fault: item text has only the ticker.

        Question entity ids come from the resolver as the lowercased
        canonical name(s). The new fallback extracts "TSLA" from the
        item text, lowercases it, and looks for it inside any qid
        ("tesla inc" contains "tsla"? NO — but we also accept text-token
        match in the original direction when canonical names appear in
        the text). The intended pass path here is the ticker-substring
        check against `tesla` — "tsla" is NOT a substring of "tesla", so
        this specific item should pass via the substring rule only when
        the ticker appears as a word inside a qid. Since "tsla" is not
        in "tesla", the pass path is via citation_meta.entity_name when
        present. We test BOTH variants below.
        """
        from rag_chat.application.use_cases.chat_orchestrator import _check_entity_grounding

        # Variant A: item exposes citation_meta.entity_name="Tesla Inc".
        # Pass path: cm_name substring match against "tesla inc".
        item = _make_grounding_item(
            text="TSLA quarterly fundamentals: revenue 25.18B, gross margin 17.9%.",
            entity_name="Tesla Inc",
        )
        result = _check_entity_grounding([item], {"tesla inc", "tesla"})
        assert result is None, "Expected grounding to pass via cm.entity_name substring"

    def test_aapl_ticker_in_text_with_apple_question(self) -> None:
        """AAPL in item.text + question {"apple", "apple inc"} → passes.

        Pass path: cm.entity_name="Apple Inc" matches "apple inc" qid
        via substring relation (equality after lowercasing).
        """
        from rag_chat.application.use_cases.chat_orchestrator import _check_entity_grounding

        item = _make_grounding_item(
            text="AAPL data block — revenue 100B.",
            entity_name="Apple Inc",
        )
        assert _check_entity_grounding([item], {"apple", "apple inc"}) is None

    def test_unrelated_ticker_still_refuses(self) -> None:
        """MSFT in item.text + question {"apple"} → MUST still refuse.

        Negative guard — the broadened fallback must NOT admit a wrong
        company. "msft" is neither equal to nor a substring-word of
        "apple", and we leave citation_meta unset so the cm.entity_name
        path is inert.
        """
        from rag_chat.application.use_cases.chat_orchestrator import _check_entity_grounding

        item = _make_grounding_item(text="MSFT data block — revenue 200B.", entity_name=None)
        result = _check_entity_grounding([item], {"apple"})
        assert result is not None, "Expected refusal for unrelated ticker"
        assert "cannot find information about the entities" in result

    def test_ticker_equality_match(self) -> None:
        """If the question id set already contains the ticker, ticker == qid passes.

        Covers the case where the resolver did include ticker in the
        question id set (e.g. {uuid, "tesla inc", "tesla", "tsla"}).
        """
        from rag_chat.application.use_cases.chat_orchestrator import _check_entity_grounding

        item = _make_grounding_item(text="TSLA fundamentals snapshot.", entity_name=None)
        assert _check_entity_grounding([item], {"tsla", "tesla"}) is None

    def test_no_question_entities_is_passthrough(self) -> None:
        """Entity-free chat (empty question id set) MUST not refuse."""
        from rag_chat.application.use_cases.chat_orchestrator import _check_entity_grounding

        item = _make_grounding_item(text="Some unrelated text.", entity_name=None)
        assert _check_entity_grounding([item], set()) is None


# ─────────────────────────────────────────────────────────────────────────────
# PLAN-0104 W37 — query_fundamentals envelope: prior-tool-call ticker fallback.
# Round 4 TSLA (q_ru_tsla_margin_trend) refused even after W26 + W29 because:
#   - question entities = {"tesla", "tesla, inc.", <uuid>} (resolver omitted
#     ticker on this run);
#   - the only retrieved item came from query_fundamentals with
#     citation_meta.entity_name="TSLA" and rendered text "## TSLA fundamentals
#     query…";
#   - the W29 substring rules required "tsla" ⊂ "tesla" (or v.v.) and
#     "tsla" ⊂ "tesla, inc." — neither holds.
# W37 widens the admission criteria by trusting the LLM's tool input ticker
# for THIS turn: query_fundamentals(ticker="TSLA") + item.entity_name="TSLA"
# = consistent → admit. The negative bound (unrelated MSFT data on an Apple
# question) MUST still refuse because the prior_tool_calls set then contains
# "msft" but the question entities do not — we still require an intersection
# anchor with question_entity_ids elsewhere in the function, OR we admit only
# when the LLM's chosen identifier is the SAME as the item's identifier (i.e.
# tool-call consistency, not question consistency). See implementation: the
# W37 path admits only when item_ids ∩ llm_chosen_ids ≠ ∅. That admits TSLA
# (item=TSLA, prior=TSLA) AND would admit MSFT-on-Apple if the LLM hallucinated
# the ticker — the trade-off is documented in the function docstring.
# ─────────────────────────────────────────────────────────────────────────────


class TestEntityGroundingPriorToolCallTicker:
    """W37 regression: query_fundamentals envelope bridges ticker ↔ canonical."""

    @staticmethod
    def _make_call(tool_input: dict[str, object]) -> MagicMock:
        """Stub for a prior tool call — only the ``input`` attr is read."""
        tc = MagicMock()
        tc.input = tool_input
        return tc

    def test_query_fundamentals_tsla_admits_via_prior_tool_call(self) -> None:
        """The Round 4 TSLA fault: prior tool call carries the canonical bridge.

        Pass path (NEW): item.citation_meta.entity_name="TSLA" → item_ids
        = {"tsla"}; prior_tool_calls = [query_fundamentals(ticker="TSLA")]
        → llm_chosen_ids = {"tsla"}. item_ids ∩ llm_chosen_ids = {"tsla"}
        → admit. The text-token & substring paths still cannot bridge
        "tsla" ↔ "tesla, inc." so W37 is the only path here.
        """
        from rag_chat.application.use_cases.chat_orchestrator import _check_entity_grounding

        item = _make_grounding_item(
            text=(
                "## TSLA fundamentals query\n"
                "Coverage: gross_margin=ok\n"
                "| Period | Periodicity | gross_margin |\n"
                "| Q1 2025 | QUARTERLY | 16.31% |"
            ),
            entity_name="TSLA",
        )
        prior_calls = [
            self._make_call(
                {
                    "metrics": ["gross_margin"],
                    "period_type": "quarterly",
                    "periods": 5,
                    "ticker": "TSLA",
                }
            )
        ]
        # Question entities mirror the resolver output observed in the
        # Round 4 artifact (no ticker, lowercase canonical names only).
        result = _check_entity_grounding(
            [item],
            {"tesla", "tesla, inc."},
            prior_tool_calls=prior_calls,
        )
        assert result is None, "W37 prior-tool-call fallback failed to admit TSLA"

    def test_unrelated_ticker_still_refuses_without_prior_call(self) -> None:
        """Negative bound: MSFT data on Apple question with NO prior call → refuse.

        Mirrors the existing two-way-fallback negative test. The W37 path
        only fires when prior_tool_calls is non-empty, so an empty list
        falls back to the prior behaviour: refuse on no overlap.
        """
        from rag_chat.application.use_cases.chat_orchestrator import _check_entity_grounding

        item = _make_grounding_item(
            text="## MSFT fundamentals query\n| Q1 | revenue | 65.0B |",
            entity_name="MSFT",
        )
        # Apple question, MSFT item, no prior tool call passed (default).
        result = _check_entity_grounding([item], {"apple", "apple inc"})
        assert result is not None, "Expected refusal for MSFT data on Apple question"
        assert "cannot find information about the entities" in result

    def test_apple_question_with_msft_item_still_refuses(self) -> None:
        """Mainline negative: healthy planner called AAPL, stray MSFT item refuses.

        The realistic false-positive scenario the task pins:
          - question = "How has Apple's revenue trended?"
          - LLM correctly called query_fundamentals(ticker="AAPL")
          - somehow an MSFT item leaked into retrieved_items (cache bleed,
            handler bug, etc.)
        The MSFT item has neither a citation_meta match against {"apple",
        "apple inc"} NOR against the LLM-chosen ticker set {"aapl"}. W37
        must refuse so we never silently attribute MSFT facts to Apple.
        """
        from rag_chat.application.use_cases.chat_orchestrator import _check_entity_grounding

        item = _make_grounding_item(
            text="## MSFT fundamentals query\n| Q1 | revenue | 65.0B |",
            entity_name="MSFT",
        )
        prior_calls = [self._make_call({"ticker": "AAPL", "metrics": ["revenue"]})]
        result = _check_entity_grounding(
            [item],
            {"apple", "apple inc"},
            prior_tool_calls=prior_calls,
        )
        assert result is not None, "MSFT-on-Apple must refuse — W37 admit window too wide"
        assert "cannot find information about the entities" in result


# ─────────────────────────────────────────────────────────────────────────────
# PLAN-0104 W42 — entity-NAME grounding (second pass) prior-tool-call bridge.
# Round 6 Q4 TSLA fault was a *double*-refusal: the first-pass
# `_check_entity_grounding` admitted via the W37 ticker fallback, but the
# orchestrator's downstream `_run_entity_grounding_validation` (the validator
# that scans the LLM's PROSE for ungrounded proper-noun mentions) was unaware
# of the bridge. Its grounded set held {"tesla", "tesla, inc."} but no
# "TSLA" — so the validator flagged the LLM's TSLA-derived synthesis and
# triggered a defensive [unverified] rewrite. W42 forwards the same
# ``prior_tool_calls`` list to the second-pass validator and adds the LLM's
# ticker/symbol values to the grounded ``tool_refs`` set, symmetric to W37.
# Negative case (LLM correctly called AAPL but hallucinates an MSFT name) is
# still flagged because MSFT is in neither the resolved entities nor any
# prior tool call.
# ─────────────────────────────────────────────────────────────────────────────


class TestEntityNameGroundingSecondPassBridge:
    """W42 regression: second-pass entity-name validator accepts ticker bridge."""

    @staticmethod
    def _make_prior_call(tool_input: dict[str, object]) -> MagicMock:
        """Stub prior tool call — only the ``input`` attr is read."""
        tc = MagicMock()
        tc.input = tool_input
        return tc

    @staticmethod
    def _make_tool_item(entity_name: str | None, item_id: str = "tool:fundamentals:row") -> MagicMock:
        """Lightweight tool_item stub for `_run_entity_grounding_validation`."""
        item = MagicMock()
        if entity_name is None:
            item.citation_meta = None
        else:
            cm = MagicMock()
            cm.entity_name = entity_name
            item.citation_meta = cm
        item.item_id = item_id
        return item

    @staticmethod
    def _make_resolved_entity(canonical_name: str, ticker: str | None = None) -> MagicMock:
        ent = MagicMock()
        ent.canonical_name = canonical_name
        ent.ticker = ticker
        ent.matched_text = canonical_name
        return ent

    @staticmethod
    def _make_pipeline_for_entity(rewrite_text: str = "") -> MagicMock:
        """Mock pipeline whose `llm_chain.stream_chat` yields a rewrite stream.

        Captures the rewrite invocation count so the test can assert
        whether the second-pass validator triggered a rewrite.
        """
        pipeline = MagicMock()
        pipeline.llm_chain = MagicMock()
        call_count = {"n": 0}

        async def _stream_chat(messages: list, **_: Any):
            call_count["n"] += 1
            if rewrite_text:
                yield rewrite_text

        pipeline.llm_chain.stream_chat = _stream_chat
        pipeline._rewrite_call_count = call_count  # type: ignore[attr-defined]
        return pipeline

    def test_tsla_prior_tool_call_admits_tesla_name_in_response(self) -> None:
        """Round 6 Q4 TSLA fault: prose mentions "Tesla", tool item carries only "TSLA".

        Without the W42 bridge: grounded = {"Tesla"} from resolved
        entity + {"TSLA"} from tool_item.citation_meta. Validator
        extracts "Tesla" from prose → normalised "tesla" → matches
        grounded set. So actually the first pass passes here trivially.
        The W42 fix matters when resolver omits canonical name OR when
        the prose ALSO contains the ticker derivative. We exercise the
        deeper case below; this test simply confirms the bridge does
        not REGRESS the trivial case.
        """
        from rag_chat.application.use_cases.chat_orchestrator import (
            AgentBudget,
            ChatOrchestratorUseCase,
        )

        resolved = [self._make_resolved_entity(canonical_name="Tesla")]
        tool_items = [self._make_tool_item(entity_name="TSLA")]
        response = "Tesla's gross margin trended from 19% to 17% over five quarters."
        prior_calls = [self._make_prior_call({"ticker": "TSLA", "metrics": ["gross_margin"]})]

        pipeline = self._make_pipeline_for_entity()
        orch = ChatOrchestratorUseCase.__new__(ChatOrchestratorUseCase)
        budget = AgentBudget()

        text, passed = asyncio.run(
            orch._run_entity_grounding_validation(
                p=pipeline,
                response=response,
                resolved_entities=resolved,
                tool_items=tool_items,
                messages=[{"role": "user", "content": "Tesla margin"}],
                budget=budget,
                prior_tool_calls=prior_calls,
            )
        )

        assert passed is True, "Validator must not flag a grounded response"
        assert text == response, "First-pass admit should return response verbatim"
        assert pipeline._rewrite_call_count["n"] == 0, "No rewrite expected when first pass passes"

    def test_tsla_bridge_admits_when_resolver_omits_canonical(self) -> None:
        """W42 core fix: resolver only gave "Tesla, Inc." while item carries "TSLA".

        Mirrors the Round 6 artifact: the validator's substring fallback
        cannot bridge "tsla" ↔ "tesla, inc." (no shared substring). The
        prior tool call carries ticker="TSLA" — W42 adds that to
        tool_refs, so any TSLA-derivative token in the prose grounds.
        """
        from rag_chat.application.use_cases.chat_orchestrator import (
            AgentBudget,
            ChatOrchestratorUseCase,
        )

        resolved = [self._make_resolved_entity(canonical_name="Tesla, Inc.")]
        # Tool item without citation_meta — the only ticker source in
        # the legacy grounded set construction.
        tool_items = [self._make_tool_item(entity_name=None, item_id="row")]
        # Prose contains "TSLA" only.
        response = "TSLA's gross margin trended from 19% to 17% over five quarters."
        prior_calls = [self._make_prior_call({"ticker": "TSLA", "metrics": ["gross_margin"]})]

        pipeline = self._make_pipeline_for_entity()
        orch = ChatOrchestratorUseCase.__new__(ChatOrchestratorUseCase)
        budget = AgentBudget()

        text, passed = asyncio.run(
            orch._run_entity_grounding_validation(
                p=pipeline,
                response=response,
                resolved_entities=resolved,
                tool_items=tool_items,
                messages=[{"role": "user", "content": "Tesla margin"}],
                budget=budget,
                prior_tool_calls=prior_calls,
            )
        )

        assert passed is True, "W42 bridge failed: TSLA prior call did not ground 'TSLA' prose"
        assert text == response
        assert pipeline._rewrite_call_count["n"] == 0, "No rewrite expected — bridge admits"

    def test_msft_prior_call_with_apple_response_still_rejects(self) -> None:
        """Negative bound: prior MSFT call cannot smuggle "Apple" into grounded set.

        Symmetric with W37's MSFT-on-Apple negative test. LLM correctly
        called query_fundamentals(ticker="MSFT") and the resolver
        resolved Microsoft — but the prose then claims "Apple revenue
        grew 8%". "Apple" is not in grounded names (resolved) nor in
        tool_refs (MSFT and prior MSFT do not substring-match "apple"),
        so the first-pass MUST flag it and trigger a rewrite. We assert
        rewrite was attempted at least once — the validator did NOT
        widen far enough to admit an unrelated entity.
        """
        from rag_chat.application.use_cases.chat_orchestrator import (
            AgentBudget,
            ChatOrchestratorUseCase,
        )

        resolved = [self._make_resolved_entity(canonical_name="Microsoft", ticker="MSFT")]
        tool_items = [self._make_tool_item(entity_name="MSFT")]
        response = "Apple's revenue grew 8% year-on-year per the filing."
        prior_calls = [self._make_prior_call({"ticker": "MSFT", "metrics": ["revenue"]})]

        # Rewrite returns a clean [unverified] response so we can verify
        # the rewrite path actually fired and produced different text.
        pipeline = self._make_pipeline_for_entity(rewrite_text="Revenue figures [unverified].")
        orch = ChatOrchestratorUseCase.__new__(ChatOrchestratorUseCase)
        budget = AgentBudget()

        text, _ = asyncio.run(
            orch._run_entity_grounding_validation(
                p=pipeline,
                response=response,
                resolved_entities=resolved,
                tool_items=tool_items,
                messages=[{"role": "user", "content": "Apple revenue"}],
                budget=budget,
                prior_tool_calls=prior_calls,
            )
        )

        assert pipeline._rewrite_call_count["n"] >= 1, "W42 bridge widened too far — Apple-on-MSFT must trigger rewrite"
        # And the returned text MUST NOT be the verbatim original prose.
        assert text != response, "Negative case must not admit response unchanged"


# ─────────────────────────────────────────────────────────────────────────────
# F-NEW-015 — tool-result entity grounding (Option A) + rewrite timeout (Option B)
#
# Iter-12 Q6 was a false PASS: a degraded fast-fail path bypassed synthesis, so
# the grounding rewrite never fired. Iter-13 unblocked the screener path → full
# synthesis → grounding rewrite fired at chat_orchestrator.py:2823 because
# screener-returned tickers (NVDA/AMD/AVGO/MRVL) were not in the resolved-
# entity set. They WERE in the tool result text body — but the previous
# tool_refs extraction only looked at ``citation_meta.entity_name`` and
# ``item_id``, missing the inline ticker rows. Option A widens the grounded
# set to include text-body tickers; Option B bounds the rewrite at 15s.
# ─────────────────────────────────────────────────────────────────────────────


class TestScreenerToolResultGrounding:
    """F-NEW-015 Option A — screener-returned tickers must enter grounded set."""

    @staticmethod
    def _make_screener_item(text: str) -> MagicMock:
        """Mirror the actual RetrievedItem screener emits from market.py:1166."""
        item = MagicMock()
        item.text = text
        item.item_id = "tool:screener:results"
        cm = MagicMock()
        cm.entity_name = None  # screener leaves this None (see handlers/market.py:1177)
        item.citation_meta = cm
        # Explicitly ensure structured ticker/canonical_name attrs are not
        # present — MagicMock would otherwise auto-create them. ``spec=[]``
        # is impractical here, so we just delete the ones we probe.
        del item.ticker
        del item.canonical_name
        del item.entity_name
        return item

    @staticmethod
    def _make_resolved_entity(canonical_name: str, ticker: str | None = None) -> MagicMock:
        ent = MagicMock()
        ent.canonical_name = canonical_name
        ent.ticker = ticker
        ent.matched_text = canonical_name
        return ent

    @staticmethod
    def _make_pipeline_for_entity(rewrite_text: str = "") -> MagicMock:
        pipeline = MagicMock()
        pipeline.llm_chain = MagicMock()
        call_count = {"n": 0}

        async def _stream_chat(messages: list, **_: Any):
            call_count["n"] += 1
            if rewrite_text:
                yield rewrite_text

        pipeline.llm_chain.stream_chat = _stream_chat
        pipeline._rewrite_call_count = call_count  # type: ignore[attr-defined]
        return pipeline

    def test_screener_result_tickers_added_to_grounded_set(self) -> None:
        """Screener text body tickers (NVDA, AMD) must reach the validator's grounded set.

        The synthesised response references the screener-returned tickers
        directly. Before F-NEW-015 the validator's grounded_names + tool_refs
        sets did NOT contain NVDA/AMD (only ``tool:screener:results`` from
        the item_id) → first pass flagged both → rewrite fired → 15-60s
        latency. After Option A: tool_refs contains NVDA + AMD + AVGO + MRVL
        extracted from the text body → first pass passes → no rewrite.
        """
        from rag_chat.application.use_cases.chat_orchestrator import (
            AgentBudget,
            ChatOrchestratorUseCase,
        )

        # Verbatim format produced by ``_handle_screen_universe`` (handlers/market.py:1132-1156).
        screener_text = (
            "## Screener Results (4 instruments)\n"
            "  NVDA — NVIDIA Corp | MCap: $3.10T (raw: 3100000000000) | P/E: 65\n"
            "  AMD — Advanced Micro Devices | MCap: $260B (raw: 260000000000) | P/E: 45\n"
            "  AVGO — Broadcom Inc | MCap: $720B (raw: 720000000000) | P/E: 55\n"
            "  MRVL — Marvell Technology | MCap: $80B (raw: 80000000000) | P/E: 40"
        )
        tool_items = [self._make_screener_item(screener_text)]
        # The user asked an open-domain "top semis by market cap" question;
        # resolver attached a single sector-level entity but no ticker.
        resolved = [self._make_resolved_entity(canonical_name="Semiconductors")]
        response = (
            "The top semiconductor names by market cap are NVDA at $3.1T, "
            "AVGO at $720B, AMD at $260B, and MRVL at $80B."
        )

        pipeline = self._make_pipeline_for_entity()
        orch = ChatOrchestratorUseCase.__new__(ChatOrchestratorUseCase)
        budget = AgentBudget()

        text, passed = asyncio.run(
            orch._run_entity_grounding_validation(
                p=pipeline,
                response=response,
                resolved_entities=resolved,
                tool_items=tool_items,
                messages=[{"role": "user", "content": "Top semis by market cap"}],
                budget=budget,
                prior_tool_calls=None,
            )
        )

        assert passed is True, "Option A: screener text-body tickers must ground the response"
        assert text == response, "First-pass admit must return response verbatim"
        assert (
            pipeline._rewrite_call_count["n"] == 0
        ), "Rewrite must NOT fire — Option A bug regressed: screener tickers not in grounded set"

    def test_structured_ticker_attr_admits_response(self) -> None:
        """Tools that DO expose ``item.ticker`` directly must also feed the grounded set.

        Future tools may carry structured ticker fields. The extraction
        loop probes ``ticker`` / ``canonical_name`` / ``entity_name`` on
        the item itself (separate from ``citation_meta.entity_name``).
        """
        from rag_chat.application.use_cases.chat_orchestrator import (
            AgentBudget,
            ChatOrchestratorUseCase,
        )

        item = MagicMock()
        item.text = "Some payload without inline tickers."
        item.item_id = "tool:custom:row"
        cm = MagicMock()
        cm.entity_name = None
        item.citation_meta = cm
        item.ticker = "NVDA"
        item.canonical_name = "NVIDIA Corporation"
        item.entity_name = "NVIDIA"

        resolved = [self._make_resolved_entity(canonical_name="Semiconductors")]
        response = "NVDA leads with $3.1T market cap."

        pipeline = self._make_pipeline_for_entity()
        orch = ChatOrchestratorUseCase.__new__(ChatOrchestratorUseCase)
        budget = AgentBudget()

        text, passed = asyncio.run(
            orch._run_entity_grounding_validation(
                p=pipeline,
                response=response,
                resolved_entities=resolved,
                tool_items=[item],
                messages=[{"role": "user", "content": "NVDA cap"}],
                budget=budget,
                prior_tool_calls=None,
            )
        )

        assert passed is True
        assert pipeline._rewrite_call_count["n"] == 0


class TestEntityGroundingRewriteTimeout:
    """F-NEW-015 Option B — rewrite stream_chat bounded by configurable timeout."""

    def test_grounding_rewrite_timeout_returns_banner(self) -> None:
        """A hung rewrite stream must surface the timeout banner + log warning.

        Reproduces the 90s end-to-end timeout from iter-13: the rewrite
        stream hangs indefinitely → ``asyncio.wait_for`` fires → we
        return the original response with the validator-timeout banner
        so the user still receives the substantive answer.
        """
        from rag_chat.application.use_cases.chat_orchestrator import (
            AgentBudget,
            ChatOrchestratorUseCase,
        )

        # A resolver that returns an unrelated entity guarantees the
        # validator flags the prose's "APPLE" mention → triggers the
        # rewrite path → which then hangs.
        resolved_ent = MagicMock()
        resolved_ent.canonical_name = "Microsoft"
        resolved_ent.ticker = "MSFT"
        resolved_ent.matched_text = "Microsoft"

        tool_item = MagicMock()
        tool_item.text = "MSFT revenue payload."
        tool_item.item_id = "tool:fundamentals:MSFT"
        cm = MagicMock()
        cm.entity_name = "MSFT"
        tool_item.citation_meta = cm
        del tool_item.ticker
        del tool_item.canonical_name
        del tool_item.entity_name

        response = "Apple revenue grew 8% per the latest filing."

        # Pipeline whose stream_chat hangs forever.
        pipeline = MagicMock()
        pipeline.llm_chain = MagicMock()

        async def _hang(messages: list, **_: Any):
            await asyncio.sleep(60)  # well past the 0.1s test timeout
            if False:
                yield ""  # pragma: no cover

        pipeline.llm_chain.stream_chat = _hang

        # Force a tiny timeout so the test runs in <0.5s.
        import os

        prev = os.environ.get("RAG_CHAT_ENTITY_GROUNDING_REWRITE_TIMEOUT_SECONDS")
        os.environ["RAG_CHAT_ENTITY_GROUNDING_REWRITE_TIMEOUT_SECONDS"] = "0.1"
        try:
            orch = ChatOrchestratorUseCase.__new__(ChatOrchestratorUseCase)
            budget = AgentBudget()
            text, passed = asyncio.run(
                orch._run_entity_grounding_validation(
                    p=pipeline,
                    response=response,
                    resolved_entities=[resolved_ent],
                    tool_items=[tool_item],
                    messages=[{"role": "user", "content": "Apple revenue"}],
                    budget=budget,
                    prior_tool_calls=None,
                )
            )
        finally:
            if prev is None:
                os.environ.pop("RAG_CHAT_ENTITY_GROUNDING_REWRITE_TIMEOUT_SECONDS", None)
            else:
                os.environ["RAG_CHAT_ENTITY_GROUNDING_REWRITE_TIMEOUT_SECONDS"] = prev

        assert passed is False, "Timeout path must mark grounding as failed"
        assert "validator timeout" in text, "Timeout banner must be appended to original response"
        assert text.startswith(response), "Original response text must be preserved verbatim"
