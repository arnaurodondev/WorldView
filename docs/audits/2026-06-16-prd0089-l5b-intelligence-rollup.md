# Audit — PRD-0089 §1 "L-5b S3-side Intelligence Rollup Sync Worker" (deferred-work review)

**Date:** 2026-06-16
**Worktree:** `worldview-wt-md-reliability` @ HEAD `2e447e8be`
**Target:** §1 of `docs/plans/0089-pages/DEFERRED-WORK-PLAN.md`
**Mode:** read-only investigation
**Bottom line:** **L-5b is SHIPPED and committed.** The "deferred" plan section is
**stale** — the entire worker, migration, 4 typed clients, screener filters/sorts,
and even the IB-L5 frontend wave landed *after* the deferred-work doc was written.
Only one small gap remains (a freshness field not plumbed to the screener API
response, blocking the IB-L5 stale-data tooltip).

---

## Lens 1 — Does it exist / current state?

**It exists, and it is committed in HEAD.** The plan describes L-5b as future
work over "5 commits, ~3 engineer-days." In reality it shipped in commit
**`f63d19e2e`** (`feat(market-data): PLAN-0089 L-5b — intelligence rollup sync
worker (T-WL5B-01..06)`, 2026-06-09, +2027 lines/16 files), with three follow-up
hardening fixes (`e5afbc3cb`, `d6789e736`, `7bb2e795c`). All files are git-tracked
(not uncommitted working-tree edits).

> Note on the prompt's "sibling created intelligence_clients.py earlier this
> session" hint: `intelligence_clients.py` is **committed in HEAD** (part of
> `f63d19e2e`), not a loose uncommitted file. `git status` is clean for all L-5b
> paths.

### Plan claim vs reality (file:line evidence)

| Plan §1 item | Status | Evidence |
|---|---|---|
| 6 new snapshot columns + `intelligence_rollup_synced_at` | **DONE** | `services/market-data/src/market_data/infrastructure/db/models/fundamentals_snapshot.py:165-174` — `news_count_7d`, `llm_relevance_7d_max`, `display_relevance_7d_weighted`, `recent_contradiction_count`, `has_active_alert`, `has_ai_brief`, `intelligence_rollup_synced_at`, all nullable |
| Migration "032" | **DONE — but numbered 035** | `services/market-data/alembic/versions/035_add_l5b_intelligence_columns.py` (7 nullable cols + 6 `screen_field_metadata` seed rows). Plan said `032 ← 031`; chain advanced to 035 by the time it landed. |
| `sync_intelligence_rollup.py` use case | **DONE** | `services/market-data/src/market_data/application/use_cases/sync_intelligence_rollup.py` (386 lines): cursor-paginated, `asyncio.Semaphore` bounded concurrency, dynamic UPSERT, keep-last-known semantics, 18h skip-guard |
| `intelligence_clients.py` — 4 typed HTTP clients | **DONE** | `services/market-data/src/market_data/infrastructure/clients/intelligence_clients.py` (295 lines): 4 client classes, `httpx.Timeout(10)` per BP-235, 1-retry budget, `X-Internal-JWT` header |
| `_intelligence_rollup_loop` lifespan task | **DONE** | `services/market-data/src/market_data/app.py:586` (loop def), `:922` (task registration). 04:00 UTC default. |
| `INTELLIGENCE_ROLLUP_HOUR_UTC` env var | **DONE** | `config.py:86` `intelligence_rollup_hour_utc: int = 4` (env `MARKET_DATA_INTELLIGENCE_ROLLUP_HOUR_UTC`); upstream URLs `config.py:99-102` |
| `ScreenFilterRequest` 10 new fields | **DONE** | `api/schemas/fundamental_metrics.py:115-124` — `news_count_7d_{min,max}`, `llm_relevance_7d_max_{min,max}`, `display_relevance_7d_weighted_{min,max}`, `recent_contradiction_count_{min,max}`, `has_active_alert`, `has_ai_brief` |
| WHERE-clause + ORDER BY whitelist | **DONE** | `infrastructure/db/repositories/fundamental_metrics_query.py:103-108` (filter whitelist), `:835-838` (boolean equality filters), `:867-872` (sort whitelist) |
| Router projection + sort whitelist | **DONE** | `api/routers/fundamental_metrics.py:200-206` (sort whitelist), `:278-279` (filter wiring), `:201` (projection) |
| Lock-step `_get_static_screen_fields()` + test | **DONE** | `app.py` 6 L-5b entries; `tests/unit/test_l5b_migration_lockstep.py` (asserts 44 fields, byte-identical to migration seed) |
| Unit + client tests | **DONE** | `tests/unit/test_sync_intelligence_rollup.py`, `test_intelligence_clients.py` — **35 tests PASS** (ran 2026-06-16: `35 passed`) |

**Migration numbering mismatch:** the plan repeatedly says "migration 032" /
`031 ← 030 ← …`. The real artifact is **035** (chain advanced between writing
the plan and shipping). Anyone reading §1 today will look for `032_…` and not
find it.

### What is NOT done (the genuine residual gap)
- **`intelligence_rollup_synced_at` is not projected into the screener API
  response.** It is in the ORM model, but neither the query projection nor the
  `ScreenResult` schema returns it: `grep synced_at services/market-data/src/market_data/api/`
  and the query repo returns **nothing**. The router sort whitelist
  (`fundamental_metrics.py:200-206`) deliberately omits it.
  → This directly blocks plan task **T-IB5-04** (frontend stale-data tooltip),
  which the plan itself flagged as "need to confirm L-5b plumbs this through
  `ScreenResult`." Answer: it does not, yet. The frontend already declares the
  field (`apps/worldview-web/types/api.ts:865`) in anticipation, but it will
  always arrive `null`.

---

## Lens 2 — Root cause (why it was "not done") + dependency verification

The plan's stated blocker was: *"gated on cross-service R9 contract; the 4 L-5a
endpoints exist but the consumer worker doesn't; 3 open architecture decisions."*
That framing was **accurate at the time the doc was written** but is now
obsolete — the consumer was built and the decisions were resolved.

### The 4 upstream endpoints (the worker's dependency) — ALL EXIST
- S6 news-rollup: `services/nlp-pipeline/src/nlp_pipeline/api/routes/internal_news_rollup.py:56` → `GET /internal/v1/instruments/{id}/news-rollup-7d`
- S7 intelligence-rollup: `services/knowledge-graph/src/knowledge_graph/api/internal_intelligence_rollup.py:42` → `…/intelligence-rollup-7d`
- S10 active-alert: `services/alert/src/alert/api/routes.py:67` → `…/active-alert-flag`
- S8 ai-brief: `services/rag-chat/src/rag_chat/api/routes/internal_ai_brief_flag.py` → `…/ai-brief-flag`

These shipped under L-5a (merge `8266629cb`). R9 compliance is satisfied exactly
as the plan's "option 2" prescribed (S3-side scheduled REST pulls; no
cross-service DB JOIN).

### The 3 "open" architecture decisions — ALL RESOLVED in code (per audit recos)
1. **Stale-data semantics** → resolved as **option (a) keep-last-known**. The
   UPSERT only sets columns from successful responses; a down upstream leaves the
   prior value untouched (`sync_intelligence_rollup.py` keep-last-known UPSERT,
   per-upstream success counters). Freshness recorded via
   `intelligence_rollup_synced_at` (model line 171). Matches audit recommendation.
2. **`has_active_alert` freshness** → shipped **nightly** (12h latency accepted),
   Kafka-subscription upgrade explicitly deferred to v2. Loop fires once/day at
   04:00 UTC (`app.py:586`). Matches "defer to v2."
3. **`has_ai_brief` "today vs ever"** → S8 endpoint owns the semantics; S3 simply
   stores the boolean (`sync_intelligence_rollup.py:301-303`). The product
   decision lives in `internal_ai_brief_flag.py`, not in the L-5b worker.

### Real (latent) root cause that the worker shipped *broken* and was hot-fixed
The original `f63d19e2e` pointed the S6 news-rollup client at
**`content-store:8006`** — wrong service *and* the endpoint lives in
**nlp-pipeline**. Every nightly S6 call silently 404'd, leaving
`news_count_7d` / `llm_relevance_7d_max` / `display_relevance_7d_weighted` NULL
across the universe (a textbook "audit-return-not-persisted / silent-drop"
pattern from the user's memory). Fixed by:
- `7bb2e795c fix(nlp-pipeline): register news-rollup-7d router in create_app` (the
  endpoint existed but was never mounted),
- `d6789e736 fix(market-data): point S6 news-rollup client at nlp-pipeline`,
- `e5afbc3cb fix(market-data): fix migration 035 column name + alert hostname`.

`config.py:93-98` now documents this trap. This is the kind of failure that would
have stayed invisible without a live smoke test.

---

## Lens 3 — UI enhancement (IB-L5 screener intelligence filters)

### Current frontend state — IB-L5 has ALSO shipped (mostly)
The plan lists IB-L5 as "GATED on §1 L-5b." It is **no longer gated** — it
shipped in `de2e80f30` / `4f36921a7` / `9d4fbf1a4`:
- 5 of 7 rows are **live** by default. `IntelligenceFilterGroup.tsx:70-78`
  `IB_L5_DEFAULTS` = `{newsCount7d, aiBrief, activeAlert, contradictions,
  llmRelevance: true; upcomingEarnings, upcomingDividend: false}`.
  `ScreenerFilterBar.tsx:942` renders `<IntelligenceFilterGroup>` without a
  `backendReady` override, so all 5 rollup rows are interactive; only the 2
  **calendar** rows (L-5c, not L-5b) still show `BackendPendingBadge`.
- Both opt-in columns shipped and default-visible: `ag-screener-columns.tsx:1257`
  (`NEWS 7D` → `news_count_7d`) and `:1268` (`BRIEF SCORE` →
  `display_relevance_7d_weighted`), with dedicated cell renderers at `:708` and `:735`.
- Wire format hardened in `9d4fbf1a4` (intelligence fields sent as per-filter
  named siblings, not own filter entries).

### The one frontend task still open: T-IB5-04 stale-data tooltip
`grep -i stale|synced|tooltip apps/.../IntelligenceFilterGroup.tsx` → **no
matches**. The component declares the field on the row type
(`types/api.ts:865 intelligence_rollup_synced_at`) but renders no freshness
indicator, because the backend never sends the value (Lens 1 gap).

### UX recommendation for surfacing intelligence filters first-class
Surfacing "news volume / relevance / contradictions / alert / brief" in a
screener is unusual — users have no Bloomberg muscle memory for it, so the UI
must teach the mental model:
- **Group identity.** Keep these under a visually distinct "INTELLIGENCE"
  section header (already grouped) so users read them as *derived signals*, not
  fundamentals. A subtle accent (e.g. the primary/yellow token) separates
  "what the market computed" from "what we inferred."
- **Boolean toggles, not range inputs, for `has_active_alert` / `has_ai_brief`.**
  Already implemented as toggles — correct. A range box for a boolean is a
  classic confusion.
- **Inline semantics tooltips.** Each row needs a one-line "?" explaining the
  field in plain English: e.g. `recent_contradiction_count` → "Number of times
  in the last 7 days our KG flagged conflicting claims about this company."
  Without this, "contradiction count ≥ 1" is meaningless to a PM.
- **Stale-data honesty (the load-bearing UX).** Nightly sync means up to ~24h
  lag and silent-staleness if an upstream is down for days. Surface a header
  badge on the INTELLIGENCE group: "Intel as of {hh}:00 UTC — N h old," turning
  amber when `now - max(synced_at) > 25h`. This requires backend to project
  `intelligence_rollup_synced_at` (the residual gap). This single tooltip
  converts a silent-failure liability into a trust signal.
- **NULL ≠ 0 in columns.** `NEWS 7D` of `null` (never synced) must render "—",
  not "0," or the screener lies. Confirm cell renderers
  (`ag-screener-columns.tsx:715,745`) treat null distinctly from zero.
- **Preset screens.** Ship a "Live Catalysts" saved preset
  (`news_count_7d_min=5 AND has_active_alert=true`) so the differentiator is
  one click from the empty state, not buried in a filter popover.

---

## Lens 4 — Bloomberg-competitive thesis

§2.2 of the plan calls the intelligence layer "the differentiator vs Bloomberg."
This is the strongest competitive claim in the whole screener and it is now
*actually shippable* (backend live, frontend live).

### What Bloomberg EQS structurally cannot screen on
Bloomberg's Equity Screen (EQS) filters over fundamentals, estimates, technicals,
ownership, ESG, and classification fields. It has **no field for**:
- **recent news *volume*** as a numeric screen criterion (`news_count_7d`) —
  Bloomberg has NEWS/news heat per security, but not as an EQS filter axis,
- **an LLM/NLP relevance or "brief" score** (`llm_relevance_7d_max`,
  `display_relevance_7d_weighted`) — there is no equivalent computed field,
- **AI-detected narrative contradictions** (`recent_contradiction_count`) — this
  is a knowledge-graph–derived signal with no Bloomberg analogue at all,
- **"this name has a live alert / a generated AI brief"** (`has_active_alert`,
  `has_ai_brief`) — these are *platform-state* signals unique to Worldview.

These are not "Bloomberg has it but worse" gaps; they are categories that do not
exist in EQS because Bloomberg's screener predates the LLM/KG layer.

### Screens that become possible (and are impossible in EQS)
1. **Catalyst-driven momentum:** `news_count_7d ≥ 5 AND 1Y RTN > 0 AND within 5%
   of 52W high` — "what is the market suddenly talking about that is also
   technically breaking out." EQS can do the technicals half only.
2. **Contradiction alpha:** `recent_contradiction_count ≥ 1 AND analyst_upside ≥
   15%` — "names where consensus is bullish but our KG sees conflicting claims" —
   a short/pairs idea-generator with **no** Bloomberg equivalent.
3. **Quiet quality:** `news_count_7d = 0 AND FCF margin > 20% AND insider_net_buy_90d
   > $1M` — high-quality compounders the news cycle is ignoring.
4. **Live-attention universe:** `has_active_alert = true` — instantly scope a
   screen to names the platform is *currently* flagging, then layer fundamentals.

### The killer demo
Open the screener, click the **"Live Catalysts"** preset
(`news_count_7d_min=5 AND has_active_alert=true`), and watch a static
fundamentals table become a *live, attention-weighted* universe — then add
`recent_contradiction_count ≥ 1` and narrate: "Bloomberg's $24k/yr terminal
cannot run this query. We just screened the entire universe for stocks the market
is loudly debating *and* where our AI sees the bull case contradicting itself."
The differentiator is not a prettier table — it is a **filter axis Bloomberg's
data model does not have**.

---

## Remaining work to ship the *advertised* polish

L-5b core + IB-L5 core are **done and tested**. To close the loop:

1. **Plumb `intelligence_rollup_synced_at` into the screener response** (S3:
   add to query projection + `ScreenResult` schema; ~0.5 d). Unblocks the only
   open frontend task.
2. **IB-L5 T-IB5-04 stale-data tooltip** in `IntelligenceFilterGroup.tsx` (amber
   when max age > 25h); ~0.5 d, depends on (1).
3. **Doc reconciliation (stale-doc cleanup):**
   - `docs/plans/0089-pages/DEFERRED-WORK-PLAN.md` §1 — mark L-5b SHIPPED
     (`f63d19e2e`, 2026-06-09); fix "migration 032"→**035**; remove "3 open
     architecture decisions" (all resolved).
   - `docs/plans/0089-pages/I-screener-plan.md:112` — still says "**L-5b
     deferred**"; flip to shipped.
   - `docs/plans/TRACKING.md` — no L-5b/intelligence-rollup row exists; add one.
4. **Production smoke test** of the S6 path specifically (it shipped broken once;
   verify `news_count_7d` is non-NULL for active names post-deploy) + an
   `intelligence_rollup_synced_at`-age alert so silent staleness is caught.

## Competitive angle (one line)
The intelligence filters are the only part of the screener Bloomberg EQS
*cannot replicate with its data model*; the work to make them first-class is now
mostly a freshness-plumbing + doc-truth exercise, not new feature build.
