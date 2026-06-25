# KG Entity-to-Edge Ratio — Deep Dive (Provenance + Isolation + Under-extraction)

**Date:** 2026-06-13
**Author:** Principal Data Engineer (read-only investigation)
**Scope:** `intelligence_db.canonical_entities / entity_aliases / relations / relation_evidence_raw`, `nlp_db.entity_mentions`, `market_data_db.instruments`. Builds on `docs/audits/2026-06-13-kg-edge-count-investigation.md` (the "edge count" audit) — read that first; this one answers the *follow-up* question: **is the 87% entity isolation by design and healthy, or a symptom?**
**Status:** Root cause established. **NO** code / schema / data / git changes. All scratch tables created during analysis were dropped; measurements are read-only via `docker exec worldview-postgres-1 psql`.

---

## 0. TL;DR verdict

The high entity:edge ratio is **a mix of (a) and (b), NOT (c) or (d)** — and the prior audit's "bulk-seeded reference universe" framing is **partly wrong and should be corrected**:

* **It is NOT a dedup / over-creation problem (c).** Only **4 duplicate-name groups / 4 surplus entities** exist. Entity inflation by duplication is negligible. BP-384/385/459 dedup is holding.
* **It is only marginally a materialization-gap bug (d).** The H3 gap is **re-confirmed at exactly 1,633 edges** — real, but small relative to the headline.
* **The headline (16,994 entities, 2,166 participating, 87.3% isolated) is driven primarily by:**
  * **(a) Expected, by design — but the design is *NLP entity over-generation*, NOT instrument seeding.** 10,802 entities (63.6%) were **never mentioned in any article** and never produced evidence. Crucially, these are overwhelmingly **NLP-extracted** people/orgs/places/tickers, *not* market-data-seeded securities. **Only 647 entities (3.8%) trace to the market-data instrument universe.** The prior audit's claim that the isolated cohort is "bulk-seeded `financial_instrument` from instrument/EODHD ingestion" is **incorrect** — market_data_db holds only **651** instruments total.
  * **(b) Genuine relation under-extraction.** **4,026 entities were mentioned in articles but participate in zero edges** — the key number. Of these, **3,288 never appeared in even one raw relation-evidence row** (the extractor saw the entity but emitted no relationship for it).

**One-line verdict:** The 87% isolation is mostly *expected sparse narration over a large NLP-generated entity vocabulary* (a), compounded by *real relation under-extraction on mentioned entities* (b: 4,026 mentioned-but-isolated, 3,288 with no evidence at all); it is **not** a dedup/over-seeding problem and only a **1,633-edge** materialization-gap bug.

---

## 1. The corpus today (live, exact)

| Metric | Prior audit (2026-06-13 AM) | This audit (live) |
|---|---|---|
| Canonical entities | 16,738 | **16,994** |
| Participating in ≥1 edge | 2,166 | **2,166** |
| Isolated (no edge) | 14,572 (87.1%) | **14,828 (87.3%)** |
| Edges (`relations`) | 4,750 | **4,750** |
| Raw evidence rows | 76,869 | **76,869** |

Entity count drifted +256 (continuous ingestion); edge/evidence counts are stable, confirming the AM snapshot.

### 1.1 Entities by type

| entity_type | total | with_ticker | with_isin |
|---|---:|---:|---:|
| financial_instrument | 4,749 | 2,201 | 1,828 |
| person | 4,597 | — | — |
| organization | 2,930 | — | — |
| unknown | 2,345 | — | — |
| place | 1,433 | — | — |
| index | 432 | 9 | 1 |
| product | 180 | 1 | — |
| currency | 95 | 4 | — |
| sector | 82 | — | — |
| exchange | 61 | 4 | — |
| industry | 42 | — | — |
| macro_indicator | 40 | — | — |
| event | 8 | — | — |

> Note the type mix is dominated by `person` (4,597) + `organization` (2,930) + `unknown` (2,345) = **9,872 (58%)** — these can only come from NLP NER, never from instrument seeding. This alone falsifies the "bulk-seeded reference universe" framing.

---

## 2. Entity provenance — seeded vs extracted (corrects the prior audit)

There is **no `source`/`origin` column** on `canonical_entities`. Provenance was triangulated from: (1) ticker/ISIN presence, (2) `metadata` seed tags, (3) `entity_aliases.source`, (4) join to `market_data_db.instruments`, (5) creation timeline.

### 2.1 Hard seed signal: join to the market-data instrument universe

```
market_data_db.instruments ................................. 651
financial_instrument canonical entities .................... 4,749
  └─ ticker matches a market_data symbol (truly seeded) ..... 645   (3.8% of all entities, 13.6% of FIs)
  └─ has a ticker NOT in market_data (extraction-discovered)  1,556
  └─ no ticker and no ISIN (extraction provisional) ......... 2,547
```

**Only ~647 entities across the whole graph trace to instrument/market-data seeding.** The remaining 16,347 (96.2%) are NLP-extraction artifacts (NER mentions promoted to provisional → canonical entities), plus a handful of metadata-tagged seeds (227 `seed_source`, 31 `discovered_at`, 8 `instrument_id`).

### 2.2 Alias-source corroboration

`entity_aliases.source` distribution: `provisional_enrichment` **24,441**, `instrument_consumer` 1,797, `canonical_entity_create` 602, `eodhd_*` ~2,200, explicit `seed:*` ~470. Classifying each entity by its alias provenance:

| Provenance class | entities |
|---|---:|
| extraction-only (provisional_enrichment / canonical_entity_create aliases) | **16,061 (94.5%)** |
| seeded (instrument / eodhd / explicit seed alias) | 928 (5.5%) |
| no alias at all | 5 |

Both independent signals agree: **the entity universe is ~95% NLP-extraction-generated, ~5% seeded.** This is the opposite of the prior audit's characterization.

### 2.3 Creation timeline confirms extraction, not bulk seeding

Entity creation has spikes on **2026-05-10/11 (1091/1582)**, **2026-05-23 (1552)**, and **2026-06-11/12/13 (3655/4624/1582)**. The June spikes coincide with the **BP-662 unblock + provisional-enrichment drain** (per the prior audit's relation timeline), i.e. the pipeline promoting a backlog of provisional NER mentions into canonical entities — **extraction throughput, not a reference-data seed load**.

---

## 3. The funnel: entities → mentioned → evidence → edge

| Stage | Count | % of total |
|---|---:|---:|
| Canonical entities (total) | 16,994 | 100% |
| Ever **mentioned** in an article (`nlp_db.entity_mentions.resolved_entity_id` distinct) | 6,175 | 36.3% |
| Appear as subject/object in **raw relation evidence** | 6,789 | 40.0% |
| **Participate in ≥1 materialized edge** | 2,166 | 12.7% |

> `entity_mentions` resolution outcomes: 99,462 auto-resolved (→ 6,175 distinct entities), 16,553 provisional, 8,239 noise, 4,481 entity_created. So even among the 128,737 NER mentions, only 6,175 distinct entities ever got a confident article link.

The funnel narrows hardest at **mentioned → edge**: of 6,175 mentioned entities, only ~2,149 also carry an edge (the 2,166 edge-participants minus ~17 that participate via evidence whose mention resolved under a different id). **Two-thirds of entities that the system confidently linked to an article never become a graph node.**

---

## 4. THE CRUX — isolated-but-mentioned vs isolated-never-mentioned

Splitting the **14,828 isolated entities** by whether they were ever mentioned in an article:

| Bucket | Count | Interpretation |
|---|---:|---|
| **Isolated AND never mentioned** | **10,802 (72.8% of isolated)** | **Expected.** Entity vocabulary that the NER cascade emitted (or instrument seeding created) but no article confidently anchored. Dead weight in the lexicon, not a relation bug. |
| **Isolated BUT mentioned** | **4,026 (27.2% of isolated)** | **The symptom.** The system *did* confidently link these to articles, yet produced no edge. |

Decomposing the crux 4,026:

| Sub-bucket | Count | Meaning |
|---|---:|---|
| Mentioned, isolated, **never in any raw evidence** | **3,288** | Pure **relation under-extraction** — the extractor saw the entity in text but emitted **no relationship** mentioning it. |
| Mentioned, isolated, **present in raw evidence but no edge** | **738** | Lost in the evidence→edge collapse (dedup, self-loop removal, or the H3 materialization gap). |

### 4.1 Type profile of the two crux buckets

**Never-mentioned (10,802 — the expected lexicon overhang):** person 3,461, financial_instrument 2,505 (only 777 with ticker), organization 1,885, unknown 1,582, place 828. Dominated by un-anchored NER surface forms.

**Isolated-but-mentioned (4,026 — the symptom):** financial_instrument 1,234 (608 with ticker), person 827, organization 757, unknown 533, place 385. These are real, article-anchored entities (including 608 tickered securities and 827 named people) that the graph simply never connects.

---

## 5. Inflation / dedup check — clean

| Check | Result |
|---|---|
| Duplicate canonical-name groups (`lower(canonical_name)`, >1 id) | **4** |
| Surplus entities from duplication | **4** |
| The only dup names | `berkshire hathaway inc`, `cboe volatility index`, `dow jones industrial average`, `s&p 500 index` (each split across a `financial_instrument` and an `index` row) |
| `provisional_entity_queue`: resolved | 17,645 |
| `provisional_entity_queue`: noise (correctly filtered out) | 3,884 |
| `provisional_entity_queue`: failed | 417 |
| `provisional_entity_queue`: pending (backlog) | **4** |

**Entity inflation by duplication is effectively zero.** The 2-layer noise filter is working (3,884 mentions correctly tombstoned as noise; 8,239 NER mentions marked noise at resolution). The 87% isolation is **not** a dedup failure and **not** provisional spam — the provisional queue is fully drained (4 pending). The 2,345 `unknown`-type entities are a quality concern (only 763 mentioned), but they are distinct real surface forms, not duplicates.

---

## 6. Dropped-relation accounting (re-confirms prior H3)

```
relation_evidence_raw rows ................................. 76,869
  ├─ entity_provisional = true (endpoint not yet canonical) . 4,834   (legitimately deferred)
  └─ entity_provisional = false (both resolved) ............. 72,035
        └─ DISTINCT (subj, canonical_type, obj) triples ..... 7,340
              ├─ self-loops (subj = obj), dropped by design .. 957
              └─ non-self-loop triples ...................... 6,383
                    └─ both endpoints currently canonical .... 6,383  (100%)
                          ├─ materialized as edges ........... 4,750
                          └─ GAP: canonical, no edge ......... 1,633  ← H3, exactly re-confirmed
```

* **Confidence gate drops nothing:** all 4,750 edges have `confidence ≥ 0.9` (avg **0.996**), the extractor saturates near 0.95 — the gate is never binding (consistent with thesis §5.3 calibration caveat).
* **The 1,633-edge gap evidence is 100% `processed=true`** (24,014 evidence rows, zero unprocessed). The materialization path *ran* and marked the evidence done but never inserted the edge — i.e. the upsert was skipped (entity-existence gate at processing time) and the back-fill (`_unblock_provisional_evidence`) never revisits it because it keys on `entity_provisional=true` and these rows are flagged `false`.
* **Gap by type** (top): `listed_on` 289, `operates_in_country` 267, `is_in_sector` 201, `competes_with` 193, `partner_of` 153, `has_executive` 108 — the structured membership relations whose object (sector/exchange/country) or subject (newly-discovered instrument) lagged the evidence. Identical profile to the prior audit.

---

## 7. Healthy-graph benchmark

| Measure | Value |
|---|---|
| Edges per **all** entities | 0.28 |
| Edges per **participating** entity | **2.19** |
| Mean degree (connected sub-graph) | 4.39 |
| Median degree | 2 |
| Max degree (hub) | 255 (NASDAQ); NYSE 250; USA 112 |
| Avg evidence rows per edge | 8.19 |

**Is 2.2 edges/participating-node reasonable for a financial-news KG?** It is **on the low side but not anomalous** for a news-narrated graph: median degree 2 means the typical connected entity sits on a single relationship plus a membership edge. A mature financial KG narrated over 14k articles would be expected to reach 4–8 edges/node on the connected core. The shortfall is explained by §4 (under-extraction) + §6 (1,633 unmaterialized), not by structure.

**Is the problem too-few-edges or too-many-entities? Both, in sequence:**
1. **Too-many-entities (vocabulary overhang):** 10,802 never-mentioned + 3,884 noise show the NER cascade emits far more entity candidates than the corpus can anchor. This inflates the denominator and makes "0.28 edges/node" look alarming. It is mostly harmless (isolated rows cost storage, not correctness) but the **2,345 `unknown` + the 2,547 ticker-less financial_instrument** rows are low-quality and worth a periodic prune/merge.
2. **Too-few-edges (under-extraction):** 4,026 mentioned-but-isolated, of which 3,288 produced no relation evidence at all — the relation extractor (Block 10) under-emits relationships for entities it has already confidently linked. This is the real quality lever.

---

## 8. Verdict (per the four hypotheses)

| Option | Verdict | Evidence |
|---|---|---|
| **(a) Expected / by-design (reference seeding + sparse narration)** | **PRIMARY — but re-characterized** | 10,802 of 14,828 isolated entities were never mentioned; the graph is genuinely a sparse narrated overlay. **However the overlay sits on an NLP-generated vocabulary, not a seeded reference universe** — only 647 entities trace to market-data seeding. |
| **(b) Relation under-extraction** | **SECONDARY, real** | 4,026 mentioned-but-isolated entities; **3,288** produced zero relation evidence despite being article-anchored. Mean connected degree 4.39 / median 2 is low for the corpus size. |
| **(c) Entity over-creation / dedup failure** | **REJECTED (as duplication)** | 4 dup-name groups, 4 surplus entities; provisional queue drained (4 pending). *Over-creation of un-anchored candidates* exists (vocabulary overhang) but is not duplication and not a correctness bug. |
| **(d) Materialization-gap bug** | **CONFIRMED but small (1,633 edges)** | H3 re-confirmed exactly: 1,633 fully-canonical, processed triples never inserted as edges; back-fill keys on the wrong flag. |

---

## 9. Recommendations

### 9.1 For the thesis §5.2

1. **Correct the provenance framing.** The current/prior characterization that the isolated cohort is "bulk-seeded `financial_instrument` from instrument/EODHD ingestion" is **factually wrong** — market_data_db holds 651 instruments and only ~647 entities trace to seeding. The correct statement: *"The entity vocabulary is ~95% NLP-extraction-generated (NER surface forms promoted to canonical entities); the graph narrates a sparse set of relationships over this large vocabulary. 36% of entities are ever article-anchored; 13% participate in an edge."*
2. **Quote density over the connected sub-graph** (2.19 edges/participating node, mean degree 4.39), not over all 16,994 entities. The "0.28 edges/node" intuition is misleading because the denominator is an un-anchored NER lexicon.
3. **Disclose the two real gaps honestly:** (i) 4,026 article-anchored entities yield no edge (under-extraction), 3,288 with no evidence at all; (ii) a 1,633-edge materialization back-fill gap (BP-662 family). Both are bounded and explained.

### 9.2 Engineering (NOT filed — candidates only)

* **BUG_PATTERNS candidate (re-affirm prior audit):** the `_unblock_provisional_evidence` back-fill keys on `entity_provisional=true`, missing the cohort whose upsert was skipped by the *entity-existence gate* (flag stays `false`, evidence marked `processed=true`). A periodic reconciler should re-materialize any `relation_evidence_raw` triple where both endpoints are now canonical and no `relations` row exists, **independent of the provisional flag**. Recoverable: **1,633 edges** (→ relations ≈ 6,383).
* **Quality lever (under-extraction):** investigate why 3,288 article-anchored entities (incl. 608 tickered securities, 827 named people) produced zero relation evidence — likely the relation extractor's entity-pair candidate generation or the prompt's structured-relation coverage. This is the highest-value graph-density improvement and is *separate* from the materialization gap.
* **Hygiene (vocabulary overhang):** consider a periodic prune/merge of the 2,345 `unknown` and 2,547 ticker-less `financial_instrument` rows that are never mentioned — they inflate the entity count and the misleading ratio without contributing signal.

---

## 10. Appendix — key queries

```sql
-- Provenance: only 647 entities trace to the market-data universe
-- (md symbols loaded to a scratch table _md, since dropped)
SELECT count(*) FROM canonical_entities ce
WHERE EXISTS (SELECT 1 FROM market_data_db_instruments m WHERE m.symbol = ce.ticker);  -- 647

-- Funnel (cross-DB): distinct resolved entities in nlp_db
SELECT count(DISTINCT resolved_entity_id) FROM nlp_db.entity_mentions
WHERE resolved_entity_id IS NOT NULL;  -- 6,175

-- Crux split (set ops on isolated vs mentioned vs evidence id lists)
--   isolated total .................. 14,828
--   isolated & never mentioned ...... 10,802
--   isolated & mentioned ............  4,026
--      └ mentioned, no evidence .....  3,288
--      └ mentioned, has evidence ....    738

-- Dedup: 4 dup-name groups / 4 surplus
WITH d AS (SELECT lower(canonical_name) ln, count(*) c FROM canonical_entities
           GROUP BY 1 HAVING count(*)>1)
SELECT count(*), sum(c-1) FROM d;  -- 4 | 4

-- H3 materialization gap: 1,633 (canonical_type is the relation column)
WITH dt AS (SELECT DISTINCT subject_entity_id s, canonical_type rt, object_entity_id o
            FROM relation_evidence_raw
            WHERE NOT entity_provisional AND canonical_type IS NOT NULL
              AND subject_entity_id<>object_entity_id)
SELECT count(*) FROM dt d
WHERE EXISTS(SELECT 1 FROM canonical_entities WHERE entity_id=d.s)
  AND EXISTS(SELECT 1 FROM canonical_entities WHERE entity_id=d.o)
  AND NOT EXISTS(SELECT 1 FROM relations r
                 WHERE r.subject_entity_id=d.s AND r.canonical_type=d.rt
                   AND r.object_entity_id=d.o);  -- 1,633

-- Connected-subgraph density
SELECT 4750.0/2166;  -- 2.19 edges per participating node
```
