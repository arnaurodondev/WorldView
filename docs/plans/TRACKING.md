# Plan Tracking Index

> Active implementation plans across the worldview project.
> Updated by `/implement` and `/plan` skills. Checked by `/qa` and `/review`.

## Active Plans

| Plan ID | Title | PRD | Status | Waves Done/Total | QA | Updated |
|---------|-------|-----|--------|-----------------|-----|---------|
| PLAN-0001-D | S9 API Gateway: External Ingestion + Intelligence Query Proxy | PRD-0001 | draft | 0/2 | — | 2026-03-25 |
| PLAN-0010 | Architecture Hardening — DLQ Use Cases (R25), Security, Platform QA Script | QA-S4S5S6S7S10-001 | complete | 6/6 | 2026-03-31 | 2026-03-31 |
| PLAN-0014 | Claude Code Source Adaptations — Tier 2 Enhancements (hooks, subagent isolation, memory scopes, S8 RAG pipeline) | investigation-2026-04-01 | pending | 0/6 | — | 2026-04-01 |
| PLAN-0015 | S8 RAG/Chat: Hybrid Intelligence Pipeline | PRD-0015 | completed | 22/22 | 2026-04-09 | 2026-04-09 |
| PLAN-0016 | Chat Enhancements: GENERAL Intent + Context Window + Portfolio Risk Email Digest | PRD-0016 | completed | 11/11 | 2026-04-09 | 2026-04-09 |
| PLAN-0018 | Geopolitical Intelligence + EODHD Deep Enrichment + Apache AGE Cypher Shadow Sync | PRD-0018 | completed | 10/10 | 2026-04-09 | 2026-04-09 |
| PLAN-0019 | Polymarket Prediction Markets Integration + EDGAR Market-Hours Polling | PRD-0019 | completed | 6/6 | 2026-04-09 | 2026-04-09 |
| PLAN-0020 | Market-Impact Signal Scoring (Option A — S6 Block 5 routing extension) | PRD-0020 | completed | 8/8 | 2026-04-10 | 2026-04-10 |
| PLAN-0021 | Score-Gated Flash Alerts (AlertSeverity tiers — S10 + frontend) | PRD-0021 | completed | 6/6 | 2026-04-10 | 2026-04-10 |
| PLAN-0022 | SnapTrade Brokerage Portfolio Sync (Read-Only, S1 + S9 + frontend) | PRD-0022 | in-progress | 8/9 | — | 2026-04-12 |
| PLAN-0023 | Knowledge Graph Analytics & NLP Cache Layer (Community Detection, Hub Scoring, Graph Evolution, NER Cache, SSRF Hardening) | PRD-0023 | draft | 0/8 | — | 2026-04-08 |
| PLAN-0024 | Production Deployment Infrastructure — Hetzner k3s, Terraform, Helm, ArgoCD, Traefik TLS, Email (Brevo), Vercel, SOPS+Age, GitHub Actions | PRD-0024 | in-progress | 3/6 | — | 2026-04-11 |
| PLAN-0025 | Authentication & Security Foundation — OIDC/Zitadel, RS256 Internal JWT, S9 Hardening | PRD-0025 | in-progress | 6/6 (Wave E pending) | 2026-04-18 | 2026-04-18 |
| PLAN-0026 | News Intelligence APIs — Ranked News Feed, Multi-Window Impact & LLM Relevance Scoring | PRD-0026 | draft | 0/7 | — | 2026-04-11 |
| PLAN-0027 | Frontend MVP UI — Professional Design v2.0: Landing (ComparisonTable/TrustBar/FAQ), Dashboard (HeatMap/TopMovers/MacroCalendar), Workspace (11 panels), Company Detail (18 fundamentals sections + full Intelligence tab), Portfolio (Strategy analytics + AddTransaction), Chat (thread search) + S8 Briefing + S9 bulk routes (20+ new proxy routes) | PRD-0027 | in-progress | 5/6 (P5 Landing ✅; P6 Markets/Screener ✅, Intelligence⬜ Portfolio✅; P7 Design-System ✅; P8 Workspace ✅; P9 Settings ✅; P10 Onboarding ✅; P4 Instrument Detail: State A ✅ State E ✅ State F ⚠️ State B ⬜ State C ⬜ State D ⬜; Canvas design plan 0027-design-canvas-plan.md 0/6 waves) | 2026-04-14 | 2026-04-14 |
| PLAN-0027-V2 | Frontend MVP UI — Complete Implementation v2 (Canvas C-1..C-6 + Backend Security S-1 + Frontend Code F-1..F-12 + Tests T-1). Supersedes PLAN-0027-DESIGN and PLAN-0027-B. 18 waves total, maximally parallelised. S-1 ✅; Canvas ALL DONE: C-1✅ C-2✅ C-3✅ C-4✅ C-5✅ C-6✅ Fix-A✅ Fix-B✅ Fix-C+D✅ Intelligence page (05-Intelligence tUPQd) FULLY DESIGNED: State A (SL9kb — Morning Brief + 14 articles + TRENDING ENTITIES), State B (mFKf3 — Signal Board entity matrix), State C (pKH88 — Impact Board PRD-0026 multi-window) — 2026-04-15 | PRD-0027 | **superseded by PRD-0028** | 2/18 | — | 2026-04-17 |
| PLAN-0028 | Worldview Web — Standalone Next.js frontend at `apps/worldview-web/` + 3 S9 proxy route waves (S9-1 market+entity, S9-2 portfolio+watchlist+auth+ws-token+S10-middleware, S9-3 composed OQ-resolved endpoints). Frontend: Bootstrap, Auth, Shell, Dashboard (9 widgets), Instrument Detail (4 tabs + sigma.js), Screener, Portfolio, Workspace (8 panels), Alerts/News, Chat (fetch+POST SSE), Settings, Landing. 17 waves total (S9-1, S9-2, S9-3, F-1..F-13, T-1). All 5 BLOCKING OQs resolved. ALL WAVES COMPLETE ✅ | PRD-0028 | **completed** | 17/17 | 2026-04-18 | 2026-04-18 |
| PLAN-0029 | Missing Frontend Endpoints — S1 watchlist rename (PATCH), S8 briefing GET endpoints (morning + instrument), S9 signals/ai proxy fix (stub → real S6 proxy) | PRD-0028 §6.2 | completed | 2/2 | 2026-04-19 | 2026-04-19 |
| PLAN-0030 | Security Hardening — QA-2026-04-19 Remediation: dependency pinning (PyJWT/cryptography bounds, pnpm-lock), CI/CD SHA-pin + yq checksum, frontend security headers, gateway hardening (fail-open log, cookie_secure, dev JWT require, CORS guard), backend JWT issuer=, Docker non-root, JTI replay protection | QA-2026-04-19 | completed | 6/6 | 2026-04-19 | 2026-04-19 |
| PLAN-UI-VISUAL-OVERHAUL | Bloomberg-Grade Visual Overhaul — Amber/gold palette, data density, component polish, landing page, dashboard 4-col, page-specific polish + critic fixups | PRD-0027 | completed | 6/6 + fixups | 2026-04-19 | 2026-04-19 |
| PLAN-0031 | Pipeline Reliability & Intelligence Hardening — Kafka retention, NER/extraction model tracking, D-004 dual-DB commit fix, entity.dirtied.v1 ordering, Gemini Lua atomicity, RAG circuit breaker, tenant isolation tests | Audit 2026-04-20 | in-progress | 6/8 | — | 2026-04-21 |
| PLAN-0032 | Forensic QA Remediation — Next.js/Vitest CVE upgrade, JWKS startup race (BP-164), CSP header, S9 callback sanitization, CORS port fix, transaction header forwarding, S1 watchlist PATCH, S7 500 errors, doc fixes | Forensic QA 2026-04-21 | draft | 0/7 | — | 2026-04-21 |
<!-- New plans are appended here by the /plan skill -->

## QA Sessions

| Date | Report | Scope | Result |
|------|--------|-------|--------|
| 2026-04-13 | [2026-04-13-qa-e2e-live-stack-report.md](../audits/2026-04-13-qa-e2e-live-stack-report.md) | Pre-demo live-stack QA — 47 containers, 10 DBs, all migrations, 4,210 pass / 4 fail (BP-134 JWT gaps) / 56 skip; direct API endpoint testing via RS256 JWT | GO |
| 2026-04-13 | [2026-04-13-qa-plan-0027-design-review.md](../audits/2026-04-13-qa-plan-0027-design-review.md) | PLAN-0027 canvas design QA — 12 pages reviewed and enhanced in worldview-mvp.pen; Bloomberg-quality density achieved across all pages; 2 new pages built (Alerts, Chat/Brief); shadcn/ui component map added to Design System | GO |
| 2026-04-18 | [2026-04-18-qa-plan-0028-s9-report.md](../audits/2026-04-18-qa-plan-0028-s9-report.md) | PLAN-0028 S9-1..S9-3 QA — 5-agent review of ~40 new proxy routes + S10 WS middleware; 127 api-gateway + 338 alert tests PASS; 1 mypy fix (BaseException); 0 BLOCKING, 2 CRITICAL (pre-existing JWT bypass + test gaps), 8 MAJOR | PASS_WITH_WARNINGS |
| 2026-04-18 | [2026-04-18-qa-plan-0028-frontend-report.md](../audits/2026-04-18-qa-plan-0028-frontend-report.md) | PLAN-0028 worldview-web frontend QA — 5-agent review of all 17 waves; 206 Vitest + 11 Playwright PASS; 5 auto-fixes (DS-001/002/007/009 AlertStream bugs, SEC-003 OIDC callback, QA-005 skipped test); testing framework unified with RUNBOOK; 0 BLOCKING, 0 CRITICAL remaining | PASS_WITH_WARNINGS |
| 2026-04-18 | [2026-04-18-qa-branch-feat-content-ingestion-wave-a1-report.md](../audits/2026-04-18-qa-branch-feat-content-ingestion-wave-a1-report.md) | Full-branch QA — 1,659 files, all 11 services, all 6 libs, both frontends; 5-agent review; 3,937 backend unit + 236 worldview-web + 36 legacy frontend tests PASS; 2 auto-fixes (R19 violation, CSRF log); 0 BLOCKING, 6 CRITICAL (auth migration incomplete + rate-limit fail-open + execute_task dual-repo + exception chain + OHLCVChart error boundary), 16 MAJOR | PASS_WITH_WARNINGS |
| 2026-04-19 | [2026-04-19-qa-security-patterns-report.md](../audits/2026-04-19-qa-security-patterns-report.md) | Security patterns QA — package management (npm vs pnpm), dependency pinning, supply chain safety, implementation security; 52 findings across 5 agents; 9 auto-fixes applied (open redirect, safeExternalUrl, .npmrc, pnpm CI pin, Grafana anon-admin, Docker image tags); 0 BLOCKING, 6 CRITICAL open | PASS_WITH_WARNINGS |
| 2026-04-19 | [2026-04-19-qa-full-platform-certification-report.md](../audits/2026-04-19-qa-full-platform-certification-report.md) | Full-platform certification QA — runtime/API/UI/contracts/cross-service hardening; readiness route fixes, gateway smoke modernization, Playwright stabilization, contract expectation alignment, dependency/env unblocks; endpoint smoke 12/12, readiness 32 pass, Playwright 122 pass | READY |

## Execution Order (Dependency Graph)

```
PLAN-0001-A Wave 1 (Avro schemas, repo fixes) ──→ PLAN-0001-B (S4+S5)
          │                                              │
          ├─→ PLAN-0001-A Wave 2 (intelligence-migrations) ──→ PLAN-0001-C Sub-Plan C (S6)
          │                                                           │
          └─→ PLAN-0001-A Wave 3 (S1 internal endpoints)            │
                    │                                                │
                    └──→ PLAN-0001-C Sub-Plan E (S10) ←────────────── │
                                                                     │
PLAN-0001-B + PLAN-0001-C C+D ──→ PLAN-0001-D (S9 Gateway)
```

**Critical path**: 0001-A W1 → 0001-B A-1..A-4 → 0001-B B-1..B-4 → 0001-C C-1..C-4 → 0001-C D-1..D-4 → 0001-C E-1..E-3
**Parallelizable**: 0001-A W2 ∥ W3 (after W1); 0001-D W1 (after 0001-B); S10 (after S1 internal + S7)

## Completed Plans

| Plan ID | Title | PRD | Completed | Waves | QA |
|---------|-------|-----|-----------|-------|----|
| PLAN-0001-C | Ingestion Pipeline v1: S6 NLP Pipeline + S7 Knowledge Graph + S10 Alert Service | PRD-0001 | 2026-03-29 | 11 | 2026-03-30 |
| PLAN-0001-A | Infrastructure Prerequisites: Repo Fixes + intelligence-migrations + S1 Internal | PRD-0001 | 2026-03-26 | 3 | — |
| PLAN-0002 | Enum Standardization: Shared OutboxStatus + ContentSourceType | N/A | 2026-03-26 | 2 | — |
| PLAN-0001-B | Ingestion Pipeline v1: S4 Content Ingestion + S5 Content Store | PRD-0001 | 2026-03-27 | 8 | 2026-04-09 |
| PLAN-0001-B-R4 | S4+S5 QA Review Fixes: DLQ Fidelity, SSRF Hardening, DDL Alignment, Process Compounding | QA Review | 2026-03-27 | 4 | — |
| PLAN-0001-B-R1 | S4 QA & Review Fixes: Runtime Bugs, Lock, Watermarks, Auth, Security, Tests, Infra | Review/QA | 2026-03-26 | 7 | — |
| PLAN-0001-B-R2 | S4+S5 QA Fixes: DDL, DLQ, SSRF, LSH, Contract Tests, Compounding | QA Review | 2026-03-27 | 4 | — |
| PLAN-0001-B-R3 | S4+S5 Architecture: ABCs, BaseKafkaConsumer, MinIO GC, DomainError, Standards | QA Review | 2026-03-27 | 5 | — |
| PLAN-0003 | Observability Standardization: Service Fixes + Monitoring Stack | N/A | 2026-03-27 | 4 | 2026-03-27 |
| QA-CROSS-001 | Cross-Service QA: market-ingestion, market-data, portfolio (16 findings fixed) | N/A | 2026-03-27 | — | 2026-03-27 |
| QA-CROSS-002 | Deep Cross-Service QA: portfolio, market-ingestion, market-data (87 findings, 9 blocking/critical) | N/A | 2026-03-27 | — | 2026-03-27 |
| PLAN-0001-E | S1+S2+S3 Deep QA Fixes: Idempotency, Atomicity, Security Hardening, Architecture Consistency | QA Review (QA-CROSS-002) | 2026-03-28 | 14 | 2026-03-28 |
| PLAN-0004 | Observability Dashboards, Alerts & Recording Rules — Auto-Provisioned | N/A | 2026-03-27 | 5 | — |
| QA-E2E-001 | Comprehensive E2E Test Suite: S4+S5+S7 ASGI tests + S2→S3 cross-service + S1 security isolation (89 new tests) | N/A | 2026-03-28 | — | 2026-03-28 |
| PLAN-0005 | Provider Config Externalization — Nested Settings Pattern (S4 + S2) | N/A | 2026-03-29 | 3 | — |
| PLAN-0006 | Process Architecture & Database Standardization: S4 Decoupling + Scheduler-Worker + R/W Split | N/A | 2026-03-30 | 5 | 2026-03-30 |
| PLAN-0001-E-R1 | S1+S2+S3 Remaining Open Items: UoW commit, TOCTOU dedup, arch violations, topic mismatch, domain layer, auth | QA-CROSS-002 | 2026-03-30 | 6 | 2026-03-30 |
| PLAN-0007 | PLAN-0001-C QA Fixes: Idempotency, Valkey Hardening, Observability, Deployment Constraints | PLAN-0001-C QA | 2026-03-30 | 2 | — |
| PLAN-0008 | QA Follow-Up — Standards Enforcement, Architecture Hardening & Production Readiness | PLAN-0001-E-R1 QA | 2026-03-30 | 10 | 2026-03-30 |
| PLAN-0009 | R25 Layer Violation Remediation — S4 API Routes + ExecuteContentTaskUseCase | PLAN-0006 QA | 2026-03-30 | 4 | 2026-03-30 |
| QA-S4S5S6S7S10-001 | Full QA Pass + E2E Test Suite: S4/S5/S6/S7/S10 security fixes + ASGI e2e suites + cross-service integration + real provider tests + infra scaffold | N/A | 2026-03-30 | — | 2026-03-30 |
| PLAN-0012 | R23 Read/Write Database Session Split — Tests & Enforcement | N/A | 2026-04-01 | 4 | 2026-04-07 |
| PLAN-0011 | Process Topology Standardization & Architecture Test Enforcement | N/A | 2026-04-01 | 9 | 2026-04-01 |
| PLAN-0013 | Process Topology Completion + Alert WebSocket Cross-Process Bridge | PLAN-0011 QA follow-up | 2026-04-01 | 6 | 2026-04-01 |
| QA-S1S2S3-2026-04-07 | QA Pass S1+S2+S3: PASS_WITH_WARNINGS — 8 MAJOR (ULID/metrics/cache-hook/contract-tests), 0 BLOCKING/CRITICAL, all unit+lint+mypy PASS | N/A | 2026-04-07 | — | 2026-04-07 |
| PLAN-0017 | Entity Screener + Similarity Search + Embedding View Fix + EODHD Description LLM | PRD-0017 | 2026-04-08 | 11 | 2026-04-08 |
| QA-S6S7S8-2026-04-09 | Deep QA Pass S6/S7/S8: TOCTOU soft_delete (CRITICAL), VectorSearch query wiring, entity.canonical.created.v1 dispatcher fix, S8 integration tests (14), 506+313+212 tests green | N/A | 2026-04-09 | — | 2026-04-09 |
| QA-S4S5-2026-04-09 | Deep QA Pass S4+S5: 5-agent review, 9 missing use-case unit tests added, F-DS-014 intra-batch dedup fix, 490+289 tests green, PASS_WITH_WARNINGS | N/A | 2026-04-09 | — | 2026-04-09 |
| QA-DEPLOY-2026-04-09 | Pre-Hetzner Deployment QA: full unit suite ~4059 tests PASS across all services+libs; BP-134 live test scope mismatch (market-ingestion/market-data); observability gap (6/10 services in Prometheus); no production error tracking (Sentry/Glitchtip) | N/A | 2026-04-09 | — | 2026-04-09 |
| QA-PRE-DEMO-2026-04-13 | Pre-Demo Full QA Pass (2nd run, Docker running): infra UP (postgres/kafka/valkey/minio/ollama); 6 Kafka topics; rag-chat BP-134 fix applied (conftest _make_system_jwt + X-Internal-JWT header); market-data readyz test fixed (state override inside TestClient block); 21 RUF059 fixed + 34 format files reformatted; ruff PASS; mypy PASS all 6 key services; libs 566 pass; services total ~3,650 pass, 0 fail; integration tests pass (api-gw 8, portfolio 53, market-data 67, nlp 10); Schema Registry networking issue (kafka:9092 vs localhost:9092 in compose); Ollama 0 models loaded; service .env files missing (runtime docker profile unusable — expected dev mode); DEMO READINESS: CONDITIONAL GO. See docs/audits/2026-04-13-qa-pre-demo-report.md | N/A | 2026-04-13 | — | 2026-04-13 |

## Conventions

- **Plan IDs** match their PRD: `PLAN-0001` corresponds to `PRD-0001`
- **Status values**: `draft` → `approved` → `in-progress` → `completed` | `cancelled`
- **QA column**: Date when `/qa` was run against the plan. `—` means not yet QA'd. `/qa` skill MUST update this column when it runs.
- **Wave tracking**: See the individual plan file for wave/task-level detail
- **Session boundaries**: Each sub-plan (A, B, C...) can be executed in a separate Claude Code session
- **Conflict check**: Before starting a wave, verify no other plan modifies the same files

## How to Use

1. **Starting work**: Check this index for active plans. Read the plan file for the next ready wave.
2. **During implementation**: The `/implement` skill updates wave/task status in the plan file.
3. **After completion**: Move the plan from Active to Completed when all waves are done.
4. **Conflict resolution**: If two plans touch the same service, execute them in dependency order.
