# Pre-Demo QA Defect Register — PRD-0087 / PLAN-0087

**Created**: 2026-05-09
**Owner**: Arnau Rodon
**Demo deadline**: 2026-05-11
**Schema**: PRD-0087 §11.1
**Severity codes**: HF-1..HF-10 (hard fail, PRD §3.1), SF-1..SF-5 (soft fail, PRD §3.2), INFO

> Append-only during audit (Wave B). Triage column populated in Wave D.
> All YAML rows below are valid YAML inside a single fenced block per defect.

---

## Pre-Audit Baseline (recorded by main session at Wave A exit, 2026-05-09)

Captured by the main session before Wave B agents fan out. Agents inherit this baseline so they don't re-discover the same issues:

```yaml
baseline_2026-05-09T_init:
  containers_running: 46
  containers_expected_under_infra_profile: 64
  observability_stack: not running (monitoring profile not loaded — by design via `make monitoring`)
  worldview_web_port: 3001 (NOT 3000 — PRD/PLAN doc fix needed)
  api_gateway_port: 8000
  uncommitted_files: 8 (FTS-area work in nlp-pipeline + content-store JWT middleware)

  intelligence_db:
    canonical_entities: 277        # target ≥400 — UNDER
    entity_narrative_versions: 0   # CRITICAL — Intelligence layer producing nothing
    relations: 18                  # target high — KG is virtually empty
    entity_aliases: ?
    entity_embedding_state: ?
    relation_evidence_raw: ?
    provisional_entity_queue: ?
    temporal_events: table_missing # validate whether table renamed or migration missing

  nlp_db:
    chunks: 536
    document_source_metadata_last_7d: 513
    sections: ?
    chunk_embeddings: ?
    entity_mentions: ?
    routing_decisions: ?
    mention_resolutions: ?

  market_data_db:
    instruments: 12                # target top-25 — UNDER (most demo tickers will miss)
    ohlcv_bars: 1916
    company_profiles: ?
    prediction_markets: ?
    earnings_calendar: ?
    economic_events: ?
    fundamental_metrics: ?
```

---

## Init Defects (recorded in Wave A)

```yaml
- id: D-INIT-1
  va: VA-7  # Avro/Kafka pipeline integrity → ops sub-area
  surface: ops
  severity: HF-1  # any 500 / failure on demo path — pipeline failure cascades to every demo surface
  status: open  # functionally fixed by `compose up -d` but ROOT CAUSE not addressed
  agent: main-session
  found_at: 2026-05-09T_init
  reproduce: |
    `make dev` runs `$(COMPOSE_DEV) up -d --build` with `--profile infra`.
    After execution, 18 consumers were in "Created" but never "Started" state:
      - knowledge-graph-{enriched,entity,fundamentals,instrument,instrument-discovered,
        temporal-event,economic-events-dataset,macro-indicator-dataset,
        insider-transactions-dataset,earnings-calendar-dataset,provisional-queued}-consumer
      - knowledge-graph-dispatcher
      - market-data-{dispatcher,ohlcv-consumer,quotes-consumer,fundamentals-consumer,
        prediction-market-consumer,intraday-resampling-consumer}
      - alert-dispatcher
    All 18 are declared in `[infra, all]` profile in `infra/compose/docker-compose.yml`.
  evidence:
    - cmd: docker compose ... ps -a → "Created" status on 18 services
    - resolution: docker compose ... up -d started them; all healthy
  root_cause: |
    Unknown — needs investigation. Hypotheses:
    1. depends_on chain failure caused initial start to skip them on a prior `make dev-rebuild`
    2. A previous crash left them in a half-started state
    3. `--build` did not rebuild dependents; they were created but not started
    Pre-demo MUST identify this so it doesn't recur the morning of the demo.
  fix_decision: TBD  # likely fix-now (investigation) + add a startup health gate
  spawned_plan: null
  fix_commit: null
  validation_evidence: null
  closed_at: null

- id: D-INIT-2
  va: VA-2  # Intelligence layer
  surface: A4-intelligence-tab, A7
  severity: HF-3  # Intelligence layer producing zero output is a hard fail
  status: open
  agent: main-session
  found_at: 2026-05-09T_init
  reproduce: |
    `SELECT COUNT(*) FROM intelligence_db.entity_narrative_versions;` → 0
    `SELECT COUNT(*) FROM intelligence_db.relations;` → 18
    These tables back the Intelligence tab (A4) and the entity-graph chat tool (A7).
  evidence:
    - count_check: 0 narratives, 18 relations vs target hundreds for the demo top-50 entities
  root_cause: |
    NarrativeGenerationWorker (PLAN-0074) has not run, OR has run but not produced rows.
    Possibly blocked on:
    - missing canonical entities (only 277, target ≥400)
    - the missing consumers (D-INIT-1) prevented enrichment events from flowing to the worker
    Now that consumers are up, monitor whether narratives accrue over the next 30 min.
  fix_decision: TBD  # may resolve naturally as consumers process backlog; if not, escalate to PLAN-0087-A or new slot
  spawned_plan: null
  fix_commit: null

- id: D-INIT-3
  va: VA-3  # KG generation pipeline + freshness
  surface: A2 (dashboard), A4 (instrument page), B5 (hands-on instrument deep-dive)
  severity: HF-4  # visible $0/empty on populated tile when director picks a name
  status: open
  agent: main-session
  found_at: 2026-05-09T_init
  reproduce: |
    `SELECT COUNT(*) FROM market_data_db.instruments;` → 12
    Demo path B5 expects director to type any ticker. If <50 instruments seeded, ~80%
    of likely picks will return 404 / empty pages.
  evidence:
    - count: 12 instruments
    - PRD §2.2 B5 quality bar: "if data is sparse, surfaces are honest"
  root_cause: |
    Either (a) seed script not run after a `dev-reset`, or (b) instrument-discovered-consumer
    (just started in D-INIT-1 fix) hasn't processed instrument-discovery events yet.
    Plan T-A-3 expected ≥top-25 instruments seeded.
  fix_decision: TBD
  spawned_plan: null
  fix_commit: null

- id: D-INIT-4
  va: VA-3
  surface: cross-cutting (KG depth)
  severity: SF-2  # affects retrieval and chat answer quality
  status: open
  agent: main-session
  found_at: 2026-05-09T_init
  reproduce: |
    `SELECT COUNT(*) FROM intelligence_db.canonical_entities;` → 277
    PRD T-A-3 acceptance bar: ≥400.
  evidence: 277 < 400 baseline.
  root_cause: |
    Likely insufficient article ingestion or entity resolution backlog.
  fix_decision: TBD

- id: D-INIT-5
  va: VA-5  # frontend critical paths
  surface: docs (PRD-0087 + PLAN-0087)
  severity: INFO  # documentation drift, not a runtime defect
  status: closed
  agent: main-session
  found_at: 2026-05-09T_init
  reproduce: |
    PRD-0087 §3.3 quality bar references "http://localhost:3000". worldview-web container
    binds to 3001 per `infra/compose/docker-compose.yml`.
  evidence: docker port worldview-worldview-web-1 → 3001
  root_cause: |
    Doc was written from memory; 3000 is Next.js default but our compose uses 3001.
  fix_decision: fix-now  # trivial doc edit
  fix_commit: in-tree-edit-2026-05-09  # PLAN-0087 §2/§3/§9 lines 128/129/179/370 corrected
  validation_evidence: grep -n "3000" docs/{specs/0087,plans/0087}* → no matches
  closed_at: 2026-05-09T_init+30m

- id: D-INIT-6
  va: VA-3  # KG generation pipeline
  surface: A4-intelligence-tab, A2-dashboard (entire intelligence layer is hobbled by this)
  severity: HF-1  # cascade-fail — every enriched.v1 event silently fails to fully process
  status: open
  agent: main-session
  found_at: 2026-05-09T_init+45m
  reproduce: |
    1. `docker logs worldview-knowledge-graph-enriched-consumer-1 --since 5m | grep -c evidence_source_metadata_lookup_failed`
       → ≥3 every 5min
    2. Inspecting full traceback: `asyncpg.exceptions.UndefinedTableError: relation "document_source_metadata" does not exist`
       Stack trace points at `services/knowledge-graph/src/knowledge_graph/infrastructure/intelligence_db/repositories/relation_evidence.py:115`
       which queries `SELECT source_name, source_type FROM document_source_metadata WHERE document_id=:doc_id`
    3. `document_source_metadata` exists in `nlp_db`, NOT in `intelligence_db`. KG service is bound to `intelligence_db`.
  evidence:
    - "log: evidence_source_metadata_lookup_failed (3 in last 5m, likely 100% of enriched events)"
    - "code: services/knowledge-graph/.../relation_evidence.py L103-124 — `lookup_source_metadata` SELECT against intelligence_db"
    - "code: services/knowledge-graph/.../enriched_consumer.py L246-262 — fallback triggered when value.get('source_name') is None"
    - "schema: infra/kafka/schemas/nlp.article.enriched.v1.avsc — has `source_type` but NO `source_name` field"
    - "DB: SELECT description IS NOT NULL → 0/301 entities enriched"
  root_cause: |
    Two-part bug:
    (a) The Avro schema `nlp.article.enriched.v1.avsc` does NOT include a `source_name` field. Producer
        (`services/nlp-pipeline/.../article_consumer.py`) cannot include it; consumer always sees None.
    (b) When `source_name is None`, the consumer falls back to `lookup_source_metadata` which queries
        `document_source_metadata` (a nlp_db table) from the intelligence_db session pool — R9 violation
        AND a guaranteed failure since the table doesn't exist in that database.
    Net effect: every enriched.v1 event silently fails after the lookup attempt; downstream relation/claim
    write may proceed but evidence rows lack source provenance, narratives never trigger.
  proposed_fix: |
    Wave E B1 fix — 4 files:
    1. infra/kafka/schemas/nlp.article.enriched.v1.avsc — add `{"name":"source_name","type":["null","string"],"default":null}`
    2. libs/contracts/src/contracts/canonical/ingestion.py — add source_name to NlpArticleEnriched canonical
    3. services/nlp-pipeline/src/nlp_pipeline/infrastructure/messaging/consumers/article_consumer.py — populate source_name from document_source_metadata when emitting enriched event (this lookup is in nlp_db where the table exists — R9-clean)
    4. services/knowledge-graph/src/knowledge_graph/infrastructure/intelligence_db/repositories/relation_evidence.py — DELETE `lookup_source_metadata` method (R9 violation removed)
    5. services/knowledge-graph/src/knowledge_graph/infrastructure/messaging/consumers/enriched_consumer.py — when source_name is None, log warning and continue (no fallback query) — never query nlp_db
    Effort: 1.5-2.5h with tests. Single PR.
  fix_decision: fix-now  # spawn fix agent in Wave E; estimated 2.5h, does not need worktree subagent
  spawned_plan: null
  fix_commit: null
  validation_evidence: null
  closed_at: null
```

---

## Severity Counts (live)

| Severity | Open | In Progress | Closed | Deferred | Dropped |
|----------|------|-------------|--------|----------|---------|
| HARD_FAIL | 3 | 0 | 0 | 0 | 0 |
| SOFT_FAIL | 1 | 0 | 0 | 0 | 0 |
| INFO      | 1 | 0 | 0 | 0 | 0 |

## Per-VA Coverage (live)

| VA | Defects found | HF | SF | INFO | Closed |
|----|---------------|-----|-----|------|--------|
| VA-1 (Chat tool catalog) | 0 | 0 | 0 | 0 | 0 |
| VA-2 (Intelligence layer) | 1 | 1 | 0 | 0 | 0 |
| VA-3 (KG pipeline) | 2 | 1 | 1 | 0 | 0 |
| VA-4 (Retrieval substrate) | 0 | 0 | 0 | 0 | 0 |
| VA-5 (Frontend critical paths) | 1 | 0 | 0 | 1 | 0 |
| VA-6 (Brokerage + portfolio) | 0 | 0 | 0 | 0 | 0 |
| VA-7 (Avro/Kafka integrity) | 1 | 1 | 0 | 0 | 0 |
| VA-8 (Brief intelligence) | 0 | 0 | 0 | 0 | 0 |
| VA-9 (Calendar + predictions) | 0 | 0 | 0 | 0 | 0 |
| VA-10 (TrustScorer) | 0 | 0 | 0 | 0 | 0 |
| VA-11 (S9 contract spine) | 0 | 0 | 0 | 0 | 0 |
| VA-12 (Frozen-dataclass) | 0 | 0 | 0 | 0 | 0 |
| VA-13 (Regression cleanup) | 0 | 0 | 0 | 0 | 0 |
| VA-14 (Multi-tenant) | 0 | 0 | 0 | 0 | 0 |
| VA-15 (Deferred-issues) | 0 | 0 | 0 | 0 | 0 |

## How agents append

Each Wave B agent appends a YAML block per finding immediately after the last YAML block.
Bump the severity counts and per-VA table after each append.
Use the next available `D-XXX` id (continuing sequentially: next is `D-001`).
