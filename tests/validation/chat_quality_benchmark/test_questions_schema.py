"""CI lint for the chat-quality benchmark question catalogue.

Why this file exists (PLAN-0107 follow-up, Agent D dataset audit, 2026-06-06):
- The audit found that ``tests/validation/chat_quality_benchmark/questions.yaml``
  contains ``expected_tools`` references for tools that DON'T EXIST in
  ``services/rag-chat/src/rag_chat/application/pipeline/tool_registry_builder.py``.
  Concretely: 5 distinct phantom tool names referenced across 11 question slots
  (``get_fundamentals_snapshot`` alone hit 6 questions — it was unified into
  ``query_fundamentals`` by PLAN-0104 W32 but the rubrics were never updated).
- Result: the ``tool_overlap_with_expected`` heuristic in the benchmark runner
  silently lies. A question can score "0 of 3 expected tools called" even when
  the agent did the right thing — because the rubric is asking for tools that
  cannot exist.
- This lint fails the build as soon as a question references a tool not in the
  live registry. Catches drift in BOTH directions: new questions citing dead
  tools, AND tools being renamed/removed without rubric updates.
- The lint is intentionally PURE-Python with NO imports from services/rag-chat —
  it parses the registry source file by regex so it can run in the repo-level
  test job without pulling the heavy rag-chat dependency tree.

Companion checks shipped in the same file (cheap, additive):
- Every question has a stable ``id`` field.
- Every question has a ``prompt``.
- No two questions share the exact same prompt text (de-duplication guard).
- Rubric-coverage report — fails soft (warns via a stat assertion) once the
  manual backfill is complete.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

# Repo-root anchors. ``__file__`` is .../tests/validation/chat_quality_benchmark/
_REPO_ROOT = Path(__file__).resolve().parents[3]
_QUESTIONS_DIR = _REPO_ROOT / "tests/validation/chat_quality_benchmark/questions"
_TOOL_REGISTRY_PY = _REPO_ROOT / "services/rag-chat/src/rag_chat/application/pipeline/tool_registry_builder.py"


# ── helpers ──────────────────────────────────────────────────────────────────


def _load_registered_tools() -> set[str]:
    """Parse tool_registry_builder.py and return the set of registered tool names.

    Pure-text parsing — we look for blocks starting with ``registry.register(``
    and pick the FIRST ``name="..."`` after each. That matches the top-level
    Tool spec; nested ``ParameterSpec(name="...")`` blocks are skipped by virtue
    of being further down the block (the first ``name="..."`` always wins).

    The same logic is used by Agent D's audit in their report; preserved here
    so the lint and the audit agree on the source of truth.
    """
    src = _TOOL_REGISTRY_PY.read_text()
    blocks = re.split(r"registry\.register\(", src)[1:]  # discard prelude
    registered: set[str] = set()
    for blk in blocks:
        m = re.search(r'name="([^"]+)"', blk)
        if m:
            registered.add(m.group(1))
    return registered


def _load_questions() -> list[dict[str, Any]]:
    """Load + concatenate all ``*.yaml`` files in the questions directory.

    PLAN-0107 follow-up: the catalogue was split from a single ``questions.yaml``
    into a ``questions/`` directory with per-pack files (00_real_user…,
    10_tool_coverage…, 20_chain_of_tools…, 30_safety…, etc.) so parallel
    dataset-author agents can each own their own file without merge conflicts.
    The lint MUST scan the whole directory so phantom-tool refs and ID
    collisions are caught across files.
    """
    files = sorted(_QUESTIONS_DIR.glob("*.yaml"))
    if not files:
        raise FileNotFoundError(f"No *.yaml files found in {_QUESTIONS_DIR}")
    all_qs: list[dict[str, Any]] = []
    for f in files:
        raw = yaml.safe_load(f.read_text())
        if not isinstance(raw, list):
            raise TypeError(f"Expected list at top level of {f.name}, got {type(raw).__name__}")
        all_qs.extend(raw)
    return all_qs


def _expected_tools_for(q: dict[str, Any]) -> set[str]:
    """Collect every tool name a question advertises across all rubric paths.

    Two locations exist historically:
    - top-level ``expected_tools`` (legacy heuristic schema)
    - ``rubric.expected_tools`` (v1.1+ judge schema)
    Both must agree with the live registry, so we union them.
    """
    top = set(q.get("expected_tools") or [])
    rubric = q.get("rubric") or {}
    nested = set(rubric.get("expected_tools") or []) if isinstance(rubric, dict) else set()
    return top | nested


# ── fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def registered_tools() -> set[str]:
    """Cache the registry parse — small file but called by every test."""
    tools = _load_registered_tools()
    # Sanity floor — if regex parsing breaks (e.g. file renamed / reformatted),
    # we'd silently return an empty set and every question would look phantom.
    # Bail loudly instead so the failure points at the parser, not the data.
    assert len(tools) >= 20, (
        f"Tool registry parse returned only {len(tools)} tools — parser likely broken. "
        f"Inspect {_TOOL_REGISTRY_PY.relative_to(_REPO_ROOT)} for format changes."
    )
    return tools


@pytest.fixture(scope="module")
def questions() -> list[dict[str, Any]]:
    return _load_questions()


# ── lints ────────────────────────────────────────────────────────────────────


def test_every_question_has_id_and_prompt(questions: list[dict[str, Any]]) -> None:
    """Schema floor — id + prompt are non-optional on every question."""
    bad = [(i, q) for i, q in enumerate(questions) if not q.get("id") or not q.get("prompt")]
    assert not bad, f"{len(bad)} questions missing id or prompt: {[(i, q.get('id')) for i, q in bad]}"


def test_question_ids_are_unique(questions: list[dict[str, Any]]) -> None:
    """ID collisions silently overwrite each other in run artefacts."""
    ids = [q["id"] for q in questions]
    duplicates = sorted({i for i in ids if ids.count(i) > 1})
    assert not duplicates, f"Duplicate question IDs: {duplicates}"


def test_no_duplicate_prompts(questions: list[dict[str, Any]]) -> None:
    """De-duplication guard — the audit found 4 prompt pairs duplicated across
    ``real_user`` and ``aggregate`` tags. Multi-classify a single entry via
    multiple tags instead. This test will FAIL until the 4 duplicates are merged.
    """
    seen: dict[str, list[str]] = {}
    for q in questions:
        seen.setdefault(q["prompt"], []).append(q["id"])
    duplicates = {p: ids for p, ids in seen.items() if len(ids) > 1}
    if duplicates:
        summary = "\n".join(f"  {ids} share prompt: {p[:80]!r}" for p, ids in duplicates.items())
        pytest.fail(f"Duplicate prompts found ({len(duplicates)} groups):\n{summary}")


def test_no_phantom_tool_references(questions: list[dict[str, Any]], registered_tools: set[str]) -> None:
    """THE load-bearing lint: every ``expected_tools`` entry must match a
    currently-registered tool in tool_registry_builder.py.

    When this fires, you have one of two situations:
    1. A tool was renamed/unified (e.g. PLAN-0104 W32: get_fundamentals_snapshot
       → query_fundamentals) — update the rubrics.
    2. A new question cites a tool that doesn't exist — either implement the
       tool first or pick an actual registered one.

    The error message names every phantom reference + the questions that
    propagate it, so the fix is a one-shot grep-replace.
    """
    phantoms: dict[str, list[str]] = {}
    for q in questions:
        for tool in _expected_tools_for(q):
            if tool not in registered_tools:
                phantoms.setdefault(tool, []).append(q["id"])
    if phantoms:
        lines = ["Phantom tool references — these tools are not registered in"]
        lines.append(f"  {_TOOL_REGISTRY_PY.relative_to(_REPO_ROOT)}:")
        for tool, qids in sorted(phantoms.items()):
            lines.append(f"  - {tool!r} referenced by {qids}")
        lines.append("")
        lines.append(f"  Live registry has {len(registered_tools)} tools: {sorted(registered_tools)}")
        pytest.fail("\n".join(lines))


def test_rubric_coverage_meets_minimum(questions: list[dict[str, Any]]) -> None:
    """Soft floor on rubric-block coverage.

    The PLAN-0107 W23 + v2.0 LLM judge needs a ``rubric`` block to do its job;
    questions without one fall back to a degraded generic prompt. The audit
    found 21% coverage (6/28). This test asserts a FLOOR that bumps upward
    as the dataset is backfilled — starts at 20% today (anything above is OK),
    raise to 50% after the first backfill pass, then 90% per Agent D's roadmap.

    Failing this asks you to either author rubric blocks for new questions
    OR raise the floor in this file after a planned backfill.
    """
    n_with_rubric = sum(1 for q in questions if isinstance(q.get("rubric"), dict))
    coverage = n_with_rubric / len(questions)
    # Current state: 6/28 = 0.214. Floor at 0.20 keeps the audit honest without
    # requiring same-day backfill. Bump this constant as you backfill.
    MIN_RUBRIC_COVERAGE = 0.20
    assert coverage >= MIN_RUBRIC_COVERAGE, (
        f"Rubric block coverage dropped to {coverage:.0%} ({n_with_rubric}/{len(questions)}); "
        f"floor is {MIN_RUBRIC_COVERAGE:.0%}. Either add rubric blocks to new questions "
        f"or lower the floor in this file."
    )
