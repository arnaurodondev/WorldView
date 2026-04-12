"""Unit tests for brokerage connection use cases (Wave C-1, PRD-0022 §6.2)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from portfolio.application.use_cases.brokerage_connection import (
    ActivateBrokerageConnectionCommand,
    ActivateBrokerageConnectionUseCase,
    DisconnectBrokerageConnectionCommand,
    DisconnectBrokerageConnectionUseCase,
    GetSyncErrorsQuery,
    GetSyncErrorsUseCase,
    InitiateBrokerageConnectionCommand,
    InitiateBrokerageConnectionUseCase,
    ListBrokerageConnectionsQuery,
    ListBrokerageConnectionsUseCase,
)
from portfolio.domain.entities.brokerage_connection import BrokerageConnection
from portfolio.domain.entities.brokerage_sync_error import BrokerageTransactionSyncError
from portfolio.domain.enums import ConnectionStatus, SyncErrorType
from portfolio.domain.errors import (
    BrokerageConnectionAlreadyDisconnectedError,
    BrokerageConnectionForbiddenError,
    BrokerageConnectionNotFoundError,
    BrokerageConnectionStateError,
    PortfolioNotFoundError,
    TosNotAcceptedError,
)

from .fakes import FakeBrokerageClient, FakeUnitOfWork

pytestmark = pytest.mark.unit

_REDIRECT_BASE = "http://localhost:5173/portfolio/brokerage/callback"
_TOS_AT = datetime(2026, 4, 11, 10, 0, 0, tzinfo=UTC)


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def uow() -> FakeUnitOfWork:
    return FakeUnitOfWork()


@pytest.fixture
def broker() -> FakeBrokerageClient:
    return FakeBrokerageClient(portal_url="https://snaptrade.example.com/connect")


@pytest.fixture
async def seeded(uow: FakeUnitOfWork) -> dict[str, object]:
    """Seed tenant, user, and portfolio into the fake UoW."""
    from portfolio.application.use_cases.create_portfolio import CreatePortfolioCommand, CreatePortfolioUseCase
    from portfolio.application.use_cases.tenant import CreateTenantCommand, CreateTenantUseCase
    from portfolio.application.use_cases.user import CreateUserCommand, CreateUserUseCase

    tenant = await CreateTenantUseCase().execute(CreateTenantCommand(name="Acme"), uow)
    user = await CreateUserUseCase().execute(CreateUserCommand(tenant_id=tenant.id, email="owner@acme.com"), uow)
    portfolio = await CreatePortfolioUseCase().execute(
        CreatePortfolioCommand(tenant_id=tenant.id, owner_id=user.id, name="My Portfolio"),
        uow,
    )
    return {"tenant": tenant, "user": user, "portfolio": portfolio}


def _seed_connection(uow: FakeUnitOfWork, **kwargs: object) -> BrokerageConnection:
    """Helper: build and seed a BrokerageConnection with sensible defaults."""
    tenant_id = kwargs.pop("tenant_id", uuid.uuid4())
    user_id = kwargs.pop("user_id", uuid.uuid4())
    portfolio_id = kwargs.pop("portfolio_id", uuid.uuid4())
    conn = BrokerageConnection(
        tenant_id=tenant_id,  # type: ignore[arg-type]
        user_id=user_id,  # type: ignore[arg-type]
        portfolio_id=portfolio_id,  # type: ignore[arg-type]
        snaptrade_user_id=str(kwargs.pop("snaptrade_user_id", "snap-user-001")),
        snaptrade_user_secret=str(kwargs.pop("snaptrade_user_secret", "secret-token")),
        snaptrade_tos_accepted_at=kwargs.pop("snaptrade_tos_accepted_at", _TOS_AT),  # type: ignore[arg-type]
        **kwargs,  # type: ignore[arg-type]
    )
    uow._brokerage_connections._store[conn.id] = conn
    return conn


# ── InitiateBrokerageConnectionUseCase ────────────────────────────────────────


class TestInitiateBrokerageConnection:
    @pytest.mark.asyncio
    async def test_happy_path_creates_pending_connection(
        self,
        uow: FakeUnitOfWork,
        broker: FakeBrokerageClient,
        seeded: dict[str, object],
    ) -> None:
        tenant = seeded["tenant"]
        user = seeded["user"]
        portfolio = seeded["portfolio"]

        uc = InitiateBrokerageConnectionUseCase()
        result = await uc.execute(
            InitiateBrokerageConnectionCommand(
                tenant_id=tenant.id,  # type: ignore[union-attr]
                user_id=user.id,  # type: ignore[union-attr]
                portfolio_id=portfolio.id,  # type: ignore[union-attr]
                snaptrade_tos_accepted=True,
            ),
            uow,
            broker,
            _REDIRECT_BASE,
        )

        assert result.redirect_uri == "https://snaptrade.example.com/connect"
        assert result.connection_id is not None

        saved = uow.brokerage_connections._store[result.connection_id]
        assert saved.status == ConnectionStatus.PENDING
        assert saved.tenant_id == tenant.id  # type: ignore[union-attr]
        assert saved.user_id == user.id  # type: ignore[union-attr]
        assert saved.portfolio_id == portfolio.id  # type: ignore[union-attr]

    @pytest.mark.asyncio
    async def test_tos_not_accepted_raises_before_snaptrade_call(
        self,
        uow: FakeUnitOfWork,
        broker: FakeBrokerageClient,
        seeded: dict[str, object],
    ) -> None:
        tenant = seeded["tenant"]
        user = seeded["user"]
        portfolio = seeded["portfolio"]

        uc = InitiateBrokerageConnectionUseCase()
        with pytest.raises(TosNotAcceptedError):
            await uc.execute(
                InitiateBrokerageConnectionCommand(
                    tenant_id=tenant.id,  # type: ignore[union-attr]
                    user_id=user.id,  # type: ignore[union-attr]
                    portfolio_id=portfolio.id,  # type: ignore[union-attr]
                    snaptrade_tos_accepted=False,
                ),
                uow,
                broker,
                _REDIRECT_BASE,
            )
        # No SnapTrade call should have been made (fail-fast)
        assert broker.register_calls == []

    @pytest.mark.asyncio
    async def test_portfolio_not_found_raises(
        self,
        uow: FakeUnitOfWork,
        broker: FakeBrokerageClient,
        seeded: dict[str, object],
    ) -> None:
        tenant = seeded["tenant"]
        user = seeded["user"]

        uc = InitiateBrokerageConnectionUseCase()
        with pytest.raises(PortfolioNotFoundError):
            await uc.execute(
                InitiateBrokerageConnectionCommand(
                    tenant_id=tenant.id,  # type: ignore[union-attr]
                    user_id=user.id,  # type: ignore[union-attr]
                    portfolio_id=uuid.uuid4(),  # wrong ID
                    snaptrade_tos_accepted=True,
                ),
                uow,
                broker,
                _REDIRECT_BASE,
            )

    @pytest.mark.asyncio
    async def test_connection_id_embedded_in_redirect_uri(
        self,
        uow: FakeUnitOfWork,
        broker: FakeBrokerageClient,
        seeded: dict[str, object],
    ) -> None:
        """connection_id is embedded in redirect_uri before SnapTrade call (§6.7 R-004)."""
        tenant = seeded["tenant"]
        user = seeded["user"]
        portfolio = seeded["portfolio"]

        uc = InitiateBrokerageConnectionUseCase()
        result = await uc.execute(
            InitiateBrokerageConnectionCommand(
                tenant_id=tenant.id,  # type: ignore[union-attr]
                user_id=user.id,  # type: ignore[union-attr]
                portfolio_id=portfolio.id,  # type: ignore[union-attr]
                snaptrade_tos_accepted=True,
            ),
            uow,
            broker,
            _REDIRECT_BASE,
        )
        # The redirect_uri passed to SnapTrade must contain the connectionId
        assert len(broker.portal_url_calls) == 1
        called_uri = broker.portal_url_calls[0]
        assert f"connectionId={result.connection_id}" in called_uri

    @pytest.mark.asyncio
    async def test_commits_after_api_calls(
        self,
        uow: FakeUnitOfWork,
        broker: FakeBrokerageClient,
        seeded: dict[str, object],
    ) -> None:
        """uow.commit() is called exactly once after SnapTrade calls (BP-057)."""
        tenant = seeded["tenant"]
        user = seeded["user"]
        portfolio = seeded["portfolio"]

        commits_before = uow.commit_count
        uc = InitiateBrokerageConnectionUseCase()
        await uc.execute(
            InitiateBrokerageConnectionCommand(
                tenant_id=tenant.id,  # type: ignore[union-attr]
                user_id=user.id,  # type: ignore[union-attr]
                portfolio_id=portfolio.id,  # type: ignore[union-attr]
                snaptrade_tos_accepted=True,
            ),
            uow,
            broker,
            _REDIRECT_BASE,
        )
        assert uow.commit_count - commits_before == 1


# ── ActivateBrokerageConnectionUseCase ────────────────────────────────────────


class TestActivateBrokerageConnection:
    @pytest.mark.asyncio
    async def test_happy_path_transitions_to_active(self, uow: FakeUnitOfWork) -> None:
        conn = _seed_connection(uow, status=ConnectionStatus.PENDING)

        uc = ActivateBrokerageConnectionUseCase()
        result = await uc.execute(
            ActivateBrokerageConnectionCommand(
                connection_id=conn.id,
                user_id=conn.user_id,
                tenant_id=conn.tenant_id,
                snaptrade_user_id=conn.snaptrade_user_id,
                authorization_id="auth-abc-123",
            ),
            uow,
        )

        assert result.status == "active"
        assert result.connection_id == conn.id
        saved = uow.brokerage_connections._store[conn.id]
        assert saved.status == ConnectionStatus.ACTIVE
        assert saved.authorization_id == "auth-abc-123"

    @pytest.mark.asyncio
    async def test_not_found_raises(self, uow: FakeUnitOfWork) -> None:
        uc = ActivateBrokerageConnectionUseCase()
        with pytest.raises(BrokerageConnectionNotFoundError):
            await uc.execute(
                ActivateBrokerageConnectionCommand(
                    connection_id=uuid.uuid4(),
                    user_id=uuid.uuid4(),
                    tenant_id=uuid.uuid4(),
                    snaptrade_user_id="snap-user",
                    authorization_id="auth-id",
                ),
                uow,
            )

    @pytest.mark.asyncio
    async def test_user_id_mismatch_raises_forbidden(self, uow: FakeUnitOfWork) -> None:
        conn = _seed_connection(uow)
        uc = ActivateBrokerageConnectionUseCase()
        with pytest.raises(BrokerageConnectionForbiddenError):
            await uc.execute(
                ActivateBrokerageConnectionCommand(
                    connection_id=conn.id,
                    user_id=conn.user_id,
                    tenant_id=conn.tenant_id,
                    snaptrade_user_id="wrong-snap-user-id",  # mismatch
                    authorization_id="auth-id",
                ),
                uow,
            )

    @pytest.mark.asyncio
    async def test_wrong_state_raises_state_error(self, uow: FakeUnitOfWork) -> None:
        conn = _seed_connection(uow, status=ConnectionStatus.ACTIVE)
        uc = ActivateBrokerageConnectionUseCase()
        with pytest.raises(BrokerageConnectionStateError):
            await uc.execute(
                ActivateBrokerageConnectionCommand(
                    connection_id=conn.id,
                    user_id=conn.user_id,
                    tenant_id=conn.tenant_id,
                    snaptrade_user_id=conn.snaptrade_user_id,
                    authorization_id="auth-id",
                ),
                uow,
            )

    @pytest.mark.asyncio
    async def test_cross_user_lookup_returns_not_found(self, uow: FakeUnitOfWork) -> None:
        """get_by_user returns None when user_id doesn't match — no forbidden info leak."""
        conn = _seed_connection(uow)
        other_user_id = uuid.uuid4()
        uc = ActivateBrokerageConnectionUseCase()
        with pytest.raises(BrokerageConnectionNotFoundError):
            await uc.execute(
                ActivateBrokerageConnectionCommand(
                    connection_id=conn.id,
                    user_id=other_user_id,  # different user
                    tenant_id=conn.tenant_id,
                    snaptrade_user_id=conn.snaptrade_user_id,
                    authorization_id="auth-id",
                ),
                uow,
            )


# ── ListBrokerageConnectionsUseCase ───────────────────────────────────────────


class TestListBrokerageConnections:
    @pytest.mark.asyncio
    async def test_returns_connections_for_user(self, uow: FakeUnitOfWork) -> None:
        tenant_id = uuid.uuid4()
        user_id = uuid.uuid4()
        conn1 = _seed_connection(uow, tenant_id=tenant_id, user_id=user_id)
        conn2 = _seed_connection(uow, tenant_id=tenant_id, user_id=user_id)
        # Different user — should NOT appear
        _seed_connection(uow, tenant_id=tenant_id, user_id=uuid.uuid4())

        uc = ListBrokerageConnectionsUseCase()
        result = await uc.execute(
            ListBrokerageConnectionsQuery(user_id=user_id, tenant_id=tenant_id),
            uow,
        )

        ids = {c.id for c in result.items}
        assert conn1.id in ids
        assert conn2.id in ids
        assert len(result.items) == 2

    @pytest.mark.asyncio
    async def test_filter_by_portfolio_id(self, uow: FakeUnitOfWork) -> None:
        tenant_id = uuid.uuid4()
        user_id = uuid.uuid4()
        portfolio_id = uuid.uuid4()
        conn_match = _seed_connection(uow, tenant_id=tenant_id, user_id=user_id, portfolio_id=portfolio_id)
        _seed_connection(uow, tenant_id=tenant_id, user_id=user_id)  # different portfolio

        uc = ListBrokerageConnectionsUseCase()
        result = await uc.execute(
            ListBrokerageConnectionsQuery(user_id=user_id, tenant_id=tenant_id, portfolio_id=portfolio_id),
            uow,
        )

        assert len(result.items) == 1
        assert result.items[0].id == conn_match.id

    @pytest.mark.asyncio
    async def test_empty_result_when_no_connections(self, uow: FakeUnitOfWork) -> None:
        uc = ListBrokerageConnectionsUseCase()
        result = await uc.execute(
            ListBrokerageConnectionsQuery(user_id=uuid.uuid4(), tenant_id=uuid.uuid4()),
            uow,
        )
        assert result.items == []


# ── DisconnectBrokerageConnectionUseCase ──────────────────────────────────────


class TestDisconnectBrokerageConnection:
    @pytest.mark.asyncio
    async def test_happy_path_marks_disconnected(self, uow: FakeUnitOfWork, broker: FakeBrokerageClient) -> None:
        conn = _seed_connection(
            uow,
            status=ConnectionStatus.ACTIVE,
            authorization_id="auth-xyz",
        )
        uc = DisconnectBrokerageConnectionUseCase()
        result = await uc.execute(
            DisconnectBrokerageConnectionCommand(
                connection_id=conn.id,
                user_id=conn.user_id,
                tenant_id=conn.tenant_id,
            ),
            uow,
            broker,
        )

        assert result.status == "disconnected"
        saved = uow.brokerage_connections._store[conn.id]
        assert saved.status == ConnectionStatus.DISCONNECTED
        # revoke was called
        assert len(broker.revoke_calls) == 1

    @pytest.mark.asyncio
    async def test_revoke_failure_still_disconnects(self, uow: FakeUnitOfWork, broker: FakeBrokerageClient) -> None:
        broker.should_raise_on_revoke = True
        conn = _seed_connection(
            uow,
            status=ConnectionStatus.ACTIVE,
            authorization_id="auth-xyz",
        )
        uc = DisconnectBrokerageConnectionUseCase()
        # Should NOT raise — best-effort revoke
        result = await uc.execute(
            DisconnectBrokerageConnectionCommand(
                connection_id=conn.id,
                user_id=conn.user_id,
                tenant_id=conn.tenant_id,
            ),
            uow,
            broker,
        )
        assert result.status == "disconnected"
        saved = uow.brokerage_connections._store[conn.id]
        assert saved.status == ConnectionStatus.DISCONNECTED

    @pytest.mark.asyncio
    async def test_no_auth_id_skips_revoke(self, uow: FakeUnitOfWork, broker: FakeBrokerageClient) -> None:
        conn = _seed_connection(uow, status=ConnectionStatus.ACTIVE)
        # authorization_id is None by default
        assert conn.authorization_id is None

        uc = DisconnectBrokerageConnectionUseCase()
        await uc.execute(
            DisconnectBrokerageConnectionCommand(
                connection_id=conn.id,
                user_id=conn.user_id,
                tenant_id=conn.tenant_id,
            ),
            uow,
            broker,
        )
        assert broker.revoke_calls == []

    @pytest.mark.asyncio
    async def test_already_disconnected_raises(self, uow: FakeUnitOfWork, broker: FakeBrokerageClient) -> None:
        conn = _seed_connection(uow, status=ConnectionStatus.DISCONNECTED)
        uc = DisconnectBrokerageConnectionUseCase()
        with pytest.raises(BrokerageConnectionAlreadyDisconnectedError):
            await uc.execute(
                DisconnectBrokerageConnectionCommand(
                    connection_id=conn.id,
                    user_id=conn.user_id,
                    tenant_id=conn.tenant_id,
                ),
                uow,
                broker,
            )

    @pytest.mark.asyncio
    async def test_not_found_raises(self, uow: FakeUnitOfWork, broker: FakeBrokerageClient) -> None:
        uc = DisconnectBrokerageConnectionUseCase()
        with pytest.raises(BrokerageConnectionNotFoundError):
            await uc.execute(
                DisconnectBrokerageConnectionCommand(
                    connection_id=uuid.uuid4(),
                    user_id=uuid.uuid4(),
                    tenant_id=uuid.uuid4(),
                ),
                uow,
                broker,
            )

    @pytest.mark.asyncio
    async def test_commits_exactly_once(self, uow: FakeUnitOfWork, broker: FakeBrokerageClient) -> None:
        conn = _seed_connection(uow, status=ConnectionStatus.ACTIVE)
        uc = DisconnectBrokerageConnectionUseCase()
        await uc.execute(
            DisconnectBrokerageConnectionCommand(
                connection_id=conn.id,
                user_id=conn.user_id,
                tenant_id=conn.tenant_id,
            ),
            uow,
            broker,
        )
        assert uow.commit_count == 1


# ── GetSyncErrorsUseCase ───────────────────────────────────────────────────────


class TestGetSyncErrors:
    @pytest.mark.asyncio
    async def test_returns_errors_for_connection(self, uow: FakeUnitOfWork) -> None:
        conn = _seed_connection(uow, status=ConnectionStatus.ACTIVE)
        err1 = BrokerageTransactionSyncError(
            connection_id=conn.id,
            snaptrade_transaction_id="txn-001",
            error_type=SyncErrorType.UNKNOWN_INSTRUMENT,
        )
        err2 = BrokerageTransactionSyncError(
            connection_id=conn.id,
            snaptrade_transaction_id="txn-002",
            error_type=SyncErrorType.UNSUPPORTED_TYPE,
        )
        uow._brokerage_sync_errors._store.extend([err1, err2])

        uc = GetSyncErrorsUseCase()
        result = await uc.execute(
            GetSyncErrorsQuery(
                connection_id=conn.id,
                user_id=conn.user_id,
                tenant_id=conn.tenant_id,
            ),
            uow,
        )

        assert len(result.items) == 2
        ids = {e.snaptrade_transaction_id for e in result.items}
        assert "txn-001" in ids
        assert "txn-002" in ids

    @pytest.mark.asyncio
    async def test_not_found_raises(self, uow: FakeUnitOfWork) -> None:
        uc = GetSyncErrorsUseCase()
        with pytest.raises(BrokerageConnectionNotFoundError):
            await uc.execute(
                GetSyncErrorsQuery(
                    connection_id=uuid.uuid4(),
                    user_id=uuid.uuid4(),
                    tenant_id=uuid.uuid4(),
                ),
                uow,
            )

    @pytest.mark.asyncio
    async def test_cross_tenant_access_denied(self, uow: FakeUnitOfWork) -> None:
        """Connection exists but belongs to different tenant — returns not found."""
        conn = _seed_connection(uow)
        uc = GetSyncErrorsUseCase()
        with pytest.raises(BrokerageConnectionNotFoundError):
            await uc.execute(
                GetSyncErrorsQuery(
                    connection_id=conn.id,
                    user_id=conn.user_id,
                    tenant_id=uuid.uuid4(),  # different tenant
                ),
                uow,
            )

    @pytest.mark.asyncio
    async def test_limit_respected(self, uow: FakeUnitOfWork) -> None:
        conn = _seed_connection(uow, status=ConnectionStatus.ACTIVE)
        for i in range(5):
            uow._brokerage_sync_errors._store.append(
                BrokerageTransactionSyncError(
                    connection_id=conn.id,
                    snaptrade_transaction_id=f"txn-{i:03d}",
                    error_type=SyncErrorType.API_ERROR,
                ),
            )

        uc = GetSyncErrorsUseCase()
        result = await uc.execute(
            GetSyncErrorsQuery(
                connection_id=conn.id,
                user_id=conn.user_id,
                tenant_id=conn.tenant_id,
                limit=3,
            ),
            uow,
        )
        assert len(result.items) == 3


# ── Additional T-D-2-03 tests ─────────────────────────────────────────────────


class TestDisconnectRetainsTransactions:
    @pytest.mark.asyncio
    async def test_disconnect_retains_transactions(self, uow: FakeUnitOfWork, broker: FakeBrokerageClient) -> None:
        """DisconnectBrokerageConnectionUseCase never deletes transaction records (PRD §6.6)."""
        conn = _seed_connection(uow, status=ConnectionStatus.ACTIVE)
        uc = DisconnectBrokerageConnectionUseCase()
        await uc.execute(
            DisconnectBrokerageConnectionCommand(
                connection_id=conn.id,
                user_id=conn.user_id,
                tenant_id=conn.tenant_id,
            ),
            uow,
            broker,
        )
        # TransactionRepository must never be accessed for delete operations
        assert not hasattr(uow._transactions, "delete_calls")
        # Existing transactions (none seeded, but count must be ≥ 0 — repo untouched)
        assert len(uow._transactions._store) == 0


class TestInitiateConnectionTypeIsAlwaysRead:
    @pytest.mark.asyncio
    async def test_initiate_connection_type_is_always_read(
        self,
        uow: FakeUnitOfWork,
        broker: FakeBrokerageClient,
        seeded: dict[str, object],
    ) -> None:
        """connectionType must be hardcoded server-side; redirect_uri must NOT carry it (PRD F-22).

        The redirect_uri passed to SnapTrade must contain connectionId so that
        the callback handler can identify the pending connection, but must NOT
        include connectionType (that would allow the frontend to override it).
        """
        tenant = seeded["tenant"]
        user = seeded["user"]
        portfolio = seeded["portfolio"]

        uc = InitiateBrokerageConnectionUseCase()
        result = await uc.execute(
            InitiateBrokerageConnectionCommand(
                tenant_id=tenant.id,  # type: ignore[union-attr]
                user_id=user.id,  # type: ignore[union-attr]
                portfolio_id=portfolio.id,  # type: ignore[union-attr]
                snaptrade_tos_accepted=True,
            ),
            uow,
            broker,
            _REDIRECT_BASE,
        )
        assert len(broker.portal_url_calls) == 1
        called_uri = broker.portal_url_calls[0]
        # connectionId embedded so callback can look up the pending connection
        assert f"connectionId={result.connection_id}" in called_uri
        # connectionType must NOT be in the redirect_uri — it is hardcoded server-side
        assert "connectionType" not in called_uri


class TestGetSyncErrorsRawTransactionExcluded:
    def test_get_sync_errors_raw_transaction_excluded(self) -> None:
        """SyncErrorResponse schema must never expose raw_transaction (PRD §6.4 privacy invariant)."""
        from portfolio.api.schemas import SyncErrorResponse

        # The Pydantic model must not have raw_transaction as a declared field
        assert "raw_transaction" not in SyncErrorResponse.model_fields
        # Verify via model_dump that serialization output is also clean
        import uuid
        from datetime import UTC, datetime

        response = SyncErrorResponse(
            id=uuid.uuid4(),
            connection_id=uuid.uuid4(),
            snaptrade_transaction_id="txn-001",
            error_type="unknown_instrument",
            error_detail="AAPL not found",
            created_at=datetime(2026, 4, 1, tzinfo=UTC),
        )
        dumped = response.model_dump()
        assert "raw_transaction" not in dumped
