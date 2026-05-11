"""ORM models package.

``Base.metadata`` aggregates all tables via the imports below.
Import ``Base`` from this module when wiring Alembic's ``target_metadata``.
"""

from market_ingestion.infrastructure.db.models.base import Base
from market_ingestion.infrastructure.db.models.ingestion_task import IngestionTaskModel
from market_ingestion.infrastructure.db.models.outbox_event import OutboxEventModel
from market_ingestion.infrastructure.db.models.polling_policy import PollingPolicyModel
from market_ingestion.infrastructure.db.models.provider_budget import ProviderBudgetModel
from market_ingestion.infrastructure.db.models.symbol_tier import SymbolTierModel
from market_ingestion.infrastructure.db.models.watermark import WatermarkModel

__all__ = [
    "Base",
    "IngestionTaskModel",
    "OutboxEventModel",
    "PollingPolicyModel",
    "ProviderBudgetModel",
    "SymbolTierModel",
    "WatermarkModel",
]
