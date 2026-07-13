"""PLAN-0117 (attribution) — grounding-rewrite spend must reach thread + user.

Regression tests for the cost-ATTRIBUTION gap documented in
``docs/audits/2026-07-03-chat-llm-cost-untracked.md``: the four grounding /
degraded-synthesis ``stream_chat`` rewrite calls previously omitted
``thread_id`` / ``user_id`` (so the per-thread ``chat_threads.estimated_cost_usd``
bump and the per-user PRD-0118 quota were silently undercounting every
grounding-repaired turn) and hard-coded ``call_site="synthesis"`` (so repair
spend was indistinguishable from the real synthesis turn in the ledger).

These tests drive each grounding method to its rewrite ``stream_chat`` call with
a SPY stream that captures the kwargs, then assert the identity + ``call_site``
are forwarded. Plus an adapter-level test that ``call_site`` flows into
``_record_cost`` (default ``"synthesis"`` preserved — forward-compatible).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest

pytestmark = pytest.mark.unit

_THREAD_ID = UUID("00000000-0000-0000-0000-0000000000dd")
_USER_ID = UUID("00000000-0000-0000-0000-0000000000cc")


# ── Fakes (mirror the small subset used by the validators) ────────────────────


@dataclass
class _FakeUnsupported:
    value: float
    field_kind: Any  # FieldKind enum
    tolerance_used: float = 0.05
    closest_tool_value: float | None = None
    snippet: str = "snippet"


@dataclass
class _FakeResult:
    passed: bool
    unsupported: tuple[_FakeUnsupported, ...] = ()


@dataclass
class _FakeEntityUnsupported:
    name: str
    kind: Any  # EntityKind enum


@dataclass
class _FakeEntityResult:
    passed: bool
    unsupported: tuple[_FakeEntityUnsupported, ...] = ()


def _make_orchestrator() -> Any:
    from rag_chat.application.use_cases.chat_orchestrator import ChatOrchestratorUseCase

    return ChatOrchestratorUseCase(pipeline=MagicMock(), tool_executor_factory=MagicMock())


def _spy_pipeline(rewrite_text: str) -> tuple[MagicMock, dict[str, Any]]:
    """Pipeline whose ``llm_chain.stream_chat`` records its kwargs into ``captured``."""
    p = MagicMock()
    p.llm_chain = MagicMock()
    captured: dict[str, Any] = {}

    async def _stream(_messages: Any, **kwargs: Any):
        captured.update(kwargs)
        yield rewrite_text

    p.llm_chain.stream_chat = _stream
    return p, captured


def _make_budget() -> Any:
    b = MagicMock()
    b.max_tokens_final = 256
    return b


def _nonempty_pool() -> list[Any]:
    """A tool-item pool with one structured numeric value (defeats the empty-pool gate)."""
    from rag_chat.application.services.numeric_grounding import FieldKind

    item = MagicMock()
    item.text = "tool row"
    item.value = 181.5e9
    item.field_kind = FieldKind.REVENUE
    item.citation_meta = None
    item.item_id = "tool:fundamentals:AAPL"
    return [item]


# ── Numeric grounding rewrite (chat_orchestrator.py:~5361) ────────────────────


class TestNumericGroundingRewriteAttribution:
    def test_forwards_thread_user_and_call_site(self) -> None:
        from rag_chat.application.services.numeric_grounding import FieldKind

        # Mixed unsupported set (does NOT trip the >=80% small-revenue guard) so
        # the rewrite branch runs. First fail → rewrite → second pass.
        unsupported = (
            _FakeUnsupported(value=181.5e9, field_kind=FieldKind.REVENUE),
            _FakeUnsupported(value=7.14, field_kind=FieldKind.EPS),
        )
        first = _FakeResult(passed=False, unsupported=unsupported)
        second = _FakeResult(passed=True)

        orch = _make_orchestrator()
        pipeline, captured = _spy_pipeline(
            rewrite_text="Apple Q3 revenue was $181.5B [1] and EPS $7.14 [2] with strong growth.",
        )

        with patch(
            "rag_chat.application.services.numeric_grounding.NumericGroundingValidator",
        ) as v_cls:
            v_cls.return_value.validate.side_effect = [first, second]
            asyncio.run(
                orch._run_grounding_validation(
                    p=pipeline,
                    response="Apple Q3 revenue was $181.5B and EPS $7.14 with strong growth.",
                    tool_items=_nonempty_pool(),
                    messages=[],
                    budget=_make_budget(),
                    thread_id=_THREAD_ID,
                    user_id=_USER_ID,
                )
            )

        assert captured["thread_id"] == _THREAD_ID
        assert captured["user_id"] == _USER_ID
        assert captured["call_site"] == "grounding_rewrite"


# ── Combined grounding rewrite (chat_orchestrator.py:~4987) ───────────────────


class TestCombinedGroundingRewriteAttribution:
    def test_forwards_thread_user_and_call_site(self) -> None:
        from rag_chat.application.services.numeric_grounding import FieldKind

        unsupported = (
            _FakeUnsupported(value=181.5e9, field_kind=FieldKind.REVENUE),
            _FakeUnsupported(value=7.14, field_kind=FieldKind.EPS),
        )
        first = _FakeResult(passed=False, unsupported=unsupported)
        second = _FakeResult(passed=True)

        orch = _make_orchestrator()
        pipeline, captured = _spy_pipeline(
            rewrite_text="Apple Q3 revenue was $181.5B [1] and EPS $7.14 [2] with strong growth.",
        )

        with patch(
            "rag_chat.application.services.numeric_grounding.NumericGroundingValidator",
        ) as v_cls:
            v_cls.return_value.validate.side_effect = [first, second]
            asyncio.run(
                orch._run_combined_grounding_validation(
                    p=pipeline,
                    response="Apple Q3 revenue was $181.5B and EPS $7.14 with strong growth.",
                    tool_items=_nonempty_pool(),
                    resolved_entities=[],
                    messages=[],
                    budget=_make_budget(),
                    # Entity pass off — isolate the numeric rewrite trigger.
                    run_entity_pass=False,
                    thread_id=_THREAD_ID,
                    user_id=_USER_ID,
                )
            )

        assert captured["thread_id"] == _THREAD_ID
        assert captured["user_id"] == _USER_ID
        assert captured["call_site"] == "grounding_rewrite"


# ── Entity grounding rewrite (chat_orchestrator.py:~5775) ─────────────────────


class TestEntityGroundingRewriteAttribution:
    def test_forwards_thread_user_and_call_site(self) -> None:
        from rag_chat.application.services.entity_name_grounding import NameKind

        first = _FakeEntityResult(
            passed=False,
            unsupported=(_FakeEntityUnsupported(name="Acme Corp", kind=NameKind.COMPANY),),
        )
        second = _FakeEntityResult(passed=True)

        orch = _make_orchestrator()
        pipeline, captured = _spy_pipeline(rewrite_text="A grounded rewrite that names no phantom company.")

        with patch(
            "rag_chat.application.services.entity_name_grounding.EntityNameGroundingValidator",
        ) as v_cls:
            v_cls.return_value.validate.side_effect = [first, second]
            asyncio.run(
                orch._run_entity_grounding_validation(
                    p=pipeline,
                    response="Acme Corp raised guidance.",
                    resolved_entities=[],
                    tool_items=[],
                    messages=[],
                    budget=_make_budget(),
                    allow_rewrite=True,
                    thread_id=_THREAD_ID,
                    user_id=_USER_ID,
                )
            )

        assert captured["thread_id"] == _THREAD_ID
        assert captured["user_id"] == _USER_ID
        assert captured["call_site"] == "grounding_rewrite"


# ── Adapter: call_site plumbing into _record_cost (deepinfra_adapter.py:~624) ──


class TestAdapterCallSitePlumbing:
    def _adapter(self) -> Any:
        from rag_chat.infrastructure.llm.deepinfra_adapter import DeepInfraCompletionAdapter

        return DeepInfraCompletionAdapter(api_key="k", http_client=AsyncMock(), cost_recorder=AsyncMock())

    def test_stream_chat_forwards_call_site_to_record_cost(self) -> None:
        adapter = self._adapter()

        async def _one_model(*_a: Any, **_kw: Any):
            yield "token"

        async def _run() -> None:
            with (
                patch.object(adapter, "_stream_chat_one_model", _one_model),
                patch.object(adapter, "_record_cost", new=AsyncMock()) as rec,
            ):
                async for _ in adapter.stream_chat(
                    [{"role": "user", "content": "hi"}],
                    thread_id=_THREAD_ID,
                    user_id=_USER_ID,
                    call_site="grounding_rewrite",
                ):
                    pass
                rec.assert_awaited_once()
                assert rec.await_args.kwargs["call_site"] == "grounding_rewrite"
                assert rec.await_args.kwargs["thread_id"] == _THREAD_ID
                assert rec.await_args.kwargs["user_id"] == _USER_ID

        asyncio.run(_run())

    def test_stream_chat_defaults_call_site_to_synthesis(self) -> None:
        """Existing callers (no call_site) still record ``"synthesis"`` (forward-compat)."""
        adapter = self._adapter()

        async def _one_model(*_a: Any, **_kw: Any):
            yield "token"

        async def _run() -> None:
            with (
                patch.object(adapter, "_stream_chat_one_model", _one_model),
                patch.object(adapter, "_record_cost", new=AsyncMock()) as rec,
            ):
                async for _ in adapter.stream_chat([{"role": "user", "content": "hi"}]):
                    pass
                assert rec.await_args.kwargs["call_site"] == "synthesis"

        asyncio.run(_run())
