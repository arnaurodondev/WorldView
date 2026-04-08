"""Topic name constants.

Central registry of all Kafka topic names used across the platform.
Import from here — never hardcode topic strings in services.
"""

# ── Portfolio domain (S1) ──────────────────────────────────
PORTFOLIO_EVENTS = "portfolio.events.v1"

# ── Market domain (S2 / S3) ───────────────────────────────
MARKET_DATASET_FETCHED = "market.dataset.fetched"
MARKET_INSTRUMENT_CREATED = "market.instrument.created"
MARKET_INSTRUMENT_UPDATED = "market.instrument.updated"

# ── Content domain (S4 / S5) ──────────────────────────────
CONTENT_ARTICLE_RAW = "content.article.raw.v1"
CONTENT_ARTICLE_STORED = "content.article.stored.v1"

# ── Intelligence domain (S6 / S7) ─────────────────────────
NLP_ARTICLE_ENRICHED = "nlp.article.enriched.v1"
NLP_SIGNAL_DETECTED = "nlp.signal.detected.v1"
INTELLIGENCE_TEMPORAL_EVENT = "intelligence.temporal_event.v1"
