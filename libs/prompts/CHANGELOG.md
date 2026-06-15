# libs/prompts CHANGELOG

Notable, behaviour-affecting changes to shared prompt templates. Each entry
records the template, the semver bump, and WHY — bumping a judge/grader prompt
breaks longitudinal comparisons in the thesis evaluation, so the change must be
traceable. Content hashes are computed automatically from the template body
(`PromptTemplate.content_hash`); a body edit flips the hash even if the version
is unchanged.

## morning_briefing

### 4.7 — 2026-06-14 (PRD-0030 causal-attribution slice, P2)

- **Added a per-holding DRIVER ATTRIBUTION ladder.** The prior brief restated
  price moves the user can already see and filled the "why" gap with fabricated
  guesses ("TSLA +3.17% — no direct news; momentum-driven move"). v4.7 makes the
  LLM walk a ladder per holding: (1) ENTITY NEWS — attribute to a fed
  `related: [cN]` story and cite it; (2) SECTOR/PEER — attribute to the fed
  `sector:` line with hedged language; (3) MACRO/EVENT — attribute to a fed
  macro print; (4) IDIOSYNCRATIC — only when NEITHER a `related:` nor a
  `sector:` line exists, write exactly "idiosyncratic — no identifiable driver".
- **Forbade speculative filler.** "momentum-driven", "may be riding", "no
  catalyst confirmed", and generic "tracking the broader market" are now
  explicitly banned; ungrounded moves must read "idiosyncratic".
- **Documented the new per-holding context shape.** The gatherer
  (`briefing_context.py`, PRD-0030 P0/P1) now fans out the per-entity articles
  call across holdings and joins per-holding sector returns from the market
  heatmap; the formatter renders `related: [cN] <headline> (sentiment, rel%)`
  and `sector: <Sector> +X.XX%` lines beneath each holding's price.
- **Marker-convention fix [N#] → [cN]** (correctness, not cosmetic). The backend
  resolver `brief_parser._CN_CITATION_RE` only matches `[cN]`; the prior prompt
  instructed `[N#]`, so morning-brief per-bullet citations were stripped as
  orphans and never resolved to a source. v4.7 standardises on `[cN]` in the
  citation rules, the summary directive, and both few-shot examples.
- **Impact:** flips the content hash; holding lines now carry grounded,
  resolvable citations instead of unresolved guesses. The
  `rag_citation_accuracy_24h` judge will validate that the new attributions are
  grounded in the cited snippet.

## instrument_briefing

### 4.1 — 2026-06-14 (PLAN-0107 follow-up — brief vector descriptions, P1)

- **Fed two KG "vector" descriptions into the instrument brief's entity context.**
  The KG stores three per-entity descriptions in
  `intelligence_db.entity_embedding_state.source_text` keyed by `view_type`. v4.1
  surfaces two of them in the `<entity_context>` block:
  - `Definition (business identity)` — the `definition` view (what the company
    IS). Already returned to rag-chat on the egocentric graph's center node as
    `EntityPublic.description`; previously the "Entity Overview" section was
    written from a ~3-line name/type/ticker stub and never used it. Now threaded
    through `EntityGraphSnapshot.description` → `format_entity_context`.
  - `Background thematic context` — the `narrative` view (LLM-generated:
    competitors, AI/EV exposure, strategic position). Fetched in parallel inside
    `gather_instrument_context` via `S7IntelligenceClient.get_narrative` into the
    new `BriefingContext.entity_narrative` slot.
  - The `fundamentals_ohlcv` view is intentionally NOT added — it is redundant
    with the brief's existing structured fundamentals.
- **Added "Using Entity Definition & Background Context" guidance.** The model is
  instructed to use the definition for the "what this company is / why it matters"
  framing of the Entity Overview, and to treat the narrative as BACKGROUND only.
- **Staleness caveat for the narrative.** The narrative is regenerated on a weekly
  (Sunday) cadence, so it can be ~1 week+ stale. Both the formatter label and the
  prompt explicitly flag it as "may be up to ~1 week old; not a recent catalyst"
  so the LLM never presents it as a current catalyst / today event. Recent
  catalysts come only from the news + events blocks.
- **Impact:** flips the content hash; the Entity Overview section is now written
  from real KG identity + thematic context instead of a 3-line stub. Both items
  are cited via their `[cN]` markers like any other context item, preserving the
  100% bullet-level citation gate. No backend schema or API changes.

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
