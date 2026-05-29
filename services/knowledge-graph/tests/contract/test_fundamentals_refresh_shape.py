"""F-DB-005 contract test — assert the FundamentalsRefresh worker parses the
REAL ``GET /api/v1/fundamentals/{id}`` response shape that market-data ships
in production.

WHY THIS IS A CONTRACT TEST (not a unit test):
    The bug F-DB-005 hid for months precisely because the unit-test fixtures
    stubbed a flat ``{revenue_usd_millions, pe_ratio, ...}`` shape that the
    market-data endpoint NEVER returned. The unit tests passed; production
    silently emitted ``failure_reason="unknown"`` for ~488 entities/cycle.

    This file anchors the contract against
    ``services/market-data/src/market_data/api/schemas/fundamentals.py``
    (``FundamentalsResponse`` + ``FundamentalsRecordResponse``). If
    market-data renames ``data`` → ``payload`` or moves ``records[]`` to a
    new envelope, THIS test must fail loudly — and the worker code must be
    updated in the SAME commit.

The test instantiates the canonical Pydantic schema, dumps it to JSON, and
feeds it into ``_build_fundamentals_narrative`` (via the worker's private
method). A successful narrative ``str`` (not ``None``) is the pass condition.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest

pytestmark = pytest.mark.contract


def _build_canonical_response() -> dict[str, object]:
    """Build a response by instantiating market-data's actual Pydantic schema.

    Doing it via the schema (rather than a hand-rolled dict) means a rename
    of any field in ``FundamentalsRecordResponse`` will surface here as an
    ImportError or ValidationError, NOT as a silent worker regression.
    """
    # Lazy import so the test only fails on missing market-data when actually
    # running the contract suite (knowledge-graph CI may not always include it).
    from market_data.api.schemas.fundamentals import (  # type: ignore[import-not-found]
        FundamentalsRecordResponse,
        FundamentalsResponse,
    )

    sec_id = "00000000-0000-0000-0000-000000000999"
    now = datetime(2026, 3, 31, tzinfo=UTC)
    records = [
        FundamentalsRecordResponse(
            id="11111111-1111-1111-1111-111111111111",
            security_id=sec_id,
            section="highlights",
            period_end=now,
            period_type="QUARTERLY",
            data={"RevenueTTM": 390_000_000_000.0, "PERatio": 28.0},
            source="eodhd",
            ingested_at=now,
        ),
        FundamentalsRecordResponse(
            id="22222222-2222-2222-2222-222222222222",
            security_id=sec_id,
            section="income_statement",
            period_end=now,
            period_type="QUARTERLY",
            data={
                "totalRevenue": 390_000_000_000.0,
                "grossProfit": 173_000_000_000.0,
                "netIncome": 98_700_000_000.0,
            },
            source="eodhd",
            ingested_at=now,
        ),
        FundamentalsRecordResponse(
            id="33333333-3333-3333-3333-333333333333",
            security_id=sec_id,
            section="technicals_snapshot",
            period_end=now,
            period_type="QUARTERLY",
            data={"Price": 189.0, "52WeekHigh": 200.0, "52WeekLow": 130.0},
            source="eodhd",
            ingested_at=now,
        ),
    ]
    return FundamentalsResponse(security_id=sec_id, records=records).model_dump(mode="json")


@pytest.mark.asyncio
async def test_worker_parses_real_fundamentals_response_shape() -> None:
    """The worker MUST produce a non-None narrative + None failure_reason for the
    canonical market-data response.

    Mirrors the read path of ``_build_fundamentals_narrative``:
      1. Worker calls ``http.get(/api/v1/fundamentals/{id})`` and gets 200.
      2. Worker parses JSON → walks ``records[]`` by section.
      3. Builder produces a multi-line narrative.

    Regression intent: if the schema mismatch returns (the F-DB-005 class of
    bug), this test will see ``narrative is None`` and the typed failure
    reason ``fundamentals_missing_sections`` — flagged loudly to CI.
    """
    from knowledge_graph.infrastructure.workers.fundamentals_refresh import (
        FundamentalsRefreshWorker,
    )

    # Build the worker with a stubbed http client. The real-shape payload
    # comes from market-data's own Pydantic schema (see _build_canonical_response
    # above) so any future field rename surfaces here.
    payload = _build_canonical_response()

    resp = MagicMock()
    resp.status_code = 200
    resp.content = b"{}"
    resp.json = MagicMock(return_value=payload)

    http = AsyncMock()
    http.get = AsyncMock(return_value=resp)

    # No DB/Valkey dependencies for the narrative-build path — we exercise
    # only ``_build_fundamentals_narrative``. We construct the worker with
    # the minimum required collaborators.
    sf = MagicMock()
    llm = AsyncMock()
    worker = FundamentalsRefreshWorker(
        sf,
        llm,
        "http://market-data:8003",
        http_client=http,
    )

    entity_id = UUID("00000000-0000-0000-0000-000000000042")
    entity_row = {"canonical_name": "Apple Inc.", "entity_type": "financial_instrument"}
    narrative, failure_reason = await worker._build_fundamentals_narrative(
        entity_id, "AAPL", entity_row, http, entity_id
    )

    assert failure_reason is None, (
        f"Expected None failure_reason for canonical shape, got {failure_reason}. "
        "This means the worker can no longer parse the production "
        "market-data /fundamentals/{id} response — F-DB-005 has regressed."
    )
    assert narrative is not None, (
        "Expected a non-None narrative for the canonical shape. "
        "Narrative=None means the worker's records[] walker is broken."
    )
    # Specific anchors so a regression that silently produces a header-only
    # narrative (the F-DB-005 surface) is caught:
    assert "Apple Inc." in narrative
    assert "Revenue" in narrative  # Revenue: $390.00B...
    assert "P/E" in narrative or "Margin" in narrative  # At least one ratio rendered


@pytest.mark.asyncio
async def test_worker_classifies_schema_mismatch_loudly() -> None:
    """If market-data ever returns the OLD flat shape, the worker must classify
    it as ``fundamentals_schema_unparsable`` — NOT silently fall through.

    This is the inverse of the previous test: it locks in the structural
    error class so a future "lying test" cannot reappear (BP-590).
    """
    from knowledge_graph.infrastructure.workers.fundamentals_refresh import (
        FundamentalsRefreshError,
        FundamentalsRefreshWorker,
    )

    # Old flat shape — what the lying unit tests used to stub.
    bad_payload = {"revenue_usd_millions": 390000.0, "price": 189.0}

    resp = MagicMock()
    resp.status_code = 200
    resp.content = b"{}"
    resp.json = MagicMock(return_value=bad_payload)

    http = AsyncMock()
    http.get = AsyncMock(return_value=resp)

    sf = MagicMock()
    llm = AsyncMock()
    worker = FundamentalsRefreshWorker(sf, llm, "http://market-data:8003", http_client=http)

    entity_id = UUID("00000000-0000-0000-0000-000000000042")
    entity_row = {"canonical_name": "Apple Inc.", "entity_type": "financial_instrument"}
    narrative, failure_reason = await worker._build_fundamentals_narrative(
        entity_id, "AAPL", entity_row, http, entity_id
    )

    assert narrative is None
    assert failure_reason == FundamentalsRefreshError.SCHEMA_UNPARSABLE.value, (
        f"Expected SCHEMA_UNPARSABLE for flat-shape response, got {failure_reason}. "
        "If this changes, the structural error classification is regressing."
    )
