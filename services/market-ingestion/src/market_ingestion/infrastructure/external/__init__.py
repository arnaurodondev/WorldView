"""External-API adapters that aren't bound to the provider chain.

WHY a separate ``external`` package (vs ``infrastructure/adapters/providers/``):
The ``providers`` directory hosts the routed-provider chain used by the
ingestion scheduler — every adapter there must implement the full
``ProviderAdapter`` port (fetch_ohlcv, fetch_quotes, fetch_fundamentals,
fetch_news_sentiment …).  PLAN-0053 T-C-3-02 needs a *narrow* adapter that
only fetches Alpha Vantage's ``OVERVIEW`` endpoint as a fallback for two
specific fields (eps_ttm + beta) used by the backfill script.  Keeping it
out of ``providers/`` avoids implementing seven unused methods just to
fall back two values.
"""
