"""Bucket tier enum for safer storage adapter usage.

The platform has three storage tiers — bronze (raw provider payloads),
silver (canonicalized), gold (analysis-ready). Each tier is a distinct
MinIO bucket. Passing raw strings to :meth:`storage.s3_adapter.S3ObjectStorage.put_bytes`
/ :meth:`~storage.s3_adapter.S3ObjectStorage.get_bytes` makes it easy to
typo a bucket name; the enum gives callers a typed alias that matches the
canonical bucket names used by the platform (``worldview-bronze``,
``worldview-silver``, ``worldview-gold``).

Existing string callers continue to work unchanged — the enum is opt-in
and the adapter signatures accept ``str | BucketTier``.

Example::

    from storage import BucketTier

    await store.put_bytes(BucketTier.BRONZE, key, data)
    # equivalent to:
    await store.put_bytes("worldview-bronze", key, data)
"""

from __future__ import annotations

from enum import StrEnum


class BucketTier(StrEnum):
    """Canonical storage tier alias.

    Values match the canonical MinIO bucket names used across the platform.
    Because :class:`enum.StrEnum` subclasses :class:`str`, instances coerce
    cleanly to strings via ``str(tier)`` and compare equal to their string
    value, which is what the boto3 client expects for the ``Bucket=`` arg.
    """

    BRONZE = "worldview-bronze"
    """Raw provider payloads — never mutated after first write."""

    SILVER = "worldview-silver"
    """Canonicalized records — schema-validated, normalized."""

    GOLD = "worldview-gold"
    """Analysis-ready aggregates and derived datasets."""
