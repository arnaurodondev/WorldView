"""Typed HTTP clients for downstream services.

The gateway never calls services by raw URL — it uses these client classes
which provide typed method signatures and handle errors consistently.

Originally a single 1424-line module; TASK-W4-06 (REF-002) split it into a
package, one file per logical surface, while preserving every existing
import path via this ``__init__.py`` re-export shim:

- ``base``       — ``DownstreamError``, ``ServiceClients``, ``_checked_get``,
                   ``_checked_post`` (the retry / error-translation primitives).
- ``instrument`` — ``get_company_overview``, ``get_instrument_page_bundle``.
- ``portfolio``  — ``get_portfolio_bundle``, ``get_watchlist_insights``.
- ``market``     — ``get_market_heatmap``, ``get_top_movers``, the GICS taxonomy
                   constants and ``_screener_for_sector`` helper.
- ``dashboard``  — ``get_dashboard_snapshot``.
- ``news``       — ``get_relevant_news``, ``get_map_layers``.

Why every public name is re-exported at the package root:
    Route modules, use-case classes, ``http_utils.py`` and several test
    files already import via ``from api_gateway.clients import …``.
    A pure split into submodules would break every one of those imports.
    Keeping the shim means *zero* downstream import updates are required
    and the existing test suite mocks (``patch("api_gateway.clients.asyncio.sleep")``
    in ``tests/unit/test_clients.py``) continue to resolve.

Why ``asyncio`` is imported here (and not used at module scope):
    Several unit tests patch ``api_gateway.clients.asyncio.sleep`` to skip
    the real retry-backoff delays.  The patch target must exist as an
    attribute of this module.  Because ``asyncio`` is a singleton module,
    patching the ``sleep`` attribute also affects the imports in
    ``api_gateway.clients.base`` — which is exactly what we want.
"""

from __future__ import annotations

# Imported for back-compat: tests patch ``api_gateway.clients.asyncio.sleep``
# to bypass real retry delays.  Removing this line would break those patches.
import asyncio  # noqa: F401

from api_gateway.clients.base import (
    DownstreamError,
    ServiceClients,
    _checked_get,
    _checked_post,
    logger,
)
from api_gateway.clients.dashboard import get_dashboard_snapshot
from api_gateway.clients.instrument import (
    get_company_overview,
    get_instrument_page_bundle,
)
from api_gateway.clients.market import (
    _GICS_TO_DB_SECTOR,
    GICS_SECTORS,
    _screener_for_sector,
    get_market_heatmap,
    get_top_movers,
)
from api_gateway.clients.news import get_map_layers, get_relevant_news
from api_gateway.clients.portfolio import (
    get_portfolio_bundle,
    get_watchlist_insights,
)

__all__ = [
    "GICS_SECTORS",
    "DownstreamError",
    "ServiceClients",
    "_GICS_TO_DB_SECTOR",
    "_checked_get",
    "_checked_post",
    "_screener_for_sector",
    "get_company_overview",
    "get_dashboard_snapshot",
    "get_instrument_page_bundle",
    "get_map_layers",
    "get_market_heatmap",
    "get_portfolio_bundle",
    "get_relevant_news",
    "get_top_movers",
    "get_watchlist_insights",
    "logger",
]
