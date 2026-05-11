"""Source-level tests for ``scripts/seed_demo_data.py``.

PLAN-0057 Wave C-5 / T-C-5-02: when the seeder inserts canonical_entities for
INSTRUMENTS or KG_EXTRA_ENTITIES, it must also insert an EXACT self-alias row
for each canonical_name so Stage-1 alias-exact resolution can match the
canonical against its own name.

These tests are pure source-text checks (regex over the file) — they do NOT
spin up a database. The alternative (full psycopg2 integration) is covered by
the live-bring-up smoke pipeline; the value here is fast, hermetic
regression coverage that prevents the self-alias inserts from being
accidentally removed in a future refactor.
"""

from __future__ import annotations

import os
import re

import pytest

pytestmark = pytest.mark.unit

_SEEDER_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "seed_demo_data.py"),
)


def _read_seeder() -> str:
    with open(_SEEDER_PATH, encoding="utf-8") as f:
        return f.read()


def test_seeder_file_exists() -> None:
    """Sanity check — the seeder lives where we think it does."""
    assert os.path.isfile(_SEEDER_PATH), f"Missing seeder file at {_SEEDER_PATH}"


def test_instruments_block_inserts_exact_self_alias() -> None:
    """The INSTRUMENTS loop must contain an entity_aliases INSERT with
    alias_type 'EXACT', source 'seed_demo_self', and the canonical name as
    alias_text — same transaction as the canonical INSERT.
    """
    src = _read_seeder()

    # Locate the "Seeding canonical_entities (financial instruments)" section
    # and ensure the alias INSERT appears within ~100 lines.
    section_match = re.search(
        r"Seeding canonical_entities \(financial instruments\).*?# .. 2\.",
        src,
        re.DOTALL,
    )
    assert section_match, "Could not locate INSTRUMENTS canonical block"
    section = section_match.group(0)

    assert "INSERT INTO entity_aliases" in section, "INSTRUMENTS block missing entity_aliases INSERT"
    assert "'EXACT'" in section, "INSTRUMENTS alias INSERT must use alias_type 'EXACT'"
    assert "'seed_demo_self'" in section, "INSTRUMENTS alias INSERT must use source 'seed_demo_self'"
    assert 'inst["name"]' in section, "INSTRUMENTS alias INSERT must use canonical name as alias_text"
    assert ".lower().strip()" in section, "INSTRUMENTS alias INSERT must normalize via lower().strip()"
    # Idempotency must reference the partial UNIQUE index from migration 0008
    assert "ON CONFLICT (entity_id, normalized_alias_text, alias_type)" in section
    assert "WHERE is_active = true" in section


def test_kg_extra_entities_block_inserts_exact_self_alias() -> None:
    """The KG_EXTRA_ENTITIES loop must also insert an EXACT self-alias for
    each theme/industry canonical.
    """
    src = _read_seeder()

    section_match = re.search(
        r"Seeding KG theme entities.*?conn_intel\.commit\(\)",
        src,
        re.DOTALL,
    )
    assert section_match, "Could not locate KG_EXTRA_ENTITIES block"
    section = section_match.group(0)

    assert "INSERT INTO entity_aliases" in section, "KG_EXTRA_ENTITIES block missing entity_aliases INSERT"
    assert "'EXACT'" in section, "KG_EXTRA_ENTITIES alias INSERT must use alias_type 'EXACT'"
    assert "'seed_demo_self'" in section, "KG_EXTRA_ENTITIES alias INSERT must use source 'seed_demo_self'"
    assert 'ent["canonical_name"]' in section
    assert ".lower().strip()" in section


def test_self_alias_inserts_appear_before_ticker_alias_loop() -> None:
    """Sanity ordering check: the self-alias INSERTs live INSIDE the canonical
    loops (sections 1+2), not in the ticker-alias section (section 3). This
    guards against a future refactor that pushes the self-alias into the
    wrong section and accidentally limits it to the financial-instrument
    type only.
    """
    src = _read_seeder()
    # Find the position of section 3 (ticker-aliases) — the self-alias INSERTs
    # must all appear before it.
    s3_pos = src.find("Seeding entity_aliases")
    assert s3_pos > 0, "Could not locate section 3 (ticker aliases)"

    # Both self-alias INSERTs use the marker source 'seed_demo_self'
    self_alias_positions = [m.start() for m in re.finditer(r"'seed_demo_self'", src)]
    assert (
        len(self_alias_positions) >= 2
    ), f"Expected ≥2 'seed_demo_self' occurrences (INSTRUMENTS + KG_EXTRA_ENTITIES), found {len(self_alias_positions)}"
    for pos in self_alias_positions:
        assert pos < s3_pos, (
            f"'seed_demo_self' INSERT at offset {pos} appears AFTER section 3 (offset {s3_pos}) — "
            "must live inside the canonical loops"
        )
