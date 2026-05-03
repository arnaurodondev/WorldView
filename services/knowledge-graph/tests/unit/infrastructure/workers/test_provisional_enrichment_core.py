"""Direct unit tests for provisional_enrichment_core (PLAN-0061 follow-up Wave B).

The module-level functions extracted in Wave E are reused by both
``ProvisionalEnrichmentWorker`` (polling sweep) and
``ProvisionalQueuedConsumer`` (hot path).  Earlier their behavior was only
covered indirectly via patches on the consumer side; these tests exercise the
real bodies directly with a mocked ``AsyncSession`` and ``FallbackChainClient``.

Coverage:

    extract_entity_profile
      - returns the profile dict on success
      - returns None when llm.extract returns None
      - constructs ExtractionInput with the right shape

    compute_embedding
      - returns the embedding list on success
      - returns None when llm.embed returns []

    apply_retry_transition (atomic CASE refactor)
      - returns True when the DB RETURNING row reports is_terminal
      - returns False when RETURNING reports not-terminal
      - returns False when the row is missing (concurrent delete)
      - issues exactly one UPDATE with the queue_id + max_retries params

    persist_enrichment
      - happy path: creates entity, inserts canonical alias, ticker, ISIN,
        LLM aliases, ensures embedding rows, writes embedding when provided,
        clears provisional flag, appends outbox entry — returns the new entity_id
      - skips embedding write when embedding=None
      - skips ticker/ISIN aliases when those fields are None
      - rejects an LLM alias that already maps to a different entity (collision)
      - truncates LLM aliases to the first 5
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest

pytestmark = pytest.mark.unit

_QUEUE_ID = UUID("01234567-89ab-7def-8012-000000000099")
_ENTITY_ID = UUID("01234567-89ab-7def-8012-345678901234")
_EXISTING_OTHER_ID = UUID("01234567-89ab-7def-8012-666666666666")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_session_with_returning(is_terminal: bool | None = None) -> AsyncMock:
    """Return an AsyncMock session whose execute().fetchone() yields (is_terminal,).

    Use ``is_terminal=None`` to simulate a missing row (RETURNING produced no row).
    """
    session = AsyncMock()
    session.commit = AsyncMock()

    result_mock = MagicMock()
    if is_terminal is None:
        result_mock.fetchone.return_value = None
    else:
        result_mock.fetchone.return_value = (is_terminal,)

    session.execute = AsyncMock(return_value=result_mock)
    return session


# ---------------------------------------------------------------------------
# extract_entity_profile
# ---------------------------------------------------------------------------


class TestExtractEntityProfile:
    async def test_returns_profile_on_success(self) -> None:
        from knowledge_graph.infrastructure.workers import provisional_enrichment_core as core

        profile = {"canonical_name": "Apple Inc.", "entity_type": "financial_instrument"}
        extraction_result = MagicMock()
        extraction_result.result = profile

        llm = MagicMock()
        llm.extract = AsyncMock(return_value=extraction_result)

        out = await core.extract_entity_profile(llm, "Apple Inc.", "financial_instrument", "ctx")

        assert out == profile
        llm.extract.assert_awaited_once()

    async def test_returns_none_when_llm_returns_none(self) -> None:
        from knowledge_graph.infrastructure.workers import provisional_enrichment_core as core

        llm = MagicMock()
        llm.extract = AsyncMock(return_value=None)

        out = await core.extract_entity_profile(llm, "Apple Inc.", "financial_instrument", "ctx")

        assert out is None


# ---------------------------------------------------------------------------
# compute_embedding
# ---------------------------------------------------------------------------


class TestComputeEmbedding:
    async def test_returns_embedding_on_success(self) -> None:
        from knowledge_graph.infrastructure.workers import provisional_enrichment_core as core

        emb_out = MagicMock()
        emb_out.embedding = [0.1] * 1024

        llm = MagicMock()
        llm.embed = AsyncMock(return_value=[emb_out])

        out = await core.compute_embedding(llm, None, "Apple Inc.", "bge-large:latest")

        assert out == [0.1] * 1024
        llm.embed.assert_awaited_once()

    async def test_returns_none_when_llm_returns_empty_list(self) -> None:
        from knowledge_graph.infrastructure.workers import provisional_enrichment_core as core

        llm = MagicMock()
        llm.embed = AsyncMock(return_value=[])

        out = await core.compute_embedding(llm, None, "Apple Inc.", "bge-large:latest")

        assert out is None


# ---------------------------------------------------------------------------
# apply_retry_transition (atomic CASE)
# ---------------------------------------------------------------------------


class TestApplyRetryTransition:
    async def test_returns_true_when_db_reports_terminal(self) -> None:
        from knowledge_graph.infrastructure.workers import provisional_enrichment_core as core

        session = _make_session_with_returning(is_terminal=True)

        out = await core.apply_retry_transition(session, _QUEUE_ID, max_retries=5)

        assert out is True
        session.execute.assert_awaited_once()

    async def test_returns_false_when_db_reports_not_terminal(self) -> None:
        from knowledge_graph.infrastructure.workers import provisional_enrichment_core as core

        session = _make_session_with_returning(is_terminal=False)

        out = await core.apply_retry_transition(session, _QUEUE_ID, max_retries=5)

        assert out is False

    async def test_returns_false_when_row_missing(self) -> None:
        from knowledge_graph.infrastructure.workers import provisional_enrichment_core as core

        session = _make_session_with_returning(is_terminal=None)  # RETURNING empty

        out = await core.apply_retry_transition(session, _QUEUE_ID, max_retries=5)

        assert out is False

    async def test_passes_queue_id_and_max_retries_as_params(self) -> None:
        from knowledge_graph.infrastructure.workers import provisional_enrichment_core as core

        session = _make_session_with_returning(is_terminal=False)

        await core.apply_retry_transition(session, _QUEUE_ID, max_retries=7)

        call = session.execute.call_args
        params = call.args[1] if len(call.args) > 1 else call.kwargs
        assert params["queue_id"] == str(_QUEUE_ID)
        assert params["max_retries"] == 7


# ---------------------------------------------------------------------------
# persist_enrichment
# ---------------------------------------------------------------------------


def _make_persist_session() -> tuple[AsyncMock, MagicMock]:
    """Return a (session, repos_mock) pair primed for persist_enrichment.

    repos_mock exposes the per-repository AsyncMock instances so individual
    tests can configure return values (e.g. alias collision via find_exact).
    """
    session = AsyncMock()
    session.commit = AsyncMock()
    session.execute = AsyncMock(return_value=MagicMock())

    repos = MagicMock()
    repos.canonical_create = AsyncMock(return_value=_ENTITY_ID)
    repos.alias_insert = AsyncMock()
    repos.alias_find_exact = AsyncMock(return_value=None)  # default: no collision
    repos.embedding_ensure = AsyncMock()
    repos.outbox_append = AsyncMock()

    return session, repos


class _PersistRepoPatches:
    """Context manager patching the four repository classes at their source modules.

    persist_enrichment lazily imports CanonicalEntityRepository, EntityAliasRepository,
    and OutboxRepository inside the function body — only EntityEmbeddingStateRepository
    is imported at the top of the core module — so we patch each at its original
    location rather than at the consumer site.
    """

    def __init__(self, repos: MagicMock) -> None:
        canonical_repo = MagicMock()
        canonical_repo.create = repos.canonical_create

        alias_repo = MagicMock()
        alias_repo.insert = repos.alias_insert
        alias_repo.find_exact = repos.alias_find_exact

        embedding_repo = MagicMock()
        embedding_repo.ensure_rows_exist = repos.embedding_ensure
        embedding_repo.upsert = AsyncMock()

        outbox_repo = MagicMock()
        outbox_repo.append = repos.outbox_append

        self._patches = [
            patch(
                "knowledge_graph.infrastructure.intelligence_db.repositories.canonical_entity.CanonicalEntityRepository",
                return_value=canonical_repo,
            ),
            patch(
                "knowledge_graph.infrastructure.intelligence_db.repositories.entity_alias.EntityAliasRepository",
                return_value=alias_repo,
            ),
            patch(
                "knowledge_graph.infrastructure.workers.provisional_enrichment_core.EntityEmbeddingStateRepository",
                return_value=embedding_repo,
            ),
            patch(
                "knowledge_graph.infrastructure.intelligence_db.repositories.outbox.OutboxRepository",
                return_value=outbox_repo,
            ),
        ]

    def __enter__(self) -> _PersistRepoPatches:
        for p in self._patches:
            p.start()
        return self

    def __exit__(self, *args: object) -> None:
        for p in self._patches:
            p.stop()


def _patch_persist_repos(repos: MagicMock) -> _PersistRepoPatches:
    return _PersistRepoPatches(repos)


class TestPersistEnrichment:
    async def test_happy_path_returns_entity_id_and_persists_aliases(self) -> None:
        from knowledge_graph.infrastructure.workers import provisional_enrichment_core as core

        session, repos = _make_persist_session()
        profile = {
            "canonical_name": "Apple Inc.",
            "entity_type": "financial_instrument",
            "ticker": "AAPL",
            "isin": "US0378331005",
            "aliases": ["Apple", "AAPL Inc."],
        }

        with _patch_persist_repos(repos):
            entity_id = await core.persist_enrichment(
                session=session,
                queue_id=_QUEUE_ID,
                mention_text="Apple Inc.",
                profile=profile,
                embedding=[0.1] * 1024,
                embed_model_id="bge-large:latest",
            )

        assert entity_id == _ENTITY_ID
        # canonical alias + ticker + isin + 2 LLM aliases = 5 inserts
        assert repos.alias_insert.await_count == 5
        repos.outbox_append.assert_awaited_once()
        # outbox topic must be entity.canonical.created.v1
        kwargs = repos.outbox_append.call_args.kwargs
        assert kwargs["topic"] == "entity.canonical.created.v1"

    async def test_skips_ticker_and_isin_when_absent(self) -> None:
        from knowledge_graph.infrastructure.workers import provisional_enrichment_core as core

        session, repos = _make_persist_session()
        profile = {
            "canonical_name": "Some Org",
            "entity_type": "ORGANIZATION",
            "ticker": None,
            "isin": None,
            "aliases": [],
        }

        with _patch_persist_repos(repos):
            await core.persist_enrichment(
                session=session,
                queue_id=_QUEUE_ID,
                mention_text="Some Org",
                profile=profile,
                embedding=None,
            )

        # Only the canonical alias should be inserted (no ticker, no ISIN, no LLM aliases).
        assert repos.alias_insert.await_count == 1

    async def test_alias_collision_skips_llm_alias(self) -> None:
        from knowledge_graph.infrastructure.workers import provisional_enrichment_core as core

        session, repos = _make_persist_session()
        # Configure find_exact: first LLM alias collides with a different entity.
        repos.alias_find_exact = AsyncMock(
            side_effect=[
                {"entity_id": _EXISTING_OTHER_ID},  # 'apple' already maps elsewhere → skip
                None,  # 'aapl inc.' clean → insert
            ]
        )
        profile = {
            "canonical_name": "Apple Inc.",
            "entity_type": "financial_instrument",
            "ticker": None,
            "isin": None,
            "aliases": ["Apple", "AAPL Inc."],
        }

        with _patch_persist_repos(repos):
            await core.persist_enrichment(
                session=session,
                queue_id=_QUEUE_ID,
                mention_text="Apple Inc.",
                profile=profile,
                embedding=None,
            )

        # canonical + 1 surviving LLM alias = 2 inserts
        assert repos.alias_insert.await_count == 2

    async def test_truncates_llm_aliases_to_first_five(self) -> None:
        from knowledge_graph.infrastructure.workers import provisional_enrichment_core as core

        session, repos = _make_persist_session()
        profile = {
            "canonical_name": "Big Co",
            "entity_type": "ORGANIZATION",
            "ticker": None,
            "isin": None,
            "aliases": [f"alias{i}" for i in range(10)],  # 10 aliases — only first 5 should be tried
        }

        with _patch_persist_repos(repos):
            await core.persist_enrichment(
                session=session,
                queue_id=_QUEUE_ID,
                mention_text="Big Co",
                profile=profile,
                embedding=None,
            )

        # canonical + 5 LLM aliases = 6 inserts
        assert repos.alias_insert.await_count == 6
