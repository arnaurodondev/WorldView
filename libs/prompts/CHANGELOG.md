# libs/prompts CHANGELOG

Notable, behaviour-affecting changes to shared prompt templates. Each entry
records the template, the semver bump, and WHY — bumping a judge/grader prompt
breaks longitudinal comparisons in the thesis evaluation, so the change must be
traceable. Content hashes are computed automatically from the template body
(`PromptTemplate.content_hash`); a body edit flips the hash even if the version
is unchanged.

## morning_briefing

### 4.8 — 2026-06-14 (brief-quality eval — attribution sign gate + tape-line citation)

- **Sentiment-SIGN + same-holding gate on driver attribution (BUG 4).** The
  adversarial eval found causal over-attribution against topically-adjacent
  citations: a holding's driver was grounded on a real, on-topic article whose
  sentiment SIGN contradicted the price move (AMZN −0.88% "explained" by a
  POSITIVE Graviton5 margin article), and unrelated articles were pinned to the
  wrong holding. v4.8 tightens rung 1 of the ladder — a `related: [cN]` article
  may back a holding's driver ONLY IF (a) it is THAT holding's own `related:`
  line (never another holding's, never a general-News article) AND (b) its
  sentiment sign is consistent with the move (a positive article cannot explain
  a down move, and vice-versa). On contradiction the model flags it explicitly,
  downgrades to the sector rung, or falls to "idiosyncratic — no identifiable
  driver". A sign-consistent same-entity article still grants a grounded driver.
- **Market Snapshot tape line carries NO citation (BUG 5).** The SPY/QQQ/VIX
  line is derived from quote/tape data, not an article, but the model attached a
  random run-varying `[cN]` to it. v4.8 instructs that the Market Snapshot line
  carries no `[cN]`; both few-shot examples were re-shot to drop the marker.
- **Singular markers only — no `[cA-cB]` ranges (BUG 5).** The model sometimes
  emitted a range like `[c13-c20]`; v4.8 forbids it (the backend resolver only
  maps a single `[cN]`). Parser-side, `brief_parser._CN_RANGE_MARKER_RE` now
  strips any range marker before resolution so it never leaks to the user.
- **Impact:** flips the content hash; holding drivers are now sign-consistent
  and same-entity-grounded, and the tape line no longer carries a stray citation.

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

### 4.3 — 2026-06-14 (brief-quality eval — citable fundamentals + deterministic staleness)

- **Fundamentals are a CITABLE structured-data source (BUG 2).** The eval found
  the Price & Fundamentals section dropped in EVERY served brief: the LLM ended
  those bullets with the literal `[fundamentals_context]` placeholder token,
  which the parser stripped (it is not a numeric `[cN]`), leaving the bullets
  uncited so `BriefBullet`'s ≥1-citation gate dropped the whole section. The
  formatter now advertises a real `[cN]` index for the fundamentals snapshot
  inside `<fundamentals_context>` and `materialize_brief_citations` appends a
  matching "Fundamentals snapshot (structured data)" citation. v4.3 instructs
  the model to cite that real `[cN]` on Price & Fundamentals bullets and FORBIDS
  emitting `[fundamentals_context]` (or any `[*_context]` token) as a marker.
  Parser-side, a fundamentals-section bullet with no numeric marker is now
  backed by the fundamentals citation rather than dropped (belt-and-braces).
- **Deterministic narrative staleness caveat (BUG 3).** The prior prompt left
  the "add a caveat if >1 week old" decision to LLM discretion, so 25-day-old
  narratives were layered as current themes with no caveat 3/5 runs. The
  narrative `generated_at` is now threaded from S7 onto the context, and the
  formatter injects a `CAVEAT:` clause into the narrative context line
  deterministically when age > 7 days (and unconditionally when the timestamp is
  absent). v4.3 instructs the model to surface that injected caveat when present,
  so the caveat no longer depends on the model.
- **Impact:** flips the content hash; the Price & Fundamentals section renders
  again, and the staleness caveat is present every time the narrative is stale.

### 4.2 — 2026-06-14 (definition-first Entity Overview ordering)

- **Enforced Definition-first ordering in the Entity Overview section.** In live
  tests the LLM opened "Entity Overview" with financial metrics (market cap, P/E,
  revenue) even though the `Definition (business identity)` KG description was
  available. v4.2 adds an explicit `## Entity Overview Section — MANDATORY
  ORDERING` rule that prescribes a three-step sequence: (1) OPEN with the
  Definition — first sentence states what the company IS in plain language, drawn
  from the KG `definition` description and cited; (2) LAYER the narrative —
  competitive position / AI/EV/sector exposure from the `Background thematic
  context`, with its staleness caveat; (3) SUPPORT with fundamentals — market
  cap, revenue, ratios as supporting evidence only, never the opening line.
- **Explicitly forbids opening Entity Overview with financial metrics.** The new
  rule reads: "DO NOT open Entity Overview with a stock price, market cap, P/E
  ratio, or any other financial metric — these belong to 'Price & Fundamentals',
  not the overview." This redirects metric-first behaviour observed in live briefs
  without removing any financial content from the brief.
- **Staleness caveat for narrative preserved.** The `MUST NOT present as a current
  catalyst` instruction from v4.1 is retained unchanged; the new ordering rule
  adds a `[staleness caveat if narrative is >1 week old]` hint alongside it.
- **No other section changes.** LEAD/DETAILS structure, citation rules, style,
  and all other section specs are unchanged.
- **Impact:** flips the content hash; Entity Overview opening sentence now
  describes the business before any financial metric. The 100% citation gate is
  unaffected — both Definition and narrative items carry `[cN]` markers.

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

## chat_trajectory_judge

### 1.0 — 2026-06-25 (NEW — Multi-Level Eval Framework W2, trajectory layer)

- **NEW judge prompt — grades the agent's TOOL-CHAIN PROCESS, not the answer.**
  Complements `CHAT_QUALITY_JUDGE` (which grades the final answer) with a
  trajectory grader that reads the SAME ordered tool trace
  (`call N: tool(args) -> status items=K`) plus the question intent and scores
  four 0-25 sub-dimensions: `routing` (tools fit intent), `ordering` (a chain
  resolves a dependency before consuming it), `recovery` (after a failed/empty
  call the agent retries/substitutes vs gives up/loops), and `efficiency`
  (minimal, non-redundant calls). `trajectory_score = sum(4)` (0-100) is
  computed in `scripts/chat_trajectory_judge.py`, not in the prompt.
- **Strict-JSON output** `{routing, ordering, recovery, efficiency,
  reviewer_summary}` (per-dim `{score, feedback}`), mirroring the answer judge's
  shape. content_hash `eb78317b2115` (computed from the body).
- **Independent of `CHAT_QUALITY_JUDGE`.** The answer grader is NOT modified;
  a unit test asserts `CHAT_QUALITY_JUDGE.content_hash` is unchanged.
- **Impact:** additive only — wired into `run_chat_quality_benchmark.py` behind
  `--trajectory` (default ON when `--judge` is on); it attaches a `trajectory`
  block to each `q_<id>.json` and a `trajectory` roll-up to `_judge_summary.json`
  / the `_report.md` "Trajectory (MUST-2)" section. It does NOT change the
  answer FAIL/PASS verdict. As with any judge prompt, a future body edit flips
  the hash and breaks longitudinal trajectory comparison — record the bump here.

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

## tool_use_system

### 1.14 — 2026-07-06 (synthesis-behavior fixes — valuation-not-a-forecast, attempt-before-refuse, cover-every-entity)

- **C7 — valuation analysis is not a price forecast.** The advice/price-forecast
  disclaimer MISFIRED on a valuation question — "Is GOOGL's P/E expensive vs its
  history?" was refused with "I cannot predict future price movements".
  Valuation-vs-history is retrospective / current analysis of already-known
  multiples, not a forecast of a future asset price. v1.14 adds a
  `NOT A FORECAST — VALUATION ANALYSIS IS ALWAYS ALLOWED` carve-out inside the
  SPECULATIVE FORECASTS block: any multiple (P/E, forward P/E, PEG, EV/EBITDA,
  P/B, P/S, EV/sales, dividend yield) judged expensive/cheap vs the entity's own
  history, its peers, or the market MUST be answered, never refused. The hard-
  refuse asset-price-direction case (A) is unchanged.
- **A5 — attempt before refusing.** A well-scoped numeric lookup
  (`apple_revenue_precision`) was REFUSED without the model calling ANY tool.
  v1.14 adds an `ATTEMPT BEFORE REFUSING` rule to STRICT RULES: for a well-scoped
  financial/factual question the model MUST call the relevant tool FIRST (per the
  TOOL ROUTING table); "no data" is a valid answer only AFTER a tool actually ran
  and returned zero rows or errored — never as a first move. The one exception is
  a hard-refuse asset-price-direction forecast.
- **A4 — a comparison covers every named entity.** A comparison DROPPED a
  requested entity ("NVIDIA is not relevant here" on an NVDA-vs-AMD question) and
  invented a scope narrowing. v1.14 adds a `COVER EVERY ENTITY (mandatory)` rule
  to the COMPARISON addendum: every entity the user named must be addressed, a
  self-authored exclusion is forbidden, and an entity with thin data is reported
  (with the gap stated), never deleted.
- **Impact.** Flips the content hash. Additive; no grounding / anti-fabrication /
  citation rule is relaxed. Consistent with chat_synthesis_system v1.12 (same
  three fixes on the synthesis turn).

### 1.13 — 2026-07-05 (narrow the price-forecast refusal — allow grounded conditional what-if impact)

- **Root cause.** The `SPECULATIVE FORECASTS — MUST REFUSE` rule (added by
  FIX-LIVE-Z after adversarial QA caught the agent answering "Will Tesla stock
  go up?" with "will go up") refused ALL forward-looking directional statements.
  Correct for bare price predictions, but it ALSO over-refused legitimate
  CONDITIONAL what-if IMPACT analysis where a price/cost move is the USER'S
  stated premise (e.g. "if wafer prices rise 10%, what's NVIDIA's gross-margin
  impact?") — the owner's headline use case, which must be ANSWERED.
- **Narrowed into two crisp cases.** v1.13 splits the rule along ONE boundary —
  reason about IMPACT given a stated hypothetical move (ALLOWED) vs predict an
  asset's OWN price movement (REFUSED):
  - **(A) STILL HARD-REFUSE** — forecasting the direction of an ASSET's own
    price/return/level: "will X go up/down", price targets, "where will it
    trade", "is it going to rally/crash", buy/sell/hold recommendations
    ("should I buy X"). The FORBIDDEN-PHRASE enumeration and canonical refusal
    ("I cannot predict future price movements") are UNCHANGED for this case.
  - **(B) NOW ALLOW** — grounded conditional what-if IMPACT analysis: reasoning
    about the DOWNSTREAM fundamental impact (margin/revenue/EPS/cost) of a
    hypothetical operational/cost/price move the USER supplies as a premise.
    Requirements: (a) the move is the user's assumption, not a forecast the
    model originates; (b) the impact is DERIVED from cited retrieved figures and
    shown; (c) every projected value is hedged/scenario-labelled per the
    numeric-grounding gate; (d) the answer must NOT then predict the asset's
    stock-price direction.
- **Consistency.** This mirrors `chat_synthesis_system` v1.9's `ANALYTICAL /
  WHAT-IF` block and `_safety.py` SAFETY_FOOTER rule 5, which already permit a
  grounded, hedged, explicitly-derived what-if projection. No blanket
  forecast-ban remained in synthesis.py/_safety.py, so no change was needed
  there — the over-refusal lived only in this planning-turn prompt.
- **Scope.** NARROW + additive: only the SPECULATIVE FORECASTS section changed;
  the REASONING RIGOR / ANTI-FABRICATION / grounding / citation rules are
  untouched. Flips the content hash.

### 1.12 — 2026-07-03 (general parallel tool batching + deeper analyst reasoning)

- **Point 1 — RESEARCH LOOP (general parallel batching).** The "single
  parallel planning turn" rule previously lived only inside the FINANCIAL_DATA
  `VALUATION CONTEXT` addendum, so it fired only for expensive/cheap/overvalued
  questions. General questions (news + intelligence + fundamentals + graph)
  fanned out ONE tool per ~6s reasoning round — measured 5 rounds / 31.5s of
  planning for a query that needed only 3 independent tools. v1.12 promotes the
  rule to a CORE (all-intent) `RESEARCH LOOP — PLAN WIDE, THEN GO DEEP` section:
  ROUND 1 must batch every INDEPENDENT tool the question already determines
  (get_entity_news + query_fundamentals/get_fundamentals_history + search_events
  + traverse_graph/search_entity_relations) in a single parallel `tool_calls`
  block. The ADAPTIVE loop is explicitly PRESERVED — ROUND 2+ is reserved for
  follow-up whose args are only knowable from earlier results (round-1 news
  surfaces a supplier -> round-2 graph query for that supplier), so parallelism
  does not collapse the analyst reasoning. The `VALUATION CONTEXT` addendum now
  cross-references this core rule as a specific instance.
- **Point 2 — ANALYST REASONING (deeper multi-step investigation).** The owner
  found investigations "pretty simple". v1.12 adds a core `ANALYST REASONING`
  section elevating the loop to senior-analyst behaviour: (1) form 2-3 explicit
  falsifiable HYPOTHESES and pick tools that confirm/refute each; (2) chase
  SECOND-ORDER IMPLICATIONS (supplier margin -> customer input cost -> customer
  guidance risk; rate cut -> discount rate -> high-duration re-rating);
  (3) CONNECT ENTITIES ACROSS TOOLS for cross-tool corroboration; (4) ADAPTIVE
  DEPTH — each round's results choose the next round's tools; (5) SYNTHESISE,
  THEN STOP, saying which hypotheses the data supported.
- **Grounding preserved.** A closing `GROUNDING IS ABSOLUTE` clause re-asserts
  that every reasoning step is about tool data only and that deeper reasoning
  NEVER licenses an ungrounded or fabricated claim — an untested hypothesis must
  be surfaced as an open question, never as a finding. All prior STRICT
  RULES / FORBIDDEN / NO NARRATION / citation rules are **unchanged**; the
  reasoning stays INTERNAL (never narrated). Body edit flips the content hash.

### 1.11 — 2026-07-01 (prediction-market citation-refusal — real-tool-name-only labels)

- Live QA found prediction-market chat answers returning an EMPTY `citations`
  array (and sometimes a refusal) even though the correct polymarket.com URLs
  were inline in the prose. Root cause: the model tagged its own interpretive
  commentary with a NON-TOOL bracket label — `[commentary row N]` — abutting a
  material number (an implied-odds %). The phantom-citation gate
  (`partition_phantom_tool_citations`) correctly reads a `[name row N]` tag whose
  `name` is not a called tool, next to a material figure, as a fabricated
  citation and fires `numeric_grounding_phantom_citation_refused`.
- v1.11 adds a REAL-TOOL-NAME-ONLY rule to the CITATIONS section: every
  `[<name> row N]` provenance tag MUST name a tool that actually ran; non-tool
  labels (`[commentary row N]`, `[analysis row N]`, `[note row N]`) are forbidden;
  interpretive commentary is unsourced prose that carries NO bracketed
  row-citation. The COMPARISON "interpretive commentary" line is clarified to
  carry NO row-tag (only the table's numeric cells do).
- The fix makes the MODEL stop emitting non-tool labels so legitimate
  tool-backed citations survive. The phantom-citation / numeric-grounding
  refusal guard in `rag-chat` is **UNCHANGED** — it stays strict and still
  refused a real Bitcoin/Fed hallucination in the same QA session.
- All prior strict-no-hallucination rules are **unchanged**.

### 1.10 — 2026-06-27 (FINAL-67 C4 — tool routing)

- Added the **TOOL ROUTING** table to the planning-turn prompt. The FINAL-67 run
  found `search_documents` over-selected as a generic catch-all while the
  purpose-built tools were under-selected, looping empty searches into refusals:
  `da_mstr_news_dec2024` never tried `get_entity_news`,
  `iter3_apple_competitors_spanish` routed competitors to `get_entity_graph`, and
  `tc_search_events_semi_earnings_beats` never called `search_events`.
- v1.10 maps question shape to the FIRST tool — 'latest news about X' ->
  `get_entity_news`, 'competitors of X in <sector>' -> `compare_entities`,
  '<sector> events/earnings beats' -> `search_events`, relations -> `traverse_graph`
  / `search_entity_relations`, numbers -> `query_fundamentals` — and demotes
  `search_documents` to an explicit fallback for open-ended free-text only.
- All prior strict-no-hallucination rules are **unchanged**.

## chat_synthesis_system

> Note: CHANGELOG entries for v1.8–v1.11 were not recorded here at the time; the
> full rationale for each lives in the version-log comments in
> `src/prompts/chat/synthesis.py`. v1.12 below resumes the CHANGELOG.

### 1.12 — 2026-07-06 (synthesis-behavior fixes — trust ok results, valuation-not-a-forecast, cover-every-entity)

- **A1 — trust a status=ok tool result; gate the canned no-data refusal.** The
  SYNTHESIS turn emitted "I couldn't retrieve any data" despite a status=ok tool
  result above it — `create_alert` SUCCEEDED (alert created) / a relations search
  RETURNED rows, but synthesis discarded them and refused. The earlier defeatist-
  patch (520f130ba) only covered the grounding-REWRITE path, leaving this
  SYNTHESIS path uncovered. v1.12 strengthens the TRUST YOUR TOOL RESULTS block:
  the canned no-data phrasings ("I couldn't retrieve any data", "no data is
  available", …) are now EXPLICITLY GATED to the case where EVERY tool returned
  empty/errored — forbidden while ANY status=ok / non-empty result is present.
  The model must report the returned rows/values, or, for an action tool, confirm
  the action succeeded.
- **C7 — valuation analysis is not a price forecast.** A valuation question ("Is
  GOOGL's P/E expensive vs its history?") was refused as a price forecast. v1.12
  extends the factual-lookup-not-a-prediction bullet to EXCLUDE valuation
  multiples (P/E, EV/EBITDA, expensive/cheap vs history/peers) from the
  price-forecast refusal — they are retrospective / current analysis of
  already-known numbers, always allowed. Mirrors `tool_use_system` v1.14.
- **A4 — a comparison covers every named entity.** A comparison dropped a
  requested entity ("NVIDIA is not relevant") and invented a scope narrowing.
  v1.12 adds the `COMPARISON / MULTI-ENTITY — COVER EVERY ENTITY NAMED` block:
  every named entity must be addressed, a self-authored exclusion is forbidden,
  and thin data is reported (with the gap stated) rather than dropped.
- **Impact.** Flips the content hash. Additive; the v1.9 what-if permission,
  v1.10 reasoning-rigor, v1.11 data-coverage boundary, and all no-fabrication /
  grounding / projection rules are unchanged.

### 1.7 — 2026-07-01 (prediction-market citation-refusal — real-tool-name-only labels)

- Same root cause as `tool_use_system` v1.11 (above), on the delivery-time
  synthesis prompt: the model emitted a NON-TOOL `[commentary row N]` label next
  to material odds numbers, which the phantom-citation gate classified as a
  material fabrication → `citations=[]` + refusal despite correct inline URLs.
- v1.7 adds the **CITATION LABELS — REAL TOOL NAMES ONLY** block: every bracketed
  `[<tool_name> row N]` must be an ACTUAL tool that ran; non-tool labels
  (`[commentary row N]`, `[analysis row N]`, `[note row N]`, `[source row N]`,
  `[interpretation row N]`) are forbidden; interpretive commentary/synthesis is
  UNSOURCED prose with NO bracket tag; prediction-market odds/probabilities/prices
  cite `[get_prediction_markets row N]`.
- The numeric-grounding / phantom-citation refusal guard is **UNCHANGED** —
  this is a MODEL-behaviour fix so legitimate tool-backed citations are the only
  bracketed labels emitted. Every 1.6 win (PERIOD-MATCHING, anti-fabrication
  policy, digit-for-digit copy, report-in-full balance) is preserved.

### 1.6 — 2026-06-28 (Cat-A period-selection)

- The v1.5 finding-run still showed the model **selecting / labelling the wrong
  fiscal period** from a payload that already carried correct labels
  (`docs/audits/2026-06-28-cat-a-period-selection.md`): it scrambled Q1–Q4 by row
  position (`da_tsla_revenue_2024_full_year`), invented/mislabelled fiscal years
  and padded extra quarters (`ru_nvda_amd_revenue_4q`), and substituted the
  nearest September quarter under a requested-but-absent label
  (`da_apple_revenue_fy2024q4_precision` — Q4 FY2024 outside the returned window).
  The tool labels themselves were correct; the missing guardrail was a
  period-binding directive (cause (d)).
- v1.6 adds the **PERIOD-MATCHING** block: bind every figure to its row's OWN
  period label / `period_end`; never map rows to quarters by position; and — when
  the requested period is **absent** from the returned window — say so and name
  the closest available period the tool DID return, rather than relabelling the
  nearest quarter (a real number under the wrong period label is still a
  fabrication).
- Adds a **long-series steer** (report first/last/high/low/range over N rather
  than enumerating every bar) for the C1-companion price-history case.
- **Additive:** keeps every v1.5 win (ANTI-FABRICATION POLICY, digit-for-digit
  copy, report-in-full balance, TRUST YOUR TOOL RESULTS). Backed by the
  deterministic period-presence guard in the rag-chat orchestrator (FIX 2) and the
  off-payload-ticker guard (FIX 3) for the financial-correctness backstop.

### 1.5 — 2026-06-28 (RC-2 anti-fabrication policy)

- The v1.4 finding-run grounding-floor root-cause
  (`docs/audits/2026-06-28-grounding-floor-rootcause.md`, RC-2) found the answer
  LLM still **fabricating** along three axes: (1) inventing missing
  quarters/rows from a single-period fundamentals payload (8 questions, e.g.
  `ru_nvda_amd_revenue_4q`, `da_tsla_revenue_2024_full_year`); (2) padding a
  screener result with off-payload mega-cap tickers it never returned (MRVL,
  UBER, SHOP, CRM — `ru_ai_semi_screener`, `iter3_top5_tech_marketcap`); and
  (3) claiming returned scalar fields were "missing" (`high`/`low` present in
  `tc_price_history_msft_ytd_range`; `status=ok` over-refusals).
- v1.5 adds the **ANTI-FABRICATION POLICY** block with three explicit rules:
  (1) never invent periods/quarters/rows — report the single returned period in
  full + state the series is unavailable; (2) never add entities absent from a
  tool result; (3) read the returned scalar fields before declaring data missing,
  declining only the genuinely-absent field.
- **Balance preserved (does NOT fight v1.4):** each rule carries the v1.4
  counter-instruction — "report every value the tools DID return, in full, with
  its citation; refuse ONLY the specific part that is genuinely unavailable,
  never the whole answer." This is anti-fabrication, not anti-answering; all v1.4
  wins (digit-for-digit copy, report-in-full, keep-the-tag, TRUST YOUR TOOL
  RESULTS) are unchanged.

### 1.4 — 2026-06-28 (FINAL-67 grounding regression — soften C1)

- v1.3's "TRANSCRIBE, DO NOT COMPUTE" block OVER-corrected. Two read-only audits
  (`docs/audits/2026-06-28-grounding-regression-{map,mechanism}.md`) converged:
  the blanket "do NOT infer/extrapolate/build a time series" plus the "prefer
  saying 'not in the retrieved data' over supplying a number" escape hatch made
  the answer LLM WITHHOLD, shrink, and wrongly REFUSE data the tools handed it.
  `GROUNDING_FLOOR` 7→16, `substantiated_n` 56→47, while `unsupported_n` stayed
  0 — i.e. shrinkage/refusal, NOT fabrication. Answers also dropped inline
  citation tags, so correct numbers read as ungrounded. Flagship
  `iter3_msft_earnings_citations` went 100→5 (wrongful refusal of a
  `query_fundamentals` result that returned `items=1`).
- v1.4 **keeps** the digit-for-digit copy rule (the part that helped —
  `unsupported_n` stayed 0), **narrows** "don't build a series" to ONLY the
  periods the tool did not return (never a reason to omit returned periods),
  **removes** the "prefer 'not in the retrieved data'" refusal escape hatch, and
  **adds** a counter-instruction: report every groundable value IN FULL WITH its
  inline `[tool_name row N]` citation tag — never refuse, hedge, shorten, or drop
  attribution on data you can ground.
- The C1 #1 numeric pin and #2 fabricated-series gate (product code) are
  **unchanged** — both were exonerated by the audits (pin fired 9× and helped,
  gate fired 0×).

### 1.3 — 2026-06-27 (FINAL-67 C1 — transcribe, don't compute)

- Added the **TRANSCRIBE, DO NOT COMPUTE** block. The dominant FINAL-67
  grounding-floor failure (8 of 14 FAILs) was the answer LLM altering numbers it
  already had: rounding $111.184B -> $111.200B
  (`da_apple_revenue_fy2024q4_precision`), fabricating a 6-quarter trajectory from
  a single-period snapshot (`ru_nvda_amd_revenue_4q`), and carrying one entity's
  revenue onto another (`da_nvda_amd_compare_fy2024q3`).
- v1.3 requires copying every figure digit-for-digit from the tool result,
  forbids rounding/extrapolating/annualising, forbids inventing a period or
  series the tool did not return, requires every derived figure's inputs to be
  present, and requires an explicit "not in the retrieved data" statement instead
  of a substitute number.
- The product-side numeric-grounding validator (chat_orchestrator) still backs
  this prompt rule as defence-in-depth.

### 1.2 — 2026-06-27 (FINAL-67 C3 — trust-your-tool-results)

- Added the **TRUST YOUR TOOL RESULTS** block to the synthesis-turn prompt. The
  FINAL-67 run found the INVERSE of fabrication: the answer LLM refused or denied
  capability despite a successful / non-empty tool result.
  `tc_price_history_msft_ytd_range` refused ("data does not contain the daily
  high or low") when the tool row carried `high=489.7, low=356.28`;
  `tc_create_alert_nvda_below` denied it could set price alerts ("not permitted")
  after `create_alert` returned `status: ok`.
- v1.2 forbids claiming a value is "unavailable/not included" when it is present
  in a tool result, requires confirming an action when its tool returned success,
  and instructs that a price/high-low/past-value lookup is factual — NOT
  speculation to be refused.
- The `{safety}` parameter, FORBIDDEN narration block, and GROUND EVERY ROW
  anti-fabrication block are **unchanged**.

### 1.1 — 2026-06-26 (platform quality failure-analysis #3 — anti-fabrication)

- Added the **GROUND EVERY ROW** block to the synthesis-turn prompt. The 2026-06-26
  chat-quality run found fabrication beyond tool results: a tool returns 1 row, the
  answer asserts N (`iter3_top5_tech_marketcap`, `agg_q5_tsla_macro`,
  `iter3_msft_earnings_citations`), inventing plausible rows with `[tool row N]`
  citations that do not exist in the trace.
- v1.1 hard-constrains the answer to EXACTLY the rows/values the tools returned,
  forbids emitting a `[tool_name row N]` citation for a row index a tool did not
  return, and requires an explicit shortfall statement when fewer items came back
  than the question asked for.
- Companion product guard: `chat_orchestrator` strips/flags citation row-indices
  not present in the returned trace before the answer is sent.
- The `{safety}` parameter and FORBIDDEN narration block are **unchanged**.
