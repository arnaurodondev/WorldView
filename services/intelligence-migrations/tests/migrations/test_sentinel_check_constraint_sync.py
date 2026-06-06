"""Regression: 0045 CHECK constraint UUIDs MUST match 0044 _SENTINELS.

PLAN-0093 Phase 5 (QA-4 A.4.2).

WHY THIS TEST EXISTS
--------------------
``0044_seed_kg_system_entities.py`` declares a Python list ``_SENTINELS``
containing the five system-sentinel ``(entity_id, name, type)`` tuples that
are INSERTed into ``canonical_entities``.

``0045_add_relations_fk_constraints.py`` adds a CHECK constraint
``chk_relations_no_self_loop`` that allows self-loops only on those five
sentinel UUIDs.  Because Postgres CHECK constraints cannot reference a
sub-query, the UUIDs are hard-coded as SQL literals inside the CHECK body.

These two lists MUST stay in sync — if a sentinel is added/removed/renumbered
in 0044 without updating 0045, the new sentinel will fail the CHECK (or a
removed sentinel will create a leaky carve-out).  This test re-parses both
migration files and asserts set-equality of the UUIDs.

It is intentionally a pure text test — no DB required, no alembic runtime
required, no SQLAlchemy required.  Runs in milliseconds on every CI shard.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest

# ── Locate the migrations directory once ─────────────────────────────────────
_VERSIONS_DIR = Path(__file__).resolve().parents[2] / "alembic" / "versions"


def _load_sentinels_module() -> object:
    """Dynamically import ``0044_seed_kg_system_entities`` as a Python module.

    ``alembic/versions/`` is not a Python package, so we use ``importlib.util``
    to load the file by absolute path.  Returns the loaded module so the test
    can read its ``_SENTINELS`` attribute.
    """
    target = _VERSIONS_DIR / "0044_seed_kg_system_entities.py"
    assert target.exists(), f"missing migration file: {target}"
    spec = importlib.util.spec_from_file_location("_m0044", target)
    assert spec is not None, "spec_from_file_location returned None"
    assert spec.loader is not None, "module spec has no loader"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _read_check_uuids() -> set[str]:
    """Extract the five UUID literals from 0045's ``chk_relations_no_self_loop``.

    Strategy:
      1. Read ``0045_add_relations_fk_constraints.py`` as plain text.
      2. Slice out the SQL fragment between
         ``ADD CONSTRAINT chk_relations_no_self_loop`` and the closing
         ``)`` of the ``IN (...)`` list.
      3. Regex-extract every UUID-shaped substring inside that slice.
      4. Return as a set so the assertion is order-independent.
    """
    target = _VERSIONS_DIR / "0045_add_relations_fk_constraints.py"
    assert target.exists(), f"missing migration file: {target}"
    text = target.read_text(encoding="utf-8")

    # Narrow to the CHECK constraint body — the file also imports sentinel
    # UUIDs *nowhere*, but constraining the slice prevents any future drift
    # from leaking unrelated UUIDs into the match set.
    start = text.find("ADD CONSTRAINT chk_relations_no_self_loop")
    assert start != -1, "chk_relations_no_self_loop constraint not found in 0045"
    # Find the closing ``)`` of the ``IN (`` list — first ``)`` that follows
    # an ``::uuid`` token in the slice.
    slice_after_start = text[start:]
    in_paren_end = slice_after_start.find(")\n            )")
    assert in_paren_end != -1, "could not locate end of IN (...) list in 0045"
    check_body = slice_after_start[: in_paren_end + 1]

    # Standard UUID v4/v7 textual shape.  We pin to lower-case hex because the
    # current literals use lower-case; if that ever flips, normalize via
    # ``.lower()`` on both sides.
    uuid_re = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
    found = set(uuid_re.findall(check_body))
    assert len(found) >= 1, f"no UUIDs found inside CHECK body: {check_body!r}"
    return found


@pytest.mark.unit
def test_sentinel_check_constraint_matches_seed() -> None:
    """The CHECK literal set MUST equal the _SENTINELS entity_id set."""
    module = _load_sentinels_module()
    sentinels: list[tuple[str, str, str]] = module._SENTINELS  # type: ignore[attr-defined]
    seed_uuids = {entity_id for entity_id, _, _ in sentinels}
    check_uuids = _read_check_uuids()

    # The assertion message reports both directions so a divergence is
    # immediately actionable: "in seed but not CHECK" → forgot to add to
    # CHECK; "in CHECK but not seed" → forgot to remove from CHECK.
    missing_from_check = seed_uuids - check_uuids
    missing_from_seed = check_uuids - seed_uuids
    assert seed_uuids == check_uuids, (
        f"0044 _SENTINELS and 0045 CHECK constraint diverged.\n"
        f"  in seed but missing from CHECK: {sorted(missing_from_check)}\n"
        f"  in CHECK but missing from seed: {sorted(missing_from_seed)}\n"
        f"  Update both files together (see comment block in 0045)."
    )


@pytest.mark.unit
def test_sentinels_count_is_five() -> None:
    """Defensive: pin the sentinel count so silent additions trigger review.

    If a future migration adds or removes a sentinel, this test forces the
    author to update the literal here too — surfacing the change in code
    review rather than letting it sneak in via an upstream constant edit.
    """
    module = _load_sentinels_module()
    sentinels: list[tuple[str, str, str]] = module._SENTINELS  # type: ignore[attr-defined]
    assert len(sentinels) == 5, (
        f"PLAN-0093 shipped with exactly 5 system sentinels; saw {len(sentinels)}. "
        "If this change is intentional, update both 0045's CHECK literal and "
        "this test in the same commit."
    )
