"""Contract test: portfolio.renamed Avro schema."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import fastavro
import pytest
from portfolio.application.messaging.mapper import portfolio_renamed_to_dict
from portfolio.domain.events import PortfolioRenamed

pytestmark = pytest.mark.contract

_SCHEMA_DIR = Path(__file__).parent.parent.parent / "src/portfolio/infrastructure/messaging/schemas"


def _load_schema(filename: str):  # type: ignore[no-untyped-def]
    path = _SCHEMA_DIR / filename
    return fastavro.parse_schema(json.loads(path.read_text()))


def test_portfolio_renamed_valid_schema() -> None:
    """portfolio.renamed mapper output must be valid against its Avro schema."""
    parsed_schema = _load_schema("portfolio.renamed.v1.avsc")

    event = PortfolioRenamed(
        tenant_id=uuid4(),
        portfolio_id=uuid4(),
        old_name="Old Name",
        new_name="New Name",
    )
    output = portfolio_renamed_to_dict(event)
    fastavro.validate(output, parsed_schema)
