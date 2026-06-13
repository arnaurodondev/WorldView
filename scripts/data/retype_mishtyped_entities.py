#!/usr/bin/env python3
"""Deterministic high-confidence re-typing of mis-typed hub entities (FR-12).

ROOT CAUSE (see docs/audits/2026-06-13-fr12-hub-mistyping-investigation.md): the
``canonical_entities.entity_type`` discriminator had no ``exchange`` value, the
ENTITY_PROFILE prompt taught "Nasdaq -> index", and the GLiNER no-enrich fallback
mapped company/corp/firm -> financial_instrument even without a ticker.  The
result: stock exchanges typed as financial_instrument/index, and country
names/abbreviations ("U.S.", "United States of America") scattered across
currency/unknown.

This script applies ONLY the two deterministic, high-confidence corrections that
need no LLM adjudication:

  (a) EXCHANGES — a row whose canonical_name matches a curated stock-exchange
      allow-list (NYSE, NASDAQ, NasdaqGS, NYSE Arca, Cboe, LSE, ...) is re-typed
      to ``exchange`` (requires intelligence-migrations 0053, which adds the
      value to ck_canonical_entities_entity_type).

  (b) COUNTRIES — a row currently typed ``currency`` or ``unknown`` whose
      canonical_name matches a small country/region gazetteer (United States /
      U.S. / US / USA, China / PRC, ...) is re-typed to ``place``.

It deliberately does NOT attempt the fuzzy ~6,235-row tickerless-FI reprofile —
that bucket is too heterogeneous for a regex and is a documented LLM-reprofile
follow-up (investigation §4.2).

SAFETY / DISCIPLINE:
  • DRY-RUN by DEFAULT.  It prints exactly the rows it WOULD change and exits
    without writing.  Pass ``--apply`` to execute (one transaction, committed
    only on success).
  • IDEMPOTENT.  Only rows whose CURRENT type differs from the target are
    selected, so a second run after a successful pass changes nothing.
  • Matching is case-insensitive on the normalised canonical_name; the gazetteer
    and allow-list are exact-membership sets (no fuzzy matching) so a re-type is
    only ever applied to a name we explicitly trust.

Usage:
    python scripts/data/retype_mishtyped_entities.py            # DRY RUN (default)
    python scripts/data/retype_mishtyped_entities.py --apply    # execute
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass

import psycopg

# Default DSN targets the local docker-compose Postgres.  Override via env.
_INTEL_DSN = os.environ.get(
    "INTELLIGENCE_DB_DSN",
    "postgresql://postgres:postgres@localhost:5432/intelligence_db",
)


# ── Curated allow-lists (the "trust" boundary — no fuzzy matching) ────────────
#
# Keys are NORMALISED names (lower-cased, stripped).  ``_normalize`` below must
# be applied to both the DB value and these literals before comparison.

# (a) Stock exchanges / trading venues -> ``exchange``.  Curated from the FR-12
#     investigation's high-degree hubs plus the common global venues; kept small
#     and explicit so a re-type only fires on a name we are certain is a venue.
_EXCHANGE_NAMES: frozenset[str] = frozenset(
    _name.lower().strip()
    for _name in (
        "NYSE",
        "New York Stock Exchange",
        "NYSE American",
        "NYSE Arca",
        "NASDAQ",
        "Nasdaq Stock Market",
        "NasdaqGS",
        "Nasdaq GS",
        "NasdaqGM",
        "NasdaqCM",
        "Cboe",
        "CBOE",
        "Cboe Global Markets",  # the exchange operator; the listed company is BATS/CBOE — treated as venue here
        "BATS",
        "LSE",
        "London Stock Exchange",
        "Euronext",
        "Deutsche Borse",
        "Xetra",
        "TSX",
        "Toronto Stock Exchange",
        "TSXV",
        "Hong Kong Stock Exchange",
        "HKEX",
        "Shanghai Stock Exchange",
        "Shenzhen Stock Exchange",
        "Tokyo Stock Exchange",
        "TSE",
        "SIX Swiss Exchange",
        "Borsa Italiana",
        "BSE",
        "Bombay Stock Exchange",
        "NSE",
        "National Stock Exchange of India",
        "ASX",
        "Australian Securities Exchange",
        "Nasdaq Nordic",
        "OTC Markets",
        "OTCMKTS",
    )
)

# (b) Countries / regions -> ``place``.  Includes the abbreviation variants the
#     small classifier mis-typed as ``currency`` ("U.S.", "US") and the
#     full-name variants seeded into ``unknown`` ("United States of America").
_COUNTRY_NAMES: frozenset[str] = frozenset(
    _name.lower().strip()
    for _name in (
        "United States",
        "United States of America",
        "U.S.",
        "US",
        "U.S",
        "USA",
        "U.S.A.",
        "America",
        "United Kingdom",
        "U.K.",
        "UK",
        "Great Britain",
        "China",
        "People's Republic of China",
        "PRC",
        "Mainland China",
        "Japan",
        "Germany",
        "France",
        "Italy",
        "Spain",
        "Canada",
        "Mexico",
        "Brazil",
        "India",
        "Republic of India",
        "Russia",
        "Russian Federation",
        "South Korea",
        "Republic of Korea",
        "North Korea",
        "Taiwan",
        "Hong Kong",
        "Singapore",
        "Australia",
        "Saudi Arabia",
        "United Arab Emirates",
        "Switzerland",
        "Netherlands",
        "Sweden",
        "Norway",
        "Ireland",
        "Israel",
        "Turkey",
        "Indonesia",
        "Vietnam",
        "Thailand",
        "Philippines",
        "Argentina",
        "South Africa",
        "Nigeria",
        "Egypt",
        "European Union",
        "Eurozone",
    )
)

# Source types we are willing to OVERWRITE for the country rule.  We deliberately
# do NOT touch a name that is already ``place`` (idempotent), and we do NOT touch
# financial_instrument/index/person/etc. for the country rule — only the two
# buckets the investigation found polluted by country names.
_COUNTRY_SOURCE_TYPES: frozenset[str] = frozenset({"currency", "unknown"})


def _normalize(name: str | None) -> str:
    """Lower-case + strip — the single comparison key for both allow-lists."""
    return (name or "").lower().strip()


@dataclass(frozen=True)
class Retype:
    """A single planned re-type (one canonical_entities row)."""

    entity_id: str
    canonical_name: str
    old_type: str
    new_type: str
    rule: str  # "exchange" | "country"


def classify_retype(entity_id: str, canonical_name: str, current_type: str) -> Retype | None:
    """Return the planned re-type for one row, or None if no rule applies.

    Pure + deterministic — this is the unit-tested core.  Idempotent by
    construction: if ``current_type`` already equals the target, returns None.
    """
    norm = _normalize(canonical_name)

    # Rule (a) exchanges — fires regardless of the current (wrong) type, as long
    # as it is not ALREADY ``exchange``.  Exchanges were seen as
    # financial_instrument (NYSE) and index (NASDAQ); both must be corrected.
    if norm in _EXCHANGE_NAMES:
        if current_type == "exchange":
            return None  # already correct — idempotent no-op
        return Retype(entity_id, canonical_name, current_type, "exchange", "exchange")

    # Rule (b) countries — only re-type the polluted source buckets, and only if
    # not already ``place``.
    if norm in _COUNTRY_NAMES and current_type in _COUNTRY_SOURCE_TYPES:
        return Retype(entity_id, canonical_name, current_type, "place", "country")

    return None


def plan_retypes(rows: list[tuple[str, str, str]]) -> list[Retype]:
    """Map ``(entity_id, canonical_name, entity_type)`` rows to planned re-types."""
    planned: list[Retype] = []
    for entity_id, name, current_type in rows:
        retype = classify_retype(str(entity_id), name, current_type)
        if retype is not None:
            planned.append(retype)
    return planned


def _fetch_candidate_rows(intel: psycopg.Connection) -> list[tuple[str, str, str]]:
    """Fetch the (small) set of rows that COULD match either rule.

    We pre-filter in SQL to candidate buckets so we never pull the whole table:
      • exchange rule: any row not already typed ``exchange`` (names are checked
        in Python against the allow-list);
      • country rule: rows currently typed currency/unknown.
    The Python ``classify_retype`` then applies the exact-membership decision.
    """
    rows = intel.execute(
        """
SELECT entity_id, canonical_name, entity_type
FROM canonical_entities
WHERE entity_type <> 'exchange'
ORDER BY canonical_name
"""
    ).fetchall()
    return [(str(r[0]), r[1], r[2]) for r in rows]


def _apply_retypes(intel: psycopg.Connection, planned: list[Retype]) -> int:
    """Execute the planned re-types in ONE transaction.  Returns rows updated.

    The UPDATE re-checks the current type in its WHERE clause so a concurrent
    change (or a stale plan) can never blindly overwrite — it only updates the
    row if it still holds the type we planned to change FROM.
    """
    updated = 0
    for r in planned:
        res = intel.execute(
            """
UPDATE canonical_entities
SET entity_type = %(new)s, updated_at = now()
WHERE entity_id = %(eid)s AND entity_type = %(old)s
""",
            {"new": r.new_type, "eid": r.entity_id, "old": r.old_type},
        )
        updated += res.rowcount or 0
    return updated


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Deterministically re-type mis-typed exchange/country canonical_entities (FR-12).",
    )
    ap.add_argument(
        "--apply",
        action="store_true",
        help="Execute the re-types. WITHOUT this flag the script is DRY-RUN (default) and writes nothing.",
    )
    args = ap.parse_args(argv)
    dry_run = not args.apply

    with psycopg.connect(_INTEL_DSN) as intel:
        candidates = _fetch_candidate_rows(intel)
        planned = plan_retypes(candidates)

        n_exchange = sum(1 for r in planned if r.rule == "exchange")
        n_country = sum(1 for r in planned if r.rule == "country")

        mode = "DRY RUN — no writes" if dry_run else "APPLY"
        print(f"FR-12 deterministic re-type ({mode}).")
        print(f"Scanned {len(candidates)} candidate row(s); {len(planned)} planned re-type(s):")
        print(f"  exchanges -> 'exchange': {n_exchange}")
        print(f"  countries -> 'place'   : {n_country}\n")

        for r in planned:
            print(f"  [{r.rule}] {r.entity_id} {r.canonical_name!r}: {r.old_type} -> {r.new_type}")

        if dry_run:
            print("\nDRY RUN complete — re-run with --apply to execute.")
            return 0

        updated = _apply_retypes(intel, planned)
        intel.commit()
        print(f"\nAPPLIED — {updated} row(s) re-typed and committed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
