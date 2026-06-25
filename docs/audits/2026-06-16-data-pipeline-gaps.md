# Data Pipeline Gaps — Intelligence Layer Audit

**Date:** 2026-06-19 (filed under 2026-06-16 frontend-QA cycle)
**Worktree:** `/Users/arnaurodon/Projects/University/final_thesis/worldview-wt-md-reliability` (`feat/md-reliability-followups`, HEAD `26f00a92c`)
**Mode:** READ-ONLY (live DB / logs / HTTP). No code, schema, or data changed.
**Author:** investigation agent

Frontend QA surfaced several universe-wide DATA gaps that make good UI look broken and block the
Bloomberg-differentiator screens. This report traces each to a precise root cause and the cheapest fix.

---

## TL;DR — verdict table

| # | Gap | Data exists? | Root cause | Cheapest fix | Severity |
|---|-----|--------------|-----------|--------------|----------|
| **1** | **KG contradictions = 0 universe-wide (keystone)** | **YES** — 7180 links, 5293 in last 7d, 65 distinct subject entities | **Query JOIN bug**: S7 rollup joins `rer.raw_id = rcl.relation_evidence_id`, but the column actually holds **claim_id** values (7180/7180 match `claims.claim_id`, 0/7180 match `relation_evidence_raw.raw_id`) → 0 rows always | One-line JOIN change in `intelligence_rollup.py` (join `claims` not `relation_evidence_raw`) + re-run nightly sync | **P0 / CRITICAL** |
| **2** | `volatility_30d` + `returns_adjustment_quality` null | NO (yet) — but code shipped, will populate next run | New worker stages 4 & 5 shipped in the build deployed **today 05:23 UTC**, AFTER the 02:00 run. Old build wrote only 8/10 metrics | Wait for next 02:00 UTC run (NOT suppressed — `worker_runs` empty); or restart with `COMPUTED_METRICS_REFRESH_HOUR_UTC` set to an imminent hour | P2 / self-healing |
| **3** | Intelligence rollup partial coverage | Partial | news/relevance signals real; contradiction=0 (gap 1); `has_active_alert`/`has_ai_brief` near-empty | Fix gap 1 + gap 5 (briefs) unlocks 2 more filters | P1 |
| **4** | Instrument Intelligence tab empty (AAPL) | YES for 3/4 sub-sections | Only the **graph canvas** is broken: depth=2 AGE traversal on the Apple hub exceeds the 20s statement timeout → 504 → bundle fails-soft to `{nodes:0,edges:0}` | Default initial canvas to **depth=1** (fast, 33 nodes/40 edges); lazy-load depth=2 | P1 |
| **5** | Dashboard widgets empty | Mixed | Morning Briefing genuinely broken (config); Market Snapshot + News Momentum actually populated | Set `SERVICE_ACCOUNT_TOKEN` on the api-gateway container | P1 (briefing) |

---

## Gap 1 — KG Contradictions Universe-Wide ZERO (THE KEYSTONE)

This gates the "Live Catalysts" Bloomberg-differentiator screen
(`news_count_7d ≥ 5 AND has_active_alert AND recent_contradiction_count ≥ 1`), which returns **0 rows**.

### Does the data exist? YES.

```
intelligence_db.relation_contradiction_links:
  total = 7180, active (invalidated_at IS NULL) = 7180,
  detected last 7d = 5293
  min detected_at = 2026-06-06, max = 2026-06-19 06:14  (actively generated, hourly)
```

The contradiction-detection pipeline runs and is healthy:
- Worker: `ContradictionBatchWorker` (Worker 13B) —
  `services/knowledge-graph/src/knowledge_graph/infrastructure/workers/contradiction_batch.py`
- 90-day detection window, subject-based polarity-conflict scan over `claims`.
- `claims` table: 70,471 rows, 45,751 in last 7d → plenty of fuel.

### Root cause — a JOIN-vs-write column mismatch (silent zero).

The detection worker **writes the claim_id into `relation_contradiction_links.relation_evidence_id`**:

```python
# contradiction_batch.py:98-104
await contra_repo.insert_link(
    relation_evidence_id=claim_id,   # <-- the SUBJECT claim's id, NOT a relation_evidence_raw.raw_id
    claim_id=opp_claim_id,
    ...
)
```

But the S7 rollup use case that feeds the screener joins as if that column were a `raw_id`:

```sql
-- intelligence_rollup.py:57-66  (GetIntelligenceRollup7dUseCase)
FROM relation_contradiction_links rcl
JOIN relation_evidence_raw rer
    ON rer.raw_id = rcl.relation_evidence_id     -- <-- WRONG: column holds claim_id
WHERE rer.subject_entity_id = :entity_id
  AND rcl.invalidated_at IS NULL
  AND rcl.detected_at >= now() - INTERVAL '7 days'
```

Live proof of the mismatch:

```
rcl rows joining via rer.raw_id   = 0    / 7180   <-- what the rollup uses
rcl rows joining via claims.claim_id = 7180 / 7180  <-- what the data actually is
EXACT rollup query (no entity filter) surviving rows = 0   <-- always zero, universe-wide
```

There is **no FK constraint** on `relation_evidence_id` (only a UNIQUE
`(relation_evidence_id, claim_id)`), so the wrong-table value was accepted silently — a textbook
"all-green / zero-output" pattern. The market-data `_intelligence_rollup_loop` worked correctly:
it synced all 669 instruments at 04:00 UTC today and faithfully stored the `0` that S7 returned.

This is **(a) "S7's endpoint returns 0 for everything"** — not a worker-drop, not a 7-day-window
issue, not an empty source table.

### What the fix unlocks (live-verified)

Re-joining via `claims` yields real signal:

```
DISTINCT subject entities with contradiction_count ≥ 1 (7d) = 65
Top subjects: 1182, 560, 544, 412, 355, 289, 239, 183 contradictions...
```

### Cheapest fix

Change the rollup JOIN to resolve the subject through `claims`, mirroring the actual write path:

```sql
FROM relation_contradiction_links rcl
JOIN claims c ON c.claim_id = rcl.relation_evidence_id
WHERE c.subject_entity_id = :entity_id
  AND rcl.invalidated_at IS NULL
  AND rcl.detected_at >= now() - INTERVAL '7 days'
```

Then trigger one market-data intelligence-rollup sweep so `recent_contradiction_count` repopulates
(it already runs daily at 04:00 UTC; next sweep will pick it up automatically once S7 is fixed and redeployed).

**Caveat / follow-up to confirm during the fix:** the column name `relation_evidence_id` plus the
`insert_link` docstring ("FK → raw_id, NOT claim_id") show the *original intent* was to store a
`relation_evidence_raw.raw_id`. The worker diverged from that intent. The minimal/cheapest fix is to
make the **read match the write** (join `claims`). A cleaner long-term fix is to make the *write* match
the schema intent (resolve `claim_id → relation_evidence_raw.raw_id` before insert) and add the missing
FK — but that is a larger change and risks dropping links where no `relation_evidence_raw` row exists.
For getting real contradiction signal flowing **now**, the read-side JOIN fix is correct and lowest-risk.

> **Affected files**
> - `services/knowledge-graph/src/knowledge_graph/application/use_cases/intelligence_rollup.py:57-66` (the bug)
> - `services/knowledge-graph/src/knowledge_graph/infrastructure/workers/contradiction_batch.py:98` (the write that defines reality)
> - Sanity-check `claim_repository.py::fetch_contradictions_for_entity` and `contradiction.py::fetch_active_for_subject` — they use the **same** `rer.raw_id = rcl.relation_evidence_id` join and are therefore **also silently returning nothing**. These back the confidence formula + per-entity contradiction lookups, so the bug is broader than the rollup alone.

---

## Gap 2 — `returns_adjustment_quality` + `volatility_30d` not populated

### Clarification of where these live

These are **NOT columns on `instrument_fundamentals_snapshot`**. They are rows in
`market_data_db.fundamental_metrics` (`period_type='SNAPSHOT'`, `section='computed_returns'`,
`metric IN ('volatility_30d','returns_adjustment_quality')`), emitted by
`ComputedMetricsBackfillWorker`
(`services/market-data/src/market_data/infrastructure/db/computed_metrics_worker.py`).

### Live state

```
fundamental_metrics SNAPSHOT/computed_returns by metric:
  dist_from_52w_high_pct  2016
  dist_from_52w_low_pct   2016
  return_1m  1962   return_3m 1895   return_6m 1891
  return_1y  1352   return_3y    1   return_ytd 2016
  volatility_30d            0   <-- MISSING
  returns_adjustment_quality 0   <-- MISSING
```

8 of 10 metrics present; the two newest absent.

### Root cause — code shipped after the last worker run (NOT a code/data defect).

- The 02:00 UTC run today wrote the 8 metrics (`ingested_at = 2026-06-19 02:00:00`).
- The market-data container was (re)started **2026-06-19 05:23 UTC** — i.e. the new build carrying the
  volatility (stage 4) + adjustment-quality (stage 5) code deployed **after** the 02:00 run.
- The current deployed worker confirmed to contain both stages
  (`grep _VOLATILITY_30D_SQL / _ADJUSTMENT_QUALITY_SQL` → present in `/app/src/...`).
- The scheduler (`_computed_metrics_refresh_loop`, `app.py:736`) is daily-at-02:00-UTC only; it will not
  fire again until tomorrow 02:00.
- 622 instruments have ≥31 daily bars (volatility needs ≥2 returns) → vol **will** populate broadly next run.
  `returns_adjustment_quality` is a 1.0/0.0 flag for every instrument with OHLCV → will be near-universal.

### Will the next scheduled run pick it up? YES.

The 20-hour skip-guard reads `worker_runs` (migration 040, durable). `worker_runs` is currently **empty**
(0 rows), so the guard will NOT suppress the next 02:00 UTC run. No compose override of
`COMPUTED_METRICS_REFRESH_HOUR_UTC` exists (default 02:00). Next run repopulates both metrics.

### How to trigger on-demand (document only — do NOT run)

There is **no manual HTTP endpoint, CLI, or standalone script** for this worker — it is only invoked by
the in-process `_computed_metrics_refresh_loop`. Options to make it run immediately:

1. **Set the hour to an imminent value and recreate the container.** Set
   `COMPUTED_METRICS_REFRESH_HOUR_UTC=<next hour>` on the market-data service in
   `infra/compose/docker-compose.yml`, recreate it; the loop sleeps until that hour then runs. Because
   `worker_runs` is empty, the 20h guard won't block it.
2. **Poke the loop programmatically** (one-shot, no schedule wait):
   `docker exec worldview-market-data-1 python -c "import asyncio; from market_data.app import _build_write_session_factory; from market_data.infrastructure.db.computed_metrics_worker import run_computed_metrics_backfill; ..."` —
   i.e. import `run_computed_metrics_backfill(write_factory)` and `asyncio.run` it against a write
   sessionmaker. (Exact factory accessor: see `app.py` lifespan; `run_computed_metrics_backfill` takes an
   `async_sessionmaker`.) This is the cheapest "right now" trigger but bypasses the durable success record.

**Recommendation:** simplest is to do nothing — the next 02:00 UTC sweep self-heals. If the demo needs it
sooner, use option 1.

---

## Gap 3 — Intelligence rollup partial coverage (which IB-L5 filters are real today)

Live distribution over `instrument_fundamentals_snapshot` (669 instruments, synced 04:00 UTC today):

| Column | Non-null / non-zero | Meaningful as a filter today? |
|--------|--------------------:|------------------------------|
| `news_count_7d > 0` | **545 / 669** | YES — strong coverage |
| `display_relevance_7d_weighted > 0` | **545 / 669** | YES |
| `llm_relevance_7d_max > 0` | **500 / 669** | YES |
| `analyst_target_price` not null | 571 / 669 | YES (fundamentals, not intelligence) |
| `insider_net_buy_90d != 0` | 30 / 669 | sparse but real |
| `has_ai_brief = true` | **0 / 669** | **NO — empty** (depends on Gap 5 briefs) |
| `has_active_alert = true` | **7 / 669** | barely populated |
| `recent_contradiction_count > 0` | **0 / 669** | **NO — Gap 1 bug** |

**Conclusion:** Today the *meaningful* intelligence filters are `news_count_7d`,
`display_relevance_7d_weighted`, and `llm_relevance_7d_max`. The "Live Catalysts" screen needs THREE
signals (`news_count_7d ≥ 5`, `has_active_alert`, `recent_contradiction_count ≥ 1`); two of them
(`has_active_alert`, contradictions) are effectively empty. **Fixing Gap 1 turns the keystone column on
for 65 entities; Gap 5 (briefs) turns on `has_ai_brief`; `has_active_alert` at 7/669 is a genuine
alert-coverage thinness, not a bug.**

---

## Gap 4 — Instrument Intelligence tab (AAPL): only the graph canvas is broken

AAPL entity_id = `01900000-0000-7000-8000-000000001001`. 3 of 4 sub-sections have data and work; the
graph canvas is a wiring/performance issue, not missing data.

| Sub-section | DB data | S9 endpoint | Live result | Verdict |
|---|---|---|---|---|
| **Graph** | 151 relations; depth-1 = 33 nodes / 40 edges | `GET /v1/entities/{id}/graph?depth=2` (bundle leg `graph_d2`) | **504 timeout**, leg degrades to `{nodes:0, edges:0}` | **BROKEN — endpoint timeout, data exists** |
| Dossier | description (296 ch), 3 narratives, 5 top relations, 24 `relation_summaries` | `GET /v1/entities/{id}/intelligence-bundle` (`detail` leg) | 200, full dossier | OK |
| News | 424 articles | `GET /v1/news/entity/{id}` | 200, total 424 | OK |
| Events | 3 `entity_event_exposures` | `GET /v1/entities/{id}/events?active_only=false` | 200, 3 events | OK |

**Graph root cause:** the frontend `GraphColumn` reads cache key `entityGraph(id, 2)`, seeded by the
bundle's `graph_d2` leg → `GET .../graph?depth=2`. For the Apple hub the depth-2 **AGE Cypher**
multi-hop traversal exceeds the 20s `statement_timeout` (`graph_depth_cypher_timeout` in KG log) → 504
→ bundle fails-soft → blank canvas. depth=1 uses a different non-AGE direct-SQL path and returns
33 nodes/40 edges in milliseconds. Same AGE dense-hub class as prior memory (entity-graph depth≥2 504).

**Cheapest fix:** default the initial canvas to **depth=1** (fast, populated) and lazy-load depth=2;
optionally surface the leg failure so the UI shows "retry" instead of a blank canvas.

> Files: `apps/worldview-web/components/instrument/intelligence/IntelligenceTab.tsx`,
> `apps/worldview-web/features/intelligence/hooks/useEntityIntelligenceBundle.ts`,
> `services/knowledge-graph/src/knowledge_graph/api/routes.py` (~273-300),
> `services/knowledge-graph/src/knowledge_graph/api/cypher_neighborhood.py` (`_STATEMENT_TIMEOUT_MS` 20s).

---

## Gap 5 — Dashboard widgets

Only Morning Briefing is actually broken; the other two return live data.

### 5a. Morning Briefing — config/wiring bug (data exists, can't be gathered)
- Endpoint `GET /v1/briefings/morning` → **HTTP 200** but degenerate: every section
  "No specific items today", 0 sections, 0 entity_mentions.
- Backing: rag-chat (S8) `rag_db.user_briefs` — **85 rows**; the 2026-06-15 brief had real content
  ("SPY +0.50%, QQQ +0.46%, VIX +11.83%…"); all 2026-06-19 briefs are empty templates.
- **Root cause (confirmed in logs):** rag-chat's brief scheduler mints a service token via
  `POST /internal/v1/service-token` → api-gateway returns **503 `service_account_unconfigured`** because
  the gateway's `service_account_token` setting is empty (`SecretStr("")`); `SERVICE_ACCOUNT_TOKEN` is
  not set on the gateway container and absent from `infra/compose/docker-compose.yml`. No token → all
  brief upstream calls 401 → every source empty → `brief_context_availability_score = 0.0`
  (`brief_low_context_refusal`) → LLM emits the empty template. Underlying data IS present
  (22,581 entity_mentions, 17,748 docs/7d, live quotes). rag-chat has
  `RAG_CHAT_SERVICE_ACCOUNT_TOKEN=dev-service-account-secret-plan-0094` but the gateway has no matching var.
- **Cheapest fix:** set `SERVICE_ACCOUNT_TOKEN=dev-service-account-secret-plan-0094` on the api-gateway
  service in `infra/compose/docker-compose.yml` (matching rag-chat), recreate the gateway, let the hourly
  `MorningBriefPregenerationWorker` regenerate.
  Route: `services/api-gateway/src/api_gateway/routes/internal.py:132`;
  setting: `services/api-gateway/src/api_gateway/config.py:105`.

### 5b. Market Snapshot — NOT empty
- `GET /v1/instruments/lookup?symbol=SPY` 200; `POST /v1/quotes/batch` 200 with real prices
  (SPY $747.93 −0.88%, AAPL $298.50 −0.25%, `freshness_status: recent`); `GET /v1/companies/{id}/overview`
  200. Backing market-data (S3) `market_data_db`. **Genuinely populated.**
  (Caveat: one transient `GET /v1/quotes/{id}` → 503 `rate_limiting_unavailable` observed — Valkey
  flapping can intermittently 503 single-quote calls; the batch path used by the widget is healthy.)

### 5c. News Momentum — NOT empty
- `GET /v1/signals/ai?limit=30&hours=24` → **200, 30 populated signals** (real headlines, sentiment,
  relevance, e.g. SF/Stifel ↑1100%). Backing: gateway proxies S6
  `GET /api/v1/news/trending-entities` over `nlp_db.entity_mentions` (22,581/24h) + S7 ticker enrichment.
  Route `services/api-gateway/src/api_gateway/routes/signals.py`. **Genuinely populated.**

---

## Prioritized data backlog (to make the intelligence layer real)

1. **[P0] Fix the contradiction rollup JOIN (Gap 1).** One-line read-side change unlocks the keystone
   `recent_contradiction_count` for 65 entities and the entire "Live Catalysts" differentiator screen.
   Also fixes the same join in `claim_repository.py` / `contradiction.py` (confidence formula + per-entity
   contradiction lookups are silently empty too). Add the missing FK as a follow-up to prevent recurrence.
2. **[P1] Set `SERVICE_ACCOUNT_TOKEN` on the api-gateway (Gap 5a).** Restores Morning Briefing AND turns
   on `has_ai_brief` for the screener (Gap 3). One env var.
3. **[P1] Default the entity graph canvas to depth=1 (Gap 4).** Removes the AGE depth-2 504 on hub
   instruments; lazy-load depth=2. Backend follow-up: bounded VLE traversal for hubs (~76x faster per prior
   investigation).
4. **[P2] Let the next 02:00 UTC run populate `volatility_30d` + `returns_adjustment_quality` (Gap 2).**
   Self-healing — no action required unless a demo needs it sooner (then bump
   `COMPUTED_METRICS_REFRESH_HOUR_UTC` and recreate market-data).
5. **[P2] Alert coverage thinness.** `has_active_alert` = 7/669 is genuine sparseness, not a bug — a
   product/data-volume question (more alert rules / lower thresholds), not a pipeline fix.

### Strategic verdict on the keystone
The Bloomberg-differentiator "Live Catalysts" screen is blocked by a **single one-line JOIN bug**, not by
a missing pipeline. Contradictions are being generated continuously (5293 in the last 7 days across 65
entities); the screener just never sees them because the read query joins the wrong table. This is the
highest-leverage, lowest-cost fix in the entire backlog.
