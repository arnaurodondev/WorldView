"""Stage A — Exact raw-bytes hash deduplication.

Computes SHA-256 of the raw bytes and checks against the dedup_hashes table.
If found, the article is an exact duplicate.
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

from content_store.domain.entities import DeduplicationDecision
from content_store.domain.enums import DedupOutcome

if TYPE_CHECKING:
    from uuid import UUID

    from content_store.infrastructure.db.repositories.dedup import DedupHashRepository


def compute_raw_hash(raw_bytes: bytes) -> str:
    """Compute SHA-256 hash of raw bytes.

    Args:
        raw_bytes: The raw article content.

    Returns:
        Hex-encoded SHA-256 hash string.
    """
    return hashlib.sha256(raw_bytes).hexdigest()


async def check_stage_a(
    raw_bytes: bytes,
    dedup_repo: DedupHashRepository,
) -> tuple[str, DeduplicationDecision | None]:
    """Run Stage A dedup: exact raw hash check.

    Args:
        raw_bytes: Raw article content bytes.
        dedup_repo: Repository for hash lookups.

    Returns:
        Tuple of (raw_hash, decision_or_None). If decision is not None,
        the article is a duplicate and should be suppressed.
    """
    raw_hash = compute_raw_hash(raw_bytes)
    existing_doc_id: UUID | None = await dedup_repo.check_exists("raw_sha256", raw_hash)

    if existing_doc_id is not None:
        return raw_hash, DeduplicationDecision(
            outcome=DedupOutcome.DUPLICATE_EXACT,
            matched_doc_id=existing_doc_id,
            stage="stage_a",
        )

    return raw_hash, None
