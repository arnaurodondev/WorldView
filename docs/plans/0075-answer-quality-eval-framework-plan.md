---
id: PLAN-0075
prd: docs/specs/0034-mvp-launch-readiness-program.md
prd_section: "§3 FR-T1-2 (eval gate) extended; §6 W5 follow-on"
title: "Layered Answer-Quality Eval Framework (L2 tool-selection + L3 answer-quality + L4 operational + UI feedback loop)"
status: stub
created: 2026-05-05
updated: 2026-05-05
plans: 1
waves: 6
tasks: ~22 (TBD when fleshed out)
critical_path: "depends on PLAN-0067 W11-3 (tool-call orchestrator) being live; depends on PLAN-0063 W5-1 eval infra being merged; user-onboarding milestone unblocks calibration step"
depends_on:
  - PLAN-0063 (L1 chunk eval substrate; dataset format; precomputed-embedding pattern)
  - PLAN-0067 W11-2 (tool catalog) and W11-3 (tool-use orchestrator)
provides:
  - Layered eval framework L2/L3/L4 over the existing L1 substrate
  - `routing_observations` table in intelligence_db (per-turn rag-chat write hook)
  - `chat_feedback` table (👍/👎 + outcome-language reason chips)
  - LLM-judge infrastructure for faithfulness, correctness, completeness, refusal-correctness
  - Operational gates (latency p95, cost/turn, stability under load)
  - Live-traffic backflow process for golden-set growth
  - LLM-judge calibration against thumbs feedback
revision_history:
  - 2026-05-05: stub created at PLAN-0063 revision v2; absorbs the v1 PLAN-0063 W5-7 (intent observability + UI feedback) which was misplaced in the retrieval plan
---

# PLAN-0075 — Layered Answer-Quality Eval Framework (Stub)

> **Status**: stub. This plan is sketched but not fully decomposed. It will be expanded with full wave bodies once (a) PLAN-0063 W5-3 has captured the post-hybrid baseline, (b) PLAN-0067 W11-3 (tool-use orchestrator) is on a known timeline. Until then, the wave map below is directional, not prescriptive.

## 0. Why This Plan Exists

PLAN-0063 ships the L1 (per-tool retrieval) eval substrate. That's necessary but not sufficient for a Bloomberg-class product. Three more eval layers are required:

- **L2 — Tool selection**: did the LLM pick the right tool(s) and pass the right parameters? Multi-label classification problem; CI gate on tool-set F1 + parameter correctness.
- **L3 — End-to-end answer quality**: is the final answer faithful (matches retrieved evidence), correct (matches ground truth), complete (covers the question), well-cited (citations resolve), and appropriately refused (out-of-scope, decision-support deflection)? LLM-judge with calibration against UI thumbs feedback.
- **L4 — Operational**: latency p95, cost/turn, stability over repeated calls. Nightly + per-PR.

In addition, this plan owns the **UI feedback loop** — 👍/👎 + reason chips with **outcome language** (no "tool" jargon visible to users), and the supporting tables (`routing_observations`, `chat_feedback`).

## 1. Cross-Plan Dependencies

- **PLAN-0063 W5-1** must be merged: the `scripts/eval.py` framework, the `tests/eval/golden/` directory layout, the precomputed-embedding pattern, and the CI workflow scaffolding are reused.
- **PLAN-0067 W11-2 (tool catalog)**: required for L2 — without a stable tool surface there is nothing to evaluate selection over.
- **PLAN-0067 W11-3 (tool-use orchestrator)**: required for L3 — answer quality on tool-call answers needs the tool-call code path live.
- **User onboarding (whatever plan owns it)**: required for L3 LLM-judge calibration — without thumbs feedback the judge prompt cannot be calibrated against ground truth.

## 2. Directional Wave Map

| Wave | Title | Depends on |
|---|---|---|
| W7-1 | Schema: `routing_observations` + `chat_feedback` tables in intelligence_db; rag-chat per-turn write hook (after-stream, non-blocking) | PLAN-0063 W5-3 |
| W7-2 | UI feedback loop: 👍/👎 buttons + reason chips with outcome language ("Wrong information", "Didn't answer my question", "Missing important context", "Outdated", "Too vague", "Sources didn't help", "Too slow", "Other"); `POST /api/v1/chat/turns/{turn_id}/feedback` endpoint in S9; client write to `chat_feedback` | W7-1 |
| W7-3 | L2 tool-selection eval: golden file `tests/eval/golden/expected_tools.jsonl` (per query: expected tool list + key parameter expectations); `scripts/eval.py --layer tool_selection`; tool-set F1 + parameter correctness via LLM-judge; CI gate | PLAN-0067 W11-2 + W7-1 |
| W7-4 | L3 answer-quality eval: golden file `tests/eval/golden/expected_answers.jsonl` (per query: expected key facts + acceptable phrasings + refusal-correct flag); LLM-judge prompts for faithfulness, correctness, completeness, citation-resolves, refusal-correctness; CI gate; `seed=fixed`, `temperature=0`, 3-retry median | PLAN-0067 W11-3 + W7-1 |
| W7-5 | L4 operational eval: latency p95 first-token + final-token; $/turn; same-question consistency over 5 retries; nightly + per-PR; gate placeholders (p95 first-token < 1.5s, p95 final < 8s, $/turn < $0.02 — refined here) | PLAN-0067 W11-3 |
| W7-6 | Calibration + live-traffic backflow: weekly job correlates LLM-judge faithfulness scores with thumbs feedback; re-tunes judge prompt if correlation < 0.6; quarterly backflow of 10 thumbs-down + 10 thumbs-up + 10 random rows from `chat_feedback` into the appropriate golden sets (anonymized, labeled, reviewed) | W7-2 + W7-4 + user onboarding |

## 3. Locked Decisions Carried From PLAN-0063 v2

The following decisions from PLAN-0063 §0-bis.0 (revision v2) apply to this plan and are not re-litigated:

- **L4 — Classifier dropped from runtime**: PLAN-0075 inherits the offline-batch-analytics-only classifier role. The classifier's predicted-intent column on `routing_observations` is computed asynchronously, not in the request path.
- **L15 — UI chips use outcome language**, not internal tool/architecture jargon. The mapping from chip → eval layer happens offline in the weekly review queue.
- **L16 — L4 placeholder gates** (p95 first-token < 1.5s, p95 final < 8s, $/turn < $0.02) are refined when W7-5 ships. They are documented here so retrieval-side tuning in PLAN-0063 has the right SLO target.

## 4. UI Chip Taxonomy (locked)

User-facing 👎 chips (multi-select) and their internal hypothesis routing:

| User-facing chip | Probable cause (internal hypothesis) | Eval layer that should have caught it |
|---|---|---|
| Wrong information | hallucination or bad evidence | L3 faithfulness |
| Didn't answer my question | wrong tool selected, or no tool called | L2 tool-selection |
| Missing important context | retrieval recall gap, or LLM didn't call enough tools | L1 recall + L2 |
| Outdated | recency decay tuning | PLAN-0063 W5-4 (recency) |
| Too vague | retrieval precision low, or LLM render shallow | L1 precision + L3 completeness |
| Sources didn't help | citation resolution, link rot, wrong chunk cited | PLAN-0063 W5-5 (citation cron) |
| Too slow | latency | L4 |
| Other | free text | weekly review queue triage |

👍 has no follow-up by default (friction kills feedback rate). Optional Nth-thumbs-up follow-up: "What did this help you do?" — used to surface workflows we don't yet support.

## 5. Open Questions (to resolve when plan is fleshed out)

- **OQ-0075-1**: should the LLM-judge for L3 be a different model from the chat completion model (to avoid self-rating bias)? Likely yes; candidates: Claude Sonnet 4.6, DeepSeek R1 32B (already used for citation cron in PLAN-0063 W5-5).
- **OQ-0075-2**: should L3 correctness require a human reviewer for some fraction of queries, or is the LLM-judge alone sufficient? Probably: human review for `factual_lookup` + `financial_data` (numeric), LLM-judge alone for `general` + `signal_intel`.
- **OQ-0075-3**: how often does the calibration job run? Weekly is the default; may need to be more frequent during early user onboarding when behaviour shifts.
- **OQ-0075-4**: how do we handle multi-turn conversations? L1/L2/L3 currently assume single-turn. Multi-turn is its own eval layer (L5?) or an extension of L3 — defer to v2 of this plan.
- **OQ-0075-5**: rate limit + abuse handling on `POST /v1/chat/turns/{turn_id}/feedback` — implement when W7-2 lands.

## 6. Activation Trigger

This plan moves from `stub` to `draft` when **either**:
- PLAN-0067 W11-3 enters in-progress status (signals tool-calling will be live soon), OR
- User onboarding milestone is announced (signals real feedback will flow soon)

— whichever comes first.

When activated, the wave bodies above will be fleshed out per the standard `/plan` skill format (full task detail, codebase state verification, break-impact tables, regression guardrails, validation gates).

---

## Compounding

Bug patterns and standards added by this plan when implemented:
- (TBD) BP-NEW: LLM-judge calibration drift detection
- (TBD) STANDARDS: feedback chip language must be outcome-language, never tool/architecture jargon
