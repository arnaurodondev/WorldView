"""Identity outbox mapper — payloads are already serialized dicts."""

from __future__ import annotations

from typing import Any


def outbox_record_to_kafka_value(payload: dict[str, Any]) -> dict[str, Any]:
    """Return *payload* unchanged (identity mapper for pre-serialized outbox records)."""
    return payload
