"""Application-layer query use cases for the market-data service.

Each module contains read-only use cases for one domain area.  Use cases
receive an already-entered ``UnitOfWork`` (opened by FastAPI dependency
injection) and delegate to the appropriate port.

Modules:
  - query_instruments  — instrument look-up and search
  - query_securities   — security look-up and listing
  - query_quotes       — latest quote retrieval
  - query_ohlcv        — OHLCV bar queries
  - query_fundamentals — fundamentals section queries
  - query_fundamental_metrics — timeseries and screening queries
"""
