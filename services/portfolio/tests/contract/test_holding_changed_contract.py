"""Contract test: holding.changed Avro schema."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import fastavro
import pytest
from portfolio.application.messaging.mapper import holding_changed_to_dict
from portfolio.domain.events import HoldingChanged

pytestmark = pytest.mark.contract

_SCHEMA_DIR = Path(__file__).parent.parent.parent / "src/portfolio/messaging/schemas"


def _load_schema(filename: str):  # type: ignore[no-untyped-def]
    path = _SCHEMA_DIR / filename
    return fastavro.parse_schema(json.loads(path.read_text()))


def test_holding_changed_valid_schema() -> None:
    """holding.changed mapper output must be valid against its Avro schema."""
    parsed_schema = _load_schema("holding.changed.v1.avsc")

    event = HoldingChanged(
        tenant_id=uuid4(),
        holding_id=uuid4(),
        portfolio_id=uuid4(),
        instrument_id=uuid4(),
        quantity="10.00000000",
        average_cost="150.00000000",
        currency="USD",
    )
    output = holding_changed_to_dict(event)
    fastavro.validate(output, parsed_schema)
