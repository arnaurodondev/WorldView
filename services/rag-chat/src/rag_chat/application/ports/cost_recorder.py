"""Port for per-LLM-call cost recording (PLAN-0107 follow-up — agent-B mission).

A ``CostRecorder`` is invoked AFTER every LLM API call completes (success or
failure) to:

  1. Compute the USD cost for the call via the canonical pricing matrix in
     ``libs/ml-clients/pricing.py``.
  2. Increment the Prometheus counter ``rag_chat_ml_api_estimated_cost_usd_total``
     so the Grafana panel id=6 (which was previously empty — the counter did
     not exist) starts showing real series.
  3. Append a row to ``llm_usage_log`` with the **real** ``estimated_cost_usd``
     value (was previously hard-coded to 0.0 across all call sites).
  4. Atomically bump ``chat_threads.estimated_cost_usd`` so operators can see
     per-conversation cumulative cost without scanning the log table.

The port lives in the application layer so use cases can depend on it
without importing infrastructure (R12 — domain/application layer purity).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from uuid import UUID


class CostRecorder(Protocol):
    """Structural protocol for per-call LLM cost recording.

    Implementations MUST be fire-and-forget safe (never raise) — a cost
    recording failure must never propagate to the chat path.
    """

    async def record(
        self,
        *,
        thread_id: UUID | None,
        model_id: str,
        tokens_in: int,
        tokens_out: int,
        call_site: str,
        provider_estimated_cost: object = None,
        user_id: UUID | None = None,
    ) -> None:
        """Record a single LLM call's cost.

        Args:
            thread_id: Owning conversation thread, or ``None`` for batch /
                non-conversational call sites (e.g. citation-judge cron).
            model_id: Canonical model identifier (must match a
                ``MODEL_PRICING`` key for a non-zero cost).
            tokens_in: Prompt token count returned by the provider.
            tokens_out: Completion token count returned by the provider.
            provider_estimated_cost: Raw ``usage.estimated_cost`` from the
                DeepInfra response (float/int/str/None). PLAN-0117 W4 (FR-1):
                when present it is the **authoritative** cost persisted verbatim
                with ``cost_source='provider'``; when ``None`` the recorder
                falls back to the price matrix (never a silent $0 for a paid
                model). The §2.2 priority is resolved once, centrally, by
                ``ml_clients.resolve_cost``.
            user_id: Authenticated end user (PLAN-0117 FR-3); ``None`` for
                system/background call sites (e.g. cron, intent classifier).
            call_site: Bounded label for the Prometheus counter. Allowed
                values used today:
                  * ``"tool_loop_iter"`` — provider_chain.chat_with_tools
                  * ``"synthesis"`` — provider_chain.stream_chat
                  * ``"intent_classifier"`` — pipeline.intent_classifier
                  * ``"safety_classifier"`` — security.llm_injection_classifier
                  * ``"citation_judge"`` — citation_judge_adapter
                Keep the cardinality bounded (≤ 10) — never user/tenant IDs.
        """
        ...  # pragma: no cover
