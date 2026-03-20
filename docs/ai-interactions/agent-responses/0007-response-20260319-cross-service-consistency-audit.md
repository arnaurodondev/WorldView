# 0007 Response — Cross-service Consistency Audit

Date: 2026-03-19
Scope: Full-system documentation vs implementation consistency audit across services, libs, frontend, infra, contracts, migrations, APIs, messaging, and tests.

---

## 1. Services inventory

| Service Name | Framework | Database | Kafka Producer | Kafka Consumer | Test Coverage (yes/partial/none) |
|---|---|---|---|---|---|
| Portfolio | FastAPI | portfolio_db | portfolio.events.v1 | market.instrument.created, market.instrument.updated | yes |
| Market Ingestion | FastAPI | ingestion_db | market.dataset.fetched | none | yes |
| Market Data | FastAPI | market_data_db (TimescaleDB) | market.instrument.created, market.instrument.updated | market.dataset.fetched | yes |
| Content Ingestion | FastAPI | content_ingestion_db | documented only (not implemented in code) | none | partial |
| Content Store | FastAPI | content_store_db | documented only (not implemented in code) | documented only (not implemented in code) | partial |
| NLP Pipeline | FastAPI | nlp_db | documented only (not implemented in code) | documented only (not implemented in code) | partial |
| Knowledge Graph | FastAPI | kg_db | none | documented only (not implemented in code) | partial |
| RAG / Chat | FastAPI | rag_db in code (docs claim stateless) | none | none | partial |
| API Gateway | FastAPI | none in code settings (docs/env mention DB) | none | none | partial |
| Frontend | React 18 + Vite 5 + TypeScript | n/a | none | none | yes |

Notes:
- S4–S8 are present as service folders, but implementation is scaffold-level (app + config + health tests), while docs describe full domain behavior.
- API Gateway has implemented composition routes, but documented route/auth surface is broader and does not match current code.

---

## 2. Documentation coverage map

| Component | Documented (file refs) | Implemented (file refs) | Match Quality (full/partial/none) |
|---|---|---|---|
| Service ports and entry points | AGENTS.md:149-159, docs/index.md:18-28 | services/*/Makefile:23 | partial |
| S1 Portfolio API + behavior | docs/services/portfolio.md | services/portfolio/src/portfolio/**/* | partial |
| S2 Market Ingestion API + behavior | docs/services/market-ingestion.md | services/market-ingestion/src/market_ingestion/**/* | partial |
| S3 Market Data API + behavior | docs/services/market-data.md | services/market-data/src/market_data/**/* | partial |
| S4 Content Ingestion | docs/services/content-ingestion.md | services/content-ingestion/src/content_ingestion/app.py, services/content-ingestion/src/content_ingestion/config.py | none |
| S5 Content Store | docs/services/content-store.md | services/content-store/src/content_store/app.py, services/content-store/src/content_store/config.py | none |
| S6 NLP Pipeline | docs/services/nlp-pipeline.md | services/nlp-pipeline/src/nlp_pipeline/app.py, services/nlp-pipeline/src/nlp_pipeline/config.py | none |
| S7 Knowledge Graph | docs/services/knowledge-graph.md | services/knowledge-graph/src/knowledge_graph/app.py, services/knowledge-graph/src/knowledge_graph/config.py | none |
| S8 RAG/Chat | docs/services/rag-chat.md | services/rag-chat/src/rag_chat/app.py, services/rag-chat/src/rag_chat/config.py | partial |
| S9 API Gateway | docs/services/api-gateway.md | services/api-gateway/src/api_gateway/**/* | partial |
| Kafka topics and schemas | docs/MASTER_PLAN.md:317-329, docs/services/*.md | infra/kafka/init/create-topics.sh, infra/kafka/schemas/*.avsc, services/{portfolio,market-ingestion,market-data}/src/**/*messaging* | partial |
| DB schema docs vs migrations (S4–S8) | docs/services/content-*.md, docs/services/nlp-pipeline.md, docs/services/knowledge-graph.md, docs/services/rag-chat.md | services/*/alembic/env.py, services/*/alembic/versions/.gitkeep | none |
| Frontend to gateway contract | docs/apps/frontend.md | apps/frontend/src/lib/gateway-client.ts, services/api-gateway/src/api_gateway/routes.py | partial |
| Infra compose coverage | docs/workflows/local-dev.md, infra/compose/docker-compose.yml header comments | infra/compose/docker-compose.yml services list | partial |

---

## 3. Divergence log

- Divergence ID: D-001
- Type: stale_doc
- Description: AGENTS service entry-point table is stale (ports and module paths do not match implementation).
- Evidence:
  - doc location(s): AGENTS.md:153, AGENTS.md:154, AGENTS.md:158, AGENTS.md:159
  - code location(s): services/portfolio/Makefile:23, services/market-ingestion/Makefile:23, services/rag-chat/Makefile:23, services/api-gateway/Makefile:23
- Severity: significant
- Recommended fix:
  - exact file(s) to change: AGENTS.md
  - exact corrective action: Replace Section 8 table with current service names, ports, and module paths.
  - whether change should be code, docs, or both: docs

- Divergence ID: D-002
- Type: doc_vs_code
- Description: Portfolio doc header says port 8000 while runtime is 8001.
- Evidence:
  - doc location(s): docs/services/portfolio.md:3
  - code location(s): services/portfolio/Makefile:23, docs/services/portfolio.md:345
- Severity: minor
- Recommended fix:
  - exact file(s) to change: docs/services/portfolio.md
  - exact corrective action: Update header Port from 8000 to 8001.
  - whether change should be code, docs, or both: docs

- Divergence ID: D-003
- Type: stale_doc
- Description: Market Ingestion doc contains stale module paths and stale local-run port guidance.
- Evidence:
  - doc location(s): docs/services/market-ingestion.md:126, docs/services/market-ingestion.md:189, docs/services/market-ingestion.md:259
  - code location(s): services/market-ingestion/Makefile:23, services/market-ingestion/src/market_ingestion/app.py:1
- Severity: significant
- Recommended fix:
  - exact file(s) to change: docs/services/market-ingestion.md
  - exact corrective action: Replace src/app tree with src/market_ingestion tree; update API server command and local run port to 8002.
  - whether change should be code, docs, or both: docs

- Divergence ID: D-004
- Type: stale_doc
- Description: RAG/Chat doc has stale module path and stale local-run port guidance.
- Evidence:
  - doc location(s): docs/services/rag-chat.md:149, docs/services/rag-chat.md:208
  - code location(s): services/rag-chat/Makefile:23, services/rag-chat/src/rag_chat/config.py:19
- Severity: significant
- Recommended fix:
  - exact file(s) to change: docs/services/rag-chat.md
  - exact corrective action: Update module tree root to src/rag_chat and local run port to 8008.
  - whether change should be code, docs, or both: docs

- Divergence ID: D-005
- Type: missing_impl
- Description: Content Ingestion docs describe full API, domain, and integration behavior, but code is scaffold-only.
- Evidence:
  - doc location(s): docs/services/content-ingestion.md:26-30, docs/services/content-ingestion.md:101-111
  - code location(s): services/content-ingestion/src/content_ingestion/app.py:33, services/content-ingestion/src/content_ingestion/app.py:37, services/content-ingestion/src/content_ingestion/app.py:39, services/content-ingestion/src/content_ingestion/config.py:23
- Severity: critical
- Recommended fix:
  - exact file(s) to change: services/content-ingestion/src/content_ingestion/**/* and docs/services/content-ingestion.md
  - exact corrective action: Either implement documented API/use-cases/adapters and messaging; or reduce docs to explicit scaffold status.
  - whether change should be code, docs, or both: both

- Divergence ID: D-006
- Type: missing_impl
- Description: Content Store docs describe consumer + article query service, but code is scaffold-only.
- Evidence:
  - doc location(s): docs/services/content-store.md:26-27, docs/services/content-store.md:84-94
  - code location(s): services/content-store/src/content_store/app.py:33, services/content-store/src/content_store/app.py:37, services/content-store/src/content_store/app.py:39
- Severity: critical
- Recommended fix:
  - exact file(s) to change: services/content-store/src/content_store/**/* and docs/services/content-store.md
  - exact corrective action: Implement documented routes and Kafka consumer workflow or rewrite docs to scaffold reality.
  - whether change should be code, docs, or both: both

- Divergence ID: D-007
- Type: missing_impl
- Description: NLP Pipeline docs describe vector search, signals, entity APIs, and producer/consumer flow, but code is scaffold-only.
- Evidence:
  - doc location(s): docs/services/nlp-pipeline.md:26-32, docs/services/nlp-pipeline.md:144-154
  - code location(s): services/nlp-pipeline/src/nlp_pipeline/app.py:33, services/nlp-pipeline/src/nlp_pipeline/app.py:37, services/nlp-pipeline/src/nlp_pipeline/app.py:39
- Severity: critical
- Recommended fix:
  - exact file(s) to change: services/nlp-pipeline/src/nlp_pipeline/**/* and docs/services/nlp-pipeline.md
  - exact corrective action: Implement documented APIs and Kafka/DB behavior, or explicitly downgrade docs to planned/not implemented.
  - whether change should be code, docs, or both: both

- Divergence ID: D-008
- Type: missing_impl
- Description: Knowledge Graph docs describe graph APIs and Kafka consumer behavior, but code is scaffold-only.
- Evidence:
  - doc location(s): docs/services/knowledge-graph.md:25-27, docs/services/knowledge-graph.md:66-76
  - code location(s): services/knowledge-graph/src/knowledge_graph/app.py:33, services/knowledge-graph/src/knowledge_graph/app.py:37, services/knowledge-graph/src/knowledge_graph/app.py:39
- Severity: critical
- Recommended fix:
  - exact file(s) to change: services/knowledge-graph/src/knowledge_graph/**/* and docs/services/knowledge-graph.md
  - exact corrective action: Implement documented graph APIs + consumer or align docs to scaffold scope.
  - whether change should be code, docs, or both: both

- Divergence ID: D-009
- Type: missing_impl
- Description: RAG/Chat docs describe chat/provider APIs and full pipeline orchestration, but code only provides health/readiness.
- Evidence:
  - doc location(s): docs/services/rag-chat.md:26-28, docs/services/rag-chat.md:146-176
  - code location(s): services/rag-chat/src/rag_chat/app.py:33, services/rag-chat/src/rag_chat/app.py:37, services/rag-chat/src/rag_chat/app.py:39
- Severity: critical
- Recommended fix:
  - exact file(s) to change: services/rag-chat/src/rag_chat/**/* and docs/services/rag-chat.md
  - exact corrective action: Implement documented chat APIs and orchestration or mark as planned scaffold.
  - whether change should be code, docs, or both: both

- Divergence ID: D-010
- Type: schema_mismatch
- Description: S4–S8 docs include concrete DB schemas, but Alembic is placeholder-only (`target_metadata = None`) with no version scripts.
- Evidence:
  - doc location(s): docs/services/content-ingestion.md:48, docs/services/content-store.md:47, docs/services/nlp-pipeline.md:53, docs/services/knowledge-graph.md:45, docs/services/rag-chat.md:3
  - code location(s): services/content-ingestion/alembic/env.py:24, services/content-store/alembic/env.py:24, services/nlp-pipeline/alembic/env.py:24, services/knowledge-graph/alembic/env.py:24, services/rag-chat/alembic/env.py:24
- Severity: critical
- Recommended fix:
  - exact file(s) to change: services/{content-ingestion,content-store,nlp-pipeline,knowledge-graph,rag-chat}/alembic/**/* and respective docs
  - exact corrective action: Add real ORM metadata + migrations for documented schemas; or mark schema sections as planned and remove SQL DDL blocks.
  - whether change should be code, docs, or both: both

- Divergence ID: D-011
- Type: contract_mismatch
- Description: API Gateway docs specify `/api/v1/*` pass-through/composition and API-key model; implementation exposes only `/v1/*` composition routes and JWT middleware.
- Evidence:
  - doc location(s): docs/services/api-gateway.md:24, docs/services/api-gateway.md:32, docs/services/api-gateway.md:63, docs/services/api-gateway.md:72, docs/services/api-gateway.md:135
  - code location(s): services/api-gateway/src/api_gateway/routes.py:20, services/api-gateway/src/api_gateway/routes.py:31, services/api-gateway/src/api_gateway/routes.py:43, services/api-gateway/src/api_gateway/routes.py:58, services/api-gateway/src/api_gateway/routes.py:67, services/api-gateway/src/api_gateway/middleware.py:50, services/api-gateway/src/api_gateway/middleware.py:85
- Severity: critical
- Recommended fix:
  - exact file(s) to change: services/api-gateway/src/api_gateway/**/* and docs/services/api-gateway.md
  - exact corrective action: Decide canonical gateway contract (paths + auth + rate-limit keys). Implement it and align docs; or update docs to current minimal implementation.
  - whether change should be code, docs, or both: both

- Divergence ID: D-012
- Type: contract_mismatch
- Description: API Gateway downstream call paths for Market Data are incompatible with actual Market Data routes.
- Evidence:
  - doc location(s): docs/services/api-gateway.md:24-39
  - code location(s): services/api-gateway/src/api_gateway/clients.py:77, services/api-gateway/src/api_gateway/clients.py:78, services/market-data/src/market_data/api/routers/fundamentals.py:57, services/market-data/src/market_data/api/routers/ohlcv.py:111, services/market-data/src/market_data/app.py:217
- Severity: critical
- Recommended fix:
  - exact file(s) to change: services/api-gateway/src/api_gateway/clients.py and/or services/market-data/src/market_data/api/**/*
  - exact corrective action: Align caller paths with callee paths (including prefix and resource shape), add contract tests between S9 and S3.
  - whether change should be code, docs, or both: both

- Divergence ID: D-013
- Type: config_gap
- Description: API Gateway env example declares DB/Kafka/SchemaRegistry/Storage variables that are not consumed; downstream URL vars consumed by code are not declared.
- Evidence:
  - doc location(s): services/api-gateway/configs/dev.local.env.example:5-10
  - code location(s): services/api-gateway/src/api_gateway/config.py:23, services/api-gateway/src/api_gateway/config.py:30, services/api-gateway/src/api_gateway/config.py:32
- Severity: significant
- Recommended fix:
  - exact file(s) to change: services/api-gateway/configs/dev.local.env.example, services/api-gateway/src/api_gateway/config.py, docs/services/api-gateway.md
  - exact corrective action: Remove unused vars from env example and add all actually consumed vars (portfolio_url, market_data_url, etc.) with prefixed env names.
  - whether change should be code, docs, or both: both

- Divergence ID: D-014
- Type: config_gap
- Description: Master Plan DB name for S2 (`market_ingestion_db`) does not match implementation (`ingestion_db`).
- Evidence:
  - doc location(s): docs/MASTER_PLAN.md:128, docs/MASTER_PLAN.md:252
  - code location(s): services/market-ingestion/src/market_ingestion/config.py:19, infra/postgres/init/init-databases.sh:11
- Severity: significant
- Recommended fix:
  - exact file(s) to change: docs/MASTER_PLAN.md and/or services/market-ingestion/src/market_ingestion/config.py and infra/postgres/init/init-databases.sh
  - exact corrective action: Pick one canonical DB name and align docs + config + init scripts.
  - whether change should be code, docs, or both: both

- Divergence ID: D-015
- Type: schema_mismatch
- Description: Master Plan and service doc state RAG/Chat is stateless, but service config defines `rag_db`.
- Evidence:
  - doc location(s): docs/MASTER_PLAN.md:134, docs/services/rag-chat.md:3
  - code location(s): services/rag-chat/src/rag_chat/config.py:23, infra/postgres/init/init-databases.sh:18
- Severity: significant
- Recommended fix:
  - exact file(s) to change: docs/MASTER_PLAN.md, docs/services/rag-chat.md and/or services/rag-chat/src/rag_chat/config.py
  - exact corrective action: Architectural decision required: true stateless orchestrator vs stateful service. Align code/docs accordingly.
  - whether change should be code, docs, or both: both

- Divergence ID: D-016
- Type: stale_doc
- Description: infra/compose compose header suggests broad all-profile scope, but implementation file only contains infra + S1-S3 services.
- Evidence:
  - doc location(s): infra/compose/docker-compose.yml:6
  - code location(s): infra/compose/docker-compose.yml:304, infra/compose/docker-compose.yml:327
- Severity: minor
- Recommended fix:
  - exact file(s) to change: infra/compose/docker-compose.yml, docs/workflows/local-dev.md
  - exact corrective action: Clarify this compose file scope (partial stack) or add missing services if intended to be full all-services stack.
  - whether change should be code, docs, or both: both

- Divergence ID: D-017
- Type: test_gap
- Description: S4–S8 docs claim domain/integration test depth, but test suites only validate health/readiness endpoints.
- Evidence:
  - doc location(s): docs/services/content-ingestion.md:126-127, docs/services/content-store.md:109-110, docs/services/nlp-pipeline.md:162-163, docs/services/knowledge-graph.md:91-92, docs/services/rag-chat.md:195-197
  - code location(s): services/content-ingestion/tests/test_health.py:11, services/content-store/tests/test_health.py:11, services/nlp-pipeline/tests/test_health.py:11, services/knowledge-graph/tests/test_health.py:11, services/rag-chat/tests/test_health.py:11
- Severity: significant
- Recommended fix:
  - exact file(s) to change: services/{content-ingestion,content-store,nlp-pipeline,knowledge-graph,rag-chat}/tests/**/* and corresponding service docs
  - exact corrective action: Add tests for documented capabilities or reclassify docs to scaffold/testing-not-yet-implemented status.
  - whether change should be code, docs, or both: both

- Divergence ID: D-018
- Type: doc_vs_code
- Description: ID standard is inconsistent across governance docs and shared-lib docs (UUIDv7 mandate vs UUIDv4/ULID guidance).
- Evidence:
  - doc location(s): RULES.md:75-78, AGENTS.md:109, docs/libs/common.md:51, docs/libs/common.md:55
  - code location(s): libs/common/src/common/ids.py:1 (uses uuid/ulid helper module per docs; verify exact implementation before migration)
- Severity: minor
- Recommended fix:
  - exact file(s) to change: RULES.md, AGENTS.md, docs/libs/common.md (and potentially libs/common/src/common/ids.py)
  - exact corrective action: Define and enforce one canonical ID policy by scope (entity IDs vs event IDs).
  - whether change should be code, docs, or both: both (policy first)

---

## 4. Required updates by service

### Portfolio (S1)
- [ ] Update docs/services/portfolio.md header port to 8001.
- [ ] Revalidate endpoint table against current routers.

### Market Ingestion (S2)
- [ ] Fix docs/services/market-ingestion.md module path tree and API server command.
- [ ] Fix docs/services/market-ingestion.md local run port (8002).
- [ ] Resolve canonical DB name mismatch (`ingestion_db` vs `market_ingestion_db`) across docs/config/init scripts.

### Market Data (S3)
- [ ] Add/refresh contract tests with API Gateway to prevent route-path drift.
- [ ] Keep docs/services/market-data.md naming consistent (singular vs plural fundamentals table names where ambiguous).

### Content Ingestion (S4)
- [ ] Either implement documented API/domain/messaging or rewrite docs to scaffold reality.
- [ ] Add real Alembic metadata/migrations if DB schema claims remain.
- [ ] Add tests beyond health checks.

### Content Store (S5)
- [ ] Either implement documented consumer/query API or rewrite docs to scaffold reality.
- [ ] Add real Alembic metadata/migrations if DB schema claims remain.
- [ ] Add tests beyond health checks.

### NLP Pipeline (S6)
- [ ] Either implement documented vector/entity/signals API + Kafka wiring or rewrite docs to scaffold reality.
- [ ] Add real Alembic metadata/migrations for nlp_db schema claims.
- [ ] Add tests beyond health checks.

### Knowledge Graph (S7)
- [ ] Either implement documented graph APIs + Kafka consumer or rewrite docs to scaffold reality.
- [ ] Add real Alembic metadata/migrations for AGE schema claims.
- [ ] Add tests beyond health checks.

### RAG / Chat (S8)
- [ ] Resolve stateless-vs-stateful architecture decision and align config/docs.
- [ ] Either implement documented chat endpoints/pipeline or rewrite docs to scaffold reality.
- [ ] Add tests beyond health checks.

### API Gateway (S9)
- [ ] Align documented API surface/auth model with implemented one.
- [ ] Fix downstream Market Data paths in clients.
- [ ] Align env examples with consumed settings (include downstream URLs, remove unused vars).

### Frontend
- [ ] Validate end-to-end route contract against final S9 path policy (`/api/v1/*` vs `/v1/*`) and keep Vite rewrite/docs aligned.

### Shared libs (common/contracts/messaging/storage/observability)
- [ ] Normalize ID policy across RULES/AGENTS/common docs and code.
- [ ] Keep Avro + contracts evolution policy explicit and enforced by tests.

---

## 5. Required documentation updates

- AGENTS.md
  - Inaccurate/incomplete: Service entry-point table (ports + module paths) is stale and incomplete.
  - Source-of-truth replacement: generate from current Makefiles and app module paths.

- docs/services/portfolio.md
  - Inaccurate/incomplete: header port.
  - Source-of-truth replacement: services/portfolio/Makefile run target.

- docs/services/market-ingestion.md
  - Inaccurate/incomplete: internal tree path, API command, local run port.
  - Source-of-truth replacement: services/market-ingestion/src/market_ingestion/* and services/market-ingestion/Makefile.

- docs/services/rag-chat.md
  - Inaccurate/incomplete: internal path root and local run port; functional scope overstates implementation.
  - Source-of-truth replacement: services/rag-chat/src/rag_chat/* and current route code.

- docs/services/content-ingestion.md
  - Inaccurate/incomplete: implementation maturity and API/messaging/DB claims are not currently implemented.
  - Source-of-truth replacement: current scaffold code until features are implemented.

- docs/services/content-store.md
  - Inaccurate/incomplete: same issue as S4.
  - Source-of-truth replacement: current scaffold code until features are implemented.

- docs/services/nlp-pipeline.md
  - Inaccurate/incomplete: same issue as S4/S5.
  - Source-of-truth replacement: current scaffold code until features are implemented.

- docs/services/knowledge-graph.md
  - Inaccurate/incomplete: same issue as S4/S5/S6.
  - Source-of-truth replacement: current scaffold code until features are implemented.

- docs/services/api-gateway.md
  - Inaccurate/incomplete: route prefixes, pass-through matrix, auth mode, middleware structure, source-tree path.
  - Source-of-truth replacement: services/api-gateway/src/api_gateway/{app.py,routes.py,middleware.py,clients.py,config.py}.

- docs/MASTER_PLAN.md
  - Inaccurate/incomplete: S2 DB naming, S8 stateless claim (pending architecture decision).
  - Source-of-truth replacement: service configs + approved ADR decision.

- docs/workflows/local-dev.md (conditional)
  - Inaccurate/incomplete: if infra/compose remains partial stack, workflow docs should clarify compose file scope.
  - Source-of-truth replacement: actual compose profiles and service definitions.

- docs/libs/common.md, RULES.md, AGENTS.md
  - Inaccurate/incomplete: inconsistent ID policy language.
  - Source-of-truth replacement: single agreed policy and matching helper implementations.

---

## 6. Suggested implementation order

1. Architecture decisions first (blocking)
- Blocking dependencies: none
- Tasks:
  - Decide S8 stateless vs stateful persistence model.
  - Decide canonical ID standard (UUIDv7 everywhere vs scoped UUID/ULID policy).
- Rollout notes: create ADRs before code/docs updates to avoid rework.

2. Contract-safety fixes (highest risk)
- Blocking dependencies: step 1 decisions for S8 only
- Tasks:
  - Fix S9↔S3 REST path mismatch and add contract tests.
  - Align S9 auth/path policy and frontend/gateway path semantics.
- Safe parallel workstreams:
  - Stream A: route contract fixes + tests
  - Stream B: docs updates for S9 and frontend
- Rollout notes: keep backward-compatible alias routes temporarily if frontend is live.

3. Baseline documentation correction wave
- Blocking dependencies: none
- Tasks:
  - AGENTS entry-point table
  - S1/S2/S8 service doc stale fields (ports, paths, commands)
  - MASTER_PLAN S2 DB name correction (or plan a rename migration)
- Safe parallel workstreams:
  - Stream C: governance docs
  - Stream D: per-service docs
- Rollout notes: docs-only PR can ship independently.

4. S4–S8 truth-alignment wave (major)
- Blocking dependencies: product/architecture decision on whether to implement now or defer
- Tasks (choose one strategy per service):
  - Implement documented APIs/messaging/migrations/tests, or
  - Mark docs as planned/scaffold and remove concrete unimplemented claims.
- Safe parallel workstreams:
  - Stream E: S4+S5
  - Stream F: S6+S7
  - Stream G: S8
- Rollout notes: avoid mixed states where docs imply production readiness before code exists.

5. Infra/config hygiene wave
- Blocking dependencies: step 3
- Tasks:
  - Align API Gateway env examples with settings consumption.
  - Clarify infra/compose scope or expand compose coverage.
- Safe parallel workstreams:
  - Stream H: env/config docs
  - Stream I: compose profile refinements
- Rollout notes: validate with smoke startup matrix after compose/env changes.

6. Testing debt closure
- Blocking dependencies: steps 2 and 4
- Tasks:
  - Add unit/integration/contract tests for newly implemented S4–S8 behaviors.
  - Keep health-only tests for scaffold services only if docs explicitly mark them scaffold.
- Rollout notes: enforce test gates before declaring “production-ready” in docs.

---

## 7. Open questions and assumptions

- Open question: Is S8 intended to remain stateless for thesis scope, or is `rag_db` a planned near-term persistence layer?
- Open question: Should S2 canonical DB name be migrated to `market_ingestion_db`, or should docs standardize on `ingestion_db`?
- Open question: Should S9 public contract be `/api/v1/*` externally with internal `/v1/*` routing, or should internal code be moved to `/api/v1/*` directly?
- Open question: Are S4–S8 expected to be implemented in current milestone, or intentionally documented ahead of implementation?
- Open question: Is UUIDv7 hard-requirement still active, or has project policy shifted to UUIDv4 for DB PK + ULID for event IDs?

Assumptions used in this audit:
- Current source code is treated as implementation truth for runtime behavior.
- Documentation is expected to describe currently implemented behavior unless explicitly marked as roadmap/planned.
- Absence of routers/messaging/migrations in S4–S8 is interpreted as missing implementation, not hidden private modules.

---

Audit completion status: complete for the requested scope, with evidence-backed divergences and dependency-ordered remediation plan.
