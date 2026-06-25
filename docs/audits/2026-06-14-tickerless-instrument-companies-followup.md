# Follow-up: ~2,549 tickerless `financial_instrument` canonical entities

**Date**: 2026-06-14
**Status**: DOCUMENTED — **not applied** (deliberate; remediation deferred pending decision)
**Origin**: surfaced during the PLAN-0112 FR-12 reprofile (`docs/audits/2026-06-13-plan-0112-fr-fixes-qa.md`).
**Related**: FR-12 entity re-typing (commit `61de327a5`), market-data instrument dedup (`17dfad462`).

## Summary

After the FR-12 reprofile re-typed ~3,304 mislabeled entities (private companies / agencies →
`organization`, phrases → `unknown`, etc.), **2,549 canonical entities remain typed
`financial_instrument` with `ticker IS NULL`**. The FR-12 LLM pass *deliberately* kept these as
`financial_instrument` (it judged them tradeable securities), so they are **not mistypes** — they are
real (or plausibly real) tradeable entities that simply have **no ticker and no market-data link**.

This is a **data-coverage gap, not a data-quality bug**: these entities were extracted from news/text
and never matched to a row in `market_data_db.instruments` (which covers only **646** seeded/watchlist
instruments), so they never acquired a ticker, OHLCV, quotes, or fundamentals.

## Quantification (live `intelligence_db`, 2026-06-14)

| Metric | Count |
|--------|-------|
| Tickerless `financial_instrument` canonicals | **2,549** |
| …with an ISIN | 0 |
| …ever through enrichment (`enrichment_attempts > 0`) | **0** |
| …exchange-prefixed name (e.g. `NYSEARCA:SHLD`) | 27 |
| …ticker-shaped name (≤6 all-caps, e.g. `PFFA`, `RIGI`) | 561 |
| …company-shaped name (Inc/Corp/Ltd/Group/Holdings/…) | 655 |

**Observed classes (from sampling):**
- **Real public companies missing a ticker** — e.g. `Rapid7`, `Silicon Motion Technology`,
  `KB Financial Group`, `Fiera Capital Corporation`, `Saputo`. These *should* carry a ticker; they
  were simply never in the instrument universe.
- **Bare symbols / ETFs not seeded** — e.g. `PFFA`, `RIGI`, `NYSEARCA:SHLD` (an exchange-qualified
  symbol mis-stored as the canonical name).
- **Residual noise the reprofile left as FI** — e.g. `gilt market`, `Crown 1`, `Hidden Rock Capital`,
  a mojibake row `AGSTid SecurityImprivata Inc.`. A minority; could be swept to `unknown` later.

## Root cause

1. **The instrument universe is small (646 rows).** `market_data_db.instruments` is seeded from the
   watchlist / on-demand fetch, not the full investable universe.
2. **News extraction far out-runs it.** The NLP→KG pipeline mints a `financial_instrument` canonical
   for any company/symbol it reads about. With no matching instrument, the BP-459 ticker pre-lookup and
   the M-017 instrument-anchoring never fire → the canonical is created **tickerless**, never enriched.
3. **Nothing back-fills the ticker later** — there is no name→ticker resolution against an external
   symbol source for entities outside the seeded universe.

## Impact (why it's low-urgency)

- **No correctness/dup risk** — these are distinct entities; the dedup + unique-index work
  (migrations 0051/0054, instrument dedup 039) is unaffected.
- **Degraded linkage only** — these entities have no price/fundamentals and won't appear on the
  instrument detail page or in market-data joins. They still participate in the knowledge graph,
  relations, and the weird-path / pairwise features.
- **Minor metric effect** — the weirdness scorer's semantic-distance falls back to `entity_type`
  inequality when an embedding is missing; a tickerless-but-real company typed `financial_instrument`
  is reasonable, so the effect is small.

## Remediation options (NOT applied — for decision)

| Option | What | Effort | Trade-off |
|--------|------|--------|-----------|
| **A. Name→ticker backfill (external lookup)** | For the ~655 company-shaped rows, resolve a ticker via EODHD symbol search by name + ISIN; seed the instrument + set the canonical ticker (re-using the BP-459 ticker pre-lookup so it dedups). | Medium | Best linkage gain; costs EODHD calls; risk of wrong-match → needs a confidence threshold + review. |
| **B. Sweep residual noise → `unknown`** | A second deterministic+LLM pass that demotes the clear non-securities ("gilt market", placeholders, mojibake) out of `financial_instrument`. | Low | Cleans the tail; doesn't recover real companies. Reuses `reprofile_tickerless_entities.py`. |
| **C. Expand the instrument universe** | Seed more instruments (broader EODHD coverage) so future news-extracted symbols match at mint time. | Medium-High | Addresses the root cause going forward; large data + ongoing cost; doesn't fix the existing 2,549. |
| **D. Accept as-is** | Leave them; they're usable graph entities without market-data linkage. | None | Zero risk; the gap persists. |

**Recommendation**: defer; if pursued, do **B (cheap tail cleanup)** first, then **A** gated on a
high-confidence name+ISIN match for the company-shaped subset. **C** is a separate market-data
roadmap item. None is blocking.

## How to reproduce the counts
```sql
-- intelligence_db
SELECT count(*) FROM canonical_entities WHERE entity_type='financial_instrument' AND ticker IS NULL;
SELECT canonical_name FROM canonical_entities
WHERE entity_type='financial_instrument' AND ticker IS NULL ORDER BY random() LIMIT 30;
```

---

## Relevance & coverage analysis (2026-06-15)

Read-only follow-up to characterize the tickerless `financial_instrument` canonicals by
**relevance**, **name quality**, and (intended) **zone × market-cap**, so we can decide which to
ingest. Live counts re-pulled 2026-06-15 (the population grew slightly since the 2026-06-14 snapshot).

### Hypothesis confirmation — coverage gap, NOT a linkage bug

| Check | Result |
|-------|--------|
| Tickerless `financial_instrument` canonicals (live) | **2,579** |
| `enrichment_attempts = 0` (never enriched) | **2,488** (96.5%) |
| `enrichment_attempts = 1` (one failed pass — *corrects prior "0" claim*) | **91** |
| ISIN populated / exchange populated | 0 / 1 |
| Names are company/symbol-shaped (sampled 30+30) | Yes — e.g. `Expensify, Inc.`, `China Merchants Bank`, `Toyota Motor`, `Aston Martin`, `PFC`, `RDDT.US` |
| **Tickerless names matching an `ingestion_db.polling_policies` symbol** | **54 of 2,579 (2.1%)** |

The 54 "matches" are **not** a linkage bug: every one is a **foreign/secondary listing or duplicate
suffix of a symbol we already poll** — e.g. `AAPL.MX`, `AAPL.BA`, `AMZN.SN`, `NVDA.MX`, `INTC.MX`,
`MSFT.BA`, `NYSEARCA:GLD`, `JPM.PRM`. The canonical was minted from the exchange-qualified string in
news text; the base symbol (`AAPL`, `NVDA`, …) is already ingested under a US policy. So this is a
**naming/normalization artifact on ~54 rows, not 2,500 mis-linked rows.**

**Verdict:** Yes — these are genuinely GLiNER/news-extracted securities for which **no ingestion
policy exists** (661 distinct polled symbols vs 2,579 tickerless names; 97.9% have no policy at all).
It is a **coverage gap**, confirming the 2026-06-14 root-cause analysis.

### Name-quality buckets (full 2,579)

| Bucket | Count | Examples |
|--------|------:|----------|
| **company_named** (Inc/Corp/Ltd/Group/… or proper-noun) | **1,691** | `Marvell Technology`, `Citi Trends Inc`, `Samsung Electronics Co. Ltd.`, `Lenovo Group Ltd` |
| **ticker_shaped** (≤6 all-caps, opt. `.XX`) | **664** | `PFFA`, `RIGI`, `NIKE`, `LSEG`, `NEC`, `RDDT.US` |
| **exchange_prefixed** (`NYSEARCA:`, `ENXTPA:` …) | **28** | `NYSEARCA:SHLD`, `ENXTPA:AF` |
| **residual noise** (generic terms, instrument-types, mojibake) | **196** | `ETFs`, `iShares`, `A-shares`, `hedge funds`, `401(k)`, `Asset-Backed Securities`, `AGSTid SecurityImprivata Inc.` |

(Classifier note: a small number of generic terms still leak into `company_named`, e.g. `Treasuries`,
and `REIT`/`NEC` land in `ticker_shaped`; the buckets are directional, not exact. The 196 noise count
is much smaller than a naive scan suggests because most rows ARE real company names.)

### Relevance ranking (internal signals: mentions, articles, relations)

Signals joined from `nlp_db.entity_mentions` (mentions, distinct articles, recency) and
`intelligence_db.relations` (relation count) on `resolved_entity_id = canonical_entities.entity_id`.

| Relevance tier | Count (of 2,579) |
|----------------|-----------------:|
| ≥10 distinct articles | 49 |
| ≥5 distinct articles | 114 |
| ≥2 distinct articles | 364 |
| ≥1 mention | 853 |
| ≥1 graph relation | 255 |
| **0 mentions (dead long tail)** | **1,726 (66.9%)** |

**Two-thirds of the population has zero mentions** — extracted once, never referenced again. These are
not worth ingesting. The signal concentrates in a small head.

**Ingestion-candidate pool** = `company_named` + `ticker_shaped` + `exchange_prefixed` **with ≥1
mention** = **786 entities**, of which:
- **high-relevance (≥5 articles): 96** — 79 company-named, 17 ticker-shaped → the real shortlist
- medium (2–4 articles): 232
- low (1 article): 458

### Zone × market-cap distribution — EODHD step DEFERRED (quota exhausted)

**The EODHD enrichment (step 4) could not run today.** The shared key (`667b…`, identical across
knowledge-graph / content-ingestion / market-data containers) is at its **daily limit**:
`/api/user` reports `apiRequests: 100000 / dailyRateLimit: 100000` for 2026-06-15. Both Search and
Fundamentals return **HTTP 402 "exceeded your daily API requests limit"**. The limit resets at
**00:00 UTC**.

A ready-to-run enrichment script is staged at `/tmp/eodhd_enrich.py` (reads
`/tmp/eodhd_candidates.json`, resolves the top 120 via Search ≥0.62 name-sim, then Fundamentals for
the top 80 resolved → `General.MarketCapitalization` + `CountryName` + `Sector`, with polite delays
and 402/404 handling). Re-run after the quota resets:
`EODHD_KEY=$(docker exec worldview-knowledge-graph-instrument-discovered-consumer-1 sh -c 'printenv KNOWLEDGE_GRAPH_EODHD_API_KEY') .venv/bin/python /tmp/eodhd_enrich.py`.

**Zone hint without EODHD** (parsed from exchange codes embedded in 786 candidate names): only
**21 names carry an explicit exchange code** (15 US, 6 "Other"/LatAm — `.MX`/`.BA`/`.SN`); the other
**765 have no embedded code and require EODHD resolution.** A full zone × cap table therefore cannot
be produced from internal data alone — it is the one part of this analysis blocked on quota.

**Provisional zone read (analyst estimate on the top-40, pending EODHD verification):** the
high-relevance head skews **heavily US large/mega-cap** (Marvell, Nike, Micron, Western Digital,
Deckers, Newmont, GlobalFoundries, Brown-Forman, Super Micro, Redwire, Rigetti) with a **secondary
Asia mega-cap** cluster (Samsung, Toyota, Alibaba, Lenovo, Infineon[EU]) and a thin **Europe** tail
(Roche, LSEG, Coca-Cola Europacific). Almost none are micro-cap — they are well-covered public names
that simply fell outside the 661-symbol seeded universe.

### Top-40 ingestion shortlist (by article coverage)

`zone*`/`cap*` are analyst estimates from public knowledge, **to be replaced by EODHD `Country` +
`MarketCapitalization` when quota resets**. `art` = distinct articles, `ment` = mentions, `rel` =
graph relations.

| # | name | art | ment | rel | bucket | zone* | cap* |
|--:|------|----:|-----:|----:|--------|-------|------|
| 1 | Yahoo TCW | 163 | 170 | 4 | company | US | (merge artifact — verify) |
| 2 | Citi Trends Inc | 64 | 117 | 6 | company | US | micro |
| 3 | Marvell Technology | 60 | 104 | 15 | company | US | large |
| 4 | Investors Title Co. | 53 | 73 | 3 | company | US | small |
| 5 | Amazon com | 51 | 127 | 7 | company | US | mega (likely dup of AMZN) |
| 6 | Alibaba | 37 | 92 | 16 | company | Asia | mega |
| 7 | NIKE | 33 | 133 | 10 | ticker | US | large |
| 8 | Samsung Electronics Co. Ltd. | 31 | 42 | 14 | company | Asia | mega |
| 9 | Invesco AI | 30 | 99 | 7 | company | US | (ETF — verify) |
| 10 | Taylor Morrison Home | 29 | 66 | 12 | company | US | mid |
| 11 | Micron Tech | 28 | 67 | 8 | company | US | large |
| 12 | Oppenheimer | 28 | 50 | 4 | company | US | small |
| 13 | XAI Octagon Floating Rate & Alt Income Trust | 27 | 40 | 10 | company | US | small (CEF) |
| 14 | Toyota | 23 | 69 | 16 | company | Asia | mega |
| 15 | First Interstate BancSystem | 23 | 23 | 4 | company | US | small |
| 16 | Peoples Bancorp | 21 | 21 | 4 | company | US | small |
| 17 | Western Digital | 20 | 77 | 7 | company | US | large |
| 18 | DECKERS OUTDOOR CORP | 17 | 51 | 5 | company | US | large |
| 19 | Marvell | 16 | 34 | 3 | company | US | large (dup of #3) |
| 20 | IREN Ltd. | 15 | 78 | 11 | company | US/AU | mid |
| 21 | GLOBALFOUNDRIES Inc. | 15 | 32 | 7 | company | US | large |
| 22 | Treasuries | 15 | 19 | 0 | (noise) | — | drop |
| 23 | The London Company | 14 | 36 | 2 | company | US | (asset mgr — verify) |
| 24 | Roche | 14 | 30 | 7 | company | Europe | mega |
| 25 | Rigetti Computing | 14 | 22 | 4 | company | US | small |
| 26 | Susquehanna | 13 | 18 | 2 | company | US | (private — verify) |
| 27 | Lenovo Group Ltd | 13 | 16 | 6 | company | Asia | large |
| 28 | First Trust Nasdaq | 12 | 47 | 2 | company | US | (ETF — verify) |
| 29 | REIT | 12 | 17 | 1 | (noise) | — | drop |
| 30 | NEC | 12 | 12 | 0 | ticker | Asia | mid |
| 31 | Redwire | 11 | 42 | 7 | company | US | small |
| 32 | Nebius | 11 | 29 | 3 | company | Europe/NL | mid |
| 33 | Brown-Forman | 11 | 29 | 3 | company | US | large |
| 34 | Coca-Cola Europacific Partners | 11 | 26 | 4 | company | Europe | large |
| 35 | Super Micro | 11 | 24 | 1 | company | US | large |
| 36 | LSEG | 11 | 18 | 0 | ticker | Europe | large |
| 37 | FB Financial | 11 | 11 | 1 | company | US | small |
| 38 | Infineon | 10 | 12 | 1 | company | Europe | large |
| 39 | U.S. Treasuries | 10 | 10 | 2 | (noise) | — | drop |
| 40 | Newmont Mining | 9 | 37 | 2 | company | US | large |

### Synthesis — what fraction is worth ingesting

Of the **2,579** tickerless `financial_instrument` canonicals:

| Segment | Approx count | Action |
|---------|------:|--------|
| **(a) High-relevance real companies / symbols** (≥5 articles, company/ticker-shaped) | **~96** | **Ingest (Tier 1)** — resolve ticker via EODHD, add a polling policy, seed the instrument |
| **(b) Medium-relevance resolvable** (2–4 articles) | ~232 | **Tier 2** — ingest opportunistically after Tier 1 validates |
| **(c) Low-relevance long tail** (1 article or 0 mentions, but real-shaped) | ~1,950 | **Skip** — not worth a policy; leave as graph-only entities |
| **(d) Residual noise** (generic terms / instrument-types / mojibake) | ~196 | **Drop** — sweep to `unknown` (option B of the 2026-06-14 remediation table) |

**Answer to "is it just GLiNER-detected companies we have no ingestion policy for?"** — **Yes,
quantified:** 97.9% have no polling policy; the 2.1% that "match" are foreign-listing duplicates of
already-polled US symbols, not mis-links; 0 were ever enriched/ISIN-resolved. The relevance signal is
**extremely head-heavy** — 66.9% have zero mentions, while a ~96-name head carries the coverage that
matters.

**Zone/cap skew (provisional, EODHD-pending):** the ingestion-worthy head is **predominantly US
large/mega-cap, with a secondary Asia mega-cap cluster (Samsung/Toyota/Alibaba/Lenovo) and a thin
Europe large-cap tail (Roche/LSEG/Infineon/CCEP)** — essentially well-known public companies outside
the seeded 661-symbol universe, **not** an obscure micro-cap long tail. This *strengthens* remediation
**option A** (name→ticker backfill): the high-value targets are exactly the names EODHD resolves most
confidently.

**Recommended ingestion tier:** start with **Tier 1 = the ~96 high-relevance head** (after EODHD
ticker resolution + market-data seeding), drop the ~196 noise rows to `unknown`, and leave the
~1,950-row long tail as graph-only. Re-run `/tmp/eodhd_enrich.py` after 00:00 UTC to fill the exact
zone × cap table and confirm the resolvable symbol for each shortlist row.
