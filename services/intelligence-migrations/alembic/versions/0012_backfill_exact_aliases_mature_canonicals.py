"""Backfill EXACT-name aliases for the 8 pre-0009 financial_instrument canonicals.

Revision ID: 0012
Revises: 0011
Create Date: 2026-05-01

PLAN-0052 QA-R6 — closes audit finding (platform-qa-r6:alias-backfill).

Background
----------
Migration 0009 seeded 224 NEW canonical entities with structured EXACT aliases.
But the 8 financial_instrument canonicals that existed BEFORE migration 0009
(Microsoft, Apple, Amazon, Nvidia, Tesla, Alphabet, Meta, JPMorgan — created
during the very first seeding) only have TICKER aliases.

Consequence: Stage-1 exact-match resolution misses "Microsoft" / "Amazon.com" /
"Alphabet" surface forms even when those strings appear verbatim in articles.
The entity must then fall all the way to Stage-4 ANN, which can fail at the
auto-resolve threshold, leaving the mention UNRESOLVED and silently dropping
every relation/event/claim that referenced it in deep-extraction output.

Fix: insert EXACT aliases for all major surface forms of each of the 8 entities.
The INSERT uses a lookup-by-canonical-name JOIN so the migration is idempotent
on any fresh DB (entity IDs are stable 11111111-00XX UUIDv7 seeds but we never
hardcode them in SQL — we rely on canonical_name + entity_type uniqueness).

ON CONFLICT clauses handle:
  - uidx_entity_aliases_entity_norm_type: same (entity_id, norm, alias_type)
    pair already exists → skip.
  - uidx_entity_aliases_normalized: same EXACT normalized text already claimed
    by another entity → skip (e.g. if "nasdaq" was already claimed by the index
    entity from 0009).

Idempotent: safe to run multiple times.
"""

from __future__ import annotations

#                     there is no user input at any point.
from alembic import op

revision: str = "0012"
down_revision: str = "0011"
branch_labels = None
depends_on = None

# Each tuple: (canonical_name_key, alias_text)
# canonical_name_key must match the exact string in canonical_entities.canonical_name.
_ALIASES: list[tuple[str, str]] = [
    # ── Microsoft ────────────────────────────────────────────────────────────
    ("Microsoft Corporation", "Microsoft Corporation"),
    ("Microsoft Corporation", "Microsoft"),
    # ── Apple ────────────────────────────────────────────────────────────────
    ("Apple Inc.", "Apple Inc."),
    ("Apple Inc.", "Apple Inc"),
    ("Apple Inc.", "Apple"),
    # ── Amazon ───────────────────────────────────────────────────────────────
    ("Amazon.com Inc", "Amazon.com Inc"),
    ("Amazon.com Inc", "Amazon.com"),
    ("Amazon.com Inc", "Amazon"),
    # ── NVIDIA ───────────────────────────────────────────────────────────────
    ("NVIDIA Corporation", "NVIDIA Corporation"),
    ("NVIDIA Corporation", "Nvidia Corporation"),
    ("NVIDIA Corporation", "Nvidia"),
    ("NVIDIA Corporation", "NVIDIA"),
    # ── Tesla ────────────────────────────────────────────────────────────────
    ("Tesla Inc", "Tesla Inc"),
    ("Tesla Inc", "Tesla"),
    # ── Alphabet / Google ─────────────────────────────────────────────────────
    ("Alphabet Inc Class A", "Alphabet Inc Class A"),
    ("Alphabet Inc Class A", "Alphabet Inc"),
    ("Alphabet Inc Class A", "Alphabet"),
    ("Alphabet Inc Class A", "Google"),
    # ── Meta ─────────────────────────────────────────────────────────────────
    ("Meta Platforms Inc.", "Meta Platforms Inc."),
    ("Meta Platforms Inc.", "Meta Platforms Inc"),
    ("Meta Platforms Inc.", "Meta Platforms"),
    ("Meta Platforms Inc.", "Meta"),
    ("Meta Platforms Inc.", "Facebook"),
    # ── JPMorgan ─────────────────────────────────────────────────────────────
    ("JPMorgan Chase & Co", "JPMorgan Chase & Co"),
    ("JPMorgan Chase & Co", "JPMorgan Chase"),
    ("JPMorgan Chase & Co", "JPMorgan"),
    ("JPMorgan Chase & Co", "J.P. Morgan"),
    ("JPMorgan Chase & Co", "JP Morgan"),
]


def upgrade() -> None:
    # Build a single VALUES list with (canonical_name, alias_text, normalized).
    # We do one INSERT per alias_text rather than a multi-row VALUES CTE so we
    # can use ON CONFLICT with a partial predicate referencing two different
    # unique indexes.  A loop of individual INSERTs is fine — this migration
    # runs once at startup on ~29 rows.
    for canonical_name, alias_text in _ALIASES:
        normalized = alias_text.lower().strip()
        _sql = f"""
            INSERT INTO entity_aliases
                (alias_id, entity_id, alias_text, normalized_alias_text,
                 alias_type, is_active, created_at, source)
            SELECT
                gen_random_uuid(),
                ce.entity_id,
                '{alias_text.replace("'", "''")}',
                '{normalized.replace("'", "''")}',
                'EXACT',
                true,
                NOW(),
                '0012-backfill'
            FROM canonical_entities ce
            WHERE ce.canonical_name = '{canonical_name.replace("'", "''")}'
              AND ce.entity_type    = 'financial_instrument'
            ON CONFLICT (entity_id, normalized_alias_text, alias_type)
                WHERE is_active = true
            DO NOTHING
            """
        op.execute(_sql)


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM entity_aliases
        WHERE source = '0012-backfill'
          AND alias_type = 'EXACT'
        """
    )
