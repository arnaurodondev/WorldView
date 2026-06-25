#!/usr/bin/env python3
"""One-shot migration: questions.yaml legacy schema → canonical v2 schema.

Why this script exists
----------------------
Before PLAN-0099-W4 the chat-quality benchmark catalogue mixed two
incompatible shapes:

* Legacy top-level fields (used by the runner's heuristic gates):
  ``expected_tools``, ``expected_entities_mentioned``,
  ``expected_numeric_class``, ``expected_min_words``,
  ``expected_max_latency_s``, ``must_not_say``.
* A partial ``rubric:`` block (only ~25% coverage) — the ONLY thing the
  v2.0 LLM judge actually reads.

The legacy fields silently produced false WARNs (e.g. "missing entity
NVDA" when the answer correctly named NVIDIA) and the judge ignored them
anyway. This script collapses both shapes into one canonical schema:

  - rubric: { expected_tools, required_facts, forbidden_facts,
              expected_depth, appropriate_refusal_ok, ... }      ← judge contract
  - budgets: { max_latency_s }                                   ← advisory only
  - id / prompt / category / tags / notes                        ← metadata

Migration rules (verbatim, in order):
  1. expected_tools (top)       → rubric.expected_tools (merge+dedup, preserve order)
  2. expected_max_latency_s     → budgets.max_latency_s
  3. expected_entities_mentioned, expected_numeric_class,
     expected_min_words, must_not_say → DELETED
  4. If no rubric: block, create one with sensible defaults
     (expected_depth=medium, appropriate_refusal_ok=false,
     required_facts=[], forbidden_facts=[]).

The script is idempotent: running it twice on an already-migrated file
is a no-op (no legacy fields remain to migrate; rubric stays as-is).

Usage
-----
    .venv312/bin/python scripts/migrate_questions_v2.py
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import yaml

_REPO_ROOT = Path(__file__).resolve().parent.parent
_QUESTIONS_DIR = _REPO_ROOT / "tests" / "validation" / "chat_quality_benchmark"

# The legacy top-level fields we strip / migrate. Kept as a tuple so the
# lint test in tests/validation/chat_quality_benchmark/ can import + reuse
# the same list (single source of truth for "what's deprecated").
LEGACY_TOP_LEVEL_FIELDS: tuple[str, ...] = (
    "expected_entities_mentioned",
    "expected_numeric_class",
    "expected_min_words",
    "must_not_say",
)

# Known keys allowed in the new ``budgets:`` block — anything else is a lint
# error. The schema test imports this so changes here propagate to the gate.
KNOWN_BUDGET_KEYS: tuple[str, ...] = ("max_latency_s",)


def _dedup_preserve_order(items: list[Any]) -> list[Any]:
    """Deduplicate while keeping the FIRST occurrence of each value."""
    seen: set[Any] = set()
    out: list[Any] = []
    for item in items:
        # We need a hashable key; for list/dict we'd skip but expected_tools
        # is always a list of strings, so this is fine.
        key = item if isinstance(item, str | int | float | bool | tuple) else repr(item)
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def migrate_question(q: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Migrate one question entry. Returns (new_dict, notes_about_changes).

    ``notes`` is a list of human-readable bullet points describing what
    happened — used for the run summary.
    """
    notes: list[str] = []
    q_id = str(q.get("id") or "<unknown>")
    out: dict[str, Any] = {}

    # 1) Carry through the immutable metadata keys in a stable order.
    for k in ("id", "prompt", "category", "tags"):
        if k in q:
            out[k] = q[k]

    # 2) Build / extend the rubric block. Legacy expected_tools at top level
    # merges into rubric.expected_tools (preserving order, deduping).
    raw_rubric = q.get("rubric") if isinstance(q.get("rubric"), dict) else None
    rubric: dict[str, Any] = dict(raw_rubric) if raw_rubric else {}
    had_rubric_block = raw_rubric is not None

    legacy_tools = q.get("expected_tools")
    if isinstance(legacy_tools, list) and legacy_tools:
        existing = list(rubric.get("expected_tools") or [])
        merged = _dedup_preserve_order(legacy_tools + existing)
        rubric["expected_tools"] = merged
        if not had_rubric_block:
            notes.append(f"{q_id}: created rubric from top-level expected_tools={legacy_tools}")
        elif merged != existing:
            notes.append(f"{q_id}: merged top-level expected_tools into rubric.expected_tools")

    # 3) Apply defaults for required keys in the canonical rubric. We don't
    # invent required_facts / forbidden_facts content — that's a human-
    # author task. We DO default the booleans/strings the judge always reads.
    rubric.setdefault("expected_tools", [])
    rubric.setdefault("required_facts", [])
    rubric.setdefault("forbidden_facts", [])
    rubric.setdefault("expected_depth", "medium")
    rubric.setdefault("appropriate_refusal_ok", False)

    # 4) Carry-through any optional rubric extensions that the question
    # already declared (must_not_call, entity_aliases, etc.) — we don't
    # invent these but we preserve them verbatim if present.
    out["rubric"] = rubric

    # 5) Build the budgets block from the legacy field.
    budgets: dict[str, Any] = {}
    if "expected_max_latency_s" in q:
        v = q["expected_max_latency_s"]
        # Latency budget is integer seconds; coerce float→int for cleanliness.
        try:
            budgets["max_latency_s"] = int(v)
        except (TypeError, ValueError):
            budgets["max_latency_s"] = v
    if budgets:
        out["budgets"] = budgets

    # 6) Carry through notes (free-text human guidance) last so it renders
    # near the bottom of each YAML entry (readable for humans).
    if "notes" in q:
        out["notes"] = q["notes"]

    # 7) Track what was dropped — purely for the run summary, not for the
    # output YAML.
    dropped: list[str] = []
    for k in LEGACY_TOP_LEVEL_FIELDS:
        if k in q:
            dropped.append(k)
    if "expected_tools" in q:
        dropped.append("expected_tools (→ rubric.expected_tools)")
    if "expected_max_latency_s" in q:
        dropped.append("expected_max_latency_s (→ budgets.max_latency_s)")
    if dropped:
        notes.append(f"{q_id}: stripped legacy fields {dropped}")

    # 8) Flag missing human-authored required_facts so the operator knows
    # which questions still need follow-up content authoring.
    if not rubric["required_facts"]:
        notes.append(f"{q_id}: NEEDS HUMAN AUTHORING — required_facts is empty")

    return out, notes


class _BlockListDumper(yaml.SafeDumper):
    """YAML dumper that emits short lists inline ``[a, b]`` and long lists block.

    This keeps the file readable: ``tags: [aggregate, smoke]`` stays on one
    line while ``required_facts:`` with multiple multi-word entries goes
    block-style.
    """


def _represent_list_smart(dumper: yaml.SafeDumper, data: list[Any]) -> yaml.Node:
    # Heuristic: short scalar lists go flow-style; everything else block-style.
    is_short_scalars = all(isinstance(x, str | int | float | bool) for x in data) and len(data) <= 6
    flow = is_short_scalars
    return dumper.represent_sequence("tag:yaml.org,2002:seq", data, flow_style=flow)


_BlockListDumper.add_representer(list, _represent_list_smart)


def _dump_questions(questions: list[dict[str, Any]]) -> str:
    """Serialise the migrated list of questions back to YAML.

    We dump entry-by-entry so each question is separated by a blank line —
    matches the existing hand-authored layout of the source file.
    """
    chunks: list[str] = []
    for q in questions:
        # ``dump`` a list-of-one so the leading ``- `` dash is emitted.
        chunk = yaml.dump(
            [q],
            Dumper=_BlockListDumper,
            sort_keys=False,
            default_flow_style=False,
            allow_unicode=True,
            width=100,
        )
        chunks.append(chunk.rstrip() + "\n")
    return "\n".join(chunks)


def _split_header_and_body(text: str) -> tuple[str, str]:
    """Split the file into (header_comments, body) at the first ``- id:`` line.

    We preserve all leading comments (the file's hand-authored schema doc),
    then rewrite everything from the first list-item onward.
    """
    lines = text.splitlines(keepends=True)
    for i, line in enumerate(lines):
        if line.lstrip().startswith("- id:"):
            return "".join(lines[:i]), "".join(lines[i:])
    return text, ""


def migrate_file(path: Path) -> dict[str, Any]:
    """Migrate a single questions.yaml file in-place. Returns a summary dict."""
    text = path.read_text()
    header, _body = _split_header_and_body(text)

    raw = yaml.safe_load(text)
    if not isinstance(raw, list):
        raise ValueError(f"Expected top-level list in {path}, got {type(raw).__name__}")

    migrated: list[dict[str, Any]] = []
    all_notes: list[str] = []
    needs_authoring: list[str] = []
    new_rubric_count = 0

    for q in raw:
        if not isinstance(q, dict):
            continue
        had_rubric = isinstance(q.get("rubric"), dict)
        new_q, notes = migrate_question(q)
        migrated.append(new_q)
        all_notes.extend(notes)
        if not had_rubric:
            new_rubric_count += 1
        if not new_q["rubric"]["required_facts"]:
            needs_authoring.append(str(new_q.get("id") or "<unknown>"))

    # Rewrite the file: preserved header + freshly-dumped body.
    new_body = _dump_questions(migrated)
    # Replace the deprecation-doc header section about legacy schema with a
    # short pointer note. We do this surgically: if the header still mentions
    # legacy fields, prepend a one-line v2 banner so future readers know the
    # schema changed. Idempotent — only added once.
    v2_banner = "# Schema v2 (PLAN-0099-W4): rubric{} is the judge contract; budgets{} is advisory.\n"
    if v2_banner not in header:
        header = v2_banner + header

    path.write_text(header.rstrip() + "\n\n" + new_body)

    return {
        "path": str(path),
        "total": len(migrated),
        "new_rubric_blocks": new_rubric_count,
        "needs_authoring": needs_authoring,
        "notes": all_notes,
    }


def main() -> int:
    files = sorted(_QUESTIONS_DIR.glob("questions*.yaml"))
    # Also tolerate a future questions/*.yaml subdirectory layout.
    sub_dir = _QUESTIONS_DIR / "questions"
    if sub_dir.is_dir():
        files.extend(sorted(sub_dir.glob("*.yaml")))

    if not files:
        print(f"ERROR: no questions yaml found under {_QUESTIONS_DIR}", file=sys.stderr)
        return 2

    grand_total = 0
    grand_new_rubric = 0
    grand_needs_authoring: list[str] = []

    for f in files:
        summary = migrate_file(f)
        grand_total += summary["total"]
        grand_new_rubric += summary["new_rubric_blocks"]
        grand_needs_authoring.extend(summary["needs_authoring"])
        print(f"\n=== {f.relative_to(_REPO_ROOT)} ===")
        print(f"  questions migrated      : {summary['total']}")
        print(f"  new rubric blocks added : {summary['new_rubric_blocks']}")
        if summary["needs_authoring"]:
            print(f"  needs human authoring   : {len(summary['needs_authoring'])}")
            for q_id in summary["needs_authoring"]:
                print(f"    - {q_id}")

    print("\n=== TOTAL ===")
    print(f"  questions          : {grand_total}")
    print(f"  new rubric blocks  : {grand_new_rubric}")
    print(f"  needs authoring    : {len(grand_needs_authoring)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
