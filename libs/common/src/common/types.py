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

# --- Ingestion pipeline cross-service identifiers ---
# Only types referenced by 2+ services live here.
# Service-local IDs (SourceId, SectionId, etc.) belong in each service's domain layer.

DocumentId = NewType("DocumentId", UUID)
"""Canonical document ID. Created by S5; referenced by S6 (enrichment) and S7 (evidence)."""

EntityId = NewType("EntityId", UUID)
"""Canonical entity ID. Resolved by S6; used by S7 (graph) and S10 (alert fan-out)."""

UrlHash = NewType("UrlHash", str)
"""SHA-256 hex digest of a normalised article URL. Computed by S4; checked by S5 for dedup."""

MinIOKey = NewType("MinIOKey", str)
"""MinIO object key. S4 writes bronze keys; S5 reads bronze + writes silver; S6 reads silver."""
