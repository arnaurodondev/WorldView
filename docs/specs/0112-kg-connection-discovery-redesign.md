# PRD-0112 — Knowledge Graph Connection Discovery: Weird-Path Redesign + Pairwise Pathfinding

**Status**: Implemented (2026-06-13)
**Author**: Arnau Rodon (with Claude)
**Created**: 2026-06-12
**Branch**: `feat/frontend-enhancement-sprint`

> **Shipped (2026-06-13) — PLAN-0112 6/6 waves complete.** All FRs delivered: flood stopped
> (seeder skips terminally-failed anchors + maxhops cap), VLE engine consolidated, weirdness
> metric (migration 0052 + `node_degree`) live and discriminating (live p10-p90 ≈ 0.23-0.78
> vs the saturated old `surprise_score` p50 ≈ 0.95), pairwise `GET /paths/between` + global
> `GET /connections/weird` endpoints + the `get_path_between` LLM tool + the `/connections`
> frontend. W6 quality gate **PASSED** (0/20 auto-flagged noise vs the <3/20 target; audit
> `docs/audits/2026-06-13-weird-path-quality-sample.md`). OQ-1/OQ-2/OQ-3/OQ-4 resolved (§14).
>
> **Four build corrections vs the original design** (each documented inline below):
> 1. **AGE 1.5 has no multi-label VLE** (`-[:A|B*L..L]-` is a hard parse error at `|`) → the
>    engine uses **untyped VLE `-[*L..L]-` + a post-hoc Python membership filter** instead of
>    a typed allow-list on the pattern (FR-2/FR-3, AD-1). BP-689.
> 2. **GUCs must be session-scoped `SET`, not `SET LOCAL`** — `SET LOCAL` evaporated before
>    the traversal transaction (the live flood bug); `SET` on the same session as the query
>    is the fix (§6.5).
> 3. **maxhops capped at 3** — the post-hoc filter prunes *results* not the traversal
>    *frontier*, so hop-4/5 blow up even on the pruned graph (OQ-3, AD-5; W2 spike measured).
> 4. **Novelty `first_seen` via `COALESCE(relations.first_evidence_at, MIN(relation_evidence.evidence_date))`**
>    to bridge the AGE↔relations sync gap (FR-13). `dst_entity_id` FK is NULL-guarded for old
>    rows; pairwise `connected`/`shortest_hops` are derived from the same distinct-node-filtered
>    path set the endpoint returns (§6.2 contract self-consistency).
**Supersedes (in part)**: PLAN-0074 path-insight scoring; PLAN-0023 hub/degree-scoring slice
**Grounding investigations**:
- `docs/audits/2026-06-12-weird-path-redesign-feasibility.md` (primary)
- `docs/audits/2026-06-12-postgres-log-investigation.md` (the symptom that triggered this)

---

## 1. Problem Statement

The knowledge graph's "path insight" feature is meant to surface **surprising, non-obvious
connections** between entities (e.g. "this obscure supplier links two rival mega-caps"). It is the
intellectual centrepiece of the intelligence layer and a thesis contribution. Today it fails on
three counts:

1. **It produces low-value output.** A live audit of the 35,298 stored insights found the top-ranked
   "surprising" paths are sector-hub chains ("both are in the Health Care sector") and degenerate
   self-loops caused by duplicate canonical entities (Cameco→Cameco, Meta→WhatsApp→Meta). The
   `surprise_score` is saturated (median 0.951) and does not discriminate. The metric rewards exactly
   the wrong thing because surprise is measured **relative to the local sibling-path set**, with no
   global baseline and no view of *which entities* a path connects.

2. **It saturates Postgres.** 298 anchor jobs fail permanently (`PathDiscovery timed out after
   60.0s`) and are **re-queued nightly forever** by a seeder whose "skip if fresh" guard never trips
   for jobs that never complete. This floods the DB with statement-timeout cancellations and AGE lock
   warnings (the originating symptom).

3. **The query primitive is pathologically slow — a genuine bug.** Measured live: the current
   explicit untyped-edge Cypher (`MATCH (n0)-[r1]-(n1)`) forces Apache AGE to **sequential-scan all
   ~30 edge-label tables** — **18.4 s for a single 1-hop fetch**. AGE's variable-length operator
   (`-[*1..N]-`) does the identical traversal in **0.24 s (76× faster)** via the vertex GIN index.
   The feature was built on the wrong primitive.

Separately, there is **no way to ask the most natural question** — *"is entity A connected to entity
B, and how?"* The feature only answers "what radiates from X?", which binds one endpoint and forces
the expensive fan-out. A pairwise query binds both endpoints and is dramatically cheaper
(60–800 ms measured, all pair types).

### Why now
The Postgres flood is active and ongoing. The feature is thesis-critical and currently
demo-embarrassing. The investigation proved all the pieces for a principled redesign already exist in
the data (no new infrastructure required).

---

## 2. Target Users & Journeys

| User | Journey | Today | After |
|------|---------|-------|-------|
| **Analyst (frontend)** | Explores an entity's intelligence page | Sees a "Paths" tab of mostly-noise sector chains | Sees genuinely surprising, reliable connections + can ask "how is X related to Y?" |
| **Analyst (frontend)** | Wants serendipitous discovery across the whole graph | No such surface | A **"Weird Connections" global feed** — top surprising connections in the graph right now |
| **Chat user (S8/rag-chat)** | Asks "how are Nvidia and SpaceX connected?" | Agent has only `get_entity_paths` (one-ended, precomputed) | Agent calls new `get_path_between` tool → bounded pairwise search |
| **Thesis** | Defends a principled "surprise" metric | Local-frequency heuristic, saturated, indefensible | Link-prediction × semantic-distance × novelty, reliability-gated — a defensible contribution |

---

## 3. Requirements

### 3.1 Functional — Must-have (v1)

- **FR-1 (Remediation)**: Stop the Postgres flood. Seeder must not re-queue terminally-failed anchors;
  the discovery query must not time out under normal operation; maxhops hard-capped until validated.
- **FR-2 (Engine)**: Replace the explicit untyped-edge query (BP-689) with the AGE VLE primitive,
  **consolidating the proven staged `*L..L` VLE probe + `nodes(p)/relationships(p)` agtype-text parse
  already in `cypher_path.py`** (BP-687) — both existence/length AND full path detail come from VLE;
  no separate "typed fixed-k" query is needed (see AD-1). Document BP-689. All traversal goes through
  one shared `GraphPathEngine` port.
  - **Correction (W2 build):** AGE 1.5 does NOT support multi-label VLE (`-[:A|B*L..L]-` is a hard
    parse error at `|`). The engine therefore uses **untyped VLE `-[*L..L]-`** + a **post-hoc Python
    membership filter** (reject any path whose `rel_types` intersect `MEMBERSHIP_RELATIONS`). This
    prunes membership noise from *results* but not the traversal *frontier* — which is why the maxhops
    cap matters (see FR-10/AD-5).
- **FR-3 (Membership pruning)**: Discovery must exclude paths routed through the four low-information
  membership relations (`IS_IN_SECTOR`, `LISTED_ON`, `OPERATES_IN_COUNTRY`, `HEADQUARTERED_IN` — 47%
  of edges) via the post-hoc filter above, so surfaced paths route through meaningful corporate links,
  not sector/exchange hubs.
- **FR-4 (New weirdness metric)**: Replace the saturated `surprise_score` with a per-path,
  globally-normalised composite scored **independently of sibling paths**:
  `weirdness = reliability_gate × (w_U·unexpectedness + w_S·semantic_distance + w_N·novelty)`.
  - **Unexpectedness (B)**: configuration-model / Adamic-Adar link surprise from node degrees.
  - **Semantic distance (C)**: cosine distance of endpoint `definition` embeddings (1024-dim).
  - **Novelty (E)**: fraction of path edges whose `first_evidence_at` is within `novelty_window_days`.
  - **Reliability gate**: harmonic mean of edge confidences (multiplicative — noise can't rank high).
- **FR-5 (Degree materialisation)**: A `node_degree` table (or materialised view) refreshed by the
  AGE-sync worker, powering unexpectedness without per-query recomputation.
- **FR-6 (Per-anchor discovery, redesigned)**: Keep `GET .../entities/{id}/paths` but ranked by the
  new `weirdness` score; exclude self-loops (src == any later node) and require distinct endpoints.
- **FR-7 (Global weird-connections feed)**: New endpoint returning the top weird connections across
  the whole graph (not anchored), with filters (limit, min_weirdness, since_days, entity_type).
- **FR-8 (Pairwise pathfinding)**: New on-demand endpoint `paths/between?source&target&max_hops` →
  `{connected, shortest_hops, paths:[ranked]}` using the consolidated VLE engine (staged existence +
  agtype-parsed detail, AD-1), scored with the same scorer. Includes membership edges by default
  (user asked "any connection"), with a `meaningful_only` flag to prune them.
- **FR-9 (LLM tool)**: Expose pairwise search as `get_path_between` in the rag-chat tool manifest
  (manifest version bump, R29 sync test).
- **FR-10 (maxhops validation)**: A measured spike re-runs latency on the **pruned** graph at maxhops
  3/4/5; the committed cap is the largest hop count whose p95 stays within budget (§3.3).

### 3.2 Functional — Nice-to-have (deferred to v2)

- **FR-11**: Duplicate-canonical dedup (NVIDIA ×3, Meta/MSFT ×2) — tracked separately (data quality).
- **FR-12**: Hub mis-typing fix (NYSE=instrument, U.S.=currency) — separate data-quality ticket.
- **FR-13**: AGE-graph ↔ `relations`-table edge sync-gap investigation — separate.
- **FR-14**: LLM explanations for global-feed paths (reuse existing batch worker).

### 3.3 Non-Functional

- **NFR-1 (Latency)**: Pairwise endpoint **p95 < 1 s** (warm), discovery per-anchor batch job
  **< 5 s/anchor**. Global feed read **p95 < 300 ms** (served from precomputed table + cache).
- **NFR-2 (Postgres safety)**: No query may exceed `statement_timeout`; `max_parallel_workers_per_gather`
  set to 0 in AGE traversal sessions to eliminate parallel-worker FATAL noise.
- **NFR-3 (No flood)**: Zero terminally-failed jobs re-queued; failed-job rate observable via metric.
- **NFR-4 (Backward compat)**: Existing `GET .../entities/{id}/paths` response stays
  forward-compatible (additive fields only); frontend + `get_entity_paths` LLM tool keep working
  through the transition (R5/R11).
- **NFR-5 (Tenant isolation)**: All read endpoints filter by `tenant_id` (path_insights carries a
  nullable tenant overlay; global feed is tenant-agnostic shared-graph data — confirm in §8).
- **NFR-6 (Reproducibility/thesis)**: Metric weights + windows are config-driven and recorded with
  each computed row (`scorer_version`) so thesis results are reproducible.

### 3.4 Open-question severity
All BLOCKING questions resolved during the investigation (signals computable, AGE behaviour
measured, pairwise feasible). Remaining items are DEFERRED with documented defaults — see §14.

---

## 4. Out of Scope

- Duplicate-canonical dedup and hub re-typing (FR-11/12 — separate data-quality work; this PRD only
  *mitigates* their effect via self-loop exclusion + degree-based hub demotion).
- The AGE↔relations edge sync gap (FR-13).
- Community detection / centrality beyond degree (PLAN-0023 remainder).
- Changing the embedding model or adding new embedding views.
- Real-time (streaming) recomputation — discovery stays a scheduled batch + on-demand pairwise.

---

## 5. Success Metrics

| Metric | Baseline (2026-06-12) | Target |
|--------|----------------------|--------|
| Terminally-failed path jobs re-queued nightly | 298 | 0 |
| Postgres statement-timeout cancellations/min (path queries) | ~8 | 0 |
| 1-hop neighbour fetch latency | 18.4 s | < 0.5 s |
| Pairwise query p95 (warm) | n/a (no endpoint) | < 1 s |
| `surprise`/`weirdness` score spread (p90 − p10) | ~0.25, saturated near 1 | discriminating (target spread > 0.5) |
| Top-20 insights that are sector-hub/self-loop noise | ~17/20 | < 3/20 (human-judged) |
| Committed maxhops on pruned graph | 3 (capped) | 4–5 if p95 within budget |

---

## 6. Technical Design

### 6.1 Affected Services

| Service | Change | Why |
|---------|--------|-----|
| **S6 knowledge-graph** | New `GraphPathEngine` port + AGE-VLE adapter (replaces `path_discovery.py` internals); new `PathScorer` (B/C/E); `node_degree` materialisation; seeder fix; new use cases (pairwise, global feed); 2 new routers | Core of the redesign |
| **intelligence-migrations** | Migration 0052: new score columns on `path_insights`, `node_degree` table, indexes | R24 — only this service owns intelligence_db DDL |
| **S9 api-gateway** | 2 new proxied routes (`/v1/paths/between`, `/v1/connections/weird`); extend paths schema (additive) | R14 — frontend talks only to S9 |
| **rag-chat (S8)** | New `get_path_between` tool in manifest (version bump); `S7IntelligencePort.get_path_between`; handler | FR-9 |
| **apps/worldview-web** | New "Weird Connections" feed component + page; pairwise "how related?" UI; PathsTab re-label to weirdness scores | FR-6/7 |

### 6.2 API Changes

#### GET /api/v1/paths/between  (KG)  ·  GET /v1/paths/between  (S9)
- **Purpose**: On-demand pairwise connection — "is A connected to B, and how?"
- **Auth**: required (S9). Internal JWT S9→S6.
- **Query params**:
  | Field | Type | Required | Default | Validation | Description |
  |-------|------|----------|---------|------------|-------------|
  | `source` | UUID | yes | — | UUIDv7, entity must exist | Source entity |
  | `target` | UUID | yes | — | UUIDv7, entity must exist, ≠ source | Target entity |
  | `max_hops` | int | no | 3 | [1, committed-cap] | Max path length |
  | `limit` | int | no | 5 | [1, 20] | Max ranked paths returned |
  | `meaningful_only` | bool | no | false | — | If true, prune membership edges from traversal |
- **Response (200)**:
  | Field | Type | Description |
  |-------|------|-------------|
  | `source_entity_id` / `target_entity_id` | UUID | Echoed |
  | `connected` | bool | A **reportable** path exists within max_hops (see note below) |
  | `shortest_hops` | int \| null | Length of the shortest **returned** path; null if not connected |
  | `paths` | list[PathBetweenPublic] | Up to `limit`, ranked by weirdness then ascending hop_count |
  | `computed_at` | datetime | UTC |
  - **PathBetweenPublic**: `path_nodes` (list[PathNodePublic]), `path_edges` (list[PathEdgePublic]),
    `hop_count` (int), `reliability` / `unexpectedness` / `semantic_distance` / `novelty` /
    `weirdness` (float [0,1]).
  - **Contract self-consistency (live-QA fix 2026-06-13)**: `connected` and `shortest_hops` are
    derived from the SAME enumerated + node-distinct-filtered path set that `paths` returns — NOT
    from a separate, looser existence probe. The fast existence probe is used only to short-circuit
    the truly-disconnected case. When the only connecting path routes through a **duplicate canonical
    vertex** (the deferred FR-11 entity-dedup — e.g. SpaceX has a duplicate), the distinct-node guard
    drops it, so there are zero reportable paths: the response is `connected:false, shortest_hops:null,
    paths:[]` rather than the contradictory `connected:true, shortest_hops:N, paths:[]`. Such a pair is
    reported as not-connected **until FR-11 dedup lands**. `shortest_hops = min(hop_count)` over the
    returned paths.
- **Errors**: 400 (source==target / bad UUID), 401, 404 (entity not found), 422 (max_hops out of range),
  504-mapped-to-200-with-`connected:false` is NOT used — a timeout returns 503 with retry hint.
- **Rate limit**: 60 req/min authenticated. **Cache**: S9 Valkey 5 min, key
  `pathbetween:{tenant}:{source}:{target}:{max_hops}:{limit}:{meaningful_only}`.

#### GET /api/v1/connections/weird  (KG)  ·  GET /v1/connections/weird  (S9)
- **Purpose**: Global feed of the most surprising connections in the graph (FR-7).
- **Auth**: required.
- **Query params**:
  | Field | Type | Required | Default | Validation | Description |
  |-------|------|----------|---------|------------|-------------|
  | `limit` | int | no | 20 | [1, 100] | Page size |
  | `offset` | int | no | 0 | ≥ 0 | Pagination |
  | `min_weirdness` | float | no | 0.0 | [0,1] | Threshold |
  | `since_days` | int \| null | no | null | [1, 365] | Only paths with a recent edge |
  | `entity_type` | str \| null | no | null | enum | Filter to paths whose endpoint matches a type |
- **Response (200)**: `{ connections: list[WeirdConnectionPublic], total: int, freshness_ts: datetime|null }`
  - **WeirdConnectionPublic** = PathBetweenPublic + `src_entity_id`, `dst_entity_id`, `computed_at`.
- **Errors**: 401, 422. **Cache**: S9 Valkey 5 min (served from precomputed `path_insights`).

#### GET /api/v1/entities/{entity_id}/paths  (existing — extended, additive only)
- New response fields on `PathInsightPublic`: `reliability`, `unexpectedness`, `semantic_distance`,
  `novelty`, `weirdness` (all float|null during transition). `composite_score` retained =
  `weirdness` once migrated. `surprise_score`/`diversity_score` retained but **deprecated** (nullable,
  no longer drive ranking). `min_hops`/`max_hops` query params: `max_hops` upper bound raised from 5
  to the committed cap. Ranking changes from `composite_score` to `weirdness` (same column).
- **Backward compat**: every new field is additive with a default → existing frontend + the
  `get_entity_paths` LLM tool deserialize unchanged (R5).

### 6.3 Event Changes

**No new Kafka events.** All flows are synchronous reads (HTTP) plus an internal work-queue
(`path_insight_jobs`, DB-polled, not Kafka). The AGE-sync worker that refreshes `node_degree` is
triggered in-process, not via Kafka. → **R5/R8 not engaged for events.**

> Decision: degree materialisation piggybacks on the existing AGE-sync worker rather than a new Kafka
> topic, because it is derived-from-graph state with no cross-service consumer (R9: no cross-service
> DB; the table lives in intelligence_db, read only by S6).

### 6.4 Database Changes (intelligence_db — migration 0052, owned by intelligence-migrations, R24)

Current migration head: **0051** (0051_unique_ticker_financial_instrument). New head: **0052**. All changes additive + forward-compatible (R5).

#### Table: `node_degree` (NEW)
Precomputed undirected degree per graph vertex, powering unexpectedness (B) without per-query recompute.
| Column | Type | Nullable | Default | Constraints | Notes |
|--------|------|----------|---------|-------------|-------|
| `entity_id` | UUID | no | — | PK, FK → canonical_entities (CASCADE) | Vertex |
| `degree` | INT | no | 0 | CHECK (degree ≥ 0) | Undirected degree (start OR end) |
| `degree_meaningful` | INT | no | 0 | CHECK ≥ 0 | Degree excluding membership edges (for pruned traversal) |
| `refreshed_at` | TIMESTAMPTZ | no | now() | — | Last refresh (UTC) |
- **Indexes**: PK(entity_id). No secondary index needed (point lookups + full scan for max).
- **Estimated rows**: ~3,800 (connected vertices). Refreshed by AGE-sync worker each cycle (~18 ms agg).
- **Also stored**: a single-row `graph_stats(total_edges, total_meaningful_edges, max_degree, refreshed_at)`
  table (or a row in a `kv` table) for the configuration-model normaliser (2m term) and score normalisation.

#### Table: `path_insights` (EXTEND)
Add per-path metric columns. Keep existing columns; repurpose `composite_score` = weirdness.
| New Column | Type | Nullable | Default | Notes |
|-----------|------|----------|---------|-------|
| `dst_entity_id` | UUID | yes | NULL | Path endpoint (the far end); enables global feed + endpoint filtering. Backfilled = last node. FK → canonical_entities (CASCADE), nullable for old rows. |
| `reliability` | FLOAT | yes | NULL | Harmonic mean of edge confidences |
| `unexpectedness` | FLOAT | yes | NULL | Link-prediction surprise [0,1] |
| `semantic_distance` | FLOAT | yes | NULL | Endpoint cosine distance, normalised [0,1] |
| `novelty` | FLOAT | yes | NULL | Recent-edge fraction [0,1] |
| `weirdness` | FLOAT | yes | NULL | Composite [0,1]; mirrors `composite_score` post-migration |
| `scorer_version` | TEXT | yes | NULL | e.g. "weirdness-1.0" — reproducibility (NFR-6) |
- **Deprecated (kept, nullable, no longer ranked on)**: `surprise_score`, `diversity_score`, `template_match`.
- **New indexes**:
  - `idx_path_insights_global_weird`: (weirdness DESC) WHERE weirdness IS NOT NULL — global feed.
  - `idx_path_insights_dst`: (dst_entity_id, weirdness DESC) — endpoint filtering.
  - Existing `idx_path_insights_anchor_score` (anchor_entity_id, composite_score DESC) retained.
- **Backfill**: migration leaves new columns NULL; the discovery worker repopulates on next run
  (replace_for_anchor already does atomic delete+insert). A one-off `scripts/backfill_weirdness.py`
  may recompute for existing rows. `dst_entity_id` backfilled from `path_nodes[-1].entity_id`.
- **CHECK**: hop_count BETWEEN 2 AND `committed_cap` — migration widens the existing
  `hop_count BETWEEN 2 AND 5` only if the validated cap exceeds 5 (it won't initially → no change).

#### `path_insight_jobs` (NO schema change)
Seeder logic change only (FR-1). The partial unique index `uq_path_insight_jobs_active (entity_id)
WHERE status IN ('pending','running')` and claim index are unchanged.

### 6.5 Domain Model Changes (S6 knowledge-graph)

#### Entity: `PathInsight` (EXTEND — frozen dataclass)
Add fields (all defaulted for backward-compat with old DB rows, mirroring the `hub_penalty` precedent):
| New Attribute | Type | Default | Validation | Description |
|---------------|------|---------|------------|-------------|
| `dst_entity_id` | UUID \| None | None | — | Far endpoint of the path |
| `reliability` | float | 0.0 | [0,1] | Harmonic mean of edge confidences |
| `unexpectedness` | float | 0.0 | [0,1] | Link-prediction surprise |
| `semantic_distance` | float | 0.0 | [0,1] | Endpoint embedding cosine distance |
| `novelty` | float | 0.0 | [0,1] | Recent-edge fraction |
| `weirdness` | float | 0.0 | [0,1] | Composite (== composite_score) |
| `scorer_version` | str \| None | None | — | Metric version stamp |
- **Invariants retained**: 2 ≤ hop_count ≤ committed_cap; 0 ≤ weirdness ≤ 1; edge confidence ∈ [0,1].
- **New invariant**: `path_nodes` must have distinct entity_ids (no self-loop) — enforced in scorer,
  not the frozen entity (entity stays a dumb record).
- **Deprecated**: `hub_penalty` (kept = 0.0; superseded by unexpectedness which demotes hubs natively),
  `surprise_score`, `diversity_score`, `template_match` (retained, not populated meaningfully).

#### Value Object: `RawPath` (EXTEND — `infrastructure/age`)
Already carries `node_ids/node_names/node_types/rel_types/edge_confs`. Add `rel_ids: tuple[UUID,...]`
(the `relation_id` per edge) so the scorer can join to `relations.first_evidence_at` (novelty) and to
`node_degree` (unexpectedness) without re-querying the graph.

#### New Port: `GraphPathEngine` (`application/ports/graph_path_engine.py`)
The single traversal abstraction (FR-2). Methods:
- `async find_paths_from_anchor(entity_id, *, max_hops, prune_membership, limit) -> list[RawPath]`
  — per-anchor discovery (untyped VLE staged probe, target end free, agtype-parsed detail).
- `async path_exists(source, target, *, max_hops) -> int | None` — shortest hop-count or None (VLE).
- `async find_paths_between(source, target, *, max_hops, prune_membership, limit) -> list[RawPath]`
  — pairwise (untyped VLE staged probe, both ends bound, agtype-parsed detail).
Adapter: `AgeGraphPathEngine` (replaces `PathDiscovery`). **Mandate**: untyped VLE `-[*L..L]-` for
existence/length AND agtype-text-parsed detail (never the slow explicit-hop `-[r]-` form, BP-689).
Membership pruning = **post-hoc Python filter** dropping any path whose `rel_types` ∩
`MEMBERSHIP_RELATIONS` (AGE 1.5 has no multi-label VLE). GUCs applied as **session-scoped `SET`** (not
`SET LOCAL` — that evaporates before the traversal's transaction): `SET statement_timeout` +
`SET max_parallel_workers_per_gather = 0` on the same session as the query. `find_paths_from_anchor`
probes from depth **2** (discovery wants multi-hop insights; `PathInsight` requires hop_count ≥ 2);
`find_paths_between` / `path_exists` probe from depth 1 (a direct connection is a valid answer).

> **Reuse existing prior art (BP-687/688).** The pairwise existence check reuses the **staged
> shortest-first probing** already in `application/use_cases/cypher_path.py` (`CypherPathUseCase` /
> `traverse_graph`, BP-687): probe `*L..L` for L=1,2,3 and stop at the first non-empty depth — never
> `ORDER BY length(p)` before `LIMIT` (forces full frontier enumeration). The GIN index on
> `entity.properties` (migration 0050, BP-688) and the corrected 25 s `statement_timeout` are already
> in place; the engine consolidates this scattered logic behind one port. The **new** fix this PRD
> adds is the detail-fetch path (`_build_2hop/_build_3hop` untyped explicit edges, BP-689) and
> membership-pruned discovery.

#### New Service: `WeirdnessScorer` (`application/services/weirdness_scorer.py`)
Pure application service (no infra imports — like the current `PathScorer`). Input: a `RawPath` +
injected lookups (`degree_of(entity_id)->int`, `meaningful_degree_of`, `graph_stats`,
`embedding_of(entity_id)->vector|None`, `first_seen_of(rel_id)->datetime|None`). Output: the 5 sub-scores
+ `weirdness`. Self-loop / non-distinct-endpoint paths return `weirdness = 0` (filtered before persist).
- **reliability** = harmonic_mean(edge_confs).
- **unexpectedness** = mean over edges of `surprise_edge(u,v)`, where
  `surprise_edge = clamp01( -log( min(1, deg(u)·deg(v) / (2·m)) ) / NORM )`, `m`=total edges,
  `NORM`=`-log(1/(2m))` (max possible) → high-degree endpoints ⇒ low surprise (hub demotion, replaces
  hub_penalty). Adamic-Adar variant evaluated in the metric-validation wave; config flag selects.
- **semantic_distance** = `clamp01( (1 − cosine(emb(src), emb(dst))) / 2 )` using the `definition`
  view; if either embedding missing (3.5% of entities) → fall back to entity_type inequality (1.0 if
  different type, 0.3 if same) and stamp `scorer_version` suffix `+typefallback`.
- **novelty** = fraction of `rel_ids` with `first_seen ≥ now() − novelty_window_days` (default 7).
- **weirdness** = `reliability × (w_U·U + w_S·S + w_N·N)`, weights default (0.45, 0.40, 0.15), config-driven.

#### Enum/constants
- `MEMBERSHIP_RELATIONS = frozenset({"IS_IN_SECTOR", "LISTED_ON", "OPERATES_IN_COUNTRY", "HEADQUARTERED_IN"})`
  — **uppercase AGE edge-label strings** (AGE stores labels derived from `relations.canonical_type`
  uppercased with spaces→underscores, per `age_sync_worker._derive_edge_label`), NOT the lowercase
  `RelationType` StrEnum values. ⚠ Note `IS_IN_SECTOR` and `HEADQUARTERED_IN` are **not** members of
  the 16-entry `RelationType` StrEnum (the full 32-type set lives in the `relation_type_registry`
  table / AGE labels) — so this set must be defined as literal AGE-label strings and **validated
  against `age_sync_worker`'s `_AGE_EDGE_LABELS` whitelist**, not derived from `RelationType`. The
  traversable allow-list = `_AGE_EDGE_LABELS − MEMBERSHIP_RELATIONS`. Referenced by engine + scorer.

### 6.6 Frontend Changes (apps/worldview-web)
- **New**: `WeirdConnectionsFeed` component + route surface (global feed) consuming `GET /v1/connections/weird`
  via a new `useWeirdConnections` hook (TanStack Query, 5-min staleTime).
- **New**: "How are these related?" pairwise UI (entity-pair picker → `usePathBetween` → ranked paths).
- **Update**: `PathsTab` + `PathInsightsBlock` — show `weirdness` + sub-score breakdown (reliability /
  unexpectedness / semantic distance / novelty) instead of harmonic/diversity/surprise; types in
  `types/intelligence.ts` gain the additive fields. Heavy inline comments (user is new to Next.js).
- **Tests**: extend `intelligence-hooks.test.ts`, `PathInsightsBlock.test.tsx`; new tests for the feed + pairwise.

### 6.7 Data Flow

**Pairwise (on-demand, interactive)**: FE `usePathBetween` → S9 `GET /v1/paths/between` (Valkey check)
→ S6 `GET /api/v1/paths/between` → `FindPathsBetweenUseCase` → `GraphPathEngine.path_exists` (VLE,
scalar length) → if connected, `find_paths_between` (VLE staged probe, agtype-parsed detail) → `WeirdnessScorer`
(degrees/embeddings/first_seen lookups) → ranked `PathBetweenPublic[]` → cache → FE.

**Discovery (batch)**: APScheduler cron → `PathInsightSeeder` (enqueue hubs, **skip terminally-failed**)
→ `PathInsightWorker` claims job → `GraphPathEngine.find_paths_from_anchor` (untyped VLE + post-hoc membership filter,
maxhops=cap) → `WeirdnessScorer` → `replace_for_anchor` writes `path_insights` (with `dst_entity_id` +
sub-scores + `scorer_version`). Global feed reads the same table ordered by `weirdness` (no separate compute).

**Degree refresh**: AGE-sync worker cycle → recompute `node_degree` + `graph_stats` (single upsert, ~18 ms).

---

## 7. Architecture Decisions & Trade-offs

### AD-1: Path-detail retrieval — reuse cypher_path VLE+agtype-parse vs in-memory adjacency
**Correction (post-planning verification):** the original premise — "VLE cannot return
`nodes(p)`/`relationships(p)`, so detail needs a new typed fixed-k query" — was **wrong**.
`application/use_cases/cypher_path.py::CypherPathUseCase._execute_staged` **already returns full path
detail** via `RETURN nodes(p) AS nodes_col, relationships(p) AS rels_col` parsed by
`_parse_agtype_text` (text-mode agtype, not asyncpg prepared-statement list binding). **BP-SA5-003
applies only to asyncpg prepared-statement agtype-*list* binding, NOT to text-parsed agtype result
columns** — cypher_path proves the text-parse path works. So no separate "typed fixed-k" query is
needed; detail comes from the same VLE staged-probe.
- **Option A — consolidate `cypher_path.py`** (chosen): the `AgeGraphPathEngine` reuses the proven
  staged `*L..L` VLE probe + `nodes(p)/relationships(p)` + `_parse_agtype_text`, with a **post-hoc
  Python membership filter** (AGE 1.5 has no multi-label VLE, so the allow-list can't live in the
  pattern). Both endpoints bound for pairwise; target free for anchor discovery. Stays in AGE; W2
  spike measured hop-3 pairwise p95 = 248 ms / anchor 1391 ms (within budget); hop-4/5 blow up because
  the post-hoc filter doesn't prune the frontier → **cap committed at 3**.
- **Option B — in-memory adjacency** (fallback, not default): the pruned graph is tiny (~5,200
  meaningful edges); load adjacency + degrees + first_seen once per worker cycle and do BFS + scoring
  in Python. Retained as an escalation if the W2 maxhops spike shows AGE p95 breaching budget at the
  desired cap.
- **Decision**: **A for both the pairwise endpoint and batch discovery** (one consolidated engine,
  least code). B is the documented fallback. The W2 spike (T-2-05) measures the pruned-graph p95 and
  decides whether B is needed for the higher maxhops; A always meets budget at maxhops ≤ 3, so this is
  not a blocking unknown.

### AD-2: Extend `path_insights` vs new `weird_paths` table
- Extend (chosen): additive columns, reuse the wired read path (S9, frontend, LLM tool), least churn,
  forward-compatible (R5). Global feed = a query over the same table with a global index.
- New table (rejected): cleaner model but doubles the write path and forces a frontend/LLM-tool cutover.
- **Decision**: extend. `dst_entity_id` + sub-scores make the global feed a pure read concern.

### AD-3: Unexpectedness formula — configuration-model surprise vs Adamic-Adar
Both need only degrees (GREEN). Configuration-model `-log(deg(u)·deg(v)/2m)` is simpler and directly
demotes hubs; Adamic-Adar rewards rare *shared neighbours* (better for "why" but costs a self-join).
- **Decision**: ship configuration-model as default; implement Adamic-Adar behind a config flag and
  pick the winner in the metric-validation wave against human-judged samples (thesis evidence).

### AD-4: Replace vs augment the seeder
- **Decision**: minimal change — seeder excludes anchors with a `failed` job at `retry_count ≥ max`
  (`NOT EXISTS` subquery) and the hub threshold is raised off the demo-era 2. The engine swap removes
  the timeouts that created the failures, so over time the failed set drains; a manual reset script
  re-opens them once the fast engine lands.

### AD-5: maxhops cap — measured, not assumed
Investigation measured maxhops≤3 safe (60–800 ms) and maxhops=4 hub↔hub = 13.8 s **on the unpruned
graph**. Pruning removes 47% of edges (the hub-routing ones), so the 4-hop blow-up should shrink
sharply. **Decision**: ship with cap=3; Wave 2 spike re-measures 4 and 5 on the pruned graph; raise
the cap (config `path_max_hops`) to the largest value with pairwise p95 < 1 s and discovery < 5 s.

---

## 8. Security & Multi-Tenancy

- **Injection**: entity_ids are UUIDs validated by strict regex before any Cypher embedding (existing
  BP-SA5-003 pattern retained — UUIDs contain no Cypher metacharacters). No user free-text reaches a
  query. Relation labels in the typed allow-list are compile-time constants, never user input.
- **Tenant isolation (NFR-5)**: `path_insights.tenant_id` is a nullable overlay; shared-graph insights
  are tenant-agnostic (the KG is a shared knowledge base, not per-tenant user data — consistent with
  the existing paths endpoint). The pairwise + global endpoints read shared-graph structure only; no
  per-user data is exposed. S9 still requires authentication and scopes the Valkey cache key by tenant
  to prevent cross-tenant cache bleed.
- **Resource-exhaustion / DoS**: the pairwise endpoint is on-demand and user-triggerable → hard
  `max_hops` cap, `statement_timeout`, rate limit (60/min), and Valkey caching prevent a crafted
  hub↔hub maxhops query from melting Postgres. `source != target` enforced.
- **Authz**: same as existing intelligence endpoints (authenticated user). No new privilege tier.

---

## 9. Failure Modes (cross-ref BUG_PATTERNS.md)

| Dependency / step | Failure | Handling |
|-------------------|---------|----------|
| AGE traversal exceeds budget | statement_timeout fires | Query cancelled cleanly (timeout < client wait_for); pairwise → 503 + retry hint; discovery → job marked failed (no re-queue, FR-1) |
| Embedding missing for an endpoint | `embedding_of` returns None | entity_type fallback in scorer (AD-1); `scorer_version` stamped `+typefallback`; never crashes |
| `node_degree` stale/empty | degree lookup misses | Scorer treats missing degree as 1 (max surprise) — fail-open to "weird", logged; AGE-sync refresh repairs |
| `relations.first_evidence_at` null | novelty unknown for an edge | Treat edge as not-recent (novelty contribution 0) |
| Duplicate-canonical self-loop path | src==dst or repeated node | Scorer returns weirdness=0 → filtered before persist (mitigates FR-11 without dedup) |
| AGE↔relations sync gap (FR-13) | VLE finds an edge `relations` lacks | Path detail join leaves edge confidence/first_seen null → reliability/novelty degrade gracefully; gap logged for the separate investigation |
| rag-chat tool wire-shape drift | `get_path_between` output mismatch | R29 manifest-sync arch test + contract test pin the shape |
| Seeder reset re-opens 298 jobs before engine swap | flood returns | Reset script gated behind a flag; only run after Wave 2 lands |

---

## 10. Scalability & Performance

- Graph scale today: 3,828 connected vertices / 9,977 edges (~5,200 after membership pruning). In-memory
  adjacency is < 1 MB — trivially resident. Degree agg ~18 ms; whole-graph weirdness recompute is seconds.
- The global feed is a precomputed read (indexed `weirdness DESC`) → p95 < 300 ms easily, 5-min cached.
- Pairwise is the only user-triggered compute: bounded by `max_hops` cap + statement_timeout + rate
  limit + cache. Worst case (cold, hub↔hub, cap=3) measured ~770 ms < 1 s budget.
- Growth: if the graph reaches ~10⁵ edges, in-memory still fits; degree/AA recompute stays sub-second.
  Re-evaluate the cap and consider incremental degree updates only past ~10⁶ edges (far future).

---

## 11. Test Strategy

### Unit (S6)
| Test | Verifies | Priority |
|------|----------|----------|
| test_weirdness_reliability_harmonic | harmonic mean, zero-confidence clamp | HIGH |
| test_weirdness_unexpectedness_demotes_hubs | high-degree endpoints → low unexpectedness | HIGH |
| test_weirdness_semantic_distance_cosine | cosine→[0,1]; missing-embedding type fallback | HIGH |
| test_weirdness_novelty_window | recent-edge fraction vs `novelty_window_days` | HIGH |
| test_weirdness_selfloop_zeroed | non-distinct nodes ⇒ weirdness 0 | HIGH |
| test_weirdness_composite_weights | weighted blend + reliability gate, clamp [0,1] | HIGH |
| test_scorer_version_stamped | version + `+typefallback` suffix | MED |
| test_engine_uses_typed_vle | engine never emits untyped `-[r]-` (string assert / mock) | HIGH |
| test_engine_membership_pruned | allow-list excludes the 4 membership labels | HIGH |
| test_seeder_skips_terminally_failed | retry_count≥max excluded from enqueue | HIGH |
| test_node_degree_refresh_upsert | degree + meaningful_degree computed correctly | MED |

### Integration (S6 + Postgres/AGE)
| Test | Infra | Verifies |
|------|-------|----------|
| test_path_exists_vle_latency | AGE | existence/length returns; under budget; both-ends-bound |
| test_find_paths_between_vle_detail | AGE | VLE staged probe returns correct agtype-parsed nodes/edges for known pair |
| test_maxhops_cap_enforced | AGE | max_hops>cap rejected (422) |
| test_discovery_no_timeout_pruned | AGE | per-anchor discovery on a hub-adjacent anchor completes < 5 s |

### Contract / arch
| Test | Verifies |
|------|----------|
| test_paths_between_contract | S9↔S6 pairwise response shape + param forwarding |
| test_weird_connections_contract | S9↔S6 global feed shape |
| test_tool_manifest_sync (R29) | `get_path_between` manifest ↔ handler signature in sync |
| test_paths_response_backward_compat | old `PathInsightPublic` fields still present (R5) |

### Frontend (Vitest)
| Test | Verifies |
|------|----------|
| useWeirdConnections.test | hook query key, staleTime, query-string build |
| usePathBetween.test | pairwise hook params + response typing |
| WeirdConnectionsFeed.test | renders ranked connections + sub-score breakdown |
| PathInsightsBlock.test (update) | shows weirdness instead of surprise; backward-compat with null sub-scores |

### Validation / thesis
| Test | Verifies |
|------|----------|
| test_path_quality_human_sample | top-20 global weird paths: < 3/20 are hub/self-loop noise (judged) |
| metric_ablation_report | configuration-model vs Adamic-Adar vs old surprise on a labelled sample (AD-3) |

---

## 12. Break-Surface Analysis & Migration Strategy

| Change | Currently Exists | What Breaks | Migration Strategy |
|--------|------------------|-------------|--------------------|
| Add 7 cols to `path_insights` | table at migration 0050 | `SELECT *` repos must map new cols; tests asserting exact column set | Migration 0052, all nullable + default; repo maps additively; no backfill required (worker repopulates) |
| Repurpose `composite_score` = weirdness | ranked by composite_score | ranking semantics change | Same column/index; value recomputed by new scorer; FE/LLM tool read the same field |
| Extend `PathInsight` dataclass (7 fields) | frozen dataclass, hub_penalty precedent | every `PathInsight(...)` construction + repo deserialize | All defaulted (mirror hub_penalty=0.0); update scorer + repo + ~4 unit test files |
| `PathInsightPublic` +5 fields | API schema | rag-chat `EntityPathsResult` map, FE `types/intelligence.ts` | Additive (R5); FE + tool ignore unknown/new fields; contract test pins it |
| New `node_degree`, `graph_stats` tables | none | none (new) | Migration 0052; refreshed by AGE-sync worker |
| Replace `PathDiscovery` → `AgeGraphPathEngine` | `path_discovery.py` (_build_2hop/_build_3hop) | `test_path_discovery.py`, worker wiring | New adapter behind `GraphPathEngine` port; keep old tests green or port them; DI swap |
| New `get_path_between` tool | rag-chat manifest v2 | manifest version + R29 sync test | Bump manifest version; add handler + port method; arch test |
| Seeder skip-failed + threshold | `path_insight_seeder.py` | `test_path_insight_seeder.py` | Add NOT EXISTS clause; raise `PATH_INSIGHT_HUB_MIN_RELATIONS` default; update test |
| Widen `max_hops` query bound 5→cap | use-case validation `_HOPS_MAX=5` | `test_paths_router.py` param tests | Only if validated cap > 5; else unchanged |

**External API reality check**: no external provider involved — all data is internal (AGE graph,
`entity_embedding_state`, `relations`). §2.8 N/A.

## 13. Observability

- **Metrics** (Prometheus, S6): `path_discovery_duration_seconds{phase=exists|detail}`,
  `path_jobs_failed_total`, `path_jobs_requeued_skipped_total` (FR-1 proof), `weirdness_score` histogram
  (spread monitoring vs the saturation baseline), `pairwise_requests_total{connected}`,
  `node_degree_refresh_duration_seconds`.
- **Logs** (structlog): engine emits chosen hop-count + pruned flag; scorer logs type-fallback usage
  rate; seeder logs skipped-failed count.
- **Alert**: `path_jobs_failed_total` rate > 0 sustained → the flood is back.

## 14. Open Questions (all DEFERRED — documented defaults)

| # | Question | Default | Severity |
|---|----------|---------|----------|
| ~~OQ-1~~ | ~~Final metric weights (w_U/w_S/w_N)~~ | **RESOLVED 2026-06-13 (W6 ablation): ship `0.45 / 0.40 / 0.15`.** `scripts/eval/weirdness_ablation.py` over the 514 live scored paths (audit §5): the shipped weights give a discriminating spread (p10-p90 = 0.522 > 0.5 target) and the top-20 head is **insensitive** to the U/S split (overlap 1.00 for every variant except `equal`, which both perturbs the top-20 *and* lowers the spread to 0.424). Result is not a tuning artefact. | **RESOLVED** |
| ~~OQ-2~~ | ~~Configuration-model vs Adamic-Adar for unexpectedness~~ | **RESOLVED 2026-06-13 (W6 ablation): ship `config_model`; `adamic_adar` kept behind the `weirdness_unexpectedness_mode` config flag (AD-3) for future re-eval.** AA gives a marginally wider raw spread (0.621) but reranks *toward* megacap-hub endpoints (`Zacks → big-tech → big-tech` fan-outs), trading the config-model top-20's genuine cross-domain endpoints (Apollo, Nebius, Saudi Arabia, Constellation Energy) for high-recognition tech hubs — the opposite of the §1 goal. config_model directly demotes high-degree endpoints, which is the property we want. config_model recompute self-check vs stored U: mean abs error 0.0176 (≈0). | **RESOLVED** |
| ~~OQ-3~~ | ~~Committed maxhops after pruning~~ | **RESOLVED 2026-06-12 (W2 spike): `path_max_hops = 3`.** Measured on the live graph (`scripts/eval/measure_maxhops_pruned.py`, audit §11): hop-3 pairwise p95=248 ms / anchor p95=1391 ms (within budget); hop-4 p95 6.5 s / 25.8 s and hop-5 timeouts — 4/5 are **not** safe even with membership pruning (hub frontier blow-up). Cap stays config-driven. Also corrected: AGE 1.5 rejects multi-label VLE `\|`, so the engine uses untyped VLE + post-hoc Python membership filter. | **RESOLVED** |
| ~~OQ-4~~ | ~~`novelty_window_days` while graph is young (~3 wks history)~~ | **RESOLVED 2026-06-13 (W6): keep `novelty_window_days = 7`; revisit as edge history grows.** N is uniformly 0.00 on the current ~3-week graph (no edges in the 7-day window), so it is harmless today (×0.15 of zero) and future-proofs the metric for when fresh edges arrive. No signal yet to justify changing it (the `no-novelty` weight variant kept the identical top-20, confirming N is currently dead weight, not harmful). | **RESOLVED** |
| OQ-5 | Does the consolidated VLE engine meet budget at the desired maxhops, or fall back to in-memory adjacency? | A meets budget at maxhops≤3; in-memory fallback available (AD-1) | DEFERRED |
| OQ-6 | Global feed: dedup near-identical paths (same endpoints, diff middle)? | show distinct endpoint-pairs, best path each | DEFERRED |

## 15. Architecture Compliance Gate (RULES.md)

| Rule | Applies | Decision | Compliant |
|------|---------|----------|-----------|
| R5 — Avro forward-compat | events: no; DB/schema: yes | All cols additive+nullable; API fields additive | PASS |
| R7/R9 — no cross-service DB | yes | All new tables in intelligence_db, read only by S6; FE via S9 only | PASS |
| R8 — no dual writes (outbox) | no | No DB+Kafka dual write; work-queue is single-DB | PASS (N/A) |
| R10 — UUIDv7 | yes | `new_uuid7()` for any new ids; entity_ids unchanged | PASS |
| R11 — UTC timestamps | yes | `utc_now()`; `refreshed_at`/`computed_at` tz-aware | PASS |
| R14 — frontend→S9 only | yes | New endpoints proxied via S9 | PASS |
| R24 — intelligence_db DDL ownership | yes | Migration 0052 in intelligence-migrations only; S6 ALEMBIC_ENABLED=false | PASS |
| R25 — API uses only use cases | yes | Routers → FindPathsBetween/GlobalWeird/GetEntityPaths use cases | PASS |
| R27 — read replica for read-only | yes | Global feed (pure `path_insights` SELECT, no AGE) uses KG's `ReadOnlyDbSessionDep` (`get_readonly_session`) — the same read-session construct the existing `get_entity_paths` uses (KG has no generic `ReadOnlyUnitOfWork`/`ReadUoWDep`). AGE traversal (pairwise + per-anchor) needs `LOAD 'age'` → write-session exception, per the existing `CypherPathUseCase` precedent (verified: `cypher_path.py` issues `LOAD 'age'`) | PASS (documented exception) |
| R29 — tool manifest sync | yes | `get_path_between` arch test | PASS |

**Completeness gate**: no BLOCKING OQs · no FAIL rules · no unverified external fields · no cross-PRD
conflict (PLAN-0074/0023 superseded-in-part, noted) · break-surface complete · every entity has a test
· every endpoint has error responses · no new events. → **PASS, cleared for planning.**

---

## 16. Proposed Wave Breakdown (for /plan)

- **Wave 1 — Remediation (hours, no schema change)**: seeder skip-terminally-failed + raise
  `PATH_INSIGHT_HUB_MIN_RELATIONS`; hard-cap maxhops=3; `max_parallel_workers_per_gather=0` +
  statement_timeout hygiene in the AGE session; metric `path_jobs_requeued_skipped_total`. **Stops the
  flood.** BUG_PATTERNS.md entries (untyped-edge seq-scan; seeder re-queue-of-failed).
- **Wave 2 — Engine + maxhops spike**: `GraphPathEngine` port + `AgeGraphPathEngine` (untyped VLE + post-hoc membership filter +
  consolidating cypher_path VLE+agtype-parse), membership pruning, replace `PathDiscovery`; measurement spike → commit the cap.
- **Wave 3 — Metric + degree**: migration 0052 (`node_degree`, `graph_stats`, path_insights cols);
  AGE-sync degree refresh; `WeirdnessScorer` (config-model + AA flag); wire into discovery worker;
  backfill script; ablation report.
- **Wave 4 — Pairwise endpoint + LLM tool**: `FindPathsBetweenUseCase`, KG + S9 routes, `get_path_between`
  tool + manifest bump + R29 test; contract tests.
- **Wave 5 — Global feed + frontend**: `GlobalWeirdConnectionsUseCase`, KG + S9 routes; `WeirdConnectionsFeed`
  + `usePathBetween`/`useWeirdConnections` hooks; PathsTab/PathInsightsBlock re-label; Vitest.
- **Wave 6 — Validation + docs**: human-sample quality gate, metric finalisation, docs
  (`docs/services/knowledge-graph.md`, api-gateway, rag-chat, `.claude-context.md`), TRACKING.md.

Critical path: W1 → W2 → W3 → (W4 ∥ W5) → W6. W1 is independently shippable immediately.
