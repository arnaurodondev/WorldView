"""EntityContextClient — HTTP adapter that loads entity intelligence context from S7.

PLAN-0074 Wave F, T-F-01.

Implements EntityContextLoaderPort by making two parallel HTTP calls to S7:
  1. GET {KG_BASE_URL}/internal/v1/entities/{entity_id}/intelligence
     → entity narrative, health score, key metrics, data completeness
  2. GET {KG_BASE_URL}/api/v1/entities/{entity_id}/graph?depth=1&limit=5
     → top-5 egocentric graph edges for system-prompt relationship section

BP-235: Both calls use httpx.Timeout(5.0) — never rely on httpx default timeout.
On any failure (404, 5xx, network error, timeout): returns is_empty=True context
and logs ``entity_chat_context_fallback`` for observability.

Retry policy: retries 5xx responses exactly once before declaring failure.
WHY once: a second 5xx within the same request usually means the upstream is
overloaded; more retries add latency to an already-degraded path.
"""

from __future__ import annotations

import asyncio
from uuid import UUID

import httpx
import structlog

from rag_chat.application.ports.entity_context_loader import EntityContextLoaderPort
from rag_chat.domain.entities.entity_chat_context import EntityChatContext

log = structlog.get_logger(__name__)  # type: ignore[no-any-return]

# Per-request timeout for S7 intelligence/graph endpoints.
# WHY 5.0s: BP-235 — always set explicit httpx.Timeout; never rely on httpx's
# default (5s but applied differently per method). 5s matches upstream_timeout_seconds.
_KG_TIMEOUT = httpx.Timeout(5.0)


class EntityContextClient(EntityContextLoaderPort):
    """Concrete HTTP adapter for S7 entity intelligence context loading.

    Constructed once at app startup and injected into EntityContextChatUseCase.
    The internal httpx.AsyncClient is shared across requests (no per-request creation).
    WHY shared client: connection pooling — avoids TCP handshake overhead per request.
    """

    def __init__(self, base_url: str) -> None:
        """Create the client.

        Args:
            base_url: S7 knowledge-graph base URL, e.g. ``http://knowledge-graph:8007``.
                      Sourced from ``RagChatSettings.kg_internal_base_url``.
        """
        # WHY httpx.Timeout object (not float): BP-235 — always use httpx.Timeout()
        # constructor; a bare float is silently treated as connect timeout only in
        # some httpx versions, leaving read/write/pool timeouts at default (5s).
        # Explicit httpx.Timeout(N) sets ALL four timeout phases to N seconds.
        self._client = httpx.AsyncClient(base_url=base_url, timeout=_KG_TIMEOUT)

    async def load(
        self,
        entity_id: UUID,
        tenant_id: UUID | None,
        jwt_token: str,
    ) -> EntityChatContext:
        """Load entity intelligence context from S7 (parallel calls).

        Fires both HTTP calls concurrently via asyncio.gather so total latency
        is max(intelligence_latency, graph_latency) rather than their sum.

        Returns EntityChatContext(is_empty=True) on ANY failure — never raises.
        """
        # Build auth header forwarded to S7's InternalJWTMiddleware.
        # PRD-0025: X-Internal-JWT is the ONLY accepted auth mechanism on backends.
        headers: dict[str, str] = {}
        if jwt_token:
            headers["X-Internal-JWT"] = jwt_token

        # WHY return_exceptions=True: if one call fails we still want the other
        # result. We inspect individually below.
        results: tuple[dict | BaseException, dict | BaseException] = await asyncio.gather(  # type: ignore[assignment]
            self._fetch_intelligence(entity_id, headers),
            self._fetch_graph(entity_id, headers),
            return_exceptions=True,
        )
        intel_result: dict | BaseException = results[0]
        graph_result: dict | BaseException = results[1]

        # If both calls failed or returned empty, return is_empty fallback.
        intel_ok = isinstance(intel_result, dict) and bool(intel_result)
        graph_ok = isinstance(graph_result, dict) and bool(graph_result)

        if not intel_ok and not graph_ok:
            log.info(  # type: ignore[no-any-return]
                "entity_chat_context_fallback",
                entity_id=str(entity_id),
                reason="both_endpoints_failed",
            )
            return EntityChatContext(entity_id=entity_id, is_empty=True)

        # If intelligence call failed but graph succeeded (rare edge case), still
        # return is_empty because we can't build a meaningful system prompt without
        # at minimum the entity name/type from the intelligence endpoint.
        if not intel_ok:
            log.info(  # type: ignore[no-any-return]
                "entity_chat_context_fallback",
                entity_id=str(entity_id),
                reason="intelligence_endpoint_failed",
            )
            return EntityChatContext(entity_id=entity_id, is_empty=True)

        # Map intelligence response → EntityChatContext fields.
        # At this point intel_ok is True so intel_result is dict; cast for mypy.
        intel: dict = intel_result if isinstance(intel_result, dict) else {}
        graph: dict = graph_result if isinstance(graph_result, dict) else {}

        canonical_name = intel.get("canonical_name", "")
        entity_type = intel.get("entity_type", "")

        # Narrative text lives inside the nested current_narrative object.
        narrative_text: str | None = None
        current_narrative = intel.get("current_narrative")
        if isinstance(current_narrative, dict):
            narrative_text = current_narrative.get("narrative_text")

        health_score = intel.get("health_score")
        data_completeness = intel.get("data_completeness")
        key_metrics: dict = intel.get("key_metrics") or {}

        # Extract top-5 graph relations from graph endpoint response.
        # S7 graph endpoint returns: {center, relations: list[dict], entities: dict}
        # We map relations to simplified dicts for the system prompt.
        top_relations = _extract_top_relations(graph, limit=5)

        return EntityChatContext(
            entity_id=entity_id,
            canonical_name=canonical_name,
            entity_type=entity_type,
            narrative_text=narrative_text,
            health_score=float(health_score) if health_score is not None else None,
            data_completeness=float(data_completeness) if data_completeness is not None else None,
            key_metrics=key_metrics,
            top_relations=top_relations,
            is_empty=False,
        )

    async def _fetch_intelligence(
        self,
        entity_id: UUID,
        headers: dict[str, str],
    ) -> dict:
        """GET /internal/v1/entities/{entity_id}/intelligence from S7.

        Retries once on 5xx before returning {}.
        Returns {} on 404 (entity not found), 5xx, timeout, or network error.
        """
        path = f"/internal/v1/entities/{entity_id}/intelligence"
        return await self._get_with_retry(path, headers, entity_id)

    async def _fetch_graph(
        self,
        entity_id: UUID,
        headers: dict[str, str],
    ) -> dict:
        """GET /api/v1/entities/{entity_id}/graph?depth=1&limit=5 from S7.

        Retries once on 5xx before returning {}.
        Returns {} on 404, 5xx, timeout, or network error.
        """
        path = f"/api/v1/entities/{entity_id}/graph"
        return await self._get_with_retry(path, headers, entity_id, params={"depth": 1, "limit": 5})

    async def _get_with_retry(
        self,
        path: str,
        headers: dict[str, str],
        entity_id: UUID,
        params: dict | None = None,
    ) -> dict:
        """GET *path* with exactly one retry on 5xx responses.

        WHY one retry: a transient 5xx (e.g. upstream rolling deploy) often
        recovers on the first retry. Two retries add unacceptable latency on
        a chat path where total budget is ~5s.

        Returns {} on any failure — never raises.
        """
        for attempt in range(2):  # attempt 0 = first try, attempt 1 = retry
            try:
                resp = await self._client.get(path, headers=headers, params=params)
                if resp.status_code == 404:
                    # Entity not found — no point retrying.
                    log.debug(  # type: ignore[no-any-return]
                        "entity_context_404",
                        path=path,
                        entity_id=str(entity_id),
                    )
                    return {}
                if resp.status_code >= 500:
                    if attempt == 0:
                        # First 5xx — retry once.
                        log.debug(  # type: ignore[no-any-return]
                            "entity_context_5xx_retrying",
                            path=path,
                            status=resp.status_code,
                            entity_id=str(entity_id),
                        )
                        continue
                    # Second attempt also 5xx — give up.
                    log.warning(  # type: ignore[no-any-return]
                        "entity_chat_context_fallback",
                        path=path,
                        status=resp.status_code,
                        entity_id=str(entity_id),
                        reason="5xx_after_retry",
                    )
                    return {}
                resp.raise_for_status()
                result: dict = resp.json()
                return result
            except httpx.TimeoutException:
                log.warning(  # type: ignore[no-any-return]
                    "entity_chat_context_fallback",
                    path=path,
                    entity_id=str(entity_id),
                    reason="timeout",
                )
                return {}
            except (httpx.HTTPStatusError, httpx.RequestError) as exc:
                log.warning(  # type: ignore[no-any-return]
                    "entity_chat_context_fallback",
                    path=path,
                    entity_id=str(entity_id),
                    reason=type(exc).__name__,
                    error=str(exc),
                )
                return {}
        # Unreachable — loop always returns above, but satisfies type checker.
        return {}  # pragma: no cover

    async def aclose(self) -> None:
        """Close the underlying httpx.AsyncClient."""
        await self._client.aclose()


def _extract_top_relations(graph: dict, limit: int = 5) -> list[dict]:
    """Map S7 graph response into simplified relation dicts for the system prompt.

    S7 egocentric graph endpoint (/api/v1/entities/{id}/graph) returns:
      {entity_id, nodes: list[{id, label, type, size, ticker}],
                  edges: list[{id, source, target, label, weight}]}

    Note: the older S7 narrative endpoint uses a different format
      {center, relations: list[...], entities: dict[...]}
    We support both formats for forward-compatibility.

    Output format per relation:
      {relation_type: str, target_name: str, confidence: float}

    WHY this mapping: the system-prompt template needs human-readable names, not
    raw UUIDs. We look up labels from the nodes list by UUID string.
    """
    if not graph:
        return []

    result: list[dict] = []

    # ── Format A: egocentric graph (nodes + edges) — current live format ──────
    nodes = graph.get("nodes")
    edges = graph.get("edges")
    if isinstance(nodes, list) and isinstance(edges, list):
        # Build a label lookup from the nodes list.
        node_label: dict[str, str] = {}
        for node in nodes:
            if isinstance(node, dict):
                node_label[str(node.get("id", ""))] = node.get("label") or node.get("id", "unknown")

        # Identify the center entity id (the entity whose graph we loaded).
        # Edges may point either TOWARD or AWAY FROM the center node, so we
        # pick the endpoint that is NOT the center as the "neighbor" to display.
        # WHY: without this, edges like "Taiwan Semiconductor → Apple (supplier_of)"
        # would show "Apple Inc." as the target instead of "Taiwan Semiconductor",
        # and Apple's own UUID would appear in the prefix and trip the PII detector.
        center_id = str(graph.get("entity_id", ""))

        for edge in edges[:limit]:
            if not isinstance(edge, dict):
                continue
            source_id = str(edge.get("source", ""))
            target_id = str(edge.get("target", ""))
            relation_type = str(edge.get("label") or "related_to")
            # Choose the neighbor endpoint (whichever is not the center).
            # If neither matches (graph inconsistency), fall back to target.
            neighbor_id = source_id if target_id == center_id else target_id
            target_name = node_label.get(neighbor_id, neighbor_id or "unknown")
            confidence = float(edge.get("weight") or 0.0)
            result.append(
                {
                    "relation_type": relation_type,
                    "target_name": target_name,
                    "confidence": confidence,
                }
            )
        return result

    # ── Format B: narrative endpoint (relations + entities dict) — legacy ─────
    entities_by_id: dict[str, dict] = {}
    for eid, edata in graph.get("entities", {}).items():
        if isinstance(edata, dict):
            entities_by_id[str(eid)] = edata

    relations = graph.get("relations", [])
    for rel in relations[:limit]:
        if not isinstance(rel, dict):
            continue
        object_id = str(rel.get("object_entity_id", ""))
        target_entity = entities_by_id.get(object_id, {})
        target_name = target_entity.get("canonical_name", object_id or "unknown")
        relation_type = rel.get("canonical_type") or rel.get("relation_type", "related_to")
        confidence = float(rel.get("confidence") or 0.0)
        result.append(
            {
                "relation_type": relation_type,
                "target_name": target_name,
                "confidence": confidence,
            }
        )
    return result
