"""Named thresholds / floors for the prod-QA harness — the single tuning knob.

Every numeric assertion in the suite reads a constant from here so drift is
adjustable in one place and reviewable in a diff. Floors are chosen to sit a
little BELOW the observed steady state of the live cluster (calibrated
2026-07-15 against the Hetzner single-node deploy, ~24h of data) so a re-run
catches a genuine regression without flapping on normal churn.

Classification convention used throughout:
    * HARD  → FAIL when breached (a broken invariant / dead liveness signal)
    * SOFT  → WARN when breached (coverage/volume still backfilling)
"""

from __future__ import annotations

# ── Expected Alembic heads (migration-drift, mirrors prod_e2e_smoke.py) ───────
# Revision ids are whatever the migration file declares — match EXACTLY.
EXPECTED_ALEMBIC_HEADS: dict[str, str] = {
    "alert_db": "0011",
    "content_ingestion_db": "0011_seed_pm_wave2_sources",
    "content_store_db": "0006",
    "ingestion_db": "0024",
    "intelligence_db": "0067",
    "market_data_db": "044",
    "nlp_db": "0024",
    "portfolio_db": "0027",
    "rag_db": "0010",
}
# DB → owning Deployment name label (for reading the image-baked head). None =
# migrator is a one-off Job (intelligence-migrations) → compare vs EXPECTED only.
DB_TO_DEPLOYMENT: dict[str, str | None] = {
    "alert_db": "alert",
    "content_ingestion_db": "content-ingestion",
    "content_store_db": "content-store",
    "ingestion_db": "market-ingestion",
    "intelligence_db": None,
    "market_data_db": "market-data",
    "nlp_db": "nlp-pipeline",
    "portfolio_db": "portfolio",
    "rag_db": "rag-chat",
}

# ── Platform / infra (coarse) ────────────────────────────────────────────────
POD_RESTART_WARN = 5  # restart count above this on a long-running pod → WARN (crashloop-ish)
KAFKA_LAG_WARN = 5_000  # per-group total lag above this → WARN (backlog)
KAFKA_LAG_FAIL = 100_000  # ...above this → FAIL (consumer wedged/dead)
DLQ_DB_BACKLOG_WARN = 50  # unresolved dead_letter_queue rows → WARN
DLQ_DB_BACKLOG_FAIL = 500  # ...→ FAIL (mass dead-lettering)
DLQ_DB_RATE_FAIL = 20  # unresolved rows arrived in last 1h → FAIL (skew storm)
OUTBOX_STUCK_FAIL = 50  # events undispatched >10m across all services → FAIL
SCHEMA_REGISTRY_SAFE_COMPAT = {"FULL", "FULL_TRANSITIVE"}

DLQ_TOPICS = [
    "alert.dead-letter.v1",
    "content.dead-letter.v1",
    "kg.dead-letter.v1",
    "market.dead-letter.v1",
    "nlp.dead-letter.v1",
]

# Consumer groups that MUST exist and have live members. A group present with
# assigned partitions but 0 members = a silently-stopped consumer. `probe-*`
# groups (architecture-test artifacts) are ignored by the group-health check.
EXPECTED_CONSUMER_GROUPS = [
    "nlp-pipeline-group",
    "content-store-consumer",
    "content-store-dedup-consumer",
    "kg-service-group-enriched",
    "kg-service-group-entity",
    "market-data-ohlcv",
    "market-data-quotes",
    "market-data-fundamentals",
    "market-data-prediction-markets",
    "market-data-prediction-history",
    "market-data-prediction-trades",
    "alert-service-group",
    "portfolio-instrument-sync",
]

# Expected long-running Deployments/StatefulSets by canonical name in `worldview`
# ns (a missing one = a process topology gap even if nothing is crashing).
EXPECTED_WORLDVIEW_WORKLOADS = [
    "api-gateway",
    "portfolio",
    "market-data",
    "market-ingestion",
    "content-ingestion",
    "content-store",
    "nlp-pipeline",
    "knowledge-graph",
    "rag-chat",
    "alert",
]

# ── Market-data (S3) ─────────────────────────────────────────────────────────
MD_INSTRUMENTS_FLOOR = 400  # instruments row count
MD_HAS_FUNDAMENTALS_FLOOR = 400  # instruments with has_fundamentals=true
MD_FUND_SNAPSHOT_FLOOR = 400  # instrument_fundamentals_snapshot rows
MD_OHLCV_BARS_FLOOR = 20_000  # ohlcv_bars total
MD_OHLCV_FRESH_WARN_H = 3.0  # newest crypto/equity bar age → WARN (Alpaca 24/7)
MD_OHLCV_FRESH_FAIL_H = 36.0  # ...→ FAIL (feed/key dead)
MD_DERIVED_BARS_FLOOR = 1_000  # is_derived bars (intraday resampling alive)
MD_EXPECTED_TIMEFRAMES = {"1m", "5m", "15m", "30m", "1h", "4h", "1d"}
MD_PRED_MARKETS_FLOOR = 50  # prediction_markets rows
MD_PRED_SNAPSHOTS_FLOOR = 10_000  # prediction_market_snapshots
MD_PRED_PRICES_FLOOR = 1_000  # prediction_market_prices (CLOB history consumer)
MD_PRED_TRADES_FLOOR = 500  # prediction_market_trades
MD_PRED_FRESH_WARN_H = 6.0
MD_PRED_FRESH_FAIL_H = 48.0
MD_INSIDER_FLOOR = 200  # insider_transactions rows

# ── Knowledge-graph (S7 / intelligence_db) ───────────────────────────────────
KG_ENTITIES_FLOOR = 1_500  # canonical_entities
KG_FIN_INSTRUMENTS_FLOOR = 400  # entity_type='financial_instrument'
KG_DESC_COVERAGE_WARN = 40.0  # % canonical entities with a description
KG_EMBED_COVERAGE_WARN = 60.0  # % entity_embedding_state embedded
KG_RELATIONS_FLOOR = 300  # active relations (valid_to IS NULL)
KG_RELATION_TYPES_FLOOR = 10  # distinct canonical_type in relations
KG_TEMPORAL_EVENTS_FLOOR = 100  # temporal_events rows
KG_AGE_VERTEX_FLOOR = 500  # AGE worldview_graph vertices (shadow sync alive)
KG_EVIDENCE_PROMOTED_WARN = 20.0  # % relation_evidence_raw promoted (promoter drain)
# Grounded-entity golden facts (deterministic — Apple is a stable megacap anchor).
KG_GOLDEN_TICKER = "AAPL"
KG_GOLDEN_NAME_SUBSTR = "Apple"
KG_GOLDEN_ISIN = "US0378331005"

# ── NLP pipeline (S6 / nlp_db) ───────────────────────────────────────────────
NLP_CHUNKS_FLOOR = 3_000  # chunks
NLP_EMBED_READY_WARN = 90.0  # % chunk_embeddings embedding_status='ready'
NLP_MENTIONS_24H_FAIL = 50  # entity_mentions in last 24h (near-zero → NER stalled)
NLP_ROUTING_FLOOR = 300  # routing_decisions rows
NLP_RELEVANCE_COVERAGE_WARN = 60.0  # % document_source_metadata with llm_relevance_score
NLP_STUCK_EMBED_WARN = 5  # embedding_pending rows at retry_count>=5
NLP_EXPECTED_SOURCE_TYPES = {"eodhd", "sec_edgar", "polymarket"}

# ── Content ingestion / store (S4 / S5) ──────────────────────────────────────
CS_DOCS_FLOOR = 1_000  # content_store_db documents
CS_DOCS_24H_WARN = 200  # docs ingested in last 24h (under-fetch)
CS_FRESH_WARN_H = 6.0  # newest doc age
CS_FRESH_FAIL_H = 30.0
CS_TITLE_COVERAGE_WARN = 95.0  # % documents with a title (SEC primary-doc fix)
CI_SOURCES_ENABLED_FLOOR = 5  # enabled polling sources
CI_TASK_FAILED_RATIO_WARN = 0.10  # failed/total content_ingestion_tasks

# ── Market-ingestion (S2 / ingestion_db) ─────────────────────────────────────
MI_TASKS_FLOOR = 1_000  # ingestion_tasks rows
MI_RUNNING_STUCK_WARN = 100  # tasks in RUNNING (possible stuck leases)

# ── rag-chat (S8) golden Q&A ─────────────────────────────────────────────────
# Deterministic-ish: the answer must ground a real, recent price figure and name
# the company. We assert SHAPE (a $ number + the ticker/name), never an exact
# value (prices move every session).
RAG_GOLDEN_QUESTION = "What was AAPL's most recent closing price?"
RAG_GOLDEN_MUST_CONTAIN_ANY = ["apple", "aapl"]  # case-insensitive
RAG_MIN_ANSWER_LEN = 20
