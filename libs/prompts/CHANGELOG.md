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

### 1.21 — 2026-07-09 (Area-2 harder projections — P2 light projection-scaffold routing rule)

- **PROJECTION / WHAT-IF SCAFFOLD on the REASONING addendum.** Planning-turn
  companion to `chat_synthesis_system` v1.19 (which resolves the
  anchor-vs-scenario-parameter conflict on the synthesis turn). The block tells
  the planner to RETRIEVE the base ANCHOR figures first (revenue / margin / EPS /
  cost, via the entity's fundamentals / intelligence tools — a what-if about a
  named entity still needs its base figures, per the STRICT-RULES `WHAT-IF /
  PROJECTION` mandate) but to recognise a SCENARIO PARAMETER (a TAM, served market
  size, segment share, or cost-share the derivation multiplies by) as a MODELLING
  ASSUMPTION the tools do not carry — so it must NOT loop tools hunting for it and
  must NOT treat its absence as a reason to refuse; the synthesis turn supplies it
  as a clearly-labelled low–high assumption.
- **Impact.** Flips the content hash (REASONING addendum body edit). Additive +
  light; no grounding / refusal / routing rule is relaxed. Source:
  `docs/plans/2026-07-09-chat-enhancement-roadmap.md` Area 2 (P2).

### 1.20 — 2026-07-08 (SOFTEN the hypo regression — mandatory tool on entity what-ifs)

- **WHAT-IF / PROJECTION ABOUT A NAMED ENTITY ⇒ CALL ITS TOOL FIRST.** The
  softening re-run `run_20260708T211838Z` showed the projection/what-if bucket
  dropping to ZERO tool calls (`fx`, `asp` what-ifs): the planner answered a
  conditional impact question about a named entity straight from parametric
  memory instead of first retrieving the base figures the projection must rest
  on. The v1.17 `TOOL CALL IS MANDATORY FOR ENTITY / PORTFOLIO DATA` rule did not
  fire because a "what if …" framing does not read as a plain entity-DATA
  question, and v1.13's ALLOWED conditional-what-if case did not restate the tool
  obligation. v1.20 adds a `WHAT-IF / PROJECTION ABOUT A NAMED ENTITY ⇒ CALL ITS
  TOOL FIRST` rule to STRICT RULES: a conditional / hypothetical /
  second-order-impact question about a named entity (margin, revenue, EPS, cost,
  ASP, FX exposure under a hypothetical move) MUST call `query_fundamentals` /
  `get_fundamentals_history(_batch)` / `get_entity_intelligence` FIRST to retrieve
  the base figures — a zero-tool memory projection is the SAME hard failure as any
  other zero-tool entity-data answer. Explicitly NOT a licence to forecast the
  asset's own price direction (hard-refuse case (A) intact).
- **Impact.** Flips the content hash. SOFTENING half of the same regression the
  `chat_synthesis_system` v1.18 `DO-NOT-OPEN-WITH-A-REFUSAL-LINE` bullet fixes;
  additive, no grounding / refusal rule is relaxed. Source:
  `docs/plans/2026-07-08-chat-quality-two-track-audit.md`, run_20260708T211838Z.

### 1.19 — 2026-07-08 (chat-quality two-track audit, Track-3 planning fixes — multi-hop traversal + dedup)

- **COMPOUND / MULTI-HOP / RIPPLE routing entry.** Compound, supply-chain, and
  ripple questions ("X's suppliers and THEIR key customers", "who does X's main
  supplier ALSO sell to", "second-order exposure to <event> through the supply
  chain") were answered ONE hop short — the model listed direct suppliers and
  never traversed to the next link. A single `search_entity_relations` call does
  not multi-hop; `traverse_graph` does. v1.19 adds a TOOL ROUTING entry forcing
  `traverse_graph` with enough hops to reach the terminal entity the question
  names, explicitly forbidding a stop at the first hop and requiring the model to
  reason over the whole path.
- **NO REDUNDANT TOOL CALLS rule (RESEARCH LOOP).** The loop was observed calling
  the SAME tool with the SAME arguments up to 5× in one turn
  (`chain_portfolio_upcoming`, `cmp_tsmc_intel`) — wasted rounds, latency, and
  cost with no new information (an identical call always returns the same result).
  v1.19 forbids repeating an identical call: a follow-up is warranted only when at
  least one argument changes or a prior round surfaced a genuinely new entity, and
  an empty/errored call must use the FALLBACK rule (a different tool/args), never
  an identical retry.
- **Impact.** Flips the content hash. Additive; no grounding / routing / refusal
  rule is relaxed. Track-3 PASS-ceiling work from the
  `2026-07-08-chat-quality-two-track-audit` (run_20260708T093242Z).

### 1.18 — 2026-07-08 (first-person portfolio-exposure routing — kill the fabricated get_portfolio_context gate)

- **FIRST-PERSON PORTFOLIO clause + TOOL ROUTING entry.** `port_semis_export_exposure`
  ("Which of my holdings are most exposed to the latest semiconductor
  export-control news?") RE-FAILED under v1.17 with zero tools — but not from
  memory this time: the model REFUSED, self-justifying with a FABRICATED gate,
  "I cannot call `get_portfolio_context` unless you explicitly ask about your
  portfolio, holdings, or watchlist", and treated the export-control-news framing
  as a general/macro question. There is NO such gate. v1.18 adds a `FIRST-PERSON
  PORTFOLIO ⇒ get_portfolio_context IS MANDATORY` clause to the mandatory-tool
  rule: a first-person possessive about the user's own book ("my holdings /
  positions / portfolio", "which of my …", "am I exposed", "how exposed am I")
  IS the trigger, TRUE EVEN WHEN framed around news / an event / a policy /
  export-control / a macro theme — the framing does NOT make it a
  general-knowledge question. The prompt explicitly rebuts the invented
  "explicit portfolio keyword" gate and forbids "I don't have access to your
  holdings" before calling the tool ("the tool IS your access"). A matching
  `TOOL ROUTING` entry routes first-person portfolio/exposure questions to
  `get_portfolio_context` FIRST, then chains to `get_entity_news` /
  `search_documents` / `search_events`.
- **Impact.** Flips the content hash. Additive; no grounding / anti-fabrication /
  citation rule is relaxed. Builds directly on v1.17 (same eval question, harder
  refusal failure mode).

### 1.17 — 2026-07-08 (no-tools routing — mandatory tool call for entity/portfolio data questions)

- **TOOL CALL IS MANDATORY FOR ENTITY / PORTFOLIO DATA rule.**
  `iter3_apple_competitors_spanish` ("¿Cuáles son los principales competidores de
  Apple…?") and `port_semis_export_exposure` ("Which of my holdings are most
  exposed to the latest semiconductor export-control news?") were both answered
  with ZERO tool calls (judge: `no_tools_called`, expected `[compare_entities,
  get_entity_intelligence]` and the portfolio/news/graph set respectively). The
  model did not refuse — the A5 `ATTEMPT-BEFORE-REFUSING` rule handles that — it
  answered a competitors / portfolio-exposure question straight from parametric
  memory, producing an ungrounded, unverifiable answer (and the Spanish phrasing
  did not change the obligation). v1.17 adds a `TOOL CALL IS MANDATORY FOR ENTITY
  / PORTFOLIO DATA` rule to STRICT RULES: any question about an entity's or
  portfolio's DATA — competitors/peers, suppliers/supply-chain, exposure/risk,
  holdings/positions, screening/ranking, relationships, news, events, or
  fundamentals — MUST call the relevant tool(s) first (in ANY language); a
  zero-tool answer from memory is a HARD FAILURE. It is explicitly distinguished
  from a refusal and complements A5 (which covers refuse-without-trying).
- **Impact.** Flips the content hash. Additive; no grounding / anti-fabrication /
  citation rule is relaxed. Pairs with chat_synthesis_system v1.16 (the
  partial-row field-fabrication fix from the same eval run).

### 1.16 — 2026-07-07 (iter3_msft_earnings_citations — latest-earnings periods>=4, never periods=1)

- **LATEST / MOST-RECENT EARNINGS periods rule.** "What was Microsoft's most
  recent earnings report?" (`iter3_msft_earnings_citations`) routed correctly to
  `query_fundamentals` (D5, status=ok, 1 item) but the planner picked
  `periods=1`. `periods=1` returns ONLY the newest fiscal quarter — for a company
  that has not yet reported it, that is a future-dated placeholder row whose
  revenue / net_income / eps / gross_margin cells are all null. Synthesis saw
  status=ok / 1 item with no figures and blanket-refused "not available" for every
  metric (judge grounding=10, wrongful refusal). This is the same null-placeholder
  failure the `RATIO-OR-TTM` directive (periods>=5) already guards against, but it
  slipped through on the plain latest-earnings (non-ratio, non-named-period) path.
  v1.16 adds a `LATEST / MOST-RECENT EARNINGS` rule to the FINANCIAL_DATA addendum:
  a latest / current-quarter earnings question with NO named past period MUST
  request `periods >= 4` (never `periods=1`) so the last REPORTED quarter with real
  figures is in the payload; report that most-recent reported quarter.
- **Impact.** Flips the content hash. Additive; no grounding / anti-fabrication /
  citation rule is relaxed. Pairs with chat_synthesis_system v1.14 (the
  synthesis-turn half — an all-null newest-quarter row must not collapse into a
  blanket refusal).

### 1.15 — 2026-07-06 (eval FAIL routing fixes — date-anchored fundamentals args, earnings→fundamentals routing + fallback)

- **D3 — date-anchored fundamentals arguments (highest-leverage prompt fix).**
  `get_fundamentals_history(periods=N)` returns the LATEST N quarters (anchored
  on "now" ≈ 2026). A question naming a specific past period
  (`da_tsla_revenue_2024_full_year`, `da_nvda_amd_compare_fy2024q3`) answered
  with `periods=N` got 2025-26 quarters and missed the 2024 target → the model
  fabricated 2024 labels or refused, even though the 2024 rows exist via
  `from_date`/`to_date`. v1.15 adds a `DATE-ANCHORED ARGUMENTS` rule to the
  FINANCIAL_DATA addendum: a named past quarter / period-end / calendar-or-fiscal
  year MUST be bounded with `from_date`/`to_date` (or `date_from`/`date_to`),
  never `periods=N`; with a worked TSLA FY2024-Q4 example. `periods=N` is
  reserved for latest / most-recent windows.
- **D5 — earnings ⇒ fundamentals routing + fallback-before-refuse.** "What did
  MSFT report / earnings figures for FY2024-Q4" (`da_msft_fy2024q4_earnings_citations`,
  `iter3_msft_earnings_citations`) routed to `get_filings` / `search_events`
  (empty) then refused — but the reported earnings NUMBERS live in the
  fundamentals tools, not in filings/events (which carry only the narrative +
  citation). v1.15 adds a TOOL ROUTING line routing earnings-report /
  reported-numbers questions to `query_fundamentals` / `get_fundamentals_history`
  first (filings/news add citation/context only), plus a `FALLBACK BEFORE
  REFUSING` rule: an empty/errored FIRST tool MUST trigger the next-best tool
  before any refusal.
- **Impact.** Flips the content hash. Additive; no grounding / anti-fabrication /
  citation rule is relaxed. Consistent with chat_synthesis_system v1.13 (the
  synthesis-turn half of the same eval FAIL analysis: D7/D8/D4).

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

### 1.19 — 2026-07-09 (Area-2 harder projections — anchor-vs-scenario-parameter split)

The owner's headline what-if use case still FAILED on scenario-parameter
projections. Root cause (`docs/plans/2026-07-09-chat-enhancement-roadmap.md`
Area 2): the `ANALYTICAL / WHAT-IF` block held an unresolved conflict — "never
refuse a projection once you hold base figures → give a hedged range" AND "never
invent the missing input" — but never distinguished an **anchor fact** (AMD
revenue, NVDA margin: MUST retrieve + cite, no fabrication) from a **scenario
parameter** (TAM, market size, segment share, cost-share: a *modelling
assumption*, not a claimable fact). When the only path to a projected number ran
through a scenario parameter, the model mis-classified it as forbidden anchor-fact
fabrication and REFUSED (`hypo_amd_datacenter_share_revenue`,
`hypo_amd_mi_accelerator_tam`, `hypo_nvda_news_next_quarter_reshape` all opened
"I cannot determine …") — and the judge's `refusal_judgment` substring-matches
"I cannot determine" / "not available" → a mechanical 0. The passing FX / HBM
exemplars prove a labelled assume-and-range answer passes **without new data**.

- **P0 — anchor-vs-parameter split.** LICENSE the model to introduce a
  clearly-labelled, order-of-magnitude ASSUMPTION for a scenario parameter drawn
  from general knowledge, fenced by THREE hard rules: (1) labelled "assumption —
  not retrieved" and carrying NO `[tool_name row N]` citation tag; (2) ALWAYS
  paired with a low–high RANGE; (3) NEVER used to state a present/past fact. The
  anchor-fact anti-fabrication rule (revenue / margin / EPS MUST be retrieved +
  cited) is intact. Adds a worked AMD exemplar mirroring the ideal answer
  ("AMD's data-centre revenue is $Nbn [query_fundamentals row 0]; assuming a
  served market of ~$X–Y bn (assumption — not retrieved) and share +Z pp, the
  incremental revenue is roughly +$A–$B bn").
- **P1 — ban refusal openers for projections.** The exact strings the judge
  substring-matches ("I cannot determine", "cannot be calculated", "is not
  available") are banned as openers/fallbacks for a what-if answer when the only
  gap is a scenario parameter — phrase it "assuming a served market of ~$X …" +
  range instead.
- **P2 — projection scaffold.** A five-step template (retrieve base → state
  labelled assumptions → show the calc → give a low–high range → flag
  conditional / not advice) that systematises the winning FX / HBM shape.
- **Impact.** Flips the content hash. NARROW + additive: every v1.5–v1.18
  anti-fabrication / grounding / coverage rule is preserved and the license is
  SCOPED to scenario parameters (assumptions), NEVER to anchor facts. Pairs with
  `tool_use_system` v1.21 (light REASONING-addendum routing rule). Source:
  `docs/plans/2026-07-09-chat-enhancement-roadmap.md` Area 2 (P0/P1/P2).

### 1.18 — 2026-07-08 (SOFTEN the v1.17 hypo regression — reverse over-refusal without re-enabling fabrication)

The softening re-run `run_20260708T211838Z` showed v1.17 OVERCORRECTED: the
hypothetical/projection bucket went 4× PASS→FAIL. v1.18 makes four targeted
edits that REVERSE the regressions without swinging the pendulum back into
fabrication.

- **(1) PROVENANCE mis-fired on RETRIEVED data** (`hypo_msft_capex`
  PASS97→FAIL50). The model tagged its OWN tool-returned capex figures "(source
  unverified)" and then tripped its own grounding veto → refusal. The PROVENANCE
  block now states: NEVER tag a retrieved value "(source unverified)" /
  "(unverified)" — a value that came back FROM a tool IS verified BY that tool;
  cite it normally with its `[tool_name row N]` / `[N]` tag. "unverified" /
  "derived" labels belong ONLY on a model-COMPUTED number. **RETRIEVED ≠
  DERIVED.**
- **(2) D-d rule 6 no-backfill OVERCORRECTED into refusal on QUALITATIVE
  questions** (`hypo_tsmc_3nm` PASS95→FAIL55, a full 2,351-char structural answer
  collapsed to a 376-char refusal). The numeric-fabrication ban bled into
  qualitative reasoning. Added a QUALITATIVE CARVE-OUT to ANTI-FABRICATION rule 6:
  for hypothetical / structural / second-order-risk questions — especially when
  tools return empty/errored — qualitative conditional reasoning from general
  domain knowledge (causal chains, directional effects) IS allowed and expected,
  PROVIDED no specific numbers / entities / dated facts are invented and it is
  labelled conditional / qualitative. The ban is on fabricating VALUES, not on
  REASONING.
- **(3) D-d ROW-PADDING still broke** (`iter3_top5` padded 3 screener rows into a
  "top 5" with memory-sourced ENPH / PATH). Added a HARD ROW-CAP to
  ANTI-FABRICATION rule 2: NEVER emit MORE rows / entities than the tool returned;
  if fewer than the requested N came back, state "only N matched" and STOP. This
  is the one TIGHTENING edit in an otherwise softening release (net-neutral on
  fabrication).
- **(4) D-e never-refuse-projection did NOT hold** (`refusal_judgment=0` on all 6
  hypo; two now LED with "I cannot predict future price movements"). Added a
  DO-NOT-OPEN-WITH-A-REFUSAL-LINE bullet to the ANALYTICAL / WHAT-IF block:
  NEVER open a conditional / what-if / projection answer with a forecast
  disclaimer ("I cannot predict future price movements", "I'm unable to
  forecast", "predicting … is speculative") — a grounded hedged range is
  required. The "I cannot predict" line is RESERVED for a bare
  asset-price-direction question, never a what-if IMPACT question that supplies
  its own premise.
- **Impact.** Flips the content hash. SOFTENING + additive: every v1.5–v1.17
  anti-fabrication / grounding / coverage / projection rule is preserved — edits
  (1) and (4) reverse over-refusal, (2) carves qualitative reasoning out of the
  numeric ban, and (3) tightens row-padding. Pairs with `tool_use_system` v1.20
  (mandatory tool on entity what-ifs — the fx/asp 0-tool-call half of the same
  regression). Source: `docs/plans/2026-07-08-chat-quality-two-track-audit.md`,
  run_20260708T211838Z.

### 1.17 — 2026-07-08 (chat-quality two-track audit — D-d memory-backfill ban, D-e projection/fallback, Track-3 enhancements)

- **D-d — ANTI-FABRICATION rule 6: no parametric-memory backfill, no "Public
  knowledge (unverified)" fallback.** Beyond D8 (empty result) and v1.16
  (partial row), the model was still promoting PARAMETRIC-MEMORY values/entities
  into answers past an empty OR partial tool result — `iter3_top5` (ENPH/PATH
  market caps), `spanish` (Samsung/Huawei competitor list), `deep_nvda` (PEG
  0.61), `deep_meta` ($2.71B), `ru_nvda_amd` (fabricated AMD), `da_tsla`
  (fabricated Q1) — frequently behind a "Public knowledge (unverified): …" hedge
  that reads as near-fact. Rule 6 forbids filling ANY gap from memory (empty or
  partial), explicitly bans the "Public knowledge (unverified)" / "Based on
  public knowledge" / "generally known" fallback pattern in the final answer, and
  requires quarantining the gap as "not available in the retrieved data".
- **D-e — never refuse a projection as unknowable + next-best-metric fallback.**
  `hypo` (×4) retrieved the base figures then refused the hedged estimate as
  unknowable, and `chain_portfolio_worst` refused a ranking because margins were
  absent. Added (a) a NEVER-REFUSE-A-PROJECTION-AS-UNKNOWABLE bullet to the
  ANALYTICAL / WHAT-IF block (once the base figures are held, produce a hedged
  RANGE under explicit assumptions — never decline as "impossible to predict" /
  "unknowable"); and (b) a NEXT-BEST METRIC block (when the primary metric is
  absent, fall back to the next-best AVAILABLE grounded signal — P/E, ROE, growth
  — and STATE the substitution; refuse only if no usable signal returned).
- **Track-3 PASS-ceiling enhancements.** (i) SINGLE-FIGURE ANSWERS block — a bare
  P/E / YoY / EPS / margin must carry an as-of date/period AND a grounded peer or
  historical benchmark. (ii) PROVENANCE block — tag each figure retrieved
  (`[tool row]`) vs model-derived (computed/scenario, labelled "(derived)", no row
  tag, cites its inputs) so a calculation is not read as fabrication. (iii)
  MULTI-ITEM RESULTS block — news dumps grouped by theme with a "what to watch"
  takeaway; multi-quarter reported as QoQ/YoY deltas + trend + TTM rather than a
  raw transcription.
- **Impact.** Flips the content hash. Additive; every v1.5–v1.16 anti-fabrication
  / grounding / coverage / projection rule is preserved and the report-in-full
  balance is unchanged (rule 6 forbids memory backfill, never withholding a
  grounded value; the fallback/projection rules push AGAINST refusal, not toward
  fabrication). Source: `docs/plans/2026-07-08-chat-quality-two-track-audit.md`,
  run_20260708T093242Z.

### 1.16 — 2026-07-08 (chain_nvda_competitor_growth_rank — no partial-row field fabrication; extends D8)

- **ANTI-FABRICATION rule 5 (partial-row field fabrication).** In
  `chain_nvda_competitor_growth_rank` ("which of NVIDIA's competitors had the best
  revenue growth over the past four quarters?") the tool returned a PRESENT ARM
  row carrying `pe_ratio` and `market_cap` but NO `revenue`, and the synthesis
  turn FABRICATED an ARM quarterly revenue series ($1.053B / $1.135B / $1.242B /
  $1.490B) to complete the growth ranking — judge grounding=0, "ARM revenue
  figures are fabricated; tool_results show no revenue data for ARM (only pe_ratio
  and market_cap)". D8 (rule 4) only covered a FULLY-EMPTY tool result; a partial
  row that returns SOME fields but omits the requested one was uncovered. v1.16
  adds rule 5: a PRESENT row carrying only some of the needed fields is NOT a
  licence to fill the missing one from memory — report the fields the row DID
  return with their tags, and state plainly that THAT SPECIFIC metric is not
  available for THAT entity; a partial row is as binding as an empty one on the
  field it omits. Explicitly distinguished from rule 3 (which forbids WRONGLY
  declaring a PRESENT field missing): here the field is genuinely absent, so
  naming it unavailable is the correct non-fabricating answer. Also corrected the
  block preamble's stale "These three rules" count (there are now five).
- **Impact.** Flips the content hash. Additive; the report-in-full balance is
  preserved (report present fields, refuse only the genuinely-absent one) and no
  grounding / coverage / projection rule is weakened. Pairs with tool_use_system
  v1.17 (the no-tools-routing fix from the same eval run).

### 1.15 — 2026-07-08 (da_tsla_revenue_2024_full_year — label the period from the row, never from today's date)

- **Period-fidelity bullet in PERIOD-MATCHING.** The date-anchored fundamentals
  fix (`tool_use_system` D3) now correctly RETRIEVES TSLA's 2024 quarters — real
  Q1-Q3 2024 revenue values were present in the tool result — but the synthesis
  turn RELABELLED those rows as Q3 2025 / Q4 2025 / Q1 2026 and then declared "no
  2025 data available" (judge grounding=0, framing=0, "Fabricated period labels …
  tool returned 2024 quarters"; the same nuance recurred in `iter3_msft`,
  "Fabricated period label contradicts tool scope"). Root cause: the model
  inferred each row's period from the "current date is 2026" system context
  instead of reading the row's own `period_end`. v1.15 adds a bullet requiring
  every figure to be labelled with the EXACT `period_end` / fiscal period on its
  own row and forbidding inferring, shifting, advancing, or relabelling the period
  from today's date or the conversation's "current" year — a `2024-09-30` row is a
  Q3 2024 figure regardless of today's date. The current-date context is scoped to
  recency reasoning only, never to stamping period labels onto retrieved rows.
- **Impact.** Flips the content hash. NARROW + additive: reinforces the existing
  v1.6 date-binding / period-matching and v1.14 unreported-quarter rules; no
  grounding / anti-fabrication / coverage rule is weakened.

### 1.14 — 2026-07-07 (iter3_msft_earnings_citations — unreported-latest-quarter is not "all not available")

- **LATEST-QUARTER-ONLY / UNREPORTED PERIOD bullet in TRUST YOUR TOOL RESULTS.**
  "Microsoft's most recent earnings report" (`iter3_msft_earnings_citations`)
  routed correctly to `query_fundamentals` (status=ok, 1 item), but the single
  returned row was the newest fiscal quarter (Q4 FY2026), not yet reported, so its
  revenue / net_income / eps / gross_margin cells were all null. The model
  blanket-declared every metric "not available" — a wrongful refusal over a
  status=ok result (judge grounding=10, refusal_judgment=0). v1.14 adds a bullet
  teaching that an all-null NEWEST-quarter row is a not-yet-reported placeholder,
  NOT an all-not-available data gap: (a) report the most-recent REPORTED quarter's
  figures if any other period row carries them, else (b) state specifically that
  the latest fiscal quarter has not been reported yet (a reporting-timing
  boundary), never a generic blanket "not in the data".
- **Impact.** Flips the content hash. Additive; no grounding / anti-fabrication
  rule relaxed — "not available" stays correct for a specific field genuinely
  absent from every returned row. Pairs with tool_use_system v1.16 (the
  planning-turn half — fetch periods>=4, not periods=1, so a reported quarter is
  in the payload).

### 1.13 — 2026-07-06 (eval FAIL synthesis fixes — anti-over-refusal on partial failure, empty-result no-fabrication, no-placeholder-for-present-field)

- **D7 — anti-over-refusal on partial tool failure.** `cmp_nvda_amd` had NVDA/AMD
  core fundamentals `status=ok` but ABANDONED the comparison because the SEGMENT
  (data-center) metric query errored and the news call timed out — a
  data-gap-as-give-up, with no verdict emitted. v1.13 extends the REASONING RIGOR
  block with a `PARTIAL / ERRORED TOOL → SYNTHESISE FROM WHAT SUCCEEDED` rule: a
  partial/errored tool NEVER suppresses synthesis from the successful results;
  reason qualitatively around the missing coverage field; treat an
  unsupported-metric / "not covered" sentinel (a sibling adds one on the
  market-data side) as a coverage gap to reason around, not a failure; never emit
  a blanket "cannot be grounded" when core data WAS returned.
- **D8 — fabrication guard on empty results.** `compare_entities` with non-US
  tickers returned empty → the model hallucinated "Estée Lauder"; a competitor
  chain hallucinated "Shift4 (FOUR)" from the phrase "past FOUR quarters." v1.13
  adds ANTI-FABRICATION rule 4: on an EMPTY tool result, never name an
  entity/ticker absent from ALL tool results, and never derive a ticker from the
  question's own tokens ("four"→FOUR, "MA"→Mastercard); say the data isn't
  available instead. (A sibling handles non-US-ticker mapping on the tool side.)
- **D4 (prompt half) — no placeholder for a present field.** The model wrote a
  dash placeholder for a P/E field the tool actually returned (`pe_ratio=37.32`).
  v1.13 adds a bullet to TRUST YOUR TOOL RESULTS forbidding a "—"/"N/A"
  placeholder for a value that IS present in a tool result (a placeholder is
  permitted only for a genuinely-absent field). (The sibling orchestrator agent
  strips the gpt-oss `【commentary…】` channel leak — the code half of D4.)
- **Impact.** Flips the content hash. Additive; every v1.9–v1.12 rule is kept and
  no grounding / anti-fabrication / projection rule is relaxed. Consistent with
  tool_use_system v1.15 (the planning-turn half of the same eval FAIL analysis:
  D3/D5).

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
