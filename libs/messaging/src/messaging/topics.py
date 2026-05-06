"""Topic name constants.

Central registry of all Kafka topic names used across the platform.
Import from here — never hardcode topic strings in services.
"""

# ── Portfolio domain (S1) ──────────────────────────────────────────────────────
PORTFOLIO_EVENTS = "portfolio.events.v1"

# ── Market domain (S2 / S3) ───────────────────────────────────────────────────
MARKET_DATASET_FETCHED = "market.dataset.fetched"
MARKET_INSTRUMENT_CREATED = "market.instrument.created"
MARKET_INSTRUMENT_UPDATED = "market.instrument.updated"

# ── Content domain (S4 / S5) ──────────────────────────────────────────────────
CONTENT_ARTICLE_RAW = "content.article.raw.v1"
CONTENT_ARTICLE_STORED = "content.article.stored.v1"

# ── Intelligence domain (S6 / S7) ─────────────────────────────────────────────
NLP_ARTICLE_ENRICHED = "nlp.article.enriched.v1"
NLP_SIGNAL_DETECTED = "nlp.signal.detected.v1"
INTELLIGENCE_TEMPORAL_EVENT = "intelligence.temporal_event.v1"

# ── Knowledge Graph domain (S7) ───────────────────────────────────────────────
# entity.provisional.queued.v1 — emitted by S6 UnresolvedResolutionWorker when a
#   new provisional entity is discovered; consumed by S7 ProvisionalQueuedConsumer.
ENTITY_PROVISIONAL_QUEUED = "entity.provisional.queued.v1"
# entity.dirtied.v1 — emitted by S7 when entity data changes and downstream
#   consumers (e.g. enrichment workers) must reprocess the entity.
ENTITY_DIRTIED = "entity.dirtied.v1"
# entity.canonical.created.v1 — emitted by S7 when a new canonical entity is
#   persisted; consumed by other S7 workers that react to new entities.
ENTITY_CANONICAL_CREATED = "entity.canonical.created.v1"
# graph.state.changed.v1 — emitted by S7 outbox when the knowledge graph topology
#   changes (edges added/removed); consumers can use it to invalidate caches.
GRAPH_STATE_CHANGED = "graph.state.changed.v1"

# ── Prediction market domain (S4 / S3) ────────────────────────────────────────
MARKET_PREDICTION = "market.prediction.v1"

# ── Dead-letter queues (platform standard — D-05) ─────────────────────────────
# Every service that routes unprocessable Kafka events MUST publish to one of
# these DLQ topics instead of silently dropping the message.
MARKET_DEAD_LETTER = "market.dead-letter.v1"
