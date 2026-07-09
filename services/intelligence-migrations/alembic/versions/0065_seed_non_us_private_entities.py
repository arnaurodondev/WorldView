"""Seed non-US-listed & private-company canonical entities — Area-3 Phase 0+2.

Revision ID: 0065
Revises: 0064
Create Date: 2026-07-09

WHY THIS MIGRATION EXISTS
  Roadmap ``docs/plans/2026-07-09-chat-enhancement-roadmap.md`` Area 3: the
  ``iter3_apple_competitors_spanish`` benchmark question ("Apple's smartphone
  competitors") FAILED because the competitor companies do not exist as canonical
  entities and are not US-listed, so the chat could not resolve them and
  fabricated a wrong US ticker/entity. This migration seeds the missing entities
  so the names resolve, with their REAL listing venue recorded:

    * Samsung Electronics  — KRX 005930   (financial_instrument, non-US listing)
    * Xiaomi Corporation   — HKEX 1810    (financial_instrument, non-US listing)
    * Tencent Holdings     — HKEX 0700    (financial_instrument, non-US listing)
    * Huawei Technologies  — private      (organization, no ticker)      [FR-12]
    * ByteDance            — private      (organization, no ticker)      [FR-12]
    * TSMC                 — US ADR 'TSM' (financial_instrument, exchange US)

  Phase 0 (TSMC ADR): TSM trades in the US, so it flows through the EXISTING US
  price/fundamentals pipeline — TSMC becomes fully priceable today via its ADR.

  Phase 2 (non-US + private): Samsung/Xiaomi/Tencent carry their local exchange +
  ticker so the rag-chat listing-status registry
  (``services/rag-chat/.../application/services/listing_status.py``) can state
  "listed on HKEX as 1810 — Worldview does not currently ingest live HKEX prices"
  instead of fabricating. Huawei/ByteDance are ``organization`` (private) so the
  chat states "privately held, not publicly traded". Live HKEX/KRX price + news
  ingestion is DEFERRED to Area-3 Phase 1/3 (needs EODHD plan + market-ingestion);
  this seed is the resolution-side half and is deployable independently.

WHAT THIS MIGRATION DOES (mirrors migration 0038 EXACTLY — proven pattern):
  Inserts canonical_entities + entity_aliases rows with deterministic
  UUIDv7-shaped IDs (prefix 'a003' = "Area-3 seed"). Idempotent via
  ``ON CONFLICT (entity_id) DO NOTHING`` on canonicals + the partial unique index
  on aliases. Reversible via ``downgrade()`` which DELETEs by seed_source.

  NOTE on the ``organization`` entity_type: added by migration 0055 (FR-12); the
  CHECK constraint accepts it, so Huawei/ByteDance seed cleanly.
"""

from __future__ import annotations

import json

from alembic import op

revision: str = "0065"
down_revision: str = "0064"
branch_labels = None
depends_on = None


# ── Seed data ──────────────────────────────────────────────────────────────────
# Seed source tag — the downgrade selector and the "rows owned by 0065" filter.
_SEED_SOURCE = "AREA3-NONUS"

# (canonical_name, entity_type, ticker, exchange, description, aliases[])
#   * financial_instrument rows carry their LOCAL exchange + ticker (Worldview
#     does not price these live yet, except the TSM ADR whose exchange is 'US').
#   * organization rows are private companies: ticker=None, exchange=None.
_AREA3_SEEDS: list[tuple[str, str, str | None, str | None, str, list[str]]] = [
    (
        "Samsung Electronics Co., Ltd.",
        "financial_instrument",
        "005930",
        "KRX",
        "South Korean multinational electronics conglomerate; the world's largest "
        "smartphone and memory-chip maker. Listed on the Korea Exchange (KRX) as 005930.",
        ["Samsung", "Samsung Electronics", "Samsung Electronics Co., Ltd.", "005930"],
    ),
    (
        "Xiaomi Corporation",
        "financial_instrument",
        "1810",
        "HKEX",
        "Chinese consumer-electronics and smart-manufacturing company; major global "
        "smartphone vendor. Listed on the Hong Kong Stock Exchange (HKEX) as 1810.",
        ["Xiaomi", "Xiaomi Corp", "Xiaomi Corporation", "1810"],
    ),
    (
        "Tencent Holdings Ltd.",
        "financial_instrument",
        "0700",
        "HKEX",
        "Chinese multinational technology conglomerate (WeChat, gaming, cloud). "
        "Listed on the Hong Kong Stock Exchange (HKEX) as 0700.",
        ["Tencent", "Tencent Holdings", "Tencent Holdings Ltd.", "0700"],
    ),
    (
        "Huawei Technologies Co., Ltd.",
        "organization",
        None,
        None,
        "Chinese multinational technology company (telecom equipment, smartphones). "
        "Privately held / employee-owned — not publicly traded, no ticker.",
        ["Huawei", "Huawei Technologies", "Huawei Technologies Co., Ltd."],
    ),
    (
        "ByteDance Ltd.",
        "organization",
        None,
        None,
        "Chinese internet technology company; owner of TikTok/Douyin. Privately "
        "held — not publicly traded, no ticker.",
        ["ByteDance", "Bytedance", "ByteDance Ltd."],
    ),
    (
        "Taiwan Semiconductor Manufacturing Company Limited",
        "financial_instrument",
        "TSM",
        "US",
        "Taiwanese contract chip manufacturer; the world's largest dedicated "
        "semiconductor foundry. Trades in the US as an ADR under 'TSM' (primary "
        "listing TWSE 2330). Worldview prices the US ADR via the existing pipeline.",
        ["TSMC", "Taiwan Semiconductor", "Taiwan Semiconductor Manufacturing Company Limited", "TSM"],
    ),
]


# ── Helpers (mirror migration 0038's pattern) ──────────────────────────────────


def _uuid(prefix: str, counter: int) -> str:
    """Stable UUIDv7-shaped ID: 0195daad-<prefix>-7<c>-8<c>-<12-hex-c>."""
    c4 = f"{counter:04x}"
    return f"0195daad-{prefix}-7{c4[:3]}-8{c4[:3]}-{counter:012x}"


def _norm(text: str) -> str:
    return text.lower().strip()


def upgrade() -> None:
    canonical_rows: list[str] = []
    alias_rows: list[str] = []

    for i, (name, etype, ticker, exchange, desc, aliases) in enumerate(_AREA3_SEEDS, start=1):
        eid = _uuid("a003", i)
        metadata = {
            "description": desc,
            "seed_source": _SEED_SOURCE,
        }
        meta_json = json.dumps(metadata).replace("'", "''")
        cn = name.replace("'", "''")
        ticker_sql = f"'{ticker}'" if ticker else "NULL"
        exchange_sql = f"'{exchange}'" if exchange else "NULL"
        canonical_rows.append(
            f"('{eid}', '{cn}', '{etype}', {ticker_sql}, {exchange_sql}, "
            f"'{desc.replace(chr(39), chr(39) + chr(39))}', '{meta_json}'::jsonb)"
        )
        for alias_text in aliases:
            at = alias_text.replace("'", "''")
            norm = _norm(alias_text).replace("'", "''")
            alias_rows.append(f"('{eid}', '{at}', '{norm}', 'EXACT', true, 'seed:{_SEED_SOURCE}')")

    if canonical_rows:
        op.execute(
            "-- Area-3 non-US/private entity seed: canonicals.\n"
            "-- ON CONFLICT DO NOTHING (no target) so BOTH the entity_id PK and the\n"
            "-- lower(canonical_name) unique index are skipped — some names (Huawei,\n"
            "-- ByteDance) already exist from news extraction with different ids.\n"
            "INSERT INTO canonical_entities "
            "(entity_id, canonical_name, entity_type, ticker, exchange, description, metadata) "
            f"VALUES {','.join(canonical_rows)} "
            "ON CONFLICT DO NOTHING"
        )

    if alias_rows:
        # Pin to the partial unique index from migration 0008 (order-independent).
        op.execute(
            "-- Area-3 non-US/private entity seed: aliases — only for canonicals that\n"
            "-- actually exist (a name-dupe canonical above was skipped, so its\n"
            "-- deterministic entity_id has no row; guard against orphan aliases).\n"
            "INSERT INTO entity_aliases "
            "(entity_id, alias_text, normalized_alias_text, alias_type, is_active, source) "
            "SELECT v.entity_id::uuid, v.alias_text, v.normalized_alias_text, v.alias_type, "
            "v.is_active, v.source "
            f"FROM (VALUES {','.join(alias_rows)}) "
            "AS v(entity_id, alias_text, normalized_alias_text, alias_type, is_active, source) "
            "WHERE EXISTS (SELECT 1 FROM canonical_entities ce WHERE ce.entity_id = v.entity_id::uuid) "
            "ON CONFLICT (entity_id, normalized_alias_text, alias_type) "
            "WHERE is_active = true "
            "DO NOTHING"
        )


def downgrade() -> None:
    # Delete by seed_source (also catches a hand-applied seed).
    op.execute(f"DELETE FROM entity_aliases WHERE source = 'seed:{_SEED_SOURCE}'")
    op.execute(f"DELETE FROM canonical_entities WHERE metadata->>'seed_source' = '{_SEED_SOURCE}'")
