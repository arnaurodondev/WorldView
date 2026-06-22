"""Event-to-Avro-dict mappers for Portfolio domain events."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from portfolio.domain.events import (
        DomainEvent,
        HoldingChanged,
        InstrumentRefCreated,
        PortfolioArchived,
        PortfolioCreated,
        PortfolioHoldingRecomputeRequested,
        PortfolioRenamed,
        TenantCreated,
        TransactionRecorded,
        UserCreated,
        WatchlistCreated,
        WatchlistDeleted,
        WatchlistItemAdded,
        WatchlistItemDeleted,
        WatchlistRenamed,
    )


def event_to_envelope_dict(event: DomainEvent) -> dict[str, Any]:
    """Serialize common envelope fields shared by all domain events.

    ``event_id`` and ``occurred_at`` are already strings (D-009 — Avro portability).
    """
    return {
        "event_id": event.event_id,
        "event_type": event.EVENT_TYPE,
        "aggregate_type": event.AGGREGATE_TYPE,
        "aggregate_id": str(event.aggregate_id),
        "tenant_id": str(event.tenant_id),
        "occurred_at": event.occurred_at,
        "schema_version": event.schema_version,
        "correlation_id": event.correlation_id,
        "causation_id": event.causation_id,
    }


def tenant_created_to_dict(event: TenantCreated) -> dict[str, Any]:
    d = event_to_envelope_dict(event)
    d["tenant_name"] = event.tenant_name
    return d


def user_created_to_dict(event: UserCreated) -> dict[str, Any]:
    d = event_to_envelope_dict(event)
    d["user_id"] = str(event.user_id)
    d["email"] = event.email
    return d


def transaction_recorded_to_dict(event: TransactionRecorded) -> dict[str, Any]:
    d = event_to_envelope_dict(event)
    d["transaction_id"] = str(event.transaction_id)
    d["portfolio_id"] = str(event.portfolio_id)
    d["instrument_id"] = str(event.instrument_id)
    d["transaction_type"] = event.transaction_type
    d["direction"] = event.direction
    d["quantity"] = event.quantity
    d["price"] = event.price
    d["fees"] = event.fees
    d["currency"] = event.currency
    d["executed_at"] = event.executed_at
    return d


def portfolio_created_to_dict(event: PortfolioCreated) -> dict[str, Any]:
    d = event_to_envelope_dict(event)
    d["portfolio_id"] = str(event.portfolio_id)
    d["owner_id"] = str(event.owner_id)
    d["name"] = event.name
    d["currency"] = event.currency
    return d


def portfolio_renamed_to_dict(event: PortfolioRenamed) -> dict[str, Any]:
    d = event_to_envelope_dict(event)
    d["portfolio_id"] = str(event.portfolio_id)
    d["old_name"] = event.old_name
    d["new_name"] = event.new_name
    return d


def portfolio_archived_to_dict(event: PortfolioArchived) -> dict[str, Any]:
    d = event_to_envelope_dict(event)
    d["portfolio_id"] = str(event.portfolio_id)
    return d


def holding_changed_to_dict(event: HoldingChanged) -> dict[str, Any]:
    d = event_to_envelope_dict(event)
    d["holding_id"] = str(event.holding_id)
    d["portfolio_id"] = str(event.portfolio_id)
    d["instrument_id"] = str(event.instrument_id)
    d["quantity"] = event.quantity
    d["average_cost"] = event.average_cost
    d["currency"] = event.currency
    return d


def instrument_ref_created_to_dict(event: InstrumentRefCreated) -> dict[str, Any]:
    d = event_to_envelope_dict(event)
    d["instrument_id"] = str(event.instrument_id)
    d["symbol"] = event.symbol
    d["exchange"] = event.exchange
    d["name"] = event.name
    d["asset_class"] = event.asset_class
    d["currency"] = event.currency
    d["entity_id"] = str(event.entity_id) if event.entity_id else None
    return d


def watchlist_created_to_dict(event: WatchlistCreated) -> dict[str, Any]:
    d = event_to_envelope_dict(event)
    d["watchlist_id"] = str(event.watchlist_id)
    d["user_id"] = str(event.user_id)
    d["name"] = event.name
    return d


def watchlist_deleted_to_dict(event: WatchlistDeleted) -> dict[str, Any]:
    d = event_to_envelope_dict(event)
    d["watchlist_id"] = str(event.watchlist_id)
    d["user_id"] = str(event.user_id)
    return d


def watchlist_item_added_to_dict(event: WatchlistItemAdded) -> dict[str, Any]:
    d = event_to_envelope_dict(event)
    d["watchlist_id"] = str(event.watchlist_id)
    d["user_id"] = str(event.user_id)
    d["entity_id"] = str(event.entity_id)
    d["entity_type"] = event.entity_type
    return d


def watchlist_renamed_to_dict(event: WatchlistRenamed) -> dict[str, Any]:
    d = event_to_envelope_dict(event)
    d["watchlist_id"] = str(event.watchlist_id)
    d["user_id"] = str(event.user_id)
    d["old_name"] = event.old_name
    d["new_name"] = event.new_name
    return d


def watchlist_item_deleted_to_dict(event: WatchlistItemDeleted) -> dict[str, Any]:
    d = event_to_envelope_dict(event)
    d["watchlist_id"] = str(event.watchlist_id)
    d["user_id"] = str(event.user_id)
    d["entity_id"] = str(event.entity_id)
    d["entity_type"] = event.entity_type
    return d


# Registry mapping event_type -> mapper function


def holding_recompute_requested_to_dict(
    event: PortfolioHoldingRecomputeRequested,
) -> dict[str, Any]:
    """Build Avro-compatible dict for portfolio.holding.recompute_requested events."""
    d = event_to_envelope_dict(event)
    d["portfolio_id"] = str(event.portfolio_id)
    d["owner_id"] = str(event.owner_id)
    return d


EVENT_MAPPER_REGISTRY: dict[str, Any] = {
    "tenant.created": tenant_created_to_dict,
    "user.created": user_created_to_dict,
    "transaction.recorded": transaction_recorded_to_dict,
    "portfolio.created": portfolio_created_to_dict,
    "portfolio.renamed": portfolio_renamed_to_dict,
    "portfolio.archived": portfolio_archived_to_dict,
    "holding.changed": holding_changed_to_dict,
    "instrument_ref.created": instrument_ref_created_to_dict,
    "watchlist.created": watchlist_created_to_dict,
    "watchlist.deleted": watchlist_deleted_to_dict,
    "watchlist.renamed": watchlist_renamed_to_dict,
    "watchlist.item_added": watchlist_item_added_to_dict,
    "watchlist.item_deleted": watchlist_item_deleted_to_dict,
    "portfolio.holding.recompute_requested": holding_recompute_requested_to_dict,
}
