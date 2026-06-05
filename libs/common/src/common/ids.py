"""ID generation utilities."""

from __future__ import annotations

import uuid
from typing import cast

import uuid6 as _uuid6  # type: ignore[import-not-found]  # imported at module level with alias to avoid shadowing stdlib uuid
from ulid import ULID

# RFC 4122 DNS namespace UUID — chosen as the worldview-wide stable namespace
# for all deterministic UUID5 derivations.  Using the well-known DNS namespace
# (rather than a random one) means the function output is reproducible from
# first principles by any reader who knows the input parts.
_WORLDVIEW_NS = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")

# Public / legacy-passthrough tenant sentinel.
#
# Used as a fallback tenant_id for messages that predate multi-tenant
# stamping (PLAN-0086 Wave A-1) and therefore arrive on Kafka without a
# ``tenant_id`` field in the Avro payload or headers. Without this sentinel
# every such legacy message fails the NOT NULL constraint added in nlp_pipeline
# migration 0020 and stalls the article consumer in a tight retry loop
# (BP-575 / PLAN-0096 Wave 4). The value is deliberately the all-zero UUID
# so it is trivially recognisable in dumps and queries.
#
# Do NOT use this for new code that has a real tenant on hand — it exists
# solely to drain in-flight pre-migration backlogs without DLQ-ing them.
PUBLIC_TENANT_ID: uuid.UUID = uuid.UUID("00000000-0000-0000-0000-000000000000")


def new_uuid() -> uuid.UUID:
    """Generate a new random UUID v4."""
    return uuid.uuid4()


def new_uuid_str() -> str:
    """Generate a new random UUID v4 as a string."""
    return str(uuid.uuid4())


def new_ulid() -> str:
    """Generate a new time-sortable ULID as a string."""
    return str(ULID())


def new_uuid7() -> uuid.UUID:
    """Generate a new time-sortable UUIDv7 (RFC 9562).

    Use for all new entity primary keys in the ingestion pipeline
    (documents, entities, relations, alerts, sections, chunks, etc.).
    UUIDv7 is monotonically increasing within a millisecond, making it
    safe for time-based ordering without a separate ``created_at`` index scan.

    Do NOT use for Kafka event IDs — use ``new_ulid()`` for those.
    Do NOT use in existing services (portfolio, market-ingestion) that already
    have UUIDv4 primary keys in production — changing would break existing rows.
    """
    return cast("uuid.UUID", _uuid6.uuid7())


def new_uuid7_str() -> str:
    """Generate a new time-sortable UUIDv7 as a hyphenated string.

    Convenience wrapper for contexts that require a str (e.g., Avro payloads,
    HTTP response bodies). Equivalent to ``str(new_uuid7())``.
    """
    return str(new_uuid7())


def uuid5_from_parts(*parts: str) -> str:
    """Deterministic UUID5 from ordered string parts. Stable across restarts.

    Same inputs always produce the same UUID; reordering the parts produces a
    different UUID (the ``"|"`` separator preserves boundaries so that
    ``("ab", "c")`` and ``("a", "bc")`` cannot collide).

    Used for ``event_id`` derivation in ``graph_write`` (DEF-025) so that
    Kafka replays of the same enriched-article message produce the same
    ``event_id`` and land on ``ON CONFLICT DO NOTHING`` instead of inserting
    duplicate ``events`` / ``temporal_events`` rows.

    The namespace is fixed (``_WORLDVIEW_NS``); callers control identity by
    choosing the input parts.

    Args:
    ----
        *parts: Ordered string parts that together identify the row uniquely.
            For events this is ``(doc_id, subject_entity_id, event_type)``.

    Returns:
    -------
        A hyphenated UUID5 string suitable for storing in a UUID column or
        passing to Avro / JSON payloads.

    """
    composite = "|".join(parts)
    return str(uuid.uuid5(_WORLDVIEW_NS, composite))
