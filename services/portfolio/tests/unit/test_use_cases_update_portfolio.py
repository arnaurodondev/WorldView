"""Unit tests for UpdatePortfolioUseCase — PLAN-0114 W6 / T-W6-07.

Tests:
- PATCH with cost_basis_method="AVCO" persists the value on the portfolio.
- PATCH with cost_basis_method=None is a no-op (no-change path).
- PATCH on a portfolio owned by another user raises AuthorizationError.
- PATCH on a missing portfolio raises PortfolioNotFoundError.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from portfolio.application.ports.repositories import (
    OutboxRecord,
    OutboxRepository,
    PortfolioRepository,
)
from portfolio.application.ports.unit_of_work import UnitOfWork
from portfolio.application.use_cases.portfolio_ops import (
    UpdatePortfolioCommand,
    UpdatePortfolioUseCase,
)
from portfolio.domain.entities.portfolio import Portfolio
from portfolio.domain.enums import CostBasisMethod, PortfolioKind, PortfolioStatus
from portfolio.domain.errors import AuthorizationError, PortfolioNotFoundError

pytestmark = pytest.mark.unit

# ── Fixtures ─────────────────────────────────────────────────────────────────

_NOW = datetime(2026, 6, 20, tzinfo=UTC)
_TENANT_ID = uuid4()
_OWNER_ID = uuid4()
_OTHER_OWNER_ID = uuid4()


def _make_portfolio(**kwargs) -> Portfolio:
    defaults: dict = {
        "id": uuid4(),
        "tenant_id": _TENANT_ID,
        "owner_id": _OWNER_ID,
        "name": "Test Portfolio",
        "currency": "USD",
        "status": PortfolioStatus.ACTIVE,
        "kind": PortfolioKind.MANUAL,
        "created_at": _NOW,
        "cost_basis_method": CostBasisMethod.FIFO,
    }
    defaults.update(kwargs)
    return Portfolio(**defaults)


# ── Minimal fake repos ────────────────────────────────────────────────────────


class _FakePortfolioRepo(PortfolioRepository):
    """In-memory portfolio repo that records save() calls."""

    def __init__(self, portfolio: Portfolio) -> None:
        self._portfolio = portfolio
        self.saved: list[Portfolio] = []

    async def get(self, portfolio_id, tenant_id):
        if self._portfolio.id == portfolio_id and self._portfolio.tenant_id == tenant_id:
            return self._portfolio
        return None

    async def save(self, portfolio):
        # Mutate in place (mirrors SQLAlchemy behaviour in tests) and record.
        self._portfolio = portfolio
        self.saved.append(portfolio)

    # Required abstract methods (not exercised by these tests).
    async def list_by_owner(self, owner_id, tenant_id, limit=100, offset=0):
        return [self._portfolio], 1

    async def find_root_by_owner(self, owner_id, tenant_id):
        return None

    async def list_non_root_active_ids_by_owner(self, owner_id, tenant_id):
        return []

    async def list_all_non_root_active(self):
        return []

    async def list_active_root(self):
        return []

    async def find_by_idempotency_key(self, tenant_id, idempotency_key):
        return None


class _FakeOutboxRepo(OutboxRepository):
    def __init__(self) -> None:
        self.saved: list[OutboxRecord] = []

    async def save(self, record):
        self.saved.append(record)

    async def claim_batch(self, worker_id, lease_seconds, batch_size):
        return []

    async def mark_published(self, record_id): ...
    async def increment_attempts(self, record_id): ...
    async def move_to_dead_letter(self, record_id): ...


class _FakeUoW(UnitOfWork):
    """Minimal unit of work that only wires portfolios + outbox."""

    def __init__(self, portfolio: Portfolio) -> None:
        self._portfolios_repo = _FakePortfolioRepo(portfolio)
        self._outbox_repo = _FakeOutboxRepo()
        self._committed = False

    @property
    def portfolios(self):
        return self._portfolios_repo

    @property
    def outbox(self):
        return self._outbox_repo

    async def commit(self):
        self._committed = True

    async def rollback(self):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    # Stubs for unused abstract properties / methods.
    # We stub every abstract member UnitOfWork declares so Python's ABC
    # machinery allows instantiation. The tests only exercise portfolios+outbox.
    @property
    def tenants(self):
        return None  # type: ignore[return-value]

    @property
    def users(self):
        return None  # type: ignore[return-value]

    @property
    def instruments(self):
        return None  # type: ignore[return-value]

    @property
    def transactions(self):
        return None  # type: ignore[return-value]

    @property
    def holdings(self):
        return None  # type: ignore[return-value]

    @property
    def idempotency(self):
        return None  # type: ignore[return-value]

    @property
    def watchlists(self):
        return None  # type: ignore[return-value]

    @property
    def watchlist_members(self):
        return None  # type: ignore[return-value]

    @property
    def alert_preferences(self):
        return None  # type: ignore[return-value]

    @property
    def brokerage_connections(self):
        return None  # type: ignore[return-value]

    @property
    def brokerage_sync_errors(self):
        return None  # type: ignore[return-value]

    @property
    def portfolio_value_snapshots(self):
        return None  # type: ignore[return-value]

    @property
    def notification_preferences(self):
        return None  # type: ignore[return-value]

    @property
    def feedback_submissions(self):
        return None  # type: ignore[return-value]

    @property
    def nps_scores(self):
        return None  # type: ignore[return-value]

    @property
    def feature_requests(self):
        return None  # type: ignore[return-value]

    @property
    def feature_votes(self):
        return None  # type: ignore[return-value]

    @property
    def micro_survey_responses(self):
        return None  # type: ignore[return-value]

    # Some UoW versions name this micro_surveys:
    @property
    def micro_surveys(self):
        return None  # type: ignore[return-value]

    @property
    def entity_suppressions(self):
        return None  # type: ignore[return-value]

    @property
    def invitations(self):
        return None  # type: ignore[return-value]

    @property
    def tenant_user_roles(self):
        return None  # type: ignore[return-value]

    @property
    def auth_audit_logs(self):
        return None  # type: ignore[return-value]

    @property
    def auth_audit_log(self):
        return None  # type: ignore[return-value]

    @property
    def beta_enrollments(self):
        return None  # type: ignore[return-value]

    async def flush(self) -> None:
        pass


# ── Tests ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_patch_cost_basis_method_avco_persists():
    """PATCH with cost_basis_method=AVCO changes the field and commits."""
    portfolio = _make_portfolio(cost_basis_method=CostBasisMethod.FIFO)
    uow = _FakeUoW(portfolio)
    uc = UpdatePortfolioUseCase()

    result = await uc.execute(
        UpdatePortfolioCommand(
            portfolio_id=portfolio.id,
            owner_id=_OWNER_ID,
            tenant_id=_TENANT_ID,
            cost_basis_method=CostBasisMethod.AVCO,
        ),
        uow,
    )

    # Domain entity reflects the new method.
    assert result.cost_basis_method == CostBasisMethod.AVCO
    # save() was called exactly once.
    assert len(uow._portfolios_repo.saved) == 1
    assert uow._portfolios_repo.saved[0].cost_basis_method == CostBasisMethod.AVCO
    # commit() was called (change was actually persisted).
    assert uow._committed is True


@pytest.mark.asyncio
async def test_patch_no_op_when_method_unchanged():
    """PATCH with the same method that's already set is a no-op (no save, no commit)."""
    portfolio = _make_portfolio(cost_basis_method=CostBasisMethod.FIFO)
    uow = _FakeUoW(portfolio)
    uc = UpdatePortfolioUseCase()

    result = await uc.execute(
        UpdatePortfolioCommand(
            portfolio_id=portfolio.id,
            owner_id=_OWNER_ID,
            tenant_id=_TENANT_ID,
            # Same method as the current value — no change needed.
            cost_basis_method=CostBasisMethod.FIFO,
        ),
        uow,
    )

    # Portfolio returned unchanged.
    assert result.cost_basis_method == CostBasisMethod.FIFO
    # save() and commit() were NOT called (no diff to persist).
    assert len(uow._portfolios_repo.saved) == 0
    assert uow._committed is False


@pytest.mark.asyncio
async def test_patch_none_cost_basis_method_is_no_op():
    """PATCH with cost_basis_method=None does not touch the field."""
    portfolio = _make_portfolio(cost_basis_method=CostBasisMethod.AVCO)
    uow = _FakeUoW(portfolio)
    uc = UpdatePortfolioUseCase()

    result = await uc.execute(
        UpdatePortfolioCommand(
            portfolio_id=portfolio.id,
            owner_id=_OWNER_ID,
            tenant_id=_TENANT_ID,
            cost_basis_method=None,  # None = "do not change"
        ),
        uow,
    )

    assert result.cost_basis_method == CostBasisMethod.AVCO
    assert len(uow._portfolios_repo.saved) == 0


@pytest.mark.asyncio
async def test_patch_wrong_owner_raises_authorization_error():
    """PATCH on a portfolio owned by another user raises AuthorizationError."""
    portfolio = _make_portfolio(owner_id=_OWNER_ID)
    uow = _FakeUoW(portfolio)
    uc = UpdatePortfolioUseCase()

    with pytest.raises(AuthorizationError):
        await uc.execute(
            UpdatePortfolioCommand(
                portfolio_id=portfolio.id,
                owner_id=_OTHER_OWNER_ID,  # wrong owner
                tenant_id=_TENANT_ID,
                cost_basis_method=CostBasisMethod.AVCO,
            ),
            uow,
        )


@pytest.mark.asyncio
async def test_patch_missing_portfolio_raises_not_found():
    """PATCH on a non-existent portfolio raises PortfolioNotFoundError."""
    portfolio = _make_portfolio()
    uow = _FakeUoW(portfolio)
    uc = UpdatePortfolioUseCase()

    with pytest.raises(PortfolioNotFoundError):
        await uc.execute(
            UpdatePortfolioCommand(
                portfolio_id=uuid4(),  # unknown UUID
                owner_id=_OWNER_ID,
                tenant_id=_TENANT_ID,
                cost_basis_method=CostBasisMethod.AVCO,
            ),
            uow,
        )
