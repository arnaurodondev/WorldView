"""Valkey cache for screen field metadata (PRD-0017 §6.2).

Key: ``s3:screen:fields:v1``
Value: JSON-serialized ``list[ScreenFieldMetadata]``
TTL: none — overwritten every 6 hours by the background refresh task in app.py.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from market_data.application.ports.cache import ScreenFieldsCachePort
from market_data.domain.entities import ScreenFieldMetadata
from observability.logging import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from messaging.valkey.client import ValkeyClient  # type: ignore[import-untyped]

logger = get_logger(__name__)

_KEY = ScreenFieldsCachePort.VALKEY_KEY


class ScreenFieldsCache(ScreenFieldsCachePort):
    """Valkey-backed cache for the list of screenable field metadata.

    Serialisation format: JSON array of dicts matching ``ScreenFieldMetadata``
    field names.  No TTL — the background job overwrites the key every 6 h.
    """

    def __init__(self, client: ValkeyClient) -> None:
        self._client = client

    async def get_all(self) -> list[ScreenFieldMetadata] | None:
        """Return cached fields or ``None`` on miss / connection error (fail-open)."""
        try:
            raw = await self._client.get(_KEY)
            if raw is None:
                return None
            records: list[dict] = json.loads(raw)
            return [
                ScreenFieldMetadata(
                    name=r["name"],
                    label=r["label"],
                    field_type=r["field_type"],
                    unit=r.get("unit"),
                    description=r.get("description"),
                    observed_min=r.get("observed_min"),
                    observed_max=r.get("observed_max"),
                    null_fraction=r.get("null_fraction", 0.0),
                )
                for r in records
            ]
        except Exception:
            logger.warning("screen_fields_cache_unavailable_get", key=_KEY)
            return None

    async def set_all(self, fields: list[ScreenFieldMetadata]) -> None:
        """Overwrite the cached field list; silently degrades on error (fail-open)."""
        # TTL is 2x the refresh interval (6 h) so stale data auto-expires if
        # the background refresh loop dies before the next write cycle.
        _TTL_SECONDS = 7 * 3600  # 7 h = 6 h refresh + 1 h grace  # noqa: N806
        try:
            payload = json.dumps(
                [
                    {
                        "name": f.name,
                        "label": f.label,
                        "field_type": f.field_type,
                        "unit": f.unit,
                        "description": f.description,
                        "observed_min": f.observed_min,
                        "observed_max": f.observed_max,
                        "null_fraction": f.null_fraction,
                    }
                    for f in fields
                ]
            )
            await self._client.set(_KEY, payload, ttl=_TTL_SECONDS)
        except Exception:
            logger.warning("screen_fields_cache_unavailable_set", key=_KEY)
