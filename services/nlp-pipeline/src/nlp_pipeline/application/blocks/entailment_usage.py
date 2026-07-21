"""Shared LLM cost logging for the entailment verifier passes.

Why this module exists
----------------------
The relation- and claim-entailment gates (``relation_entailment.py`` /
``claim_entailment.py``) each fire a cheap verifier LLM call per gated item.
Both originally called ``ExtractionClient.extract()`` with NO usage_logger, so
their spend never reached ``nlp_db.llm_usage_log`` — it only incremented an
in-process counter on the (unscraped) consumer pod, making the verifier cost
INVISIBLE on the cost dashboards. ``deep_extraction._run_extraction_window``
already logs every extraction call; this helper factors that exact accounting
out so the twin entailment gates record their calls the SAME way, without
duplicating the ~30-line token/cost/fallback block in two places.

Design invariants (mirror the protocol contract):
* **Fire-and-forget / fail-open**: a usage-logging failure MUST NEVER propagate
  to the caller — a cost-log blip cannot be allowed to drop a verdict. All
  internal exceptions are swallowed and logged via structlog.
* **Actual serving model**: records ``ExtractionOutput.model_used`` (the
  secondary slug when a 429/timeout forced a fallback hop) and ``fallback_reason``,
  not just the configured primary — same as deep extraction.
* **Provider-authoritative cost**: prefers the provider's verbatim
  ``usage.estimated_cost`` (``provider_cost_usd``) via ``resolve_cost``, falling
  back to the price matrix; Ollama-served calls resolve to $0/"local".
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID

import structlog  # type: ignore[import-untyped]
from ml_clients.pricing import resolve_cost  # type: ignore[import-not-found]

if TYPE_CHECKING:
    from ml_clients.protocols import ExtractionClient  # type: ignore[import-not-found]
    from ml_clients.usage_log import LlmUsageLogProtocol  # type: ignore[import-untyped]

logger = structlog.get_logger(__name__)  # type: ignore[no-any-return]


async def log_entailment_usage(
    usage_logger: LlmUsageLogProtocol,
    *,
    entailment_client: ExtractionClient,
    model_id: str,
    prompt: str,
    output: Any | None,
    latency_ms: int,
    success: bool,
    doc_id: str | None,
    event_name: str,
) -> None:
    """Append one ``llm_usage_log`` row for a single entailment verifier call.

    Best-effort: any failure is swallowed and logged, mirroring the
    ``LlmUsageLogProtocol`` contract (a cost-log failure must never disrupt the
    verifier). ``output`` is ``None`` when ``extract()`` raised — the row is
    still written with ``success=False`` so failed verifier calls are visible.

    Args:
        usage_logger: the service cost-log repository (already known non-None).
        entailment_client: the verifier ExtractionClient (for ``provider``).
        model_id: configured verifier model id (fallback when the adapter does
            not surface ``model_used``).
        prompt: the full prompt string (word-split for the ``tokens_in`` estimate).
        output: the ``ExtractionOutput`` on success, else ``None``.
        latency_ms: wall-clock duration of the LLM call.
        success: whether ``extract()`` returned without raising.
        doc_id: source document id (telemetry only).
        event_name: structlog event name used if logging itself fails
            (e.g. ``"relation_entailment.usage_log_failed"``).
    """
    try:
        # Record the ACTUAL serving model + why any fallback happened — identical
        # accounting to deep_extraction._run_extraction_window (Task #36).
        actual_model = getattr(output, "model_used", None) or model_id
        fallback_reason = getattr(output, "fallback_reason", "none")
        provider = getattr(entailment_client, "provider", "unknown")
        # Word-split token estimates (protocol guidance). Context for the verifier
        # prompt is embedded in the prompt string itself, so there is no separate
        # context term to add (unlike deep extraction's window_text).
        tokens_in = len(prompt.split())
        tokens_out = len(str(getattr(output, "raw_response", "") or "").split())
        cost, cost_source = resolve_cost(
            actual_model,
            provider=provider,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            provider_estimated_cost=getattr(output, "provider_cost_usd", None),
        )
        await usage_logger.log(
            model_id=actual_model,
            provider=provider,
            capability="extraction",
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            latency_ms=latency_ms,
            estimated_cost_usd=float(cost),
            success=success,
            error_code=None if success else "model_error",
            doc_id=UUID(doc_id) if doc_id else None,
            fallback_reason=fallback_reason,
            cost_source=cost_source,
        )
    except Exception as exc:  # protocol forbids raising; belt-and-braces
        logger.warning(
            event_name,
            doc_id=doc_id,
            error=str(exc),
            exc_info=True,
        )
