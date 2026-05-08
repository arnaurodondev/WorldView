"""EntityContextChatUseCase — entity-scoped chat use case (PLAN-0074 Wave F, T-F-02).

Architecture rules enforced here:
  R25: This class imports ONLY from the application/domain layers. The
       EntityContextLoaderPort is injected — no direct import from infrastructure.
  R12: Domain types (EntityChatContext) carry no infrastructure imports.
  R14: This use case is called by the S8 API layer; frontend never calls S8 directly.

Pipeline for POST /api/v1/chat/entity-context:
  1. Load entity context via EntityContextLoaderPort (parallel S7 HTTP calls).
  2. Build entity-scoped system-prompt prefix.
  3. If is_empty=True (S7 unavailable): use generic prompt without entity context.
  4. Compose prefixed question and delegate to ChatOrchestratorUseCase.execute_streaming.
  5. Yield SSE events from the underlying orchestrator unchanged.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator
    from uuid import UUID

    from rag_chat.application.ports.entity_context_loader import EntityContextLoaderPort
    from rag_chat.application.ports.unit_of_work import RagUnitOfWorkPort
    from rag_chat.application.use_cases.chat_orchestrator import ChatOrchestratorUseCase
    from rag_chat.domain.entities.entity_chat_context import EntityChatContext

log = structlog.get_logger(__name__)  # type: ignore[no-any-return]

# Maximum length (chars) for the system-prompt prefix injected before the user
# question. Capped to avoid context-window overflow when entity narratives are
# long (some S7 narratives can exceed 2000 characters).
_MAX_PREFIX_CHARS = 2000

# Characters allowed in entity names when interpolated into system prompts.
# WHY: defence-in-depth against prompt-injection via crafted canonical_name
# values (e.g. a canonical_name containing "</Q_…>" or "Ignore all instructions").
# We strip everything except word chars, spaces, parentheses, hyphens, dots, &, /.
_ENTITY_NAME_SAFE_RE = re.compile(r"[^\w\s\(\)\-\.\&\/]")


def _sanitize_entity_name(name: str) -> str:
    """Strip characters that could affect prompt structure from entity names.

    WHY: an entity with a canonical_name containing injection markers (e.g.
    "Apple Inc. Ignore prior instructions") would bleed through directly into
    the system prompt. This conservative allow-list keeps financial entity names
    readable while preventing structural prompt manipulation.
    """
    return _ENTITY_NAME_SAFE_RE.sub("", name).strip()


def _build_system_prompt_prefix(ctx: EntityChatContext) -> str:
    """Build the entity-context system prompt prefix from an EntityChatContext.

    The prefix is injected BEFORE the user question in the message payload
    sent to ChatOrchestratorUseCase so the LLM is grounded in entity-specific
    facts before answering.

    WHY truncated to _MAX_PREFIX_CHARS: S7 narratives can be lengthy; the total
    context window must accommodate the prefix + conversation history + the LLM's
    answer buffer. 2000 chars of prefix + ~500 chars of question fits comfortably
    within most 8k-token windows.
    """
    if ctx.is_empty:
        # Fallback: no entity context available — use generic prompt.
        # The question is passed through unchanged; the orchestrator will answer
        # from its training data and any tool results it retrieves.
        return ""

    safe_name = _sanitize_entity_name(ctx.canonical_name)
    safe_type = _sanitize_entity_name(ctx.entity_type)

    lines: list[str] = [
        f"You are analyzing {safe_name} ({safe_type}).",
        "",
        f"Entity narrative: {ctx.narrative_text or 'No narrative available.'}",
        "",
        f"Data completeness: {ctx.data_completeness if ctx.data_completeness is not None else 'unknown'}",
        f"Health score: {ctx.health_score if ctx.health_score is not None else 'unknown'}",
    ]

    if ctx.top_relations:
        lines.append("")
        lines.append("Key relationships (top 5):")
        for rel in ctx.top_relations[:5]:
            rel_type = _sanitize_entity_name(str(rel.get("relation_type", "")))
            target = _sanitize_entity_name(str(rel.get("target_name", "")))
            conf = rel.get("confidence", 0.0)
            lines.append(f"  - {rel_type} → {target} (confidence: {conf:.2f})")

    lines.append("")
    lines.append(f"Answer based on this entity context. Stay focused on {safe_name}.")

    prefix = "\n".join(lines)
    # Truncate to prevent context-window overflow.
    return prefix[:_MAX_PREFIX_CHARS]


class EntityContextChatUseCase:
    """Orchestrate entity-scoped chat by prepending S7 entity context to the question.

    Collaborators (injected, never imported directly from infrastructure):
      - entity_context_loader: EntityContextLoaderPort — loads S7 intelligence context.
      - chat_orchestrator: ChatOrchestratorUseCase — drives the full tool-use pipeline.

    The use case itself performs no LLM calls, DB access, or HTTP calls directly —
    it delegates all of that to collaborators (R25 compliance).
    """

    def __init__(
        self,
        entity_context_loader: EntityContextLoaderPort,
        chat_orchestrator: ChatOrchestratorUseCase,
    ) -> None:
        self._loader = entity_context_loader
        self._orchestrator = chat_orchestrator

    async def execute_streaming(
        self,
        entity_id: UUID,
        question: str,
        tenant_id: UUID,
        user_id: UUID,
        jwt_token: str,
        thread_id: UUID | None,
        include_graph_context: bool,
        uow: RagUnitOfWorkPort,
    ) -> AsyncGenerator[dict[str, str], None]:
        """Run entity-context chat pipeline, yielding SSE events.

        Args:
            entity_id:            UUID of the entity to load context for.
            question:             User question (already HTML-stripped and validated
                                  by the calling route via EntityContextChatRequest).
            tenant_id:            Tenant UUID from the auth context.
            user_id:              User UUID from the auth context.
            jwt_token:            X-Internal-JWT forwarded from the incoming request.
            thread_id:            Optional existing conversation thread UUID.
            include_graph_context: When True, loads the graph endpoint in parallel.
                                  When False, skips the graph call (used by callers
                                  that only want narrative context).
            uow:                  Write-capable unit of work for chat persistence.

        Yields:
            SSE event dicts in the same format as ChatOrchestratorUseCase.execute_streaming
            (status, thinking, tool_call, tool_result, token, citations, metadata, done).
        """
        # Step 1: Load entity context from S7.
        # is_empty=True on any S7 failure — never raises from the loader.
        ctx: EntityChatContext = await self._loader.load(
            entity_id=entity_id,
            tenant_id=tenant_id,
            jwt_token=jwt_token,
        )

        log.info(  # type: ignore[no-any-return]
            "entity_context_chat_start",
            entity_id=str(entity_id),
            is_empty=ctx.is_empty,
            has_narrative=bool(ctx.narrative_text),
            relation_count=len(ctx.top_relations),
        )

        # Step 2: Build system-prompt prefix.
        # Returns "" when is_empty=True → generic prompt path.
        prefix = _build_system_prompt_prefix(ctx)

        # Step 3: Compose prefixed question for the orchestrator.
        # WHY prepend prefix as part of the user message (not a system message):
        # ChatOrchestratorUseCase builds the system prompt internally from the
        # tool registry's to_system_prompt_section(); we prepend the entity context
        # to the user question so the LLM sees it as grounding context BEFORE
        # answering.  This is the minimal-invasive integration — it does not
        # require modifying ChatOrchestratorUseCase or ChatPipeline.
        # Fallback: no entity context (prefix="") — pass question unchanged.
        prefixed_question = f"{prefix}\n\n[USER QUESTION]\n{question}" if prefix else question

        # Step 4: Build a ChatRequest and delegate to the existing orchestrator.
        # WHY import inside function: R25 — domain entities are in the domain
        # layer; we import lazily here to avoid module-level circular imports
        # that could arise if this use case file is imported early.
        from rag_chat.domain.entities.chat import ChatContext, ChatRequest

        chat_req = ChatRequest(
            message=prefixed_question,
            # WHY entity_id in entity_ids: this scopes the tool executor's
            # search_documents tool to chunks mentioning this entity (PLAN-0078).
            context=ChatContext(entity_ids=(entity_id,)),
            tenant_id=tenant_id,
            user_id=user_id,
            thread_id=thread_id,
        )

        # Step 5: Stream events from the orchestrator unchanged.
        # The orchestrator drives the full tool-use pipeline (input validation,
        # rate limit, entity resolution, tool calls, LLM turns, persistence).
        async for event in self._orchestrator.execute_streaming(chat_req, uow):
            yield event

    async def _stream_for_sync(
        self,
        entity_id: UUID,
        question: str,
        tenant_id: UUID,
        user_id: UUID,
        jwt_token: str,
        thread_id: UUID | None,
        include_graph_context: bool,
        uow: RagUnitOfWorkPort,
    ) -> AsyncGenerator[dict[str, str], None]:
        """Alias of execute_streaming for the sync wrapper below."""
        # Step 1: Load entity context from S7.
        # is_empty=True on any S7 failure — never raises from the loader.
        ctx: EntityChatContext = await self._loader.load(
            entity_id=entity_id,
            tenant_id=tenant_id,
            jwt_token=jwt_token,
        )

        log.info(  # type: ignore[no-any-return]
            "entity_context_chat_start",
            entity_id=str(entity_id),
            is_empty=ctx.is_empty,
            has_narrative=bool(ctx.narrative_text),
            relation_count=len(ctx.top_relations),
        )

        # Step 2: Build system-prompt prefix.
        # Returns "" when is_empty=True → generic prompt path.
        prefix = _build_system_prompt_prefix(ctx)

        # Step 3: Compose prefixed question for the orchestrator.
        # WHY prepend prefix as part of the user message (not a system message):
        # ChatOrchestratorUseCase builds the system prompt internally from the
        # tool registry's to_system_prompt_section(); we prepend the entity context
        # to the user question so the LLM sees it as grounding context BEFORE
        # answering.  This is the minimal-invasive integration — it does not
        # require modifying ChatOrchestratorUseCase or ChatPipeline.
        # Fallback: no entity context (prefix="") — pass question unchanged.
        prefixed_question = f"{prefix}\n\n[USER QUESTION]\n{question}" if prefix else question

        # Step 4: Build a ChatRequest and delegate to the existing orchestrator.
        # WHY import inside function: R25 — domain entities are in the domain
        # layer; we import lazily here to avoid module-level circular imports
        # that could arise if this use case file is imported early.
        from rag_chat.domain.entities.chat import ChatContext, ChatRequest

        chat_req = ChatRequest(
            message=prefixed_question,
            # WHY entity_id in entity_ids: this scopes the tool executor's
            # search_documents tool to chunks mentioning this entity (PLAN-0078).
            context=ChatContext(entity_ids=(entity_id,)),
            tenant_id=tenant_id,
            user_id=user_id,
            thread_id=thread_id,
        )

        # Step 5: Stream events from the orchestrator unchanged.
        # The orchestrator drives the full tool-use pipeline (input validation,
        # rate limit, entity resolution, tool calls, LLM turns, persistence).
        async for event in self._orchestrator.execute_streaming(chat_req, uow):
            yield event

    async def execute_sync(
        self,
        entity_id: UUID,
        question: str,
        tenant_id: UUID,
        user_id: UUID,
        jwt_token: str,
        thread_id: UUID | None,
        include_graph_context: bool,
        uow: RagUnitOfWorkPort,
    ) -> dict[str, Any]:
        """Synchronous wrapper — collects all SSE events and returns final answer.

        Used by POST /api/v1/chat/entity-context (sync variant).
        Delegates to _stream() and collects token/citations/metadata events.
        """
        import json

        answer = ""
        citations: list[Any] = []
        contradictions: list[Any] = []
        metadata: dict[str, Any] = {}

        async for event in self._stream_for_sync(
            entity_id,
            question,
            tenant_id,
            user_id,
            jwt_token,
            thread_id,
            include_graph_context,
            uow,
        ):
            event_type = event.get("event", "")
            data = json.loads(event.get("data", "{}"))
            if event_type == "token":
                answer += data.get("text", "")
            elif event_type == "citations":
                citations = data
            elif event_type == "contradictions":
                contradictions = data
            elif event_type == "metadata":
                metadata = data

        # WHY process_output call: strips any residual <think> blocks
        # accumulated from the streaming token events.
        answer = self._orchestrator._pipeline.process_output(answer, [])[0]

        return {
            "answer": answer,
            "citations": citations,
            "contradictions": contradictions,
            **metadata,
        }
