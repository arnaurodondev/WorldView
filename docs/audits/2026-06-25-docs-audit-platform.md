# Platform Documentation Audit — Synthesis & Cross-Document Consistency Sweep

> **Date**: 2026-06-25 · **Branch**: `feat/md-reliability-followups` ·
> **Scope**: All per-service docs (`docs/services/*.md` + `services/*/.claude-context.md`),
> all lib docs (`docs/libs/*.md`), the frontend doc, and root docs
> (`README.md`, `AGENTS.md`, `docs/MASTER_PLAN.md`, `docs/PRODUCT_CONTEXT.md`).

This report synthesizes a fan-out per-component documentation refresh and adds a
final **cross-document consistency sweep** that verified every shared fact
(service/lib counts, ports, database placement, Kafka topic names, internal links)
against the live code and `infra/` ground truth.

---

## 1. Per-Component Health

| Component | Health | Notes |
|-----------|--------|-------|
| alert | minor-drift | Added entire PLAN-0113 user-rule engine surface (5 alert-rules endpoints, RuleType enum, alert_rules table 0010, rule-poller process); corrected alert_type column type, digest cadence (weekly), JWT-derived ids, migration head 0010 |
| api-gateway | minor-drift | Rewrote stale internal-module tree (no monolithic `proxy.py`); corrected rate-limit defaults (2000), middleware order, admin path, route count (~186), removed false "fail-open on Valkey" rule |
| content-ingestion | minor-drift | Documented `DocumentReadyConsumer` (was "producer-only"), `content.document.deleted.v1`, real JWT auth, EODHD ticker-news adapter, migrations 0008/0009, DLQ payload column, MinIO key path |
| content-store | **major-drift** | Removed phantom `GET /api/v1/articles[/{id}]`; documented real cluster-sizes/cluster-articles routes, Internal-JWT auth, 4th dedup-consumer process, `content.article.stored.v1` re-consumption |
| intelligence-migrations | **major-drift** | Head 0038→**0062** (58 revisions); added 24 missing revisions, `ticker_aliases`, `relations_history`, sector-seed script, corrected relation_type_registry/entity_type CHECK history, OLAP host placement |
| knowledge-graph | refreshed | DB placement (intelligence_db on postgres-intelligence; legacy market_kg in kg_db) verified accurate |
| market-data | refreshed + sweep fix | **Topic routing table corrected** (see §3): instrument events go to dedicated topics, not `market.events.v1` |
| market-ingestion | refreshed | Ports/DB/topics verified accurate |
| nlp-pipeline | refreshed | Dual-DB (`nlp_db` + `intelligence_db`, ALEMBIC_ENABLED=false) verified accurate |
| portfolio | refreshed | `holding.changed.v1` gating note verified; recompute topic name matches code |
| rag-chat | refreshed | Ports/DB/tool-loop manifest verified accurate |
| libs (×8) | refreshed | `common, contracts, messaging, ml-clients, observability, prompts, storage, tools` — count verified = 8 |
| worldview-web (frontend) | refreshed | Port 3001, S9-only contract verified |
| Root docs | minor-drift + sweep fixes | README port-map/DB-split + broken link fixed (see §3) |

---

## 2. Cross-Document Facts Verified Against Code (✅ consistent)

- **Service count = 11** (10 FastAPI services S1–S10 + `intelligence-migrations`).
  README, AGENTS.md, MASTER_PLAN all agree.
- **Lib count = 8** (`common, contracts, messaging, ml-clients, observability,
  prompts, storage, tools`). README §Documentation, AGENTS.md tree, and
  MASTER_PLAN §"Eight shared Python packages" all agree and enumerate correctly.
- **Service ports** (`infra/compose/docker-compose.yml` is ground truth):
  S9=8000, S1=8001, S2=8002, S3=8003, S4=8004, S5=8005, S6=8006, S7=8007,
  S8=8008, S10=8010, frontend=3001. Every service-doc header + MASTER_PLAN
  port table + cross-service env-var URLs match.
- **Dev/infra ports**: Postgres 5432 / postgres-intelligence 5433, Kafka 9092,
  Schema Registry 8081, Valkey 6379, MinIO 7480/7481, Ollama 11434, GLiNER 8090,
  Grafana 3000, MailHog 8025, pgweb 8091, kafka-ui 8092 — all match compose.
- **Postgres OLTP/OLAP split** (workload split 2026-06-08):
  - `postgres` (OLTP, :5432): `portfolio_db, ingestion_db, market_data_db,
    content_ingestion_db, content_store_db, rag_db, gateway_db, alert_db` (8 DBs).
  - `postgres-intelligence` (OLAP, :5433→5432 internal): `nlp_db, intelligence_db,
    kg_db`.
  - AGE live graph `worldview_graph` lives in `intelligence_db`; legacy `market_kg`
    + `ticker_aliases` in `kg_db`. MASTER_PLAN §3 and the postgres init scripts agree.
- **Kafka topics**: All topic tokens in service docs map to a real `.avsc` schema
  and/or a code topic constant. Verified: `alert.created/delivered/email.sent.v1`,
  `content.article.raw/stored.v1`, `content.document.deleted.v1`,
  `entity.{canonical.created,dirtied,narrative.generated,provisional.queued,refresh}.v1`,
  `graph.state.changed.v1`, `intelligence.{contradiction,temporal_event}.v1`,
  `market.{dataset.fetched,instrument.created/updated/discovered.v1,prediction.v1}`,
  `nlp.{article.enriched,document.ready,signal.detected}.v1`,
  `portfolio.{events,watchlist.updated,holding.recompute_requested}.v1`,
  `relation.type.proposed.v1`, `watchlist.item_added/deleted`.
  - Note: runtime topic for holding recompute is the **dotted**
    `portfolio.holding.recompute_requested.v1` (per `topics.py` + contracts); the
    underscore form is only the `.avsc` filename. Docs correctly use the dotted form.

---

## 3. Cross-Document Inconsistencies FIXED in this sweep

1. **README port-map implied S1 Portfolio uses the OLAP database.**
   Row read `S1 Portfolio | 8001 | PostgreSQL (intelligence/OLAP) | 5433`, but
   `portfolio_db` lives on the OLTP `postgres` (:5432). The two columns are an
   independent (service | infra) listing, not a mapping. Rewrote the two infra
   rows to be self-describing and added a footnote clarifying the columns are
   independent, with a pointer to MASTER_PLAN §3.

2. **`market-data.md` topic-routing table was pre-QA-016 stale.**
   It claimed both `market.instrument.created` and `market.instrument.updated`
   publish to a single `market.events.v1` topic. Per
   `infrastructure/messaging/outbox/dispatcher.py` (`EVENT_TOPIC_MAP`), `market.events.v1`
   is the **old, incorrect** routing (it caused Portfolio S1 to miss instrument
   sync events). Corrected to per-event dedicated topics
   (`market.instrument.created`, `market.instrument.updated`,
   `market.instrument.discovered.v1`) with a QA-016 note; added the missing
   `discovered` row to both the topic and Avro-schema tables.

3. **`alert-service.md` produced-topics table omitted `alert.created.v1`.**
   `CreateAlertUseCase` publishes `alert.created.v1` via the outbox dispatcher
   (REST- and LLM-tool-created alerts). Added the row.

4. **Broken internal link in README.**
   `docs/testing/TESTING_GUIDE.md` → corrected to the real file
   `docs/testing/TEST_GUIDE.md`.

---

## 4. Aggregate Drift Tally

- **Components audited**: 11 services + 8 libs + frontend + 4 root docs = **24 units**
  (each with both its `docs/` page and, for services, its `.claude-context.md`).
- **Major-drift components**: 2 (`content-store`, `intelligence-migrations`).
- **Minor-drift components**: 4 (`alert`, `api-gateway`, `content-ingestion`, root docs).
- **Per-component drift items fixed (fan-out)**: ~110+ documented corrections
  (endpoint tables, process counts, config vars, migration history, auth model,
  topic tables, schema paths).
- **Cross-document consistency fixes (this sweep)**: 4 (README DB-split implication,
  market-data topic routing, alert produced-topics, README broken link).
- **Internal links checked**: all `.md` links in touched docs + all
  `.claude-context.md` links resolve (1 broken → fixed).

---

## 5. Remaining For User Decision

Aggregated from per-unit summaries + this sweep. None are doc-only; each needs a code/ownership decision:

1. **`CLAUDE.md` line 114 still says "6 shared Python libraries"** (should be 8).
   `CLAUDE.md` was outside the fan-out scope (operating guide, not a service/lib/root
   doc), so it was intentionally **not** edited. The owner should update the tree
   comment to 8 to match README/AGENTS/MASTER_PLAN. *(Also `docs/MASTER_PLAN.md`
   line 479 "M1.4 Shared libraries (6 libs)" is a frozen historical Phase-1
   milestone record — left as-is; confirm whether milestone counts should reflect
   delivery-time or current state.)*

2. **api-gateway dead code**: legacy `GET /v1/signals/ai` handler still in
   `routes/market.py` (registration order guards it). Owner of the market-routes
   workstream should remove it.

3. **api-gateway planned consumer unbuilt**: `entity.dirtied.v1` Kafka consumer for
   resolution-cache invalidation (PLAN-0089 F2 step 6) is still a TODO. Confirm
   whether it is still wanted.

4. **api-gateway code comments stale**: `RateLimitMiddleware` in-code comments still
   reference the old 300/min figure while the config default is 2000. Reconcile the
   comments (code-comment issue, not docs).

5. **`services/intelligence-migrations/README.md` is also stale** (claims ~0038-era
   head / "all 21 tables" / old EMBEDDING_MODEL default). Not in the docs/ fan-out
   scope; bring it in line with the corrected `docs/services/intelligence-migrations.md`
   (head 0062, ~28 tables).

6. **content-ingestion exact test counts** (~780 unit / ~36 integration) were
   approximated via test-function grep. Run `pytest --collect-only` for hard numbers
   if precision is required in the docs.
