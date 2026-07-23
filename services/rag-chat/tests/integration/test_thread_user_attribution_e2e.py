"""End-to-end regression test — chat_thread_id/user_id attribution (2026-07-23 audit).

``docs/audits/2026-07-23-three-vertical-prod-investigation.md`` (LLM-cost vertical,
item 2) found ``llm_usage_log.chat_thread_id`` NULL on 100% of rows over a 7-day
prod window, blocking all per-thread/per-user cost attribution. The 2026-07-03
audit (``docs/audits/2026-07-03-chat-llm-cost-untracked.md``) had already
identified and (per its own account) fixed the *forwarding* of ``thread_id``/
``user_id`` into every ``stream_chat``/``chat_with_tools`` call inside
``ChatOrchestratorUseCase`` — and indeed, by 2026-07-23, every one of those call
sites DOES forward ``request.thread_id``/``request.user_id`` correctly.

The REAL, still-live bug: ``request.thread_id`` itself is ``None`` for the
ENTIRE turn on every new conversation (the client has no thread_id to send
yet). Before this fix, ``ChatOrchestratorUseCase._execute_streaming_inner``
only resolved a concrete thread_id at the very END of the turn — in the
persist step (``thread_id = request.thread_id or _new_thread_id()``) — which
runs AFTER every LLM call (planning/synthesis/grounding-rewrite) has already
recorded its ``llm_usage_log`` row with ``chat_thread_id=NULL``. Since a
first-turn-of-a-new-conversation is the overwhelming majority of chat traffic,
this explained the 100% NULL finding.

The fix (``chat_orchestrator.py`` ``execute_streaming``) resolves the
EFFECTIVE thread_id ONCE, before any LLM call, and reuses it for every
cost-attribution call site AND the final persisted thread row.

This test proves the fix end-to-end against a REAL Postgres database (schema
created via the actual rag-chat Alembic migrations — mirrors the
docker-compose local ``rag_db`` schema) and a REAL ``PrometheusAndDbCostRecorder``
+ ``RagChatUsageLogRepository`` write path — i.e. it performs a genuine
``INSERT INTO llm_usage_log`` and then queries the row back, rather than
asserting on a mocked SQL shape. Only the outbound LLM provider HTTP call is
faked (there is no live DeepInfra dependency in CI); everything from the
orchestrator's identity-resolution logic through the real cost-recorder and
real repository SQL into a real database row is exercised as production code.

Drives THREE distinct call sites in one turn, matching the audit's language
("planner + synthesizer + grounding-rewrite paths"):
  1. planner       — ``chat_with_tools`` (call_site="tool_loop_iter"), x2
     (one tool-call iteration + one direct-answer iteration to end the loop)
  2. synthesizer    — ``stream_chat`` (call_site="synthesis")
  3. grounding-rewrite — ``stream_chat`` (call_site="grounding_rewrite"), forced
     by making the NumericGroundingValidator fail once then pass on rewrite
     (same deterministic technique already proven in
     ``tests/unit/use_cases/test_chat_orchestrator_cost_attribution.py``).

Requires Docker (testcontainers Postgres) — skips gracefully if unavailable,
matching the rest of the rag-chat integration suite's convention
(see ``tests/integration/test_migration_0010_cost_source_user_id.py``).
"""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import AsyncGenerator, Iterator
from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

pytestmark = pytest.mark.integration

_ALEMBIC_ENV_VAR = "ALEMBIC_URL"


@dataclass
class _Unsupported:
    """Real dataclass double for ``UnsupportedNumber`` — see the long comment at
    its use site (below) for why a MagicMock here would silently break the test.
    """

    value: float
    field_kind: Any  # numeric_grounding.FieldKind
    tolerance_used: float = 0.05
    closest_tool_value: float | None = None
    snippet: str = "snippet"


# ── Override the shared docker-compose-DB autouse fixture from conftest.py ────
# tests/integration/conftest.py's ``_clean_tables(db_engine)`` targets the
# docker-compose ``rag_db`` at RAG_CHAT_E2E_DATABASE_URL (localhost:55433) and
# skips the whole test when that instance isn't reachable. This module uses
# its OWN throwaway testcontainers Postgres (fresh schema per module, real
# Alembic migrations) instead, so it must not depend on — or be skipped by —
# the shared docker-compose instance being up.
@pytest.fixture(autouse=True)
async def _clean_tables() -> AsyncGenerator[None, None]:  # type: ignore[override]
    """No-op override: this module manages its own testcontainers Postgres."""
    yield


# ── Postgres fixture (real schema via the actual rag-chat Alembic migrations) ──


@pytest.fixture(scope="module")
def _pg_url() -> Iterator[str]:
    pytest.importorskip("testcontainers", reason="testcontainers not installed")
    pytest.importorskip("asyncpg", reason="asyncpg not installed")
    from testcontainers.postgres import PostgresContainer  # type: ignore[import-not-found]

    with PostgresContainer("postgres:16-alpine") as pg:
        yield pg.get_connection_url().replace("psycopg2", "asyncpg")


def _service_dir() -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def _run_alembic_upgrade_head(url: str) -> None:
    alembic_bin = shutil.which("alembic")
    if not alembic_bin:  # pragma: no cover - env guard
        pytest.skip("alembic not on PATH")
    result = subprocess.run(
        [alembic_bin, "upgrade", "head"],
        cwd=_service_dir(),
        capture_output=True,
        text=True,
        env={**os.environ, _ALEMBIC_ENV_VAR: url},
    )
    if result.returncode != 0:  # pragma: no cover - surfaced as test failure
        raise RuntimeError(f"alembic upgrade head failed:\n{result.stdout}\n{result.stderr}")


@pytest.fixture(scope="module")
def _migrated_pg_url(_pg_url: str) -> str:
    """Apply every real rag-chat migration (creates ``threads`` + ``llm_usage_log``)."""
    _run_alembic_upgrade_head(_pg_url)
    return _pg_url


@pytest.fixture
async def _session_factory(_migrated_pg_url: str) -> AsyncGenerator[Any, None]:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    engine = create_async_engine(_migrated_pg_url)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        yield factory
    finally:
        await engine.dispose()


@pytest.fixture
async def _cost_recorder(_session_factory: Any) -> Any:
    from rag_chat.infrastructure.llm.cost_recorder import PrometheusAndDbCostRecorder

    # WHY not the app's real DeepInfraCompletionAdapter: that would require
    # either a live DeepInfra call or mocking deep HTTP internals. The
    # PrometheusAndDbCostRecorder (the ``CostRecorder`` port implementation
    # every adapter delegates to for the actual DB write) IS the real,
    # unmocked production code under test here — this is the exact class
    # wired into ``app.py`` in production.
    return PrometheusAndDbCostRecorder(write_session_factory=_session_factory)


# ── Fakes: only the outbound LLM provider call is faked ───────────────────────


def _tool_call_response() -> Any:
    """First planner turn: LLM requests one tool call."""
    from rag_chat.application.pipeline.tool_executor import ToolUseBlock as LocalToolUseBlock

    block = LocalToolUseBlock(
        name="get_fundamentals_history",
        input={"ticker": "AAPL"},
        tool_use_id="call-attrib-001",
    )
    response = MagicMock()
    response.tool_calls = [block]
    response.text = None
    response.finish_reason = "tool_calls"
    return response


def _direct_answer_response() -> Any:
    """Second planner turn: LLM stops requesting tools — loop breaks to synthesis."""
    response = MagicMock()
    response.tool_calls = []
    response.text = None
    response.finish_reason = "stop"
    return response


def _fundamentals_tool_item() -> Any:
    """A numeric tool result — same shape as the proven-working unit-test fixture
    (``tests/unit/use_cases/test_chat_orchestrator_cost_attribution.py::_nonempty_pool``)
    so the real grounding-validation call path (phantom-citation / empty-pool
    guards) reaches the (mocked) ``NumericGroundingValidator`` instead of
    short-circuiting before it.
    """
    from rag_chat.application.services.numeric_grounding import FieldKind

    item = MagicMock()
    item.text = "Apple Q3 revenue was $181.5B."
    item.value = 181.5e9
    item.field_kind = FieldKind.REVENUE
    item.citation_meta = None
    item.item_id = "tool:fundamentals:AAPL"
    return item


class _RecordingFakeLlmChain:
    """Drop-in ``llm_chain`` replacement that performs REAL cost recording.

    Mirrors exactly what the production adapters (``DeepInfraCompletionAdapter``
    et al.) do at the end of ``chat_with_tools``/``stream_chat``: call
    ``self._cost_recorder.record(thread_id=..., user_id=..., ...)`` with
    whatever identity kwargs the ORCHESTRATOR forwarded. Only the LLM
    provider's HTTP round-trip is faked; the cost-attribution write is 100%
    real production code (``PrometheusAndDbCostRecorder`` -> repository ->
    Postgres).

    ``captured`` accumulates every ``(call_site, thread_id, user_id)`` tuple
    seen — the test asserts on this AND independently re-queries the DB row
    to confirm the value that was actually persisted.
    """

    def __init__(self, cost_recorder: Any) -> None:
        self._cost_recorder = cost_recorder
        self.last_provider_name = "test_provider"
        # ``_resolve_model_id`` (chat_orchestrator.py) walks the real
        # ``LLMProviderChain._providers`` list to recover the active model_id
        # for metrics — an empty list makes it fall back to "" harmlessly.
        self._providers: list[Any] = []
        self._planning_calls = 0
        self._stream_calls = 0
        self.captured: list[tuple[str, UUID | None, UUID | None]] = []

    async def chat_with_tools(self, _messages: Any, **kwargs: Any) -> Any:
        call_site = "tool_loop_iter"
        self.captured.append((call_site, kwargs.get("thread_id"), kwargs.get("user_id")))
        await self._cost_recorder.record(
            thread_id=kwargs.get("thread_id"),
            user_id=kwargs.get("user_id"),
            model_id=kwargs.get("model") or "test-planner-model",
            tokens_in=20,
            tokens_out=10,
            call_site=call_site,
        )
        self._planning_calls += 1
        return _tool_call_response() if self._planning_calls == 1 else _direct_answer_response()

    async def stream_chat(self, _messages: Any, **kwargs: Any) -> AsyncGenerator[str, None]:
        call_site = kwargs.get("call_site", "synthesis")
        self.captured.append((call_site, kwargs.get("thread_id"), kwargs.get("user_id")))
        await self._cost_recorder.record(
            thread_id=kwargs.get("thread_id"),
            user_id=kwargs.get("user_id"),
            model_id=kwargs.get("model") or "test-synthesis-model",
            tokens_in=30,
            tokens_out=15,
            call_site=call_site,
        )
        self._stream_calls += 1
        # First stream_chat call is the main synthesis turn — deliberately
        # phrased with a number the (mocked) numeric-grounding validator will
        # flag as unsupported on its first pass, forcing the grounding-rewrite
        # branch (third distinct call_site) to fire on the SAME turn.
        text = (
            "Apple Q3 revenue was $181.5B and EPS $7.14 with strong growth."
            if self._stream_calls == 1
            else "Apple Q3 revenue was $181.5B [1] and EPS $7.14 [2] with strong growth."
        )
        yield text


def _build_pipeline(cost_recorder: Any) -> tuple[Any, _RecordingFakeLlmChain]:
    """Heavily mocked ``ChatPipeline`` (mirrors ``tests/integration/test_tool_use_orchestrator.py``
    ``_build_pipeline_mock``) with the real cost-recording ``_RecordingFakeLlmChain`` swapped in.
    """
    pipeline = MagicMock()
    pipeline.validate_input = AsyncMock(side_effect=lambda msg: msg)
    pipeline.check_cache = AsyncMock(return_value=None)
    pipeline.check_rate_limit = AsyncMock(return_value=None)
    pipeline.load_history = AsyncMock(return_value=[])
    pipeline.resolve_entities = AsyncMock(return_value=[])
    pipeline.rerank_items = AsyncMock(side_effect=lambda _query, items: items)
    pipeline.build_prompt = MagicMock(return_value=("Test system prompt", [], "Context block from tools"))
    # Return an EMPTY citation list regardless of input (mirrors
    # tests/integration/test_tool_use_orchestrator.py's ``_build_pipeline_mock``)
    # — the real ``_renumber_citations_dense`` post-step expects genuine
    # ``Citation`` dataclass instances, not the MagicMock items our fake
    # tool executor returns.
    pipeline.process_output = MagicMock(side_effect=lambda text, _citations: (text, []))
    pipeline.persist_chat = AsyncMock(return_value=(uuid4(), uuid4()))
    pipeline.write_completion_cache = AsyncMock(return_value=None)
    pipeline.persistence = MagicMock()
    pipeline.persistence.save_interaction = AsyncMock(return_value=None)

    llm_chain = _RecordingFakeLlmChain(cost_recorder)
    pipeline.llm_chain = llm_chain

    from rag_chat.application.pipeline.sse_emitter import SSEEmitter

    pipeline.emitter = SSEEmitter()

    return pipeline, llm_chain


def _build_tool_executor_factory(tool_result: Any) -> Any:
    executor = MagicMock()
    executor.execute = AsyncMock(return_value=tool_result)

    async def _execute_all(tool_calls: Any) -> list[Any]:
        return [await executor.execute(tc) for tc in tool_calls]

    executor.execute_all = AsyncMock(side_effect=_execute_all)

    registry = MagicMock()
    registry.to_system_prompt_section = MagicMock(return_value="[Tool manifest]")
    registry.to_tool_definitions = MagicMock(return_value=[])
    executor._registry = registry

    factory = MagicMock()
    factory.for_request = MagicMock(return_value=executor)
    return factory


async def _run_new_conversation_turn(cost_recorder: Any, user_id: UUID) -> _RecordingFakeLlmChain:
    """Drive one full chat turn for a BRAND-NEW conversation (thread_id=None) —
    the exact scenario the 2026-07-23 audit found 100% NULL on.
    """
    from rag_chat.application.services.numeric_grounding import FieldKind
    from rag_chat.application.use_cases.chat_orchestrator import ChatOrchestratorUseCase
    from rag_chat.domain.entities.chat import ChatContext, ChatRequest

    pipeline, llm_chain = _build_pipeline(cost_recorder)
    factory = _build_tool_executor_factory(_fundamentals_tool_item())

    request = ChatRequest(
        message="What was Apple's Q3 revenue and EPS?",
        context=ChatContext(entity_ids=(), date_range=None),
        tenant_id=uuid4(),
        user_id=user_id,
        thread_id=None,  # <-- new conversation: this is what used to poison every cost row
    )

    uow = AsyncMock()
    uow.__aenter__ = AsyncMock(return_value=uow)
    uow.__aexit__ = AsyncMock(return_value=None)
    uow.commit = AsyncMock()
    uow.rollback = AsyncMock()

    orchestrator = ChatOrchestratorUseCase(pipeline=pipeline, tool_executor_factory=factory)

    # Force the numeric-grounding validator to fail once (triggering the
    # grounding-rewrite stream_chat call) then pass on the rewrite — the same
    # deterministic technique proven in
    # tests/unit/use_cases/test_chat_orchestrator_cost_attribution.py. IMPORTANT:
    # ``unsupported`` items must be real dataclass instances, NOT MagicMock —
    # ``material_unsupported_numbers()`` (real, unmocked code) does
    # ``getattr(u, "hedged_or_derived", False)``, and a MagicMock auto-vivifies
    # ANY attribute access (never falling through to the ``False`` default),
    # which would make every "unsupported" number look hedged/derived and
    # silently skip the rewrite trigger entirely.
    with patch(
        "rag_chat.application.services.numeric_grounding.NumericGroundingValidator",
    ) as v_cls:
        first = MagicMock(passed=False, unsupported=(_Unsupported(value=181.5e9, field_kind=FieldKind.REVENUE),))
        second = MagicMock(passed=True, unsupported=())
        v_cls.return_value.validate.side_effect = [first, second]

        events = []
        async for event in orchestrator.execute_streaming(request, uow):
            events.append(event)

    assert events, "orchestrator produced no SSE events — turn did not run"
    return llm_chain


# ── The test ───────────────────────────────────────────────────────────────────


async def test_new_conversation_turn_writes_non_null_thread_and_user_id(
    _cost_recorder: Any,
    _session_factory: Any,
) -> None:
    """Regression test for the 2026-07-23 audit's ``chat_thread_id`` 100%-NULL finding.

    Drives one full turn of a BRAND-NEW conversation (``thread_id=None`` at the
    API boundary, the dominant real-world case) through
    ``ChatOrchestratorUseCase.execute_streaming`` — exercising the planner
    (``chat_with_tools``, x2), the synthesizer (``stream_chat``), and the
    grounding-rewrite path (``stream_chat`` again) in one turn. Each of those
    calls performs a REAL ``llm_usage_log`` INSERT via the production
    ``PrometheusAndDbCostRecorder``.

    Asserts:
      1. At least 4 llm_usage_log rows were written (2 planner + 1 synthesis +
         1 grounding-rewrite).
      2. EVERY row has a non-NULL ``chat_thread_id`` — this is the literal
         audit finding; before the fix every one of these was NULL because
         ``request.thread_id`` stayed ``None`` for the whole turn.
      3. ALL rows share the SAME ``chat_thread_id`` — proving the id was
         resolved ONCE up-front and reused consistently (not a different
         accidental UUID per call).
      4. EVERY row has ``user_id`` equal to the authenticated caller's id
         (non-NULL) — this is an authenticated chat turn, so user_id has no
         legitimate NULL case here (unlike the pre-thread-context safety
         classifier / batch citation-judge call sites, which are documented,
         deliberate exceptions left untouched by this fix).
    """
    user_id = uuid4()
    llm_chain = await _run_new_conversation_turn(_cost_recorder, user_id)

    # The fake chain recorded (call_site, thread_id, user_id) for every call —
    # sanity-check the in-process view before re-querying the DB row.
    assert len(llm_chain.captured) >= 4, f"expected >=4 LLM calls, got {llm_chain.captured}"
    call_sites = {c[0] for c in llm_chain.captured}
    assert "tool_loop_iter" in call_sites
    assert "synthesis" in call_sites
    assert "grounding_rewrite" in call_sites
    in_process_thread_ids = {c[1] for c in llm_chain.captured}
    assert (
        None not in in_process_thread_ids
    ), f"a NULL thread_id reached the LLM chain — the fix regressed: {llm_chain.captured}"
    assert (
        len(in_process_thread_ids) == 1
    ), f"expected ONE consistent effective thread_id across the whole turn, got {llm_chain.captured}"
    resolved_thread_id = next(iter(in_process_thread_ids))

    # Now the real assertion: query the ACTUAL persisted rows back out of
    # Postgres (not a mock) using the id captured above.
    from sqlalchemy import text

    async with _session_factory() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT capability, chat_thread_id, user_id FROM llm_usage_log "
                    "WHERE chat_thread_id = :tid ORDER BY created_at"
                ),
                {"tid": str(resolved_thread_id)},
            )
        ).fetchall()

    assert len(rows) >= 4, f"expected >=4 persisted llm_usage_log rows for thread {resolved_thread_id}, got {rows}"
    persisted_call_sites = {r[0] for r in rows}
    assert {"tool_loop_iter", "synthesis", "grounding_rewrite"} <= persisted_call_sites

    for capability, chat_thread_id, row_user_id in rows:
        assert chat_thread_id is not None, f"NULL chat_thread_id persisted for call_site={capability!r}"
        assert str(chat_thread_id) == str(resolved_thread_id)
        assert row_user_id is not None, f"NULL user_id persisted for call_site={capability!r}"
        assert str(row_user_id) == str(user_id)
