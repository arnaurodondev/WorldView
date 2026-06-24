# KG Edge Count Investigation — Is "629 edges" Implausibly Sparse?

**Date:** 2026-06-13
**Author:** investigation (read-only)
**Scope:** `intelligence_db.relations` / `relation_evidence_raw` / `canonical_entities` and the Apache AGE shadow graph `worldview_graph`, vs the snapshot reported in `thesis/chapters/05-evaluation.typ` §5.2.
**Status:** Root cause confirmed. NO code / schema / data / git changes made — all measurements taken read-only via `docker exec worldview-postgres-1 psql -U postgres -d intelligence_db`.

> **CORRECTION (2026-06-13, superseded on provenance):** This report's characterisation of the isolated-entity cohort as "bulk-seeded reference entities (instruments/persons/places)" is **wrong**. The deeper follow-up `2026-06-13-kg-entity-edge-ratio-deepdive.md` shows only **~4%** of entities trace to instrument seeding; **~95% are NER-extracted** from articles. The high entity:edge ratio is mostly expected sparse narration over a large *NLP-generated* vocabulary, **plus a real relation-under-extraction gap** (~4,026 article-anchored entities with zero relation, 3,288 of them never in any evidence row). The edge-count root cause (stale pre-BP-662 snapshot) and the 1,633-edge materialization gap (now BP-694) stand.

---

## 1. Executive summary

The thesis §5.2 snapshot of **629 graph edges** is **not a materialization bug and not implausible — it is a STALE snapshot taken while the BP-662 FK-crash bug was actively suppressing edge materialization.** The "629" figure is the `public.relations` row count captured before the 2026-06-11 BP-662 fix; the thesis then equates "629 stored relations" with "629 graph edges" (correct — relations *are* the edges).

The same query run today returns a graph that is **~7.5× larger** than the snapshot, because the entire snapshot (articles, OHLCV, entities, relations) predates roughly three weeks of ingestion **and** the 2026-06-11/12 BP-662 fix that unblocked a backlog of relations the crashing transaction had been throwing away.

| Metric | Thesis §5.2 snapshot | Live (2026-06-13) |
|---|---|---|
| Articles | 13,907 | (grown; not re-measured) |
| Canonical entities | 5,503 | **16,738** |
| **Graph edges (canonical relations)** | **629** | **4,750** |
| Article-level relation-evidence rows | 6,944 | **76,869** |
| OHLCV bars | 212,428 | **551,493** |

The graph is **not** sparse-by-bug. AGE and `relations` are currently **in sync** (the FR-13 phantom-orphan problem documented earlier the same day has since been reconciled — see §5). There is a small *residual* materialization gap (~1,633 edges that should exist but don't), described in §6, which is a real BP-662-family follow-up but does **not** explain the headline 629.

**Recommendation (one line):** the thesis number is stale; re-snapshot and report the current high-confidence edge count (4,750), OR keep 629 but explicitly frame it as an early-corpus snapshot. Either way, fix the misleading "0.11 edges/node" intuition (§7).

---

## 2. The three key counts (exact, live)

| # | Quantity | SQL source | Count |
|---|---|---|---|
| 1 | **Raw relation evidence** (`relation_evidence_raw`, S6 output) | `SELECT count(*) FROM relation_evidence_raw` | **76,869** |
| 2 | **Canonical relations** (`relations`, S7 — the edges) | `SELECT count(*) FROM relations` | **4,750** |
| 3 | **Materialized AGE edges** (`worldview_graph`) | `cypher('worldview_graph', $$ MATCH ()-[r]->() RETURN count(r) $$)` | **5,298** |

Supporting:

* `canonical_entities`: **16,738** (snapshot said 5,503).
* `relation_evidence_raw` flagged `entity_provisional=true`: **4,834** (still-deferred raw rows whose endpoint isn't canonical).
* AGE edge total via `_ag_label_edge` (exact): **5,298** — matches the Cypher count.

### 2.1 Reconciling AGE 5,298 vs relations 4,750

The 548-edge difference is **membership edges that carry no `relation_id`** (they are not `relations` rows by design):

```
LOAD 'age'; SET search_path = ag_catalog, public;
WITH ag AS (SELECT (agtype_access_operator(e.properties,'"relation_id"'::agtype))::text rid_raw
            FROM worldview_graph._ag_label_edge e),
     parsed AS (SELECT NULLIF(trim(both '"' from rid_raw),'null') rid FROM ag)
SELECT count(*) total, count(*) FILTER (WHERE rid IS NOT NULL) with_rid,
       count(*) FILTER (WHERE rid IS NULL) without_rid,
       count(*) FILTER (WHERE rid IS NOT NULL AND rid::uuid IN (SELECT relation_id FROM relations)) healthy,
       count(*) FILTER (WHERE rid IS NOT NULL AND rid::uuid NOT IN (SELECT relation_id FROM relations)) orphan
FROM parsed;
-- total=5298  with_rid=4750  without_rid=548  healthy=4750  orphan=0
```

* **4,750** AGE edges carry a `relation_id` and **all 4,750 join a live `relations` row (orphans = 0).**
* **548** AGE edges carry no `relation_id` → membership edges (`EVENT_EXPOSES` 547 + 1). These are entity↔temporal-event links, intentionally not in `relations`.

So **"629" measures the `relations` table** (= canonical graph edges). AGE today holds exactly those 4,750 plus 548 membership edges. No orphan/phantom skew remains.

> Note: the FR-13 audit from earlier today (`2026-06-13-fr13-age-relations-sync-gap-investigation.md`) reported 9,980 total / 4,662 orphan edges, but those figures were derived from stale `pg_class.reltuples` estimates (it cites `EVENT_EXPOSES=579`, `EXPOSED_TO_THEME=26`; exact live counts are 547 and 0). Exact `_ag_label_edge` counting shows 5,298 edges and **zero** orphans — the reconcile has since run (or the estimates were never accurate). Live exact counts supersede the estimate-based numbers.

---

## 3. Where the thesis "629" comes from

§5.2 says (verbatim): *"the platform held … 629 graph edges …"* and §6 conclusions say *"All 629 stored relations saturate the [0.9,1.0] bin."* The thesis uses **"629 graph edges" = "629 stored relations" interchangeably** — which is correct: a `relations` row *is* a graph edge. The probe that produced the snapshot counted `relations`, not AGE.

`thesis/plans/REVISION-PLAN.md:284` records the same number as an O-3 outcome ("629 edges materialised"). The number is internally consistent in the thesis; it is simply **a `relations`-table snapshot from before 2026-06-11**.

### 3.1 The snapshot is stale — proof from the creation timeline

```
SELECT date_trunc('day', created_at)::date, count(*) FROM relations GROUP BY 1 ORDER BY 1;
2026-05-24 | 227
2026-05-25 |  68
2026-05-28 |  15
2026-05-29 |   1   -- ← cumulative ~311 here; graph was stuck
2026-06-11 | 2139  -- ← BP-662 fix lands: backlog unblocks
2026-06-12 | 2295
2026-06-13 |   5
```

Before 2026-06-11 the `relations` table held only a few hundred rows and was **not growing** despite evidence pouring in (76k raw evidence rows) — the classic BP-662 symptom: *"278 evidence rows/hr, 0 edges, relations stuck."* The 629 snapshot was taken in that window. The two big bars on 6/11 and 6/12 are the BP-662 fix (entity-existence gate + `_unblock_provisional_evidence` edge materialization) draining the backlog. Every other corpus count in the snapshot is correspondingly stale (entities 5,503→16,738; OHLCV 212,428→551,493).

---

## 4. The funnel (raw evidence → canonical edges), quantified

```
relation_evidence_raw rows ............................. 76,869
  └─ entity_provisional = false (both endpoints resolved) 72,035
       └─ DISTINCT (subj, type, obj) triples ............ 12,014   (all)
             └─ DISTINCT triples among resolved evidence . 7,340
                   └─ both endpoints currently canonical .. 7,340   (100%)
                         └─ materialized as relations ..... 4,750   ← edges
```

Drop accounting from 7,340 distinct resolved triples to 4,750 edges (2,590 gap):

| Reason triple has evidence but no `relations` row | Count |
|---|---|
| **Self-loops** (subject = object) — dropped by design (BP-384/385) | **957** |
| **Non-self-loop, both endpoints now canonical, evidence `processed=true`, no edge** | **1,633** |

The confidence gate (§4.4, ~0.9) drops **nothing**: all 4,750 relations have `confidence ≥ 0.9` (avg **0.996**, min 0.9). The extractor saturates near 0.95, so the gate is never the binding constraint — consistent with the thesis's own §5.3/§6 calibration caveat. The aggregation ratio is real: **8.19 evidence rows per edge** (sum `evidence_count` 38,891 / 4,750), close to the snapshot's "11 per edge" (lower now because newer edges have fewer corroborating articles yet).

---

## 5. Hypothesis verdicts

| Hyp | Statement | Verdict | Evidence |
|---|---|---|---|
| **H1** | Expected funnel: confidence + existence + dedup legitimately collapse 6,944 raw → a few hundred edges | **PARTIAL — and irrelevant to the headline** | The funnel is real (76,869 raw → 12,014 distinct triples → 4,750 edges) but the *confidence* gate drops 0 (all edges ≥0.9). The collapse is dedup/aggregation (8.19 ev/edge) + self-loop removal, not confidence. This does not explain 629. |
| **H2** | AGE sync gap: relations exist in the table but were never materialized into AGE (under-reporting) | **REJECTED** | AGE holds all 4,750 relation-bearing edges (orphans=0); reverse gap is 74 rows, all `updated_at` 6/11–6/12 = normal 15-min watermark lag, self-healing. AGE is *complete*, not deficient. |
| **H3** | Entity-existence/FK gate over-drops edges whose endpoint wasn't canonical at materialization time and was never back-filled | **CONFIRMED (residual, ~1,633 edges)** | 1,633 non-self-loop resolved triples have `processed=true` evidence but no edge. Sampled cases: subject entity `created_at` (e.g. 2026-06-06, 2026-05-11) is *after* the evidence `processed_at` (2026-05-24) → entity-existence gate skipped the upsert and marked evidence processed; `_unblock_provisional_evidence` only re-fires for `entity_provisional=true` rows, so these (flag already false) were never re-materialized. This is a genuine BP-662-family residual, but small. |
| **H4** | Large provisional/blocked backlog never promoted | **PARTIAL** | 4,834 `relation_evidence_raw` rows still `entity_provisional=true` (endpoint not canonical) — a legitimate deferred backlog, not stuck edges. These correctly do *not* count as edges yet. |

**Decisive answer:** 629 is **not** the complete set of legitimate edges *today* — but only because it is a stale snapshot. There is **no materialization bug inflating the gap between `relations` and AGE** (H2 rejected). The real current edge count is **4,750** (canonical relations) / **5,298** (AGE incl. membership). A small residual ~1,633-edge BP-662 back-fill gap exists (H3) but is a follow-up, not the cause of the headline number.

---

## 6. The residual gap (H3) — BP-662 follow-up candidate

1,633 non-self-loop triples have fully-resolved, `processed=true` evidence with both endpoints canonical, yet no `relations` row. Mechanism:

1. Evidence processed while one endpoint was **not yet canonical** → BP-662 entity-existence gate skips `relation_repo.upsert`, writes/keeps the evidence row, marks it `processed=true`.
2. Endpoint later becomes canonical (instrument discovery, dedup, enrichment).
3. `_unblock_provisional_evidence` (the back-fill path) only materializes rows still flagged `entity_provisional=true`. These rows have `entity_provisional=false` (they were "resolved" all along — the *gate* failure was endpoint-existence, not provisional-flag), so the unblock path never revisits them.

Top missing types: `listed_on` 289, `operates_in_country` 267, `is_in_sector` 201, `competes_with` 193, `partner_of` 153, `has_executive` 108. These are exactly the structured/sector membership relations whose object entities (sectors, exchanges, countries) or subjects (newly-discovered instruments) lag the evidence.

**Suggested BUG_PATTERNS candidate (NOT filed here):** the BP-662 back-fill (`_unblock_provisional_evidence`) keys on `entity_provisional=true`, missing the cohort whose upsert was skipped purely by the *entity-existence gate* (flag never set true). A periodic reconciler should re-materialize any `relation_evidence_raw` triple where both endpoints are now canonical and no `relations` row exists — independent of the provisional flag. Estimated recoverable edges: ~1,633 (→ relations ≈ 6,383).

---

## 7. Recommendation for the THESIS

**Adopt option (a) corrected, with a re-snapshot — this is NOT a materialization bug, so the number simply needs refreshing and framing.**

1. **Re-snapshot the corpus.** The entire §5.2 snapshot (13,907 articles / 5,503 entities / 629 edges / 6,944 evidence / 212,428 bars) predates the BP-662 fix and ~3 weeks of ingestion. Re-run the pipeline-metrics probe and report the post-fix figures. Current edges = **4,750** (canonical relations) / **5,298** AGE (incl. 548 membership edges); raw evidence = **76,869**; entities = **16,738**; OHLCV = **551,493**.
   * If a re-snapshot is impractical before submission, **keep 629 but add one sentence**: *"Snapshot taken on the early seeded corpus, before the relation-materialization fix of 2026-06; the post-fix graph holds ≈4,750 high-confidence edges."*

2. **Re-frame "629 graph edges" as "high-confidence canonical edges after the confidence + entity-existence gates,"** and **drop / fix the "0.11 edges/node" intuition.** That ratio is misleading because the denominator (entities) includes a large isolated cohort by design:
   * Live: **2,166 / 16,738 entities (12.9%) participate in ≥1 edge; 14,572 (87.1%) are isolated.** Isolated entities are overwhelmingly bulk-seeded `financial_instrument` (7,949), `person` (4,505), `place` (1,404) and `unknown` (2,024) rows created from instrument/EODHD ingestion that have no *extracted* relation yet. The KG is intentionally a sparse overlay of *narrated* relationships on top of a dense reference universe, not a fully-connected graph. Density should be quoted over the **connected sub-graph** (2,166 nodes / 4,750 edges ≈ **2.2 edges/participating node**), not the whole entity table.

3. **The "≈11 evidence rows per edge" and "≈8.7 entities per relation" ratios are sound in mechanism** but will shift on re-snapshot (live: 8.19 ev/edge). Keep the cross-document-aggregation argument; refresh the numbers.

4. **O-3 verdict is safe.** The graph mechanism (per-edge confidence, temporal decay, AGE materialization) is fully operational and AGE↔relations are in sync; only the *snapshot magnitude* and the *edges/node framing* need correction. The PARTIAL-on-calibration caveat (extractor saturates at 0.95) remains correct and is independent of the count.

---

## 8. Appendix — exact queries used

```sql
-- Core counts (intelligence_db)
SELECT 'canonical_entities', count(*) FROM canonical_entities
UNION ALL SELECT 'relations_total', count(*) FROM relations
UNION ALL SELECT 'relation_evidence_raw', count(*) FROM relation_evidence_raw
UNION ALL SELECT 'rev_raw_provisional', count(*) FROM relation_evidence_raw WHERE entity_provisional;
-- 16738 / 4750 / 76869 / 4834

-- AGE materialized edges
LOAD 'age'; SET search_path = ag_catalog, public;
SELECT * FROM cypher('worldview_graph', $$ MATCH ()-[r]->() RETURN count(r) $$) AS (c agtype);  -- 5298
SELECT count(*) FROM worldview_graph._ag_label_edge;                                            -- 5298

-- Confidence: all relations ≥ 0.9
SELECT count(*) FILTER (WHERE confidence>=0.9), round(avg(confidence)::numeric,3),
       round(avg(evidence_count)::numeric,2) FROM relations;  -- 4750 / 0.996 / 8.19

-- Participating vs isolated entities
WITH p AS (SELECT subject_entity_id e FROM relations UNION SELECT object_entity_id FROM relations)
SELECT (SELECT count(*) FROM canonical_entities),
       (SELECT count(*) FROM p WHERE e IN (SELECT entity_id FROM canonical_entities));
-- 16738 total / 2166 participating  → 14572 isolated (87.1%)

-- Funnel + residual gap (see §4, §6)
```
