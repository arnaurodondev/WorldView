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
