"""Seed demo-critical canonical entities — PLAN-0087 (D-R3-007 / D-F2-005 / D-R4-010).

Revision ID: 0038
Revises: 0037
Create Date: 2026-05-09

WHY THIS MIGRATION EXISTS:
  PRD-0087 §2.2 B5 expects the hedge fund director to type any ticker on the
  instrument deep-dive surface (B5).  Audit R3 / R4 / F2 found a series of
  demo-critical canonicals MISSING from intelligence_db.canonical_entities:

    - OpenAI, Anthropic       (organisations, no ticker)
    - COIN (Coinbase)         (financial_instrument)
    - NFLX (Netflix)          (financial_instrument)
    - INTC (Intel)            (financial_instrument)
    - QCOM (Qualcomm)         (financial_instrument)
    - AMD                     (financial_instrument)
    - GOOG (Alphabet Class C) (financial_instrument)

  Without these the chat A7 prompt "show me the entity graph around OpenAI"
  fails outright (D-R3-007), instrument briefs for COIN/NFLX/INTC/QCOM/AMD
  return cold-start placeholders (D-R4-010), and Phase B B5 deep-dive on any
  of these tickers shows a 404 page instead of an instrument page.

WHAT THIS MIGRATION DOES:
  Inserts canonical_entities + entity_aliases rows for the 8 demo-critical
  names with deterministic UUIDv7-shaped IDs (mirrors migration 0009's
  pattern).  Idempotent via ``ON CONFLICT (entity_id) DO NOTHING`` on
  canonicals + the partial unique index on aliases.

  Post-demo: revert via ``downgrade()`` which DELETEs the seeded rows by id
  prefix.  The IDs use ``0195daad-d001-...`` (prefix 'd001' for "demo seed
  Wave 0") so they are trivially identifiable in queries.
"""

from __future__ import annotations

import json

from alembic import op

revision: str = "0038"
down_revision: str = "0037"
branch_labels = None
depends_on = None


# ── Seed data ──────────────────────────────────────────────────────────────────

# (canonical_name, entity_type, ticker, exchange, description, aliases[])
_DEMO_SEEDS: list[tuple[str, str, str | None, str | None, str, list[str]]] = [
    (
        "OpenAI",
        "organization",
        None,
        None,
        "American AI research and deployment organization, creator of GPT family models, ChatGPT, and DALL·E. Founded 2015.",
        ["OpenAI", "Open AI", "OAI"],
    ),
    (
        "Anthropic",
        "organization",
        None,
        None,
        "American AI safety and research company, creator of the Claude family of large language models. Founded 2021.",
        ["Anthropic", "Anthropic PBC"],
    ),
    (
        "Coinbase Global Inc.",
        "financial_instrument",
        "COIN",
        "US",
        "American publicly-traded cryptocurrency exchange platform. Largest US-based crypto exchange by trading volume.",
        ["Coinbase", "Coinbase Global", "Coinbase Global Inc.", "COIN"],
    ),
    (
        "Netflix, Inc.",
        "financial_instrument",
        "NFLX",
        "US",
        "American media and entertainment company providing subscription streaming service worldwide.",
        ["Netflix", "Netflix Inc", "Netflix, Inc.", "NFLX"],
    ),
    (
        "Intel Corporation",
        "financial_instrument",
        "INTC",
        "US",
        "American semiconductor manufacturer; one of the world's largest producers of x86 processors and chip foundry services.",
        ["Intel", "Intel Corp", "Intel Corporation", "INTC"],
    ),
    (
        "QUALCOMM Incorporated",
        "financial_instrument",
        "QCOM",
        "US",
        "American semiconductor and telecommunications equipment company; leading designer of mobile-device system-on-chips.",
        ["Qualcomm", "QUALCOMM", "Qualcomm Inc", "QUALCOMM Incorporated", "QCOM"],
    ),
    (
        "Advanced Micro Devices, Inc.",
        "financial_instrument",
        "AMD",
        "US",
        "American semiconductor company; designer of CPUs (Ryzen/EPYC), GPUs (Radeon), and adaptive computing products.",
        ["AMD", "Advanced Micro Devices", "Advanced Micro Devices, Inc."],
    ),
    (
        "Alphabet Inc. Class C",
        "financial_instrument",
        "GOOG",
        "US",
        "American multinational technology conglomerate; Class C non-voting shares (vs GOOGL Class A).",
        ["GOOG", "Alphabet Class C", "Alphabet Inc Class C"],
    ),
]


# ── Helpers (mirror migration 0009's pattern) ──────────────────────────────────


def _uuid(prefix: str, counter: int) -> str:
    """Stable UUIDv7-shaped ID: 0195daad-<prefix>-7<c>-8<c>-<12-hex-c>."""
    c4 = f"{counter:04x}"
    return f"0195daad-{prefix}-7{c4[:3]}-8{c4[:3]}-{counter:012x}"


def _norm(text: str) -> str:
    return text.lower().strip()


def upgrade() -> None:
    canonical_rows: list[str] = []
    alias_rows: list[str] = []

    for i, (name, etype, ticker, exchange, desc, aliases) in enumerate(_DEMO_SEEDS, start=1):
        eid = _uuid("d001", i)
        metadata = {
            "description": desc,
            "seed_source": "PLAN-0087",
        }
        meta_json = json.dumps(metadata).replace("'", "''")
        cn = name.replace("'", "''")
        ticker_sql = f"'{ticker}'" if ticker else "NULL"
        exchange_sql = f"'{exchange}'" if exchange else "NULL"
        canonical_rows.append(
            f"('{eid}', '{cn}', '{etype}', {ticker_sql}, {exchange_sql}, '{desc.replace(chr(39), chr(39) + chr(39))}', '{meta_json}'::jsonb)"
        )
        for alias_text in aliases:
            at = alias_text.replace("'", "''")
            norm = _norm(alias_text).replace("'", "''")
            alias_rows.append(f"('{eid}', '{at}', '{norm}', 'EXACT', true, 'seed:PLAN-0087')")

    if canonical_rows:
        op.execute(
            "-- PLAN-0087 demo entity seed: 8 canonicals\n"
            "INSERT INTO canonical_entities "
            "(entity_id, canonical_name, entity_type, ticker, exchange, description, metadata) "
            f"VALUES {','.join(canonical_rows)} "
            "ON CONFLICT (entity_id) DO NOTHING"
        )

    if alias_rows:
        # Pin to the partial unique index from migration 0008 to be order-independent
        # against any future indexes added on the same table.
        op.execute(
            "-- PLAN-0087 demo entity seed: aliases\n"
            "INSERT INTO entity_aliases "
            "(entity_id, alias_text, normalized_alias_text, alias_type, is_active, source) "
            f"VALUES {','.join(alias_rows)} "
            "ON CONFLICT (entity_id, normalized_alias_text, alias_type) "
            "WHERE is_active = true "
            "DO NOTHING"
        )


def downgrade() -> None:
    # Delete by metadata->>seed_source for safety (also catches any operator
    # who hand-applied the seed via psql).
    op.execute("DELETE FROM entity_aliases WHERE source = 'seed:PLAN-0087'")
    op.execute("DELETE FROM canonical_entities WHERE metadata->>'seed_source' = 'PLAN-0087'")
