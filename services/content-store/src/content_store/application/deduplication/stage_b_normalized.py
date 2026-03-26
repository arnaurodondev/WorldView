"""Stage B — Normalized hash deduplication.

Computes SHA-256 of (normalized_url | cleaned_text.lower()) and checks
against the dedup_hashes table. Catches reformatted duplicates that differ
only in URL parameters or whitespace.
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from content_store.domain.entities import DeduplicationDecision
from content_store.domain.enums import DedupOutcome

if TYPE_CHECKING:
    from uuid import UUID

    from content_store.infrastructure.db.repositories.dedup import DedupHashRepository

# UTM and tracking parameters to strip from URLs
_TRACKING_PARAMS = frozenset(
    {
        "utm_source",
        "utm_medium",
        "utm_campaign",
        "utm_term",
        "utm_content",
        "fbclid",
        "gclid",
        "gclsrc",
        "dclid",
        "msclkid",
        "mc_cid",
        "mc_eid",
        "ref",
        "referrer",
    }
)


def normalize_url(url: str) -> str:
    """Normalize a URL for dedup comparison.

    - Lowercase scheme and host
    - Strip tracking/UTM parameters
    - Sort remaining query parameters
    - Remove trailing slash
    - Remove fragment

    Args:
        url: Original URL string.

    Returns:
        Normalized URL string.
    """
    if not url:
        return ""

    parsed = urlparse(url)
    scheme = parsed.scheme.lower()
    netloc = parsed.netloc.lower()
    path = parsed.path.rstrip("/") or "/"

    # Filter out tracking params and sort remaining
    params = parse_qs(parsed.query, keep_blank_values=True)
    filtered = sorted(
        ((k, sorted(v)) for k, v in params.items() if k.lower() not in _TRACKING_PARAMS),
        key=lambda item: item[0],
    )
    sorted_query = urlencode(filtered, doseq=True) if filtered else ""

    return urlunparse((scheme, netloc, path, "", sorted_query, ""))


def compute_normalized_hash(normalized_url: str, cleaned_text: str) -> str:
    """Compute SHA-256 of normalized_url + separator + lowercased cleaned text.

    Args:
        normalized_url: URL after normalization.
        cleaned_text: Text after extraction and normalization.

    Returns:
        Hex-encoded SHA-256 hash string.
    """
    combined = f"{normalized_url}|{cleaned_text.lower()}"
    return hashlib.sha256(combined.encode("utf-8")).hexdigest()


async def check_stage_b(
    url: str,
    cleaned_text: str,
    dedup_repo: DedupHashRepository,
) -> tuple[str, DeduplicationDecision | None]:
    """Run Stage B dedup: normalized hash check.

    Args:
        url: Original article URL.
        cleaned_text: Cleaned/normalized text content.
        dedup_repo: Repository for hash lookups.

    Returns:
        Tuple of (normalized_hash, decision_or_None). If decision is not None,
        the article is a normalized duplicate and should be suppressed.
    """
    norm_url = normalize_url(url)
    normalized_hash = compute_normalized_hash(norm_url, cleaned_text)

    existing_doc_id: UUID | None = await dedup_repo.check_exists(
        "normalized_sha256",
        normalized_hash,
    )

    if existing_doc_id is not None:
        return normalized_hash, DeduplicationDecision(
            outcome=DedupOutcome.DUPLICATE_NORMALIZED,
            matched_doc_id=existing_doc_id,
            stage="stage_b",
        )

    return normalized_hash, None
