"""TASK-W3-01 — Migration file naming + revision-chain convention.

Every file in ``services/intelligence-migrations/alembic/versions/`` must:
  1. Match the ``NNNN_<short_description>.py`` pattern (4-digit prefix).
  2. Have a unique numeric prefix.
  3. Declare ``revision = "NNNN"`` exactly equal to its filename prefix.
  4. Declare a ``down_revision`` that points to an existing migration (or
     to ``None`` for the first migration).
  5. Form a contiguous chain (exactly one head, no orphans, no cycles).

NOTE on the gap between 0013 and 0018: that gap is intentional (revisions
0014-0017 were renumbered/abandoned during PRD-0018 development). The chain
itself remains contiguous via ``down_revision`` pointers; only the file-name
numeric prefixes have a gap. This test enforces a valid alembic revision
graph rather than dense filename prefixes.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

# Locate this service's versions/ directory relative to the test file.
# tests/integration/test_migration_naming.py → tests/integration → tests
#   → services/intelligence-migrations → alembic/versions
VERSIONS_DIR = Path(__file__).resolve().parents[2] / "alembic" / "versions"

FILENAME_RE = re.compile(r"^(\d{4})_[a-z0-9][a-z0-9_]*\.py$")


def _iter_files() -> list[Path]:
    """Sorted list of migration files (excluding __init__ / __pycache__)."""
    return sorted(p for p in VERSIONS_DIR.glob("*.py") if not p.name.startswith("_"))


def _parse_revision(file: Path) -> tuple[str | None, str | None]:
    """Return (revision, down_revision) parsed from the file body.

    Alembic migrations declare these as module-level ``revision`` and
    ``down_revision`` assignments. We grep for both — they may be typed
    (``revision: str = "0001"``) or untyped (``revision = '0001'``).
    """
    text = file.read_text(encoding="utf-8")
    rev_match = re.search(r"^\s*revision(?:\s*:\s*\w+)?\s*=\s*['\"]([^'\"]+)['\"]", text, re.MULTILINE)
    down_match = re.search(
        r"^\s*down_revision(?:\s*:\s*[\w\[\]| ]+)?\s*=\s*(['\"]([^'\"]+)['\"]|None)",
        text,
        re.MULTILINE,
    )
    revision = rev_match.group(1) if rev_match else None
    down_revision: str | None
    if not down_match:
        down_revision = None
    elif down_match.group(1) == "None":
        down_revision = None
    else:
        down_revision = down_match.group(2)
    return revision, down_revision


# ── Filename pattern ────────────────────────────────────────────────────────


def test_versions_directory_exists() -> None:
    """Sanity check: the alembic/versions/ dir is where we expect it."""
    assert VERSIONS_DIR.is_dir(), f"missing versions dir at {VERSIONS_DIR}"


def test_every_migration_filename_matches_pattern() -> None:
    """Every file must match ``NNNN_short_description.py``."""
    bad_names = [f.name for f in _iter_files() if not FILENAME_RE.match(f.name)]
    assert not bad_names, f"Migration filenames violate NNNN_*.py pattern: {bad_names}"


def test_filename_prefixes_are_unique() -> None:
    """No two migrations may share the same 4-digit prefix."""
    prefixes: dict[str, list[str]] = {}
    for f in _iter_files():
        match = FILENAME_RE.match(f.name)
        if match is None:
            continue
        prefixes.setdefault(match.group(1), []).append(f.name)
    duplicates = {k: v for k, v in prefixes.items() if len(v) > 1}
    assert not duplicates, f"Duplicate migration prefixes: {duplicates}"


# ── Revision identifier consistency ─────────────────────────────────────────


# Legacy hex revision IDs predate the NNNN-prefix convention. Migrations
# 0001-0004 were authored with random 12-char hex IDs (a1b2c3d4e5f6 style)
# and the chain still links via those IDs. Renaming them would require a
# coordinated schema-stamp rewrite on every live DB, so they are grand-
# fathered in. New migrations (0005+) MUST use the NNNN form.
_LEGACY_HEX_REVISION_FILES: frozenset[str] = frozenset(
    {
        "0001_create_intelligence_db.py",
        "0002_enhance_events_and_relations.py",
        "0003_cleanup_non_company_fundamentals_ohlcv.py",
        "0004_geopolitical_age_temporal_events.py",
    }
)


def test_revision_identifier_matches_filename_prefix() -> None:
    """The ``revision`` declared inside each file must equal the filename prefix.

    Drift between filename and the alembic revision ID is the most common
    source of "downgrade goes to the wrong target" bugs. Files in
    ``_LEGACY_HEX_REVISION_FILES`` are exempt because they predate the
    NNNN-prefix convention and renaming would require re-stamping every
    live database.
    """
    mismatches: list[tuple[str, str | None, str]] = []  # (file, declared_revision, expected)
    for f in _iter_files():
        if f.name in _LEGACY_HEX_REVISION_FILES:
            continue
        match = FILENAME_RE.match(f.name)
        if match is None:
            continue
        expected = match.group(1)
        declared, _ = _parse_revision(f)
        if declared != expected:
            mismatches.append((f.name, declared, expected))
    assert not mismatches, f"revision ID mismatches (post-legacy): {mismatches}"


def test_legacy_hex_revisions_still_form_valid_chain_links() -> None:
    """The 4 legacy-hex migrations must still be reachable from the head and
    their ``revision`` declarations must be non-empty 12-char hex strings.
    """
    hex_re = re.compile(r"^[0-9a-f]{6,16}$")
    for f in _iter_files():
        if f.name not in _LEGACY_HEX_REVISION_FILES:
            continue
        declared, _ = _parse_revision(f)
        assert declared is not None, f"legacy {f.name} has no revision identifier"
        assert hex_re.match(declared), f"legacy {f.name} revision {declared!r} is not the expected hex form"


# ── Revision graph integrity ────────────────────────────────────────────────


def test_revision_chain_is_valid_alembic_graph() -> None:
    """The set of (revision, down_revision) pairs must form a valid alembic graph.

    Concretely:
      - Every down_revision (other than None) must point to an existing
        revision.
      - There is exactly one head (a revision that no other revision points
        back to).
      - There is exactly one root (a revision whose down_revision is None).
      - The graph is a tree, not a DAG (we don't currently use branches).
    """
    revisions: dict[str, str | None] = {}  # revision -> down_revision
    for f in _iter_files():
        rev, down = _parse_revision(f)
        assert rev is not None, f"{f.name} has no parsed revision identifier"
        revisions[rev] = down

    # Every down_revision must exist (or be None).
    dangling = [(rev, down) for rev, down in revisions.items() if down is not None and down not in revisions]
    assert not dangling, f"down_revision points to non-existent migration: {dangling}"

    # Exactly one root.
    roots = [rev for rev, down in revisions.items() if down is None]
    assert len(roots) == 1, f"Expected exactly 1 root migration (down_revision=None), found {roots}"

    # Exactly one head: a revision that no other revision points back to.
    pointed_to = {down for down in revisions.values() if down is not None}
    heads = [rev for rev in revisions if rev not in pointed_to]
    assert len(heads) == 1, f"Expected exactly 1 head migration, found {heads}"


def test_revision_chain_reaches_every_migration_from_head() -> None:
    """Walking down_revision from the head must visit every migration exactly
    once. This guarantees there is no orphaned branch sitting unreachable in
    the versions directory.
    """
    revisions: dict[str, str | None] = {}
    for f in _iter_files():
        rev, down = _parse_revision(f)
        if rev is not None:
            revisions[rev] = down

    # Find head.
    pointed_to = {down for down in revisions.values() if down is not None}
    heads = [rev for rev in revisions if rev not in pointed_to]
    assert len(heads) == 1, f"head detection failed: {heads}"
    head = heads[0]

    # Walk back to root.
    visited: list[str] = []
    cursor: str | None = head
    while cursor is not None:
        if cursor in visited:
            pytest.fail(f"Cycle detected in revision chain at {cursor}: {visited}")
        visited.append(cursor)
        cursor = revisions.get(cursor)

    # Visited set must equal full revision set.
    missing = set(revisions) - set(visited)
    assert not missing, f"Migrations not reachable from head {head}: {missing}"
