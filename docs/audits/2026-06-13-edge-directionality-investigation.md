# Edge Directionality Investigation — KG Path Traversal

**Date:** 2026-06-13
**Scope:** Read-only investigation. No code, data, or schema changes.
**Question:** Should some knowledge-graph relation types be **directional** (directed edges) rather than treated as undirected, given that all AGE path traversal today is **undirected** (`-[*L..L]-`, no arrow)?

**Bottom line:** The underlying data IS directed and stored correctly (`relations.subject_entity_id → object_entity_id`; AGE edges written `(s)-[r]->(o)` with `start_id=subject`, `end_id=object`). The traversal layer **discards that direction**: it runs an undirected VLE and the parser assumes every edge goes `node[i] → node[i+1]` in *path order*, which is frequently backwards. The result is semantically inverted chains for asymmetric relation types (e.g. "Informatica ACQUIRED_BY Salesforce" when the truth is "Salesforce ACQUIRED_BY Informatica"). The agtype payload already contains `start_id`/`end_id` per edge, so direction is fully **recoverable post-hoc** — the cheapest correct fix is to render direction from those fields rather than from path order. AGE 1.5 *can* express directed VLE (`-[*L..L]->`), confirmed working, so directed traversal is also an option for asymmetric types.

---

## 1. Relation-type taxonomy

`relation_type_registry` has **32 active rows** (columns: `canonical_type, semantic_mode, decay_class, base_confidence, embedding, description, is_active, data_source, source_field`). There is **no `is_directed` / `symmetry` / `inverse_type` column** — directionality is implicit and nowhere declared.

Classification (✦ = live edge count in `relations`, 2026-06-13):

| canonical_type | semantic_mode | Symmetry | Notes |
|---|---|---|---|
| acquired_by ✦51 | RELATION_STATE | **ASYMMETRIC** | "subj was acquired BY obj"; reversing inverts meaning |
| subsidiary_of ✦40 | RELATION_STATE | **ASYMMETRIC** | parent/child; reversing inverts |
| supplier_of ✦115 | RELATION_STATE | **ASYMMETRIC** | "subj supplies obj"; reversing inverts |
| owns_stake_in ✦38 | RELATION_STATE | **ASYMMETRIC** | holder→holdee |
| investment_in ✦92 | RELATION_STATE | **ASYMMETRIC** | investor→investee |
| employs ✦49 | RELATION_STATE | **ASYMMETRIC** | employer→person |
| has_executive ✦311 | RELATION_STATE | **ASYMMETRIC** | company→person |
| board_member_of ✦44 | RELATION_STATE | **ASYMMETRIC** | person→company |
| appointed_as ✦14 | RELATION_STATE | **ASYMMETRIC** | person→role |
| regulates ✦167 | RELATION_STATE | **ASYMMETRIC** | regulator→regulated |
| produces ✦152 | RELATION_STATE | **ASYMMETRIC** | company→product |
| listed_on ✦841 | RELATION_STATE | **ASYMMETRIC** (membership) | security→exchange |
| is_in_sector ✦417 | RELATION_STATE | **ASYMMETRIC** (membership) | company→sector |
| is_in_industry ✦57 | RELATION_STATE | **ASYMMETRIC** (membership) | company→industry |
| operates_in_country ✦805 | RELATION_STATE | **ASYMMETRIC** (membership) | company→country |
| headquartered_in ✦236 | RELATION_STATE | **ASYMMETRIC** (membership) | company→country |
| revenue_from_country ✦0 | TEMPORAL_CLAIM | **ASYMMETRIC** | company→country |
| reported_revenue_of ✦8 | TEMPORAL_CLAIM | **ASYMMETRIC** | company→value |
| divested_from ✦23 | TEMPORAL_CLAIM | **ASYMMETRIC** | seller→divested asset |
| downgraded_by ✦13 | TEMPORAL_CLAIM | **ASYMMETRIC** | issuer→analyst/agency |
| filed_lawsuit_against ✦16 | TEMPORAL_CLAIM | **ASYMMETRIC** | plaintiff→defendant |
| analyst_rating ✦120 | TEMPORAL_CLAIM | **ASYMMETRIC** | subject→rating source |
| price_target ✦24 | TEMPORAL_CLAIM | **ASYMMETRIC** | subject→target value |
| credit_rating ✦0 | TEMPORAL_CLAIM | **ASYMMETRIC** | issuer→rating |
| earnings_guidance ✦0 | TEMPORAL_CLAIM | **ASYMMETRIC** | company→guidance |
| earnings_released ✦0 | TEMPORAL_CLAIM | **ASYMMETRIC** | company→report |
| issues_debt ✦6 | TEMPORAL_CLAIM | **ASYMMETRIC** | issuer→instrument |
| market_share_claim ✦0 | TEMPORAL_CLAIM | **ASYMMETRIC** | company→claim |
| corporate_action ✦2 | TEMPORAL_CLAIM | **ASYMMETRIC** | company→action |
| sentiment_signal ✦9 | TEMPORAL_CLAIM | mostly directional | source→subject |
| **partner_of** ✦461 | RELATION_STATE | **SYMMETRIC** | "A partners with B" ⇔ "B partners with A" |
| **competes_with** ✦675 | RELATION_STATE | **SYMMETRIC** | "A competes with B" ⇔ "B competes with A" |

**Verdict:** **30 of 32** relation types are inherently **asymmetric/directional**. Only **2** (`partner_of`, `competes_with`) are genuinely symmetric — and those two are the highest-volume non-membership types. Direction is therefore the *common* case, not the exception.

`MEMBERSHIP_RELATIONS` (`domain/constants.py`) = `{IS_IN_SECTOR, LISTED_ON, OPERATES_IN_COUNTRY, HEADQUARTERED_IN}` — these are already pruned from anchor/pairwise results, so the directionality concern for them is moot in practice (they never appear in surfaced paths when `prune_membership=True`). The directionality problem that actually reaches users is dominated by: `has_executive` (311), `regulates` (167), `produces` (152), `supplier_of` (115), `investment_in` (92), `acquired_by` (51), `employs` (49), `board_member_of` (44), `subsidiary_of` (40), `owns_stake_in` (38).

---

## 2. How direction is stored & written

**`public.relations` is fully directional and canonical:**
- Columns `subject_entity_id` and `object_entity_id` (both `NOT NULL`).
- Unique constraint `uidx_relations_triple (subject_entity_id, canonical_type, object_entity_id)` — `(A,type,B)` and `(B,type,A)` are distinct rows.
- Indexes on both `subject` and `object` directions.

**AGE preserves direction on write.** `age_sync_worker._build_relation_merge_sql` emits:
```cypher
MATCH (s:entity {entity_id:$subject_id}), (o:entity {entity_id:$object_id})
MERGE (s)-[r:LABEL {relation_id:$relation_id}]->(o)
```
i.e. `start_id = subject`, `end_id = object`. **Verified in the live graph** — a directed Cypher `MATCH (s)-[:ACQUIRED_BY]->(o)` returns subject→object pairs, and the raw `worldview_graph.ACQUIRED_BY` edges carry `start_id`/`end_id` consistent with `relations`.

Sample of the raw edge payload (from `relationships(p)` agtype):
```json
{"id":2251799813685282,"label":"ACQUIRED_BY",
 "start_id":9288674231452071,   // Salesforce
 "end_id":9288674231457959,     // Informatica
 "properties":{"relation_id":"c30045ad-8a9f-4b99-80cf-d0ca8ed8a50f"}}
```
So **direction IS in the graph and IS in the agtype payload returned by traversal**. The loss happens later, in parsing.

> Side note (out of scope, but worth flagging): the *extraction* direction for `acquired_by` is noisy — several stored rows look inverted (e.g. `Cloudflare Inc acquired_by VoidZero`, when Cloudflare acquired VoidZero). That is a separate NLP-extraction data-quality issue, independent of the traversal-direction problem analysed here. Even with perfect extraction, the traversal still loses direction.

---

## 3. Semantic impact of undirected traversal

The active engine is `infrastructure/age/graph_path_engine.py::AgeGraphPathEngine` (the older `path_discovery.py` is deprecated but uses the same undirected form). Both build **undirected** VLE patterns:
```cypher
MATCH p = (s:entity {entity_id:'…'})-[*L..L]-(t:entity)   // note: -[ ]-  no arrow
RETURN nodes(p) AS nodes_col, relationships(p) AS rels_col
```

**Where the meaning is lost:** `graph_path_engine._row_to_raw_path` (and the twin `cypher_path._extract_edges`) build `RawPath` with the explicit assumption *"edge i connects nodes[i] → nodes[i+1]"* (documented verbatim in `ports/graph_path_engine.py::RawPath` and `_row_to_raw_path` line ~204). They read only `label`, `confidence`, `relation_id` from each edge and **drop `start_id`/`end_id`**. So when AGE walks an edge *backwards* relative to the path, the code still renders it forwards.

`RawPath` / `PathEdge` / `PathEdgePublic` all carry only `relation_type` — **no direction field anywhere** in the domain entity, the port DTO, or the public wire schema (`application/schemas/paths.py`). `PathEdge`'s docstring even says "A directed relation edge" but stores no direction.

**The render that ships the wrong meaning:** `path_explanation_service._build_prompt` (line ~186) constructs
```python
f"{from_name} --[{safe_rel}]--> {to_name}"   # from = node[i], to = node[i+1], path order
```
and feeds it to the LLM with a forward arrow `-->`. The frontend does the same pairing of `path_edges[i]` with `path_nodes[i]→[i+1]`.

### Concrete wrong-direction example (live graph, 2026-06-13)

Undirected 1-hop traversal anchored at **Informatica** (`d607b621-…`):
- `nodes(p)` order: **Informatica → Salesforce**
- the `ACQUIRED_BY` edge: `start_id = Salesforce`, `end_id = Informatica`

True fact (stored direction): **Salesforce ACQUIRED_BY Informatica** ("Salesforce is acquired by Informatica" per the row; regardless of extraction polarity, the *graph* says subject=Salesforce). The undirected path renders it as **"Informatica --[ACQUIRED_BY]--> Salesforce"** → inverted. Inside a multi-hop chain the LLM then narrates a false causal story ("Informatica was acquired by Salesforce, which connects it to …").

The same backward-walk happens generically: any path anchored at (or passing through) the *object* of an asymmetric edge traverses that edge against its stored direction. Given the 2-/3-hop neighbourhood sizes and that ~30/32 types are asymmetric, **a large fraction of multi-hop paths contain at least one backward-traversed asymmetric hop**. For the two symmetric types (`partner_of` 461, `competes_with` 675) direction is irrelevant, so they are safe under undirected traversal — but they are the minority of edge *types*, not of edge *instances* in arbitrary paths.

**Why this matters more than "no path":** an inverted chain is *confidently wrong*. "X is a supplier of Y, which acquired Z" reads as plausible analysis even when every arrow is reversed. For a thesis whose value proposition is *surprising-but-correct* connections, a semantically inverted path is strictly worse than returning nothing.

---

## 4. AGE 1.5 directed-VLE feasibility (live tests, 2026-06-13)

| Test | Pattern | Result |
|---|---|---|
| Forward directed VLE, 1 hop | `(s)-[*1..1]->(o)` | ✅ parses & returns rows |
| Forward directed VLE, 2 hops | `(s)-[*2..2]->(o)` | ✅ parses & returns rows |
| Forward directed pairwise | `(s)-[*1..3]->(o) WHERE id(s)<>id(o) RETURN nodes(p)` | ✅ parses |
| Reverse directed VLE, unbound source | `(s)<-[*2..2]-(o)` (no anchor) | ⏱ ran unbounded over the full frontier — had to be cancelled (not a parse failure; just a hub blow-up when neither end is bound, identical to the known untyped-frontier cost) |
| Edge direction in payload | `relationships(p)` → each edge carries `start_id` + `end_id` | ✅ direction fully present in the returned agtype |

**Key results:**
1. **Directed VLE works in AGE 1.5** (`-[*L..L]->`). This contradicts the assumption that direction can only be handled post-hoc — directed *traversal* is on the table. (Still constrained by the PLAN-0112 limits: no multi-label VLE `-[:A|B*L..L]-`, no `shortestPath()`. Direction via the arrow is orthogonal to those and is supported.)
2. **`relationships(p)` already returns `start_id`/`end_id` per edge**, so even keeping undirected traversal, true direction is **100% recoverable** by comparing each edge's `start_id`/`end_id` to the adjacent node ids — no extra query needed.

---

## 5. Recommendation

**Recommended: (a) keep undirected traversal, but render direction correctly from `start_id`/`end_id` — with a small enhancement toward (c) for the worst asymmetric types.**

Rationale:

- **Undirected traversal is the right *discovery* primitive for the thesis goal.** Surprising connections often require crossing an edge "against" its stored direction (e.g. reaching an acquirer from the acquired company). Forcing directed-only traversal would *eliminate* legitimate surprising paths — the opposite of the product goal. The problem is not the traversal; it's the **rendering**.
- **The fix is cheap and exact.** Direction is already in the agtype payload (`start_id`/`end_id`) and in `relations` (`relation_id` is already parsed into `RawPath.rel_ids`). No new query, no AGE-feature risk.
- **Inverted chains are the actual harm.** Fixing rendering removes the "confidently wrong" failure mode entirely while preserving recall.

### Implementation sketch

1. **Capture direction in the parser** (`graph_path_engine._row_to_raw_path`, mirror in `cypher_path._extract_edges`): for each edge, read `start_id` and `end_id` (already in the parsed dict), compare against the vertex `id` sequence (`nodes(p)` elements also carry `id`), and record a per-edge `traversed_forward: bool` (True if `start_id == nodes[i].id`).
   - *Alternative without relying on AGE vertex ids:* join `rel_ids` back to `relations` and compare `subject_entity_id` to `node_ids[i]`. Slightly more robust to the `Entity`/`entity` dual-label quirk.
2. **Add `edge_directions: tuple[bool, ...]`** to `RawPath` (default empty for back-compat, same pattern as `rel_ids`).
3. **Thread a `direction` field** through `PathEdge` (domain) and `PathEdgePublic` (wire) — e.g. `"forward" | "reverse"`, default `"forward"` (forward-compatible, R11).
4. **Render correctly:**
   - `path_explanation_service._build_prompt`: when an edge is reverse-traversed, swap the endpoints so the LLM always sees `subject --[rel]--> object` (true direction), regardless of walk order. This is the single highest-leverage change — it stops feeding inverted facts to the LLM.
   - Frontend: orient the arrow per `direction` (render `B ←[ACQUIRED_BY]— A` or relabel), so the displayed chain reads truthfully even when the path walks an edge backward.
5. **Symmetric types need no orientation** (`PARTNER_OF`, `COMPETES_WITH`): mark them symmetric (a small `SYMMETRIC_RELATIONS` constant alongside `MEMBERSHIP_RELATIONS`) and skip the swap — either rendering reads correctly.
6. **(Optional, toward hybrid (c))** Expose `inverse phrasing` for asymmetric types so the UI can read a reverse hop naturally (e.g. reverse `ACQUIRED_BY` → "acquired", reverse `SUPPLIER_OF` → "is supplied by"). This is presentation polish on top of (1)–(5).

**What NOT to do:** Do **not** switch the discovery query to directed-only VLE for asymmetric types. It compiles in AGE 1.5, but it would drop the surprising "reached from the object side" paths that are the whole point, and it complicates the staged-probe engine. Directed VLE is worth keeping in the back pocket only for a future *typed* query mode (e.g. "supply-chain downstream of X"), not for general weird-connection discovery.

### Effort / risk

- Parser + `RawPath` + DTO + render changes: contained to `graph_path_engine.py`, `cypher_path.py`, `ports/graph_path_engine.py`, `domain/entities/path_insight.py`, `application/schemas/paths.py`, `path_explanation_service.py`, plus one frontend component. No migration, no AGE feature dependency, forward-compatible schema additions only.
- Re-running `path_insight` precompute would re-render existing insights with correct direction (explanations are regenerated; the stored `relation_id`s already let a backfill recompute direction without re-traversing).
