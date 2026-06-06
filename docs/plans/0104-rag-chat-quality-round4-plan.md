# PLAN-0104 — RAG-Chat Quality Round 4

**Status**: in-progress
**Created**: 2026-06-01
**Owner**: rag-chat + market-data + libs/prompts
**Parent context**: Follow-up to PLAN-0103 W1-W27. Round 3 benchmark (`tests/validation/chat_quality_benchmark/runs/run_20260601T225231Z/`) eliminated all FAILs but surfaced 11 root-cause issues across 3 investigation dimensions (missing entities, tool-use correctness, short answers).

---

## Goals

1. Eliminate silent answer corruption (decimal-eating regex).
2. Stop the numeric-grounding validator from rewriting correct answers into refusals.
3. Stop the entity-grounding guard from refusing correct answers when ticker ≠ canonical name.
4. Close the forward-P/E data + intent gap.
5. Raise answer richness from terse single-sentence to a mandated 4-section structure.
6. Add multi-tool composition guidance for valuation-context questions.

## Non-goals

- Frontend changes.
- DB migrations.

## Added scope (post-W31, user-directed 2026-06-01)

- **W32** — One **unified** `query_fundamentals` tool (parameterised over metrics/periods/aggregation) replacing the per-metric handler proliferation. Underlying source is the same fundamentals table; one tool with a typed argument schema is preferable to N narrow tools.
- **W33** — Replace word-count benchmark heuristics with **quality-based grading**: an LLM-judge rubric over (a) which tools were called, (b) whether tool outputs were correctly cited, (c) whether the answer is well-framed vs the question's depth, (d) whether refusals are appropriate when data is missing. Short answers to shallow questions are OK; long answers required only for genuinely deep multi-tool questions.
- **W34** — Fix the pre-existing rag-chat unit-test collection `ModuleNotFoundError: No module named 'tools'` (13 test files). Critical for future agents to validate work.

## Round 5 patches (post-bench 2026-06-02, surfaced by run_20260602T012842Z)

- **W35 — `query_fundamentals` envelope alignment** (P0): the new W32 tool's response wraps snapshot values inside `metrics_by_period` / `snapshot` blocks that `numeric_grounding._flatten_tool_values` doesn't recognise as `tool:fundamentals:<TICKER>` item ids. Result: when LLM cites `37.73x` from `query_fundamentals` snapshot, validator marks it unsupported → defeatist banner fires → W31 structured answer clobbered. Fix: ensure the rag-chat handler renders `query_fundamentals` output with the same RetrievedItem id format (`tool:fundamentals:<TICKER>`) and includes the snapshot fields in `citation_meta` so numeric_grounding's entity-tag pool matches.
- **W36 — investigate `llm_second_turn_failed` empty answers** (P0): Q3 AMZN and Q5 GOOGL returned empty text after successful tool calls. Need to dive into `worldview-rag-chat-1` container logs for the second-turn LLM exception, identify the root cause (timeout? provider 5xx? context-window overflow on long tool results?), and patch.
- **W37 — W29 ticker extraction across new envelope** (P0): the two-way fallback added in W29 doesn't catch TSLA when the tool output is from `query_fundamentals` because the ticker-shaped token regex doesn't see "TSLA" in the new payload format. Audit `_check_entity_grounding` against both `get_fundamentals_history` and `query_fundamentals` output shapes and harmonise.
- **W38 — judge rubric refresh** (P1): `tests/validation/chat_quality_benchmark/questions.yaml` `expected_tools` lists need `query_fundamentals` added as an equivalent for `get_fundamentals_history`/`get_fundamentals_snapshot` so the judge doesn't penalise the LLM for picking the new unified tool.

---

## Waves

### W28 — Validator + Output Processor Correctness (P0, foundational)
Touches `services/rag-chat/`.

| # | Task | File | Why |
|---|------|------|-----|
| W28-1 | Fix `_BARE_CITATION_INT_RE` with `(?<!\.)` lookbehind | `services/rag-chat/src/rag_chat/application/pipeline/output_processor.py:51` | `$7.14`→`$7.`, `$5.11`→`$5.` silent corruption |
| W28-2 | Add regression tests: `$7.14`, `$5.11`, `0.25%`, `1.10x`, `Q3 2026` | `services/rag-chat/tests/unit/test_output_processor.py` | Prevent recurrence |
| W28-3 | Fix `_flatten_tool_values` to match `tool:<name>:<TICKER>` IDs | `services/rag-chat/src/rag_chat/application/services/numeric_grounding.py:428-482` | Scale-mismatch (181.5 vs 1.815e11) + entity-tag pool bleed |
| W28-4 | Fix `classify_number` to skip `Q\d` quarter labels | `numeric_grounding.py:290-307` | "Q2 2026" classified 7× as revenue |
| W28-5 | Guard rewrite path: skip if unsupported dominated by single-digit REVENUE; reject rewrites that start with "I cannot" and are shorter than original | `services/rag-chat/src/rag_chat/application/use_cases/chat_orchestrator.py:2244-2280` | Prevents defeatist LLM rewrite from clobbering good answer |
| W28-6 | Tests for #3-#5 | `services/rag-chat/tests/unit/test_numeric_grounding.py`, `tests/unit/test_chat_orchestrator_rewrite.py` | Regression coverage |

**Validation**: re-run `ru_amzn_revenue_yoy`, `ru_meta_eps_trend`, `ru_googl_pe_vs_history`. Expect: AMZN gives a real YoY answer; META EPS shows `$7.14` / `$7.25`; GOOGL EPS shows `$5.11`.

---

### W29 — Entity-Grounding Two-Way Fallback (P0)
Touches `services/rag-chat/`.

| # | Task | File | Why |
|---|------|------|-----|
| W29-1 | In `_check_entity_grounding`, also extract uppercase ticker tokens from `item.text` and intersect with question entity `matched_text` (lowercase) | `services/rag-chat/src/rag_chat/application/use_cases/chat_orchestrator.py:548-625` | TSLA tool text has "TSLA" but `_question_entity_ids` has only `{"tesla inc","tesla"}` — current FIX-F is one-way |
| W29-2 | Log `question_ids` + `item_ids` at refusal | same file, near line 1960 | Observability for future false-positives |
| W29-3 | Tests: TSLA fundamentals + question "Tesla gross margin" passes grounding | `services/rag-chat/tests/unit/test_chat_orchestrator_grounding.py` | Regression |

**Validation**: re-run `ru_tsla_margin_trend`. Expect: real answer, not refusal.

---

### W30 — Forward P/E Coverage (P0)
Touches `services/market-data/`, `services/rag-chat/`.

| # | Task | File | Why |
|---|------|------|-----|
| W30-1 | Add `forward_pe: float \| None`, `peg_ratio: float \| None` to `CurrentSnapshot` | `services/market-data/src/market_data/api/schemas/fundamentals.py:120-132` | Schema drops fields EODHD already provides |
| W30-2 | Populate `forward_pe` / `peg_ratio` from `highlights_data["ForwardPE"]` / `["PEGRatio"]` | `services/market-data/src/market_data/application/use_cases/get_fundamentals_history.py:316-326` | Wire field through use case |
| W30-3 | Render Forward P/E + PEG rows in snapshot block | `services/rag-chat/src/rag_chat/application/pipeline/handlers/market.py` snapshot renderer | LLM needs them visible |
| W30-4 | Extend intent classifier triggers: `forward p/e`, `peg`, `valuation`, `expensive`, `cheap` → FINANCIAL_DATA | `services/rag-chat/src/rag_chat/application/pipeline/intent_classifier.py` | Q6 routed to GENERAL → zero tools |
| W30-5 | Tests: snapshot block contains forward_pe; "What's AAPL forward P/E" → FINANCIAL_DATA | new + existing | Regression |

**Validation**: re-run `ru_aapl_forward_pe`. Expect: real forward P/E value from snapshot.

---

### W31 — Answer Structure + Composition Prompt (P1)
Touches `libs/prompts/`.

| # | Task | File | Why |
|---|------|------|-----|
| W31-1 | Add ANSWER STRUCTURE block (4 sections, 120-250 words, "single-paragraph NOT acceptable") to FINANCIAL_DATA addendum | `libs/prompts/src/prompts/chat/tool_use.py:_PER_INTENT_ADDENDA["FINANCIAL_DATA"]` | LLM mimics one-line examples |
| W31-2 | Replace one-line SNAPSHOT-VS-PERIODS example at line 303 with multi-section exemplar | same file | Anchor LLM to richer output |
| W31-3 | Add VALUATION-CONTEXT composition rule (parallel fundamentals + price_history + search_documents for ratio-vs-history Qs) | same file | Q5 only worked by luck |
| W31-4 | Bump prompt `version="1.5"` → `"1.6"`; update description | same file lines 57-62 | Versioning |
| W31-5 | Update libs/prompts unit tests for v1.6 | `libs/prompts/tests/test_chat_prompts.py` | Regression |

**Validation**: re-run all 6 `real_user_v2` questions. Expect: every answer ≥120 words, includes table + interpretation + caveats.

---

## Validation Gates

After each wave: `pytest <service>/tests/unit -q`.

After all four waves: full Round 4 benchmark on `real_user_v2` tag. Targets:
- 6/6 PASS
- 0 silent decimal corruption
- 0 unjustified refusals
- All answers ≥120 words with 4-section structure

## Bug Pattern Closures (target)

- **BP-645** (new): output_processor regex strips post-decimal digits — silent corruption
- **BP-646** (new): numeric_grounding entity-tag pool mismatch causes cross-question value bleed
- **BP-647** (new): numeric_grounding classifies quarter labels (Q2, Q3) as revenue
- **BP-648** (new): defeatist LLM rewrite clobbers correct streamed answer
- **BP-644** (extend): entity-grounding FIX-F was one-way; TSLA still trips
- **BP-649** (new): intent classifier misses forward/valuation keywords → GENERAL routing
- **BP-650** (new): CurrentSnapshot drops EODHD-provided forward_pe / peg_ratio
- **BP-651** (new): single-line prompt examples train LLM to be terse

---

## References

- Round 3 run: `tests/validation/chat_quality_benchmark/runs/run_20260601T225231Z/`
- Parent plan: PLAN-0103 (W1-W27) committed at HEAD `7f491b77`
- Investigation transcripts: 3 parallel agents reported 2026-06-01
