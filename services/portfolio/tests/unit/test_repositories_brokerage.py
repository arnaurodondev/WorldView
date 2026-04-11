"""Unit tests for brokerage repository implementations and fake implementations.

Covers:
- SqlAlchemyBrokerageConnectionRepository: save/load round-trip, encryption, queries
- SqlAlchemyBrokerageTransactionSyncErrorRepository: save, list_by_connection
- FakeBrokerageConnectionRepository: all query methods
- FakeBrokerageTransactionSyncErrorRepository: save + list
- FakeUnitOfWork: new brokerage properties
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from portfolio.domain.entities.brokerage_connection import BrokerageConnection
from portfolio.domain.entities.brokerage_sync_error import BrokerageTransactionSyncError
from portfolio.domain.enums import ConnectionStatus, SyncErrorType
from portfolio.infrastructure.db.models.brokerage_connection import BrokerageConnectionModel
from portfolio.infrastructure.db.models.brokerage_sync_error import BrokerageTransactionSyncErrorModel
from portfolio.infrastructure.db.repositories.brokerage_connection import SqlAlchemyBrokerageConnectionRepository
from portfolio.infrastructure.db.repositories.brokerage_sync_error import (
    SqlAlchemyBrokerageTransactionSyncErrorRepository,
)

from tests.unit.fakes import (
    FakeBrokerageConnectionRepository,
    FakeBrokerageTransactionSyncErrorRepository,
    FakeUnitOfWork,
)

pytestmark = pytest.mark.unit

# ── Helpers ────────────────────────────────────────────────────────────────────

_NOW = datetime(2026, 4, 11, 12, 0, 0, tzinfo=UTC)


def _make_connection(
    *,
    tenant_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
    portfolio_id: uuid.UUID | None = None,
    status: ConnectionStatus = ConnectionStatus.PENDING,
    snaptrade_user_secret: str = "plain-secret",  # noqa: S107
) -> BrokerageConnection:
    return BrokerageConnection(
        id=uuid.uuid4(),
        tenant_id=tenant_id or uuid.uuid4(),
        user_id=user_id or uuid.uuid4(),
        portfolio_id=portfolio_id or uuid.uuid4(),
        snaptrade_user_id="snap-user-id",
        snaptrade_user_secret=snaptrade_user_secret,
        snaptrade_tos_accepted_at=_NOW,
        status=status,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _make_sync_error(connection_id: uuid.UUID) -> BrokerageTransactionSyncError:
    return BrokerageTransactionSyncError(
        id=uuid.uuid4(),
        connection_id=connection_id,
        snaptrade_transaction_id="txn-001",
        error_type=SyncErrorType.UNKNOWN_INSTRUMENT,
        error_detail="Symbol XYZ not found",
        created_at=_NOW,
    )


def _make_orm_row(conn: BrokerageConnection, secret_override: str | None = None) -> BrokerageConnectionModel:
    """Build an ORM model row matching a domain entity (bypasses DB)."""
    row = MagicMock(spec=BrokerageConnectionModel)
    row.id = conn.id
    row.tenant_id = conn.tenant_id
    row.user_id = conn.user_id
    row.portfolio_id = conn.portfolio_id
    row.snaptrade_user_id = conn.snaptrade_user_id
    row.snaptrade_user_secret = secret_override if secret_override is not None else conn.snaptrade_user_secret
    row.authorization_id = conn.authorization_id
    row.brokerage_name = conn.brokerage_name
    row.status = str(conn.status)
    row.snaptrade_tos_accepted_at = conn.snaptrade_tos_accepted_at
    row.last_synced_at = conn.last_synced_at
    row.last_sync_cursor = conn.last_sync_cursor
    row.created_at = conn.created_at
    row.updated_at = conn.updated_at
    return row


def _make_error_orm_row(err: BrokerageTransactionSyncError) -> BrokerageTransactionSyncErrorModel:
    row = MagicMock(spec=BrokerageTransactionSyncErrorModel)
    row.id = err.id
    row.connection_id = err.connection_id
    row.snaptrade_transaction_id = err.snaptrade_transaction_id
    row.error_type = str(err.error_type)
    row.error_detail = err.error_detail
    row.raw_transaction = err.raw_transaction
    row.created_at = err.created_at
    return row


# ══════════════════════════════════════════════════════════════════════════════
# SqlAlchemyBrokerageConnectionRepository
# ══════════════════════════════════════════════════════════════════════════════


class TestSqlAlchemyBrokerageConnectionRepositoryEncryption:
    """Tests for the Fernet encrypt/decrypt helpers (no DB required)."""

    def test_encrypt_decrypt_roundtrip_with_cipher(self) -> None:
        from cryptography.fernet import Fernet

        key = Fernet.generate_key()
        cipher = Fernet(key)
        session = MagicMock()
        repo = SqlAlchemyBrokerageConnectionRepository(session, cipher=cipher)

        original = "super-secret-token"
        ciphertext = repo._encrypt(original)
        assert ciphertext != original
        assert repo._decrypt(ciphertext) == original

    def test_encrypt_is_identity_without_cipher(self) -> None:
        session = MagicMock()
        repo = SqlAlchemyBrokerageConnectionRepository(session, cipher=None)

        plaintext = "my-secret"
        assert repo._encrypt(plaintext) == plaintext
        assert repo._decrypt(plaintext) == plaintext

    def test_decrypt_recovers_plaintext_after_encrypt(self) -> None:
        from cryptography.fernet import Fernet

        key = Fernet.generate_key()
        cipher = Fernet(key)
        session = MagicMock()
        repo = SqlAlchemyBrokerageConnectionRepository(session, cipher=cipher)

        secret = "another-secret-value"  # noqa: S105
        assert repo._decrypt(repo._encrypt(secret)) == secret


class TestSqlAlchemyBrokerageConnectionRepositoryToEntity:
    """Tests for _to_entity mapping (no DB required)."""

    def test_status_mapped_to_enum(self) -> None:
        session = MagicMock()
        repo = SqlAlchemyBrokerageConnectionRepository(session)
        conn = _make_connection(status=ConnectionStatus.ACTIVE)
        row = _make_orm_row(conn)
        row.status = "active"

        entity = repo._to_entity(row)
        assert entity.status == ConnectionStatus.ACTIVE

    def test_secret_decrypted_with_cipher(self) -> None:
        from cryptography.fernet import Fernet

        key = Fernet.generate_key()
        cipher = Fernet(key)
        session = MagicMock()
        repo = SqlAlchemyBrokerageConnectionRepository(session, cipher=cipher)

        conn = _make_connection(snaptrade_user_secret="plaintext-secret")
        ciphertext = cipher.encrypt(b"plaintext-secret").decode()
        row = _make_orm_row(conn, secret_override=ciphertext)

        entity = repo._to_entity(row)
        assert entity.snaptrade_user_secret == "plaintext-secret"  # noqa: S105

    def test_secret_returned_as_is_without_cipher(self) -> None:
        session = MagicMock()
        repo = SqlAlchemyBrokerageConnectionRepository(session, cipher=None)
        conn = _make_connection(snaptrade_user_secret="plain")
        row = _make_orm_row(conn)

        entity = repo._to_entity(row)
        assert entity.snaptrade_user_secret == "plain"  # noqa: S105

    def test_all_fields_mapped(self) -> None:
        session = MagicMock()
        repo = SqlAlchemyBrokerageConnectionRepository(session)
        conn = _make_connection()
        row = _make_orm_row(conn)

        entity = repo._to_entity(row)
        assert entity.id == conn.id
        assert entity.tenant_id == conn.tenant_id
        assert entity.user_id == conn.user_id
        assert entity.portfolio_id == conn.portfolio_id
        assert entity.snaptrade_user_id == conn.snaptrade_user_id
        assert entity.snaptrade_tos_accepted_at == conn.snaptrade_tos_accepted_at
        assert entity.created_at == conn.created_at
        assert entity.updated_at == conn.updated_at


class TestSqlAlchemyBrokerageConnectionRepositoryGet:
    @pytest.mark.asyncio
    async def test_get_returns_none_when_not_found(self) -> None:
        session = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(return_value=result_mock)

        repo = SqlAlchemyBrokerageConnectionRepository(session)
        result = await repo.get(uuid.uuid4(), uuid.uuid4())
        assert result is None

    @pytest.mark.asyncio
    async def test_get_returns_entity_when_found(self) -> None:
        conn = _make_connection()
        session = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = _make_orm_row(conn)
        session.execute = AsyncMock(return_value=result_mock)

        repo = SqlAlchemyBrokerageConnectionRepository(session)
        entity = await repo.get(conn.id, conn.tenant_id)
        assert entity is not None
        assert entity.id == conn.id

    @pytest.mark.asyncio
    async def test_get_by_user_returns_none_when_not_found(self) -> None:
        session = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(return_value=result_mock)

        repo = SqlAlchemyBrokerageConnectionRepository(session)
        result = await repo.get_by_user(uuid.uuid4(), uuid.uuid4(), uuid.uuid4())
        assert result is None


class TestSqlAlchemyBrokerageConnectionRepositorySave:
    @pytest.mark.asyncio
    async def test_save_new_connection_adds_to_session(self) -> None:
        conn = _make_connection()
        session = AsyncMock()
        session.get = AsyncMock(return_value=None)  # not found → new insert
        session.add = MagicMock()  # session.add is sync in SQLAlchemy

        repo = SqlAlchemyBrokerageConnectionRepository(session)
        await repo.save(conn)

        session.add.assert_called_once()
        added_row = session.add.call_args[0][0]
        assert added_row.id == conn.id
        assert added_row.status == "pending"

    @pytest.mark.asyncio
    async def test_save_encrypts_secret_with_cipher(self) -> None:
        from cryptography.fernet import Fernet

        key = Fernet.generate_key()
        cipher = Fernet(key)
        conn = _make_connection(snaptrade_user_secret="raw-secret")
        session = AsyncMock()
        session.get = AsyncMock(return_value=None)
        session.add = MagicMock()  # session.add is sync in SQLAlchemy

        repo = SqlAlchemyBrokerageConnectionRepository(session, cipher=cipher)
        await repo.save(conn)

        added_row = session.add.call_args[0][0]
        # The stored secret must be ciphertext, not plaintext
        assert added_row.snaptrade_user_secret != "raw-secret"  # noqa: S105
        # And it must be decryptable back to the original
        assert cipher.decrypt(added_row.snaptrade_user_secret.encode()).decode() == "raw-secret"

    @pytest.mark.asyncio
    async def test_save_existing_connection_updates_fields(self) -> None:
        conn = _make_connection(status=ConnectionStatus.ACTIVE)
        existing_row = MagicMock(spec=BrokerageConnectionModel)
        session = AsyncMock()
        session.get = AsyncMock(return_value=existing_row)

        repo = SqlAlchemyBrokerageConnectionRepository(session)
        await repo.save(conn)

        # Should NOT call session.add (UPDATE path)
        session.add.assert_not_called()
        assert existing_row.status == "active"

    @pytest.mark.asyncio
    async def test_save_and_load_plaintext_roundtrip(self) -> None:
        """Save then load preserves the original secret (no cipher — dev mode)."""
        secret = "dev-plaintext-secret"  # noqa: S105
        conn = _make_connection(snaptrade_user_secret=secret)

        session = AsyncMock()
        session.get = AsyncMock(return_value=None)
        # session.add is sync in SQLAlchemy — override the AsyncMock default
        captured_row: list[BrokerageConnectionModel] = []
        session.add = MagicMock(side_effect=lambda row: captured_row.append(row))

        repo = SqlAlchemyBrokerageConnectionRepository(session, cipher=None)
        await repo.save(conn)

        assert captured_row[0].snaptrade_user_secret == secret
        # Simulate loading back: _to_entity on the captured row
        entity = repo._to_entity(_make_orm_row(conn, secret_override=captured_row[0].snaptrade_user_secret))
        assert entity.snaptrade_user_secret == secret

    @pytest.mark.asyncio
    async def test_save_and_load_encrypted_roundtrip(self) -> None:
        """Save (encrypts) then load (_to_entity decrypts) preserves original secret."""
        from cryptography.fernet import Fernet

        key = Fernet.generate_key()
        cipher = Fernet(key)
        secret = "prod-secret-token"  # noqa: S105
        conn = _make_connection(snaptrade_user_secret=secret)

        session = AsyncMock()
        session.get = AsyncMock(return_value=None)
        captured_row: list[BrokerageConnectionModel] = []
        # session.add is sync in SQLAlchemy — override the AsyncMock default
        session.add = MagicMock(side_effect=lambda row: captured_row.append(row))

        repo = SqlAlchemyBrokerageConnectionRepository(session, cipher=cipher)
        await repo.save(conn)

        ciphertext = captured_row[0].snaptrade_user_secret
        entity = repo._to_entity(_make_orm_row(conn, secret_override=ciphertext))
        assert entity.snaptrade_user_secret == secret


# ══════════════════════════════════════════════════════════════════════════════
# SqlAlchemyBrokerageTransactionSyncErrorRepository
# ══════════════════════════════════════════════════════════════════════════════


class TestSqlAlchemyBrokerageTransactionSyncErrorRepository:
    @pytest.mark.asyncio
    async def test_save_adds_row_to_session(self) -> None:
        error = _make_sync_error(uuid.uuid4())
        session = AsyncMock()
        session.add = MagicMock()  # session.add is sync in SQLAlchemy

        repo = SqlAlchemyBrokerageTransactionSyncErrorRepository(session)
        await repo.save(error)

        session.add.assert_called_once()
        row = session.add.call_args[0][0]
        assert row.id == error.id
        assert row.connection_id == error.connection_id
        assert row.error_type == "unknown_instrument"

    @pytest.mark.asyncio
    async def test_list_by_connection_returns_matching(self) -> None:
        connection_id = uuid.uuid4()
        error = _make_sync_error(connection_id)
        session = AsyncMock()
        scalars_mock = MagicMock()
        scalars_mock.__iter__ = MagicMock(return_value=iter([_make_error_orm_row(error)]))
        result_mock = MagicMock()
        result_mock.scalars.return_value = scalars_mock
        session.execute = AsyncMock(return_value=result_mock)

        repo = SqlAlchemyBrokerageTransactionSyncErrorRepository(session)
        results = await repo.list_by_connection(connection_id)

        assert len(results) == 1
        assert results[0].connection_id == connection_id
        assert results[0].error_type == SyncErrorType.UNKNOWN_INSTRUMENT

    def test_to_entity_maps_all_fields(self) -> None:
        connection_id = uuid.uuid4()
        error = _make_sync_error(connection_id)
        row = _make_error_orm_row(error)
        session = MagicMock()

        repo = SqlAlchemyBrokerageTransactionSyncErrorRepository(session)
        entity = repo._to_entity(row)

        assert entity.id == error.id
        assert entity.connection_id == connection_id
        assert entity.snaptrade_transaction_id == "txn-001"
        assert entity.error_type == SyncErrorType.UNKNOWN_INSTRUMENT
        assert entity.error_detail == "Symbol XYZ not found"


# ══════════════════════════════════════════════════════════════════════════════
# FakeBrokerageConnectionRepository
# ══════════════════════════════════════════════════════════════════════════════


class TestFakeBrokerageConnectionRepository:
    @pytest.mark.asyncio
    async def test_save_and_get(self) -> None:
        repo = FakeBrokerageConnectionRepository()
        conn = _make_connection()
        await repo.save(conn)

        result = await repo.get(conn.id, conn.tenant_id)
        assert result is not None
        assert result.id == conn.id

    @pytest.mark.asyncio
    async def test_get_wrong_tenant_returns_none(self) -> None:
        repo = FakeBrokerageConnectionRepository()
        conn = _make_connection()
        await repo.save(conn)

        result = await repo.get(conn.id, uuid.uuid4())
        assert result is None

    @pytest.mark.asyncio
    async def test_get_by_user_success(self) -> None:
        repo = FakeBrokerageConnectionRepository()
        conn = _make_connection()
        await repo.save(conn)

        result = await repo.get_by_user(conn.id, conn.user_id, conn.tenant_id)
        assert result is not None

    @pytest.mark.asyncio
    async def test_get_by_user_wrong_user_returns_none(self) -> None:
        repo = FakeBrokerageConnectionRepository()
        conn = _make_connection()
        await repo.save(conn)

        result = await repo.get_by_user(conn.id, uuid.uuid4(), conn.tenant_id)
        assert result is None

    @pytest.mark.asyncio
    async def test_list_by_user_filters_correctly(self) -> None:
        user_id = uuid.uuid4()
        tenant_id = uuid.uuid4()
        repo = FakeBrokerageConnectionRepository()

        conn1 = _make_connection(user_id=user_id, tenant_id=tenant_id)
        conn2 = _make_connection(user_id=user_id, tenant_id=tenant_id)
        conn3 = _make_connection()  # different user
        await repo.save(conn1)
        await repo.save(conn2)
        await repo.save(conn3)

        results = await repo.list_by_user(user_id, tenant_id)
        ids = {r.id for r in results}
        assert conn1.id in ids
        assert conn2.id in ids
        assert conn3.id not in ids

    @pytest.mark.asyncio
    async def test_list_by_user_portfolio_filter(self) -> None:
        user_id = uuid.uuid4()
        tenant_id = uuid.uuid4()
        portfolio_id = uuid.uuid4()
        repo = FakeBrokerageConnectionRepository()

        conn1 = _make_connection(user_id=user_id, tenant_id=tenant_id, portfolio_id=portfolio_id)
        conn2 = _make_connection(user_id=user_id, tenant_id=tenant_id)  # different portfolio
        await repo.save(conn1)
        await repo.save(conn2)

        results = await repo.list_by_user(user_id, tenant_id, portfolio_id=portfolio_id)
        assert len(results) == 1
        assert results[0].id == conn1.id

    @pytest.mark.asyncio
    async def test_list_active_or_error(self) -> None:
        repo = FakeBrokerageConnectionRepository()
        active = _make_connection(status=ConnectionStatus.ACTIVE)
        error = _make_connection(status=ConnectionStatus.ERROR)
        pending = _make_connection(status=ConnectionStatus.PENDING)
        disconnected = _make_connection(status=ConnectionStatus.DISCONNECTED)

        for c in (active, error, pending, disconnected):
            await repo.save(c)

        results = await repo.list_active_or_error()
        ids = {r.id for r in results}
        assert active.id in ids
        assert error.id in ids
        assert pending.id not in ids
        assert disconnected.id not in ids

    @pytest.mark.asyncio
    async def test_save_overwrites_existing(self) -> None:
        repo = FakeBrokerageConnectionRepository()
        conn = _make_connection(status=ConnectionStatus.PENDING)
        await repo.save(conn)

        conn.status = ConnectionStatus.ACTIVE
        await repo.save(conn)

        result = await repo.get(conn.id, conn.tenant_id)
        assert result is not None
        assert result.status == ConnectionStatus.ACTIVE


# ══════════════════════════════════════════════════════════════════════════════
# FakeBrokerageTransactionSyncErrorRepository
# ══════════════════════════════════════════════════════════════════════════════


class TestFakeBrokerageTransactionSyncErrorRepository:
    @pytest.mark.asyncio
    async def test_save_and_list(self) -> None:
        connection_id = uuid.uuid4()
        repo = FakeBrokerageTransactionSyncErrorRepository()
        error = _make_sync_error(connection_id)
        await repo.save(error)

        results = await repo.list_by_connection(connection_id)
        assert len(results) == 1
        assert results[0].id == error.id

    @pytest.mark.asyncio
    async def test_list_filters_by_connection(self) -> None:
        repo = FakeBrokerageTransactionSyncErrorRepository()
        cid1 = uuid.uuid4()
        cid2 = uuid.uuid4()

        await repo.save(_make_sync_error(cid1))
        await repo.save(_make_sync_error(cid2))

        results = await repo.list_by_connection(cid1)
        assert len(results) == 1
        assert results[0].connection_id == cid1

    @pytest.mark.asyncio
    async def test_list_respects_limit(self) -> None:
        connection_id = uuid.uuid4()
        repo = FakeBrokerageTransactionSyncErrorRepository()

        for _ in range(5):
            await repo.save(_make_sync_error(connection_id))

        results = await repo.list_by_connection(connection_id, limit=3)
        assert len(results) == 3


# ══════════════════════════════════════════════════════════════════════════════
# FakeUnitOfWork — brokerage properties
# ══════════════════════════════════════════════════════════════════════════════


class TestFakeUnitOfWorkBrokerageProperties:
    def test_brokerage_connections_property_accessible(self) -> None:
        uow = FakeUnitOfWork()
        assert isinstance(uow.brokerage_connections, FakeBrokerageConnectionRepository)

    def test_brokerage_sync_errors_property_accessible(self) -> None:
        uow = FakeUnitOfWork()
        assert isinstance(uow.brokerage_sync_errors, FakeBrokerageTransactionSyncErrorRepository)

    @pytest.mark.asyncio
    async def test_brokerage_connection_save_and_retrieve_via_uow(self) -> None:
        uow = FakeUnitOfWork()
        conn = _make_connection()
        await uow.brokerage_connections.save(conn)
        await uow.commit()

        result = await uow.brokerage_connections.get(conn.id, conn.tenant_id)
        assert result is not None
        assert result.id == conn.id
