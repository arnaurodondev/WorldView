"""Canonical entity model — knowledge-graph NER output."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from contracts.versions import ENTITY_SCHEMA_VERSION


@dataclass(frozen=True)
class CanonicalEntity:
    """Knowledge-graph entity extracted from an article (NER output, S6/S7).

    entity_type is kept as a plain string (not an enum) to remain flexible
    while the Intelligence service schema evolves. Application-layer validation
    should enforce allowed values (Person, Company, Location, Event).
    """

    entity_id: str
    entity_type: str
    name: str
    canonical_name: str
    source_article_id: str
    confidence: float
    metadata: dict[str, Any] = field(default_factory=dict)
    schema_version: int = field(default=ENTITY_SCHEMA_VERSION, init=False)

    @classmethod
    def from_dict(cls, d: dict) -> CanonicalEntity:
        return cls(
            entity_id=d["entity_id"],
            entity_type=d["entity_type"],
            name=d["name"],
            canonical_name=d["canonical_name"],
            source_article_id=d["source_article_id"],
            confidence=float(d["confidence"]),
            metadata=dict(d.get("metadata", {})),
        )

    def to_dict(self) -> dict:
        return {
            "entity_id": self.entity_id,
            "entity_type": self.entity_type,
            "name": self.name,
            "canonical_name": self.canonical_name,
            "source_article_id": self.source_article_id,
            "confidence": self.confidence,
            "metadata": dict(self.metadata),
            "schema_version": self.schema_version,
        }
