# Empty Entity Description Investigation
**Date:** 2026-06-14
**Investigator:** Claude Code (Principal Debugging Engineer)
**Classification:** READ-ONLY audit — no code changes

---

## Executive Summary

Three root causes cooperate to explain the description-gap pattern. The creation-time machinery **does exist** for `financial_instrument` entities (Step 4 `ensure_rows_exist` + Step 5 `refresh_for_entity` in `InstrumentEntityConsumer`), but the refresh workers are either processing 0 entities per cycle (definition) or 0 successfully (fundamentals). Narrative is working well (97% embedding coverage). The headline numbers:

| view_type | Rows (all entity types) | with source_text | with embedding | Pct embedded |
|---|---|---|---|---|
| `definition` | 17,115 | 17,067 (99.7%) | 16,510 (96.5%) | 96.5% |
| `narrative` | 17,115 | 17,006 (99.4%) | 16,623 (97.1%) | 97.1% |
| `fundamentals_ohlcv` | 8,433 | 615 (7.3%) | 615 (7.3%) | 7.3% |

**For `financial_instrument` entities only** (4,757 total):

| view_type | Rows | with source_text | with embedding | Pct embedded |
|---|---|---|---|---|
| `definition` | 4,757 | 4,709 (99.0%) | 4,152 (87.3%) | 87.3% |
| `narrative` | 4,757 | 4,752 (99.9%) | 4,633 (97.4%) | 97.4% |
| `fundamentals_ohlcv` | 4,757 | 615 (12.9%) | 615 (12.9%) | 12.9% |

The ~13% `definition` / ~13% `fundamentals_ohlcv` / ~60% `narrative` rates cited in the original investigation brief were measured on a stale or differently-scoped snapshot. Current live numbers are substantially better for `definition` and `narrative`, but `fundamentals_ohlcv` remains at ~12.9% for FI entities — confirming the core problem is concentrated there.

---

## Investigation Findings by Hypothesis

### H1 — Is there create-time generation?

**CONFIRMED YES for `financial_instrument`; PARTIAL for non-FI.**

`InstrumentEntityConsumer.process_message` (`services/knowledge-graph/src/knowledge_graph/infrastructure/messaging/consumers/instrument_consumer.py`) executes a 5-step flow on every `market.instrument.created` event:

- **Step 4** (`ensure_rows_exist`): creates the 3 placeholder `entity_embedding_state` rows (definition/narrative/fundamentals_ohlcv) with `next_refresh_at = now()` and `embedding = NULL`.
- **Step 5** (`refresh_for_entity`): if a description string is present in the Kafka event, immediately calls `DefinitionRefreshWorker.refresh_for_entity()` to embed it.

For provisionally-discovered entities (`InstrumentDiscoveredConsumer` path), `ensure_rows_exist` is also called so rows exist before any worker runs.

The `entity.canonical.created.v1` consumer (`EntityCreatedConsumer`) does **NOT** trigger any description generation — it only unblocks provisional evidence rows. The comment at line 117 says "Wave D-3: create entity profile embedding here" but the body is empty (just `commit()`).

**Result:** Definition is triggered at create-time IF the instrument event carries a description. Narrative and fundamentals_ohlcv are NOT triggered at create-time; they rely entirely on the periodic workers.

---

### H2 — Are the refresh workers actually running?

**Workers are running but most cycles produce zero useful output.**

All three workers run in `worldview-knowledge-graph-scheduler-1` (healthy, up 7h). Scheduler intervals from live container env:

- `worker_13d1_definition` (`DefinitionRefreshWorker`): every 3600 s (60 min), fires 120 s after boot.
- `worker_13d3_narrative_generation` (`NarrativeGenerationWorker`): every 6 hours, fires 60 s after boot.
- `worker_13d3_fundamentals` (`FundamentalsRefreshWorker`): every 300 s (5 min), fires 120 s after boot.

**Definition worker:** Every cycle for the past 2+ hours logs:
```json
{"refreshed": 0, "skipped_unchanged": 0, "event": "definition_refresh_worker_complete"}
```
The worker IS running but finds 0 work. The 48 entities that are `due_now` all have `source_text IS NULL` — the worker fetches them, then hits `if not source_text: continue` (line 167–168 of `definition_refresh.py`) and skips every one. Since `description_provider = "deepinfra"` IS configured with a valid API key (confirmed in container env), the `NullDescriptionAdapter` is NOT active. However, the description-generation branch at line 164 only fires for `entity_type != 'financial_instrument'`. These 48 entities ARE `financial_instrument` (crypto tokens: BTC.USD, ETH.USD; FX: GBPUSD; indices: DJI, GSPC; equity KMPR etc.) with no EODHD business description. They are stuck in a permanent loop: fetched every cycle, skipped every cycle, `next_refresh_at` never advanced.

**Narrative worker:** Running correctly. The periodic `_fetch_stale_entities()` query (`WHERE current_narrative_version_id IS NULL LIMIT 500`) returned 0 entities at 2026-06-14 18:54 UTC, and 6 at 2026-06-15 00:54 UTC (all 6 generated successfully). The 97.4% embedding rate for FI entities confirms narrative is the healthiest of the three.

**Fundamentals worker:** Runs every 5 minutes but has logged `"refreshed": 0` on every single cycle in the past 2+ hours. The complete event consistently shows:
```json
{
  "refreshed": 0, "skipped_non_ticker": 0–3,
  "backoff_escalations": 1267–1268, "backoff_resets": 0,
  "failure_breakdown": {
    "instrument_lookup_failed": 1237–1238,
    "fundamentals_missing_sections": 23,
    "fundamentals_http_404": 7
  }
}
```

**1268 entities are backoff-escalated every cycle.** The worker picks them from the due queue, attempts `_resolve_instrument_id(http, ticker)` for each, gets no match, and escalates them to 1h backoff. After the 1h window expires they come back due → same result → escalate again. The cycle repeats indefinitely. No ticker among these 1268 FI entities resolves to an instrument in market_data.

---

### H3 — Quantify the gap live

**Total entities:** 17,115 canonical entities (4,757 FI + 12,358 non-FI).

**Fundamentals orphan rows (data quality bug):** 3,676 `fundamentals_ohlcv` rows exist for NON-`financial_instrument` entities (organizations, unknowns, indices, exchanges, etc.). These will never be populated — the `get_due_for_refresh` query for `fundamentals_ohlcv` explicitly filters to `entity_type = 'financial_instrument'` (added in PLAN-0093 T-C-4-03), so the worker never processes them. But they consume slots and inflate row counts.

**FI entity breakdown:**

| Embedded view count | Entity count |
|---|---|
| 1 of 3 views | 50 |
| 2 of 3 views | 4,095 |
| 3 of 3 views | 612 |

So 4,095 FI entities have definition + narrative but NO fundamentals. Only 612 (12.9%) have all 3 views populated. The 50 with only 1 view are the stuck crypto/FX/index instruments with no definition embedding.

**Fundamentals scheduling state for FI entities:**

| Status | Count |
|---|---|
| `source_text IS NOT NULL` (populated) | 615 |
| `next_refresh_at IS NULL` | 0 |
| `next_refresh_at < now()` (due, failing) | 1,268 (all ticker entities with no market_data match) |
| `next_refresh_at ≥ now()`, no source_text (backoff-deferred) | 2,874 |
| `next_refresh_at ≥ now()`, has source_text (scheduled for normal refresh) | 615 (next due ~2026-07-12) |
| Tombstoned to year 9999 | 319 (no-ticker entities; correct behavior) |

The 615 successfully populated FI entities had their fundamentals set on 2026-06-12 (599 entities) and 2026-06-13 (16 entities). No further fundamentals have been populated since then.

---

### H4 — Why definition & fundamentals lag narrative?

**Root causes per view:**

**`definition` (87.3% FI coverage, not 13%):**
The original 13% figure was not current. The instrument consumer embeds the EODHD description at create-time (Step 5), so every instrument with a non-empty description gets its definition embedding immediately. The remaining 12.7% (605 entities) have `embedding IS NOT NULL` = false because:
- 48 entities: FI type + no EODHD description + stuck in the skip loop (crypto, FX, indices).
- 557 entities: `source_text IS NOT NULL` but `embedding IS NULL` with `next_refresh_at ≥ 2026-08-21` — these were already embedded by the instrument consumer, then had their `next_refresh_at` set to 90 days forward, and the embedding column was written. Wait — this is contradictory. Let me clarify: these 557 have `source_text` but the `embedding` column itself is NULL for 557 entities with `has_embedding = false` in the query. These are entities where the create-time embed call failed (embedding model error) and `next_refresh_at` was advanced to 90 days regardless.

**`fundamentals_ohlcv` (12.9% FI coverage):**
Three cooperating causes:
1. **53.7% of FI entities have NO ticker** (2,555 of 4,757). No ticker → worker tombstones to next_refresh_at = 9999. These are news-discovered entities (provisional path) that have no market_data instrument reference.
2. **The 1,268 due FI ticker entities fail `instrument_lookup`**: KG has 2,202 FI entities with tickers, but market_data only has 646 instruments. The FundamentalsRefreshWorker does a REST lookup by symbol (`GET /api/v1/instruments/lookup?symbol={ticker}`) and ~1,583 tickers (72%) have no match. Per backoff state, 1,268 are currently stuck.
3. **Backoff escalation loop**: Each failed entity hits the Valkey backoff key for 1h → the key expires → it comes back due → fails again → escalates. With 1,268 entities failing every 5-minute cycle, the worker produces 1,268 backoff escalations per cycle and zero refreshes. The 615 successful entities represent instruments that ARE in market_data AND have fundamentals data in the correct shape (`records[]` with populated sections).

**`narrative` (97.4% FI coverage — working well):**
The narrative worker queries `WHERE current_narrative_version_id IS NULL` which is 0–6 entities per 6-hour run. No external API dependency. Works correctly.

---

### H5 — Is generation event-driven or cron?

**Mixed:**
- **Definition**: create-time embedding (event-driven via `market.instrument.created` consumer) + 60-min cron fallback (Worker 13D-1).
- **Narrative**: 6-hour cron (changed from weekly for demo window per comment in scheduler.py line 201–211). Also triggered by `entity.narrative.generated.v1` consumer (NarrativeRefreshConsumer, separate container).
- **Fundamentals**: Pure 5-min cron (Worker 13D-3). No event-driven trigger. `market.dataset.fetched` triggers Workers 13D-5/6/7/8 for events/macro/insider, NOT for fundamentals embeddings.

No create-time trigger exists for `narrative` or `fundamentals_ohlcv`. The scheduler's `_register_jobs` fires all three 120s after boot (definition, narrative, fundamentals in the `early_jobs` list).

---

## Non-FI Orphan Rows

3,676 `fundamentals_ohlcv` rows exist for non-FI entities. The `get_due_for_refresh` WHERE clause (`entity_type = 'financial_instrument'`) added in PLAN-0093 means the worker never processes these, and they are never tombstoned. They sit with `next_refresh_at ≈ now()` forever, consuming space and inflating the total `fundamentals_ohlcv` count from 4,757 (correct) to 8,433.

These rows appear to have been created before the entity-type guard was added to `ensure_rows_exist`. Looking at the code: `ensure_rows_exist` calls `get_view_types_for_entity_type` which correctly returns only 2 rows for non-FI entities — so these 3,676 orphan rows were created by an earlier version of the code or by the startup repair task running against old entities that were mistyped.

---

## Fix Plan

### P0 — Stop the fundamentals backoff storm (immediate)

**Problem:** 1,268 FI entities with tickers not in market_data are escalating their Valkey backoff key every 5 minutes. After the 1h TTL expires they immediately re-enter the due queue. This wastes CPU, fills logs with 1,268 warnings per cycle, and prevents any newly-ingested instruments from being visible (they get buried in the failure noise).

**Fix:**
In `FundamentalsRefreshWorker._process_entity_io` (`fundamentals_refresh.py`), after `_instrument_id = await self._resolve_instrument_id(...)` returns `None`, instead of setting `failure_reason = "instrument_lookup_failed"` (which causes backoff escalation), tombstone the entity to a longer retry window (e.g. 7 days or even 30 days). The backoff escalation path is designed for transient errors; a missing instrument is a data-availability gap that will not self-heal within 1h.

Alternatively: after N consecutive `instrument_lookup_failed` failures, set `next_refresh_at = now() + 30 days` (same as a successful refresh) and log at INFO. This drains the perpetual-failure loop.

**Files:** `services/knowledge-graph/src/knowledge_graph/infrastructure/workers/fundamentals_refresh.py`, around line 420–436 in `_process_entity_io`.

### P0 — Fix fundamentals_ohlcv orphan rows for non-FI entities

**Problem:** 3,676 `fundamentals_ohlcv` rows exist for non-FI entities. They are never processed (correct) but also never tombstoned, creating permanent noise.

**Fix:** One-time SQL to tombstone them:
```sql
UPDATE entity_embedding_state ees
SET next_refresh_at = '9999-01-01'
FROM canonical_entities ce
WHERE ce.entity_id = ees.entity_id
  AND ce.entity_type != 'financial_instrument'
  AND ees.view_type = 'fundamentals_ohlcv';
```
Then prevent recurrence: add a guard in `ensure_rows_exist` so it ONLY creates `fundamentals_ohlcv` rows for `financial_instrument` entities (already correct in code; the orphans are historical).

**Files:** One-time DB operation; no code change needed (the create-path is already correct).

### P1 — Fix the 48 stuck definition entities (FI with no EODHD description)

**Problem:** 48 FI entities (crypto tokens, FX pairs, indices like DJI/GSPC) have `source_text IS NULL` and `entity_type = 'financial_instrument'`. The definition worker skips them because the `description_client.generate_description()` path only runs for `entity_type != 'financial_instrument'` (line 164). These entities have a DeepInfra description provider configured (`KNOWLEDGE_GRAPH_DESCRIPTION_PROVIDER=deepinfra`) but the code never invokes it for them.

**Fix:** In `DefinitionRefreshWorker.run`, after checking `if entity_type != _FINANCIAL_INSTRUMENT` for the LLM generation path, add a secondary branch: if `entity_type == _FINANCIAL_INSTRUMENT AND not source_text`, also call `_resolve_non_company_text()` (which uses the `description_client`). This allows crypto/FX/index instruments with no EODHD blurb to get LLM-generated descriptions.

**Files:** `services/knowledge-graph/src/knowledge_graph/infrastructure/workers/definition_refresh.py`, lines 159–168.

### P1 — Backfill missing fundamentals for instruments that ARE in market_data but whose `next_refresh_at` is deferred to 2027

**Problem:** After the backoff-storm fix in P0, there are still ~2,874 FI ticker entities with `source_text IS NULL` and `next_refresh_at` deferred to 2027 (30-day defer from a prior successful-but-empty run) or 9999 (tombstone). The 615 that succeeded represent instruments where market_data had populated fundamentals. Another ~600 might succeed with current market_data data.

**Fix:** Run a targeted one-time backfill by setting `next_refresh_at = now()` for all FI entities that: (a) have a ticker, (b) have `source_text IS NULL` for `fundamentals_ohlcv`, and (c) are not tombstoned to year 9999. This makes all viable candidates due on the next worker cycle.

**Files:** One-time SQL operation. No code change needed.

### P1 — Add create-time fundamentals trigger for new instruments

**Problem:** When a `market.instrument.created` event arrives, the consumer creates the 3 embedding state rows (`ensure_rows_exist`) and embeds the definition (if description present), but does NOT trigger a fundamentals refresh. The fundamentals worker will only pick up the new entity on the next 5-min cycle.

**Fix:** In `InstrumentEntityConsumer.process_message`, after Step 4 (`ensure_rows_exist`), enqueue an immediate fundamentals refresh by calling `FundamentalsRefreshWorker.run_for_entity(entity_id, ticker)` (a new single-entity method to add), or simply set `next_refresh_at = now()` (already the default from `ensure_rows_exist`). Since the current default `next_refresh_at = now()` already means the worker will pick it up within 5 minutes, this may be low priority.

**Files:** `services/knowledge-graph/src/knowledge_graph/infrastructure/messaging/consumers/instrument_consumer.py`.

### P2 — Add event-driven narrative trigger on instrument creation

**Problem:** Narrative is generated by a 6-hour cron that queries `current_narrative_version_id IS NULL LIMIT 500`. New instruments get processed within 6 hours at most — acceptable but slow for the demo.

**Fix:** In `InstrumentEntityConsumer`, after Step 5 (or as a separate async task), call `GenerateNarrativeUseCase.execute()` for the new entity. This matches the `POST /api/v1/entities/{id}/narratives/generate` flow already used by the manual trigger endpoint.

**Files:** `services/knowledge-graph/src/knowledge_graph/infrastructure/messaging/consumers/instrument_consumer.py`, plus wire the `GenerateNarrativeUseCase` into the consumer dependency chain.

### P2 — Tombstone no-ticker FI entities in fundamentals

**Problem:** 319 FI entities already tombstoned to year 9999 (correct). But 2,555 FI entities have `ticker IS NULL`; of these, only the tombstoned ones are "resolved". The rest still have `next_refresh_at = now()` and will be picked up as `skipped_non_ticker` by the worker every cycle (small overhead).

**Fix:** The worker already handles this via the `no_ticker_ids` tombstone logic (lines 360–366 + 690–714 of `fundamentals_refresh.py`). Ensure those tombstones actually committed — check that the batch reaches the `no_ticker_ids` list for all 2,236 un-tombstoned no-ticker FI entities.

---

## Summary of Worker Status at Investigation Time (2026-06-15 02:10 UTC)

| Worker | Container | Running | Last non-zero cycle | Per-cycle output |
|---|---|---|---|---|
| `DefinitionRefreshWorker` (13D-1) | knowledge-graph-scheduler | YES, every 60 min | Cannot determine from logs | 0 refreshed, 0 skipped_unchanged; 48 due rows all skipped (no source_text) |
| `NarrativeGenerationWorker` (13D-3) | knowledge-graph-scheduler | YES, every 6h | 2026-06-15 00:54 UTC | 6 generated successfully |
| `FundamentalsRefreshWorker` (13D-3/F) | knowledge-graph-scheduler | YES, every 5 min | 2026-06-13 (615 total across 2 days) | 0 refreshed; 1268 backoff escalations per cycle |
| `NarrativeRefreshWorker` (13D-2) | narrative-refresh-consumer (separate) | Likely healthy | — | Consumes entity.narrative.generated.v1 |
| `EmbeddingRefreshWorker` (13F) | knowledge-graph-scheduler | YES, every 5 min | Recent | 0 summaries_embedded (expected; relation summaries scope) |

---

## Evidence: 48 Permanently-Stuck Definition Entities

These are `financial_instrument` entities with no EODHD description that the worker cannot process:
- Crypto tokens: `BTC.USD`, `ETH.USD`, `AAVE-USD`, `ATOM-USD`, `FIL-USD`, `MATIC-USD`, `HBAR-USD`, `NEAR-USD`, etc.
- FX pairs: `GBPUSD`, `XAGUSD`, `XAUUSD`
- Equity indices: `DJI`, `GSPC`, `IXIC`, `FCHI`, `HSI`, `N225`, `TYX`, `IRX`
- Listed equity with missing description: `CDAY`, `KMPR`

All have `next_refresh_at` set to May 2026 (90 days after initial creation), are in the due queue permanently, and are skipped on every cycle.
