"""Unit tests for the F-1 SQL extractor + PREPARE-pass translator.

FIX-LIVE-F (INV-LIVE-B Part 1 + Part 3):
  * Patch 1 — ``_translate_named_to_positional`` rewrites SQLAlchemy
    ``:name`` placeholders into Postgres ``$N`` so PREPARE doesn't emit
    "syntax error at or near ':'" noise.
  * Patch 2 — extractor folds module-level ``NAME + Constant`` chains so
    fragment literals are not PREPARE'd in isolation (which fails because
    a CTE-only fragment cannot stand on its own).

These tests are pure-Python — no database required.
"""

from __future__ import annotations

from pathlib import Path

# Extractor lives in repository_sql_extractor.py.
from tests.architecture.repository_sql_extractor import extract_sql_from_file

# Translator lives in the live-PREPARE harness module.
from tests.architecture.test_repository_sql_prepare import _translate_named_to_positional

# ---------------------------------------------------------------------------
# Patch 1 — :name → $N translator
# ---------------------------------------------------------------------------


def test_translate_named_to_positional_basic() -> None:
    """Repeated names re-use the same ``$N`` slot; ``::TYPE`` is left alone."""
    out = _translate_named_to_positional(":x + :y + :x::text")
    # ``:x`` and ``:y`` get $1 and $2; the second ``:x`` re-uses $1.
    # ``::text`` is a Postgres type cast and must NOT be touched.
    assert out == "$1 + $2 + $1::text", out


def test_translate_named_to_positional_skips_strings() -> None:
    """A ``:status`` *inside* single quotes is a string literal, not a param."""
    sql = "SELECT * FROM t WHERE label = ':status' AND id = :id"
    out = _translate_named_to_positional(sql)
    # The quoted ':status' is preserved verbatim; only the real :id becomes $1.
    assert out == "SELECT * FROM t WHERE label = ':status' AND id = $1", out


def test_translate_handles_dollar_quoting() -> None:
    """Inside ``$$…$$`` blocks, ``:foo`` is opaque payload — never translated."""
    sql = "DO $$ BEGIN PERFORM :foo; END $$ LANGUAGE plpgsql; SELECT :bar"
    out = _translate_named_to_positional(sql)
    # The :foo inside the $$…$$ block is untouched; the :bar outside becomes $1.
    assert ":foo" in out, "dollar-quoted :foo must not be translated"
    assert "$1" in out, ":bar outside the block should translate to $1"
    # And the verbatim block itself must survive intact.
    assert "$$ BEGIN PERFORM :foo; END $$" in out, out


# ---------------------------------------------------------------------------
# Patch 2 — fragment-fold extractor
# ---------------------------------------------------------------------------


def test_fold_concat_emits_composed_only(tmp_path: Path) -> None:
    """``Q = _CTE + " " + _SELECT`` emits one composed SQL, not three fragments."""
    fixture = tmp_path / "fake_repo.py"
    fixture.write_text(
        """
# Module-level SQL fragments — only the composition is valid in isolation.
_CTE = "WITH x AS (SELECT 1 AS n)"
_SELECT = "SELECT * FROM x"

Q = _CTE + " " + _SELECT
""",
        encoding="utf-8",
    )
    extracted, _ = extract_sql_from_file(fixture)
    # Exactly one SQL statement should be emitted: the composed Q.
    assert len(extracted) == 1, f"expected 1 composed statement, got {len(extracted)}: {extracted!r}"
    composed = extracted[0].sql_text
    assert "WITH x AS" in composed and "SELECT * FROM x" in composed, composed


def test_fold_skips_when_name_unresolved(tmp_path: Path) -> None:
    """If a Name in the chain isn't a known module constant, skip the fold."""
    fixture = tmp_path / "fake_repo.py"
    fixture.write_text(
        """
# ``unknown_name`` is not a module-level string constant — fold must fail.
def make_query(unknown_name: str) -> str:
    return unknown_name + "SELECT *"
""",
        encoding="utf-8",
    )
    extracted, _ = extract_sql_from_file(fixture)
    # No composed statement should be emitted; the "SELECT *" literal alone
    # doesn't begin with a recognised verb-start (the leading text fragment
    # makes the merged string non-SQL-looking) — and the Name resolution
    # bails out, so we get no emission for the composition.
    # However the bare "SELECT *" constant IS a recognised SQL literal on its
    # own. Acceptance: the bare literal can still appear; the composed
    # statement must NOT (because the fold failed). The crucial assertion
    # is: no extracted item contains "unknown_name" (Name was never resolved).
    for item in extracted:
        assert "unknown_name" not in item.sql_text, (
            "fold must skip when a Name leaf is unknown; " f"got {item.sql_text!r}"
        )
