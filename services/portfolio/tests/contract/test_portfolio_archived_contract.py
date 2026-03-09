"""Contract test: portfolio.archived Avro schema."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import fastavro
import pytest
from portfolio.domain.events import PortfolioArchived
from portfolio.messaging.mapper import portfolio_archived_to_dict

pytestmark = pytest.mark.contract

_SCHEMA_DIR = Path(__file__).parent.parent.parent / "src/portfolio/messaging/schemas"


def _load_schema(filename: str):  # type: ignore[no-untyped-def]
    path = _SCHEMA_DIR / filename
    return fastavro.parse_schema(json.loads(path.read_text()))


def test_portfolio_archived_valid_schema() -> None:
    """portfolio.archived mapper output must be valid against its Avro schema."""
    parsed_schema = _load_schema("portfolio.archived.avsc")

    event = PortfolioArchived(
        tenant_id=uuid4(),
        portfolio_id=uuid4(),
    )
    output = portfolio_archived_to_dict(event)
    fastavro.validate(output, parsed_schema)
