# FR-12 — entity_type Mis-classification of Hub Entities (Investigation)

**Date:** 2026-06-13
**Scope:** `intelligence_db.canonical_entities.entity_type`
**Status:** Investigation only — NO changes applied.
**Related:** PLAN-0112 (this issue), PLAN-0111 (parallel ticker-dedup, **collision risk — see §5**)

---

## 1. Scope & Inventory

### 1.1 entity_type distribution (live, 2026-06-13)

| entity_type           | count | no_ticker | has_ticker |
|-----------------------|-------|-----------|------------|
| financial_instrument  | 8420  | 6235      | 2185       |
| person                | 4502  | 4502      | 0          |
| unknown               | 1897  | 1896      | 1          |
| place                 | 1398  | 1398      | 0          |
| index                 | 228   | 220       | 8          |
| product               | 157   | 156       | 1          |
| currency              | 93    | 89        | 4          |
| sector                | 73    | 73        | 0          |
| macro_indicator       | 40    | 40        | 1(system)  |
| industry              | 38    | 38        | 0          |
| event                 | 8     | 8         | 0          |

**Headline signal:** 6235 of 8420 `financial_instrument` rows (**74%**) have **no ticker**. A real tradable instrument should almost always carry a ticker. This bucket is the primary contamination reservoir — it contains exchanges, generic phrases ("Nvidia shares", "Microsoft Stock", "Stock futures"), bond/option descriptions ("2027 Notes", "$150 strike call option"), private companies (SpaceX, Anthropic-style), foundations ("Duke Energy Foundation"), and research shops ("Zacks").

### 1.2 Mis-typed high-degree hubs (top by node_degree)

The most damaging mistypes are high-degree (many graph edges + many feed appearances):

| name | current type | degree | correct type |
|------|-------------|--------|--------------|
| **NYSE** | financial_instrument | 393 | exchange/venue (no such type → closest = `unknown` or new `exchange`) |
| **NASDAQ** | index | 381 | exchange/venue |
| Information Technology | sector | 295 | ✓ correct |
| Financials / Industrials / Consumer Discretionary / Health Care / ... | sector | 90–259 | ✓ correct |
| United States of America | unknown | 166 | place |
| **U.S.** | currency | 155 | place |
| Anthropic | unknown | 131 | financial_instrument (private co) / unknown acceptable |
| People's Republic of China | unknown | 118 | place |
| OpenAI | unknown | 116 | financial_instrument (private co) / unknown acceptable |
| **SpaceX** | financial_instrument | 96 | unknown / company (no ticker) |
| **Nvidia shares** | financial_instrument | 87 | should dedup into NVDA (it's a phrase, not an entity) |
| **Microsoft Stock** | financial_instrument | 85 | should dedup into MSFT |
| **NasdaqGS** | index | 72 | exchange/venue |
| **Dow Jones** | index | 69 | ✓ index (acceptable) |
| **Amazon** | place | 68 | financial_instrument (AMZN) — NER confused company vs rainforest |
| **Stock futures / Alphabet Stock / Google Cloud / Meta AI** | financial_instrument | 40–81 | concept/phrase, not instruments |
| Natural Gas | unknown | 36 | product/commodity |
| **Zacks** | financial_instrument | 21 | unknown (research firm) |
| **Duke Energy Foundation** | financial_instrument | 25 | unknown (non-profit) |

### 1.3 currency-typed rows that are actually places/concepts

81 of 93 `currency` rows have letters + no ticker. Real currencies are present (Euro, Japanese Yen, Swiss Franc → CHF) but the bucket is polluted by:
- **place mislabels:** `U.S.`, `The Dollar` (concept), `cable`/`sterling`/`yen`/`yuan` (slang)
- **price-literal garbage:** `$0.0732`, `$100`, `$135`, `CHF330`, `RMB49`, `Rs20`, `US$15.20` (NER captured a price as a currency entity)
- **ticker symbols:** `$DOWI`, `$NASX`, `$IUXX`, `$SRIT` (these are index/instrument symbols)

### 1.4 Quantified mis-typed estimate

| bucket | est. count | basis |
|--------|-----------|-------|
| financial_instrument w/o ticker that are NOT instruments | ~hundreds–low thousands of the 6235 | phrases, exchanges, bonds, options, private orgs, foundations |
| `index` rows that are exchanges (NYSE-class) | NASDAQ, NasdaqGS + similar | exchange ≠ index |
| `currency` rows that are place/concept/price-literal | ~50–81 of 93 | letters + no ticker, minus the ~12 real FX/crypto names |
| `unknown` high-degree that are place or company | dozens (USA, PRC, India, Canada, AI labs) | named-entity gap |
| `place` that are companies (Amazon) | small | NER homonym confusion |

A precise count requires per-row adjudication (ideally LLM re-classification), but the **74% tickerless financial_instrument** figure is the single most actionable headline.

---

## 2. Root Cause

`entity_type` is assigned on **two independent mint paths**, and a third (LLM) enrichment overlay:

### 2.1 Path A — market-data instrument seed (correct by construction)
`services/knowledge-graph/.../consumers/instrument_consumer.py:464` and
`instrument_discovered_consumer.py:179` **hardcode** `entity_type="financial_instrument"`.
These rows always carry a ticker and pin `entity_id == instruments.id` (M-017). This path is
**not** the source of the mistype problem — it produces the 2185 ticker-bearing FIs.

### 2.2 Path B — provisional/news mint (the actual culprit)
News mentions that fail resolution are queued in `provisional_entity_queue`
(`services/nlp-pipeline/.../blocks/entity_resolution.py:283`) keyed by
`(normalized_surface, mention_class)`. The KG worker then mints a canonical via
`provisional_enrichment_core.py`. entity_type here comes from **two sub-sources**:

1. **LLM extraction** (`extract_entity_profile`, line 133) — the `ENTITY_PROFILE`
   prompt (`libs/prompts/src/prompts/knowledge/entity_profile.py` v2.0) asks the
   model (Qwen3.5-0.8B small model) to pick a type from a fixed list.
2. **Fallback to GLiNER `mention_class`** when the LLM omits the field
   (`provisional_enrichment_core.py:247`):
   `_raw_type = profile.get("entity_type") or profile.get("mention_class", "unknown")`.

The raw value is normalised and remapped through `_ENTITY_TYPE_ALIASES`
(lines 67–101), then anything outside `_VALID_ENTITY_TYPES` is forced to `unknown`.

### 2.3 Why each known example is wrong

- **NYSE → financial_instrument** (degree 393, `enrichment_attempts=0`):
  Never LLM-enriched, so the type is the **GLiNER `mention_class` fallback**.
  GLiNER tagged "NYSE" as an organization/company-ish class; the alias map sends
  `organization → unknown` but `company/corp/firm → financial_instrument`. There is
  **no `exchange`/`venue` type in the schema at all** (`ck_canonical_entities_entity_type`
  has 11 values, none of them an exchange), so an exchange can only land as FI, index, or unknown.

- **NASDAQ → index** and **NasdaqGS → index** (`enrichment_attempts=1`):
  These **were** LLM-enriched. The `ENTITY_PROFILE` prompt literally lists
  **"Nasdaq"** as an example under `index` (line 37: `index=market indices (S&P 500, Nasdaq, FTSE)`).
  The prompt actively *teaches the model the wrong answer* — it conflates the
  NASDAQ exchange with the Nasdaq Composite index. Again, no `exchange` type exists,
  so even a correct model couldn't express the right answer.

- **U.S. → currency** (degree 155, enriched): The prompt's `currency` definition
  (`currency=currencies (USD, EUR, BTC)`) plus the ambiguous abbreviation "U.S."
  (which the small model reads as the dollar) wins over `place`. The full-name
  variant "United States of America" landed in `unknown` (seeded `F-CRIT-10`, not
  LLM-typed) — so we have the **same country split across `currency` + `unknown`**,
  neither of which is `place`.

- **Amazon → place** (degree 68): GLiNER/LLM homonym confusion — Amazon the river/region
  vs Amazon.com the company. No ticker captured → no disambiguation signal.

- **"Nvidia shares" / "Microsoft Stock" / "Stock futures" → financial_instrument**:
  These are **phrases, not entities**. The provisional path mints a canonical for any
  unresolved surface; the LLM dutifully types the phrase as an instrument. These are
  *also* a dedup problem (they should fold into NVDA/MSFT) — overlaps with PLAN-0111.

### 2.4 Root-cause summary
1. **Schema gap:** no `exchange`/`venue` entity_type → every exchange is forced into a wrong bucket.
2. **Prompt defect:** `ENTITY_PROFILE` uses "Nasdaq" as an `index` exemplar, teaching the exchange/index conflation.
3. **Weak typing on the no-enrich path:** rows with `enrichment_attempts=0` rely on GLiNER `mention_class` → FI/unknown coarse fallback.
4. **Small classifier model:** Qwen3.5-0.8B mis-resolves ambiguous abbreviations ("U.S.").
5. **No entity-vs-phrase gate:** the provisional path mints phrases ("Microsoft Stock") as typed entities.

---

## 3. Impact

### (a) Weirdness metric — semantic-distance type-fallback
`weirdness_scorer.py:244` `_semantic_distance`: when an endpoint embedding is missing,
it falls back to `entity_type` equality:
`_TYPE_FALLBACK_DIFFERENT = 1.0`, `_TYPE_FALLBACK_SAME = 0.3` (scorer_version gets `+typefallback`).
With weight `w_semantic = 0.40`, a single mistype flips the dominant term between 0.3 and 1.0,
swinging the composite weirdness by up to **0.28** for any path touching a mistyped node.
Because the mistyped nodes are exactly the **highest-degree hubs** (NYSE deg 393, NASDAQ 381,
U.S. 155), they appear in a disproportionate share of paths — so the contamination is concentrated
where it matters most. NYSE-as-instrument vs a real company endpoint reads as "same type" (0.3,
*looks mundane*) when it should be a genuinely cross-type, surprising link.

### (b) entity_type filter on the global feed
`global_weird_connections.py:60,76` accepts an `entity_type` filter and surfaces
`node.entity_type` (line 116) in feed rows. A user filtering "show me index connections"
gets NASDAQ-the-exchange and `$DOWI`-style ticker junk; filtering "currency" returns
price literals ($100, RMB49) and the United States. The filter is only as good as the
column, so it currently returns semantically wrong sets.

### (c) Graph traversal / display
`temporal_event_consumer.py` gates GLOBAL-scope events on `entity_type`
(`_GLOBAL_ALLOWED_ENTITY_TYPES`); mistypes leak or suppress global events incorrectly.
`structured_enrichment_consumer.py:261` branches on
`entity_type in ('financial_instrument','company')` to decide structured-enrichment —
so the ~6000 tickerless FIs get pulled into instrument-style enrichment (fundamentals,
analyst data) they can never satisfy, wasting enrichment attempts.

### (d) Frontend
Node/dossier rendering keys icon + label off entity_type (the feed passes it straight
through from S9 → KG). Users see NYSE rendered as a stock, the United States as a
currency, Amazon as a place. This is the most visible symptom and the one driving FR-12.

---

## 4. Recommended Fix (NOT applied)

Two distinct deliverables: a **data backfill** (corrects existing rows) and a
**prevention** (fixes the typing logic at source). Backfill without prevention will
re-pollute within days of news flow.

### 4.1 Prevention (code — the durable fix)

1. **Add an `exchange` (or `venue`) entity_type** — schema change owned by
   `intelligence-migrations` (R24). Extend `ck_canonical_entities_entity_type`,
   `_VALID_ENTITY_TYPES` in `provisional_enrichment_core.py`, and the
   `ENTITY_PROFILE` prompt enum. Without this, exchanges have no correct home.
2. **Fix `ENTITY_PROFILE` prompt** (`libs/prompts/.../entity_profile.py`, bump to v2.1):
   - Remove "Nasdaq" from the `index` exemplar list; add an explicit `exchange`
     definition with NYSE/NASDAQ/LSE as examples, and a rule: "a stock *exchange or
     trading venue* is `exchange`, NOT `index` or `financial_instrument`".
   - Add a disambiguation rule for country abbreviations: "'U.S.', 'US', 'U.K.' are
     `place`, never `currency`. `currency` is only the unit of money (USD, EUR)."
   - Add an entity-vs-phrase rule: "If the mention is a phrase like 'X shares',
     'X stock', 'stock futures', return the underlying entity's canonical_name and
     ticker — do NOT mint the phrase as its own instrument."
   - Bump version → libs/prompts CHANGELOG + content_hash (per PLAN-0107 conventions).
3. **Strengthen the no-enrich fallback** (`provisional_enrichment_core.py:247`):
   stop letting GLiNER `mention_class` directly become `financial_instrument` via the
   `company/corp/firm` aliases when there is **no ticker**. A tickerless "company"-class
   mention should default to `unknown` (or `company` if a non-tradable company type is
   added), not `financial_instrument`. Reserve `financial_instrument` for rows that
   either have a ticker or were LLM-confirmed tradable.
4. **Consider a stronger classifier** for the type field (the budget judge model
   DeepSeek V4 Flash per project memory, or keep Qwen but only for extraction) — the
   0.8B model is the proximate cause of "U.S."→currency.

### 4.2 Backfill (data — one-time correction)

Deterministic, high-confidence corrections (safe SQL, owned by intelligence-migrations
as a data migration or a `scripts/` one-off run against intelligence_db):

- **Exchanges:** re-type NYSE, NASDAQ, NasdaqGS (+ a curated exchange allow-list:
  LSE, TSX, Euronext, CBOE, etc.) → `exchange` (after the type exists).
- **Country places:** `currency` and `unknown` rows whose name matches a country/region
  gazetteer (`U.S.`, `United States of America`, `People's Republic of China`,
  `Republic of India`, `Canada`, ...) → `place`. The repo already has an `iso2`-tagged
  seed (`United States of America` metadata) to anchor a gazetteer join.
- **Price-literal / ticker-symbol currency junk:** rows like `$100`, `RMB49`, `$DOWI`
  → either re-type (`$DOWI`/`$NASX` → index) or **tombstone** (price literals are not
  entities — coordinate with the dedup/cleanup pass).
- **Tickerless financial_instrument:** the large bucket needs **LLM re-classification**
  rather than a regex (too heterogeneous). Recommend a batch re-profile pass that reuses
  `extract_entity_profile` with the fixed v2.1 prompt for all
  `entity_type='financial_instrument' AND ticker IS NULL` rows, writing the corrected type.
  This doubles as a re-enrichment for the 6037 never-enriched rows.

Sequence: ship schema + prompt + fallback fix **first**, then run the LLM re-profile
backfill so corrected rows are written under the fixed logic.

---

## 5. ⚠️ Collision with parallel PLAN-0111 ticker-dedup session

`provisional_enrichment_core.py` (lines 349–403) is **actively being modified by the
parallel session** doing BP-459 ticker-dedup (the "451 tickers with duplicate canonicals
/ 593 excess rows" work, dated 2026-06-12 in-file). **Significant overlap:**

- Many FR-12 mistypes ("Nvidia shares", "Microsoft Stock", "Alphabet Stock") are
  **the same rows** the dedup pass wants to fold into the ticker-bearing canonical.
  A re-type script that touches these would race the dedup's merge/delete.
- Both efforts edit `canonical_entities.entity_type` / row lifecycle and both edit
  `provisional_enrichment_core.py`.

**Recommendation:**
- Do **NOT** run an FR-12 backfill against rows in PLAN-0111's dedup target set until
  that session lands; sequence FR-12 backfill **after** dedup so phrase-rows are gone first.
- Coordinate the `provisional_enrichment_core.py` edits (prompt-type plumbing + fallback
  hardening for FR-12 vs ticker pre-lookup for PLAN-0111) on a single branch or with
  explicit hand-off — concurrent edits to this file are a known corruption risk (R42/BP-590).
- The prompt fix (`libs/prompts`) and the schema/migration (intelligence-migrations) are
  **independent** of the dedup work and can proceed in parallel safely.

---

## 6. Files Referenced

- `services/knowledge-graph/src/knowledge_graph/infrastructure/workers/provisional_enrichment_core.py` — type assignment + alias map (root cause Path B)
- `services/knowledge-graph/src/knowledge_graph/infrastructure/messaging/consumers/instrument_consumer.py:464` — hardcoded FI (Path A)
- `services/knowledge-graph/src/knowledge_graph/infrastructure/messaging/consumers/instrument_discovered_consumer.py:179` — hardcoded FI (Path A)
- `services/nlp-pipeline/src/nlp_pipeline/application/blocks/entity_resolution.py:283` — provisional queue insert
- `libs/prompts/src/prompts/knowledge/entity_profile.py` — ENTITY_PROFILE v2.0 (prompt defect)
- `services/knowledge-graph/src/knowledge_graph/application/services/weirdness_scorer.py:244` — type-fallback impact
- `services/knowledge-graph/src/knowledge_graph/application/use_cases/global_weird_connections.py` — feed type filter
- `services/knowledge-graph/src/knowledge_graph/infrastructure/messaging/consumers/structured_enrichment_consumer.py:261` — type-gated enrichment
- DB CHECK: `ck_canonical_entities_entity_type` (11 values, no `exchange`)
