# libs/prompts CHANGELOG

Notable, behaviour-affecting changes to shared prompt templates. Each entry
records the template, the semver bump, and WHY — bumping a judge/grader prompt
breaks longitudinal comparisons in the thesis evaluation, so the change must be
traceable. Content hashes are computed automatically from the template body
(`PromptTemplate.content_hash`); a body edit flips the hash even if the version
is unchanged.

## entity_profile

### 2.2 — 2026-06-13 (FR-12 tickerless-org mis-typing prevention)

- **Added `organization` as an allowed `entity_type`** — a company / agency /
  non-profit / institution that is NOT a tradeable instrument and has no ticker
  (private companies like SpaceX/Anthropic, government bodies like the SEC/Fed,
  universities & research firms like MIT/Zacks/Y Combinator, foundations & NGOs
  like the Duke Energy Foundation). Previously these had no home in the taxonomy
  and were forced into `financial_instrument` (the dominant tickerless-FI
  mistype) or fell through to `unknown`. Paired with intelligence-migrations
  0055, which extends `ck_canonical_entities_entity_type` to 13 values.
- **Tightened the `financial_instrument` definition** to "a TRADEABLE security
  with a ticker (publicly-listed companies)" — it no longer says "companies"
  unqualified, which had taught the model to type any company as an instrument.
- **Added a disambiguation rule (#3):** `financial_instrument` only for tradeable
  securities/tickers; a private company with no confident ticker is
  `organization`, not `financial_instrument`. (The old phrase rule is now #4.)
- **Removed `organization` from the "Do NOT use" list** (it is now canonical);
  reworded the `company` guidance to route to `financial_instrument` (with
  ticker) vs `organization` (without).
- **Impact:** changes the type distribution of newly-minted provisional entities;
  pairs with `provisional_enrichment_core.py` (organization added to the valid
  set + alias map) and the reprofile backfill.

### 2.1 — 2026-06-13 (FR-12 hub mis-typing prevention)

- **Added `exchange` as an allowed `entity_type`** (NYSE, NASDAQ, LSE, Euronext,
  Cboe). Previously no exchange type existed, so every exchange was forced into
  `financial_instrument` (NYSE) or `index` (NASDAQ) — the dominant FR-12 mistype.
  Paired with intelligence-migrations 0053, which extends
  `ck_canonical_entities_entity_type` to accept `exchange`.
- **Removed "Nasdaq" from the `index` exemplar list.** The old definition
  (`index=market indices (S&P 500, Nasdaq, FTSE)`) actively taught the model to
  type the NASDAQ *exchange* as an `index`. The `index` definition now names
  baskets only (S&P 500, Dow Jones, FTSE 100) and explicitly contrasts the
  exchange/index distinction.
- **Added a country-abbreviation rule:** "U.S.", "US", "U.K." etc. are `place`,
  never `currency`; `currency` is reserved for the money unit (USD, EUR).
- **Added an entity-vs-phrase rule:** mentions like "Nvidia shares" / "Microsoft
  Stock" / "stock futures" must resolve to the underlying instrument
  (canonical_name + ticker), not be minted as their own financial_instrument.
- **Impact:** changes the type distribution of newly-minted provisional
  entities; pairs with the `provisional_enrichment_core.py` fallback hardening
  (tickerless company-class -> `unknown`, not `financial_instrument`).

## chat_quality_judge

### 3.0 — 2026-06-12 (BREAKING, PLAN-0110 W3 / PRD-0091 FR-7)

- **DELETED the "PRESUME GROUNDED" instruction.** v2.0 told the judge that
  `status=ok items>=1` was strong evidence and a matching quantitative claim was
  "PRESUMED GROUNDED → award 20-25". That let a fabricated number ride through as
  grounded because the judge had no values to check against.
- Numeric value verification is now **deterministic**: `scripts/chat_quality_judge.py`
  (`cross_check_grounding`) compares every numeric claim against the W2-captured
  `grounding_sample` values and HARD-FAILS contradictions
  (`GROUNDING_CONTRADICTED`) independent of the prompt's soft score.
- The grounding dimension is now a **qualitative** judgement of attribution
  discipline + scope. The prompt grades against a supplied `GROUNDING SAMPLE`
  block when present, and falls back to an explicit **"presumed" band** (saying
  so in feedback) when no sample is supplied.
- The 4-dimension schema and output keys (`feedback`, `reviewer_summary`) are
  **unchanged** from v2.0.
- **Impact:** shifts grounding scores vs v2.0; breaks longitudinal comparison.
  Recorded in `.claude/evals/` and triggers FR-12 recalibration (PLAN-0110 W6).

### 2.0 — 2026-06-08 (BREAKING)

- Per-dimension JSON output key `reason` → `feedback`.
- Top-level `notes` → `reviewer_summary` (≤800-char PR-review paragraph).
- FRAMING dimension rewritten LENGTH-AGNOSTIC (short factual answers score 25).
