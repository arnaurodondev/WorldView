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
KAFKA_LAG_FAIL = 100_000  # ...above this → FAIL for a group with NO live members (wedged/dead)
# Member-aware backstop: a group WITH live members and a large lag is a draining
# backfill, not a wedge — the 2026-07-16 195k-doc news backfill legitimately drove
# nlp-pipeline-group to ~187k lag while consuming healthily. Only FAIL a
# live-member group when lag is so extreme (>this hard ceiling) that even a
# backfill can't explain it; otherwise WARN. A 0-member group FAILs at
# KAFKA_LAG_FAIL (a stopped consumer is a real regression regardless of size).
KAFKA_LAG_FAIL_HARD = 1_000_000  # live-member group above this → FAIL (pathological)
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

# ── Disk / PVC free-space floors (P0-B: MinIO full → write-halt regression) ───
# The 2026-07-15 P0 was worldview-silver filling its 20Gi MinIO PVC to the
# minimum-free-drive guard, halting ALL PutObject and stalling the 88k
# content-store backlog. These floors alert BEFORE a volume wedges. Calibrated
# under observed-good (2026-07-16: minio /export 50% free, postgres 66% free,
# kafka 98% free) so a slow leak trips WARN with headroom to act.
PVC_FREE_PCT_WARN = 20.0  # data volume free % below this → WARN (fill trend)
PVC_FREE_PCT_FAIL = 8.0  # ...→ FAIL (near MinIO min-free guard / write-halt)
PVC_FREE_BYTES_FAIL = 1_500_000_000  # absolute 1.5 GiB floor regardless of %
# INODE headroom (the P0 that byte-checks missed entirely): the polymarket bronze
# firehose writes millions of tiny objects, so the MinIO PVC can exhaust INODES
# long before bytes (2026-07-16: 41% bytes used but 75% inodes used). df -i on the
# same data volumes. Calibrated under observed-good (25% inodes free) so a slow
# small-object leak trips WARN with room to expand/expire before writes halt.
PVC_FREE_INODE_PCT_WARN = 20.0  # inode-free % below this → WARN (small-object growth)
PVC_FREE_INODE_PCT_FAIL = 8.0  # ...→ FAIL (inode exhaustion imminent → write-halt)
# Re-fetchable object buckets that MUST carry a lifecycle expiry rule: their
# contents are derivable (bronze = raw firehose payloads, silver = canonical
# bodies) so without expiry they grow unbounded and exhaust inodes/bytes. bronze
# got a 7-day expiry after the P0; silver had NONE (this guard would have caught
# the durability gap the byte-check missed).
MINIO_LIFECYCLE_BUCKETS = ["worldview-bronze", "worldview-silver"]
# df targets: (namespace, pod name-prefix, container-or-'', mountpoint). Each is
# the volume that carries irreplaceable state (article bodies, DBs, event log).
PVC_DF_TARGETS = [
    ("infra", "minio-", "", "/export"),  # article bodies — the P0 volume
    ("infra", "postgres-0", "postgres", "/var/lib/postgresql/data"),  # all service DBs
    ("infra", "kafka-broker-0", "kafka", "/bitnami/kafka"),  # event log
]

# ── Ephemeral-secret guard (roll-fragility class) ────────────────────────────
# Every non-optional Secret a workload references (envFrom / secretKeyRef /
# volume) MUST exist NOW. A running pod keeps its injected secret in memory, so a
# secret deleted after pod-create is invisible until the next roll — when the pod
# fails to start. This guard catches that latent trap by comparing live refs vs
# present secrets. No threshold: any missing non-optional ref is a FAIL.

# ── Synthetic monitor (prod-smoke CronJob) ───────────────────────────────────
PROD_SMOKE_CRONJOB = "prod-smoke"  # */30 monitoring CronJob
PROD_SMOKE_LOOKBACK = 5  # inspect the most-recent N Jobs
PROD_SMOKE_MAX_FAILED = 1  # more than this many Failed in the window → FAIL

# ── Pod restart-rate (gliner OOM P1-A + nlp poison-pill P0-A regressions) ─────
# restarts / pod-age-hours on liveness-sensitive pods. gliner OOMs ~3/h when its
# 12Gi cap is undersized; the nlp article-consumer poison-pills on a many-mention
# article. A healthy pod restarts rarely, so a low rate floor is sensitive.
POD_RESTART_RATE_WARN = 0.5  # restarts/hour → WARN
POD_RESTART_RATE_FAIL = 2.0  # ...→ FAIL (OOM / poison-pill storm)
# (namespace, pod name-prefix) for the liveness-sensitive workloads.
RESTART_RATE_TARGETS = [
    ("infra", "gliner"),
    ("worldview", "nlp-pipeline-article-consumer"),
    ("worldview", "content-store-article-consumer"),
]

# ── Outbox per-table backlog + age (content-ingestion 111k miss regression) ──
# The existing aggregate outbox check sums undispatched>10m across DBs. This adds
# a PER-TABLE floor plus an OLDEST-UNDISPATCHED-AGE dimension: a small number of
# very OLD undispatched rows signals a wedged dispatcher even when the total is
# low, and a per-table count catches a single service (content-ingestion hit
# 111k) that a global sum could mask. All observed 0-age on 2026-07-16.
OUTBOX_TABLE_BACKLOG_WARN = 500  # undispatched rows in one table → WARN
OUTBOX_TABLE_BACKLOG_FAIL = 10_000  # ...→ FAIL (mass un-dispatch, 111k class)
OUTBOX_AGE_WARN_MIN = 10.0  # oldest undispatched older than this → WARN
OUTBOX_AGE_FAIL_MIN = 60.0  # ...→ FAIL (dispatcher wedged, not just slow)
OUTBOX_DBS = [
    "portfolio_db",
    "intelligence_db",
    "nlp_db",
    "market_data_db",
    "content_store_db",
    "alert_db",
    "content_ingestion_db",
    "ingestion_db",
    "rag_db",
    "gateway_db",
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
# Daily OHLCV history coverage (F1/D2: 1d held ~1 bar/instrument, 3 dates → the
# entire returns/levels/heatmap surface was null). Floors sit above the broken
# state so an incomplete daily backfill is flagged while it fills in.
MD_OHLCV_1D_DATES_WARN = 30  # distinct 1d bar_dates (was 3 — no daily history)
MD_OHLCV_1D_BARS_PER_INST_WARN = 60  # avg 1d bars/instrument (was ~2)
# Per-timeframe staleness: the aggregate "OHLCV freshness" check uses the newest
# bar across ALL timeframes, so a fresh 1m bar masks a stalled intraday timeframe
# (e.g. 15m resampler wedged) or a dead daily feed. Judge the STALEST intraday
# timeframe and the daily timeframe independently. Intraday must be near-live
# (2026-07-16: 15m/5m/30m all <1.1h). Daily closes once/session, so up to a long
# weekend of staleness is normal (observed 15.6h).
MD_INTRADAY_TIMEFRAMES = {"1m", "5m", "15m", "30m", "1h", "4h"}
# WARN ceiling must clear the LARGEST intraday interval (4h): a 4h bar is normally
# up to one interval + resampling lag old (observed 3.9h), so a 4.0h floor would
# flap on it. 6h stays well under a genuinely dead intraday pipeline while not
# firing on the 4h timeframe's normal age.
MD_INTRADAY_STALE_WARN_H = 6.0  # stalest intraday timeframe newest bar → WARN
MD_INTRADAY_STALE_FAIL_H = 24.0  # ...→ FAIL (a resampler/feed for that tf is dead)
MD_DAILY_STALE_WARN_H = 48.0  # newest 1d bar older than this → WARN (weekend-tolerant)
MD_DAILY_STALE_FAIL_H = 120.0  # ...→ FAIL (daily feed dead >5 days)
# Prediction market→event linkage (D6: every one of 101 markets had event_id
# NULL despite a populated prediction_events table). % markets with event_id set.
MD_PRED_EVENT_LINK_WARN = 50.0

# ── Knowledge-graph (S7 / intelligence_db) ───────────────────────────────────
KG_ENTITIES_FLOOR = 1_500  # canonical_entities
KG_FIN_INSTRUMENTS_FLOOR = 400  # entity_type='financial_instrument'
KG_DESC_COVERAGE_WARN = 40.0  # % canonical entities with a description
KG_EMBED_COVERAGE_WARN = 60.0  # % entity_embedding_state embedded
KG_RELATIONS_FLOOR = 300  # active relations (valid_to IS NULL)
KG_RELATION_TYPES_FLOOR = 10  # distinct canonical_type in relations
KG_TEMPORAL_EVENTS_FLOOR = 100  # temporal_events rows
KG_AGE_VERTEX_FLOOR = 500  # AGE worldview_graph vertices (shadow sync alive)
# Promoter drain sits at a low steady state (~18%: most raw evidence is corroborating
# duplicates that never promote), so a 20% floor flapped a permanent, boundary-hugging
# WARN. Recalibrated just under the observed-good band so it only fires on a real drop.
KG_EVIDENCE_PROMOTED_WARN = 15.0  # % relation_evidence_raw promoted (promoter drain)
# Grounded-entity golden facts (deterministic — Apple is a stable megacap anchor).
KG_GOLDEN_TICKER = "AAPL"
KG_GOLDEN_NAME_SUBSTR = "Apple"
KG_GOLDEN_ISIN = "US0378331005"
# fundamentals_ohlcv embedding coverage (D1: all 713 rows NULL embedding + empty
# source_text while last_refreshed_at was current — "stamps success, writes
# nothing"). Root cause: KG→market-data internal-JWT rejected (see JWT probe).
KG_FUND_OHLCV_EMBED_WARN = 50.0  # % fundamentals_ohlcv rows with an embedding
# Generic "stamped-but-empty" anti-pattern: a view_type whose worker stamped
# last_refreshed_at on many rows but left source_text empty. Calibrated against
# observed-good (2026-07-16: definition 0% empty, narrative 15% empty) vs the D1
# silent-failure signature (fundamentals_ohlcv was 100% empty). A gradual
# backfill legitimately sits near 50% empty mid-fill (e.g. 578/1105 unfilled with
# last_refreshed_at seconds old), so 0.5 as a HARD FAIL flaps on any in-progress
# fill. FAIL only when the worker persists almost nothing (near-total empty = true
# "reports success, writes nothing"); WARN in the ambiguous mid-fill band. The
# actual D1 root cause (KG→market-data JWT) is caught deterministically by the
# _internal_jwt_probe, so this stays a coverage signal, not the primary guard.
KG_STAMPED_EMPTY_FRACTION_FAIL = 0.9  # ~all stamped rows empty → silent-failure worker
KG_STAMPED_EMPTY_FRACTION_WARN = 0.5  # partial fill / backfill in progress → WARN
KG_STAMPED_MIN_ROWS = 50  # only judge view_types with at least this many stamped rows
# PLAN-0056 prediction entity-linking Kafka groups (must exist + bounded lag).
KG_PREDICTION_GROUPS = ["kg-prediction-enriched-group", "kg-prediction-move-group"]
KG_PREDICTION_LAG_WARN = 5_000
KG_PREDICTION_LAG_FAIL = 100_000
# Internal-JWT service→service signing (D1 empty-key class). KG mints an
# X-Internal-JWT to reach market-data; an empty KNOWLEDGE_GRAPH_INTERNAL_JWT_
# PRIVATE_KEY makes market-data (skip_verification=false) return 401 for every
# call, silently deferring all fundamentals_ohlcv embeddings. The probe mints the
# worker's exact token and asserts a 200, not a 401.
JWT_PROBE_DEV_SECRET = "dev-skip-verification-key-for-kg-fundamentals"  # noqa: S105 (public dev HS256 fallback, not a credential)
# Every workload that MINTS an internal JWT carries a `*_INTERNAL_JWT_PRIVATE_KEY`
# env var; an empty one silently 401s every downstream call (the D1 class, but for
# ANY signer not just KG). We scan all worldview pods for such a var and assert it
# is non-empty — generic across signers (currently api-gateway + knowledge-graph),
# auto-covering a new signer the day it ships. A real RSA PEM is ~1.7 KB.
JWT_SIGNING_KEY_MIN_LEN = 200  # a real PEM private key is >>200 chars; empty/placeholder is short
# relation_evidence is RANGE-partitioned by month with a DEFAULT catch-all. Rows
# landing in DEFAULT escaped every monthly range (NULL/out-of-range evidence_date)
# — bounded is fine (2026-07-16: 746), a spike means the monthly-partition worker
# stopped creating current partitions and everything falls through. The worker
# health is also asserted directly: a partition covering the CURRENT and NEXT
# month must exist (2026-07-16: partitions pre-created through 2026_12).
KG_EVIDENCE_DEFAULT_PARTITION_WARN = 3_000  # rows in relation_evidence_default → WARN
KG_EVIDENCE_DEFAULT_PARTITION_FAIL = 50_000  # ...→ FAIL (monthly worker wedged, mass fall-through)

# ── NLP pipeline (S6 / nlp_db) ───────────────────────────────────────────────
NLP_CHUNKS_FLOOR = 3_000  # chunks
NLP_EMBED_READY_WARN = 90.0  # % chunk_embeddings embedding_status='ready'
NLP_MENTIONS_24H_FAIL = 50  # entity_mentions in last 24h (near-zero → NER stalled)
NLP_ROUTING_FLOOR = 300  # routing_decisions rows
# Relevance-coverage % over ALL document_source_metadata is structurally low and
# NOT a regression signal: most news rows are dedup/corroboration/backfill docs
# that legitimately bypass LLM relevance scoring (a 195k-doc news backfill drove
# coverage to ~17%). The old 60% floor flapped a permanent WARN. Recalibrated to a
# realistic drift floor AND paired with a direct liveness signal (scored/24h) that
# is immune to backfill dilution — the scorer being ALIVE is what we actually care
# about (2026-07-16: 1700 scored/24h, 550/6h, coverage ~17%).
NLP_RELEVANCE_COVERAGE_WARN = 10.0  # % dsm with a relevance score → WARN (drift floor)
NLP_RELEVANCE_SCORED_24H_FLOOR = 200  # rows relevance-scored in last 24h → WARN if below (scorer stalled)
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

# ── rag-chat golden regression set (chat-quality audit 2026-07-15) ───────────
# Phrases that signal a (possibly false) refusal / tool-failure template. A
# question whose ground truth IS in the store must NOT trip these.
RAG_REFUSAL_PATTERNS = [
    "not available",
    "no data",
    "couldn't retrieve",
    "could not retrieve",
    "not present",
    "no records",
    "unable to",
    "data source may be unavailable",
    "try again",
]
# Date-anchored fundamentals: MSFT FY-Q4-2024 revenue for the quarter ending
# 2024-06-30 = $64.727B IS in market_data_db.fundamental_metrics, yet chat
# falsely refused AND confabulated the period to "Q4 2026" (audit FAIL). The
# answer must NOT refuse and should surface the revenue magnitude.
RAG_DATE_ANCHOR_QUESTION = (
    "What was Microsoft's total revenue for its fiscal quarter ending June 30, 2024? Give the dollar figure."
)
RAG_DATE_ANCHOR_MUST_CONTAIN_ANY = ["64", "$64"]  # $64.727B — tolerant to rounding
# Prediction-market routing: markets for "Donald Trump win the 2028 US
# Presidential Election" are live, but chat routed GENERAL and refused (audit
# FAIL — tool not invoked). Answer must engage the market, not give a generic
# refusal.
RAG_PREDICTION_QUESTION = "What do prediction markets say about Donald Trump winning the 2028 US Presidential Election?"
RAG_PREDICTION_MUST_CONTAIN_ANY = ["trump", "2028", "market", "odds", "probability", "%"]

# ── v4: S9 gateway composition-route contracts (driven in-pod via localhost:8000) ─
# The gateway-S2S fix (fix/gateway-s2s-auth) made the gateway accept its OWN
# internal JWT (X-Internal-JWT) as a principal, restoring ~8 backend-composing
# routes that previously 401'd for every service-to-service caller (chat tools,
# briefings, screener). We drive each real /v1 gateway route in-pod with a user
# internal JWT and assert a 200 + a non-trivial, well-shaped payload, so a
# re-break (guard removed / prefix regressed) is visible — not a silent []-return.
GW_ROUTE_MIN_LEN = 5  # a 200-but-empty envelope below this many bytes → WARN

# ── v4: OHLCV daily-source authority (provider_priority ↔ source integrity) ────
# ohlcv_bars upserts resolve conflicts by provider_priority (higher wins), so the
# priority baked onto each row MUST match its source's canonical rank. A drift in
# that map lets a low-priority feed overwrite an authoritative bar. Canonical map
# (services/market-data provider registry): alpaca=110, derived=110,
# yahoo_finance=80, eodhd=60. (Note: daily history is EODHD-backfilled and thus
# multi-source — the authority is defined by priority, not by row-count share.)
MD_SOURCE_PRIORITY: dict[str, int] = {"alpaca": 110, "derived": 110, "yahoo_finance": 80, "eodhd": 60}
MD_DAILY_AUTHORITY_PRIORITY = 110  # a priority-110 source (alpaca/derived) must contribute 1d bars

# ── v4: KG anti-fabrication / relation precision / graph-edge parity ──────────
KG_SELF_LOOP_FAIL = 0  # active self-loop relations (subject==object) — must be 0
KG_RELATION_PRECISION_FLOOR = 95.0  # % active relations with confidence > floor (precision gate)
KG_RELATION_CONF_MIN = 0.1  # confidence floor used by the precision gate
# AGE shadow graph vs relational relations: the AGE edge count tracks the active
# relation count within a band (both alive, neither side wedged). 2026-07-16:
# 5369 AGE edges vs 5185 active relations ≈ 1.04x.
KG_AGE_PARITY_LO = 0.5  # AGE_edges / active_relations lower bound → below = AGE sync stalled
KG_AGE_PARITY_HI = 1.8  # ...upper bound → above = relational side lost rows
# public.graph_edges matview emits BOTH directions → ≈2x the eligible (active,
# conf>floor, non-self-loop) relations. 2026-07-16: 10242 vs 5185 eligible ≈ 1.98x.
KG_MATVIEW_PARITY_LO = 1.4
KG_MATVIEW_PARITY_HI = 2.2
# Anti-fabrication spot-probe: a known financial_instrument's stored description
# must not assert a contradicting human/role identity (a classic KG hallucination
# where a ticker's description is filled with a person's bio). AAPL's real
# description opens "Apple Inc. designs, manufactures…" — none of these appear.
KG_GOLDEN_DESC_FORBIDDEN = ["ceo of", "president of", "prime minister", "politician", "actor", "is a person"]

# ── v4: outcome-based pipeline liveness (per 24h) ─────────────────────────────
# Floors sit far BELOW observed 24h throughput (2026-07-16: docs 198k, relations
# 5k, embeddings 51k, pred-snaps 73k) — they catch a *silently wedged* worker
# (near-zero output) faster than consumer lag, without flapping on churn. A wedged
# worker whose lag is still draining, or one that commits offsets but persists
# nothing, shows here as an outcome-count collapse.
PIPE_DOCS_24H_FLOOR = 200  # content_store_db.documents ingested
PIPE_RELATIONS_24H_FLOOR = 50  # intelligence_db.relations created
PIPE_EMBEDDINGS_24H_FLOOR = 200  # nlp_db.chunk_embeddings created
PIPE_PRED_SNAPS_24H_FLOOR = 200  # market_data_db.prediction_market_snapshots

# ── v4: TLS certificate expiry runway (extends the existing issued=True check) ─
# The issued-status check confirms cert-manager succeeded ONCE; this asserts the
# cert is not about to lapse (a renewal-loop failure only shows as imminent
# expiry, never as issued=False). 2026-07-16: api-tls notAfter 2026-10-13 ≈ 89d.
CERT_EXPIRY_WARN_DAYS = 21
CERT_EXPIRY_FAIL_DAYS = 7
