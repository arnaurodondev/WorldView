---
id: PRD-0091
title: "Chat-Quality Scoring & Reporting Model Redesign"
status: draft
created: 2026-06-11
updated: 2026-06-11
author: "human + claude"
services: ["rag-chat (S8)", "tooling (scripts/, libs/prompts, tests/validation)"]
priority: P1
estimated-waves: 6
parent_investigation: docs/audits/2026-06-11-investigation-chat-quality-benchmark-framework.md
related_prd: PRD-0030 (daily-briefings-prompt-library — owns libs/prompts PromptTemplate semver)
---

> **Scope boundary — read first.** A *parallel mechanical-fix workstream* (tracked
> as the `/fix-bug` follow-on to the 2026-06-11 investigation) is already shipping
> the five immediate patches the audit calls P0/P1: (1) a grounding veto in
> `_finalise_verdict`, (2) a deterministic degenerate-answer pre-check
> (control-token leak / truncation / digit-drop / empty-after-tools), (3) a
> tool-failure penalty wiring `appropriate_refusal_ok=false`, (4) a failure-first
> report headline, (5) a single `--baseline` diff. **This PRD does NOT re-specify
> those patches.** It specifies the deeper redesign those patches do not solve:
> a principled scoring model, *verifiable* grounding (payload values, not exit
> status), an *empirically validated* judge (gold set + agreement metric),
> *durable* longitudinal regression tracking, and a report information hierarchy
> built for an ML engineer. The mechanical fixes are stop-gaps that "stop the
> framework from lying today"; this PRD is what makes it trustworthy and
> thesis-defensible.

# PRD-0091: Chat-Quality Scoring & Reporting Model Redesign

## 1. Problem Statement

### 1.1 Background

The chat-quality benchmark (`scripts/run_chat_quality_benchmark.py` + `scripts/chat_quality_judge.py`
+ the `CHAT_QUALITY_JUDGE` v2.0 prompt in `libs/prompts/src/prompts/evaluation/chat_quality_judge.py`)
is the instrument the thesis uses to claim the RAG-chat agent produces grounded,
high-quality financial answers. The 2026-06-11 investigation
(`docs/audits/2026-06-11-investigation-chat-quality-benchmark-framework.md`)
found the instrument structurally unable to fail the failure mode that matters
most. On run `run_20260609T175104Z` it reported **93.27/100, 14 PASS / 1 WARN**
while a human reading the raw answers saw fabricated numbers, leaked tool-call
control tokens (`<function_calls><invoke …>` rendered as the user answer),
truncated stubs, and a 500-error non-answer — all scored PASS.

Three structural defects drive this, and none is fixed by the mechanical patches:

- **Additive scoring (F1).** `verdict = sum(4 dims)`, each ≤25, PASS ≥85
  (`chat_quality_judge.py:80-87`). A catastrophic grounding failure costs at
  most 15 points, so `grounding=10 + 25 + 25 + 25 = 85 = PASS`. The veto patch
  caps *one* dimension below *one* floor; it does not give us a defensible,
  documented verdict model that an examiner can interrogate.
- **Unverifiable grounding (F2).** The judge sees only `{tool, status, item_count}`
  (`harness.py:630-640`) and is *instructed to presume grounding* when
  `status=ok items>=1` (judge prompt L86-107). It therefore measures "did a tool
  succeed", not "is the number true". The `tool_result` SSE frame carries no
  payload *values* — only a bounded `result_preview` of `{id, title}`
  (`sse_emitter.py:419-510`). Fabrication is invisible *by construction*.
- **Unvalidated judge (audit §4.4).** There is no human-labelled gold set, no
  inter-rater/agreement metric, no acceptance bar for the judge itself, and no
  recalibration tie to prompt-version bumps. For a thesis, the judge's *validity*
  is unestablished — and F1-F4 show it is currently miscalibrated.

Two more gaps block trustworthy iteration: runs are isolated (no durable
baseline/trend store — F5/§4.5), and the report leads with the average and buries
the failures (F5).

### 1.2 Problem

The benchmark cannot **fail** the answers that should fail, cannot **prove** an
answer is grounded, cannot **demonstrate** that its own judge agrees with a human,
cannot **detect a regression** across runs, and **hides** the failures it does
detect. As an evaluation instrument for a thesis claim, it is not currently
defensible.

### 1.3 Business Value

- **Thesis credibility.** The evaluation chapter's central claim ("grounded,
  high-quality answers") rests on this instrument. An examiner who reads
  `run_20260609T175104Z` and sees fabrication-scored-PASS will reject the claim.
  A validated judge with a published agreement metric (Cohen's κ) and a veto-gated
  verdict model is *defensible under questioning*.
- **Engineering signal.** A failure-first report + durable trend store turns the
  benchmark from a vanity number into a regression gate that catches the agent
  getting worse between commits.
- **Correctness of the product.** Verifiable grounding is the only way to detect
  the real chat bugs the artifacts already contain (leading-digit drops;
  `final_answer` overwriting a grounded stream with a fabricated one — F10) before
  they reach a user.

---

## 2. Users & Use Cases

### 2.1 Target Users

| User Type | Description | Primary Need |
|-----------|-------------|--------------|
| ML / platform engineer | Iterates on the chat agent (prompts, tools, retrieval) | A report that makes regressions and failures impossible to miss, and a verdict they can trust |
| Thesis author (Arnau) | Defends the evaluation methodology | A *validated* judge (gold set + κ) and a verdict taxonomy an examiner cannot trivially break |
| Reviewer / examiner | Audits the evaluation chapter | Evidence the judge agrees with humans; a documented, principled scoring model |
| CI / automation (future) | Gates merges on chat quality | A stable machine-readable verdict + regression signal with an exit code |

### 2.2 Use Cases

| ID | As a... | I want to... | So that... | Priority |
|----|---------|-------------|------------|----------|
| UC-1 | ML engineer | Have any answer with a hard-invariant violation (fabrication, leaked control tokens, infra non-answer) marked FAIL regardless of the soft score | A polished-but-wrong answer can never PASS | must-have |
| UC-2 | ML engineer | See the judge's grounding verdict backed by *sampled tool-result values*, not tool exit status | Grounding measures truth, not "a tool ran" | must-have |
| UC-3 | Thesis author | Show the judge agrees with human labels at κ ≥ a stated bar on a held-out gold set | The judge's validity is established and citable | must-have |
| UC-4 | ML engineer | See a run diffed against a durable baseline and trend, with regressions surfaced at the top | I catch the agent getting worse between commits | must-have |
| UC-5 | ML engineer | Open the report and see worst-first: FAILs, fabrications, leaks, latency breaches — before any average | I never miss a failure buried under a rosy mean | must-have |
| UC-6 | Thesis author | Re-grade an existing run offline against a new rubric/judge without re-running chat | I can iterate on calibration cheaply (preserve `--judge-only`) | must-have |
| UC-7 | ML engineer | Keep a single longitudinal series even across a judge-prompt bump, with the discontinuity annotated | My trend line isn't silently invalidated by a prompt change | nice-to-have |

### 2.3 User Flows

**Primary flow (UC-1/2/4/5):**
1. Engineer runs `python scripts/run_chat_quality_benchmark.py --tags smoke`.
2. Runner streams each question through S9 `/v1/chat/stream`, capturing the
   enriched `tool_result` SSE frames (now carrying *sampled grounding values* —
   FR-5/§6.3).
3. The deterministic **invariant gate** runs first (control-token leak, truncation,
   digit-drop, empty-after-tools, infra-error non-answer). Any hit → hard FAIL,
   recorded with the triggering rule; the LLM judge still runs for diagnostic
   sub-scores but cannot lift the verdict above FAIL.
4. The LLM judge grades the soft quality dimensions and — when grounding samples
   are present — performs a value cross-check.
5. `_finalise_verdict` composes the **tiered verdict** (§7 AD-1): correctness gates
   first, then the soft quality band.
6. The runner writes the run artefacts, **appends a row to the durable trend store**
   (`scripts/.../trend/trend.sqlite` — §6.4), diffs against the registered baseline,
   and renders a **failure-first report** (§6.6).
7. Periodically (or on a prompt bump), engineer runs
   `--calibrate --gold-set <path>` to recompute judge-vs-human agreement (§6.6.2).

---

## 3. Functional Requirements

| ID | Requirement | Priority | Use Case |
|----|------------|----------|----------|
| **Scoring model** ||||
| FR-1 | Replace the single additive `score = sum(4 dims) ≥ 85` verdict with a **lexicographic / tiered model**: a set of **hard-FAIL invariants** (correctness gates) is evaluated *before* a **soft quality score**; any invariant violation caps the verdict at FAIL irrespective of the soft score. | must-have | UC-1 |
| FR-2 | Define the **verdict taxonomy** as `FAIL` / `WEAK` / `PASS` / `STRONG` with explicit thresholds, plus a `FAIL` **reason code** (which gate fired) and a separate `quality_score` (0-100) retained for trend continuity. | must-have | UC-1 |
| FR-3 | Define the **hard-FAIL invariant set**: (a) control-token / stub leakage; (b) truncation / mid-call cut-off; (c) empty-after-successful-tools; (d) infra-error non-answer (tool `transport_error`/5xx with no grounded substance); (e) **grounding contradiction** (a sampled tool value disproves a numeric claim); (f) `grounding` soft-dim below floor. Each invariant is independently toggleable and individually reported. | must-have | UC-1 |
| FR-4 | Preserve **longitudinal comparability** with prior thesis runs: the soft `quality_score` remains an additive 0-100 over the four (or five) dimensions so historical means stay comparable; the *verdict* is the new gated decision layered on top. Document the discontinuity introduced when the verdict model changes (a one-time re-grade of the latest baseline run under both models is recorded). | must-have | UC-3, UC-7 |
| **Verifiable grounding** ||||
| FR-5 | Capture **sampled tool-result payload values** (not just `{id,title}`) in the `tool_result` SSE frame, behind an env flag, redacted + size-capped, so the judge can cross-check numeric claims against what the tool actually returned. | must-have | UC-2 |
| FR-6 | Add a **programmatic numeric cross-check**: extract numeric claims from the answer, match each against the captured grounding samples within a tolerance, and emit a `grounding_check` block (`matched` / `unmatched` / `contradicted` counts + examples). A `contradicted` claim trips invariant FR-3(e). | must-have | UC-2 |
| FR-7 | Feed the captured grounding samples into the judge prompt and **delete the "PRESUME GROUNDED" instruction**; grounding is scored against evidence, with an explicit fallback band for the legacy case where no samples are present. | must-have | UC-2 |
| FR-8 | Enforce hard size / PII bounds on captured samples: per-frame byte cap, per-value char cap, field allow-list (numeric + short-string fields only; never raw document bodies), and redaction of any portfolio/account identifiers. | must-have | UC-2 |
| **Judge calibration & validity** ||||
| FR-9 | Define and persist a **human-labelled GOLD set**: N items, sampling strategy, and a label schema of overall `PASS/FAIL` **plus per-dimension** scores, stored as a versioned fixture. | must-have | UC-3 |
| FR-10 | Compute a **judge-vs-human agreement metric** each calibration run: Cohen's κ on the binary PASS/FAIL verdict, simple agreement %, and a 2×2 confusion matrix (incl. the asymmetric cost: a false-PASS on a fabrication is the worst cell). | must-have | UC-3 |
| FR-11 | Define an **acceptance bar for the judge itself** (κ threshold + zero tolerance on the false-PASS-fabrication cell on the gold set) and **fail the calibration run** if unmet. | must-have | UC-3 |
| FR-12 | Tie **recalibration to prompt/judge version**: any bump of `CHAT_QUALITY_JUDGE.version` or change of judge model id requires a fresh calibration run before the new judge is used for thesis numbers; the run artefact records the judge `version` + model id + κ. | must-have | UC-3, UC-7 |
| **Longitudinal regression tracking** ||||
| FR-13 | Persist a **durable trend store** across runs (not a single `--baseline` diff): one row per (run, question, dimension/verdict) plus a run-level summary, in a committed, queryable store. | must-have | UC-4 |
| FR-14 | On each run, **detect regressions** vs the registered baseline and a rolling window: per-question verdict downgrades (PASS→WEAK/FAIL), `quality_score` drops beyond a noise threshold, new invariant violations, and latency-breach increases. | must-have | UC-4 |
| FR-15 | Surface regressions at the **top** of the report and as a machine-readable `_regressions.json`; provide `--set-baseline <run_ts>` to register the current run as the comparison baseline. | must-have | UC-4, UC-5 |
| **Report / UX** ||||
| FR-16 | Rewrite the report **information hierarchy** failure-first: lead with verdict counts (FAIL first), min/worst-N scores, the fabrication list, the leaked-stub list, the latency-breach count, and the regression delta vs baseline; demote the average and per-dimension means into a collapsible appendix. | must-have | UC-5 |
| FR-17 | Make each FAIL **impossible to miss**: the triggering invariant, the offending answer excerpt, and (for grounding contradictions) the claim-vs-sample mismatch are shown inline, not averaged away. | must-have | UC-5 |
| FR-18 | Print **exactly one authoritative verdict system**; demote or remove the legacy heuristic buckets (F6) so a reader is never shown two disagreeing scores without a labelled authority. | must-have | UC-5 |
| FR-19 | Preserve offline iteration: `--judge-only --runs-dir <path>` still re-grades a stored run; the invariant gate and grounding cross-check run on the stored artefacts (no chat re-run). | must-have | UC-6 |

---

## 4. Non-Functional Requirements

| ID | Requirement | Target Metric | Rationale |
|----|------------|---------------|-----------|
| NFR-1 | SSE grounding-sample overhead | ≤ +1 KB per `tool_result` frame (hard cap); ≤ +5% end-to-end chat latency | The frame is also consumed by the live frontend; bloat is unacceptable |
| NFR-2 | Grounding capture is opt-in for prod | Default OFF in production; ON only when `CHAT_EVAL_GROUNDING_SAMPLES=true` | Eval-only data must not leak into normal traffic or logs |
| NFR-3 | Judge determinism preserved | `temperature=0`, `response_format=json_object`, recorded seed when supported | Reproducible grading across re-runs |
| NFR-4 | Calibration cost bound | A full gold-set calibration ≤ N judge calls, runnable offline from stored artefacts | Calibration must be cheap enough to run on every prompt bump |
| NFR-5 | Trend store portability | Single-file, dependency-light, diff-friendly enough to commit | Lives in-repo for thesis reproducibility; no external DB |
| NFR-6 | No exit-code regression | Benchmark still never gates the shell exit code unless `--strict` is passed | The framework stays descriptive by default (audit §1 design intent) |

---

## 5. Out of Scope

- The five mechanical P0/P1 patches (veto, degenerate pre-check, tool-failure
  penalty, failure-first headline, single `--baseline` diff) — owned by the
  parallel `/fix-bug` workstream. This PRD *supersedes* their stop-gap shape with
  a principled model but does not re-implement them from scratch.
- Fixing the underlying **product** chat bugs the benchmark surfaces (F10:
  leading-digit deletion; `final_answer` overwriting a grounded stream). These get
  their own `/fix-bug` once the measurement is trustworthy. This PRD only makes
  them *visible and FAIL-ing*.
- Any change to the live chat agent's behaviour, prompts, or tool routing.
- A frontend surface for the benchmark report (stays Markdown + JSON).
- Reconciling the two question catalogues (`chat_eval/questions.yaml` vs
  `chat_quality_benchmark/questions/`) beyond what FR-19 needs — tracked as F9 cleanup.
- Multi-judge ensembles / a second judge model as primary (kept as an open question, OQ-3).

---

## 6. Technical Design

### 6.1 Affected Services

| Service / Area | Changes | Impact Level | Notes |
|---------|---------|-------------|-------|
| **S8 rag-chat** | `sse_emitter.py`: extend `tool_result` frame with an optional, capped, redacted `grounding_sample` block (FR-5/FR-8); plumb sampled values from the tool-execution layer | HIGH | The frame is shared with the frontend — must stay forward-compatible (R11/AD-4) |
| **scripts/chat_quality_judge.py** | New tiered verdict (`_finalise_verdict`), invariant gate, numeric grounding cross-check, dual-read of new SSE fields, pair-by-name tool↔result | HIGH | Core scoring redesign |
| **scripts/run_chat_quality_benchmark.py** | Capture grounding samples; invariant gate orchestration; trend-store append; regression diff; report rewrite; demote legacy buckets | HIGH | Report + persistence |
| **libs/prompts/.../chat_quality_judge.py** | Judge prompt v3.0: delete "PRESUME GROUNDED", add grounding-sample reasoning, add tiered-verdict awareness | HIGH | Version bump triggers FR-12 recalibration |
| **tests/validation/chat_quality_benchmark/** | New `gold/` fixtures (gold set + human labels), `trend/` store, `calibration/` outputs | MED | New eval assets, committed |
| **tests/validation/chat_eval/harness.py** | Capture `grounding_sample` from `tool_result` into `ChatRunResult.tool_results`; persist on artefact | MED | The harness already captures `{tool,status,item_count}` at L630-640 — extend that block |

### 6.2 API Changes

No HTTP API (S9 gateway) request/response shapes change. The only wire change is
the **SSE `tool_result` event payload** (an internal streaming contract), specified
in §6.3 because it is event-shaped.

### 6.3 Event Changes (SSE `tool_result` frame)

The `tool_result` SSE event (`SSEEmitter.emit_tool_result`, `sse_emitter.py:441-510`)
gains one optional, bounded, opt-in field. **No existing field changes**; the
legacy 4-key payload (`type, tool, status, item_count`) stays byte-identical when
the flag is off (preserves frontend snapshot tests and the harness pattern-match).

#### `tool_result` — new optional field `grounding_sample`

- **Emitted only when** `CHAT_EVAL_GROUNDING_SAMPLES=true` (NFR-2) and `status=ok`.
- **Shape** (all caps enforced server-side per FR-8):
  | Field | Type | Default | Nullable | Description |
  |-------|------|---------|----------|-------------|
  | `grounding_sample` | object | omitted | yes | Present only when flag on + status ok |
  | `grounding_sample.fields` | object | `{}` | no | Allow-listed `{field_name: value}` pairs sampled from ≤K result rows; numeric or short-string values only |
  | `grounding_sample.sampled_rows` | int | 0 | no | How many rows were sampled (for "is the sample representative?") |
  | `grounding_sample.total_rows` | int | 0 | no | Total rows the tool returned (vs sampled) |
  | `grounding_sample.truncated` | bool | false | no | True if values were cut to satisfy the byte cap |
- **Hard bounds** (constants alongside `_PREVIEW_MAX_ITEMS` in `sse_emitter.py`):
  `GROUNDING_MAX_ROWS = 3`, `GROUNDING_MAX_FIELDS_PER_ROW = 8`,
  `GROUNDING_VALUE_MAX_CHARS = 32`, `GROUNDING_SAMPLE_MAX_BYTES = 1024`.
- **Field allow-list**: a per-tool allow-list of numeric/identifier fields
  (e.g. `revenue, eps, gross_profit, pe_ratio, period, ticker, confidence`).
  Document bodies, narrative text, and any portfolio/account identifiers are
  **never** sampled (FR-8). Unknown tools degrade to **no sample** (id/title
  preview only — current behaviour), never to raw-payload leakage.
- **Forward compatibility**: additive optional field with omit-when-empty
  semantics — same pattern already used for `result_preview` / `reason` /
  `duration_ms` (`sse_emitter.py:493-506`). Frontend ignores unknown keys (R11).

### 6.4 Database / Storage Changes

No service database changes. One **new in-repo trend store** under the eval tree.

#### Store: `tests/validation/chat_quality_benchmark/trend/trend.sqlite`

A single committed SQLite file (NFR-5 — dependency-light, portable, queryable).

- **Table `runs`**:
  | Column | Type | Nullable | Notes |
  |--------|------|----------|-------|
  | run_ts | TEXT | no | PK; UTC run-id (`run_YYYYMMDDTHHMMSSZ`) |
  | started_at | TEXT | no | ISO-8601 UTC |
  | judge_prompt_version | TEXT | no | e.g. `3.0` (from `CHAT_QUALITY_JUDGE.version`) |
  | judge_model_id | TEXT | no | e.g. `deepseek-ai/DeepSeek-V4-Flash` |
  | verdict_model_version | TEXT | no | tiered-model schema version (FR-4 discontinuity tracking) |
  | n_questions | INT | no | |
  | n_pass / n_weak / n_fail / n_strong | INT | no | verdict counts |
  | mean_quality_score | REAL | no | the additive 0-100 (longitudinal continuity, FR-4) |
  | is_baseline | INT | no | 1 if registered baseline (FR-15) |
- **Table `question_results`**:
  | Column | Type | Nullable | Notes |
  |--------|------|----------|-------|
  | run_ts | TEXT | no | FK → runs.run_ts |
  | question_id | TEXT | no | |
  | run_index | INT | no | 0-based per-question repeat |
  | verdict | TEXT | no | FAIL/WEAK/PASS/STRONG |
  | fail_reason | TEXT | yes | invariant code when verdict=FAIL |
  | quality_score | INT | no | 0-100 additive |
  | dim_tool_use / dim_grounding / dim_framing / dim_refusal | INT | no | 0-25 each |
  | grounding_contradicted | INT | no | # numerically-contradicted claims (FR-6) |
  | latency_breach | INT | no | 1 if over budget |
  - **Indexes**: `(question_id, run_ts)` for trend queries; `(run_ts)` for run rollups.
- **Why SQLite over JSON-lines/CSV**: queryable trend windows + atomic append +
  no parse-the-world; one file commits cleanly (no per-run file explosion). A
  newline-delimited JSON sidecar (`trend.jsonl`) is *also* written for grep-ability
  and zero-tooling inspection.

#### Fixtures: `tests/validation/chat_quality_benchmark/gold/`

- `gold_set.yaml` — the frozen GOLD set: each item is a `{question_id, run_ref,
  answer_text, tool_trace, grounding_sample}` snapshot drawn from real runs (FR-9).
- `gold_labels.yaml` — human labels: `{item_id, human_verdict: PASS|FAIL,
  human_dims: {tool_use, grounding, framing, coherence}, labeler, labeled_at}`.
- `calibration/<judge_version>_<ts>.json` — per-calibration output: κ, agreement %,
  confusion matrix, per-dimension MAE, accept/reject against the bar (FR-10/11).

### 6.5 Domain Model Changes (judge / runner data structures — no service entities)

#### New value object: `VerdictDecision` (in `chat_quality_judge.py`)

- **Purpose**: the composed, tiered verdict an answer receives.
- **Frozen**: yes.
- **Attributes**:
  | Attribute | Type | Required | Validation | Description |
  |-----------|------|----------|------------|-------------|
  | verdict | Verdict (enum) | yes | enum member | FAIL/WEAK/PASS/STRONG |
  | quality_score | int | yes | 0-100 | additive soft score (FR-4 continuity) |
  | fail_reason | InvariantCode \| None | yes | enum or None | which gate fired (None unless FAIL) |
  | gate_results | dict[InvariantCode, bool] | yes | all gates present | per-invariant pass/fail (FR-3 reporting) |
  | grounding_check | GroundingCheck | yes | — | numeric cross-check outcome (FR-6) |
  | dimensions | dict[str,int] | yes | 4 keys, 0-25 | raw judge sub-scores |
- **Invariants**: `verdict==FAIL ⟺ fail_reason is not None`; `quality_score == sum(dimensions)`.

#### New enum: `Verdict`

| Value | Meaning | Threshold (when no gate fired) |
|------|---------|-------------------------------|
| STRONG | Gates pass + quality_score ≥ 90 | top band |
| PASS | Gates pass + quality_score ≥ 75 | acceptance |
| WEAK | Gates pass + quality_score 60-74 | needs work, not a hard failure |
| FAIL | Any hard invariant violated, OR quality_score < 60 | unconditional |

#### New enum: `InvariantCode` (FR-3 gates)

| Value | Trips when |
|------|-----------|
| `CONTROL_TOKEN_LEAK` | answer contains `<function`, `<invoke`, `<think`, or fenced JSON-only stub |
| `TRUNCATED` | answer ends mid-token / mid-table / mid-call (digit-drop pattern, unbalanced markdown) |
| `EMPTY_AFTER_TOOLS` | ≥1 tool returned `status=ok items>=1` but answer has no substantive synthesis |
| `INFRA_NON_ANSWER` | all relevant tools `transport_error`/5xx and the answer is an apology with no grounded substance |
| `GROUNDING_CONTRADICTED` | a numeric claim is contradicted by a captured `grounding_sample` value (FR-6) |
| `GROUNDING_FLOOR` | judge `grounding` sub-dim < floor (default 12) |

#### New value object: `GroundingCheck` (FR-6)

| Attribute | Type | Description |
|-----------|------|-------------|
| matched | int | numeric claims that matched a sampled value within tolerance |
| unmatched | int | claims with no corresponding sample (no evidence either way) |
| contradicted | int | claims a sample disproves → trips `GROUNDING_CONTRADICTED` |
| examples | list[dict] | `{claim, nearest_sample, delta}` for the report |
| evidence_mode | str | `verified` (samples present) \| `presumed` (legacy, no samples) |

### 6.6 Report / UX Design

#### 6.6.1 Run report (`_report.md`) — failure-first hierarchy (FR-16/17/18)

```
# Chat Quality Benchmark — <run_ts>
## ⛔ Verdict  (authoritative)
FAIL 4 · WEAK 2 · PASS 7 · STRONG 2        ← FAIL leads, always
Regressions vs baseline <ts>: 2 questions downgraded ↓        ← top, not buried
## ⛔ Failures  (every FAIL, expanded — impossible to miss)
- ru_mstr_news run2 — FAIL[GROUNDING_CONTRADICTED]
    claim "271,474 BTC" vs sample total_holdings=… (Δ …)   ← claim-vs-sample inline
    answer excerpt: "…purchased an additional ,095 BTC…"
- ru_nvda_amd_compare_qtr run3 — FAIL[CONTROL_TOKEN_LEAK]
    answer excerpt: "<function_calls><invoke name=…>"
## ⏱ Latency breaches: 3/5 questions  (list)
## 📉 Regressions (machine: _regressions.json)
<details><summary>Soft-score appendix (means, per-dimension averages)</summary>
  Judge avg quality_score 78.1 · grounding 14.2 · …   ← demoted, collapsed
</details>
```

The legacy heuristic buckets (F6) are **removed from the headline** and, if kept
at all, appear only inside the collapsed appendix clearly labelled "legacy /
non-authoritative" (FR-18).

#### 6.6.2 Calibration report (`calibration/<judge_version>_<ts>.json` + `.md`)

Leads with **accept/reject vs the bar** (FR-11), then κ, agreement %, the 2×2
confusion matrix with the **false-PASS-on-fabrication cell highlighted**, and
per-dimension MAE vs human labels. This is the artefact the thesis cites for the
judge's validity (UC-3).

### 6.7 Data Flow

#### Grounding capture path (FR-5 → FR-6/7)
```
Tool execution (S8) → allow-list + cap + redact (FR-8) → emit_tool_result(grounding_sample)
  → SSE → harness captures into ChatRunResult.tool_results → artefact JSON
  → judge numeric cross-check (GroundingCheck) + judge prompt evidence → verdict gate
```

#### Verdict composition path (FR-1 → FR-2/3)
```
answer + tool_trace + grounding_samples
  → deterministic invariant gate (FR-3 codes)   [runs FIRST, hard-FAIL]
  → LLM judge (4 soft dims, evidence-backed grounding)
  → _finalise_verdict: if any gate fired → FAIL(reason); else band quality_score
  → VerdictDecision
```

#### Trend / regression path (FR-13 → FR-14/15)
```
VerdictDecision per (run,question,repeat) → append runs/question_results to trend.sqlite + trend.jsonl
  → diff vs is_baseline=1 run + rolling window → _regressions.json + report top section
```

#### Calibration path (FR-9 → FR-10/11/12)
```
gold_set.yaml + gold_labels.yaml → judge each gold item (offline, stored artefacts)
  → confusion matrix + Cohen's κ + per-dim MAE → accept/reject vs bar
  → calibration/<judge_version>_<ts>.json   (gates whether this judge version is "thesis-blessed")
```

---

## 7. Architecture Decisions

| # | Decision | Alternatives Considered | Trade-offs | Rationale |
|---|----------|------------------------|------------|-----------|
| **AD-1** | **Tiered / lexicographic verdict**: deterministic hard-FAIL invariants gate first; soft additive `quality_score` only *bands* answers that already passed the gates. | (A) **Veto dimension only** — keep additive sum, cap verdict if one dim < floor. (B) **Multiplicative** — `verdict = Π(dim/25)` so any low dim crushes the product. (C) **Tiered/lexicographic** (chosen). | (A) is the mechanical patch — easy, but a single soft floor is a blunt instrument and still trusts the LLM judge for the *catastrophic* checks (leaked tokens, truncation) it demonstrably mis-scores (F3). (B) is smooth but uninterpretable to an examiner ("why 0.41?") and still lets a *judge mis-score* propagate — a 24/25 on a fabricated answer stays ~0.92. (C) puts the *deterministic, cheap, reliable* checks (regexes for leaks/truncation; numeric cross-check for fabrication) where the LLM is weakest, and reserves the LLM for the *graded* qualities it's good at. | **Choose C.** Correctness is a *gate*, not a *weighted ingredient*. Fabrication and control-token leakage are deterministically detectable and must be unfailable-to-fail; the LLM judge should never be able to "buy back" a hard failure with polish. This is also the most defensible to an examiner: "an answer that leaks tool stubs or states a number a tool contradicts is FAIL, full stop — here is the rule." |
| **AD-2** | Keep the additive **0-100 `quality_score`** as a *retained sub-metric* even though the verdict is gated. | Drop the additive score entirely and report only the tier. | Dropping it breaks comparability with every prior thesis run. | FR-4: the means stay comparable longitudinally; only the *decision layer* is new. The thesis can show "quality_score trend unchanged, but N answers that previously PASSed now correctly FAIL". |
| **AD-3** | **Sampled values + programmatic numeric cross-check**, judge sees samples. | (A) Pass the *entire* tool payload to the judge. (B) Keep `{status,item_count}` and trust the judge. (C) Sample + cross-check (chosen). | (A) blows the SSE byte budget (NFR-1), risks PII, and floods the judge context. (B) is the status quo that produced F2. (C) bounds size/PII (FR-8) and makes the *decisive* check (contradiction) deterministic, not LLM-dependent. | **Choose C.** A regex/tolerance numeric match is cheaper and more reliable than asking an LLM "is 271,474 BTC in this payload?"; the judge gets samples to *reason over qualitative* grounding, the cross-check *decides* numeric contradiction. |
| **AD-4** | SSE `grounding_sample` is **additive, opt-in, omit-when-empty**. | New SSE event type; or always-on. | New event = more frontend coordination; always-on = prod PII/latency risk. | Mirrors the existing `result_preview`/`reason`/`duration_ms` extension pattern (`sse_emitter.py:493-506`); R11 forward-compat; NFR-2 keeps it eval-only. |
| **AD-5** | Trend store = **single committed SQLite + jsonl sidecar** in-repo. | Postgres table in a service DB; external TSDB; per-run JSON only. | Service DB = cross-service coupling for a dev tool (violates the spirit of R7); external = not reproducible for thesis; per-run JSON = no queryable trend (status quo). | NFR-5: portable, queryable, reproducible, commits cleanly. The benchmark is tooling, not a service — it must not touch service DBs. |
| **AD-6** | **Cohen's κ** as the headline agreement metric (+ raw agreement % + confusion matrix). | Raw agreement only; Krippendorff's α; F1 on the FAIL class. | Raw agreement overstates with class imbalance (mostly-PASS gold set). κ corrects for chance and is the standard, examiner-recognised metric. | κ is citable and defensible; the confusion matrix carries the *asymmetric* story (false-PASS-on-fabrication is the cell that matters), which a single κ would hide — so we report both. |

---

## 8. Security & Data-Handling Analysis

### 8.1 Threat Model
| Threat | Likelihood | Impact | Mitigation |
|--------|-----------|--------|------------|
| Grounding samples leak PII (portfolio holdings, account ids) into eval artefacts / logs | MED | HIGH | FR-8 field allow-list (numeric/short-string only), explicit redaction of portfolio/account ids, unknown tools → no sample; capture default OFF in prod (NFR-2) |
| Grounding samples bloat the live SSE frame / leak into normal user traffic | MED | MED | Hard byte cap (NFR-1, `GROUNDING_SAMPLE_MAX_BYTES`); env-gated OFF by default |
| Gold-set / labels contain sensitive real-account answers | LOW | MED | Gold items drawn from synthetic / public-entity questions only; no real user-portfolio questions in the committed fixture |
| Judge prompt-injection via answer text (answer tells judge "score 100") | LOW | MED | Judge already `temperature=0` + strict JSON; the *deterministic* invariant gate is immune to injection and is what decides FAIL |

### 8.2 Input Validation
| Entry Point | Data Source | Validation |
|-------------|------------|------------|
| `grounding_sample` builder | tool result rows | allow-list field names; coerce to str + char-cap; drop non-allow-listed; enforce byte cap |
| numeric claim extractor | answer text | bounded regex; ignore values inside code fences/citations to avoid false contradictions |
| gold label loader | `gold_labels.yaml` | schema-validate verdict ∈ {PASS,FAIL}, dims ∈ [0,25] |

### 8.3 Multi-Tenant Isolation
The benchmark runs under a single dev JWT (`/v1/auth/dev-login`, non-prod only).
No cross-tenant data is queried; gold fixtures contain no real user data.

---

## 9. Failure Modes & Recovery

| # | Scenario | Probability | Impact | Detection | Recovery |
|---|----------|------------|--------|-----------|----------|
| F-1 | Grounding flag ON but a tool returns no allow-listed fields | MED | LOW | `grounding_sample.fields == {}` | `GroundingCheck.evidence_mode = presumed`; verdict uses legacy fallback band; report flags "no grounding evidence" |
| F-2 | Numeric extractor false-positive (formats a date as a contradicted number) | MED | MED | calibration MAE on gold set spikes | tolerance + format-aware extraction; contradictions require sample on the *same field*; gold set guards regressions |
| F-3 | Judge prompt v3.0 shifts scores (FR-12 discontinuity) | HIGH (expected) | MED | trend store `judge_prompt_version` change | one-time dual-grade of baseline run under v2.0 + v3.0 recorded; trend annotated; thesis reports the step |
| F-4 | DEEPINFRA_API_KEY unset (offline/CI) | MED | LOW | judge returns SKIPPED | invariant gate + numeric cross-check still run deterministically → verdict still meaningful (gates are LLM-free) |
| F-5 | trend.sqlite write contention (parallel sessions, R42) | LOW | MED | sqlite busy / lock | append in a short transaction with retry; jsonl sidecar is append-only and lock-free as backstop |
| F-6 | Gold set drifts stale vs the live agent | MED | MED | calibration κ degrades over time | recalibration cadence (FR-12) + refresh gold set when the agent's tool surface changes |

---

## 10. Scalability & Performance

### 10.1 Expected Volumes
| Metric | Current | After | Notes |
|--------|---------|-------|-------|
| `tool_result` frame size | ~0.1-0.5 KB | ≤ +1 KB when flag on | NFR-1 cap |
| Judge calls per run | N questions × R repeats | unchanged | invariant gate + cross-check are LLM-free |
| Gold-set calibration calls | 0 (does not exist) | N_gold (one-shot, offline) | NFR-4 |
| Trend rows per run | 0 persisted | N×R question rows + 1 run row | trivial sqlite volume |

### 10.2 Bottlenecks
| Bottleneck | Risk | Mitigation |
|-----------|------|------------|
| Numeric cross-check on long answers | LOW | bounded regex, cap claims examined |
| SQLite trend growth over many runs | LOW | one file; prune/rollup helper if it ever matters (out of scope now) |

---

## 11. Test Strategy

### 11.1 Unit Tests
| Test | What It Verifies | Priority |
|------|-----------------|----------|
| test_invariant_control_token_leak | `<function`/`<invoke`/`<think`/fenced-JSON-only → `CONTROL_TOKEN_LEAK` FAIL | HIGH |
| test_invariant_truncation_digit_drop | leading-digit-drop / unbalanced-table answer → `TRUNCATED` | HIGH |
| test_invariant_empty_after_tools | tools ok+items≥1, answer no synthesis → `EMPTY_AFTER_TOOLS` | HIGH |
| test_invariant_infra_non_answer | all tools transport_error + apology → `INFRA_NON_ANSWER` | HIGH |
| test_grounding_contradiction_trips_fail | claim contradicts sampled value → `GROUNDING_CONTRADICTED` FAIL | HIGH |
| test_additive_fabrication_now_fails (E1 regression) | the `ru_mstr_news` run2 artefact (grounding 10) → FAIL, not PASS | HIGH |
| test_verdict_banding | quality_score thresholds map to STRONG/PASS/WEAK | HIGH |
| test_quality_score_continuity | `quality_score == sum(dims)`, unchanged vs v2 numbers | HIGH |
| test_grounding_sample_caps | byte/char/row/field caps enforced; over-cap → truncated=true | HIGH |
| test_grounding_sample_pii_redaction | portfolio/account fields never emitted | HIGH |
| test_tool_pairing_by_name | tool_call↔tool_result paired by name/id not index (F8) | MED |
| test_evidence_mode_presumed_fallback | no samples → evidence_mode=presumed, legacy band | MED |
| test_kappa_and_confusion_matrix | κ + confusion matrix computed correctly on a synthetic label set | HIGH |
| test_calibration_accept_reject | bar enforced; false-PASS-fabrication cell → reject | HIGH |
| test_trend_append_and_regression_diff | append row; PASS→FAIL downgrade detected vs baseline | HIGH |

### 11.2 Integration Tests
| Scenario | Infrastructure | Verifies |
|----------|---------------|----------|
| SSE grounding_sample round-trip | live S8 + flag on | tool→frame→harness→artefact carries capped redacted sample |
| judge-only re-grade with samples | stored run dir | `--judge-only` runs gate + cross-check offline, no chat re-run (FR-19) |
| full run → trend → report | live S8 (smoke pack) | trend.sqlite row written, `_regressions.json` + failure-first `_report.md` produced |

### 11.3 Calibration "Tests" (eval gate, not pytest)
| Gate | Verifies |
|------|---------|
| gold-set calibration ≥ κ bar | judge agreement acceptable (FR-11) |
| zero false-PASS on fabrication gold items | the worst confusion cell is empty |

---

## 12. Migration Plan

### 12.1 Backward Compatibility
- SSE `tool_result` legacy 4-key payload is byte-identical when the flag is off
  (frontend snapshot tests + harness pattern-match unaffected).
- `quality_score` (additive 0-100) is retained → prior thesis means stay comparable.
- `--judge-only --runs-dir` keeps working on *old* artefacts (no `grounding_sample`):
  `evidence_mode=presumed`, legacy grounding band — old runs re-grade, just without
  verified grounding.

### 12.2 Verdict-Model Discontinuity (the one intentional break)
- The *verdict* changes meaning (gated, not additive-threshold). This is recorded
  once: re-grade the registered baseline run under both the old additive verdict and
  the new tiered verdict, store both in the trend, and annotate the thesis figure
  with the changeover date. FR-4 makes this explicit and defensible rather than silent.

### 12.3 Rollback
- Grounding capture is a single env flag → off = pre-PRD SSE behaviour.
- Tiered verdict and additive verdict can both be computed from stored artefacts
  (`--judge-only`), so reverting the *report* to the additive headline is a flag,
  not a re-run.

---

## 13. Observability

### 13.1 Metrics (run-artefact / trend, not Prometheus)
| Metric | Type | Purpose |
|--------|------|---------|
| n_fail / n_weak / n_pass / n_strong | counter | verdict distribution per run |
| grounding_contradicted_total | counter | fabrications caught per run |
| invariant_violations{code} | counter | which gates fire, by code |
| judge_kappa | gauge | judge-vs-human agreement at last calibration |
| regression_count | gauge | downgrades vs baseline |
| mean_quality_score | gauge | longitudinal continuity series |

### 13.2 Logging
| Event | Level | Fields | Purpose |
|-------|-------|--------|---------|
| grounding_sample_truncated | INFO | tool, total_rows, sampled_rows | NFR-1 cap visibility |
| invariant_fired | INFO | question_id, code, excerpt_hash | per-FAIL forensics |
| calibration_rejected | WARN | judge_version, kappa, bar | judge failed acceptance bar |

---

## 14. Open Questions

| # | Question | Classification | Owner | Resolution |
|---|----------|---------------|-------|------------|
| OQ-1 | Is `tests/validation/chat_eval/` (the binary acceptance gate) still the authority, with `chat_quality_benchmark/` purely exploratory? If the gate is authoritative, does it *also* need the tiered verdict + grounding cross-check, or does this PRD's model become the single source of truth and the binary gate is retired? (audit §6) | **BLOCKING** for final scope | user | **RESOLVED (2026-06-12):** this PRD's tiered model is the **single source of truth**. `chat_eval`'s binary gate is reduced to a thin wrapper that **delegates** to the tiered scoring engine (no second scoring path); the shared SSE/dev-login harness is kept; the two question catalogues are **consolidated** into one. Eliminates the divergent-sources-of-truth flaw (audit F9). |
| OQ-2 | GOLD set size N and sampling: the audit suggests **20-30 items**; for a thesis κ to be stable, is 30 enough or should it be ~50, and should sampling be stratified by question pack / by failure mode (fabrication, leak, infra, good)? | **BLOCKING** for FR-9 | user | **RESOLVED (2026-06-12):** **~40 items, stratified by failure mode** (fabrication / leak / infra-failure / good / appropriate-refusal), including a **deliberate fabrication+leak subset** so the κ confusion matrix has signal in the false-PASS-on-fabrication cell. |
| OQ-3 | Which **judge model** is blessed for thesis runs? Default is `DeepSeek-V4-Flash`; a stronger judge may change calibration enough to matter (F1-F4). Single judge, or a stronger judge for thesis numbers + cheap judge for CI? | DEFERRED | user | **ACCEPTED DEFAULT (2026-06-12):** single `DeepSeek-V4-Flash`; re-evaluate after the first calibration run. |
| OQ-4 | κ **acceptance bar**: what value? Convention: κ ≥ 0.6 "substantial", ≥ 0.8 "almost perfect". For a thesis claim, recommend **κ ≥ 0.7 AND zero false-PASS on fabrication gold items**. Acceptable? | DEFERRED | user | **ACCEPTED DEFAULT (2026-06-12):** κ ≥ 0.7 AND zero false-PASS on fabrication gold items. |
| OQ-5 | Per-dimension **human labels**: should humans label the *current* four dims (tool_use/grounding/framing/refusal) or the redesigned set (where a **coherence/completeness** dimension may replace `refusal_judgment` as a soft dim, since refusal is now partly a hard gate)? | DEFERRED | user | **ACCEPTED DEFAULT (2026-06-12):** label the current 4 dims **plus a new coherence/completeness dim**; finalize in §6.5. |
| OQ-6 | Recalibration **cadence** beyond prompt-version bumps: every N runs? monthly? on every agent-tool-surface change? | DEFERRED | user | **ACCEPTED DEFAULT (2026-06-12):** recalibrate on every judge-version bump + on agent-tool-surface change + a monthly floor. |
| OQ-7 | Should the `final_answer`-overwrites-streamed-tokens behaviour (F10) be treated as a `TRUNCATED`/fabrication invariant here, or quarantined to its own `/fix-bug`? | DEFERRED | user | **RESOLVED (2026-06-12):** the product bug is **already fixed** (BP-671, `_rewrite_is_divergent_resynthesis` in `chat_orchestrator.py`); this PRD keeps the fabrication/degenerate invariants as a safety net only. |

---

## 15. Implementation Estimation

| Aspect | Estimate |
|--------|----------|
| Number of plans | 1 (tooling + S8 SSE) |
| Number of waves | ~6 — W1 tiered verdict + invariant gate; W2 SSE grounding capture (S8) + caps/redaction; W3 numeric cross-check + judge prompt v3.0; W4 trend store + regression diff; W5 report rewrite + legacy-bucket demotion; W6 gold set + κ calibration harness |
| Total tasks | ~24-30 |
| Critical path | W1 (verdict model) → W2 (grounding capture) → W3 (cross-check + prompt v3.0 → triggers recalibration) → W6 (calibration validates the whole thing) |
| Key risk | Judge prompt v3.0 (FR-12) invalidates longitudinal comparability if the discontinuity is not recorded; and gold-set quality determines whether the κ claim is defensible — a weak/biased gold set produces a meaningless validity number |

---

## Changelog

| Date | Author | Change |
|------|--------|--------|
| 2026-06-11 | human + claude | Initial draft — forward-looking scoring/reporting redesign per 2026-06-11 investigation; mechanical P0/P1 patches scoped out to parallel `/fix-bug` workstream |
