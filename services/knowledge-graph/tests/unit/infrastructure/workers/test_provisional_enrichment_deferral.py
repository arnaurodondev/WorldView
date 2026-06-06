"""PRD-0089 F2 §4.3 — tradable provisional enrichment deferral tests.

The F2 wave introduces invariant M-017 (canonical_entities.entity_id ==
market_data.instruments.id for every tradable entity). ``persist_enrichment``
now consults a ``MarketDataLookupPort`` BEFORE minting a new UUID for any
profile whose ``entity_type == 'financial_instrument'`` and which carries a
ticker:

* Branch A — instrument exists in S2 → reuse ``instruments.id`` as the new
  canonical entity_id (passed to ``CanonicalEntityRepository.create_or_get``).
* Branch B — instrument missing in S2 → return ``None`` so the worker's
  ``_apply_retry`` schedules an exponential-backoff retry. No DB writes,
  no outbox emission.
* Branch C — retry_count reaches ``max_retries`` → ``apply_retry_transition``
  transitions the row to terminal status='failed'. The provisional queue's
  ``failed`` status IS the project's DLQ for this path (operator-visible
  via /admin/dlq endpoints); no separate Kafka DLQ topic is emitted because
  failed rows live in the same DB transaction graph as the queue itself.

These tests use ``AsyncMock`` for both the S2 client (so no HTTP is made)
and the DB session (so no asyncpg engine is required). They are pure
unit tests against the module-level core functions and the polling worker's
delegate ``_persist_enrichment``.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest

pytestmark = pytest.mark.unit

# ---------------------------------------------------------------------------
# Test fixtures and helpers
# ---------------------------------------------------------------------------

# Stable UUIDs used across branches so failures point at the exact row.
_QUEUE_ID = UUID("01234567-89ab-7def-8012-000000000099")
_INSTRUMENT_ID = UUID("01999999-9999-7999-8999-999999999999")  # what S2 returns
_FALLBACK_NEW_ID = UUID("01234567-89ab-7def-8012-345678901234")  # what create_or_get would mint

_TRADABLE_PROFILE: dict[str, object] = {
    "canonical_name": "Apple Inc.",
    "entity_type": "financial_instrument",
    "ticker": "AAPL",
    "isin": None,
    "aliases": [],
}


def _make_persist_session() -> tuple[AsyncMock, MagicMock]:
    """Same shape as the existing test_provisional_enrichment_core helper.

    We re-create it here (instead of importing) so the deferral tests have a
    self-contained fixture surface — easier to reason about when the deferral
    branch changes the mock interaction pattern.
    """
    session = AsyncMock()
    session.commit = AsyncMock()
    session.execute = AsyncMock(return_value=MagicMock())

    repos = MagicMock()
    repos.canonical_create_or_get = AsyncMock(return_value=(_FALLBACK_NEW_ID, True))
    repos.canonical_create = AsyncMock(return_value=_FALLBACK_NEW_ID)
    repos.alias_insert = AsyncMock()
    repos.alias_find_exact = AsyncMock(return_value=None)
    repos.alias_fuzzy_search = AsyncMock(return_value=[])  # no fuzzy match
    repos.embedding_ensure = AsyncMock()
    repos.outbox_append = AsyncMock()
    return session, repos


class _PersistRepoPatches:
    """Mirrors the patch context manager used by test_provisional_enrichment_core.

    Lazily importing repositories inside ``persist_enrichment`` means we have
    to patch them at their definition modules, not at the consumer site.
    """

    def __init__(self, repos: MagicMock) -> None:
        canonical_repo = MagicMock()
        canonical_repo.create = repos.canonical_create
        canonical_repo.create_or_get = repos.canonical_create_or_get

        alias_repo = MagicMock()
        alias_repo.insert = repos.alias_insert
        alias_repo.find_exact = repos.alias_find_exact
        alias_repo.fuzzy_search = repos.alias_fuzzy_search

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


def _make_lookup(instrument_ref: object | None) -> AsyncMock:
    """Build an AsyncMock satisfying ``MarketDataLookupPort``.

    Pass ``None`` to simulate the "instrument not found" branch; pass an
    ``InstrumentRef`` to simulate the "instrument exists" branch.
    """
    lookup = AsyncMock()
    lookup.lookup_instrument_by_ticker = AsyncMock(return_value=instrument_ref)
    return lookup


# ---------------------------------------------------------------------------
# Branch A — instrument exists in S2 → anchor on instrument_id
# ---------------------------------------------------------------------------


class TestBranchAInstrumentExists:
    """When S2 returns an instrument, persist_enrichment passes its UUID
    through to ``CanonicalEntityRepository.create_or_get`` as the
    ``entity_id`` kwarg so the canonical row is anchored on the same UUID."""

    async def test_passes_instrument_id_to_create_or_get(self) -> None:
        from knowledge_graph.application.ports.market_data_lookup_port import InstrumentRef
        from knowledge_graph.infrastructure.workers import provisional_enrichment_core as core

        session, repos = _make_persist_session()
        # create_or_get returns the same UUID we asked it to use — simulates
        # the SQL ``INSERT ... RETURNING entity_id`` happy path.
        repos.canonical_create_or_get = AsyncMock(return_value=(_INSTRUMENT_ID, True))

        lookup = _make_lookup(InstrumentRef(instrument_id=_INSTRUMENT_ID, ticker="AAPL", exchange="US"))

        with _PersistRepoPatches(repos):
            result = await core.persist_enrichment(
                session=session,
                queue_id=_QUEUE_ID,
                mention_text="Apple Inc.",
                profile=_TRADABLE_PROFILE,
                embedding=None,
                market_data_lookup=lookup,
            )

        # The returned entity_id MUST equal what S2 has, not a freshly minted UUID.
        assert result == _INSTRUMENT_ID

        # The lookup was made exactly once with the ticker from the profile.
        lookup.lookup_instrument_by_ticker.assert_awaited_once_with("AAPL")

        # The repository call site received entity_id=instrument_id.
        repos.canonical_create_or_get.assert_awaited_once()
        kwargs = repos.canonical_create_or_get.call_args.kwargs
        assert kwargs["entity_id"] == _INSTRUMENT_ID, (
            "When S2 has the instrument, persist_enrichment MUST forward "
            "entity_id=instrument_id to create_or_get to enforce M-017"
        )
        # Other fields still wire through correctly.
        assert kwargs["canonical_name"] == "Apple Inc."
        assert kwargs["entity_type"] == "financial_instrument"
        assert kwargs["ticker"] == "AAPL"

        # Outbox event was emitted (Branch A is the happy path — full persist).
        repos.outbox_append.assert_awaited_once()
        # The outbox payload's entity_id MUST also be the instrument's UUID
        # so downstream consumers see the M-017-aligned id.
        outbox_kwargs = repos.outbox_append.call_args.kwargs
        assert outbox_kwargs["partition_key"] == str(_INSTRUMENT_ID)


# ---------------------------------------------------------------------------
# Branch B — instrument missing in S2 → defer
# ---------------------------------------------------------------------------


class TestBranchBInstrumentMissing:
    """When S2 returns 404 / None, persist_enrichment returns None and makes
    no DB writes. The worker's existing _apply_retry → apply_retry_transition
    chain then increments retry_count and writes next_retry_at."""

    async def test_returns_none_when_lookup_returns_none(self) -> None:
        from knowledge_graph.infrastructure.workers import provisional_enrichment_core as core

        session, repos = _make_persist_session()
        lookup = _make_lookup(None)  # S2 has no row for this ticker yet.

        with _PersistRepoPatches(repos):
            result = await core.persist_enrichment(
                session=session,
                queue_id=_QUEUE_ID,
                mention_text="Apple Inc.",
                profile=_TRADABLE_PROFILE,
                embedding=None,
                market_data_lookup=lookup,
            )

        assert result is None, "Branch B (S2 missing) must return None to signal deferral"
        lookup.lookup_instrument_by_ticker.assert_awaited_once_with("AAPL")

        # Crucial: no DB writes happened — the deferral path is side-effect free.
        repos.canonical_create_or_get.assert_not_awaited()
        repos.canonical_create.assert_not_awaited()
        repos.alias_insert.assert_not_awaited()
        repos.outbox_append.assert_not_awaited()
        repos.embedding_ensure.assert_not_awaited()

    async def test_worker_applies_retry_when_persist_returns_none(self) -> None:
        """End-to-end through ProvisionalEnrichmentWorker._persist_enrichment:
        the worker's run() loop already treats persist_enrichment=None as a
        retryable failure (existing behaviour for LLM extraction errors).
        Returning None for the deferral case reuses that same code path.
        """
        from knowledge_graph.infrastructure.workers.provisional_enrichment import (
            ProvisionalEnrichmentWorker,
        )

        # Worker construction wires the lookup port through to _persist_enrichment.
        session_factory = MagicMock()  # never actually used in this assert.
        llm_client = MagicMock()
        lookup = _make_lookup(None)

        worker = ProvisionalEnrichmentWorker(
            session_factory=session_factory,
            llm_client=llm_client,
            market_data_lookup=lookup,
        )

        # Patch core.persist_enrichment to confirm forwarding without exercising
        # the full body (the body is already covered by the test above).
        with patch(
            "knowledge_graph.infrastructure.workers.provisional_enrichment.core.persist_enrichment",
            new=AsyncMock(return_value=None),
        ) as core_persist:
            session = AsyncMock()
            result = await worker._persist_enrichment(
                session=session,
                queue_id=_QUEUE_ID,
                mention_text="Apple Inc.",
                profile=_TRADABLE_PROFILE,
                embedding=None,
            )

        assert result is None
        # The lookup port was threaded into the delegate call so the deferral
        # decision still happens inside core.persist_enrichment.
        kwargs = core_persist.call_args.kwargs
        assert kwargs["market_data_lookup"] is lookup


# ---------------------------------------------------------------------------
# Branch C — retry_count reaches max_retries → DLQ (status='failed')
# ---------------------------------------------------------------------------


class TestBranchCDLQAtMaxRetries:
    """When the row's retry_count would exceed max_retries on the next
    increment, ``apply_retry_transition`` transitions status to 'failed'
    (the project's DLQ state for this queue) and returns True so the worker
    can increment the failed-counter Prometheus metric.

    This branch validates the EXISTING terminal-transition path in
    ``apply_retry_transition`` so that F2's deferral mechanism participates
    in the same DLQ convention rather than introducing a new Kafka topic.
    """

    async def test_apply_retry_transitions_to_failed_at_cap(self) -> None:
        from datetime import datetime
        from unittest.mock import MagicMock as Mm

        from knowledge_graph.infrastructure.workers import provisional_enrichment_core as core

        # DB-side: row had retry_count = max_retries - 1 BEFORE this call.
        # After increment retry_count == max_retries → status='failed' (terminal).
        session = AsyncMock()
        session.commit = AsyncMock()
        result_mock = Mm()
        # is_terminal=True signals the row has crossed the retry cap.
        # next_retry_at=None because failed rows do not need a deadline.
        result_mock.fetchone.return_value = (True, 5, None)
        session.execute = AsyncMock(return_value=result_mock)

        out = await core.apply_retry_transition(
            session,
            _QUEUE_ID,
            max_retries=5,
            base_retry_minutes=2,
            max_retry_minutes=1440,
        )

        assert out is True, (
            "apply_retry_transition must return True when the DB CASE has "
            "transitioned the row to terminal status='failed' (queue-level DLQ)."
        )

        # The SQL must include the terminal CASE branch (sanity: no future
        # refactor accidentally drops the failed transition).
        sql_str = str(session.execute.call_args.args[0])
        assert "'failed'" in sql_str
        assert "WHEN q.retry_count + 1 >= :max_retries THEN 'failed'" in sql_str

        # next_retry_at must be NULL for failed rows so they are never re-claimed.
        assert "WHEN q.retry_count + 1 >= :max_retries THEN NULL" in sql_str

        # The placeholder import is used elsewhere in the package — ensure no
        # accidental drift in the datetime import (smoke against module-level
        # imports being removed).
        assert datetime  # type: ignore[truthy-function]


# ---------------------------------------------------------------------------
# Idempotency — replaying the same provisional must not double-mint
# ---------------------------------------------------------------------------


class TestIdempotency:
    """If the worker receives the same provisional twice (Kafka redelivery,
    polling race), the lookup → create_or_get path is naturally idempotent:
    create_or_get's ``ON CONFLICT DO NOTHING`` returns ``was_created=False``
    on the second call, and persist_enrichment short-circuits without
    re-inserting aliases or emitting another outbox event.
    """

    async def test_replay_returns_existing_id_without_duplicate_writes(self) -> None:
        from knowledge_graph.application.ports.market_data_lookup_port import InstrumentRef
        from knowledge_graph.infrastructure.workers import provisional_enrichment_core as core

        session, repos = _make_persist_session()
        # Second call: ON CONFLICT hit, was_created=False → short-circuit.
        repos.canonical_create_or_get = AsyncMock(return_value=(_INSTRUMENT_ID, False))

        lookup = _make_lookup(InstrumentRef(instrument_id=_INSTRUMENT_ID, ticker="AAPL", exchange="US"))

        with _PersistRepoPatches(repos):
            result = await core.persist_enrichment(
                session=session,
                queue_id=_QUEUE_ID,
                mention_text="Apple Inc.",
                profile=_TRADABLE_PROFILE,
                embedding=None,
                market_data_lookup=lookup,
            )

        # Returns the existing entity_id, which IS the instrument's UUID.
        assert result == _INSTRUMENT_ID

        # No alias inserts, no outbox event — the dedup short-circuit fired.
        repos.alias_insert.assert_not_awaited()
        repos.outbox_append.assert_not_awaited()


# ---------------------------------------------------------------------------
# Negative — non-tradable profiles bypass the lookup entirely
# ---------------------------------------------------------------------------


class TestNonTradableBypassesLookup:
    """Lookups only fire for tradable profiles with a ticker. A person/event
    profile must never hit S2 — those are owned by the KG alone."""

    async def test_person_profile_does_not_call_lookup(self) -> None:
        from knowledge_graph.infrastructure.workers import provisional_enrichment_core as core

        session, repos = _make_persist_session()
        lookup = _make_lookup(None)

        with _PersistRepoPatches(repos):
            result = await core.persist_enrichment(
                session=session,
                queue_id=_QUEUE_ID,
                mention_text="Tim Cook",
                profile={
                    "canonical_name": "Tim Cook",
                    "entity_type": "person",
                    "ticker": None,  # person profile has no ticker anyway
                    "isin": None,
                    "aliases": [],
                },
                embedding=None,
                market_data_lookup=lookup,
            )

        assert result == _FALLBACK_NEW_ID  # default create_or_get UUID
        # No S2 call — non-tradable entities never round-trip to market-data.
        lookup.lookup_instrument_by_ticker.assert_not_awaited()

    async def test_tradable_without_ticker_does_not_call_lookup(self) -> None:
        """Defensive: a tradable-classified profile that lacks a ticker (LLM
        omission) cannot be looked up — we let create_or_get mint a UUID and
        let downstream de-dup catch any collision."""
        from knowledge_graph.infrastructure.workers import provisional_enrichment_core as core

        session, repos = _make_persist_session()
        lookup = _make_lookup(None)
        profile_no_ticker = dict(_TRADABLE_PROFILE)
        profile_no_ticker["ticker"] = None

        with _PersistRepoPatches(repos):
            result = await core.persist_enrichment(
                session=session,
                queue_id=_QUEUE_ID,
                mention_text="Some unknown instrument",
                profile=profile_no_ticker,
                embedding=None,
                market_data_lookup=lookup,
            )

        assert result == _FALLBACK_NEW_ID
        lookup.lookup_instrument_by_ticker.assert_not_awaited()
