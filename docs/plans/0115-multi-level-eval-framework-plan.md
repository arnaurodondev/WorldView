---
id: PLAN-0115
title: Multi-Level Evaluation Framework — Trace / Tool-Chain / Reasoning + Judge Calibration
prd: none (CIKM-2026 proposal-driven; no PRD — direct plan per team-lead brief 2026-06-25)
status: draft
created: 2026-06-25
updated: 2026-06-25
deadline: 2026-06-29 (CIKM 2026 Industry Day proposal, AoE)
---

# PLAN-0115 — Multi-Level Evaluation Framework

> **Goal**: Make trace-level, tool-chain-level, and reasoning-level chat evaluation
> REAL — built and producing at least one defensible finding each — so they can be
> CLAIMED in the CIKM 2026 Industry Day proposal (due 29 Jun 2026 AoE). This is an
> evaluation-LAYER plan: it builds judges/checks OVER data the harness ALREADY
> captures. It minimises new backend/infra and plans NO corpus backfill.

> **AUDIT NOTE (revise-prd pass, 2026-06-25)** — independent verification against live code.
> Corrections applied in-place (search "CORRECTED"/"RESOLVED"): (1) allow-list is **10** tools, not
> "~13" — the proposal coverage-bound number was wrong; (2) the questions-schema-lint test does NOT
> reject extra keys, so T-W2-05 needs no schema change (false break-impact removed); (3) all 5 [VERIFY]
> items resolved against code (§ at end) — none blocking; (4) `_judge_summary.json` schema bump
> `"2.0"→"2.1"` made an explicit decision, not silent; (5) the "parallel session" caveat is now stale
> (working tree clean, all 0110 judge commits landed). All other symbol/line references spot-checked and
> found ACCURATE. Verdict: **NEEDS_MINOR_REVISION → now clean; feasible under the 4-day window.**

## Overview

No PRD. This plan is driven directly by the team-lead brief and grounded in a
code inventory of the existing eval stack (see §Codebase State below). It extends
— never redesigns — the shipped answer-quality judge (`scripts/chat_quality_judge.py`,
4 dims + 7 deterministic gates, tiered STRONG/PASS/WEAK/FAIL verdict) and the
PLAN-0110 trend/calibration scaffolding.

Surfaces affected (all under the eval harness — **NOT** product services):
- `scripts/chat_quality_judge.py` — answer-quality judge + deterministic gates (extend)
- `scripts/run_chat_quality_benchmark.py` — benchmark runner (new layer hook-in)
- `scripts/chat_quality_calibration.py` — κ calibration harness (re-run on human labels)
- `libs/prompts/src/prompts/evaluation/` — versioned judge prompts (1 new prompt, no bump to existing)
- `tests/validation/chat_quality_benchmark/` — harness, questions, gold set, trend store
- `.claude/evals/prompt_changes/` — judge-prompt-change records (semver discipline, R-prompt-versioning)
- `docs/cikm-proposal/` — the claimable findings land here

**Total estimated waves: 4** (MUST-1, MUST-2, SHOULD-3, STRETCH-4) + a §Cut Line.

## Dependency Graph

```
W1 (substantiation gate)  ─┐
                           ├─ both extend the judge; W1 before W2 only to avoid
W2 (trajectory judge)     ─┘   two parallel edits to run_chat_quality_benchmark.py
                               (merge-sensitivity, not a logical dep)

W3 (judge calibration)    ── independent; touches only gold_labels.yaml + calibration
                              re-run. Can run fully in parallel from hour 0.

W4 (reasoning sanity)     ── depends on W2's per-Q layer hook (reuses the same
                              run-loop insertion point); STRETCH, droppable.
```

Critical path for the proposal: **W3 ∥ W1 → W2**. W3 is the cheapest, highest-credibility
deliverable and should start immediately and in parallel. W4 is stretch and must not
block W1-W3.

## Codebase State Verification (read from code, not docs — 2026-06-25)

| Reference | Type | Actual Current State (verified) | Needed for this plan | Delta |
|-----------|------|---------------------------------|----------------------|-------|
| `JudgeInput.tool_calls` | dataclass field, `chat_quality_judge.py:389-397` | ordered `list[{name, arguments}]`, full arg dicts, call order preserved | trajectory judge input | **none — already captured** |
| `JudgeInput.tool_results` | dataclass field | `list[{tool, status, item_count, grounding_sample?}]` | substantiation + trajectory input | **none** |
| harness `ToolCall`, `_events_to_result` | `tests/validation/chat_eval/harness.py:166-173, 567-763` | captures call order, args, status, item_count, `grounding_sample` (when present), `raw_events` | both new judges | **none** |
| `cross_check_grounding()` | `chat_quality_judge.py:1484-1560` | DETERMINISTIC numeric claim↔sample cross-check, fully wired; trips `GROUNDING_CONTRADICTED` | MUST-1 reuses + extends | exists but **dormant** (no samples streamed) |
| `grounding_sample` SSE field | `services/rag-chat/.../sse_emitter.py:638 (`_GROUNDING_FIELD_ALLOWLIST`), 707-816 (`build_grounding_sample`), 920-923 (flag gate)` | built + capped + redacted; gated behind `CHAT_EVAL_GROUNDING_SAMPLES=true` (env, default OFF); **10** financial/intel tools allow-listed (`get_fundamentals_history`, `get_fundamentals_history_batch`, `compare_entities`, `get_price_history`, `screen_universe`, `get_market_movers`, `search_claims`, `search_entity_relations`, `get_contradictions`, `get_entity_health` — VERIFIED 2026-06-25, NOT "~13"); news/graph/narrative tools produce **None** | MUST-1 evidence source | **config-only flip — NO code change** |
| `CHAT_EVAL_GROUNDING_SAMPLES` | env flag, read from `os.environ` | **NOT set** in any compose/env file → samples not streamed today | MUST-1 needs it ON at eval time | set in eval env (config) |
| raw tool output (rows/docs) | — | **NOT persisted** anywhere (chat_audit_log = name/success/latency/count only; no payload) | — | **unreachable** → MUST-1 coverage is bounded to grounding_sample tools (honest limitation) |
| `InvariantCode`, `VerdictDecision`, `evaluate_invariants()` | `chat_quality_judge.py:209-329, 1095-1192` | 7-gate tiered model; `enabled` set toggles gates; gates emit per-code pass/fail | MUST-1 adds 1 gate; W2 adds a soft score (NOT a gate) | additive |
| `CHAT_QUALITY_JUDGE` | `libs/prompts/.../chat_quality_judge.py` | v3.0, frozen for longitudinal trend; bumping breaks comparisons | MUST-2 adds a **separate** prompt; do NOT bump this one | new prompt file |
| `chat_quality_calibration.py` | `scripts/` | `assemble`/`calibrate`; computes Cohen's κ + 2×2 confusion (false-PASS-on-fabrication cell) + per-dim MAE + accept gate (κ≥0.7 ∧ 0 fab-false-PASS) | SHOULD-3 re-runs it | **none — just needs human labels** |
| `gold_labels.yaml` | `tests/validation/chat_quality_benchmark/gold/` | 39/39 labelled but `labeler=agent-draft`; `_calibration_report.json` already computed: **κ=0.594, agreement=79.5%, 1 false-PASS-on-fabrication, MAE 6.0-8.7/dim** | SHOULD-3 human-revises | human pass over 39 items |
| question packs | `tests/validation/chat_quality_benchmark/questions/*.yaml` | 67 Qs across 5 packs; rubric has `expected_tools` (equivalence SET, unordered), `expected_depth`, `appropriate_refusal_ok`, `chat_eval_id`, `ground_truth_assertions` | W2 adds optional `intent` / `expected_chain` fields | additive YAML fields |

**Key consequences for the plan:**
1. **MUST-2 (trajectory) needs ZERO backend changes** — the ordered call/arg/result trace is already in every `q_<id>.json`.
2. **MUST-1 (substantiation) is config-only on the backend** — flip `CHAT_EVAL_GROUNDING_SAMPLES=true` at eval time; the deterministic cross-check already exists. Its coverage is HONESTLY BOUNDED to the **10** allow-listed financial/intel tools (verified count, see table above); for news/graph/narrative the finding is "unverifiable from sample" (not a false PASS). This bound is itself a proposal-honest point. **The proposal MUST cite 10, not "~13".**
3. **SHOULD-3 is a human-review wave**, not a build — the κ machinery and an agent-draft baseline already exist.

## Name Verification (BP-405 guard, git-grep pass — 2026-06-25)

Verified present (no `(NEW)` tag needed): `JudgeInput`, `VerdictDecision`, `InvariantCode`,
`evaluate_invariants`, `cross_check_grounding`, `GroundingCheck`, `detect_phantom_citation`,
`judge_answer`, `CHAT_QUALITY_JUDGE`, `cohens_kappa`, `build_confusion_matrix`,
`build_grounding_sample`, `emit_tool_result`, `_events_to_result`, `ToolCall`.

Tagged **(NEW — created in this plan)** on first mention below: `SubstantiationCheck`,
`SUBSTANTIATION_UNSUPPORTED` (InvariantCode member), `evaluate_substantiation`,
`TrajectoryJudgement`, `judge_trajectory`, `CHAT_TRAJECTORY_JUDGE` (prompt),
`ReasoningCheck`, `judge_reasoning_validity`, `CHAT_REASONING_JUDGE` (prompt),
`intent` / `expected_chain` (optional question YAML fields).

---

## Wave 1 (MUST-1): Tool-Output Substantiation Check

**Claimable finding**: *"On the 67-question benchmark, X% of answers were
SUBSTANTIATED (their quantitative claims are traceable to and consistent with the
values the called tools actually returned), Y% UNSUBSTANTIATED (claims with no
supporting sampled value), and Z% CONTRADICTED (a claim a sampled value disproves).
Substantiation is verified deterministically for the N financial/intelligence tools
that expose grounding samples; the remaining tools are reported as unverifiable —
an honest coverage bound."*

**Goal**: Today the judge only catches EMPTY-after-tools and numeric CONTRADICTION.
It does NOT catch the answer that *ignores* the retrieved data — confidently
asserting numbers the tools never returned (no contradicting sample because the
field was never claimed-against, just fabricated past). W1 exercises the dormant
grounding cross-check + adds a substantiation classification and one new gate.

**Depends on**: none. **Estimated effort**: 6-8 h. **Layer**: eval harness (judge).

### Tasks

#### T-W1-01: Flip `CHAT_EVAL_GROUNDING_SAMPLES` for eval runs (config)
**Type**: config · **depends_on**: none · **blocks**: T-W1-02..05
**Target files**: `tests/validation/chat_quality_benchmark/README.md` **(NEW — no top-level
README exists today; only `gold/README.md` + `trend/README.md`. Either create this file or
fold the instructions into `results/chat_model_eval/_arm_recreate.sh`, which DOES exist and
already carries the live-eval env block)**; the eval run command / `_arm_recreate.sh` env block
under `results/chat_model_eval/` (VERIFIED present).
**What to build**: Document + wire that the substantiation benchmark run exports
`CHAT_EVAL_GROUNDING_SAMPLES=true` so S8 streams `grounding_sample` on `tool_result`
frames. No service code change — the flag is read per-call from `os.environ`
(`sse_emitter.py:920-923`; the gate condition is at 920-923, the builder at 707). The harness
targets a LOCAL S8 (`RAG_CHAT_BASE_URL`, default `http://localhost:8009`; harness L304), so the
env flag IS settable at eval time (resolves [VERIFY] #1). Verify a live S8 turn emits a sample
(e.g. ask "What is AAPL's P/E?"; `pe_ratio` IS in the `get_fundamentals_history` allow-list, so
confirm `grounding_sample.fields.pe_ratio` appears in the captured `q_*.json`).
**Acceptance**:
- [ ] A captured `q_<id>.json` from a fundamentals question contains a non-empty `result.tool_results[].grounding_sample.fields`.
- [ ] README/`_arm_recreate.sh` documents the flag + the **10**-tool allow-list coverage bound.
- [ ] Flag is set ONLY in the eval path; product compose files untouched (flag stays OFF in prod).

#### T-W1-02: `SubstantiationCheck` value object + `evaluate_substantiation()` (NEW)
**Type**: impl · **depends_on**: T-W1-01 · **blocks**: T-W1-03,04
**Target files**: `scripts/chat_quality_judge.py`
**What to build**: A deterministic, LLM-free classifier `evaluate_substantiation(answer_text, tool_results) -> SubstantiationCheck (NEW)`.
Reuse the EXISTING claim-extraction + field-association machinery
(`_CLAIM_NUMBER_RE`, `_strip_code_spans`, `_collect_grounding_fields`,
`_nearest_field`, `_values_within_tolerance`). For every numeric claim associated
to a sampled field, classify:
- `substantiated` — within tolerance of a sampled value (== the existing `matched`);
- `contradicted` — outside tolerance (== existing `contradicted`, already gated);
- `unsupported` — a quantitative claim associated to a sampled FIELD NAME present in the
  sample set but whose VALUE is absent for that field (the field was sampled, the claim
  cites it, no value within tolerance AND no value to contradict — i.e. the answer asserts
  a number the tool did not return), counted distinctly from `unmatched` (claims with no
  associated sampled field at all → neutral, never failed).
`SubstantiationCheck` fields: `substantiated:int, unsupported:int, contradicted:int,
unmatched:int, coverage:str ("verified"|"presumed"), examples:list[dict]`.
**Entities/Components**:
- **Name**: `SubstantiationCheck` (NEW) — frozen dataclass, `to_dict()` for artefact persistence (feedback_audit_returned_value_persistence: must reach the artefact, not just a counter).
- **Invariants**: `coverage=="presumed"` ⟹ all counts 0 (no samples → never assert unsupported). `unsupported` counts ONLY claims that name a sampled field but mismatch every sampled value of it.
**Logic**: Build on `cross_check_grounding`'s loop; do NOT duplicate the regex/association code — factor the shared association step if needed, but keep `cross_check_grounding` behaviour byte-identical (its tests must stay green, R19).
**Tests to write**:
| Test | Verifies | Type |
|------|----------|------|
| test_substantiation_matched_value | claim == sample → substantiated | unit |
| test_substantiation_unsupported_field_present_value_absent | claim names sampled field, value not returned → unsupported (NOT unmatched) | unit |
| test_substantiation_unmatched_no_field | claim with no associated field → unmatched, neutral | unit |
| test_substantiation_presumed_when_no_samples | no grounding_sample → coverage=presumed, all counts 0 | unit |
| test_substantiation_does_not_change_cross_check | `cross_check_grounding` output unchanged on shared fixtures | unit |
- Minimum 8 tests; edge cases: percent claims, scale suffixes (B/M/K), year-like ints excluded, code-span numbers excluded.
**Acceptance**:
- [ ] `evaluate_substantiation` returns `coverage="verified"` only when ≥1 sample present.
- [ ] Existing `cross_check_grounding` tests all pass unchanged.

#### T-W1-03: `SUBSTANTIATION_UNSUPPORTED` invariant gate (NEW) + priority wiring
**Type**: impl · **depends_on**: T-W1-02 · **blocks**: T-W1-04
**Target files**: `scripts/chat_quality_judge.py`
**What to build**: Add `InvariantCode.SUBSTANTIATION_UNSUPPORTED` (NEW). Wire it into
`evaluate_invariants` (fires when `SubstantiationCheck.unsupported > 0` AND
`coverage=="verified"`), `_ALL_INVARIANTS`, `_INVARIANT_PRIORITY` (rank it just
BELOW `GROUNDING_CONTRADICTED` — a value the tool disproves is worse than a value
the tool never returned — and ABOVE `PHANTOM_CITATION`), and the `enabled` toggle.
Default-ENABLED, but the gate can NEVER fire in `presumed` coverage, so flag-off
runs are byte-identical (back-compat invariant, mirrors W2/W3 discipline).
Add a `_substantiation_unsupported_fail_result()` builder (mirror of
`_grounding_contradicted_fail_result`) so it hard-FAILs offline with a precise reason.
**Downstream test impact**: any test asserting the LENGTH/membership of `_ALL_INVARIANTS`
or the full `gate_results` dict will see one new key — update those fixtures (R19: update, never weaken).
**Tests**:
| Test | Verifies | Type |
|------|----------|------|
| test_unsupported_gate_fires_verified | unsupported>0 + verified → FAIL, fail_reason=SUBSTANTIATION_UNSUPPORTED | unit |
| test_unsupported_gate_silent_presumed | unsupported counts 0 in presumed → gate passes | unit |
| test_priority_contradicted_beats_unsupported | both fire → fail_reason=GROUNDING_CONTRADICTED | unit |
| test_unsupported_gate_disableable | enabled set excludes it → reported True | unit |
- Minimum 5 tests.
**Acceptance**:
- [ ] Gate present in `_ALL_INVARIANTS` + `_INVARIANT_PRIORITY` + `enabled` toggle.
- [ ] Flag-off (presumed) run produces byte-identical verdicts to pre-W1.

#### T-W1-04: Persist substantiation in artefact + `_judge_summary.json` rollup
**Type**: impl · **depends_on**: T-W1-03 · **blocks**: T-W1-05
**Target files**: `scripts/chat_quality_judge.py` (`judge_answer` attaches `substantiation_check`),
`scripts/run_chat_quality_benchmark.py` (aggregate the % into `_judge_summary.json` + `_report.md`).
**What to build**: Emit `substantiation_check.to_dict()` on every `judge` block; roll up
benchmark-wide counts (substantiated / unsupported / contradicted / unmatched / unverifiable)
into `_judge_summary.json` and a `_report.md` section "Substantiation (MUST-1)".
**Acceptance**:
- [ ] `_judge_summary.json` carries `substantiation: {verified_n, unsupported_n, contradicted_n, unverifiable_n, pct_unsubstantiated}`.
- [ ] `_report.md` lists the % unsubstantiated and the per-question unsupported examples.

#### T-W1-05: Produce the finding (run + write to proposal)
**Type**: docs · **depends_on**: T-W1-04 · **blocks**: none
**Target files**: `docs/cikm-proposal/` (a substantiation-finding fragment).
**What to build**: Run the 67-Q benchmark with the flag ON + judge ON; record the
substantiation breakdown; write the one-sentence claimable finding (with the honest
coverage bound) into the proposal evidence folder.
**Acceptance**:
- [ ] A committed run dir + a proposal fragment stating the X/Y/Z % with the tool-coverage caveat.

### Pre-read
- `scripts/chat_quality_judge.py:1207-1560` (cross-check), `:1095-1205` (gates), `:266-329` (objects)
- `services/rag-chat/.../sse_emitter.py:638` (`_GROUNDING_FIELD_ALLOWLIST` — 10 tools), `:707-816` (`build_grounding_sample` shape), `:920-923` (flag gate)

### Validation Gate
- [ ] ruff check passes on changed files
- [ ] mypy passes on `scripts/`
- [ ] ≥13 new unit tests pass; ALL existing `chat_quality_judge` tests pass (R19)
- [ ] Flag-off run byte-identical to baseline (regression assertion)
- [ ] Finding written to `docs/cikm-proposal/`

### Architecture Compliance
- [ ] No product-service code changed (eval-layer only; backend change is config-only flag)
- [ ] R12 structlog / R10 UUIDv7 / R11 UTC — N/A (no entities, no logging added in scripts)
- [ ] Judge-prompt versioning — N/A (W1 is deterministic, NO prompt change)

### Break Impact
| Broken File | Why | Fix |
|-------------|-----|-----|
| `scripts/` judge unit tests asserting `_ALL_INVARIANTS` length/keys | new gate member | add `SUBSTANTIATION_UNSUPPORTED: True` to expected gate-map fixtures |
| `_judge_summary.json` schema-readers / golden snapshots | new `substantiation` block | update snapshot; additive key, forward-compatible |

### Regression Guardrails
- **feedback_audit_returned_value_persistence**: `SubstantiationCheck` MUST reach the artefact (`to_dict`), not just a metric — the gate result is load-bearing for the finding.
- **feedback_prompt_input_mismatch**: the substantiation check MUST read the SAME `grounding_sample` values the judge prompt renders and `cross_check_grounding` consumes — one parser, one source. Do NOT introduce a second claim regex.
- **BP-405**: `SubstantiationCheck` / `evaluate_substantiation` / `SUBSTANTIATION_UNSUPPORTED` are tagged NEW above; all reused names verified present.

---

## Wave 2 (MUST-2): Trajectory / Tool-Chain Quality Judge

**Claimable finding**: *"A trajectory-quality judge over the captured tool-call
trace scores each turn on routing-correctness, chain coherence, failure-recovery,
and non-redundancy (0-100). Mean trajectory quality on the 67-Q benchmark is X;
N turns exhibited a wasteful-redundancy or unrecovered-failure trajectory despite
producing an acceptable final answer — a class the answer-only judge cannot see."*

**Goal**: The captured trace (ordered tool names + arguments + status + item_count,
already in every artefact) is never JUDGED. Today tool quality = equivalence-set
membership only (the `tool_use` dim: "did ≥1 expected tool fire?"). W2 adds a
SEPARATE LLM judge over the trajectory itself: right tools for the intent, sensible
order, recovery after a failed call, no wasteful redundant calls.

**Depends on**: none logically; sequence AFTER W1 only to serialise edits to
`run_chat_quality_benchmark.py` (merge-sensitivity). **Effort**: 8-10 h. **Layer**: eval harness.

### Tasks

#### T-W2-01: `CHAT_TRAJECTORY_JUDGE` prompt (NEW), versioned v1.0
**Type**: impl · **depends_on**: none · **blocks**: T-W2-02..04
**Target files**: `libs/prompts/src/prompts/evaluation/chat_trajectory_judge.py` (NEW),
`libs/prompts/src/prompts/evaluation/__init__.py` (export), `libs/prompts/CHANGELOG.md`,
`.claude/evals/prompt_changes/2026-06-2X-chat_trajectory_judge-v1.0.md` (NEW record).
**What to build**: A NEW `PromptTemplate` `CHAT_TRAJECTORY_JUDGE` (NEW), version `1.0`,
distinct from `CHAT_QUALITY_JUDGE` (do NOT touch the frozen answer-judge prompt).
It grades the TRAJECTORY on four sub-dimensions, each 0-25, from the ordered trace +
the question intent:
- `routing` — were the tools appropriate to the question's intent?
- `ordering` — is the call sequence sensible (e.g. resolve entity before querying it)?
- `recovery` — after a failed/empty call, did the agent retry/substitute sensibly (or give up / loop)?
- `efficiency` — minimal non-redundant calls (penalise repeated identical calls, unused fetches)?
Output strict JSON `{routing, ordering, recovery, efficiency, reviewer_summary}`.
**Versioning discipline**: semver + content_hash via `PromptTemplate`; record the new
prompt in `.claude/evals/prompt_changes/` and the CHANGELOG (a NEW prompt at v1.0 does
NOT break a longitudinal series — there is none yet — but the record establishes the baseline).
**Acceptance**:
- [ ] `CHAT_TRAJECTORY_JUDGE.identifier()` returns a stable id; prompt-change record committed.
- [ ] `CHAT_QUALITY_JUDGE` body + version UNCHANGED (assert in test).

#### T-W2-02: `judge_trajectory()` + `TrajectoryJudgement` (NEW)
**Type**: impl · **depends_on**: T-W2-01 · **blocks**: T-W2-03,04
**Target files**: `scripts/chat_trajectory_judge.py` (NEW) OR a new section in
`scripts/chat_quality_judge.py` (decide by file size; prefer a NEW module to keep the
answer-judge file bounded).
**What to build**: `judge_trajectory(inp: JudgeInput, *, llm=None) -> dict` mirroring
`judge_answer`'s structure: reuse the SAME `_build_user_prompt` tool-trace rendering
(ordered `call N: tool(args) -> status items=K`), feed it + the question + the
question's `intent`/`expected_chain` (W2-05) to `CHAT_TRAJECTORY_JUDGE`. Return
`TrajectoryJudgement` (NEW): `{trajectory_score:int (0-100, sum of 4), sub_scores:dict,
reviewer_summary:str, judge_prompt_id:str}`. Plus a DETERMINISTIC pre-signal that does
NOT need the LLM: `redundant_call_pairs` (count of identical (name,args) repeats) and
`unrecovered_failures` (a failed/empty call with no subsequent successful call to a
substitute tool) — these are cheap, offline, and corroborate the LLM efficiency/recovery sub-scores.
**Logic**: when no LLM key, return the deterministic signals + `trajectory_score=None`
(SKIPPED) so the layer still produces artefacts in CI.
**Tests**:
| Test | Verifies | Type |
|------|----------|------|
| test_trajectory_redundant_calls_detected | two identical (name,args) → redundant_call_pairs=1 | unit |
| test_trajectory_unrecovered_failure | failed call, no later success → unrecovered_failures=1 | unit |
| test_trajectory_recovered_failure | failed call then successful substitute → unrecovered=0 | unit |
| test_trajectory_skipped_without_llm | no key → score None, deterministic signals still present | unit |
| test_trajectory_uses_ordered_trace | mock LLM receives the ordered trace string | unit |
- Minimum 8 tests (LLM mocked via the `JudgeLLM` Protocol — no network).
**Acceptance**:
- [ ] Deterministic signals computed offline; LLM sub-scores when key present.
- [ ] Reuses existing trace-rendering (no second trace formatter).

#### T-W2-03: Wire the trajectory layer into the runner + artefact + summary
**Type**: impl · **depends_on**: T-W2-02 · **blocks**: T-W2-04
**Target files**: `scripts/run_chat_quality_benchmark.py`
**What to build**: In the per-question loop, after `judge_answer`, call `judge_trajectory`
(behind a `--trajectory` flag, default ON when `--judge` is on). Attach a `trajectory`
block to each `q_<id>.json`; roll mean trajectory_score + redundancy/recovery counts into
`_judge_summary.json` + a `_report.md` "Trajectory (MUST-2)" section. The trajectory verdict
is REPORTED ALONGSIDE the answer verdict — it does NOT change the answer FAIL/PASS (separation
of concerns: a turn can have a great answer via a sloppy trajectory, and that is the finding).
**Acceptance**:
- [ ] `_judge_summary.json` carries `trajectory: {mean_score, redundant_turns_n, unrecovered_turns_n}`.
- [ ] `--trajectory` toggle; answer verdict unchanged when trajectory judge runs.

#### T-W2-04: Produce the finding (run + write to proposal)
**Type**: docs · **depends_on**: T-W2-03 · **blocks**: none
**Target files**: `docs/cikm-proposal/`
**Acceptance**:
- [ ] Mean trajectory score + the redundancy/unrecovered-failure count, with ≥1 concrete example turn, written to the proposal evidence folder.

#### T-W2-05: Optional `intent` / `expected_chain` question fields (additive)
**Type**: schema · **depends_on**: none · **blocks**: T-W2-02 (soft — judge works without them)
**Target files**: `tests/validation/chat_quality_benchmark/questions/20_chain_of_tools.yaml`
(+ the schema-lint test that loads packs).
**What to build**: Add OPTIONAL `intent: <one-line>` and `expected_chain: [toolA, toolB]`
(an ordered HINT, not a hard checklist — the judge treats it as guidance) to the
multi-tool questions. Backward-compatible: absent fields → judge infers intent from the prompt.
**Downstream test impact (CORRECTED 2026-06-25)**: the existing schema-lint test
`tests/validation/chat_quality_benchmark/test_questions_schema.py` does **NOT** enforce a
closed allow-list of keys — `test_rubric_required_keys_present` only checks that *required*
rubric keys are PRESENT (`missing = [k for k in required_keys if k not in rubric]`); it never
rejects *extra/unknown* keys. Therefore adding `intent`/`expected_chain` (whether as top-level
question keys or rubric keys) needs **NO schema-lint change** — the earlier "must accept the
new optional keys / extend the allowed-keys set" was a false break-impact. If you WANT the new
fields validated (recommended, to catch typos), ADD a new positive test that, when present,
`expected_chain` is a list of strings and `intent` is a non-empty str — additive, R19-safe.
The 20_chain_of_tools.yaml pack today has **8** chain questions (verified), so "≥6 annotated"
is achievable.
**Acceptance**:
- [ ] Existing schema-lint test passes unchanged with and without the new fields; ≥6 of the 8 chain questions annotated.
- [ ] (Optional) a new additive positive-validation test for `intent`/`expected_chain` shape.

### Pre-read
- `scripts/chat_quality_judge.py:405-540` (JudgeLLM Protocol + `_build_user_prompt` trace rendering)
- `libs/prompts/src/prompts/evaluation/chat_quality_judge.py` (PromptTemplate pattern)
- `tests/validation/chat_quality_benchmark/questions/20_chain_of_tools.yaml`

### Validation Gate
- [ ] ruff + mypy on changed files
- [ ] ≥8 new unit tests (LLM mocked); existing judge tests unchanged (R19)
- [ ] `CHAT_QUALITY_JUDGE` unchanged (regression assert)
- [ ] Finding written to `docs/cikm-proposal/`

### Architecture Compliance
- [ ] Judge-prompt versioning: new prompt at v1.0 with content_hash + a `.claude/evals/prompt_changes/` record; frozen answer-prompt untouched
- [ ] Eval-layer only; no product-service changes

### Break Impact
| Broken File | Why | Fix |
|-------------|-----|-----|
| ~~questions-schema-lint test~~ | ~~new optional YAML keys~~ | **NOT BROKEN (corrected 2026-06-25): `test_questions_schema.py` only checks for required-key PRESENCE, never rejects extra keys. No change needed.** |
| `_judge_summary.json` readers | new `trajectory` block | additive; update snapshot |

### Regression Guardrails
- **BP-405**: `judge_trajectory` / `TrajectoryJudgement` / `CHAT_TRAJECTORY_JUDGE` tagged NEW; reused names verified.
- **Judge-prompt-versioning discipline**: a new prompt must carry semver + content_hash and a change record — do NOT inline an unversioned string.
- **feedback_prompt_input_mismatch**: trajectory judge must consume the SAME captured trace the answer judge sees — reuse `_build_user_prompt` rendering, do not re-derive the trace from `raw_events`.

---

## Wave 3 (SHOULD-3): Judge Calibration — Real Cohen's κ

**Claimable finding**: *"The answer-quality judge was calibrated against a 39-item
human-labelled, failure-mode-stratified GOLD set. Judge-vs-human Cohen's κ = X
(agreement Y%), with the false-PASS-on-fabrication cell at N items — the
safety-critical asymmetry we hold to zero."*

**Goal**: An agent-draft label set + the κ machinery + a computed baseline
(κ=0.594, agreement 79.5%, 1 false-PASS-on-fabrication) ALREADY exist. W3 is the
cheap, high-credibility wave: a HUMAN revises the 39 agent-draft labels (independently
of `machine_verdict`), re-runs `chat_quality_calibration.py calibrate`, and reports a
DEFENSIBLE κ. This converts "rubrics exist, no human verdicts" → a real number.

**Depends on**: none — fully parallel from hour 0. **Effort**: 3-5 h (mostly human labelling).
**Layer**: eval harness (data + re-run).

### Tasks

#### T-W3-01: Human-revise the 39 GOLD labels
**Type**: docs (human-in-the-loop) · **depends_on**: none · **blocks**: T-W3-02
**Target files**: `tests/validation/chat_quality_benchmark/gold/gold_labels.yaml`
**What to build**: A human (Arnau) reviews each of the 39 agent-draft entries using
`REVIEW_SHEET.md` + `LABELING_NOTES.md`, setting `human_verdict` (PASS/FAIL) and
`human_dims` INDEPENDENTLY of `machine_verdict` (the draft notes already flag the
ambiguous items, e.g. `gold_fabrication_01`'s honesty-caveat tension). Update
`labeler` from `agent-draft` to the human id + `labeled_at`. Resolve the one current
false-PASS-on-fabrication (`gold_fabrication_09`) — confirm whether it is a true judge
miss (then it stays as evidence of the bound) or a draft-label error.
**Acceptance**:
- [ ] All 39 entries carry `labeler != agent-draft` and a human verdict + dims.
- [ ] Ambiguous items have a one-line rationale in `notes`.

#### T-W3-02: Re-run calibration + record the number
**Type**: docs · **depends_on**: T-W3-01 · **blocks**: T-W3-03
**Target files**: `tests/validation/chat_quality_benchmark/gold/_calibration_report.{json,md}` (regenerated)
**What to build**: Run `python scripts/chat_quality_calibration.py calibrate`; commit the
regenerated κ + confusion + per-dim MAE. If κ < 0.7, do NOT silently weaken the bar —
report the honest number and the dominant disagreement axis (the proposal can claim a
calibrated judge with a stated κ and a named limitation; that is more credible than a
suspiciously-high number).
**Acceptance**:
- [ ] `_calibration_report.json` regenerated from human labels; κ + agreement + confusion committed.

#### T-W3-03: Write the finding
**Type**: docs · **depends_on**: T-W3-02 · **blocks**: none
**Target files**: `docs/cikm-proposal/task2_judge_validation_sheet.md` context note +
a calibration fragment under `docs/cikm-proposal/`.
**Note**: `docs/cikm-proposal/task2_judge_validation_sheet.md` is the RELATION-extraction
judge sheet (64 items, separate judge) — DISTINCT from this chat-quality calibration.
The finding must NOT conflate the two; label this as the CHAT-AGENT answer-judge κ.
**Acceptance**:
- [ ] Proposal fragment states the chat-judge κ + agreement + the zero-fab-false-PASS goal, explicitly distinguished from the relation-judge sheet.

### Validation Gate
- [ ] `chat_quality_calibration.py calibrate` exits cleanly; report regenerated
- [ ] No code change weakens the κ bar (R19 — the gate stays κ≥0.7 ∧ 0 fab-false-PASS even if the current run is below it)
- [ ] Finding written + the two judges (chat vs relation) kept distinct

### Regression Guardrails
- **feedback_never_delete_tests / R19**: do NOT lower `KAPPA_BAR` to manufacture an "accepted" verdict.
- **Two-judge confusion**: the relation-judge sheet (`task2_judge_validation_sheet.md`) and the chat-judge gold set are different populations — keep findings separate.

---

## Wave 4 (STRETCH-4): Reasoning / Inference-Validity Sanity Layer

**Claimable finding** (framed as EMERGING, not validated): *"A minimal LLM
reasoning-validity check grades whether each evidence→claim inference in an answer
is supported, contradicted, or unsupported by the cited tool evidence. We report it
as an emerging signal only: the reasoning judge is itself an LLM, i.e. the very
unreliable component the talk warns about — so we ship a sanity check (agreement
with the deterministic substantiation gate on the overlap set), NOT a validated benchmark."*

**Goal**: A minimal, HONESTLY-CAVEATED inference-validity layer. Must NOT block W1-W3.

**Depends on**: W2's per-question layer hook (reuses the same run-loop insertion point) +
W1's `SubstantiationCheck` (the sanity anchor). **Effort**: 6-8 h. **Layer**: eval harness.

### Tasks

#### T-W4-01: `CHAT_REASONING_JUDGE` prompt (NEW) v0.1 + `judge_reasoning_validity()` (NEW)
**Type**: impl · **depends_on**: W2-01 (prompt pattern) · **blocks**: T-W4-02
**Target files**: `libs/prompts/.../chat_reasoning_judge.py` (NEW), prompt-change record,
`scripts/chat_trajectory_judge.py` or a new `scripts/chat_reasoning_judge.py` (NEW).
**What to build**: A v0.1 (explicitly pre-1.0 = emerging) prompt that, given the answer's
claims + the grounding sample + tool trace, labels each major inferential claim
`supported | unsupported | contradicted`. `judge_reasoning_validity()` returns
`ReasoningCheck (NEW)`: `{supported:int, unsupported:int, contradicted:int, reviewer_summary:str}`.
**Acceptance**:
- [ ] Versioned NEW prompt at v0.1 with change record; clearly marked emerging.

#### T-W4-02: Sanity check vs the deterministic substantiation gate
**Type**: impl · **depends_on**: T-W4-01, W1 · **blocks**: T-W4-03
**Target files**: `scripts/run_chat_quality_benchmark.py` (report section)
**What to build**: On the OVERLAP set (turns with grounding samples), compute agreement
between the LLM reasoning judge's `contradicted` and the deterministic
`SubstantiationCheck.contradicted`/`unsupported`. Report the agreement as the
SANITY metric — if the LLM judge disagrees with the deterministic check, that is the
evidence of its unreliability (the honest framing).
**Acceptance**:
- [ ] A reasoning-vs-deterministic agreement number on the overlap set, in `_report.md`.

#### T-W4-03: Write the emerging-signal finding
**Type**: docs · **depends_on**: T-W4-02 · **blocks**: none
**Target files**: `docs/cikm-proposal/`
**Acceptance**:
- [ ] A clearly-caveated "emerging" paragraph: the reasoning layer + its sanity agreement, with the explicit irony note that an LLM reasoning-judge is itself the unreliable thing.

### Validation Gate
- [ ] ruff + mypy; ≥5 new tests (LLM mocked)
- [ ] Reasoning layer is OFF by default (`--reasoning` flag) — never affects answer/trajectory verdicts
- [ ] Finding framed as emerging, not a validated benchmark

### Regression Guardrails
- **BP-405**: `ReasoningCheck` / `judge_reasoning_validity` / `CHAT_REASONING_JUDGE` tagged NEW.
- **Honesty constraint**: the prompt + finding MUST state the LLM-judging-LLM circularity; no validated-benchmark claim.

---

## Cross-Cutting Concerns
- **Judge-prompt versioning**: two NEW prompts (`CHAT_TRAJECTORY_JUDGE` v1.0, `CHAT_REASONING_JUDGE` v0.1). Each gets a `.claude/evals/prompt_changes/` record + a CHANGELOG line. The frozen `CHAT_QUALITY_JUDGE` v3.0 is NOT touched (no longitudinal break).
- **No backend code change**: MUST-1 needs only the `CHAT_EVAL_GROUNDING_SAMPLES` env flag flipped at eval time; everything else is eval-layer Python.
- **No corpus backfill** (explicit brief constraint).
- **Coverage honesty**: MUST-1 is bounded to ~13 grounding-sample tools; this bound is reported, not hidden.

## Risk Assessment
- **Critical path**: W3 (human labelling) gates only itself; W1→W2 share `run_chat_quality_benchmark.py` (serialise edits). Start W3 + W1 at hour 0.
- **Highest risk**: W1's substantiation precision (false "unsupported" on a legitimately-grounded claim). Mitigation: reuse the proven association/tolerance machinery; the gate fires only in `verified` coverage; conservative — `unmatched` (no associated field) is never failed.
- **Backend dependency risk**: `CHAT_EVAL_GROUNDING_SAMPLES` must be ON for the live S8 the harness hits; verify with a probe turn (T-W1-01) before the full run.
- **Stretch leakage**: W4 must stay flag-OFF and out of the answer/trajectory verdict path so a wobbly reasoning judge never corrupts the MUST findings.

## Cut Line (4-day window, due 29 Jun AoE)
- **MUST ship (non-droppable)**: **W1** (substantiation finding) + **W3** (κ calibration). W3 is the cheapest and highest-credibility — do it first, in parallel.
- **STRONGLY ship**: **W2** (trajectory). Highest novelty for the proposal; ZERO backend change. Drop only if W1+W3 are at risk.
- **DROPPABLE (stretch)**: **W4** (reasoning). If time-pressed, ship W4-01 prompt + the honest "emerging, not yet built out" sentence WITHOUT the full sanity-agreement run — the proposal can name it as planned/emerging without the number. Do not let W4 consume W1/W2/W3 time.

**Recommended order**: (W3 ∥ W1) → W2 → (W4 if slack). If only 2 days remain: ship W3 + W1 fully, W2 partial (deterministic redundancy/recovery signals + finding, defer the LLM trajectory sub-scores), cut W4.

## [VERIFY] Items for the Implementer — RESOLVED (audit pass 2026-06-25)
1. **[RESOLVED ✓]** Live S8 honours `CHAT_EVAL_GROUNDING_SAMPLES=true`: the flag is read per-call from
   `os.environ` at `sse_emitter.py:920-923` (gate condition) — no settings/restart needed. The 67-Q
   harness targets a **local** S8 via `RAG_CHAT_BASE_URL` (default `http://localhost:8009`, harness L304),
   so env IS settable at eval time. `pe_ratio` ∈ `get_fundamentals_history` allow-list, so the probe turn
   is valid. A real `results/chat_model_eval/GROUNDING_235b_oss120b/` run dir already exists (grounding
   runs have been attempted). NO blocker. Still re-probe one fundamentals turn before the full W1 run.
2. **[RESOLVED ✓]** Harness module path: the 67-Q runner `scripts/run_chat_quality_benchmark.py` imports
   `from chat_eval.harness import ...` (L80) and `from chat_eval.grading import is_refusal` (L79) — i.e. the
   harness is `tests/validation/chat_eval/harness.py`. The `tests/validation/chat_quality_benchmark/`
   directory holds the **question packs + gold set + trend store** (DATA), loaded via `load_questions`. So:
   edit question YAML under `chat_quality_benchmark/questions/`, but the SSE/trace capture logic lives in
   `chat_eval/harness.py` (`_events_to_result` L567, captures `grounding_sample` L648, `ToolCall` L167,
   `raw_events` L245). Both new judges read the captured artefacts — no harness edit required.
3. **[RESOLVED ✓]** `chat_quality_judge.py` is **2211 lines** (verified). A new module
   `scripts/chat_trajectory_judge.py` IS warranted — do NOT grow the answer-judge file. Note the file imports
   are flat (`sys.path` injected); the new module can `from chat_quality_judge import JudgeInput, JudgeLLM, _build_user_prompt`.
4. **[RESOLVED — ACTION REQUIRED]** `_JUDGE_SUMMARY_SCHEMA_VERSION = "2.0"` at
   `run_chat_quality_benchmark.py:411` (field serialised as `"schema_version": "2.0"`). Adding
   `substantiation`/`trajectory` blocks is ADDITIVE and forward-compatible, BUT the trend store
   (`scripts/chat_quality_trend.py`) reads this file — **bump to `"2.1"`** and confirm the TrendStore
   loader tolerates the new minor (it should; the blocks are nested, not new top-level required columns).
   Decide the bump in T-W1-04 / T-W2-03, not silently.
5. **[RESOLVED ✓ — caveat now STALE]** Working tree is **clean** for `scripts/chat_quality_judge.py`,
   `run_chat_quality_benchmark.py`, and `chat_quality_calibration.py` (`git status --short` empty). All
   PLAN-0110 W1-W6 judge commits are LANDED (last: `e1a706dec` PHANTOM_CITATION). No active worktree branch
   is named for judge/0110/0115 work. The "PLAN-0110 W-series recently churned both" warning is now stale —
   safe to start. **NOTE:** the current checkout is on `feat/frontend-enhancement-sprint` with uncommitted
   `presentation/` deck files; **branch PLAN-0115 work onto its own branch** (`git worktree add` per R42),
   do NOT implement on the frontend-sprint branch.
