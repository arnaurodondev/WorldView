"""PathTemplateMatcher — matches a RawPath against operator-defined templates (T-E1-03).

Templates are loaded from the ``path_templates`` DB table and cached for
``_CACHE_TTL_SECONDS`` (5 minutes).  A path matches a template when:
  1. ``entity_type_sequence`` aligns with the path's node types.
  2. Each relation in ``relation_type_sequence`` matches the corresponding
     edge using ``|``-separated alternatives (OR semantics).

No infrastructure imports in the matching logic — the repository call is
injected at construction time via the session factory.
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Any

from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from knowledge_graph.infrastructure.age.path_discovery import RawPath

logger = get_logger(__name__)  # type: ignore[no-any-return]

# 5-minute cache TTL for templates loaded from DB.
_CACHE_TTL_SECONDS = 300.0


class PathTemplateMatcher:
    """Match a RawPath against configured path templates.

    Args:
    ----
        session_factory: Read-only session factory for ``path_templates`` table.

    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],  # type: ignore[type-arg]
    ) -> None:
        self._sf = session_factory
        self._cache: list[dict[str, Any]] = []
        self._cache_loaded_at: float = 0.0
        self._cache_lock = asyncio.Lock()

    async def _load_templates(self) -> list[dict[str, Any]]:
        """Fetch enabled templates from DB, respecting the 5-minute cache TTL."""
        now = time.monotonic()
        if self._cache and (now - self._cache_loaded_at) < _CACHE_TTL_SECONDS:
            return self._cache

        async with self._cache_lock:
            # Re-check under lock to avoid cache stampede.
            now = time.monotonic()
            if self._cache and (now - self._cache_loaded_at) < _CACHE_TTL_SECONDS:
                return self._cache

            from sqlalchemy import text

            async with self._sf() as session:
                result = await session.execute(
                    text("""
SELECT template_name,
       entity_type_sequence,
       relation_type_sequence
FROM path_templates
WHERE enabled = TRUE
ORDER BY template_name
""")
                )
                rows = result.fetchall()

            templates: list[dict[str, Any]] = []
            for row in rows:
                import json as _json

                ets = row[1] if isinstance(row[1], list) else _json.loads(str(row[1]))
                rts = row[2] if isinstance(row[2], list) else _json.loads(str(row[2]))
                templates.append(
                    {
                        "template_name": str(row[0]),
                        "entity_type_sequence": [str(e) for e in ets],
                        "relation_type_sequence": [str(r) for r in rts],
                    }
                )

            self._cache = templates
            self._cache_loaded_at = time.monotonic()
            logger.debug(  # type: ignore[no-any-return]
                "path_templates_cache_refreshed",
                count=len(templates),
            )
            return templates

    def _matches_template(
        self,
        raw_path: RawPath,
        template: dict[str, Any],
    ) -> bool:
        """Return True if ``raw_path`` matches ``template``.

        Matching rules:
        - ``entity_type_sequence`` must align with the path node types
          (case-insensitive).
        - Each entry in ``relation_type_sequence`` is a ``|``-separated set of
          alternatives; at least one alternative must match the corresponding
          edge's relation_type (case-insensitive).
        - Sequences are compared against ALL path nodes/edges, so the path
          length must exactly match the template length.
        """
        ets: list[str] = template["entity_type_sequence"]
        rts: list[str] = template["relation_type_sequence"]

        # Length guards: template must match the exact path dimensions.
        if len(raw_path.node_types) != len(ets):
            return False
        if len(raw_path.rel_types) != len(rts):
            return False

        # Check entity type sequence alignment.
        for node_type, expected_type in zip(raw_path.node_types, ets, strict=True):
            if str(node_type).lower() != expected_type.lower():
                return False

        # Check relation type sequence with OR alternation.
        for rel_type, alternatives_str in zip(raw_path.rel_types, rts, strict=True):
            alternatives = [a.strip().upper() for a in alternatives_str.split("|")]
            if str(rel_type).upper() not in alternatives:
                return False

        return True

    async def match(
        self,
        raw_path: RawPath,
        templates: list[dict[str, Any]] | None = None,
    ) -> str | None:
        """Return the first matching template name, or None.

        Args:
        ----
            raw_path:  The path to match.
            templates: Optional pre-loaded templates list (for testing /
                       batch calls).  When None, templates are loaded from
                       DB with the 5-minute cache.
        """
        if templates is None:
            templates = await self._load_templates()

        for template in templates:
            try:
                if self._matches_template(raw_path, template):
                    return str(template["template_name"])
            except Exception:
                logger.warning(  # type: ignore[no-any-return]
                    "path_template_match_error",
                    template_name=template.get("template_name"),
                    exc_info=True,
                )

        return None

    def invalidate_cache(self) -> None:
        """Force a cache refresh on the next call (useful for testing)."""
        self._cache = []
        self._cache_loaded_at = 0.0
