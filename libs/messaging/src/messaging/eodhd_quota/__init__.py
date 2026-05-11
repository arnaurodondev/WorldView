"""eodhd_quota — shared monthly EODHD credit quota enforcement via Valkey.

Usage::

    from messaging.eodhd_quota import EodhdQuotaService, QuotaCheckResult, QuotaStatus

    service = EodhdQuotaService(valkey_client)
    result = await service.try_consume(cost=1, service="market-ingestion", symbol="AAPL")
    if result == QuotaCheckResult.HARD_LIMIT_EXCEEDED:
        # block — quota exhausted for this month
        ...
"""

from messaging.eodhd_quota.quota_service import (
    EodhdQuotaService,
    QuotaCheckResult,
    QuotaStatus,
)

__all__ = [
    "EodhdQuotaService",
    "QuotaCheckResult",
    "QuotaStatus",
]
