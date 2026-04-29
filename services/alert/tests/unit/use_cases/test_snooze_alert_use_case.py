"""Unit tests for SnoozeAlertUseCase (PLAN-0051 T-D-4-02).

Covers: validation (past, naive, >30d), tenant isolation, missing alert,
successful snooze with commit + re-read.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from alert.application.use_cases.snooze_alert import MAX_SNOOZE_DAYS, SnoozeAlertUseCase
from alert.domain.entities import Alert
from alert.domain.enums import AlertSeverity, AlertType


def _make_alert(tenant_id: UUID | None) -> Alert:
    return Alert(
        alert_id=uuid4(),
        entity_id=uuid4(),
        alert_type=AlertType.SIGNAL,
        severity=AlertSeverity.HIGH,
        source_event_id=uuid4(),
        source_topic="nlp.signal.detected.v1",
        payload={},
        dedup_key="dk",
        created_at=datetime.now(UTC),
        tenant_id=tenant_id,
    )


def _make_uc() -> tuple[SnoozeAlertUseCase, AsyncMock, AsyncMock]:
    repo = AsyncMock()
    session = AsyncMock()
    uc = SnoozeAlertUseCase(alert_repo=repo, session=session)  # type: ignore[arg-type]
    return uc, repo, session


@pytest.mark.unit
class TestSnoozeAlertUseCase:
    async def test_successful_snooze_persists_and_commits(self) -> None:
        """Valid future snooze writes ``snooze_until`` and commits."""
        tenant_id = uuid4()
        alert = _make_alert(tenant_id=tenant_id)
        until = datetime.now(UTC) + timedelta(hours=4)

        uc, repo, session = _make_uc()
        # First get_by_id returns the existing alert (pre-snooze); second
        # returns the updated row after commit.
        repo.get_by_id = AsyncMock(side_effect=[alert, alert])
        repo.snooze = AsyncMock(return_value=True)

        outcome, returned = await uc.execute(alert.alert_id, until, tenant_id)

        assert outcome == "ok"
        assert returned is alert
        repo.snooze.assert_awaited_once()
        # Validate the timestamp passed to repo is the same target time (UTC)
        passed_until = repo.snooze.await_args.args[1]
        assert passed_until == until
        session.commit.assert_awaited_once()

    async def test_past_datetime_rejected_as_invalid(self) -> None:
        """A snooze_until in the past returns ('invalid', None) — no DB calls."""
        tenant_id = uuid4()
        past = datetime.now(UTC) - timedelta(minutes=1)

        uc, repo, session = _make_uc()
        # Even if get_by_id were called we'd want it not to matter.
        repo.get_by_id = AsyncMock(return_value=_make_alert(tenant_id))

        outcome, ret = await uc.execute(uuid4(), past, tenant_id)

        assert outcome == "invalid"
        assert ret is None
        # Validation must short-circuit BEFORE any DB read/write.
        repo.get_by_id.assert_not_awaited()
        repo.snooze.assert_not_awaited()
        session.commit.assert_not_awaited()

    async def test_naive_datetime_rejected_as_invalid(self) -> None:
        """A naive datetime (no tzinfo) is rejected — UTC-only invariant."""
        # Build naive datetime explicitly; using datetime.utcnow() would also
        # yield a naive value but DTZ001 lints flag it.
        naive = datetime(2099, 1, 1, 12, 0, 0)  # noqa: DTZ001 — testing naive-rejection

        uc, _repo, session = _make_uc()
        outcome, ret = await uc.execute(uuid4(), naive, uuid4())

        assert outcome == "invalid"
        assert ret is None
        session.commit.assert_not_awaited()

    async def test_more_than_30_days_rejected(self) -> None:
        """A snooze_until > MAX_SNOOZE_DAYS in the future is rejected."""
        tenant_id = uuid4()
        # +1 hour beyond the max so we don't drift into the boundary clock skew
        too_far = datetime.now(UTC) + timedelta(days=MAX_SNOOZE_DAYS, hours=1)

        uc, repo, _session = _make_uc()
        repo.get_by_id = AsyncMock(return_value=_make_alert(tenant_id))

        outcome, ret = await uc.execute(uuid4(), too_far, tenant_id)

        assert outcome == "invalid"
        assert ret is None

    async def test_tenant_isolation_returns_forbidden(self) -> None:
        """An alert owned by a different tenant returns 'forbidden'."""
        owner_tenant = uuid4()
        other_tenant = uuid4()
        alert = _make_alert(tenant_id=owner_tenant)
        until = datetime.now(UTC) + timedelta(hours=2)

        uc, repo, session = _make_uc()
        repo.get_by_id = AsyncMock(return_value=alert)

        outcome, ret = await uc.execute(alert.alert_id, until, other_tenant)

        assert outcome == "forbidden"
        assert ret is None
        repo.snooze.assert_not_awaited()
        session.commit.assert_not_awaited()

    async def test_missing_alert_returns_not_found(self) -> None:
        """Unknown alert id → ('not_found', None) without writes."""
        until = datetime.now(UTC) + timedelta(hours=2)

        uc, repo, session = _make_uc()
        repo.get_by_id = AsyncMock(return_value=None)

        outcome, ret = await uc.execute(uuid4(), until, uuid4())

        assert outcome == "not_found"
        assert ret is None
        repo.snooze.assert_not_awaited()
        session.commit.assert_not_awaited()

    async def test_alert_with_null_tenant_is_forbidden_for_snooze(self) -> None:
        """QA-iter1 MAJ-1: NULL tenant_id alerts MUST be forbidden for snooze.

        Symmetric with acknowledge_alert — NULL-tenant rows are filtered out
        of tenant-scoped reads, so allowing snooze was a tenant isolation
        bypass for legacy alerts.
        """
        until = datetime.now(UTC) + timedelta(hours=2)
        alert = _make_alert(tenant_id=None)

        uc, repo, session = _make_uc()
        repo.get_by_id = AsyncMock(return_value=alert)

        outcome, ret = await uc.execute(alert.alert_id, until, uuid4())

        assert outcome == "forbidden"
        assert ret is None
        repo.snooze.assert_not_awaited()
        session.commit.assert_not_awaited()

    async def test_non_utc_tz_normalized_to_utc(self) -> None:
        """A datetime in another tz is converted to UTC before persisting."""
        from datetime import timezone

        tenant_id = uuid4()
        alert = _make_alert(tenant_id=tenant_id)
        # Build an aware datetime in UTC+5 a few hours ahead.
        plus_five = timezone(timedelta(hours=5))
        target_local = (datetime.now(UTC) + timedelta(hours=4)).astimezone(plus_five)

        uc, repo, _session = _make_uc()
        repo.get_by_id = AsyncMock(side_effect=[alert, alert])
        repo.snooze = AsyncMock(return_value=True)

        outcome, _ = await uc.execute(alert.alert_id, target_local, tenant_id)

        assert outcome == "ok"
        passed_until = repo.snooze.await_args.args[1]
        # Whatever was stored must be in UTC.
        assert passed_until.tzinfo is not None
        assert passed_until.utcoffset() == timedelta(0)
