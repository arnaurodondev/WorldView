"""NotificationPreferences domain entity.

Represents per-tenant notification preferences. Stored as a single row
keyed by tenant_id (one set of prefs per tenant / workspace). The upsert-on-read
pattern returns defaults when no row exists so the frontend always gets
a valid payload without requiring an explicit seed step.

W1-BACKEND: added to support CRIT-004 / MED-022 notification preferences endpoint.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True)
class NotificationPreferences:
    """Per-tenant notification toggle preferences.

    All boolean fields default to True (opt-in by default). The use cases
    return a default instance when no DB row exists yet so the frontend
    always gets a well-typed response.

    WHY tenant_id as PK (not user_id): preferences are workspace-scoped
    in the current single-tenant model. If multi-user per-tenant preferences
    are needed later, add a user_id column and change the PK — forward-compat
    is preserved because this entity is currently only read/written by one user
    per tenant.
    """

    tenant_id: UUID
    # price_alerts: toggles flash alerts for significant price moves.
    price_alerts: bool
    # news_alerts: toggles news article arrival notifications.
    news_alerts: bool
    # movers_alerts: toggles pre-market / intraday movers notifications.
    movers_alerts: bool
    # contradiction_alerts: toggles knowledge-graph contradiction signals.
    contradiction_alerts: bool
    updated_at: datetime
