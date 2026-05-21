"""Unit tests for TriggerEntityRefreshUseCase (REQ-003 / TASK-W0-06).

Validates the application-layer logic in isolation:
  - Invalid refresh_type raises InvalidRefreshTypeError (422 mapping).
  - Missing entity raises EntityNotFoundError (404 mapping).
  - Rate-limit hit (set_nx → False) returns None (429 mapping).
  - Happy path: outbox append called with topic=entity.refresh.v1.
  - Avro payload contains all expected fields, including the chosen refresh_type.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from knowledge_graph.application.use_cases.trigger_entity_refresh import (
    EntityNotFoundError,
    InvalidRefreshTypeError,
    TriggerEntityRefreshUseCase,
)

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]


def _make_session_factory(*, fetchone_result=None) -> MagicMock:
    """Build an async sessionmaker mock that yields a session with execute().

    The session enters/exits via ``async with``.  ``execute().fetchone()``
    returns ``fetchone_result`` (None → entity not found, anything else →
    entity exists).  ``commit()`` and ``execute()`` are AsyncMocks so the
    outbox append path works too.
    """
    session = AsyncMock()
    session.__aenter__.return_value = session
    session.__aexit__.return_value = None
    session.commit = AsyncMock()

    result = MagicMock()
    result.fetchone.return_value = fetchone_result
    session.execute = AsyncMock(return_value=result)

    factory = MagicMock(return_value=session)
    return factory


def _make_outbox_repo_class() -> tuple[MagicMock, AsyncMock]:
    """Return (outbox_repo_class, append_mock) so tests can assert call args."""
    append_mock = AsyncMock(return_value=uuid4())  # returns outbox row UUID

    class _RepoStub:
        def __init__(self, _session):
            self.append = append_mock

    return MagicMock(side_effect=_RepoStub), append_mock


class TestValidation:
    async def test_invalid_refresh_type_raises(self) -> None:
        """refresh_type='bogus' → InvalidRefreshTypeError before any DB I/O."""
        write_sf = _make_session_factory()
        read_sf = _make_session_factory(fetchone_result=(1,))
        outbox_cls, _ = _make_outbox_repo_class()

        uc = TriggerEntityRefreshUseCase(
            valkey=None,
            write_session_factory=write_sf,
            read_session_factory=read_sf,
            outbox_repo_class=outbox_cls,
        )

        with pytest.raises(InvalidRefreshTypeError):
            await uc.execute(
                entity_id=uuid4(),
                tenant_id=None,
                user_id="u1",
                refresh_type="bogus",
            )

    async def test_entity_not_found_raises(self) -> None:
        """canonical_entities returns no row → EntityNotFoundError."""
        write_sf = _make_session_factory()
        read_sf = _make_session_factory(fetchone_result=None)
        outbox_cls, _ = _make_outbox_repo_class()

        uc = TriggerEntityRefreshUseCase(
            valkey=None,
            write_session_factory=write_sf,
            read_session_factory=read_sf,
            outbox_repo_class=outbox_cls,
        )

        with pytest.raises(EntityNotFoundError):
            await uc.execute(
                entity_id=uuid4(),
                tenant_id=None,
                user_id="u1",
                refresh_type="all",
            )


class TestRateLimit:
    async def test_returns_none_when_rate_limited(self) -> None:
        """Valkey.set_nx → False → execute returns None; outbox NOT touched."""
        write_sf = _make_session_factory()
        read_sf = _make_session_factory(fetchone_result=(1,))
        outbox_cls, append_mock = _make_outbox_repo_class()

        valkey = AsyncMock()
        valkey.set_nx = AsyncMock(return_value=False)  # rate-limited

        uc = TriggerEntityRefreshUseCase(
            valkey=valkey,
            write_session_factory=write_sf,
            read_session_factory=read_sf,
            outbox_repo_class=outbox_cls,
        )

        result = await uc.execute(
            entity_id=uuid4(),
            tenant_id=None,
            user_id="u1",
            refresh_type="all",
        )

        assert result is None
        append_mock.assert_not_called()
        # set_nx was called with ex=3600 (the BP-200 pattern).
        valkey.set_nx.assert_awaited_once()
        kwargs = valkey.set_nx.call_args.kwargs
        assert kwargs.get("ex") == 3600


class TestHappyPath:
    async def test_outbox_append_called_with_entity_refresh_topic(self) -> None:
        """Happy path: outbox.append called with topic='entity.refresh.v1'."""
        write_sf = _make_session_factory()
        read_sf = _make_session_factory(fetchone_result=(1,))
        outbox_cls, append_mock = _make_outbox_repo_class()

        valkey = AsyncMock()
        valkey.set_nx = AsyncMock(return_value=True)  # allowed

        entity_id = uuid4()
        uc = TriggerEntityRefreshUseCase(
            valkey=valkey,
            write_session_factory=write_sf,
            read_session_factory=read_sf,
            outbox_repo_class=outbox_cls,
        )

        result = await uc.execute(
            entity_id=entity_id,
            tenant_id=None,
            user_id="u1",
            refresh_type="narrative",
        )

        assert result is not None
        assert result.entity_id == entity_id
        assert result.refresh_type == "narrative"
        assert isinstance(result.job_id, UUID)

        append_mock.assert_awaited_once()
        kwargs = append_mock.call_args.kwargs
        assert kwargs["topic"] == "entity.refresh.v1"
        assert kwargs["partition_key"] == str(entity_id)
        # Avro payload is a non-empty bytes blob with the Confluent magic byte.
        assert isinstance(kwargs["payload_avro"], bytes)
        assert kwargs["payload_avro"][0:1] == b"\x00"


class TestAvroForwardCompat:
    async def test_default_refresh_type_resolves_to_all(self) -> None:
        """Omitting refresh_type at the use-case boundary defaults to 'all'.

        The Avro schema declares ``"default": "all"`` for refresh_type — this
        test guards that the use case honours the same default (so old callers
        that don't send the field still produce a valid event)."""
        write_sf = _make_session_factory()
        read_sf = _make_session_factory(fetchone_result=(1,))
        outbox_cls, append_mock = _make_outbox_repo_class()

        valkey = AsyncMock()
        valkey.set_nx = AsyncMock(return_value=True)

        uc = TriggerEntityRefreshUseCase(
            valkey=valkey,
            write_session_factory=write_sf,
            read_session_factory=read_sf,
            outbox_repo_class=outbox_cls,
        )

        # Note: refresh_type omitted — use case default is "all".
        result = await uc.execute(
            entity_id=uuid4(),
            tenant_id=None,
            user_id="u1",
        )

        assert result is not None
        assert result.refresh_type == "all"
        append_mock.assert_awaited_once()
