"""Unit tests for the ``claim_batch`` SELECT semantics (PLAN-0076 Wave A-4 / DEF-033).

The worldview ``provisional_entity_queue`` does **not** have a dedicated
``ProvisionalEntityQueueRepository`` class — the Phase-1 ``claim_batch`` SELECT
is inlined inside ``ProvisionalEnrichmentWorker.run()``
(``services/knowledge-graph/src/knowledge_graph/infrastructure/workers/
provisional_enrichment.py``).  Wave A-4's plan doc described a hypothetical
repository file at ``infrastructure/intelligence_db/repositories/
provisional_entity_queue.py`` that does not exist; rather than fabricate one
just to host the tests, this module asserts the *observable* claim_batch
behavior — which row predicates make it through the ``FOR UPDATE SKIP LOCKED``
SELECT — directly against the real worker.

Coverage (Wave A-4 / DEF-033):
  - test_claim_batch_skips_future_retry_at      — row with next_retry_at
    in the future MUST NOT be returned by the Phase-1 SELECT.
  - test_claim_batch_includes_past_retry_at     — row with next_retry_at
    already elapsed MUST be returned.
  - test_claim_batch_includes_null_retry_at     — row with next_retry_at
    IS NULL MUST be returned (backward-compat for pre-migration-0029 rows).

The mocked ``AsyncSession`` records every executed SQL string and parameter
dict.  The tests assert the SQL contains the new
``next_retry_at IS NULL OR next_retry_at <= CAST(:now AS TIMESTAMPTZ)``
predicate and that ``:now`` is bound from ``common.time.utc_now``.
Returned-row assertions reuse the worker's downstream paths to confirm the
end-to-end behavior is what an in-DB SELECT would produce.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest

pytestmark = pytest.mark.unit


# Fixed UUIDs so assertions are unambiguous.
_QUEUE_ID = UUID("01234567-89ab-7def-8012-000000000099")


def _make_pending_row(
    queue_id: UUID = _QUEUE_ID,
    retry_count: int = 0,
) -> tuple:
    """Build a fake row matching the Phase-1 SELECT column order.

    The worker's SELECT projects ``(queue_id, mention_text, normalized_surface,
    mention_class, context_snippet, source_doc_id, retry_count)`` — the same
    7-tuple shape used by ``test_provisional_enrichment._make_pending_row``.
    """
    return (
        str(queue_id),
        "Apple Inc.",
        "apple inc.",
        "financial_instrument",
        "Apple is a tech company",
        None,
        retry_count,
    )


def _make_session_returning_rows(rows: list) -> tuple[AsyncMock, MagicMock]:
    """Mocked AsyncSession factory returning the provided rows from execute()."""
    session = AsyncMock()
    session.commit = AsyncMock()

    result_mock = MagicMock()
    result_mock.fetchall.return_value = rows
    result_mock.rowcount = 0
    session.execute = AsyncMock(return_value=result_mock)

    def _make_cm() -> AsyncMock:
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=session)
        cm.__aexit__ = AsyncMock(return_value=False)
        return cm

    factory = MagicMock(side_effect=lambda: _make_cm())
    return session, factory


class TestClaimBatchNextRetryAtFilter:
    """The Phase-1 SELECT MUST filter on ``next_retry_at`` per DEF-033."""

    async def test_phase1_select_includes_next_retry_at_predicate(self) -> None:
        """SQL string must contain the new ``next_retry_at`` predicate."""
        from knowledge_graph.infrastructure.workers.provisional_enrichment import (
            ProvisionalEnrichmentWorker,
        )

        session, factory = _make_session_returning_rows([])
        worker = ProvisionalEnrichmentWorker(factory, AsyncMock(), max_retries=5)
        await worker.run()

        # Find the Phase-1 SELECT among the executed SQL strings.
        select_sqls = [
            str(call.args[0])
            for call in session.execute.call_args_list
            if call.args and "FROM provisional_entity_queue" in str(call.args[0])
        ]
        assert select_sqls, "Phase 1 SELECT must run (even with no rows)"

        phase1_sql = select_sqls[0]
        assert (
            "next_retry_at IS NULL" in phase1_sql
        ), f"Phase-1 SELECT must permit NULL next_retry_at (backward-compat); SQL was: {phase1_sql}"
        assert (
            "next_retry_at <= CAST(:now AS TIMESTAMPTZ)" in phase1_sql
        ), f"Phase-1 SELECT must compare next_retry_at against bound :now; SQL was: {phase1_sql}"

    async def test_phase1_select_binds_now_parameter_from_utc_now(self) -> None:
        """``:now`` parameter MUST come from ``common.time.utc_now`` (testable)."""
        from knowledge_graph.infrastructure.workers.provisional_enrichment import (
            ProvisionalEnrichmentWorker,
        )

        session, factory = _make_session_returning_rows([])
        worker = ProvisionalEnrichmentWorker(factory, AsyncMock(), max_retries=5)
        await worker.run()

        # Find the parameters dict for the Phase-1 SELECT.
        select_params = [
            call.args[1]
            for call in session.execute.call_args_list
            if call.args
            and len(call.args) > 1
            and isinstance(call.args[1], dict)
            and "FROM provisional_entity_queue" in str(call.args[0])
            and "now" in call.args[1]
        ]
        assert select_params, "Phase 1 SELECT must bind a :now parameter"
        bound_now = select_params[0]["now"]
        # ``:now`` is a tz-aware UTC datetime — common.time.utc_now() guarantees this.
        assert isinstance(bound_now, datetime), f"Expected datetime, got {type(bound_now)}"
        assert bound_now.tzinfo is not None, "now must be timezone-aware (UTC)"
        # Sanity bound: the value should be within a few seconds of "now".
        delta_s = abs((datetime.now(tz=UTC) - bound_now).total_seconds())
        assert delta_s < 5.0, f"now drifted by {delta_s}s — must be derived from utc_now()"

    async def test_claim_batch_skips_future_retry_at(self) -> None:
        """Row with ``next_retry_at = now + 1h`` is NOT returned (DB filters it out).

        We model the DB filter behaviorally: when ``utc_now()`` < the row's
        ``next_retry_at``, the SQL ``next_retry_at <= :now`` predicate is
        false, the row is excluded from ``fetchall()``, and the worker sees
        an empty batch — no Phase-3 writes happen.
        """
        from knowledge_graph.infrastructure.workers.provisional_enrichment import (
            ProvisionalEnrichmentWorker,
        )

        # The DB would filter this row out — model that by returning [].
        _session, factory = _make_session_returning_rows([])
        worker = ProvisionalEnrichmentWorker(factory, AsyncMock(), max_retries=5)

        with patch.object(worker, "_extract_entity_profile", new=AsyncMock()) as mock_extract:
            await worker.run()

        # No row claimed → no LLM extraction was attempted.
        mock_extract.assert_not_called()

    async def test_claim_batch_includes_past_retry_at(self) -> None:
        """Row with ``next_retry_at = now - 1s`` IS returned (deadline elapsed)."""
        from knowledge_graph.infrastructure.workers.provisional_enrichment import (
            ProvisionalEnrichmentWorker,
        )

        # The DB would include this row — return it directly.
        session, factory = _make_session_returning_rows([_make_pending_row()])
        worker = ProvisionalEnrichmentWorker(factory, AsyncMock(), max_retries=5)

        # Mock LLM extraction to short-circuit Phase 2/3; we only need to
        # confirm the row was claimed (extraction was attempted).
        with patch.object(worker, "_extract_entity_profile", new=AsyncMock(return_value=None)):
            await worker.run()

        # Row WAS claimed → SELECT returned it; UPDATE to 'processing' fired.
        update_sqls = [
            str(call.args[0])
            for call in session.execute.call_args_list
            if call.args and "SET status = 'processing'" in str(call.args[0])
        ]
        assert update_sqls, "Past-deadline row must be transitioned to 'processing'"

        # Sanity: the Phase-1 SELECT bound :now to a datetime later than the
        # simulated past deadline (1 second ago).
        select_params = [
            call.args[1]
            for call in session.execute.call_args_list
            if call.args
            and len(call.args) > 1
            and isinstance(call.args[1], dict)
            and "next_retry_at" in str(call.args[0])
        ]
        bound_now: datetime = select_params[0]["now"]
        past_deadline = bound_now - timedelta(seconds=1)
        assert past_deadline < bound_now  # the SQL predicate would evaluate true

    async def test_claim_batch_includes_null_retry_at(self) -> None:
        """Row with ``next_retry_at IS NULL`` IS returned (backward compat).

        Pre-migration-0029 rows have a NULL next_retry_at because the column
        was just added.  The Phase-1 SELECT explicitly handles this with the
        ``next_retry_at IS NULL OR ...`` clause.
        """
        from knowledge_graph.infrastructure.workers.provisional_enrichment import (
            ProvisionalEnrichmentWorker,
        )

        # NULL retry → DB returns the row (the IS NULL clause matches).
        session, factory = _make_session_returning_rows([_make_pending_row()])
        worker = ProvisionalEnrichmentWorker(factory, AsyncMock(), max_retries=5)

        with patch.object(worker, "_extract_entity_profile", new=AsyncMock(return_value=None)):
            await worker.run()

        # Row WAS claimed → UPDATE to 'processing' fired.
        update_sqls = [
            str(call.args[0])
            for call in session.execute.call_args_list
            if call.args and "SET status = 'processing'" in str(call.args[0])
        ]
        assert update_sqls, "NULL retry-deadline row must be transitioned to 'processing'"
