# New judge prompt — CHAT_TRAJECTORY_JUDGE v1.0 (trajectory / tool-chain layer)

> Required record per the judge-prompt versioning convention: a new or bumped
> judge/grader prompt changes evaluation verdicts and must be traceable for the
> thesis evaluation. Recorded in `.claude/evals/` + `libs/prompts/CHANGELOG.md`.

| Field | Value |
|-------|-------|
| Date | 2026-06-25 |
| Plan / task | Multi-Level Eval Framework — Wave 2 (T1) |
| Template | `libs/prompts/src/prompts/evaluation/chat_trajectory_judge.py` -> `CHAT_TRAJECTORY_JUDGE` |
| Version | NEW `1.0` |
| identifier() | `chat_trajectory_judge@1.0#eb78317b2115` |
| content_hash | `eb78317b2115` (computed from the template body) |
| Companion answer judge | `CHAT_QUALITY_JUDGE` v3.0 — UNCHANGED (asserted by unit test) |

## What this is

A NEW LLM-as-judge prompt that grades the chat agent's TOOL-CHAIN TRAJECTORY
(its process), distinct from `CHAT_QUALITY_JUDGE` which grades the final answer.
It reads the SAME flat ordered tool trace the answer judge already renders
(`call N: <tool>(args) -> status=<...> items=<K>`, built by
`scripts/chat_quality_judge._build_user_prompt`) plus the question intent, and
scores four sub-dimensions, each 0-25:

1. **routing** — do the called tools fit the question's intent?
2. **ordering** — in a chain, is a dependency resolved before it is consumed?
3. **recovery** — after a failed/empty call, does the agent retry/substitute
   rather than give up or loop the identical call?
4. **efficiency** — is the call set minimal and non-redundant?

`trajectory_score = sum(4 sub-dims)` (0-100) is computed in the Python layer
(`scripts/chat_trajectory_judge.py`), NOT inside the prompt. The Python layer
also computes deterministic, LLM-free pre-signals (`redundant_call_pairs`,
`unrecovered_failures`) so the trajectory layer still yields signal with no
judge LLM configured.

Output is strict JSON `{routing, ordering, recovery, efficiency,
reviewer_summary}` (per-dim `{score, feedback}`), mirroring the answer judge.

## Why it is recorded

A new judge prompt establishes the v1.0 baseline for the trajectory metric. A
future body edit flips `content_hash` and breaks longitudinal trajectory
comparison in the thesis eval — the bump must be re-recorded here.

## Independence guarantee

`CHAT_QUALITY_JUDGE` (the answer grader, v3.0) is NOT modified by this change.
A unit test asserts its `content_hash` is unchanged so the answer-quality
longitudinal series is not perturbed by the trajectory layer.

## Wiring (eval-harness only)

- `scripts/chat_trajectory_judge.py` — `judge_trajectory(inp, *, llm=None)`,
  mirroring `judge_answer`; reuses `_build_user_prompt`. Returns a
  `TrajectoryJudgement` dict `{trajectory_score, sub_scores, reviewer_summary,
  judge_prompt_id, redundant_call_pairs, unrecovered_failures}`. `llm=None` ->
  deterministic pre-signals only + `trajectory_score=None` (SKIPPED).
- `scripts/run_chat_quality_benchmark.py` — additive `--trajectory` flag
  (default ON when `--judge` is on); attaches a `trajectory` block to each
  `q_<id>.json` and a `trajectory` roll-up to `_judge_summary.json` /
  `_report.md` "Trajectory (MUST-2)" section. Does NOT change the answer
  FAIL/PASS verdict.

## Data reality (2026-06-25)

The deterministic pre-signals (`redundant_call_pairs`, `unrecovered_failures`)
are exercised against synthetic traces in the unit tests and run even with no
`DEEPINFRA_API_KEY`. The live finding-run (a real benchmark execution to
surface trajectory regressions) is DEFERRED (T-W2-04) and is NOT part of this
change — BUILD + TEST + VALIDATE only.
