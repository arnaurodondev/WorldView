# `.claude/eval-artifacts/`

Machine-readable evidence that a **live eval run** validated a change to a
versioned prompt file, checked mechanically by
[`scripts/hooks/check_tool_use_prompt_eval_artifact.py`](../../scripts/hooks/check_tool_use_prompt_eval_artifact.py)
(wired into `scripts/hooks/pre-commit-validate.sh` and
`scripts/hooks/pre-pr-checklist.sh`).

Background: `docs/audits/2026-07-23-bottleneck-rag-chat-grounding.md` §1
Recurrence B, `docs/BUG_PATTERNS.md` BP-735,
`.claude/review/heuristics/HIGH_RISK_PATTERNS.md` HR-065,
`.claude/review/checklists/REVIEW_CHECKLIST.md:117`.

## Current gated files

| Source file | Artifact naming convention |
|---|---|
| `libs/prompts/src/prompts/chat/tool_use.py` (`TOOL_USE_SYSTEM_PROMPT_TEMPLATE.version`) | `tool_use_v<version>.json`, e.g. `tool_use_v1.27.json` |

Add a row here (and a matching branch in the check script) if another
versioned, additive, LLM-interpreted prompt file earns the same gate.

## Artifact schema (minimum required shape)

```json
{
  "prompt_version": "1.27",
  "run_id": "run_20260723T120000Z",
  "model": "Qwen3-235B-A22B-Instruct-2507",
  "questions": [
    {
      "question_id": "cmp_nvda_amd",
      "tools_called": ["get_fundamentals_history_batch", "traverse_graph"],
      "expected_tools": ["traverse_graph"],
      "pass": true
    }
  ],
  "regressions": []
}
```

- `questions` — one entry per question in the FULL regression set
  (`tests/validation/chat_eval/questions.yaml`), not a hand-picked subset.
  `tools_called` should come straight from the eval harness's
  `ConversationResult.tools_called()` (`tests/validation/chat_eval/harness.py`).
- `regressions` — non-empty entries document a KNOWN, reviewed regression
  (a previously-passing question that lost a previously-called tool). An
  empty list represents a clean run. A non-empty list still satisfies the
  gate — the point is forcing the evidence to exist and be reviewed, not
  auto-blocking every prompt change forever — but the PR description should
  explain each entry.

## How to produce one

1. Run `tests/validation/chat_eval/harness.py` against
   `tests/validation/chat_eval/questions.yaml` with the new prompt version
   live (see `services/rag-chat/.claude-context.md` for eval-harness
   environment/API-key setup gotchas).
2. Diff each question's `tools_called()` against its previously-passing
   trace (raw traces persist under
   `tests/validation/chat_eval/runs/<run_ts>/q<N>.json`).
3. Distill the result into `tool_use_v<version>.json` per the schema above
   and commit it alongside the prompt change — OR, if a full run is not
   practical in the moment, commit with an `Eval-Artifact: <path-or-run-id>`
   trailer in the commit message instead (the gate accepts either).

No artifact from this directory is consumed at runtime by any service —
this is a development/CI-time gate only.
