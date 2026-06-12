---
id: PLAN-0110
title: "Chat-Quality Scoring & Reporting Model Redesign"
prd: PRD-0091
status: draft
created: 2026-06-11
updated: 2026-06-11
---

# PLAN-0110 — Chat-Quality Scoring & Reporting Model Redesign

> **PRD**: [docs/specs/0091-chat-quality-scoring-reporting-redesign.md](../specs/0091-chat-quality-scoring-reporting-redesign.md)
> **Status**: draft
> **Author**: agent-plan
> **Date**: 2026-06-11
> **Branch**: `feat/plan-0110-chat-quality-scoring` (create from current work branch / `main`)
> **Services / areas**: `scripts/` (chat-quality tooling), `libs/prompts`, `tests/validation/`, **S8 rag-chat** (SSE frame only)
> **Total waves**: 6 | **Total tasks**: 27 | **Estimated effort**: ~6–8 developer-days

---

## Overview

The chat-quality benchmark is the instrument the thesis uses to claim the RAG-chat agent
produces grounded, high-quality financial answers. The 2026-06-11 investigation found it
structurally unable to fail fabrication, leaked control tokens, and infra non-answers. A
**parallel mechanical-fix workstream has already shipped** the five P0/P1 stop-gaps
(grounding veto floor=12, `detect_degenerate_answer`, tool-failure non-answer penalty,
failure-first report headline, `--baseline` diff). **This plan does NOT re-implement those.**

This plan delivers PRD-0091's deeper, still-unbuilt scope:

1. **W1 — Tiered/lexicographic verdict model** that consolidates the ad-hoc gates into the
   principled `VerdictDecision` / `Verdict` / `InvariantCode` taxonomy (§7 AD-1, §6.5).
2. **W2 — Verifiable grounding capture (S8)**: sampled, capped, redacted tool-result payload
   values flow through the `tool_result` SSE frame and into the harness artefact (FR-5/8).
3. **W3 — Numeric cross-check + judge prompt v3.0**: programmatic claim↔sample contradiction
   detection feeds the `GROUNDING_CONTRADICTED` gate; the "PRESUME GROUNDED" instruction is
   deleted (FR-6/7).
4. **W4 — Durable longitudinal trend store + regression diff** (SQLite + jsonl sidecar, FR-13/14/15).
5. **W5 — Failure-first report rewrite + single-authority verdict + `chat_eval` consolidation**
   (FR-16/17/18, OQ-1).
6. **W6 — Human-labelled GOLD set + Cohen's κ calibration harness** (FR-9/10/11/12, OQ-2/4/6) —
   **contains the one human-in-the-loop task**.

### Critical sequencing

```
W1 (verdict model + gates)          ──┐
                                       ├─► W3 (numeric cross-check + judge v3.0)
W2 (SSE grounding capture, S8) ───────┘        │
                                               ├─► W4 (trend store + regression)
                                               ├─► W5 (report rewrite + chat_eval consolidation)
                                               └─► W6 (gold set + κ calibration) ◄── validates everything
                                                      ▲
                              W6-T-1 gold-set LABELLING (human) gates W6 calibration tasks
```

- **Backend SSE-payload work (W2) MUST precede the judge cross-check that consumes it (W3).**
- **Gold-set construction + human labelling (W6-T-1/T-2) MUST precede calibration metric tasks (W6-T-3+).**
- W1 and W2 are **independent** and can run in **parallel worktrees** (W1 is `scripts/`-only;
  W2 is S8-only). They re-converge at W3.
- W4 and W5 both depend only on W1 (verdict objects) and can run in **parallel** with each other.
- W6 depends on W3 (judge v3.0 is the version under calibration) and on the trend/artefact shape
  from W4/W5 being stable for the gold snapshots; in practice run W6 **last**.

### Parallelization summary

| Wave | Depends on | Parallelizable with | Worktree isolation |
|------|-----------|---------------------|--------------------|
| W1 | none | **W2** | `scripts/` only — no S8 |
| W2 | none | **W1** | **S8 only** — merge-sensitive (see below) |
| W3 | W1, W2 | — (convergence point) | `scripts/` + `libs/prompts` |
| W4 | W1 | **W5** | `scripts/` + `tests/validation/` |
| W5 | W1 | **W4** | `scripts/` + `tests/validation/chat_eval` |
| W6 | W3 (+ stable W4/W5 artefacts) | — | `tests/validation/` + `scripts/` |

### Human-in-the-loop

- **W6-T-2 (`gold_labels.yaml` labelling)** requires a human to assign `PASS/FAIL` + per-dimension
  scores to ~40 stratified gold items. The agent prepares the unlabelled `gold_set.yaml` snapshots
  (W6-T-1) and a labelling worksheet; **the human must label before W6-T-3 (κ computation) can run.**
  Acceptance bar κ ≥ 0.7 + zero false-PASS-on-fabrication (OQ-4) cannot be evaluated without it.

---

## ⚠️ Merge-Sensitivity Warning — S8 rag-chat (W2 only)

> A **parallel session has uncommitted work on this branch** touching
> `services/rag-chat/src/rag_chat/application/use_cases/chat_orchestrator.py`,
> `application/pipeline/output_processor.py`, and their tests (confirmed dirty at plan time).
> **Wave 2 is the ONLY wave that touches S8.** It edits `sse_emitter.py` (clean at plan time)
> and adds a NEW call argument at the three `emit_tool_result(...)` call sites inside
> `chat_orchestrator.py:2088 / 2099 / 3879` (DIRTY).
>
> **Rules for the W2 implementer:**
> 1. Run W2 in its own `git worktree` (R42 / BP-590). **Never** `git stash` on this branch.
> 2. Before editing `chat_orchestrator.py`, run `git status` and `bash scripts/orphan_commit_check.sh`;
>    if the three call sites differ from what this plan describes, **re-read them** — the parallel
>    session may have reshaped the tool-execution loop.
> 3. Keep the S8 change strictly **additive and opt-in** (AD-4): a new optional `grounding_sample`
>    kwarg defaulted to `None`, emitted only behind `CHAT_EVAL_GROUNDING_SAMPLES=true`. This
>    minimizes conflict surface with the parallel session.
> 4. W1 (scripts-only) has **zero** overlap with the parallel session — prefer to land W1 first.

---

## Pre-flight Context (verified against code, 2026-06-11)

| Item | Verified value |
|------|----------------|
| Next plan ID | **PLAN-0110** (highest in TRACKING.md = PLAN-0109) |
| `scripts/chat_quality_judge.py` | 932 LOC — `_finalise_verdict` at L768, `detect_degenerate_answer` at L427, `detect_tool_failure_nonanswer` at L549, `GROUNDING_VETO_FLOOR=12` at L104, `_PASS_THRESHOLD=85` at L86 — **all mechanical fixes present** |
| `scripts/run_chat_quality_benchmark.py` | 1503 LOC — runner + report + `--baseline` |
| `tests/validation/chat_eval/harness.py` | 974 LOC — tool_result capture at **L630-640** (`{tool, status, item_count}`) |
| `tests/validation/chat_eval/grading.py` | 885+ LOC — `grade_response` (L365), `extract_numbers` (L189) — binary acceptance gate |
| `libs/prompts/src/prompts/evaluation/chat_quality_judge.py` | 324 LOC — `CHAT_QUALITY_JUDGE` v2.0; **"PRESUMED" grounding instruction at L90** |
| `services/rag-chat/.../sse_emitter.py` | 510 LOC — `emit_tool_result` at L441, `build_result_preview` at L419, preview caps `_PREVIEW_MAX_ITEMS=3` at L415 |
| `emit_tool_result` call sites (S8) | `chat_orchestrator.py:2088, 2099, 3879` — **DIRTY (parallel session)** |
| Existing eval question catalogues | `tests/validation/chat_eval/questions.yaml` **and** `tests/validation/chat_quality_benchmark/questions/` — **two sources (F9), consolidated in W5** |
| Gold/trend/calibration dirs | `tests/validation/chat_quality_benchmark/{gold,trend,calibration}/` — **do NOT exist; created in this plan** |
| `CHAT_EVAL_GROUNDING_SAMPLES` env var | **does NOT exist** — NEW in W2 |
| `VerdictDecision` / `Verdict` / `InvariantCode` / `GroundingCheck` | **do NOT exist** — NEW in W1 |
| `grounding_sample` SSE field | **does NOT exist** — NEW in W2 |

> **NEW-target tags** below mark every symbol/path that does not yet exist, per the BP-405 name-verification pass.

---

## Architecture Compliance Requirements

This plan is **tooling + one SSE-frame change**. The bulk lives outside the hexagonal service
layers (no domain entities, no use cases, no DB migrations, no Kafka). The applicable rules:

| Rule / NFR | What it means for this plan |
|------------|-----------------------------|
| R11 (UTC) | Every timestamp in the trend store, gold snapshots, and calibration artefacts uses `common.time.utc_now()` / ISO-8601 UTC — never naive `datetime.now()` |
| R12 (structlog) | New S8 logging (`grounding_sample_truncated`, §13.2) uses `structlog.get_logger(__name__)`. Script logging may use the existing benchmark logging pattern |
| R8 / R9 (no service DB, no cross-service) | Trend store is an **in-repo SQLite file** under `tests/validation/`, never a service DB (AD-5) |
| AD-4 / forward-compat | SSE `grounding_sample` is **additive, optional, omit-when-empty** — legacy 4-key `tool_result` payload stays **byte-identical** when the flag is off |
| NFR-1 | `tool_result` frame grows ≤ +1 KB when flag on (`GROUNDING_SAMPLE_MAX_BYTES=1024`) |
| NFR-2 | Grounding capture default **OFF**; `CHAT_EVAL_GROUNDING_SAMPLES=true` opt-in only |
| NFR-3 | Judge stays `temperature=0`, `response_format=json_object` |
| NFR-6 | Benchmark never gates shell exit code unless `--strict` is passed |
| FR-8 / §8 | Field allow-list (numeric/short-string only); portfolio/account ids never sampled; unknown tools → no sample |

---

## Wave 1 — Tiered Verdict Model + Deterministic Invariant Gate

**Goal**: Replace the additive `sum(4 dims) ≥ 85` verdict with the principled tiered model
(`VerdictDecision` + `Verdict` + `InvariantCode`), consolidating the existing ad-hoc grounding
veto / degenerate pre-check / tool-failure penalty into one lexicographic gate that runs BEFORE
the soft quality band.
**Depends on**: none | **Parallelizable with**: W2 | **Effort**: ~1.5 dev-days
**Architecture layer**: scoring core (`scripts/chat_quality_judge.py`) — **no S8, no parallel-session overlap**

### Task T-W1-01 — Verdict taxonomy: `Verdict`, `InvariantCode`, `GroundingCheck`, `VerdictDecision`

| Attribute | Value |
|-----------|-------|
| Type | impl |
| depends_on | none |
| blocks | T-W1-02, T-W1-03, T-W1-04, T-W3-01, T-W4-02 |
| Target files | `scripts/chat_quality_judge.py` |
| PRD ref | §6.5, FR-1, FR-2 |

**What to build** (all **NEW — created in this plan**):
- `Verdict` (str enum): `STRONG / PASS / WEAK / FAIL`.
- `InvariantCode` (str enum): `CONTROL_TOKEN_LEAK / TRUNCATED / EMPTY_AFTER_TOOLS / INFRA_NON_ANSWER / GROUNDING_CONTRADICTED / GROUNDING_FLOOR`.
- `GroundingCheck` (frozen dataclass): `matched:int, unmatched:int, contradicted:int, examples:list[dict], evidence_mode:str` (`"verified"|"presumed"`). Populated in W3; in W1 default to a `presumed`/zeroed instance.
- `VerdictDecision` (frozen dataclass): `verdict:Verdict, quality_score:int (0-100), fail_reason:InvariantCode|None, gate_results:dict[InvariantCode,bool], grounding_check:GroundingCheck, dimensions:dict[str,int]`.

**Invariants**:
- `verdict == FAIL ⟺ fail_reason is not None` (and at least one `gate_results` value False) **OR** `quality_score < 60`.
- `quality_score == sum(dimensions.values())` (FR-4 continuity — must equal the old additive sum).

**Tests to write** (in `tests/validation/chat_quality_benchmark/test_judge.py` or a new `test_verdict_model.py`):
| Test | Verifies | Type |
|------|----------|------|
| test_verdict_enum_members | all four members resolve and order STRONG>PASS>WEAK>FAIL | unit |
| test_invariant_code_members | all six codes present | unit |
| test_verdict_decision_invariants | `FAIL ⟺ fail_reason set`; `quality_score == sum(dims)` | unit |

**Acceptance criteria**:
- [ ] Four new types defined, frozen where specified
- [ ] `quality_score` is the exact additive `sum(dimensions)` (no rescaling) — FR-4
- [ ] No existing import of `chat_quality_judge` breaks

---

### Task T-W1-02 — Deterministic invariant gate (consolidate existing ad-hoc checks)

| Attribute | Value |
|-----------|-------|
| Type | impl |
| depends_on | T-W1-01 |
| blocks | T-W1-03, T-W6-04 |
| Target files | `scripts/chat_quality_judge.py` |
| PRD ref | FR-1, FR-3, §6.7 (verdict composition path) |

**What to build**:
- A single `evaluate_invariants(answer, tool_trace, grounding_check) -> dict[InvariantCode, bool]` (**NEW**) that runs the deterministic, LLM-free gates BEFORE the judge:
  - `CONTROL_TOKEN_LEAK`: answer contains `<function`, `<invoke`, `<think`, or is a fenced-JSON-only stub. **Reuse the regexes already in `detect_degenerate_answer` (L427)** — do not duplicate; refactor the detection into this gate.
  - `TRUNCATED`: leading-digit-drop / unbalanced markdown table / mid-token cut-off — **reuse `detect_degenerate_answer`'s truncation logic**.
  - `EMPTY_AFTER_TOOLS`: ≥1 tool `status=ok items>=1` but no substantive synthesis — **reuse `_answer_delivers_data` (L538)**.
  - `INFRA_NON_ANSWER`: all relevant tools `transport_error`/5xx + apology — **reuse `detect_tool_failure_nonanswer` (L549)**.
  - `GROUNDING_CONTRADICTED`: `grounding_check.contradicted > 0` (populated in W3; always `False` in W1 until samples exist).
  - `GROUNDING_FLOOR`: judge `grounding` sub-dim `< GROUNDING_VETO_FLOOR` (12) — **reuse the existing veto floor**.
- Each invariant is **independently toggleable** (a dict/config of enabled codes) and individually reported (FR-3).

**Logic & Behavior**:
- This task **refactors** the three existing detectors (`detect_degenerate_answer`, `detect_tool_failure_nonanswer`, grounding veto) so they emit `InvariantCode` results instead of ad-hoc dicts — **no detection logic is weakened or deleted** (R19). The functions remain callable (back-compat) but their results route through `evaluate_invariants`.

**Tests to write** (from PRD §11.1):
| Test | Verifies | Type |
|------|----------|------|
| test_invariant_control_token_leak | `<function`/`<invoke`/`<think`/fenced-JSON → CONTROL_TOKEN_LEAK | unit |
| test_invariant_truncation_digit_drop | leading-digit-drop / unbalanced table → TRUNCATED | unit |
| test_invariant_empty_after_tools | tools ok+items≥1, no synthesis → EMPTY_AFTER_TOOLS | unit |
| test_invariant_infra_non_answer | all transport_error + apology → INFRA_NON_ANSWER | unit |
| test_invariant_floor_below_12 | grounding sub-dim 10 → GROUNDING_FLOOR | unit |
| test_invariant_toggle_disables_gate | disabled code never fires | unit |

**Acceptance criteria**:
- [ ] `evaluate_invariants` returns all six codes with bool results
- [ ] Existing `detect_degenerate_answer` / `detect_tool_failure_nonanswer` tests still pass (no logic weakened)
- [ ] Gates are LLM-free (run with `DEEPINFRA_API_KEY` unset — F-4)

---

### Task T-W1-03 — Rewrite `_finalise_verdict` to the lexicographic composition

| Attribute | Value |
|-----------|-------|
| Type | impl |
| depends_on | T-W1-01, T-W1-02 |
| blocks | T-W1-04, T-W4-02, T-W5-01 |
| Target files | `scripts/chat_quality_judge.py` (L768 region) |
| PRD ref | FR-1, FR-2, §6.7 |

**What to build**:
- Rewrite `_finalise_verdict` so it: (1) computes `dimensions` + `quality_score=sum(dims)` as today; (2) calls `evaluate_invariants`; (3) if **any** gate fired → `Verdict.FAIL` with `fail_reason = first-fired code` (priority order: `GROUNDING_CONTRADICTED` > `CONTROL_TOKEN_LEAK` > `TRUNCATED` > `INFRA_NON_ANSWER` > `EMPTY_AFTER_TOOLS` > `GROUNDING_FLOOR`); (4) else **band** `quality_score`: `≥90 STRONG`, `≥75 PASS`, `60-74 WEAK`, `<60 FAIL` (§6.5 table); (5) return a `VerdictDecision`.
- Keep emitting the legacy `verdict`/`score`/`dimensions`/`veto` keys in the result dict for one release (back-compat for artefact readers) **alongside** the new structured fields.

**Tests to write** (PRD §11.1):
| Test | Verifies | Type |
|------|----------|------|
| test_verdict_banding | quality_score 92→STRONG, 80→PASS, 65→WEAK, 50→FAIL (no gate) | unit |
| test_quality_score_continuity | `quality_score == sum(dims)`, identical to v2 numbers for a fixed input | unit |
| test_gate_overrides_high_quality | dims sum 95 + CONTROL_TOKEN_LEAK → FAIL[CONTROL_TOKEN_LEAK] | unit |
| test_additive_fabrication_now_fails | the `ru_mstr_news` run2 artefact (grounding 10) → FAIL not PASS (E1 regression) | unit |

**Downstream test impact**:
- `tests/validation/chat_quality_benchmark/test_judge.py` — asserts on `_finalise_verdict` output keys; update for new structured fields (keep legacy assertions green via back-compat keys).
- Any `scripts/` caller reading `result["verdict"]` as `PASS/WARN/FAIL` — now `STRONG/PASS/WEAK/FAIL`; W5 owns the report-side migration but **runner code that branches on `WARN` must be updated here or flagged**.

**Acceptance criteria**:
- [ ] Tiered verdict returned as `VerdictDecision`; legacy keys still present
- [ ] `ru_mstr_news` run2 fabrication artefact → FAIL (E1)
- [ ] `quality_score` numerically unchanged vs v2 for a fixed dimension set

---

### Task T-W1-04 — Wire verdict model into `judge_answer` + `build_input_from_artifact`

| Attribute | Value |
|-----------|-------|
| Type | impl |
| depends_on | T-W1-03 |
| blocks | T-W3-01, T-W4-02 |
| Target files | `scripts/chat_quality_judge.py` (`judge_answer` L681, `build_input_from_artifact` L858, `summarise_judge_records` L877) |
| PRD ref | FR-1, FR-19 |

**What to build**:
- `judge_answer` returns/embeds a `VerdictDecision`; the deterministic gate runs even when the LLM judge is SKIPPED (no API key) so the verdict is still meaningful (F-4).
- `build_input_from_artifact` reads a stored `q_<id>.json` and reconstructs the inputs the gate needs (answer text + `tool_results`) so `--judge-only` re-grades old artefacts offline (FR-19) — grounding samples absent → `evidence_mode=presumed`.
- `summarise_judge_records` aggregates the new `Verdict` counts (`n_strong/n_pass/n_weak/n_fail`) + `fail_reason` histogram.

**Acceptance criteria**:
- [ ] `--judge-only` path produces `VerdictDecision` from stored artefacts (no chat re-run)
- [ ] Gate-only verdict produced when judge SKIPPED
- [ ] `summarise_judge_records` exposes verdict + invariant histograms for the report

### Pre-read (W1)
- `scripts/chat_quality_judge.py` L80-140 (thresholds/constants), L427-680 (detectors), L768-880 (`_finalise_verdict` + helpers)
- `tests/validation/chat_quality_benchmark/test_judge.py`

### Validation Gate (W1)
- [ ] ruff + mypy clean on `scripts/chat_quality_judge.py`
- [ ] ≥ 13 new unit tests pass; existing judge tests green (no weakened detection — R19)
- [ ] `ru_mstr_news` run2 fabrication → FAIL (E1 regression locked)
- [ ] Gate runs with `DEEPINFRA_API_KEY` unset (LLM-free path)

### Break Impact (W1)
| Broken File | Why | Fix |
|-------------|-----|-----|
| `tests/validation/chat_quality_benchmark/test_judge.py` | verdict literals `PASS/WARN/FAIL` → `STRONG/PASS/WEAK/FAIL`; new result keys | update expected verdicts; keep legacy-key assertions via back-compat dual-emit |
| `scripts/run_chat_quality_benchmark.py` | branches on `verdict == "WARN"` | W5 migrates the report; if any runner branch hard-depends on `WARN`, map `WARN→WEAK` here and note for W5 |

### Regression Guardrails (W1)
- **R19 / feedback_never_delete_tests**: refactor detection into the gate; never delete/skip/weaken the existing degenerate / tool-failure tests.
- **feedback_audit_returned_value_persistence**: `VerdictDecision.gate_results` and `fail_reason` MUST be persisted to the artefact + trend store (W4) — a metrics-only consumption is a silent failure.

---

## Wave 2 — S8 SSE Grounding-Sample Capture (caps + redaction)

**Goal**: Emit sampled, capped, redacted tool-result payload **values** in the `tool_result`
SSE frame behind `CHAT_EVAL_GROUNDING_SAMPLES`, and capture them in the harness artefact, so the
judge can later cross-check numeric claims against what the tool actually returned.
**Depends on**: none | **Parallelizable with**: W1 | **Effort**: ~1.5 dev-days
**Architecture layer**: S8 infrastructure (SSE) + eval harness — **⚠️ MERGE-SENSITIVE (see warning above)**

### Task T-W2-01 — `grounding_sample` builder + hard caps in `sse_emitter.py`

| Attribute | Value |
|-----------|-------|
| Type | impl |
| depends_on | none |
| blocks | T-W2-02, T-W2-03, T-W2-04 |
| Target files | `services/rag-chat/src/rag_chat/application/pipeline/sse_emitter.py` |
| PRD ref | FR-5, FR-8, §6.3, NFR-1 |

**What to build** (all **NEW**):
- Module constants alongside `_PREVIEW_MAX_ITEMS` (L415): `GROUNDING_MAX_ROWS = 3`, `GROUNDING_MAX_FIELDS_PER_ROW = 8`, `GROUNDING_VALUE_MAX_CHARS = 32`, `GROUNDING_SAMPLE_MAX_BYTES = 1024`.
- A per-tool **field allow-list** map (numeric/identifier fields only, e.g. `revenue, eps, gross_profit, pe_ratio, period, ticker, confidence`). Document bodies, narrative text, portfolio/account ids are **never** listed. Unknown tools → empty allow-list → **no sample** (degrade to id/title preview only).
- `build_grounding_sample(tool_name, items) -> dict | None` (**NEW**, classmethod near `build_result_preview`): samples ≤`GROUNDING_MAX_ROWS` rows, keeps only allow-listed fields, coerces each value to `str` capped at `GROUNDING_VALUE_MAX_CHARS`, redacts portfolio/account ids, enforces `GROUNDING_SAMPLE_MAX_BYTES` (set `truncated=true` when cut). Returns the `{fields, sampled_rows, total_rows, truncated}` shape (§6.3). Returns `None` when allow-list empty or no fields survive.

**Tests to write** (PRD §11.1):
| Test | Verifies | Type |
|------|----------|------|
| test_grounding_sample_caps | byte/char/row/field caps enforced; over-cap → truncated=true | unit |
| test_grounding_sample_pii_redaction | portfolio/account fields never emitted | unit |
| test_grounding_sample_unknown_tool_no_sample | unknown tool → None (id/title preview only) | unit |
| test_grounding_sample_shape | returns `{fields,sampled_rows,total_rows,truncated}` | unit |

**Acceptance criteria**:
- [ ] All four hard caps enforced; serialized sample ≤ 1024 bytes (NFR-1)
- [ ] Allow-list only; portfolio/account ids redacted (FR-8 / §8)
- [ ] Unknown tool degrades to no-sample, never raw-payload leak

---

### Task T-W2-02 — Add optional `grounding_sample` to `emit_tool_result` (flag-gated, omit-when-empty)

| Attribute | Value |
|-----------|-------|
| Type | impl |
| depends_on | T-W2-01 |
| blocks | T-W2-03 |
| Target files | `services/rag-chat/src/rag_chat/application/pipeline/sse_emitter.py` (`emit_tool_result` L441), config/settings for `CHAT_EVAL_GROUNDING_SAMPLES` |
| PRD ref | FR-5, AD-4, NFR-2, §6.3 |

**What to build**:
- New optional kwarg `grounding_sample: dict | None = None` on `emit_tool_result`. Attach to payload **only when** the env flag `CHAT_EVAL_GROUNDING_SAMPLES=true` AND `status == "ok"` AND `grounding_sample` is non-empty — mirroring the existing `if result_preview:` omit-when-empty pattern (L505). **Legacy 4-key payload stays byte-identical when off.**
- `CHAT_EVAL_GROUNDING_SAMPLES` (**NEW env var**) via the rag-chat pydantic-settings (default `false`); read where other SSE flags are read.
- `structlog` `grounding_sample_truncated` INFO log (`tool, total_rows, sampled_rows`) per §13.2.

**Tests to write**:
| Test | Verifies | Type |
|------|----------|------|
| test_tool_result_legacy_byte_identical_flag_off | flag off → payload == legacy 4-key dict (snapshot) | unit |
| test_tool_result_grounding_attached_flag_on | flag on + status ok + sample → field present | unit |
| test_tool_result_no_sample_on_error_status | status != ok → no grounding_sample even if flag on | unit |

**Downstream test impact**:
- `services/rag-chat/tests/unit/...` SSE snapshot tests that assert the 4-key `tool_result` shape — **must stay green** because the field is omit-when-empty (the test asserting byte-identity IS the guard).

**Acceptance criteria**:
- [ ] Flag OFF → byte-identical legacy frame (frontend + harness pattern-match safe)
- [ ] Flag ON + status ok → bounded `grounding_sample` present
- [ ] Env flag defaults OFF (NFR-2)

---

### Task T-W2-03 — Plumb sampled values from the tool-execution loop (⚠️ DIRTY file)

| Attribute | Value |
|-----------|-------|
| Type | impl |
| depends_on | T-W2-02 |
| blocks | T-W2-04 |
| Target files | `services/rag-chat/src/rag_chat/application/use_cases/chat_orchestrator.py` (call sites L2088, L2099, L3879) |
| PRD ref | FR-5, §6.7 (grounding capture path) |

**⚠️ MERGE-SENSITIVE**: this is the file the parallel session is editing. **Re-read the three
`emit_tool_result(...)` call sites at edit time** — line numbers may have moved. Make the change
strictly additive: build the sample via `SSEEmitter.build_grounding_sample(tool_name, items)`
where the tool's `items` are already in scope, and pass it as the new kwarg. If the parallel
session has refactored the loop, adapt to the new shape but keep the change minimal.

**What to build**:
- At each `emit_tool_result` call where the executed tool's result `items` are available, compute `grounding_sample = SSEEmitter.build_grounding_sample(tool_name, items)` and pass it through. Guarded internally by the env flag (the emitter already checks it), so no behavior change when off.

**Tests to write**:
| Test | Verifies | Type |
|------|----------|------|
| test_orchestrator_passes_grounding_sample | with flag on, emit_tool_result receives a non-None sample for an allow-listed tool | unit (mock emitter) |

**Acceptance criteria**:
- [ ] Sample plumbed at all relevant call sites; flag-off behavior unchanged
- [ ] Existing `test_chat_orchestrator_tool_loop` / `_fallback` / `_observability` tests (which mock `emit_tool_result`) still pass

---

### Task T-W2-04 — Harness captures `grounding_sample` into `ChatRunResult.tool_results`

| Attribute | Value |
|-----------|-------|
| Type | impl |
| depends_on | T-W2-03 |
| blocks | T-W3-01 |
| Target files | `tests/validation/chat_eval/harness.py` (capture block L630-640; `ChatRunResult.tool_results` L240; serialisation L284) |
| PRD ref | FR-5, §6.1, §6.7 |

**What to build**:
- Extend the `tool_result` capture block (L630-640) to also read `data.get("grounding_sample")` (when present) into each captured `tool_results` entry. Keep the existing `{tool, status, item_count}` keys; add `grounding_sample` only when present (forward-compatible — old artefacts have none).
- Ensure it is serialised into the saved `q_<id>.json` artefact (L284 region) so `--judge-only` can read it later.

**Tests to write**:
| Test | Verifies | Type |
|------|----------|------|
| test_harness_captures_grounding_sample | SSE frame with grounding_sample → present in ChatRunResult + artefact | unit |
| test_harness_legacy_frame_no_sample | frame without the field → tool_results entry has no grounding_sample (no crash) | unit |

**Acceptance criteria**:
- [ ] Harness captures + persists `grounding_sample`; absent field is tolerated
- [ ] Artefact JSON round-trips the sample for offline re-grade

### Pre-read (W2)
- `services/rag-chat/src/rag_chat/application/pipeline/sse_emitter.py` L410-510
- `services/rag-chat/src/rag_chat/application/use_cases/chat_orchestrator.py` L2080-2110, L3870-3890 (**git status first**)
- `tests/validation/chat_eval/harness.py` L230-290, L580-650

### Validation Gate (W2)
- [ ] ruff + mypy clean on changed S8 files + harness
- [ ] ≥ 8 new unit tests pass
- [ ] **Flag-off byte-identity test green** (frontend + harness pattern-match preserved)
- [ ] rag-chat existing SSE + orchestrator tool-loop tests green
- [ ] `docs/services/rag-chat.md` updated: new SSE optional field + `CHAT_EVAL_GROUNDING_SAMPLES`

### Architecture Compliance (W2)
- [ ] R12 structlog for the new `grounding_sample_truncated` log
- [ ] AD-4: additive, opt-in, omit-when-empty; legacy frame byte-identical when off
- [ ] FR-8 / §8: allow-list only, PII redaction, unknown-tool → no sample
- [ ] NFR-1 / NFR-2: ≤ +1 KB, default OFF

### Break Impact (W2)
| Broken File | Why | Fix |
|-------------|-----|-----|
| `services/rag-chat/tests/unit/.../test_*sse*` (4-key snapshot) | new optional field | none if omit-when-empty — the byte-identity test IS the guard; assert flag-off equality |
| `services/rag-chat/tests/unit/use_cases/test_chat_orchestrator_tool_loop.py` (mocks `emit_tool_result`) | new kwarg | mock signature tolerant of extra kwarg; assert sample passed when flag on |

### Regression Guardrails (W2)
- **R42 / BP-590**: parallel session on `chat_orchestrator.py` — own worktree, no `git stash`, `orphan_commit_check.sh` before editing.
- **feedback_frontend_comments**: heavy inline comments on the SSE/flag plumbing (user is new to this surface).
- **BP-623 context**: the `transport_error` status path already exists — do NOT emit a sample for non-`ok` statuses.

---

## Wave 3 — Numeric Grounding Cross-Check + Judge Prompt v3.0

> **STATUS: SHIPPED 2026-06-12.** `cross_check_grounding` + `_nearest_field`
> association (tolerance/scale/fence/year-aware) populate `GroundingCheck` and
> trip `GROUNDING_CONTRADICTED` on a sampled-value contradiction (hard FAIL);
> absent samples → `presumed` (no fail). Judge prompt bumped v2.0→**v3.0**
> (BREAKING): "PRESUME GROUNDED" deleted, grounding graded qualitatively, a
> `GROUNDING SAMPLE` evidence block rendered into the user prompt. FR-12 stamps
> (`judge_prompt_version` / `judge_model_id` / `verdict_model_version`) added to
> `_meta.json` + `_judge_summary.json`; `VERDICT_MODEL_VERSION=1.1`. Breaking
> record: `.claude/evals/prompt_changes/2026-06-12-chat_quality_judge-v3.0.md`
> + `libs/prompts/CHANGELOG.md`. 18 new tests (synthetic
> contradiction/match/absent + fence/same-field/year guards). **Runner
> threading was minimal**: W2 already flows samples into
> `JudgeInput.tool_results` (via `build_input_from_artifact` + the live
> `list(result.tool_results)` path), so only the FR-12 version stamps were added
> to the runner.

**Goal**: Turn captured grounding samples into a deterministic `GroundingCheck` (matched /
unmatched / contradicted), feed samples to the judge, and **delete the "PRESUME GROUNDED"
instruction** so grounding is scored against evidence. A contradicted claim trips
`GROUNDING_CONTRADICTED` (W1 gate).
**Depends on**: W1 (verdict + gate), W2 (samples in artefact) — **convergence point** | **Effort**: ~1.5 dev-days
**Architecture layer**: scoring (`scripts/`) + prompt (`libs/prompts`)

### Task T-W3-01 — Programmatic numeric cross-check → `GroundingCheck`

| Attribute | Value |
|-----------|-------|
| Type | impl |
| depends_on | T-W1-04, T-W2-04 |
| blocks | T-W3-02, T-W3-03 |
| Target files | `scripts/chat_quality_judge.py` |
| PRD ref | FR-6, §6.5 (`GroundingCheck`), §8.2 |

**What to build**:
- `cross_check_grounding(answer, tool_results) -> GroundingCheck` (**NEW**): extract numeric claims from the answer (reuse / adapt `chat_eval/grading.py:extract_numbers` L189 patterns), match each against the captured `grounding_sample.fields` values within a tolerance, on the **same field**. Classify each claim `matched` / `unmatched` / `contradicted`; collect `examples = [{claim, nearest_sample, delta}]`. Set `evidence_mode = "verified"` when samples present, else `"presumed"` (legacy fallback).
- **Guard against false positives (F-2)**: ignore numbers inside code fences / citations; require the sample to be on the same field; tolerance-based equality (relative + absolute) so rounding/units don't trip a contradiction; format-aware (don't treat a date/year as a contradicted figure).

**Tests to write** (PRD §11.1):
| Test | Verifies | Type |
|------|----------|------|
| test_grounding_contradiction_trips_fail | claim contradicts sampled value → contradicted≥1 → GROUNDING_CONTRADICTED | unit |
| test_grounding_match_within_tolerance | claim within tolerance → matched, no contradiction | unit |
| test_grounding_no_samples_presumed | no samples → evidence_mode=presumed, contradicted=0 | unit |
| test_cross_check_ignores_fenced_numbers | numbers in code fences not treated as claims (F-2) | unit |
| test_cross_check_same_field_only | contradiction requires same-field sample | unit |

**Acceptance criteria**:
- [ ] `GroundingCheck` populated; `contradicted>0` feeds `evaluate_invariants` → FAIL
- [ ] `evidence_mode` correctly `verified`/`presumed`
- [ ] False-positive guards (fences, same-field, tolerance) in place

---

### Task T-W3-02 — Wire `GroundingCheck` into the gate + `VerdictDecision`

| Attribute | Value |
|-----------|-------|
| Type | impl |
| depends_on | T-W3-01 |
| blocks | T-W3-04 |
| Target files | `scripts/chat_quality_judge.py` (`evaluate_invariants`, `_finalise_verdict`, `judge_answer`) |
| PRD ref | FR-3(e), FR-6, §6.7 |

**What to build**:
- `judge_answer` calls `cross_check_grounding` before `evaluate_invariants`; passes the `GroundingCheck` into the gate so `GROUNDING_CONTRADICTED` fires on `contradicted>0`; embeds the `GroundingCheck` in the returned `VerdictDecision`.

**Tests to write**:
| Test | Verifies | Type |
|------|----------|------|
| test_contradiction_overrides_high_quality | dims sum 95 + contradicted=1 → FAIL[GROUNDING_CONTRADICTED] | unit |
| test_verdict_decision_carries_grounding_check | VerdictDecision.grounding_check populated | unit |

**Acceptance criteria**:
- [ ] Contradiction → FAIL regardless of soft score
- [ ] `GroundingCheck` persisted on the verdict for the report (W5)

---

### Task T-W3-03 — Judge prompt v3.0: delete "PRESUME GROUNDED", add sample reasoning

| Attribute | Value |
|-----------|-------|
| Type | impl |
| depends_on | T-W3-01 |
| blocks | T-W3-04, T-W6-03 |
| Target files | `libs/prompts/src/prompts/evaluation/chat_quality_judge.py` (PRESUMED at L90; `version="2.0"` at L316) + CHANGELOG |
| PRD ref | FR-7, FR-12, AD-1 |

**What to build**:
- Bump `CHAT_QUALITY_JUDGE.version` `2.0 → 3.0` with `content_hash` update (per PRD-0030 PromptTemplate semver pattern).
- **Delete the L90 "PRESUMED grounding" instruction**; replace with: grade grounding against the provided `grounding_sample` evidence; when no samples present, fall back to an explicit "presumed" band and say so. Add tiered-verdict awareness (the judge produces soft sub-scores; the deterministic gate decides hard FAIL).
- Add a `libs/prompts` CHANGELOG entry. **This bump triggers FR-12 recalibration (W6).**

**Tests to write**:
| Test | Verifies | Type |
|------|----------|------|
| test_prompt_version_bumped | `CHAT_QUALITY_JUDGE.version == "3.0"` and content_hash changed | unit |
| test_prompt_has_no_presume_grounded | the PRESUME instruction string is gone | unit |
| test_prompt_renders_grounding_samples | sample block renders into the user prompt when present | unit |

**Downstream test impact**:
- `libs/prompts/tests/` prompt-registry/version tests — update expected version + hash.
- `scripts/chat_quality_judge.py:_build_user_prompt` (L267) — must render the sample block; update its tests.

**Acceptance criteria**:
- [ ] v3.0 registered; PRESUME instruction deleted; samples rendered
- [ ] CHANGELOG + content_hash updated (PRD-0030 pattern)
- [ ] FR-12 recalibration requirement noted in W6

---

### Task T-W3-04 — Record judge version + model id on every run artefact (FR-12 plumbing)

| Attribute | Value |
|-----------|-------|
| Type | impl |
| depends_on | T-W3-02, T-W3-03 |
| blocks | T-W4-02, T-W6-05 |
| Target files | `scripts/run_chat_quality_benchmark.py`, `scripts/chat_quality_judge.py` |
| PRD ref | FR-12, §6.4 (`runs.judge_prompt_version`, `judge_model_id`) |

**What to build**:
- Stamp every run artefact + (later) trend row with `judge_prompt_version` (from `CHAT_QUALITY_JUDGE.version`), `judge_model_id`, and `verdict_model_version` (a constant bumped when the tiered schema changes — FR-4 discontinuity).

**Acceptance criteria**:
- [ ] Each run records judge version + model id + verdict-model version
- [ ] These flow into the W4 trend `runs` row

### Pre-read (W3)
- `scripts/chat_quality_judge.py` L189-end (cross-check site), L267-340 (`_build_user_prompt`), L681-770
- `tests/validation/chat_eval/grading.py` L189-230 (`extract_numbers`, number patterns)
- `libs/prompts/src/prompts/evaluation/chat_quality_judge.py` (full)

### Validation Gate (W3)
- [ ] ruff + mypy clean
- [ ] ≥ 10 new unit tests pass
- [ ] Judge v3.0 registered; PRESUME instruction deleted (asserted)
- [ ] Contradiction E2E: a fabricated-number artefact → FAIL[GROUNDING_CONTRADICTED]
- [ ] `libs/prompts` CHANGELOG updated

### Architecture Compliance (W3)
- [ ] NFR-3: judge stays `temperature=0`, `response_format=json_object`
- [ ] PRD-0030 semver: version bump + content_hash + CHANGELOG together

### Break Impact (W3)
| Broken File | Why | Fix |
|-------------|-----|-----|
| `libs/prompts/tests/...` version/registry | prompt v2.0→3.0 + hash | update expected version + hash |
| `scripts/chat_quality_judge.py` `_build_user_prompt` tests | prompt body adds sample block | update rendered-prompt assertions |

### Regression Guardrails (W3)
- **F-2 (PRD §9)**: numeric extractor false positives — same-field + tolerance + fence-skip guards are mandatory; gold set (W6) is the regression net.
- **feedback_prompt_input_mismatch**: the prompt advertises `grounding_sample` evidence — the cross-check MUST read the **same** sample source the prompt renders, or the two diverge silently.

---

## Wave 4 — Durable Longitudinal Trend Store + Regression Diff

> **STATUS: SHIPPED 2026-06-12.** New `scripts/chat_quality_trend.py` adds a
> durable in-repo `TrendStore` (committed `tests/validation/chat_quality_benchmark/trend/trend.sqlite`
> with tables `runs` + `question_results` per §6.4 + indexes `(question_id,run_ts)`
> / `(run_ts)`, mirrored to a deterministic `trend.jsonl` sidecar). Appends are
> **idempotent by `run_ts`** (DELETE+CASCADE+re-insert; same run_ts twice = one
> row) and write only runner-supplied timestamps, so the committed files are
> diff-stable. Short `BEGIN IMMEDIATE` transaction with sqlite-busy retry +
> lock-free jsonl backstop (F-5/R42). The runner (`run_chat_quality_benchmark.py`)
> projects each judged per-Q artefact's `verdict_decision` into typed rows,
> appends one `runs` row + N×R `question_results` rows per run, and runs
> `detect_regressions` vs the registered baseline **and** the rolling prior run —
> emitting `_regressions.json` (per-question verdict downgrades PASS→WEAK/FAIL,
> new invariants, new grounding contradictions, latency breaches, and
> score-drop-beyond-noise-threshold=5) and a delimited regression block into
> `_report.md`. `--set-baseline <run_ts>` pins an existing run (no chat run, one
> baseline at a time); bare `--set-baseline` pins THIS run after append. 25 new
> tests (schema/idempotency/busy-retry/concurrent/set-baseline/PASS→FAIL diff/
> noise-threshold/empty-store-first-run + runner projection helpers).

**Goal**: Persist one durable, queryable trend store across runs (SQLite + jsonl sidecar),
append every run, and detect regressions vs a registered baseline + rolling window.
**Depends on**: W1 (VerdictDecision) | **Parallelizable with**: W5 | **Effort**: ~1.25 dev-days
**Architecture layer**: `scripts/` persistence + `tests/validation/chat_quality_benchmark/trend/`

### Task T-W4-01 — Trend-store module: schema + atomic append (SQLite + jsonl)

| Attribute | Value |
|-----------|-------|
| Type | impl |
| depends_on | T-W1-01 |
| blocks | T-W4-02, T-W4-03 |
| Target files | `scripts/chat_quality_trend.py` (**NEW**), `tests/validation/chat_quality_benchmark/trend/` (**NEW dir**) |
| PRD ref | FR-13, §6.4, AD-5, NFR-5, F-5 |

**What to build** (all **NEW**):
- A `TrendStore` helper writing `tests/validation/chat_quality_benchmark/trend/trend.sqlite` with tables `runs` and `question_results` exactly per §6.4 (columns + types + indexes `(question_id, run_ts)` and `(run_ts)`).
- Mirror each row to an append-only `trend.jsonl` sidecar (grep-able, lock-free backstop — F-5).
- **R11**: `started_at` ISO-8601 UTC via `common.time.utc_now()`. Append in a short transaction with retry on `sqlite busy` (F-5, R42 parallel sessions).

**Tests to write**:
| Test | Verifies | Type |
|------|----------|------|
| test_trend_schema_created | tables + indexes exist on first write | unit |
| test_trend_append_run_and_questions | run row + N question rows written; jsonl mirrored | unit |
| test_trend_busy_retry | sqlite-busy → retried, not lost (F-5) | unit |

**Acceptance criteria**:
- [ ] Single committed SQLite file + jsonl sidecar; queryable trend windows
- [ ] Atomic append with busy-retry; no service DB (AD-5)

---

### Task T-W4-02 — Runner appends each run to the trend store

| Attribute | Value |
|-----------|-------|
| Type | impl |
| depends_on | T-W4-01, T-W1-03, T-W3-04 |
| blocks | T-W4-03 |
| Target files | `scripts/run_chat_quality_benchmark.py` |
| PRD ref | FR-13, §6.7 (trend path) |

**What to build**:
- After grading, append a `runs` summary row (verdict counts, `mean_quality_score`, judge version/model, `verdict_model_version`, `is_baseline`) and one `question_results` row per (question, repeat) carrying `verdict`, `fail_reason`, `quality_score`, the four `dim_*`, `grounding_contradicted`, `latency_breach`.

**Acceptance criteria**:
- [ ] Every run appends exactly one `runs` row + N×R `question_results` rows
- [ ] Persisted fields match `VerdictDecision` (no metrics-only silent drop)

---

### Task T-W4-03 — Regression diff vs baseline + rolling window → `_regressions.json` + `--set-baseline`

| Attribute | Value |
|-----------|-------|
| Type | impl |
| depends_on | T-W4-02 |
| blocks | T-W5-02 |
| Target files | `scripts/run_chat_quality_benchmark.py`, `scripts/chat_quality_trend.py` |
| PRD ref | FR-14, FR-15, §6.7 |

**What to build**:
- Diff the current run vs the `is_baseline=1` run and a rolling window: per-question verdict downgrades (PASS→WEAK/FAIL), `quality_score` drops beyond a noise threshold, new invariant violations, latency-breach increases. Emit `_regressions.json` (machine-readable). Add `--set-baseline <run_ts>` to register the comparison baseline. Supersedes the stop-gap single `--baseline` diff with a durable store-backed diff (keep `--baseline` working as an alias).

**Tests to write**:
| Test | Verifies | Type |
|------|----------|------|
| test_trend_append_and_regression_diff | append + PASS→FAIL downgrade detected vs baseline | unit |
| test_regression_quality_drop_threshold | drop within noise → not flagged; beyond → flagged | unit |
| test_set_baseline_marks_run | `--set-baseline` sets is_baseline=1 (and clears prior) | unit |

**Acceptance criteria**:
- [ ] `_regressions.json` produced; downgrades + score drops + new invariants + latency breaches detected
- [ ] `--set-baseline` registers baseline; only one baseline at a time

### Pre-read (W4)
- `scripts/run_chat_quality_benchmark.py` (run loop, existing `--baseline` diff, report assembly)
- PRD §6.4 (exact column schema)

### Validation Gate (W4)
- [ ] ruff + mypy clean
- [ ] ≥ 9 new unit tests pass
- [ ] trend.sqlite + trend.jsonl committed and queryable; regression diff produces `_regressions.json`
- [ ] NFR-6: no exit-code change unless `--strict`

### Architecture Compliance (W4)
- [ ] R8/R9/AD-5: in-repo SQLite, never a service DB
- [ ] R11: UTC timestamps in all rows
- [ ] F-5: busy-retry + jsonl backstop for parallel sessions (R42)

### Break Impact (W4)
| Broken File | Why | Fix |
|-------------|-----|-----|
| any `scripts/` test asserting the run produces only per-run JSON | new trend writes + `_regressions.json` | update expected artefact set |

### Regression Guardrails (W4)
- **R42 / BP-590**: trend.sqlite write contention across parallel sessions — short transaction + retry + lock-free jsonl sidecar.
- **feedback_audit_returned_value_persistence**: regression results must be persisted to `_regressions.json` AND surfaced in the report (W5), not consumed only as a counter.

---

## Wave 5 — Failure-First Report + Single Authority + `chat_eval` Consolidation

**Goal**: Rewrite the report information hierarchy failure-first, print exactly one authoritative
verdict system (demote legacy buckets), and reduce `chat_eval`'s binary gate to a thin wrapper
that delegates to the tiered engine, consolidating the two question catalogues (OQ-1).
**Depends on**: W1 (verdict), W4 (regressions, for the top section) | **Parallelizable with**: W4 (report-skeleton parts) | **Effort**: ~1.25 dev-days
**Architecture layer**: `scripts/` report + `tests/validation/chat_eval/` consolidation

### Task T-W5-01 — Failure-first `_report.md` rewrite (FR-16/17/18)

| Attribute | Value |
|-----------|-------|
| Type | impl |
| depends_on | T-W1-03 |
| blocks | T-W5-02 |
| Target files | `scripts/run_chat_quality_benchmark.py` (report assembly) |
| PRD ref | FR-16, FR-17, FR-18, §6.6.1 |

**What to build**:
- Reorder the report per §6.6.1: lead with authoritative verdict counts (FAIL first), regressions vs baseline at the top, an expanded **Failures** section (each FAIL with triggering `InvariantCode`, offending answer excerpt, and for `GROUNDING_CONTRADICTED` the claim-vs-sample mismatch inline), a latency-breach list, then the regression block. **Demote** the average + per-dimension means into a collapsed `<details>` appendix. Print **exactly one** authoritative verdict; legacy heuristic buckets removed from the headline (kept only in the collapsed appendix labelled "legacy / non-authoritative" if retained).

**Tests to write**:
| Test | Verifies | Type |
|------|----------|------|
| test_report_failures_lead | FAIL section precedes the means appendix | unit |
| test_report_single_authority | only one verdict system in the headline | unit |
| test_report_contradiction_shows_claim_vs_sample | GROUNDING_CONTRADICTED renders claim+sample+delta | unit |

**Acceptance criteria**:
- [x] Failure-first hierarchy; means demoted to collapsed appendix
- [x] One authoritative verdict; legacy buckets demoted/labelled (FR-18)
- [x] Each FAIL shows invariant + excerpt inline (FR-17)

---

### Task T-W5-02 — Surface regressions at report top + `_regressions.json` link

| Attribute | Value |
|-----------|-------|
| Type | impl |
| depends_on | T-W5-01, T-W4-03 |
| blocks | none |
| Target files | `scripts/run_chat_quality_benchmark.py` |
| PRD ref | FR-15, §6.6.1 |

**What to build**:
- Render the regression delta (downgrades, score drops, new invariants) at the **top** of the report and link the machine-readable `_regressions.json`.

**Acceptance criteria**:
- [x] Regressions appear above any average; `_regressions.json` referenced

---

### Task T-W5-03 — Reduce `chat_eval` binary gate to a thin delegating wrapper (OQ-1)

| Attribute | Value |
|-----------|-------|
| Type | impl |
| depends_on | T-W1-04 |
| blocks | T-W5-04 |
| Target files | `tests/validation/chat_eval/grading.py` (`grade_response` L365), `tests/validation/chat_eval/test_*.py` |
| PRD ref | OQ-1 (RESOLVED), FR-1, §5 |

**What to build**:
- Make the `chat_eval` binary PASS/FAIL gate **delegate** to the tiered scoring engine (`chat_quality_judge` invariant gate + verdict) instead of running a second, divergent scoring path. The binary gate maps tiered `FAIL → fail`, `WEAK/PASS/STRONG → pass` (or a stated threshold). **Keep** the shared SSE/dev-login harness. **Do not weaken or delete** the existing `chat_eval` per-question tests (R19) — they continue to assert acceptance, now backed by the single engine.

**Tests to write / update**:
| Test | Verifies | Type |
|------|----------|------|
| test_chat_eval_delegates_to_tiered | binary gate verdict derives from VerdictDecision, not a second path | unit |
| existing `test_q1..q8`, adversarial, topic tests | still pass via the delegated engine | unit |

**Downstream test impact**:
- All `tests/validation/chat_eval/test_q*.py` + `test_new_topics_adversarial.py` + `test_iter3_topics.py` assert on `grade_response`; they must pass through the delegated engine unchanged in intent.

**Acceptance criteria**:
- [x] No second scoring path: `chat_eval` PASS/FAIL is derived from the tiered engine (`grading.py::tiered_verdict_for` → `grade_response` maps fired gate → HARMFUL/USELESS; legacy heuristics retained ADD-only so the gate can only get stricter)
- [x] All existing `chat_eval` tests pass (R19) — 46 unit `test_grading.py` green; live-gated per-Q tests skip without a stack

---

### Task T-W5-04 — Consolidate the two question catalogues into one (F9)

| Attribute | Value |
|-----------|-------|
| Type | impl |
| depends_on | T-W5-03 |
| blocks | none |
| Target files | `tests/validation/chat_eval/questions.yaml`, `tests/validation/chat_quality_benchmark/questions/` |
| PRD ref | OQ-1 (RESOLVED), §5 (F9 cleanup) |

**What to build**:
- Consolidate `chat_eval/questions.yaml` and `chat_quality_benchmark/questions/` into **one** canonical catalogue (choose the benchmark's structured `questions/` as canonical or a single merged YAML — document the choice). Update both runners + the `test_questions_schema.py` schema test to read the single source. No question is dropped without an explicit note.

**Tests to write / update**:
| Test | Verifies | Type |
|------|----------|------|
| test_single_question_catalogue | both runners load from one source; no duplicate ids | unit |
| `test_questions_schema.py` | schema validates the consolidated catalogue | unit |

**Acceptance criteria**:
- [x] One canonical question catalogue (`chat_quality_benchmark/questions/*.yaml`); both entrypoints read it (benchmark runner natively; chat_eval via `harness.load_questions` projecting `chat_eval_id`-tagged entries). `chat_eval/questions.yaml` → deprecated empty stub.
- [x] No silent question loss (all 9 q1..q8/a10 preserved + `ground_truth_assertions` merged in verbatim); schema test green + new `test_chat_eval_questions_consolidated_into_canonical_catalogue`

### Pre-read (W5)
- `scripts/run_chat_quality_benchmark.py` (report section)
- `tests/validation/chat_eval/grading.py` L365-700, `tests/validation/chat_eval/questions.yaml`
- `tests/validation/chat_quality_benchmark/questions/`, `test_questions_schema.py`

### Validation Gate (W5)
- [x] ruff clean (touched files); mypy: no NEW errors introduced (pre-existing `_StandaloneClient`/harness `no-any-return`/`has-type` errors unchanged)
- [x] 16 new unit tests pass (8 report + 6 grading delegation/loader + 2 schema consolidation); **all** existing chat_eval unit tests green (R19); live-stack per-Q + aggregate tests skip without `RAG_CHAT_BASE_URL`
- [x] Report leads with FAILs + regressions; means collapsed in `<details>`; one authoritative verdict
- [x] Single question catalogue; both runners read it

### Break Impact (W5)
| Broken File | Why | Fix |
|-------------|-----|-----|
| `tests/validation/chat_eval/test_q*.py`, adversarial/topic tests | gate now delegates to tiered engine | ensure verdict mapping keeps them green; do not weaken |
| `tests/validation/chat_quality_benchmark/test_questions_schema.py` | single catalogue | point at consolidated source |

### Regression Guardrails (W5)
- **R19 / feedback_never_delete_tests**: the chat_eval per-question gate tests must keep passing through the delegated engine — never delete/skip to make consolidation green.
- **feedback_tracking_and_docs_mandatory**: update plan + TRACKING + `docs/services/rag-chat.md` (eval section) on completion.

---

## Wave 6 — Human-Labelled GOLD Set + Cohen's κ Calibration (HUMAN-IN-THE-LOOP)

> **STATUS: AUTOMATABLE PARTS SHIPPED 2026-06-12** (T-01, T-01b loader, T-03,
> T-04, T-05 docs). New `scripts/chat_quality_calibration.py` (`assemble` +
> `calibrate` subcommands) + `tests/validation/chat_quality_benchmark/gold/`
> (`gold_set.jsonl` = 39 items stratified fabrication 9 / leak 8 / infra 8 /
> good 8 / refusal 6 across 7 real runs; blank `gold_labels.yaml`; `README.md`
> with HUMAN LABELLING INSTRUCTIONS). Note: the gold set is written as **JSONL**
> (not YAML) per the W6 task brief for line-stable diffs. The κ harness computes
> Cohen's κ + 2×2 confusion (false-PASS-on-fabrication cell highlighted) +
> per-dim MAE + the κ≥0.7-AND-zero-fabrication-false-PASS gate, writes
> `gold/_calibration_report.{md,json}` (accept/reject first), and degrades
> gracefully on the blank set ("0/39 labelled — cannot compute", exit 0). 26 new
> unit tests (synthetic-κ / confusion / MAE / accept+both-reject / blank-set /
> loader range+missing+blank validation / v2+v3 verdict extraction).
> FR-12 recalibration cadence documented in `docs/services/rag-chat.md`.
> **STILL PENDING: T-02 — a human must label `gold_labels.yaml`** before κ can
> be computed (the blocking human-in-the-loop gate).

**Goal**: Build a ~40-item gold set stratified by failure mode, capture human labels, and compute
Cohen's κ + confusion matrix + per-dim MAE, gated on κ ≥ 0.7 + zero false-PASS-on-fabrication.
**Depends on**: W3 (judge v3.0 is the version under calibration) + stable W4/W5 artefacts | **Effort**: ~1.5 dev-days + human labelling time
**Architecture layer**: `tests/validation/chat_quality_benchmark/{gold,calibration}/` + `scripts/`

### Task T-W6-01 — Assemble unlabelled `gold_set.yaml` (~40 items, stratified)

| Attribute | Value |
|-----------|-------|
| Type | impl |
| depends_on | T-W5-04 |
| blocks | T-W6-02 |
| Target files | `tests/validation/chat_quality_benchmark/gold/gold_set.yaml` (**NEW**), a small assembly helper in `scripts/` |
| PRD ref | FR-9, OQ-2 (RESOLVED: ~40, stratified), §6.4, §8.1 |

**What to build** (**NEW**):
- Draw ~40 `{question_id, run_ref, answer_text, tool_trace, grounding_sample}` snapshots from **real stored runs**, **stratified by failure mode**: fabrication / leak / infra-failure / good / appropriate-refusal — including a **deliberate fabrication+leak subset** so the confusion matrix has signal in the false-PASS-on-fabrication cell. **Synthetic / public-entity questions only — no real user-portfolio data** (§8.1).

**Acceptance criteria**:
- [x] ~40 items (39), each stratum represented; fabrication+leak subset present (9 fab all machine-PASS = false-PASS signal)
- [x] No real-account / PII data in the committed fixture (synthetic/public-entity questions only)
- [x] Written as `gold/gold_set.jsonl` + blank `gold/gold_labels.yaml` + `gold/README.md` (assembler: `scripts/chat_quality_calibration.py assemble`)

---

### Task T-W6-02 — 🧑 HUMAN: label `gold_labels.yaml` (PASS/FAIL + per-dim)

| Attribute | Value |
|-----------|-------|
| Type | **human-in-the-loop** |
| depends_on | T-W6-01 |
| blocks | T-W6-03, T-W6-04, T-W6-05 |
| Target files | `tests/validation/chat_quality_benchmark/gold/gold_labels.yaml` (**NEW**) |
| PRD ref | FR-9, OQ-5 (RESOLVED: 4 dims + new coherence/completeness), §6.4 |

**What to do** (agent prepares, **human labels**):
- Agent writes an empty labelling worksheet (one row per gold item) + a schema-validating loader.
- **Human** assigns `human_verdict ∈ {PASS, FAIL}` and `human_dims ∈ {tool_use, grounding, framing, coherence}` (0-25 each — the current 4 dims **plus the new coherence/completeness dim** per OQ-5), with `labeler` + `labeled_at`.
- Loader schema-validates: `verdict ∈ {PASS,FAIL}`, dims ∈ [0,25] (§8.2).

**Acceptance criteria**:
- [ ] All ~40 items labelled by a human; loader schema-validation passes
- [ ] Per-dim labels include the new coherence/completeness dim (OQ-5)

> **BLOCKING human gate**: W6-T-3/T-4/T-5 cannot proceed until this file is populated by a human.

---

### Task T-W6-03 — κ + agreement % + 2×2 confusion matrix + per-dim MAE

| Attribute | Value |
|-----------|-------|
| Type | impl |
| depends_on | T-W6-02, T-W3-03 |
| blocks | T-W6-04 |
| Target files | `scripts/chat_quality_calibrate.py` (**NEW**) |
| PRD ref | FR-10, AD-6, §6.6.2 |

**What to build** (**NEW**):
- Judge each gold item **offline from stored artefacts** (NFR-4) with judge v3.0; compute Cohen's κ on binary PASS/FAIL, raw agreement %, the 2×2 confusion matrix (highlight the **false-PASS-on-fabrication** cell), and per-dimension MAE vs human labels.

**Tests to write** (PRD §11.1):
| Test | Verifies | Type |
|------|----------|------|
| test_kappa_and_confusion_matrix | κ + confusion matrix correct on a synthetic label set | unit |
| test_per_dim_mae | MAE computed per dimension | unit |

**Acceptance criteria**:
- [x] κ, agreement %, confusion matrix, per-dim MAE computed deterministically (in `scripts/chat_quality_calibration.py`; tested on synthetic fixtures with hand-computed κ=0.40)
- [x] Calibration runs offline from stored artefacts (no chat re-run); blank set → "0/39 labelled — cannot compute" (exit 0)

---

### Task T-W6-04 — Acceptance bar + accept/reject gate (κ≥0.7 + zero false-PASS-fabrication)

| Attribute | Value |
|-----------|-------|
| Type | impl |
| depends_on | T-W6-03, T-W1-02 |
| blocks | T-W6-05 |
| Target files | `scripts/chat_quality_calibrate.py` |
| PRD ref | FR-11, OQ-4 (RESOLVED), §6.6.2 |

**What to build**:
- Enforce the bar: **fail the calibration run** if κ < 0.7 OR the false-PASS-on-fabrication cell is non-empty. Emit the calibration report `calibration/<judge_version>_<ts>.json` (+ `.md`) leading with accept/reject, then κ, agreement, confusion matrix, per-dim MAE (§6.6.2).

**Tests to write**:
| Test | Verifies | Type |
|------|----------|------|
| test_calibration_accept_reject | bar enforced; false-PASS-fabrication cell → reject | unit |
| test_calibration_kappa_below_bar_rejects | κ=0.65 → rejected | unit |

**Acceptance criteria**:
- [x] Calibration rejects on κ<0.7 or any false-PASS-fabrication (both reject cases unit-tested)
- [x] `gold/_calibration_report.json` + `.md` written, accept/reject first (FR-11)

---

### Task T-W6-05 — Recalibration trigger + FR-12 discontinuity record + cadence docs

| Attribute | Value |
|-----------|-------|
| Type | impl + docs |
| depends_on | T-W6-04, T-W3-04 |
| blocks | none |
| Target files | `scripts/run_chat_quality_benchmark.py`, `scripts/chat_quality_calibrate.py`, `docs/services/rag-chat.md` (eval section) |
| PRD ref | FR-12, FR-4, OQ-6 (RESOLVED), §12.2, F-3 |

**What to build**:
- Warn/refuse to use a judge version for "thesis-blessed" numbers if no passing calibration exists for that `judge_prompt_version` + model id (FR-12).
- Record the FR-4 **discontinuity**: one-time dual-grade of the baseline run under the additive (v2) verdict and the tiered (v3) verdict, both stored in the trend, annotated (§12.2, F-3).
- Document the recalibration cadence (OQ-6): every judge-version bump + every agent-tool-surface change + a monthly floor.

**Acceptance criteria**:
- [x] Cadence documented in `docs/services/rag-chat.md` ("Judge Calibration & Recalibration Cadence" — tied to the v3.0 bump, tool-surface change, monthly floor)
- [ ] Uncalibrated judge version flagged before thesis numbers are trusted (runner-side flag — deferred; needs a non-automatable trend write)
- [ ] Baseline dual-grade (v2+v3) recorded in trend + annotated (deferred — requires a live re-grade run)

### Pre-read (W6)
- `scripts/chat_quality_judge.py` (`build_input_from_artifact`, `judge_answer`)
- PRD §6.4 (gold/label/calibration schemas), §6.6.2, §11.3

### Validation Gate (W6)
- [ ] ruff + mypy clean
- [ ] ≥ 6 new unit tests pass (κ/confusion/accept-reject on synthetic labels)
- [ ] gold_set.yaml (~40, stratified) + human gold_labels.yaml committed
- [ ] Calibration report produced; bar enforced; FR-12 + discontinuity recorded
- [ ] `docs/services/rag-chat.md` eval section updated

### Architecture Compliance (W6)
- [ ] R11 UTC for `labeled_at` / calibration timestamps
- [ ] §8.1: gold fixtures contain no real user / PII data
- [ ] NFR-4: calibration runs offline from stored artefacts

### Break Impact (W6)
| Broken File | Why | Fix |
|-------------|-----|-----|
| none expected (new files) | gold/calibration are additive | n/a — but the trend gains a `judge_prompt_version` discontinuity row |

### Regression Guardrails (W6)
- **F-6 (PRD §9)**: gold-set staleness — refresh when the agent tool surface changes; cadence enforced (OQ-6).
- **feedback_audit_returned_value_persistence**: κ + accept/reject must be persisted to `calibration/*.json` AND gate "thesis-blessed" usage — not computed-and-discarded.

---

## Cross-Cutting Concerns

| Concern | Detail |
|---------|--------|
| **SSE contract** | `tool_result` gains one additive optional field (W2); legacy 4-key byte-identical when off (AD-4). Update `docs/services/rag-chat.md` SSE section. |
| **Prompt version** | `CHAT_QUALITY_JUDGE` 2.0→3.0 (W3) — semver + content_hash + CHANGELOG (PRD-0030 pattern); triggers FR-12 recalibration (W6). |
| **New env var** | `CHAT_EVAL_GROUNDING_SAMPLES` (default false) — add to rag-chat settings + `dev.local.env.example`. |
| **New in-repo store** | `tests/validation/chat_quality_benchmark/{trend,gold,calibration}/` committed; SQLite + jsonl + yaml (AD-5, NFR-5). No service DB, no migration. |
| **Docs** | `docs/services/rag-chat.md` (SSE field, env flag, eval methodology, calibration cadence); plan file + TRACKING.md every wave. |
| **No HTTP API change** | S9 gateway request/response shapes unchanged (§6.2). |

---

## Risk Assessment

| Risk | Severity | Mitigation |
|------|----------|------------|
| **Parallel session conflict on `chat_orchestrator.py` (W2-T-03)** | HIGH | Own worktree; `orphan_commit_check.sh`; minimal additive kwarg; land W1 first. R42/BP-590. |
| **Judge v3.0 invalidates longitudinal comparability (FR-12 / F-3)** | HIGH (expected) | FR-4 dual-grade of baseline under v2+v3, recorded + annotated in trend (W6-T-05). |
| **Weak/biased gold set → meaningless κ** | HIGH | Stratified ~40 incl. fabrication+leak subset (W6-T-01); human labelling (W6-T-02); per-dim MAE cross-check. |
| **Numeric cross-check false positives (F-2)** | MED | Same-field + tolerance + fence-skip guards (W3-T-01); gold set as regression net. |
| **Grounding-sample PII leak** | MED→HIGH | Allow-list + redaction + unknown-tool-no-sample + default-OFF flag (W2-T-01/02, §8). |
| **trend.sqlite contention (R42)** | LOW | Short txn + busy-retry + jsonl sidecar (W4-T-01). |

**Critical path**: W1 → (W2 in parallel) → W3 → W6 (calibration validates the whole instrument).
W4 and W5 hang off W1 and can run in parallel with each other once W1 lands.

**Human-in-the-loop**: W6-T-02 (gold-set labelling) is the only task requiring a human; it blocks
all κ/calibration tasks. Schedule the human labelling session as soon as W6-T-01 produces the
unlabelled gold set.

---

## Compounding Check

- Consider adding a BUG_PATTERN for the F1 class (additive scoring lets a catastrophic single-dim
  failure PASS) and the "PRESUME GROUNDED" instruction anti-pattern (a judge instructed to assume
  the thing it is meant to verify) once W3 lands.
- `docs/services/rag-chat.md` must document the eval methodology (tiered verdict, verifiable
  grounding, κ calibration cadence) on W6 completion — this is the thesis-citable artefact.
