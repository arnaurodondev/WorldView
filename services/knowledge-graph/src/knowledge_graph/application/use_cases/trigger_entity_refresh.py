"""TriggerEntityRefreshUseCase — rate-limited manual entity refresh (REQ-003).

Publishes an ``entity.refresh.v1`` event via the outbox; consumed by S6
``EntityRefreshConsumer`` which marks the entity_embedding_state row as due
for refresh.  S7 ``DefinitionRefreshWorker`` then picks it up on the next
cycle (or sooner if a Kafka consumer / scheduler is wired to react).

Rate-limit key: ``entity_refresh:{tenant}:{user}:{entity_id}`` — one trigger
per hour per (entity, tenant, user) tuple, identical structure to
``TriggerNarrativeGenerationUseCase`` (BP-200: uses set_nx + ex).

R25: this module never imports from ``infrastructure/`` — repo classes are
injected by the API layer (resolved from app.state at request time).
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from uuid import UUID

from common.ids import new_uuid7  # type: ignore[import-untyped]
from common.time import utc_now  # type: ignore[import-untyped]
from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from collections.abc import Callable

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from messaging.valkey.client import ValkeyClient  # type: ignore[import-untyped]

logger = get_logger(__name__)  # type: ignore[no-any-return]

# Rate-limit window: one manual refresh per entity+tenant+user per hour.
_RATE_LIMIT_TTL_S = 3600

_ENTITY_REFRESH_TOPIC = "entity.refresh.v1"

# Allowed values for ``refresh_type`` — kept here (single source of truth)
# instead of repeated in the API schema so both the route and the use case
# share the validation.
ALLOWED_REFRESH_TYPES: frozenset[str] = frozenset({"description", "narrative", "all"})


class InvalidRefreshTypeError(ValueError):
    """Raised when ``refresh_type`` is not in :data:`ALLOWED_REFRESH_TYPES`."""


class EntityNotFoundError(Exception):
    """Raised when the requested entity does not exist in canonical_entities."""


@dataclass
class TriggerEntityRefreshResult:
    """Successful trigger result returned to the API layer.

    Attributes:
        job_id:        UUIDv7 event_id of the outbox row (used as ``job_id``
                       in the HTTP response for client-side tracking).
        entity_id:     The entity that was queued for refresh.
        refresh_type:  Validated refresh_type ("description" | "narrative" | "all").
    """

    job_id: UUID
    entity_id: UUID
    refresh_type: str


class TriggerEntityRefreshUseCase:
    """Rate-limited manual entity refresh trigger.

    Responsibilities:
      1. Validate ``refresh_type`` ∈ {description, narrative, all}.
      2. Verify the entity exists in canonical_entities (read replica).
      3. Enforce 1-per-hour rate limit via Valkey set_nx + ex=3600.
      4. Append an ``entity.refresh.v1`` event to the outbox (write session).
      5. Return TriggerEntityRefreshResult for the route.

    Args:
        valkey:                 ValkeyClient (rate-limit store).  ``None``
                                disables rate limiting (fail-open for dev).
        write_session_factory:  Sessionmaker for intelligence_db (write side).
        read_session_factory:   Sessionmaker for intelligence_db (read side).
        outbox_repo_class:      Callable ``(AsyncSession) -> OutboxRepository``;
                                injected by the API layer from app.state (R25).
        schema_path:            Absolute path to entity.refresh.v1.avsc.
    """

    def __init__(
        self,
        valkey: ValkeyClient | None,
        write_session_factory: async_sessionmaker[AsyncSession],
        read_session_factory: async_sessionmaker[AsyncSession],
        outbox_repo_class: Callable[[AsyncSession], Any],
        schema_path: str | None = None,
    ) -> None:
        self._valkey = valkey
        self._write_sf = write_session_factory
        self._read_sf = read_session_factory
        self._outbox_repo_class = outbox_repo_class
        if schema_path is None:
            from messaging.kafka.schema_paths import get_schema_path  # type: ignore[import-untyped]

            self._avsc_path = get_schema_path("entity.refresh.v1.avsc")
        else:
            self._avsc_path = schema_path

    # ── Public API ──────────────────────────────────────────────────────────

    async def execute(
        self,
        entity_id: UUID,
        tenant_id: UUID | None,
        user_id: str,
        refresh_type: str = "all",
    ) -> TriggerEntityRefreshResult | None:
        """Validate, rate-limit, and enqueue an entity refresh event.

        Returns:
            ``TriggerEntityRefreshResult`` on success.
            ``None`` when the rate limit was hit (caller should return 429).

        Raises:
            InvalidRefreshTypeError: ``refresh_type`` is not allowed.
            EntityNotFoundError: entity_id is not present in canonical_entities.
        """
        # 1. Validate refresh_type (cheap — do this before any I/O).
        if refresh_type not in ALLOWED_REFRESH_TYPES:
            msg = f"refresh_type must be one of {sorted(ALLOWED_REFRESH_TYPES)}; got {refresh_type!r}"
            raise InvalidRefreshTypeError(msg)

        # 2. Verify the entity exists.  Cheap COUNT(*)=0 check on the read replica.
        if not await self._entity_exists(entity_id):
            raise EntityNotFoundError(f"entity_id {entity_id} not found")

        # 3. Rate limit (BP-200 — set_nx, NOT set(..., nx=True)).
        tenant_str = str(tenant_id) if tenant_id else "global"
        rate_key = f"entity_refresh:{tenant_str}:{user_id}:{entity_id}"

        if self._valkey is not None:
            # Returns True when the key was newly created (allowed), False when
            # the key already existed (rate-limited).
            allowed = await self._valkey.set_nx(rate_key, "1", ex=_RATE_LIMIT_TTL_S)
            if not allowed:
                logger.info(  # type: ignore[no-any-return]
                    "entity_refresh_rate_limited",
                    entity_id=str(entity_id),
                    tenant_id=tenant_str,
                    user_id=user_id,
                    refresh_type=refresh_type,
                )
                return None
        # Else: Valkey unavailable — fail-open (allow without rate limiting).

        # 4. Build the Avro payload + outbox append (transactional via session.commit).
        event_id = new_uuid7()  # type: ignore[no-any-return]
        payload_avro = self._build_event_payload(
            event_id=event_id,
            entity_id=entity_id,
            tenant_id=tenant_id,
            user_id=user_id,
            refresh_type=refresh_type,
        )

        try:
            async with self._write_sf() as write_session:
                outbox_repo = self._outbox_repo_class(write_session)
                # Returns the outbox row's UUID — but for the public job_id we
                # surface the event_id baked into the Avro payload (clients reference
                # the same UUID that downstream consumers see in ``event_id``).
                await outbox_repo.append(
                    topic=_ENTITY_REFRESH_TOPIC,
                    partition_key=str(entity_id),
                    payload_avro=payload_avro,
                    event_id=event_id,
                )
                await write_session.commit()
        except Exception:
            # Outbox append / commit failed — release the rate-limit slot so
            # the user can retry immediately instead of being locked out for
            # the full 1-hour window. The set_nx reservation guards against
            # concurrent stampede during the in-flight window; deletion on
            # failure restores idempotent retry semantics. Post-audit review SF #7.
            if self._valkey is not None:
                with contextlib.suppress(Exception):
                    await self._valkey.delete(rate_key)
            raise

        logger.info(  # type: ignore[no-any-return]
            "entity_refresh_queued",
            entity_id=str(entity_id),
            tenant_id=tenant_str,
            user_id=user_id,
            refresh_type=refresh_type,
            event_id=str(event_id),
        )

        return TriggerEntityRefreshResult(
            job_id=event_id,
            entity_id=entity_id,
            refresh_type=refresh_type,
        )

    # ── Internals ───────────────────────────────────────────────────────────

    async def _entity_exists(self, entity_id: UUID) -> bool:
        """Lookup canonical_entities for existence.  Uses the read replica."""
        from sqlalchemy import text

        async with self._read_sf() as session:
            result = await session.execute(
                text(
                    "SELECT 1 FROM canonical_entities WHERE entity_id = CAST(:entity_id AS uuid) LIMIT 1",
                ),
                {"entity_id": str(entity_id)},
            )
            return result.fetchone() is not None

    def _build_event_payload(
        self,
        event_id: UUID,
        entity_id: UUID,
        tenant_id: UUID | None,
        user_id: str,
        refresh_type: str,
    ) -> bytes:
        """Serialize the entity.refresh.v1 event for the outbox.

        All Avro fields use string defaults so the payload is forward-compatible
        (R11) — consumers running against an older schema simply read the
        defaults for unknown fields.  Empty-string fallback for tenant_id /
        user_id preserves wire-format simplicity (vs. union-with-null) so the
        consumer can ``value.get(...)`` without ``None`` handling.
        """
        from messaging.kafka.serialization_utils import serialize_confluent_avro  # type: ignore[import-untyped]

        now_iso: str = utc_now().isoformat()  # type: ignore[no-any-return]
        payload = {
            "event_id": str(event_id),
            "schema_version": 1,
            "occurred_at": now_iso,
            "tenant_id": str(tenant_id) if tenant_id else "",
            "entity_id": str(entity_id),
            "triggered_by_user_id": user_id,
            "refresh_type": refresh_type,
        }
        return serialize_confluent_avro(self._avsc_path, payload)  # type: ignore[no-any-return]
