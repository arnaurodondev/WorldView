# KG Deep-Quality Investigation — 2026-07-16 (S6 extraction / S7 KG)

**Scope**: Knowledge-graph quality on the lean single-node prod cluster
(`intelligence_db`, AGE graph `worldview_graph`). Read-only on prod; code fixes
on branch `fix/kg-deep-quality`.

> **Access caveat (important)**: during this session the Hetzner firewall was
> dropping the reviewer's source IP (cellular IP oscillated to
> `174.194.131.29`; SSH:22 and API:6443 both timed out — confirmed dropped, not
> refused). I could **not** re-measure live numbers. The scorecard below carries
> the **2026-07-15 live numbers** (prior audit `2026-07-15-prod-review-data-quality.md`,
> node time ~1 day ahead) as the baseline. Every fix here is code-level +
> unit-tested and does **not** require live access; the live re-measure + any
> data cleanup are listed as follow-ups to run once the firewall admits the IP.

---

## KG quality scorecard (2026-07-15 live baseline)

| Metric | Value | Notes |
|---|---|---|
| Description coverage — person | **18%** (99/547) | worst bucket |
| Description coverage — product | **24%** (16/67) | |
| Description coverage — organization | **32%** (276/865) | |
| Description coverage — place | 43% (106/249) | |
| Description coverage — financial_instrument | 80% (572/712) | healthy |
| Description coverage — sector | 97% (38/39) | healthy |
| Fabrication rate (person bios) | **~1 in 12** (Fouquet→STMicro; actually ASML) | confident-wrong |
| `entity_type='unknown'` count | **~150** clearly-typable | no re-typing path existed |
| Relation summary coverage | 53% (244/459); 60% flagged stale | worker behind ingestion |
| definition embeddings | 100% (2761/2761) | healthy |
| narrative embeddings | 99% (2739/2761) | 22 missing |
| fundamentals_ohlcv embeddings | **0%** (0/713 populated) | D1 — silent-success empty builder |
| AGE vs relational | 2761 vertices vs 2753 entities (8 orphan); 445 edges vs 459 relations | small projection lag |
| provisional_entity_queue | 2393 resolved / 595 noise / 114 failed / 29 pending | 114 retry-exhausted |
| Duplicate/junk canonicals | 4 pairs (e.g. `NYSE: BCS`) | D9 |

---

## FIXED this session (branch `fix/kg-deep-quality`, tested)

### 1. Worker 13K — `EntityRetypeWorker` (the missing re-typing path)
The ~150 `entity_type='unknown'` rows (`Interactive Brokers Group, Inc.`,
`ISM Services PMI`, `Coffee`, `Palladium`, `European Commission`, …) had **no
re-classification path**: the provisional-enrichment pipeline types an entity
exactly once at promotion and never revisits the `unknown` bucket, and `unknown`
rows are excluded from type-filtered retrieval and typed graph traversals.

New periodic worker (30 min, batch 100, gated on `retype_enabled`, LLM-gated):
- **Phase 1 (read replica)** `list_unknown_entities(limit)` — oldest first.
- **Phase 2 (no session)** re-runs the SAME `extract_entity_profile` extraction
  LLM the promotion path uses; maps the raw type through a new shared,
  side-effect-free helper `resolve_canonical_entity_type()` (extracted from the
  inline logic in `persist_enrichment` so the two paths can never diverge).
- **Phase 3 (write)** guarded `UPDATE … WHERE entity_type='unknown'` (never
  clobbers a concurrently-typed row) + `ensure_rows_exist()` seeds the correct
  `entity_embedding_state` rows so the newly-typed entity becomes visible to the
  definition/narrative refresh workers (which is what generates its description).

**Safety**: only ever moves a row OUT of `unknown` (cannot corrupt existing good
types); rows the LLM still can't classify are left untouched (no churn) and
retried next cycle; tickerless company-class results resolve to `organization`
(FR-12 canonical type), never a bogus tickerless `financial_instrument`.

**Files**:
- `services/knowledge-graph/src/knowledge_graph/infrastructure/workers/entity_retype.py` (new)
- `.../workers/provisional_enrichment_core.py` — new `resolve_canonical_entity_type()` helper
- `.../intelligence_db/repositories/canonical_entity.py` — `list_unknown_entities()`, `retype_unknown_entity()`
- `.../scheduler/scheduler.py` — construct + register `worker_13k_entity_retype`
- `.../config.py` — `retype_enabled`, `worker_retype_interval_s`, `worker_retype_batch_size`
- tests: `tests/unit/infrastructure/workers/test_entity_retype.py` (new, 11),
  `tests/unit/infrastructure/test_scheduler.py` (+2 registration tests, helper updated)

**Deploy note**: additive, off nobody's critical path, defaults to enabled. No
migration. Needs the extraction DeepInfra key present (now provisioned) to infer
types; with no LLM the scheduler runs a no-op stub. Not deployed (per task).

---

## Analysis of the description-coverage collapse (root cause, no code change needed yet)

The `DefinitionRefreshWorker` already grew the right fix on 2026-07-15
(`get_due_for_refresh(..., backfill_missing_description=True)`): it now also
claims rows whose `canonical_entities.description` is NULL/empty regardless of
`next_refresh_at`, and writes a (news-grounded) description back. Why coverage
was still 18–32%:

1. **The fix is < 1 day old** relative to the baseline snapshot and drains at
   `worker_embedding_batch_limit=200` per **60-min** cycle. With ~1500
   undescribed non-FI entities that is ~8 cycles ≈ 8 h to converge — it was
   simply mid-drain. **Expected to self-heal**; re-measure to confirm.
2. **JOIN blind spot (real risk)**: `get_due_for_refresh` INNER JOINs
   `entity_embedding_state`. Any entity created **without** a `definition`
   embedding-state row is invisible to the worker forever. Worker 13K's
   `ensure_rows_exist()` closes this for re-typed rows; a one-off
   `ensure_rows_exist` backfill over ALL entities missing a definition row is
   recommended (see plan P2).
3. **401-degradation**: if the description DeepInfra key was placeholder/401
   during the window, `_resolve_non_company_text` fell back to the deterministic
   `"<name> is a <type>."` template — non-empty, so it *would* populate
   `description`, but with a useless stub. The internal-JWT + DeepInfra keys are
   now provisioned; re-measure fabrication AND stub-rate on a fresh sample.

---

## Flagged with plan (not fixed — needs live access and/or is higher-risk)

Priority order (P0 = do first once the firewall admits the IP):

- **P0 — Re-measure the scorecard live** and confirm Worker 13K + the
  description backfill are converging. Queries: coverage by `entity_type`;
  `count(*) WHERE entity_type='unknown'`; `count(*) WHERE description ILIKE
  '% is a %.'` (stub-template rate); fabrication spot-check on 20 fresh person
  bios (grep for `is the (CEO|Chief Executive|Chairman|President) of`).

- **P1 — fundamentals_ohlcv embeddings 0/713 (D1)**: the source-text builder
  emits empty text while `last_refreshed_at` is stamped current — classic
  audit-returns-success-persists-nothing. Add a guard: refresh must FAIL LOUDLY
  (or skip without stamping success) when `source_text` is empty. Highest
  semantic-search leverage. Fix in `fundamentals_refresh.py` +
  `get_due_for_refresh` fundamentals branch.

- **P1 — executive-role fabrication guard (D5)**: post-generation validator for
  person descriptions — if the bio asserts `is the CEO/Chairman/President of
  <Org>`, keep the claim only when the `(person, role, org)` triple is
  supported by the entity's own `relation_evidence_raw`/news evidence; otherwise
  strip the role clause or fall back to the hedged template. Lives in the
  description adapter / `DefinitionRefreshWorker._resolve_non_company_text`.
  Prompt-level; must be tested against the live adapter — do NOT ship blind.

- **P2 — definition-row backfill**: run `ensure_rows_exist` over every
  `canonical_entities` row missing a `definition`/`narrative` embedding-state row
  so the refresh worker can see them (closes the JOIN blind spot). Safe,
  idempotent (`ON CONFLICT DO NOTHING`). Can be a one-off script or a small
  periodic sweep.

- **P2 — duplicate/junk canonical merge (D9)**: 4 pairs incl. `NYSE: BCS`
  (raw exchange-prefixed junk name) → merge into `Barclays PLC`; `ANZ Bank`/`ANZ
  Banking`; `XLI`; `Vanguard S&P 500 ETF` dup. Use the existing
  `scripts/kg_merge_org_fi_duplicates.py` normalization; **back up the affected
  rows + their relations/aliases first**, then merge relations onto the survivor.

- **P2 — relation-summary backlog + staleness (D7)**: 47% of relations lack a
  summary and 60% are `summary_stale`. Drain the SummaryWorker backlog (raise
  `summary_worker_force_regen_batch_size` temporarily) and confirm the worker
  keeps up with ingestion rate.

- **P3 — provisional_entity_queue 114 failed / 29 pending (D8)**: inspect the
  114 retry-exhausted mentions; many are FI-anchoring deferrals waiting on an S2
  instrument row that never arrived. Requeue the genuinely resolvable ones after
  the market-data instrument backfill; discard confirmed noise.

- **P3 — AGE↔relational reconciliation**: 8 orphan `entity` vertices (2761 vs
  2753) and a ~14-edge projection lag. Small; the AgeSyncWorker should converge.
  Add a periodic assertion/metric (vertex count == entity count) so drift alarms.

- **P3 — relation precision/density**: baseline healthy on predicate types
  (no OOV/junk predicates observed in the 2026-07-15 sweep), but graph is a
  sparse star-topology that starves `path_insights`. Re-measure self-loops
  (`subject_entity_id = object_entity_id`), OOV predicate rate, and mean node
  degree live; the ~29% extraction `api_error` rate from a prior finding should
  be re-checked against the current live model.

- **P3 — prediction_markets.event_id 0/101 (D6)**: relational event FK unset
  despite a populated `prediction_events` table. S3-owned; cross-listed here
  because it blocks event-level KG rollups.

---

## Does it need a KG rebuild + backfill/reprocess?

**No full rebuild.** The graph structure and embeddings are sound. What is
needed is **incremental backfill/convergence**, all achievable on the live graph
without a rebuild:
1. Let Worker 13K drain the `unknown` bucket (ships in this branch).
2. Let the description backfill (already deployed 2026-07-15) converge; add the
   P2 definition-row `ensure_rows_exist` backfill to close the JOIN blind spot.
3. Fix + backfill the fundamentals_ohlcv embeddings (P1 — the only 0% view).
4. One-off dedup merge for the 4 junk pairs (P2, back up first).

## Top remaining KG quality risk

**The `fundamentals_ohlcv` embedding view is 100% empty (0/713) while reporting
success (D1).** Semantic/vector search over fundamentals+price context is
entirely non-functional for every instrument, and nothing alarms because the
refresh loop stamps `last_refreshed_at` regardless. It is the single largest
silent-quality hole and the highest-leverage next fix after the re-typing worker.
