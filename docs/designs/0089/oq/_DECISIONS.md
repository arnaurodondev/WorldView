---
id: PRD-0089-DECISIONS
title: PRD-0089 Open Questions — Consolidated Decisions Index
status: partially-locked
created: 2026-05-20
last_updated: 2026-05-20
sources: docs/designs/0089/oq/01..10-*.md (6,969 lines investigation)
---

## 🔒 USER-LOCKED DECISIONS — 2026-05-20

### §A DISCUSS-1..12 — all locked

| # | Lock | Side effects |
|---|------|--------------|
| DISCUSS-1 | ROOT default; switcher always visible (incl. when user has 1 portfolio); all portfolios + ROOT shown in switcher | Resolves FU-1.2 (switcher always visible) |
| DISCUSS-2 | **Direct to unified ID — skip phased approach.** Single canonical UUID per tradable security. Name stays `instrument_id` (no rename). KG `canonical_entities.entity_id` for tradable securities EQUALS `instruments.id`. URL form `/instruments/{ticker}` (e.g. `/instruments/AAPL`). Multi-class via dot `/instruments/BRK.B`. Single canonical listing per ticker (portfolio service convention). | Resolves FU-2.1 (no exchange suffix), FU-2.2 (dot for multi-class), FU-2.3 (`instrument_id` kept permanently). Revises §B D-2.1, D-2.2, D-2.3, D-2.8. Migration is now one wave (Wave C in §D) instead of three phases. |
| DISCUSS-3 | Border-radius 0 globally; 10.5px tables / 11px narrative; 20px rows / 18px hyper-dense; 6px cell padding; tiered density. **Hero/page-primary value (portfolio total, etc) = 14px**. | Resolves FU-5.3 (14px hero). Confirms FU-5.1 hybrid font scale. |
| DISCUSS-4 | 4-tier animation taxonomy (data BANNED; affordance ≤100ms; chrome state ≤200ms; indicators allowed) | — |
| DISCUSS-5 | Per-article sentiment on rows; daily aggregate as 30-day sparkline only; NEVER averaged | — |
| DISCUSS-6 | Single `InlineCitationAnchor` primitive across surfaces; AskAiPanel deletes ~310 LOC of duplicate parsing | — |
| DISCUSS-7 | Lazy brief generate: `POST .../generate` → 202 + `job_id`; poll `GET .../generate/{job_id}` at 8s. Rate limit 60/hr/user + 10/hr/entity-global. **Confirmed user-agnostic**: drop `:{user_id}` from public-instrument brief cache key (D-3.2 locked). | Resolves D-3.2 explicit confirmation. |
| DISCUSS-8 | Per-surface tiered density floor (40/100/150/200/250/300) — replaces single 40-cell NFR-1 | — |
| DISCUSS-9 | Watchlist sidebar: zero new endpoints; extend `/v1/watchlists` with `?expand=quotes,sparklines`; sparkline via existing `POST /v1/ohlcv/batch` | — |
| DISCUSS-10 | **SPY only, ALWAYS, including non-US books.** No regional-benchmark auto-pick. | Resolves FU-1.3 (SPY always, no regional auto-pick). |
| DISCUSS-11 | Default chart timeframe **1Y** (was 1D); viewport reset on timeframe change; volume profile NOT re-added in v1 | — |
| DISCUSS-12 | Brief left-2px Bloomberg amber rail (`border-l-2 border-[hsl(var(--accent-ai))]`) — reconciles OQ-D3 + OQ-D20 inconsistency in master PRD | — |

### §B revisions forced by DISCUSS-2

| Original | New |
|----------|-----|
| D-2.1 Phase 1 v1: `/instruments/{ticker}` URL routing | **REVISED**: ship URL routing as part of unified Wave C, not a separate phase |
| D-2.2 Phase 2 v1.1: introduce internal `security_id` UUID | **REJECTED**: `instrument_id` is the canonical name forever |
| D-2.3 Phase 3 v2: deprecate dual ID model | **MERGED into Wave C** — done in one shot |
| D-2.8 Keep `instrument_id` "in v1"; rename to `security_id` in v1.1 | **REVISED**: keep `instrument_id` permanently. ADR-F-12 is wrong; Kafka schema M-017 (entity_id = instrument_id for tradable securities) is correct. Update ADR-F-12 in Wave C. |

### §C — implicitly resolved follow-ups (from DISCUSS locks)

- **FU-1.2** — switcher always visible (even with 1 portfolio) — LOCKED
- **FU-1.3** — SPY always, no regional auto-pick — LOCKED
- **FU-2.1** — `/instruments/AAPL` (no exchange suffix in URL) — LOCKED
- **FU-2.2** — `/instruments/BRK.B` (dot for multi-class) — LOCKED
- **FU-2.3** — keep `instrument_id` name permanently — LOCKED
- **FU-5.3** — 14px for hero/page-primary numbers (portfolio total value) — LOCKED

### §C — 72 follow-ups resolved across 5 FU agents (2026-05-20)

Full per-row reasoning lives in `docs/designs/0089/oq/fu/A..E-*.md`. The
matrix below surfaces the headline answers; rows flagged ⚠️ are the ones
agents themselves marked as "user may push back".

#### Cluster 1 — Portfolio (5 rows)
| FU | Resolution |
|----|-----------|
| ⚠️ **FU-1.1** | ROOT label = **"All Portfolios"** in switcher; "All Portfolios — $X.XM" in header. Rejected "Total Portfolio" (collides with IBKR NLV term), "ROOT" (DB lingo leak), "My Book" (buy-side jargon) |
| FU-1.4 | Single base USD v1; original-CCY label on holding rows non-authoritative. True multi-CCY books → v1.1 |
| FU-1.5 | Demo data tagging: opaque "DEMO" badge in switcher (no page watermark) |
| FU-1.6 | Mobile (v1.1): stack-each-strip with 360px min-width guard. True responsive = v2 |
| FU-1.7 | `currency_breakdown` ships in v1 contract as `[{currency:"USD",weight_pct:100}]` (forward-compat) |

#### Cluster 2 — Entity/Instrument ID (2 remaining; the other 3 locked by DISCUSS-2)
| FU | Resolution |
|----|-----------|
| FU-2.4 | `ticker_aliases` retention: **forever**, append-only (Bloomberg keeps META←FB visible 13y later) |
| FU-2.5 | ID-unification cutover: **new-tenant cutover only**; existing tenants opt-in re-sync via SnapTrade replay |

#### Cluster 3 — AI brief + chat (7 rows)
| FU | Resolution |
|----|-----------|
| FU-3.1 | Brief token-streaming **deferred** — BriefParser needs full text (incremental markdown parsing breaks on section/citation collisions). 8s polling acceptable |
| FU-3.2 | Force-regenerate endpoint → v1.1 (per-entity rate-limit already gives fresh-enough briefs) |
| FU-3.3 | Feedback in AskAiPanel: **yes** but as **binary thumbs** (new `ChatAnswerFeedback`, not the 5-star `BriefRating`) |
| FU-3.4 | `[brief:AAPL]` citations in chat: **yes**, as `[BRF]` badge alongside `[SEC]/[EARN]/[NEWS]/[KG]` |
| FU-3.5 | Pin endpoint → v1.1 (D-3.8 already hides button v1; backend bundled later) |
| FU-3.6 | Brief age: **hybrid** — relative on Quote/Financials banners with `title=` absolute UTC tooltip; absolute mono on Intelligence StructuredBrief footer |
| FU-3.7 | Inflight handoff: **named-cache-promise via SETNX gate**. User B's POST collides on `rag:v1:brief_inflight:{entity_id}`, gets back A's `job_id`, polls same route |

#### Cluster 4 — Watchlist (7 rows)
| FU | Resolution |
|----|-----------|
| FU-4.1 | `freshness_status` on `/v1/quotes/batch` — **confirmed in code** (`price_snapshot.py:35`, `quotes.py:98-115`, `market.py:769-815`). Zero-backend-cost |
| FU-4.2 | "+N more" link target: **fix to `/watchlists`** (`WatchlistPanel.tsx:184,244` is the stale link) |
| FU-4.3 | IndexStrip manifest: SPY/QQQ/IWM/DIA/VIX/TLT/**^TNX**/GLD/USO/BTC-USD. DXY hidden v1 (no EODHD feed); VIX non-negotiable |
| ⚠️ **FU-4.4** | Watchlist add hotkey: **`w` in watchlist scope** + global `Shift+W` (mirrors Shift+A for alerts). `mod+w` keeps browser-close |
| FU-4.5 | Quote refresh: **polling at 30s** (current implementation correct; SSE not warranted at EOD-bounded freshness) |
| FU-4.6 | Drag-to-add ticker: **v1.1** (cost of HTML5 DnD across every ticker source not justified; +button + hotkey + right-click already cover 3 paths) |
| FU-4.7 | Multi-row tiled watchlists: **out of scope** (sidebar real-estate too narrow; full `/watchlists` page for comparison) |

#### Cluster 5 — Design system fine-tuning (9 rows)
| FU | Resolution |
|----|-----------|
| FU-5.1 | Hybrid 10.5px tables / 11px narrative — **confirmed** |
| FU-5.2 | Dropdown/Popover radius: **0px everywhere**, no exception (Bloomberg HELP overlays precedent). Fallback if QA fails: 1px `--border-strong` accent (NOT radius) |
| FU-5.4 | Accept `--border-strong` (#37373B) + `--border-subtle` (#1E1E22) — calibrated against `--card` (#111113), not canvas |
| FU-5.5 | `data-table-grid` v1 scope: **7 surfaces** (Screener, Holdings, Tx Ledger, Financials FlatMetricsGrid, Watchlist, Workspace data panels, Peer Comparison). Excluded: articles, alerts, chat, brief, intelligence events |
| FU-5.6 | Sparkline color: **trend-tinted** (3-state positive/negative/flat), NOT yellow (burns accent), NOT muted (loses signal) |
| FU-5.7 | Shadow purge: **remove from `tailwind.config.ts`** + arch-test ban + delete CSS reset (~0.4KB savings) |
| FU-5.8 | Group divider: **hairline `border-t border-border-subtle`** — no gap void (saves 48px on 6-group Holdings) |
| FU-5.9 | Accept 7 new arch-test forbidden regexes (with 2 clarifications: row-heights needs `role="row"` lookahead; hover-bg needs PR-E migration allowlist) |
| FU-5.10 | **7 small PRs A-G** (per the original plan); hotspots quantified — 633 rounded sites across 120 files. Top hotspots: `components/ui` (80), `app/(app)` (76), `components/instrument` (64), `components/alerts` (60), `components/portfolio` (55) |

#### Cluster 6 — Graph + Intelligence (12 rows)
| FU | Resolution |
|----|-----------|
| FU-6.1 | Cancellation: **forward TanStack `signal` into `getEntityGraph(..., {signal})`** (gateway client currently ignores upstream signal — `GraphColumn.tsx:54-67`). ~5 LOC fix |
| ⚠️ **FU-6.2** | Description fetch: **first-hover, 200ms debounce** + immediate fetch on `onNodeSelect`. May push to eager-prefetch if QA reveals lag |
| FU-6.3 | Contradiction tie-break: **highest `strength`**; on tie, most recent `detected_at`; banner is single-slot |
| FU-6.4 | WS drop visual: dot-only for green↔amber; toast on red + every 30s while red |
| FU-6.5 | URL-hash node stickiness: **v1.1**, mechanism `#node=<entity_id>` |
| FU-6.6 | Path label format: reuse `RelationsList.tsx:114-180` 3-row format (source→target / relation_label·weight / relation_summary) — already implemented |
| FU-6.7 | Narrative history: closed by default, `History (N)` chip in header (Tier-2 ≤200ms expand) |
| ⚠️ **FU-6.8** | Graph layout: **ForceAtlas2 default; no user-selectable v1**. Per-relation-type layout hint = v1.1 PRD candidate |
| FU-6.9 | Playwright perf fixture sizes: **200 / 500 / 1000 nodes**; budget < 1500ms p95 at 1000 |
| ⚠️ **FU-6.10** | Telemetry sampling: **100% v1** (low volume); revisit at 10k DAU |
| FU-6.11 | Path query: **cap top-20 portfolio entities by `current_value_usd` DESC** server-side; UI copy "Showing paths to your 20 largest holdings" |
| FU-6.12 | Edge bundling: **v1.1** confirmed (sigma.js doesn't bundle natively; type-filter chips + depth slider cover v1) |

#### Cluster 7 — Chart + technicals (7 rows)
| FU | Resolution |
|----|-----------|
| FU-7.1 | Brief border = Left-2px `border-l-2 border-[hsl(var(--accent-amber))] rounded-none` — confirmed; reconcile master PRD OQ-D20 |
| FU-7.2 | Default chart 1Y — confirmed (`OHLCVChart.tsx:41` single-LOC change) |
| FU-7.3 | Pivot cache TTL: 5min market hours / 60min after-hours |
| FU-7.4 | IPO baseline: **`—` em-dash** with hover tooltip `Insufficient history — listed YYYY-MM-DD`; NO "since IPO Xd" copy |
| ⚠️ **FU-7.5** | Manual peer override: **no v1** (EODHD sector cohort sufficient); move to v1.1 if telemetry shows >30% peer dismissal |
| FU-7.6 | Camarilla pivots: **v2** (niche intraday signal; analyst/PM persona doesn't need it; Classic-only v1) |
| FU-7.7 | Volume profile overlay: **do NOT re-add v1** (DISCUSS-11 lock confirmed) |

#### Cluster 8 — News + sentiment (8 rows)
| FU | Resolution |
|----|-----------|
| FU-8.1 | Topic taxonomy: **curated 24-tag whitelist** (GICS sub-industries + 6 macro buckets) in `libs/contracts/topics.py`; LLM classifies into buckets (free-text creates synonym hell) |
| FU-8.2 | HoverCard a11y: keyboard trigger via `Enter` on focused row; `Esc` closes; doesn't conflict with j/k navigation |
| FU-8.3 | Filter persistence on entity nav: **split by type** — sentiment + time-range carry over (intent), publisher + topic reset (ticker-specific) |
| FU-8.4 | Cluster modal: explicit click only (no auto-open at N+ similar) |
| FU-8.5 | Sentiment sparkline tooltip: value + article count |
| FU-8.6 | Sentiment-history endpoint: keyed by `instrument_id` (DISCUSS-2: identical to entity_id for tradables) |
| FU-8.7 | `summary_excerpt` cap: **280 chars** (Twitter-length; fits 320px hovercard from FU-10.7) |
| FU-8.8 | Article reading list / saved-for-later: **cut to v2** (no validated demand) |

#### Cluster 9 — Secondary pages (6 rows)
| FU | Resolution |
|----|-----------|
| FU-9.1 | Disabled-filter click telemetry: 100% sample rate (bounded volume) |
| FU-9.2 | Workspace crosshair mixed-timeframes: sync both axes; snap time to nearest candle on receiving chart |
| FU-9.3 | Bulk-snooze: same scope as bulk-ack (Shift+S all critical); preserves local-only ACK fallback |
| FU-9.4 | Workspace `?config=` URL: **layout-only** (privacy + URL length); no user-data embedded |
| FU-9.5 | Predictions drawer on mid-view resolution: final outcome banner + read-only state |
| FU-9.6 | Alerts snooze duration: fixed list — 1h / 4h / 1d / 1w / forever (no custom time picker v1) |

#### Cluster 10 — Interaction nuances (10 rows)
| FU | Resolution |
|----|-----------|
| FU-10.1 | j/k coverage: **opt-in via `data-jk` attribute** on lists (no global hijacking of text inputs) |
| FU-10.2 | Touch hovercard: long-press 500ms (Worldview is desktop-first but accommodates iPad) |
| FU-10.3 | Toast position: top-right (Sonner default) |
| FU-10.4 | Streaming chat flash duration: 600ms |
| FU-10.5 | Esc cascade: **Bloomberg cascade** (chord buffer → modal → drawer → popover → search → page-reset), NOT panic-clear-all |
| FU-10.6 | Spinner color: **muted-foreground grey default**; primary yellow reserved for AI surfaces only |
| FU-10.7 | Tooltip width: **tiered — 240px tooltip / 320px hovercard** (wider for 280-char `summary_excerpt`) |
| FU-10.8 | Skeleton color: `bg-muted` (no new `--skeleton` token; reduces palette complexity) |
| FU-10.9 | Streaming text weight: **stays `font-normal`** throughout (weight change = layout shift = Tier-0 violation) |
| FU-10.10 | Empty-state CTA: primary for blocking states (brokerage connect); ghost for informational |

---

### §G — Backend additions consolidated (post-FU)

Total minor adds across all clusters (most ship with their wave; ~10 endpoints total):

| Service | Addition | Wave |
|---------|----------|------|
| S1 portfolio | `currency_breakdown: [...]` on `ExposureResponse` (v1 forward-compat) | D |
| S1 portfolio | `/portfolios/{id}/top-movers?period=` (v1.1) | N |
| S1 portfolio | `/portfolios/{id}/twr`, `/risk-metrics?include=drawdown_series`, `/attribution`, `/holdings/{id}/value-history` (v1.1) | N |
| S2 market-data | `/instruments/{id}/peers`, `/intraday-stats`, `/multi-period-returns`, `/price-levels` (B-Q-1..4) | F |
| S3 content-store | `summary_excerpt varchar(280)` column on `document_source_metadata` | (with cluster 8) |
| S6 nlp-pipeline | `topics` field populated from 24-tag whitelist | (with cluster 8) |
| S7 KG | `/entities/{id}/paths` with `target_entity_id[]` filter (v1.1) | N |
| S7 KG | `path_insights.terminal_entity_id` column (v1.1) | N |
| S7 KG | `entity_graph_snapshot` nightly snapshot table (v1.1) | N |
| S7 KG | `max_neighbors_per_node` query param (v1) | E (Intelligence wave) |
| S8 rag-chat | `POST /v1/briefings/instrument/{id}/generate` lazy endpoint pair (DISCUSS-7) | E |
| S8 rag-chat | `POST /v1/briefings/instrument/{id}/regenerate` (v1.1) | N |
| S8 rag-chat | `POST /v1/chat/{id}/feedback` (binary thumbs for AskAiPanel — FU-3.3) | M (chat polish) |
| S8 rag-chat | `[BRF]` citation kind support (FU-3.4) | M |
| S8 rag-chat | Drop `:{user_id}` from public-instrument cache key (DISCUSS-7) | E |
| S9 gateway | URL ticker→UUID resolution shim (DISCUSS-2) | C |
| S9 gateway | Proxy passthroughs for all new endpoints | per wave |
| S10 alert | `display_trigger` field on alert payload | L |
| (cross) | `intelligence-migrations` ticker_aliases table (DISCUSS-2 + FU-2.4) | C |
| (cross) | `tailwind.config.ts` purge shadow + radius classes | A |

### §H — Push-back-flagged rows — USER-LOCKED 2026-05-20

| # | Final lock |
|---|------------|
| FU-1.1 | **"All Portfolios"** (agent recommendation accepted) |
| FU-4.4 | **`mod+shift+w`** (two-handed but unambiguous; user chose alternative) |
| FU-6.2 | **Eager prefetch on graph load** — fetch every node's description as soon as the graph data arrives so hover is instant. Bulk endpoint `POST /v1/entities/details` keyed by `entity_id[]` to avoid N+1; backend cost ~1 round trip per graph fetch |
| FU-6.8 | **User-selectable graph layout in v1** — dropdown in `GraphToolbar` with options: ForceAtlas2 (default), Circular, Hierarchical (for supply-chain views). Per-user preference persisted to localStorage |
| FU-6.10 | 100% sampling (agent recommendation accepted) |
| FU-7.5 | Manual override deferred (agent recommendation accepted) |

---

### §I — 🚨 PLATFORM OPERATIONAL CONSTRAINT (USER DIRECTIVE 2026-05-20)

**No real platform instance is running. There is no production data, no
live users, no backfill required anywhere.**

This single constraint massively simplifies the implementation:

| Concern | Without constraint | With this constraint |
|---------|--------------------|-----------------------|
| **Entity ID unification (DISCUSS-2)** | Phased migration with dual-id period, in-place ID rewrites, brokerage-sync replay (FU-2.5 conservative) | **Drop and recreate seed data** — single migration, no compat window, no aliases needed for "old IDs in cached briefings" |
| **`ticker_aliases` (FU-2.4)** | Forever-retention for archived research / broker statement reconciliation | **Empty table; no historical aliases to backfill** — feature exists for future ticker changes only |
| **Brokerage-sync timing (FU-2.5)** | New-tenant cutover only; existing tenants opt-in re-sync | **N/A — no existing tenants. Wipe + replay from SnapTrade on every dev cycle.** |
| **Alembic migrations** | Each schema change needs server_default + backfill plan | **Schema-only migrations; no data migration logic** |
| **`server_default` on new NOT NULL columns** | Required for R5 forward-compat | **Still added (it's free) but no backfill SQL needed** |
| **Multi-tenant data partitioning concerns** | Existing tenant data isolation | **Single dev tenant only; ROOT portfolio is per-user but only one user exists** |
| **Schema-version compatibility** | Old clients reading new schemas | **Frontend + backend ship together always** |
| **Cache invalidation policy** | Stale briefs need TTL/event-driven refresh | **`docker compose down -v && up` is the canonical reset; no need for surgical cache busts** |
| **Outbox/Kafka topic schema evolution** | Forward-compat required (R5) | **R5 still honoured for hygiene but blast radius is zero** |
| **PRD-0089 Wave C (ID unification)** | 8-12 engineer-days incl. migration playbook | **3-5 engineer-days** — schema migration + seed rewrite + frontend URL routing |
| **`/runbooks/instrument-id-unification.md`** | Required artefact from FU-2.5 | **Not required** — pin a note in the migration commit instead |

**Codify in master PRD frontmatter:**
```yaml
platform_state: pre-production
no_backfill: true
```

**Applies to every wave going forward** until a production instance exists.

---

---

## ✅ NEXT STEPS WHEN DOC IS FULLY LOCKED

1. Flip `docs/specs/0089-platform-page-redesign.md` frontmatter `status: draft` → `status: active`
2. Update `docs/plans/TRACKING.md`: change PRD-0089 from "draft" / "OQ-B1..B5 user decision" to "active" / "ready for /plan"
3. Update master PRD §14 to reference this DECISIONS doc as the canonical answer source
4. Run `/plan` to decompose into `docs/plans/0089-platform-page-redesign-plan.md` (16 waves per §D)
5. Run `/implement-ui` per wave with cherry-pick + commit discipline (proven on PLAN-0090)

---



# PRD-0089 — Consolidated Decisions Index

> **What this is.** After 10 investigation agents covered ~60 open questions
> across the 11 design docs, this file rolls every recommendation up so you
> can review option-by-option. **Default-accept** any row you don't react
> to — silent rows lock at the recommendation as soon as you sign off the
> doc. **Push back** on any row by replying with its ID.

## Reading guide

- **Locked** — agent confirmed, no real ambiguity, lock unless user objects
- **Discuss** — the 12 high-stakes decisions that warrant a conversation
- **Follow-up** — 70+ smaller questions the agents themselves raised; we'll
  resolve in the same conversation but they aren't gating

---

## §A — Cross-cluster architectural decisions (the big ones)

These touch multiple clusters; locking them first unblocks everything else.

### DISCUSS-1 · Aggregated household view as the default landing portfolio (C1)
- **User leaning:** "show total portfolio (all positions) with the ability to switch"
- **Discovery:** the backend ALREADY has `PortfolioKind.ROOT` (PLAN-0046),
  auto-provisioned per user, with aggregated holdings + exposure + daily
  snapshots all working. Frontend types/api.ts already declares the kind.
- **Recommendation:** Default to ROOT on Dashboard and Portfolio Overview;
  show portfolio switcher chip (`ROOT ▾`) in the page header. Single-portfolio
  drilldown via the switcher.
- **Cost:** Minimal — backend already there; ~40 LOC frontend.
- **Open knobs** (your call):
  - **ROOT display name**: "Total Portfolio" / "All Portfolios" / "ROOT" / "My Book"?
  - When user has exactly 1 portfolio, do we still show the switcher (`ROOT ▾`) or hide it?

### DISCUSS-2 · Entity/instrument ID unification path (C2)
- **User leaning:** "standardize entity and instrument id, enable ticker-based querying"
- **Discovery:** two contradictory architectural invariants exist in the
  codebase right now — ADR-F-12 says they MUST be distinct, Kafka schema
  M-017 says they MUST be equal. Production outbox honors M-017; seed data
  honors ADR-F-12. This is a latent bug, not a design preference.
- **Recommendation:** **Option D — Phased hybrid**
  - **Phase 1 (5 days, v1):** Frontend URLs flip to `/instruments/{ticker}`.
    Gateway adds a ticker→UUID resolution shim. Zero backend ID changes.
    Fixes the depth-3 KG timeout in Intelligence tab (same root cause).
  - **Phase 2 (v1.1):** Backend introduces a single `security_id` as the
    canonical UUID. `canonical_entities.entity_id` becomes the system of
    record. Partial UNIQUE on `(upper(ticker), exchange)` so ticker→id is 1:1.
  - **Phase 3 (v2):** Deprecate the dual-id model; reconcile ADR-F-12 with M-017.
- **Open knobs:**
  - URL form for cross-exchange tickers: `/instruments/AAPL` or `/instruments/AAPL.US`?
  - Multi-class shares: `/instruments/BRK.B` or `/instruments/BRK-B`?
  - Internal field name: `security_id` vs `asset_id` vs keep `instrument_id`?

### DISCUSS-3 · Design system overhaul — sharp corners, tighter density (C5)
- **User leaning:** "smaller fonts, smaller padding, more straight lines, NO rounded borders"
- **Audit findings:**
  - 475 sites use `rounded-[2px]` + 28 sites use `rounded-md/lg/xl/sm` — all flip to 0px
  - 603 `text-[10px]` + 554 `text-[11px]` sites today — body text already aggressive but tables can drop to 10.5px
  - 96 `h-[22px]` row sites — drop to 20px standard, 18px hyper-dense
  - Existing architecture test already bans `rounded-[Npx≥3]`; one-line extension bans all `rounded-md/lg/xl/sm`
- **Recommendation:**
  - **Border radius: 0px everywhere** for rectangles. `rounded-full` retained for dots/avatars only.
  - **Body text**: hybrid — 10.5px inside `data-table-grid` containers, 11px in narrative/UI.
  - **Row height**: 20px standard (was 22px), 18px hyper-dense (transactions/screener results).
  - **Cell padding**: 6px (was 8px).
  - **Two new tokens**: `--border-strong` (#37373B for cell grids), `--border-subtle` (#1E1E22 for row dividers).
  - **Density floor (NFR-1)**: replace single 40-cell rule with tiered floors per surface
    (Header strip 40 / Quote 100 / Intelligence 100 / Dashboard 200 / Financials 150 / Portfolio 250 / Screener 240).
  - Migration: 7 small PRs, ~17h mechanical + 1 day visual QA, ~1800 sites across ~120 files.
- **Open knobs:**
  - Hybrid 10.5/11px font scale (agent-recommended) vs uniform 10.5px everywhere?
  - Should DropdownMenu / Popover keep ANY radius for visual separation, or 0px there too?
  - Hero font for "page primary number" (e.g. portfolio total value) — 14px or 16px?

### DISCUSS-4 · Animation policy revision (C10)
- **Current NFR-6:** "No animations on data surfaces"
- **Discovery:** the literal reading is already inconsistent with what the
  11 design docs specify (chat token streaming, brief regenerate spinner,
  alert flash, accordions expand, popovers fade). NFR-6 needs a more
  precise definition or it'll be argued in every PR.
- **Recommendation: 4-tier taxonomy**:
  - **Tier 0 — Data animation: BANNED.** No transition on numeric values, chart bar heights, sparkline data, table row positions, layout-shift props (width/height/max-h).
  - **Tier 1 — Affordance (hover/focus): allowed ≤100ms.** Color-only transitions on hover/focus. No layout/transform.
  - **Tier 2 — State chrome (open/close/expand): allowed ≤200ms.** Popovers, dropdowns, accordions, modal mount/unmount.
  - **Tier 3 — Indicator (loading/streaming): allowed.** Spinners, skeleton shimmer (if used), chat token streaming, brief generate progress.
- **Cost:** doc-only change to NFR-6 wording + 8 architecture tests (animation-policy, motion-safe-wrapper, etc.) + 4 Playwright specs.

### DISCUSS-5 · Sentiment dot source policy (C8)
- **Discovery:** two sentiment signals exist in completely different services
  (per-article LLM-scored from S6 vs daily EODHD aggregate from S3, no cross-reference)
- **Recommendation:** per-article `RankedArticle.sentiment` drives dots on
  article rows; daily aggregate `daily_sentiments` powers a 30-day sparkline
  on entity overview only. NEVER averaged together.
- **Cost:** sparkline endpoint deferred to v1.1 (1 new endpoint, ~1 day).

### DISCUSS-6 · Single canonical citation primitive (C3)
- **Discovery:** AskAiPanel reimplements citation parsing (~310 LOC) duplicating
  MessageBubble's working implementation.
- **Recommendation:** unify into one `<InlineCitationAnchor>` primitive with
  density prop (terminal/compact/brief-footer). AskAiPanel deletes its parsing
  and consumes the primitive. Brief, chat, news rows all use the same `[cN]`
  hovercard treatment.
- **Cost:** ~310 LOC deletion + small refactor. Pure consolidation; no API surface change.

### DISCUSS-7 · Lazy AI-brief generation contract (C3)
- **OQ-B4 in master PRD**
- **Recommendation:** `POST /v1/briefings/instrument/{id}/generate` → 202
  with `job_id`; poll `GET /v1/briefings/instrument/{id}/generate/{job_id}`
  every 8s until 200 or terminal. Rate limit: 60/hr/user + 10/hr/entity-global.
  Drop `:{user_id}` from cache key (briefs are user-agnostic for public instruments).
- **Cost:** Wave-2 backend work (~3 days S8: 1 use case + 2 routes + Prometheus metrics).
  V1 ships with `Generate brief` CTA that calls the new endpoint OR falls back to
  showing whatever's cached. No degraded UX if endpoint isn't ready yet.

### DISCUSS-8 · Density floor (NFR-1) — raise from 40 to tiered? (C5)
- **OQ-B5 in master PRD**
- **Recommendation:** Replace single 40-cell rule with per-surface floors:
  - Header strip: 40 (unchanged)
  - Quote / Intelligence: 100
  - Financials / Dashboard: 150-200
  - Portfolio Overview / Screener: 240-280
  - Workspace (multi-panel): 200+
- **Cost:** Playwright enforcement in CI; no code change needed for v1 since agents already overshot.

### DISCUSS-9 · Watchlist endpoint expansion strategy (C4)
- **OQ-B2 in master PRD**
- **Discovery:** zero new endpoints needed — existing `POST /v1/ohlcv/batch`
  already supports 50-symbol-cap sparkline fetch, and `freshness_status` is
  already on batch quotes.
- **Recommendation:** sidebar calls `/v1/watchlists/{id}/snapshot` (extend list
  endpoint with `?expand=quotes,sparklines` query param) — 1 round trip per
  active watchlist switch. Cache: 5-min stale, 30-min stale-while-revalidate.

### DISCUSS-10 · ROOT portfolio benchmark policy (C1)
- **Recommendation:** v1 ships SPY-only with a clear "benchmark: S&P 500" label.
  Add `benchmark_ticker` column on `portfolios` for v1.1 user-selectable benchmark
  (QQQ, R2K, sector ETFs, custom ticker).
- **Open knobs:**
  - For non-US books, should we auto-pick a regional benchmark (EWG, EWJ) or stick with SPY?

### DISCUSS-11 · Default chart timeframe and viewport behavior (C7)
- **Current:** 1D default; viewport resets to "most recent" each load
- **Recommendation:** Default to **1Y** (Bloomberg/TradingView triage default).
  Viewport resets on timeframe change (preserves BP-376 scroll-to-1985 fix).
  Volume profile overlay NOT re-added in v1 (was removed in PLAN-0090 T-B-01;
  Bloomberg has it, Finviz doesn't, the user didn't ask for it back).

### DISCUSS-12 · Brief left-rail accent color (C3 + C7)
- **PRD inconsistency surfaced:** OQ-D3 says "Top-only 1px", OQ-D20 says "Top-only 1px",
  C7 recommends "Left-2px Bloomberg amber rail"
- **Recommendation:** Reconcile to **Left-2px `border-l-2 border-[hsl(var(--accent-ai))]`** — the iconic Bloomberg rail. Top/right/bottom bands removed (saves 4-6px of chrome per surface).

---

## §B — Locked decisions (per-cluster — silent acceptance unless you push back)

### Cluster 01 — Portfolio model (20 decisions, all locked)
- D-1.1 ROOT is default landing; chip in header shows `ROOT ▾`
- D-1.2 Switcher dropdown lists all portfolios + ROOT label
- D-1.3 Empty state when no brokerage AND no portfolios: full-page "Connect brokerage" CTA (no demo data fallback)
- D-1.4 Demo data only renders when user explicitly opens a demo portfolio
- D-1.5 Day P&L pre-market: prior-close basis; hover tooltip clarifies "(since prev close)"
- D-1.6 Mobile collapse: deferred to v1.1 (Out of scope confirmed)
- D-1.7 Brief diff: against last-seen, "N new since {date}" copy
- D-1.8 Top-contributors backend endpoint (`/portfolios/{id}/top-movers`): v1.1 backend; v1 client-side day-only
- D-1.9 Sharpe/vol/drawdown: v1 hides on overview (avoid stale math); ships on Analytics tab via client-side compute from value-history
- D-1.10 Currency exposure: top-2 inline + `+N more` chip + popover for full
- D-1.11 Sector taxonomy: GICS strings; unknown bucket = "OTHER"
- D-1.12 Performance chart height: 120px default; "tall mode" deferred to v1.1
- D-1.13 Sparkline perf: single-path SVG per row (already designed)
- D-1.14 Period-return chip in header: locked to chart period (same selector)
- D-1.15 Excess-return colour: ALWAYS coloured (Bloomberg precedent)
- D-1.16 Holding contribution chart series: contribution-to-portfolio (most informative on this page)
- D-1.17 Custom period picker: shadcn `Calendar` component (consistent with rest of app)
- D-1.18 Running balance: ship column with "Approximate" tooltip; backend exact-balance endpoint v1.1
- D-1.19 Attribution time aggregation: TWR with cash-flow weighting (S1 owner decision)
- D-1.20 CSV importer: scope to transactions + lots; full CSV importer = separate PRD

### Cluster 02 — Entity/instrument ID (8 decisions)
- D-2.1 Phase 1 v1: `/instruments/{ticker}` URL routing (gateway shim resolves)
- D-2.2 Phase 2 v1.1: introduce internal `security_id` UUID, unify outbox/topic keys
- D-2.3 Phase 3 v2: deprecate dual ID model entirely
- D-2.4 Class shares: `/instruments/BRK.B` (dot separator, matches Bloomberg)
- D-2.5 Multi-exchange: prefer `/instruments/AAPL` (canonical-listing) by default; explicit `?exchange=US` for ambiguity
- D-2.6 Ticker collision: handle via `(upper(ticker), exchange)` partial UNIQUE; surfaces as 409 if duplicate
- D-2.7 Ticker change events (META ← FB): maintain `ticker_aliases` table; old URL 301-redirects to canonical
- D-2.8 Internal field name: keep `instrument_id` in v1 (avoid mass rename); rename to `security_id` in v1.1

### Cluster 03 — AI brief + chat (17 decisions)
- D-3.1 Lazy generate endpoint pair as in DISCUSS-7
- D-3.2 Drop `:{user_id}` from public-instrument brief cache key
- D-3.3 Multi-day diff: `since_brief_id` param, 7-day cap, "what changed since {date}" summary
- D-3.4 Unified `InlineCitationAnchor` primitive (3 density modes)
- D-3.5 Brief AI rail: `border-l-2 border-[hsl(var(--accent-ai))]`
- D-3.6 Surface `intent`/`provider`/`latency_ms` as analyst-facing tags in chat (not debug-only)
- D-3.7 Primary token (yellow) as flash indicator on streaming
- D-3.8 Pin behind feature flag in v1 (no backend support yet); ship in v1.1
- D-3.9 Citation dedup: `[c3 · 2×]` when same source cited twice
- D-3.10 `⌘\` reserved for chat ContextRail collapse (no AskAiPanel collision verified)
- D-3.11 `NarrativeHistoryDisclosure` accordion in StructuredBrief footer
- D-3.12 Brief token-streaming: defer (polling at 8s acceptable for now)
- D-3.13 Brief diff badge: integrate into existing MorningBriefCard, not new component
- D-3.14 Brief generate rate-limit display: small "10/hr remaining" chip on the Generate button
- D-3.15 Empty-brief copy: "No brief yet — Generate"
- D-3.16 Cached-brief age: relative ("3h ago") + tooltip absolute ("2026-05-20 14:32")
- D-3.17 Contradiction surfacing: D-6.5 in C6 (banner only when strength ≥ 0.85 + polarity_delta ≥ 0.7)

### Cluster 04 — Watchlist (8 decisions)
- D-4.1 IndexStrip: swap USO → ^TNX (one rates ticker per Bloomberg precedent)
- D-4.2 Sparkline: `POST /v1/ohlcv/batch` with `timeframe=5m, limit=78` (78 bars = full trading day)
- D-4.3 Freshness dot: server-driven `freshness_status` enum (not client timer)
- D-4.4 Sidebar auto-collapse < 1280px: NO; show banner suggesting `Cmd+B`
- D-4.5 Section dividers: hairline `border-t border-border` + 4px padding (not extra gap)
- D-4.6 Add-flow: modal (480×360) via `+` button OR `mod+w` hotkey OR right-click on existing
- D-4.7 Multi-watchlist switcher: dropdown chip in header + `Alt+[/]` cycle
- D-4.8 Watchlist sharing: deferred to v2

### Cluster 05 — Design system (11 decisions)
- D-5.1 Body text: hybrid — 10.5px in `data-table-grid`, 11px elsewhere
- D-5.2 Cell padding: 6px (was 8px)
- D-5.3 Row height: 20px standard, 18px hyper-dense
- D-5.4 Border radius: 0px globally for rectangles; `rounded-full` only for dots/avatars
- D-5.5 Two new color tokens: `--border-strong` (#37373B), `--border-subtle` (#1E1E22)
- D-5.6 Hover: `.row-hover` utility (color-only ≤100ms, no layout shift)
- D-5.7 Focus ring: 3-tier (inset hairline T1 for tables, ring-1 T2 for inputs, ring-2 T3 for chrome)
- D-5.8 Animation policy: per DISCUSS-4 4-tier taxonomy
- D-5.9 Cell-grid borders: opt-in via `data-table-grid` attribute (not default; controlled rollout)
- D-5.10 Density floor: tiered per DISCUSS-8
- D-5.11 Architecture test extension: 7 new forbidden regexes (rounded-md, rounded-lg, rounded-xl, rounded-sm, ring-2 on dense rows, transition-all, duration-200+ on data surfaces)

### Cluster 06 — Graph + intelligence (18 decisions)
- D-6.1 Default depth: **2** (depth 1 too shallow, depth 3 too slow)
- D-6.2 Depth-adaptive timeout: 1500ms@d1 / 4000ms@d2 / 8000ms@d3
- D-6.3 WS dot: single global, sustained drop > 5s only
- D-6.4 Contradiction severity: client-derived from S7 `strength` field — HIGH≥0.75 / MED 0.55–0.74 / LOW<0.55
- D-6.5 Contradiction banner: only when `strength≥0.85 AND polarity_delta≥0.7` (rare/high-signal)
- D-6.6 Path insights: always visible top-3 in right rail (text list v1; visual highlight v1.1)
- D-6.7 Narrative history: collapsed `Accordion`, no version diff in v1
- D-6.8 Node selection sticky within tab; cleared on entity OR tab change
- D-6.9 Max neighbors per node: backend `?max_neighbors_per_node=` query param (prevents AAPL-scale explosion)
- D-6.10 Cold-cache p50/p95 budgets: d1 200/500ms, d2 800/1500ms, d3 2000/3000ms
- D-6.11 Telemetry: `graph.fetch`, `graph.render.frame`, `graph.timeout` events
- D-6.12 V1.1 backend: `entity_graph_snapshot` nightly snapshot table (drops depth-3 hot-cache to ~50ms)
- D-6.13 V1.1 path filter: `target_entity_id[]` query param on `/paths`
- D-6.14 Path materialization: add `terminal_entity_id` column on `path_insights` (blocks D-6.13)
- D-6.15 Graph node hover: tooltip with entity name + type + degree
- D-6.16 Graph relation hover: tooltip with `relation_summary` + edge weight
- D-6.17 Graph color scheme: entity type → token mapping (company/person/place/event/macro)
- D-6.18 Graph zoom controls: visible at bottom-right (no auto-fit on every depth change)

### Cluster 07 — Chart + technicals + peers (12 decisions)
- D-7.1 Peer ranking: GICS sub-industry + market-cap ±50% (fallback ±75%/±100%)
- D-7.2 Pivot formula: Classic floor-trader (R1/R2/R3, PIVOT, S1/S2/S3); compute on read
- D-7.3 IPO baseline: explicit "—" + `missing_periods[]` in response; never partial-window returns
- D-7.4 Multi-period returns anchor: prior-trading-day close (consistent across periods)
- D-7.5 Returns formatting: compound percent (not annualised CAGR; deferred)
- D-7.6 Intraday stats: polling (60s market / 5min after-hours / 1h weekend)
- D-7.7 Default chart timeframe: **1Y** (was 1D)
- D-7.8 Viewport behaviour on timeframe change: reset (preserves BP-376 fix)
- D-7.9 Volume profile overlay: NOT re-added in v1
- D-7.10 Brief border style: Left-2px (reconciles OQ-D3 + OQ-D20)
- D-7.11 Peer comparison: 5 peers × 9 ratios, below-fold on Financials tab
- D-7.12 Backend additions: 4 endpoints (B-Q-1..4) + 1 composite index migration (one wave)

### Cluster 08 — News + sentiment (10 decisions)
- D-8.1 Per-article sentiment on rows; daily aggregate as 30-day sparkline only
- D-8.2 Ranking by `display_relevance_score` (already canonical, no change)
- D-8.3 `sentiment_subject_score` aspirational — not in scope for v1
- D-8.4 Single `DenseArticleRow` primitive across Intelligence/Quote/Dashboard/News pages
- D-8.5 Filter taxonomy: 4 time tabs + faceted dropdown (source/sentiment/topic) + sort toggle
- D-8.6 Article hover preview: HoverCard with first paragraph (backend `/articles/{id}/preview` endpoint)
- D-8.7 Sentiment sparkline endpoint: `/instruments/{id}/sentiment-history` (v1.1)
- D-8.8 Backend additions: `summary_excerpt` column on `document_source_metadata`; query params for filters
- D-8.9 Topic-tag persistence table: deferred to v1.1
- D-8.10 Cluster modal (grouped articles): defer to v1.1

### Cluster 09 — Secondary pages (17 decisions)
- D-9.1 Screener preset persistence: localStorage v1; `/screener/presets` endpoint v1.1
- D-9.2 Screener watchlist add default: prompt picker with last-used persisted
- D-9.3 Screener compare-set: 5 instruments v1, more in v1.1
- D-9.4 Client-side filter stubs: keep visible-but-disabled with `[backend pending]` badge; telemetry on disabled-click
- D-9.5 Workspace crosshair sync: workspace-level toggle (single setting per workspace), default ON
- D-9.6 Workspace tab-stacking: v1.1
- D-9.7 Workspace layout templates: 4 built-in (Quad / Triple+News / Earnings-focus / Risk-watch) v1; user-saved layouts v1.1; sharing v2
- D-9.8 Predictions inline sparkline: 7-bar from new `recent_yes_history` field
- D-9.9 Predictions drawer: 576px right-anchored, history chart + bid/ask
- D-9.10 Predictions top-of-book depth: best-bid/best-ask only (no L2 depth; not a brokerage)
- D-9.11 Alerts severity grouping: keep grouped (not flat Bloomberg-style); user can toggle
- D-9.12 Alerts payload row: IBKR-style opt-in expand (per-row caret)
- D-9.13 Alerts bulk-ack: `Shift+A` ack-all-critical; bulk-snooze v1.1
- D-9.14 Alerts audio cues: NEVER (no audio system, no plans)
- D-9.15 Workspace config persistence: localStorage + URL `?config=` share v1; server-side v1.1+
- D-9.16 Predictions sparkline backend: 1 new field on list response
- D-9.17 Alerts backend: `display_trigger` field for "current vs trigger" rendering

### Cluster 10 — Interaction nuances (15 decisions)
- D-10.1 Animation 4-tier taxonomy (per DISCUSS-4)
- D-10.2 Hover taxonomy: `bg-foreground/[0.03]` clickable rows, `[0.02]` read-only, `bg-muted/40` chrome lists
- D-10.3 Sparkline expand-on-hover: REJECTED (layout shift ban)
- D-10.4 Citation HoverCard delay: 250ms
- D-10.5 Radix Tooltip delay: 300ms
- D-10.6 Focus ring T1 (table/list rows): `outline-1 outline-primary outline-offset-[-1px]`
- D-10.7 Focus ring T2 (compact inputs): `ring-1 ring-primary`
- D-10.8 Focus ring T3 (chrome CTAs): `ring-2 ring-primary ring-offset-2`
- D-10.9 Keyboard navigation: j/k in lists; arrow-keys in tables; Esc closes modal/clears filter
- D-10.10 Chord scope stack: modal > input > chart > table > page > global (already implicit; doc makes it explicit)
- D-10.11 Empty state taxonomy: 5 distinct conditions (Loading/Empty-cold-start/Empty-no-data/Error/Permission/Coming-soon)
- D-10.12 Empty state copy library: `lib/copy/empty-states.ts`, architecture-test-enforced
- D-10.13 Loading: skeleton matching dimensions (tables), `—` em-dash (cells), gray-block + caption (charts), empty SVG (sparklines)
- D-10.14 Error visual matrix: inline banner / page banner / toast / `—` fallback / status badge
- D-10.15 High-contrast mode: explicitly v1.1

---

## §C — New follow-up OQs surfaced by the investigation (need your decision)

These came out of the deep-dive and aren't in the original PRD §14. Most
have an agent-proposed answer; replying "default" accepts.

### Portfolio model (C1)
- FU-1.1 ROOT display name: "Total Portfolio" / "All Portfolios" / "ROOT" / "My Book"?
- FU-1.2 When user has 1 portfolio, hide the `ROOT ▾` switcher (silent ROOT) or show it for explicitness?
- FU-1.3 Benchmark scope for non-US books: stick with SPY v1 or auto-pick by dominant currency?
- FU-1.4 Currency policy v1 — single base currency or display-only multi-currency?
- FU-1.5 Demo data tagging in UI: opaque badge or explicit "DEMO" watermark?
- FU-1.6 Mobile priority v1.1+: stack-each-strip or true responsive?
- FU-1.7 `currency_breakdown` field on exposure response: ship in v1 contract for forward-compat?

### Entity/instrument ID (C2)
- FU-2.1 URL form for exchange disambiguation: `/instruments/AAPL` or `/instruments/AAPL.US`?
- FU-2.2 Multi-class shares URL form: `BRK.B` or `BRK-B`?
- FU-2.3 Internal field rename: `security_id` / `asset_id` / keep `instrument_id`?
- FU-2.4 `ticker_aliases` retention policy: forever or N years?
- FU-2.5 Brokerage-sync timing for the unification: in-place migration or new tenant cutover?

### AI brief + chat (C3)
- FU-3.1 Should brief generation stream tokens via SSE (requires LLMProviderChain re-plumb)?
- FU-3.2 Force-regenerate endpoint priority: v1 or v1.1?
- FU-3.3 Surface brief feedback (👍/👎) in AskAiPanel too?
- FU-3.4 Allow briefs to be cited inline in chat (`[brief:AAPL]`)?
- FU-3.5 Pin endpoint priority: ship in v1 behind flag or wait v1.1?
- FU-3.6 Brief age display absolute or relative by default?
- FU-3.7 Inflight-job handoff: if user A starts a generate, can user B see the partial?

### Watchlist (C4)
- FU-4.1 Confirm `freshness_status` is returned by `/v1/quotes/batch` (need code check)
- FU-4.2 Existing "+N more" link in sidebar — fix to `/watchlists` (PRD-0089 separated this)
- FU-4.3 IndexStrip ticker definitions: should DXY be live or hidden? VIX always on?
- FU-4.4 Watchlist hotkey for add-flow: `mod+w` collides with browser-close — pick another?
- FU-4.5 Watchlist member quote refresh: SSE per active watchlist or polling?
- FU-4.6 Drag-to-add ticker from any page to watchlist sidebar — v1 or v1.1?
- FU-4.7 Multi-row watchlist (different watchlists tiled in sidebar) — out of scope confirm?

### Design system (C5)
- FU-5.1 Hybrid 10.5/11px font scale or uniform 10.5px?
- FU-5.2 DropdownMenu/Popover keep some radius for visual separation, or 0px there too?
- FU-5.3 Hero font size for page-primary numbers — 14px or 16px?
- FU-5.4 Accept `--border-strong` + `--border-subtle` token additions?
- FU-5.5 Should `data-table-grid` opt-in stay scoped to a few pages v1, or roll out everywhere?
- FU-5.6 Sparkline color in dense tables — primary yellow or muted-foreground?
- FU-5.7 Shadow class purge — confirm zero shadows on Terminal Dark for good?
- FU-5.8 Group divider style — hairline `border-t` or section gap-2?
- FU-5.9 Accept the architecture-test extension list?
- FU-5.10 Migration ordering — do all 7 PRs in one wave or one per surface?

### Graph + intelligence (C6)
- FU-6.1 In-flight request cancellation on depth switch?
- FU-6.2 Node missing description: fetch entity detail on first hover or eagerly?
- FU-6.3 Contradiction banner tie-breaking when 2+ contradictions clear the threshold?
- FU-6.4 WS connection drop: toast or silent dot-only?
- FU-6.5 V1.1 URL-hash node-stickiness so refresh preserves selection?
- FU-6.6 Path insights label format: "AAPL → MSFT (1 hop)" or richer?
- FU-6.7 Narrative history default open vs closed?
- FU-6.8 Graph layout algorithm — ForceAtlas2 default or user-selectable?
- FU-6.9 Graph performance test fixture size (200/500/1000 nodes)?
- FU-6.10 Telemetry sampling rate for graph events?
- FU-6.11 Path query timeout if user has 100+ portfolio entities?
- FU-6.12 Edge bundling for dense graphs — v1.1 candidate?

### Chart + technicals (C7)
- FU-7.1 Brief border style — confirm Left-2px and update PRD spec table OQ-D20?
- FU-7.2 Default chart timeframe — confirm 1Y over 1D?
- FU-7.3 Pivot computation cache TTL — 5min market hours / 60min after-hours?
- FU-7.4 IPO baseline copy: "—" / "since IPO (Xd)" / "<1Y history"?
- FU-7.5 Peers manual override table for top-50 instruments?
- FU-7.6 Camarilla pivots — add behind user-settings toggle in v1.1?
- FU-7.7 Volume profile overlay — confirm we don't re-add in v1?

### News + sentiment (C8)
- FU-8.1 Topic taxonomy ownership — S6 generates or human-curated whitelist?
- FU-8.2 Hover-preview a11y keybinding (avoid conflict with `j/k`)?
- FU-8.3 Filter persistence on entity navigation — keep filters or reset?
- FU-8.4 Cluster modal parallel-slot routing — when does it open?
- FU-8.5 Sentiment sparkline tooltip detail — value + count or just value?
- FU-8.6 Daily-aggregate API endpoint shape — UNIQUE per instrument or per entity_id?
- FU-8.7 `summary_excerpt` length cap — 200 / 280 / 500 chars?
- FU-8.8 Article reading list / saved-for-later — v1 or v2?

### Secondary pages (C9)
- FU-9.1 Telemetry on disabled-filter clicks — sampling rate?
- FU-9.2 Crosshair-sync semantics across mixed timeframes (1D and 1W charts in same workspace)?
- FU-9.3 Bulk-snooze interaction with existing local-only ACK fallback?
- FU-9.4 Workspace `?config=` URL share — does it embed user data or only structure?
- FU-9.5 Predictions drawer behaviour when underlying market resolves mid-view?
- FU-9.6 Alerts "snooze" duration options — fixed list or custom time?

### Interaction nuances (C10)
- FU-10.1 j/k coverage scope — all lists or only news/articles?
- FU-10.2 Touch hovercard behaviour — long-press or none?
- FU-10.3 Toast position — top-right or bottom-right?
- FU-10.4 Flash duration on streaming chat — 600ms or 1000ms?
- FU-10.5 Esc-as-panic-reset — close everything, or only top-most?
- FU-10.6 Spinner color — primary yellow or muted-foreground?
- FU-10.7 Tooltip max-width — 240px or fluid?
- FU-10.8 Skeleton color — `bg-muted` or new `--skeleton`?
- FU-10.9 Streaming text font weight — same as final or slightly muted while streaming?
- FU-10.10 Empty-state CTA button style — primary or ghost?

---

## §D — Revised wave plan (after DISCUSS-1..12 locked)

| Wave | Scope | Backend deps | Est. | Why now |
|------|-------|--------------|-----:|---------|
| 0 | Lock DISCUSS-1..12 (this doc) + amend master PRD | — | 1d | Gating |
| A | Design system overhaul: tokens, primitives, arch-test extension, migration PRs | — | 5-7d | Every later wave consumes these |
| B | Global shell tightening | — | 3-4d | Visible across every page |
| C | Entity ID Phase 1: `/instruments/{ticker}` URL routing | gateway shim | 4-5d | Fixes Intelligence depth-3 timeout |
| D | ROOT portfolio frontend (default landing + switcher chip) | — | 2-3d | Highest user complaint |
| E | Financials sidebar restoration (7 panels: analyst/target/revisions/beat-miss/AI-brief/company-snapshot/targets-by-firm) | rag-chat brief generate endpoint | 4-5d | Highest user complaint |
| F | Instrument Quote density (CompanyAboutCard / MetricGrid4 / Peers / Earnings / Headlines) | B-Q-1..4 (parallel) | 4-5d | Closes restoration |
| G | Instrument Intelligence (StructuredBrief / right-rail blocks / depth-adaptive timeout / contradictions) | — | 4-5d | Closes restoration |
| H | Portfolio Overview holdings table + KPI mega-cell + sector exposure | — | 4-5d | "Cannot see positions" complaint |
| I | Portfolio Detail (slide-over + tx ledger + analytics) | — (client-side TWR v1) | 5-6d | Drilldowns |
| J | Dashboard | — | 4-5d | Landing |
| K | Screener (filter chips + popover + preset bar) | — | 4-5d | Single-page surgery |
| L | Workspace + Predictions + Alerts | predictions sparkline + alert display_trigger | 4-5d | Secondary surfaces |
| M | Chat polish + unified citation primitive | — | 3-4d | Cross-cutting AI UX |
| N | Optional backend endpoints (B-Q-1..5, B-F-1..2, B-P-1..4, B-D-1, sentiment-history, brief-regenerate, top-movers, etc.) — parallel with prior waves | per endpoint | 10-15d | Lights up deferred cards |
| O | Entity ID Phase 2: internal `security_id` unification + DB migration | services migration | 8-12d | v1.1 |
| P | QA + Playwright density gates + architecture-test enforcement | — | 4-5d | Lock NFR-1 in CI |

Total v1 (waves A-N, parallelisable): **15-22 days wall-clock with 5-7 parallel agents** (same dispatch pattern PLAN-0090 proved).

---

## §E — Suggested user conversation flow

Read this doc top-to-bottom, then react in priority order:

1. **First pass — DISCUSS-1..12 in §A.** Twelve high-stakes decisions; lock each or push back.
2. **Second pass — §B locked decisions.** Skim; flag any row to discuss instead.
3. **Third pass — §C follow-ups.** Bulk-respond ("accept all defaults except FU-X.Y, FU-X.Z").
4. **Fourth pass — §D wave plan.** Tweak ordering / scope cuts before `/plan` runs.

When the doc is signed off:
1. Update `docs/specs/0089-platform-page-redesign.md` (status: `active`)
2. Update `docs/designs/0089/_INDEX.md` (status: locked)
3. Run `/plan` to decompose into `docs/plans/0089-platform-page-redesign-plan.md`
4. Run `/implement-ui` per wave with the established cherry-pick + commit discipline

---

## §F — Cross-cluster discoveries worth highlighting

The agents surfaced findings that go beyond their own clusters:

1. **PRD-0088 / PLAN-0090's T-E-01 deletion was over-aggressive** — removed the AI brief, company description, sector classification surfaces that USER explicitly noticed missing. PRD-0089 restores them via per-page design docs.

2. **Latent architectural contradiction**: `ADR-F-12` (distinct entity_id ≠ instrument_id) vs Kafka schema M-017 (entity_id = instrument_id). Production code follows M-017; seed data follows ADR-F-12. This is documented as a contradiction that PRD-0089 forces resolution of (DISCUSS-2).

3. **Backend already supports aggregated portfolio view (ROOT)** — frontend just doesn't surface it. This dramatically lowers the cost of DISCUSS-1 ("show total portfolio").

4. **AskAiPanel and Chat duplicate citation rendering** (~310 LOC) — cleanup wins from unifying.

5. **Watchlist sidebar needs zero new endpoints** — `POST /v1/ohlcv/batch` + extending `/v1/watchlists` with `?expand=` covers everything.

6. **Animation policy NFR-6 is unenforceable as written** — 4-tier taxonomy fixes it.

7. **Chart canvas height bug** (already fixed 2026-05-19 in commit `b6b9fd3e`) — the C7 agent verified the fix is in production; no regression risk.

8. **MetricsTable rich fundamentals fetch** (already fixed in commit `87741ea5`) — the C5 agent confirmed the cache-sharing pattern this PRD wants to formalize is already in place.

9. **PascalCase EODHD field type mismatch** (fixed 2026-05-19 in commit `2d184472`) — C5 + C8 agents both flagged the recurring pattern; NFR-12 in the master PRD codifies the watchdog.

10. **Density agents over-shot the 40-cell floor by 3-7x** — confirms the floor was too conservative; DISCUSS-8 raises it.
