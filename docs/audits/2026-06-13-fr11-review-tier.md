# FR-11 — Review-Tier Duplicate Clusters + Ticker-Bearing Exact-Name Dups (human decision required)

- **Date:** 2026-06-13
- **Branch:** `feat/frontend-enhancement-sprint`
- **Scope:** READ-ONLY analysis + (separately) the non-applied migration 0054. **No merges applied, no data mutated, no `--apply` run.**
- **Inputs:** `scripts/data/merge_name_duplicates.py` dry-run (review tier 0.80–0.92) + live read-only DB inspection of the 2 residual exact-name FI clusters.
- **Companion artefacts:** review CSV `docs/audits/2026-06-13-fr11-review-clusters.csv`; migration `services/intelligence-migrations/alembic/versions/0054_canonical_name_ticker_unique_fi.py` (implemented, NOT applied).

---

## 0. TL;DR

- The name-merge **dry-run** surfaced **7 review-tier clusters** (0.80–0.92 trigram). **None should be blindly auto-merged.** 3 are clearly **DISTINCT** macro series (Core CPI ≠ CPI, Real GDP ≠ GDP, 2yr ≠ 10yr Treasury). 1 is a clear **merge** (person dup). 3 are **uncertain** legal-entity vs sub-entity pairs.
- The 2 residual ticker-bearing exact-name FI clusters ("berkshire hathaway inc" ×4, "brown-forman corporation" ×2) are a **MIX**: some are **genuinely distinct share classes** (BRK Class A vs Class B — different ISINs, must NOT merge) and some are **ticker-notation duplicates of the same security** (BRK-A vs BRK.A; BF-B vs BF.B — same ISIN, true dups owned by the ticker-merge path).
- Because distinct share classes legitimately share `lower(canonical_name)`, an **unconditional `UNIQUE(lower(canonical_name))` index is WRONG**. Migration 0054 instead uses the **share-class-aware composite** `UNIQUE(lower(canonical_name), coalesce(ticker,'')) WHERE entity_type='financial_instrument'`, which is conflict-free on live data **today**.

> ⚠️ **Note on the AUTO tier (separate from this review tier):** the dry-run's *auto* tier proposed merging **"Core Personal Consumption Expenditures Price Index" → "Personal Consumption Expenditures Price Index"**. **Core PCE ≠ PCE** (Core excludes food & energy) — this is a **false-positive auto-merge** caused by the token-superset rule ("PCE Price Index" tokens ⊆ "Core PCE Price Index" tokens). **Do NOT run `--apply --tier auto` without first excluding the `Core …` / `Real …` prefix family**, or it will collapse a distinct macro series. Flagged here because it shares the FR-11 root family with the review clusters below.

---

## 1. Review-tier clusters (0.80 ≤ sim < 0.92) — human decision

Source: `merge_name_duplicates.py` dry-run → `docs/audits/2026-06-13-fr11-review-clusters.csv` (7 rows).

| # | Hub (name · type · degree) | Candidate (name · type · degree) | sim | RECOMMENDATION | Rationale |
|---|---|---|---|---|---|
| 1 | Consumer Price Index · `unknown` · 2 | Core Consumer Price Index · `unknown` · 0 | 0.875 | **KEEP SEPARATE** | Core CPI **excludes food & energy** — a distinct, separately-reported macro series. Merging would conflate two indicators. |
| 2 | Gross Domestic Product · `unknown` · 1 | Real Gross Domestic Product · `unknown` · 0 | 0.821 | **KEEP SEPARATE** | Real GDP is inflation-adjusted vs nominal GDP — different series, different values. Distinct. |
| 3 | 10-Year U.S. Treasury Yield · `unknown` · 0 | 2-Year U.S. Treasury Yield · `unknown` · 0 | 0.821 | **KEEP SEPARATE** | Different tenors on the curve (2yr vs 10yr) — the spread between them is itself a tracked signal. Never merge. |
| 4 | Dr. Michelle Longmire · `person` · 0 | Michelle Longmire · `person` · 0 | 0.857 | **MERGE** | Same person; the only delta is the "Dr." honorific. Both degree 0; pick either as survivor (prefer the cleaner "Michelle Longmire" if degree ties). Low blast radius. |
| 5 | Mizuho Securities · `financial_instrument` · 8 | Mizuho Securities USA LLC · `financial_instrument` · 1 | 0.818 | **UNCERTAIN** | "Mizuho Securities USA LLC" is a *subsidiary* of the Mizuho parent. Whether to collapse into one node depends on whether the graph should distinguish the US broker-dealer entity. Both ticker-less. Defer to human; if merged, survivor = the degree-8 hub. |
| 6 | J.P. Morgan Asset Management · `financial_instrument` · 3 | JP Morgan Asset Management Holdings Inc. · `financial_instrument` · 1 | 0.828 | **UNCERTAIN / lean MERGE** | Same business; "Holdings Inc." is the legal-entity surface of the same asset-management arm. Likely the same node in practice. If merged, survivor = degree-3 hub. Confirm the "Holdings Inc." row carries no distinct edges first. |
| 7 | Veris Residential, Inc. · `financial_instrument` · 0 | Veris Residential, L.P. · `financial_instrument` · 0 | 0.818 | **KEEP SEPARATE (lean)** | "Inc." (the REIT) vs "L.P." (the operating partnership) are a classic **UPREIT** parent/operating-partnership pair — legally distinct entities, often modelled separately in filings. Both degree 0 (no edges lost either way). Recommend keep-separate unless the graph deliberately collapses UPREIT structures. |

**Summary:** 3 KEEP-SEPARATE (distinct macro series), 1 MERGE (honorific dup), 3 UNCERTAIN (legal-entity / subsidiary / UPREIT pairs). **None auto-merged.**

---

## 2. Residual ticker-bearing exact-name FI clusters (FR-11 #2) — dups vs distinct share classes

Read-only live inspection (intelligence_db `canonical_entities` ⨝ `node_degree`, cross-checked against market_data_db `instruments.isin`).

### 2a. "berkshire hathaway inc" — ×4 (NOT all dups)

| canonical entity_id (8) | ticker | exchange | degree | created | instrument ISIN | security |
|---|---|---|---|---|---|---|
| `019e0dc1` | `BRK-B` | US | 14 | 2026-05-09 | `US0846707026` | **Class B** |
| `019e4abc` | `BRK.B` | US | 21 | 2026-05-21 | `US0846707026` | **Class B** |
| `697cc151` | `BRK-A` | US | 14 | 2026-05-11 | `US0846701086` | **Class A** |
| `019e6f5b` | `BRK.A` | *(none)* | 11 | 2026-05-28 | `US0846701086` | **Class A** |

**Finding:** two *distinct securities* (Class A ISIN `US0846701086`, Class B ISIN `US0846707026`) each duplicated by **ticker-notation** (dash `BRK-A` vs dot `BRK.A`; `BRK-B` vs `BRK.B`). The notation dups slipped past migration 0051 (`UNIQUE(ticker)`) because the **ticker strings differ** (`BRK-B` ≠ `BRK.B`).

- **MUST NOT merge across share classes:** `BRK.A`/`BRK-A` (Class A) ≠ `BRK.B`/`BRK-B` (Class B). Different ISINs, different prices, different rights.
- **SAFE to merge within a share class (notation dups):**
  - Class B: survivor `019e4abc` (`BRK.B`, degree 21) ← loser `019e0dc1` (`BRK-B`, degree 14).
  - Class A: survivor `697cc151` (`BRK-A`, degree 14, has exchange) ← loser `019e6f5b` (`BRK.A`, degree 11, **no exchange**).
- These notation dups are **owned by the ticker-merge path** but `merge_ticker_duplicates.py` clusters on *exact ticker equality*, so it will NOT pick them up automatically (BRK-A vs BRK.A are different strings). They need a **targeted, manually-specified pairwise merge** (see §4) — the orchestrator should choose the canonical ticker notation first (the platform appears to be standardising on **dot** notation given the newer `.`-style instruments).

> The same notation duplication exists upstream in **market_data_db.instruments** (e.g. two `BF.B` instrument rows, one with empty exchange). Fixing only the canonical_entities side leaves the instrument-seed path able to re-mint. Flag for a follow-up market-data instrument-dedup (out of FR-11 scope).

### 2b. "brown-forman corporation" — ×2 (a true notation dup, same share class)

| canonical entity_id (8) | ticker | exchange | degree | created | instrument ISIN | security |
|---|---|---|---|---|---|---|
| `bfcb2f31` | `BF-B` | US | 1 | 2026-05-11 | `US1156372096` | **Class B** |
| `019e9f13` | `BF.B` | US | 1 | 2026-06-06 | `US1156372096` | **Class B** |

**Finding:** both are the **same security** (Class B, ISIN `US1156372096`) — a pure **ticker-notation duplicate** (`BF-B` vs `BF.B`). **Genuine dup, safe to merge.** Survivor: pick the canonical notation (recommend `BF.B` `019e9f13` if standardising on dot, else the older `BF-B` `bfcb2f31`); both degree 1, so tie-break on the chosen notation.

### 2c. Implication for migration 0054

Because **distinct share classes (BRK Class A vs Class B) legitimately share `lower(canonical_name)='berkshire hathaway inc'`**, the FR-11 recommendation to make the `lower(canonical_name)` unique index **unconditional is WRONG** — it would reject Class B once Class A exists. See §3.

---

## 3. Migration 0054 design — share-class-aware, NOT unconditional

**Decision: implement the FI-scoped COMPOSITE index, NOT an unconditional name index.**

```sql
CREATE UNIQUE INDEX uq_canonical_entities_name_ticker_fi
  ON canonical_entities (lower(canonical_name), coalesce(ticker, ''))
  WHERE entity_type = 'financial_instrument';
```

### Why not the unconditional `UNIQUE(lower(canonical_name))`?

Live dup-group counts on `canonical_entities` (2026-06-13):

| candidate index key | conflicting groups | verdict |
|---|---|---|
| `lower(canonical_name)` (ALL types, truly unconditional) | **5** (berkshire ×4, brown-forman ×2, CBOE Volatility Index ×2, Dow Jones Industrial Average ×2, S&P 500 Index ×2) | ❌ rejects legitimate data |
| `lower(canonical_name)` (FI only) | **2** (berkshire, brown-forman) | ❌ rejects distinct share classes |
| **`(lower(canonical_name), coalesce(ticker,''))` (FI only)** | **0** | ✅ **safe today** |

The unconditional variants reject **correct** data:
- **Distinct share classes** — BRK Class A (ISIN `US0846701086`) and Class B (ISIN `US0846707026`) share the name but are different securities (§2a).
- **FI-vs-`index` name splits** — "CBOE Volatility Index", "Dow Jones Industrial Average", "S&P 500 Index" each exist once as `financial_instrument` (ticker VIX/DJI/GSPC) and once as `index` (ticker NULL). (These are an FR-12-class mistyping issue, out of FR-11 scope — but a *truly* unconditional index would also wrongly reject them.)

The **composite `(name, ticker)`** key keys each security distinctly, so distinct share classes (different tickers) coexist while a second canonical with the **same name AND same ticker** can no longer be minted — exactly the FR-11 dup class. On live data the composite key has **0 conflict groups**, so the index builds cleanly today; the merge of the notation dups in §2 is **not a prerequisite** for 0054 (those rows have different ticker strings, so they don't collide on the composite key).

### Why a SEPARATE index (don't touch migration 0026)?

`CanonicalEntityRepository.create_or_get` writes `ON CONFLICT (lower(canonical_name)) WHERE entity_type != 'financial_instrument'`, bound to the **0026 partial index**. Dropping/widening 0026 would break the inferred conflict target ("no unique or exclusion constraint matching the ON CONFLICT specification") on every non-FI insert. 0054 therefore **adds** an FI-scoped index and leaves 0026 intact.

### Safety properties (mirrors 0051/0053)

- **FAIL-LOUD pre-flight (BP-688):** counts FI rows sharing `(lower(canonical_name), coalesce(ticker,''))`; `RAISE EXCEPTION` listing them (with the BRK-A/BRK.A guidance) instead of a generic CREATE-INDEX abort.
- **FAIL-LOUD post-assert (BP-688):** asserts the index materialised; `RAISE EXCEPTION` on silent no-op.
- **No `CONCURRENTLY` (BP-393):** plain in-transaction `CREATE UNIQUE INDEX` (table is small/unpartitioned).
- **Forward-compatible (R5/R11):** purely additive; downgrade drops only the index.
- **`coalesce(ticker,'')`:** folds NULL-ticker FI rows to one empty-string key so two NULL-ticker FI canonicals with the same name also conflict (raw NULLs would be treated as distinct otherwise — e.g. lets "SpaceX" duplicate freely).

**Status:** implemented at `services/intelligence-migrations/alembic/versions/0054_canonical_name_ticker_unique_fi.py` + static test `tests/unit/test_migration_0054_name_ticker_unique_fi.py`. **NOT applied.**

---

## 4. Recommended actions for the orchestrator (NOT performed here)

1. **Notation-dup merges (targeted, manual — NOT blind):** consolidate within each share class only:
   - Brown-Forman Class B: `bfcb2f31` (`BF-B`) ↔ `019e9f13` (`BF.B`) → one survivor.
   - Berkshire Class B: `019e0dc1` (`BRK-B`) ↔ `019e4abc` (`BRK.B`) → survivor `019e4abc` (degree 21).
   - Berkshire Class A: `697cc151` (`BRK-A`) ↔ `019e6f5b` (`BRK.A`) → survivor `697cc151` (has exchange).
   - **Never** merge BRK Class A into Class B. Use a targeted `merge_ticker_duplicates`-style run with explicit survivor/loser IDs (the engine's `_merge_cluster` accepts explicit `survivor_id` + `loser_ids`), or extend the ticker script to normalise `-`/`.` ticker notation before clustering.
2. **Review-tier (§1):** apply human decisions — merge #4; keep #1/#2/#3 separate; decide #5/#6/#7.
3. **Do NOT run `--apply --tier auto`** until the `Core …`/`Real …` prefix family is excluded (the Core-PCE false positive, §0 note).
4. **Apply migration 0054** (the composite index is conflict-free today; it does not depend on the §1 notation merges).
5. **Follow-up (out of FR-11 scope):** dedup the upstream `market_data_db.instruments` notation dups so the instrument-seed path cannot re-mint them; consider standardising ticker notation (dot vs dash) platform-wide.
