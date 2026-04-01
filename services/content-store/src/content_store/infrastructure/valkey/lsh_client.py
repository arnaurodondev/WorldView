"""Valkey LSH client for near-duplicate detection (Stage C).

Uses 4 bands x 32 rows with sorted sets for time-windowed candidate lookup.
Tier 1: band hash → candidate doc IDs from Valkey.
Tier 2: exact Jaccard comparison against candidate signatures.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

import structlog

from content_store.application.ports.lsh import LSHClientPort
from content_store.domain.entities import (
    CorroborationPolicy,
    DeduplicationDecision,
    get_thresholds,
)
from content_store.domain.enums import DedupOutcome

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from uuid import UUID

    from messaging.valkey.client import ValkeyClient

logger = structlog.get_logger(__name__)  # type: ignore[no-any-return]

# ── LSH time windows per source type (seconds) ───────────────────────────────

_SOURCE_TTL_DAYS: dict[str, int] = {
    "eodhd": 7,
    "newsapi": 7,
    "sec_edgar": 180,
    "finnhub": 60,
    "manual": 30,
}

# Default TTL for unknown source types
_DEFAULT_TTL_DAYS = 30


@dataclass(frozen=True)
class LSHConfig:
    """Configuration for the LSH index."""

    num_bands: int = 4
    rows_per_band: int = 32
    num_perm: int = 128


@dataclass(frozen=True)
class LSHCandidate:
    """A candidate document found via LSH band lookup."""

    doc_id: str
    source_type: str
    signature: list[int]


def _band_hash(signature: list[int], band_idx: int, rows_per_band: int) -> str:
    """Compute MD5 hash for a band slice of the signature.

    Args:
        signature: Full MinHash signature (list[int]).
        band_idx: Band index (0-based).
        rows_per_band: Number of rows per band.

    Returns:
        Hex-encoded MD5 hash of the band slice.
    """
    start = band_idx * rows_per_band
    end = start + rows_per_band
    band_slice = signature[start:end]
    # MD5 of the concatenated integer bytes
    h = hashlib.md5()  # noqa: S324
    for v in band_slice:
        h.update(v.to_bytes(8, byteorder="big", signed=True))
    return h.hexdigest()


def _sorted_set_key(band_idx: int, bucket_hash: str, source_type: str) -> str:
    """Build the Valkey sorted set key for an LSH band bucket.

    Key format: lsh:band:{band_id}:{bucket_hash}:{source_type}
    """
    return f"lsh:band:{band_idx}:{bucket_hash}:{source_type}"


def _ttl_seconds(source_type: str) -> int:
    """Return TTL in seconds for a source type."""
    days = _SOURCE_TTL_DAYS.get(source_type, _DEFAULT_TTL_DAYS)
    return days * 86400


def compute_exact_jaccard(sig_a: list[int], sig_b: list[int]) -> float:
    """Compute exact Jaccard similarity from two MinHash signatures.

    Jaccard = count(sig_a[i] == sig_b[i]) / len(signature)

    Args:
        sig_a: First signature.
        sig_b: Second signature.

    Returns:
        Jaccard similarity in [0.0, 1.0].
    """
    if len(sig_a) != len(sig_b):
        return 0.0
    if not sig_a:
        return 0.0
    matches = sum(1 for a, b in zip(sig_a, sig_b, strict=False) if a == b)
    return matches / len(sig_a)


class ValkeyLSHClient(LSHClientPort):
    """Valkey-backed LSH index for near-duplicate detection.

    Uses sorted sets with Unix timestamp scores for time-windowed lookups.
    Each band has one sorted set per (bucket_hash, source_type) combination.
    """

    def __init__(
        self,
        valkey: ValkeyClient,
        config: LSHConfig | None = None,
    ) -> None:
        self._valkey = valkey
        self._config = config or LSHConfig()

    async def query(
        self,
        signature: list[int],
        source_type: str,
        source_name: str | None = None,
        fetch_signature: Callable[[str], Awaitable[list[int] | None]] | None = None,
    ) -> DeduplicationDecision:
        """Query the LSH index for near-duplicate candidates.

        Tier 1: band hash lookup in Valkey sorted sets.
        Tier 2: exact Jaccard comparison with per-source thresholds.

        Args:
            signature: MinHash signature (list[int], length = num_perm).
            source_type: Source type for threshold selection and TTL window.
            source_name: Source name (for same-source detection).
            fetch_signature: Async callable (doc_id: str) -> list[int] | None
                to fetch stored signatures for Tier 2 comparison.

        Returns:
            DeduplicationDecision with outcome and best match info.
        """
        thresholds = get_thresholds(source_type)
        window_seconds = _ttl_seconds(source_type)
        now = time.time()
        min_score = now - window_seconds

        # Tier 1: Collect candidate doc IDs from all bands
        candidate_ids: set[str] = set()
        for band_idx in range(self._config.num_bands):
            bucket_hash = _band_hash(signature, band_idx, self._config.rows_per_band)

            # Query ALL source types for cross-source corroboration
            for st in _SOURCE_TTL_DAYS:
                key = _sorted_set_key(band_idx, bucket_hash, st)
                try:
                    members = await self._valkey._redis.zrangebyscore(  # type: ignore[union-attr]
                        key,
                        min_score,
                        "+inf",
                    )
                    for m in members:
                        # Members are stored as "doc_id:source_name"
                        candidate_ids.add(str(m))
                except Exception:
                    logger.warning("lsh_band_query_failed", band=band_idx, key=key)

        if not candidate_ids or fetch_signature is None:
            return DeduplicationDecision(outcome=DedupOutcome.UNIQUE, stage="stage_c")

        # Tier 2: Exact Jaccard computation against candidates
        best_jaccard = 0.0
        best_doc_id: str | None = None
        best_same_source = False

        for cid in candidate_ids:
            # Parse "doc_id:source_name" format
            parts = cid.split(":", 1)
            cand_doc_id = parts[0]
            cand_source_name = parts[1] if len(parts) > 1 else ""

            cand_sig = await fetch_signature(cand_doc_id)
            if cand_sig is None:
                continue

            jaccard = compute_exact_jaccard(signature, cand_sig)
            if jaccard > best_jaccard:
                best_jaccard = jaccard
                best_doc_id = cand_doc_id
                best_same_source = source_name is not None and cand_source_name == source_name

        if best_doc_id is None:
            return DeduplicationDecision(outcome=DedupOutcome.UNIQUE, stage="stage_c")

        # Apply corroboration policy
        outcome = CorroborationPolicy.classify(best_jaccard, best_same_source, thresholds)

        from uuid import UUID

        return DeduplicationDecision(
            outcome=outcome,
            jaccard_score=best_jaccard,
            matched_doc_id=UUID(best_doc_id),
            stage="stage_c",
        )

    async def index(
        self,
        doc_id: UUID,
        signature: list[int],
        source_type: str,
        source_name: str = "",
    ) -> None:
        """Add a document's signature to the LSH index.

        Stores the doc_id in sorted sets for each band, with Unix timestamp
        as score for time-window expiry.

        Args:
            doc_id: Document UUID.
            signature: MinHash signature (list[int]).
            source_type: Source type (for TTL and key partitioning).
            source_name: Source name (stored with doc_id for same-source detection).
        """
        ttl = _ttl_seconds(source_type)
        now = time.time()
        member = f"{doc_id!s}:{source_name}"

        for band_idx in range(self._config.num_bands):
            bucket_hash = _band_hash(signature, band_idx, self._config.rows_per_band)
            key = _sorted_set_key(band_idx, bucket_hash, source_type)

            try:
                await self._valkey._redis.zadd(key, {member: now})  # type: ignore[union-attr]
                await self._valkey._redis.expire(key, ttl)  # type: ignore[union-attr]
            except Exception:
                logger.warning(
                    "lsh_index_failed",
                    band=band_idx,
                    doc_id=str(doc_id),
                )
