"""Shared type aliases for domain identifiers."""

from __future__ import annotations

from typing import Any, NewType
from uuid import UUID

TenantId = NewType("TenantId", UUID)
UserId = NewType("UserId", UUID)
InstrumentId = NewType("InstrumentId", UUID)
TransactionId = NewType("TransactionId", UUID)
EventId = NewType("EventId", str)
TopicName = NewType("TopicName", str)
JsonDict = dict[str, Any]
