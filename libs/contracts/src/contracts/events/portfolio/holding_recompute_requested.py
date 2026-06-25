"""Canonical Pydantic model for the portfolio.holding.recompute_requested.v1 topic.

PLAN-0114 W1 / T-W1-05.

R28: every Kafka topic must have a canonical model in ``libs/contracts``
that matches the Avro schema field-for-field. This model is the single source
of truth for consumers in other services that may need to subscribe to
``portfolio.holding.recompute_requested.v1`` in the future.

Fields mirror ``portfolio_holding_recompute_requested.v1.avsc`` exactly.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field


class PortfolioHoldingRecomputeRequested(BaseModel):
    """Event emitted when a MANUAL portfolio transaction is recorded.

    Instructs ManualHoldingsRecomputeConsumer to replay the full transaction
    history for ``portfolio_id`` and rebuild the ``holdings`` table.

    Schema version: 1
    Topic: portfolio.holding.recompute_requested.v1
    """

    event_id: str = Field(description="UUIDv7 hex string — unique event identifier")
    event_type: str = Field(default="portfolio.holding.recompute_requested")
    aggregate_type: str = Field(default="portfolio")
    aggregate_id: str = Field(description="Same as portfolio_id (string UUID)")
    tenant_id: str = Field(description="Tenant UUID as string")
    occurred_at: str = Field(description="ISO-8601 UTC timestamp with Z suffix")
    schema_version: int = Field(default=1)
    correlation_id: str | None = Field(default=None)
    causation_id: str | None = Field(default=None)
    portfolio_id: str = Field(default="", description="Portfolio UUID as string")
    owner_id: str = Field(default="", description="Portfolio owner user UUID as string")

    @property
    def portfolio_uuid(self) -> UUID:
        """Convenience property returning portfolio_id as a UUID object."""
        return UUID(self.portfolio_id)

    @property
    def tenant_uuid(self) -> UUID:
        """Convenience property returning tenant_id as a UUID object."""
        return UUID(self.tenant_id)

    @property
    def owner_uuid(self) -> UUID:
        """Convenience property returning owner_id as a UUID object."""
        return UUID(self.owner_id)
