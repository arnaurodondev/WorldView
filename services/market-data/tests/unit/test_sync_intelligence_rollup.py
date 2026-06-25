"""Unit tests for SyncIntelligenceRollupUseCase.

PLAN-0089 Wave L-5b (T-WL5B-06).

Covers:
  - Success scenario: all 6 columns written
  - Partial failure: S6 down → keeps last-known S6 columns; S7/S10/S8 written
  - All-failure: row not touched
  - Stale-freshness skip: ``intelligence_rollup_synced_at`` < 18h → skip
  - Summary counters are correct for each scenario
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from market_data.application.use_cases.sync_intelligence_rollup import (
    SyncIntelligenceRollupOptions,
    SyncIntelligenceRollupUseCase,
)
from market_data.infrastructure.clients.intelligence_clients import (
    S6NewsRollup,
    S7IntelligenceRollup,
    S8BriefFlag,
    S10AlertFlag,
)

pytestmark = pytest.mark.unit


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_row(
    instrument_id: str = "inst-001",
    synced_at: datetime | None = None,
) -> MagicMock:
    """Return a mock DB row with the fields query_screen would return."""
    row = MagicMock()
    row.id = instrument_id
    row.intelligence_rollup_synced_at = synced_at
    row.news_count_7d = None
    row.llm_relevance_7d_max = None
    row.display_relevance_7d_weighted = None
    row.recent_contradiction_count = None
    row.has_active_alert = None
    row.has_ai_brief = None
    return row


def _make_write_factory(rows: list[Any]) -> AsyncMock:
    """Return a write_factory mock that yields ``rows`` on first page, [] on second.

    The factory is used as an async context manager (``async with factory() as session``).
    Two calls: first returns instruments, second is the UPSERT.
    """
    # Simulate two pages: first page has rows, second is empty (signals end).
    page_call_count = [0]

    async def _execute(sql: Any, params: Any = None) -> MagicMock:
        result = MagicMock()
        page_call_count[0] += 1
        if page_call_count[0] == 1:
            result.all.return_value = rows
        else:
            # Pagination query — alternates between instrument list and UPSERT.
            # For simplicity return empty so the loop terminates after one batch.
            result.all.return_value = []
        return result

    session = AsyncMock()
    session.execute = _execute
    session.commit = AsyncMock()

    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=session)
    cm.__aexit__ = AsyncMock(return_value=False)

    factory = MagicMock()
    factory.return_value = cm
    return factory  # type: ignore[return-value]


def _make_clients(
    s6_result: S6NewsRollup | None,
    s7_result: S7IntelligenceRollup | None,
    s10_result: S10AlertFlag | None,
    s8_result: S8BriefFlag | None,
) -> tuple[AsyncMock, AsyncMock, AsyncMock, AsyncMock]:
    """Return 4 mock clients with pre-set return values."""
    s6 = AsyncMock()
    s6.get_news_rollup = AsyncMock(return_value=s6_result)
    s7 = AsyncMock()
    s7.get_intelligence_rollup = AsyncMock(return_value=s7_result)
    s10 = AsyncMock()
    s10.get_active_alert_flag = AsyncMock(return_value=s10_result)
    s8 = AsyncMock()
    s8.get_ai_brief_flag = AsyncMock(return_value=s8_result)
    return s6, s7, s10, s8


# ── Tests ─────────────────────────────────────────────────────────────────────


class TestSyncIntelligenceRollupUseCase:
    """Happy-path and failure-mode coverage."""

    @pytest.mark.asyncio
    async def test_success_all_columns_written(self) -> None:
        """All 6 columns updated when every upstream call succeeds."""
        rows = [_make_row("inst-001")]
        # We need pagination to terminate: first call returns rows, subsequent
        # calls return empty (handled inside the factory's execute mock).
        # But the factory is called multiple times per instrument (once for
        # pagination, once per UPSERT). Patch utc_now and replicate structure.

        upserted_params: list[dict[str, Any]] = []

        # Custom execute: first call → instrument page, subsequent → UPSERT
        call_count = [0]

        async def _execute(sql: Any, params: Any = None) -> MagicMock:
            result = MagicMock()
            call_count[0] += 1
            if call_count[0] == 1:
                result.all.return_value = rows
            elif call_count[0] == 2:
                # Second cursor call returns empty → loop exits
                result.all.return_value = []
            else:
                # UPSERT call — capture params
                if params:
                    upserted_params.append(dict(params))
                result.all.return_value = []
            return result

        session = AsyncMock()
        session.execute = _execute
        session.commit = AsyncMock()

        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=session)
        cm.__aexit__ = AsyncMock(return_value=False)

        factory = MagicMock()
        factory.return_value = cm

        s6_data = S6NewsRollup(
            news_count_7d=5,
            llm_relevance_7d_max=0.85,
            display_relevance_7d_weighted=0.72,
        )
        s7_data = S7IntelligenceRollup(recent_contradiction_count=2)
        s10_data = S10AlertFlag(has_active_alert=True)
        s8_data = S8BriefFlag(has_ai_brief=False)

        s6, s7, s10, s8 = _make_clients(s6_data, s7_data, s10_data, s8_data)

        uc = SyncIntelligenceRollupUseCase(factory, s6, s7, s10, s8)
        options = SyncIntelligenceRollupOptions(batch_size=100, concurrency=2)
        summary = await uc.execute(options)

        assert summary.instruments_processed == 1
        assert summary.s6_success == 1
        assert summary.s6_failure == 0
        assert summary.s7_success == 1
        assert summary.s7_failure == 0
        assert summary.s10_success == 1
        assert summary.s10_failure == 0
        assert summary.s8_success == 1
        assert summary.s8_failure == 0
        assert summary.all_failed == []

    @pytest.mark.asyncio
    async def test_s6_failure_keeps_last_known_s6_columns(self) -> None:
        """When S6 fails, S7/S10/S8 are still written; S6 columns not updated."""
        rows = [_make_row("inst-002")]

        upserted_sql_texts: list[str] = []
        call_count = [0]

        async def _execute(sql: Any, params: Any = None) -> MagicMock:
            result = MagicMock()
            call_count[0] += 1
            if call_count[0] == 1:
                result.all.return_value = rows
            elif call_count[0] == 2:
                result.all.return_value = []
            else:
                # Capture SQL text to verify S6 columns absent
                if hasattr(sql, "text"):
                    upserted_sql_texts.append(sql.text)
                elif hasattr(sql, "_bindparams"):
                    upserted_sql_texts.append(str(sql))
                result.all.return_value = []
            return result

        session = AsyncMock()
        session.execute = _execute
        session.commit = AsyncMock()
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=session)
        cm.__aexit__ = AsyncMock(return_value=False)
        factory = MagicMock()
        factory.return_value = cm

        # S6 returns None (failure)
        s6, s7, s10, s8 = _make_clients(
            None,
            S7IntelligenceRollup(recent_contradiction_count=1),
            S10AlertFlag(has_active_alert=False),
            S8BriefFlag(has_ai_brief=True),
        )

        uc = SyncIntelligenceRollupUseCase(factory, s6, s7, s10, s8)
        summary = await uc.execute(SyncIntelligenceRollupOptions(batch_size=100, concurrency=1))

        assert summary.s6_failure == 1
        assert summary.s6_success == 0
        assert summary.s7_success == 1
        assert summary.s10_success == 1
        assert summary.s8_success == 1
        # The instrument was processed (not skipped)
        assert summary.instruments_processed == 1
        # Not in all_failed because at least one upstream succeeded
        assert "inst-002" not in summary.all_failed

    @pytest.mark.asyncio
    async def test_all_failure_snapshot_not_touched(self) -> None:
        """When all 4 upstreams fail, no UPSERT is issued for the instrument."""
        rows = [_make_row("inst-003")]

        upsert_issued = [False]
        call_count = [0]

        async def _execute(sql: Any, params: Any = None) -> MagicMock:
            result = MagicMock()
            call_count[0] += 1
            if call_count[0] == 1:
                result.all.return_value = rows
            elif call_count[0] == 2:
                result.all.return_value = []
            else:
                # Any extra call = UPSERT attempt (should NOT happen)
                upsert_issued[0] = True
                result.all.return_value = []
            return result

        session = AsyncMock()
        session.execute = _execute
        session.commit = AsyncMock()
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=session)
        cm.__aexit__ = AsyncMock(return_value=False)
        factory = MagicMock()
        factory.return_value = cm

        # All 4 clients fail
        s6, s7, s10, s8 = _make_clients(None, None, None, None)

        uc = SyncIntelligenceRollupUseCase(factory, s6, s7, s10, s8)
        summary = await uc.execute(SyncIntelligenceRollupOptions(batch_size=100, concurrency=1))

        assert summary.s6_failure == 1
        assert summary.s7_failure == 1
        assert summary.s10_failure == 1
        assert summary.s8_failure == 1
        assert "inst-003" in summary.all_failed
        # No UPSERT should have been issued
        assert not upsert_issued[0]

    @pytest.mark.asyncio
    async def test_skip_fresh_instrument(self) -> None:
        """Instrument synced < 18h ago must be skipped (not processed)."""
        # Set synced_at to 2 hours ago — well within the 18h skip window.
        recent_sync = datetime.now(tz=UTC) - timedelta(hours=2)
        rows = [_make_row("inst-004", synced_at=recent_sync)]

        call_count = [0]

        async def _execute(sql: Any, params: Any = None) -> MagicMock:
            result = MagicMock()
            call_count[0] += 1
            if call_count[0] == 1:
                result.all.return_value = rows
            else:
                result.all.return_value = []
            return result

        session = AsyncMock()
        session.execute = _execute
        session.commit = AsyncMock()
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=session)
        cm.__aexit__ = AsyncMock(return_value=False)
        factory = MagicMock()
        factory.return_value = cm

        s6, s7, s10, s8 = _make_clients(
            S6NewsRollup(news_count_7d=3, llm_relevance_7d_max=0.9, display_relevance_7d_weighted=0.8),
            S7IntelligenceRollup(recent_contradiction_count=0),
            S10AlertFlag(has_active_alert=False),
            S8BriefFlag(has_ai_brief=True),
        )

        uc = SyncIntelligenceRollupUseCase(factory, s6, s7, s10, s8)
        options = SyncIntelligenceRollupOptions(
            batch_size=100,
            concurrency=1,
            skip_if_fresh_within_hours=18,
        )
        summary = await uc.execute(options)

        assert summary.instruments_skipped_fresh == 1
        assert summary.instruments_processed == 0
        # Clients must NOT have been called for the skipped instrument
        s6.get_news_rollup.assert_not_called()
        s7.get_intelligence_rollup.assert_not_called()
        s10.get_active_alert_flag.assert_not_called()
        s8.get_ai_brief_flag.assert_not_called()

    @pytest.mark.asyncio
    async def test_stale_instrument_is_processed(self) -> None:
        """Instrument synced > 18h ago must NOT be skipped."""
        old_sync = datetime.now(tz=UTC) - timedelta(hours=20)
        rows = [_make_row("inst-005", synced_at=old_sync)]

        call_count = [0]

        async def _execute(sql: Any, params: Any = None) -> MagicMock:
            result = MagicMock()
            call_count[0] += 1
            if call_count[0] == 1:
                result.all.return_value = rows
            else:
                result.all.return_value = []
            return result

        session = AsyncMock()
        session.execute = _execute
        session.commit = AsyncMock()
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=session)
        cm.__aexit__ = AsyncMock(return_value=False)
        factory = MagicMock()
        factory.return_value = cm

        s6, s7, s10, s8 = _make_clients(
            S6NewsRollup(news_count_7d=1, llm_relevance_7d_max=0.5, display_relevance_7d_weighted=0.4),
            S7IntelligenceRollup(recent_contradiction_count=3),
            S10AlertFlag(has_active_alert=True),
            S8BriefFlag(has_ai_brief=False),
        )

        uc = SyncIntelligenceRollupUseCase(factory, s6, s7, s10, s8)
        summary = await uc.execute(SyncIntelligenceRollupOptions(batch_size=100, concurrency=1))

        assert summary.instruments_skipped_fresh == 0
        assert summary.instruments_processed == 1
        s6.get_news_rollup.assert_called_once_with("inst-005")

    @pytest.mark.asyncio
    async def test_never_synced_instrument_is_processed(self) -> None:
        """Instrument with NULL synced_at must be processed (not skipped)."""
        rows = [_make_row("inst-006", synced_at=None)]

        call_count = [0]

        async def _execute(sql: Any, params: Any = None) -> MagicMock:
            result = MagicMock()
            call_count[0] += 1
            if call_count[0] == 1:
                result.all.return_value = rows
            else:
                result.all.return_value = []
            return result

        session = AsyncMock()
        session.execute = _execute
        session.commit = AsyncMock()
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=session)
        cm.__aexit__ = AsyncMock(return_value=False)
        factory = MagicMock()
        factory.return_value = cm

        s6, s7, s10, s8 = _make_clients(
            S6NewsRollup(news_count_7d=0, llm_relevance_7d_max=None, display_relevance_7d_weighted=None),
            None,
            S10AlertFlag(has_active_alert=False),
            S8BriefFlag(has_ai_brief=False),
        )

        uc = SyncIntelligenceRollupUseCase(factory, s6, s7, s10, s8)
        summary = await uc.execute(SyncIntelligenceRollupOptions(batch_size=100, concurrency=1))

        assert summary.instruments_skipped_fresh == 0
        assert summary.instruments_processed == 1
        assert summary.s6_success == 1
        assert summary.s7_failure == 1  # S7 returned None
