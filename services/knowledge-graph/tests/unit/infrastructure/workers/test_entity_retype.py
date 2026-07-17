"""Unit tests for Worker 13K — EntityRetypeWorker + resolve_canonical_entity_type.

Covers the shared type-resolution helper and the 3-phase re-typing sweep:
happy-path re-type, the guarded UPDATE no-op (row re-typed concurrently), the
"LLM still can't classify" skip, and the tickerless-company → organization rule.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest

pytestmark = pytest.mark.unit

_EID_A = UUID("01234567-89ab-7def-8012-000000000001")
_EID_B = UUID("01234567-89ab-7def-8012-000000000002")


# ---------------------------------------------------------------------------
# resolve_canonical_entity_type (pure helper)
# ---------------------------------------------------------------------------


class TestResolveCanonicalEntityType:
    def test_valid_type_passthrough(self) -> None:
        from knowledge_graph.infrastructure.workers.provisional_enrichment_core import (
            resolve_canonical_entity_type,
        )

        assert resolve_canonical_entity_type("person") == "person"
        assert resolve_canonical_entity_type("macro_indicator") == "macro_indicator"

    def test_alias_remap(self) -> None:
        from knowledge_graph.infrastructure.workers.provisional_enrichment_core import (
            resolve_canonical_entity_type,
        )

        # commodity → product; regulator/agency → organization; country → place
        assert resolve_canonical_entity_type("commodity") == "product"
        assert resolve_canonical_entity_type("regulator") == "organization"
        assert resolve_canonical_entity_type("Country") == "place"

    def test_invalid_type_collapses_to_unknown(self) -> None:
        from knowledge_graph.infrastructure.workers.provisional_enrichment_core import (
            resolve_canonical_entity_type,
        )

        assert resolve_canonical_entity_type("wizard") == "unknown"
        assert resolve_canonical_entity_type(None) == "unknown"

    def test_tickerless_company_default_is_unknown(self) -> None:
        from knowledge_graph.infrastructure.workers.provisional_enrichment_core import (
            resolve_canonical_entity_type,
        )

        # company-class with no ticker → default fallback is 'unknown' (mirrors
        # the provisional persist path).
        assert resolve_canonical_entity_type("company", ticker=None) == "unknown"

    def test_tickerless_company_retype_fallback_is_organization(self) -> None:
        from knowledge_graph.infrastructure.workers.provisional_enrichment_core import (
            resolve_canonical_entity_type,
        )

        assert (
            resolve_canonical_entity_type("company", ticker=None, tickerless_company_fallback="organization")
            == "organization"
        )

    def test_company_with_ticker_stays_financial_instrument(self) -> None:
        from knowledge_graph.infrastructure.workers.provisional_enrichment_core import (
            resolve_canonical_entity_type,
        )

        assert resolve_canonical_entity_type("company", ticker="IBKR") == "financial_instrument"


# ---------------------------------------------------------------------------
# EntityRetypeWorker
# ---------------------------------------------------------------------------


def _make_session_factory() -> tuple[MagicMock, AsyncMock]:
    session = AsyncMock()
    session.commit = AsyncMock()
    session_cm = AsyncMock()
    session_cm.__aenter__ = AsyncMock(return_value=session)
    session_cm.__aexit__ = AsyncMock(return_value=False)
    factory = MagicMock(return_value=session_cm)
    return factory, session


def _make_worker(batch_limit: int = 100):  # type: ignore[no-untyped-def]
    from knowledge_graph.infrastructure.workers.entity_retype import EntityRetypeWorker

    factory, session = _make_session_factory()
    worker = EntityRetypeWorker(factory, AsyncMock(), batch_limit=batch_limit)
    return worker, session


@pytest.mark.asyncio
class TestEntityRetypeWorker:
    async def test_no_unknown_rows_is_noop(self) -> None:
        worker, _ = _make_worker()
        with (
            patch(
                "knowledge_graph.infrastructure.intelligence_db.repositories.canonical_entity."
                "CanonicalEntityRepository.list_unknown_entities",
                new=AsyncMock(return_value=[]),
            ),
            patch(
                "knowledge_graph.infrastructure.workers.provisional_enrichment_core.extract_entity_profile",
                new=AsyncMock(),
            ) as mock_extract,
        ):
            await worker.run()
        mock_extract.assert_not_awaited()

    async def test_happy_path_retypes_and_seeds_rows(self) -> None:
        worker, _ = _make_worker()
        rows = [
            {
                "entity_id": _EID_A,
                "canonical_name": "Interactive Brokers Group, Inc.",
                "ticker": None,
                "isin": None,
                "description": None,
            },
            {
                "entity_id": _EID_B,
                "canonical_name": "ISM Services PMI",
                "ticker": None,
                "isin": None,
                "description": "A monthly economic index.",
            },
        ]
        retype = AsyncMock(return_value=True)
        ensure = AsyncMock()
        # LLM types A as organization (tickerless company) and B as macro_indicator.
        extract = AsyncMock(
            side_effect=[
                {"entity_type": "company"},  # → tickerless company → organization
                {"entity_type": "macro_indicator"},
            ]
        )
        with (
            patch(
                "knowledge_graph.infrastructure.intelligence_db.repositories.canonical_entity."
                "CanonicalEntityRepository.list_unknown_entities",
                new=AsyncMock(return_value=rows),
            ),
            patch(
                "knowledge_graph.infrastructure.intelligence_db.repositories.canonical_entity."
                "CanonicalEntityRepository.retype_unknown_entity",
                new=retype,
            ),
            patch(
                "knowledge_graph.infrastructure.intelligence_db.repositories.entity_embedding_state."
                "EntityEmbeddingStateRepository.ensure_rows_exist",
                new=ensure,
            ),
            patch(
                "knowledge_graph.infrastructure.workers.provisional_enrichment_core.extract_entity_profile",
                new=extract,
            ),
        ):
            await worker.run()

        assert retype.await_count == 2
        # Verify the resolved types written back.
        typed = {call.args[1] for call in retype.await_args_list}
        assert typed == {"organization", "macro_indicator"}
        assert ensure.await_count == 2

    async def test_unresolved_row_is_skipped(self) -> None:
        worker, _ = _make_worker()
        rows = [{"entity_id": _EID_A, "canonical_name": "Xyzzy", "ticker": None, "isin": None, "description": None}]
        retype = AsyncMock(return_value=True)
        with (
            patch(
                "knowledge_graph.infrastructure.intelligence_db.repositories.canonical_entity."
                "CanonicalEntityRepository.list_unknown_entities",
                new=AsyncMock(return_value=rows),
            ),
            patch(
                "knowledge_graph.infrastructure.intelligence_db.repositories.canonical_entity."
                "CanonicalEntityRepository.retype_unknown_entity",
                new=retype,
            ),
            patch(
                "knowledge_graph.infrastructure.workers.provisional_enrichment_core.extract_entity_profile",
                new=AsyncMock(return_value={"entity_type": "gibberish"}),  # → unknown
            ),
        ):
            await worker.run()
        retype.assert_not_awaited()

    async def test_guarded_update_noop_skips_ensure_rows(self) -> None:
        """When retype_unknown_entity returns False (row already re-typed), skip seeding."""
        worker, _ = _make_worker()
        rows = [{"entity_id": _EID_A, "canonical_name": "Palladium", "ticker": None, "isin": None, "description": None}]
        ensure = AsyncMock()
        with (
            patch(
                "knowledge_graph.infrastructure.intelligence_db.repositories.canonical_entity."
                "CanonicalEntityRepository.list_unknown_entities",
                new=AsyncMock(return_value=rows),
            ),
            patch(
                "knowledge_graph.infrastructure.intelligence_db.repositories.canonical_entity."
                "CanonicalEntityRepository.retype_unknown_entity",
                new=AsyncMock(return_value=False),  # row already re-typed concurrently
            ),
            patch(
                "knowledge_graph.infrastructure.intelligence_db.repositories.entity_embedding_state."
                "EntityEmbeddingStateRepository.ensure_rows_exist",
                new=ensure,
            ),
            patch(
                "knowledge_graph.infrastructure.workers.provisional_enrichment_core.extract_entity_profile",
                new=AsyncMock(return_value={"entity_type": "commodity"}),  # → product
            ),
        ):
            await worker.run()
        ensure.assert_not_awaited()

    async def test_extract_exception_is_swallowed(self) -> None:
        worker, _ = _make_worker()
        rows = [{"entity_id": _EID_A, "canonical_name": "Boom", "ticker": None, "isin": None, "description": None}]
        retype = AsyncMock(return_value=True)
        with (
            patch(
                "knowledge_graph.infrastructure.intelligence_db.repositories.canonical_entity."
                "CanonicalEntityRepository.list_unknown_entities",
                new=AsyncMock(return_value=rows),
            ),
            patch(
                "knowledge_graph.infrastructure.intelligence_db.repositories.canonical_entity."
                "CanonicalEntityRepository.retype_unknown_entity",
                new=retype,
            ),
            patch(
                "knowledge_graph.infrastructure.intelligence_db.repositories.canonical_entity."
                "CanonicalEntityRepository.record_retype_attempts",
                new=AsyncMock(),
            ),
            patch(
                "knowledge_graph.infrastructure.workers.provisional_enrichment_core.extract_entity_profile",
                new=AsyncMock(side_effect=RuntimeError("llm down")),
            ),
        ):
            await worker.run()  # must not raise
        retype.assert_not_awaited()

    async def test_transient_llm_error_does_not_increment_attempts(self) -> None:
        """CRITICAL (review defect): a transient LLM/extraction error must NOT
        count toward the attempt cap.  Otherwise a routine DeepInfra outage —
        every scanned row errors for a few cycles — would burn the whole
        ``unknown`` backlog's attempts and permanently exclude recoverable rows
        from the sweep.  The row is simply retried next cycle instead."""
        worker, _ = _make_worker()
        rows = [
            {
                "entity_id": _EID_A,
                "canonical_name": "Interactive Brokers",
                "ticker": None,
                "isin": None,
                "description": None,
            }
        ]
        record = AsyncMock()
        with (
            patch(
                "knowledge_graph.infrastructure.intelligence_db.repositories.canonical_entity."
                "CanonicalEntityRepository.list_unknown_entities",
                new=AsyncMock(return_value=rows),
            ),
            patch(
                "knowledge_graph.infrastructure.intelligence_db.repositories.canonical_entity."
                "CanonicalEntityRepository.record_retype_attempts",
                new=record,
            ),
            patch(
                "knowledge_graph.infrastructure.workers.provisional_enrichment_core.extract_entity_profile",
                new=AsyncMock(side_effect=RuntimeError("deepinfra 503 outage")),
            ),
        ):
            await worker.run()
        # The erroring row is NEVER handed to the attempt-counter bump — whether
        # the bump is skipped entirely or called with an empty list, _EID_A must
        # not appear so the row stays eligible on the next cycle.
        for call in record.await_args_list:
            assert _EID_A not in call.args[0], "transient-error row must not be capped"


# ---------------------------------------------------------------------------
# Attempt-tracking (2026-07-16 follow-up)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestEntityRetypeAttemptTracking:
    """Per-entity attempt cap: skip capped rows, retry under-cap rows, bump on fail."""

    async def test_configured_cap_is_passed_to_the_query(self) -> None:
        """Worker forwards ``max_attempts`` to ``list_unknown_entities`` so the
        SQL layer excludes rows that have already hit the cap (at-cap skip)."""
        from knowledge_graph.infrastructure.workers.entity_retype import EntityRetypeWorker

        factory, _ = _make_session_factory()
        worker = EntityRetypeWorker(factory, AsyncMock(), batch_limit=50, max_attempts=3)
        list_unknown = AsyncMock(return_value=[])
        with patch(
            "knowledge_graph.infrastructure.intelligence_db.repositories.canonical_entity."
            "CanonicalEntityRepository.list_unknown_entities",
            new=list_unknown,
        ):
            await worker.run()
        # (batch_limit, max_attempts) — the SQL predicate drops rows at the cap.
        list_unknown.assert_awaited_once_with(50, 3)

    async def test_unresolved_row_increments_attempt_counter(self) -> None:
        """A row the LLM can't classify stays ``unknown`` AND has its attempt
        counter bumped (so it eventually crosses the cap)."""
        worker, _ = _make_worker()
        rows = [{"entity_id": _EID_A, "canonical_name": "Xyzzy", "ticker": None, "isin": None, "description": None}]
        record = AsyncMock()
        retype = AsyncMock(return_value=True)
        with (
            patch(
                "knowledge_graph.infrastructure.intelligence_db.repositories.canonical_entity."
                "CanonicalEntityRepository.list_unknown_entities",
                new=AsyncMock(return_value=rows),
            ),
            patch(
                "knowledge_graph.infrastructure.intelligence_db.repositories.canonical_entity."
                "CanonicalEntityRepository.retype_unknown_entity",
                new=retype,
            ),
            patch(
                "knowledge_graph.infrastructure.intelligence_db.repositories.canonical_entity."
                "CanonicalEntityRepository.record_retype_attempts",
                new=record,
            ),
            patch(
                "knowledge_graph.infrastructure.workers.provisional_enrichment_core.extract_entity_profile",
                new=AsyncMock(return_value={"entity_type": "gibberish"}),  # → unknown
            ),
        ):
            await worker.run()
        retype.assert_not_awaited()
        # The unresolved row's id is handed to the attempt-counter bump.
        record.assert_awaited_once_with([_EID_A])

    async def test_resolved_row_is_not_counted_as_an_attempt(self) -> None:
        """A successfully re-typed row leaves the ``unknown`` bucket, so it is
        NOT added to the attempt-counter bump (preserves under-cap behaviour)."""
        worker, _ = _make_worker()
        rows = [{"entity_id": _EID_A, "canonical_name": "Palladium", "ticker": None, "isin": None, "description": None}]
        record = AsyncMock()
        with (
            patch(
                "knowledge_graph.infrastructure.intelligence_db.repositories.canonical_entity."
                "CanonicalEntityRepository.list_unknown_entities",
                new=AsyncMock(return_value=rows),
            ),
            patch(
                "knowledge_graph.infrastructure.intelligence_db.repositories.canonical_entity."
                "CanonicalEntityRepository.retype_unknown_entity",
                new=AsyncMock(return_value=True),
            ),
            patch(
                "knowledge_graph.infrastructure.intelligence_db.repositories.entity_embedding_state."
                "EntityEmbeddingStateRepository.ensure_rows_exist",
                new=AsyncMock(),
            ),
            patch(
                "knowledge_graph.infrastructure.intelligence_db.repositories.canonical_entity."
                "CanonicalEntityRepository.record_retype_attempts",
                new=record,
            ),
            patch(
                "knowledge_graph.infrastructure.workers.provisional_enrichment_core.extract_entity_profile",
                new=AsyncMock(return_value={"entity_type": "commodity"}),  # → product
            ),
        ):
            await worker.run()
        # Bump is called with an empty list — the resolved id is absent.
        record.assert_awaited_once_with([])

    async def test_nameless_row_is_counted_as_an_attempt(self) -> None:
        """A row with no canonical_name is un-classifiable — count the attempt so
        a nameless junk row eventually crosses the cap and stops being scanned."""
        worker, _ = _make_worker()
        rows = [{"entity_id": _EID_A, "canonical_name": None, "ticker": None, "isin": None, "description": None}]
        record = AsyncMock()
        extract = AsyncMock()
        with (
            patch(
                "knowledge_graph.infrastructure.intelligence_db.repositories.canonical_entity."
                "CanonicalEntityRepository.list_unknown_entities",
                new=AsyncMock(return_value=rows),
            ),
            patch(
                "knowledge_graph.infrastructure.intelligence_db.repositories.canonical_entity."
                "CanonicalEntityRepository.record_retype_attempts",
                new=record,
            ),
            patch(
                "knowledge_graph.infrastructure.workers.provisional_enrichment_core.extract_entity_profile",
                new=extract,
            ),
        ):
            await worker.run()
        # No LLM call for a nameless row, but the attempt is still recorded.
        extract.assert_not_awaited()
        record.assert_awaited_once_with([_EID_A])
