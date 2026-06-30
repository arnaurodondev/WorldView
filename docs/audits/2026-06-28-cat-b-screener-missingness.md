# Category B Audit — Off-Payload Entity Invention (B1) & False Missingness (B2)

**Date:** 2026-06-28
**Scope:** READ-ONLY investigation. Two answer-construction defect classes that the
RC-2 anti-fabrication synthesis prompt (`synthesis@1.5`, commit `ef77c547d`) did NOT
close. No code/matcher/draft touched.

**Runs used:**
- RC-FIXED (analysis target): `tests/validation/chat_quality_benchmark/runs/run_20260628T234356Z`
- FROZEN (contrast): `tests/validation/chat_quality_benchmark/runs/run_20260627T032420Z`

**Synthesis prompt under test:** `libs/prompts/src/prompts/chat/synthesis.py` v1.5. Relevant
rules:
- Rule #2 — *NEVER add entities, tickers, or companies absent from a tool result.*
- Rule #3 — *NEVER claim returned data is missing without reading the scalar fields first.*

---

## Executive summary

| Question | Class | Dominant cause | 1.5 status | Top fix |
|----------|-------|----------------|-----------|---------|
| `ru_ai_semi_screener` | B1 | Backend universe-mismatch + dropped filters → model pads with own AI-chip allowlist | Rule #2 VIOLATED, but provoked by backend | Pass the question's filters reliably; deterministic off-payload-ticker guard |
| `iter3_top5_tech_marketcap` | B1 | **Backend data-coverage gap** — mega-caps have no `market_capitalization` rows, so screener's true top-N is sub-$65B | Rule #2 VIOLATED (RC-FIXED invents KEYS/HPE which weren't even in `grounding_sample`) | Backfill mega-cap `market_capitalization`; deterministic guard |
| `tc_price_history_msft_ytd_range` | B2 | **Tool-text gap** — the price table rendered to the LLM is Close-only; high/low exist ONLY in `grounding_fields` (eval wire), never in `item.text` | Rule #3 NOT APPLICABLE — the model read its context correctly; high/low truly absent from it | Render high/low into `_format_price_table`; add an aggregated window-range line |

**Dominant cause B1:** backend (universe mismatch + coverage gap); the model padding is a
*symptom* of being handed a wrong/empty universe it cannot reconcile with the question.
**Dominant cause B2:** the high/low scalars the judge sees in `grounding_sample` are NEVER
in the text the model is given — it is a tool-rendering omission, not a prompt-adherence
failure.

---

# B1 — OFF-PAYLOAD ENTITY INVENTION

## B1-a · `ru_ai_semi_screener`

**Prompt:** "Screen for AI semiconductor companies with market cap above $50B and positive
YoY revenue growth."

### What the tool RETURNED (RC-FIXED)
- **Tool call:** `screen_universe(sector="Technology", industry="Semiconductors", limit=100)`
  — note **no `market_cap_min`, no `revenue_growth_yoy_min`** were passed.
- **Tool result:** `item_count=1`, `total_rows=1`, `truncated=false`. `grounding_sample.fields`
  expose tickers **QRVO / SWKS / ALGM** (caps ~$8.7B / $11.1B / $11.5B). None are
  "AI-chip" leaders; none satisfy the >$50B floor the question asked for.

### What the answer ADDED
> "No AI-semiconductor companies **from the allowed AI-chip list (NVDA, AMD, AVGO, TSM,
> ARM, AMAT, ASML, MRVL, INTC, QCOM, MU, LRCX)** have both a market-cap above $50B and
> positive YoY revenue growth …"

The 12-ticker "allowed AI-chip list" is **the model's own world knowledge**, not from the
payload (which contained QRVO/SWKS/ALGM). Judge `grounding=5` (floored, GROUNDING VETO →
FAIL): *"answer claims to screen an 'allowed AI-chip list' … but tool_results only returned
QRVO, SWKS, ALGM."*

### FROZEN contrast
In the frozen run the model passed the **correct** filters
(`market_cap_min=50000000000, revenue_growth_yoy_min=0, industry=Semiconductors`) and the
screener returned **MCHP / MPWR**. The answer then **fabricated MRVL ($244.10B) and ARM**,
neither in the payload. Same grounding floor, *different* fabrication.

### Root cause
Two stacked backend-driven causes; prompt-adherence is the *third*, downstream layer:

1. **Filter non-determinism (tool-call layer).** The question's two hard constraints
   (>$50B, YoY growth>0) are tool *arguments*, and the model passed them in FROZEN but
   **dropped them** in RC-FIXED. With no thresholds the handler still binds the
   sector/industry scope (`market_data.py:1625`, no-op `min_value:0` floor) and returns a
   generic semis universe. So the LLM was handed semis it does not recognize as "AI-chip"
   and could not satisfy the question from the payload.
2. **Universe mismatch (backend semantics).** `screen_universe` has **no "AI semiconductor"
   concept** — only GICS `sector`/`industry` (`market_data.py:1580-1596`). "AI semiconductor"
   is not a screenable attribute, so the closest the model can do is `Semiconductors`, which
   returns the wrong cohort (QRVO/SWKS/ALGM are RF/analog, not AI accelerators).
3. **Prompt not followed (synthesis layer).** Faced with a payload that cannot answer an
   AI-specific question, the model substituted its own canonical AI-chip list to produce a
   "complete" negative — a **clear Rule #2 violation** ("NEVER add … companies absent from a
   tool result"). 1.5 is *necessary but insufficient*: a soft NL rule does not stop a model
   that has decided the payload is unusable.

**Dominant cause:** backend (universe mismatch) + tool-call (dropped filters). The Rule #2
violation is real but is the model's coping response to an unusable payload.

### Fixes
- **(backend / tool-call, primary)** Make the screener filters deterministic for this
  question shape. Either (a) coerce the question's numeric constraints into filter entries
  server-side when the LLM omits them, or (b) add a validation nudge that re-prompts when a
  screen question mentions a numeric threshold but the `screen_universe` call carries none.
  This removes the "unusable payload" trigger.
- **(backend, secondary)** There is no fix that makes `Semiconductors` mean "AI chips";
  document that `screen_universe` cannot express thematic universes, so the honest answer is
  "the screener cannot filter by 'AI semiconductor'; here are the semiconductors it
  returned" — not a fabricated allowlist.
- **(deterministic guard, the real backstop)** Add an **off-payload ticker guard** in the
  orchestrator: extract ticker-like tokens from the final answer, intersect against tickers
  present in the tool-result items' rendered text, and reject/strip any ticker the answer
  introduces that no tool returned (the `_extract_ticker_tokens` machinery at
  `chat_orchestrator.py:1482` already exists for the inverse check). This is the only
  mechanism that *guarantees* Rule #2 rather than requesting it.

---

## B1-b · `iter3_top5_tech_marketcap`

**Prompt:** "List the top 5 US-listed technology companies by market capitalization, in
descending order, with their market caps."

### What the tool RETURNED (RC-FIXED)
Two `screen_universe` calls:
1. `(sector="Technology", region="US", limit=5)` → top row **PLUS** ($2.07B), ROG ($2.97B),
   EPAM ($4.98B).
2. `(sector="Technology", region="US", market_cap_min=50000000000, limit=5)` → top rows
   **FLEX** ($55.63B), MCHP ($55.68B), TEL ($59.27B).

Both calls are `item_count=1, total_rows=1, truncated=false`. The sort is market-cap
**descending** (the handler defaults `sort_by`/`sort_dir` correctly, `market_data.py:1639-1655`;
`query_screen` orders before LIMIT, `fundamental_metrics_query.py:418-539`).

### What the answer ADDED
A table of **KEYS / HPE / TEL / MCHP / FLEX** ($63.80B…$55.63B). KEYS and HPE are **not in
either tool result's `grounding_sample`** — judge `grounding=0` (VETO → FAIL):
*"Answer fabricates tickers (KEYS, HPE) … that do not appear in any tool result."*

### FROZEN contrast
Frozen answer listed **TRMB / ALGM / DAY / SWKS / ZBRA** (all ~$11B), also `grounding=0`.
Frozen's second call used `market_cap_min=10000000000`. The prompt's described
"UBER/SHOP/CRM padding" is **not present in this RC-FIXED trace** — the RC-FIXED fabrication
is KEYS/HPE, a different but equivalent off-payload set.

### Root cause — **backend data-coverage gap (dominant)**
The decisive signal: with `sort_by=market_capitalization DESC` and **no upper bound**, the
genuine top-5 US tech *must* be AAPL/MSFT/NVDA/GOOGL/AMZN (all > $1T). Instead the
descending-sorted top row is **PLUS at $2.07B**, and even with `market_cap_min=$50B` the top
is **FLEX at $55.6B**. The only explanation consistent with a correct sort is that the
mega-caps **have no `market_capitalization` rows in `fundamental_metrics`** — the local
ingestion populated mid-cap fundamentals but not the mega-caps' market-cap metric. The
`market_capitalization` metric is extracted from EODHD fundamentals
(`metric_extractor.py:148`), so absence = those issuers were never fundamentals-ingested
locally. This matches the prior-memory note "screener POST projection = top backend gap."

The query code itself is **correct** — the 2026-06-12 "top-N" fix (page-selection ORDER BY
before LIMIT, `DISTINCT ON (instrument_id)` latest-value pick) is in place and sound. The
defect is the *data*, not the query.

The model's KEYS/HPE invention is a **secondary** Rule #2 violation: handed a top-5 that
visibly excludes Apple/Microsoft, the model "corrected" toward a more plausible-looking list
and introduced tickers (KEYS, HPE) that were in neither payload.

**Dominant cause:** backend data-coverage gap (mega-caps absent from `market_capitalization`).
The prompt violation is downstream of the model distrusting an obviously-wrong universe.

### Fixes
- **(backend, primary)** Backfill `market_capitalization` (and core fundamentals) for the
  mega-cap universe so a "top 5 tech by market cap" returns AAPL/MSFT/NVDA/GOOGL/AMZN. This
  is a data/ingestion task (run the EODHD fundamentals ingestion for the megacap symbol set),
  not a code change. Until then, *no* prompt or guard can make this answer correct — the
  right rows do not exist.
- **(deterministic guard, backstop)** Same off-payload ticker guard as B1-a: strip/refuse
  any answer ticker not present in a tool result. With the guard, the worst case becomes an
  honest "the screener returned FLEX/MCHP/TEL/… as the largest it has data for" instead of a
  fabricated KEYS/HPE table.
- **(prompt, marginal)** 1.5 Rule #2 already forbids this; strengthening the NL wording will
  not reliably stop a model that has decided the payload is wrong. Treat the guard, not the
  prompt, as the fix.

---

# B2 — FALSE MISSINGNESS

## B2 · `tc_price_history_msft_ytd_range`

**Prompt:** "What's MSFT's high and low so far this year?"

### What the tool RETURNED vs what the answer CLAIMED
- **Tool call:** `get_price_history(ticker="MSFT", from_date="2026-01-01",
  to_date="2026-06-29", interval="day")`.
- **`grounding_sample.fields`:** `high=489.7`, `low=356.28`, `close=365.46`, `ticker=MSFT`
  (`item_count=1`).
- **Answer:** *"the price-history data returned for Microsoft (MSFT) only includes daily
  closing prices and volume; **it does not contain the daily high and low values**. Without
  those fields I can't provide the year-to-date high and low."*

At face value this looks like a flagrant Rule #3 violation — the judge sees `high`/`low` in
the sample and marks false-missingness. **It is not.** The high/low the judge sees are NOT
in the text the model was given.

### Root cause — **tool-text omission; high/low never reach the LLM (dominant)**
Traced the exact bytes the LLM receives:

1. The price-history `RetrievedItem.text` is `_format_price_table(...)`
   (`market.py:716,727-730`). That formatter renders **only**
   `| Date | Close | Volume |` (`market.py:2038-2045`) — **no high/low columns**.
2. The window high/low (`max(bar.high)`, `min(bar.low)`) ARE computed — but only into
   `grounding_fields` via `_grounding_fields_from_bars` (`market.py:341-381, 726`). The
   docstring is explicit: *"this only fills the in-memory item; `CHAT_EVAL_GROUNDING_SAMPLES`
   still gates the wire."*
3. `grounding_fields` are consumed **only** by `sse_emitter.py` (the SSE/eval wire,
   `sse_emitter.py:799-890`) to build `grounding_sample`. They are **never** rendered into
   the LLM context.
4. The LLM context is built from `item.text` alone: `build_prompt → context_assembler.assemble`
   uses `item.text[:1000]` (`context_assembler.py:89`); the orchestrator injects that
   `_context_block` into the `role="tool"` message (`chat_orchestrator.py:3332-3345`).

So the model's actual tool message was a Close+Volume-only markdown table. **The model read
its context correctly** and truthfully reported that high/low are absent from it. The
`high=489.7 / low=356.28` exist only in the parallel `grounding_fields` instrumentation the
judge reads — a channel the model cannot see. The `grounding_sample` collapsing the whole
YTD series into one synthetic row (`total_rows=1`) with window high/low is purely an eval
artifact; the model saw ~120 Close/Volume bars and no extrema.

**This is a tool-rendering gap, not a prompt-adherence failure. Rule #3 is NOT
APPLICABLE** — there were no returned high/low scalars for the model to "read first."

### Is an aggregation also needed?
Partly. Even if individual-bar `high`/`low` were rendered per-row, "high and low so far this
year" requires `max(high)`/`min(low)` **across ~120 bars** — an aggregation the model is
unreliable at (and which would be brittle over a long table). The cleanest fix supplies the
aggregate directly so the model copies, not computes.

### Fixes (all backend/tool-text; no prompt change)
- **(primary)** Render the window range into the price-history text the LLM sees. Two
  complementary edits in `_format_price_table` / `_handle_get_price_history`
  (`market.py:2029-2045`, `596-744`):
  1. Add `High`/`Low` columns to the per-bar table (the upstream `/ohlcv/bars` payload
     already carries `high`/`low` — see `_grounding_fields_from_bars` reading `b.get("high")`).
  2. Prepend an **explicit aggregated summary line** to the table text, e.g.
     `"Window high: $489.70 — Window low: $356.28 — Latest close: $365.46"`, computed from the
     same `max(highs)/min(lows)` already done in `_grounding_fields_from_bars`. This removes
     the aggregation burden entirely: the model copies one line.
- **(consistency)** The work to compute window high/low for `grounding_fields` already
  exists (PLAN-0116 W5 / Item 3); this fix just routes the *same* numbers into `item.text`
  so the model and the judge see the same data. Today the eval can substantiate a high/low
  claim the model was never given the data to make — a silent split-brain between the wire
  and the LLM context.
- **(prompt, NOT needed)** Do not strengthen Rule #3 for this case; the model obeyed it. A
  stronger "read the fields" rule would only push the model to hallucinate high/low it
  genuinely lacks. The fix is to give it the fields.

---

## Cross-cutting observation

B1 and B2 share a **split-brain between `grounding_fields` (eval wire) and `item.text`
(LLM context)**:
- In B2 the substantiation numbers (high/low) live only in `grounding_fields`, so the judge
  rewards/penalizes against data the model never saw.
- In B1 the screener DOES render its tickers into `item.text` (so the LLM saw QRVO/SWKS/ALGM,
  KEYS-absent), making B1 a genuine Rule #2 violation — but one provoked by a wrong/empty
  backend universe.

The structural lesson: every value the eval substantiates against MUST also be present in the
text the model is given, and every off-payload entity MUST be machine-checkable, not left to
a soft NL rule.
