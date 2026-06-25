# FR-11 — Duplicate Canonical Entities Investigation (ticker-less / name-based residue)

- **Date:** 2026-06-13
- **Branch:** `feat/frontend-enhancement-sprint`
- **Scope:** READ-ONLY investigation. No code/data/schema/git changes were made.
- **Trigger:** PLAN-0112 pairwise pathfinding hit a "connected but no reportable path" case for SpaceX; NVIDIA appears ≥3×, Meta/Microsoft 2×.
- **Coordination:** A concurrent Claude session has ALREADY shipped the **ticker-based** dedup (BP-459 Phase 3). This report covers ONLY what remains after that work: **ticker-less / name-based** duplicates.

---

## 0. TL;DR

The parallel session's ticker work is **committed and effective** — exact same-ticker `financial_instrument` duplicates are gone (live `GROUP BY ticker HAVING count(*)>1` would now return ~0). What remains is a **different, larger class**: semantic duplicates that share **no ticker** and **no exact name**, so neither the ticker-unique index (migration 0051) nor the existing `lower(canonical_name)` unique index (migration 0026) nor the 0.75 trigram fuzzy pre-lookup catches them.

The naïve detector `GROUP BY lower(canonical_name) HAVING count(*)>1` reports only **2 groups / 4 excess rows** platform-wide — this badly *understates* the problem because every real duplicate has a *slightly different surface string* (e.g. `SpaceX`, `SpaceX shares`, `SpaceX stock`, `SpaceX Class A common stock`). The true residual is in the **6,235 ticker-less `financial_instrument`** rows (plus 4,502 `person`, 1,896 `unknown`), none of which any current guard dedups.

**Recommended:** a sibling `scripts/data/merge_name_duplicates.py` that reuses the committed `_merge_cluster` repoint engine, driven by a conservative alias-trigram + same-entity_type cluster rule, run `--dry-run` first; plus a prevention patch lowering the SpaceX-class miss in `persist_enrichment`. Sequence AFTER the parallel session's files land to avoid collision.

---

## 1. Current duplicate landscape (post-ticker-dedup)

### 1a. Naïve exact-name detector (the one in BP-459) — almost nothing left
```sql
SELECT lower(canonical_name), entity_type, count(*) FROM canonical_entities
GROUP BY 1,2 HAVING count(*)>1 ORDER BY count(*) DESC;
```
| name | entity_type | count |
|---|---|---|
| berkshire hathaway inc | financial_instrument | 4 |
| brown-forman corporation | financial_instrument | 2 |

**2 groups, 6 rows, 4 excess.** All have tickers — these are residual ticker clusters the merge either skipped or that re-appeared; minor. **This detector is the wrong instrument** for the FR-11 problem because real dups don't share an exact lowercased name.

### 1b. The real residual pool (ticker-less, no exact-name overlap)
```sql
SELECT entity_type, count(*) FILTER (WHERE ticker IS NULL) ticker_less, ... FROM canonical_entities GROUP BY 1;
```
| entity_type | ticker_less | with_ticker | total |
|---|---|---|---|
| financial_instrument | **6,235** | 2,185 | 8,420 |
| person | **4,502** | 0 | 4,502 |
| unknown | **1,896** | 1 | 1,897 |
| place | 1,398 | 0 | 1,398 |
| index | 220 | 8 | 228 |
| product | 156 | 1 | 157 |
| currency | 89 | 4 | 93 |
| (others) | … | | |

The **6,235 ticker-less financial_instrument** rows are the SpaceX-class blast zone: private companies, "X shares" / "X stock" news fragments, subsidiaries, ETFs without a resolved ticker. None are protected by migration 0051's `UNIQUE(ticker) WHERE entity_type='financial_instrument'` (NULL ticker ⇒ not in the partial index).

---

## 2. The SpaceX case (root cause of the PLAN-0112 "connected but no path")

All SpaceX-family canonical rows (`canonical_name ILIKE '%spacex%' OR '%space exploration%'`):

| entity_id | canonical_name | entity_type | ticker | degree | created_at |
|---|---|---|---|---|---|
| **9ecb9bad…2d137f1b** | **SpaceX** | financial_instrument | — | **96** | 2026-05-23 19:43 |
| 727a2791…a4599d3 | SpaceXAI | financial_instrument | — | 1 | 2026-05-23 19:55 |
| 62316375…6 5ca65d | SpaceXâ | financial_instrument | — | 0 | 2026-05-23 20:36 |
| a394450d…3bea3c48 | ARK Space Exploration & Innovation ETF | financial_instrument | — | 0 | 2026-06-11 |
| aa205ab0…0357f48efe | SpaceX Starlink | product | — | 0 | 2026-06-12 |
| 8423e28e…66189ca9 | SpaceX shares | financial_instrument | — | 0 | 2026-06-12 |
| 8dc8acb2…2daf6a5ee | SpaceX stock | financial_instrument | — | 0 | 2026-06-13 |
| 7ef56458…1a2f46fc | SpaceX Class A common stock | financial_instrument | — | 0 | 2026-06-13 |

**Why there are ≥2:** every row is **ticker-less** (SpaceX is private), so:
- The **ticker pre-lookup** (`find_by_ticker`) in `persist_enrichment` never fires (`ticker is None`).
- The **`lower(canonical_name)` unique index** (migration 0026) is partial: `WHERE entity_type != 'financial_instrument'` — it *excludes financial_instrument entirely*, so two FI rows never conflict on name even if the name matched exactly.
- The **0.75 trigram fuzzy pre-lookup** misses because the surface strings are below threshold. Measured against `'spacex'`:

| variant | similarity('spacex', …) | ≥0.75? |
|---|---|---|
| spacexâ | 0.667 | no |
| spacexai | 0.60 | no |
| spacex stock | 0.583 | no |
| spacex shares | 0.538 | no |
| spacex class a common stock | 0.269 | no |
| space exploration technologies corp | 0.132 | no |

So each news mention of "SpaceX shares" / "SpaceX stock" / "SpaceXAI" minted a **fresh** canonical.

**Minting path of each:** all are **news/provisional** path (`provisional_enrichment_core.persist_enrichment`) — none are instrument-seeded (no row is anchored on a `market_data.instruments.id`; all have NULL ticker, and the seed path requires a ticker). The bad-encoding `SpaceXâ` / `SpaceXAI` are GLiNER span-boundary artifacts that were never deduped.

**Why PLAN-0112 saw "connected but no reportable path":** the graph is **fragmented across the cluster**. The real hub `SpaceX` (degree 96) holds the meaningful edges, but `SpaceXAI` (degree 1) carries a *separate* edge from NVIDIA (`01900000…1006 → 727a2791…`). A pairwise query that resolves one endpoint to the **wrong** SpaceX vertex (e.g. `SpaceXAI`, or a degree-0 `SpaceX shares`) finds the two nodes "connected" in the canonical set but cannot trace a real path through the degree-0/degree-1 satellite — the edges live on the *other* vertex. This is the FR-11 symptom: dedup would collapse the satellites into the degree-96 hub and the path appears.

---

## 3. Root cause for ticker-LESS dups (minting-path trace)

Canonical entities are minted in exactly two places:

1. **Instrument-seeding** — `infrastructure/messaging/consumers/instrument_consumer.py` → `CanonicalEntityRepository.create()`. Requires a ticker (M-017: `entity_id == instruments.id`). **Irrelevant to ticker-less dups.** The parallel session added `instrument_consumer_ticker_dup_detected` here.

2. **News/provisional promotion** — `infrastructure/workers/provisional_enrichment_core.py::persist_enrichment` (shared by the polling `ProvisionalEnrichmentWorker` and the hot-path `ProvisionalQueuedConsumer`). The guard ladder, in order:
   1. **M-017 S2 anchoring** (`provisional_enrichment_core.py:298`) — only if `market_data_lookup` set AND `entity_type=='financial_instrument'` AND `ticker`. → **skipped for ticker-less**.
   2. **Ticker-equality pre-lookup** (`:376`, parallel session's BP-459 fix, `find_by_ticker`) — guarded by `entity_type=='financial_instrument' and ticker`. → **skipped for ticker-less**.
   3. **Trigram fuzzy pre-lookup** (`:407`) — `EntityAliasRepository.fuzzy_search(name, limit=3)`, reuse iff `similarity ≥ 0.75`. → **the only guard that runs for ticker-less, and it misses the SpaceX class** (§2 table).
   4. **`create_or_get` ON CONFLICT** (`:443`) — atomic on the `lower(canonical_name)` unique index, which is **partial (excludes financial_instrument)** — so for FI rows it never conflicts on name.

**Net:** for a ticker-less `financial_instrument` (or `person`/`unknown`), the **only** active dedup is the 0.75 trigram, and it fails on:
- suffix/word-addition variants ("SpaceX" → "SpaceX shares/stock/Class A common stock"),
- encoding artifacts ("SpaceX" → "SpaceXâ", GLiNER span bleed),
- abbreviation vs legal name ("SpaceX" vs "Space Exploration Technologies Corp", sim 0.13),
- type splits ("SpaceX Starlink" minted as `product`, not even compared because it's a different name *and* type).

`class_aware_canonical_match()` exists in `nlp-pipeline/.../blocks/entity_resolution.py` and `infrastructure/.../repositories/entity_alias.py` but, as BP-459 already notes, **is never called during S7 provisional enrichment** — it's S8/NLP-side only.

---

## 4. Blast radius

For the SpaceX cluster specifically (counts from `relation_evidence_raw`):
- The hub `SpaceX` (9ecb9bad) has **~88 distinct edge endpoints** and degree 96 — healthy.
- `SpaceXAI` (727a2791) — **1 edge** (NVIDIA→SpaceXAI). Lost to the hub.
- `SpaceXâ`, `SpaceX shares`, `SpaceX stock`, `SpaceX Class A common stock`, `SpaceX Starlink`, `ARK … ETF` — **degree 0** noise vertices.

What breaks if unfixed:
- **Graph fragmentation** — meaningful edges scatter across satellite vertices (NVIDIA↔SpaceXAI orphaned from the SpaceX hub).
- **Pairwise contract violation** (PLAN-0112) — "connected but no reportable path" whenever resolution lands on a satellite.
- **Duplicate search/dossier results** — multiple "SpaceX" hits in entity search; thin dossiers on the degree-0 twins (same family as BP-661's phantom-twin resolver problem).
- **Weird-connections feed pollution** — degree-0/1 satellites with one odd edge surface as spurious "weird" links.
- **Self-loops on merge** — if later merged carelessly, NVIDIA→SpaceXAI and NVIDIA→SpaceX collapse to a duplicate edge (the merge engine already drops self-loops/dedups, see §5).

Platform-wide, the residual pool (§1b) means thousands of ticker-less FI/person/unknown rows are at risk, though the *high-degree* fragmentation (the part that actually hurts pathfinding) is concentrated in a smaller set of well-known private/large entities.

---

## 5. Recommended fix (DO NOT APPLY — sequenced plan)

### What the parallel session already covers (do NOT duplicate)
- Migration **0051** — `UNIQUE(ticker) WHERE entity_type='financial_instrument'` (commit `21d69a110`). Ticker hard-dedup at DB level.
- `persist_enrichment` **ticker pre-lookup** + `instrument_consumer` **dup detection** (commit `c3f7ee28e`).
- **`scripts/data/merge_ticker_duplicates.py`** + its test (merged 591 ticker dups). This script contains the reusable **`_merge_cluster`** repoint engine covering: `relation_evidence_raw` (subj/obj), `relations` (partitioned, self-loop + collision safe), `claims`, `events`, `event_entities`, `entity_event_exposures`, `entity_narrative_versions`, `path_insights.anchor_entity_id`, `path_insight_jobs` (active-unique safe), `llm_usage_log`, `ticker_aliases`, `entity_aliases` (move+dedup), and `nlp_db.entity_mentions.resolved_entity_id`.

### What we add (the name/ticker-less class)

**A. One-off merge — `scripts/data/merge_name_duplicates.py` (sibling, NOT an edit of the ticker script).**
   - **Reuse, don't fork:** import/extract `_merge_cluster`, `_INTEL_REPOINTS`, `_NLP_DSN`/`_INTEL_DSN`/`_MARKET_DSN` from the ticker script (or refactor them into a shared `_merge_common.py` — see collision note). The repoint surface is identical; only **clustering** differs.
   - **Clustering rule (conservative, to avoid bad merges):** within the **same `entity_type`** and **ticker IS NULL** (or both NULL), cluster by alias-trigram. Concretely, for each candidate, gather `entity_aliases` (EXACT type) and compute `similarity(normalized_alias_text, …)`; treat as same entity iff a high threshold is met. Recommend **two tiers**:
     - *Auto-merge tier* `sim ≥ 0.92` AND same entity_type AND token-superset relationship (one name's tokens ⊂ other's, e.g. "SpaceX" ⊂ "SpaceX shares") — high precision.
     - *Review tier* `0.80 ≤ sim < 0.92` — emit to a `--report` CSV for human confirmation; do not auto-merge (avoids "Brown-Forman" vs "Brown & Brown" type errors).
   - **Survivor rule (mirror ticker script, adapted):** highest `node_degree.degree` wins (the real hub), tie-break oldest `created_at`. For SpaceX this correctly picks 9ecb9bad (degree 96).
   - **Cross-type guard:** never merge across `entity_type` (so "SpaceX Starlink" the *product* is NOT auto-merged into SpaceX the *instrument* — flag for review instead).
   - **Encoding-artifact pre-pass:** rows whose name fails a clean-UTF8 / mojibake check ("SpaceXâ", "Nvidiaâ", "SpaceXAI") with degree ≤1 and a high-degree clean sibling → safe auto-merge candidates.
   - **Always `--dry-run` first**, per-cluster row-count report, same one-transaction-per-connection pattern as the ticker script.

**B. Prevention patch — close the SpaceX miss in `persist_enrichment`.** Options (pick one, smallest first):
   1. **Token-superset fallback** after the 0.75 trigram miss: if the candidate name is the fuzzy match's name plus generic finance suffixes (`shares|stock|class [a-z] common stock|adr|equity|holdings`) strip them and re-test exact-alias match. Catches "SpaceX shares"→"SpaceX" with zero new infra.
   2. **Lower the fuzzy threshold for token-subset cases only** (not globally — 0.75→lower across the board would cause false merges).
   3. **Call `class_aware_canonical_match()` in S7** (the original BP-459 recommendation #2, still open) — broadest fix but largest blast radius; gate behind the same-entity_type constraint.
   - Also: make the **`lower(canonical_name)` unique index unconditional** (drop the `WHERE entity_type != 'financial_instrument'` predicate from migration 0026) so two *exact-name* FI rows ("berkshire hathaway inc" ×4) can no longer co-exist. **This is now safe only after the ticker merge** removed same-ticker FI dups; verify zero exact-name FI dups before adding (currently 2 groups remain — must merge those first or the index creation fails).

### Collision flags with the in-flight parallel session
- **`scripts/data/merge_ticker_duplicates.py`** — if we refactor shared helpers (`_merge_cluster`, DSNs, `_INTEL_REPOINTS`) into `_merge_common.py`, we **edit a file the parallel session owns**. **Sequence AFTER their work is committed/landed**; until then, keep `merge_name_duplicates.py` self-contained (copy the engine) and refactor later. Flag explicitly: do NOT touch the ticker script while the sibling session is active.
- **`provisional_enrichment_core.py::persist_enrichment`** — the parallel session edited this (ticker pre-lookup at `:376`). Our prevention patch (token-superset fallback) inserts AFTER the fuzzy block (`:425`). **Coordinate to avoid an overlapping diff** in the same function — apply ours only once their ticker pre-lookup is merged, and place it as a distinct block below `:429`.
- **Migration numbering** — next free intel migration after **0052** (PLAN-0112 `node_degree`/weirdness) is **0053**. If we add the unconditional-name-index migration, use **0053** (0051=ticker-unique, 0052=node_degree). Confirm no parallel session has reserved 0053.

### Suggested execution order
1. Wait for parallel session's ticker files to land (avoid script/`persist_enrichment` collision).
2. Build `merge_name_duplicates.py` (self-contained engine copy) + `--dry-run` report; review the 0.80–0.92 tier manually.
3. Run encoding-artifact + token-superset auto-merge tier; spot-check SpaceX collapses to 9ecb9bad with degree intact.
4. Add prevention patch (token-superset fallback) to `persist_enrichment`, with a regression test (news "SpaceX shares" reuses existing "SpaceX").
5. Merge the 2 residual exact-name FI clusters, then add migration **0053** making the name unique index unconditional.
6. Update BP-459 (append the ticker-less/name resolution) + `docs/services/knowledge-graph.md`.

---

## Appendix — key file references
- `services/knowledge-graph/src/knowledge_graph/infrastructure/workers/provisional_enrichment_core.py` — `persist_enrichment` guard ladder (M-017 :298, ticker pre-lookup :376, fuzzy :407, create_or_get :443).
- `services/knowledge-graph/src/knowledge_graph/infrastructure/messaging/consumers/instrument_consumer.py` — instrument-seed minting path.
- `scripts/data/merge_ticker_duplicates.py` — reusable `_merge_cluster` repoint engine (`_INTEL_REPOINTS` :76, `_choose_survivor` :131, nlp repoint :449).
- `services/intelligence-migrations/alembic/versions/0026_add_canonical_entities_dedup_index.py` — partial name unique index (the FI-excluding predicate to drop).
- `services/intelligence-migrations/alembic/versions/0051_unique_ticker_financial_instrument.py` — ticker-unique (parallel session).
- `docs/BUG_PATTERNS.md` BP-459 + `docs/bug-patterns/database-orm.md:1458`.
