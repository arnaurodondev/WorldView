"""AgenticBriefGenerator — experimental, flag-gated agentic morning brief.

PLAN-0099 Wave C scaffold. OFF by default (``RAG_CHAT_BRIEF_AGENTIC_ENABLED``).
Intended for A/B comparison against ``GenerateBriefingUseCase.execute_public_morning``
(the standard single-turn generator).

High-level loop (see docstring on :meth:`AgenticBriefGenerator.generate`):
    1. PLAN: ask the LLM what tools it needs to draft a brief.
    2. CALL: dispatch each ``tool_call`` through the rag-chat ``ToolExecutor``
       (re-using the existing per-domain handlers).
    3. INJECT: append every tool result into the message stack.
    4. LOOP: repeat 1-3 until the LLM returns ``finish_reason="stop"`` OR the
       per-generation tool-call budget (``brief_agentic_max_tool_calls``) is
       exhausted.
    5. ASSEMBLE: take the final ``text`` chunk and wrap it in the same response
       envelope as ``execute_public_morning`` (``content``/``risk_summary``/
       ``citations``/``generated_at``) so the route layer needs no branching.

If anything blows up — exception, budget overrun, empty LLM response — we fall
back to the standard generator passed via ``fallback`` and increment
:data:`brief_agentic_fallback_total` with the reason label.

WHY this lives outside ``generate_briefing.py``: that file is owned by the
parallel Wave A+B agent (PLAN-0099). Keeping the agentic path in its own module
makes the flag-gated rollout reviewable and lets us revert with a single
deletion if the A/B does not pan out.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Protocol
from uuid import UUID

import structlog
from prompts.briefing.agentic_plan import AGENTIC_BRIEF_PLAN

from rag_chat.application.metrics.prometheus import (
    brief_agentic_fallback_total,
    brief_agentic_llm_calls_total,
    brief_agentic_tool_calls_total,
)

if TYPE_CHECKING:  # pragma: no cover — import-time only
    from tools.types import ToolUseBlock  # type: ignore[import-untyped]

    from rag_chat.application.pipeline.tool_executor import ToolExecutor
    from rag_chat.config import Settings
    from rag_chat.infrastructure.llm.provider_chain import LLMProviderChain

log = structlog.get_logger(__name__)  # type: ignore[no-any-return]


# ── Tool subset (see plan T-C-02) ────────────────────────────────────────────
# Only tools relevant to a *morning* portfolio brief. Pulled from
# ``tool_registry_builder.py``; the LLM only ever sees these specs so it cannot
# wander off into e.g. ``create_alert``.  This is also the only place we accept
# new tools — adding one here is the explicit opt-in.
_BRIEF_AGENTIC_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "get_portfolio_news",
        "get_top_movers",
        "screen_universe",
        "search_documents",
        "get_economic_calendar",
        "get_morning_brief",
    }
)


class StandardBriefFallback(Protocol):
    """The minimal slice of ``GenerateBriefingUseCase`` the fallback needs.

    Keeping this a Protocol (not a concrete import) means the agentic generator
    has zero hard dependency on the standard generator's module — the parallel
    Wave A+B agent can rewrite ``generate_briefing.py`` without breaking us.
    """

    async def execute_public_morning(
        self,
        user_id: str,
        tenant_id: str,
        internal_jwt: str | None = None,
    ) -> dict[str, Any]: ...


class AgenticBriefGenerator:
    """Iterative LLM tool-use loop for morning briefs (experimental).

    Args:
        llm_chain:     The same LLMProviderChain the standard generator uses.
                       We call ``chat_with_tools`` (NOT ``stream``) so we get a
                       structured tool-call list back.
        tool_executor: A per-request :class:`ToolExecutor` already bound to the
                       caller's auth context.  Built by
                       :class:`ToolExecutorFactory.for_request`.
        settings:      Rag-chat settings; we read
                       ``brief_agentic_max_tool_calls`` from here.
        fallback:      The standard ``GenerateBriefingUseCase`` (or any
                       :class:`StandardBriefFallback`) used when the agentic
                       path errors / exhausts budget / returns no text.

    NOTE:
        This is a scaffold. The PLAN prompt copy below is intentionally
        minimal — it does NOT (yet) match the full ``MORNING_BRIEFING`` prompt
        used by the standard generator. The Wave A+B agent owns the prompt
        engineering; this scaffold only proves the wiring.
    """

    # Phase 2B (2026-06-05): the planning prompt body lives in
    # ``libs/prompts/briefing/agentic_plan.py`` (``AGENTIC_BRIEF_PLAN``) for
    # content-addressable versioning + drift detection. The module-level
    # alias here keeps the existing class-internal call site readable.
    _PLAN_PROMPT = AGENTIC_BRIEF_PLAN.template
    _PLAN_PROMPT_ID = AGENTIC_BRIEF_PLAN.identifier()

    def __init__(
        self,
        llm_chain: LLMProviderChain,
        tool_executor: ToolExecutor,
        settings: Settings,
        fallback: StandardBriefFallback,
    ) -> None:
        self._llm_chain = llm_chain
        self._tool_executor = tool_executor
        self._settings = settings
        self._fallback = fallback

    async def generate(self, user_id: UUID, tenant_id: UUID) -> dict[str, Any]:
        """Run the agentic loop; fall back to the standard generator on failure.

        Returns the same response envelope as
        :meth:`GenerateBriefingUseCase.execute_public_morning` so the route
        layer can call either generator interchangeably.

        Loop budget is bounded by ``settings.brief_agentic_max_tool_calls``.
        Exceeding it triggers fallback with reason ``budget_exhausted``.
        """
        max_tool_calls = int(self._settings.brief_agentic_max_tool_calls)

        try:
            envelope = await self._run_loop(
                user_id=user_id,
                tenant_id=tenant_id,
                max_tool_calls=max_tool_calls,
            )
        except _BudgetExhausted:
            # Loop hit the configured ``brief_agentic_max_tool_calls`` cap.
            # WHY metric BEFORE fallback: if the fallback itself raises we
            # still want the counter to show the agentic budget was hit.
            brief_agentic_fallback_total.labels(reason="budget_exhausted").inc()
            log.warning(  # type: ignore[no-any-return]
                "brief_agentic_budget_exhausted",
                user_id=str(user_id),
                max_tool_calls=max_tool_calls,
                # Drift detection: tag the prompt identifier so dashboards
                # can correlate budget-exhaustion rate with prompt rollouts.
                briefing_plan_prompt=self._PLAN_PROMPT_ID,
            )
            return await self._fallback.execute_public_morning(
                user_id=str(user_id),
                tenant_id=str(tenant_id),
            )
        except Exception as exc:
            # Any other failure — provider chain down, tool executor blew up,
            # malformed tool args, etc. R9 safe-degrade to the standard path.
            brief_agentic_fallback_total.labels(reason="exception").inc()
            log.warning(  # type: ignore[no-any-return]
                "brief_agentic_fallback_exception",
                user_id=str(user_id),
                error=str(exc) or repr(exc),
                error_type=type(exc).__name__,
                briefing_plan_prompt=self._PLAN_PROMPT_ID,
            )
            return await self._fallback.execute_public_morning(
                user_id=str(user_id),
                tenant_id=str(tenant_id),
            )

        if not envelope.get("content"):
            # LLM gave us no usable narrative — treat the same as a hard
            # failure so users always see *something*.
            brief_agentic_fallback_total.labels(reason="empty_response").inc()
            log.warning("brief_agentic_empty_response", user_id=str(user_id))  # type: ignore[no-any-return]
            return await self._fallback.execute_public_morning(
                user_id=str(user_id),
                tenant_id=str(tenant_id),
            )

        return envelope

    # ── Internals ────────────────────────────────────────────────────────────

    async def _run_loop(
        self,
        *,
        user_id: UUID,
        tenant_id: UUID,
        max_tool_calls: int,
    ) -> dict[str, Any]:
        """Drive the planning ↔ tool-call loop and assemble the final envelope.

        Raises:
            _BudgetExhausted: if ``max_tool_calls`` was reached before the LLM
                emitted ``finish_reason="stop"``.
        """
        tool_specs = self._brief_tool_specs()
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": self._PLAN_PROMPT},
            {
                "role": "user",
                "content": (f"Generate this morning's portfolio brief for user {user_id} " f"(tenant {tenant_id})."),
            },
        ]

        tool_calls_made = 0
        final_text: str | None = None

        # Hard cap on LLM round-trips too — without one a buggy provider could
        # keep emitting empty tool_calls forever. We allow at most
        # ``max_tool_calls + 2`` LLM hops (1 final + 1 safety margin).
        max_llm_hops = max_tool_calls + 2
        for _hop in range(max_llm_hops):
            brief_agentic_llm_calls_total.inc()
            response = await self._llm_chain.chat_with_tools(
                messages=messages,
                tools=tool_specs,
            )

            if not response.has_tool_calls:
                # Either ``finish_reason="stop"`` (final answer) or
                # ``finish_reason="length"`` (truncated). Both end the loop;
                # if text is empty we'll trip the empty-response fallback in
                # the caller.
                final_text = response.text or ""
                break

            for tool_call in response.tool_calls:
                if tool_calls_made >= max_tool_calls:
                    raise _BudgetExhausted

                if tool_call.name not in _BRIEF_AGENTIC_TOOL_NAMES:
                    # LLM asked for a tool outside the brief subset — skip it
                    # (no exception; just feed back an empty result so the loop
                    # can converge). This shouldn't happen because we only
                    # advertise the subset, but defence-in-depth.
                    log.warning(  # type: ignore[no-any-return]
                        "brief_agentic_unexpected_tool",
                        tool=tool_call.name,
                    )
                    messages.append(_tool_result_msg(tool_call.id, "[]"))
                    continue

                brief_agentic_tool_calls_total.labels(tool=tool_call.name).inc()
                tool_calls_made += 1

                result = await self._execute_tool(tool_call)
                messages.append(_tool_result_msg(tool_call.id, result))

        # If we exited the for-loop naturally (max_llm_hops reached) without
        # final_text, the agent is stuck. Treat as budget overrun.
        if final_text is None:
            raise _BudgetExhausted

        return _wrap_envelope(final_text)

    async def _execute_tool(self, tool_call: ToolUseBlock) -> str:
        """Dispatch via the bound ToolExecutor; serialise the result to a string.

        We always return a string (even on error) so the message stack stays
        well-formed for the next LLM hop. The orchestrator-side ToolExecutor
        already logs/metrics tool errors, so we don't double-log here.
        """
        import json  # local import keeps module import-time tiny

        from rag_chat.application.pipeline.tool_executor import ToolUseBlock as ExecutorToolUseBlock

        # The libs/tools ToolUseBlock and the executor's local ToolUseBlock are
        # near-clones; the executor expects its own dataclass shape. Convert.
        executor_block = ExecutorToolUseBlock(
            name=tool_call.name,
            input=tool_call.input,
            tool_use_id=tool_call.id,
        )
        try:
            result = await self._tool_executor.execute(executor_block)
        except Exception as exc:  # pragma: no cover — executor.execute already swallows
            return json.dumps({"error": str(exc), "type": type(exc).__name__})

        if result is None:
            return "[]"
        if isinstance(result, list):
            return json.dumps([_item_to_dict(it) for it in result])
        return json.dumps(_item_to_dict(result))

    def _brief_tool_specs(self) -> list[dict[str, Any]]:
        """Return the OpenAI-format tool schemas for the brief-relevant subset.

        WHY iterate the executor's registry: we re-use the same canonical specs
        registered in ``tool_registry_builder.py`` so adding a tool there
        automatically makes it available here (subject to allowlist gating).
        """
        registry = self._tool_executor._registry  # — intentional read of internal registry
        specs: list[dict[str, Any]] = []
        for tool_name in _BRIEF_AGENTIC_TOOL_NAMES:
            spec = registry.get_spec(tool_name)
            if spec is None:
                # Tool advertised in the allowlist but missing from the
                # manifest — treat as drift. Skip silently here (the boot-time
                # validate_registry_parity already catches this); we just
                # don't expose a broken tool to the LLM.
                continue
            specs.append(_to_openai_tool_schema(spec))
        return specs


# ── Helpers (module-level so they're trivially testable) ─────────────────────


class _BudgetExhausted(Exception):  # noqa: N818 — internal sentinel, not a public Error
    """Internal sentinel — raised when the tool-call budget is hit."""


def _tool_result_msg(tool_call_id: str, content: str) -> dict[str, Any]:
    """Build the OpenAI-format ``role="tool"`` message that follows a tool call."""
    return {
        "role": "tool",
        "tool_call_id": tool_call_id,
        "content": content,
    }


def _item_to_dict(item: Any) -> Any:
    """Best-effort RetrievedItem → dict conversion for JSON serialisation."""
    if hasattr(item, "to_dict"):
        return item.to_dict()
    if hasattr(item, "__dict__"):
        # Filter out private/dunder attrs — keep only the data fields.
        return {k: v for k, v in item.__dict__.items() if not k.startswith("_")}
    return item


def _to_openai_tool_schema(spec: Any) -> dict[str, Any]:
    """Convert a libs/tools ToolSpec → OpenAI tool-call JSON schema.

    Best-effort: if the spec doesn't expose ``parameters`` in a recognisable
    shape we still emit a stub so the LLM can at least *see* the tool name.
    """
    properties: dict[str, Any] = {}
    required: list[str] = []
    for param in getattr(spec, "parameters", []) or []:
        properties[param.name] = {
            "type": _normalise_json_type(getattr(param, "type", "string")),
            "description": getattr(param, "description", "") or "",
        }
        if getattr(param, "enum", None):
            properties[param.name]["enum"] = list(param.enum)
        if getattr(param, "required", False):
            required.append(param.name)

    return {
        "type": "function",
        "function": {
            "name": spec.name,
            "description": getattr(spec, "description", "") or "",
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        },
    }


def _normalise_json_type(raw: str) -> str:
    """Map our ParameterSpec ``type`` strings onto JSON-schema primitives."""
    return {
        "string": "string",
        "date": "string",  # ISO date → string at JSON level
        "integer": "integer",
        "int": "integer",
        "number": "number",
        "float": "number",
        "boolean": "boolean",
        "bool": "boolean",
        "array": "array",
        "object": "object",
    }.get(raw, "string")


def _wrap_envelope(narrative: str) -> dict[str, Any]:
    """Wrap the agentic narrative in the standard ``execute_public_morning`` envelope.

    The standard envelope carries far more fields (lead/sections/confidence/
    citations) than we populate here — those will be filled in once Wave A+B
    lands a real prompt + parser. For now we ship a minimal valid envelope so
    the route layer can serialise the response without crashing.
    """
    return {
        "content": narrative,
        "summary": None,
        "sections": [],
        "risk_summary": {},
        "entity_mentions": [],
        "citations": [],
        "generated_at": datetime.now(tz=UTC).isoformat(),
        "lead": None,
        "confidence": 0.0,
    }


__all__ = ["AgenticBriefGenerator", "StandardBriefFallback"]
