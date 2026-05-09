"""Canonical object key builder with validation."""

from __future__ import annotations

import dataclasses
import re

from storage.exceptions import InvalidObjectKeyError

# Pattern: {service}/{domain}/{resource_id}/{artifact}/{version}.{ext}
_KEY_PATTERN = re.compile(
    r"^[a-z][a-z0-9\-]+/"  # service
    r"[a-z][a-z0-9\-]+/"  # domain
    r"[A-Za-z0-9._/\-]+/"  # resource_id (flexible, may contain slashes)
    r"[a-z][a-z0-9\-]+/"  # artifact
    r"v\d+\.[a-z0-9]+$"  # version.ext
)

# Minimum segment pattern for individual component validation
_SLUG_RE = re.compile(r"^[a-z][a-z0-9\-]*$")
_VERSION_RE = re.compile(r"^v\d+$")
_EXT_RE = re.compile(r"^[a-z0-9]+$")


@dataclasses.dataclass(frozen=True)
class KeyComponents:
    """Parsed components of a canonical object storage key."""

    service: str
    domain: str
    resource_id: str
    artifact: str
    version: str
    extension: str

    @property
    def full_key(self) -> str:
        """Reconstruct the canonical key string."""
        return f"{self.service}/{self.domain}/{self.resource_id}/{self.artifact}/{self.version}.{self.extension}"


class KeyBuilder:
    """Builds, validates, and parses canonical object storage keys.

    Format: ``{service}/{domain}/{resource_id}/{artifact}/{version}.{extension}``

    Example: ``market-ingestion/ohlcv/AAPL.US/2024-01-01_2024-12-31/canonical/v2.parquet``
    """

    @staticmethod
    def build(
        service: str,
        domain: str,
        resource_id: str,
        artifact: str,
        version: str = "v1",
        extension: str = "parquet",
    ) -> str:
        """Build a canonical key and validate each component.

        Args:
            service: Service slug, e.g. ``"market-ingestion"``.
            domain: Domain slug, e.g. ``"ohlcv"``.
            resource_id: Resource identifier; may contain ``/``, ``.``, ``_``, ``-``.
            artifact: Artifact type slug, e.g. ``"canonical"``.
            version: Version string, e.g. ``"v1"``.  Must match ``v{N}``.
            extension: File extension without leading dot, e.g. ``"parquet"``.

        Returns:
            A validated canonical key string.

        Raises:
            :exc:`storage.exceptions.InvalidObjectKeyError`: If any component is malformed.
        """
        KeyBuilder._validate_slug(service, "service")
        KeyBuilder._validate_slug(domain, "domain")
        KeyBuilder._validate_slug(artifact, "artifact")
        KeyBuilder._validate_version(version)
        KeyBuilder._validate_extension(extension)
        if not resource_id:
            raise InvalidObjectKeyError("resource_id must not be empty")

        key = f"{service}/{domain}/{resource_id}/{artifact}/{version}.{extension}"
        return key

    @staticmethod
    def validate(key: str) -> None:
        """Validate a full key string against the naming convention.

        Args:
            key: Full key string to validate.

        Raises:
            :exc:`storage.exceptions.InvalidObjectKeyError`: If the key is malformed.
        """
        if not _KEY_PATTERN.match(key):
            raise InvalidObjectKeyError(f"Key does not match expected pattern: {key!r}")

    @staticmethod
    def parse(key: str) -> KeyComponents:
        """Parse a canonical key into its components.

        Args:
            key: Full canonical key string.

        Returns:
            A :class:`KeyComponents` dataclass.

        Raises:
            :exc:`storage.exceptions.InvalidObjectKeyError`: If the key is malformed.
        """
        KeyBuilder.validate(key)
        # Split into fixed parts: service / domain / ...resource_id... / artifact / version.ext
        parts = key.split("/")
        if len(parts) < 5:
            raise InvalidObjectKeyError(f"Key has too few segments: {key!r}")

        service = parts[0]
        domain = parts[1]
        artifact = parts[-2]
        version_ext = parts[-1]
        resource_id = "/".join(parts[2:-2])

        version, _, extension = version_ext.partition(".")
        if not extension:
            raise InvalidObjectKeyError(f"Key has no extension in last segment: {key!r}")

        return KeyComponents(
            service=service,
            domain=domain,
            resource_id=resource_id,
            artifact=artifact,
            version=version,
            extension=extension,
        )

    # Pattern for silver-layer keys written by content-store (legacy news pipeline):
    # silver/<source_slug>/<YYYY>/<MM>/<DD>/<uuid>.txt
    # Example: silver/reuters/2024/01/15/0195c7b4-a9f2-7b3e-8d1c-3f2e1a4b5c6d.txt
    _SILVER_KEY_PATTERN = re.compile(
        r"^silver/[a-zA-Z0-9_\-]+/\d{4}/\d{2}/\d{2}/[0-9a-f\-]+\.txt$",
        re.IGNORECASE,
    )
    # Pattern for canonical keys written by content-store (PLAN-0086 canonical pipeline):
    # content-store/canonical/<uuid>/body.json
    _CANONICAL_KEY_PATTERN = re.compile(
        r"^content-store/canonical/[0-9a-f\-]+/body\.json$",
        re.IGNORECASE,
    )

    @classmethod
    def is_valid_silver_key(cls, key: str) -> bool:
        """Return True if *key* is a canonical silver-layer or content-store MinIO key.

        Accepted formats::

            silver/<source_slug>/<YYYY>/<MM>/<DD>/<uuid>.txt    (legacy news)
            content-store/canonical/<uuid>/body.json            (PLAN-0086)

        Args:
            key: The MinIO object key to validate.

        Returns:
            ``True`` when the key matches either pattern; ``False`` otherwise.
            Never raises.
        """
        return bool(cls._SILVER_KEY_PATTERN.match(key)) or bool(cls._CANONICAL_KEY_PATTERN.match(key))

    @staticmethod
    def build_prefix(service: str, domain: str | None = None) -> str:
        """Build a key prefix for listing objects in a service (and optional domain).

        Args:
            service: Service slug.
            domain: Optional domain slug.

        Returns:
            Prefix string ending with ``/``.
        """
        KeyBuilder._validate_slug(service, "service")
        if domain is not None:
            KeyBuilder._validate_slug(domain, "domain")
            return f"{service}/{domain}/"
        return f"{service}/"

    # ------------------------------------------------------------------ helpers

    @staticmethod
    def _validate_slug(value: str, field: str) -> None:
        if not _SLUG_RE.match(value):
            raise InvalidObjectKeyError(
                f"{field} must be lowercase letters/digits/hyphens starting with a letter, got {value!r}"
            )

    @staticmethod
    def _validate_version(value: str) -> None:
        if not _VERSION_RE.match(value):
            raise InvalidObjectKeyError(f"version must be 'v{{N}}', got {value!r}")

    @staticmethod
    def _validate_extension(value: str) -> None:
        if not _EXT_RE.match(value):
            raise InvalidObjectKeyError(f"extension must be alphanumeric, got {value!r}")
