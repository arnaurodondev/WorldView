"""Unit tests for watchlist domain entities, events, and errors."""

from __future__ import annotations

from uuid import uuid4

import pytest
from portfolio.domain.entities.watchlist import Watchlist
from portfolio.domain.entities.watchlist_member import WatchlistMember
from portfolio.domain.enums import WatchlistStatus
from portfolio.domain.errors import (
    DomainError,
    WatchlistAlreadyExistsError,
    WatchlistMemberAlreadyExistsError,
    WatchlistMemberNotFoundError,
    WatchlistNotFoundError,
)
from portfolio.domain.events import WatchlistItemAdded, WatchlistItemDeleted

from common.time import utc_now  # type: ignore[import-untyped]

pytestmark = pytest.mark.unit


def _make_watchlist(status: WatchlistStatus = WatchlistStatus.ACTIVE) -> Watchlist:
    return Watchlist(
        id=uuid4(),
        tenant_id=uuid4(),
        user_id=uuid4(),
        name="Tech Stocks",
        status=status,
        created_at=utc_now(),
    )


def _make_member() -> WatchlistMember:
    return WatchlistMember(
        id=uuid4(),
        watchlist_id=uuid4(),
        entity_id=uuid4(),
        entity_type="company",
        added_at=utc_now(),
    )


def test_watchlist_is_active_returns_true_for_active_status() -> None:
    w = _make_watchlist(WatchlistStatus.ACTIVE)
    assert w.is_active() is True


def test_watchlist_is_active_returns_false_for_deleted_status() -> None:
    w = _make_watchlist(WatchlistStatus.DELETED)
    assert w.is_active() is False


def test_watchlist_member_stores_entity_id_without_fk() -> None:
    """entity_id must be a plain UUID with no FK enforcement in the domain layer."""
    entity_id = uuid4()
    member = WatchlistMember(
        id=uuid4(),
        watchlist_id=uuid4(),
        entity_id=entity_id,
        entity_type="company",
        added_at=utc_now(),
    )
    assert member.entity_id == entity_id


def test_watchlist_item_added_event_fields() -> None:
    tenant_id = uuid4()
    watchlist_id = uuid4()
    user_id = uuid4()
    entity_id = uuid4()

    event = WatchlistItemAdded(
        tenant_id=tenant_id,
        watchlist_id=watchlist_id,
        user_id=user_id,
        entity_id=entity_id,
        entity_type="company",
    )
    assert event.EVENT_TYPE == "watchlist.item_added"
    assert event.AGGREGATE_TYPE == "watchlist"
    assert event.watchlist_id == watchlist_id
    assert event.user_id == user_id
    assert event.entity_id == entity_id
    assert event.entity_type == "company"
    assert event.aggregate_id == watchlist_id


def test_watchlist_item_deleted_event_fields() -> None:
    tenant_id = uuid4()
    watchlist_id = uuid4()
    user_id = uuid4()
    entity_id = uuid4()

    event = WatchlistItemDeleted(
        tenant_id=tenant_id,
        watchlist_id=watchlist_id,
        user_id=user_id,
        entity_id=entity_id,
        entity_type="etf",
    )
    assert event.EVENT_TYPE == "watchlist.item_deleted"
    assert event.aggregate_id == watchlist_id
    assert event.entity_id == entity_id


def test_watchlist_error_hierarchy() -> None:
    """All 4 watchlist errors must be subclasses of DomainError."""
    assert issubclass(WatchlistNotFoundError, DomainError)
    assert issubclass(WatchlistAlreadyExistsError, DomainError)
    assert issubclass(WatchlistMemberNotFoundError, DomainError)
    assert issubclass(WatchlistMemberAlreadyExistsError, DomainError)
