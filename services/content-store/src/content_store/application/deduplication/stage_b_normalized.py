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

    from content_store.application.ports.repositories import DedupHashRepositoryPort

# UTM and tracking parameters to strip from URLs.
#
# Source list: ClearURLs project (https://rules2.clearurls.xyz/) — the canonical
# community-maintained registry of advertising / analytics / share-tracking URL
# parameters. We cherry-pick the subset that:
#   1. Is observed in real news-syndication / social-share URLs, AND
#   2. Has no semantic effect on the article content the URL resolves to.
#
# Adding to this list improves Stage B normalized-hash dedup recall (BUG-006 /
# TASK-W2-01) because near-duplicate URLs that differ ONLY in tracking params
# would otherwise hash to different canonical forms and slip past dedup.
#
# Keep alphabetically sorted for readability and to make future additions easy
# to review in a diff.
_TRACKING_PARAMS = frozenset(
    {
        "_ga",  # Google Analytics cross-domain linker
        "_gl",  # Google Analytics cross-domain linker (modern variant)
        "_hsenc",  # HubSpot email engagement token
        "_hsmi",  # HubSpot email message id
        "dclid",  # Google Display Click Identifier
        "fbclid",  # Facebook click identifier
        "gclid",  # Google Ads click identifier
        "gclsrc",  # Google Ads click source
        "igshid",  # Instagram share id
        "mc_cid",  # Mailchimp campaign id
        "mc_eid",  # Mailchimp subscriber/email id
        "msclkid",  # Microsoft Ads click identifier
        "oly_anon_id",  # Omeda anonymous visitor id
        "oly_enc_id",  # Omeda encrypted visitor id
        "ref",  # Generic referrer tag
        "referrer",  # Generic referrer tag (long form)
        "s_cid",  # Adobe SiteCatalyst campaign id
        "utm_campaign",  # UTM campaign name
        "utm_content",  # UTM ad/content variant
        "utm_medium",  # UTM medium (email/social/cpc/...)
        "utm_source",  # UTM traffic source
        "utm_term",  # UTM paid-search keyword
        "vero_conv",  # Vero conversion id
        "vero_id",  # Vero subscriber id
        "wickedid",  # WickedReports click id
        "yclid",  # Yandex Ads click identifier
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
    dedup_repo: DedupHashRepositoryPort,
    tenant_id: UUID | None = None,
) -> tuple[str, DeduplicationDecision | None]:
    """Run Stage B dedup: normalized hash check.

    Args:
        url: Original article URL.
        cleaned_text: Cleaned/normalized text content.
        dedup_repo: Repository for hash lookups.
        tenant_id: PLAN-0086 Wave C-1 — scope the dedup check to the given tenant
            namespace. None = global public content space.

    Returns:
        Tuple of (normalized_hash, decision_or_None). If decision is not None,
        the article is a normalized duplicate and should be suppressed.
    """
    norm_url = normalize_url(url)
    normalized_hash = compute_normalized_hash(norm_url, cleaned_text)

    existing_doc_id: UUID | None = await dedup_repo.check_exists(
        "normalized_sha256",
        normalized_hash,
        tenant_id=tenant_id,
    )

    if existing_doc_id is not None:
        return normalized_hash, DeduplicationDecision(
            outcome=DedupOutcome.DUPLICATE_NORMALIZED,
            matched_doc_id=existing_doc_id,
            stage="stage_b",
        )

    return normalized_hash, None
