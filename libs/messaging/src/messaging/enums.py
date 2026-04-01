"""Shared enums for messaging infrastructure.

These enums are canonical definitions used across multiple services.
Services should import from here rather than defining their own copies.
"""

from __future__ import annotations

from enum import StrEnum


class OutboxStatus(StrEnum):
    """Transactional outbox event lifecycle status.

    Canonical status progression::

        PENDING → PROCESSING → DELIVERED
                             → FAILED → DEAD_LETTER

    Used by: S1 (Portfolio), S2 (Market Ingestion), S4 (Content Ingestion),
    S5 (Content Store), and any future service implementing the outbox pattern.
    """

    PENDING = "pending"
    PROCESSING = "processing"
    DELIVERED = "delivered"
    FAILED = "failed"
    DEAD_LETTER = "dead_letter"
