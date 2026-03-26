"""Contract test: instrument_ref.created Avro schema."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import fastavro
import pytest
from portfolio.application.messaging.mapper import instrument_ref_created_to_dict
from portfolio.domain.events import InstrumentRefCreated

pytestmark = pytest.mark.contract

_SCHEMA_DIR = Path(__file__).parent.parent.parent / "src/portfolio/infrastructure/messaging/schemas"


def _load_schema(filename: str):  # type: ignore[no-untyped-def]
    path = _SCHEMA_DIR / filename
    return fastavro.parse_schema(json.loads(path.read_text()))


def test_instrument_ref_created_valid_schema() -> None:
    """instrument_ref.created mapper output must be valid against its Avro schema."""
    parsed_schema = _load_schema("instrument_ref.created.v1.avsc")

    event = InstrumentRefCreated(
        tenant_id=uuid4(),
        instrument_id=uuid4(),
        symbol="AAPL",
        exchange="NASDAQ",
        name="Apple Inc.",
        asset_class="equity",
        currency="USD",
    )
    output = instrument_ref_created_to_dict(event)
    fastavro.validate(output, parsed_schema)


def test_instrument_ref_created_minimal_schema() -> None:
    """instrument_ref.created with null optional fields passes validation."""
    parsed_schema = _load_schema("instrument_ref.created.v1.avsc")

    event = InstrumentRefCreated(
        tenant_id=uuid4(),
        instrument_id=uuid4(),
        symbol="TSLA",
        exchange="NASDAQ",
        name=None,
        asset_class=None,
        currency=None,
    )
    output = instrument_ref_created_to_dict(event)
    fastavro.validate(output, parsed_schema)
