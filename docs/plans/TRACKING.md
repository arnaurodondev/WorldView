# Plan Tracking Index

> Active implementation plans across the worldview project.
> Updated by `/implement` and `/plan` skills. Checked by `/qa` and `/review`.

## Active Plans

| Plan ID | Title | PRD | Status | Waves Done/Total | QA | Updated |
|---------|-------|-----|--------|-----------------|-----|---------|
| PLAN-0001-D | S9 API Gateway: External Ingestion + Intelligence Query Proxy | PRD-0001 | draft | 0/2 | — | 2026-03-25 |
| PLAN-0014 | Claude Code Source Adaptations — Tier 2 Enhancements (hooks, subagent isolation, memory scopes, S8 RAG pipeline) | investigation-2026-04-01 | pending | 0/6 | — | 2026-04-01 |
| PLAN-0023 | Knowledge Graph Analytics & NLP Cache Layer (Community Detection, Hub Scoring, Graph Evolution, NER Cache, SSRF Hardening) | PRD-0023 | draft | 0/8 | — | 2026-04-08 |
| PLAN-0024 | Production Deployment Infrastructure — Hetzner k3s, Terraform, Helm, ArgoCD, Traefik TLS, Email (Brevo), Vercel, SOPS+Age, GitHub Actions | PRD-0024 | in-progress | 3/6 (A-3/A-4/A-5 pending) | — | 2026-04-11 |
| PLAN-0037 | Frontend Terminal Redesign — enforce 2px radius, compact padding, no max-w-4xl, terminal-grade empty states, dense instrument/screener/portfolio/workspace layouts | PRD-0027/PRD-0028 | **SUPERSEDED by PRD-0031** | 3/5 partial waves committed | 2026-04-25 | 2026-04-25 |
| PLAN-0039 | Terminal UI v3 Ground-Up Redesign — Bloomberg/CLI terminal quality: 48px icon rail, resizable panels, 12-col screener, 22px rows, §0 Terminal CLI Quality Standard (zero shadows/gradients/rounding, gap-px seams, 10px ALL CAPS headers) | PRD-0031 | **complete** | 8/8 | INSTITUTIONAL_DEMO_READY | 2026-04-25 |
| PLAN-0043 | Dashboard UX Refinement — MorningBrief compact layout, grid borders, 1D/1W/1M period wiring (new S3+S9 endpoints), AI Signals widget, Polymarket URL fix + economics filter | user feedback 2026-04-27 | in-progress | 9/9 (all waves done) | — | 2026-04-28 |
| PLAN-0044 | Portfolio Page Enhancement — sidebar edge bug, holdings DAY CHG columns + weight bars + sort, watchlist delete/create, brokerages merged into transactions tab | user feedback 2026-04-28 | draft | 0/3 | — | 2026-04-28 |
<!-- New plans are appended here by the /plan skill -->

## QA Sessions

| Date | Report | Scope | Result |
|------|--------|-------|--------|
| 2026-04-27 | (3-agent live-stack investigation) | End-to-end pipeline investigation — Agent 1: EODHD fundamentals ingestion (task_save_lease_mismatch, yfinance kwarg, Alpaca timestamp, Polygon adapter, Polymarket new Gamma API, prediction_market ON CONFLICT, economic/macro/insider scheduler dispatch); Agent 2: Chat/RAG pipeline (bge-large 60s timeout, nomic dimension guard, DeepSeek [N6] citation fix, claim_repository CAST dates); Agent 3: Macro/news (Polymarket adapter, FetchResult.title propagation, title ON CONFLICT preserve); + sector heatmap GICS-to-DB name translation (5/11 sectors now returning data); yield_curve/market_cap scheduler dispatch branches; commits: bed7fab + 27bbc0e + f1ad800 | **READY_FOR_DEMO** |
| 2026-04-26 | [2026-04-26-qa-live-validation-wave-a2-report.md](../audits/2026-04-26-qa-live-validation-wave-a2-report.md) | Live-stack Wave A-2 — 8 fixes: alert dual-instantiation JTI (BP-230), qwen3 CPU timeout 5s→20s (BP-231), fundamentals $B/T/% normalization, empty-context professional placeholder, DeepSeek [N:X] citation stripping, empty embedding 422 guard, S1 /internal/v1/ path fix, bge-large serialized to 1 concurrent; 448 rag-chat + 348 alert unit tests PASS; BP-230/231/232 documented | **READY_FOR_DEMO** |
| 2026-04-26 | [2026-04-26-qa-llm-quality-report.md](../audits/2026-04-26-qa-llm-quality-report.md) | LLM quality & pipeline certification — 3 live-stack agents (morning brief, instrument brief, chat) + email QA; 8 BLOCKING + 6 CRITICAL fixed: JTI replay (BP-183), wrong route method, DeepInfra 404, missing embed endpoint, S3Client key/structure bugs, S7Client format mismatch, market-data empty exchange, S5 wrong port, S1/S10 auth headers, KG asyncpg BP-180, email digest non-functional, empty-context hallucination; MORNING_BRIEFING v2.1 + INSTRUMENT_BRIEFING v3.0 prompts; qwen3:0.6b pre-load infra; entity articles endpoint added | **READY_PENDING_SEED_DATA** |
| 2026-04-26 | [2026-04-26-qa-branch-feat-content-ingestion-wave-a1-report.md](../audits/2026-04-26-qa-branch-feat-content-ingestion-wave-a1-report.md) | Branch QA — E2E stabilization (LIFO route fix, SectorHeatmap null guard, stale palette #E8A317→#FFD60A, landing page heading, exhaustive CSS selector, screener/alerts empty state text, content null guards); 411/411 Vitest + 260/260 mocked E2E PASS; 8 live-stack skips (infra not running) | **PASS** |
| 2026-04-26 | [2026-04-26-qa-plan-0039-institutional-report.md](../audits/2026-04-26-qa-plan-0039-institutional-report.md) | PLAN-0039 institutional QA — 6-agent review + Institutional Trader Persona; 12 screenshots captured; 7 fixes applied (4 BLOCKING + 3 CRITICAL); 2 MAJOR deferred; 411/411 Vitest + 11/11 E2E Chromium PASS; BP-182 added | READY_WITH_POLISH_NEEDED |
| 2026-04-25 | [2026-04-25-plan-0039-wave8-acceptance-report.md](../audits/2026-04-25-plan-0039-wave8-acceptance-report.md) | PLAN-0039 Wave 8 final acceptance — 411/411 Vitest pass, 0 TypeScript errors, 0 ESLint errors; §0.10 Bloomberg benchmarks all 0; PRD §16 all criteria verified; Playwright E2E spec committed | INSTITUTIONAL_DEMO_READY |
| 2026-04-25 | [2026-04-25-qa-ui-bloomberg-grade-report.md](../audits/2026-04-25-qa-ui-bloomberg-grade-report.md) | Bloomberg-grade UI audit — PLAN-0039 all waves; 7 fixes applied (avatar rounded-full, animate-pulse, p-8×3, inline hex colors×4, BriefWidget hex×7, text-amber-400×2); TypeCheck PASS, 367 tests PASS; 2 backend data gaps remain (sector alloc, realized P&L) | READY_WITH_POLISH_NEEDED |
| 2026-04-25 | [2026-04-25-qa-terminal-redesign-report.md](../audits/2026-04-25-qa-terminal-redesign-report.md) | Terminal redesign gap audit (Waves A/B/C vs qa-frontend-design.md plan) — TypeCheck FAIL (5 errors), no screenshots, workspace placeholders still present, screener 7 cols not 8, SessionStatsStrip missing, Wave C/D/E not committed | NOT_READY |
| 2026-04-13 | [2026-04-13-qa-e2e-live-stack-report.md](../audits/2026-04-13-qa-e2e-live-stack-report.md) | Pre-demo live-stack QA — 47 containers, 10 DBs, all migrations, 4,210 pass / 4 fail (BP-134 JWT gaps) / 56 skip; direct API endpoint testing via RS256 JWT | GO |
| 2026-04-13 | [2026-04-13-qa-plan-0027-design-review.md](../audits/2026-04-13-qa-plan-0027-design-review.md) | PLAN-0027 canvas design QA — 12 pages reviewed and enhanced in worldview-mvp.pen; Bloomberg-quality density achieved across all pages; 2 new pages built (Alerts, Chat/Brief); shadcn/ui component map added to Design System | GO |
| 2026-04-18 | [2026-04-18-qa-plan-0028-s9-report.md](../audits/2026-04-18-qa-plan-0028-s9-report.md) | PLAN-0028 S9-1..S9-3 QA — 5-agent review of ~40 new proxy routes + S10 WS middleware; 127 api-gateway + 338 alert tests PASS; 1 mypy fix (BaseException); 0 BLOCKING, 2 CRITICAL (pre-existing JWT bypass + test gaps), 8 MAJOR | PASS_WITH_WARNINGS |
| 2026-04-18 | [2026-04-18-qa-plan-0028-frontend-report.md](../audits/2026-04-18-qa-plan-0028-frontend-report.md) | PLAN-0028 worldview-web frontend QA — 5-agent review of all 17 waves; 206 Vitest + 11 Playwright PASS; 5 auto-fixes (DS-001/002/007/009 AlertStream bugs, SEC-003 OIDC callback, QA-005 skipped test); testing framework unified with RUNBOOK; 0 BLOCKING, 0 CRITICAL remaining | PASS_WITH_WARNINGS |
| 2026-04-18 | [2026-04-18-qa-branch-feat-content-ingestion-wave-a1-report.md](../audits/2026-04-18-qa-branch-feat-content-ingestion-wave-a1-report.md) | Full-branch QA — 1,659 files, all 11 services, all 6 libs, both frontends; 5-agent review; 3,937 backend unit + 236 worldview-web + 36 legacy frontend tests PASS; 2 auto-fixes (R19 violation, CSRF log); 0 BLOCKING, 6 CRITICAL (auth migration incomplete + rate-limit fail-open + execute_task dual-repo + exception chain + OHLCVChart error boundary), 16 MAJOR | PASS_WITH_WARNINGS |
| 2026-04-19 | [2026-04-19-qa-security-patterns-report.md](../audits/2026-04-19-qa-security-patterns-report.md) | Security patterns QA — package management (npm vs pnpm), dependency pinning, supply chain safety, implementation security; 52 findings across 5 agents; 9 auto-fixes applied (open redirect, safeExternalUrl, .npmrc, pnpm CI pin, Grafana anon-admin, Docker image tags); 0 BLOCKING, 6 CRITICAL open | PASS_WITH_WARNINGS |
| 2026-04-19 | [2026-04-19-qa-full-platform-certification-report.md](../audits/2026-04-19-qa-full-platform-certification-report.md) | Full-platform certification QA — runtime/API/UI/contracts/cross-service hardening; readiness route fixes, gateway smoke modernization, Playwright stabilization, contract expectation alignment, dependency/env unblocks; endpoint smoke 12/12, readiness 32 pass, Playwright 122 pass | READY |
| 2026-04-23 | [2026-04-23-qa-full-platform-overhaul-report.md](../audits/2026-04-23-qa-full-platform-overhaul-report.md) | Full-platform overhaul QA — institutional UI redesign (Bloomberg palette, 2px radius, gap-px grid), 15 functional/infra fixes applied (workspace multi-instance+persistence, search navigation, MinIO market-bronze bucket, BP-182 null-volume OHLCV, content sources seeded); 4,998 unit tests PASS; market data pipeline restored (655 OHLCV bars flowing) | PASS_WITH_WARNINGS |
| 2026-04-23 | (implement-ui polish pass) | Institutional UI polish — OHLCVChart Terminal Dark theme sync, landing page radius cleanup (rounded-[2px]), sidebar keyboard shortcut strip (g+d/g+w/g+c/⌘K), workspace density (p-4→p-1 + gap-3→gap-px), DESIGN_SYSTEM.md Terminal Dark palette update; 285 tests PASS | PASS |
| 2026-04-23 | (implement-ui remediation pass) | Final radius remediation — eliminated all remaining 4px (`rounded`) and 16px (`rounded-2xl`) violations across 19 files: 8 dashboard components, 5 instrument components (EntityGraph/Panel/IntelligenceTab/LiveQuoteBadge/OHLCVChart), chat bubbles (TypingIndicator/MessageBubble/StreamingBubble + skeleton), MarketStatusPill pill container, ArticleCard ticker link, HeatCell score spans, portfolio row items; lint ✓ typecheck ✓ 285/285 tests ✓ build ✓ | PASS |
| 2026-04-24 | [2026-04-24-qa-eodhd-optimization-wave-report.md](../audits/2026-04-24-qa-eodhd-optimization-wave-report.md) | EODHD optimization wave QA (commit f0a031f): OPT-3/10 + D-W1/2/3/5; 3 BLOCKING fixed (docker-compose missing 3 consumers, _parse_symbol format inversion, ISO3→ISO2 mismatch); 631 KG + 548 CI + 224 MI tests PASS; ruff clean | PASS_WITH_WARNINGS |
| 2026-04-24 | [2026-04-23-qa-full-post-bugfix-report.md](../audits/2026-04-23-qa-full-post-bugfix-report.md) | Full post-bugfix QA — 5-agent review of bcbf61d+a89c543+f65df81 commits (BP-159/179/180/181/182 fixes + Terminal Dark frontend); 4,206 backend unit + 285 worldview-web PASS; ruff+mypy clean; 2 BLOCKING (nlp-pipeline tenant isolation gaps — pre-existing), 6 CRITICAL (rag-chat arch violation + null-volume contract + alert startup race), 8 MAJOR | PASS_WITH_WARNINGS |
| 2026-04-24 | [2026-04-24-qa-post-remediation-certification-report.md](../audits/2026-04-24-qa-post-remediation-certification-report.md) | Post-remediation certification — independent verification of 11 findings fixed (F-001..F-017+F-020); nlp-pipeline sectioning arch violation fixed; ADR-AUTH-002 (JWT consolidation) + volume recovery plan written; 4,850 total tests PASS (4,467 backend + 288 frontend + 95 arch); 0 BLOCKING/CRITICAL; 3 residual risks mitigated with ADR/plans | READY |
| 2026-04-24 | [2026-04-24-qa-full-report.md](../audits/2026-04-24-qa-full-report.md) | Full production-grade certification — 8 specialist agents (Runtime, UI, Security, KG, Data, SnapTrade, AI, Architecture) across 1,855 files; 10 fixes applied (UI-007 WS reconnect, AI-005/006 chat fix, SEC-001 admin JWT, health test drift, SSE mismatch, CORS, prompts .pth, ruff format); 4,825 backend + 288 frontend tests PASS; KG-001 (S6→S7 data gap) and SEC-002 (logout spoofing) documented as open | PASS_WITH_WARNINGS |
| 2026-04-24 | [2026-04-24-qa-remediation-report.md](../audits/2026-04-24-qa-remediation-report.md) | Remediation QA — all 4 CRITICAL + 8 MAJOR fixes applied: KG-001 (enriched payload), SEC-002 (logout spoofing), RH-001 (KG Dockerfile), ARCH-003/004/005 (session-across-I/O), RH-002 (topic mismatch), ST-003 (cipher), SEC-005 (tenant filter), SEC-007 (port binding), SEC-009 (rate limiter); 5,322 total tests PASS (4,034 backend + 598 lib + 288 frontend + 0 failures) | **READY** |
| 2026-04-24 | [2026-04-24-residual-remediation-report.md](../audits/2026-04-24-residual-remediation-report.md) | Residual remediation — R27 ReadOnlyUnitOfWork added to portfolio (14 files, 8 use cases), rag-chat (5 files + 7 new tests), alert (7 files); SEC-003 verified already resolved; KG-002 validated with 21 new claim-path tests (S6 build + S7 parse + materialize); 3,803 backend + 412 lib + 288 frontend tests PASS; R27 coverage 6/6 applicable services | **READY** |
| 2026-04-24 | [2026-04-24-qa-live-stack-report.md](../audits/2026-04-24-qa-live-stack-report.md) | Live-stack runtime certification — full make dev-rebuild, 54/54 containers healthy; 5 CRITICAL/HIGH bugs found and fixed (BUG-001: rag-chat Dockerfile missing libs/prompts; BUG-002: temporal_events absent on stale volume → migration 0007; BUG-003: ValkeyClient.set() ex=/nx= mismatch → jti_check_valkey_unavailable across all 9 services; BUG-004: WS JWT sub=oidc_sub instead of UUID → alert WebSocket 403; BUG-005: KG fundamentals consumer BP-122 Avro dead-letter); security agent: SEC-002 FIXED, all boundaries hold; 4,054 backend + 288 frontend tests PASS | **READY_WITH_REMEDIATION** |

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
| PLAN-0041 | Instrument Page Redesign — Bloomberg-grade Overview (chart+right sidebar) + Fundamentals overhaul (section cards, sparklines, right sidebar: competitors/ownership/news, earnings/insider/technical components) + 6 new S9 proxy routes | Investigation 2026-04-27 | 2026-04-27 | 7 | — |
| PLAN-0040 | Multi-Provider OHLCV Routing and Intraday Resampling — Alpaca/Polygon adapters, config-backed routing cache, reclaim worker, intraday resampling worker (S2+S3) | PRD-0032 | 2026-04-26 | 10 | 2026-04-26 |
| PLAN-0038 | Free Provider Integration + Loki API Usage Observability — BaseProviderAdapter, Finnhub, Yahoo Finance, provider routing, zero-bar failover | investigation-2026-04-25 | 2026-04-26 | 5 | 2026-04-26 |
| PLAN-0036 | EODHD API Usage Reduction — Quota Enforcement, Symbol Tiering, PriceSnapshot Layer | PRD-native | 2026-04-24 | 4 | — |
| PLAN-0025 | Authentication & Security Foundation — OIDC/Zitadel, RS256 Internal JWT, S9 Hardening | PRD-0025 | 2026-04-23 | 6 | 2026-04-18 |
| PLAN-0026 | News Intelligence APIs — Ranked News Feed, Multi-Window Impact & LLM Relevance Scoring | PRD-0026 | 2026-04-22 | 8 | 2026-04-23 |
| PLAN-0001-A | Infrastructure Prerequisites: Repo Fixes + intelligence-migrations + S1 Internal | PRD-0001 | 2026-03-26 | 3 | — |
| PLAN-0001-B | Ingestion Pipeline v1: S4 Content Ingestion + S5 Content Store | PRD-0001 | 2026-03-27 | 8 | 2026-04-09 |
| PLAN-0001-B-R1 | S4 QA & Review Fixes: Runtime Bugs, Lock, Watermarks, Auth, Security, Tests, Infra | Review/QA | 2026-03-26 | 7 | — |
| PLAN-0001-B-R2 | S4+S5 QA Fixes: DDL, DLQ, SSRF, LSH, Contract Tests, Compounding | QA Review | 2026-03-27 | 4 | — |
| PLAN-0001-B-R3 | S4+S5 Architecture: ABCs, BaseKafkaConsumer, MinIO GC, DomainError, Standards | QA Review | 2026-03-27 | 5 | — |
| PLAN-0001-B-R4 | S4+S5 QA Review Fixes: DLQ Fidelity, SSRF Hardening, DDL Alignment, Process Compounding | QA Review | 2026-03-27 | 4 | — |
| PLAN-0001-C | Ingestion Pipeline v1: S6 NLP Pipeline + S7 Knowledge Graph + S10 Alert Service | PRD-0001 | 2026-03-29 | 11 | 2026-03-30 |
| PLAN-0001-E | S1+S2+S3 Deep QA Fixes: Idempotency, Atomicity, Security Hardening, Architecture Consistency | QA Review (QA-CROSS-002) | 2026-03-28 | 14 | 2026-03-28 |
| PLAN-0001-E-R1 | S1+S2+S3 Remaining Open Items: UoW commit, TOCTOU dedup, arch violations, topic mismatch, domain layer, auth | QA-CROSS-002 | 2026-03-30 | 6 | 2026-03-30 |
| PLAN-0002 | Enum Standardization: Shared OutboxStatus + ContentSourceType | N/A | 2026-03-26 | 2 | — |
| PLAN-0003 | Observability Standardization: Service Fixes + Monitoring Stack | N/A | 2026-03-27 | 4 | 2026-03-27 |
| PLAN-0004 | Observability Dashboards, Alerts & Recording Rules — Auto-Provisioned | N/A | 2026-03-27 | 5 | — |
| PLAN-0005 | Provider Config Externalization — Nested Settings Pattern (S4 + S2) | N/A | 2026-03-29 | 3 | — |
| PLAN-0006 | Process Architecture & Database Standardization: S4 Decoupling + Scheduler-Worker + R/W Split | N/A | 2026-03-30 | 5 | 2026-03-30 |
| PLAN-0007 | PLAN-0001-C QA Fixes: Idempotency, Valkey Hardening, Observability, Deployment Constraints | PLAN-0001-C QA | 2026-03-30 | 2 | — |
| PLAN-0008 | QA Follow-Up — Standards Enforcement, Architecture Hardening & Production Readiness | PLAN-0001-E-R1 QA | 2026-03-30 | 10 | 2026-03-30 |
| PLAN-0009 | R25 Layer Violation Remediation — S4 API Routes + ExecuteContentTaskUseCase | PLAN-0006 QA | 2026-03-30 | 4 | 2026-03-30 |
| PLAN-0010 | Architecture Hardening — DLQ Use Cases (R25), Security, Platform QA Script | QA-S4S5S6S7S10-001 | 2026-03-31 | 6 | 2026-03-31 |
| PLAN-0011 | Process Topology Standardization & Architecture Test Enforcement | N/A | 2026-04-01 | 9 | 2026-04-01 |
| PLAN-0012 | R23 Read/Write Database Session Split — Tests & Enforcement | N/A | 2026-04-01 | 4 | 2026-04-07 |
| PLAN-0013 | Process Topology Completion + Alert WebSocket Cross-Process Bridge | PLAN-0011 QA follow-up | 2026-04-01 | 6 | 2026-04-01 |
| PLAN-0015 | S8 RAG/Chat: Hybrid Intelligence Pipeline | PRD-0015 | 2026-04-09 | 22 | 2026-04-09 |
| PLAN-0016 | Chat Enhancements: GENERAL Intent + Context Window + Portfolio Risk Email Digest | PRD-0016 | 2026-04-09 | 11 | 2026-04-09 |
| PLAN-0017 | Entity Screener + Similarity Search + Embedding View Fix + EODHD Description LLM | PRD-0017 | 2026-04-08 | 11 | 2026-04-08 |
| PLAN-0018 | Geopolitical Intelligence + EODHD Deep Enrichment + Apache AGE Cypher Shadow Sync | PRD-0018 | 2026-04-09 | 10 | 2026-04-09 |
| PLAN-0019 | Polymarket Prediction Markets Integration + EDGAR Market-Hours Polling | PRD-0019 | 2026-04-09 | 6 | 2026-04-09 |
| PLAN-0020 | Market-Impact Signal Scoring (Option A — S6 Block 5 routing extension) | PRD-0020 | 2026-04-10 | 8 | 2026-04-10 |
| PLAN-0021 | Score-Gated Flash Alerts (AlertSeverity tiers — S10 + frontend) | PRD-0021 | 2026-04-10 | 6 | 2026-04-10 |
| PLAN-0027 | Frontend MVP UI — Professional Design v2.0. Superseded by PLAN-0028 before implementation was complete. | PRD-0027 | superseded | — | — |
| PLAN-0027-V2 | Frontend MVP UI — Complete Implementation v2 (Canvas + Code + Security). Superseded by PLAN-0028 after scope was rebaselined to `apps/worldview-web/`. | PRD-0027 | superseded | 2 | — |
| PLAN-0022 | SnapTrade Brokerage Portfolio Sync (Read-Only, S1 + S9 + frontend) | PRD-0022 | 2026-04-22 | 9 | — |
| PLAN-0028 | Worldview Web — Standalone Next.js frontend at `apps/worldview-web/` + S9 proxy route waves (S9-1/S9-2/S9-3) + all frontend waves F-1..F-13 + T-1 | PRD-0028 | 2026-04-18 | 17 | 2026-04-18 |
| PLAN-0029 | Missing Frontend Endpoints — S1 watchlist rename (PATCH), S8 briefing GET endpoints, S9 signals/ai proxy fix | PRD-0028 §6.2 | 2026-04-19 | 2 | 2026-04-19 |
| PLAN-0030 | Security Hardening — QA-2026-04-19 Remediation: dependency pinning, CI/CD SHA-pin, frontend security headers, gateway hardening, backend JWT issuer=, Docker non-root, JTI replay protection | QA-2026-04-19 | 2026-04-19 | 6 | 2026-04-19 |
| PLAN-0031 | Pipeline Reliability & Intelligence Hardening — Kafka retention, NER/extraction model tracking, D-004 dual-DB commit fix, entity.dirtied.v1 ordering, Gemini Lua atomicity, RAG circuit breaker, tenant isolation tests | Audit 2026-04-20 | 2026-04-22 | 8 | 2026-04-22 |
| PLAN-UI-VISUAL-OVERHAUL | Bloomberg-Grade Visual Overhaul — Amber/gold palette, data density, component polish, landing page, dashboard 4-col, page-specific polish + critic fixups | PRD-0027 | 2026-04-19 | 6+fixups | 2026-04-19 |
| PLAN-0032 | Forensic QA Remediation — Next.js 15.5.15 CVE upgrade, JWKS startup race (BP-164), CSP header, S9 callback sanitization (SEC-003), CORS port fix (SEC-008), transaction header forwarding (API-004), economic-calendar param (R-002), contradictions BP-069 fix, doc fixes | Forensic QA 2026-04-21 | 2026-04-22 | 6 | 2026-04-23 |
| PLAN-0033 | Unresolved Entity Re-Resolution & Cross-Service LLM Cost Tracking — UnresolvedResolutionWorker (S6), LlmUsageLogProtocol (libs/ml-clients), per-service llm_usage_log tables (S6+S8), S7+GeminiDescriptionAdapter refactor, S9 admin cost endpoint | PRD-0029 | 2026-04-22 | 5 | 2026-04-23 |
| PLAN-0034 | Daily AI Briefings & Centralized Prompt Library — Context Gathering Pipeline, libs/prompts, S6/S7/ml-clients Prompt Migration, Frontend Rendering | PRD-0030 | 2026-04-24 | 6 | 2026-04-24 |
| QA-CROSS-001 | Cross-Service QA: market-ingestion, market-data, portfolio (16 findings fixed) | N/A | 2026-03-27 | — | 2026-03-27 |
| QA-CROSS-002 | Deep Cross-Service QA: portfolio, market-ingestion, market-data (87 findings, 9 blocking/critical) | N/A | 2026-03-27 | — | 2026-03-27 |
| QA-E2E-001 | Comprehensive E2E Test Suite: S4+S5+S7 ASGI tests + S2→S3 cross-service + S1 security isolation (89 new tests) | N/A | 2026-03-28 | — | 2026-03-28 |
| QA-S4S5S6S7S10-001 | Full QA Pass + E2E Test Suite: S4/S5/S6/S7/S10 security fixes + ASGI e2e suites + cross-service integration + real provider tests + infra scaffold | N/A | 2026-03-30 | — | 2026-03-30 |
| QA-S1S2S3-2026-04-07 | QA Pass S1+S2+S3: PASS_WITH_WARNINGS — 8 MAJOR (ULID/metrics/cache-hook/contract-tests), 0 BLOCKING/CRITICAL, all unit+lint+mypy PASS | N/A | 2026-04-07 | — | 2026-04-07 |
| QA-S6S7S8-2026-04-09 | Deep QA Pass S6/S7/S8: TOCTOU soft_delete (CRITICAL), VectorSearch query wiring, entity.canonical.created.v1 dispatcher fix, S8 integration tests (14), 506+313+212 tests green | N/A | 2026-04-09 | — | 2026-04-09 |
| QA-S4S5-2026-04-09 | Deep QA Pass S4+S5: 5-agent review, 9 missing use-case unit tests added, F-DS-014 intra-batch dedup fix, 490+289 tests green, PASS_WITH_WARNINGS | N/A | 2026-04-09 | — | 2026-04-09 |
| QA-DEPLOY-2026-04-09 | Pre-Hetzner Deployment QA: full unit suite ~4059 tests PASS across all services+libs; BP-134 live test scope mismatch; observability gap (6/10 services in Prometheus); no production error tracking (Sentry/Glitchtip) | N/A | 2026-04-09 | — | 2026-04-09 |
| QA-PRE-DEMO-2026-04-13 | Pre-Demo Full QA Pass (2nd run, Docker running): ruff PASS; mypy PASS all 6 key services; libs 566 pass; services total ~3,650 pass, 0 fail; DEMO READINESS: CONDITIONAL GO. See docs/audits/2026-04-13-qa-pre-demo-report.md | N/A | 2026-04-13 | — | 2026-04-13 |
| QA-PLAN-0032-0033-0026-2026-04-23 | Cross-plan QA certification PLAN-0032+0033+0026: 4 BLOCKING + 3 CRITICAL fixed (TC003 regression, BP-165 JWT UUID, resolution_outcome type, log_id Rule 6); 5-agent review; 3,812 unit + 72 contract + 27+ integration PASS; ruff/mypy all clean; READY. See docs/audits/2026-04-23-qa-plan-0032-0033-0026-report.md | N/A | 2026-04-23 | — | 2026-04-23 |

## Conventions

- **Plan IDs** match their PRD: `PLAN-0001` corresponds to `PRD-0001`
- **File naming**: `NNNN-<description>-plan.md` (e.g. `0031-pipeline-reliability-hardening-plan.md`) — no `PLAN-` prefix in filename
- **Status values**: `draft` → `approved` → `in-progress` → `completed` | `cancelled` | `superseded`
- **QA column**: Date when `/qa` was run against the plan. `—` means not yet QA'd. `/qa` skill MUST update this column when it runs.
- **Wave tracking**: See the individual plan file for wave/task-level detail
- **Session boundaries**: Each sub-plan (A, B, C...) can be executed in a separate Claude Code session
- **Conflict check**: Before starting a wave, verify no other plan modifies the same files
- **Move to Completed**: When ALL waves in a plan reach `✅`, immediately move the row from Active to Completed. Do NOT leave completed rows in Active.

## How to Use

1. **Starting work**: Check this index for active plans. Read the plan file for the next ready wave.
2. **During implementation**: The `/implement` skill updates wave/task status in the plan file.
3. **After last wave**: Move the plan row from Active → Completed. Update the plan file frontmatter to `status: completed`.
4. **Conflict resolution**: If two plans touch the same service, execute them in dependency order.
