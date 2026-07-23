#!/usr/bin/env python3
"""Block a version bump to ``TOOL_USE_SYSTEM_PROMPT_TEMPLATE`` without an
attached live-eval artifact (2026-07-23 bottleneck audit, §4 item 3;
Recurrence B / BP-735 / HR-065 / REVIEW_CHECKLIST.md:117).

WHY THIS EXISTS
----------------
``libs/prompts/src/prompts/chat/tool_use.py`` is a versioned, additive,
natural-language system prompt that drives tool selection for the chat
orchestrator. Every prior regression in this file (see the module's own
version-history comment, e.g. v1.23 -> v1.24, and the `1e8744443` "reverse
v1.17 hypothesis regression" precedent) was caught ONLY by a live A/B run
against a real model (Qwen3-235B / gpt-oss-120b) — never by
``libs/prompts/tests/test_tool_use_prompt.py``, which asserts the prompt's
*static string contract* (version bump present, new clause text present) and
cannot predict how a stochastic model weighs two competing imperative clauses
against each other. ``REVIEW_CHECKLIST.md:117`` already tells a human
reviewer to ask for that live-run evidence, but a checklist line is advisory
only — nothing blocks the merge if the author forgets or skips it under time
pressure. This script makes that requirement a MECHANICAL gate instead of a
memory-dependent one, mirroring the existing "Pre-PR checklist" hook pattern
(``scripts/hooks/pre-pr-checklist.sh``, registered in
``.claude/settings.json`` under the ``Bash.*gh pr create`` / ``Bash.*git
commit`` matchers) — i.e. a repo-native script wired into the SAME hook
infrastructure the ruff/mypy checks already use, not a new external system.

WHAT IT DOES
------------
1. Diffs ``libs/prompts/src/prompts/chat/tool_use.py`` (staged diff by
   default; set ``TOOL_USE_EVAL_GATE_DIFF_RANGE`` to a git revision range,
   e.g. ``main...HEAD``, to check a range instead — used in the pre-PR/CI
   context).
2. If the diff touches the ``version="X.Y"`` kwarg on
   ``TOOL_USE_SYSTEM_PROMPT_TEMPLATE`` (a ``PromptTemplate(...)`` call), it
   extracts the new version string.
3. Requires ONE of:
   a. A machine-readable artifact file at
      ``.claude/eval-artifacts/tool_use_v<version>.json`` (schema below), OR
   b. An ``Eval-Artifact: <path-or-run-id>`` trailer in the commit message
      (read from the ``TOOL_INPUT`` env var's ``command`` field when
      invoked as a Claude Code ``PreToolUse`` hook on ``git commit``, or
      from the tip commit's message in the CI/range context).
4. If neither is present: prints a clear, actionable failure and exits 1
   (mirrors ``pre-commit-validate.sh``'s "block, don't silently warn"
   contract — wire this script into that hook's step sequence, see below).
   If the file is untouched, or touched but the version constant did not
   change, exits 0 (no-op) — this gate is narrowly scoped to version bumps
   only, exactly like the checklist line it replaces.

HOW A FUTURE SESSION PRODUCES A REAL ARTIFACT
----------------------------------------------
This script does NOT run a live eval itself (no LLM access from this repo's
CI sandbox) — it only enforces that one was run and its result attached.
To produce a real artifact for a prompt version bump:

1. Run the existing chat-quality eval harness against the FULL regression
   question set (not a hand-picked subset):
   ``tests/validation/chat_eval/harness.py`` + ``tests/validation/chat_eval/
   questions.yaml`` — this is the SAME harness that already exercises
   ``tool_calls`` / ``tools_called()`` per question (see
   ``ConversationResult.tools_called`` in ``harness.py``) and persists raw
   traces to ``tests/validation/chat_eval/runs/<run_ts>/q<N>.json``.
2. For every question, compare the new prompt version's ``tools_called()``
   list against the question's expected/previously-passing tool list. Any
   PREVIOUSLY-PASSING question that drops a previously-called tool is a
   regression — this is exactly the ``cmp_nvda_amd`` failure mode
   (BP-735) that motivated this gate.
3. Distill the run into
   ``.claude/eval-artifacts/tool_use_v<new_version>.json`` with (at
   minimum) this shape:

   .. code-block:: json

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

   ``regressions`` MUST be an empty list for the artifact to represent a
   clean run — a non-empty list documents a KNOWN, accepted regression and
   still satisfies this gate (the point is forcing the evidence to exist
   and be reviewed, not silently blocking every bump forever); a human
   reviewer or the PR description should explain any non-empty
   ``regressions`` entry.
4. Commit the artifact file alongside the prompt change (satisfies check
   3a above), OR, if a full harness run is impractical in the moment,
   commit with an ``Eval-Artifact: <run-id-or-path>`` trailer pointing at
   where the run's results live (satisfies check 3b) — e.g.:

   .. code-block:: text

       feat(prompts): tool_use v1.27 hoists BATCH WIDTH scoping

       Eval-Artifact: tests/validation/chat_eval/runs/run_20260723T120000Z/

Exit codes:
    0 — gate satisfied (no version bump, or artifact/trailer present).
    1 — version bump detected with NO attached eval evidence.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
TOOL_USE_REL_PATH = "libs/prompts/src/prompts/chat/tool_use.py"
ARTIFACT_DIR = ROOT / ".claude" / "eval-artifacts"

# Matches the `version="1.26"` kwarg on the PromptTemplate(...) call —
# deliberately narrow (only the exact kwarg name) so unrelated numeric
# literals elsewhere in the file never trip the gate.
_VERSION_KWARG_RE = re.compile(r'version\s*=\s*"([0-9]+(?:\.[0-9]+)*)"')

# The commit-message escape hatch. Must appear on its own line, matching the
# style of other structured trailers (e.g. `Co-Authored-By:`).
_EVAL_ARTIFACT_TRAILER_RE = re.compile(r"^Eval-Artifact:\s*(\S.*)$", re.MULTILINE)


def _run_git(args: list[str]) -> str:
    """Run a git command from the repo root and return stdout (never raises)."""
    result = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout


def _diff_target_args() -> list[str]:
    """Return the ``git diff`` positional args identifying what to inspect.

    Defaults to the staged diff (pre-commit hook context: ``git diff
    --cached``). Set ``TOOL_USE_EVAL_GATE_DIFF_RANGE`` (e.g. ``main...HEAD``)
    to check a committed range instead — used by the pre-PR / CI context,
    which runs after the commit(s) already exist.
    """
    diff_range = os.environ.get("TOOL_USE_EVAL_GATE_DIFF_RANGE", "").strip()
    if diff_range:
        return [diff_range]
    return ["--cached"]


def _tool_use_diff() -> str:
    """Return the unified diff for ``tool_use.py`` in the target range.

    Empty string when the file is untouched in that range (including when
    the range comparison itself fails, e.g. an unknown ref — treated the
    same as "nothing to check" so this gate never crashes a commit over an
    unrelated git-state issue; ruff/mypy/tests are the hooks responsible for
    catching real problems).
    """
    return _run_git(["diff", *_diff_target_args(), "--", TOOL_USE_REL_PATH])


def extract_version_bump(diff_text: str) -> tuple[str | None, str | None]:
    """Return ``(old_version, new_version)`` parsed from a unified diff.

    Only lines that are pure removals/additions (not context lines, not the
    ``---``/``+++`` file headers) are inspected. Returns ``(None, None)``
    when the diff does not touch the ``version=`` kwarg at all (e.g. the
    file changed but the version constant did not).
    """
    old_version: str | None = None
    new_version: str | None = None
    for line in diff_text.splitlines():
        if line.startswith("---") or line.startswith("+++"):
            continue
        if line.startswith("-"):
            m = _VERSION_KWARG_RE.search(line)
            if m:
                old_version = m.group(1)
        elif line.startswith("+"):
            m = _VERSION_KWARG_RE.search(line)
            if m:
                new_version = m.group(1)
    return old_version, new_version


def _artifact_path_for(version: str) -> Path:
    return ARTIFACT_DIR / f"tool_use_v{version}.json"


def _commit_message_best_effort() -> str:
    """Best-effort commit message lookup across the two invocation contexts.

    Pre-commit context (default ``--cached`` diff target, no
    ``TOOL_USE_EVAL_GATE_DIFF_RANGE`` set): Claude Code's ``PreToolUse`` hook
    passes the full shell command about to run (e.g. ``git commit -m
    "..."``) via the ``TOOL_INPUT`` env var as a JSON object with a
    ``command`` key — pull an inline ``-m "..."`` argument out of it when
    present. This mirrors the ``CLAUDE_TOOL_INPUT_FILE_PATH`` / ``TOOL_INPUT``
    reading pattern already used by ``scripts/hooks/post-edit-validate.sh``.
    In this context the commit being validated does NOT exist yet, so we
    deliberately do NOT fall back to ``git log -1`` here — that would read
    the PREVIOUS commit's message, and if that unrelated prior commit
    happened to carry an ``Eval-Artifact:`` trailer, a later version bump
    with NO real evidence could spuriously inherit it and pass the gate
    (a fail-open path in an otherwise fail-closed check). No usable trailer
    found in this context simply means "keep checking the artifact-file
    path (3a)" — returning an empty string here is the safe default.

    CI / pre-PR / range context (``TOOL_USE_EVAL_GATE_DIFF_RANGE`` set):
    falls back to the tip commit's message (``git log -1 --format=%B``)
    since the commit(s) being checked already exist by then, so ``git log``
    reads the message that actually belongs to the range under review.
    """
    tool_input_raw = os.environ.get("TOOL_INPUT", "")
    if tool_input_raw:
        try:
            payload = json.loads(tool_input_raw)
        except (json.JSONDecodeError, TypeError):
            payload = {}
        command = payload.get("command", "") if isinstance(payload, dict) else ""
        if command:
            # Handles `-m "single line"` and `-m 'single line'`. Heredoc-style
            # `-m "$(cat <<'EOF' ... EOF)"` messages are multi-line and this
            # simple pattern will not capture them faithfully — such commits
            # should rely on the artifact-FILE path (check 3a) instead, or
            # the CI/range fallback below once the commit lands.
            m = re.search(r"""-m\s+["']([^"']*)["']""", command, re.DOTALL)
            if m:
                return m.group(1)
    if os.environ.get("TOOL_USE_EVAL_GATE_DIFF_RANGE", "").strip():
        return _run_git(["log", "-1", "--format=%B"])
    return ""


def main() -> int:
    diff_text = _tool_use_diff()
    if not diff_text.strip():
        return 0  # tool_use.py untouched in this range -- gate does not apply

    _old_version, new_version = extract_version_bump(diff_text)
    if new_version is None:
        return 0  # file changed, but not the version= kwarg -- gate does not apply

    artifact = _artifact_path_for(new_version)
    if artifact.exists():
        return 0

    commit_message = _commit_message_best_effort()
    if _EVAL_ARTIFACT_TRAILER_RE.search(commit_message):
        return 0

    print(
        "\n".join(
            [
                "=" * 70,
                "BLOCKED: TOOL_USE_SYSTEM_PROMPT_TEMPLATE version bump with no live-eval artifact",
                "=" * 70,
                f"Detected version bump to {new_version!r} in {TOOL_USE_REL_PATH}.",
                "",
                "Every prior regression in this prompt file (BP-735; the `1e8744443` "
                "'reverse v1.17 hypothesis regression' precedent; the cmp_nvda_amd "
                "dropped-traverse_graph regression) was caught ONLY by a live A/B run "
                "against a real model, never by the static prompt-contract tests. "
                "REVIEW_CHECKLIST.md:117 requires evidence of that run for any version "
                "bump; this gate enforces it mechanically.",
                "",
                "Attach evidence via ONE of:",
                f"  1. Commit a machine-readable artifact at {artifact.relative_to(ROOT)}",
                "     (schema + generation steps: see this script's module docstring, "
                "or scripts/hooks/check_tool_use_prompt_eval_artifact.py).",
                "  2. Add an `Eval-Artifact: <path-or-run-id>` trailer to the commit message.",
                "",
                "If you have not yet run the live eval, see the module docstring's "
                "'HOW A FUTURE SESSION PRODUCES A REAL ARTIFACT' section for the exact "
                "harness invocation (tests/validation/chat_eval/harness.py + "
                "questions.yaml).",
            ]
        ),
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
