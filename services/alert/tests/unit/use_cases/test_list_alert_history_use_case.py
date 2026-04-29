"""Unit tests for ListAlertHistoryUseCase (PLAN-0051 T-D-4-02).

Covers: status/severity/entity/date filters delegated to repo, pagination
clamps, tenant isolation, unknown-status fallback.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from alert.application.use_cases.list_alert_history import MAX_LIMIT, ListAlertHistoryUseCase
from alert.domain.enums import AlertSeverity


def _make_uc() -> tuple[ListAlertHistoryUseCase, AsyncMock]:
    repo = AsyncMock()
    repo.list_history = AsyncMock(return_value=[])
    # QA-iter1 C-3: use case now also calls count_history to drive canonical
    # pagination. Default to 0 so tests that don't care about totals don't
    # need to wire it up explicitly.
    repo.count_history = AsyncMock(return_value=0)
    uc = ListAlertHistoryUseCase(alert_repo=repo)  # type: ignore[arg-type]
    return uc, repo


@pytest.mark.unit
class TestListAlertHistoryUseCase:
    @pytest.mark.parametrize("status", ["active", "acknowledged", "snoozed", "all"])
    async def test_status_filter_passed_through(self, status: str) -> None:
        """Each valid status enum value is forwarded to the repo unchanged."""
        tenant_id = uuid4()
        uc, repo = _make_uc()

        await uc.execute(tenant_id, status=status)

        kwargs = repo.list_history.await_args.kwargs
        assert kwargs["status"] == status

    async def test_severity_filter_passed_to_repo(self) -> None:
        """Severity enum forwards to repo verbatim."""
        tenant_id = uuid4()
        uc, repo = _make_uc()

        await uc.execute(tenant_id, severity=AlertSeverity.HIGH)

        kwargs = repo.list_history.await_args.kwargs
        assert kwargs["severity"] is AlertSeverity.HIGH

    async def test_date_range_filter_passed_to_repo(self) -> None:
        """from_dt / to_dt forward to repo."""
        tenant_id = uuid4()
        from_dt = datetime.now(UTC) - timedelta(days=7)
        to_dt = datetime.now(UTC)

        uc, repo = _make_uc()
        await uc.execute(tenant_id, from_dt=from_dt, to_dt=to_dt)

        kwargs = repo.list_history.await_args.kwargs
        assert kwargs["from_dt"] == from_dt
        assert kwargs["to_dt"] == to_dt

    async def test_entity_id_filter_passed_to_repo(self) -> None:
        """entity_id is forwarded to repo for the JOIN-side filter."""
        tenant_id = uuid4()
        entity_id = uuid4()

        uc, repo = _make_uc()
        await uc.execute(tenant_id, entity_id=entity_id)

        kwargs = repo.list_history.await_args.kwargs
        assert kwargs["entity_id"] == entity_id

    async def test_pagination_limit_offset_forwarded(self) -> None:
        """limit + offset arrive at the repo unchanged when within bounds."""
        tenant_id = uuid4()
        uc, repo = _make_uc()

        await uc.execute(tenant_id, limit=25, offset=50)

        kwargs = repo.list_history.await_args.kwargs
        assert kwargs["limit"] == 25
        assert kwargs["offset"] == 50

    async def test_limit_clamped_to_max(self) -> None:
        """Out-of-bounds limit is clamped to MAX_LIMIT (defence-in-depth)."""
        tenant_id = uuid4()
        uc, repo = _make_uc()

        await uc.execute(tenant_id, limit=MAX_LIMIT * 10, offset=-3)

        kwargs = repo.list_history.await_args.kwargs
        assert kwargs["limit"] == MAX_LIMIT
        # Negative offset must clamp to 0.
        assert kwargs["offset"] == 0

    async def test_tenant_isolation_in_repo_call(self) -> None:
        """The use case forwards the *caller's* tenant_id, not anything else."""
        tenant_id = uuid4()
        uc, repo = _make_uc()

        await uc.execute(tenant_id)

        # tenant_id is the first positional arg to list_history.
        assert repo.list_history.await_args.args[0] == tenant_id

    async def test_unknown_status_falls_back_to_all(self) -> None:
        """Unrecognised status string is normalised to 'all' (forward-compat)."""
        tenant_id = uuid4()
        uc, repo = _make_uc()

        await uc.execute(tenant_id, status="garbage-value")

        kwargs = repo.list_history.await_args.kwargs
        assert kwargs["status"] == "all"

    async def test_returns_rows_and_universe_total(self) -> None:
        """QA-iter1 C-3: total returned must be the universe count, not page size.

        With page_size=10 and 100 matching rows, ``total`` must equal 100 so
        the frontend can render "Load more" — not 10 (the page row count).
        """
        from datetime import datetime as _dt

        from alert.domain.entities import Alert
        from alert.domain.enums import AlertSeverity, AlertType

        def _row(i: int) -> Alert:
            return Alert(
                alert_id=uuid4(),
                entity_id=uuid4(),
                alert_type=AlertType.SIGNAL,
                severity=AlertSeverity.HIGH,
                source_event_id=uuid4(),
                source_topic="t",
                payload={},
                dedup_key=f"k{i}",
                created_at=_dt.now(tz=UTC),
                tenant_id=uuid4(),
            )

        tenant_id = uuid4()
        uc, repo = _make_uc()
        # 10 rows on the page, 123 in the universe
        repo.list_history = AsyncMock(return_value=[_row(i) for i in range(10)])
        repo.count_history = AsyncMock(return_value=123)

        rows, total = await uc.execute(tenant_id, limit=10, offset=0)

        assert len(rows) == 10
        assert total == 123  # universe — proves "Load more" can render

    async def test_count_history_receives_same_filters(self) -> None:
        """count_history must mirror list_history's filter args exactly.

        WHY this matters: if count omitted (e.g.) the severity filter, the
        universe size would over-count and "Load more" would render forever.
        """
        from datetime import datetime as _dt
        from datetime import timedelta

        tenant_id = uuid4()
        entity_id = uuid4()
        from_dt = _dt.now(tz=UTC) - timedelta(days=2)
        to_dt = _dt.now(tz=UTC)
        uc, repo = _make_uc()

        await uc.execute(
            tenant_id,
            status="acknowledged",
            severity=AlertSeverity.HIGH,
            entity_id=entity_id,
            from_dt=from_dt,
            to_dt=to_dt,
            limit=25,
            offset=50,
        )

        # The same filter kwargs (sans limit/offset) must be present on
        # count_history — anything else would make ``total`` inconsistent
        # with the page rows.
        list_kwargs = repo.list_history.await_args.kwargs
        count_kwargs = repo.count_history.await_args.kwargs
        for key in ("status", "severity", "entity_id", "from_dt", "to_dt"):
            assert list_kwargs[key] == count_kwargs[key], f"filter {key!r} drifted between list and count"
        # And count must NOT receive limit/offset.
        assert "limit" not in count_kwargs
        assert "offset" not in count_kwargs
