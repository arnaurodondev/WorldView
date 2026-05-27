"""Intelligence tool handlers — knowledge graph, entity relations, claims, and events.

Covers tools backed by S7Port:
  - get_entity_graph          (egocentric graph)
  - traverse_graph            (multi-hop Cypher traversal)
  - search_entity_relations   (ANN relation search)
  - search_claims             (analyst claims)
  - search_events             (corporate events)
  - get_contradictions        (cross-source contradictions)

Narrative/intelligence bundle tools (S7IntelligencePort) live in narrative.py.
"""

from __future__ import annotations

import asyncio
import re
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

import structlog

from rag_chat.domain.entities.chat import CitationMeta, RetrievedItem
from rag_chat.domain.enums import ItemType

from .base import ToolHandler

if TYPE_CHECKING:
    from rag_chat.application.pipeline.tool_executor import EntityContext, ToolUseBlock
    from rag_chat.application.ports.upstream_clients import S6Port, S7Port

log = structlog.get_logger(__name__)  # type: ignore[no-any-return]

# Maximum characters for tool result text injected into LLM context.
_TOOL_RESULT_MAX_CHARS = 4000


def _load_resolver_settings() -> tuple[frozenset[str], float, float]:
    """Load resolver stop-words + similarity thresholds from rag_chat.config.

    Lazy + best-effort: if Settings cannot be instantiated (e.g. running under
    a minimal unit-test harness without env vars) we fall back to a hard-coded
    default. The fallback mirrors the Settings default so the tuning surface
    is identical across both code paths.
    """
    _fallback_words = frozenset(
        {
            "space",
            "industry",
            "sector",
            "market",
            "markets",
            "system",
            "platform",
            "company",
            "companies",
            "stocks",
            "stock",
            "share",
            "shares",
            "ticker",
            "tickers",
            "the",
            "a",
            "an",
            "or",
            "and",
            "in",
            "of",
            "for",
            "with",
            "ai",
            "tech",
            "energy",
            "sentiment",
            "rising",
            "falling",
            "bullish",
            "bearish",
        }
    )
    try:
        from rag_chat.config import Settings  # local import to keep test imports cheap

        s = Settings()  # type: ignore[call-arg]
        words = frozenset(w.strip().lower() for w in s.resolver_stop_words.split(",") if w.strip())
        return words, float(s.resolver_similarity_delta_min), float(s.resolver_top_similarity_min)
    except Exception:  # pragma: no cover — defensive fallback
        return _fallback_words, 0.15, 0.75


# Module-level cache (recomputed on first use). Tests can override the
# handler's instance attributes directly to inject custom values.
_RESOLVER_STOP_WORDS, _RESOLVER_DELTA_MIN, _RESOLVER_TOP_SIM_MIN = _load_resolver_settings()

# Allowlist of Cypher relationship type tokens accepted from LLM input.
# WHY: traverse_graph accepts a cypher_pattern string; we must guard against
# prompt injection — an adversarial user could inject arbitrary Cypher. We
# extract relationship type tokens (e.g. INVESTS_IN from [:INVESTS_IN]) and
# only allow known domain types. Unknown tokens are silently dropped.
_ALLOWED_CYPHER_REL_TYPES: frozenset[str] = frozenset(
    {
        "INVESTS_IN",
        "BOARD_MEMBER_OF",
        "SUBSIDIARY_OF",
        "COMPETES_WITH",
        "PARTNERSHIP",
        "ACQUIRED",
        "FOUNDER_OF",
        "SUPPLIES_TO",
        "REGULATES",
        "LISTED_ON",
    }
)


def _parse_dt(s: str | None) -> datetime | None:
    """Parse an ISO-format date string to a UTC datetime; returns None on failure."""
    if s is None:
        return None
    try:
        return datetime.fromisoformat(s).replace(tzinfo=UTC)
    except ValueError:
        return None


class IntelligenceHandler(ToolHandler):
    """Handles knowledge graph tools (get_entity_graph, traverse_graph, relations, claims, events, contradictions).

    All tools call S7Port (knowledge-graph service). Narrative/intelligence tools
    are handled by NarrativeHandler (handlers/narrative.py).
    """

    _HANDLED_TOOLS = frozenset(
        {
            "get_entity_graph",
            "traverse_graph",
            "search_entity_relations",
            "search_claims",
            "search_events",
            "get_contradictions",
        }
    )

    def __init__(
        self,
        s7: S7Port | None = None,
        entity_context: EntityContext | None = None,
        timeout: float = 5.0,
        # s7_intel is accepted but not used by IntelligenceHandler — narrative/
        # intelligence bundle tools live in NarrativeHandler (handlers/narrative.py).
        # Accepted here so ToolExecutorFactory can pass a uniform kwarg set to
        # all handlers without per-handler conditionals.
        s7_intel: object | None = None,
        # PLAN-0093 E-4 T-E-4-01: optional S6Port for embed_text — used by
        # search_entity_relations to issue a real query embedding instead of
        # a 1024-dim zero vector (F-RAG-004). None falls back to zero vec.
        # Reinstated after FIX-LIVE-O dropped this parameter during the
        # tiebreaker rewrite, which broke the ToolExecutorFactory call site
        # (TypeError: unexpected keyword argument 's6') AND silently
        # regressed search_entity_relations ranking back to zero-vector ANN.
        s6: S6Port | None = None,
        # F-LIVE-NEW-001: configurable resolver tuning. Tests inject custom
        # values; production reads from settings via the module-level cache.
        stop_words: frozenset[str] | None = None,
        similarity_delta_min: float | None = None,
        top_similarity_min: float | None = None,
    ) -> None:
        self._s7 = s7
        self._entity_context = entity_context
        self._timeout = timeout
        self._s6 = s6
        # s7_intel intentionally unused; accepted to keep factory call uniform.
        self._stop_words: frozenset[str] = stop_words if stop_words is not None else _RESOLVER_STOP_WORDS
        self._similarity_delta_min: float = (
            similarity_delta_min if similarity_delta_min is not None else _RESOLVER_DELTA_MIN
        )
        self._top_similarity_min: float = (
            top_similarity_min if top_similarity_min is not None else _RESOLVER_TOP_SIM_MIN
        )

    def _strip_stop_words(self, query: str) -> str:
        """Return ``query`` with all-stop-word tokens removed (lowercased).

        Used as a pre-filter before fuzzy alias match so generic English
        fragments cannot bind to a canonical entity. Returns an empty
        string when EVERY token is a stop-word — the caller treats that as
        a resolver refusal (the query carries no entity-shaped signal).
        """
        # Tokenise on whitespace; punctuation is stripped from each token so
        # "AI semiconductor space." matches the stop list with a trailing dot.
        tokens = query.lower().split()
        kept = [t for t in tokens if t.strip(".,!?:;'\"()[]") not in self._stop_words]
        return " ".join(kept)

    def can_handle(self, tool_name: str) -> bool:
        return tool_name in self._HANDLED_TOOLS

    async def execute(self, tool_name: str, args: dict[str, Any]) -> Any:
        # Import ToolUseBlock only for the graph tools that pass it through.
        # WHY: the handler dispatcher no longer passes ToolUseBlock to execute();
        # a dummy stub is created here so the handler signatures remain unchanged.
        from rag_chat.application.pipeline.tool_executor import ToolUseBlock

        _stub = ToolUseBlock(name=tool_name, input=args)

        if tool_name == "get_entity_graph":
            return await self._handle_get_entity_graph(_stub, **args)
        if tool_name == "traverse_graph":
            return await self._handle_traverse_graph(_stub, **args)
        if tool_name == "search_entity_relations":
            return await self._handle_search_entity_relations(_stub, **args)
        if tool_name == "search_claims":
            return await self._handle_search_claims(_stub, **args)
        if tool_name == "search_events":
            return await self._handle_search_events(_stub, **args)
        if tool_name == "get_contradictions":
            return await self._handle_get_contradictions(_stub, **args)
        raise ValueError(f"IntelligenceHandler cannot handle tool: {tool_name}")

    def _sanitize_cypher_pattern(self, pattern: str | None) -> str | None:
        """Allowlist-filter a Cypher rel-type pattern to guard against prompt injection.

        Extracts :REL_TYPE tokens and keeps only those in _ALLOWED_CYPHER_REL_TYPES.
        Returns None when no allowlisted tokens remain (traverse_graph skips pattern).
        """
        if pattern is None:
            return None
        tokens = re.findall(r":([A-Z_]+)", pattern)
        allowed = [t for t in tokens if t in _ALLOWED_CYPHER_REL_TYPES]
        if not allowed:
            log.warning("cypher_pattern_rejected", pattern=pattern[:100], reason="no_allowlisted_rel_types")
            return None
        return "[:" + "|:".join(allowed) + "]"

    def _require_context_entity(self, tool_name: str, entity_name: str) -> UUID | None:
        """Return entity_context.entity_id or log a warning and return None."""
        if self._entity_context is not None:
            return self._entity_context.entity_id
        log.warning(
            "tool_entity_unresolved",
            tool=tool_name,
            entity_name=entity_name,
            reason="no_entity_context_and_name_resolution_not_wired",
        )
        return None

    async def _resolve_entity_by_name(self, tool_name: str, entity_name: str) -> UUID | None:
        """Resolve entity_name to UUID via entity_context fuzzy-match or S7 alias search.

        Returns None and logs a warning when resolution fails.
        """
        assert self._s7 is not None  # callers must check self._s7 is not None first
        ctx_name_lower = self._entity_context.name.lower() if self._entity_context else ""
        name_lower = entity_name.lower()
        use_context = self._entity_context is not None and (
            name_lower in ctx_name_lower or ctx_name_lower in name_lower or name_lower == ctx_name_lower
        )
        if use_context and self._entity_context is not None:
            return self._entity_context.entity_id

        # F-LIVE-NEW-001: strip generic stop-words BEFORE the fuzzy match so
        # phrases like "AI semiconductor space" cannot collide with SpaceX on
        # a partial-substring alias hit. If stripping leaves the query too
        # short (≤ 2 chars) the resolver bails out — the remaining tokens are
        # not specific enough to identify a single canonical entity.
        stripped = self._strip_stop_words(entity_name)
        if len(stripped.strip()) <= 2:
            from rag_chat.application.metrics.prometheus import (
                rag_entity_resolver_ambiguous_total,
            )

            rag_entity_resolver_ambiguous_total.labels(reason="stop_word_strip").inc()
            log.warning(
                "tool_entity_unresolved",
                tool=tool_name,
                entity_name=entity_name,
                stripped=stripped,
                reason="all_stop_words_after_strip",
            )
            return None
        search_query = stripped if stripped != entity_name.lower() else entity_name
        candidates = await self._s7.resolve_entity_by_name(search_query, limit=3)
        if not candidates:
            log.warning("tool_entity_unresolved", tool=tool_name, entity_name=entity_name, reason="no_alias_match")
            return None
        # FIX-LIVE-O — ambiguity gate + three tiebreakers.
        # When the top two candidates are within 0.10 similarity of each
        # other the resolution is statistically ambiguous (e.g. "Apple"
        # → Apple Inc. vs Apple Computer Holdings). Naively returning the
        # top candidate has caused the agent to pull tool data for the
        # wrong entity; refusing outright loses queries where the top
        # candidates are noise aliases of the SAME canonical, or where one
        # candidate is the canonical-name exact match. Apply three rules
        # in order before declaring ambiguous:
        #   1. Same-canonical collapse — top-K all share entity_id → take
        #      the highest-similarity row.
        #   2. Exact canonical-name match — alias_text (suffix-stripped)
        #      equals the query → wins even with lower similarity. Fixes
        #      the Tesla case where "Teslas"(0.625) outranks "Tesla Inc"
        #      (0.600) on raw embedding similarity.
        #   3. Length-penalty fallback — clear length-distance winner.
        # F-LIVE-NEW-001: low-top-similarity floor BEFORE the delta gate so
        # candidates that all sit below the absolute threshold are rejected
        # even when their relative spread is large. Catches the SpaceX case
        # where top-1 sat at ~0.62 on a noisy substring match.
        try:
            top_sim_value = float(candidates[0].get("similarity", 0.0))
        except (TypeError, ValueError):
            top_sim_value = 0.0
        if top_sim_value < self._top_similarity_min:
            # Exact canonical-name match is allowed to skip the floor — a
            # perfect alias hit on a low-confidence row should still resolve.
            # We check ALL top-K (not just candidates[0]) because the canonical
            # row often has a slightly lower similarity than a noisy plural
            # alias (the Tesla case from FIX-LIVE-O).
            query_norm = self._normalize_canonical(entity_name)
            exact = False
            if query_norm:
                for _c in candidates[:3]:
                    if self._normalize_canonical(str(_c.get("alias_text") or "")) == query_norm:
                        exact = True
                        break
            if not exact:
                from rag_chat.application.metrics.prometheus import (
                    rag_entity_resolver_ambiguous_total,
                )

                rag_entity_resolver_ambiguous_total.labels(reason="low_top_similarity").inc()
                log.warning(
                    "tool_entity_unresolved",
                    tool=tool_name,
                    entity_name=entity_name,
                    top_similarity=top_sim_value,
                    threshold=self._top_similarity_min,
                    reason="top_similarity_below_threshold",
                )
                return None
        if len(candidates) >= 2:
            try:
                top_sim = float(candidates[0].get("similarity", 0.0))
                second_sim = float(candidates[1].get("similarity", 0.0))
                if (top_sim - second_sim) < self._similarity_delta_min:
                    tiebreak_winner = self._apply_resolver_tiebreakers(
                        tool_name=tool_name,
                        entity_name=entity_name,
                        candidates=candidates,
                    )
                    if tiebreak_winner is not None:
                        return tiebreak_winner
                    from rag_chat.application.metrics.prometheus import (
                        rag_entity_resolver_ambiguous_total,
                    )

                    rag_entity_resolver_ambiguous_total.labels(reason="delta_below_threshold").inc()
                    log.warning(
                        "tool_entity_ambiguous",
                        tool=tool_name,
                        entity_name=entity_name,
                        top_two=[
                            {
                                "entity_id": str(candidates[0].get("entity_id")),
                                "similarity": top_sim,
                                "alias_text": candidates[0].get("alias_text"),
                            },
                            {
                                "entity_id": str(candidates[1].get("entity_id")),
                                "similarity": second_sim,
                                "alias_text": candidates[1].get("alias_text"),
                            },
                        ],
                        delta_min=self._similarity_delta_min,
                        reason="similarity_delta_below_threshold",
                    )
                    return None
            except (TypeError, ValueError):
                # Malformed similarity score — fall through to legacy
                # behaviour (use top candidate) rather than crash.
                pass
        try:
            entity_id = UUID(str(candidates[0]["entity_id"]))
        except (ValueError, KeyError):
            log.warning(
                "tool_entity_unresolved",
                tool=tool_name,
                entity_name=entity_name,
                reason="invalid_entity_id_in_candidate",
            )
            return None
        log.info(
            "tool_entity_resolved_by_name",
            tool=tool_name,
            entity_name=entity_name,
            resolved_entity_id=str(entity_id),
            alias_text=candidates[0].get("alias_text"),
            similarity=candidates[0].get("similarity"),
        )
        return entity_id

    # Canonical-suffix tokens stripped before exact-name comparison so
    # "Tesla" matches "Tesla Inc", "Apple Corp", etc. Kept short on
    # purpose — broader fuzzy matching belongs in S7's alias index, not here.
    _CANONICAL_SUFFIXES: tuple[str, ...] = (
        " inc",
        " inc.",
        " corp",
        " corp.",
        " corporation",
        " ltd",
        " ltd.",
        " limited",
        " co",
        " co.",
        " company",
        " plc",
        " sa",
        " ag",
        " nv",
        " holdings",
        " group",
    )

    @staticmethod
    def _normalize_canonical(text: str | None) -> str:
        """Lower-case + strip a trailing canonical company suffix.

        Used only by the exact-canonical tiebreaker — we DO NOT use this
        for the primary alias match (S7's embedding ANN handles that).
        """
        if text is None:
            return ""
        t = text.strip().lower()
        for suffix in IntelligenceHandler._CANONICAL_SUFFIXES:
            if t.endswith(suffix):
                t = t[: -len(suffix)].rstrip()
                break
        return t

    def _apply_resolver_tiebreakers(
        self,
        *,
        tool_name: str,
        entity_name: str,
        candidates: list[dict[str, Any]],
    ) -> UUID | None:
        """Apply FIX-LIVE-O tiebreakers when |Δsim| < 0.10 between top candidates.

        Returns the chosen entity UUID when a rule fires, else None (caller
        will fall back to the legacy ambiguous-bail path). Whenever a rule
        fires we emit a structured ``entity_resolution_tiebreaker_applied``
        event so the resolution is auditable.
        """
        # Look at the same top-K window the ambiguity gate already considered.
        # We cap at 3 candidates (the request limit) but stay defensive.
        topk = candidates[:3]

        # --- Rule 1: same-canonical collapse ---------------------------------
        # All top-K candidates share the same entity_id → not actually
        # ambiguous; pick the highest-similarity row (which is candidates[0]
        # because S7 returns them sorted DESC by similarity).
        try:
            ids = [str(c.get("entity_id")) for c in topk if c.get("entity_id") is not None]
        except Exception:  # pragma: no cover — defensive
            ids = []
        if len(ids) >= 2 and len(set(ids)) == 1:
            try:
                winner_id = UUID(ids[0])
            except ValueError:
                return None
            log.info(
                "entity_resolution_tiebreaker_applied",
                tool=tool_name,
                entity_name=entity_name,
                rule="same_canonical_collapse",
                resolved_entity_id=str(winner_id),
                num_candidates=len(topk),
            )
            return winner_id

        # --- Rule 2: exact canonical-name match ------------------------------
        # If any candidate's alias_text (normalised: lower-case + canonical
        # suffix stripped) equals the query string (same normalisation), it
        # wins even when its similarity score is lower than a noisy alias.
        query_norm = self._normalize_canonical(entity_name)
        if query_norm:
            for cand in topk:
                alias = cand.get("alias_text")
                if alias is None:
                    continue
                if self._normalize_canonical(str(alias)) == query_norm:
                    try:
                        winner_id = UUID(str(cand["entity_id"]))
                    except (ValueError, KeyError, TypeError):
                        continue
                    log.info(
                        "entity_resolution_tiebreaker_applied",
                        tool=tool_name,
                        entity_name=entity_name,
                        rule="exact_canonical_name",
                        resolved_entity_id=str(winner_id),
                        winning_alias_text=str(alias),
                        winning_similarity=cand.get("similarity"),
                    )
                    return winner_id

        # --- Rule 3: length-penalty fallback ---------------------------------
        # Last-resort tiebreaker: prefer a candidate whose alias_text length
        # is CLEARLY closer to the query length than the current top pick.
        # Conservative gates so this can't silently regress genuinely
        # ambiguous queries:
        #   * best candidate must be at least 2 chars closer than the top
        #     candidate (strict gap), AND
        #   * best candidate must be within 3 chars of the query length
        #     (i.e. it must actually look like a near-exact alias).
        # When neither rule 1 nor rule 2 disambiguates and rule 3 doesn't
        # fire either, the resolver falls through to the legacy "ambiguous"
        # path and refuses to resolve.
        query_len = len(entity_name.strip())
        top_alias = candidates[0].get("alias_text")
        top_diff = abs(len(str(top_alias)) - query_len) if top_alias is not None else None
        best_idx: int | None = None
        best_diff: int | None = top_diff
        for idx, cand in enumerate(topk[1:], start=1):
            alias = cand.get("alias_text")
            if alias is None:
                continue
            diff = abs(len(str(alias)) - query_len)
            if best_diff is None or diff < best_diff:
                best_diff = diff
                best_idx = idx
        len_gap_min = 2  # best must be at least 2 chars closer than top
        len_near_exact = 3  # AND within 3 chars of the query length
        if (
            best_idx is not None
            and best_diff is not None
            and top_diff is not None
            and (top_diff - best_diff) >= len_gap_min
            and best_diff <= len_near_exact
        ):
            cand = topk[best_idx]
            try:
                winner_id = UUID(str(cand["entity_id"]))
            except (ValueError, KeyError, TypeError):
                return None
            log.info(
                "entity_resolution_tiebreaker_applied",
                tool=tool_name,
                entity_name=entity_name,
                rule="length_penalty",
                resolved_entity_id=str(winner_id),
                winning_alias_text=str(cand.get("alias_text")),
                winning_similarity=cand.get("similarity"),
            )
            return winner_id

        return None

    async def _handle_get_entity_graph(
        self,
        tool_call: ToolUseBlock,
        entity_name: str,
        depth: int = 1,
        relation_types: list[str] | None = None,
    ) -> list[RetrievedItem]:
        """Retrieve egocentric knowledge graph via S7 (PLAN-0078 alias resolution)."""
        if self._s7 is None:
            log.warning("tool_handler_missing_port", tool="get_entity_graph", port="s7")
            return []

        entity_id = await self._resolve_entity_by_name("get_entity_graph", entity_name)
        if entity_id is None:
            return []

        t0 = time.monotonic()
        try:
            graph = await asyncio.wait_for(
                self._s7.get_egocentric_graph(
                    entity_id=entity_id,
                    min_confidence=0.3,
                    limit=50 * depth,  # depth 1 → 50 edges, depth 2 → 100
                ),
                timeout=self._timeout,
            )
        except Exception as e:
            log.warning("tool_failed", tool="get_entity_graph", error=str(e))
            return []

        if not graph.nodes and not graph.edges:
            log.warning("tool_no_data", tool="get_entity_graph", entity_name=entity_name)
            return []

        text = self._format_graph(entity_name, graph)

        item = RetrievedItem.create(
            item_id=f"tool:graph:{graph.entity_id}",
            item_type=ItemType.relation,
            text=text[:_TOOL_RESULT_MAX_CHARS],
            score=0.85,
            trust_weight=0.80,
            citation_meta=CitationMeta(
                title=f"Knowledge graph: {entity_name}",
                url=None,
                source_name="knowledge_graph",
                published_at=None,
                entity_name=entity_name,
            ),
        )
        log.info(
            "tool_executed", tool="get_entity_graph", latency_ms=round((time.monotonic() - t0) * 1000), items_returned=1
        )
        return [item]

    async def _handle_traverse_graph(
        self,
        tool_call: ToolUseBlock,
        start_entity: str,
        target_entity: str | None = None,
        depth: int = 3,
        cypher_pattern: str | None = None,
    ) -> list[RetrievedItem]:
        """Execute multi-hop Cypher traversal via S7 (BP-459-A fix, injection guard)."""
        if self._s7 is None:
            log.warning("tool_handler_missing_port", tool="traverse_graph", port="s7")
            return []

        # BUG-4 FIX: clamp depth to [1,4] — unclamped depth=100 is a DoS vector.
        raw_depth = int(depth)
        clamped_depth = min(max(raw_depth, 1), 4)
        if clamped_depth != raw_depth:
            log.warning("traverse_depth_clamped", requested=raw_depth, clamped=clamped_depth)

        # SECURITY: sanitize cypher pattern before forwarding
        safe_pattern = self._sanitize_cypher_pattern(cypher_pattern)

        # BP-459-A FIX: resolve source + target independently via alias search so
        # two-entity queries (e.g. "Apple → Anthropic") each get their own UUID.
        # entity_context is used only when start_entity name fuzzy-matches it.
        source_entity_id = await self._resolve_entity_by_name("traverse_graph", start_entity)
        if source_entity_id is None:
            return []

        # target_entity is always resolved via alias search (context holds ONE entity).
        target_entity_id: UUID | None = None
        if target_entity:
            target_entity_id = await self._resolve_entity_by_name("traverse_graph", target_entity)
            if target_entity_id is None:
                return []

        # BP-459-B FIX: source_id/target_id keys route to /graph/cypher/path or /neighborhood.
        params: dict[str, Any] = {
            "source_id": str(source_entity_id),
            "max_hops": clamped_depth,
        }
        if target_entity_id is not None:
            params["target_id"] = str(target_entity_id)

        if target_entity:
            cypher = (
                f"MATCH p=(a:entity {{entity_id: $source}})-[r{safe_pattern or ''}*1..{clamped_depth}]-"
                f"(b:entity {{entity_id: $target}}) RETURN p LIMIT 10"
            )
        else:
            cypher = (
                f"MATCH p=(a:entity {{entity_id: $source}})-[r{safe_pattern or ''}*1..{clamped_depth}]-() "
                f"RETURN p LIMIT 20"
            )

        t0 = time.monotonic()
        try:
            paths = await asyncio.wait_for(
                self._s7.cypher_traverse(cypher=cypher, params=params, max_results=20),
                timeout=self._timeout,
            )
        except Exception as e:
            log.warning("tool_failed", tool="traverse_graph", error=str(e))
            return []

        if not paths:
            log.warning("tool_no_data", tool="traverse_graph", start_entity=start_entity)
            return []

        text = f"Graph traversal: {start_entity}"
        if target_entity:
            text += f" → {target_entity}"
        text += f" (depth {clamped_depth})\n"
        text += "\n".join(str(p) for p in paths[:20])

        item = RetrievedItem.create(
            item_id=f"tool:traverse:{start_entity}",
            item_type=ItemType.cypher_path,
            text=text[:_TOOL_RESULT_MAX_CHARS],
            score=0.80,
            trust_weight=0.75,
            citation_meta=CitationMeta(
                title=f"Graph traversal: {start_entity}",
                url=None,
                source_name="knowledge_graph",
                published_at=None,
                entity_name=start_entity,
            ),
        )
        log.info(
            "tool_executed", tool="traverse_graph", latency_ms=round((time.monotonic() - t0) * 1000), items_returned=1
        )
        return [item]

    async def _handle_search_entity_relations(
        self,
        tool_call: ToolUseBlock,
        entity_name: str,
        relation_type: str | None = None,
        min_confidence: float = 0.6,
        limit: int = 15,
    ) -> list[RetrievedItem]:
        """Search relation triplets for an entity via S7 ANN relation search.

        S7.search_relations takes an embedding + entity_ids — not a text query.
        We use entity_context.entity_id when available; otherwise degrade to [].
        relation_type filtering is accepted from the LLM but not forwarded to
        search_relations because S7 v1 filters by embedding ANN, not type literal.
        """
        if self._s7 is None:
            log.warning("tool_handler_missing_port", tool="search_entity_relations", port="s7")
            return []
        entity_id = await self._resolve_entity_by_name("search_entity_relations", entity_name)
        if entity_id is None:
            return []
        # PLAN-0093 E-4 T-E-4-01: real query embedding instead of a 1024-dim
        # zero vector. The old placeholder made S7 fall back to a non-ranked
        # entity_id filter — the LLM got back the same top-K regardless of
        # the user's actual question. We use ``relation_type`` (when supplied)
        # + entity_name as the embedding text so the ANN search ranks by
        # semantic relevance to e.g. "Microsoft acquisitions" not just
        # "any Microsoft edge". Restored after FIX-LIVE-O regression.
        embedding_query = f"{relation_type} {entity_name}".strip() if relation_type else entity_name
        if self._s6 is not None:
            placeholder_embedding: list[float] = await self._s6.embed_text(embedding_query)
        else:
            placeholder_embedding = [0.0] * 1024

        t0 = time.monotonic()
        try:
            relations = await asyncio.wait_for(
                self._s7.search_relations(
                    embedding=placeholder_embedding,
                    entity_ids=[entity_id],
                    top_k=limit,
                    min_confidence=min_confidence,
                ),
                timeout=self._timeout,
            )
        except Exception as e:
            log.warning("tool_failed", tool="search_entity_relations", error=str(e))
            return []

        if not relations:
            log.warning("tool_no_data", tool="search_entity_relations", entity_name=entity_name)
            return []

        lines = [f"Relations for {entity_name}:"]
        for r in relations:
            lines.append(
                f"  {r.subject} --[{r.relation_type}]--> {r.object} (confidence={r.confidence:.2f}): {r.summary}"
            )

        text = "\n".join(lines)
        item = RetrievedItem.create(
            item_id=f"tool:relations:{entity_id}",
            item_type=ItemType.relation,
            text=text[:_TOOL_RESULT_MAX_CHARS],
            score=0.82,
            trust_weight=0.80,
            citation_meta=CitationMeta(
                title=f"Relations: {entity_name}",
                url=None,
                source_name="knowledge_graph",
                published_at=None,
                entity_name=entity_name,
            ),
        )
        log.info(
            "tool_executed",
            tool="search_entity_relations",
            latency_ms=round((time.monotonic() - t0) * 1000),
            items_returned=1,
        )
        return [item]

    async def _handle_search_claims(
        self,
        tool_call: ToolUseBlock,
        entity_name: str,
        claim_type: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> list[RetrievedItem]:
        """Search analyst claims for an entity via S7.search_claims.

        Returns one RetrievedItem per claim, up to 20. Returns [] on any error.
        """
        if self._s7 is None:
            log.warning("tool_handler_missing_port", tool="search_claims", port="s7")
            return []
        entity_id = await self._resolve_entity_by_name("search_claims", entity_name)
        if entity_id is None:
            return []
        claim_types = [claim_type] if claim_type else None

        t0 = time.monotonic()
        try:
            claims = await asyncio.wait_for(
                self._s7.search_claims(
                    entity_ids=[entity_id],
                    claim_types=claim_types,
                    date_from=_parse_dt(date_from),
                    date_to=_parse_dt(date_to),
                    top_k=20,
                    min_confidence=0.45,
                ),
                timeout=self._timeout,
            )
        except Exception as e:
            log.warning("tool_failed", tool="search_claims", error=str(e))
            return []

        if not claims:
            log.warning("tool_no_data", tool="search_claims", entity_name=entity_name)
            return []

        items: list[RetrievedItem] = []
        for claim in claims:
            text = (
                f"[{claim.claim_type}] ({claim.polarity}) "
                f"{claim.claim_text} "
                f"(confidence={claim.extraction_confidence:.2f})"
            )
            items.append(
                RetrievedItem.create(
                    item_id=f"tool:claim:{claim.claim_id}",
                    item_type=ItemType.claim,
                    text=text[:_TOOL_RESULT_MAX_CHARS],
                    score=claim.extraction_confidence,
                    trust_weight=0.75,
                    extraction_confidence=claim.extraction_confidence,
                    citation_meta=CitationMeta(
                        title=f"Claim: {claim.claim_type}",
                        url=None,
                        source_name="knowledge_graph",
                        published_at=None,
                        entity_name=entity_name,
                    ),
                )
            )

        log.info(
            "tool_executed",
            tool="search_claims",
            latency_ms=round((time.monotonic() - t0) * 1000),
            items_returned=len(items),
        )
        return items

    async def _handle_search_events(
        self,
        tool_call: ToolUseBlock,
        entity_name: str,
        event_type: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> list[RetrievedItem]:
        """Search structured corporate events for an entity via S7.search_events.

        date_from and date_to are forwarded to S7 to enable timeline filtering.
        Returns [] on any error (graceful degradation).
        """
        if self._s7 is None:
            log.warning("tool_handler_missing_port", tool="search_events", port="s7")
            return []
        entity_id = await self._resolve_entity_by_name("search_events", entity_name)
        if entity_id is None:
            return []
        event_types = [event_type] if event_type else None

        t0 = time.monotonic()
        try:
            events = await asyncio.wait_for(
                self._s7.search_events(
                    entity_ids=[entity_id],
                    event_types=event_types,
                    date_from=_parse_dt(date_from),
                    date_to=_parse_dt(date_to),
                    top_k=20,
                ),
                timeout=self._timeout,
            )
        except Exception as e:
            log.warning("tool_failed", tool="search_events", error=str(e))
            return []

        if not events:
            log.warning("tool_no_data", tool="search_events", entity_name=entity_name)
            return []

        items: list[RetrievedItem] = []
        for event in events:
            text = (
                f"[{event.event_type}]"
                + (f" ({event.event_subtype})" if event.event_subtype else "")
                + (f" on {event.event_date}" if event.event_date else "")
                + f": {event.event_text}"
            )
            items.append(
                RetrievedItem.create(
                    item_id=f"tool:event:{event.event_id}",
                    item_type=ItemType.event,
                    text=text[:_TOOL_RESULT_MAX_CHARS],
                    score=event.extraction_confidence,
                    trust_weight=0.78,
                    citation_meta=CitationMeta(
                        title=f"Event: {event.event_type}",
                        url=None,
                        source_name="knowledge_graph",
                        published_at=None,
                        entity_name=entity_name,
                    ),
                )
            )

        log.info(
            "tool_executed",
            tool="search_events",
            latency_ms=round((time.monotonic() - t0) * 1000),
            items_returned=len(items),
        )
        return items

    async def _handle_get_contradictions(
        self,
        tool_call: ToolUseBlock,
        entity_name: str,
        confidence_threshold: float = 0.5,
    ) -> list[RetrievedItem]:
        """Retrieve analyst claim contradictions for an entity via S7.get_contradictions.

        Returns one RetrievedItem per contradiction pair. Returns [] on any error.
        """
        if self._s7 is None:
            log.warning("tool_handler_missing_port", tool="get_contradictions", port="s7")
            return []
        entity_id = await self._resolve_entity_by_name("get_contradictions", entity_name)
        if entity_id is None:
            return []

        t0 = time.monotonic()
        try:
            contradictions = await asyncio.wait_for(
                self._s7.get_contradictions(entity_id=entity_id, top_k=10),
                timeout=self._timeout,
            )
        except Exception as e:
            log.warning("tool_failed", tool="get_contradictions", error=str(e))
            return []

        # Filter by confidence_threshold (S7 doesn't accept threshold param in v1)
        contradictions = [c for c in contradictions if c.strength >= confidence_threshold]

        if not contradictions:
            log.warning("tool_no_data", tool="get_contradictions", entity_name=entity_name)
            return []

        items: list[RetrievedItem] = []
        for contradiction in contradictions:
            sides_text = ""
            for i, side in enumerate(contradiction.sides, 1):
                sides_text += f"\n  Side {i}: {side}"
            text = (
                f"[CONTRADICTION: {contradiction.claim_type}] "
                f"strength={contradiction.strength:.2f} "
                f"detected={contradiction.detected_at}" + sides_text
            )
            items.append(
                RetrievedItem.create(
                    item_id=f"tool:contradiction:{contradiction.claim_type}:{entity_id}",
                    item_type=ItemType.claim,
                    text=text[:_TOOL_RESULT_MAX_CHARS],
                    score=contradiction.strength,
                    trust_weight=0.70,
                    citation_meta=CitationMeta(
                        title=f"Contradiction: {contradiction.claim_type}",
                        url=None,
                        source_name="knowledge_graph",
                        published_at=None,
                        entity_name=entity_name,
                    ),
                )
            )

        log.info(
            "tool_executed",
            tool="get_contradictions",
            latency_ms=round((time.monotonic() - t0) * 1000),
            items_returned=len(items),
        )
        return items

    def _format_graph(self, entity_name: str, graph: Any) -> str:
        """Format an EgocentricGraph as compact text for LLM context injection."""
        lines = [f"Knowledge graph: {entity_name} ({len(graph.nodes)} nodes, {len(graph.edges)} edges)"]
        if graph.nodes:
            lines.append("Nodes:")
            for node in graph.nodes[:20]:
                lines.append(f"  {node}")
        if graph.edges:
            lines.append("Edges:")
            for edge in graph.edges[:30]:
                lines.append(f"  {edge}")
        return "\n".join(lines)
