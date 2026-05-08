from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class NlpDocumentReady:
    event_id: str
    event_type: str
    schema_version: int
    occurred_at: str
    doc_id: str
    tenant_id: str
    chunk_count: int
    word_count: int
