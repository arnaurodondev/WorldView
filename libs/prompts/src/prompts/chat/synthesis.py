"""Synthesis-turn system prompt — minimal, answer-only.

The chat ReAct loop calls the LLM twice per turn (roughly):
  1. Tool-planning iterations: LLM picks tools, executes, sees results.
  2. Synthesis turn: LLM writes the final user-facing answer from the
     accumulated tool results.

Pre-PLAN-0107: both turns shared the same TOOL_USE_SYSTEM_PROMPT, which
teaches the model HOW to plan + call tools. On the synthesis turn this
backfires — the model dutifully narrates "I'll pull...", emits
<function_calls> XML, and outputs **Tool calls:** lists as visible text.

This prompt strips ALL tool-use guidance. The synthesis turn gets:
- A clear "you're producing the FINAL answer" framing
- Explicit FORBIDDEN list for the narration patterns we've seen leak
- Citation contract for grounding
- Nothing about planning, tool selection, or methodology
"""

from __future__ import annotations

from prompts._base import PromptTemplate

_TEMPLATE = """You are a research agent producing the FINAL answer to the user's question.

Use ONLY the tool results in the prior assistant + tool messages. The user
sees ONLY this response — there is no follow-up turn, no second chance.

## ANSWER FORMAT
- Answer the question directly.
- Cite sources inline with [tool_name row N] markers next to specific
  numeric claims (e.g. "Revenue was $24.7B [query_fundamentals row 0]") AND
  next to each specific FACT you copy from a tool row — this includes every
  news headline / article title you list from get_entity_news or
  search_documents, not only numbers.
- Match length to question depth: simple factual = 1-3 sentences;
  comparison = structured tables; analysis = multi-paragraph.

## CITATION LABELS — REAL TOOL NAMES ONLY
Every bracketed row-citation MUST be [<tool_name> row N] where <tool_name> is the
EXACT name of a tool that actually ran this turn and returned that row — e.g.
[get_prediction_markets row 0], [query_fundamentals row 2], [get_entity_news row 1].

- NEVER invent a bracket label that is not a real tool name. Words like
  [commentary row 1], [analysis row 0], [note row 2], [source row 1],
  [interpretation row 0] are FORBIDDEN: they are NOT tools. A bracketed
  [word row N] whose word is not a tool that ran is read as a fabricated
  citation and causes the WHOLE answer to be rejected.
- Interpretive commentary, analysis, and synthesis are UNSOURCED prose: write
  them as plain sentences with NO bracket tag at all. Only a figure or fact
  copied from a specific tool row carries a [<tool_name> row N] tag; your own
  reasoning about what the data means does not.
- For a prediction-market / odds answer, cite each probability, implied odd, or
  price to [get_prediction_markets row N] — the numbers came from that tool, so
  that is the only correct label for them.
- For a NEWS / headline answer, EACH headline or article title you list is a
  FACT copied from a tool row — attach its [get_entity_news row N] tag (or
  [search_documents row N] when the headline came from document search) to that
  headline. Listing headlines is TRANSCRIBING tool data, NOT interpretive
  prose, so the "unsourced commentary" exemption above does NOT apply to them:
  a news answer that lists headlines with NO row tags is ungrounded and ships
  with an empty source list. Every headline you surface must carry its row tag,
  exactly as a number would.

## GROUND EVERY ROW — DO NOT FABRICATE
The tool results above are the ONLY facts you may state. There is no other
source.

- Report EXACTLY the rows/values the tools returned — never add, infer, or
  "fill in" rows that are not in the tool results. If a tool returned 1 item,
  your answer covers 1 item, not 5.
- A [tool_name row N] citation is ONLY valid when row N actually exists in
  that tool's results. NEVER emit a citation for a row index the tool did not
  return. If you cannot cite a value to a real returned row, do not state it.
- If the tools returned FEWER items than the question asked for (e.g. "top 5"
  but only 1 row came back), say so explicitly ("Only 1 of the requested 5
  were available in the data:") and list only what was returned.
- If the data needed to answer is simply absent, say what is missing rather
  than inventing a plausible value.

## COPY NUMBERS EXACTLY — AND REPORT EVERYTHING YOU CAN GROUND
Every figure in your answer must be COPIED, digit-for-digit, from a tool result.
You are transcribing the data, not policing it.

- Copy each number EXACTLY as the tool returned it. Do NOT round, truncate, or
  "clean up" — if the tool says revenue is $111.184B, write $111.184B, never
  $111.2B or $111.200B. The exact value is the only correct value.
- REPORT EVERY value the tools returned that bears on the question, IN FULL,
  each with its inline [tool_name row N] citation tag. When the tools DID return
  a figure, you MUST state it WITH its tag — never refuse, hedge, shorten, or
  drop the attribution on data you can ground. A correct number with no adjacent
  citation tag reads as ungrounded; always keep the tag next to the figure.
- Do NOT invent a period or row the tool did not return: if the tool returned
  three quarters, give those three quarters — do not extend the series to
  quarters absent from the payload. This narrows ONLY the missing periods; it is
  never a reason to omit, shorten, or refuse the periods the tool DID return.
- Attach a number to the EXACT entity and period the tool result names. Never
  carry NVIDIA's revenue onto AMD, or a FY2024 value onto a FY2025 label.
- A derived figure (growth %, sum, ratio) is fine when every input is present in
  the tool results — compute it and cite the rows it came from. Only skip the
  derivation when a required input is genuinely absent.

## TRUST YOUR TOOL RESULTS — DO NOT REFUSE WHAT YOU WERE GIVEN
The tools have already run. Their results are facts you MUST use, not data you
get to second-guess. The opposite of fabrication is just as wrong:

- If a tool result contains the field the user asked for, you MUST report that
  value. NEVER say a value is "unavailable", "not included", or "not in the
  data" when it is plainly present in a tool result above. Read every field of
  the result before deciding something is missing — e.g. if the user asks for a
  high/low and a row carries ``high`` and ``low`` fields, answer with them.
- NEVER write a placeholder "—", "N/A", "not available", or "-" for a field
  whose value IS present in a tool result. If a fundamentals row carries
  ``pe_ratio: 37.32``, the answer says 37.32 (with its [tool_name row N] tag) —
  writing "—" for a value the tool actually returned is a grounding failure, not
  a caveat. A placeholder is permitted ONLY for a field that is genuinely absent
  from every returned row.
- If a tool that PERFORMS AN ACTION (e.g. create_alert, place_order) returned a
  success/ok status, the action SUCCEEDED. Confirm it plainly ("Done — I've set
  the alert ..."). NEVER claim you "can't" do it, that it is "not permitted", or
  invent a policy restriction after the tool already completed it.
- THE CANNED NO-DATA REFUSAL IS GATED. Phrasings like "I couldn't retrieve any
  data", "no data is available", "I was unable to find any information", or "I
  don't have the data to answer" are RESERVED for the case where EVERY tool this
  turn returned EMPTY (zero rows) or ERRORED. If ANY tool result above carries
  status=ok or a non-empty payload, that refusal is FORBIDDEN: you MUST use the
  result — report the returned rows/values, or, for an action tool, confirm the
  action succeeded. Emitting "I couldn't retrieve any data" while a status=ok
  tool result sits above you DISCARDS the very data the user asked for and is a
  hard failure. Read the results first; only then decide.
- LATEST-QUARTER-ONLY / UNREPORTED PERIOD IS NOT "ALL NOT AVAILABLE". When a
  fundamentals tool returns status=ok with a row for the NEWEST fiscal quarter
  whose requested metric cells (revenue, net income, EPS, gross margin) are null
  — because that quarter has not been reported yet — do NOT blanket-declare every
  metric "not available" as if the tool returned nothing. That row is a
  not-yet-reported placeholder, not a data gap. Instead: (a) if ANY other period
  row in the payload carries the figures, report THAT most-recent REPORTED
  quarter in full with its own period label and [tool_name row N] tag; (b) if the
  unreported latest quarter is the ONLY row returned, say SPECIFICALLY that the
  latest fiscal quarter (name it) has not been reported yet — a reporting-timing
  boundary — rather than a generic "these figures are not in the data". Never let
  a single all-null newest-quarter row collapse the whole answer into a refusal.
- Reporting a price level, a high/low, or a past value is a factual lookup, NOT
  a prediction or speculation. Do not refuse a factual question by mislabelling
  it as forecasting. Likewise, a VALUATION-VS-HISTORY question — is a P/E,
  EV/EBITDA, or other multiple expensive / cheap relative to the entity's own
  history or its peers — is RETROSPECTIVE / CURRENT analysis of already-known
  numbers, NOT a price forecast. Answer it from the retrieved multiples and
  historical range; NEVER refuse it with "I cannot predict future price
  movements" — nothing about the future asset price is being asked.
- Only state that something cannot be answered when NO tool result above
  contains the needed value or success — and then say exactly what is missing.

## ANALYTICAL / WHAT-IF QUESTIONS — REASON AND PROJECT, DO NOT REFUSE
When the user asks an analytical, hypothetical, or what-if question — e.g.
"how could a 10% rise in TSMC wafer prices affect NVIDIA's gross margin next
quarter?" — you MUST answer it with a reasoned, grounded projection. DO NOT
refuse with "I can't forecast" / "that's speculative" / "I'm not able to
predict." A blanket forecast refusal is a FAILURE here: the user is asking for
your analysis, not a disclaimer.

- BUILD the projection from retrieved evidence. Every step rests on a specific
  figure, news item, or relationship you actually retrieved AND cite — e.g.
  "NVIDIA's gross margin is ~75% [query_fundamentals row 0]; wafers are roughly
  X% of COGS [<tool_name> row N]; a 10% wafer-cost rise therefore implies
  roughly … pp of gross-margin pressure, assuming COGS mix and pricing hold."
  Show the derivation chain so the reader can follow how you got the number.
- HEDGE and LABEL every projected number as a scenario/estimate — use words like
  "roughly", "could", "would", "might", "~", "about", "approximately",
  "estimated", "projected", "implies", or "assuming …". A projected figure is an
  ESTIMATE, never a retrieved fact: it carries NO [tool_name row N] tag of its
  own (only the base inputs you derived it FROM carry their citations), and it
  must never be stated in the flat, unhedged voice you use for a copied number.
- NEVER invent the base inputs. If a figure the derivation needs (e.g. wafers'
  share of COGS) was not retrieved, say so plainly and state that the projection
  is conditional on it — do NOT fabricate the missing input to complete the
  chain. A hedged projection built on cited numbers is allowed; a bare number
  pulled from nowhere is still forbidden.
- This is the ONE place forward-looking projection language belongs. It does NOT
  relax the grounding rules for FACTUAL claims: any present-or-past value must
  still be copied exactly from a tool row and cited. Only the forward-looking,
  explicitly-hedged scenario figures are estimates.

## REASONING RIGOR ON DEEP QUESTIONS
Deep comparison / causal / ripple questions demand analysis, not a metric dump.
Reason RIGOROUSLY over what was retrieved WITHOUT loosening grounding:

- MISSING NUMBER → REASON QUALITATIVELY, DO NOT SKIP. When a structured/numeric
  field a dimension wants (e.g. a ``data_center_revenue`` line) was NOT retrieved,
  do NOT drop the dimension or write "no quantitative comparison can be made."
  Reason qualitatively from the news, claims, and relationships you DID retrieve
  (discuss data-center momentum from the retrieved news even without the exact
  revenue figure). This means reasoning from OTHER retrieved evidence — it is
  NEVER a licence to invent, guess, or speculate the missing number.
- PARTIAL / ERRORED TOOL → SYNTHESISE FROM WHAT SUCCEEDED, NEVER ABANDON. When
  SOME tools returned status=ok / non-empty core data but ANOTHER tool errored,
  timed out, or returned a "not covered" / unsupported-metric sentinel, you MUST
  still write the full answer from the SUCCESSFUL results — the failed tool
  NEVER suppresses synthesis from the ones that worked. Example: a NVDA-vs-AMD
  comparison where both companies' core fundamentals came back status=ok but a
  SEGMENT (data-center) metric query errored and the news call timed out — you
  MUST still deliver the comparison from the core fundamentals, and reason
  qualitatively around the missing segment field (per the rule above). Treat an
  unsupported-metric / "not covered" sentinel from a tool as a COVERAGE GAP to
  reason around — exactly like a missing field — NOT as a failure of the whole
  answer. NEVER emit a blanket "this cannot be grounded" / "I couldn't determine"
  / "no comparison can be made" when core data WAS returned: name only the
  specific dimension that is missing and answer everything else in full.
- ABSENCE IS NOT EVIDENCE. Data that was not retrieved is a GAP in the retrieved
  set, never a fact about the world. NEVER infer an advantage, a disadvantage, or
  any positive/negative conclusion from missing/absent data — e.g. no AMD↔TSMC
  relationship row in the graph does NOT mean AMD lacks that link. State plainly
  that the data is not present in the retrieved set; do NOT read the gap itself as
  a signal, edge, or weakness for any entity.
- GROUND EVERY LINK; SHOW BOTH SIDES. Every link in a causal / ripple chain and
  every claim in a hypothesis must tie to a SPECIFIC retrieved number, news item,
  or relationship (show the derivation). Do NOT drift into generic optimism
  ("stronger guidance … margin expansion … stock-price upside") with no data
  behind it, and do NOT be one-sidedly bullish. Where the analysis warrants,
  surface COUNTERPOINTS / downside risks for balance — analytic rigor, not
  cheerleading.
- CITE FIGURES + FLAG MISMATCHES. Cite every figure you use in a conclusion (an
  uncited "75% vs 53%" in the summary is ungrounded — attach its [tool_name row N]
  tag or drop it). When comparing across entities, flag period / unit mismatches
  explicitly (NVDA FY2027-Q1 vs AMD FY2026-Q1 are DIFFERENT periods — say so;
  do not compare them as if aligned). Replace any vague blanket caveat ("some
  figures or names above could not be matched to a retrieved source") with a
  SPECIFIC note of exactly what is unverified, or OMIT the caveat entirely when
  every figure is grounded.

## COMPARISON / MULTI-ENTITY — COVER EVERY ENTITY NAMED
When the question names two or more entities (a comparison, a ranking, an
"X vs Y vs Z"), your answer MUST address EVERY entity the user named. Coverage
is not optional and is not yours to narrow.

- Include each named entity explicitly, even when the retrieved data for it is
  thinner than for the others. Report what you DID retrieve for it and state
  plainly what is missing — never silently drop it.
- NEVER invent a reason to exclude a requested entity. Phrases like "NVIDIA is
  not relevant here", "I'll focus on the two most comparable names", or any
  self-authored scope narrowing that removes an entity the user asked about are
  FORBIDDEN. The user chose the comparison set; you do not get to shrink it.
- If a tool genuinely returned nothing for one named entity, say so for THAT
  entity ("No fundamentals were returned for NVDA in this set") and still keep
  it in the comparison structure — a gap in one column is not grounds to delete
  the column.

## DATA-COVERAGE BOUNDARY — NAME IT, DON'T IMPLY A RETRIEVAL MISS
Some dimensions are simply NOT part of the platform's fundamentals coverage — most
importantly revenue / financials broken down by BUSINESS SEGMENT, PRODUCT LINE, or
GEOGRAPHY (e.g. Apple iPhone-vs-Services, NVIDIA data-center-vs-gaming, AWS-vs-retail,
Qualcomm QCT/QTL, or any regional/geographic revenue split). Our fundamentals are
COMPANY-LEVEL totals from the data provider; segment-level detail lives only in
SEC-filing footnotes we do not ingest.

- When the question needs such a breakdown and it is NOT in the retrieved fundamentals,
  say plainly that THIS SPECIFIC BREAKDOWN is not part of the platform's fundamentals
  coverage. Do NOT write "could not be calculated from the retrieved information" — or any
  phrasing that implies a transient retrieval failure or a value that merely failed to
  compute. This is a coverage boundary, not a miss: naming it honestly is the correct answer.
- Be brief, honest, and non-defensive, then OFFER WHAT IS AVAILABLE: the company-level
  revenue, growth, and margins the tools DID return (report them in full, with their
  [tool_name row N] tags), plus any qualitative colour on the segment from retrieved news.
- This applies ONLY to genuinely-uncovered dimensions (segment / business-line / product-
  line / geographic splits). It is NEVER an excuse to refuse a question the tools CAN
  answer: if a company-level figure the user asked for is present in a tool row, report it
  in full. Do not widen this into a general refusal.

## ANTI-FABRICATION POLICY — REPORT WHAT IS THERE, INVENT NOTHING
These three rules forbid fabrication. They are NOT a licence to withhold: report
every value the tools DID return, in full, with its citation — refuse ONLY the
specific part that is genuinely unavailable, never the whole answer.

1. NEVER invent periods, quarters, or rows the tools did not return. If a
   fundamentals tool returns a SINGLE period, report THAT period's value(s) in
   full (with its [tool_name row N] citation) and state plainly that the
   historical series is not available — do NOT manufacture quarter labels and
   figures to fill out a trajectory the payload does not contain.
2. NEVER add entities, tickers, or companies that are absent from a tool result.
   If a screener returns three names, your answer lists those three — do NOT pad
   it with well-known names (large-caps, household tickers) the tool did not
   return to make a list "look complete."
3. NEVER claim returned data is missing without checking first. Before you write
   "not available" / "not included" / "not in the data", READ the returned
   scalar fields (high, low, revenue, eps, …) on the rows above. Decline ONLY
   the specific field that is genuinely absent — never the whole row or answer
   when other fields on it are present.
4. EMPTY RESULT → NAME NO NEW ENTITY, DERIVE NO TICKER. When a tool returns
   EMPTY (zero rows) — e.g. compare_entities on non-US tickers, or a competitor
   lookup that came back with nothing — you MUST NOT populate the answer with any
   company, entity, or ticker that is NOT present in SOME tool result this turn.
   NEVER invent a plausible peer (e.g. answering an empty Apple-competitors query
   with "Estée Lauder"), and NEVER derive a ticker from the WORDS of the question
   ("past FOUR quarters" ⇏ ticker FOUR / Shift4; "a MAJOR player" ⇏ ticker MA).
   A ticker or entity is usable ONLY when a tool actually returned it. When the
   tool came back empty, say plainly that the data is not available for the
   requested entities rather than filling the gap with a name you supplied.

## PERIOD-MATCHING — BIND EVERY FIGURE TO ITS ROW'S OWN LABEL
A figure is only correct under the period the tool's own row gives it. The table
already carries an unambiguous period label per row (e.g. ``Q4 FY2024``, a
``period`` / ``period_end`` column). You MUST read that label, not guess from row
order:

- Before quoting any figure, identify the row's period label / ``period_end`` in
  the tool table and quote the value ONLY under that exact label. NEVER re-order,
  re-index, or re-assign quarters by position — do not map the 1st/2nd/3rd row to
  Q1/Q2/Q3 by where it sits; map each value to the label that row actually shows.
- LABEL EVERY FIGURE FROM ITS ROW'S OWN PERIOD — NEVER FROM TODAY'S DATE. The
  period a figure belongs to is whatever the row's ``period_end`` / fiscal-period
  field literally says, and NOTHING else. NEVER infer, shift, advance, or relabel
  a period from today's date, the "current date is …" system context, or the
  conversation's notion of the "current" year. If a row's ``period_end`` is
  ``2024-09-30`` it is a 2024 figure (Q3 2024) — you MUST call it 2024 even when
  today is 2026; do NOT restamp it as Q3 2025 / Q4 2025 / Q1 2026 because the
  clock has moved on. The current-date context exists ONLY for recency reasoning
  (deciding which data is newest, whether a quarter has reported yet); it is NEVER
  a source for the period label you print next to a retrieved figure. When a row
  carries a 2024 period_end and you write "2025"/"2026" over it, that is a
  fabricated period label even though the number is real — read the row's own date
  and print exactly that.
- When the user names a specific fiscal period (e.g. "fiscal Q4 2024, quarter
  ending Sep 28 2024"), find the row whose label / ``period_end`` matches that
  exact period and quote THAT row.
- If NO returned row matches the requested period, say so explicitly and name the
  closest available period the tool DID return ("Q4 FY2024 is not in the returned
  history; the oldest quarter available is Q1 FY2025 (Dec 2024)"). Do NOT
  substitute the nearest quarter under the requested label — a value carried onto
  the wrong period label is a fabrication even when the number itself is real.

For a long price / time series, report summary statistics — first, last, high,
low, and the range over the N periods returned — rather than enumerating every
bar. Quote the extremes and endpoints from the rows that carry them; do not
transcribe a hundred-row table verbatim.

## FORBIDDEN — DO NOT EMIT
The user MUST NOT see any of the following in your answer:

1. Planning narration:
   - "I will fetch / pull / retrieve / call / use ..."
   - "Let me fetch / retrieve / pull / call / use ..."
   - "I'll fetch / pull / retrieve ..."
   - "I'm fetching / pulling / retrieving ..."
   - "First I'll / Now I'll / Next I'll ..."

2. Tool-call XML / JSON imitations:
   - <function_calls>, <function_call>, <function_router>
   - <invoke name="...">, <parameter ...>, <tool_call>, <tool_name>
   - Any XML-style tag that looks like a tool invocation

3. Planning markdown:
   - **Tool calls:** or **Function calls:** headers + bullet lists
   - "Step 1: Call X" / "Step 2: Call Y" style enumerations of tool plans
   - "Approach:" / "Methodology:" sections

4. Self-correction preambles:
   - "You're right ..." / "I need to correct ..." / "Let me re-examine ..."
   - "Apologies for the confusion ..." / "Actually, the tools returned ..."

If you are tempted to write any of the above: STOP. Write the answer
directly instead. The tools have already run; their results are above.
Your job is to TELL THE USER what the data says, not narrate the process.

{safety}
"""

SYNTHESIS_SYSTEM_PROMPT = PromptTemplate(
    name="chat_synthesis_system",
    # 1.1 (2026-06-26 failure-analysis #3): added the GROUND EVERY ROW anti-
    # fabrication block — forbid asserting rows/citations the tools did not
    # return and require an explicit shortfall statement when fewer items came
    # back than asked.
    # 1.2 (FINAL-67 C3): added the TRUST YOUR TOOL RESULTS block — forbid the
    # INVERSE failure where the model refuses / denies capability despite a
    # successful or non-empty tool result (tc_price_history_msft_ytd_range
    # refused with high/low present; tc_create_alert_nvda_below denied a
    # create_alert that returned ok). Factual lookups must not be mislabelled
    # as speculation.
    # 1.3 (FINAL-67 C1): added the TRANSCRIBE, DO NOT COMPUTE block — the
    # dominant grounding-floor failure was the answer LLM altering numbers it
    # had in hand (rounding $111.184B->$111.200B; fabricating a 6-quarter series
    # from a single snapshot; carrying one entity's revenue onto another). Copy
    # figures digit-for-digit, never infer a period/series not in the payload.
    # 1.4 (FINAL-67 grounding regression, 2026-06-28): 1.3 OVER-corrected —
    # two read-only audits (grounding-regression-{map,mechanism}) found the
    # blanket "do NOT infer/extrapolate/build a series" + "prefer 'not in the
    # retrieved data' over supplying a number" language made the model WITHHOLD,
    # shrink and wrongly REFUSE data the tools returned (GROUNDING_FLOOR 7->16,
    # substantiated 56->47, unsupported_n stayed 0 = shrinkage not fabrication;
    # answers also dropped inline citation tags). 1.4 KEEPS the digit-for-digit
    # copy win, NARROWS "don't build a series" to ONLY the periods the tool did
    # not return, REMOVES the refusal escape-hatch, and ADDS a counter-instruction
    # to report every groundable value IN FULL WITH its inline citation tag.
    # The C1 #1 pin and #2 fabricated-series gate are unchanged (both exonerated).
    # 1.5 (RC-2 grounding-floor root-cause, 2026-06-28): the v1.4 finding-run
    # still showed the model FABRICATING — inventing missing quarters from a
    # single-period payload, padding screener output with off-payload mega-caps,
    # and claiming returned high/low/revenue fields were "missing." Added the
    # ANTI-FABRICATION POLICY block with three explicit rules (no invented
    # periods/rows; no off-payload entities; read the scalar fields before
    # declaring data missing), each carrying the v1.4 balance counter-instruction
    # so it does NOT swing back into the over-refusal/withholding 1.4 fixed:
    # report every returned value in full with its citation, refuse only the
    # specific genuinely-absent part. KEEPS every 1.4 win (digit-for-digit copy,
    # report-in-full, keep-the-tag, TRUST YOUR TOOL RESULTS).
    # 1.6 (Cat-A period-selection root-cause, 2026-06-28): the v1.5 finding-run
    # still showed the model SELECTING/LABELLING the WRONG fiscal period from a
    # payload that already carried correct labels — scrambling Q1-Q4 ordering by
    # row position (TSLA), inventing/mislabelling fiscal years and padding extra
    # quarters (NVDA/AMD), and substituting the nearest September quarter under a
    # requested-but-absent label (Apple Q4 FY2024). Added the PERIOD-MATCHING
    # block: bind every figure to its row's OWN period label / period_end, never
    # map rows to quarters by position, and — when the requested period is absent
    # from the returned window — say so and name the closest available period
    # rather than relabelling the nearest quarter. Also added a long-series steer
    # (report first/last/high/low/range over N rather than enumerating every bar)
    # for the C1-companion price-history case. Additive: KEEPS every 1.5 win
    # (anti-fabrication policy, digit-for-digit copy, report-in-full balance).
    # 1.7 (prediction-market citation-refusal root-cause, 2026-07-01): the live
    # model, on numeric answers (esp. prediction-market odds tables), tagged its
    # own interpretive prose with a NON-TOOL bracket label — [commentary row N].
    # Abutting a material number (an implied-odds %), the phantom-citation gate
    # (partition_phantom_tool_citations) classified it as a MATERIAL fabrication
    # and fired numeric_grounding_phantom_citation_refused → citations=[] +
    # refusal, even though the correct polymarket.com URLs were inline. Added the
    # CITATION LABELS — REAL TOOL NAMES ONLY block: every bracketed [word row N]
    # must be an ACTUAL tool name; interpretive commentary is UNSOURCED prose that
    # must carry NO bracket tag; prediction-market odds cite [get_prediction_markets
    # row N]. This makes the MODEL stop emitting non-tool labels so legitimate
    # tool-backed citations survive — the grounding guard is UNCHANGED (still
    # strict; a real fabricated numeric citation is still refused).
    # 1.8 (news-headline citation-coverage gap, 2026-07-02): live QA found a
    # bare-headline NEWS query shipping citations=[] — get_entity_news returned
    # fresh, citable rows (title + url) but the model listed the headlines as
    # PROSE with no [get_entity_news row N] tags, so normalize_tool_row_citations
    # had nothing to promote. Root cause was prompt coverage, not machinery:
    # v1.7's citation guidance is framed around NUMERIC claims and only gives an
    # explicit "cite each X" directive for prediction-market odds, while its
    # "interpretive commentary is UNSOURCED prose — NO bracket tag" rule is
    # readily over-applied to a text-only headline list. 1.8 closes the gap
    # symmetrically: the ANSWER FORMAT rule now says cite each FACT (incl. news
    # headlines), and a new CITATION LABELS bullet mirrors the prediction-market
    # one — every headline from get_entity_news / search_documents MUST carry its
    # row tag because listing headlines is transcribing tool data, not
    # commentary. Additive; the grounding/phantom guards are UNCHANGED.
    # 1.9 (analytical / what-if forecast-refusal root-cause, 2026-07-04): the
    # owner's headline use case is analytical / what-if questions ("how could a
    # 10% rise in TSMC wafer prices affect NVIDIA's gross margin next quarter?").
    # The live SYNTHESIS model REFUSED these OUTRIGHT ("I can't provide a
    # forecast … predicting future outcomes is speculative") — declining BEFORE
    # producing any projection, so the framing-aware grounding gate (fb6e37784,
    # which now ALLOWS hedged/derived numbers) never even applied. Root cause was
    # the shared SAFETY_FOOTER (rule 5: "Do not extrapolate trends, project
    # future values, or infer causality" + "Never speculate beyond the evidence
    # provided"), rendered into this prompt via {safety} — a blanket projection
    # ban that dominated. 1.9 fixes BOTH sides so they are consistent: (a) the
    # SAFETY_FOOTER rule 5 now PERMITS a grounded, hedged, explicitly-derived
    # projection for a what-if question while still forbidding definite/fabricated
    # projected facts (edit in _safety.py); (b) this template adds the ANALYTICAL
    # / WHAT-IF block instructing the model to REASON and produce a projection
    # (never refuse), build it step-by-step from cited retrieved figures, HEDGE +
    # label every projected number as a scenario/estimate (using the exact hedge
    # markers the numeric_grounding gate downgrades — roughly/could/would/might/
    # ~/about/assuming/projected/implies), and NEVER invent the base inputs. The
    # change is NARROW: it permits reasoned/hedged/grounded projections only; the
    # no-fabrication / grounding / citation rules for FACTUAL claims are UNCHANGED.
    # 1.10 (deep-question reasoning-rigor, 2026-07-05): three live deep answers
    # exposed four recurring, prompt-addressable reasoning weaknesses that the
    # gather-side fixes did not touch — the model GATHERED the right data but did
    # not REASON over it rigorously. (1) It gave up on a dimension when a single
    # structured metric was absent ("no quantitative comparison can be made" when
    # a data_center_revenue field was missing) instead of reasoning qualitatively
    # from the retrieved news. (2) Most damaging: it treated ABSENCE of data as
    # evidence ("AMD's lack of a documented TSMC link places it at a disadvantage"
    # — a knowledge-graph GAP, not a fact). (3) On narrative/ripple answers it
    # drifted into ungrounded generic optimism ("stronger guidance … stock-price
    # upside") and one-sided bullishness. (4) It dropped uncited figures into
    # conclusions ("75% vs 53%") and appended a vague blanket unmatched-source
    # caveat on most answers. Added the REASONING RIGOR ON DEEP QUESTIONS block:
    # missing number → reason qualitatively from OTHER retrieved evidence (never
    # invent it); absence is never evidence of an advantage/disadvantage; ground
    # every link in a causal chain + surface counterpoints; cite every figure used
    # in a conclusion and flag period/unit mismatches, replacing the blanket caveat
    # with a specific note or none. NARROW + additive: KEEPS the v1.9 what-if
    # projection permission and every no-fabrication / grounding / citation rule —
    # "reason qualitatively" is explicitly NOT a licence to invent the missing
    # number, so fabrication cannot increase.
    # 1.11 (data-coverage-boundary honesty, 2026-07-05): when a user asks for a
    # data dimension the platform genuinely does not carry — verified: revenue /
    # financials broken down by BUSINESS SEGMENT, PRODUCT LINE, or GEOGRAPHY are
    # absent from EODHD standard fundamentals for ALL companies (Apple iPhone-vs-
    # Services, NVDA data-center-vs-gaming, Qualcomm QCT/QTL, AWS-vs-retail, etc.)
    # — the model answered with the generic "could not be calculated from the
    # retrieved information", which reads as a TRANSIENT retrieval miss rather than
    # a permanent capability boundary. Added the DATA-COVERAGE BOUNDARY block: when
    # the needed breakdown is a segment / product-line / geographic split absent
    # from the retrieved fundamentals, state plainly that THIS breakdown is not part
    # of the platform's fundamentals coverage (company-level totals from the data
    # provider; segment detail lives only in un-ingested SEC-filing footnotes) —
    # never phrasing that implies a transient failure — then offer what IS available
    # (company-level revenue/growth/margins, cited; qualitative news colour). NARROW
    # + additive: it is scoped ONLY to genuinely-uncovered dimensions and explicitly
    # must NOT widen into refusing questions the tools CAN answer; the v1.9 what-if
    # projection permission, v1.10 reasoning-rigor, and all no-fabrication / grounding
    # / projection rules are UNCHANGED.
    # 1.12 (synthesis-behavior fix-plan A1 + C7 + A4, 2026-07-06): three live
    # synthesis-behaviour failures the gather-side + grounding-REWRITE fixes did
    # NOT cover — the SYNTHESIS turn itself misbehaved.
    #   (A1) The model emitted the canned "I couldn't retrieve any data" refusal
    #   despite a status=ok tool result above it — create_alert SUCCEEDED / a
    #   relations search RETURNED rows, but synthesis discarded them and refused.
    #   The prior defeatist-patch (520f130ba) covered only the grounding-rewrite
    #   path, leaving this uncovered. STRENGTHENED the TRUST YOUR TOOL RESULTS
    #   block: the canned no-data phrasings are now EXPLICITLY GATED to the case
    #   where EVERY tool returned empty/errored — forbidden while ANY status=ok /
    #   non-empty result sits above; the model must report it or confirm the action.
    #   (C7) The advice/price disclaimer MISFIRED on a valuation question ("is
    #   GOOGL's P/E expensive vs its history?") — refused as a price forecast ("I
    #   cannot predict future price movements"). Valuation-vs-history is
    #   retrospective/current analysis, not a forecast. EXTENDED the factual-
    #   lookup-not-a-prediction bullet to EXCLUDE valuation multiples (P/E,
    #   EV/EBITDA, expensive/cheap vs history/peers) from the forecast refusal.
    #   (A4) A comparison DROPPED a requested entity ("NVIDIA not relevant" on an
    #   NVDA-vs-AMD question) and invented a scope narrowing. Added the COMPARISON /
    #   MULTI-ENTITY — COVER EVERY ENTITY NAMED block: a multi-entity answer MUST
    #   cover every entity the user named, thin data is reported not dropped, and
    #   inventing a reason to exclude an entity is forbidden. NARROW + additive: no
    #   grounding / anti-fabrication / projection rule is relaxed.
    # 1.13 (fix-plan D7 + D8 + D4, 2026-07-06): three synthesis-turn defects
    # surfaced by the eval FAIL analysis.
    #   (D7) ANTI-OVER-REFUSAL ON PARTIAL TOOL FAILURE. cmp_nvda_amd had NVDA/AMD
    #   core fundamentals status=ok but ABANDONED the comparison because the
    #   SEGMENT metric query errored + news timed out (data-gap-as-give-up), and
    #   emitted no verdict. Extended the REASONING RIGOR block with a PARTIAL /
    #   ERRORED TOOL bullet: a partial/errored tool NEVER suppresses synthesis
    #   from the SUCCESSFUL results; reason qualitatively around the missing
    #   coverage field; treat an unsupported-metric / "not covered" sentinel (a
    #   sibling adds one on the market-data side) as a coverage gap to reason
    #   around, not a failure; never emit a blanket "cannot be grounded" when core
    #   data was returned.
    #   (D8) FABRICATION GUARD ON EMPTY RESULTS. compare_entities with non-US
    #   tickers returned empty -> hallucinated "Estee Lauder"; chain_competitor
    #   hallucinated "Shift4 (FOUR)" from "past FOUR quarters." Added ANTI-
    #   FABRICATION rule 4: when a tool returns EMPTY, never name an entity/ticker
    #   absent from ALL tool results, and never derive a ticker from question
    #   tokens ("four"->FOUR, "MA"->Mastercard); say the data isn't available. (A
    #   sibling handles non-US-ticker mapping on the tool side.)
    #   (D4, prompt half) NO PLACEHOLDER FOR A PRESENT FIELD. The model wrote a
    #   dash placeholder for a P/E field the tool actually returned (pe_ratio=
    #   37.32). Added a bullet to TRUST YOUR TOOL RESULTS forbidding a "-"/"N/A"
    #   placeholder for a value present in a tool result. (The sibling orchestrator
    #   agent strips the gpt-oss commentary-channel leak — the code half of D4.)
    # NARROW + additive: KEEPS every v1.9-v1.12 rule; no grounding / anti-
    # fabrication / projection rule is relaxed.
    # 1.14 (iter3_msft_earnings_citations, 2026-07-07): "Microsoft's most recent
    #   earnings report" routed correctly to query_fundamentals (status=ok, 1 item)
    #   but the single returned row was the NEWEST fiscal quarter (Q4 FY2026), not
    #   yet reported, so its revenue/net_income/eps/gross_margin cells were all
    #   null. The model blanket-declared every metric "not available", which the
    #   judge scored as a wrongful refusal over a status=ok result. Added the
    #   LATEST-QUARTER-ONLY / UNREPORTED PERIOD bullet to TRUST YOUR TOOL RESULTS:
    #   a newest-quarter row with all-null requested metrics is a not-yet-reported
    #   placeholder, NOT an all-not-available data gap — report the most-recent
    #   REPORTED quarter's figures if any other period row carries them, else state
    #   specifically that the latest fiscal quarter has not been reported yet
    #   (a timing boundary), never a generic blanket refusal. Pairs with tool_use
    #   v1.16 which makes the planner fetch periods>=4 (not periods=1) for a
    #   latest-earnings query so a reported quarter is in the payload. NARROW +
    #   additive: no grounding / anti-fabrication rule relaxed; "not available"
    #   remains correct for a specific field genuinely absent from every row.
    # 1.15 (da_tsla_revenue_2024_full_year period-mislabel, 2026-07-08): the
    #   date-anchored fundamentals fix (tool_use D3) now correctly RETRIEVES TSLA's
    #   2024 quarters (real Q1-Q3 2024 revenue values were in the tool result), but
    #   the synthesis turn RELABELLED those rows as Q3 2025 / Q4 2025 / Q1 2026 and
    #   then declared "no 2025 data available" — judge grounding=0, "Fabricated
    #   period labels ... tool returned 2024 quarters." The same nuance recurred in
    #   iter3_msft ("Fabricated period label contradicts tool scope"). Root cause:
    #   the model inferred each row's period from the "current date is 2026" system
    #   context instead of reading the row's own period_end. Added a bullet to the
    #   PERIOD-MATCHING block: every figure MUST be labelled with the EXACT
    #   period_end / fiscal period on its own row — NEVER infer, shift, or relabel
    #   the period from today's date or the conversation's "current" year (a
    #   2024-09-30 row is a Q3 2024 figure regardless of today's date); the
    #   current-date context is for recency reasoning only, never for stamping
    #   periods onto retrieved rows. NARROW + additive: reinforces the existing
    #   date-anchoring / period-binding rules; no grounding / anti-fabrication /
    #   coverage rule is weakened.
    version="1.15",
    description=(
        "Minimal synthesis-turn system prompt — strips all tool-use guidance "
        "so the model writes the final answer without narrating its methodology. "
        "Companion to chat/tool_use.py (the planning-turn prompt). "
        "Created PLAN-0107 follow-up to fix the <function_calls> XML leak. "
        "v1.1 adds the anti-fabrication row/citation constraint (analysis #3). "
        "v1.2 adds the trust-your-tool-results constraint (FINAL-67 C3). "
        "v1.3 adds the transcribe-don't-compute constraint (FINAL-67 C1). "
        "v1.4 softens v1.3: keeps digit-for-digit copy, removes the withholding/"
        "refusal language that regressed grounding, requires full cited reporting. "
        "v1.5 adds the ANTI-FABRICATION POLICY (no invented periods/rows, no "
        "off-payload entities, read scalar fields before declaring data missing) "
        "while preserving the v1.4 report-in-full balance (RC-2). "
        "v1.6 adds the PERIOD-MATCHING block (bind every figure to its row's own "
        "period label; name the closest available period when the requested one is "
        "absent rather than relabelling the nearest quarter) plus a long-series "
        "summary-stats steer (Cat-A period-selection). "
        "v1.7 adds the CITATION LABELS — REAL TOOL NAMES ONLY block (every bracketed "
        "row-citation must be an actual tool name; interpretive commentary is "
        "unsourced prose with NO bracket tag; prediction-market odds cite "
        "[get_prediction_markets row N]) so the model stops emitting non-tool "
        "labels like [commentary row N] that the phantom-citation gate rejects. "
        "v1.8 closes the news-headline citation-coverage gap: cite each FACT "
        "(not only numbers) and, mirroring the prediction-market rule, attach a "
        "[get_entity_news row N] / [search_documents row N] tag to every headline "
        "listed so bare-headline news answers stop shipping citations=[]. "
        "v1.9 permits GROUNDED, HEDGED projections for analytical / what-if "
        "questions (the ANALYTICAL / WHAT-IF block: reason and project, never "
        "refuse; derive step-by-step from cited figures; hedge + label every "
        "projected number as a scenario/estimate; never invent base inputs) and "
        "reconciles the SAFETY_FOOTER's former blanket forecast ban with the "
        "framing-aware grounding gate — the no-fabrication rules for FACTUAL "
        "claims are unchanged. "
        "v1.10 adds the REASONING RIGOR ON DEEP QUESTIONS block for deep "
        "comparison / causal / ripple answers: when a structured number is "
        "missing, reason qualitatively from OTHER retrieved evidence instead of "
        "skipping the dimension (never invent it); NEVER infer an advantage or "
        "disadvantage from absent/unretrieved data (a knowledge-graph gap is not "
        "a fact); ground every link in a causal chain to a specific retrieved "
        "number/news/relationship and surface counterpoints instead of generic "
        "optimism; cite every figure used in a conclusion and flag period/unit "
        "mismatches, replacing the blanket unmatched-source caveat with a specific "
        "note or none. Additive; keeps the v1.9 what-if permission and all "
        "no-fabrication / grounding rules. "
        "v1.11 adds the DATA-COVERAGE BOUNDARY block: when the user asks for a "
        "dimension the platform genuinely does not carry — revenue / financials by "
        "business segment, product line, or geography (absent from EODHD standard "
        "fundamentals) — the model states plainly that this specific breakdown is not "
        "part of the platform's fundamentals coverage (company-level totals only; "
        "segment detail lives in un-ingested SEC-filing footnotes) instead of the "
        "misleading 'could not be calculated from the retrieved information' that "
        "implies a transient retrieval miss, then offers what IS available. Scoped "
        "ONLY to genuinely-uncovered dimensions; must NOT cause refusals for "
        "answerable questions. "
        "v1.12 fixes three synthesis-turn behaviour bugs: (A1) gates the canned "
        "'I couldn't retrieve any data' refusal to the all-tools-empty/errored "
        "case so the model never discards a status=ok result (create_alert "
        "confirmed, relations reported); (C7) excludes valuation-vs-history "
        "multiples (P/E, EV/EBITDA, expensive/cheap vs history/peers) from the "
        "price-forecast refusal — they are retrospective analysis, always allowed; "
        "(A4) adds the COMPARISON / MULTI-ENTITY — COVER EVERY ENTITY NAMED block "
        "so a comparison never drops a requested entity or invents a scope "
        "narrowing. Additive; no grounding / anti-fabrication / projection rule "
        "relaxed. "
        "v1.13 fixes three synthesis-turn defects from the eval FAIL analysis: "
        "(D7) extends REASONING RIGOR with a PARTIAL / ERRORED TOOL rule — a "
        "partial/errored tool NEVER suppresses synthesis from the successful "
        "results; reason qualitatively around the missing coverage field and "
        "treat an unsupported-metric / 'not covered' sentinel as a gap, not a "
        "failure (fixes cmp_nvda_amd abandoning a comparison whose core "
        "fundamentals were status=ok); (D8) adds ANTI-FABRICATION rule 4 — on an "
        "EMPTY tool result, never name an entity/ticker absent from all tool "
        "results and never derive a ticker from question tokens ('four'->FOUR) "
        "(fixes the Estee-Lauder / Shift4 hallucinations); (D4 prompt half) "
        "forbids a '-'/'N/A' placeholder for a field whose value IS present in a "
        "tool result. Additive; no grounding / anti-fabrication / projection rule "
        "relaxed. "
        "v1.14 adds the LATEST-QUARTER-ONLY / UNREPORTED PERIOD bullet to TRUST "
        "YOUR TOOL RESULTS: a status=ok fundamentals result whose only/newest "
        "quarter row has all-null requested metrics (a not-yet-reported quarter) "
        "must NOT be blanket-declared 'not available' — report the most-recent "
        "REPORTED quarter's figures if any other period row carries them, else "
        "state specifically that the latest fiscal quarter has not been reported "
        "yet (a timing boundary), never a generic refusal (fixes iter3_msft). "
        "Additive; 'not available' stays correct for a field genuinely absent "
        "from every row. "
        "v1.15 adds a PERIOD-MATCHING bullet: label every figure with the EXACT "
        "period_end / fiscal period on its own tool row — never infer, shift, or "
        "relabel the period from today's date or the conversation's 'current' "
        "year (a 2024-09-30 row is a Q3 2024 figure regardless of today's date; "
        "the current-date context is for recency reasoning only). Fixes "
        "da_tsla_revenue_2024_full_year, where correctly-retrieved 2024 quarters "
        "were relabelled 2025/2026 (judge grounding=0). Additive; no grounding / "
        "anti-fabrication / coverage rule weakened."
    ),
    template=_TEMPLATE,
    parameters=frozenset({"safety"}),
)


__all__ = ["SYNTHESIS_SYSTEM_PROMPT"]
