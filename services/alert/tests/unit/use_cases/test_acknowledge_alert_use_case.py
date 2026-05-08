"""Unit tests for the alert-entity AcknowledgeAlertUseCase (PLAN-0051 T-D-4-02).

Covers: idempotency, tenant isolation, missing alert, ack metadata persistence,
race-condition handling.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from alert.application.use_cases.acknowledge_alert import AcknowledgeAlertUseCase
from alert.domain.entities import Alert
from alert.domain.enums import AlertSeverity, AlertType

pytestmark = pytest.mark.unit


def _make_alert(
    *,
    tenant_id: UUID | None,
    acknowledged_at: datetime | None = None,
    acknowledged_by_user_id: UUID | None = None,
) -> Alert:
    """Build a minimal Alert with the given ack state.

    Helper isolates the noisy required fields so each test reads cleanly.
    """
    return Alert(
        alert_id=uuid4(),
        entity_id=uuid4(),
        alert_type=AlertType.SIGNAL,
        severity=AlertSeverity.MEDIUM,
        source_event_id=uuid4(),
        source_topic="nlp.signal.detected.v1",
        payload={},
        dedup_key="dk",
        created_at=datetime.now(UTC),
        tenant_id=tenant_id,
        acknowledged_at=acknowledged_at,
        acknowledged_by_user_id=acknowledged_by_user_id,
    )


def _make_uc() -> tuple[AcknowledgeAlertUseCase, AsyncMock, AsyncMock]:
    """Wire the use case with mocked repo + session and return all three."""
    repo = AsyncMock()
    session = AsyncMock()
    uc = AcknowledgeAlertUseCase(alert_repo=repo, session=session)  # type: ignore[arg-type]
    return uc, repo, session


@pytest.mark.unit
class TestAcknowledgeAlertUseCase:
    async def test_successful_ack_writes_metadata(self) -> None:
        """First-time ack writes acknowledged_at + user_id and commits."""
        tenant_id = uuid4()
        user_id = uuid4()
        before = _make_alert(tenant_id=tenant_id)
        # After ack, the persisted row carries ack metadata. The mock returns
        # `before` on the first get_by_id (use case checks ack state) and
        # `after` on the post-commit re-read (use case returns canonical state).
        after = _make_alert(
            tenant_id=tenant_id,
            acknowledged_at=datetime.now(UTC),
            acknowledged_by_user_id=user_id,
        )

        uc, repo, session = _make_uc()
        repo.get_by_id = AsyncMock(side_effect=[before, after])
        repo.acknowledge = AsyncMock(return_value=True)

        outcome, alert = await uc.execute(before.alert_id, user_id, tenant_id)

        assert outcome == "ok"
        assert alert is after
        repo.acknowledge.assert_awaited_once_with(before.alert_id, user_id)
        session.commit.assert_awaited_once()

    async def test_repeat_ack_is_idempotent(self) -> None:
        """When alert is already acked, no UPDATE/COMMIT happens; original metadata preserved."""
        tenant_id = uuid4()
        original_ack_user = uuid4()
        original_ack_time = datetime.now(UTC)
        already_acked = _make_alert(
            tenant_id=tenant_id,
            acknowledged_at=original_ack_time,
            acknowledged_by_user_id=original_ack_user,
        )

        uc, repo, session = _make_uc()
        repo.get_by_id = AsyncMock(return_value=already_acked)
        repo.acknowledge = AsyncMock(return_value=True)  # would fire if called

        # A *different* user re-acks; use case must NOT overwrite original_ack_user.
        outcome, alert = await uc.execute(already_acked.alert_id, uuid4(), tenant_id)

        assert outcome == "already"
        assert alert is already_acked
        # The ack_at/user must remain unchanged because no write happened.
        assert alert is not None and alert.acknowledged_by_user_id == original_ack_user
        assert alert.acknowledged_at == original_ack_time
        repo.acknowledge.assert_not_awaited()
        session.commit.assert_not_awaited()

    async def test_missing_alert_returns_not_found(self) -> None:
        """When the alert id is unknown, the use case returns ('not_found', None)."""
        uc, repo, session = _make_uc()
        repo.get_by_id = AsyncMock(return_value=None)

        outcome, alert = await uc.execute(uuid4(), uuid4(), uuid4())

        assert outcome == "not_found"
        assert alert is None
        session.commit.assert_not_awaited()

    async def test_tenant_isolation_returns_forbidden(self) -> None:
        """When the alert's tenant differs from caller's, return ('forbidden', None)."""
        owner_tenant = uuid4()
        other_tenant = uuid4()
        alert = _make_alert(tenant_id=owner_tenant)

        uc, repo, session = _make_uc()
        repo.get_by_id = AsyncMock(return_value=alert)

        outcome, ret = await uc.execute(alert.alert_id, uuid4(), other_tenant)

        assert outcome == "forbidden"
        assert ret is None
        session.commit.assert_not_awaited()

    async def test_sets_acknowledged_by_user_id_correctly(self) -> None:
        """The acknowledger's user_id is forwarded verbatim to the repo."""
        tenant_id = uuid4()
        user_id = uuid4()
        before = _make_alert(tenant_id=tenant_id)
        after = _make_alert(
            tenant_id=tenant_id,
            acknowledged_at=datetime.now(UTC),
            acknowledged_by_user_id=user_id,
        )

        uc, repo, _session = _make_uc()
        repo.get_by_id = AsyncMock(side_effect=[before, after])
        repo.acknowledge = AsyncMock(return_value=True)

        await uc.execute(before.alert_id, user_id, tenant_id)

        # Inspect the kwargs/args the repo was actually called with.
        call = repo.acknowledge.await_args
        assert call.args[0] == before.alert_id
        assert call.args[1] == user_id  # exact user — not None, not anyone else

    async def test_concurrent_ack_treated_as_idempotent(self) -> None:
        """Race: another writer beats us to the UPDATE; we surface 'already' not error."""
        tenant_id = uuid4()
        user_id = uuid4()
        before = _make_alert(tenant_id=tenant_id)
        # Re-read after the lost race shows another user's ack.
        winner_id = uuid4()
        winner_after = _make_alert(
            tenant_id=tenant_id,
            acknowledged_at=datetime.now(UTC),
            acknowledged_by_user_id=winner_id,
        )

        uc, repo, session = _make_uc()
        repo.get_by_id = AsyncMock(side_effect=[before, winner_after])
        # repo.acknowledge returns False — UPDATE matched zero rows because
        # another transaction already set acknowledged_at first.
        repo.acknowledge = AsyncMock(return_value=False)

        outcome, alert = await uc.execute(before.alert_id, user_id, tenant_id)

        assert outcome == "already"
        assert alert is winner_after
        session.commit.assert_not_awaited()

    async def test_alert_with_null_tenant_is_forbidden_for_ack(self) -> None:
        """QA-iter1 MAJ-1: NULL tenant_id rows MUST be forbidden for ACK.

        WHY this changed: an earlier draft allowed NULL-tenant alerts to be
        acknowledged by any caller ("legacy compat"). That was a tenant
        isolation bypass — the list endpoint filters NULL-tenant rows out of
        tenant-scoped queries, but ACK left them mutable. We now treat NULL
        tenant_id symmetrically: forbidden for mutations.
        """
        user_id = uuid4()
        before = _make_alert(tenant_id=None)

        uc, repo, session = _make_uc()
        repo.get_by_id = AsyncMock(return_value=before)
        repo.acknowledge = AsyncMock(return_value=True)  # would fire if called

        outcome, ret = await uc.execute(before.alert_id, user_id, uuid4())

        assert outcome == "forbidden"
        assert ret is None
        # Critical: no UPDATE issued — proves the isolation guard short-circuits.
        repo.acknowledge.assert_not_awaited()
        session.commit.assert_not_awaited()
