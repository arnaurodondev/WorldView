"""Contract test: transaction.recorded Avro schema."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import fastavro
import pytest
from portfolio.application.messaging.mapper import transaction_recorded_to_dict
from portfolio.domain.events import TransactionRecorded

pytestmark = pytest.mark.contract

_SCHEMA_DIR = Path(__file__).parent.parent.parent / "src/portfolio/infrastructure/messaging/schemas"


def _load_schema(filename: str):  # type: ignore[no-untyped-def]
    path = _SCHEMA_DIR / filename
    return fastavro.parse_schema(json.loads(path.read_text()))


def test_transaction_recorded_valid_schema() -> None:
    """transaction.recorded mapper output must be valid against its Avro schema."""
    parsed_schema = _load_schema("transaction.recorded.v1.avsc")

    event = TransactionRecorded(
        tenant_id=uuid4(),
        transaction_id=uuid4(),
        portfolio_id=uuid4(),
        instrument_id=uuid4(),
        transaction_type="buy",
        direction="inflow",
        quantity="10.00000000",
        price="150.00000000",
        fees="0.50000000",
        currency="USD",
        executed_at="2025-01-01T00:00:00+00:00",
    )
    output = transaction_recorded_to_dict(event)
    fastavro.validate(output, parsed_schema)
