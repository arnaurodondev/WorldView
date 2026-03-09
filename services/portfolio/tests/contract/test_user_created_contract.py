"""Contract test: user.created Avro schema."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import fastavro
import pytest
from portfolio.domain.events import UserCreated
from portfolio.messaging.mapper import user_created_to_dict

pytestmark = pytest.mark.contract

_SCHEMA_DIR = Path(__file__).parent.parent.parent / "src/portfolio/messaging/schemas"


def _load_schema(filename: str):  # type: ignore[no-untyped-def]
    path = _SCHEMA_DIR / filename
    return fastavro.parse_schema(json.loads(path.read_text()))


def test_user_created_valid_schema() -> None:
    """user.created mapper output must be valid against its Avro schema."""
    parsed_schema = _load_schema("user.created.avsc")

    tenant_id = uuid4()
    user_id = uuid4()
    event = UserCreated(tenant_id=tenant_id, user_id=user_id, email="alice@example.com")
    output = user_created_to_dict(event)

    fastavro.validate(output, parsed_schema)
