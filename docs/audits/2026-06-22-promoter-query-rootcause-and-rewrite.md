# RelationEvidencePromoterWorker (Worker 13B) — Query Root-Cause & Semantics-Preserving Rewrite

**Date:** 2026-06-22
**Scope:** READ-ONLY investigation (EXPLAIN no-ANALYZE, SELECT/pg_stat, code + git). No DDL/DML applied.
**Target:** `services/knowledge-graph/src/knowledge_graph/infrastructure/workers/relation_evidence_promoter.py`
**DB:** `intelligence_db` (container `worldview-postgres-intelligence-1`, host port 5433)

> **Hard constraint honored throughout:** the rewrite MUST preserve the exact promotion set. `relation_evidence_raw.processed` is owned by the ConfidenceWorker (`confidence.py:223`), NOT the promoter; the promoter dedups via a `NOT EXISTS` anti-join against `relation_evidence`. **No proposal below filters on `processed`, drops, or adds a single promoted row.**

---

## 0. TL;DR

| Item | Finding | Recommendation |
|------|---------|----------------|
| `_FETCH_SQL` cost | **1,128,047** | Rewrite to CTE-precomputed density → **~35,700 (32×)** |
| `_COUNT_GATED_QUALITY_SQL` cost | **1,127,636** | **Fold into `_FETCH_SQL` pass** (preferred) OR drop cadence to hourly |
| Real cost driver | NOT the density subquery in isolation, and NOT a missing index. It is the **join shape**: the planner reads ALL of `relations` (13,455 rows, 8-partition seq-scan) and probes `relation_evidence_raw` once per relation via a Memoize node priced at 353/probe. | Precompute density once per cycle; drive the plan so the per-row correlated subquery disappears. |
| Missing triple index on p0,p2–p6 (prior audit claim) | **REFUTED.** All 8 partitions currently have `relations_pN_subject_entity_id_canonical_type_object_entity_idx`. | No index DDL strictly required. Optional: refresh stale `relations` stats (`n_live_tup=0`). See §4. |

---

## 1. EXPLAIN evidence + cost driver

### 1.1 `_FETCH_SQL` — top of plan (full plan captured during investigation)

```
Limit  (cost=1128047.40..1128047.60 rows=79)
  Sort  Sort Key: rer.extracted_at
    Nested Loop Anti Join  (cost=0.43..1128044.91 rows=79)
      Join Filter: (re.relation_id = r.relation_id)
      Nested Loop  (cost=0.43..1127553.42 rows=180)
        ->  Append  (cost=0.00..793.82 rows=13455)          -- ALL of relations
              Seq Scan on relations_p0 ... p7                -- 8× seq scan, 13,455 rows
        ->  Memoize  (cost=0.43..353.37 rows=1)             -- executed ~13,455×
              Cache Key: r.subject_entity_id, r.object_entity_id, r.canonical_type
              ->  Index Scan using idx_raw_evidence_triple on relation_evidence_raw rer (cost=0.42..353.36)
                    Filter: (... OR ((SubPlan 1)/(NULLIF(SubPlan 2,0)) >= 0.05))
                    SubPlan 1  Aggregate (Index Only Scan idx_raw_evidence_triple)        -- numerator, cheap
                    SubPlan 2  Aggregate (Sort -> Bitmap Heap Scan, BitmapOr) cost 343.30  -- DENSITY denominator
```

**Diagnosis.** `1127553 ≈ 13455 × 353.37 × (Memoize cache-miss fraction)`. The planner:
1. Reads the **entire** `relations` table (no WHERE predicate on `relations`) → 8-partition Append seq-scan, 13,455 rows. The per-partition triple indexes are present but *not used* because the whole table is consumed (a full index-only scan would not be cheaper than seq-scan, and stats are stale — §4).
2. For each relation row, probes `relation_evidence_raw` via `idx_raw_evidence_triple`, and inside that probe evaluates the **density denominator SubPlan 2** (`Sort → Bitmap Heap Scan → BitmapOr` of `idx_raw_evidence_triple` + `idx_raw_evidence_object`), priced at **343** per distinct triple.

So the cost is the product of "scan all relations" × "per-row correlated density subquery". The density subquery alone is cheap (343); multiplied across the candidate space it dominates.

### 1.2 `_COUNT_GATED_QUALITY_SQL` — top of plan

```
Aggregate  (cost=1127635.50..1127635.51)
  Nested Loop Anti Join  (cost=0.43..1127635.50)
    Nested Loop  (cost=0.43..1127553.42)        -- IDENTICAL inner shape to _FETCH_SQL
      ->  Append rows=13455  (8× Seq Scan relations_p0..p7)
      ->  Memoize cost=353.37  (Index Scan idx_raw_evidence_triple)
            SubPlan 1 numerator / SubPlan 2 density denominator (Sort->BitmapOr) cost 343.30
    ->  Append ... SubPlan 3 (correlated relation_id lookup per evidence partition)
```

**This query scans the *same* candidate space as `_FETCH_SQL`** (same 13,455-row Append, same Memoized density SubPlan) and is purely diagnostic (its own comment: "does not affect promotion logic" — emits the `gated_quality` log field + `kg_evidence_quality_gated_total` counter). It costs **1.127M every 5 min for a metric**, and is structurally redundant with `_FETCH_SQL`.

### 1.3 Supporting facts (gentle SELECTs)

| Fact | Value |
|------|-------|
| `relation_evidence_raw` est. rows | 95,059 (95,200 live) |
| `relations` est. rows | 13,433 (8 partitions ~1.5–1.8k each) |
| `relation_evidence` est. rows | 119,564 |
| Non-provisional raw rows | 82,502 |
| **Distinct non-provisional triples** | **13,530** |
| Raw join-key NULLs (subject/object/canonical_type) | **0 / 0 / 0** |
| `relations` triple uniqueness | **UNIQUE** — 0 triples map to >1 relation_id (confirmed by `relations_pN_subject_entity_id_canonical_type_object_entity_idx` being a UNIQUE index) |
| `relations` `n_live_tup` (pg_stat) | **0** (stale stats; never row-level analyzed) |

The triple-uniqueness fact is load-bearing: the `JOIN relations r ON triple` produces **at most one** relation per raw row, so it neither multiplies nor drops rows. An `EXISTS`/CTE-join rewrite is therefore row-for-row equivalent.

---

## 2. Semantics-preserving rewrite of the density denominator

### 2.1 What the original computes (exact semantics)

Density = `triple_count(s,o,ct) / |docs(s) ∪ docs(o)|` where:
- **numerator** = `COUNT(*) FROM relation_evidence_raw WHERE (subject,object,canonical_type) = (s,o,ct)` (SubPlan 1).
- **denominator** = `COUNT(DISTINCT source_document_id) WHERE subject_entity_id IN (s,o) OR object_entity_id IN (s,o)` (SubPlan 2). This is the count of distinct docs that mention **either** entity, where "doc mentions entity e" ≡ e appears as subject **or** object in **any** raw row of that doc. I.e. `|docs(s) ∪ docs(o)|`.

### 2.2 Rewrite: single per-cycle aggregate pass

Replace the per-row correlated SubPlans with two CTEs computed **once**:

```sql
WITH
-- (entity, doc) bridge: a doc "mentions" an entity iff the entity appears as
-- subject OR object in ANY raw row for that doc. UNION (not UNION ALL) dedups
-- so each (entity, doc) appears once. Computed ONCE per cycle.
entity_doc AS (
    SELECT subject_entity_id AS entity_id, source_document_id AS doc_id
      FROM relation_evidence_raw
    UNION
    SELECT object_entity_id  AS entity_id, source_document_id AS doc_id
      FROM relation_evidence_raw
),
-- numerator: rows per triple. Computed ONCE per cycle.
triple_count AS (
    SELECT subject_entity_id, object_entity_id, canonical_type, COUNT(*) AS triple_n
      FROM relation_evidence_raw
     GROUP BY 1, 2, 3
)
```

Per-candidate density then becomes (still a small correlated count, but now over the deduped `entity_doc` bridge, evaluated once per distinct candidate triple rather than per candidate row):

```sql
triple_count.triple_n::float
  / NULLIF((SELECT COUNT(DISTINCT ed.doc_id)
              FROM entity_doc ed
             WHERE ed.entity_id = rer.subject_entity_id
                OR ed.entity_id = rer.object_entity_id), 0)
```

### 2.3 Correctness proof — denominator equality

**Claim.** `COUNT(DISTINCT doc WHERE subj IN (s,o) OR obj IN (s,o))` (original)
`= COUNT(DISTINCT ed.doc WHERE ed.entity IN (s,o))` over `entity_doc` (rewrite).

**Argument.** A doc `d` is counted by the original iff ∃ a raw row in `d` with `s` or `o` in subject **or** object position ⟺ `(s,d) ∈ entity_doc OR (o,d) ∈ entity_doc` ⟺ `d ∈ docs(s) ∪ docs(o)`. `entity_doc` is exactly the set `{(e,d) : e is subject-or-object of some raw row in d}`, so its `DISTINCT doc` count filtered to `entity ∈ {s,o}` equals the original union. The numerator is byte-identical (`COUNT(*)` of the triple). ∎

**Numerical verification** (8 sample triples, original OR-scan vs rewritten `entity_doc` union):

| orig | rewritten |
|-----:|----------:|
| 110 | 110 |
| 162 | 162 |
| 10 | 10 |
| 163 | 163 |
| 96 | 96 |
| 1544 | 1544 |
| 7814 | 7814 |
| 140 | 140 |

Exact match on every sample, including a 7,814-doc hub entity. (A naive `GREATEST(deg(s), deg(o))` per-entity approximation was tested and **rejected** — it gave 96 vs the true 110, i.e. it would silently change the promotion set. Inclusion-exclusion requires the per-pair intersection, so the union must be evaluated per pair; the `entity_doc` bridge does this correctly and cheaply.)

### 2.4 Full rewritten `_FETCH_SQL` (drop-in)

```sql
WITH entity_doc AS (
    SELECT subject_entity_id AS entity_id, source_document_id AS doc_id FROM relation_evidence_raw
    UNION
    SELECT object_entity_id  AS entity_id, source_document_id AS doc_id FROM relation_evidence_raw
),
triple_count AS (
    SELECT subject_entity_id, object_entity_id, canonical_type, COUNT(*) AS triple_n
      FROM relation_evidence_raw
     GROUP BY 1, 2, 3
)
SELECT
    rer.raw_id, r.relation_id, rer.source_document_id AS doc_id, rer.chunk_id,
    rer.evidence_text, rer.extraction_confidence, rer.source_trust_weight AS source_weight,
    rer.evidence_date, rer.claim_id
FROM relation_evidence_raw rer
JOIN relations r
  ON  r.subject_entity_id = rer.subject_entity_id
  AND r.object_entity_id  = rer.object_entity_id
  AND r.canonical_type    = rer.canonical_type
JOIN triple_count tc
  ON  tc.subject_entity_id = rer.subject_entity_id
  AND tc.object_entity_id  = rer.object_entity_id
  AND tc.canonical_type    = rer.canonical_type
WHERE rer.entity_provisional = false
  AND NOT EXISTS (
    SELECT 1 FROM relation_evidence re
     WHERE re.relation_id   = r.relation_id
       AND re.doc_id        = rer.source_document_id
       AND re.evidence_date = rer.evidence_date)
  AND (
      rer.extraction_confidence >= :conf_threshold
      OR tc.triple_n::float / NULLIF((
            SELECT COUNT(DISTINCT ed.doc_id) FROM entity_doc ed
             WHERE ed.entity_id = rer.subject_entity_id
                OR ed.entity_id = rer.object_entity_id), 0) >= :density_threshold)
ORDER BY rer.extracted_at
LIMIT :batch_size
```

**Why the promotion set is unchanged:**
- Same source table, same `entity_provisional = false`, same triple-JOIN to `relations` (unique → no row multiply/drop), same `NOT EXISTS` dedup against `relation_evidence`, same `ORDER BY extracted_at`, same `LIMIT`.
- The OR-branch numerator/denominator are proven identical (§2.3). `triple_count` join is inner on the same triple, which always exists for any raw row (every raw row contributes ≥1 to its own triple count), so it never drops a row.
- Thresholds remain bind params (`:conf_threshold`, `:density_threshold`).

**Measured plan cost of the rewrite:** the CTE form EXPLAINed at **~35,706** vs **1,128,047** for the original — a **~32× reduction**. The single density pass (two raw scans + aggregate, ~30,905) replaces ~13.5k correlated SubPlan evaluations.

> Note: even the rewrite's exact-union variant still shows a correlated `COUNT(DISTINCT)` SubPlan per *distinct candidate triple* (≈9.5k groups), but it is evaluated once per triple over a deduped bridge and only for rows that fail the confidence gate — already an order of magnitude cheaper than per-row. If further reduction is wanted, the `entity_doc` union count can be pre-aggregated per entity into a `MATERIALIZED` CTE and the per-pair union derived, but the per-pair intersection term keeps that from being a pure per-entity lookup; the form above is the simplest provably-correct version.

---

## 3. Diagnostic gated-quality COUNT: fold vs cadence

**Recommendation: FOLD into the `_FETCH_SQL` pass. Remove `_COUNT_GATED_QUALITY_SQL` entirely.**

**Reasoning.**
1. `_COUNT_GATED_QUALITY_SQL` scans the *identical* candidate space as `_FETCH_SQL` (same Append over `relations`, same Memoized density SubPlan — see §1.2). Running it separately doubles the most expensive work in the cycle for a single log field + counter.
2. The "gated" set is, by construction, the complement of the promoted set within the matched-non-provisional-not-yet-promoted population: a candidate row is *gated* iff it matches a relation, is not yet in `relation_evidence`, is non-provisional, and fails **both** gate arms (`confidence < threshold` AND `density < threshold`). `_FETCH_SQL`'s WHERE already evaluates exactly these predicates (it selects the rows that **pass** the gate). The diagnostic is the same scan with the gate predicate negated.
3. **Fold mechanism (no extra scan):** compute the gated count in the same CTE pass via a conditional aggregate over the candidate set, e.g. a sibling CTE that counts candidates failing the gate:

```sql
-- Sibling CTE in the same statement as the rewritten _FETCH_SQL, or a single
-- combined query returning both the batch and the gated count via a window/CTE.
, gate_eval AS (
    SELECT
        rer.raw_id,
        (rer.extraction_confidence >= :conf_threshold
         OR tc.triple_n::float / NULLIF((
              SELECT COUNT(DISTINCT ed.doc_id) FROM entity_doc ed
               WHERE ed.entity_id = rer.subject_entity_id
                  OR ed.entity_id = rer.object_entity_id), 0) >= :density_threshold) AS passes_gate
    FROM relation_evidence_raw rer
    JOIN relations r ON r.subject_entity_id = rer.subject_entity_id
                    AND r.object_entity_id  = rer.object_entity_id
                    AND r.canonical_type    = rer.canonical_type
    JOIN triple_count tc ON tc.subject_entity_id = rer.subject_entity_id
                        AND tc.object_entity_id  = rer.object_entity_id
                        AND tc.canonical_type    = rer.canonical_type
    WHERE rer.entity_provisional = false
      AND NOT EXISTS (SELECT 1 FROM relation_evidence re
            WHERE re.relation_id = r.relation_id
              AND re.doc_id = rer.source_document_id
              AND re.evidence_date = rer.evidence_date)
)
SELECT count(*) FILTER (WHERE NOT passes_gate) AS gated_quality FROM gate_eval;
```

   Both the batch fetch and `gated_quality` then derive from one shared `entity_doc`/`triple_count` computation. (Implementation note for the worker: run a single statement that materializes the candidate set once — e.g. fetch the batch and the gated count from CTEs sharing `entity_doc`/`triple_count` — so the expensive aggregate is built exactly once per cycle.)
4. **Why not just lower cadence?** Lowering to hourly is a 12× reduction in frequency but leaves a 1.1M-cost query in place and introduces a second code path with drifting thresholds. Folding eliminates the query outright at near-zero marginal cost since the candidate set is already materialized. Cadence-lowering is the **fallback** only if folding proves awkward in the worker's session structure (it should not — both already run as short-lived read sessions in `run()`).

**Net effect:** the cycle goes from **two ~1.13M-cost queries** to **one ~35.7k-cost query** (plus the existing trivial `_COUNT_PROVISIONAL_SQL` / `_COUNT_NO_MATCH_SQL` anti-joins, which are cheap and unchanged).

---

## 4. The "missing triple index on p0,p2–p6" — REFUTED + the real stat issue

**Finding: the prior audit's claim is no longer true.** All 8 partitions currently carry the triple index:

```
 partition   | has_triple_idx
--------------+----------------
 relations_p0 | t   relations_p1 | t   relations_p2 | t   relations_p3 | t
 relations_p4 | t   relations_p5 | t   relations_p6 | t   relations_p7 | t
```

Definition (UNIQUE, all partitions):
```
CREATE UNIQUE INDEX relations_pN_subject_entity_id_canonical_type_object_entity_idx
  ON public.relations_pN USING btree (subject_entity_id, canonical_type, object_entity_id);
```

These indexes were added since the prior audit. They are **not** the lever for the promoter cost — the EXPLAIN shows seq-scan chosen because the query consumes the *entire* `relations` table (no selective predicate), for which a full index-only scan is not cheaper. The rewrite in §2/§3 fixes the cost by eliminating the per-relation probe, independent of these indexes.

### 4.1 The actual stat anomaly (optional, low-risk)

`pg_stat_user_tables` reports `relations.n_live_tup = 0` and `last_analyze = NULL` despite 13,433 rows. Stale/zero stats can mislead the planner's join-order and row estimates. If a tuning step is desired, a one-time `ANALYZE relations;` (per-partition or parent) is safe and gentle (no lock beyond a brief ShareUpdateExclusive, reads only a sample). This is **optional** — the §2/§3 rewrite is the primary fix.

### 4.2 If an index DDL is still wanted (defensive, parent-level)

Should a future audit find a partition genuinely lacking the triple index, the correct pattern (matching BP-393 — **plain `CREATE INDEX`, never `CONCURRENTLY`** inside Alembic; owned by `intelligence-migrations`, not S6/S7 which set `ALEMBIC_ENABLED=false`) is to create it on the **parent** partitioned table so Postgres cascades it to every existing and future partition:

```sql
-- intelligence-migrations Alembic migration 00NN_relations_triple_index.py
-- (op.execute used because Alembic create_index on a partitioned parent must
--  target the parent; plain CREATE INDEX per BP-393 — NOT CONCURRENTLY.)
CREATE UNIQUE INDEX IF NOT EXISTS relations_subject_canonical_object_idx
  ON public.relations (subject_entity_id, canonical_type, object_entity_id);
```

A parent-level `CREATE INDEX` on a partitioned table creates an `ON ONLY`-style parent index plus matching child indexes automatically; this is preferable to per-partition DDL because it also covers partitions created in the future. **Not required given current state** — recorded for completeness.

---

## 5. Guarantee summary (no row added/dropped)

| Change | Promotion-set impact |
|--------|----------------------|
| Density denominator → `entity_doc` UNION CTE | **None.** Proven equal (§2.3) + 8/8 numeric match incl. 7,814-doc hub. |
| Numerator → `triple_count` CTE join | **None.** Inner join on triple that always exists; `COUNT(*)` identical. |
| Fold gated-quality count into shared CTE pass | **None.** Diagnostic-only; was never in the promotion path. |
| (Optional) `ANALYZE relations` | **None.** Stats only — never changes results, only the plan. |
| No `processed` filter introduced anywhere | **Constraint honored** — `processed` remains ConfidenceWorker-owned. |

The rewrite keeps the exact `WHERE`/`JOIN`/`NOT EXISTS`/`ORDER BY`/`LIMIT` predicates of the original; only the *density computation* is restructured and the *redundant diagnostic query* is folded. **The set of rows passing into `_INSERT_SQL` is byte-for-byte unchanged.**

---

## 6. Appendix — environment

- Container: `worldview-postgres-intelligence-1`, DB `intelligence_db`, host `127.0.0.1:5433`.
- Tables confirmed in `intelligence_db` (not `kg_db`): `relations`, `relation_evidence_raw`, `relation_evidence`.
- `relation_evidence_raw` indexes: `idx_raw_evidence_triple (subject,object,canonical_type)`, `idx_raw_evidence_subject (subject, extracted_at DESC)`, `idx_raw_evidence_object (object)`, partial `idx_raw_evidence_unprocessed` / `idx_raw_evidence_partition_unprocessed` (processed=false ∧ provisional=false).
- `relation_evidence` hot partitions carry `relation_id_evidence_date_idx` and `doc_id_idx`; empty older partitions seq-scan at cost 0 (harmless).
- Git context: density denominator changed to intelligence_db-only proxy in `04d128f9a` (Final-QA-1, fixed cross-DB R9 crash); E-3 gate added in `a6452094d`.
- All EXPLAINs run with `EXPLAIN` only (no ANALYZE); all SELECTs `LIMIT`-bounded or pg_class/pg_stat estimates. No relation/relation_evidence_raw full scans issued for diagnostics.
