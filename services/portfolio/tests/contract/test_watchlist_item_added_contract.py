"""Contract test: watchlist.item_added Avro schema round-trip."""

from __future__ import annotations

import io
import json
from pathlib import Path
from uuid import uuid4

import fastavro
import pytest
from portfolio.application.messaging.mapper import watchlist_item_added_to_dict
from portfolio.domain.events import WatchlistItemAdded

pytestmark = pytest.mark.contract

_SCHEMA_DIR = Path(__file__).parent.parent.parent / "src/portfolio/infrastructure/messaging/schemas"


def _load_schema(filename: str):  # type: ignore[no-untyped-def]
    path = _SCHEMA_DIR / filename
    return fastavro.parse_schema(json.loads(path.read_text()))


def _round_trip(schema, record: dict) -> dict:  # type: ignore[type-arg]
    buf = io.BytesIO()
    fastavro.schemaless_writer(buf, schema, record)
    buf.seek(0)
    return fastavro.schemaless_reader(buf, schema)  # type: ignore[return-value]


def test_watchlist_item_added_valid_schema() -> None:
    """watchlist.item_added mapper output is valid against its Avro schema."""
    schema = _load_schema("watchlist.item_added.v1.avsc")
    tenant_id = uuid4()
    entity_id = uuid4()

    event = WatchlistItemAdded(
        tenant_id=tenant_id,
        watchlist_id=uuid4(),
        user_id=uuid4(),
        entity_id=entity_id,
        entity_type="company",
    )
    output = watchlist_item_added_to_dict(event)
    fastavro.validate(output, schema)


def test_watchlist_item_added_round_trip() -> None:
    """Encode → decode preserves all fields."""
    schema = _load_schema("watchlist.item_added.v1.avsc")
    tenant_id = uuid4()
    watchlist_id = uuid4()
    user_id = uuid4()
    entity_id = uuid4()

    event = WatchlistItemAdded(
        tenant_id=tenant_id,
        watchlist_id=watchlist_id,
        user_id=user_id,
        entity_id=entity_id,
        entity_type="company",
    )
    original = watchlist_item_added_to_dict(event)
    recovered = _round_trip(schema, original)

    assert recovered["event_type"] == "watchlist.item_added"
    assert recovered["watchlist_id"] == str(watchlist_id)
    assert recovered["user_id"] == str(user_id)
    assert recovered["entity_id"] == str(entity_id)
    assert recovered["entity_type"] == "company"
    assert recovered["tenant_id"] == str(tenant_id)
