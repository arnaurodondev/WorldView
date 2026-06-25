# Investigation Report: chat_quality_benchmark framework

**Date**: 2026-06-11
**Investigator**: Claude (investigate skill)
**Severity**: HIGH — the benchmark reports "all green" (93.27/100, 14 PASS / 1 WARN) on a run where a human reading the raw answers sees mostly broken output (fabricated numbers, leaked tool-call control tokens, truncated stubs, a 500-error non-answer). The framework is **structurally unable to fail the failure mode that matters most** (hallucination) and its top-line report actively hides the failures it does detect.
**Status**: Root causes identified — no code changed (audit only).

---

## 1. What the framework is

Two cooperating layers under `tests/validation/chat_quality_benchmark/` + `scripts/`:

| Component | Path | Role |
|-----------|------|------|
| Runner | `scripts/run_chat_quality_benchmark.py` (1172 LOC) | Dev-logs into S9, streams each question through `/v1/chat/stream`, captures per-Q artifacts, computes advisory heuristics, optionally calls the LLM judge, renders `_report.md`. |
| Judge | `scripts/chat_quality_judge.py` (448 LOC) | Wraps the canonical `CHAT_QUALITY_JUDGE` prompt; calls DeepInfra (`deepseek-ai/DeepSeek-V4-Flash`, temp=0, `response_format=json_object`); returns 4 dimensions × 0-25. |
| Judge prompt | `libs/prompts/src/prompts/evaluation/chat_quality_judge.py` (v2.0) | 4-dim rubric: `tool_use`, `grounding`, `framing`, `refusal_judgment`. |
| Questions | `tests/validation/chat_quality_benchmark/questions/*.yaml` (5 packs) | Per-question `rubric{}` (judge contract) + `budgets{}` (advisory latency). |
| Output | `runs/run_<ts>/` | `_meta.json`, `_summary.json`, `_judge_summary.json`, `_report.md`, plus `q_<id>[_runN].json` / `.log` / `.error.txt`. |

Design intent (sound): *descriptive, not prescriptive* — capture everything, never gate the exit code, keep heuristics advisory, let the LLM judge grade quality. Offline re-grade (`--judge-only --runs-dir`) lets you iterate on the rubric without re-running chat. The split-file question catalogue and the v2.0 length-agnostic framing rewrite are good moves.

The problem is not the plumbing — it's the **scoring model, the judge's evidence diet, and the report's information hierarchy**.

---

## 2. Evidence (from `runs/run_20260609T175104Z/`)

| # | Observed | Source |
|---|----------|--------|
| E1 | `ru_mstr_news` run2: judge writes "Most claims are fabricated", scores grounding **10/25**, but total **85 = PASS**. | `q_ru_mstr_news_run2.json:130-151` |
| E2 | `ru_ai_semi_screener` runs 1-3: answer is "I cannot reach the stock screener data source right now — it returned a 500 error." → **100/100 PASS ×3**, despite `appropriate_refusal_ok=false`. | `_report.md:31-92` |
| E3 | `ru_nvda_amd_compare_qtr` run2/run3 and `ru_mstr_news` run1: answer is a **leaked tool-call stub** (`<function_calls><invoke name=...>`, `<function>…`) — control tokens rendered as the user-facing answer → **100/100** / **90/100 PASS**. | `_report.md:106-133, 274-325` |
| E4 | The judge receives tool results as **`{tool, status, item_count}` only** — no payload. The prompt then says "status=ok + items>=1 → PRESUMED GROUNDED, award 20-25." | `harness.py:634-638`; `q_ru_mstr_news_run2.json:1046-1072`; judge prompt L78-107 |
| E5 | Headline: avg **93.27/100**, dimension averages all look healthy (grounding 22.9). The grounding=10 fabrication and the 80/WARN are invisible at the top; you must read every per-run table to find them. | `_report.md:10-17` |
| E6 | Raw answer text shows systematic **leading-digit drops** ("`**,095 BTC**`", "last ` ` quarters", "`×` the revenue", "Path ` ` — (` ` hop)") and the `final_answer` event **overwrites a correctly-grounded streamed answer** with a fabricated one. Neither is flagged. | `q_ru_mstr_news_run2.json:681-939` |

---

## 3. Root causes

### F1 — CRITICAL: additive scoring lets fabrication PASS
`verdict = sum(4 dims)`, `PASS ≥ 85`, each dim ≤ 25 (`chat_quality_judge.py:80-87, 360-365`). A catastrophic grounding failure costs at most 15 points (25→10), so `10 + 25 + 25 + 25 = 85 = PASS`. **No dimension can veto.** For a financial-research agent, fabricated numbers are the single worst outcome, yet grounding alone cannot fail an answer. E1 is the proof: the judge *correctly* detected fabrication and the framework *still* stamped it PASS.

### F2 — CRITICAL: grounding is unverifiable by construction
The judge never sees tool-result **payloads** — only `status` + `item_count` (E4). It therefore *cannot* check whether "P/E is 37.73x" matches what the tool returned. The prompt resolves this blind spot by **instructing the judge to presume grounding** when `status=ok items>=1` (judge prompt L88-107). Consequence: fabrication is normally invisible; E1 was caught only because `items=1` was absurdly low against an answer full of numbers — luck, not mechanism. The grounding dimension is, in the common case, measuring "did a tool succeed", not "is the answer true."

### F3 — CRITICAL: degenerate answers score full marks
Leaked control tokens, mid-call truncation, raw JSON stubs, and tool-failure non-answers (E2, E3) all pass because **there is no "is this a coherent, complete, user-renderable answer?" dimension.** `framing` is explicitly length-agnostic and reads a stub as "appropriately concise"; `refusal_judgment` scores 25 for "no refusal phrase present"; `tool_use` scores 25 because a tool was called. A garbage answer maximises three of four dimensions. This is the classic **all-green / zero-output anti-pattern** already in project memory (`project_pipeline_quality_2026_04_29`).

### F4 — HIGH: tool failures reported as perfect quality
E2: an upstream 500 produces a graceful apology, which the judge scores 100/100. The rubric flag `appropriate_refusal_ok=false` is **not wired** to penalise a non-answer caused by infra error — `refusal_judgment` only pattern-matches refusal *phrases*, and "I cannot reach the data source right now" isn't on the list. So infra outages inflate the score instead of depressing it.

### F5 — HIGH: the report leads with the average and buries the failures
`_report.md` headline = avg score + verdict counts + per-dimension **averages** (`run_chat_quality_benchmark.py:711-733`). Everything an ML engineer actually needs — *which runs fabricated, which leaked stubs, which breached latency* — is either averaged away (grounding 22.9) or buried in per-run tables. There is no "worst-N", no score **min**, no "runs with grounding<15", no leaked-token count, no aggregated latency-breach count (3 of 5 questions breached, surfaced only as a `> ⏱` line under each run). The report's information hierarchy is inverted: rosy summary on top, failures hidden below.

### F6 — MEDIUM: two grading systems shown side-by-side, neither labelled authoritative
The headline prints both **Judge verdicts** (14 PASS/1 WARN) and **Heuristic buckets (legacy)** (11 PASS/4 WARN) with no note on which to trust or why they disagree (`_report.md:14-17`). A reader cannot tell whether the legacy buckets are deprecated noise or a second opinion.

### F7 — MEDIUM: `required_facts` / `forbidden_facts` are dead symbolic tokens
Rubrics declare e.g. `required_facts: [pe_ratio_value, as_of_date_or_period]`, `forbidden_facts: [fabricated_period]` (`00_real_user_and_aggregate.yaml:320-326`). These are **placeholder identifiers, not checkable values**, and the judge prompt contains **no instruction** on how to evaluate them. They are serialized into the RUBRIC JSON and then effectively ignored. The most precise part of the rubric contract does nothing — false assurance that "required facts" are being enforced.

### F8 — MEDIUM: positional tool_call ↔ tool_result pairing
`_build_user_prompt` zips `tool_calls[i]` with `tool_results[i]` (`chat_quality_judge.py:218-230`). Calls and results are not guaranteed index-aligned (multiple calls, interleaved/empty results); a mismatch mislabels which result belongs to which call in the evidence the judge reasons over. Pair by `tool` name / call-id instead.

### F9 — LOW: rough edges
- `--concurrency` is advertised but does nothing (`run_chat_quality_benchmark.py:865`).
- `_judge_summary.json` carries `schema_version: 1` while the judge prompt is `v2.0` — version-naming skew.
- `--max-runs-per-q` default "has been reverted by parallel-session activity multiple times" per its own help text — fragile shared-state.
- Two overlapping catalogues (`chat_eval/questions.yaml` legacy + `chat_quality_benchmark/questions/`) duplicate questions; unclear which is canonical.

### F10 — product bugs the benchmark surfaces but does not flag
Raw text shows (a) systematic **leading-digit deletion** in the rendered answer (E6) and (b) the `final_answer` event **replacing a grounded streamed answer with a fabricated one**. These are real chat bugs visible in the artifacts; the benchmark captures them and reports PASS. Worth their own `/fix-bug` once the measurement is trustworthy.

---

## 4. What's missing

1. **A veto / gate** — any single dimension below a floor (esp. grounding) must cap the verdict at FAIL, regardless of the sum.
2. **A coherence/completeness dimension** — detect control-token leakage (`<function`, `<invoke`, `<think`, fenced JSON-only), truncation, empty-after-successful-tools, and the digit-drop pattern. These are deterministic regexes; they should run *before* the LLM judge and hard-fail.
3. **Real grounding evidence** — feed the judge sampled tool-result values (or a programmatic numeric cross-check), so grounding measures truth, not tool exit status.
4. **Judge calibration** — there is no held-out human-graded set and no inter-rater check. For a thesis, the judge's *validity* is unestablished, and F1-F4 show it is currently miscalibrated. A 20-30 item gold set with human PASS/FAIL labels + agreement metric is the highest-value addition.
5. **Regression / baseline** — runs are isolated; no diff vs a previous run, no trend, no threshold. A benchmark with no baseline cannot detect regressions.
6. **Failure-first report** — lead with min score, worst-N runs, fabrication list, leaked-stub list, latency-breach count; demote the average.
7. **Wire `required_facts`/`forbidden_facts`** into the prompt with real, checkable strings — or delete them so they stop implying coverage that doesn't exist.

---

## 5. Recommended fixes (priority order)

| P | Fix | Touch |
|---|-----|-------|
| P0 | Add a **grounding veto**: `grounding < 12 ⇒ verdict=FAIL` regardless of sum. | `_finalise_verdict` |
| P0 | Add a deterministic **degenerate-answer pre-check** (control-token leak / truncation / digit-drop / empty-after-tools) that hard-fails before the judge runs. | runner + new helper |
| P1 | Pass **sampled tool-result values** to the judge so grounding is verifiable; stop instructing "presume grounded". | harness payload capture + judge prompt |
| P1 | **Report rewrite**: failure-first headline (min, worst-N, fabrication/leak/latency counts); collapse the rosy average below. | `_render_report_md` |
| P1 | Build a **20-30 item human-labelled gold set**; report judge agreement each run. | new fixture + harness |
| P2 | Wire `appropriate_refusal_ok=false` + tool-error status into a real penalty (infra-failure non-answer ⇒ not PASS). | judge prompt / pre-check |
| P2 | Pair tool_call↔tool_result by name/id, not index. | `_build_user_prompt` |
| P3 | Remove or implement `required_facts`/`forbidden_facts`; drop dead `--concurrency`; reconcile the two catalogues; fix `schema_version`. | cleanup |

This is feature-shaped work (changes what the benchmark measures and reports), so the natural next step is **`/prd`** for the scoring/reporting redesign, with the P0 veto + degenerate-answer pre-check pulled out as an immediate **`/fix-bug`** because they are small and stop the framework from lying today.

---

## 6. Open questions

- Is `tests/validation/chat_eval/` (the binary acceptance gate) still the authority, with this framework purely exploratory? If so the report should say so loudly; if not, the gate needs the veto too.
- Which judge model is intended for thesis runs? `DeepSeek-V4-Flash` is the default; a stronger judge may change calibration enough to matter for F1-F4.
- Is the `final_answer`-overwrites-streamed-tokens behaviour (F10) a known chat bug or new?
