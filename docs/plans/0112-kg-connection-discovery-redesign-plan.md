---
id: PLAN-0112
title: KG Connection Discovery — Weird-Path Redesign + Pairwise Pathfinding
prd: PRD-0112
status: draft
created: 2026-06-12
updated: 2026-06-12
---

# PLAN-0112 — KG Connection Discovery: Weird-Path Redesign + Pairwise Pathfinding

## Overview
PRD: [PRD-0112](../specs/0112-kg-connection-discovery-redesign.md)
Investigation: `docs/audits/2026-06-12-weird-path-redesign-feasibility.md`
Services affected: **knowledge-graph (S6)**, **intelligence-migrations**, **api-gateway (S9)**,
**rag-chat (S8)**, **apps/worldview-web**.
Total waves: **6** (W1 independently shippable now). Critical path: W1 → W2 → W3 → (W4 ∥ W5) → W6.

### Pre-flight ledger (verified 2026-06-12)
- **intelligence_db migration HEAD = `0051_unique_ticker_financial_instrument`** → new migration is
  **`0052`** (PRD originally said 0051 — corrected; 0051 is the BP-459 ticker-unique migration).
- **R## max = R34** (no new rules in this plan).
- **PLAN id = PLAN-0112** (TRACKING max was PLAN-0111).
- Existing prior art (do NOT reinvent):
  - `application/use_cases/cypher_path.py::CypherPathUseCase._execute_staged` — staged `*L..L` VLE
    probing (BP-687) + `_build_path_sql(exact_hops=…)` + `_parse_agtype_text` that **already returns
    `nodes(p)/relationships(p)` parsed from agtype text**. This is the reusable engine core.
  - migration `0050_age_entity_properties_gin_index` — GIN index on `entity.properties` (BP-688).
  - `infrastructure/age/path_discovery.py::PathDiscovery._build_2hop_sql/_build_3hop_sql` — the SLOW
    untyped-explicit-edge form (BP-689); retired by W2.
  - `infrastructure/workers/path_insight_seeder.py::PathInsightSeeder` — the re-queue loop (BP-690).
  - `api/paths.py` (KG router), `api-gateway/routes/intelligence.py` (S9 proxy), `schemas/paths.py`.
  - rag-chat `application/pipeline/tool_registry_builder.py` (`compare`/manifest `{version, tools[]}`),
    `application/ports/upstream_clients.py::S7Port.get_entity_paths`,
    `infrastructure/clients/s7_intelligence_client.py`, handler `pipeline/handlers/narrative.py`.

> **⚠ AD-1 reconsideration flagged for /revise-prd**: PRD §AD-1 + FR-8 assume path detail must use a
> NEW "typed fixed-k" query because `RETURN nodes(p)/relationships(p)` fails (BP-SA5-003). But
> `cypher_path.py` **already returns those lists via agtype-text parsing**. So the engine should
> CONSOLIDATE `cypher_path.py`'s VLE-staged-probe-and-parse approach, not build a typed-fixed-k path.
> This reduces W2/W4 scope. The revision pass should update AD-1, FR-2, FR-8 accordingly. Plan tasks
> below are written for the **consolidation** interpretation and tag the divergence.

## Sub-Plans
This is a single cohesive plan (one PRD, tightly coupled waves) executed as 6 waves. No split into
service-sub-plans because W2/W3 share the S6 engine + scorer and must land in order.

## Wave Summary

| Wave | Goal | Services | Depends | Shippable alone |
|------|------|----------|---------|-----------------|
| **W1** | Stop the Postgres flood (no schema change) | S6 | none | **YES — do now** |
| **W2** | Consolidate VLE engine (`GraphPathEngine`) + membership pruning + maxhops spike | S6 | W1 | no |
| **W3** | Migration 0052 + `node_degree` + `WeirdnessScorer` (B×C×E) + degree refresh | intelligence-migrations, S6 | W2 | no |
| **W4** | Pairwise `GET /paths/between` (KG+S9) + `get_path_between` LLM tool | S6, S9, S8 | W2 (W3 for scoring) | no |
| **W5** | Global `GET /connections/weird` feed (KG+S9) + frontend | S6, S9, web | W3 | no |
| **W6** | Quality gate + metric finalisation + docs | S6, docs | W3,W4,W5 | no |

## Checkpoint: skeleton written; waves below.

---

## Wave 1 — Remediation (stop the flood)

**Goal**: Halt the nightly re-queue of terminally-failed jobs and the statement-timeout flood, with
**zero schema change**, shippable in hours. **Depends on**: none. **Effort**: 1–2 h.
**Architecture layer**: infrastructure + config.

#### T-1-01 — Seeder skips terminally-failed anchors (BP-690)
**Type**: impl · **depends_on**: none · **blocks**: T-1-04
**Target files**: `services/knowledge-graph/src/knowledge_graph/infrastructure/workers/path_insight_seeder.py`
**PRD reference**: §3.1 FR-1, §9, §16 W1
**What to build**: Add a `NOT EXISTS` guard to the hub-enqueue query so an entity with a `failed` job at
`retry_count >= max_retries` (3) is never re-enqueued. Today the seeder skips only entities with a fresh
`path_insights` row; a never-completing anchor has no such row → re-queued forever.
**Logic**: enqueue SQL gains
`AND NOT EXISTS (SELECT 1 FROM path_insight_jobs j WHERE j.entity_id = c.entity_id AND j.status='failed' AND j.retry_count >= :max_retries)`.
Keep the existing freshness + `ON CONFLICT DO NOTHING` logic.
**Read/Write**: write (enqueue) — existing UoW.
**Tests to write** (extend `tests/unit/infrastructure/workers/test_path_insight_seeder.py`):
| Test | Verifies | Type |
|------|----------|------|
| test_seeder_skips_terminally_failed | anchor with failed/retry=3 job not enqueued | unit |
| test_seeder_still_enqueues_fresh_failure | anchor with failed/retry<3 still enqueued | unit |
| test_seeder_still_skips_fresh_insights | existing freshness guard unbroken | unit |
**Acceptance**: [ ] failed/retry≥3 excluded [ ] metric counts skips (T-1-03) [ ] existing seeder tests green

#### T-1-02 — Raise `PATH_INSIGHT_HUB_MIN_RELATIONS` off the demo-era default
**Type**: config · **depends_on**: none · **blocks**: none
**Target files**: `services/knowledge-graph/src/knowledge_graph/infrastructure/workers/path_insight_seeder.py`
(the `_HUB_MIN_RELATIONS` env read), `dev.local.env.example` if present.
**PRD reference**: §3.1 FR-1, §AD-4
**What to build**: Change the default for `PATH_INSIGHT_HUB_MIN_RELATIONS` from `2` (lowered for the empty
demo KG, D-R3-005) to a production value (**5**), reducing the qualifying-hub set. Document it as an env
override. NOTE: value is advisory — W2's fast engine makes the volume safe; this is belt-and-suspenders.
**Tests**: test_hub_min_relations_default_is_5 (unit).
**Acceptance**: [ ] default 5 [ ] still env-overridable [ ] documented

#### T-1-03 — Remediation metrics
**Type**: impl · **depends_on**: none · **blocks**: none
**Target files**: `services/knowledge-graph/src/knowledge_graph/infrastructure/metrics/prometheus.py`,
seeder + worker call sites.
**PRD reference**: §13
**What to build**: Add counters `path_jobs_requeued_skipped_total` (seeder, proof of FR-1) and ensure
`path_jobs_failed_total` exists/incremented. structlog the skipped-count per seeder run.
**Tests**: test_metric_increments_on_skip (unit, with a fake registry).
**Acceptance**: [ ] both metrics emit [ ] alert-ready (NFR-3)

#### T-1-04 — Hard-cap maxhops=3 + AGE-session Postgres hygiene
**Type**: impl/config · **depends_on**: T-1-01 · **blocks**: T-2-04
**Target files**: `services/knowledge-graph/src/knowledge_graph/infrastructure/age/path_discovery.py`
(`_DISCOVERY` constants + `_setup_age_session`), `config.py` (new `path_max_hops: int = 3`).
**PRD reference**: §3.1 FR-1, §3.3 NFR-2, §AD-5
**What to build**: Introduce a config knob `path_max_hops` (default **3**) consumed by discovery; ensure the
3-hop query path is the ceiling. In the AGE session setup add
`SET LOCAL max_parallel_workers_per_gather = 0` (kills the `FATAL: parallel worker` noise) alongside the
existing `SET LOCAL statement_timeout`. Confirm `_STATEMENT_TIMEOUT_MS` (25000) < client `wait_for` (BP-688).
**Tests**: test_age_session_disables_parallel_workers (unit, assert SQL emitted); test_max_hops_default_3.
**Downstream test impact**: `tests/unit/infrastructure/age/test_path_discovery.py` — session-setup assertions.
**Acceptance**: [ ] parallel-workers=0 set [ ] cap=3 config-driven [ ] timeouts ordered correctly

#### Pre-read
- `infrastructure/workers/path_insight_seeder.py`, `infrastructure/age/path_discovery.py` (`_setup_age_session`),
  `infrastructure/metrics/prometheus.py`, `config.py` (path_insight knobs).

#### Validation Gate
- [ ] ruff + mypy on changed files · [ ] ≥6 new unit tests green · [ ] seeder + path_discovery suites green
- [ ] No schema change introduced (grep: no alembic edit) · [ ] docs: note knob in service .claude-context.md

#### Architecture Compliance
- [ ] R12 structlog (seeder skip log) · [ ] R11 utc_now if any timestamp · [ ] R32 N/A (no migration)
- [ ] R25/R27 N/A (worker/infra only, no new use case)

#### Break Impact
| Broken File | Why | Fix |
|-------------|-----|-----|
| `tests/unit/infrastructure/workers/test_path_insight_seeder.py` | new NOT EXISTS clause + default 5 | update fixtures/expected SQL |
| `tests/unit/infrastructure/age/test_path_discovery.py` | session SQL gains parallel-workers SET | update assertion |

#### Regression Guardrails
- **BP-690**: this wave IS the fix — verify the NOT EXISTS keys on terminal failure, not success artifact.
- **BP-688**: do not reintroduce timeout inversion; keep statement_timeout(25s) < wait_for(30s).
- **BP-687**: do not touch cypher_path staged-probing here (W2 owns engine).

---

## Wave 2 — Consolidate the VLE engine + membership pruning + maxhops spike

**Goal**: One `GraphPathEngine` port; the per-anchor discovery stops using the slow untyped-explicit form
(BP-689) and reuses `cypher_path.py`'s proven VLE-staged-probe-and-parse; membership edges pruned; the
committed maxhops cap is set by measurement. **Depends on**: W1. **Effort**: 4–6 h.
**Architecture layer**: application port + infrastructure adapter.

> **Scope note (AD-1 consolidation)**: because `cypher_path.py` already returns full path detail via
> agtype-text parsing, W2 does NOT build a separate "typed fixed-k" detail query. It extracts the
> staged-probe-and-parse into the shared adapter for membership pruning. Tag any new file
> `(NEW — created in this plan)`.
>
> **⚠ BUILD CORRECTION (2026-06-13, W2 shipped):** AGE 1.5 rejects multi-label VLE (`-[:A|B*L..L]-`
> parse error at `|`), so the "typed label allow-list on the VLE pattern" described in T-2-02/T-2-03
> below was **not possible**. Actual impl: **untyped VLE `-[*L..L]-` + post-hoc Python membership
> filter** (drop paths whose `rel_types` ∩ `MEMBERSHIP_RELATIONS`). GUCs use session-scoped `SET`
> (not `SET LOCAL`, which evaporated before the traversal txn — the live flood bug). Anchor discovery
> probes from depth **2** (`PathInsight` needs hop_count ≥ 2); pairwise/exists from depth 1. Maxhops
> spike committed **cap = 3** (hop-4/5 blow up — post-hoc filter doesn't prune the frontier). Read the
> task text below as intent; the engine docstring + PRD §AD-1/FR-3 are authoritative.

#### T-2-01 — `GraphPathEngine` port (NEW)
**Type**: impl · **depends_on**: none · **blocks**: T-2-02, T-2-03
**Target files**: `services/knowledge-graph/src/knowledge_graph/application/ports/graph_path_engine.py` (NEW)
**PRD reference**: §6.5 (New Port)
**What to build**: ABC `GraphPathEngine` (R25 port) with: `path_exists(source, target, *, max_hops) -> int | None`;
`find_paths_between(source, target, *, max_hops, prune_membership, limit) -> list[RawPath]`;
`find_paths_from_anchor(entity_id, *, max_hops, prune_membership, limit) -> list[RawPath]`. Extend `RawPath`
(in `infrastructure/age/path_discovery.py` or a moved location) with `rel_ids: tuple[UUID, ...]`.
**Port interfaces**: this IS the port. **Read/Write**: traversal needs `LOAD 'age'` → write-session
exception (documented, per CypherPathUseCase precedent, R27).
**Tests**: test_graph_path_engine_port_is_abc; RawPath rel_ids carried.
**Acceptance**: [ ] ABC with 3 methods [ ] RawPath has rel_ids [ ] no infra import in port

#### T-2-02 — `AgeGraphPathEngine` adapter (NEW) — consolidate cypher_path + retire explicit form
**Type**: impl · **depends_on**: T-2-01 · **blocks**: T-2-04, T-4-01
**Target files**: `services/knowledge-graph/src/knowledge_graph/infrastructure/age/graph_path_engine.py` (NEW);
refactor-extract from `application/use_cases/cypher_path.py` (`_build_path_sql`, `_execute_staged`,
`_parse_agtype_text`, `_setup_age_session`); deprecate `path_discovery.py::_build_2hop_sql/_build_3hop_sql`.
**PRD reference**: §6.5, §AD-1; BP-687/688/689
**What to build**: Implement the port using staged `*L..L` VLE probing (BP-687) + agtype-text parse for
detail; membership pruning = typed relationship label allow-list in the VLE pattern (e.g.
`-[:PARTNER_OF|SUPPLIER_OF|...*L..L]-`) built from `MEMBERSHIP_RELATIONS` complement (T-2-03);
`SET LOCAL max_parallel_workers_per_gather = 0` + statement_timeout. `find_paths_from_anchor` leaves the
target end free (anchor discovery); `find_paths_between` binds both ends. NEVER emit untyped `-[r]-` (BP-689).
**Logic / errors**: timeout → `CypherTimeoutError`-style → caller maps (job failed / 503). Idempotent reads.
**Tests** (`tests/unit/infrastructure/age/test_graph_path_engine.py` NEW):
| Test | Verifies |
|------|----------|
| test_engine_emits_typed_vle_only | generated SQL contains `*` VLE + typed labels, never bare `-[r]-` |
| test_membership_labels_excluded | allow-list excludes the 4 membership relations |
| test_staged_probe_stops_at_first_depth | `*1..1` then `*2..2`… stops on first hit (no ORDER BY length) |
| test_rel_ids_parsed | rel_ids populated from relationships(p) |
**Acceptance**: [ ] reuses cypher_path logic (no duplicate) [ ] typed-only [ ] pruning works [ ] CypherPathUseCase still green

#### T-2-03 — `MEMBERSHIP_RELATIONS` domain constant + relation-label catalogue
**Type**: impl · **depends_on**: none · **blocks**: T-2-02
**Target files**: `services/knowledge-graph/src/knowledge_graph/domain/constants.py` (or existing constants module)
**PRD reference**: §6.5 (Enum/constants), §3.1 FR-3
**What to build**: `MEMBERSHIP_RELATIONS = frozenset({"IS_IN_SECTOR","LISTED_ON","OPERATES_IN_COUNTRY","HEADQUARTERED_IN"})`
as **uppercase AGE edge-label strings** — NOT `RelationType` StrEnum values (those are lowercase, e.g.
`RelationType.LISTED_ON == "listed_on"`), and ⚠ `IS_IN_SECTOR`/`HEADQUARTERED_IN` are NOT members of the
16-entry `RelationType` enum (they live only in the AGE label space / `relation_type_registry`). AGE stores
labels uppercased-with-underscores via `age_sync_worker._derive_edge_label`. `TRAVERSABLE_RELATIONS` =
`age_sync_worker._AGE_EDGE_LABELS` (the existing 27-relation + EVENT_EXPOSES whitelist) **minus**
`MEMBERSHIP_RELATIONS`. Validate at import that all 4 membership strings ∈ `_AGE_EDGE_LABELS` (fail fast on drift).
**Tests**: test_membership_relations_frozen; test_membership_subset_of_age_labels; test_traversable_excludes_membership.
**Acceptance**: [ ] uppercase AGE-label strings (not RelationType enum) [ ] validated ⊆ `_AGE_EDGE_LABELS` [ ] traversable = whitelist − membership

#### T-2-04 — Wire engine into `PathInsightWorker`; retire `PathDiscovery`
**Type**: impl · **depends_on**: T-2-02, T-1-04 · **blocks**: T-3-04
**Target files**: `infrastructure/workers/path_insight_worker.py`, DI/composition (`infrastructure/.../container` or
`workers/path_insight_worker_main.py`).
**PRD reference**: §6.7 (Discovery flow)
**What to build**: Inject `GraphPathEngine` (replacing `PathDiscovery`) into the worker; discovery calls
`find_paths_from_anchor(..., prune_membership=True, max_hops=path_max_hops)`. Keep scoring call site intact
(W3 swaps the scorer). Self-loop filtering happens in the scorer (W3) but add a guard here too.
**Tests**: test_worker_uses_graph_path_engine (mock engine); test_worker_passes_prune_membership.
**Downstream test impact**: `tests/unit/infrastructure/workers/test_path_insight_worker.py` (engine mock swap).
**Acceptance**: [ ] worker uses port [ ] PathDiscovery removed/deprecated [ ] worker tests green

#### T-2-05 — maxhops measurement spike → commit the cap (SPIKE/docs)
**Type**: docs/test · **depends_on**: T-2-02 · **blocks**: T-3 (cap value)
**Target files**: `scripts/eval/measure_maxhops_pruned.py` (NEW), append results to
`docs/audits/2026-06-12-weird-path-redesign-feasibility.md`.
**PRD reference**: §3.1 FR-10, §AD-5, §14 OQ-3
**What to build**: A read-only script that runs `path_exists` + `find_paths_between` on the **membership-pruned**
graph for representative pairs (hub↔hub, hub↔leaf, distant, connected, disconnected) at max_hops 3/4/5 and
reports p50/p95 latency. Decision rule: commit `path_max_hops` = largest hop count with pairwise p95 < 1 s AND
per-anchor discovery < 5 s. Update `config.py` default if >3 is safe; record in OQ-3.
**Acceptance**: [ ] measured table recorded [ ] cap committed with evidence [ ] OQ-3 resolved in PRD

#### Pre-read
- `application/use_cases/cypher_path.py` (full), `infrastructure/age/path_discovery.py`,
  `infrastructure/workers/path_insight_worker.py`, `domain/` constants/relation enum.

#### Validation Gate
- [ ] ruff + mypy · [ ] ≥10 new unit tests · [ ] CypherPathUseCase + worker suites green
- [ ] No untyped `-[r]-` anywhere (grep guard) · [ ] spike results recorded · [ ] docs updated

#### Architecture Compliance
- [ ] R25 — worker depends on `GraphPathEngine` ABC, not the adapter · [ ] R27 — write-session exception documented
- [ ] R10/R11 — N/A new ids/timestamps · [ ] R12 structlog in adapter

#### Break Impact
| Broken File | Why | Fix |
|-------------|-----|-----|
| `tests/.../test_path_discovery.py` | PathDiscovery deprecated | port assertions to engine test or keep as thin shim test |
| `tests/.../test_path_insight_worker.py` | worker now takes engine | swap mock |
| `application/use_cases/cypher_path.py` callers | logic extracted | keep public API stable; delegate to shared helpers |

#### Regression Guardrails
- **BP-689**: engine must be typed VLE only — the `test_engine_emits_typed_vle_only` test is the guard.
- **BP-687**: reuse staged `*L..L`; never `ORDER BY length(p)` before LIMIT.
- **BP-SA5-003**: detail via agtype-text parse (as cypher_path does); do not attempt prepared-statement agtype lists.
- **BP-461/450**: no `shortestPath()`/`ALL(... WHERE)` (AGE 1.5 unsupported).

---

## Wave 3 — Migration 0052 + node_degree + WeirdnessScorer (B×C×E)

**Goal**: Land the new persisted metric. **Depends on**: W2 (engine + committed maxhops). **Effort**: 5–7 h.
**Architecture layer**: schema → infrastructure (degree refresh, repo) → application (scorer).

#### T-3-01 — Migration 0052: node_degree, graph_stats, path_insights columns (schema)
**Type**: schema · **depends_on**: none · **blocks**: T-3-02, T-3-03, T-3-04
**Target files**: `services/intelligence-migrations/alembic/versions/0052_weirdness_metric_and_node_degree.py` (NEW)
**PRD reference**: §6.4
**What to build** (R24 — intelligence-migrations ONLY owns intelligence_db DDL; current HEAD `0051`):
- `node_degree(entity_id UUID PK FK→canonical_entities CASCADE, degree INT NOT NULL DEFAULT 0 CHECK≥0,
  degree_meaningful INT NOT NULL DEFAULT 0 CHECK≥0, refreshed_at TIMESTAMPTZ NOT NULL DEFAULT now())`.
- `graph_stats(id SMALLINT PK CHECK(id=1), total_edges INT, total_meaningful_edges INT, max_degree INT,
  refreshed_at TIMESTAMPTZ)` — single-row normaliser store.
- ALTER `path_insights` ADD (all NULLable, additive R5): `dst_entity_id UUID FK→canonical_entities`,
  `reliability FLOAT`, `unexpectedness FLOAT`, `semantic_distance FLOAT`, `novelty FLOAT`, `weirdness FLOAT`,
  `scorer_version TEXT`.
- Indexes: `idx_path_insights_global_weird (weirdness DESC) WHERE weirdness IS NOT NULL`;
  `idx_path_insights_dst (dst_entity_id, weirdness DESC)`.
- **Forward-compat**: no NOT NULL without default; no column drops/renames (R5). Downgrade drops the additions.
**Downstream test impact**: `services/intelligence-migrations/tests/` migration-apply test; any KG repo test
asserting `path_insights` column set.
**Tests**: `test_migration_0052.py` (apply + rollback; columns present; indexes exist).
**Acceptance**: [ ] applies on HEAD 0051 [ ] rollback clean [ ] additive only [ ] FAIL-LOUD like 0050 (BP-688)

#### T-3-02 — node_degree + graph_stats refresh in AGE-sync worker
**Type**: impl · **depends_on**: T-3-01 · **blocks**: T-3-03
**Target files**: `infrastructure/workers/age_sync_worker.py`, a new repo
`infrastructure/intelligence_db/repositories/node_degree_repository.py` (NEW) + ABC port
`application/ports/node_degree_repository.py` (NEW).
**PRD reference**: §6.4, §6.7 (degree refresh), §3.1 FR-5
**What to build**: After each AGE-sync cycle, recompute undirected degree (and meaningful-degree excluding
`MEMBERSHIP_RELATIONS`) from `worldview_graph._ag_label_edge` (the ~18 ms aggregation) and upsert into
`node_degree`; upsert `graph_stats` (total/meaningful edges, max_degree). structlog the refresh duration metric.
**Port interfaces**: `NodeDegreeRepositoryPort` (ABC) — impl by `NodeDegreeRepository`. **Read/Write**: write.
**Tests**: test_degree_refresh_upsert; test_meaningful_degree_excludes_membership; test_graph_stats_singlerow.
**Acceptance**: [ ] upsert correct [ ] meaningful split right [ ] metric emitted

#### T-3-03 — WeirdnessScorer service (NEW)
**Type**: impl · **depends_on**: T-3-01, T-3-02 · **blocks**: T-3-04
**Target files**: `application/services/weirdness_scorer.py` (NEW); deprecate `application/services/path_scorer.py`
usage in the worker (keep file for back-compat tests until W6).
**PRD reference**: §6.5 (WeirdnessScorer), §3.1 FR-4
**What to build**: Pure application service (no infra imports, like PathScorer). Inputs: a `RawPath` + injected
pure lookups `degree_of`, `meaningful_degree_of`, `graph_stats`, `embedding_of`, `first_seen_of`. Computes:
- `reliability` = harmonic_mean(edge_confs) (clamp zeros to 1e-6).
- `unexpectedness` = mean over edges of `clamp01(-log(min(1, deg(u)·deg(v)/(2m)))/NORM)`, `m`=graph_stats.total_edges,
  `NORM=-log(1/(2m))`. Adamic-Adar behind a config flag `weirdness_unexpectedness_mode` (AD-3, default `config_model`).
- `semantic_distance` = `clamp01((1 - cosine(emb(src),emb(dst)))/2)`; missing embedding → entity_type fallback
  (1.0 diff / 0.3 same) + `scorer_version` suffix `+typefallback`.
- `novelty` = fraction of `rel_ids` with `first_seen >= now() - novelty_window_days` (config, default 7).
- `weirdness` = `reliability * (w_U*U + w_S*S + w_N*N)`, weights from config (0.45/0.40/0.15), clamp [0,1].
- Self-loop / non-distinct endpoints → weirdness 0 (filtered before persist). Stamps `scorer_version` (e.g. "weirdness-1.0").
**Config knobs** (`config.py`): `weirdness_w_unexpectedness/_semantic/_novelty`, `novelty_window_days`,
`weirdness_unexpectedness_mode`.
**Tests** (`tests/unit/application/services/test_weirdness_scorer.py` NEW, ≥8): per §11 unit table.
**Acceptance**: [ ] all 5 sub-scores correct [ ] hubs demoted [ ] self-loop zeroed [ ] config-driven [ ] version stamped

#### T-3-04 — Wire scorer into worker; persist new columns; backfill script
**Type**: impl · **depends_on**: T-3-03, T-2-04 · **blocks**: T-5-01
**Target files**: `infrastructure/workers/path_insight_worker.py`,
`infrastructure/intelligence_db/repositories/path_insight_repository.py`,
`domain/entities/path_insight.py` (add 7 fields, all defaulted — mirror hub_penalty precedent),
`application/schemas/paths.py` + `api/schemas/paths.py` (additive public fields),
`scripts/backfill_weirdness.py` (NEW).
**PRD reference**: §6.5 (PathInsight extend), §6.2 (additive response), §12 (break surface)
**What to build**: Worker scores via `WeirdnessScorer`, populates `dst_entity_id` (= last node) + sub-scores +
`weirdness` (mirrored to `composite_score`) + `scorer_version`; repo persists/deserializes new columns; domain
entity gains the 7 fields with defaults; public schema gains additive nullable fields (`reliability`,
`unexpectedness`, `semantic_distance`, `novelty`, `weirdness`). Backfill script recomputes existing rows
(or leaves NULL → repopulated on next discovery). Ranking switches to `weirdness`.
**Read/Write**: write (worker); read schema additive.
**Downstream test impact**: `test_path_insight_repository`, `test_path_insight` (domain), `test_paths_schemas`,
`test_get_entity_paths`, rag-chat `get_entity_paths` mapping (additive → safe), FE `types/intelligence.ts`.
**Tests**: round-trip new columns; backward-compat (old NULL rows deserialize); ranking by weirdness.
**Acceptance**: [ ] columns persisted [ ] old rows still load [ ] response additive (R5) [ ] existing tests green

#### Pre-read
- `services/intelligence-migrations/alembic/versions/0050_*.py` + `0051_*.py` (style + FAIL-LOUD),
  `infrastructure/workers/age_sync_worker.py`, `application/services/path_scorer.py`,
  `domain/entities/path_insight.py`, `infrastructure/intelligence_db/repositories/path_insight_repository.py`.

#### Validation Gate
- [ ] ruff + mypy · [ ] ≥14 new unit tests + migration apply/rollback · [ ] KG suite green
- [ ] migration FAILS LOUD (BP-688) · [ ] additive-only (R5) · [ ] docs: service doc data-model section

#### Architecture Compliance
- [ ] R24 — DDL only in intelligence-migrations; S6 `ALEMBIC_ENABLED=false` · [ ] R32 — migration # = 0052 (verified HEAD 0051)
- [ ] R25 — worker depends on `NodeDegreeRepositoryPort` ABC · [ ] R11 — `utc_now()` for refreshed_at/computed_at
- [ ] R10 — `new_uuid7()` for any new id · [ ] R12 — structlog

#### Break Impact
| Broken File | Why | Fix |
|-------------|-----|-----|
| `domain/.../test_path_insight.py` | entity gains 7 fields | add defaults to constructions |
| `.../test_path_insight_repository.py` | new columns | extend round-trip fixtures |
| `api/schemas/.../test_paths_schemas.py` | response +5 fields | assert additive presence |
| rag-chat `EntityPathsResult` map | new fields | additive — verify ignore-unknown, contract test |
| `apps/worldview-web/types/intelligence.ts` | response shape | add optional fields (W5 uses them) |

#### Regression Guardrails
- **BP-688**: migration must FAIL LOUD (assert pg_class after CREATE; no silent WHEN OTHERS swallow).
- **BP-126**: NOT NULL column needs server_default — all new cols nullable, OK.
- **BP-540/541**: do not write placeholder/None where a real value exists (embedding/first_seen lookups fail-open, logged).
- **BP-405**: every name referenced (NodeDegreeRepository, age_sync_worker, _ag_label_edge) grep-verified before use.

---

## Wave 4 — Pairwise endpoint + get_path_between LLM tool

**Goal**: Expose "is A connected to B, and how?" as a clean endpoint + chat tool, reusing the W2 engine.
**Depends on**: W2 (engine); W3 for scoring (degrade to unscored if run before W3). **Effort**: 4–6 h.
**Architecture layer**: application use case → API (KG + S9) → rag-chat tool.

#### T-4-01 — `FindPathsBetweenUseCase` (NEW)
**Type**: impl · **depends_on**: T-2-02 (T-3-03 for scoring) · **blocks**: T-4-02, T-4-04
**Target files**: `application/use_cases/find_paths_between.py` (NEW)
**PRD reference**: §6.2 (paths/between), §6.7 (pairwise flow)
**What to build**: Validate `source != target`, both exist, `max_hops ∈ [1, path_max_hops]`. Call
`GraphPathEngine.path_exists` (shortest hop) then `find_paths_between(..., prune_membership = not meaningful_only)`;
score each via `WeirdnessScorer`; rank by weirdness then ascending hop_count; return up to `limit`.
`connected=False` + `shortest_hops=None` when no path. Timeout → domain `PathTimeoutError`.
**Port interfaces**: `GraphPathEngine`, `WeirdnessScorer` (pure), `NodeDegreeRepositoryPort`,
`EntityEmbeddingStateRepository`(read), entity-exists check. **Read/Write**: read-path but `LOAD 'age'` needs
write-session (documented R27 exception, as CypherPathUseCase).
**Tests**: connected/disconnected/self-loop-rejected/maxhops-422/ranking-order/meaningful_only-prunes.
**Acceptance**: [ ] correct connectivity [ ] ranked [ ] validation errors [ ] timeout mapped

#### T-4-02 — KG router `GET /api/v1/paths/between` + schemas
**Type**: impl · **depends_on**: T-4-01 · **blocks**: T-4-03
**Target files**: `api/paths.py` (add route) or new `api/paths_between.py`; `api/schemas/paths.py` +
`application/schemas/paths.py` (add `PathBetweenPublic`, `PathsBetweenResponse`); `api/dependencies.py` (DI).
**PRD reference**: §6.2
**What to build**: Route per §6.2 (params source/target/max_hops/limit/meaningful_only; response
connected/shortest_hops/paths[]/computed_at). R25: router → use case only. Errors 400/401/404/422/503.
**Tests**: `tests/unit/api/test_paths_between_router.py` — param validation, 404, response shape.
**Acceptance**: [ ] route wired via use case [ ] errors correct [ ] schema matches PRD

#### T-4-03 — S9 proxy `GET /v1/paths/between` + cache
**Type**: impl · **depends_on**: T-4-02 · **blocks**: T-4-05
**Target files**: `services/api-gateway/src/api_gateway/routes/intelligence.py`,
`services/api-gateway/src/api_gateway/schemas/paths.py`
**PRD reference**: §6.2, §8 (cache key scoped by tenant)
**What to build**: Authenticated proxy → S6; forward params; Valkey 5-min cache key
`pathbetween:{tenant}:{source}:{target}:{max_hops}:{limit}:{meaningful_only}`; rate-limit 60/min.
**Tests**: contract `test_paths_between_contract.py` (shape + forwarding); cache hit/miss.
**Acceptance**: [ ] proxied [ ] cached per-tenant [ ] rate-limited

#### T-4-04 — `get_path_between` LLM tool (rag-chat) + manifest bump (R29)
**Type**: impl · **depends_on**: T-4-01 · **blocks**: T-4-05
**Target files**: `services/rag-chat/.../application/ports/upstream_clients.py` (add `S7Port.get_path_between`),
`infrastructure/clients/s7_intelligence_client.py` (impl, S9-proxied per R14/R7),
`application/pipeline/tool_registry_builder.py` (register tool + bump manifest `version`),
the tool YAML manifest file, `application/pipeline/handlers/narrative.py` (or a new handler module).
**PRD reference**: §3.1 FR-9, §6.1
**What to build**: Tool `get_path_between(source_entity, target_entity, max_hops=3)` → calls S9
`/v1/paths/between`; returns a `PathBetweenResult` dict for Claude. Bump manifest version; keep manifest↔handler
in sync (R29). EntityContext enforcement consistent with existing tools (PLAN-0080 M-1).
**Tests**: handler unit (success/empty/missing-port); `test_tool_manifest_sync` (R29 — manifest matches handlers).
**Acceptance**: [ ] tool callable [ ] manifest version bumped [ ] R29 sync test green

#### T-4-05 — Pairwise contract + integration tests
**Type**: test · **depends_on**: T-4-03, T-4-04 · **blocks**: none
**Target files**: `services/knowledge-graph/tests/contract/test_paths_between_contract.py` (NEW),
`tests/integration/.../test_paths_between_age.py` (NEW, AGE-backed).
**What to build**: S9↔S6 contract; AGE integration measuring p95 < 1 s for representative pairs (NFR-1).
**Acceptance**: [ ] contract green [ ] latency within budget recorded

#### Pre-read
- `application/use_cases/cypher_path.py`, `application/use_cases/get_entity_paths.py`, `api/paths.py`,
  `api-gateway/routes/intelligence.py`, rag-chat `tool_registry_builder.py` + `s7_intelligence_client.py`.

#### Validation Gate
- [ ] ruff + mypy (S6, S9, S8) · [ ] ≥10 new tests · [ ] contract + R29 green · [ ] latency recorded
- [ ] docs: api-gateway.md + rag-chat.md tool list updated

#### Architecture Compliance
- [ ] R25 — routers use only use cases · [ ] R27 — read endpoint, AGE write-session exception documented
- [ ] R14/R7 — rag-chat → S9 only, never S6 directly · [ ] R29 — manifest sync test

#### Break Impact
| Broken File | Why | Fix |
|-------------|-----|-----|
| rag-chat manifest sync test | new tool | bump manifest + handler together |
| `api-gateway` route tests | new route | add coverage |

#### Regression Guardrails
- **BP-687**: pairwise existence uses staged probing (via engine), not `ORDER BY length(p)`.
- **BP-SA5-003**: detail via agtype-text parse.
- **BP-235**: any httpx client in S9→S6 / rag-chat→S9 sets explicit timeout (asyncio.wait_for + httpx.Timeout).
- **BP-405**: verify `S7Port`, `s7_intelligence_client`, manifest YAML path before referencing.

---

## Wave 5 — Global weird-connections feed + frontend

**Goal**: A graph-wide "Weird Connections" feed (read from precomputed `path_insights`) + the frontend
surfaces (global feed + pairwise "how related?" + PathsTab re-label). **Depends on**: W3 (weirdness column).
**Effort**: 5–7 h. **Architecture layer**: application (read use case) → API → frontend.

#### T-5-01 — `GlobalWeirdConnectionsUseCase` (NEW, read-only)
**Type**: impl · **depends_on**: T-3-04 · **blocks**: T-5-02
**Target files**: `application/use_cases/global_weird_connections.py` (NEW)
**PRD reference**: §6.2 (connections/weird), §3.1 FR-7
**What to build**: Query `path_insights` ordered by `weirdness DESC` with filters (limit/offset/min_weirdness/
since_days/entity_type). `since_days` → join novelty / `relations.first_evidence_at`; `entity_type` → filter on
endpoint type. Dedup to distinct endpoint-pairs (best path each, OQ-6 default).
**Port interfaces**: `PathInsightRepositoryPort` (extend with `list_global_weird(...)`). **Read/Write**: read-only
→ KG's `ReadOnlyDbSessionDep` (`Depends(get_readonly_session)` in `api/dependencies.py`) — the same read-session
construct `get_entity_paths` already uses. ⚠ KG does NOT have a generic `ReadOnlyUnitOfWork`/`ReadUoWDep`; use
`ReadOnlyDbSessionDep`. No AGE `LOAD 'age'` needed (pure `path_insights` SELECT) → genuine read replica (R27).
**Tests**: ordering, filters, endpoint-pair dedup, pagination.
**Acceptance**: [ ] ranked global [ ] filters work [ ] uses `ReadOnlyDbSessionDep` [ ] dedup

#### T-5-02 — KG `GET /api/v1/connections/weird` + S9 proxy
**Type**: impl · **depends_on**: T-5-01 · **blocks**: T-5-03
**Target files**: KG `api/connections.py` (NEW) + schemas (`WeirdConnectionPublic`, `WeirdConnectionsResponse`),
`api/dependencies.py`; S9 `routes/intelligence.py` + `schemas/paths.py`.
**PRD reference**: §6.2
**What to build**: KG route (read use case, R25) + S9 authenticated proxy with 5-min Valkey cache. Response per §6.2.
**Tests**: KG router unit + S9 contract `test_weird_connections_contract.py`.
**Acceptance**: [ ] route + proxy [ ] cached [ ] p95 < 300 ms (NFR-1)

#### T-5-03 — Frontend: feed + pairwise + PathsTab re-label
**Type**: impl · **depends_on**: T-5-02, T-4-03 · **blocks**: none
**Target files**: `apps/worldview-web/lib/api/intelligence.ts` (add `useWeirdConnections`, `usePathBetween`),
`types/intelligence.ts` (add `WeirdConnectionPublic`, `PathBetweenPublic`, additive `PathInsightPublic` fields),
`components/intelligence/WeirdConnectionsFeed.tsx` (NEW), pairwise "How are these related?" UI (NEW),
`components/intelligence/tabs/PathsTab.tsx` + `components/instrument/intelligence/context/PathInsightsBlock.tsx`
(show weirdness + sub-score breakdown).
**PRD reference**: §6.6
**What to build**: TanStack Query hooks (5-min staleTime, query-key factories), feed component rendering ranked
connections with the reliability/unexpectedness/semantic/novelty breakdown; pairwise picker → ranked paths;
re-label PathsTab/PathInsightsBlock from harmonic/diversity/surprise → weirdness. **Heavy inline comments**
(user new to Next.js). **pnpm** only; **Vitest**.
**Tests** (Vitest): `useWeirdConnections.test`, `usePathBetween.test`, `WeirdConnectionsFeed.test`,
update `PathInsightsBlock.test` (weirdness + null-sub-score back-compat).
**Acceptance**: [ ] feed renders [ ] pairwise works [ ] PathsTab re-labelled [ ] heavy comments [ ] vitest green

#### Pre-read
- `apps/worldview-web/lib/api/intelligence.ts`, `types/intelligence.ts`,
  `components/intelligence/tabs/PathsTab.tsx`, `components/instrument/intelligence/context/PathInsightsBlock.tsx`,
  `api-gateway/routes/intelligence.py`.

#### Validation Gate
- [ ] ruff + mypy (S6/S9) · [ ] pnpm typecheck + vitest green · [ ] contract green
- [ ] docs: worldview-web.md + api-gateway.md route lists

#### Architecture Compliance
- [ ] R25 — read use case · [ ] R27 — `ReadOnlyDbSessionDep` (KG's read-session; no ReadUoWDep in KG) · [ ] R14 — FE → S9 only
- [ ] Frontend: pnpm exact versions, lockfile committed (feedback_frontend_pnpm)

#### Break Impact
| Broken File | Why | Fix |
|-------------|-----|-----|
| `types/intelligence.ts` | shape additions | additive optional fields |
| `PathInsightsBlock.test.tsx` / `intelligence-hooks.test.ts` | re-label + new hooks | update assertions |

#### Regression Guardrails
- **BP-676 / hsl(var()) no-paint class** (frontend sprint memory): verify new components actually paint (no zero-value CSS var).
- **BP-235**: hooks honor abort/timeout.
- **R27**: global feed MUST use read replica (high-traffic read).

---

## Wave 6 — Quality gate + metric finalisation + docs

**Goal**: Prove the redesign works (human-judged), finalise weights, update all docs.
**Depends on**: W3, W4, W5. **Effort**: 3–4 h. **Architecture layer**: validation + docs.

#### T-6-01 — Human-sample quality gate
**Type**: test · **depends_on**: T-5-02 · **blocks**: T-6-02
**Target files**: `scripts/eval/weird_path_quality_sample.py` (NEW), report under `docs/audits/`.
**PRD reference**: §5, §11 (validation), success metric "<3/20 noise".
**What to build**: Pull top-20 global weird connections + top-10 per-anchor for 5 anchors; render for human
judgement (is it hub/self-loop noise?). Gate: <3/20 noise. Record before/after vs the old surprise_score.
**Acceptance**: [ ] sample rendered [ ] noise < 3/20 [ ] before/after recorded

#### T-6-02 — Metric ablation + weight finalisation (OQ-1, OQ-2)
**Type**: test/docs · **depends_on**: T-6-01 · **blocks**: T-6-03
**Target files**: `scripts/eval/weirdness_ablation.py` (NEW), PRD §14 OQ updates.
**What to build**: Compare config-model vs Adamic-Adar (OQ-2) and weight variants (OQ-1) on the labelled sample;
commit final `weirdness_*` config defaults + `scorer_version`. Resolve OQ-1/OQ-2/OQ-4 in the PRD.
**Acceptance**: [ ] ablation recorded [ ] weights committed [ ] OQs resolved

#### T-6-03 — Docs + compounding
**Type**: docs · **depends_on**: T-6-02 · **blocks**: none
**Target files**: `docs/services/knowledge-graph.md`, `docs/services/api-gateway.md`, `docs/services/rag-chat.md`,
`services/knowledge-graph/.claude-context.md`, `services/api-gateway/.claude-context.md`,
`apps/worldview-web` docs, `docs/plans/TRACKING.md` (mark waves done), PRD status → implemented.
**What to build**: Document the 2 new endpoints, the `get_path_between` tool, the weirdness metric + config knobs,
the engine/BP-689 fix, migration 0052. Confirm BP-689/690 already in BUG_PATTERNS.md.
**Acceptance**: [ ] all service docs updated [ ] TRACKING current [ ] context files updated

#### Pre-read
- `docs/services/knowledge-graph.md`, `.claude-context.md` files, PRD §14.

#### Validation Gate
- [ ] quality gate < 3/20 noise · [ ] weights committed · [ ] all docs updated · [ ] TRACKING done-state

#### Architecture Compliance
- [ ] no code-path changes (validation/docs) · [ ] reproducibility: scorer_version recorded (NFR-6)

#### Break Impact
| Broken File | Why | Fix |
|-------------|-----|-----|
| PRD §14 OQ table | OQs resolved | strike-through resolved OQs |

#### Regression Guardrails
- **feedback_audit_returned_value_persistence**: the ablation/quality outputs must be persisted (reports committed), not metrics-only.
- **feedback_tracking_and_docs_mandatory**: TRACKING + docs updated in the wave commit.

---

## Cross-Cutting Concerns

- **Contracts**: 2 new S9↔S6 contracts (`paths/between`, `connections/weird`) + R29 tool-manifest sync. Existing
  `get_entity_paths` response is additive-only (backward-compatible).
- **Migrations**: one — `0052` (intelligence-migrations, after HEAD `0051`). R24/R32 respected.
- **Events**: none (no Kafka). Degree refresh piggybacks AGE-sync worker.
- **Config (new knobs)**: `path_max_hops`, `weirdness_w_unexpectedness/_semantic/_novelty`, `novelty_window_days`,
  `weirdness_unexpectedness_mode`, raised `PATH_INSIGHT_HUB_MIN_RELATIONS` default. Document in env example.
- **Docs**: knowledge-graph.md, api-gateway.md, rag-chat.md, worldview-web docs, 2 `.claude-context.md`.

## Risk Assessment

- **Critical path**: W1 → W2 → W3. W2 is highest-risk (AGE engine consolidation + the AD-1 reinterpretation);
  the maxhops spike (T-2-05) de-risks the cap decision with data before W3 depends on it.
- **Highest integration risk**: W4 (3 services: S6 use case, S9 proxy, S8 tool) — mitigated by contract + R29 tests.
- **Rollback**: W1 is pure logic/config (revert commit). Migration 0052 is additive + has a clean downgrade.
  W2 keeps `PathDiscovery` as a deprecated shim until tests pass so the worker can fall back.
- **Testing gaps**: AGE-backed latency tests need the live extension (integration profile) — gated like existing
  AGE tests; unit layer mocks the engine.
- **Open dependency on PRD revision**: the AD-1 consolidation (cypher_path reuse) should be ratified by the
  pending `/revise-prd` pass before W2 starts; tasks are written for it but PRD §AD-1/FR-2/FR-8 wording lags.
