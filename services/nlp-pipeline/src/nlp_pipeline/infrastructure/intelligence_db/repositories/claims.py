"""Claims repository — writes to intelligence_db via nlp_db outbox pattern.

Claims are NEVER written directly to intelligence_db. They are serialized
into the nlp_db outbox and dispatched by the S6 outbox dispatcher.
This preserves atomicity — outbox pattern (no dual writes).
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from nlp_pipeline.infrastructure.nlp_db.repositories.outbox import OutboxRepository

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

_TOPIC_CLAIM_EXTRACTED = "claim.extracted"


class ClaimsRepository:
    """Write claims via the nlp_db outbox — never directly to intelligence_db (BP-005 pattern)."""

    def __init__(self, nlp_session: AsyncSession) -> None:
        self._outbox = OutboxRepository(nlp_session)

    async def write_via_outbox(
        self,
        doc_id: UUID,
        entity_id: UUID,
        claim_type: str,
        polarity: str,
        confidence: float,
        evidence_text: str,
        evidence_date: datetime,
        claimer_entity_id: UUID | None = None,
    ) -> None:
        """Enqueue a claim into the nlp_db outbox for dispatch to intelligence_db."""
        payload = {
            "doc_id": str(doc_id),
            "entity_id": str(entity_id),
            "claim_type": claim_type,
            "polarity": polarity,
            "confidence": confidence,
            "evidence_text": evidence_text,
            "evidence_date": evidence_date.isoformat(),
            "claimer_entity_id": str(claimer_entity_id) if claimer_entity_id else None,
        }
        # Write as JSON bytes — dispatcher will re-serialize for Avro
        payload_bytes = json.dumps(payload).encode()
        await self._outbox.add(
            topic=_TOPIC_CLAIM_EXTRACTED,
            partition_key=str(entity_id),
            payload_avro=payload_bytes,
        )
