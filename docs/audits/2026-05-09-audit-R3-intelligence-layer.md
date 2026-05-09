# Audit R3 — Intelligence Layer (PLAN-0073/0074/0079/0080)

**Wave**: PLAN-0087 Wave B / Swarm 1
**Agent**: R3 — Intelligence layer
**VA**: VA-2
**Surfaces**: A4 Intelligence tab, A7 Chat (entity-graph tool)
**Date**: 2026-05-09 (Saturday)
**Read-only**: yes
**Demo deadline**: 2026-05-11

> Demo entities scoped: AAPL, MSFT, OPENAI, NVDA, META.
> Verdict: **the Intelligence layer is non-functional end-to-end.** All four
> "intelligence" reads return HTTP 500; the narrative/path producers cannot
> populate their tables because of a schema mismatch, a missing seed trigger,
> a too-aggressive hub threshold for the current KG, and a missing canonical
> entity (OpenAI). Multiple HF defects below.

---

## 1. Per-entity endpoint matrix

S9 prefix is `/v1` (NOT `/api/v1` as the audit brief listed; S7 internal prefix
is `/api/v1`). Verified via `services/api-gateway/src/api_gateway/routes/proxy.py`
line 51 (`router = APIRouter(prefix="/v1")`). Hits below use the correct S9 path.
Token: `POST /v1/auth/dev-login` `{"email":"demo@worldview.local"}` → RS256 JWT.

| Entity | Canonical entity_id | `/v1/entities/{id}/intelligence` | `/v1/entities/{id}/paths` | `/v1/entities/{id}/narratives` |
|--------|---------------------|----------------------------------|---------------------------|---------------------------------|
| AAPL   | `11111111-0001-7000-8000-000000000001` | **500** `{"error":"internal_error"}` | 200 `{"paths":[],"total":0,"freshness_ts":null}` | 200 `{"versions":[],"next_cursor":null}` |
| MSFT   | `11111111-0002-7000-8000-000000000001` | **500** `{"error":"internal_error"}` | 200 empty | 200 empty |
| NVDA   | `11111111-0003-7000-8000-000000000001` | **500** `{"error":"internal_error"}` | 200 empty | 200 empty |
| META   | `11111111-0007-7000-8000-000000000001` | **500** `{"error":"internal_error"}` | 200 empty | 200 empty |
| **OPENAI** | **(absent)** | n/a — entity missing | n/a | n/a |

Notes:
- The bundle endpoint requested by the brief, `/health`, is NOT a separate
  endpoint — `health_score` is a field of the `/intelligence` response
  (`EntityIntelligencePublic.health_score` in
  `services/knowledge-graph/src/knowledge_graph/application/schemas_intelligence.py`).
  Same for "narrative" (singular) — the current narrative is nested inside the
  `/intelligence` response; standalone listing is `/narratives` (plural), which
  is paginated history. The PRD-0087 §2.1 wording conflates these. The
  worldview-web frontend agrees with the actual endpoints — see
  `apps/worldview-web/lib/api/intelligence.ts` lines 98/141/182/225 — so this
  is a brief-only mismatch, not a contract bug.
- `/v1/entities/{id}/intelligence` 500 root cause and resolution path are
  D-R3-001 below — single-line schema bug, all four fail identically.
- `/paths` and `/narratives` are 200 but **always empty** (D-R3-003,
  D-R3-005). The frontend will render the Intelligence tab as a fully
  populated 500-banner-or-empty-state UI; no real content shows.

---

## 2. Narrative generation diagnosis (D-INIT-2 root cause)

D-INIT-2 captured zero rows in `intelligence_db.entity_narrative_versions`.
**This is not a backlog effect — it is structural.** Three independent
problems together guarantee zero output before the demo:

### 2.1 `NarrativeGenerationWorker` only fires weekly, on Sunday 03:00 UTC

File: `services/knowledge-graph/src/knowledge_graph/infrastructure/scheduler/scheduler.py`
lines 170–183.

```python
# Worker 13D-3: weekly narrative generation PERIODIC_REFRESH at 03:00 UTC every Sunday
self._scheduler.add_job(fn_13d3, "cron", hour=3, minute=0, day_of_week="sun", ...)
```

Today is **Saturday 2026-05-09**; demo is **Monday 2026-05-11**. The worker
will fire once at Sunday 03:00 UTC — but see §2.2/2.3 for why it may not
produce anything even then. There is no event-driven trigger and no `INITIAL`
seed run wired into service startup despite `NarrativeGenerationReason.INITIAL`
being defined in `domain/narrative.py`. The only way to populate narratives
before demo is the manual API trigger
`POST /v1/entities/{entity_id}/narratives/generate` (rate-limited per
entity per user via Valkey).

Evidence (live container logs, grep `narrative_generation`):
```
docker logs worldview-knowledge-graph-scheduler-1 | grep -i narrative_generation
# (no matches — never fired)
```
Compare with `narrative_refresh_worker_complete` events (Worker 13D-2 = embedding
refresh, NOT text generation; runs hourly):
```
2026-05-09T14:51:36 narrative_refresh_worker_complete refreshed=262
2026-05-09T15:51:34 narrative_refresh_worker_complete refreshed=13
2026-05-09T16:51:31 narrative_refresh_worker_complete refreshed=0
```
These are vector embeddings being refreshed against zero new narratives —
the system is happily idle while producing nothing.

### 2.2 Even if the worker fires, the `INITIAL` reason is never used

`NarrativeGenerationReason` enum in `domain/narrative.py` defines
`INITIAL`, `MANUAL_TRIGGER`, `PERIODIC_REFRESH`. The scheduler passes
`PERIODIC_REFRESH` only. Per-entity narratives for the 277-entity backlog
should have been seeded with `INITIAL` once at first deploy — that path has
no runner. A safer demo posture is to programmatically POST manual triggers
for the demo top-N (AAPL, MSFT, NVDA, META, plus ~20 other indexed entities).

### 2.3 The use case ALWAYS falls back to `template-v1` because `llm_client=None`

`scheduler.py` line 335 instantiates `GenerateNarrativeUseCase(...)` with
`llm_client=None` (the worker factory does not pass an `llm_client`); the use
case at `application/use_cases/generate_narrative.py` line 430 takes the
template fallback whenever `self._llm is None`:

```python
if self._llm is None:
    return self._template_fallback(entity_name, entity_type, relation_count), "template-v1"
```

So if the worker did produce output, every narrative would be
`"[template-v1] Apple Inc.: financial_instrument with 2 known relations
tracked in the knowledge graph. This narrative was generated from
structured metadata without an LLM..."` — a glorified placeholder. PRD-0087
§3 quality bar says "indistinguishable from a real institutional terminal"
and "no fabricated entities"; template-v1 narratives meet "non-fabricated"
but fail "real-content" — they will be visibly demo-killing.

`NarrativeRefreshWorker` (Worker 13D-2, the embedding refresh) is given a
real `FallbackChainClient` because `llm_client` is wired into its factory,
but `NarrativeGenerationWorker` (13D-3) was registered without it. This is a
two-line wiring fix in `scheduler.py:build_workers` — pass
`llm_client=llm_client` to `GenerateNarrativeUseCase`.

### 2.4 Even if narratives are produced, only 8 distinct subject entities exist in `relations`

```sql
SELECT count(*) FROM relations;                       -- 18
SELECT count(DISTINCT subject_entity_id) FROM relations;  -- 8
SELECT canonical_type, count(*) FROM relations GROUP BY 1;
-- EXPOSED_TO_THEME=13, COMPETES_WITH=4, SUPPLIER_OF=1
```

So the narrative for any entity outside those 8 will reduce to "0 known
relations" boilerplate, providing no signal. Closing this is upstream of R3
(KG depth — VA-3, see audit R6/R7) but is the dominant content-quality
constraint on top of the wiring bugs.

---

## 3. TrustScorer audit (PLAN-0079)

File: `services/rag-chat/src/rag_chat/application/pipeline/trust_scorer.py`
Wired in: `services/rag-chat/src/rag_chat/app.py` lines 363–382 (env-tunable
weights at boot); `application/pipeline/retrieval_orchestrator.py` lines 285,
329, 365, 403, 444, 474, 510, 528, 546, 578, 604.

### 3.1 Multi-factor formula present and correct on paper

Implementation (lines 51–85): additive
`trust = w_source*source_authority + w_corroboration*corr_factor + w_extraction*extr_factor`,
clipped to `[0, 1]`. Defaults `0.4 / 0.1 / 0.1`. `_corroboration_factor` =
`1 - exp(-evidence_count/3)` saturating ~0.95 at evidence_count≥10, default
0.5 when count=0.

### 3.2 But `evidence_count` is NEVER passed at any production call site

Eleven call sites in `retrieval_orchestrator.py` call `score()`:
- 2 sites pass `extraction_confidence`
- 0 sites pass `evidence_count`

So `corroboration_factor` always equals the `_DEFAULT_CORROBORATION = 0.5`
constant. Final score per source therefore reduces to:
- `0.4 * source_authority(source_type) + 0.05 + 0.05` when `extraction_confidence`
  is unknown, equivalent to `0.4 * SA + 0.10`.
- `0.4 * SA + 0.05 + 0.1 * extraction_confidence` otherwise.

The "multi-factor" advertised by PLAN-0079 is *partially* live — it is
strictly equivalent to a 3-bucket source-authority score with a flat
corroboration premium. PRD-0087 §3 demo bar talks about evidence depth
visibility ("8 sources cite this"); the RetrievedItem has fields for it,
but rag-chat retrieval consumers do not aggregate evidence_count from
`relations.evidence_count` or `relation_evidence_raw`. Wiring this is a
larger task than a doc-edit.

### 3.3 No production trust-score telemetry

`trust_scorer.score()` calls `log.debug(...)` only — there is no Prometheus
histogram for `trust_weight` distributions. R3 cannot validate "sane
confidence ranges" without persistent telemetry; ad-hoc inspection requires
running rag-chat retrieval which depends on broken intelligence endpoints.

---

## 4. PathInsightWorker / paths diagnosis

### 4.1 Worker is now running, but had a 70-minute crash-loop after `make dev`

`docker logs worldview-knowledge-graph-path-insight-worker-1` shows a
`relation "path_insight_jobs" does not exist` UndefinedTableError loop from
13:55:25 UTC through 14:09:38 UTC, then a clean restart at 14:12:13 with no
errors since. The table now exists (verified via psql); the crash-loop was
caused by the worker container starting *before* `intelligence-migrations`
finished. Migration container `worldview-intelligence-migrations-1` is now
in `Exited (0)` so the table is current at version 0036.

This is the same class of defect as D-INIT-1 — racy `depends_on` chain.
Worth lifting as **D-R3-007** because it's a different surface (intelligence
producer) and would be cataclysmic if intelligence-migrations had been any
slower.

### 4.2 Path queue is empty AND seeder cannot find any hubs

```sql
SELECT count(*) FROM path_insight_jobs;  -- 0
SELECT count(*) FROM path_insights;      -- 0
```

`PathInsightSeeder` runs nightly at `30 2 * * *` (next fire: ~13h from now,
2026-05-10 02:30 UTC). It would still produce zero jobs because of:

```python
# services/.../infrastructure/workers/path_insight_seeder.py:30
_HUB_MIN_RELATIONS = 10
```

against the live distribution:

```sql
SELECT subject_entity_id, count(*) FROM relations GROUP BY 1 ORDER BY 2 DESC;
-- max=3, all 8 subjects
```

So the demo will hit Sunday 02:30 UTC, the seeder will run, find 0 hubs,
log `path_insight_seeder_no_hubs_found`, and the `/paths` endpoint stays
permanently empty. This is the path-insight equivalent of the
NarrativeGenerationWorker problem in §2.

The hub threshold is set for a fully populated KG (PLAN-0074 assumed
hundreds of relations per top-50 entity); the demo KG has ~2 relations per
entity — three orders of magnitude below.

---

## 5. API contract validation vs. worldview-web

Frontend client: `apps/worldview-web/lib/api/intelligence.ts`. Tests:
`apps/worldview-web/__tests__/intelligence/intelligence-hooks.test.ts`.

| Frontend call (relative to `/api/`) | Backend route (S9) | Match? |
|---|---|---|
| GET `/v1/entities/{id}/intelligence` | proxy.py:2127 `/entities/{entity_id}/intelligence` (S9 prefix `/v1`) | yes |
| GET `/v1/entities/{id}/paths?...` | proxy.py:2302 `/entities/{entity_id}/paths` | yes |
| GET `/v1/entities/{id}/narratives?cursor&limit` | proxy.py:2206 `/entities/{entity_id}/narratives` | yes |
| POST `/v1/entities/{id}/narratives/generate` | proxy.py:2242 | yes |

Response shape: `EntityIntelligencePublic` (S7
`application/schemas_intelligence.py`) → `intelligence` types in
`apps/worldview-web/types/intelligence.ts`. Field-by-field match for
`narrative` (current), `health_score`, `confidence_breakdown.{mean_*,
relation_count, latest_evidence_at, source_distribution, confidence_trend}`,
`key_metrics`, `data_completeness`. **No contract drift.**

The contract spine is fine. The data plane is broken.

---

## 6. Defect rows (append to `2026-05-09-pre-demo-qa-defect-register.md`)

```yaml
- id: D-R3-001
  va: VA-2
  surface: A4-intelligence-tab, A7
  severity: HF-3
  status: open
  agent: R3
  found_at: 2026-05-09T17:13:00Z
  reproduce: |
    TOKEN=$(curl -fsS -X POST http://localhost:8000/v1/auth/dev-login \
      -H 'content-type: application/json' \
      -d '{"email":"demo@worldview.local"}' | jq -r .access_token)
    for EID in 11111111-0001-7000-8000-000000000001 \
               11111111-0002-7000-8000-000000000001 \
               11111111-0003-7000-8000-000000000001 \
               11111111-0007-7000-8000-000000000001; do
      curl -sS -o /dev/null -w "%{http_code}\n" \
        "http://localhost:8000/v1/entities/$EID/intelligence" \
        -H "authorization: Bearer $TOKEN"
    done
    # Returns 500 for all four entities.
  evidence:
    - all four S9 calls return 500 with body {"error":"internal_error"}
    - kg log: "column \"confidence_components\" does not exist" UndefinedColumnError
    - failing query is in
      services/knowledge-graph/src/knowledge_graph/infrastructure/intelligence_db/repositories/intelligence_aggregates_repository.py:47-60
      (also a duplicate query at routes.py:109 referencing the same column)
    - DB schema check: `\d relations` shows base_confidence/confidence/etc,
      no confidence_components JSONB column; no migration in
      services/intelligence-migrations/alembic/versions/ creates one
  root_cause: |
    Schema drift. The `relations.confidence_components` JSONB column was
    designed in PLAN-0074 Wave B (per .claude-context.md line 52) but never
    actually shipped in any intelligence-migrations revision. Two read-side
    queries reference it: `IntelligenceAggregatesRepository.get_confidence_breakdown`
    (the failing one) and the helper at `api/routes.py:109`. Every call to
    `GET /v1/entities/{id}/intelligence` raises ProgrammingError → 500.
    Cascade: this is the only data path used by the Intelligence tab AND by
    rag-chat's `S7IntelligenceClient.get_entity_intelligence` (the chat tool
    catalog, A7 quality bar). Both fail identically.
  fix_decision: fix-now
  proposed_fix: |
    Two options, equivalent for the demo:
    (a) Repoint the SQL to scalar columns:
        `AVG(confidence) AS mean_support` (and drop the corroboration/contradiction
        averages, which don't exist as scalars) — quickest path to a working
        endpoint with degraded breakdown fidelity.
    (b) Add an Alembic migration creating
        `relations.confidence_components JSONB DEFAULT '{}'::jsonb` and a
        post-step that backfills support=base_confidence for existing rows so
        the AVG() calls produce a number.
    Recommend (a) because (b) requires upstream populators (ConfidenceWorker,
    `application/blocks/`) to start writing the JSONB and that touches more
    of PLAN-0074 than is safe in a 36h window. Capture the schema-drift TODO
    as a post-demo plan.
  spawned_plan: PLAN-0087-A candidate
  fix_commit: null
  validation_evidence: null
  closed_at: null

- id: D-R3-002
  va: VA-2
  surface: A4-intelligence-tab, A7
  severity: HF-3
  status: open
  agent: R3
  found_at: 2026-05-09T17:14:00Z
  reproduce: |
    docker exec worldview-postgres-1 psql -U postgres -d intelligence_db \
      -c "SELECT count(*) FROM entity_narrative_versions;"  # 0
    docker logs worldview-knowledge-graph-scheduler-1 | grep narrative_generation
    # No matches — Worker 13D-3 has never fired in this deployment
  evidence:
    - 0 rows in `entity_narrative_versions`
    - scheduler.py line 173-183: cron `hour=3 minute=0 day_of_week=sun`
      means next fire is 2026-05-10T03:00Z (~10h from this audit)
    - generate_narrative.py:430 — `if self._llm is None: return template-v1`
    - scheduler.py:335 — `GenerateNarrativeUseCase(write_session_factory, ...)`
      called WITHOUT `llm_client=`; the worker therefore always takes the
      template-v1 fallback even after the cron fires
  root_cause: |
    Three compounding wiring bugs:
    1. NarrativeGenerationWorker is registered with weekly cron
       (`day_of_week=sun`) only. There is no INITIAL or event-driven trigger.
    2. The `INITIAL` enum value in NarrativeGenerationReason is unused; no
       startup-time seed loop calls `run_batch(reason=INITIAL)` against
       the demo top-N entities.
    3. `build_workers()` instantiates GenerateNarrativeUseCase without an
       `llm_client`, so even the Sunday cron will produce template-v1 stubs
       which fail the demo "real content" bar.
  fix_decision: fix-now
  proposed_fix: |
    Smallest-diff path:
    (a) Pass `llm_client=llm_client` in `scheduler.py` build_workers narrative
        section (line 335) — same pattern already used by NarrativeRefreshWorker
        and DefinitionRefreshWorker.
    (b) Add a POST `/internal/v1/narratives/seed-demo-batch` admin route or a
        `make seed-narratives` script that POSTs `/narratives/generate` for the
        demo top-N entities, awaiting the worker's `run_batch(INITIAL, ...)`.
        S9 already exposes the per-entity manual trigger at
        proxy.py:2242 with valkey rate-limiting; a script can drive it.
    (c) Optional follow-up: change the cron to daily until the demo or invoke
        `run_batch` from KG service startup behind an env flag.
    Persists narratives so the Intelligence tab (and the A7 chat tool) shows
    real LLM-generated content rather than empty `narrative: null`.
  spawned_plan: PLAN-0087-A candidate
  fix_commit: null
  validation_evidence: null
  closed_at: null

- id: D-R3-003
  va: VA-2
  surface: A4-intelligence-tab (paths sub-card), A7
  severity: HF-4
  status: open
  agent: R3
  found_at: 2026-05-09T17:14:30Z
  reproduce: |
    docker exec worldview-postgres-1 psql -U postgres -d intelligence_db \
      -c "SELECT count(*) FROM path_insights; SELECT count(*) FROM path_insight_jobs;"
    # 0, 0
    curl -sS "http://localhost:8000/v1/entities/11111111-0001-7000-8000-000000000001/paths" \
      -H "authorization: Bearer $TOKEN"
    # {"entity_id":"...","paths":[],"total":0,"freshness_ts":null}
  evidence:
    - 0 rows in `path_insights` and `path_insight_jobs`
    - PathInsightSeeder cron `30 2 * * *` next fires 2026-05-10T02:30Z
    - path_insight_seeder.py:30 `_HUB_MIN_RELATIONS = 10`
    - max relations per subject in `relations` table: 3 (8 distinct subjects)
    - therefore the seeder will return 0 hubs even after firing
  root_cause: |
    Two-layer problem.
    1. Pre-demo cold start — seeder hasn't run yet on this deployment.
    2. Even after it runs, the hub threshold (10 outgoing relations) is set
       for a fully-populated KG; the live KG averages ~2 relations per
       subject. Seeder will log `path_insight_seeder_no_hubs_found` and
       insert nothing.
    Cascade: `/paths` returns `[]` for every entity, so the Intelligence tab
    "key relationships" / "multi-hop opportunities" panel is permanently
    empty. The chat tool catalog's `get_entity_paths` also returns nothing,
    silently weakening A7 ("explain key relationships").
  fix_decision: fix-now
  proposed_fix: |
    (a) Lower `_HUB_MIN_RELATIONS` to 1 for the demo (or read from settings;
        no env var exists today — settings.path_insight_seeder_cron exists
        but no threshold settings).
    (b) Add a manual seed entry-point — script that bulk-inserts
        `path_insight_jobs (entity_id, status='pending')` rows for the demo
        top-N entities, then waits for PathInsightWorker to drain them.
    (c) Schedule PathInsightSeeder hourly until the demo, or call
        `seed_hub_entities()` once at service startup behind an env flag.
    A combined (a)+(b) is a 30-line patch and surfaces real paths.
    NOTE: the underlying KG sparsity (only 18 relations across 8 subjects)
    is upstream of R3 — see audit R6/R7 (VA-3). Fixing path computation
    without fixing KG depth produces only `EXPOSED_TO_THEME` paths.
  spawned_plan: PLAN-0087-A candidate
  fix_commit: null
  validation_evidence: null
  closed_at: null

- id: D-R3-004
  va: VA-2
  surface: A7
  severity: HF-3
  status: open
  agent: R3
  found_at: 2026-05-09T17:15:00Z
  reproduce: |
    docker exec worldview-postgres-1 psql -U postgres -d intelligence_db -c \
      "SELECT canonical_name FROM canonical_entities WHERE canonical_name ILIKE '%OpenAI%';"
    docker exec worldview-postgres-1 psql -U postgres -d intelligence_db -c \
      "SELECT alias_text FROM entity_aliases WHERE alias_text ILIKE '%OpenAI%';"
    # Both empty.
  evidence:
    - 0 rows for OpenAI in canonical_entities and entity_aliases
    - PRD-0087 §2.1 A7 quality bar: 'Show me the entity graph around OpenAI'
    - PRD-0087 demo top-N includes OPENAI explicitly
  root_cause: |
    OpenAI was never canonicalized in the seed bundle. With only 12
    instruments in market_data_db (D-INIT-3) and 301 canonical_entities,
    private companies that aren't in the SP500 OHLCV feed never get a
    canonical_entity_id minted. There is no manual override for adding
    famous private entities to the demo.
  fix_decision: fix-now
  proposed_fix: |
    Add OpenAI (and any other demo-script private entities) to the seed
    fixtures consumed by the entity-discovered consumer. The minimum
    viable seed is one row in `canonical_entities` (entity_type='company',
    canonical_name='OpenAI') plus a couple of rows in `entity_aliases`
    ('OpenAI', 'Open AI'). The narrative trigger script in D-R3-002 then
    needs to include this entity.
    Cross-references with the KG-depth defect (VA-3) — even with the
    canonical entity added, OpenAI will have ~0 relations until the
    extraction pipeline catches up. Acceptable short-term: a seeded
    EXPOSED_TO_THEME ('AI') relation so the A7 demo path shows non-empty
    output.
  spawned_plan: PLAN-0087-A candidate
  fix_commit: null
  validation_evidence: null
  closed_at: null

- id: D-R3-005
  va: VA-2 / VA-10
  surface: A7 (chat trust ranking), retrieval substrate
  severity: SF-2
  status: open
  agent: R3
  found_at: 2026-05-09T17:15:30Z
  reproduce: |
    grep -nE "_trust_scorer.score" \
      services/rag-chat/src/rag_chat/application/pipeline/retrieval_orchestrator.py
    # 11 call sites. None pass evidence_count=. Two pass extraction_confidence=.
  evidence:
    - retrieval_orchestrator.py lines 285, 329, 365, 403, 444, 474, 510,
      528, 546, 578, 604 — all `score(source_type=...)` only
    - trust_scorer.py:64-65 — `evidence_count=0 → corr_factor=0.5` (constant)
    - PLAN-0079 §1 advertises "multi-factor"; effective formula is
      `0.4*source_authority + 0.05 + (0.05 or 0.1*extraction_confidence)`
  root_cause: |
    PLAN-0079 Wave A landed the TrustScorer class but the call-site migration
    (Wave B?) only updated 2 of 11 sites to pass `extraction_confidence`,
    and 0 sites pass `evidence_count`. Corroboration premium is therefore
    flat for every retrieved item, defeating the "more sources => higher
    trust" demo narrative.
    No Prometheus telemetry exists for trust_weight (only debug logging),
    so this regression has been silent.
  fix_decision: defer-or-mitigate (post-demo if scope-limited; fix-now if
    director plans to use the trust badges in the demo)
  proposed_fix: |
    For each branch in retrieval_orchestrator.py that builds a RetrievedItem
    from a relation/claim source, populate evidence_count from
    `relations.evidence_count` (already a column, see `\d relations`) and
    pass it through. For free-text vector hits (line 285), evidence_count is
    not directly available; fall back to constructing it from
    `chunk.entity_mentions` count. Add a Histogram for trust_weight.
  spawned_plan: PLAN-0087-A optional
  fix_commit: null
  validation_evidence: null
  closed_at: null

- id: D-R3-006
  va: VA-2
  surface: ops / health
  severity: SF-1
  status: open
  agent: R3
  found_at: 2026-05-09T17:16:00Z
  reproduce: |
    docker logs worldview-knowledge-graph-path-insight-worker-1 --tail 200 \
      | grep -c path_insight_worker_fatal_error
    # Multiple fatal restarts between 13:55 and 14:09 UTC; healthy after 14:12
  evidence:
    - 14 consecutive `path_insight_worker_fatal_error` events
    - Cause: `relation "path_insight_jobs" does not exist`
    - Worker restarted into healthy state once intelligence-migrations
      completed; D-INIT-1 also describes the same race
  root_cause: |
    `worldview-knowledge-graph-path-insight-worker` `depends_on` does NOT
    include `intelligence-migrations`. On a cold `make dev`, the worker boots
    before DDL is applied, crash-loops for ~15 minutes, and only stabilizes
    after the migration container exits successfully. If migrations had been
    slower (e.g. the LLM-driven one in `populate_embeddings.py` that already
    threw a SyntaxError on this deploy), the worker would be unhealthy at
    demo time.
  fix_decision: fix-now
  proposed_fix: |
    Add `worldview-intelligence-migrations` to `depends_on:` in the
    `knowledge-graph-path-insight-worker` service entry of
    `infra/compose/docker-compose.yml`. Or, lower the worker's restart cadence
    so migration drift retries don't burn through `restart: on-failure` quotas
    before the schema is ready.
  spawned_plan: D-INIT-1 fix should subsume this
  fix_commit: null
  validation_evidence: null
  closed_at: null

- id: D-R3-007
  va: VA-2
  surface: docs (PRD-0087)
  severity: INFO
  status: open
  agent: R3
  found_at: 2026-05-09T17:16:30Z
  reproduce: |
    grep -n "narrative\|/health" docs/specs/0087-pre-demo-qa-program.md \
      | head -20
    # PRD §2.1 A4: 'Intelligence tab shows narrative + paths + health + bundle'
    # implies four endpoints; only /intelligence + /paths + /narratives exist.
  evidence:
    - Frontend client (`apps/worldview-web/lib/api/intelligence.ts`)
      uses 4 endpoints, none of them `/narrative` (singular) or `/health`
    - S9 proxy.py exposes only `/intelligence`, `/paths`, `/narratives`,
      `/narratives/generate`
    - S7 entities.py mounts `/intelligence` and `/intelligence` (internal);
      health_score is a field of `EntityIntelligencePublic`
  root_cause: |
    PRD wording in §2.1 A4 enumerates "narrative + paths + health + bundle"
    as if four distinct endpoints. They are conceptual sub-cards of the
    Intelligence tab, all served by `/intelligence` (a single bundle) plus
    `/paths` for the multi-hop card.
  fix_decision: fix-now (doc edit only)
  proposed_fix: |
    PRD-0087 §2.1 A4: replace 'narrative + paths + health + bundle' with
    'Intelligence tab fetches `/v1/entities/{id}/intelligence` (current
    narrative + health_score + confidence breakdown + key_metrics +
    data_completeness) and `/v1/entities/{id}/paths` for the multi-hop
    card; both must return non-empty content for the demo top-N.'
    Same in §2.1 A7.
  spawned_plan: null
  fix_commit: null
  validation_evidence: null
  closed_at: null
```

---

## 7. Severity counts and per-VA bumps

After appending the 7 D-R3 rows, update the live tables in
`2026-05-09-pre-demo-qa-defect-register.md`:

```yaml
severity_counts_after_r3:
  HARD_FAIL: 7   # (was 3 — adds D-R3-001/002/003/004 + D-R3-006 SF-1; D-R3-001/2/3/4 are HF, R3-006 is SF, R3-005 SF, R3-007 INFO)
  SOFT_FAIL: 3   # (was 1 — adds D-R3-005 + D-R3-006)
  INFO:      2   # (was 1 — adds D-R3-007)

per_va_after_r3:
  VA-2_Intelligence_layer:
    defects_found: 7   # (was 1)
    HF: 5              # (was 1 — D-INIT-2 already, plus R3-001/002/003/004)
    SF: 1              # (R3-005)
    INFO: 1            # (R3-007)
    closed: 0
```

(Note: D-R3-005 has dual VA-2/VA-10 ownership; counted once under VA-2 here.
 Triage may move it.)

---

## 8. Recommended demo-day fix order (R3 view, ranked by impact-per-hour)

1. **D-R3-001** — 1 line SQL repoint, 5 min. Unblocks A4 + A7 simultaneously.
2. **D-R3-002 part (a)** — Wire `llm_client` into `GenerateNarrativeUseCase`,
   2 lines, 5 min. Required so the next step produces real content.
3. **D-R3-002 part (b)** — Manual `/narratives/generate` driver script for
   demo top-N (~30 lines bash + curl), 30 min including LLM latency.
4. **D-R3-004** — Seed OpenAI canonical_entity + alias, 5 min SQL.
5. **D-R3-003 part (a)+(b)** — Lower `_HUB_MIN_RELATIONS` and bulk-insert
   path_insight_jobs for demo top-N, 20 min.
6. **D-R3-007** — PRD wording cleanup, 5 min.
7. **D-R3-006** — Add `depends_on` to compose, 5 min (also helps D-INIT-1).
8. **D-R3-005** — Skip pre-demo unless trust badges are on the demo script;
   they're not in §2.1 explicitly. Capture as post-demo plan.

Total wall time to "all four entities return non-empty intelligence": ~1.5h
of execution + LLM time. Two of the seven defects are root-cause shared with
D-INIT-1 (D-R3-006) and D-INIT-2 (D-R3-002); fixing these resolves both
init-baseline and R3 findings together.
