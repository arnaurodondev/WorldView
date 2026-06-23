"""Canonical, versioned SSE event contract for the rag-chat streaming API.

WHY THIS MODULE EXISTS (Phase-1 SSE contract standardization):
Before this module the SSE event ``type``/``event`` string values were scattered
as inline literals across :mod:`rag_chat.application.pipeline.sse_emitter` and
the orchestrator. The frontend (``apps/worldview-web/features/chat``) hard-codes
the same strings in its SSE demultiplexer. Two independently-edited string
tables drift silently: a typo or a rename on one side is only caught at runtime
(a dropped event = a frozen spinner). Centralising every event ``type`` value
plus a single ``SSE_PROTOCOL_VERSION`` here gives backend + frontend ONE source
of truth to evolve the vocabulary in lockstep.

DESIGN RULES (all enforced by the tests in
``tests/unit/application/pipeline/test_sse_contract.py``):

* **Additive only.** New event types are appended; existing ``type`` values are
  NEVER renamed or removed — the frontend pattern-matches on them and an old
  client must keep working against a newer server (forward compatibility, R11).
* **Version bump policy.** ``SSE_PROTOCOL_VERSION`` is bumped on every additive
  change so the frontend can branch on capabilities if it ever needs to. A
  *breaking* change (renaming/removing a type, changing a payload field's
  meaning) is forbidden under the additive rule — it would require a new
  endpoint, not a version bump.
* **Surfaced on the wire.** The version travels on the terminal ``done`` event
  AND the ``metadata`` event (see :meth:`SSEEmitter.emit_done` /
  :meth:`SSEEmitter.emit_metadata`) under the key ``protocol_version`` so the
  frontend can read it without an out-of-band negotiation.

EVENT CATALOGUE (every ``type``/``event`` value the stream can emit, with its
payload shape). The emitter methods that produce each are named in brackets.

  status           {"step": str}                         [emit_status]
      Coarse pipeline-phase progress. ``step`` is a free-form token the UI maps
      to a human label (e.g. "cache_hit", "loading_context", "entity_resolution",
      "verifying"). The ``verifying`` step (Phase-1) marks the post-synthesis
      grounding-validation / repair phase that used to be silent.
  thinking         {"stage": str}                        [emit_thinking]
      First-turn LLM call started (tool classification). ``stage`` defaults to
      "tool_classification".
  agent_iteration  {"iteration": int, "max_iterations": int,
                    "stage": "planning_tools"|"reasoning_over_results"
                             |"synthesizing",
                    "tools_completed_total": int, "elapsed_ms": int}
                                                          [emit_agent_iteration]
      ReAct-loop boundary pulse so the UI never goes blank between tool batches.
  tool_call        {"type": "tool_call", "tool": str, "label": str,
                    "input": {...}, "status": "running",
                    "is_fallback"?: bool, "fallback_of"?: str}
                                                          [emit_tool_call]
      A tool is about to execute. ``label`` is the human, input-aware line the
      Research timeline renders (e.g. "Searching news for NVIDIA").
  tool_result      {"type": "tool_result", "tool": str,
                    "status": "ok"|"error"|"empty"|"transport_error",
                    "item_count": int, "label"?: str,
                    "reason"?: str, "status_code"?: int,
                    "elapsed_ms"?: int, "duration_ms"?: int,
                    "result_preview"?: [{id,title}],
                    "grounding_sample"?: {...}}           [emit_tool_result]
      A tool finished. ``label`` (Phase-1) mirrors the human line so the UI can
      render a completion line ("Found 12 articles") without re-deriving it.
  token            {"text": str}                         [emit_token / emit_delta]
      One streamed slice of the answer.
  final_answer     {"text": str}                         [emit_final_answer]
      The complete post-validation answer in one frame (fallback for zero-token
      streams; streaming clients already saw the tokens).
  citations        [{ref,item_type,id,title,url,source_name,
                     published_at,entity_name,confidence}]  [emit_citations]
  suggestions      [str, ...]                            [emit_suggestions]
  contradictions   [{claim_type,strength,sides}]         [emit_contradictions]
  pending_action   {"type": "pending_action", "proposal_id": str,
                    "tool": str, "description": str, "params": {...}}
                                                          [emit_pending_action]
  action_executed  {"type": "action_executed", "proposal_id": str,
                    "tool": str, "result": {...}}         [emit_action_executed]
  action_rejected  {"type": "action_rejected", "proposal_id": str,
                    "tool": str, "reason": str}           [emit_action_rejected]
  metadata         {"thread_id": str, "message_id": str, "intent": str,
                    "provider": str, "latency_ms": int,
                    "protocol_version": int}              [emit_metadata]
  error            {"code": str, "message": str}         [emit_error]
  done             {"type": "done", "protocol_version": int,
                    "phase_timings_ms"?: {...}}           [emit_done]
      Terminal frame. Always last.
"""

from __future__ import annotations

from enum import Enum
from typing import Final

# ── Protocol version ─────────────────────────────────────────────────────────
# Bumped on EVERY additive change to the catalogue above (new event type, new
# payload field). Surfaced on the wire via the ``done`` and ``metadata`` events
# under the key ``protocol_version`` so the frontend reads it directly.
#
# History:
#   1 — pre-standardization baseline (all event types up to PLAN-0107).
#   2 — Phase-1: tool_call/tool_result gain an input-aware human ``label``;
#       ``status`` event adds the ``verifying`` step; protocol_version is now
#       surfaced on the ``done`` + ``metadata`` events.
SSE_PROTOCOL_VERSION: Final[int] = 2

# Key under which the version is attached to the done/metadata payloads. A named
# constant so the frontend contract and the tests reference one literal.
PROTOCOL_VERSION_KEY: Final[str] = "protocol_version"


class SSEEventType(str, Enum):
    """Canonical enum of every SSE ``event``/``type`` value the stream emits.

    The string VALUES are the wire contract — they MUST NOT change (the frontend
    demultiplexes on them; renaming one silently drops the event). New types are
    appended only. Subclassing ``str`` lets these be used directly as the
    ``event`` field of an SSE frame dict (``{"event": SSEEventType.TOKEN, ...}``)
    while still being a typed enum for backend call sites.
    """

    STATUS = "status"
    THINKING = "thinking"
    AGENT_ITERATION = "agent_iteration"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    TOKEN = "token"  # noqa: S105 — SSE event name, not a credential
    FINAL_ANSWER = "final_answer"
    CITATIONS = "citations"
    SUGGESTIONS = "suggestions"
    CONTRADICTIONS = "contradictions"
    PENDING_ACTION = "pending_action"
    ACTION_EXECUTED = "action_executed"
    ACTION_REJECTED = "action_rejected"
    METADATA = "metadata"
    ERROR = "error"
    DONE = "done"


# ── Status-step vocabulary ────────────────────────────────────────────────────
# The ``status`` event carries a free-form ``step`` token; these constants name
# the ones with cross-cutting meaning so the orchestrator and tests don't repeat
# string literals. The ``VERIFYING`` step (Phase-1) is the headline addition —
# it marks the previously-silent post-synthesis grounding-validation / repair
# phase so the UI can show "Verifying answer against sources…".
class SSEStatusStep(str, Enum):
    """Well-known ``step`` values for the ``status`` event."""

    CACHE_HIT = "cache_hit"
    LOADING_CONTEXT = "loading_context"
    ENTITY_RESOLUTION = "entity_resolution"
    # Phase-1: the grounding-validation / repair phase that runs AFTER synthesis
    # and BEFORE the final answer is finalised. Before this it was silent.
    VERIFYING = "verifying"
