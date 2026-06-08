"""Lint tests for the chat-quality benchmark question catalogue (PLAN-0099-W4).

The catalogue (`questions.yaml`) is the single source of truth for the
chat-quality benchmark. v2 of the schema (2026-06-08) finalised three
invariants we enforce here:

1. Every question MUST have a ``rubric:`` block — the v2.0 LLM judge reads
   ONLY this block, so a missing rubric means the question is silently
   ungradeable.
2. Legacy top-level heuristic fields (`expected_entities_mentioned`,
   `expected_numeric_class`, `expected_min_words`, `must_not_say`) MUST
   NOT appear at top level any more — they were the source of false
   WARNs and the v2.0 judge ignored them. Adding them back would
   silently corrupt the benchmark.
3. If a ``budgets:`` block exists, it must use only known keys — at
   present `max_latency_s` is the only valid key. Anything else is a
   typo / silent ignore.

These are FAST yaml-only checks, no network, no LLM — they run in pytest's
unit lane.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

# Resolve the path even when pytest is invoked from a different CWD —
# the file lives next to this test module.
_HERE = Path(__file__).resolve().parent
_QUESTIONS_PATH = _HERE / "questions.yaml"

# Pull the deprecated-fields tuple from the migration script so the lint
# and the migrator stay in lockstep. We add scripts/ to sys.path the same
# way scripts/tests/ does — there is no package init there.
_SCRIPTS_DIR = (_HERE / ".." / ".." / ".." / "scripts").resolve()
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from migrate_questions_v2 import (  # — sys.path mutation must precede import
    KNOWN_BUDGET_KEYS,
    LEGACY_TOP_LEVEL_FIELDS,
)

# 100 % rubric coverage is the post-W4 invariant. Anything below 1.0 means
# someone re-added a rubric-less question and the judge is silently
# ungradeable for it.
MIN_RUBRIC_COVERAGE = 1.0

pytestmark = pytest.mark.unit


def _load_questions() -> list[dict[str, Any]]:
    """Decode the YAML catalogue once; helper avoids duplicate parsing."""
    raw = yaml.safe_load(_QUESTIONS_PATH.read_text())
    assert isinstance(raw, list), f"Expected top-level list in {_QUESTIONS_PATH}"
    return [q for q in raw if isinstance(q, dict)]


def test_rubric_coverage_is_one_hundred_percent() -> None:
    """Every question must have a ``rubric:`` dict — the judge contract."""
    questions = _load_questions()
    with_rubric = [q for q in questions if isinstance(q.get("rubric"), dict)]
    coverage = len(with_rubric) / max(len(questions), 1)
    missing = [q.get("id") for q in questions if not isinstance(q.get("rubric"), dict)]
    assert coverage >= MIN_RUBRIC_COVERAGE, (
        f"Rubric coverage {coverage:.2%} below floor {MIN_RUBRIC_COVERAGE:.0%}. "
        f"Questions missing a rubric: {missing}"
    )


def test_no_legacy_top_level_expected_fields() -> None:
    """Deprecated top-level heuristic fields MUST NOT reappear.

    These were removed in the v2 migration; if someone re-adds one, the
    runner silently re-acquires the false-WARN behaviour the migration
    eliminated. This gate fails loudly so the regression is caught at PR.
    """
    questions = _load_questions()
    offenders: dict[str, list[str]] = {}
    for q in questions:
        bad = [f for f in LEGACY_TOP_LEVEL_FIELDS if f in q]
        if bad:
            offenders[str(q.get("id"))] = bad
    assert not offenders, (
        f"Deprecated top-level fields reintroduced: {offenders}. "
        f"These fields are ignored by the v2.0 judge and were the source "
        f"of false WARNs (BP from PLAN-0099-W4). Move important checks "
        f"into rubric.required_facts / rubric.forbidden_facts instead."
    )


def test_budgets_block_optional_but_well_formed() -> None:
    """If ``budgets:`` exists it must have only known keys (`max_latency_s`)."""
    questions = _load_questions()
    known = set(KNOWN_BUDGET_KEYS)
    bad: dict[str, list[str]] = {}
    for q in questions:
        b = q.get("budgets")
        if b is None:
            continue
        assert isinstance(b, dict), f"{q.get('id')}: budgets must be a dict, got {type(b).__name__}"
        unknown = [k for k in b if k not in known]
        if unknown:
            bad[str(q.get("id"))] = unknown
    assert not bad, f"Unknown keys in budgets blocks (allowed: {sorted(known)}): {bad}"


def test_rubric_required_keys_present() -> None:
    """Each rubric MUST declare the keys the judge reads unconditionally.

    Defaults exist in code (Rubric.from_question), but a missing key in
    YAML is almost always a typo — fail loudly rather than silently
    grading with a wrong default.
    """
    required_keys = (
        "expected_tools",
        "required_facts",
        "forbidden_facts",
        "expected_depth",
        "appropriate_refusal_ok",
    )
    questions = _load_questions()
    offenders: dict[str, list[str]] = {}
    for q in questions:
        rubric = q.get("rubric") or {}
        if not isinstance(rubric, dict):
            continue
        missing = [k for k in required_keys if k not in rubric]
        if missing:
            offenders[str(q.get("id"))] = missing
    assert not offenders, f"Rubrics missing required keys: {offenders}"


def test_expected_depth_uses_canonical_values() -> None:
    """rubric.expected_depth ∈ {shallow, medium, deep} — typos break grading."""
    allowed = {"shallow", "medium", "deep"}
    questions = _load_questions()
    bad: dict[str, str] = {}
    for q in questions:
        rubric = q.get("rubric") or {}
        if not isinstance(rubric, dict):
            continue
        depth = rubric.get("expected_depth")
        if depth is not None and depth not in allowed:
            bad[str(q.get("id"))] = str(depth)
    assert not bad, f"expected_depth must be one of {sorted(allowed)}; offenders: {bad}"
