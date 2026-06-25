# Investigation Report: "Weird Path" Redesign Feasibility

**Date**: 2026-06-12
**Investigator**: Claude (investigate skill)
**Severity**: HIGH (feature produces low-value output + saturates Postgres)
**Status**: Root cause identified; redesign feasible — all three target signals computable today
**Related**: `docs/audits/2026-06-12-postgres-log-investigation.md` (the log-flood symptom)

## 1. Issue Summary

The `PathInsightWorker` precomputes "surprising" multi-hop paths radiating from each anchor
entity. Investigation set out to (a) quantify why it floods Postgres with timeouts, (b) decide
whether the three chosen "weirdness" signals — **statistical unexpectedness (B)**, **semantic /
domain distance (C)**, **temporal novelty (E)** — are computable on the live graph, and (c) test
the feasibility of a new pairwise *"is A connected to B?"* endpoint.

**Headline result:** all three signals are computable today with no new infrastructure, the
pairwise endpoint is fast and viable, **and the single biggest finding is unexpected** — the
current slowness is *not* primarily the `O(degree³)` walk. It is that the codebase's
**explicit-hop query pattern with untyped edges forces AGE to sequential-scan all ~30 edge-label
tables**, making even a *1-hop* neighbour fetch take **18 seconds**. Apache AGE's variable-length
operator (`-[*1..N]-`) is **76× faster** for the identical traversal because it uses the vertex
GIN index. The current design picked the pathologically slow primitive.

---

## 2. Thread 1 — Current State & Bottleneck Quantification

### 2.1 The graph is small and hub-dominated
- **3,828 connected vertices, 9,977 edges** (the oft-cited "33k vertices" is misleading — ~29k are
  isolated `TemporalEvent`/orphan nodes with no edges).
- **47% of all edges are membership-to-hub**: `IS_IN_SECTOR` (1,812), `LISTED_ON` (1,375),
  `OPERATES_IN_COUNTRY` (1,192), `HEADQUARTERED_IN` (338) = 4,717 / 9,977. Nearly half the graph's
  connectivity is "everyone points at the same 11 sectors / 2 exchanges / handful of countries."

### 2.2 Degree distribution — brutally heavy-tailed
- **median degree 2**, p90 = 10, p99 = 72, p99.9 = 259, **max = 393**.
- degree > 20: 128 vertices · > 50: 47 · > 100: 18.
- **All 18 mega-hubs (degree >100) are sector/exchange/country/macro nodes** — NYSE (393),
  NASDAQ (381), Information Technology (294), Financials (259), Industrials (233), … the GICS sector
  taxonomy plus the two exchanges plus US/China. These are *low-information* membership hubs that any
  undirected traversal routes through.

### 2.3 Current `path_insights` output is low-value
- **35,298 rows across 713 anchors** (~49.5/anchor). Only hop=2 (53.6%) and hop=3 (46.4%) exist.
- **`surprise_score` is saturated and non-discriminating**: p50 = 0.951, mean = 0.839, 75% of paths
  score ≥ 0.73. "Surprise" is essentially always-on.
- **There is no `hub_penalty` column persisted** — the scorer computes one transiently but it is not
  stored, and it clearly fails to demote hub paths.
- **Top-20 by composite_score are hub-routed noise or degenerate self-loops**, e.g.:
  - CVS → *Health Care sector* → Intuitive Surgical → Medtronic ("both are healthcare companies").
  - Cameco → uranium → **Cameco** → Persian Gulf (path returns to its own anchor — degenerate cycle).
  - Meta → WhatsApp → **Meta** (anchor-to-itself via a duplicate Meta vertex).
  - Ford → *Utilities sector* → Tesla (both mis-typed into "Utilities"; nonsensical relations).
  - The few non-degenerate paths are *correct but obvious* corporate facts (Micron→NVIDIA supplier),
    not surprising cross-domain links.
  - **Verdict: the current scorer rewards exactly the wrong thing** — high score correlates with
    passing through a high-degree hub and with duplicate-entity self-loops.

### 2.4 The re-queue loop is real
- `path_insight_jobs`: done 2,571 · pending 381 · **failed 298 (all retry_count = 3)** · running 3.
- **100% of failures are `PathDiscovery timed out after 60.0s`** — pure traversal timeouts, no logic
  errors.
- Failed anchors are **not** themselves hubs (median degree 6) — but **222 of 298 (74.5%) have a
  direct membership edge into a mega-hub**. A degree-6 company (Garmin, Colgate-Palmolive, Schwab)
  times out because hop 1 lands on a degree-300 sector and hop 2 fans out. These 298 are re-queued
  indefinitely (each attempt burns 60s × 3 retries for zero output).

### 2.5 Bonus data-quality findings (relevant to redesign)
- **Hub mis-typing**: NYSE typed `financial_instrument`, NASDAQ `index`, "U.S." `currency`. Pollutes
  any type-based logic.
- **Heavy duplicate canonicals**: NVIDIA appears ≥3× (deg 155/116/106/87), Meta 2×, Microsoft 2×.
  Splits one logical entity across multiple high-degree vertices → inflates fan-out, fragments paths,
  produces the self-loop "insights."

---

## 3. Thread 2 — Feasibility of the Three Weirdness Signals

**Edge keying (foundation):** a logical edge = `public.relations.relation_id` (UUID). Every AGE edge
stores exactly `{"relation_id": "<uuid>"}`; AGE vertices store `{"entity_id": "<uuid>"}`. Verified
join: AGE edge → `relations` on `relation_id` → `relation_evidence` (monthly-partitioned). This join
is what lets structural edges be enriched with confidence + timestamps.

| Signal | Verdict | Primary source | Coverage | Approach |
|--------|---------|----------------|----------|----------|
| **B** Statistical unexpectedness (PMI / Adamic-Adar / common-neighbors) | **🟢 GREEN** | `worldview_graph._ag_label_edge` (start_id/end_id) | 100% structural | Materialize a `node_degree` table (graph-wide degree agg measured at **~18 ms**); compute AA / common-neighbors / PMI via a SQL self-join on an undirected edge view. Sub-second graph-wide at this scale. |
| **C** Semantic / domain distance | **🟢 GREEN** | `entity_embedding_state` (`view_type='definition'`, `vector(1024)`, bge-large-en-v1.5) | **96.5%** (16,614 / 17,222) | Cosine distance via the existing pgvector `<=>` operator (already in production in `entity_embedding_ann.py`). HNSW cosine index exists. Use `entity_type` (11 values, 100% populated) as a coarse complementary signal. **Do NOT** use sector/industry — only ~12% coverage. |
| **E** Temporal novelty | **🟢 GREEN** | `relations.first_evidence_at` (timestamptz, NOT NULL) | 100% of edges | Direct column filter `first_evidence_at > now() - interval 'N days'`. `relation_evidence` MIN(evidence_date) as an audit fallback (partition-pruned). |

**All three are computable today with no new infrastructure.** The only optional add-on is
materializing `node_degree` for Signal B (sub-20ms even on the fly, so cron-refresh is a nicety, not
a requirement).

**Thesis caveat (Signal E):** the graph is only ~3 weeks old — all 7,165 relations have
`first_evidence_at` within the last 30 days (6,482 within 7 days). Until more history accumulates,
"emerged in last N days" needs a small N (3–7 days) to discriminate.

---

## 4. Thread 3 — Pairwise "Is A Connected to B?" Feasibility

- **AGE version 1.5.0.** Variable-length `-[*lo..hi]-` **is supported**. There is **no
  `shortestPath()` / `dijkstra()`** function — that is a hard syntax error in 1.5.0.
- **BP-SA5-003 confirmed server-side**: you cannot `RETURN p` / `relationships(p)` / `nodes(p)` from a
  VLE path (`agtype argument must resolve to a scalar value`) — this fails *even in psql*, it is not
  an asyncpg artifact. **Scalar projections work fine**: `RETURN length(p)`, `count(p)`, and
  individual `n.entity_id` serialize cleanly.

### 4.1 The decisive finding: VLE is 76× faster than the codebase's explicit-hop pattern
Same anchor, same 96 neighbours, **1 hop**:

| Form | Latency |
|------|---------|
| Explicit `MATCH (n0 {id})-[r1]-(n1)` (the `path_discovery.py` pattern) | **18,411 ms** |
| VLE `MATCH (n0 {id})-[*1..1]-(n1)` | **240 ms** |

`EXPLAIN` shows the explicit untyped edge `-[r1]-` forces a **Parallel Seq Scan of every one of the
~30 edge-label tables** with no predicate pushdown; VLE drives off the GIN-indexed start vertex via
the internal `age_vle` function scan. **The entire `path_discovery.py` design is built on the slow
primitive** — this, not just the cubic walk, is why the 298 jobs time out.

### 4.2 Measured pairwise latencies (VLE, both endpoints bound)

| Query | Result | Latency |
|-------|--------|---------|
| Nvidia↔SpaceX `*1..2` LIMIT 1 | found | 56 ms |
| Nvidia↔SpaceX `*1..3` LIMIT 1 | found | 227–770 ms |
| Apple↔Microsoft `*1..3` LIMIT 1 | found | 130 ms |
| NYSE↔NASDAQ (hub↔hub) `*1..3` LIMIT 1 | found | 87 ms |
| NYSE↔Nvidia `*1..3` LIMIT 1 | found | 412 ms |
| LG↔Valaris (leaves) `*1..3` LIMIT 1 | **no path** | 68 ms |
| **Nvidia↔SpaceX `*1..4` LIMIT 1** | found | **🔴 13,793 ms** |
| Nvidia↔SpaceX `*1..4` count(p) | 102,549 paths | 🔴 32,748 ms |

**Conclusions:**
- With **both endpoints bound**, VLE stays **≤~800 ms up to maxhops=3 for every pair type** —
  including hub↔hub and disconnected pairs. **Bidirectional meet-in-the-middle in app code is NOT
  needed.**
- **`LIMIT 1` does NOT short-circuit** — `*1..4` hub↔hub is 13.8s even with LIMIT 1 (partial
  materialization, not lazy early-out). The blow-up is specifically **maxhops ≥ 4 between high-degree
  nodes** (~100k paths). **maxhops ≤ 3 is the hard safe ceiling.**
- The hypothesized "explicit-hop with bound target" alternative is **20–40s — unusable** (same
  seq-scan pathology).

### 4.3 Data-sync gap (flag separately)
AGE returns `length(p)=1` for Apple↔Microsoft, but `relations` has **zero** direct Apple↔Microsoft
edge. The AGE `entity` graph contains edges not present in / differently directed from the
`relations` table. The AGE graph is the query source of truth, but this sync gap should be
investigated independently.

---

## 5. Root Cause Synthesis

| # | Root cause | Evidence |
|---|-----------|----------|
| RC-1 | **Slow query primitive.** Explicit untyped-edge MATCH seq-scans all ~30 edge-label tables. | 18.4s vs 0.24s for identical 1-hop; `EXPLAIN` seq-scan of every label table. |
| RC-2 | **Surprise defined relative to the local sibling path set**, which both (a) saturates the score and (b) *forces* full enumeration → couples the metric to the bottleneck. | surprise p50 0.951; metric needs `total_paths`. |
| RC-3 | **No hub down-weighting that works.** Hub penalty not persisted; membership edges (47% of graph) route every path through low-information sector/exchange hubs. | Top-20 all hub-routed; 74.5% of failed anchors link directly to a hub. |
| RC-4 | **Seeder re-queues terminally-failed hubs forever.** | 298 jobs at retry_count=3, all 60s timeouts. |
| RC-5 | **Data quality**: duplicate canonicals + hub mis-typing produce self-loop "insights." | NVIDIA ≥3×, Meta/MSFT 2×; NYSE typed instrument. |

---

## 6. Recommended Architecture — Shared Bounded-Search + Per-Path Surprise Engine

Both features (pairwise endpoint **and** redesigned discovery) sit on **one** primitive + **one**
scorer.

### 6.1 Bounded-search primitive (replaces `path_discovery.py` internals)
- **Use VLE `-[*1..3]-`, never the explicit untyped-edge MATCH.** Hard-cap **maxhops = 3**.
- **Existence / hop-length**: `MATCH p=(a:entity {entity_id:'A'})-[*1..3]-(b:entity {entity_id:'B'})
  RETURN length(p) LIMIT 1` → scalar, asyncpg-safe, 60–800 ms. Empty = not connected within 3 hops.
- **Path detail** (can't return list columns, BP-SA5-003): once `k` = hop-length is known, fetch the
  concrete path with a **fixed-k scalar-column** query binding both endpoints, returning
  `n_i.entity_id, n_i.canonical_name, type(r_i), r_i.confidence`. Run only for the discovered `k`.
- **Prune membership edges** (`IS_IN_SECTOR`, `LISTED_ON`, `OPERATES_IN_COUNTRY`, `HEADQUARTERED_IN`)
  from *discovery* traversal — typed VLE `-[:REL_A|REL_B*1..3]-` — eliminating 47% of low-value
  fan-out at the source. (Keep them queryable for the pairwise endpoint when the user explicitly
  wants "any connection.")

### 6.2 Per-path surprise scorer (replaces local-frequency `surprise_score`)
Each path scored **independently** from global precomputable stats (decouples from enumeration):
- **B — statistical unexpectedness**: for each edge on the path, Adamic-Adar / PMI from the
  materialized `node_degree` table; aggregate (e.g. min over edges = weakest "expectedness"). Hub
  routing is penalised *naturally* because hub endpoints have high degree → low PMI. **Replaces the
  hand-tuned hub_penalty.**
- **C — semantic distance**: cosine distance between the two *endpoint* embeddings (`definition` view,
  `<=>`), and optionally max pairwise distance across the path. High distance = bridges distant
  domains = weird.
- **E — temporal novelty**: fraction of the path's edges with `first_evidence_at` in the last N days
  (small N for now). Recently-formed bridges score higher.
- **reliability gate**: harmonic mean of edge confidence — keep as a *multiplicative gate* so a
  high-surprise path built on extraction noise can't win.
- Suggested composite: `weirdness = reliability × (w_B·B + w_C·C + w_E·E)`, weights tunable; drop the
  saturated local-frequency term entirely.

### 6.3 Loop / cost fixes
- Seeder **skips terminally-failed anchors** (retry_count ≥ max) and raises
  `PATH_INSIGHT_HUB_MIN_RELATIONS` off the demo-era value of 2.
- `SET LOCAL statement_timeout` well under the client `wait_for`; set
  `max_parallel_workers_per_gather = 0` in the AGE session to silence the `parallel worker` FATALs.

### 6.4 Infra / data-quality follow-ups (separate work)
- Investigate the untyped-edge seq-scan pathology (typed traversal sidesteps it; consider whether an
  index or AGE config helps the general case).
- Dedup canonical entities (NVIDIA/Meta/MSFT); fix hub mis-typing (NYSE/NASDAQ/U.S.).
- Investigate the AGE-graph ↔ `relations`-table edge sync gap.

---

## 7. Verdict

| Question | Answer |
|----------|--------|
| Are B / C / E computable today? | **Yes — all three GREEN, no new infra.** |
| Is the pairwise endpoint feasible & fast? | **Yes — VLE both-ends-bound, maxhops≤3, 60–800 ms.** |
| Is "find weird paths" the right goal? | Yes, but the *metric* and the *query primitive* are both wrong today. |
| Biggest surprise | The slowness is mostly the **explicit-hop seq-scan (18s/1-hop)**, fixable by switching to VLE (76×), not only the cubic walk. |

## 8. Open Questions
1. Weight tuning (w_B/w_C/w_E) and whether semantic distance should be endpoint-only or path-max.
2. Whether discovery should be per-anchor at all, or reframed as "top weird connections graph-wide."
3. The AGE↔`relations` edge-count discrepancy (data integrity — needs its own investigation).

## 9. Recommended Next Step
This is a feature redesign, not a bug fix → **`/prd`** to capture: (1) pairwise connection endpoint,
(2) redesigned weirdness metric (B×C×E, reliability-gated), (3) VLE-based bounded-search engine,
(4) membership-edge pruning, (5) seeder loop fix. Optionally ship the seeder loop fix + VLE swap as a
fast first wave to stop the Postgres flood immediately.

## 10. Compounding Check
Recommend new bug-pattern entries:
- **BP (new): AGE untyped-edge MATCH seq-scans all label tables** — always prefer VLE `-[*..]-` or
  typed edges; explicit untyped `-[r]-` is O(#label-tables) seq-scan. (18s vs 0.24s, measured.)
- **BP (new): seeder re-queues terminally-failed work** — any job re-seeder must exclude
  `retry_count >= max` or it burns timeout budget forever.
- Reinforces existing BP-SA5-003 (agtype list return is server-side, not asyncpg-only).

---

## 11. Wave-2 maxhops measurement spike (PLAN-0112 T-2-05, measured 2026-06-12)

**Method**: `scripts/eval/measure_maxhops_pruned.py` — read-only, runs the consolidated
`AgeGraphPathEngine` query shapes against the live `worldview_graph` (33,301 vertices /
9,979 edges) for representative pairs (hub↔hub, hub↔leaf, distant, connected, disconnected),
top-degree hub = 393 edges. Same session GUCs as production (`statement_timeout=25s`,
`max_parallel_workers_per_gather=0`). 2 runs/probe.

**Engine-design finding (supersedes the §6.2 "typed VLE" assumption)**: AGE 1.5 does **NOT**
support the multi-label VLE syntax `-[:LABEL_A|LABEL_B*L..L]-` — it is a hard parse error at
the `|` (same family as the BP-461 `|` list-comprehension limitation), nor does it support
`ALL(r IN relationships(p) WHERE type(r) <> …)` (BP-450). The engine therefore uses an
**untyped VLE `-[*L..L]-`** (fast: ~190 ms 2-hop / 1.7 s 3-hop hub vs the retired 18 s
explicit-edge form, BP-689) with **membership pruning applied post-hoc in Python**. Pruning
removes membership *paths from results*; it does not shrink the traversal frontier.

**Latency (membership-pruned graph, untyped VLE)**:

| max_hops | pairwise p50 | pairwise p95 | anchor p50 | anchor p95 | within budget? |
|----------|-------------:|-------------:|-----------:|-----------:|:--------------:|
| **3**    | 103 ms       | **248 ms**   | 1092 ms    | **1391 ms** | ✅ pairwise<1 s AND anchor<5 s |
| 4        | 221 ms       | 6491 ms      | 15993 ms   | 25815 ms    | ❌ (hub frontier blow-up) |
| 5        | 179 ms       | 25729 ms     | 25760 ms   | 26020 ms    | ❌ (statement_timeout) |

The 4-/5-hop p95 explosions are the top-degree hubs (anchor discovery enumerates the full
O(degree^k) neighbourhood; pairwise both-bound 4-hop hub↔hub measured 3.3 s standalone).

**Decision (resolves OQ-3)**: committed **`path_max_hops = 3`** — the largest hop with pairwise
p95 < 1 s AND per-anchor discovery p95 < 5 s. `config.py` default already 3; **no change** (4/5
are unsafe even with membership pruning, contrary to the optimistic "raise to 4/5" hypothesis).
The cap is config-driven (`KNOWLEDGE_GRAPH_PATH_MAX_HOPS`) so it can be re-measured as the graph
grows / hub mis-typing (NYSE/NASDAQ dedup, §6.4) is fixed.
