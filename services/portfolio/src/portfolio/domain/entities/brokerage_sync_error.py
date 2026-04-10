"""BrokerageTransactionSyncError domain entity."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from common.ids import new_uuid  # type: ignore[import-untyped]
from common.time import utc_now  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from portfolio.domain.enums import SyncErrorType


@dataclass(frozen=True)
class BrokerageTransactionSyncError:
    """An immutable record of a transaction that could not be imported.

    Privacy note: raw_transaction may contain sensitive financial data and
    MUST NEVER be included in any API response.
    """

    connection_id: UUID
    snaptrade_transaction_id: str
    error_type: SyncErrorType
    id: UUID = field(default_factory=new_uuid)
    error_detail: str | None = None
    raw_transaction: dict[str, Any] | None = None
    created_at: datetime = field(default_factory=utc_now)
