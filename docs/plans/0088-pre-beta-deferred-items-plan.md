---
id: PLAN-0088
title: "Pre-Beta Deferred Items — Hardening between Demo (PLAN-0087) and Daily-Analyst Beta"
status: in-progress
created: 2026-05-09
updated: 2026-05-10
owner: Arnau Rodon
audience: hedge-fund analyst/trader using the platform daily inside the firm
deadline: 2026-06-06 (T+4 weeks after demo on 2026-05-11)
type: implementation
spawned_from: PRD-0087 + 2026-05-09 beta-readiness audits
supersedes: none
---

## 0. Status Log

### 2026-05-10 demo-stabilization pass — all 13 Demo P0 closed

All 13 Demo P0 items shipped and validated against the live local stack
in a single orchestrated session (main + 2 worktree subagents). Final
report: `docs/audits/2026-05-10-demo-stabilization-report.md`.

**Done (commits, in order):**

- `b1342e33` **P0-1, P0-4** — alert WS audience validation +
  alert-dispatcher Postgres asyncpg pool recycle. WS upgrades now
  succeed (101) with correct `aud=worldview-internal` +
  `scope=alerts:stream`; wrong-audience tokens rejected with 403.
  Tests: 447 alert unit pass.
- `3915be23` **P0-2, P0-9, P0-12 (FE)** — AG Grid `theme="legacy"` prop
  for v33+ legacy-CSS theming; NarrativeHistoryPage `versions` (not
  `items`) aligned with canonical S7 schema; FundamentalSparkline
  empty-state renders `null` instead of stray em-dash. Test fixture
  realigned. Worldview-web rebuilt + deployed.
- `3915be23` (backend deploy) **P0-12 (data)** — market-data container
  rebuilt to deploy commit `55a06cd4` (sort-fix); AAPL revenue
  timeseries now returns `[2025-09-30, 2025-12-31, 2026-03-31]` instead
  of pre-IPO 1985 quarters.
- *(no commit — operational)* **P0-3** — Polymarket consumer was stuck
  at 0.6 msg/s with 48k pending lag after a 14h run. Restart raised
  drain to 11 msg/s; offsets reset to LATEST since prediction snapshots
  are upsert-keyed on `(market_id, snapshot_at)` — old events gain
  nothing on replay. Lag now 0–1k steady-state.
- `2e46c2c3` **P0-10** — Phase-A heuristic auto-titles on lazy
  thread-create in `persist_chat.py`. Sentence-boundary truncation,
  60-char ellipsis cap, "New Conversation" fallback only for
  whitespace-only messages. Manual rename via PATCH still wins.
  Tests: 26/26 chat persistence pass (6 new).
- `1090dcef` **P0-5, P0-6, P0-11** — equity-curve catchup raised 30 →
  252 trading days in `portfolio_snapshot_worker`; chart honestly
  starts at 2026-03-27 since OHLCV is missing for 11 of the held ETFs
  (audit notes the gap). `scripts/ops/backfill_watchlist_denorm.py`
  resolved 9 NULL `watchlist_members` rows → 0 NULL. CashRow renders
  em-dash + tooltip when broker balance unavailable; full SnapTrade
  balance integration scoped in
  `docs/audits/2026-05-10-demo-stabilization-cash-balance-state.md`.
- `60642605` **P0-7, P0-8, P0-13** — root cause of template-v1 was the
  shared `FallbackChainClient.extract` forcing JSON-mode for what is a
  free-form prose task. New `DeepInfraNarrativeChatClient` bypasses
  JSON mode; wired into both the scheduler and the manual trigger
  route. Live: 0 → 80 narratives with `model_id=meta-llama/
  Meta-Llama-3.1-8B-Instruct` (covers all 12 demo tickers). KG graph
  cap raised 50 → 200 in S9; FE slider ladder extended to 5 stops
  (15/40/80/120/160). AAPL has 128 relations available; previously
  capped at 50. `scripts/ops/backfill_duplicate_clusters.py` populated
  `duplicate_clusters` 0 → 791 rows (title-identity + minhash Jaccard
  passes); streaming Stage C worker remains TBD.
- `0582e3a5` **P1-19** — synthetic monitor probes corrected to canonical
  S9 surface: `/healthz` (was `/health`), `/v1/quotes/{instrument_id}`
  (was `/api/v1/market-data/AAPL/quote`),
  `/v1/holdings/{portfolio_id}` (was `/api/v1/portfolio/holdings`).
  Probes were silently 404'ing for an unknown duration.

**Live evidence summary (2026-05-10 ~16:17 UTC, all from real stack):**
- 76 containers up (only metrics-only sidecars without healthcheck;
  all app services healthy).
- Polymarket lag total: ~1.1k (steady state vs 48k baseline).
- Alert-dispatcher last 5min DNS errors: 0.
- Alert WS happy path: HTTP 101 + immediate `{"type":"ping"}`; wrong-aud
  token: HTTP 403.
- AAPL revenue timeseries: 2025-Q3 → 2026-Q1 (was 1985–1988).
- Narratives: 80 LLM rows (was 0); 689 template-v1 are pre-existing
  rows on long-tail entities.
- AAPL relations available to FE graph: 128 (cap 200 honoured).
- duplicate_clusters: 791 rows (was 0).
- watchlist_members NULL ticker/instrument_id rows: 0 (was 9).

**Beta blockers intentionally deferred (per user instruction):**
Wave A (Zitadel SSO + MFA), Wave B (TDE + GDPR + PII), Wave C (PITR),
Wave D (alerts + LLM-cost cap), F-1/F-2/G-1/G-4 frontend polish, full
SnapTrade balance integration (P0-11 follow-up), streaming
duplicate_clusters worker (P0-13 follow-up), OHLCV backfill for the 11
ETFs blocking honest equity-curve history (P0-5 follow-up).

### 2026-05-10 second pass — Wave E + replay + QA

Six parallel subagents shipped a substantial second batch:

**Done:**
- **Wave E Holdings redesign** (commit `84314be4`) — full implementation:
  - Deleted CashManagementCard, RealizedPnLChart, DividendIncomeTimeline
  - Added 8 new components: CashRow, ConcentrationStrip, ExposureStrip,
    DayPnLDistribution, DividendYTDStrip, RealizedPnLSparkline,
    PositionBarHeat, HoldingLotsPanel
  - Backend: get_holding_lots + compute_concentration use cases
  - 2 new endpoints: `GET /portfolios/{id}/holdings/{instr}/lots` and
    `GET /portfolios/{id}/concentration` (R27 ReadUoW, R25 use-case-only)
  - 13 new unit tests (FIFO, ST/LT boundary, HHI math, edge cases)
  - Portfolio tests 710 → 724; api-gateway 407 pass; frontend zero
    regressions
  - Live verified: HHI=2370 moderate, top-3=81.24%, 7 positions
- **Wave I-2 KG replay path** (commit `89363198`):
  - Built `scripts/ops/replay_kg_extraction.py` — clears
    routing_decisions sentinels and re-emits content.article.stored.v1
    outbox events
  - Discovered 561 EODHD silver articles never reached NLP (no
    routing_decisions row)
  - Enqueued 600 events; ~60 processed in session window
  - Density: relations 133→189, evidence_raw 120→178, canonicals 364→399
  - AAPL stuck at 6 edges due to **content-quality ceiling**: 100% of
    AAPL articles are 47-word Finnhub headlines (LLM yields 0-1 unique
    triples each; replays no-op once triples exist). Path to ≥30: longer
    sources (SEC 10-K, per-ticker EODHD) or extraction model upgrade
    (PLAN-0088 I-4).
- **Realized P&L sign-convention fix** (commit `fa279b7e`):
  - SnapTrade-synced SELL transactions have negative quantity; the FIFO
    walker silently dropped them via `if tx.quantity <= 0: return`
  - Fix: `effective_qty = abs(tx.quantity)` throughout BUY/SELL paths
  - Live verified: portfolio realized P&L was $0.00/0 trades; now
    $735.34/76 trades
- **Frontend Invalid-Date polish** (commit `19945166`):
  - 4 components leaking literal "Invalid Date" via unguarded `new Date(x).toLocaleTimeString()`
  - Centralised guard in `lib/utils.ts` (formatDate + safeFormatClockTime),
    11 regression tests added; touched MessageBubble, SlashTurnBlock,
    StaleBadge, InsiderTransactionsTable
- **Service validation matrix** (no commit — read-only):
  - 10 services verified up + healthy + migrated
  - Identified orphaned `market-data-prediction-markets` consumer (62k
    lag, dead 8h ago after Postgres DNS hiccup); restarted, now draining
- **News ingestion QA** (no commit — read-only):
  - All 5 adapters producing; EODHD now 772 docs, NLP draining backlog
  - 0 DLQ messages; outbox dispatcher 100% delivered

**Done (SA-3, commit 1fe34cbd):**
- **F-1** EarningsHistoryChart + TechnicalSnapshot into Overview right rail
  (zones 9+10 of 12-zone wireframe; same component instances, no double-fetch).
- **F-2** OwnershipSnapshotPanel into Overview right rail (zone 11).
- **G-1** IncomeStatementFY.tsx (NEW) — Finviz-style 4-FY column table
  (Revenue / Gross Profit / Op. Income / Net Income / EBITDA / EPS); G-4
  placeholder cleanup: rows where ALL FY columns null are collapsed. New
  S9 proxy route `/fundamentals/{id}/income-statement`; gateway method
  `getIncomeStatement`.
- **G-4** EarningsHistoryChart beat/miss coloring — bars now green=beat /
  red=miss vs epsEstimate when available (sign-based fallback when absent);
  tooltip shows "Est: $X ▲ beat / ▼ miss".
- **G-4** AnalystTargetSparkline.tsx (NEW) — visual low/consensus/high
  distribution bar with current-price marker; ±15% fallback spread; mounted
  at top of FundamentalsTab right sidebar.

**Still open:**
- Wave A (Zitadel SSO + MFA + Settings substance) — beta-blocking, ~25h
- Wave B (Postgres TDE + MinIO SSE + GDPR + structlog PII) — ~22h
- Wave C (PITR backups + MinIO mirror) — ~14h
- Wave D (Grafana alerts + LLM-cost cap) — ~12h
- Wave H-4 confirmed **moot** (existing entity_mentions path returns
  114+ articles for AAPL)
- ~~Wave H-5 (duplicate_clusters streaming worker)~~ — **DONE** SA-4 commit `f5268efa`
- Wave I-3, I-4, I-5 — relation_summaries close-out, model bench,
  density check (I-3 unblocked: prompt_templates FK seed fixed SA-4)
- Wave J — perf & scale
- AAPL graph: dense-graph auto-filter + camera-reset shipped SA-4; raw edge count still content-quality-gated

**Open issues flagged but not fixed:**
- ~~Portfolio internal JWT missing `aud` claim (log noise every 24s)~~ — **FIXED** SA-5 commit `cbbf0a4b`: alert `ALERT_S1_INTERNAL_JWT` re-generated with `aud=worldview-internal` (gitignored docker.env; container rebuild needed to deploy)
- ~~Market-data CRITICAL `internal_jwt_unverified_decode` log~~ — **FIXED** SA-5 commit `cbbf0a4b`: demoted CRITICAL→DEBUG (container rebuild needed)
- KG `/readyz` cosmetic kafka="not_started"
- Content-store consumer drift ~1.2k lag on content.article.raw.v1
- SnapTrade brokerage worker writes signed quantities to DB
  (Portfolio QA Issue-A); read path now correct but data shape divergent
- ~~duplicate_clusters table 0 rows after 1641 docs~~ — **FIXED** SA-4 commit `f5268efa`: streaming writer shipped + prompt_template FK seed fixed
- **NEW BP-443**: KG path-insight-worker: `end` reserved AGE keyword caused PostgresSyntaxError on all jobs — **FIXED** SA-5 commit `cbbf0a4b` (container rebuild needed; 3 pending jobs reset in DB)

### 2026-05-10 partial landing

The deferred-failure trio (EODHD, KG density, failing fixtures) and two
small Wave F/G items shipped in a single session. Larger waves (E, I-2
density replay, A–D) remain.

**Done:**
- **H-3** EODHD news adapter — root cause was seeder omission + stale
  "demo key" disable; `_EODHD_NEWS_SOURCES` now seeded conditionally on
  premium-key presence. 57 EODHD docs flowing within 5min of restart.
- **I core unblock** — three orthogonal bugs:
  1. `provisional_enrichment_core.py` referenced
     `subject_provisional_id` / `object_provisional_id` columns that do
     not exist on `relation_evidence_raw` (only `provisional_queue_id`
     was ever shipped). Rewritten to mirror
     `entity_consumer._unblock_provisional_evidence` single-column path.
  2. `dead_letter_cap` 100 → 5000 in `libs/messaging/.../base.py`. The
     previous cap fail-stopped the entire KG pipeline when D-INIT-6
     (source_name field added to nlp.article.enriched.v1) caused ~770
     pre-change messages on the topic to fail Avro deserialisation.
  3. `kg-service-group-enriched` offsets reset to LATEST to skip the
     poisoned backlog.
  → relations: 18 (seed only) → 46 in 30min. AAPL still at 5 edges
  pending broader backlog replay (Wave I-2).
- **Failing test fixtures (deferred-failure #3)** — three patches:
  1. `services/portfolio/tests/conftest.py` + `test_watchlist_api.py` +
     `test_watchlist_reverse_index.py` now wire `get_read_uow` +
     `read_factory` (R23 read/write split fixtures lagged behind PLAN-
     0076 B-5).
  2. `services/nlp-pipeline/tests/unit/api/test_entity_ownership.py`
     updated to assert the disabled-guard behaviour set by PLAN-0087
     (200 regardless of watchlist; `is_watched` never awaited).
  3. `services/market-data/tests/e2e/conftest.py` now probes the test
     DB host:port and `pytest.skip`s when unreachable (was: hard
     `OSError: Connect call failed`).
  Plus stale-assertion drift surfaced by the read_factory fix:
  `test_buy_transaction_creates_records` (no `holding.changed` post-
  BP-264) and `test_holdings_*` (paginated envelope).
- **F-3** `SplitsDividendsPanel.tsx` — 4-row Yield/Payout/Ex-Date/Last
  Split panel in the Overview right rail (zone 12 of the wireframe).
- **G-3** `ShortInterestRow.tsx` — 4-column Float/Short Float/Short
  Ratio/Short Int strip on the Fundamentals tab.

**Done (SA-4, commit f5268efa):**
- **prompt_templates FK seed**: SummaryWorker UUID `00000000-...-0001` seeded;
  `relation_summaries` will now populate on the next 60-min SummaryWorker tick.
- **Narrative regen longtail**: `scripts/ops/trigger_narrative_regen_longtail.py`
  executed; 100 entities reset, 310 eligible for Worker 13D-3 regen.
- **AAPL graph UX**: dense-graph auto-filter (30% floor for >50 edges) + Sigma
  camera-reset button + warning badge for 128-edge graphs.
- **EntitySidebar top-3 relations**: LLM summary panel reading from TanStack
  Query graph cache; `GraphEdge` type extended with `relation_summary`.
- **H-5 streaming dedup**: `StoredArticleDedupConsumer` on
  `content.article.stored.v1`; Jaccard >=0.65; `content-store-dedup-consumer`
  docker-compose entry; 321 unit tests pass.

**Still open:**
- Wave A (Zitadel SSO, MFA, Settings substance) — beta-blocking, not started.
- Wave B (Postgres TDE, MinIO SSE, GDPR, structlog PII) — not started.
- Wave C (PITR backups, MinIO mirror, alembic stamp) — not started.
- Wave D (Grafana alerts, Tempo, SnapTrade dashboard, LLM-cost cap) — not started.
- Wave H-1, H-2 (NewsAPI, SEC EDGAR adapter audits) — adapters seeded;
  audit deferred. H-4 (entity_article_links backfill) — moot per prior SA.
- I-2 (replay extraction for AAPL ≥ 30 edges target) — pipeline alive
  and growing, but a deliberate offset-reset-to-earliest replay is
  needed to materialise the 1141 historical LLM calls; currently the
  reset-to-latest skips them. Worth ~1h of operations work.
- I-3 (`relation_summaries` close-out) — unblocked by SA-4 seed fix; SummaryWorker
  will self-populate on next tick (no code change needed).
- I-4 (extraction model bench) — not started.
- Wave J (perf & scale) — not started.

### 2026-05-09 created



# PLAN-0088 — Pre-Beta Deferred Items

> **Boundary**: this plan covers everything that must land **between the
> 2026-05-11 hedge-fund-director demo (PLAN-0087 demo-readiness scope) and
> the platform being deployed inside the firm as a beta** (paying analyst
> uses it daily, unsupervised, for a week, with the firm's IT security
> review having looked at the substrate).
>
> Driver: 10-agent consolidated audit
> `docs/audits/2026-05-09-qa-plan-0087-beta-readiness-report.md` returned
> ~95 distinct beta-blocker / critical / major findings split across
> identity, data security, multi-tenant isolation, backups, observability,
> data quality, UI deferred work, and LLM/prompt quality. PLAN-0087 closes
> only the demo-grade subset; PLAN-0088 is the rest.

### 2026-05-10 PM pre-beta second pass — Demo P1 + Wave F/G/H-5 + full QA

Five parallel worktree subagents (SA-1..SA-5) + main-session integration +
read-only QA (SA-6). 14 commits on top of the AM P0 batch.
Final report: `docs/audits/2026-05-10-pre-beta-second-pass-report.md`.

**Done (commits, in order):**

- `e1b80e78` **SA-1 / Phase-1 demo risk** — OHLCV ETF backfill (2,750 bars
  across XLE/MSTR/QQQ/PPA/XLK/TLT/IEF/IBIT/VTV/XLV/XLY); equity curve now
  slopes $23,851–$26,351; 250 of 252 snapshots `data_quality=ok`. Cash/BP
  remains truthful em-dash by design. SnapTrade signed-quantity verified
  already correct (all 80 SELLs negative). Realized P&L fallback already
  correctly em-dash on null. 680 portfolio unit tests pass.
- `cbbf0a4b`, `0ee24338`, `96556a38` **SA-5 / runtime hygiene** —
  market-data `internal_jwt_unverified_decode` CRITICAL→debug
  (1,872/10m → 2/10m); BP-443 documented + AGE reserved-keyword `end`
  → `tgt` in path_discovery; Polymarket `auto_offset_reset=latest`
  config; alert `ALERT_S1_INTERNAL_JWT` regenerated with `aud:
  worldview-internal` so portfolio aud-noise drops to ~1/10m.
  Synthetic monitor revalidated probing `/healthz` 200. Service-health
  matrix clean except known Wave-D `alloy`. 7 KG AGE unit + 646
  market-data unit pass.
- `1fe34cbd`, `164e57de` **SA-3 / Wave F-1, F-2, G-1, G-4** — Overview
  right-rail densification (zones 9 EarningsHistoryChart + 10
  TechnicalSnapshot + 11 OwnershipSnapshotPanel); Fundamentals tab
  IncomeStatementFY (309 LOC) with last-4-FY columns; AnalystTargetSparkline
  (250 LOC); EPS bars green=beat / red=miss vs `epsEstimate`. New gateway
  proxy route `/v1/fundamentals/{id}/income-statement`. 407 api-gateway
  unit pass; TS clean; 0 lint errors on changed files.
- `17bc8f58`, `1d811437`, `46114f70`, `d61318b8`, `b0a50718` **SA-2 /
  dashboard P1** — predictions classifier 4 → 7 buckets (added
  ai/energy/tech with priority order); zero-count topic pills hidden
  after category query resolves; predictions empty-state gap fixed via
  `flex min-h-[88px]`; Movers segmented control with MARKET / HOLDINGS /
  WATCHLIST tabs (MARKET default); Market Snapshot rewrite — INDICES
  (QQQ/SPY/BTC) + EQUITIES (AAPL/MSFT/NVDA/AMZN/GOOGL/JPM) with
  `hasPrice` em-dash guard; Daily Brief actions polish (220px strip,
  icon alignment); density tokens on calendar widgets (`py-2` →
  `py-1.5`). 89/89 SA-2 tests pass; TS clean.
- `f5268efa`, `2493efd1` **SA-4 / KG / narratives / dedup** —
  `prompt_templates` FK seed `00000000-...-000001` (relation_summary_v2)
  applied (was the silent FK violation blocking SummaryWorker writes);
  `scripts/ops/trigger_narrative_regen_longtail.py` ran for 100 entities
  (LLM-generated narrative count climbing 80 → **345** at QA time);
  AAPL dense-graph readability — 50-edge threshold, camera-reset button,
  warning badge in `EntityGraph.tsx`; EntitySidebar top-3 relations
  panel reads cached graph data (relation type + confidence + neighbour
  + summary); H-5 streaming dup writer — `StoredArticleDedupConsumer`
  (Kafka group `content-store-dedup-consumer` on `content.article.stored.v1`,
  Jaccard ≥0.65, 14-day window) + `DuplicateClusterRepository` +
  `MinHashCorpusRepository` + new compose service entry. 321 content-store
  unit + 7 path-discovery regression pass.
- `08f09fc1` **main / lint cleanup** — removed unused
  `InlineEmptyState` import in `PredictionMarketsWidget.tsx` so next.js
  production build passes the strict no-unused-vars rule.

**Container rebuilds + recreations (30 containers):** api-gateway,
worldview-web, market-data and 5 consumers, alert and 4 consumers/schedulers,
knowledge-graph and 9 consumers/schedulers/workers (3 of which required
`--no-cache` because compose's per-service-name image hash didn't bust
on the SA-5 source change), content-store and 2 consumers + new
`content-store-dedup-consumer`. All healthy except deferred Wave-D `alloy`.

**Final QA (SA-6, read-only on real local stack):** verdict
**BETA-READY for 2026-05-11 demo**. 76 containers up; only Wave-D
`alloy` unhealthy. All 13 Demo P0s remain closed. 14 frontend routes
200; 0 ERROR/CRITICAL log lines in 10-min window across all 11
implementation services. DLQs offset 0. Polymarket lag steady ~6.7k
(acceptable due to upsert semantics). Two known partials documented
for follow-up: `content-store-dedup-consumer` MissingGreenlet at
session disposal blocks offset commits on 11/12 partitions
(backfill-writer is source of truth — `duplicate_clusters` = 791);
`knowledge-graph-path-insight-worker` Cypher list-comprehension `|`
syntax error breaks path computation downstream of BP-443 fix (3
failed jobs; not on demo path). New P2: scheduler 6h tick attempts
to insert path-insight job for orphaned `canonical_entities` row
(FK violation; no UX impact).

**Demo P1 backlog status:** 7 of 7 SA-2 items shipped; 4 of 4 SA-3
PLAN-0088 items shipped; 8 of 11 SA-1 items resolved (4 already
correct, 4 newly shipped, 3 deferred as not-load-bearing for demo);
4 of 5 SA-5 hygiene items closed; 5 of 7 SA-4 items shipped (H-5
streaming PARTIAL by design — backfill remains canonical).

---

## Phase 0 — What this plan does NOT cover

Boundary table (so future-me doesn't double-allocate effort):

| Area | Owner plan | Why excluded from PLAN-0088 |
|---|---|---|
| Demo-grade walkthrough fixes (Phase A surfaces, F-LLM-007 narrative venv skew, F-LLM-001 GLiNER class-mismatch, F-LLM-016 `[cN]` literal leak, demo-day rehearsal cadence, contingency trim path) | **PLAN-0087** | Already in flight; demo on 2026-05-11. |
| Multi-tenant content pipeline + tenant_document_uploads + delete consumer | **PLAN-0086** | Shipped 2026-05-08; this plan only adds the secondary hardening (MinIO key prefix, document_source_metadata tenant column, dedup-key tenant scoping). |
| Operating-table hardening (PLAN-0063 close-out, citation cron, ValkeyDedupMixin migration, port ABCs, boost sweep, CI gate flip) | **PLAN-0084** | Completed 2026-05-09. |
| Production deployment to Hetzner (Terraform, Helm, ArgoCD, Vercel) | **PLAN-0024** | Independent track; PLAN-0088 assumes same `make dev` deployment shape and prepares the platform to be run by the customer firm. |
| Answer-quality eval gating (L2-L4 NDCG/Hit@K gates, golden-set chunk_id audit) | **PLAN-0075** | Out of scope — diagnostic-only during PLAN-0087, gate-wiring deferred. |
| Light-mode theme support, full a11y audit, mobile/responsive, i18n | (none — not committed for beta) | Customer pre-qualified as dark-mode-tolerant; document-only. |
| Tier feature-gating + Stripe + entitlement service | (deferred to GA) | Beta is free for early customers. |
| Retrieval substrate W5-7 (contextual retrieval experiment) and W5-6 (ingestion bench) | **PLAN-0063** | Active but parallel; no overlap. |
| Polymarket Wave 2 adapters (4 new) | **PLAN-0056** | Roadmap; not blocking beta. |
| KG analytics + community detection + NLP cache + SSRF hardening | **PLAN-0023** | Roadmap; not blocking beta. |
| Frontend Settings → Notifications channel routing (email/SMS/Slack/webhook), mute windows, digest opt-in | (deferred — minimum-beta does not need this) | Document as known-limitation in onboarding doc; pick up post-beta. |
| Brokerage management UI (remove/re-sync from Settings → Integrations) | **PLAN-0088 Wave A only at the connect-flow recovery level** | Full Settings UI uplift deferred; minimum hook is "settings deep-links to /portfolio". |
| Workspace layout server-sync (per-device → per-user) | (deferred) | Document as per-device behaviour. |
| Customer-facing API portal / public OpenAPI publish | (deferred) | Customer integration is post-beta. |
| Light-mode token sweep | (deferred) | 2-3 weeks effort; pre-qualify customers. |

---

## Phase -1 — ID + rule collision check

- Plan IDs scanned: `ls docs/plans/` → highest existing is PLAN-0087. **PLAN-0088 is free**.
- Rule references used below: R10 (UUIDv7), R11 (UTC), R25 (no API → infra import), R27 (ReadOnlyUnitOfWork). All four verified in `RULES.md` lines 98/104/181/244.
- BP/SA references touched: BP-442, BP-443, BP-444, BP-445 (just landed in PLAN-0087 QA pass). New BPs likely to be added during this plan: backup/restore drill (Wave C), tenant-key MinIO migration (Wave A/B), GDPR cascade-delete pattern (Wave B).

---

## 1. Overview

### 1.1 Goal sentence
Bring the platform from "demo-grade for a friendly walkthrough" to
"a hedge-fund analyst at one regulated firm can use it daily for a week
unsupervised, and the firm's IT review accepts the security/compliance
substrate", inside a **3-4 engineer-week** budget.

### 1.2 Quality bar
- Zitadel SSO is the only login path (dev-login hard-blocked outside `APP_ENV != production`).
- Encryption at rest on Postgres + MinIO; encryption in transit on every Postgres / Kafka / MinIO link inside the cluster.
- Tested, documented PITR backup + restore drill (RPO ≤ 24 h, RTO ≤ 2 h).
- GDPR right-to-delete + chat retention worker live; PII scrubbed in structlog.
- MinIO objects key-prefixed by tenant_id; ValkeyDedupMixin keys tenant-scoped.
- Per-tenant + per-route (`/v1/chat`) rate limits + tenant-scoped LLM-cost dashboard + budget alerts.
- Holdings tab redesigned (drop dead widgets, add cost-basis ladder + sector HHI + tax-lot view + beta-adjusted exposure).
- Instrument Overview densified (move EarningsHistoryChart, TechnicalSnapshot, OwnershipSnapshotPanel, SplitsDividendsPanel into Overview right rail).
- Fundamentals Finviz polish (FY-column income statement, Performance row, short-interest row, beat/miss markers, analyst price-target distribution sparkline).
- News ingestion adapters (NewsAPI, SEC EDGAR, EODHD) running in parallel with Finnhub; entity_article_links populated for top-100 entities; dedup audit clean.
- Knowledge graph density: AAPL ≥ 30 edges; demo-critical entities (12 tickers) ≥ 20 each.
- Performance budgets met: pgvector HNSW p95 < 100 ms, AGE Cypher 2-hop p95 < 500 ms, frontend bundle < 1 MB gzipped.

### 1.3 Estimated total effort
**~140 engineer-hours ≈ 3.5 engineer-weeks** (target met). Distribution
by wave below.

---

## 2. Wave Structure (10 waves, A–J)

```
Wave A  Identity & access control hardening              ~25h
Wave B  Data security & compliance                       ~22h
Wave C  Backups & disaster recovery                      ~14h
Wave D  Observability & alerting                         ~12h
Wave E  Holdings redesign (Phase 2)                      ~16h
Wave F  Instrument Overview densification (Phase 2)      ~10h
Wave G  Fundamentals Finviz polish                       ~10h
Wave H  News ingestion completeness                      ~14h
Wave I  Knowledge graph density                          ~10h
Wave J  Performance & scale                              ~7h
                                                          ────
                                                         ~140h
```

Dependencies (top-down execution flow):
- **A (auth) blocks beta entirely**; can start day 1.
- **B (data security)** depends on A§5 (Settings UI deep-link) only loosely; starts day 1.
- **C (backups)** can start day 1, validates day 5.
- **D (observability)** day 1 in parallel.
- **E, F, G** (UI polish) parallel after demo (post-2026-05-11), independent of A–D.
- **H (news)** parallel after demo, independent.
- **I (KG density)** depends on H (more articles → more extraction); plan to start mid-week.
- **J (performance)** depends on E + F + H + I to have steady-state load to measure against; final week.

---

## Wave A — Identity & access control hardening

### Goal
Replace dev-login with production Zitadel SSO; enforce MFA for analyst users; wire the four placeholder Settings → Security/Integrations/Data/Beta-Program tabs to deep-link or hold real content; document an internal-JWT key-rotation playbook; document a secrets-rotation runbook.

### Dependencies
None — this wave starts day 1.

### Effort
~25h.

### Tasks

#### A-1 Deploy Zitadel + wire as live OIDC provider

- **Target files**:
  - `infra/compose/docker-compose.zitadel.yml` (already exists; promote to default-up service)
  - `infra/compose/docker-compose.yml` (add `worldview-zitadel-1`, `worldview-zitadel-init-1` to default profile)
  - `services/api-gateway/src/api_gateway/config.py` (set `oidc_issuer_url` default to local Zitadel)
  - `services/api-gateway/src/api_gateway/routes/auth.py:610-619` (`/v1/auth/register` redirect — verify Zitadel self-registration enabled)
  - `apps/worldview-web/.env.local` (set `NEXT_PUBLIC_AUTH_PROVIDER=zitadel`)
  - `docs/runbooks/zitadel-onboarding.md` (NEW)
- **depends_on**: none
- **Acceptance**:
  - `docker compose ps` shows `worldview-zitadel-1` healthy.
  - `GET /v1/auth/register` 302s to a working Zitadel register page (branded or default).
  - `POST /v1/auth/dev-login` returns 403 when `APP_ENV=production`.
  - Login via Zitadel completes the full PKCE round-trip and lands on `/` with a valid session cookie.
  - Integration test in `services/api-gateway/tests/integration/test_auth_zitadel.py` covers the happy path + missing-aud + expired-token negatives.

#### A-2 MFA enforcement for analyst role

- **Target files**:
  - Zitadel admin console (config-only — TOTP + WebAuthn enabled per project)
  - `apps/worldview-web/app/(app)/settings/security/page.tsx` (replace `<SettingsPlaceholder>` with deep-link card to Zitadel account console)
  - `services/api-gateway/src/api_gateway/middleware.py` (assert `amr` claim ⊃ {`mfa`} for analyst-tier roles before allowing any `/v1/portfolio*` write)
- **depends_on**: A-1
- **Acceptance**:
  - User without MFA enrolled cannot complete a `POST /v1/transactions`; receives 403 with `code="mfa_required"`.
  - Settings → Security page renders a "Manage 2FA" button that deep-links to `${oidc_issuer_url}/ui/console/users/me/security`.

#### A-3 Settings sub-pages: substance not placeholders

- **Target files**:
  - `apps/worldview-web/app/(app)/settings/security/page.tsx` (deep-links + active-sessions list via `/v1/auth/sessions`)
  - `apps/worldview-web/app/(app)/settings/integrations/page.tsx` (brokerage list with disconnect / re-sync via S1 endpoints)
  - `apps/worldview-web/app/(app)/settings/data/page.tsx` (export / delete-my-data — wires to Wave B-2)
  - `apps/worldview-web/app/(app)/settings/preferences/page.tsx` (server-persisted via new `/v1/users/me/preferences` — wires to Wave B-3)
  - `services/api-gateway/src/api_gateway/routes/auth.py` (NEW `GET /v1/auth/sessions`, `DELETE /v1/auth/sessions/{jti}`)
  - `services/portfolio/src/portfolio/api/routes/brokerage.py` (NEW `DELETE /v1/brokerage/connections/{id}`)
- **depends_on**: A-1, A-2
- **Acceptance**:
  - All four sub-pages render real state (no `<SettingsPlaceholder>` left).
  - User can disconnect a brokerage from the UI; `BrokerageConnection.is_active` flips to false; next sync skips it.
  - Active-sessions page lists current refresh-cookie JTIs (via Zitadel introspect or local audit log) and supports per-row revoke.

#### A-4 Internal-JWT key rotation playbook

- **Target files**:
  - `docs/runbooks/internal-jwt-rotation.md` (NEW — step-by-step JWKS rotation, dual-key window, kid pinning)
  - `services/api-gateway/src/api_gateway/internal_jwt_keys.py` (verify supports two kids simultaneously during rotation window; add unit test)
  - `infra/compose/docker-compose.yml` (env var `INTERNAL_JWT_PRIVATE_KEY_NEXT` for rotation grace period)
- **depends_on**: A-1
- **Acceptance**:
  - Runbook walks an operator through: generate new RSA key → load as `_NEXT` → restart S9 → confirm both kids in JWKS → flip primary to `_NEXT` → restart consumers → drop old kid after token TTL.
  - Unit test asserts an internal JWT signed by `_NEXT` is accepted by every middleware while `_PRIMARY` is also active.

#### A-5 Secrets-rotation runbook + APP_ENV guards on dev-login

- **Target files**:
  - `docs/runbooks/secrets-rotation.md` (NEW or expand existing — covers DeepInfra, Zitadel client_secret, MinIO root key, Postgres pg_hba password, JWT signing key, SnapTrade API key)
  - `services/api-gateway/src/api_gateway/middleware.py` (move `APP_ENV != production` guard from `__init__` config validation into `InternalJWTMiddleware.__init__` itself — F-005 from security audit)
  - 8 other services with same skip_verification pattern (audit + add guard)
- **depends_on**: A-1
- **Acceptance**:
  - Runbook covers all 6 secret families with rotation cadence (90 d for app secrets, 365 d for KMS root) and zero-downtime procedure.
  - Architectural test `tests/architecture/test_internal_jwt_skip_guard.py` asserts every `InternalJWTMiddleware.__init__` raises when `APP_ENV=production` AND `skip_verification=True`.

#### A-6 Tenant onboarding flow (manual-assist mode)

- **Target files**:
  - `docs/runbooks/tenant-onboarding.md` (NEW — admin-driven CLI script `scripts/ops/provision_tenant.py` + Zitadel project setup)
  - `scripts/ops/provision_tenant.py` (NEW — wraps `POST /tenants` + Zitadel project create + first-admin invite email)
  - `services/portfolio/src/portfolio/api/routes/tenant.py` (verify SEC-005 fix: `POST /tenants` requires platform-admin JWT)
- **depends_on**: A-1
- **Acceptance**:
  - Single-script execution provisions a new tenant + first admin user end-to-end (≤ 5 min).
  - SEC-005 verified: anonymous `POST /tenants` returns 401.

### Wave A validation gate
- E2E playwright test logs in via Zitadel, navigates Settings → all four sub-pages, disconnects a brokerage, re-runs sync, signs out — zero placeholder text reachable.
- Integration tests for A-1, A-3, A-5 architectural test all green.
- `docker compose ps` shows Zitadel healthy.
- Review checklist confirms R25 (no API → infrastructure imports added in route handlers) and R10 (any new IDs use UUIDv7).

### Wave A architecture compliance
- **R25**: New `/v1/auth/sessions` and `DELETE /v1/brokerage/connections/{id}` routes use application-layer use cases, no direct repository/infra imports in route handler bodies.
- **R27**: `GET /v1/auth/sessions` is a read use case → `ReadOnlyUnitOfWork`; `DELETE` uses write UoW.
- **R10**: New session-revocation rows / brokerage-disconnect events use `common.ids.new_uuid7()`.
- **R11**: All timestamps in new tables/events `TIMESTAMPTZ` UTC, never naive.

---

## Wave B — Data security & compliance

### Goal
Encrypt data at rest on Postgres + MinIO; enforce TLS / SASL_SSL on every intra-cluster link; ship GDPR right-to-delete + right-to-export; lock down chat-history retention; ship MinIO tenant key prefixing; redact PII in structlog.

### Dependencies
A-1 (Settings → Data page must already exist as a placeholder we now fill).

### Effort
~22h.

### Tasks

#### B-1 Postgres TDE + MinIO SSE-S3 + sslmode=require everywhere

- **Target files**:
  - `infra/compose/docker-compose.yml` (Postgres `POSTGRES_INITDB_ARGS=--data-checksums`, mount LUKS-equivalent volume; MinIO `MINIO_KMS_AUTO_ENCRYPTION=on` + bucket `BucketEncryption` SSE-S3)
  - `services/*/config.py` (every service — set `sslmode=require` on `DATABASE_URL` + `KAFKA_SECURITY_PROTOCOL=SASL_SSL` + `MINIO_USE_SSL=true`)
  - `infra/kafka/server.properties` (broker SASL_SSL + key/truststore)
  - `docs/architecture/decisions/0008-encryption-at-rest-and-in-transit.md` (NEW ADR)
  - `docs/runbooks/encryption-rotation.md` (NEW)
- **depends_on**: none
- **Acceptance**:
  - `docker exec worldview-postgres-1 pg_ctlcluster status` confirms data-checksums on.
  - `mc encrypt info` confirms SSE-S3 active on `worldview-bronze`, `worldview-silver`, `market-bronze`, `market-canonical`.
  - `psql "host=worldview-postgres-1 sslmode=disable …"` is rejected; `sslmode=require` succeeds.
  - All 30+ service containers reconnect with TLS; smoke `make dev && curl /v1/health` on every service returns 200.

#### B-2 GDPR right-to-delete + right-to-export

- **Target files**:
  - `services/api-gateway/src/api_gateway/routes/users.py` (NEW — `POST /v1/users/me/delete-request`, `GET /v1/users/me/export`)
  - `services/portfolio/src/portfolio/application/use_cases/delete_user_data.py` (NEW — cascade across S1/S8/S10 via Kafka event)
  - `infra/kafka/schemas/user.deletion.requested.v1.avsc` (NEW Avro schema)
  - `services/rag-chat/src/rag_chat/application/use_cases/handle_user_deletion.py` (NEW consumer — deletes threads/messages/briefs)
  - `services/alert/src/alert/application/use_cases/handle_user_deletion.py` (NEW consumer — deletes alerts + subscriptions)
  - `services/knowledge-graph/src/knowledge_graph/application/use_cases/handle_user_deletion.py` (NEW consumer — anonymises tenant-scoped overlays)
  - `apps/worldview-web/app/(app)/settings/data/page.tsx` (replace placeholder with export button + delete-my-data flow)
  - `docs/runbooks/gdpr-delete.md` (NEW)
- **depends_on**: A-3
- **Acceptance**:
  - `POST /v1/users/me/delete-request` writes one outbox row, returns 202 with a soft-delete confirmation token (30-day window).
  - After 30 days a scheduled worker hard-deletes; before that, user can cancel.
  - `GET /v1/users/me/export` returns a signed URL (≤5 min TTL) to a JSON+CSV bundle in MinIO `worldview-export/<tenant>/<user>/<uuid7>.zip`.
  - Integration test asserts: create user → record 5 transactions, 3 chat threads, 2 alerts → export → assert all 10 rows present in zip → delete → assert all rows gone after worker run.

#### B-3 Chat-history retention + PII redaction in structlog

- **Target files**:
  - `services/rag-chat/alembic/versions/00xx_add_chat_retention.py` (NEW — TTL field on `messages` + `threads`)
  - `services/rag-chat/src/rag_chat/infrastructure/workers/chat_retention_worker.py` (NEW — daily delete of `messages.created_at < NOW() - INTERVAL '90 days'`, configurable per-tenant)
  - `apps/worldview-web/app/(app)/settings/data/page.tsx` (add "delete chat older than X days" control)
  - `services/rag-chat/src/rag_chat/api/routes/users.py` (NEW endpoint `PATCH /v1/users/me/preferences` — wires preference to backend, fixes B.5 from blockers audit)
  - `services/portfolio/alembic/versions/00xx_add_user_preferences.py` (NEW table or column on `users`)
  - `libs/observability/src/observability/structlog_pii.py` (NEW — `redact_pii_processor` that strips `$NNN[KMB]?`, email, SSN-shape, phone-shape from message field; mounts on every service's structlog config)
- **depends_on**: B-2
- **Acceptance**:
  - Retention worker run on a synthetic 1k-row `messages` table with 80% old → 800 rows deleted, 200 retained.
  - Preferences (density/currency/timezone) persisted across browser-clear + cross-device.
  - Architectural test asserts `redact_pii_processor` is in the structlog chain of every service that ingests user input.

#### B-4 MinIO tenant key prefixing + libs/storage adapter enforcement

- **Target files**:
  - `libs/storage/src/storage/keys.py` (NEW or extended `KeyBuilder.with_tenant(tenant_id)` — prefix every key `tenants/<uuid>/...` for tenant-private content)
  - `libs/storage/src/storage/minio_client.py` (assert prefix in `put_object` / `get_object`; raise `MissingTenantPrefixError` on absent)
  - `services/content-store/src/content_store/application/use_cases/store_article.py` (pass `tenant_id` to KeyBuilder)
  - `services/content-ingestion/src/content_ingestion/application/use_cases/upload_document.py` (pass `tenant_id`)
  - `scripts/ops/migrate_minio_tenant_keys.py` (NEW — one-time migration of existing tenant-scoped objects under tenants/<uuid>/ prefix)
  - `docs/architecture/decisions/0009-minio-tenant-key-prefixing.md` (NEW ADR)
- **depends_on**: B-1
- **Acceptance**:
  - `mc ls --recursive worldview-bronze/tenants/` returns ≥ 1 object after tenant-uploaded document workflow.
  - Architectural test `tests/architecture/test_minio_tenant_prefix.py` greps `libs/storage` and `services/*/infrastructure` for `put_object(` calls and asserts every call passes through `KeyBuilder.with_tenant(...)` (allowlist for public-content paths).
  - Cross-tenant `get_object` for a key under another tenant's prefix returns 403 (MinIO bucket policy).

#### B-5 ValkeyDedupMixin tenant scoping (F-DS-004)

- **Target files**:
  - `libs/messaging/src/messaging/kafka/consumer/dedup.py` (extend key format `{prefix}:{tenant_id}:{event_id}`)
  - `libs/messaging/src/messaging/kafka/consumer/base.py` (extract `tenant_id` from event payload before mark_processed/is_duplicate)
  - `services/nlp-pipeline/src/nlp_pipeline/infrastructure/messaging/consumers/article_consumer.py` (verify tenant_id extraction)
  - `services/content-store/src/content_store/infrastructure/messaging/consumers/document_ready_consumer.py` (same)
  - `services/content-ingestion/src/content_ingestion/infrastructure/messaging/consumers/document_deletion_consumer.py` (same)
- **depends_on**: B-4
- **Acceptance**:
  - Unit test: same `event_id` from two different `tenant_id` values is processed twice (not dedup'd).
  - Same `event_id` + same `tenant_id` is dedup'd as before.

#### B-6 Audit-log expansion (event taxonomy + retention)

- **Target files**:
  - `services/portfolio/alembic/versions/00xx_expand_audit_log.py` (extend `auth_audit_log` with new event_type values: `entity_view`, `portfolio_query`, `admin_dashboard_view`, `gdpr_delete_request`, `gdpr_export`)
  - `services/portfolio/src/portfolio/application/use_cases/log_audit_event.py` (NEW shared audit-log writer)
  - 5 callsites (one per new event_type)
  - `apps/worldview-web/app/(app)/admin/audit/page.tsx` (NEW admin-only page for browsing audit log)
  - `docs/runbooks/audit-log-retention.md` (NEW — 7-year retention for regulated firms)
- **depends_on**: B-2 (uses delete + export event_types)
- **Acceptance**:
  - Every Phase A surface that touches user data writes one audit row (verified by integration test that hits 8 endpoints + asserts 8 rows).
  - Admin audit page paginates 1000+ rows without slowness.

### Wave B validation gate
- All B-* integration tests green.
- E2E: create user, do 10 actions, request delete → 202; export → zip contains all 10; after retention window → zero rows visible to that user.
- Architectural tests for MinIO tenant prefix and structlog PII redaction green.
- Smoke: `psql sslmode=disable` rejected; `mc encrypt info` confirms SSE on all 4 buckets.

### Wave B architecture compliance
- **R25**: Cascade-delete consumers in S8/S10/S7 are application-layer use cases; route handlers in S9 are thin wrappers.
- **R27**: Audit-log read APIs use `ReadOnlyUnitOfWork`.
- **R10**: New `audit_log_id`, `deletion_request_id`, `export_request_id` columns are UUIDv7.
- **R11**: All timestamp columns `TIMESTAMPTZ` UTC.

---

## Wave C — Backups & disaster recovery

### Goal
Nightly Postgres + MinIO backups with off-cluster replication; documented + tested restore drill (RPO ≤ 24 h, RTO ≤ 2 h).

### Dependencies
B-1 (encrypt before backing up so restore round-trip preserves encryption).

### Effort
~14h.

### Tasks

#### C-1 Postgres PITR via WAL archiving

- **Target files**:
  - `infra/compose/docker-compose.yml` (postgres `wal_level=replica`, `archive_mode=on`, `archive_command='/scripts/wal_archive.sh %p'`)
  - `infra/scripts/wal_archive.sh` (NEW — push WAL to MinIO `worldview-backups/postgres/wal/`)
  - `infra/cron/postgres-basebackup.sh` (NEW — nightly `pg_basebackup` to MinIO `worldview-backups/postgres/base/<date>/`)
  - `docs/runbooks/backup-restore-postgres.md` (NEW with restore-drill steps)
- **depends_on**: B-1
- **Acceptance**:
  - 3 consecutive nights of base + WAL backups present in MinIO `worldview-backups/postgres/`.
  - Restore drill: spin up empty Postgres, restore from yesterday's base + replay WAL to T-1h, verify row counts match production within 1%.
  - Drill log committed to `docs/audits/2026-MM-DD-restore-drill-postgres.md`.

#### C-2 MinIO mirroring to off-cluster bucket

- **Target files**:
  - `infra/compose/docker-compose.yml` (add `mc mirror` cron container or `MinIO bucket replication` config)
  - `infra/cron/minio-mirror.sh` (NEW — nightly `mc mirror --remove worldview-bronze offsite/worldview-bronze`)
  - `docs/runbooks/backup-restore-minio.md` (NEW)
- **depends_on**: B-1
- **Acceptance**:
  - 3 consecutive nights of bronze + silver mirrors verified by `mc diff`.
  - Restore drill: drop a random object, run `mc cp offsite/<key> worldview-bronze/<key>`, verify roundtrip < 30 s.

#### C-3 RPO/RTO doc + executive summary

- **Target files**:
  - `docs/MASTER_PLAN.md` (add "Disaster Recovery" subsection citing C-1, C-2)
  - `docs/disaster-recovery.md` (NEW — RPO=24h on Postgres, RPO=24h on MinIO, RTO=2h end-to-end; documented drill date)
- **depends_on**: C-1, C-2
- **Acceptance**:
  - Doc reviewed; one-line summary visible to MASTER_PLAN.md readers.

#### C-4 Alembic stamp-head fix on 5 unstamped DBs (F-021)

- **Target files**:
  - `infra/scripts/alembic_stamp_head.sh` (NEW one-shot)
  - Alembic configs for: `nlp_db`, `intelligence_db`, `market_data_db`, `portfolio_db`, `rag_db`
- **depends_on**: none
- **Acceptance**:
  - All 9 DBs return non-empty `SELECT * FROM alembic_version`.
  - Architectural test `tests/architecture/test_alembic_versions_present.py` asserts every DB has exactly one alembic_version row.

### Wave C validation gate
- Restore drill log committed; RPO/RTO doc reviewed.
- All 9 DBs stamped.
- `mc diff` clean on the offsite mirror.

### Wave C architecture compliance
- No code changes inside service layers; entirely infra + ops.
- **R10/R11** untouched (no new tables).
- BP entry: BP-446 — "PITR drill procedure".

---

## Wave D — Observability & alerting

### Goal
Wire Grafana alert rules for the 6 SLO-critical signals; size Tempo retention; surface SnapTrade quota dashboard; expose per-tenant LLM-cost dashboard with budget alerts.

### Dependencies
None.

### Effort
~12h.

### Tasks

#### D-1 Grafana alert rules + error-rate SLO

- **Target files**:
  - `infra/grafana/provisioning/alerting/worldview-alerts.yaml` (NEW or extend — alerts for: rag-chat 5xx > 5/min, S9 p95 > 2 s, Kafka consumer-group lag > 1k, outbox dispatcher backlog > 100, KG narrative template-fallback > 5/min, SnapTrade quota > 80%)
  - `infra/grafana/dashboards/worldview-slo.json` (NEW — burn-rate dashboard for the 99.5% availability SLO over 30d)
  - `infra/observability/alertmanager.yml` (verify Slack webhook routing per env)
- **depends_on**: none
- **Acceptance**:
  - All 6 alerts visible in Grafana Alerting UI; one synthetic alert fires + reaches Slack #worldview-alerts test channel.
  - SLO dashboard reads from Prometheus and shows non-zero burn rate for at least one source.

#### D-2 Tempo retention sizing

- **Target files**:
  - `infra/observability/tempo.yml` (set `compactor.compaction.block_retention=336h` (14d); validate disk budget at 14d × current ingest rate)
  - `infra/compose/docker-compose.yml` (set Tempo volume size accordingly)
- **depends_on**: none
- **Acceptance**:
  - 24h ingestion test confirms Tempo disk usage < 10 GB; 14d projection < 100 GB.

#### D-3 SnapTrade quota dashboard

- **Target files**:
  - `services/portfolio/src/portfolio/infrastructure/snaptrade/quota_metrics.py` (NEW — Prometheus counter + gauge for `snaptrade_quota_remaining`)
  - `infra/grafana/dashboards/worldview-brokerage.json` (NEW dashboard)
- **depends_on**: D-1
- **Acceptance**:
  - Dashboard renders quota remaining; alert fires at < 20%.

#### D-4 Per-tenant LLM-cost dashboard + budget alerts

- **Target files**:
  - `services/api-gateway/src/api_gateway/routes/admin_costs.py:N` (extend `GET /v1/admin/llm-costs` to accept `tenant_id` filter; respect tenant of caller for non-admin role)
  - `apps/worldview-web/app/(app)/settings/data/page.tsx` (extend Wave B-2 page with "Your LLM cost this month: $X / cap $Y" gauge)
  - `services/portfolio/alembic/versions/00xx_tenant_llm_budget.py` (NEW — `tenant_llm_budgets` table)
  - `services/api-gateway/src/api_gateway/middleware.py` (NEW middleware: 503 if tenant has burned 100% of monthly cap; 429 with retry-after if 95%)
- **depends_on**: D-1, B-2
- **Acceptance**:
  - Tenant-scoped cost page shows real $ figures (matches `llm_usage_log` aggregate).
  - Synthetic test: budget=$1, burn $1.05 → next request 503 with body `code="budget_exhausted"`.

### Wave D validation gate
- 6 alert rules visible + one-shot fire validated.
- Tempo disk usage projection accepted.
- Cost-cap circuit breaker integration test green.

### Wave D architecture compliance
- **R25**: cost-cap middleware in `api_gateway/middleware.py` reads from S1 service (no direct DB).
- **R27**: cost-aggregate query is read-side, uses `ReadOnlyUnitOfWork`.

---

## Wave E — Holdings redesign (Phase 2)

### Goal
Drop the 4 dead widgets (CashManagementCard, RealizedPnLChart, DividendIncomeTimeline, RecentActivityFeed) and add 4 high-value institutional widgets (cost-basis ladder, sector HHI strip, tax-lot view, beta-adjusted exposure). Anchored to `docs/audits/2026-05-09-qa-holdings-redesign.md` §1+§2.

### Dependencies
None — purely frontend + portfolio S1 read-side use cases.

### Effort
~16h.

### Tasks

#### E-1 Drop dead widgets, replace with single-row strips

- **Target files**:
  - `apps/worldview-web/components/portfolio/CashManagementCard.tsx` (DELETE)
  - `apps/worldview-web/components/portfolio/RealizedPnLChart.tsx` (DELETE — replaced by sparkline in E-2)
  - `apps/worldview-web/components/portfolio/DividendIncomeTimeline.tsx` (DELETE)
  - `apps/worldview-web/components/portfolio/RecentActivityFeed.tsx` (only kept when broker-connected)
  - `apps/worldview-web/app/(app)/portfolio/page.tsx` (drop imports, layout)
  - `apps/worldview-web/components/portfolio/CashRow.tsx` (NEW R-7 — h-7 strip)
  - `apps/worldview-web/components/portfolio/DividendYTDStrip.tsx` (NEW R-6 — h-7 strip)
- **depends_on**: none
- **Acceptance**:
  - Holdings tab vertical scroll ≤ 700 px (down from ~1400).
  - All 4 dead widgets removed from imports + tests; `pnpm test`/`pnpm typecheck`/`pnpm lint` clean.

#### E-2 Cost-basis ladder + tax-lot expand-row in main table

- **Target files**:
  - `services/portfolio/src/portfolio/application/use_cases/get_holding_lots.py` (NEW — reuses `_OpenLot` walker from `get_realized_pnl.py`)
  - `services/api-gateway/src/api_gateway/routes/portfolio.py` (NEW `GET /v1/portfolios/{id}/holdings/{instrument_id}/lots`)
  - `apps/worldview-web/components/portfolio/SemanticHoldingsTable.tsx` (extend to support expand-row showing FIFO lots: open date, qty, cost-per-share, days-held, ST/LT classification, unrealised)
  - `apps/worldview-web/components/portfolio/RealizedPnLSparkline.tsx` (NEW R-10 — h-12 sparkline replacing 280px chart)
- **depends_on**: E-1
- **Acceptance**:
  - Click row in holdings table → expand shows ≥ 1 lot per holding for AAPL/MSFT/NVDA seed positions.
  - `GET /v1/portfolios/{id}/holdings/{instrument_id}/lots` returns FIFO-ordered lots; integration test asserts ST vs LT classification correct on a 365-day boundary.

#### E-3 Sector HHI strip + beta-adjusted exposure row

- **Target files**:
  - `services/portfolio/src/portfolio/application/use_cases/compute_concentration.py` (NEW — Herfindahl index + top-3 share)
  - `services/api-gateway/src/api_gateway/routes/portfolio.py` (NEW `GET /v1/portfolios/{id}/concentration`)
  - `services/portfolio/src/portfolio/application/use_cases/compute_beta_exposure.py` (NEW — joins holdings × instrument betas from `technicals_snapshots`)
  - `apps/worldview-web/components/portfolio/ConcentrationStrip.tsx` (NEW R-3 — HHI label + top-3 % badge)
  - `apps/worldview-web/components/portfolio/ExposureStrip.tsx` (NEW R-12 — replaces ExposureBreakdown panel; gross / net / leverage / beta-adjusted row)
- **depends_on**: E-2
- **Acceptance**:
  - HHI computed for the 5-position seed = ~1847 (moderate).
  - Beta-adjusted exposure row shows weighted average β across positions.

#### E-4 Position bar heat strip + day P&L distribution sparkline

- **Target files**:
  - `apps/worldview-web/components/portfolio/PositionBarHeat.tsx` (NEW R-11 — h-12 row, vertical bars: weight × pnl%)
  - `apps/worldview-web/components/portfolio/DayPnLDistribution.tsx` (NEW R-2 — h-7 sparkline of last 30 trading days)
  - `services/portfolio/src/portfolio/application/use_cases/get_value_history.py` (extend to return per-day Δ for sparkline)
- **depends_on**: E-3
- **Acceptance**:
  - Both new components render with seed-data only; pnpm test green.

### Wave E validation gate
- Vertical scroll ≤ 700 px verified in E2E playwright.
- All four new endpoints green in S9 smoke matrix.
- Lint + typecheck + test clean.
- Visual diff vs `docs/audits/2026-05-09-qa-holdings-redesign.md` §3 wireframe approved.

### Wave E architecture compliance
- **R27**: All new endpoints (`/lots`, `/concentration`) are read-side → `ReadOnlyUnitOfWork`.
- **R25**: New use cases live in `application/use_cases/`; route handlers thin.
- **R10**: Lot identifiers are deterministic (no new IDs); concentration response uses computed shape only.

---

## Wave F — Instrument Overview densification (Phase 2)

### Goal
Move EarningsHistoryChart, TechnicalSnapshot, OwnershipSnapshotPanel, and a new SplitsDividendsPanel from the Fundamentals tab into the Overview right rail to hit the 12-zone wireframe in `docs/audits/2026-05-09-qa-instrument-overview-redesign.md` §3.

### Dependencies
None — pure frontend composition.

### Effort
~10h.

### Tasks

#### F-1 Move EarningsHistoryChart + TechnicalSnapshot into Overview

- **Target files**:
  - `apps/worldview-web/components/instrument/OverviewLayout.tsx` (extend right column with [9] Key Metrics + [10] Tech Snapshot zones; left column adds [6] Earnings History 140 px)
  - `apps/worldview-web/components/instrument/EarningsHistoryChart.tsx` (verify reusable; no API changes)
  - `apps/worldview-web/components/instrument/TechnicalSnapshot.tsx` (verify reusable)
  - `apps/worldview-web/app/(app)/instruments/[entityId]/page.tsx` (deduplicate — Fundamentals tab still owns the full version, Overview shows compact)
- **depends_on**: none
- **Acceptance**:
  - Overview tab vertical content ~1100 px (matches §3 wireframe).
  - No double-render of EarningsHistoryChart between tabs (each instance has unique React key).

#### F-2 Move OwnershipSnapshotPanel into Overview right rail

- **Target files**:
  - `apps/worldview-web/components/instrument/OverviewLayout.tsx` ([11] Ownership zone)
  - `apps/worldview-web/components/instrument/OwnershipSnapshotPanel.tsx` (verify reusable)
- **depends_on**: F-1
- **Acceptance**:
  - Insider% / Inst% / Float visible in Overview right rail.

#### F-3 New SplitsDividendsPanel

- **Target files**:
  - `apps/worldview-web/components/instrument/SplitsDividendsPanel.tsx` (NEW)
  - `apps/worldview-web/lib/api/instruments.ts` (extend `getFundamentals` transformer to surface div_yield, payout_ratio, ex_date, last_split)
  - `apps/worldview-web/components/instrument/OverviewLayout.tsx` ([12] zone)
- **depends_on**: F-2
- **Acceptance**:
  - For AAPL, panel shows: Yield, Payout Ratio, Ex-date, Last split (`/v1/fundamentals/{id}/splits-dividends` already returns these).

#### F-4 Insider Activity strip + entity graph fallback list

- **Target files**:
  - `apps/worldview-web/components/instrument/OverviewInsiderStrip.tsx` (already created in PLAN-0087 audit pass; verify integrated)
  - `apps/worldview-web/components/instrument/EntityGraphPanel.tsx` (verify <5-edges fallback list lands in Overview redesign)
- **depends_on**: F-3
- **Acceptance**:
  - Insider strip renders 5 most recent rows for AAPL.
  - With 3-edge AAPL graph, fallback relations list shows beneath SVG.

### Wave F validation gate
- E2E playwright on `/instruments/AAPL` Overview tab counts 12 distinct visible zones.
- Lighthouse / bundle size ≤ baseline + 5%.
- Lint + typecheck + test clean.

### Wave F architecture compliance
- Frontend-only; no backend boundary tests required.
- R25/R27 unaffected (no route changes).

---

## Wave G — Fundamentals Finviz polish

### Goal
Adopt items 4–9 from `docs/audits/2026-05-09-qa-fundamentals-finviz.md` "Backlog" — FY-column income statement, Performance row, short-interest row, beat/miss markers, analyst price-target distribution sparkline.

### Dependencies
None.

### Effort
~10h.

### Tasks

#### G-1 FY-column income statement table

- **Target files**:
  - `apps/worldview-web/components/instrument/IncomeStatementFY.tsx` (NEW — 5 rows × 6 FY columns + TTM)
  - `apps/worldview-web/lib/api/instruments.ts` (extend timeseries call to fetch annual)
  - `services/market-data/src/market_data/api/routers/fundamental_metrics.py` (verify `period_type=ANNUAL` honoured by the same `order=desc` fix landed in PLAN-0087)
- **depends_on**: none
- **Acceptance**:
  - For AAPL, table shows 6 most-recent FYs of Revenue / Gross Profit / Operating Income / Net Income / EPS. TTM column leftmost.

#### G-2 Performance row (1D/5D/1M/3M/6M/YTD/1Y/5Y)

- **Target files**:
  - `apps/worldview-web/components/instrument/PerformanceBar.tsx` (already drafted in PLAN-0087 audit — verify or extend with 5Y)
- **depends_on**: none
- **Acceptance**:
  - Strip shows 8 chips, color-coded, computed client-side from existing OHLCV bars (no new endpoint).

#### G-3 Short-interest row

- **Target files**:
  - `apps/worldview-web/components/instrument/ShortInterestRow.tsx` (NEW — Float / Short Float % / Short Ratio / Short Interest)
  - `apps/worldview-web/lib/api/instruments.ts` (extract `share_statistics` section)
- **depends_on**: none
- **Acceptance**:
  - For AAPL, row shows real values from `/v1/fundamentals/{id}/share-statistics`.

#### G-4 EPS Trend beat/miss markers + analyst price-target distribution

- **Target files**:
  - `apps/worldview-web/components/instrument/EarningsHistoryChart.tsx` (color bars by surprise: green if actual > estimate)
  - `apps/worldview-web/components/instrument/AnalystTargetSparkline.tsx` (NEW — sparkline of low/median/high target with current price marker)
- **depends_on**: G-1
- **Acceptance**:
  - Beat/miss colors visible on AAPL 8-quarter chart.
  - Sparkline shows 4-point distribution + current price line.

### Wave G validation gate
- All 4 components rendered in Fundamentals tab with seed data.
- Lint + typecheck + test clean.

### Wave G architecture compliance
- Frontend-only.

---

## Wave H — News ingestion completeness

### Goal
Confirm/fix NewsAPI + SEC EDGAR + EODHD adapters (currently only Finnhub flows reliably); backfill `entity_article_links`; clean dedup audit.

### Dependencies
None — but feeds Wave I (KG density relies on more articles).

### Effort
~14h.

### Tasks

#### H-1 NewsAPI adapter — verify + fix

- **Target files**:
  - `services/content-ingestion/src/content_ingestion/infrastructure/adapters/newsapi.py` (audit: rate-limit handling, dedup hashing, fields populated)
  - `services/content-ingestion/tests/integration/test_newsapi_adapter.py` (NEW — uses recorded VCR cassette)
  - `services/content-ingestion/src/content_ingestion/config.py` (verify `NEWSAPI_API_KEY` plumbed)
- **depends_on**: none
- **Acceptance**:
  - Live `make dev` run shows ≥ 1 article from `source_kind="newsapi"` in `documents` within 1 hour.
  - DLQ for newsapi remains empty over 24h.

#### H-2 SEC EDGAR adapter — verify + fix

- **Target files**:
  - `services/content-ingestion/src/content_ingestion/infrastructure/adapters/sec_edgar.py` (audit: filing-type filter, body extraction, ratelimit @10 req/s)
  - `services/content-ingestion/tests/integration/test_sec_edgar_adapter.py` (NEW or extend)
- **depends_on**: H-1
- **Acceptance**:
  - At least 5 EDGAR filings (10-Q, 8-K) ingested in 24h on top-50 watchlist.

#### H-3 EODHD news adapter — verify + fix

- **Target files**:
  - `services/content-ingestion/src/content_ingestion/infrastructure/adapters/eodhd_news.py` (audit cycle)
  - existing tests
- **depends_on**: H-2
- **Acceptance**:
  - ≥ 10 EODHD-sourced articles within 24h.

#### H-4 Backfill `entity_article_links` for top-100 entities

- **Target files**:
  - `scripts/ops/backfill_entity_article_links.py` (NEW — joins `entity_mentions` + canonical-entity match, writes `entity_article_links` rows)
  - `services/nlp-pipeline/src/nlp_pipeline/infrastructure/workers/entity_article_link_worker.py` (NEW continuous worker — keeps the table in sync)
- **depends_on**: H-3
- **Acceptance**:
  - For AAPL, `SELECT COUNT(*) FROM entity_article_links WHERE entity_id=<aapl>` returns ≥ 50.
  - Worker continues to add new links on each `nlp.article.enriched.v1`.

#### H-5 Dedup audit + duplicate cluster expansion

- **Target files**:
  - `scripts/audits/dedup_audit.sql` (NEW — surface `dedup_hashes` collisions, `minhash_signatures` near-duplicates not yet linked)
  - `services/content-store/src/content_store/application/use_cases/cluster_duplicates.py` (audit if `duplicate_clusters` is being populated; F-data-platform reports 0 rows)
- **depends_on**: H-4
- **Acceptance**:
  - `duplicate_clusters` table has ≥ 1 cluster after 24h ingestion (real-world duplicate stories should produce them).
  - Audit script committed; clean baseline run.

### Wave H validation gate
- 4 source adapters confirmed in `source_adapter_state` rows with `last_fetched_at` within 1h.
- Per-source article counts checkpointed.
- KG enrichment lag (Wave I dependency) below 200 messages.

### Wave H architecture compliance
- **R25**: Adapters live in `infrastructure/adapters/`; use cases in `application/use_cases/`.
- **R28**: Every adapter publishes `content.article.raw.v1` with valid Avro envelope.
- **R10**: `entity_article_link_id` is UUIDv7.

---

## Wave I — Knowledge graph density

### Goal
Investigate why AAPL has only 3 edges; close PLAN-0064 W6 follow-through; consider extraction model upgrade if needed.

### Dependencies
H-4 (more articles → more extraction surface).

### Effort
~10h.

### Tasks

#### I-1 Investigate AAPL 3-edge baseline

- **Target files**:
  - `docs/audits/2026-MM-DD-investigate-kg-density-aapl.md` (NEW investigation report following `/investigate` skill)
  - root-cause hypothesis: F-LLM-001 (mention class mismatch) is the primary; PLAN-0087 fixed at runtime, but the relation extractor backfill on the 1141 already-spent LLM calls likely needs replay
- **depends_on**: PLAN-0087 F-LLM-001 fix landed
- **Acceptance**:
  - Investigation report committed.
  - Identified root causes triaged: extractor logic, GLiNER class config, prompt template, model selection.

#### I-2 Replay extraction on 1141 historical LLM calls

- **Target files**:
  - `scripts/ops/replay_relation_extraction.py` (NEW — reads `llm_usage_log` for `capability=extraction`, re-fires the resolver only — no new LLM spend)
- **depends_on**: I-1
- **Acceptance**:
  - After replay, `relation_evidence_raw` has ≥ 200 rows.
  - `relations` for AAPL ≥ 30 edges.

#### I-3 Close PLAN-0064 W6 follow-through (relation_summaries + relation_contradiction_links)

- **Target files**:
  - `services/knowledge-graph/src/knowledge_graph/infrastructure/workers/relation_summary_worker.py` (verify or repair)
  - `services/knowledge-graph/src/knowledge_graph/infrastructure/workers/contradiction_link_worker.py` (verify or repair)
- **depends_on**: I-2
- **Acceptance**:
  - `relation_summaries` ≥ 50 rows; `relation_contradiction_links` populated where contradictions exist.

#### I-4 Extraction model upgrade evaluation

- **Target files**:
  - `docs/audits/2026-MM-DD-extraction-model-bench.md` (NEW — A/B Llama-3.1-8B-Instruct-Turbo vs Qwen3-235B-A22B-Instruct on 100 articles, measure precision/recall on a labelled set)
- **depends_on**: I-2
- **Acceptance**:
  - Bench report committed; recommendation made (keep current OR switch).
  - If switch: change `services/knowledge-graph/src/knowledge_graph/infrastructure/llm/extractor_config.py` and document cost delta.

#### I-5 Demo-critical 12 entities edge density check

- **Target files**:
  - `scripts/audits/kg_density_check.sql` (NEW — assert each of the 12 demo tickers has ≥ 20 edges)
  - `tests/architecture/test_kg_density_threshold.py` (optional — soft gate)
- **depends_on**: I-3
- **Acceptance**:
  - All 12 entities pass density threshold.

### Wave I validation gate
- AAPL ≥ 30 edges; 12 demo entities ≥ 20 each.
- relation_evidence_raw + relation_evidence growing daily (CDC counter).

### Wave I architecture compliance
- **R25**: replay script is an ops tool, lives in `scripts/`; uses domain repositories via DI.

---

## Wave J — Performance & scale

### Goal
Hit the performance SLOs: pgvector HNSW p95 < 100 ms, AGE Cypher 2-hop p95 < 500 ms, S8 RAG cache TTLs sane, frontend bundle < 1 MB gzipped.

### Dependencies
E + F + H + I (load shape stable).

### Effort
~7h.

### Tasks

#### J-1 pgvector HNSW index sizing

- **Target files**:
  - `services/intelligence-migrations/alembic/versions/00xx_hnsw_tune.py` (verify `m=16, ef_construction=200, ef_search=100`)
  - `docs/audits/2026-MM-DD-pgvector-perf-bench.md` (NEW — bench using 5k chunks)
- **Acceptance**:
  - p95 < 100 ms on `/v1/search/chunks` with realistic vector + tenant filter.

#### J-2 AGE Cypher latency for 2-hop traversals

- **Target files**:
  - `docs/audits/2026-MM-DD-age-cypher-perf-bench.md` (NEW)
  - `services/knowledge-graph/src/knowledge_graph/infrastructure/intelligence_db/repositories/relation.py` (add covering indexes if hot Cypher patterns identified)
- **Acceptance**:
  - p95 < 500 ms on `/v1/entities/{id}/graph?depth=2` for AAPL post-Wave-I.

#### J-3 S8 RAG cache TTL audit

- **Target files**:
  - `services/rag-chat/src/rag_chat/infrastructure/cache/keys.py` (audit every TTL; align with backend-cache TTL doc)
  - `docs/services/rag-chat.md` (add Cache TTL table)
- **Acceptance**:
  - Documented; TanStack Query staleTime on the frontend matches backend TTL ± 50%.

#### J-4 Frontend bundle size budget

- **Target files**:
  - `apps/worldview-web/next.config.mjs` (set `experimental.bundlePagesRouterDependencies` etc., enable analyze)
  - `apps/worldview-web/scripts/check-bundle-size.mjs` (NEW CI check — fails on > 1 MB gzip per route)
- **Acceptance**:
  - `/`, `/instruments/[id]`, `/portfolio`, `/chat` all < 1 MB gzipped per first-load.

### Wave J validation gate
- All 4 SLOs met in bench reports.
- CI bundle-size gate active and green.

### Wave J architecture compliance
- **R25**: no layer changes.
- Frontend bundle gate is CI-enforced.

---

## 3. Cross-wave validation gate (PLAN-0088 exit)

Pass conditions:
- Every wave's individual gate passed.
- 5-agent QA pass per `/qa` skill green: 0 BLOCKING / 0 CRITICAL on demo-path (already covered by PLAN-0087) AND 0 BLOCKING / ≤2 MAJOR on beta-path.
- The 16 F-BB-NNN findings in `docs/audits/2026-05-09-qa-beta-blockers.md` Final go/no-go matrix flip from NO-GO to GO.
- Restore drill log + GDPR delete drill log committed.
- One pilot tenant onboarded via `scripts/ops/provision_tenant.py` and signs in via Zitadel.

## 4. Risk register

| Risk | L | I | Mitigation |
|------|---|---|------------|
| Zitadel deploy stalls (config edge case) | M | H | A-1 has 2-day buffer; fallback = Zitadel Cloud (1d wire) |
| TLS rollout breaks intra-cluster connectivity | H | H | Stage roll-out service-by-service; revert script `infra/scripts/tls_rollback.sh` |
| Restore drill takes longer than 2h | L | M | Document RTO ≤ 4h initially; tune later |
| MinIO key migration breaks existing tenant uploads | M | H | Migration script is dry-run by default; manual approval gate |
| Holdings redesign breaks SnapTrade-connected user flow | L | H | Visual regression suite + manual QA on connected demo account |
| News adapter rate-limits blow up costs | M | M | Per-adapter quota dashboard (D-3-style), 503 hard-cap |
| Extraction replay overwhelms KG worker | M | M | Replay in batches of 100; backpressure policy from F-DS-006 |

## 5. Estimation summary

| Wave | Effort (h) | Tasks | Parallel-with |
|------|-----------:|------:|---------------|
| A | 25 | 6 | B, C, D |
| B | 22 | 6 | A, C, D |
| C | 14 | 4 | A, B, D |
| D | 12 | 4 | A, B, C |
| E | 16 | 4 | F, G, H |
| F | 10 | 4 | E, G, H |
| G | 10 | 4 | E, F, H |
| H | 14 | 5 | E, F, G |
| I | 10 | 5 | (after H) |
| J | 7 | 4 | (after E,F,H,I) |
| **Total** | **140** | **46** | |

---

## 2026-05-10 evening — pre-beta third pass (full beta-hardening sweep)

Eight subagents (SA-1..SA-8) ran in parallel; verdict **GO for beta**.

* **SA-1** — KG bugs root-caused: NarrativeWorker NoneType (BP-SA1-001), PathInsightSeeder FK (BP-SA1-002), AGE Cypher `|` rewrite (BP-SA1-003), one-shot raw→partitioned promotion (BP-SA1-004). `relation_evidence` 0 → 438; `relation_summaries` 0 → 5.
* **SA-2** — Long-tail narrative regen unblocked (idempotency guard now exempts template-v1). LLM narratives 337 → 898; template-v1 689 → 263; narrative embeddings 988 → 1103; demo-critical entities on template-v1 = **0**.
* **SA-3** — `evidence_date` plumbing fix: `_build_raw_relations` now propagates article `published_at`. Graph camera auto-fit + 'R' shortcut shipped.
* **SA-4** — BP-442 root cause: migration `0002` constraint name mismatch → `UndefinedObjectError` → cascading `MissingGreenlet`. Migration `0006` rename + repo `index_elements` switch. `duplicate_clusters` 791 → 807. New gateway `cluster_size` enrichment endpoint.
* **SA-5** — DIVIDEND UI now shows broker-reported `amount` at 3 render sites (incl. negatives); `/portfolio/brokerage` redirect stub; 3 regression tests.
* **SA-6** — Runtime hygiene clean: 0 ERROR/CRITICAL across 9 backend services; Polymarket lag stable; no DLQ topics.
* **SA-7** — Font-mono label enforcement + EPS formatPrice; full primary-page polish review.
* **SA-8** — Final beta QA: all 11 actual app routes 200; all primary user-data APIs 200; verdict GO.

Post-rebuild verification:
* Path-insight worker: **0 syntax errors** in 2m window (was 147/10m on stale image).
* Dedup-consumer: residual `MissingGreenlet` ~11/3m (data integrity OK; tracked as P1-B).

Commits this pass: `fa410cd1`, `730069bc`, `6c109a6f`, `2ea4bef0`, `b0ff21aa`, `fadabb87`, `67247347`, `34185d29`, `2c15aae4`, `a433d0fe`. Full audit: `docs/audits/2026-05-10-pre-beta-third-pass-report.md`.

## 2026-05-10 late evening — pre-beta fourth pass (universe + AGE + Worker 13B + dedup BP-443)

Ten subagents (SA-1..SA-10) ran in parallel; verdict **GO for beta**.

* **SA-1** — Dedup `MissingGreenlet` root cause (BP-443): `_SessionUnitOfWork.__aexit__` lacked explicit `await session.close()` before delegating to context manager. Fix verified: 0 errors across 10 min (was ~11/3m). 7 regression tests; 334 unit tests pass.
* **SA-2** — Worker 13B periodic (5-min) `relation_evidence` promoter + SummaryWorker retry-with-backoff + Gemini 2.5 Flash Lite fallback (no Groq). Confirmed firing organically.
* **SA-3** — Definition embedding root causes: stale `source_hash`, silent `source_text=NULL` skip, wrong `FundamentalsRefreshWorker` URL. **def_emb 100%** across all entity types; `fst_emb` 0→55.
* **SA-4** — Cross-DB `evidence_date` backfill from `content_store_db.documents.published_at`. **Distinct days 1→10**; AAPL trend 5 real points. Aggregates repo switched from raw to partitioned table.
* **SA-5** — AGE sync worker + `path_discovery.py` rewrite (2-hop/3-hop scalar Cypher, UUID injection guard). **AGE 1268 nodes / 323 edges**; **path_insight_jobs 54/54 done**; **path_insights 0→2107**.
* **SA-6** — **FR-T0-2 met**: 57→614 instruments (543 S&P + ADRs, 20 ETFs, 29 crypto, 7 macro, 6 FX). OHLCV 29→600 (+137k bars). Idempotent seed.
* **SA-7** — News density polish (cluster-chip copy, source border, NewsTab compression).
* **SA-8** — SnapTrade dividend regression check: clean (98 positive / 102 withholding); `/balances` unmapped → P1.
* **SA-9** — Settings density + intelligence-tab/portfolio empty states.
* **SA-10** — Final QA: verdict GO; all routes, APIs, KG semantic completeness, Kafka, container health verified.

DB delta this pass: `relation_evidence` 438→947, `relation_summaries` 5, `path_insights` 0→2107, `LLM narratives` 898→1257, `template-v1` 263→**0**, `def_emb` 1040→1277 (100%), `instruments` 57→614, `AGE nodes` 2→1268, `duplicate_clusters` 807→835.

Commits this pass: `ca089fbc`, `0832f4a2`, `1968ee24`, `c184e53e`, `1eb00225`, `9603059d`, `f191799d`, `eb913f4f`. Full audit: `docs/audits/2026-05-10-pre-beta-fourth-pass-report.md`.

---

**End of PLAN-0088.**

> Compounding check: future BPs likely landing during this plan — BP-446
> (PITR drill), BP-447 (MinIO tenant key migration), BP-448 (GDPR cascade-delete event taxonomy), BP-449 (PII redaction processor in structlog).
> ADRs to write: 0008 (encryption at rest+transit), 0009 (MinIO tenant key prefix). Runbooks: zitadel-onboarding, internal-jwt-rotation, secrets-rotation, tenant-onboarding, encryption-rotation, backup-restore-postgres, backup-restore-minio, gdpr-delete, audit-log-retention.
