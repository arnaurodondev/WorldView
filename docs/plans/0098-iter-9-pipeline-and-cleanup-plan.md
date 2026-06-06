---
id: PLAN-0098
title: ITER-9 Follow-ups IV — Phase-D Pipeline Restoration + R40 Debt + screen_field_metadata + Chat-Eval Concerns + Code-Review P2 Punch List
prd: inline (see §0)
status: draft
created: 2026-05-27
updated: 2026-05-27
revision_note: |
  Revised 2026-05-27 (round 2) — folded in the two just-landed audits:
  (a) `docs/audits/2026-05-27-plan-0098-data-pipelines-and-bp-583-investigation.md`
  (§A1-§A5 NLP/AGE/fundamentals/revenue root causes + §B screen_field_metadata
  shape) and (b) `docs/audits/2026-05-27-plan-0097-unblock-chat-eval.md`
  (migration 022 unblock verdict + Q1-Q4 partial results — 2 NEW concerns:
  NVDA/AMD batch row-mix and Q4 latency 289s). T-W1-01 is SHIPPED in commit
  `7e8ec9a8` (chunk_search.py R40 extension; BP-583 already taken by that
  fix). W3 BP renumbered to BP-585. NEW W5 added for the two chat-eval
  concerns. TRACKING.md PLAN-0098 row added at `draft 1/5`.
source_audits:
  - docs/audits/2026-05-27-plan-0097-phase-d-chat-eval.md (BLOCKER: migration 022 references non-existent `dividend_summary` — handled by parallel Option-A agent commit 8e4a5d0d)
  - docs/audits/2026-05-27-plan-0097-phase-d-code-review.md (1 P1 + 7 P2s — full punch list, all with file:line)
  - docs/audits/2026-05-27-plan-0097-phase-d-slo-check.md (5 data-pipeline FAILs: entity_mentions=0, fundamentals JSONB empty, AGE not synced, sentinel rows invisible, screen_field_metadata constraint violation)
  - docs/audits/2026-05-27-plan-0097-p2-punchlist-and-docs.md (2 doc P2s)
  - docs/audits/2026-05-27-plan-0097-unblock-chat-eval.md (LANDED — migration 022 fix verdict + Q1-Q4 partial results + 2 NEW P1 concerns)
  - docs/audits/2026-05-27-plan-0098-data-pipelines-and-bp-583-investigation.md (LANDED — pipeline §A1-§A5 + screen_field_metadata §B root causes)
---

# PLAN-0098 — ITER-9 Phase-D Pipeline Restoration & Cleanup (revised)

## §0 — Inline PRD

> No separate PRD. This plan closes every open item left after PLAN-0097
> Phase D shipped W1-W4 but was unable to execute the chat-eval
> acceptance gate honestly because (a) migration 022 referenced a
> non-existent `dividend_summary` table and aborted (fixed in commit
> `8e4a5d0d`, see unblock audit), and (b) the live data pipelines are
> silently dead. PLAN-0098 is the remediation umbrella covering: the
> data-pipeline restorations (W2 — root causes now concrete per
> investigation §A1-§A5), the screen_field_metadata constraint
> violation (W3 — Option 1 coercion per §B), the R40 chunk_search
> extension (W1 — T-W1-01 already SHIPPED in `7e8ec9a8`), the two
> NEW P1 concerns from the partial chat-eval (W5 — batch row-mix +
> 289s latency), and the 7 Phase-D code-review P2s (W4).

### Problem statement (revised)

Phase-D adversarial code review + SLO check + the just-landed unblock
chat-eval surface five failure classes:

1. **P1 — R40 sentinel-tenant contract half-applied (LARGELY SHIPPED)**:
   Parallel agent already shipped the chunk_search.py R40 extension in
   commit **`7e8ec9a8`** (4 sites + 4 regression tests; BP-583 filed —
   note: the originally-promised BP-584 number for this work collided
   and the agent took BP-583, so PLAN-0098 W3 below uses **BP-585**).
   The broader cross-service grep sweep (T-W1-02) is still pending.
2. **P0 — Data pipelines silently dead (root causes now concrete)**:
   per investigation §A1-§A5 — `entity_mentions` blocked because
   mention objects are constructed without `tenant_id` in deeper
   blocks (the NER post-stamp at `article_consumer.py:583-585` does
   not cover all paths); AGE temporal-event sync isn't happening
   despite PLAN-0096 W3 fix (reconciliation script not running OR
   sync worker not invoked post-restart); fundamentals freshness has
   no `FundamentalsRefreshWorker` and upstream ingest events stopped
   flowing; revenue JSONB is empty because the consumer writes rows
   without payload (Avro field mapping bug OR EODHD parsing fallback).
3. **CRIT — screen_field_metadata constraint** (renamed from BP-583
   to **BP-585**): root cause CONFIRMED at
   `services/market-data/src/market_data/app.py:190` and `:200` —
   `ScreenFieldMetadata` for `has_fundamentals` + `has_ohlcv` use
   `field_type="boolean"` but the constraint allows only
   `'numeric'`/`'text'`. Recommended fix (Option 1, no migration):
   coerce to `"numeric"` at write time.
4. **NEW P1 — Two chat-eval concerns** from the partial Q1-Q4 run
   (`docs/audits/2026-05-27-plan-0097-unblock-chat-eval.md` §3 + §5):
   (a) Q4 NVDA Q3 FY2025 row shows `$10.3B` which is actually AMD's
   value — a row-mix in the batch tool result, suspected in the
   `/v1/fundamentals/batch` handler. (b) Q4 latency `289s` despite
   `get_fundamentals_history_batch` being used — suspected intra-ticker
   serial fetch (3 sections × 2 tickers = 6 sequential reads) in
   `GetFundamentalsHistoryUseCase`.
5. **P2 — Phase-D code-review punch list (7 items)**: test-quality,
   minor defensiveness, doc fixes. Unchanged from prior draft.

### Goals (revised)

1. Restore the four data pipelines per investigation §A1-§A5 so the
   chat-eval acceptance gate (§5) can produce a defensible verdict.
2. Land BP-585 screen_field_metadata coercion (Option 1 — no migration).
3. Close the broader R40 grep sweep (T-W1-01 shipped; T-W1-02 + helper).
4. Fix the two chat-eval concerns (W5): batch row-mix + 289s latency.
5. Land all 7 Phase-D code-review P2s in ~3 commits.

### Non-goals

- Re-architecting the NLP consumer or the AGE bootstrap path — fixes
  follow the audit recommendations minimally.
- Long-term answer-quality CI (still PLAN-0075).
- New PRD features.

### Open questions (now resolved by inputs)

All `<TBD-investigation>` markers from the prior draft are RESOLVED:
- §A1 NLP stall — entity_mentions construction missing tenant_id in
  deeper blocks; see W2-T01.
- §A3 AGE Cypher unresponsive — reconciliation not invoked; see W2-T02.
- §A4 fundamentals freshness — no worker exists; see W2-T03.
- §A5 revenue JSONB — consumer payload-empty write; see W2-T04.
- §B screen_field_metadata — Option 1 coercion; see W3-T01.

Remaining decision: W2-T03 ships a **proper FundamentalsRefreshWorker**
(deferred from PLAN-0097 W1-T4 by the audit) OR documents the gap +
manual script. Default unless investigation §A4 dictates otherwise:
ship the worker (BP-578 path).

---

## §1 — Overview

**PRD**: inline (above)
**Services affected**: nlp-pipeline (S6), market-data (S2), rag-chat
                       (S8), knowledge-graph (S7), content-ingestion (S4
                       if FundamentalsRefreshWorker ships), docs
**Total waves**: **5** (W1-W5, was 4)
**Total estimated effort**: ~12 h engineering + 1 full docker rebuild
                            cycle + 1 chat-eval rerun (~30 min)
**Critical path**: W2 (data-pipeline restoration) + W5 (chat-eval P1s)
                   both gate the cross-cutting acceptance gate.
                   W1/W3/W4 are independent hygiene.

**Coordination note**: T-W1-01 SHIPPED in commit `7e8ec9a8` (chunk_search.py
R40 extension; 4 SQL sites + 4 regression tests). BP-583 was filed by
that fix; the screen_field_metadata bug PLAN-0098 W3 takes **BP-585**
(BP-584 is the next free slot for any new BP discovered in W2).

### Branch & commit hygiene

PLAN-0098 lands on `feat/plan-0098-pipeline-and-cleanup` (or remains on
the active in-progress branch if PLAN-0097 hasn't merged yet). Each
wave gets its own small commit set.

## §2 — Dependency Graph

```
        ┌────────────────────────────────────────────────────┐
        │ PLAN-0097 W1-W4 + commit 8e4a5d0d (migration 022   │
        │ dividend_summary unblock) + commit 7e8ec9a8        │
        │ (T-W1-01 chunk_search R40 extension, BP-583)       │
        └─────────────────────────────┬──────────────────────┘
                                      │
       ┌──────────────┬──────────┬────┴───────┬──────────────┬──────────┐
       ▼              ▼          ▼            ▼              ▼          ▼
   W1 (R40 sweep   W2 (data    W3 (BP-585    W4 (P2 punch   W5 (chat-eval
   tail —          pipeline    screen_field_ list — 3       NEW P1s —
   T-W1-01         §A1-§A5     metadata      commits)       batch row-mix
   SHIPPED         restorat.   coercion                     + 289s lat.)
   7e8ec9a8;       — 4 tasks)  Option 1)
   T-W1-02/03
   pending)
       │              │            │            │              │
       └──────┬───────┴────┬───────┘            │              │
              ▼            ▼                    │              │
       Cross-cutting acceptance gate (§5):      │              │
       chat-eval rerun on stack with W2+W5      │              │
       shipped. Pass criteria expanded — see §5.│              │
                                                │              │
       (W4 independent — docs+hygiene) ◄────────┘              │
                                                                │
       (W5 also independent of W4 — straight code+test) ◄───────┘
```

W2 + W5 are on the critical path for the acceptance gate. W1 tail,
W3, W4 are independent.

## §3 — Codebase State Verification (revised — concrete refs filled in)

| Reference | Type | Service | Actual current state | Plan target | Delta |
|-----------|------|---------|----------------------|-------------|-------|
| chunk_search.py R40 sites | code | nlp-pipeline | **SHIPPED** in commit `7e8ec9a8`: 4 SQL sites in `chunk_search.py` extended with PUBLIC_TENANT_ID OR-leg; 4 regression tests in `tests/unit/infrastructure/test_tenant_id_chunk_isolation.py::TestChunkANNRepositoryPublicTenantSentinel`; BP-583 filed | n/a — confirm landed | done |
| Other R40 sites (sweep) | code | nlp-pipeline + rag-chat + portfolio | UNKNOWN — broader grep sweep not yet run beyond chunk_search + news_query | run `grep -rn "tenant_id IS NULL OR tenant_id = " services/`; patch any hit; add an architecture test | code |
| NLP entity_mentions construction | code | nlp-pipeline | per investigation §A1: NER post-stamp at `services/nlp-pipeline/src/nlp_pipeline/infrastructure/messaging/consumers/article_consumer.py:583-585` covers ONE path; deeper EntityMention construction sites in the same module (and downstream blocks) build mentions without `tenant_id`, so persist hits the NOT NULL constraint and silently drops | grep all `EntityMention(` construction sites; stamp tenant_id at every site; add a pre-persist validation that raises a typed error if any mention lacks tenant_id | code + tests |
| AGE TemporalEvent sync | runtime + ops | knowledge-graph | per investigation §A3: PLAN-0096 W3 fix (connection invalidate) shipped; reconciliation script exists at `services/knowledge-graph/scripts/reconcile_age_temporal_events.py`; but it is not being invoked AND the sync worker isn't running post-restart | run the reconcile script + verify sync worker is registered in worker startup; if absent, wire it back; if registered, capture why post-restart invocation drops | ops + (likely) small code wire-up |
| Fundamentals freshness | code | content-ingestion | per investigation §A4: no `FundamentalsRefreshWorker` exists; ingest events stopped flowing upstream; `scripts/refresh_fundamentals.py` (PLAN-0097 T-W1-04) is manual-only; BP-578 is MITIGATED not fixed | decide: SHIP a proper periodic worker (4-6 h work — preferred per audit) OR document gap + cron-wrap the script (minimal) | new worker OR ops |
| Revenue JSONB hydration | code | market-data | per investigation §A5: consumer at `services/market-data/src/market_data/infrastructure/messaging/consumers/fundamentals_consumer.py` writes rows without payload — Avro field mapping bug OR EODHD parsing fallback path is silently dropping the `revenue` key | trace the Avro→domain mapping; fix the missing key; add a regression test asserting JSONB shape after sample ingest | code + test |
| screen_field_metadata field_type | code | market-data | per investigation §B: `services/market-data/src/market_data/app.py:190` (has_fundamentals) and `:200` (has_ohlcv) set `field_type="boolean"`; constraint `ck_screen_field_metadata_field_type` admits only `'numeric'`/`'text'`; refresh fails every ~60s | **Option 1 (preferred — NO migration)**: coerce `field_type="numeric"` at write time in `app.py` lines 190+200; document the 0/1 value mapping in metadata | code + test |
| Q4 NVDA/AMD batch row-mix | code | market-data | per unblock audit §3: Q4 answer shows `NVDA Q3 FY2025 = $10.3B` which is AMD's value; row indices appear to collide between tickers in `services/market-data/src/market_data/api/routers/fundamentals.py` batch handler | reproduce against `/v1/fundamentals/batch?tickers=NVDA,AMD&periods=4`; verify per-ticker rows are keyed by ticker not by global row index; fix the keying | code + integration test |
| Q4 latency 289s | code | market-data + rag-chat | per unblock audit §5: Q4 used `get_fundamentals_history_batch` (W3 win) but still took 289s vs 60s p99 target; suspect intra-ticker serial fetch in `GetFundamentalsHistoryUseCase` (3 sections × 2 tickers = 6 sequential reads) | wall-clock instrument per-ticker fetch in the batch handler; parallelize the 3 section reads inside `GetFundamentalsHistoryUseCase` via `asyncio.gather`; reduce to one round-trip per ticker | code + test + EXPLAIN ANALYZE |
| Phase-D P2 punch list (7 items) | mixed | rag-chat + market-data + knowledge-graph + docs | unchanged from prior draft — see §4 W4 | unchanged | unchanged |
| Chat-eval acceptance gate | code | tests/validation | shipped (PLAN-0095/96/97); partial Q1-Q4 verdict in unblock audit (BASELINE for §5 compare) | re-run full suite after W2+W5 ship on a foreground bash (not nested agent — see unblock audit §6) | execution gate |

## §4 — Sub-Plans

---

### Wave W1 — R40 debt closure (T-W1-01 SHIPPED)

**Goal**: Confirm the chunk_search.py R40 extension landed; complete
the broader grep sweep to ensure no other R40 violation sites exist;
extract a shared helper for future R40 regression tests.

**Depends on**: PLAN-0097 W4 T-W4-01 (R40 third-OR-leg pattern) in main.
**Estimated effort**: ~1 h (T-W1-01 done; T-W1-02 + T-W1-03 remain).
**Architecture layer**: nlp-pipeline infrastructure repositories + any
                        other service touched by sweep findings.
**Branch**: `feat/plan-0098-w1` (T-W1-01 commit `7e8ec9a8` already on
            ancestor branch).
**Migration**: NO
**Docker rebuild**: NO (T-W1-01 already deployed; T-W1-02 only if hits)

#### Tasks

##### T-W1-01: chunk_search.py R40 extension — **SHIPPED**

**Status**: DONE in commit **`7e8ec9a8`**.
**Type**: impl + test (landed)
**BP filed**: **BP-583** (note: BP-584 originally reserved here; agent
took BP-583 instead — PLAN-0098 W3 renumbered to BP-585 below).

**Landed files**:
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/nlp_db/repositories/chunk_search.py`
  — 4 SQL surfaces extended with PUBLIC_TENANT_ID OR-leg (matches
  PLAN-0097 W4 T-W4-01 pattern from `news_query._ENTITY_ARTICLES_SQL`).
- `services/nlp-pipeline/tests/unit/infrastructure/test_tenant_id_chunk_isolation.py::TestChunkANNRepositoryPublicTenantSentinel`
  — 4 new regression tests (one per SQL surface + one defensive
  anonymous-branch test).

**Acceptance check**: chunk-search returns rows tagged with
`PUBLIC_TENANT_ID` to authenticated callers — verified by the
4 regression tests.

##### T-W1-02: Sweep for OTHER R40 anti-pattern sites

**Type**: investigate + code (if any hits)
**depends_on**: none
**blocks**: T-W1-03

**Target areas**:
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/`
- `services/rag-chat/src/rag_chat/infrastructure/`
- `services/portfolio/src/portfolio/infrastructure/`

**Audit reference**: `2026-05-27-plan-0097-phase-d-code-review.md` §2.3
("other repos not exhaustively scanned").

**What to build**: run

```bash
grep -rn "tenant_id IS NULL OR tenant_id = " services/
grep -rn "tenant_id IS NULL OR.*tenant_id.*CAST" services/
```

Patch any hit with the same third OR-leg. Add a repo-wide architecture
test `tests/architecture/test_no_two_legged_tenant_filter.py` that scans
the source tree and fails CI if a new violation appears.

**Acceptance check**:
- Grep returns ZERO hits without the third OR-leg.
- Architecture test passes; deliberately re-introducing a violating
  string in a fixture file flips it red.

##### T-W1-03: Shared R40 regression assertion helper

**Status**: **DEFERRED** unless T-W1-02 sweep reveals ≥2 new R40 sites
across services. Justification: PLAN-0098 should not pre-build
infrastructure that current grep coverage may not justify. Re-evaluate
after T-W1-02 lands.

#### Validation gate

- [x] T-W1-01 commit `7e8ec9a8` landed; 4 regression tests pass
- [ ] T-W1-02 grep sweep returns zero hits OR all hits patched
- [ ] Architecture test `test_no_two_legged_tenant_filter.py` passes
- [ ] T-W1-03 deferred (re-evaluate after T-W1-02)

#### Compounding updates

- `services/nlp-pipeline/.claude-context.md` — pitfall pointing at
  BP-583 (R40 half-application class).
- `docs/BUG_PATTERNS.md` — BP-583 already filed by `7e8ec9a8`; no new BP.
- `docs/plans/TRACKING.md` — PLAN-0098 row update.

---

### Wave W2 — Data pipeline restoration (root causes concrete)

**Goal**: Restore the four data-pipeline SLO failures per investigation
§A1-§A5 so the chat-eval gate can produce a defensible verdict.

**Depends on**: PLAN-0097 W4 in main; investigation audit landed.
**Estimated effort**: ~5 h (NLP §A1 60-90m + AGE §A3 30-60m +
                       FundamentalsRefreshWorker 4-6 h OR cron 30m +
                       revenue JSONB §A5 60-90m).
**Architecture layer**: nlp-pipeline application + knowledge-graph
                        application/ops + content-ingestion application
                        + market-data infrastructure
**Branch**: `feat/plan-0098-w2`
**Migration**: NO (none anticipated; investigation did not surface a
               schema migration need)
**Docker rebuild**: YES — nlp-pipeline + market-data + content-ingestion

#### Tasks

##### T-W2-01: NLP entity_mentions tenant_id stamping (P0)

**Type**: impl + test
**Audit ref**: investigation §A1.

**Root cause**: per §A1, mention objects are constructed without
`tenant_id` in deeper code blocks of `article_consumer.py`. The NER
post-stamp loop at lines **583-585** of
`services/nlp-pipeline/src/nlp_pipeline/infrastructure/messaging/consumers/article_consumer.py`
covers only one code path — other `EntityMention(...)` construction
sites in the same module (and any downstream block that materialises
mentions for persist) build the object without setting `tenant_id`, so
the NOT NULL constraint (alembic 0020) fires and the row is silently
dropped.

**Target files**:
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/messaging/consumers/article_consumer.py`
  — every `EntityMention(...)` construction site
- `services/nlp-pipeline/src/nlp_pipeline/domain/...` — add a pre-persist
  validation (raises a typed `MissingTenantIdError` if any mention lacks
  tenant_id; turns a silent drop into a loud bug)
- `services/nlp-pipeline/tests/unit/.../test_article_consumer_*.py`
  — regression test asserting that ALL construction paths stamp tenant_id

**What to build**:
1. `grep -n "EntityMention(" services/nlp-pipeline/src/` — enumerate
   every construction site.
2. Ensure every site passes `tenant_id` (PUBLIC_TENANT_ID sentinel for
   legacy payloads, real tenant for new payloads).
3. Add a pre-persist validation in the repository (or the use case)
   that raises if any mention lacks tenant_id.
4. Regression test that builds a representative article through each
   construction path and asserts every produced mention has tenant_id.

**Acceptance check**: `SELECT count(*) FROM entity_mentions WHERE
created_at > now() - interval '1 hour'` > 0 within 5 min of redeploy.

##### T-W2-02: AGE TemporalEvent reconciliation drain (P1)

**Type**: ops + (likely) small code wire-up
**Audit ref**: investigation §A3.

**Root cause**: per §A3, despite PLAN-0096 W3 shipping the connection
invalidate fix, the sync isn't actually happening post-restart. Either
(a) the existing `services/knowledge-graph/scripts/reconcile_age_temporal_events.py`
needs running, OR (b) the periodic sync worker isn't being invoked
after container restart (worker registration drop or startup-order bug).

**Target files**:
- `services/knowledge-graph/scripts/reconcile_age_temporal_events.py`
  — invoke (`--dry-run` then real)
- `services/knowledge-graph/src/knowledge_graph/app.py` (or wherever
  workers register) — verify the periodic AGE sync worker is registered
  and starts after `AgeBootstrap`

**Acceptance check**: `MATCH (n:TemporalEvent) RETURN count(n)`
returns the current SQL row count within 30 s.

##### T-W2-03: Fundamentals freshness — ship FundamentalsRefreshWorker (P1)

**Type**: new worker (decision: SHIP the worker per audit §A4 preference)
**Audit ref**: investigation §A4 + BP-578.

**Target files** (NEW):
- `services/content-ingestion/src/content_ingestion/application/workers/fundamentals_refresh_worker.py`
  — periodic worker fanning out to `POST /api/v1/ingest/trigger` for
  the top-500 by market cap with exponential backoff on 429 (per
  BP-114) and a `FUNDAMENTALS_REFRESH_ENABLED` env flag for safe
  rollout
- `services/content-ingestion/src/content_ingestion/app.py` — register
  the worker in lifespan
- `services/content-ingestion/configs/docker.env` — `FUNDAMENTALS_REFRESH_ENABLED=true` + cadence vars
- regression test for the worker's batch-and-backoff loop

**Fallback (Option B — if §A4 audit recommends NOT shipping the
worker)**: cron-wrap the existing `scripts/refresh_fundamentals.py`
every 6 h via a compose sidecar; document the gap explicitly in
`docs/services/content-ingestion.md`.

**Acceptance check**: `SELECT count(*) FROM instruments WHERE
last_fundamentals_ingest_at > now() - interval '24 hours'` > 50% of
top-500 by market cap within 6 h of deploy.

##### T-W2-04: Revenue JSONB hydration fix (P1)

**Type**: impl + test
**Audit ref**: investigation §A5.

**Root cause**: per §A5, the consumer at
`services/market-data/src/market_data/infrastructure/messaging/consumers/fundamentals_consumer.py`
writes rows without payload — either the Avro field mapping is missing
the `revenue` key OR an EODHD parsing fallback path is silently
dropping it.

**Target files**:
- `services/market-data/src/market_data/infrastructure/messaging/consumers/fundamentals_consumer.py`
  — trace the Avro→domain mapping; fix the missing key
- `services/market-data/tests/unit/.../test_fundamentals_consumer_revenue_hydration.py`
  — regression test ingesting a sample payload and asserting `revenue`
  JSONB is non-empty post-write

**Acceptance check**: `GET /v1/fundamentals/{nvda_id}/history?periods=6`
returns non-null revenue on QUARTERLY rows.

#### Validation gate

- [ ] ruff + mypy clean on touched services
- [ ] T-W2-01..04 acceptance SQL queries all green
- [ ] No new errors in any container for 15 min post-deploy

#### Compounding updates

- `docs/services/nlp-pipeline.md` — entity_mentions tenant_id stamping
  contract.
- `docs/services/knowledge-graph.md` — AGE reconcile runbook.
- `docs/services/market-data.md` — revenue JSONB shape note.
- `docs/services/content-ingestion.md` — FundamentalsRefreshWorker.
- `.claude-context.md` files for each affected service — pitfall entries.
- `docs/BUG_PATTERNS.md` — BP-584 (NLP tenant_id stamping silent drop)
  + BP-586 (Avro `revenue` field mapping bug). BP-585 is reserved for W3.
- `docs/plans/TRACKING.md` — PLAN-0098 row update.

---

### Wave W3 — BP-585 screen_field_metadata coercion (Option 1)

**Goal**: Stop the every-60s `CheckViolationError`; restore the
screener field catalogue so `has_fundamentals` + `has_ohlcv` are
visible.

**Depends on**: investigation §B landed.
**Estimated effort**: ~1 h.
**Architecture layer**: market-data application bootstrap.
**Branch**: `feat/plan-0098-w3`
**Migration**: **NO** (Option 1 — write-time coercion only).
**Docker rebuild**: YES — market-data

#### Tasks

##### T-W3-01: Coerce `field_type` to `"numeric"` for boolean fields

**Type**: impl
**Audit ref**: investigation §B.

**Root cause CONFIRMED**: `services/market-data/src/market_data/app.py:190`
constructs `ScreenFieldMetadata` for `has_fundamentals` with
`field_type="boolean"`, and `:200` does the same for `has_ohlcv`. The
`ck_screen_field_metadata_field_type` CHECK constraint admits only
`'numeric'`/`'text'`, so the upsert raises `CheckViolationError` every
~60s.

**Target files**:
- `services/market-data/src/market_data/app.py` lines **190** + **200**
  — change `field_type="boolean"` → `field_type="numeric"`; document the
  0/1 value mapping inline (boolean serialised as 0/1 numeric for
  catalogue compatibility).
- Optional: add a note in the metadata payload (`description` or
  similar) saying "boolean — 0/1 encoded as numeric".

**Acceptance check**: `event=screen_fields_refresh_error` count over
15 min post-deploy == 0; `SELECT * FROM screen_field_metadata WHERE
field_name='has_fundamentals'` returns one row with `field_type='numeric'`.

##### T-W3-02: Regression test on `_get_static_screen_fields()`

**Type**: test
**depends_on**: [T-W3-01]

**Target files**: new test in
`services/market-data/tests/unit/.../test_screen_field_metadata_static_fields.py`.

**What to build**: import `_get_static_screen_fields()` (or whatever
function in `app.py` returns the static catalogue), assert that EVERY
returned field's `field_type` is in `{"numeric", "text"}`. This prevents
future boolean/percent/etc. drift.

**Acceptance check**: test passes; deliberately changing a field back
to `"boolean"` flips it red.

#### Validation gate

- [ ] ruff + mypy clean
- [ ] T-W3-02 test passes
- [ ] Live `event=screen_fields_refresh_error` rate == 0 for 15 min
      post-deploy

#### Compounding updates

- `docs/services/market-data.md` — screen_field_metadata schema note +
  CHECK constraint enumeration + boolean-as-numeric coercion note.
- `services/market-data/.claude-context.md` — pitfall on field_type
  enum.
- `docs/BUG_PATTERNS.md` — **BP-585** (
  "screen_field_metadata CHECK constraint admits only numeric/text;
  boolean fields must be coerced to numeric 0/1 at write time —
  refresh worker fails silently every 60s otherwise").
- `docs/plans/TRACKING.md` — PLAN-0098 row update.

---

### Wave W4 — Phase-D code-review P2 punch list (7 items in ~3 commits)

**Unchanged from prior draft.** See prior §4 W4 entry — the 7 items
remain: classifier-drift nightly CI (T-W4-01a), parallel-resolve de-flake
(T-W4-01b), R36→R41 comment cleanup (T-W4-01c); fundamentals.py:222 None
handling (T-W4-02a), deploy-token flush `asyncio.wait_for` (T-W4-02b);
RAG_CACHE_DEPLOY_TOKEN docstring + Periodicity rendering note +
TRACKING.md "14→18 tables" (T-W4-03).

**Depends on**: none (independent of W1/W2/W3/W5).
**Estimated effort**: ~2 h.
**Branch**: `feat/plan-0098-w4`
**Migration**: NO
**Docker rebuild**: minor (rag-chat + market-data if T-W4-02 ships
                   alongside W2)

(Full T-W4-01..T-W4-03 task bodies are unchanged — see prior draft;
they are stable because the unblock audit + investigation audit did
not modify the P2 punch list.)

---

### Wave W5 — Chat-eval NEW P1 concerns (added in this revision)

**Goal**: Close the two NEW P1 concerns surfaced by the unblock audit's
partial Q1-Q4 chat-eval run: batch row-mix between tickers (Q4 data
bug) and 289s Q4 latency (perf bug).

**Depends on**: none (independent of W1/W2/W3/W4).
**Estimated effort**: ~3 h (~1 h reproduce + fix row-mix; ~2 h profile +
                       parallelize section reads).
**Architecture layer**: market-data api + market-data application use cases
**Branch**: `feat/plan-0098-w5`
**Migration**: NO
**Docker rebuild**: YES — market-data

#### Tasks

##### T-W5-01: Batch tool NVDA/AMD row-mix fix (NEW P1)

**Type**: impl + integration test
**Audit ref**: `2026-05-27-plan-0097-unblock-chat-eval.md` §3.

**Symptom**: Q4 rendered `NVDA Q3 FY2025 = $10.3B` which is actually
AMD's value. Other rows in NVDA's column are correct ($22.1B Q4 FY25,
$26B Q1 FY26, $46.7B Q2 FY26). Looks like a row-shuffle in the batch
result — NOT an LLM misread (rest of mapping is right).

**Target files**:
- `services/market-data/src/market_data/api/routers/fundamentals.py`
  — batch handler; verify per-ticker rows are keyed by ticker, not by
  global row index across the combined `asyncio.gather` result.
- new integration test:
  `services/market-data/tests/integration/test_fundamentals_batch_no_row_mix.py`
  — hit `/v1/fundamentals/batch?tickers=NVDA,AMD&periods=4` against a
  seeded test DB; assert each ticker's rows match the singular endpoint
  output for that ticker exactly (no cross-ticker bleed).

**Repro recipe**: `curl /v1/fundamentals/batch?tickers=NVDA,AMD&periods=4`
+ compare against per-ticker `/v1/fundamentals/{id}/history?periods=4`.

**Acceptance check**: integration test green; manual repro shows
NVDA Q3 FY2025 returns NVDA's actual value (not $10.3B).

**BP**: file BP-587 (or next-free) — "batch endpoint row-mix between
tickers; rows must be keyed by ticker not by global index".

##### T-W5-02: Q4 latency 289s — parallelize intra-ticker section fetch (NEW P1)

**Type**: impl + perf test + EXPLAIN ANALYZE
**Audit ref**: `2026-05-27-plan-0097-unblock-chat-eval.md` §5.

**Symptom**: Q4 took 289s vs 60s p99 target despite using the batch
tool. PLAN-0097 W3 parallelized **ticker** resolution but the 3
**section** reads per ticker (income_statement + balance_sheet +
cash_flow) likely still serialize inside `GetFundamentalsHistoryUseCase`.
For Q4: 2 tickers × 3 sections = 6 sequential reads.

**Target files**:
- `services/market-data/src/market_data/application/use_cases/get_fundamentals_history.py`
  (or wherever the use case lives) — wrap the 3 section reads in
  `asyncio.gather` so they fan out concurrently per ticker.
- `services/market-data/src/market_data/api/routers/fundamentals.py`
  batch handler — add wall-clock instrumentation (structlog
  `event=fundamentals_batch_fetch_timing` with per-ticker duration)
  to validate the win and surface future regressions.
- new unit test:
  `test_get_fundamentals_history_parallelizes_section_reads.py`
  — mock 3 section repos with 100ms each, assert wall-clock < 0.25s
  (serial bound would be ≥0.3s); use the `asyncio.Event` barrier
  pattern from W4 T-W4-01b (not wall-clock) to avoid CI flake.

**EXPLAIN ANALYZE pre-step**: run
`EXPLAIN ANALYZE SELECT * FROM income_statements WHERE instrument_id =
:iid ORDER BY period_end_date DESC LIMIT 8` against the live DB to
confirm the composite index from migration 019 + 022 ANALYZE is being
chosen. If not, the latency win from parallelization will be masked by
a sequential scan.

**Acceptance check**:
- Wall-clock instrumentation shows per-ticker fetch < 1s on the
  acceptance gate stack.
- Chat-eval Q4 latency < 60s on the next full rerun.
- EXPLAIN shows the composite index is used.

**BP**: file BP-588 (or next-free) — "intra-ticker section reads
serialize inside use case; parallelize via asyncio.gather".

#### Validation gate

- [ ] ruff + mypy clean on market-data
- [ ] T-W5-01 integration test passes; manual repro confirms no row-mix
- [ ] T-W5-02 unit test passes; wall-clock instrumentation logs < 1s
      per ticker
- [ ] EXPLAIN ANALYZE confirms composite index used

#### Compounding updates

- `docs/services/market-data.md` — batch endpoint row-keying contract
  + intra-ticker parallelization note.
- `services/market-data/.claude-context.md` — pitfalls on both bugs.
- `docs/BUG_PATTERNS.md` — BP-587 (row-mix) + BP-588 (intra-ticker
  serial fetch).
- `docs/plans/TRACKING.md` — PLAN-0098 row update.

---

## §5 — Cross-Cutting Acceptance Gate (revised)

**Trigger**: W2 + W5 BOTH ship (W1/W3/W4 are hygiene, do NOT block).

**Why W2 + W5 are both gating**: the unblock audit's partial Q1-Q4 run
already demonstrated the qualitative wins from PLAN-0097 are real
(Q4 produces a real comparison table; tool selection now correct).
But two NEW concerns prevent declaring victory: (a) the NVDA Q3 row is
wrong (data bug — W5-T01), and (b) p99 latency is 289s vs the 60s
target (perf bug — W5-T02). W2 is required so the pre-gate SQL
spot-checks pass (entity_mentions > 0, fundamentals fresh, revenue
JSONB hydrated, AGE synced).

**Command** (run from foreground bash, NOT nested in agent — per
unblock audit §6 recommendation):

```bash
RAG_CHAT_BASE_URL=http://localhost:8000 \
  RAG_COMPLETION_CACHE_DISABLED=true \
  DEBUG_SKIP_CLASSIFIER=true \
  APP_ENV=dev \
  pytest tests/validation/chat_eval/test_aggregate_score.py 2>&1 | tee /tmp/chat_eval.log &
disown
```

**Pre-gate SQL spot-checks** (unchanged from prior draft — 5 queries
covering entity_mentions, AGE sync, fundamentals freshness, revenue
JSONB, screen_field_metadata errors).

**Pass criteria (revised — folds in unblock partial)**:
- All 5 pre-gate SQL checks green.
- chat-eval verdicts: ≥6 USEFUL, HARMFUL=0.
- **Q4 must produce a real comparison** (baseline from unblock
  partial: ALREADY ✓ — both columns plausible quarterly, no
  annualized leak).
- **Q4 NVDA Q3 FY2025 must show NVDA's actual revenue, NOT $10.3B**
  (W5-T01 must ship; the $10.3B value is AMD's, not NVDA's).
- **p99 < 60s** (baseline from unblock partial: ❌ 289s on Q4 — W5-T02
  + W2-T04 + ANALYZE from PLAN-0097 W3 must combine to clear this).
- No new error log lines in nlp-pipeline / market-data /
  knowledge-graph / rag-chat for 15 min post-deploy.

**On fail**: investigate which specific gate is still red, file a
sub-bug, iterate the relevant wave.

---

## §6 — Risk Register (revised — non-gating risks dropped, two added)

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| W3 Option 1 coercion (boolean→numeric) confuses downstream screener filter UI that assumed `field_type='boolean'` | Low | Low | Document the 0/1 mapping in the field metadata `description`; verify the screener frontend treats numeric 0/1 correctly (likely already does — pre-existing behaviour). |
| W2-T01 entity_mentions retroactive backfill of dropped rows | Medium | Medium | Out of scope — fix only forward; legacy dropped rows replayed via existing `scripts/replay_stuck_articles.py` (PLAN-0096 W4 T-W4-02) if needed. |
| W2-T02 AGE worker re-wire collides with PLAN-0096 W3 connection-invalidate fix | Low | Medium | Investigation §A3 must explicitly confirm the new wire-up layers on top of the W3 fix (not replaces it). |
| W2-T03 FundamentalsRefreshWorker reintroduces BP-578 quota-burn | Low | Medium | Top-500 only with exponential backoff (BP-114); `FUNDAMENTALS_REFRESH_ENABLED` env flag for safe rollout. |
| W2-T04 revenue JSONB fix surfaces other missing Avro field mappings (cash_flow, balance_sheet) | Medium | Medium | Audit §A5 mentions only revenue; widen the regression test to assert all expected JSONB keys exist; file follow-up BPs if needed. |
| W5-T01 row-mix fix changes the batch response shape | Low | Low | Keep the response shape stable — only fix the keying; rag-chat tool result parsing is unchanged. |
| W5-T02 parallelizing section reads exhausts asyncpg pool | Medium | Medium | Cap concurrency at 3 per ticker (3 sections — already small); monitor `event=fundamentals_batch_fetch_timing` for pool exhaustion warnings post-deploy. |
| BP-583 already taken by the chunk_search fix; downstream docs may cite the original "BP-584" reservation | Low | Low | This revision explicitly renumbers: BP-583 = chunk_search R40 fix (already filed); BP-584 = NLP tenant_id stamping (W2-T01); BP-585 = screen_field_metadata coercion (W3); BP-586 = revenue JSONB (W2-T04); BP-587 = batch row-mix (W5-T01); BP-588 = intra-ticker serial fetch (W5-T02). Update any references in subsequent commits. |

---

## §7 — Owner stub

- **PLAN-0098 owner**: Arnau Rodon (`arnaurodondev@gmail.com`)
- **W1 owner**: Arnau (T-W1-01 SHIPPED in `7e8ec9a8`; T-W1-02 pending)
- **W2 owner**: Arnau (all 4 tasks)
- **W3 owner**: Arnau
- **W4 owner**: Arnau
- **W5 owner**: Arnau
- **Acceptance-gate executor**: Arnau (foreground bash + `disown`)

---

## §8 — Next revise-prd round (revised)

The prior revise-prd promised to fold in §A1/§A3/§A5 and §B — DONE in
this round. Remaining items for any future revise-prd round:

1. After W2-T03 lands, decide if BP-578 can be marked FIXED (worker
   ships) or stays MITIGATED (cron fallback).
2. After the post-W2+W5 chat-eval rerun, fold the new verdict into §5
   as the new baseline; if NEW concerns emerge, draft PLAN-0099.
3. If W2-T04 surfaces additional Avro field mapping bugs in
   balance_sheet or cash_flow, file follow-up tasks under PLAN-0099
   (out of scope for PLAN-0098 to avoid scope creep).

End of PLAN-0098 (revised 2026-05-27).
