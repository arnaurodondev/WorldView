"""Dataset taxonomy and TTL policy table for the market-data cache.

PLAN-0107 section A.1 -- the cache key shape is::

    f"market_data:{dataset_type}:{symbol}:{period_key}"

where ``dataset_type`` is a member of :class:`DatasetType` defined below. The
enum is intentionally distinct from
:class:`market_ingestion.domain.enums.DatasetType` (which uses provider-call
granularity such as ``ohlcv``/``fundamentals``); the cache layer needs **finer
grain** (``ohlcv_eod`` vs ``ohlcv_intraday``) because their TTLs differ by more
than two orders of magnitude.

Schema-drift mitigation (PLAN-0107 section A.5)
-----------------------------------------------
The values of :class:`DatasetType` are part of the **cache key on disk**
(Valkey). They are **append-only** and **never renamed**:

  * Adding a new member is safe -- old payloads simply will not match the new
    key.
  * Renaming a member silently orphans every existing cached entry under the
    old name. If a removal is ever required, the migration PR must include a
    ``ValkeyClient.delete_pattern("market_data:<removed>:*")`` step.

The TTL table below is reviewed at the same time as routing-table changes --
keep the docstring rationale current when a value moves.
"""

from __future__ import annotations

from collections.abc import Mapping

# R25: the cache dataset taxonomy now lives in the domain layer so the
# application layer can reference it without importing infrastructure.  We
# re-export it here under the historical name ``DatasetType`` so existing
# infrastructure-side imports (and the TTL table below) keep working unchanged.
from market_ingestion.domain.enums import (
    CacheDatasetType as DatasetType,  # — public re-export
)

#: TTL in seconds for each :class:`DatasetType`. Rationale: see PLAN-0107
#: section A.1 TTL policy table.
CACHE_TTL_SECONDS: Mapping[DatasetType, int] = {
    DatasetType.OHLCV_EOD: 21_600,  # 6 h -- EOD bars finalize once/day
    DatasetType.OHLCV_INTRADAY: 60,  # 60 s -- intraday but not real-time
    DatasetType.FUNDAMENTALS_SNAPSHOT: 86_400,  # 24 h -- reported quarterly
    DatasetType.EARNINGS_CALENDAR: 43_200,  # 12 h -- mostly stable intraday
    DatasetType.DIVIDENDS: 86_400,  # 24 h -- event-driven
    DatasetType.SPLITS: 86_400,  # 24 h -- event-driven
    DatasetType.EXCHANGES_LIST: 604_800,  # 7 d -- reference data
    DatasetType.SYMBOL_SEARCH: 3_600,  # 1 h -- search results stable enough
}
