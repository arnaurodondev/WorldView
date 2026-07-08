"""SSE event emitter - converts pipeline events into SSE data frames (T-F-3-02).

Uses sse-starlette conventions: each emit method returns a dict with
"event" and "data" keys, suitable for direct use with EventSourceResponse.

PLAN-0067 W11-3: added emit_thinking, updated emit_tool_call (label field,
new input_summary param), updated emit_tool_result (item_count param).
"""

from __future__ import annotations

import json
import os
import re
from typing import TYPE_CHECKING, Any, ClassVar
from uuid import UUID

import structlog

from rag_chat.application.pipeline.sse_events import (
    PROTOCOL_VERSION_KEY,
    SSE_PROTOCOL_VERSION,
    SSEEventType,
)

if TYPE_CHECKING:
    from rag_chat.domain.entities.conversation import Citation, ContradictionRef

# Module-level structlog logger (R12 — never stdlib logging). Used for the
# ``grounding_sample_truncated`` observability event (PRD-0091 §13.2).
_log = structlog.get_logger(__name__)

# ── Tool label map ─────────────────────────────────────────────────────────────
# Maps tool names (from capability_manifest.yaml) to human-readable UI labels.
# WHY here: the SSEEmitter is the only layer that emits tool_call events, so
# co-locating the label map avoids a separate lookup on every call site.
#
# Phase-1 split: each entry is a (verb_template) — a base label used when the
# tool's input carries no useful identifier. When the input DOES carry one
# (ticker / entity / symbol), ``_human_tool_label`` weaves it in to produce a
# specific line ("Searching news for NVIDIA") instead of the generic one. This
# is DETERMINISTIC string templating only — NO extra LLM call (respects the
# DeepSeek-judge-budget cost rule).
_TOOL_LABELS: dict[str, str] = {
    "search_documents": "Searching documents...",
    "get_entity_news": "Searching news...",
    "get_entity_graph": "Building entity map...",
    "traverse_graph": "Traversing knowledge graph...",
    "search_entity_relations": "Mapping relationships...",
    "get_relations": "Querying the knowledge graph...",
    "search_claims": "Checking analyst claims...",
    "search_events": "Looking up corporate events...",
    "get_contradictions": "Detecting contradictions...",
    "get_portfolio_context": "Loading portfolio context...",
    "get_price_history": "Fetching price history...",
    "get_fundamentals_history": "Fetching fundamentals...",
    "get_entity_narrative": "Loading narrative...",
    "get_entity_paths": "Tracing entity paths...",
    "get_path_between": "Querying the knowledge graph...",
    "get_entity_health": "Computing health score...",
    "get_entity_intelligence": "Loading intelligence bundle...",
    # Risk-metrics family — templated, no LLM.
    "get_risk_metrics": "Computing risk metrics...",
    "compute_risk_metrics": "Computing risk metrics...",
    # PLAN-0081 Wave A: catalog tools
    "get_morning_brief": "Loading morning brief...",
    "compare_entities": "Comparing entities...",
    "screen_universe": "Screening universe...",
    "get_market_movers": "Fetching market movers...",
    "get_economic_calendar": "Loading economic calendar...",
    "get_earnings_calendar": "Loading earnings calendar...",
    # Chat prediction-market tool: Polymarket odds search
    "get_prediction_markets": "Searching prediction markets...",
    # PLAN-0082 Wave A: action tools
    "get_alerts": "Loading your alerts...",
    # PLAN-0082 Wave B: write action tools
    "create_alert": "Creating alert...",
}

# Per-tool template for the INPUT-AWARE label (Phase-1). When the tool's input
# carries a recognised identifier, the matching template here produces a
# specific line. ``{subject}`` is filled with the resolved identifier. Tools
# absent from this map fall back to their static ``_TOOL_LABELS`` entry even
# when an identifier is present (e.g. "Screening universe..." reads better
# without a subject). Keep templates short and present-progressive to match the
# rest of the chat chrome.
_TOOL_LABEL_TEMPLATES: dict[str, str] = {
    "get_entity_news": "Searching news for {subject}",
    "search_documents": "Searching documents for {subject}",
    "search_entity_relations": "Mapping relationships for {subject}",
    "get_relations": "Querying the knowledge graph for {subject}",
    "get_entity_graph": "Building entity map for {subject}",
    "search_claims": "Checking analyst claims on {subject}",
    "get_contradictions": "Detecting contradictions for {subject}",
    "get_price_history": "Fetching price history for {subject}",
    "get_fundamentals_history": "Fetching fundamentals for {subject}",
    "get_entity_narrative": "Loading narrative for {subject}",
    "get_entity_paths": "Tracing entity paths for {subject}",
    "get_entity_health": "Computing health score for {subject}",
    "get_entity_intelligence": "Loading intelligence for {subject}",
    "get_risk_metrics": "Computing risk metrics for {subject}",
    "compute_risk_metrics": "Computing risk metrics for {subject}",
    "compare_entities": "Comparing {subject}",
    "create_alert": "Creating alert for {subject}",
}

# Input keys probed (in order) to find the human "subject" of a tool call. The
# FIRST present, non-empty, string-coercible value wins. These are the safe,
# display-only identifier fields tool inputs carry — NEVER queries / free text
# (those are excluded from the SSE input_summary upstream anyway).
_SUBJECT_INPUT_KEYS: tuple[str, ...] = (
    "ticker",
    "symbol",
    "entity_name",
    "entity",
    "entity_id",
    "name",
    "source_entity",
)

# Optional ticker→display-name map so common symbols render as the recognisable
# company name ("NVDA" → "NVIDIA") rather than the bare ticker. Unknown tickers
# fall through to the raw symbol — correct and never wrong, just less polished.
# Intentionally small + deterministic (NO lookup service / LLM): this is pure
# display sugar on the hot streaming path.
_TICKER_DISPLAY_NAMES: dict[str, str] = {
    "NVDA": "NVIDIA",
    "AAPL": "Apple",
    "MSFT": "Microsoft",
    "GOOGL": "Alphabet",
    "GOOG": "Alphabet",
    "AMZN": "Amazon",
    "META": "Meta",
    "TSLA": "Tesla",
    "MSTR": "MicroStrategy",
    "AMD": "AMD",
    "INTC": "Intel",
    "NFLX": "Netflix",
}


def _resolve_subject(input_summary: dict[str, Any]) -> str | None:
    """Extract a short, human display subject from a tool's input summary.

    Deterministic + best-effort: probes :data:`_SUBJECT_INPUT_KEYS` in order,
    str-coerces the first present non-empty value, maps known tickers to their
    company name, and bounds the length. Returns ``None`` when no usable subject
    is present (caller then uses the static base label). NEVER raises — an odd
    input shape degrades to ``None`` rather than breaking the stream.
    """
    if not isinstance(input_summary, dict):
        return None
    for key in _SUBJECT_INPUT_KEYS:
        raw = input_summary.get(key)
        if raw is None:
            continue
        # Lists (e.g. compare_entities tickers=["NVDA","AMD"]) → join the first
        # few so the label stays short.
        if isinstance(raw, list | tuple):
            parts = [str(p).strip() for p in raw if str(p).strip()]
            if not parts:
                continue
            mapped = [_TICKER_DISPLAY_NAMES.get(p.upper(), p) for p in parts[:3]]
            return ", ".join(mapped)[:48]
        text = str(raw).strip()
        if not text:
            continue
        # Ticker-shaped tokens (all caps, ≤5 chars) get the display-name map.
        if text.upper() in _TICKER_DISPLAY_NAMES:
            return _TICKER_DISPLAY_NAMES[text.upper()]
        return text[:48]
    return None


def _human_tool_label(tool_name: str, input_summary: dict[str, Any]) -> str:
    """Build the deterministic, input-aware human label for a tool_call.

    Resolution order:
      1. If the tool has an input-aware template AND a subject is present →
         "Searching news for NVIDIA".
      2. Else the static base label from :data:`_TOOL_LABELS`.
      3. Else a final fallback of ``"{tool_name}..."`` so an unknown tool never
         raises and still shows *something* legible.

    Pure templating — NO LLM call, NO network. Safe to run on every tool_call.
    """
    subject = _resolve_subject(input_summary)
    template = _TOOL_LABEL_TEMPLATES.get(tool_name)
    if template and subject:
        return template.format(subject=subject)
    return _TOOL_LABELS.get(tool_name, f"{tool_name}...")


class SSEEmitter:
    """Convert RAG pipeline events into SSE wire format dictionaries."""

    @staticmethod
    def human_tool_label(tool_name: str, input_summary: dict[str, Any]) -> str:
        """Public accessor for the deterministic input-aware tool label.

        WHY exposed: the orchestrator builds the SAME label for the matching
        ``tool_result`` event (so the Research timeline's completion line keeps
        the subject from the call line). Delegating to the module-level helper
        keeps the label logic in ONE place — there is exactly one definition of
        "Searching news for NVIDIA".
        """
        return _human_tool_label(tool_name, input_summary)

    def emit_status(self, step: str) -> dict[str, str]:
        """Emit a pipeline step progress event.

        ``step`` is a free-form token the frontend maps to a human label. Known
        cross-cutting values are enumerated in
        :class:`rag_chat.application.pipeline.sse_events.SSEStatusStep` (e.g.
        ``"verifying"`` — the post-synthesis grounding-validation phase).
        """
        return {"event": SSEEventType.STATUS.value, "data": json.dumps({"step": step})}

    def emit_token(self, text: str) -> dict[str, str]:
        """Emit a single LLM token chunk."""
        return {"event": "token", "data": json.dumps({"text": text})}

    def emit_delta(self, text: str) -> dict[str, str]:
        """Emit a streaming text chunk.

        Wire-compatible alias of :meth:`emit_token` (same ``event: token``
        SSE frame shape) so existing frontends and the chat-eval harness keep
        working unchanged. The dedicated method name documents intent at the
        caller site: this is one slice of a streamed answer, not necessarily
        a single LLM token. Used by the orchestrator's per-chunk loop in the
        "LLM answered directly" branch (PLAN-0099 W1 / BP-595).
        """
        return self.emit_token(text)

    def emit_final_answer(self, text: str) -> dict[str, str]:
        """Emit the post-validation final answer in a single event.

        PLAN-0093 E-5 T-E-5-03: ``execute_sync`` uses this to avoid
        concatenating intermediate-draft token events together with the
        post-validation rewrite (F-CHAT-002 response duplication).
        Streaming clients can ignore this event — they already saw the
        token-by-token stream.
        """
        return {"event": "final_answer", "data": json.dumps({"text": text})}

    def emit_citations(self, citations: list[Citation]) -> dict[str, str]:
        """Emit the citations block after LLM generation completes."""
        return {
            "event": "citations",
            "data": json.dumps(
                [
                    {
                        "ref": c.ref,
                        "item_type": c.item_type,
                        "id": str(c.id),
                        "title": c.title,
                        "url": c.url,
                        "source_name": c.source_name,
                        "published_at": c.published_at.isoformat() if c.published_at else None,
                        "entity_name": c.entity_name,
                        "confidence": c.confidence,
                    }
                    for c in citations
                ]
            ),
        }

    def emit_suggestions(self, suggestions: list[str]) -> dict[str, str]:
        """Emit server-derived follow-up suggestions after the final answer.

        Wire shape (forward-compatible — the frontend prefers server-sent
        suggestions over its client-templated ones when this event arrives):

            event: suggestions
            data: ["question 1", "question 2", "question 3"]

        Derivation is deterministic (no extra LLM call) — see
        ``rag_chat.application.services.suggestions``. Toggled by
        ``RAG_CHAT_SUGGESTIONS_ENABLED`` (default true).
        """
        return {"event": "suggestions", "data": json.dumps(suggestions)}

    def emit_contradictions(self, contradictions: list[ContradictionRef]) -> dict[str, str]:
        """Emit contradiction references detected during retrieval."""
        return {
            "event": "contradictions",
            "data": json.dumps(
                [
                    {
                        "claim_type": c.claim_type,
                        "strength": c.strength,
                        "sides": list(c.sides),
                    }
                    for c in contradictions
                ]
            ),
        }

    def emit_metadata(
        self,
        thread_id: UUID,
        message_id: UUID,
        intent: str,
        provider: str,
        latency_ms: int,
    ) -> dict[str, str]:
        """Emit final response metadata (thread/message IDs, latency, provider)."""
        return {
            "event": SSEEventType.METADATA.value,
            "data": json.dumps(
                {
                    "thread_id": str(thread_id),
                    "message_id": str(message_id),
                    "intent": intent,
                    "provider": provider,
                    "latency_ms": latency_ms,
                    # Phase-1: surface the SSE protocol version on metadata too
                    # (additive). The frontend reads it from whichever of
                    # metadata/done it sees first.
                    PROTOCOL_VERSION_KEY: SSE_PROTOCOL_VERSION,
                }
            ),
        }

    def emit_error(self, code: str, message: str) -> dict[str, str]:
        """Emit an error event (pipeline failure, rate limit, etc.)."""
        return {"event": "error", "data": json.dumps({"code": code, "message": message})}

    def emit_done(self, phase_timings_ms: dict[str, float] | None = None) -> dict[str, str]:
        """Emit the terminal SSE event signalling the stream is complete.

        WHY NEEDED: Without a ``done`` event the frontend EventSource listener has no
        reliable signal to close the connection — it relies on the server closing the
        HTTP stream, which some proxies buffer.  An explicit ``event: done`` lets the
        frontend close the EventSource immediately and mark the response as finished.

        PLAN-0099 W1-T03: when ``phase_timings_ms`` is provided, the per-phase
        wall-clock breakdown is attached to the ``done`` payload as
        ``phase_timings_ms``.  The chat-eval harness scrapes this from the
        artifact to decompose end-to-end latency into classifier / first-LLM /
        tool-fanout / second-LLM / streaming buckets.  When the dict is empty
        or None it is omitted to preserve byte-for-byte backwards
        compatibility for callers that did not opt in.
        """
        # Phase-1: surface the SSE protocol version on the terminal frame so the
        # frontend can read the contract version it just consumed without an
        # out-of-band negotiation. ``type`` and ``phase_timings_ms`` keep their
        # exact prior shapes — this is purely additive.
        payload: dict[str, Any] = {
            "type": SSEEventType.DONE.value,
            PROTOCOL_VERSION_KEY: SSE_PROTOCOL_VERSION,
        }
        if phase_timings_ms:
            payload["phase_timings_ms"] = phase_timings_ms
        return {"event": SSEEventType.DONE.value, "data": json.dumps(payload)}

    def emit_agent_iteration(
        self,
        *,
        iteration: int,
        max_iterations: int,
        stage: str,
        tools_completed_total: int,
        elapsed_ms: int,
    ) -> dict[str, str]:
        """Emit a per-iteration ReAct-loop progress event (PLAN-0107).

        WHY: the multi-round tool loop can take 30-90s on heavy financial
        questions (3-5 tool calls + reranks + synthesis). Before this event
        the frontend showed only ``thinking`` → ``tool_call`` → ``tool_result``
        spinners and had no signal between iterations, so the UI looked
        frozen during the brief LLM-planning gap between tool batches. The
        ``agent_iteration`` event fires immediately before each
        ``chat_with_tools`` planning call AND immediately before the final
        synthesis stream, giving the frontend a 1-3 events-per-second pulse
        the user can render as "Step 2/8 — reasoning over 4 results...".

        Wire shape (the frontend consumer is implemented against this exact
        contract — DO NOT change field names without coordinating with
        ``apps/worldview-web``):

            event: agent_iteration
            data: {
              "iteration": int,             # 0-indexed loop counter
              "max_iterations": int,        # AgentBudget.max_iterations
              "stage": "planning_tools"     # iter 0: choosing first tools
                     | "reasoning_over_results"  # iter N>0: reasoning over results
                     | "synthesizing",      # AFTER loop: final stream
              "tools_completed_total": int, # cumulative tool exec count this turn
              "elapsed_ms": int             # ms since the tool-loop started
            }

        Args:
            iteration:            0-indexed iteration number for ``planning_tools``
                                  and ``reasoning_over_results``. For
                                  ``synthesizing`` it should be the actual
                                  iteration count completed.
            max_iterations:       Hard cap from AgentBudget.max_iterations.
            stage:                One of the three string literals above.
            tools_completed_total:Running cumulative count of tools whose
                                  results were captured across all iterations
                                  so far.
            elapsed_ms:           Wall-clock ms since the tool-loop started
                                  (NOT since request arrival — the cache /
                                  validate / load-history phases are excluded
                                  so the frontend shows real ReAct progress
                                  rather than fixed startup overhead).
        """
        return {
            "event": "agent_iteration",
            "data": json.dumps(
                {
                    "iteration": iteration,
                    "max_iterations": max_iterations,
                    "stage": stage,
                    "tools_completed_total": tools_completed_total,
                    "elapsed_ms": elapsed_ms,
                }
            ),
        }

    def emit_thinking(self, stage: str = "tool_classification") -> dict[str, str]:
        """Emitted immediately when the first-turn LLM call starts (PLAN-0067 §0 I-1).

        WHY: non-streaming first turn adds ~600ms latency vs classical path. This event
        shows the user activity before the first token arrives — the frontend can show
        a pulsing "Thinking..." indicator immediately instead of a blank stream.

        Args:
            stage: identifies which sub-step the service is in. Defaults to
                   "tool_classification" (the only stage in the W11-3 path).
                   Future waves may add "entity_resolution", "reranking", etc.
        """
        return {"event": "thinking", "data": json.dumps({"stage": stage})}

    def emit_tool_call(
        self,
        tool_name: str,
        input_summary: dict,  # type: ignore[type-arg]
        status: str = "running",
        is_fallback: bool = False,
        fallback_of: str | None = None,
    ) -> dict[str, str]:
        """Emit a tool_call event before execution starts (PLAN-0066 Wave H T-W10-H-04).

        Updated in PLAN-0067 W11-3: added ``label`` field (user-friendly string) and
        renamed ``tool_input`` → ``input_summary`` (safe subset, no PII).

        FIX-LIVE-E (2026-05-24): added ``is_fallback``/``fallback_of`` so the
        orchestrator can flag automatic alt-tool retries after a primary tool
        returns empty.  The frontend can render a subtler "(retrying with X)"
        affordance instead of a fresh spinner.

        WHY BEFORE EXECUTE: the frontend can immediately show a spinner
        "Fetching AAPL price history..." without waiting for the S3 round-trip.
        The ``status: "running"`` field lets the UI differentiate from the result.

        WHY label: raw tool names ("get_price_history") are not user-friendly. The
        label ("Fetching price history...") is displayed in the chat UI while the
        tool executes.

        Args:
            tool_name:     Internal tool name (from capability_manifest.yaml).
            input_summary: Safe subset of the tool input, no PII. Displayed in UI.
            status:        Current tool status. Defaults to "running".
            is_fallback:   True when this is an automatic alt-tool retry after a
                           primary tool returned empty (FIX-LIVE-E).
            fallback_of:   Name of the originally-failed tool when is_fallback=True;
                           ignored otherwise.
        """
        # Phase-1: build the input-aware human label deterministically (no LLM).
        # ``get_entity_news({"ticker": "NVDA"})`` → "Searching news for NVIDIA".
        label = _human_tool_label(tool_name, input_summary)
        payload: dict[str, Any] = {
            "type": SSEEventType.TOOL_CALL.value,
            "tool": tool_name,
            "label": label,
            "input": input_summary,
            "status": status,
        }
        if is_fallback:
            payload["is_fallback"] = True
            if fallback_of:
                payload["fallback_of"] = fallback_of
        return {
            "event": "tool_call",
            "data": json.dumps(payload),
        }

    def emit_pending_action(
        self,
        proposal_id: str,
        tool_name: str,
        description: str,
        params: dict,  # type: ignore[type-arg]
    ) -> dict[str, str]:
        """Emit a pending_action event when a write-action tool requires user confirmation.

        WHY a separate SSE event type (not tool_call): tool_call/tool_result are
        informational spinners — they fire for read tools and resolve automatically.
        ``pending_action`` is a blocking event: the frontend must show a modal and
        wait for explicit user confirmation before the action executes.

        The ``proposal_id`` is a server-generated UUID the frontend sends back via
        POST /v1/chat/proposals/{id}/confirm to execute the action.

        Args:
            proposal_id:  UUID string for the pending proposal (client sends back on confirm).
            tool_name:    Internal tool name (e.g. "create_alert").
            description:  Human-readable description of the pending action shown in modal.
            params:       Safe display parameters shown in the confirmation modal.
        """
        return {
            "event": "pending_action",
            "data": json.dumps(
                {
                    "type": "pending_action",
                    "proposal_id": proposal_id,
                    "tool": tool_name,
                    "description": description,
                    "params": params,
                }
            ),
        }

    def emit_action_executed(
        self,
        proposal_id: str,
        tool_name: str,
        result: dict,  # type: ignore[type-arg]
    ) -> dict[str, str]:
        """Emit an action_executed event after the user confirms and the action completes.

        WHY ALWAYS EMITTED on confirm: the frontend proposal modal opened by
        ``pending_action`` must always receive a close signal.  Emitting on
        success ensures the UI never hangs in a loading state.

        Args:
            proposal_id:  UUID string matching the prior pending_action proposal_id.
            tool_name:    Internal tool name matching the prior pending_action.
            result:       Action result summary (e.g. {"alert_id": "...", "condition": "..."}).
        """
        return {
            "event": "action_executed",
            "data": json.dumps(
                {
                    "type": "action_executed",
                    "proposal_id": proposal_id,
                    "tool": tool_name,
                    "result": result,
                }
            ),
        }

    def emit_action_rejected(
        self,
        proposal_id: str,
        tool_name: str,
        reason: str = "user_cancelled",
    ) -> dict[str, str]:
        """Emit an action_rejected event when the user dismisses the confirmation modal.

        WHY ALWAYS EMITTED on dismiss: mirrors emit_action_executed so the frontend
        always has a matching close signal regardless of whether the user confirmed
        or cancelled.

        Args:
            proposal_id:  UUID string matching the prior pending_action proposal_id.
            tool_name:    Internal tool name matching the prior pending_action.
            reason:       Rejection reason token. Default "user_cancelled".
        """
        return {
            "event": "action_rejected",
            "data": json.dumps(
                {
                    "type": "action_rejected",
                    "proposal_id": proposal_id,
                    "tool": tool_name,
                    "reason": reason,
                }
            ),
        }

    # ── result_preview bounds (tool_result SSE enrichment) ────────────────────
    # Hard caps so the tool_result SSE frame stays small regardless of how many
    # items / how large the titles a tool returns. 3 items x ~80 chars title +
    # ~64 chars id keeps the preview well under ~500 bytes of JSON.
    _PREVIEW_MAX_ITEMS = 3
    _PREVIEW_TITLE_MAX_CHARS = 80
    _PREVIEW_ID_MAX_CHARS = 64

    @classmethod
    def build_result_preview(cls, items: list[Any]) -> list[dict[str, str | None]]:
        """Build a small, bounded preview of tool-result items for the SSE frame.

        Each entry carries the item's ``item_id`` and its citation title when
        present. Inputs are duck-typed (RetrievedItem or anything with
        ``item_id`` / ``citation_meta.title``) so handler-specific result
        shapes never crash the emitter — unknown shapes degrade to id-only
        entries, never to an exception.
        """
        preview: list[dict[str, str | None]] = []
        for item in items[: cls._PREVIEW_MAX_ITEMS]:
            raw_id = getattr(item, "item_id", None)
            title = getattr(getattr(item, "citation_meta", None), "title", None)
            preview.append(
                {
                    "id": str(raw_id)[: cls._PREVIEW_ID_MAX_CHARS] if raw_id is not None else None,
                    "title": str(title)[: cls._PREVIEW_TITLE_MAX_CHARS] if title else None,
                }
            )
        return preview

    # ── grounding_sample bounds (PRD-0091 FR-5 / FR-8 / §6.3) ─────────────────
    # The grounding sample carries a few REDACTED, allow-listed *values* from
    # the tool result (not just {id,title}) so a downstream judge (W3) can
    # cross-check numeric claims in the answer against what the tool actually
    # returned. These hard caps keep the serialized sample tiny (≤1 KB, NFR-1)
    # regardless of how many rows / how large the values a tool produced.
    #   - MAX_ROWS:        at most this many result rows are sampled.
    #   - MAX_FIELDS:      at most this many allow-listed fields per row.
    #   - VALUE_MAX_CHARS: each value is str-coerced then truncated to this.
    #   - SAMPLE_MAX_BYTES:the whole serialized sample is bounded; over → cut +
    #                      ``truncated=true``.
    #
    # 2026-06-28 (substantiation-drop fix): raised MAX_ROWS 3->10 and
    # SAMPLE_MAX_BYTES 1024->4096. The 3-row cap was the Class-B truncation that
    # silently dropped real multi-row tool data (batch fundamentals, screeners)
    # before the W3 judge could verify it -- e.g. tc_batch_fundamentals_mag5
    # returns 5 tickers but rows 4-5 (AAPL/AMZN) were never sampled, capping
    # substantiation regardless of answer quality. 10 rows covers every
    # batch/screener result of <=10 rows in the benchmark; the byte cap rises in
    # step so the added rows survive the post-build byte-trim instead of being
    # truncated away again (the largest real sample, get_fundamentals_history_batch
    # at 5 rows is ~1.4 KB, fits comfortably in 4 KB). VALUE_MAX_CHARS is
    # unchanged -- only the row/byte ceilings moved here.
    #
    # RC-3 follow-up (2026-06-28): raised MAX_FIELDS_PER_ROW 8->14. A single
    # fundamentals item now packs MULTIPLE periods under suffixed keys
    # (``revenue``, ``revenue_2`` … one per quarter — see market.py
    # ``_grounding_fields_from_rows`` + ``_GROUNDING_MAX_PERIODS=8``). With the
    # field cap at 8, a long-horizon "since 2023" answer (12 quarters) had its
    # OLDEST ~4 quarters trimmed out of the single packed row → those figures
    # stayed unsubstantiated and the answer floored despite being correct
    # (RC-3 residual A in docs/audits/2026-06-28-grounding-floor-rootcause.md).
    # 14 = ticker + up to 13 period values, covering a full ~3-year quarterly
    # trend. The byte cap (4096) already holds: 14 short numeric fields
    # (<=32 chars each) plus keys serialize to well under 1 KB, so the post-build
    # byte-trim does not re-truncate. The per-period emit cap (_GROUNDING_MAX_PERIODS)
    # still bounds how many periods the handler packs, so this only RAISES the
    # ceiling the packed periods compete for — it never invents fields.
    GROUNDING_MAX_ROWS = 10
    GROUNDING_MAX_FIELDS_PER_ROW = 14
    GROUNDING_VALUE_MAX_CHARS = 32
    GROUNDING_SAMPLE_MAX_BYTES = 4096

    # Per-tool field allow-list (FR-8). ONLY numeric / short-identifier fields
    # appear here — NEVER document bodies, narrative text, or any
    # portfolio/account identifiers. A tool NOT listed here yields NO sample at
    # all (degrades to the id/title result_preview only); this is the
    # fail-closed default that prevents raw-payload leakage from unknown shapes.
    #
    # NOTE: field names are matched duck-typed against each result item
    # (``getattr`` on the item, then its ``citation_meta``, then dict-style
    # ``get``) — the same robustness contract as ``build_result_preview``. When
    # a handler does not (yet) surface a structured field, it simply does not
    # survive into the sample; the builder never raises on a missing field.
    _GROUNDING_FIELD_ALLOWLIST: ClassVar[dict[str, tuple[str, ...]]] = {
        # Market / fundamentals tools — numeric financial fields + identifiers.
        # Value-substantiation (2026-06-26): widened to the full metric set the
        # fundamentals handlers now emit on ``grounding_fields`` (net_income,
        # forward_pe, ebitda, free_cash_flow). Keep <= GROUNDING_MAX_FIELDS_PER_ROW
        # surviving per row (ticker + period + metrics; period rarely resolves so
        # the numeric metrics fit the cap of 8).
        # NOTE: ``MAX_FIELDS_PER_ROW`` (8) bounds how many of these survive per
        # row — for the multi-period rows the suffixed-key admission below packs
        # additional periods. Margins were added 2026-06-26 (STEP A) so the
        # percent-typed claim matcher (ru_tsla_margin_trend) has a value to match.
        "get_fundamentals_history": (
            "ticker",
            "period",
            "revenue",
            "eps",
            "gross_profit",
            "net_income",
            "pe_ratio",
            "forward_pe",
            "market_cap",
            "ebitda",
            "free_cash_flow",
            "gross_margin",
            "operating_margin",
            "net_margin",
            # C1 (2026-07-06): valuation metrics the fundamentals handlers now
            # emit on ``grounding_fields``. Absent from this allow-list they were
            # dropped before the judge, so pe/ps/growth answers stayed "presumed"
            # (blind PASS). ``_\d+$``-suffixed period variants are admitted via the
            # base-name match below, so one entry covers every period.
            "price_to_sales_ttm",
            "quarterly_revenue_growth_yoy",
        ),
        "get_fundamentals_history_batch": (
            "ticker",
            "period",
            "revenue",
            "eps",
            "gross_profit",
            "net_income",
            "pe_ratio",
            "forward_pe",
            "market_cap",
            "ebitda",
            "free_cash_flow",
            "gross_margin",
            "operating_margin",
            "net_margin",
            # C1 (2026-07-06): valuation metrics the fundamentals handlers now
            # emit on ``grounding_fields``. Absent from this allow-list they were
            # dropped before the judge, so pe/ps/growth answers stayed "presumed"
            # (blind PASS). ``_\d+$``-suffixed period variants are admitted via the
            # base-name match below, so one entry covers every period.
            "price_to_sales_ttm",
            "quarterly_revenue_growth_yoy",
        ),
        # query_fundamentals (2026-06-26 STEP A): the confirmed routed-but-silent
        # gap — its handler populates ``grounding_fields`` (raw numbers + covered
        # margins) but the tool was absent here, so no sample reached the judge and
        # coverage stayed ``presumed`` (ru_aapl_pe_simple, ru_tsla_margin_trend,
        # ru_googl_pe_vs_history). Same field set as the history family.
        "query_fundamentals": (
            "ticker",
            "period",
            "revenue",
            "eps",
            "gross_profit",
            "net_income",
            "pe_ratio",
            "forward_pe",
            "market_cap",
            "ebitda",
            "free_cash_flow",
            "gross_margin",
            "operating_margin",
            "net_margin",
            # C1 (2026-07-06): valuation metrics the fundamentals handlers now
            # emit on ``grounding_fields``. Absent from this allow-list they were
            # dropped before the judge, so pe/ps/growth answers stayed "presumed"
            # (blind PASS). ``_\d+$``-suffixed period variants are admitted via the
            # base-name match below, so one entry covers every period.
            "price_to_sales_ttm",
            "quarterly_revenue_growth_yoy",
        ),
        "compare_entities": (
            "ticker",
            "period",
            "revenue",
            "eps",
            "gross_profit",
            "net_income",
            "pe_ratio",
            "forward_pe",
            "market_cap",
            "ebitda",
            "free_cash_flow",
            "gross_margin",
            "operating_margin",
            "net_margin",
            # C1 (2026-07-06): valuation metrics the fundamentals handlers now
            # emit on ``grounding_fields``. Absent from this allow-list they were
            # dropped before the judge, so pe/ps/growth answers stayed "presumed"
            # (blind PASS). ``_\d+$``-suffixed period variants are admitted via the
            # base-name match below, so one entry covers every period.
            "price_to_sales_ttm",
            "quarterly_revenue_growth_yoy",
        ),
        "get_price_history": ("ticker", "period", "open", "high", "low", "close", "volume"),
        "screen_universe": ("ticker", "pe_ratio", "market_cap", "revenue"),
        "get_market_movers": ("ticker", "change_pct", "price"),
        # Knowledge / intelligence tools — short identifiers + confidence only.
        "search_claims": ("ticker", "confidence", "polarity", "period"),
        "search_entity_relations": ("ticker", "confidence", "relation_type"),
        "get_contradictions": ("ticker", "confidence", "claim_type"),
        "get_entity_health": ("ticker", "confidence", "health_score"),
    }

    # Substrings that, if present in a *surviving* field NAME, force redaction
    # of that field (defence-in-depth on top of the allow-list — FR-8 / §8). A
    # portfolio/account identifier must NEVER reach an eval artefact or log.
    _GROUNDING_REDACT_NAME_SUBSTRINGS: tuple[str, ...] = (
        "portfolio",
        "account",
        "holding",
        "position_id",
        "user_id",
        "tenant",
    )

    @classmethod
    def _grounding_field_value(cls, item: Any, field: str) -> Any | None:  # — duck-typed
        """Best-effort extraction of one allow-listed field from a result item.

        Probes, in order: a direct attribute on the item, the item's
        ``citation_meta`` (where ``ticker`` is often surfaced as
        ``entity_name``), then dict-style ``.get`` for handlers that return
        plain dicts. Returns ``None`` when the field is absent — NEVER raises,
        so an unexpected item shape degrades to a smaller sample rather than a
        500 mid-stream.
        """
        # 1. Direct attribute on the item (e.g. a structured RetrievedItem-like
        #    object that already exposes ``revenue`` / ``confidence``).
        val = getattr(item, field, None)
        if val is not None:
            return val
        # 2. citation_meta fallback — ``ticker`` is frequently carried as the
        #    citation's ``entity_name``; surface it so financial tool rows still
        #    get an identifier in the sample.
        meta = getattr(item, "citation_meta", None)
        if meta is not None:
            mval = getattr(meta, field, None)
            if mval is not None:
                return mval
            if field == "ticker":
                ent = getattr(meta, "entity_name", None)
                if ent is not None:
                    return ent
        # 3. dict-style item (some handlers return plain dicts).
        if isinstance(item, dict):
            return item.get(field)
        # 4. Structured grounding_fields bag (value-substantiation, 2026-06-26):
        #    fundamentals/compare handlers carry raw numeric values as an ordered
        #    tuple of (key, str-value) pairs. Probe it last so the direct-attr /
        #    citation_meta paths (e.g. ticker via entity_name) still win. Dict-ify
        #    once per call; the bag is small (<=~9 keys) so this is cheap.
        gf = getattr(item, "grounding_fields", None)
        if gf:
            gf_map = dict(gf)
            if field in gf_map:
                return gf_map[field]
        return None

    # ── D2 (2026-07-06): per-entity / per-period grounding view ────────────────
    # A period-slot label for the Nth-newest period within an entity. The newest
    # period keeps ``"latest"``; older periods get ``"p2"``, ``"p3"`` … mirroring
    # market.py's ``_grounding_fields_from_rows`` suffix convention (newest-first).
    # NOTE: this is a period *slot* (unambiguous ordinal), not a calendar quarter
    # — grounding_fields do not carry the fiscal label, but the slot is sufficient
    # for the LLM to attribute a value to (entity, period) without cross-mixing.
    @staticmethod
    def _period_slot_label(slot: int) -> str:
        return "latest" if slot <= 1 else f"p{slot}"

    @classmethod
    def _merge_item_into_entity_view(
        cls,
        item: Any,
        allow: tuple[str, ...],
        view: dict[str, dict[str, dict[str, str]]],
    ) -> None:
        """Fold ONE result item's grounding into the ``{entity:{period:{metric:val}}}`` view.

        Handles the two multi-value handler shapes uniformly:
          * ENTITY-suffixed (compare_entities / get_market_movers): a SINGLE item
            packs several entities under ``ticker``/``ticker_2`` + ``revenue``/
            ``revenue_2`` — the ``_N`` suffix encodes the ENTITY. Detected by >= 2
            distinct ``ticker`` slots; each slot's metrics attach to that slot's
            ticker under the ``"latest"`` period.
          * PERIOD-suffixed (get_fundamentals_history[_batch] / query_fundamentals):
            ONE item per entity, whose ``_N`` suffix encodes the PERIOD (newest
            bare, older ``_2`` …). The whole item attaches to its single entity,
            one nested dict per period slot.

        Only allow-listed metric bases survive (same fail-closed contract as the
        flat builder), the same portfolio/account redaction applies, and each
        value is str-coerced + length-capped. Reads the item's grounding_fields
        DIRECTLY (never the byte-capped flat bag) so entity-1's core metrics are
        never dropped by the flat free-slot logic.
        """
        primary_raw = cls._grounding_field_value(item, "ticker")
        primary = str(primary_raw) if primary_raw is not None else None
        gf = getattr(item, "grounding_fields", None)
        if gf:
            # Parse the bag into per-slot metric dicts + per-slot ticker labels.
            slot_metrics: dict[int, dict[str, str]] = {}
            slot_ticker: dict[int, str] = {}
            for raw_key, raw_val in gf:
                if raw_val is None:
                    continue
                m = re.search(r"_(\d+)$", raw_key)
                if m:
                    base = raw_key[: m.start()]
                    slot = int(m.group(1))
                else:
                    base = raw_key
                    slot = 1
                if base not in allow:
                    continue
                if any(sub in base.lower() for sub in cls._GROUNDING_REDACT_NAME_SUBSTRINGS):
                    continue
                value = str(raw_val)[: cls.GROUNDING_VALUE_MAX_CHARS]
                if base == "ticker":
                    slot_ticker[slot] = value
                    continue
                slot_metrics.setdefault(slot, {})[base] = value
            if len(slot_ticker) >= 2:
                # ENTITY-suffixed: each slot is a distinct entity, single period.
                for tk in slot_ticker.values():
                    view.setdefault(tk, {})
                for slot, metrics in slot_metrics.items():
                    entity = slot_ticker.get(slot) or primary or f"entity_{slot}"
                    if metrics:
                        view.setdefault(entity, {}).setdefault("latest", {}).update(metrics)
            else:
                # PERIOD-suffixed: one entity, one nested dict per period slot.
                entity = slot_ticker.get(1) or primary or "entity"
                view.setdefault(entity, {})
                for slot in sorted(slot_metrics):
                    metrics = slot_metrics[slot]
                    if metrics:
                        view[entity][cls._period_slot_label(slot)] = dict(metrics)
        else:
            # Attr/dict item (no structured bag): single entity, single period.
            entity = primary or "entity"
            metrics = {}
            for field in allow:
                if field == "ticker":
                    continue
                if any(sub in field.lower() for sub in cls._GROUNDING_REDACT_NAME_SUBSTRINGS):
                    continue
                raw = cls._grounding_field_value(item, field)
                if raw is None:
                    continue
                metrics[field] = str(raw)[: cls.GROUNDING_VALUE_MAX_CHARS]
            if metrics:
                view.setdefault(entity, {}).setdefault("latest", {}).update(metrics)
            elif primary is not None:
                view.setdefault(entity, {})

    @classmethod
    def _build_entity_period_view(cls, tool_name: str, items: list[Any]) -> dict[str, dict[str, dict[str, str]]] | None:
        """Build the D2 ``{entity:{period:{metric:value}}}`` disambiguation view.

        Returns the view ONLY when it spans >= 2 distinct entities — a
        single-entity result is already unambiguous via the flat bag's period
        suffixes, and adding the key there would change the legacy 4-key sample
        shape (AD-4). ``None`` for non-allow-listed tools / < 2 entities.
        """
        allow = cls._GROUNDING_FIELD_ALLOWLIST.get(tool_name)
        if not allow:
            return None
        view: dict[str, dict[str, dict[str, str]]] = {}
        for item in items[: cls.GROUNDING_MAX_ROWS]:
            cls._merge_item_into_entity_view(item, allow, view)
        if not view:
            return None
        # Multi-entity result → always emit (the original D2 case: batch / compare
        # / movers pack several entities the flat bag cannot disambiguate).
        if len(view) >= 2:
            return view
        # H-1 (2026-07-08): a SINGLE-entity result ALSO gets the structured view
        # when it packs >= 2 period/bar slots — a multi-period fundamentals trend
        # or a multi-bar price series (tc_price_history, single fundamentals
        # history). The flat bag alone reported ``total_rows:1`` with no per-row
        # nesting, so the judge could not map each period/bar to a row and
        # false-flagged real table data as fabricated. A genuinely single-period
        # single-entity result (< 2 slots) stays on the legacy flat bag so the
        # 4-key sample shape is preserved (AD-4).
        only_periods = next(iter(view.values()))
        if len(only_periods) >= 2:
            return view
        return None

    @classmethod
    def _max_value_row_depth(cls, items: list[Any]) -> int:
        """Largest number of VALUE-ROWS (period/bar/entity slots) in any one item.

        A multi-row table tool (price_history, single fundamentals-history) returns
        ONE item whose ``grounding_fields`` pack N rows under ``_N`` suffixes
        (``close``/``close_2`` …, ``revenue``/``revenue_2`` …). ``len(items)`` is
        then 1 even though the sample REPRESENTS N rows — which the judge read as
        "only 1 data point" and used to false-flag multi-value answers (H-1). This
        returns the max ``_N`` slot index seen across items so the caller can
        surface a truthful ``value_rows`` count alongside the item-count
        ``total_rows``. Always >= 1.
        """
        max_depth = 1
        for item in items[: cls.GROUNDING_MAX_ROWS]:
            gf = getattr(item, "grounding_fields", None)
            if not gf:
                continue
            depth = 1
            for raw_key, raw_val in gf:
                if raw_val is None:
                    continue
                m = re.search(r"_(\d+)$", raw_key)
                if m:
                    depth = max(depth, int(m.group(1)))
            max_depth = max(max_depth, depth)
        return max_depth

    @classmethod
    def build_grounding_sample(cls, tool_name: str, items: list[Any]) -> dict[str, Any] | None:
        """Build a bounded, redacted, allow-list-only sample of tool-result values.

        PRD-0091 FR-5 / FR-8 / §6.3. This is the *opt-in* counterpart to
        :meth:`build_result_preview`: where the preview carries only
        ``{id, title}`` for the UI, the grounding sample carries a few
        allow-listed numeric / identifier VALUES so the W3 judge can verify (not
        presume) grounding — e.g. cross-check a "$271,474" claim against the
        revenue the tool actually returned.

        Hard guarantees (all enforced here, server-side):
          * Only fields in ``_GROUNDING_FIELD_ALLOWLIST[tool_name]`` are read;
            an unknown tool → ``None`` (no sample, never a raw-payload leak).
          * Each value is ``str``-coerced and truncated to
            ``GROUNDING_VALUE_MAX_CHARS``.
          * At most ``GROUNDING_MAX_ROWS`` rows and
            ``GROUNDING_MAX_FIELDS_PER_ROW`` fields per row.
          * Any field whose name matches a portfolio/account redaction
            substring is dropped (defence-in-depth).
          * The serialized sample is capped at ``GROUNDING_SAMPLE_MAX_BYTES``;
            when the cap forces fields out, ``truncated=true``.

        Returns the ``{fields, sampled_rows, total_rows, truncated}`` shape
        (§6.3), or ``None`` when the tool is not allow-listed or no allow-listed
        field survived (caller then emits no ``grounding_sample`` at all).
        """
        allow = cls._GROUNDING_FIELD_ALLOWLIST.get(tool_name)
        if not allow:
            # Unknown / not-allow-listed tool → fail closed: no sample.
            return None

        total_rows = len(items)
        truncated = False

        # ``fields`` is a flat {field_name: value} map sampled across the first
        # few rows. We key by field name (not by row index) because the judge
        # cross-checks claim numbers against the *set* of returned values; a
        # per-row matrix would blow the byte budget for marginal benefit. When
        # multiple sampled rows carry the same field, later rows are appended
        # under suffixed keys (``revenue``, ``revenue_2``) so distinct values
        # survive without collisions — still bounded by the field/byte caps.
        fields: dict[str, str] = {}
        sampled_rows = 0
        for item in items[: cls.GROUNDING_MAX_ROWS]:
            row_field_count = 0
            row_contributed = False
            for field in allow:
                if row_field_count >= cls.GROUNDING_MAX_FIELDS_PER_ROW:
                    break
                # Defence-in-depth redaction on the field NAME (FR-8 / §8): a
                # portfolio/account identifier must never be emitted even if it
                # somehow appears in an allow-list (it does not today, but this
                # guard makes the leak structurally impossible).
                lname = field.lower()
                if any(sub in lname for sub in cls._GROUNDING_REDACT_NAME_SUBSTRINGS):
                    continue
                raw = cls._grounding_field_value(item, field)
                if raw is None:
                    continue
                value = str(raw)[: cls.GROUNDING_VALUE_MAX_CHARS]
                # First occurrence keeps the bare field name; subsequent rows
                # get a numeric suffix so distinct values from different rows
                # are not silently overwritten.
                #
                # C6 (2026-07-06): the naive ``f"{field}_{sampled_rows + 1}"`` key
                # COLLIDED with a suffixed period key a PRIOR item already inserted
                # via the gf-loop below (item 1 packs ``revenue_2`` for its own Q4;
                # item 2's bare ``revenue`` then also resolves to ``revenue_2`` and
                # OVERWROTE item 1's value). That silently dropped one entity's
                # figure and cross-attributed it to the other (ru_nvda_amd_revenue_4q:
                # NVDA's revenue clobbered by AMD). Probe upward until a FREE key so
                # no value is ever overwritten — attribution stays 1:1 with a slot.
                if field not in fields:
                    key = field
                else:
                    n = sampled_rows + 1
                    while f"{field}_{n}" in fields:
                        n += 1
                    key = f"{field}_{n}"
                fields[key] = value
                row_field_count += 1
                row_contributed = True
            if row_contributed:
                sampled_rows += 1

            # Value-substantiation (2026-06-26): admit ALREADY-SUFFIXED grounding
            # keys (``revenue_2``, ``ticker_3``) that a single item carries for
            # MULTIPLE entities — e.g. compare_entities packs every compared
            # ticker into one item. The main loop only probes bare allow-listed
            # names, so the 2nd+ entity's metrics would otherwise be dropped. We
            # admit a suffixed key ONLY when its ``_\d+$``-stripped base is in the
            # allow-list AND passes the same portfolio/account redaction — so this
            # stays fail-closed and never leaks an unknown field shape.
            gf = getattr(item, "grounding_fields", None)
            if gf:
                for raw_key, raw_val in dict(gf).items():
                    if row_field_count >= cls.GROUNDING_MAX_FIELDS_PER_ROW:
                        break
                    base = re.sub(r"_\d+$", "", raw_key)
                    if base == raw_key or base not in allow:
                        # Bare keys already handled above; non-allow-listed base → skip.
                        continue
                    if any(sub in raw_key.lower() for sub in cls._GROUNDING_REDACT_NAME_SUBSTRINGS):
                        continue
                    if raw_val is None or raw_key in fields:
                        continue
                    fields[raw_key] = str(raw_val)[: cls.GROUNDING_VALUE_MAX_CHARS]
                    row_field_count += 1

        if not fields:
            # No allow-listed field survived (e.g. the handler renders numbers
            # into ``text`` only) → no sample, judge falls back to "presumed".
            return None

        sample: dict[str, Any] = {
            "fields": fields,
            "sampled_rows": sampled_rows,
            "total_rows": total_rows,
            "truncated": truncated,
        }

        # Enforce the byte cap LAST: drop the least-recently-added fields until
        # the serialized sample fits, flipping ``truncated`` so the judge knows
        # the values are partial. We re-serialize after each drop because JSON
        # length is not a simple sum of value lengths.
        while len(json.dumps(sample).encode("utf-8")) > cls.GROUNDING_SAMPLE_MAX_BYTES and fields:
            # Remove the last-inserted field (dicts preserve insertion order).
            drop_key = next(reversed(fields))
            del fields[drop_key]
            truncated = True
            sample["fields"] = fields
            sample["truncated"] = truncated

        if not fields:
            # Byte cap removed everything — degrade to no sample rather than an
            # empty-fields object the judge cannot use.
            return None

        if truncated:
            # PRD-0091 §13.2 observability: surface that the cap fired so the
            # cap can be tuned from telemetry (R12 — structlog only).
            _log.info(
                "grounding_sample_truncated",
                tool=tool_name,
                total_rows=total_rows,
                sampled_rows=sampled_rows,
            )

        # ── D2 (2026-07-06): attach the per-entity/per-period view ────────────
        # The flat ``fields`` bag above stays UNCHANGED — the W1/W3 numeric
        # matcher strips ``_\d+$`` to the base metric and cross-checks the SET of
        # values, so it must keep the free-slot flat shape. But for a multi-entity
        # result (batch: one item per ticker; compare/movers: several tickers in
        # one item) that flat ``_N`` suffix carries NO entity/period semantics, so
        # the LLM cannot map a value back to its (ticker, period) and fabricates /
        # cross-attributes (tc_batch_fundamentals_mag5, chain_nvda_competitor).
        # ``by_entity`` is the explicit, unambiguous nesting built directly from
        # the items' grounding_fields (never the byte-trimmed flat bag), so
        # entity-1's core metrics are never dropped. Attached ONLY when it spans
        # >= 2 entities so single-entity samples keep the legacy 4-key shape.
        by_entity = cls._build_entity_period_view(tool_name, items)
        if by_entity is not None:
            sample["by_entity"] = by_entity

        # ── H-1 (2026-07-08): truthful value-row count ────────────────────────
        # ``total_rows`` is the ITEM count (len(items)). A multi-row table tool
        # (price_history, single fundamentals-history) returns ONE item packing
        # N period/bar rows under ``_N`` suffixes, so ``total_rows:1`` under-
        # reported the sample's depth and the judge false-flagged real table data
        # as fabricated. ``value_rows`` reports the true per-row depth. Emitted
        # ONLY when it exceeds ``total_rows`` so a single-row single-entity sample
        # stays byte-identical to the legacy 4-key shape (AD-4). Additive +
        # backward-compatible: a consumer that does not know the key ignores it.
        value_rows = cls._max_value_row_depth(items)
        if value_rows > total_rows:
            sample["value_rows"] = value_rows

        return sample

    def emit_tool_result(
        self,
        tool_name: str,
        status: str,  # "ok" | "error" | "empty" | "transport_error"
        item_count: int = 0,
        *,
        reason: str | None = None,
        status_code: int | None = None,
        elapsed_ms: int | None = None,
        duration_ms: int | None = None,
        result_preview: list[dict[str, str | None]] | None = None,
        grounding_sample: dict[str, Any] | None = None,
        label: str | None = None,
    ) -> dict[str, str]:
        """Emit a tool_result event after execution completes (PLAN-0066 Wave H T-W10-H-04).

        Updated in PLAN-0067 W11-3: changed ``success: bool`` → ``status: str`` to
        support a third "empty" state (tool executed but returned no items), and added
        ``item_count`` so the frontend can show "Found 5 results" inline.

        Updated in PLAN-0103 W2 (BP-623): added ``"transport_error"`` status and
        the optional ``reason`` / ``status_code`` / ``elapsed_ms`` fields so the
        frontend (and chat-eval harness) can distinguish a downed upstream from
        a legitimate empty result.  ``reason`` is one of
        ``upstream_unreachable | upstream_timeout | upstream_5xx``; the frontend
        can surface "I cannot reach <upstream> right now — please retry" rather
        than the misleading "No data was found".

        WHY ALWAYS EMITTED: the frontend spinner opened by ``tool_call`` must always
        have a corresponding close signal. Emitting on both success and failure
        ensures the UI never hangs in a loading state.

        Args:
            tool_name:  Internal tool name matching the prior emit_tool_call.
            status:     "ok" | "error" | "empty" | "transport_error".
            item_count: Number of items returned by the tool (0 on error/empty/transport_error).
            reason:     transport_error reason code (None for non-transport statuses).
            status_code:upstream HTTP status (5xx only; None otherwise).
            elapsed_ms: wall-clock ms spent on the failing call (transport_error only).
            duration_ms: server-measured wall-clock ms for this tool execution
                         (set for ALL statuses, unlike elapsed_ms). The
                         frontend prefers duration_ms when present and falls
                         back to its own client-side measurement otherwise.
            result_preview: bounded preview (≤3 entries of {id, title}) built
                         via :meth:`build_result_preview`. Omitted when None
                         or empty so the legacy SSE shape is preserved for
                         error/empty results.
            grounding_sample: bounded, redacted, allow-list-only sample of
                         tool-result VALUES built via
                         :meth:`build_grounding_sample` (PRD-0091 FR-5). Attached
                         to the payload ONLY when the ``CHAT_EVAL_GROUNDING_SAMPLES``
                         env flag is on AND ``status == "ok"`` AND the sample is
                         non-empty. Default OFF (NFR-2) — when off, the legacy
                         4-key payload stays byte-identical, so the frontend and
                         the chat-eval harness pattern-match unchanged (AD-4).
        """
        payload: dict[str, object] = {
            "type": SSEEventType.TOOL_RESULT.value,
            "tool": tool_name,
            "status": status,
            "item_count": item_count,
        }
        # Phase-1: carry the SAME human label as the matching tool_call so the
        # Research timeline can render a completion line ("✓ Searching news for
        # NVIDIA") without re-deriving the label client-side. Omitted when None
        # so the legacy payload stays byte-identical for callers that don't pass
        # it (forward-compatible, additive).
        if label:
            payload["label"] = label
        # Only attach the optional fields when populated so the legacy SSE
        # shape stays byte-identical for callers that did not opt in
        # (frontend snapshot tests and the chat-eval harness both
        # pattern-match on the existing 4-key payload).
        if reason is not None:
            payload["reason"] = reason
        if status_code is not None:
            payload["status_code"] = status_code
        if elapsed_ms is not None:
            payload["elapsed_ms"] = elapsed_ms
        if duration_ms is not None:
            payload["duration_ms"] = duration_ms
        if result_preview:
            payload["result_preview"] = result_preview
        # ── grounding_sample (PRD-0091 FR-5 / AD-4 / NFR-2) ──────────────────
        # Opt-in, omit-when-empty — mirrors the ``result_preview`` pattern above
        # so the legacy 4-key payload is byte-identical when off. THREE
        # conditions must ALL hold before the sample is attached:
        #   1. status == "ok"            — never sample error/empty/transport
        #      results (BP-623: a downed upstream has no values to verify).
        #   2. grounding_sample is non-empty — the builder returned a real
        #      sample (not None / not {}).
        #   3. CHAT_EVAL_GROUNDING_SAMPLES env flag is truthy — read per-call so
        #      ops can flip it without a restart (same hot-toggle pattern as
        #      RAG_COMPLETION_CACHE_DISABLED / RAG_CHAT_SUGGESTIONS_ENABLED).
        #      Default OFF in prod (NFR-2) keeps eval-only data out of normal
        #      traffic. NOTE: the var is intentionally UN-prefixed
        #      (CHAT_EVAL_*, not RAG_CHAT_*) per PRD-0091 §6.3 — it is an
        #      eval-harness toggle, not a service config knob, so it is read
        #      directly from os.environ rather than via the RAG_CHAT_-prefixed
        #      pydantic Settings.
        if (
            status == "ok"
            and grounding_sample
            and os.environ.get("CHAT_EVAL_GROUNDING_SAMPLES", "").strip().lower() == "true"
        ):
            payload["grounding_sample"] = grounding_sample
        return {
            "event": "tool_result",
            "data": json.dumps(payload),
        }
