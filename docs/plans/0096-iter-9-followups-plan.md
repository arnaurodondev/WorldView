---
id: PLAN-0096
title: ITER-9 Follow-ups — PLAN-0095 Phase-D Gaps + PLAN-0095 W4 Tail + AGE/DLQ Carry-Forwards
prd: inline (see §0)
status: ready
created: 2026-05-26
updated: 2026-05-26
source_audits:
  - docs/audits/2026-05-26-iter-9-phase-d-adversarial-qa.md
  - docs/audits/2026-05-26-iter-9-multi-issue-investigation-report.md
  - docs/plans/0095-iter-9-pipeline-quality-plan.md (waves already shipped)
  - docs/audits/2026-05-26-age-temporal-event-sync-investigation.md (LANDED — folded into W3 by revision 2026-05-26)
  - docs/audits/2026-05-26-nlp-dlq-stall-investigation.md (LANDED — folded into W4 by revision 2026-05-26)
  - docs/audits/2026-05-26-plan-0096-revision-report.md (revision audit)
---

# PLAN-0096 — ITER-9 Follow-ups

## §0 — Inline PRD

> No separate PRD doc. This plan closes the open Phase-D gaps surfaced by the
> ITER-9 adversarial QA pass and finishes the deferred PLAN-0095 W4 tail
> (MarketDataClient JWT-mint backoff + NLP relevance-scoring API key), plus
> two carry-forward live-infra findings (AGE TemporalEvent sync, NLP DLQ
> stall) that the adversarial QA flagged but could not investigate in-branch.

### Problem statement

The 2026-05-26 adversarial QA pass on PLAN-0095 returned **CONDITIONAL PASS**
with 3 P1 gaps:

1. **Finding 1 (P1)** — `query_fundamentals` defaults `period_type=None` on
   `balance_sheet` and `cash_flow`. No current caller queries those sections,
   but the next caller that comes along will silently inherit the same mixed-
   periodicity bug PLAN-0095 W1 fixed for `income_statement`. Defensive
   default at the repo layer kills the trap forever.
2. **Finding 5 (P1)** — NLP pipeline `content.article.stored.v1` DLQ was
   reported at 94 stalled messages with `entity_mentions=0`; the adversarial
   pass could not verify against live infra. A parallel investigation is now
   running.
3. **Finding 6 (P1)** — AGE TemporalEvent `_bootstrap_age_labels` relabeled
   **0 of 14,822** nodes (external-QA finding from commit `53b2c8a1`); no
   follow-up fix is visible since. A parallel investigation is now running.

Plus two **non-blocking** items from PLAN-0095 W4 that did not ship before W3
landed:

- **T-W4-02 (deferred)** — MarketDataClient JWT-mint exponential backoff to
  fix the `PriceImpactLabellingWorker` cold-start race against api-gateway.
- **T-W4-04 (deferred)** — Wire `NLP_PIPELINE_RELEVANCE_SCORING_API_KEY` from
  the same `DEEPINFRA_API_KEY` other workers consume (currently empty → falls
  back to Ollama → Ollama down → starvation).

Plus a per-instrument freshness column (`T-W1-07` was descoped from PLAN-0095
when EODHD-deep-dive landed; lifted here as **T-W1-02**) so future operator
queries can find stale fundamentals without scraping section tables.

### Goals

1. Close all 3 Phase-D P1 gaps (defensive period_type, DLQ stall, AGE sync).
2. Land the two deferred PLAN-0095 W4 tasks so cluster-1 NLP workers stop
   starving.
3. Add `instruments.last_fundamentals_ingest_at` so the freshness signal we
   already log is also queryable.
4. Once W1+W2 are deployed, re-run chat-eval as the **wave-level acceptance
   gate for PLAN-0095 W1 + W2** (deferred T-W2-04 from PLAN-0095).

### Non-goals

- Refactoring `_most_recent_financial_row_with_period` to honour the
  `period_type_*` columns added in PLAN-0095 T-W1-04 — these remain
  observability-only (deferred per Phase-D Finding 11).
- Re-architecting the snapshot to split QUARTERLY vs ANNUAL TTM rows
  (deferred per PLAN-0095 T-W1-04 alt-(b)).
- Migrating the path-insight worker off APScheduler.

### Open questions

- **AGE investigation findings** (RESOLVED 2026-05-26): root cause =
  **AGE schema cache survives `session.commit()`**. `_bootstrap_age_labels`
  creates the `TemporalEvent` vlabel in the same `AsyncSession` that the
  subsequent `_run_phase('temporal_events')` MERGEs against, but the AGE
  `cypher()` plpgsql function caches the schema lookup for the lifetime of
  that connection — so the MERGEs reference a label the cache doesn't see
  and silently match zero nodes. Fix = invalidate the underlying connection
  between bootstrap and phases (Option A in the investigation). W3 below is
  now concrete.
- **NLP DLQ investigation findings** (RESOLVED 2026-05-26): root cause =
  **`entity_mentions.tenant_id NOT NULL`** (migration 0020) blocking
  pre-PLAN-0086 articles whose Avro payload predates the tenant_id field.
  94 messages are stuck in-flight on `content.article.stored.v1` (not in
  DLQ — IntegrityError is treated as retryable so offsets never advance).
  Fix = substitute a well-known PUBLIC tenant sentinel when the payload
  lacks `tenant_id`. W4 below is now concrete.

---

## §1 — Overview

**PRD**: inline (above)
**Services affected**: market-data (S2), nlp-pipeline (S6), knowledge-graph (S7),
                       rag-chat (S8 — chat-eval gate only, no code change here)
**Total waves**: 4
**Total estimated effort**: ~5 h engineering + 1 docker rebuild cycle +
                            1 chat-eval rerun (~30 min wall-clock)
**Critical path**: W1 (defensive period_type + freshness migration) can
                   land in parallel with W2 (NLP worker tail). W3 (AGE) and
                   W4 (NLP DLQ) are independent — but both block on their
                   respective in-flight investigations.

### Branch & commit hygiene

PLAN-0095 W1 + W2 are still mid-flight on `feat/plan-0093-remediation`. This
plan should land on a fresh branch `feat/plan-0096-followups` off **main**
after PLAN-0095 W1 + W2 merge. If it lands earlier, the same PLAN-0094 W2
WIP mypy commit-blocker applies — see PLAN-0095 §1.

## §2 — Dependency Graph

```
                ┌──────────────────────────────────────────────┐
                │ PLAN-0095 W1 + W2 in main                    │
                │ (T-W1-01/02/03/04/05/06 + T-W2-01/02/03)     │
                └─────────────────────┬────────────────────────┘
                                      │
            ┌─────────────────────────┼──────────────┬────────────────┐
            ▼                         ▼              ▼                ▼
W1 (market-data:            W2 (nlp-pipeline:  W3 (AGE temporal      W4 (NLP article
    defensive period_type   JWT-mint backoff   event sync —          stall —
    + freshness column      + relevance API    invalidate conn       PUBLIC_TENANT_ID
    + docs cleanup)         key wiring)        between bootstrap     sentinel + replay
            │               │                  + phases; + recon     tool + retry-storm
            │               │                  script)               alert)
            └───────┬───────┘                  │                     │
                    ▼                          ▼                     ▼
       Cross-cutting acceptance gate:                 (independent)
       chat-eval p99 < 60 s rerun
       (PLAN-0095 W1+W2 deferred T-W2-04)
```

W3 and W4 can run in parallel; W3+W4 do NOT block the cross-cutting chat-eval
acceptance gate (that gate measures PLAN-0095 W1+W2 latency, not AGE/DLQ).
Both W3 and W4 are no-longer-blocked as of 2026-05-26 — investigations
landed and are folded in (see §0 Open questions).

## §3 — Codebase State Verification

| Reference | Type | Service | Actual current state | Plan target | Delta |
|-----------|------|---------|----------------------|-------------|-------|
| `query_fundamentals` default `period_type` | repo fn | market-data | `services/market-data/src/market_data/infrastructure/db/repositories/fundamentals_query.py:74-76` (PLAN-0095 T-W1-01) — `period_type: PeriodType \| None = None`; `if period_type is not None: stmt = stmt.where(...)` | overload / wrapper: when `section in {BALANCE_SHEET, CASH_FLOW}` AND `period_type is None`, default to `PeriodType.QUARTERLY` rather than leaving the trap open | code change |
| `_most_recent_financial_row_with_period` | helper | market-data | `services/market-data/src/market_data/infrastructure/db/fundamentals_snapshot_writer.py` (snapshot derivation; prefers ANNUAL) | **no change** (snapshot path is observability-only; preserves behaviour) | none |
| `instruments.last_fundamentals_ingest_at` | column | market-data | **does not exist** (PLAN-0095 T-W1-07 was descoped before merge) | NEW Alembic migration 021 — additive `TIMESTAMPTZ NULL`; consumer bumps on every successful UPSERT | NEW migration |
| `fundamentals_consumer.py` success site | code | market-data | `services/market-data/src/market_data/infrastructure/messaging/consumers/fundamentals_consumer.py:575` (success log site, verified in PLAN-0095) | also `UPDATE instruments SET last_fundamentals_ingest_at = utc_now() WHERE id = :iid` inside the same UoW | code change |
| `MarketDataClient` JWT mint | code | nlp-pipeline | mints JWT once at startup (cold-start race against api-gateway); no backoff today | 3-retry exponential backoff (1 s / 2 s / 4 s) OR defer construction to first `run_once()` | code change |
| `NLP_PIPELINE_RELEVANCE_SCORING_API_KEY` | env | nlp-pipeline | empty in deployed `docker.env` → falls back to Ollama → Ollama down → starvation | export from same source as `DEEPINFRA_API_KEY` (mirror existing pattern; do NOT hardcode literal value) | env change + docker-compose |
| `_bootstrap_age_labels` session reuse | code | knowledge-graph | `services/knowledge-graph/src/knowledge_graph/infrastructure/workers/age_sync_worker.py:447-479` — calls `session.commit()` at L478 but reuses the same `AsyncSession` for the immediately following `_run_phase(...)` calls (L266-L282 in `run()`); AGE plpgsql schema cache survives the commit → MERGEs reference an invisible label → 0/14,822 relabeled (investigation §"Root Cause: Most Likely") | invalidate the underlying connection after the commit: `await session.connection().invalidate()` (or close + re-open) before the first `_run_phase()`. Path noted in audit as `infrastructure/scheduler/age_sync_worker.py`; actual path is `infrastructure/workers/age_sync_worker.py` (drift corrected here). | code change |
| `entity_mentions.tenant_id` NOT NULL | migration | nlp-pipeline | `services/nlp-pipeline/alembic/versions/0020_entity_mentions_tenant_not_null.py` (already shipped) — enforces NOT NULL; legacy Avro payloads (pre-PLAN-0086) have no `tenant_id` field → `IntegrityError` → 504 retries → 94 stuck messages on `content.article.stored.v1` (DLQ is empty — IntegrityError is retryable so offset never commits) | NO new migration; instead substitute a well-known PUBLIC tenant sentinel in the consumer when payload+headers both lack `tenant_id`. | runtime fix (no migration) |
| `article_consumer` tenant_id extraction | code | nlp-pipeline | `services/nlp-pipeline/src/nlp_pipeline/infrastructure/messaging/consumers/article_consumer.py:454-458` — `raw_tenant = headers.get("tenant_id") or value.get("tenant_id") or None`; when both missing, `tenant_id` stays `None`; downstream NER stamping at L563-565 is gated on `if tenant_id is not None:` so the entity-mention rows go in with `tenant_id=None` and trip the NOT NULL constraint at the repo write site | substitute `PUBLIC_TENANT_ID` sentinel when raw_tenant is None; WARN-log with article_id + topic offset so operators see legacy passthrough. | code change |
| PUBLIC tenant UUID sentinel | constant | libs/common | **does not exist** in `libs/common/src/common/ids.py` (verified 2026-05-26 — only `new_uuid7()` helper). Investigation report suggests `00000000-0000-7000-8000-000000000001` as the value; no canonical home today. | add `PUBLIC_TENANT_ID: Final[uuid.UUID] = uuid.UUID("00000000-0000-7000-8000-000000000001")` to `libs/common/src/common/ids.py` so the sentinel is reusable + dashboards can filter `WHERE tenant_id <> PUBLIC_TENANT_ID` to exclude legacy. | new constant in shared lib |
| Alerting infra | infra | observability | `infra/grafana/alerts/*.yml` (Grafana-managed, e.g. `kafka_stalled.yml`, `path_insight_stalled.yml`) AND `infra/prometheus/rules/*.yml` (Prometheus-evaluated). T-W4-03 target: Grafana alerts dir mirrors the existing pattern (R28 path-insight precedent). | add `nlp_dlq_retry_storm.yml` to `infra/grafana/alerts/` mirroring `path_insight_stalled.yml` shape. | new alert file |
| `docs/services/market-data.md` period_type | docs | docs | not updated for defensive default (PLAN-0095 only documented income_statement) | document the defensive QUARTERLY default for balance_sheet + cash_flow read paths | docs change |
| `services/market-data/.claude-context.md` | docs | docs | Pitfalls section updated by PLAN-0095 T-W1-05 (BP-543) | add Pitfalls entry: "repository defaults `period_type=QUARTERLY` on balance_sheet + cash_flow IF caller passes None — explicit `period_type=` overrides" (BP-546) | docs change |
| `docs/MASTER_PLAN.md` | docs | docs | generic architecture; no fundamentals detail | append a paragraph to the market-data section about the period_type contract + freshness column | docs change |
| `tests/validation/chat_eval/test_aggregate_score.py` | test | chat-eval | exists today as the verdicts + p99 gate harness | re-run after PLAN-0095 W1 + W2 + this plan's W1 + W2 deploy with `RAG_CHAT_BASE_URL=http://localhost:8000`; confirm verdicts count and `p99_seconds < 60.0` | execution gate (no code change) |

## §4 — Sub-Plans

---

### Wave W1 — Market-data defensive period_type + freshness tracking

**Goal**: Close Phase-D Finding 1 (P1) by defaulting `period_type=QUARTERLY`
at the repo layer for `balance_sheet` + `cash_flow` reads, then add
`instruments.last_fundamentals_ingest_at` so the freshness signal we already
log on every UPSERT becomes queryable. Plus the documentation drift cleanup
the Phase-D pass flagged (Finding 10).

**Depends on**: PLAN-0095 W1 (T-W1-01 introduced the `period_type` kwarg this
wave defends) must be live on the working branch.
**Estimated effort**: ~2 h (15 min defensive default + 45 min migration +
                       consumer wiring + 45 min docs + 15 min tests)
**Architecture layer**: application + infrastructure + Alembic
**Branch**: `feat/plan-0096-w1`
**Migration**: YES — **1 new Alembic revision** in
                `services/market-data/alembic/versions/`:
                - 021: `instruments.last_fundamentals_ingest_at TIMESTAMPTZ NULL`
                The current PLAN-0095 head is `020_snapshot_period_type_columns.py`
                (verified 2026-05-26); new revision is `021_*`.
**Docker rebuild**: YES — `market-data` image + `market-data-migrate` re-run

#### Tasks

##### T-W1-01: Defensive `period_type=QUARTERLY` default on balance_sheet + cash_flow (BP-546)

**Type**: impl
**depends_on**: PLAN-0095 T-W1-01 (the `period_type` kwarg must already exist)
**blocks**: T-W1-03 (docs)
**Target files**:
- `services/market-data/src/market_data/infrastructure/db/repositories/fundamentals_query.py:74-76` (the existing `if period_type is not None: stmt = stmt.where(...)` block)

**Audit reference**: Phase-D Finding 1 (P1) lines 15-31.

**What to build**:

Replace the existing `period_type` filter block with a defensive default:

```python
# Defensive default — balance_sheet and cash_flow tables mix QUARTERLY+ANNUAL
# rows at the same period_end_date (BP-546). If no caller-supplied period_type,
# fall through to QUARTERLY to prevent silent mixing. Income statement already
# requires explicit period_type from the use case (PLAN-0095 T-W1-02).
effective_period_type = period_type
if effective_period_type is None and section in {
    FundamentalsSection.BALANCE_SHEET,
    FundamentalsSection.CASH_FLOW_STATEMENT,
}:
    effective_period_type = PeriodType.QUARTERLY
if effective_period_type is not None:
    stmt = stmt.where(model_class.period_type == effective_period_type.value)
```

**Rationale**: PLAN-0095 fixed income_statement at the use-case layer
(T-W1-02). The Phase-D audit pointed out balance_sheet and cash_flow have no
current direct callers, but any future use case will silently inherit the
trap. Defaulting at the repo layer (lowest-level enforcement point) means
the next caller cannot regress. Income_statement is deliberately left
explicit — the use case already passes `period_type=QUARTERLY`, and adding a
repo default there would mask future explicit-`period_type=ANNUAL` callers.

**Acceptance check**:
- Unit test `test_query_fundamentals_defaults_balance_sheet_to_quarterly` in
  `services/market-data/tests/unit/infrastructure/db/test_fundamentals_query.py`
  — seed QUARTERLY + ANNUAL balance_sheet at same `period_end_date`; query
  with `period_type=None`; assert only quarterly row returned.
- Unit test `test_query_fundamentals_explicit_annual_overrides_default` —
  same seed; query with `period_type=PeriodType.ANNUAL`; assert annual row
  returned.
- Unit test `test_query_fundamentals_income_statement_no_default` — income
  query with `period_type=None` returns BOTH rows (no repo-level default
  for income; use case must pass explicit `QUARTERLY`).

##### T-W1-02: Alembic 021 — `instruments.last_fundamentals_ingest_at` + consumer wiring (BP-545 / deferred T-W1-07)

**Type**: migration + impl
**depends_on**: none
**blocks**: T-W1-03 (docs)
**Target files**:
- new `services/market-data/alembic/versions/021_instruments_last_fundamentals_ingest_at.py`
- `services/market-data/src/market_data/infrastructure/messaging/consumers/fundamentals_consumer.py:575` (success log site — also bump the column inside the same UoW)
- `services/market-data/src/market_data/infrastructure/db/models.py` (or wherever the Instrument ORM model lives — add the new field)

**Audit reference**: PLAN-0095 T-W1-07 (descoped before merge); EODHD
deep-dive §8 (lines 230-254); BP-545.

**What to build**:

Migration 021 — additive nullable column:

```python
def upgrade() -> None:
    op.add_column(
        "instruments",
        sa.Column("last_fundamentals_ingest_at", sa.DateTime(timezone=True), nullable=True),
    )

def downgrade() -> None:
    op.drop_column("instruments", "last_fundamentals_ingest_at")
```

Consumer wiring (same UoW as section writes — no dual write):

```python
# In fundamentals_consumer.py at the existing success site (~L575):
await session.execute(
    update(Instrument)
    .where(Instrument.id == instrument_id)
    .values(last_fundamentals_ingest_at=utc_now())
)
```

Use `common.time.utc_now()` per R10. Run inside the same UoW that wrote the
section rows; no outbox needed (no Kafka event).

**Operator queries this unlocks**:

```sql
SELECT ticker FROM instruments
 WHERE last_fundamentals_ingest_at < NOW() - INTERVAL '7 days'
   AND is_active;
```

**Acceptance check**:
- Alembic up→down→up cycle clean.
- Unit test `test_consumer_sets_last_fundamentals_ingest_at` in the existing
  consumer test file — process a payload; assert the column updates to
  approximately `utc_now()` (within 5 s).
- Manual: post a redeploy, query `SELECT count(*) FROM instruments WHERE
  last_fundamentals_ingest_at IS NOT NULL` and confirm it grows as the
  consumer processes the backlog.

##### T-W1-03: Documentation drift cleanup (Phase-D Finding 10)

**Type**: docs (no code change)
**depends_on**: [T-W1-01, T-W1-02]
**blocks**: W1 sign-off
**Target files**:
- `docs/services/market-data.md` — Fundamentals section
- `services/market-data/.claude-context.md` — Pitfalls
- `docs/MASTER_PLAN.md` — market-data subsection

**Audit reference**: Phase-D Finding 10 (P2) lines 192-208.

**What to build**:

1. **`docs/services/market-data.md`** — under the Fundamentals section, add a
   subsection "Period-type contract":
   > Fundamentals section tables (`income_statements`, `balance_sheets`,
   > `cash_flow_statements`) store both QUARTERLY and ANNUAL rows under the
   > same section enum, distinguished by `period_type`. The repository layer
   > (`query_fundamentals`) accepts an optional `period_type` filter. For
   > **`income_statement`** the use case (`GetFundamentalsHistoryUseCase`)
   > MUST pass `period_type=PeriodType.QUARTERLY` (PLAN-0095 T-W1-02).
   > For **`balance_sheet`** and **`cash_flow_statement`** the repo defaults
   > to QUARTERLY when no `period_type` is provided (PLAN-0096 T-W1-01,
   > BP-546). Future callers querying ANNUAL must pass it explicitly.

   Also add a short paragraph under "Freshness tracking":
   > Every successful fundamentals UPSERT bumps
   > `instruments.last_fundamentals_ingest_at` inside the same UoW (PLAN-0096
   > T-W1-02, BP-545). Operators can identify stale tickers with
   > `WHERE last_fundamentals_ingest_at < NOW() - INTERVAL '7 days'`.

2. **`services/market-data/.claude-context.md`** Pitfalls — add:
   > - `query_fundamentals` defaults `period_type=QUARTERLY` for
   >   `balance_sheet` and `cash_flow_statement` if the caller passes
   >   `None`. Pass `period_type=PeriodType.ANNUAL` explicitly if you need
   >   ANNUAL rows (PLAN-0096 W1 T-W1-01, BP-546).
   > - `income_statement` does NOT get the defensive default — the use case
   >   passes `period_type=QUARTERLY` explicitly (PLAN-0095 T-W1-02). New
   >   callers must do the same.

3. **`docs/MASTER_PLAN.md`** — in the market-data subsection (or add one if
   absent) include a single-sentence pointer:
   > Fundamentals query contract: see `docs/services/market-data.md`
   > §"Period-type contract" and §"Freshness tracking".

**Acceptance check**:
- `grep "BP-546" docs/services/market-data.md` returns a hit.
- `grep "BP-545" docs/services/market-data.md` returns a hit.
- `grep "BP-546" services/market-data/.claude-context.md` returns a hit.
- `grep -i "period-type contract" docs/MASTER_PLAN.md` returns a hit.

#### Validation gate

- [ ] ruff + mypy clean on `market-data`
- [ ] All existing market-data unit tests pass
- [ ] New unit tests pass (T-W1-01 x3 + T-W1-02 x1 = 4 new tests)
- [ ] Alembic up→down→up clean for revision 021
- [ ] Docker compose rebuild of `market-data` + `market-data-migrate` clean
- [ ] Three grep checks (T-W1-03) all return hits

#### Architecture compliance

- [ ] **R24** — only `market-data` owns its DDL; intelligence_db untouched
- [ ] **R32** — Alembic revision 021 is next-in-sequence after PLAN-0095's 020
- [ ] **BP-393** — no CONCURRENTLY (additive column, no index)
- [ ] **R10** — `utc_now()` from `common.time` for the timestamp write
- [ ] **R15** — every code change has a matching docs change (T-W1-03)

#### Break impact

| Broken file | Why | Fix |
|-------------|-----|-----|
| Existing `query_fundamentals` callers for balance_sheet / cash_flow with `period_type=None` | Now silently returns QUARTERLY-only instead of mixed | None — there are no such callers today (verified Phase-D Finding 1) |
| Smoke test asserting `alembic head == "020"` | If one exists | Update to `"021"` (BP-130 pattern) |

#### Regression guardrails

- **BP-393** — additive column migration; runs in default transaction.
- **BP-126** — new nullable column; no `server_default` needed because we
  bump it on next consumer cycle. **Explicitly safe** because the column is
  observational, not a NOT NULL constraint.
- **BP-130** — re-check smoke-test migration-head assertions.

#### Compounding updates

- `docs/services/market-data.md` — Period-type contract subsection +
  Freshness tracking subsection (T-W1-03).
- `services/market-data/.claude-context.md` — 2 new Pitfalls entries
  (T-W1-03).
- `docs/MASTER_PLAN.md` — single-sentence pointer (T-W1-03).
- `docs/BUG_PATTERNS.md` — new entry **BP-546** "`query_fundamentals` repo
  layer defaults `period_type=QUARTERLY` for balance_sheet + cash_flow to
  prevent silent QUARTERLY+ANNUAL mixing in future callers"; also confirm
  **BP-545** ("no per-instrument fundamentals freshness tracking") is filed
  if PLAN-0095 left it dangling.
- `docs/plans/TRACKING.md` — flip PLAN-0096 row to W1 in-progress, then done.
- `RULES.md` — no new rule.
- `CLAUDE.md` — no change.

---

### Wave W2 — NLP pipeline tail (PLAN-0095 W4 deferrals)

**Goal**: Land the two PLAN-0095 W4 tasks that did not ship before the W3
acceptance gate — MarketDataClient JWT-mint backoff (cluster-1 item 1) and
`NLP_PIPELINE_RELEVANCE_SCORING_API_KEY` wiring (cluster-1 item 2). Together
these stop two NLP workers from cold-starving on every redeploy.

**Depends on**: none (independent of W1)
**Estimated effort**: ~90 min (60 min for the backoff code + test, 30 min
                       for env wiring + verification)
**Architecture layer**: nlp-pipeline application (client) + env / docker-compose
**Branch**: `feat/plan-0096-w2`
**Migration**: NO
**Docker rebuild**: YES — `nlp-pipeline` image

#### Tasks

##### T-W2-01: MarketDataClient — JWT-mint exponential backoff (deferred PLAN-0095 T-W4-02)

**Type**: impl
**depends_on**: none
**blocks**: none
**Target files**:
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/clients/market_data_client.py` (path inferred; locate via `grep -rn "class MarketDataClient" services/nlp-pipeline/`)
- Used by `PriceImpactLabellingWorker`

**Audit reference**: PLAN-0095 §6 cluster-1 item 1 (lines 156-157), original
audit `docs/audits/2026-05-26-iter-9-multi-issue-investigation-report.md`;
PLAN-0095 T-W4-02 (deferred).

**What to build**:

Two acceptable patterns — pick whichever matches the existing pattern in
the codebase (`grep "exponential" services/nlp-pipeline/src` first):

**Option A (preferred per original audit)** — defer client construction to
first `run_once()` so the cycle naturally retries on its next tick:

```python
class PriceImpactLabellingWorker:
    def __init__(self, ...) -> None:
        self._market_data_client: MarketDataClient | None = None
        # NOT constructed at startup — defer to run_once()

    async def run_once(self) -> None:
        if self._market_data_client is None:
            self._market_data_client = await MarketDataClient.create(...)
        ...
```

**Option B** — 3-retry exponential backoff (1 s → 2 s → 4 s) inside
`MarketDataClient.__init__` or the JWT-mint helper:

```python
last_exc: Exception | None = None
for attempt, delay in enumerate([1.0, 2.0, 4.0]):
    try:
        self._jwt = await self._mint_jwt()
        break
    except (httpx.ConnectError, httpx.TimeoutException) as exc:
        last_exc = exc
        logger.warning("jwt_mint_retry", attempt=attempt, delay=delay)
        await asyncio.sleep(delay)
else:
    raise last_exc  # type: ignore[misc]
```

Per BP-235, set `httpx.Timeout(N)` explicitly on the underlying client if not
already set — exponential backoff is useless if the inner request hangs.

**Acceptance check**:
- Unit test `test_market_data_client_retries_jwt_mint_on_startup_failure` —
  mock first 2 attempts to raise `httpx.ConnectError`, third to succeed;
  assert no exception bubbles and `attempt=2` recorded.
- Unit test `test_market_data_client_gives_up_after_3_attempts` — mock all
  3 attempts to fail; assert exception is re-raised.
- Manual: `docker compose restart nlp-pipeline` with api-gateway intentionally
  delayed by 5 s — `PriceImpactLabellingWorker` no longer dies; recovers on
  retry.

##### T-W2-02: Wire `NLP_PIPELINE_RELEVANCE_SCORING_API_KEY` (deferred PLAN-0095 T-W4-04)

**Type**: config
**depends_on**: none
**blocks**: none
**Target files**:
- `services/nlp-pipeline/configs/docker.env` (and `.example`)
- `infra/compose/docker-compose.yml` — `nlp-pipeline` env block (verify it
  passes the env through if it's container-side)

**Audit reference**: PLAN-0095 §6 cluster-1 item 2 (line 157); PLAN-0095
T-W4-04 (deferred).

**What to build**:

1. **First verify the existing env pattern** for DeepInfra keys in other
   workers (read `services/nlp-pipeline/configs/docker.env` and
   `services/knowledge-graph/configs/docker.env` for how
   `*_API_KEY=${DEEPINFRA_API_KEY}` is wired):

   ```bash
   grep -rn "DEEPINFRA_API_KEY" services/*/configs/docker.env*
   grep -rn "DEEPINFRA_API_KEY" infra/compose/
   ```

2. **Mirror that pattern** for the relevance-scoring worker. Do NOT hardcode
   a literal API-key value into this plan or into any docker.env file. The
   canonical secret is pulled by `make fetch-secrets` from the
   `worldview-config` repo (see CLAUDE.md "Local Development").

   Expected change in `services/nlp-pipeline/configs/docker.env`:

   ```
   # Relevance-scoring worker uses DeepInfra primary (Ollama fallback only
   # for emergency dev). See PLAN-0096 W2 T-W2-02 / PLAN-0095 W4 deferral.
   NLP_PIPELINE_RELEVANCE_SCORING_API_KEY=${DEEPINFRA_API_KEY}
   ```

   If `${DEEPINFRA_API_KEY}` substitution does not flow through to nlp-pipeline
   (different env-loading pattern than knowledge-graph), the actual fix may
   be in `infra/compose/docker-compose.yml`'s `nlp-pipeline.environment`
   block — pass through from the host env there.

3. Update `docker.env.example` with the same line (no value — just the
   reference) so new operators know the env exists.

**Acceptance check**:
- `docker compose exec nlp-pipeline env | grep RELEVANCE_SCORING` shows a
  non-empty value after `make fetch-secrets && make dev`.
- 30 minutes of live observation: `ArticleRelevanceScoringWorker` log shows
  DeepInfra 200 OK responses (not Ollama-down errors).
- Prom metric `nlp_pipeline_articles_relevance_scored_total` advances.

#### Validation gate

- [ ] ruff + mypy clean on `nlp-pipeline`
- [ ] All existing nlp-pipeline unit tests pass
- [ ] 2 new unit tests pass (T-W2-01 x2)
- [ ] Docker rebuild of `nlp-pipeline` clean
- [ ] Live: `PriceImpactLabellingWorker` survives a 5-s api-gateway delay
- [ ] Live: `ArticleRelevanceScoringWorker` not stuck on Ollama-down

#### Architecture compliance

- [ ] **R12** — structlog for retry / fallback log events
- [ ] **R30** — API key via pydantic-settings env var, never in code or plan
- [ ] **BP-235** — `httpx.Timeout(N)` explicit on the JWT-mint client
- [ ] **BP-407** — max-retry cap (3) prevents thrash on permanent outage

#### Break impact

| Broken file | Why | Fix |
|-------------|-----|-----|
| Worker startup tests (if mocks expected zero-retry) | Backoff added | Update mocks to expect retry behaviour |
| Compose env smoke tests | New env var expected | Add `NLP_PIPELINE_RELEVANCE_SCORING_API_KEY` to baseline |

#### Regression guardrails

- **BP-235** — httpx timeout shadowing: the JWT-mint client must set
  `httpx.Timeout(N)` explicitly, especially when wrapped in `asyncio.wait_for`.
- **BP-407** — retry storm: max-retry cap = 3 so a permanent api-gateway
  outage doesn't thrash.
- **BP-563** (filed by PLAN-0095) — silent Ollama fallback when required
  API key empty; this wave closes the dev/staging path for that BP.

#### Compounding updates

- `docs/services/nlp-pipeline.md` — document `MarketDataClient` JWT-mint
  retry behaviour and the `NLP_PIPELINE_RELEVANCE_SCORING_API_KEY`
  requirement.
- `services/nlp-pipeline/.claude-context.md` Pitfalls — confirm the
  PLAN-0095 T-W4-04 entry already exists; if not, add: "relevance scoring
  worker silently falls back to Ollama if API key empty; wire
  `${DEEPINFRA_API_KEY}` (PLAN-0096 W2 T-W2-02 / PLAN-0095 T-W4-04)".
- `docs/BUG_PATTERNS.md` — confirm **BP-562** ("JWT-mint race on cold-start
  without backoff") and **BP-563** ("silent Ollama fallback") are filed
  (PLAN-0095 §7 said it would file them; verify they exist; if missing
  file here under PLAN-0096 W2).
- `docs/plans/TRACKING.md` — flip PLAN-0096 row state.
- `RULES.md` — no new rule.
- `CLAUDE.md` — no change.

---

### Wave W3 — AGE TemporalEvent sync (F-DB-002)

> **Investigation landed**:
> `docs/audits/2026-05-26-age-temporal-event-sync-investigation.md`. Root
> cause = AGE plpgsql `cypher()` schema cache survives `session.commit()`,
> so the `TemporalEvent` vlabel created by `_bootstrap_age_labels` is
> invisible to the MERGEs in the immediately following phase running on
> the **same** `AsyncSession`. Fix = invalidate the connection between
> bootstrap and phases.

**Goal**: Restore `_bootstrap_age_labels` so that the `TemporalEvent`
vlabel created on the first cycle is actually visible to the phase MERGEs
that run right after — backfilling the 14,822 stale nodes — and prevent
the next deploy from regressing.

**Depends on**: none.
**Estimated effort**: ~3 h (30 min fix + 45 min regression test + 60 min
                       reconciliation script + 30 min docs + 15 min docker
                       redeploy verification).
**Architecture layer**: knowledge-graph infrastructure (AGE sync worker).
**Branch**: `feat/plan-0096-w3`
**Migration**: NO (AGE-side fix; no DDL change in any service-owned DB).
**Docker rebuild**: YES — `knowledge-graph`

#### Tasks

##### T-W3-01: Invalidate AGE session between bootstrap and phases (BP-547)

**Type**: impl
**depends_on**: none
**blocks**: T-W3-02

**Target files**:
- `services/knowledge-graph/src/knowledge_graph/infrastructure/workers/age_sync_worker.py:447-479` (the `_bootstrap_age_labels` method — the `await session.commit()` at L478 is followed in `run()` L266-282 by `_run_phase(...)` calls that reuse the same session).

> **Audit drift correction**: the investigation report cites the file as
> `infrastructure/scheduler/age_sync_worker.py`. The actual path is
> `infrastructure/workers/age_sync_worker.py` (verified 2026-05-26 by
> `find services/knowledge-graph -name age_sync_worker.py`). Use the
> corrected path here.

**Audit reference**: investigation §"Root Cause: Most Likely" + Option A;
Phase-D Finding 6 (P1) lines 119-133; external-QA commit `53b2c8a1`.

**What to build**:

At the end of `_bootstrap_age_labels`, immediately after `await session.commit()`,
invalidate the underlying connection so the next operation pulls a fresh
connection whose AGE plpgsql cache is empty and will look up
`TemporalEvent` from scratch:

```python
await session.commit()
# BP-547 (PLAN-0096 W3): the AGE plpgsql `cypher()` function caches the
# label-lookup for the lifetime of the underlying connection. Newly created
# vlabels are invisible to MERGEs that reuse the same connection — even
# after commit. Force the next operation onto a fresh connection so the
# label cache is rebuilt. See
# docs/audits/2026-05-26-age-temporal-event-sync-investigation.md §Option A.
conn = await session.connection()
await conn.invalidate()
logger.info("age_sync_labels_bootstrapped", vlabels=2, elabels=len(_VALID_EDGE_LABELS))
```

Verify the **session lifecycle** in `run()` (L238-282): bootstrap and
phases share the same `async with self._sf() as session:` block, so the
session-scoped invalidation is sufficient — no need to reopen the session
explicitly. The first `_run_phase('entities', ...)` call will call
`_setup_age_session(session)` which re-issues `LOAD 'age'` + `SET search_path`
on the new connection; this rebuilds the cache cleanly.

Do **not** call `await session.close()` — that would tear down the
context manager mid-block. Connection invalidation (which forces the
pool to discard the current connection on the next `session.execute()`)
is the minimal-surface fix.

**Acceptance check**:
- Unit test `test_bootstrap_invalidates_connection_before_phases` in
  `services/knowledge-graph/tests/unit/infrastructure/workers/test_age_sync_worker.py`
  — mock the session/connection, run one cycle with `_labels_bootstrap_pending=True`,
  assert `connection.invalidate()` is called between `session.commit()`
  and the first `_run_phase` call. xfail-strict before the fix.
- `await conn.invalidate()` is async-safe (verified against SQLAlchemy
  ≥2.0 `AsyncConnection.invalidate()` API).

##### T-W3-02: Regression test — bootstrap + sync round-trips through AGE

**Type**: test
**depends_on**: [T-W3-01]
**blocks**: T-W3-03

**Target files**:
- `services/knowledge-graph/tests/integration/test_age_sync_worker_bootstrap.py` (new file; integration suite, needs real Postgres + AGE).

**What to build**: an integration test that:

1. Boots a fresh `intelligence_db` (or truncates `temporal_events` +
   drops the `worldview_graph` AGE graph) so the test starts in the
   "label does not exist" state.
2. Seeds N=20 rows into `temporal_events` (using the existing test
   factories from PLAN-0093 Wave B-1 if available).
3. Constructs an `AgeSyncWorker` with `_labels_bootstrap_pending=True`
   and `cypher_enabled=True`; awaits one `run()`.
4. Executes the Cypher count query against the same DB:
   ```sql
   SELECT count(*) FROM cypher('worldview_graph',
     $$ MATCH (n:TemporalEvent) RETURN count(n) $$
   ) AS (cnt agtype);
   ```
5. Asserts the count equals 20.

The test must **fail on the unpatched code** (xfail-strict before T-W3-01,
pass after).

**Acceptance check**:
- Integration test passes locally against `make dev` stack.
- Test is marked with the standard `integration` pytest marker so it is
  excluded from unit-test CI.

##### T-W3-03: One-shot reconciliation script for the 14,822 stale nodes

**Type**: tool / script
**depends_on**: [T-W3-01]
**blocks**: W3 sign-off

**Target files**:
- `scripts/reconcile_age_temporal_events.py` (new; sits next to the
  existing repo-root reconciliation scripts like `apply_state_a_fixes.py`
  and `partition_retention.py` — verified `scripts/` exists at repo root,
  no dedicated knowledge-graph scripts dir except for `backfill_path_insights.py`).
- Runnable via `python -m scripts.reconcile_age_temporal_events`.

**What to build**:

```python
"""One-shot reconciliation for AGE TemporalEvent nodes (BP-547).

After the W3 fix lands, the AGE sync worker will only pick up NEW
temporal_events going forward. This script backfills the 14,822 historical
rows by MERGEing them directly into the AGE graph. Idempotent — re-running
is a no-op because the script uses MERGE (not CREATE).
"""

import argparse, asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
# ... reuse the worker's _setup_age_session + Cypher MERGE template ...

async def main(dry_run: bool, batch_size: int = 500) -> int:
    # 1. SELECT id, event_type, ... FROM temporal_events
    # 2. For each batch:
    #      Cypher MERGE (n:TemporalEvent {id: ...}) SET n += {...}
    # 3. Commit after each batch (per-batch UoW; failures don't lose progress).
    # 4. Return the final AGE count.
    ...
```

Constraints:
- Idempotent (MERGE, not CREATE) — safe to re-run.
- Honours `--dry-run` (reports the expected MERGE count without writing).
- Honours `--batch-size N` (default 500).
- Per-batch commit + WARN log on failure so partial drains are recoverable.
- Uses `common.time.utc_now()` (R10) for any timestamp writes.
- Uses `structlog` (R12) for progress logs.

**Acceptance check**:
- `python -m scripts.reconcile_age_temporal_events --dry-run` reports
  `expected_merges=14822` on the current dev DB.
- Real run drains the 14,822-row backlog within one maintenance window
  (target <30 min).
- Re-running the script is a no-op (final AGE count unchanged, log shows
  `merged=14822, created=0`).
- **Acceptance gate for W3 sign-off**: post-deploy + post-reconciliation,
  the Cypher count equals the SQL count:
  ```sql
  -- expect equality
  SELECT (SELECT count(*) FROM temporal_events) AS sql_count,
         (SELECT count(*)::text FROM cypher('worldview_graph',
           $$ MATCH (n:TemporalEvent) RETURN count(n) $$) AS (c agtype)) AS age_count;
  ```

#### Validation gate

- [ ] ruff + mypy clean on `knowledge-graph`
- [ ] T-W3-01 unit test passes (and fails xfail-strict on unpatched code)
- [ ] T-W3-02 integration test passes against `make dev`
- [ ] T-W3-03 dry-run reports `expected_merges=14822` on dev DB
- [ ] T-W3-03 wet-run drains the backlog; SQL count == AGE count
- [ ] Re-run of T-W3-03 is no-op
- [ ] Docker rebuild of `knowledge-graph` clean; post-restart, fresh
      `age_sync_worker` cycle confirms new temporal_events land in AGE

#### Architecture compliance

- [ ] **R12** — structlog for the new `connection.invalidate()` log line
      and reconciliation script progress
- [ ] **R24** — no DDL change; AGE-side fix only; no intelligence-migrations
      revision needed
- [ ] **R32** — no Alembic revision required (verified — only PLAN-0096
      W1 adds a revision, in market-data, unrelated)
- [ ] **BP-461** — AGE Cypher `|` syntax + rfind agtype parse pitfalls
      re-read; the W3 fix touches session lifecycle, not Cypher text,
      so no regression risk on BP-461 surface

#### Break impact

| Broken file | Why | Fix |
|-------------|-----|-----|
| Tests that mock `AsyncSession` without exposing `.connection()` | New `await session.connection().invalidate()` call | Extend the mock to return a connection mock with `invalidate=AsyncMock()` |
| `_bootstrap_age_labels` callers in tests that assert exact `await` sequence | One additional `await` after commit | Update assertions |

#### Regression guardrails

- **BP-461** (AGE Cypher pitfalls) — not touched by this fix (no Cypher
  text change); still re-validated before final commit.
- **In-flight overlap**: confirmed PLAN-0095 does not touch
  `age_sync_worker.py` (`grep` returned no hits), so W3 is conflict-free
  on the `feat/plan-0096-w3` branch.

#### Compounding updates

- `docs/services/knowledge-graph.md` — document the bootstrap/phase
  session-isolation contract and the reconciliation script entry point.
- `services/knowledge-graph/.claude-context.md` Pitfalls — new entry:
  > AGE plpgsql `cypher()` caches label lookups per connection — any
  > workflow that creates a vlabel and then MERGEs against it on the
  > same connection must invalidate the connection between the two.
  > See `_bootstrap_age_labels` in `age_sync_worker.py` (BP-547).
- `docs/BUG_PATTERNS.md` — new entry **BP-547** "AGE plpgsql `cypher()`
  schema cache survives `session.commit()` — newly created vlabels are
  invisible to MERGEs reusing the same connection; force
  `connection.invalidate()` between label DDL and the first MERGE".
- `docs/plans/TRACKING.md` — flip PLAN-0096 row state.

---

### Wave W4 — NLP article stall remediation (F-DB-NEW-001)

> **Investigation landed**:
> `docs/audits/2026-05-26-nlp-dlq-stall-investigation.md`. Root cause =
> **`entity_mentions.tenant_id NOT NULL`** (alembic 0020) blocking
> pre-PLAN-0086 articles whose Avro payload predates the tenant_id field.
> 94 messages are stuck **in-flight** on `content.article.stored.v1`
> (`.dlq` topic is empty — IntegrityError is treated as retryable, so the
> consumer-group offset never advances and the same 94 messages re-run
> in a perpetual loop). Fix = substitute a public-tenant sentinel UUID
> for legacy articles.
>
> **Naming correction**: the original placeholder called this a "DLQ
> stall". The investigation showed the DLQ is empty; the stall is on the
> **main topic** offset. Wave goal text and acceptance criteria are
> updated accordingly. The alert rule is renamed from a DLQ-lag alert
> to a **consumer-retry-storm** alert because that is the real signal.

**Goal**: Unblock the 94-message in-flight stall on
`content.article.stored.v1`, fix the consumer so legacy payloads without
`tenant_id` are processed under a public-tenant sentinel, and add a
retry-storm alert so the next silent stall pages instead of festering.

**Depends on**: none.
**Estimated effort**: ~4 h (30 min sentinel constant + 45 min consumer
                       change + 60 min replay tool + 45 min alert + 30 min
                       docs + 30 min regression test + docker redeploy).
**Architecture layer**: libs/common (new constant) + nlp-pipeline
                       application + observability.
**Branch**: `feat/plan-0096-w4`
**Migration**: NO (no DDL change; the existing NOT NULL stays — the
               sentinel UUID is a non-null value so the constraint holds).
**Docker rebuild**: YES — `nlp-pipeline` (and any service that imports
                   `libs/common` and picks up the new sentinel constant).

#### Tasks

##### T-W4-01: Add `PUBLIC_TENANT_ID` sentinel + substitute in article consumer (BP-548)

**Type**: impl
**depends_on**: none
**blocks**: T-W4-02

**Target files**:
- `libs/common/src/common/ids.py` — add a new module-level constant
  `PUBLIC_TENANT_ID: Final[uuid.UUID] = uuid.UUID("00000000-0000-7000-8000-000000000001")`
  (UUIDv7 namespace, matches investigation report §"Option 1"; verified
  the constant does not exist anywhere in `libs/` or `services/nlp-pipeline/src/`
  via grep 2026-05-26).
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/messaging/consumers/article_consumer.py:454-458` (the existing tenant_id extraction block).

**Audit reference**: investigation §"Root Cause: Stale Article Messages
Without tenant_id" + Option 1; Phase-D Finding 5 (P1) lines 97-117.

**What to build**:

```python
# libs/common/src/common/ids.py
from typing import Final
import uuid

# BP-548 (PLAN-0096 W4): sentinel tenant UUID for legacy articles produced
# before PLAN-0086 Wave A-1 wired tenant_id into the Avro envelope. Used
# by any consumer that needs a non-null fallback to satisfy a tenant_id
# NOT NULL constraint without claiming any real tenant ownership.
# Dashboards filter `WHERE tenant_id <> PUBLIC_TENANT_ID` to exclude.
PUBLIC_TENANT_ID: Final[uuid.UUID] = uuid.UUID(
    "00000000-0000-7000-8000-000000000001"
)
```

```python
# services/nlp-pipeline/.../article_consumer.py (~L454)
raw_tenant = headers.get("tenant_id") or value.get("tenant_id") or None
tenant_id: uuid.UUID | None = None
if raw_tenant:
    with contextlib.suppress(ValueError, AttributeError):
        tenant_id = uuid.UUID(str(raw_tenant))

# BP-548 (PLAN-0096 W4): pre-PLAN-0086 articles have no tenant_id in the
# Avro envelope. Substitute the public-tenant sentinel and WARN-log so
# operators can see the legacy passthrough on the offset that produced it.
if tenant_id is None:
    logger.warning(
        "article_consumer.legacy_tenant_id_sentinel",
        doc_id=str(value.get("doc_id")),
        topic_offset=headers.get("kafka_offset"),
        topic=headers.get("kafka_topic", "content.article.stored.v1"),
    )
    tenant_id = PUBLIC_TENANT_ID
```

The substitution happens **before** the existing `if tenant_id is not None:`
stamping at L563-565, so all downstream EntityMention objects get the
sentinel naturally — no further code paths need to change.

> **Multi-tenant pollution check**: the sentinel is a fixed, well-known
> UUIDv7 in a reserved namespace (`00000000-0000-7000-8000-…`). Existing
> tenant-scoped dashboards filter on the authenticated user's tenant_id,
> which never equals the sentinel. Pre-existing tenant-scoped use cases
> (`portfolio.*`, `news.*` already shipped) join on the real tenant_id
> column from the JWT; legacy rows tagged with the sentinel will not
> appear in any user's view because no user's JWT carries the sentinel.
> Operator queries can explicitly include legacy rows via
> `WHERE tenant_id IN (jwt_tenant, PUBLIC_TENANT_ID)` if needed.

**Acceptance check**:
- Unit test `test_public_tenant_id_constant` in
  `libs/common/tests/test_ids.py` — asserts the sentinel value + type +
  importability.
- Unit test `test_article_consumer_substitutes_sentinel_for_missing_tenant`
  in `services/nlp-pipeline/tests/unit/infrastructure/messaging/consumers/test_article_consumer.py`
  — synthetic Avro payload with neither `headers['tenant_id']` nor
  `value['tenant_id']`; asserts `EntityMention.tenant_id == PUBLIC_TENANT_ID`
  and a `legacy_tenant_id_sentinel` WARN log was emitted.
- See T-W4-04 below for the Avro-shape regression test.

##### T-W4-02: Replay tool for the 94 stuck in-flight messages

**Type**: tool / script
**depends_on**: [T-W4-01]
**blocks**: T-W4-03

**Target files**:
- `scripts/replay_stuck_articles.py` (new; sits next to existing reconciliation
  scripts at repo root; not under `services/nlp-pipeline/scripts/` because
  that dir holds only worker-internal backfills like
  `backfill_path_insights.py`).
- Runnable via `python -m scripts.replay_stuck_articles`.

**What to build**:

Because the messages are stuck **in-flight** (not in DLQ — the investigation
clarified this), the replay path is:

1. Connect to the `nlp-pipeline-article-consumer` consumer group and
   describe its current offset on `content.article.stored.v1`.
2. Read the 94 messages from that offset forward (peek; do NOT commit
   yet).
3. For each message: parse the Avro envelope, apply the sentinel
   substitution (mirroring T-W4-01 — the script imports the same helper
   so the logic stays single-sourced), re-publish to the **same** topic
   with `headers['tenant_id']` populated.
4. Commit the original offset for the 94 stuck messages **only after**
   the re-published copies are acknowledged by the broker.

Constraints:
- Idempotent — re-running with the same offset window is a no-op because
  the entity-mention writes use `ON CONFLICT (mention_id) DO NOTHING`
  (verified at `entity_mention.py:76`).
- Honours `--dry-run` (enumerates the 94 messages + would-be sentinel
  substitutions without writing).
- Honours `--limit N` (default 94).
- WARN-logs per-message outcome with `doc_id` + offset.
- Uses `structlog` (R12) and `common.time.utc_now()` (R10).
- **Avro re-encoding** (R28): re-publish via the same Confluent-Avro
  serializer the producer uses (BP-122); do NOT re-publish raw bytes.

**Acceptance check**:
- `python -m scripts.replay_stuck_articles --dry-run` enumerates 94
  messages on dev.
- Wet run drains the in-flight backlog; consumer offset advances past
  the 94 messages within 5 min.
- `entity_mentions` row count climbs from 0 to >0 within 5 min of the
  replay (the original observable symptom from the investigation).

##### T-W4-03: Prometheus retry-storm alert for the article consumer

**Type**: observability
**depends_on**: [T-W4-01]
**blocks**: W4 sign-off

**Target files**:
- `infra/grafana/alerts/nlp_article_consumer_retry_storm.yml` (new file;
  mirrors the existing `infra/grafana/alerts/kafka_stalled.yml` +
  `path_insight_stalled.yml` shape; verified those are the canonical
  alert-rule home, NOT `infra/prometheus/rules/` which holds SLO rules).

**Audit reference**: investigation §"Why DLQ Is Empty" (the DLQ-lag alert
originally proposed in the placeholder will not fire because the DLQ stays
empty during this failure mode; the **retry counter on the main topic** is
the real signal).

**What to build**:

A Grafana-evaluated alert on the existing
`kafka_consumer_messages_retried_total` (or equivalent — verify against
`libs/observability/metrics.py` BaseKafkaConsumer instrumentation) for
the article consumer:

```yaml
# infra/grafana/alerts/nlp_article_consumer_retry_storm.yml
# PLAN-0096 W4 (BP-548): silent in-flight stalls on content.article.stored.v1
# manifest as a runaway retry counter while the consumer offset stays put.
# DLQ-lag alerts do not catch this (the DLQ stays empty). Fires when the
# article consumer is retrying more than N times/minute over a 10 min
# window AND the consumer offset is not advancing.
groups:
  - name: nlp_article_consumer_retry_storm
    rules:
      - alert: NlpArticleConsumerRetryStorm
        expr: |
          (
            sum by (service, topic) (
              rate(kafka_consumer_messages_retried_total{
                service="nlp-pipeline",
                topic="content.article.stored.v1"
              }[5m])
            ) > 1
          )
          and on (topic) (
            sum by (topic) (
              rate(kafka_consumer_messages_consumed_total{
                service="nlp-pipeline",
                topic="content.article.stored.v1"
              }[10m])
            ) == 0
          )
        for: 10m
        labels:
          severity: warning
          service: nlp-pipeline
        annotations:
          summary: "NLP article consumer in retry-storm (no progress in 10m)"
          description: "content.article.stored.v1 has retries >1/min with zero successful consumes — likely a deterministic IntegrityError or schema mismatch. See BP-548."
```

(Exact metric names depend on the BaseKafkaConsumer instrumentation —
verify against the existing `kafka_stalled.yml` example which uses
`kafka_consumer_messages_consumed_total`. If a `_retried_total` counter
doesn't yet exist, file as a precursor sub-task and emit it from
`BaseKafkaConsumer._handle_message`'s exception path.)

**Acceptance check**:
- Alert YAML validates with `promtool check rules` (Grafana ingestion).
- Synthetic test: pause the article consumer with a known-bad message,
  observe the alert fire in Alertmanager within 10 min.
- Recovery (drain the bad message → offset advances): alert resolves
  within 5 min.

##### T-W4-04: Regression test — pre-PLAN-0086 Avro payload accepted

**Type**: test
**depends_on**: [T-W4-01]
**blocks**: W4 sign-off

**Target files**:
- `services/nlp-pipeline/tests/integration/test_article_consumer_legacy_payload.py` (new).

**What to build**: a regression test that:

1. Constructs an `ArticleProcessingConsumer` against a real Postgres
   session (uses the existing integration-test factories).
2. Calls `process_message(key=None, value=payload, headers={})` with an
   Avro-shape `payload` that includes `doc_id`, `minio_silver_key`,
   `source_type`, `title` BUT **no** `tenant_id` field (mirroring the
   pre-PLAN-0086 wire format).
3. Asserts no exception is raised.
4. Asserts `SELECT count(*) FROM entity_mentions WHERE tenant_id = '00000000-0000-7000-8000-000000000001'`
   is ≥ 1 (entity mentions landed under the sentinel).
5. Asserts the consumer emitted exactly one `article_consumer.legacy_tenant_id_sentinel`
   WARN-log event.

Test must **fail on the unpatched code** (xfail-strict before T-W4-01,
pass after).

**Acceptance check**:
- Integration test passes locally.
- xfail-strict on unpatched code (proving the regression is caught).

#### Acceptance gate (W4 sign-off)

Post-deploy of T-W4-01..04 + execution of T-W4-02 replay:

- `SELECT count(*) FROM entity_mentions` starts climbing within 5 min of
  the replay (the original symptom recovery).
- `content.article.stored.v1` consumer-group lag drops to 0.
- `NlpArticleConsumerRetryStorm` alert is in OK state.

#### Validation gate

- [ ] ruff + mypy clean on `libs/common` and `nlp-pipeline`
- [ ] T-W4-01 unit tests pass (2 new — sentinel constant + substitution)
- [ ] T-W4-02 dry-run enumerates the 94 messages on dev
- [ ] T-W4-02 wet-run drains the backlog; consumer offset advances
- [ ] T-W4-03 alert YAML loads + fires on synthetic retry storm
- [ ] T-W4-04 integration test passes (and xfail-strict on unpatched code)
- [ ] Acceptance gate above passes within 5 min of deploy

#### Architecture compliance

- [ ] **R10** — `utc_now()` from `common.time` for any timestamp writes
      in the replay tool
- [ ] **R12** — structlog for sentinel WARN log and replay tool progress
- [ ] **R13** — `libs/common` is the correct home for the sentinel UUID
      (cross-service reuse expected)
- [ ] **R24** — no DDL change; no intelligence-migrations revision
- [ ] **R28** — replay tool re-serialises via Confluent-Avro, not raw
      bytes (BP-122)
- [ ] **BP-407** — replay tool respects the existing Kafka backpressure
      limits; produces serially, not in bulk

#### Break impact

| Broken file | Why | Fix |
|-------------|-----|-----|
| Tests that asserted `IntegrityError` was raised for missing tenant_id | Consumer now substitutes sentinel instead of crashing | Update assertion — expect `EntityMention.tenant_id == PUBLIC_TENANT_ID` |
| Dashboards that count rows without a tenant filter | Sentinel rows now appear in totals | Add `WHERE tenant_id <> PUBLIC_TENANT_ID` to legacy-exclusion queries; add a "legacy rows" tile if useful |
| `libs/common` import surface | New public constant `PUBLIC_TENANT_ID` | Additive — no break |

#### Regression guardrails

- **BP-122** — Confluent-Avro wire-format magic byte: replay tool MUST
  re-serialise through the standard producer, not re-publish raw bytes
  blindly.
- **BP-407** — Kafka backpressure cap: replay tool produces serially with
  the same rate limits as the original producer.
- **BP-200** — Valkey API: not implicated; the stall is a Postgres-side
  constraint, not idempotency cache.

#### In-flight overlap check

- PLAN-0095 does not touch `article_consumer.py` (`grep` returned no
  hits — verified 2026-05-26). `feat/plan-0096-w4` is conflict-free.
- W4 does NOT introduce a new Alembic revision. PLAN-0096 W1's revision
  021 is in `market-data`, isolated from W4's nlp-pipeline scope.
- `libs/common/ids.py` is touched only additively; no other in-flight
  branch is editing it (`git log --since=2026-05-20 -- libs/common/src/common/ids.py`
  — confirm at implementation start).

#### Compounding updates

- `docs/services/nlp-pipeline.md` — document the sentinel substitution,
  the replay tool entry point, and the new retry-storm alert.
- `services/nlp-pipeline/.claude-context.md` Pitfalls — new entry:
  > Pre-PLAN-0086 Avro payloads have no `tenant_id` field. The article
  > consumer substitutes `common.ids.PUBLIC_TENANT_ID` so the NOT NULL
  > constraint holds; dashboards must filter the sentinel for
  > tenant-scoped views (BP-548).
- `libs/common/README.md` (or the equivalent doc) — document
  `PUBLIC_TENANT_ID` and the dashboard-filter convention.
- `docs/BUG_PATTERNS.md` — new entry **BP-548** "NLP article consumer
  in-flight stall (94 stuck messages) — `entity_mentions.tenant_id NOT
  NULL` migration (alembic 0020) blocked pre-PLAN-0086 payloads;
  consumer treated IntegrityError as retryable so offsets never
  advanced + DLQ stayed empty; fix = `PUBLIC_TENANT_ID` sentinel +
  retry-storm alert (not a DLQ-lag alert)".
- `infra/grafana/alerts/nlp_article_consumer_retry_storm.yml` — new file
  (T-W4-03).
- `docs/plans/TRACKING.md` — flip PLAN-0096 row state.

---

## §5 — Cross-cutting concerns

### Cross-cutting acceptance gate: PLAN-0095 W1+W2 chat-eval rerun

PLAN-0095 W1 fixed the fundamentals correctness bug and added the composite
indexes; PLAN-0095 W2 added the batch tool + classifier reorder; PLAN-0095
T-W2-04 (the chat-eval p99 < 60 s acceptance gate) was deferred because it
requires a live docker stack with the new migrations applied. PLAN-0096
inherits that gate. Once **PLAN-0095 W1+W2 + PLAN-0096 W1+W2** are all
deployed, run:

```bash
# 1. Rebuild affected services
docker compose build market-data rag-chat nlp-pipeline

# 2. Apply all 3 new migrations on market-data
#    019 composite fundamentals indexes  (PLAN-0095 T-W1-03)
#    020 snapshot period_type columns    (PLAN-0095 T-W1-04)
#    021 instruments.last_fundamentals_ingest_at  (PLAN-0096 T-W1-02)
docker compose run --rm market-data-migrate alembic upgrade head

# 3. Restart the stack
docker compose up -d market-data rag-chat nlp-pipeline

# 4. Run the aggregate gate
RAG_CHAT_BASE_URL=http://localhost:8000 \
  pytest tests/validation/chat_eval/test_aggregate_score.py -v
```

**Pass criteria** (gates the closure of PLAN-0095 W1+W2 + PLAN-0096 W1+W2):

- `verdicts` count matches the harness expectation (no skipped questions).
- `latency.p99_seconds < 60.0` (the ITER-8 gate that originally failed at
  91.9 s).
- Zero HARMFUL verdicts.
- AMD/NVDA Q1 fundamentals questions return revenue in the $5-15B range,
  not $30B+.

If the run fails the p99 gate, root-cause-analyse before adding more code
— PLAN-0095 W2 was the latency wave; PLAN-0096 only fixes correctness +
freshness. Failure here means a PLAN-0095 W2 regression, not a PLAN-0096
issue.

### Other cross-cutting items

- **Contract changes** (all additive):
  - `query_fundamentals` adds defensive QUARTERLY default for
    balance_sheet + cash_flow when `period_type=None` (T-W1-01). Backward
    compatible — existing explicit-`period_type` callers unaffected.
  - `instruments` table gains 1 nullable column (T-W1-02).
  - No new HTTP routes, no new Kafka topics.
- **Migration needs**: 1 new Alembic revision (`021_*`) on market-data,
  additive. Sequence after PLAN-0095's `020_*`.
- **Event flow changes**: none.
- **Configuration changes**:
  - nlp-pipeline: `NLP_PIPELINE_RELEVANCE_SCORING_API_KEY=${DEEPINFRA_API_KEY}`
    in `services/nlp-pipeline/configs/docker.env` (mirror existing pattern;
    do NOT hardcode literal secrets).
  - knowledge-graph: none in this plan (PLAN-0095 W4 path-insight env
    tuning already shipped).
  - libs/common: new public constant `PUBLIC_TENANT_ID` exported from
    `common.ids` (additive — W4 T-W4-01).
- **Documentation updates**: see per-wave Compounding updates.

## §6 — Risk assessment

- **Critical path**: W1 + W2 are both pre-requisites for the cross-cutting
  chat-eval acceptance gate. W3 and W4 can run in parallel after their
  respective investigations land.
- **Highest-risk task**: T-W1-01 (defensive default). Risk is low — the
  Phase-D audit confirmed zero current callers. The risk surface is
  exclusively *future* callers (which is exactly the point — fail-safe).
  Mitigation: the new test `test_query_fundamentals_explicit_annual_overrides_default`
  proves the override path still works.
- **Second-highest**: T-W4-01 — the `PUBLIC_TENANT_ID` sentinel changes
  data shape (legacy rows get a real, queryable tenant_id instead of
  failing the constraint). Mitigation: explicit dashboard-filter
  guidance in the compounding docs; reserved-namespace UUID
  (`00000000-0000-7000-8000-…`) chosen to be visually distinguishable.
- **Third-highest**: T-W3-01 — connection invalidation is a low-blast-
  radius fix, but `await session.connection().invalidate()` is a less
  common SQLAlchemy idiom than `session.close()`. Mitigation: unit test
  asserts the exact call sequence; integration test exercises the full
  bootstrap→phase cycle end-to-end.
- **Rollback strategy**:
  - W1: `alembic downgrade -1` drops `instruments.last_fundamentals_ingest_at`;
    revert the `query_fundamentals` defensive default to restore the prior
    `if period_type is not None` shape.
  - W2: revert backoff code (JWT mint reverts to "mint-once-die-on-fail"
    behaviour — known failure mode, not a regression); unset the env var
    (worker reverts to Ollama-down starvation — known failure mode).
  - W3: revert the single `connection.invalidate()` line — bootstrap reverts
    to the silent-zero-relabel state (known failure mode, not a worse
    regression). The reconciliation script is idempotent so partial runs
    are safe to abandon mid-stream.
  - W4: unset the sentinel substitution — consumer reverts to the
    in-flight stall state (known failure mode). Replay tool is
    idempotent so partial drains are safe; tenant-scoped queries are
    unaffected by the sentinel rows under standard dashboard filters.
- **Testing gaps**: no CI-level chat-eval gate (run is operator-driven).
  Acceptable for now; PLAN-0075 owns the long-term answer-quality CI work.

## §7 — Compounding step

- **New bug patterns** to add to `docs/BUG_PATTERNS.md`:
  - **BP-546** (defensive period_type default at repo layer; W1 T-W1-01)
  - **BP-547** (AGE plpgsql `cypher()` schema cache survives commit;
    invalidate connection between vlabel DDL and first MERGE; W3 T-W3-01)
  - **BP-548** (NLP article in-flight stall — NOT NULL tenant_id blocks
    pre-PLAN-0086 payloads; fix via `PUBLIC_TENANT_ID` sentinel +
    retry-storm alert, NOT a DLQ-lag alert; W4 T-W4-01..03)
  - Verify **BP-545** (per-instrument freshness gap) is filed; if not, file
    here under W1 T-W1-02.
  - Verify **BP-562** + **BP-563** (PLAN-0095 §7 promised these for the
    deferred W4 tasks); if missing, file here under W2.
- **No new rule** required — leverages existing R10 / R12 / R15 / R24 /
  R28 / R30 / R32.
- **No CLAUDE.md change** — workflow unchanged.
- **TRACKING.md**: insert PLAN-0096 row in the Active Plans section (see
  below for content). Flip status across wave lifecycle.
- **REVIEW_CHECKLIST.md**: no change — orphan-prune item from PLAN-0093
  already covers any helper deletions.

---

## Owner

**Owner**: TBD (assign at implementation start). Suggested split: data-
platform engineer for W1 (mirrors PLAN-0095 W1 ownership pattern);
platform engineer for W2 (mirrors PLAN-0095 W4 ownership); knowledge-graph
specialist for W3 (AGE Cypher domain knowledge — same engineer who fixed
BP-461 ideally); pipeline engineer for W4 (Kafka + consumer-replay
familiarity).
