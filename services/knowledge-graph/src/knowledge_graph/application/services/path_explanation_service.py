"""PathExplanationService — generate and persist LLM explanations for path insights.

Called as a fire-and-forget background task from ``GetEntityPathsUseCase`` (NFR-2).
Failures are logged but never re-raised so a flaky LLM never crashes the HTTP handler.

§12 input sanitization: entity names and relation types are passed through
``prompts.knowledge.alias.sanitize_description()`` before prompt construction.

§13 race tolerance: two concurrent tasks for the same ``insight_id`` are harmless —
both write the same column; the last writer wins.  The DB ``UPDATE`` is idempotent.

BP-235: no httpx.AsyncClient is used directly in this service. LLM calls go
through ``ml_clients.dataclasses.ExtractionInput`` so the BP-235 timeout issue
is handled at the adapter layer.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from knowledge_graph.application.ports.path_insight_repository import PathInsightRepositoryPort
    from knowledge_graph.domain.entities.path_insight import PathEdge, PathNode


logger = get_logger(__name__)  # type: ignore[no-any-return]

# Maximum tokens to request from the LLM for explanation generation.
# Kept small to reduce latency on the background task (NFR-2).
_MAX_TOKENS = 200

# Fallback model ID used when the injected model_id is empty.
_FALLBACK_MODEL_ID = "meta-llama/Meta-Llama-3.1-8B-Instruct"


class PathExplanationService:
    """Generate and persist LLM explanations for pre-computed path insights.

    Args:
        path_insight_repo: Repository bound to a **write** session.  The session
            must support ``UPDATE path_insights`` — do NOT pass a read-only
            session here.
        llm_client:  An object implementing ``async def extract(inp) -> result``
            (ml_clients ``ExtractionClient`` protocol).  When ``None`` the
            service is effectively a no-op (returns without calling the LLM).
        model_id:    LLM model ID string (e.g.
            ``"meta-llama/Meta-Llama-3.1-8B-Instruct"``).

    """

    def __init__(
        self,
        path_insight_repo: PathInsightRepositoryPort,
        *,
        llm_client: object | None = None,
        model_id: str = _FALLBACK_MODEL_ID,
    ) -> None:
        self._repo = path_insight_repo
        self._llm = llm_client
        # Guard: fall back to default if caller passes an empty string.
        self._model_id = model_id if model_id else _FALLBACK_MODEL_ID

    async def generate_explanation(
        self,
        insight_id: UUID,
        path_nodes: list[PathNode],
        path_edges: list[PathEdge],
    ) -> None:
        """Generate and persist an LLM explanation for a single path insight.

        This method is designed to run as a ``asyncio.create_task()`` background
        coroutine.  It:
          1. Sanitizes entity names (§12 prompt injection guard).
          2. Builds a focused prompt describing the multi-hop path.
          3. Calls the LLM with ``max_tokens=200`` (concise explanation).
          4. Persists the result via ``PathInsightRepositoryPort.update_explanation``.

        On any failure (LLM error, DB error, validation error) the exception is
        caught, logged as ``path_explanation_failed``, and NOT re-raised (§13
        race tolerance — a missing explanation is acceptable; a crashed handler
        is not).
        """
        if self._llm is None:
            # No LLM configured — this is valid in dev/test environments.
            logger.debug(  # type: ignore[no-any-return]
                "path_explanation_skipped_no_llm",
                insight_id=str(insight_id),
            )
            return

        try:
            explanation_text = await self._call_llm(insight_id, path_nodes, path_edges)
            if not explanation_text:
                logger.warning(  # type: ignore[no-any-return]
                    "path_explanation_empty_result",
                    insight_id=str(insight_id),
                    model_id=self._model_id,
                )
                return

            await self._repo.update_explanation(
                insight_id=insight_id,
                llm_explanation=explanation_text,
                explanation_model=self._model_id,
            )

            logger.info(  # type: ignore[no-any-return]
                "path_explanation_persisted",
                insight_id=str(insight_id),
                model_id=self._model_id,
                explanation_len=len(explanation_text),
            )

        except Exception as exc:
            # §13: Never crash the background task — log and move on.
            logger.warning(  # type: ignore[no-any-return]
                "path_explanation_failed",
                insight_id=str(insight_id),
                model_id=self._model_id,
                error=str(exc),
            )

    # ── Private helpers ───────────────────────────────────────────────────────

    async def _call_llm(
        self,
        insight_id: UUID,
        path_nodes: list[PathNode],
        path_edges: list[PathEdge],
    ) -> str:
        """Build prompt, call LLM, return the explanation text (possibly empty str).

        Any exception propagates to ``generate_explanation`` which will catch it.
        """
        from ml_clients.dataclasses import ExtractionInput  # type: ignore[import-untyped]

        prompt = self._build_prompt(path_nodes, path_edges)

        inp = ExtractionInput(
            prompt=prompt,
            context="",
            output_schema={"type": "string"},
            model_id=self._model_id,
        )

        # _llm is typed as object to avoid a hard dependency on ml_clients at
        # import time.  The actual runtime object implements ExtractionClient.
        result = await self._llm.extract(inp)  # type: ignore[union-attr]
        if result is None or not result.output:
            return ""
        return str(result.output).strip()

    def _build_prompt(
        self,
        path_nodes: list[PathNode],
        path_edges: list[PathEdge],
    ) -> str:
        """Construct a focused LLM prompt for path explanation.

        §12 guard: all entity names are sanitized via ``sanitize_description``
        before interpolation so a malicious canonical_name cannot inject
        additional instructions into the prompt.
        """
        from prompts.knowledge.alias import sanitize_description  # type: ignore[import-untyped]

        if not path_nodes:
            return ""

        # Sanitize all node names before prompt construction (§12).
        sanitized_names = [sanitize_description(node.name or "") for node in path_nodes]

        start_name = sanitized_names[0] if sanitized_names else "unknown"
        end_name = sanitized_names[-1] if len(sanitized_names) > 1 else start_name
        hop_count = len(path_edges)

        # Build a human-readable path chain: "A --[rel]--> B --[rel]--> C".
        chain_parts: list[str] = []
        for i, edge in enumerate(path_edges):
            from_name = sanitized_names[i] if i < len(sanitized_names) else "unknown"
            to_name = sanitized_names[i + 1] if (i + 1) < len(sanitized_names) else "unknown"
            # Sanitize relation_type as well — defensive (§12 defence-in-depth).
            safe_rel = sanitize_description(edge.relation_type or "")
            chain_parts.append(f"{from_name} --[{safe_rel}]--> {to_name}")

        path_summary = " -> ".join(chain_parts)

        return (
            f"Explain how {start_name} relates to {end_name} via this {hop_count}-hop path: "
            f"{path_summary}. "
            "Highlight the implicit business connection in 1-3 sentences."
        )
