"""Scope the SEC EDGAR source to a CIK watchlist (R1 Fix ② — coverage).

Revision ID: 0010_sec_edgar_cik_watchlist
Revises: 0009_remove_finnhub_global_news
Create Date: 2026-07-04

WHY (R1 Fix ②)
--------------
The ``sec-edgar-filings`` source (seeded by 0008) carried only
``config={"user_agent": "worldview/1.0"}`` — no filer scoping. The EDGAR EFTS
full-text search, when unscoped, returns only the most-recent filings across ALL
filers (date-sorted). The result set is dominated by tiny/obscure companies, so a
company users actually ask about (e.g. Apple) is essentially NEVER ingested — its
filings are diluted out. Investigation: a live ``get_filings`` for Apple returned
0/50 Apple rows.

FIX
---
Attach a ``ciks`` watchlist to the source config. The fixed adapter issues one
EFTS search PER CIK (``ciks=<cik>`` query param), guaranteeing every watched
company's filings are pulled. CIKs are EDGAR's canonical zero-padded 10-digit
Central Index Keys.

This is a curated starter set of frequently-asked mega-caps. Operators can extend
it by updating the source's ``config->'ciks'`` array (no code change needed). An
empty/absent ``ciks`` list falls back to the legacy global search.

Downgrade restores the original ``{"user_agent": "worldview/1.0"}`` config.
"""

from __future__ import annotations

import json

import sqlalchemy as sa
from alembic import op

# revision identifiers
revision: str = "0010_sec_edgar_cik_watchlist"
down_revision: str = "0009_remove_finnhub_global_news"
branch_labels = None
depends_on = None

# Curated CIK watchlist (zero-padded 10-digit). Verified against EDGAR company
# search. Extend via the source config JSONB; no migration needed to add more.
_CIK_WATCHLIST: list[str] = [
    "0000320193",  # Apple Inc.
    "0000789019",  # Microsoft Corporation
    "0001018724",  # Amazon.com, Inc.
    "0001652044",  # Alphabet Inc. (Google)
    "0001326801",  # Meta Platforms, Inc.
    "0001045810",  # NVIDIA Corporation
    "0001318605",  # Tesla, Inc.
    "0001067983",  # Berkshire Hathaway Inc.
    "0000019617",  # JPMorgan Chase & Co.
    "0000070858",  # Bank of America Corporation
    "0000104169",  # Walmart Inc.
    "0000034088",  # Exxon Mobil Corporation
    "0000200406",  # Johnson & Johnson
    "0001403161",  # Visa Inc.
    "0001141391",  # Mastercard Incorporated
    "0000021344",  # The Coca-Cola Company
    "0000050863",  # Intel Corporation
    "0000002488",  # Advanced Micro Devices, Inc.
    "0000078003",  # Pfizer Inc.
    "0000858877",  # Cisco Systems, Inc.
    "0000796343",  # Adobe Inc.
    "0001341439",  # Oracle Corporation
    "0001108524",  # Salesforce, Inc.
    "0001065280",  # Netflix, Inc.
    "0000093410",  # Chevron Corporation
]

_SEC_SOURCE_NAME = "sec-edgar-filings"
_NEW_CONFIG = {"user_agent": "worldview/1.0", "forms": "10-K,10-Q,8-K,DEF14A", "ciks": _CIK_WATCHLIST}
_OLD_CONFIG = {"user_agent": "worldview/1.0"}


def upgrade() -> None:
    # Alembic's ``op.execute`` takes a single executable and cannot bind params,
    # so run the parameterized UPDATE on the bind connection directly.
    bind = op.get_bind()
    bind.execute(
        sa.text("UPDATE sources SET config = CAST(:cfg AS JSONB) WHERE name = :name AND source_type = 'sec_edgar'"),
        {"cfg": json.dumps(_NEW_CONFIG), "name": _SEC_SOURCE_NAME},
    )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text("UPDATE sources SET config = CAST(:cfg AS JSONB) WHERE name = :name AND source_type = 'sec_edgar'"),
        {"cfg": json.dumps(_OLD_CONFIG), "name": _SEC_SOURCE_NAME},
    )
