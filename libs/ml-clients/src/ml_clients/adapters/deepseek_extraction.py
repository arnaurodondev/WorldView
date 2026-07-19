"""DeepSeek extraction adapter — structured extraction via DeepSeek-compatible OpenAI endpoint."""

from __future__ import annotations

import asyncio
import json
import os
import re
import time
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import structlog

from ml_clients.dataclasses import ExtractionInput, ExtractionOutput
from ml_clients.errors import (
    FatalError,
    ProviderBillingError,
    RateLimitError,
    RetryableError,
    is_billing_status,
    is_transient_status,
    parse_retry_after,
)
from ml_clients.pricing import provider_cost_to_decimal

if TYPE_CHECKING:
    from observability.metrics import MLMetrics

logger = structlog.get_logger()

_DEFAULT_MODEL_ID = "deepseek-ai/DeepSeek-V4-Flash"
_DEFAULT_BASE_URL = "https://api.deepinfra.com/v1/openai"

# ── Task #36: 429 rate-limit fallback to a SECONDARY model ────────────────────
# Motivation (post-outage RCA): after a platform outage a backlog saturated the
# PRIMARY deep-extraction model (Qwen/Qwen3-235B-A22B-Instruct-2507 on DeepInfra).
# Articles then hit the consumer's ``message_processing_timeout`` and were
# dead-lettered.  The dominant saturation signal is HTTP 429 ``engine_overloaded``.
#
# When the primary returns 429 (or, optionally, persistently times out AFTER its
# own bounded retry is exhausted), we re-issue the SAME extraction request — same
# prompt, same ``response_format=json_object`` so the output is schema-compatible —
# against a SECONDARY model that is verified to exist on DeepInfra and accept the
# OpenAI-compatible chat/JSON request:
#
#   deepseek-ai/DeepSeek-V4-Flash  (284B MoE / 13B active, 1M ctx, $0.14/$0.28 per
#   1M tok; FP4; TTFT ~1.05s).  Confirmed via DeepInfra model/API reference.
#
# The fallback model id is INJECTED (env ``ML_CLIENTS_EXTRACTION_FALLBACK_MODEL_ID``
# / nlp-pipeline config).  When it is empty/unset the behaviour is UNCHANGED — we
# simply exhaust the primary's retry budget and raise, exactly as before this task.
_DEFAULT_FALLBACK_MODEL_ID = os.environ.get("ML_CLIENTS_EXTRACTION_FALLBACK_MODEL_ID", "")
# When True, a persistent timeout/5xx on the primary (after its retry budget is
# spent) ALSO triggers the fallback hop — not just a 429.  A 429 ALWAYS triggers
# the fallback (it is the canonical saturation signal).  Env-overridable.
_DEFAULT_FALLBACK_ON_TIMEOUT = os.environ.get("ML_CLIENTS_EXTRACTION_FALLBACK_ON_TIMEOUT", "true").lower() in (
    "1",
    "true",
    "yes",
)

# ── fallback_reason vocabulary (mirrors ExtractionOutput.fallback_reason) ──────
# These are the ONLY strings written to ``llm_usage_log.fallback_reason`` so the
# audit query ``SELECT model, fallback_reason, count(*) ... GROUP BY 1,2`` has a
# stable, low-cardinality domain.
_FALLBACK_NONE = "none"
_FALLBACK_RATE_LIMIT = "rate_limit"
_FALLBACK_TIMEOUT = "timeout"
_FALLBACK_SERVER_ERROR = "server_error"

# Deep-tier extraction (Qwen3-235B-A22B on DeepInfra) has a bursty latency tail:
# p50 ~16.5s but p95/p99 pin at the wall-clock cap under queue pressure.
#
# RETRY/TIMEOUT MODEL (2026-06-14, extraction transient-failure resilience):
# The dominant live failure is HTTP 429 ``engine_overloaded`` ("Model busy, retry
# later") from DeepInfra under throughput bursts — 73% of failures are fast-fail
# 429s (<5s), 20% are wall-clock timeouts (~150s), 7% mid-range 5xx/conn.  Before
# this change the adapter made ONE shot and a single 429/timeout raised
# ``RetryableError`` immediately; the consumer's OFF retry path then committed the
# offset with empty ``relations`` (silent-null).  We now bound-retry transient
# failures INSIDE the adapter (the only layer that can see ``Retry-After`` and the
# 429-vs-5xx-vs-4xx distinction before the error is type-erased).
#
# BUDGET ARITHMETIC (why these numbers fit the consumer watchdog):
#   * ``message_processing_timeout_s`` watchdog bounds the WHOLE article pipeline
#     (GLiNER NER, which can take ~160s under load, PLUS every extraction window run
#     sequentially).  So the extraction retry budget cannot multiply freely or it
#     would blow the watchdog.
#   * TASK #5 (2026-06-16): the 235B deep tier is LATENCY-bound — the throughput
#     audit measured a full extract() at p50=161s / p95=179s, yet the old 90s
#     per-attempt cap cut calls that would have completed, logging "wall-clock
#     timeout after 90.0s".  The defaults below are RAISED so a p95 call finishes:
#       - per-attempt cap   = 300s  (was 90s) → p95 (179s) completes on attempt 1.
#       - max_attempts      = 2     (was 3)   → with a 300s cap, 2 fits the budget.
#       - total per-model budget = 320s (was 200s) → one 300s attempt + short backoff.
#     The nlp-pipeline ALSO passes these explicitly from NLP_PIPELINE_* config (the
#     authoritative source — see article_consumer_main.py); these module defaults are
#     the fallback when the adapter is constructed without explicit values.
#   * Worst case per window (primary 320 + fresh fallback budget 320) ≈ 640s; the
#     consumer watchdog is sized to 900s to fit this + NER + writes (see config.py).
#
# The openai SDK default of 600s means a stalled request would otherwise hang the
# article consumer for up to 10 minutes (BP-235 variant); asyncio.wait_for caps the
# wall clock per attempt.  The httpx read timeout is wired to the SAME per-attempt
# timeout_s value (see __init__) so it never fires before the wait_for guard.
# All knobs env-overridable so they can be tuned without a code change.
_EXTRACTION_TIMEOUT_S = float(os.environ.get("ML_CLIENTS_EXTRACTION_TIMEOUT_S", "300.0"))
# Total wall-time budget across ALL attempts of a single extract() call against ONE
# model (s).  Once the elapsed time would exceed this, no further retry on THAT
# model is scheduled and the last transient error is raised (or — Task #36 — the
# fallback model is tried).  Task #5: bumped 200->320s so one full 300s attempt plus
# a short backoff stays in budget for the latency-bound 235B.  The fallback model
# gets its OWN fresh budget (see _create_with_retry), so the worst-case wall time per
# window is roughly ``primary_budget + fallback_budget`` — the consumer
# ``message_processing_timeout_s`` is raised to fit this (see nlp-pipeline config).
_EXTRACTION_TOTAL_BUDGET_S = float(os.environ.get("ML_CLIENTS_EXTRACTION_TOTAL_BUDGET_S", "320.0"))
# Maximum attempts for a single extract() call (1 initial + retries).  Task #5:
# lowered 3->2 — with the 300s per-attempt cap, 2 attempts is the most that fits the
# 320s per-model budget; the 235B's failures are dominated by latency (now absorbed
# by the larger cap), not by recoverable 429 bursts that a 3rd attempt would catch.
_EXTRACTION_MAX_ATTEMPTS = int(os.environ.get("ML_CLIENTS_EXTRACTION_MAX_ATTEMPTS", "2"))
# Exponential-backoff-with-full-jitter parameters for transient retries.
_EXTRACTION_BACKOFF_BASE_S = float(os.environ.get("ML_CLIENTS_EXTRACTION_BACKOFF_BASE_S", "2.0"))
_EXTRACTION_BACKOFF_CAP_S = float(os.environ.get("ML_CLIENTS_EXTRACTION_BACKOFF_CAP_S", "20.0"))

# ── reasoning_effort (relation-extraction quality, 2026-06-15) ────────────────
# The relation-extraction quality audit (docs/audits/2026-06-13-relation-extraction-
# quality-audit.md §5/§6 and the v1.6 re-A/B) found that running Qwen3-235B with
# ``reasoning_effort="none"`` suppresses BOTH recall (the model never enumerates
# candidate entity pairs before deciding, so it defaults to the empty array) AND
# precision (with no scratchpad it cannot reason that two co-mentioned companies
# are merely listed together, not in a relationship).  We therefore default to
# ``"low"`` — a lightweight reasoning budget that lets the model "list candidate
# pairs, then classify" implicitly — paired with the v1.6 precision prompt.
#
# COST / LATENCY TRADEOFF: "low" reasoning adds a modest hidden-token + latency
# cost over "none" (the answer still lands in ``content`` because the prompt forces
# ``response_format=json_object``; reasoning tokens are billed but not returned).
# The per-attempt 300s cap and the 320s total budget absorb the extra latency.  The
# knob is env-overridable (``ML_CLIENTS_EXTRACTION_REASONING_EFFORT``) so it can be
# reverted to "none" without a code change if a future cost review demands it.
_EXTRACTION_REASONING_EFFORT = os.environ.get("ML_CLIENTS_EXTRACTION_REASONING_EFFORT", "low")
# Separate reasoning budget for the SECONDARY (fallback) model.  gpt-oss-20b was
# validated at ``@low`` (see docs/audits/2026-06-16-extraction-model-ab-results.md)
# and is the cheap/fast last-resort hop, so it does NOT need the primary's higher
# reasoning budget.  When empty, the fallback inherits the primary's effort (legacy
# behaviour — a single shared knob).  Env: ML_CLIENTS_EXTRACTION_FALLBACK_REASONING_EFFORT.
_EXTRACTION_FALLBACK_REASONING_EFFORT = os.environ.get("ML_CLIENTS_EXTRACTION_FALLBACK_REASONING_EFFORT", "")

# max_tokens CAP for the extraction completion.  This is a CEILING, not a target:
# gpt-oss-120b@medium emits at most ~3k completion tokens on the 100-doc golden set
# (p50 ~1.4k), so 8192 is pure safety margin the model never fills — verified to add
# no latency vs 4096 (docs/audits/2026-06-16-extraction-model-ab-results.md, 8192-check).
# Reasoning models can need headroom above the answer JSON; the user asked for margin.
# Env-overridable: ML_CLIENTS_EXTRACTION_MAX_TOKENS.
_EXTRACTION_MAX_TOKENS = int(os.environ.get("ML_CLIENTS_EXTRACTION_MAX_TOKENS", "4096"))


class DeepSeekExtractionAdapter:
    """Implements ExtractionClient via DeepInfra OpenAI-compatible endpoint. Default model: DeepSeek-V4-Flash."""

    def __init__(
        self,
        api_key: str,
        model_id: str = _DEFAULT_MODEL_ID,
        base_url: str = _DEFAULT_BASE_URL,
        *,
        semaphore: asyncio.Semaphore,
        timeout_s: float = _EXTRACTION_TIMEOUT_S,
        max_attempts: int = _EXTRACTION_MAX_ATTEMPTS,
        total_budget_s: float = _EXTRACTION_TOTAL_BUDGET_S,
        backoff_base_s: float = _EXTRACTION_BACKOFF_BASE_S,
        backoff_cap_s: float = _EXTRACTION_BACKOFF_CAP_S,
        # reasoning budget for the extraction call (see _EXTRACTION_REASONING_EFFORT).
        # "low" (default) lets the model enumerate candidate entity pairs before
        # classifying — improves recall AND co-mention rejection (precision).
        reasoning_effort: str = _EXTRACTION_REASONING_EFFORT,
        # Separate reasoning budget for the fallback model.  Empty => inherit the
        # primary's ``reasoning_effort`` (legacy single-knob behaviour).  Set to a
        # cheaper level (e.g. "low") so the fast last-resort hop is not forced into
        # the primary's higher reasoning cost.
        fallback_reasoning_effort: str = _EXTRACTION_FALLBACK_REASONING_EFFORT,
        # max_tokens ceiling for the completion (see _EXTRACTION_MAX_TOKENS).  A CAP,
        # not a target — reasoning models won't fill it; raising it is free margin.
        max_tokens: int = _EXTRACTION_MAX_TOKENS,
        # Task #36: SECONDARY model slug used when the primary is rate-limited (or
        # persistently fails).  Empty string => fallback disabled (behaviour
        # unchanged: exhaust primary retries then raise).
        fallback_model_id: str = _DEFAULT_FALLBACK_MODEL_ID,
        # Whether a persistent timeout/5xx on the primary ALSO triggers the
        # fallback hop.  A 429 always does, regardless of this flag.
        fallback_on_timeout: bool = _DEFAULT_FALLBACK_ON_TIMEOUT,
        max_connections: int = 64,
        max_keepalive_connections: int = 32,
        metrics: MLMetrics | None = None,
    ) -> None:
        try:
            import openai as _openai
        except ImportError as exc:
            raise FatalError("openai package not installed; install ml-clients[openai]") from exc

        self._model_id = model_id
        # Task #36: normalise the fallback slug — a blank/whitespace value disables
        # the fallback entirely (behaviour identical to pre-task).  We never fall
        # back onto the SAME model as the primary (that would be a pointless extra
        # hop into the same saturated engine), so a fallback == primary is treated
        # as "no fallback configured".
        _fb = (fallback_model_id or "").strip()
        self._fallback_model_id: str | None = _fb if _fb and _fb != model_id else None
        self._fallback_on_timeout = fallback_on_timeout
        self._semaphore = semaphore
        self._metrics = metrics
        self._openai = _openai
        self._timeout_s = timeout_s
        # Bounded in-adapter retry knobs (transient-failure resilience).
        # max_attempts is clamped to >=1 so a misconfigured 0 still makes one call.
        self._max_attempts = max(1, max_attempts)
        self._total_budget_s = total_budget_s
        self._backoff_base_s = backoff_base_s
        self._backoff_cap_s = backoff_cap_s
        self._reasoning_effort = reasoning_effort
        # Fallback reasoning_effort: explicit value if given, else inherit primary.
        _fb_effort = (fallback_reasoning_effort or "").strip()
        self._fallback_reasoning_effort = _fb_effort or reasoning_effort
        self._max_tokens = max_tokens
        # Task #14: deep extraction is I/O-bound (12-22s DeepInfra network wait per
        # article).  When the article consumer processes many articles concurrently,
        # an equal number of extraction calls hit this client at once.  httpx's
        # default Limits (max_connections=100, max_keepalive=20) silently *queue*
        # connections beyond the keepalive pool, adding hidden latency under load.
        # We pass an explicit httpx.AsyncClient with Limits sized for the configured
        # concurrency (default 64 conns / 32 keepalive ~ 50 concurrent + headroom).
        # A wide keepalive pool also keeps warm TCP+TLS connections so DeepInfra's
        # server-side KV prefix cache (same system prompt) stays hot across calls.
        import httpx  # local import: httpx ships transitively with the openai SDK

        http_client = httpx.AsyncClient(
            limits=httpx.Limits(
                max_connections=max_connections,
                max_keepalive_connections=max_keepalive_connections,
            ),
            timeout=httpx.Timeout(connect=5.0, read=timeout_s, write=30.0, pool=5.0),
        )
        # Client is created once at startup so httpx maintains a persistent connection
        # pool across extraction calls. This also enables DeepInfra's server-side KV
        # prefix cache: when the system prompt bytes are identical across calls, the
        # provider reuses cached KV tensors and charges only for the new user tokens.
        self._client = _openai.AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=_openai.Timeout(connect=5.0, read=timeout_s, write=30.0, pool=5.0),
            http_client=http_client,
        )

    @property
    def model_id(self) -> str:
        """Canonical primary model id, exposed for cost/usage attribution.

        Consumers such as ``knowledge_graph.infrastructure.llm.fallback_chain``
        read ``getattr(client, "model_id", provider)`` when writing a row to
        ``llm_usage_log``. Without this property that ``getattr`` silently fell
        back to the transport ``provider`` string (``"deepinfra"``), so every KG
        extraction row logged ``model_id="deepinfra"`` — the real serving model
        (e.g. ``deepseek-ai/DeepSeek-V4-Flash-Thinking``) was lost and per-model
        cost attribution across services was impossible. Exposing the configured
        primary slug restores correct attribution (LLM-cost audit 2026-07-16).

        The primary slug is reported even when an individual call transparently
        falls back to ``self._fallback_model_id`` — attribution to the fallback
        tier is a follow-up; primary-vs-``"deepinfra"`` is the material fix.
        """
        return self._model_id

    async def aclose(self) -> None:
        await self._client.close()

    def _classify_transient(self, exc: BaseException) -> RetryableError | FatalError:
        """Map a raw provider exception to RetryableError (transient) or FatalError.

        Transient (retry-worthy):
          * ``openai.RateLimitError`` (HTTP 429 — the dominant ``engine_overloaded``
            case).  Promoted to :class:`RateLimitError` carrying the parsed
            ``Retry-After`` so the backoff can honour the provider's hint.
          * ``openai.APITimeoutError`` / ``openai.APIConnectionError`` (network/TTFT).
          * ``asyncio.TimeoutError`` / builtin ``TimeoutError`` (our per-attempt
            ``asyncio.wait_for`` wall-clock cap firing).
          * ``openai.APIStatusError`` with status >= 500 (provider 5xx) or a
            transient 4xx (408/409/425).
          * ``openai.APIStatusError`` with a BILLING/auth status (401/402/403) —
            promoted to :class:`ProviderBillingError`. HTTP 402 is the DeepInfra
            spend-cap refusal (the 2026-07-18 incident that silently empty-committed
            693 article extractions); it clears when the operator raises the cap, so
            it MUST redeliver rather than drop.

        Fatal (NOT retry-worthy — a retry cannot fix bad input):
          * ``openai.APIStatusError`` with a bad-input 4xx (400/404/413/422/…).
          * Anything else unexpected.
        """
        # NOTE: RateLimitError subclasses APIStatusError in the openai SDK, so it
        # MUST be checked before the generic APIStatusError branch.
        if isinstance(exc, self._openai.RateLimitError):
            retry_after = parse_retry_after(getattr(getattr(exc, "response", None), "headers", None))
            return RateLimitError(f"DeepSeek rate limit (429): {exc}", retry_after=retry_after)
        if isinstance(exc, self._openai.APITimeoutError):
            return RetryableError(f"DeepSeek timeout: {exc}")
        if isinstance(exc, self._openai.APIConnectionError):
            return RetryableError(f"DeepSeek connection error: {exc}")
        if isinstance(exc, TimeoutError):
            # builtin TimeoutError is what asyncio.TimeoutError aliases to (py3.11+).
            return RetryableError(f"DeepSeek wall-clock timeout after {self._timeout_s}s")
        if isinstance(exc, self._openai.APIStatusError):
            status_code = getattr(exc, "status_code", 0)
            # Billing/auth refusal (401/402/403) — retry, but self-heal only when
            # the operator raises the spend cap. ProviderBillingError is a
            # RetryableError so deep_extraction's ``except RetryableError`` re-queues
            # the doc instead of silently empty-committing it.
            if is_billing_status(status_code):
                return ProviderBillingError(f"DeepSeek billing/auth refusal (HTTP {status_code}): {exc}")
            if is_transient_status(status_code):
                # Keep the "5xx" marker in the message for >=500 so
                # ``_reason_for_transient`` still tags fallback_reason=server_error;
                # transient 4xx (408/409/425) fall back to the generic reason.
                marker = "5xx" if status_code >= 500 else f"transient {status_code}"
                return RetryableError(f"DeepSeek {marker} (HTTP {status_code}): {exc}")
            return FatalError(f"DeepSeek 4xx: {exc}")
        return FatalError(f"Unexpected DeepSeek error: {exc}")

    def _compute_backoff(self, attempt: int, retry_after: int | None) -> float:
        """Backoff (seconds) before the next attempt: exponential with full jitter.

        ``attempt`` is the 1-based number of the attempt that JUST failed.  Base is
        ``backoff_base_s * 2**(attempt-1)`` capped at ``backoff_cap_s``; full jitter
        picks a uniform value in ``[0, capped_base]`` to avoid thundering-herd
        re-tries that re-trigger ``engine_overloaded``.  When the provider supplied
        a ``Retry-After`` hint (429), we honour it as a floor but still cap it at
        ``backoff_cap_s`` so a hostile/large hint cannot blow the total budget.
        """
        import random  # local import: only needed on the (rare) retry path.

        exp = self._backoff_base_s * (2.0 ** (attempt - 1))
        capped = min(exp, self._backoff_cap_s)
        jittered = random.uniform(0.0, capped)  # noqa: S311 — jitter, not cryptographic
        if retry_after is not None and retry_after > 0:
            return min(float(retry_after), self._backoff_cap_s)
        return jittered

    @staticmethod
    def _reason_for_transient(exc: RetryableError) -> str:
        """Map a terminal transient error to a ``fallback_reason`` literal.

        Used to tag WHY the primary failed when we hand off to the fallback model
        (and for the audit row).  ``RateLimitError`` => ``rate_limit``; an explicit
        5xx-tagged ``RetryableError`` => ``server_error``; everything else
        (wall-clock / APITimeout / connection) => ``timeout``.
        """
        if isinstance(exc, RateLimitError):
            return _FALLBACK_RATE_LIMIT
        # ``_classify_transient`` tags 5xx with the "5xx" marker in the message.
        if "5xx" in str(exc):
            return _FALLBACK_SERVER_ERROR
        return _FALLBACK_TIMEOUT

    async def _create_with_retry(self, inp: ExtractionInput, model_id: str, reasoning_effort: str) -> tuple[Any, int]:
        """Call ``model_id`` with bounded retry on transient failures.

        Returns ``(response, attempts)`` where ``attempts`` is the number of HTTP
        attempts this model consumed (>=1).  Retries 429/5xx/timeout/connection
        errors up to ``self._max_attempts`` times, each attempt capped at
        ``self._timeout_s`` and the WHOLE per-model call capped at
        ``self._total_budget_s``.  A non-transient error (4xx/auth) raises
        :class:`FatalError` immediately with NO retry.  When all attempts are
        exhausted (or the budget is spent) the LAST transient error is re-raised
        (``RetryableError`` subclass) — never an empty result — so the caller can
        either try the fallback model or DLQ.

        ``model_id`` is a parameter (not ``self._model_id``) so the SAME retry loop
        serves both the primary and the Task #36 fallback model.
        """
        call_start = time.monotonic()
        last_transient: RetryableError | None = None
        for attempt in range(1, self._max_attempts + 1):
            try:
                response = await asyncio.wait_for(
                    self._client.chat.completions.create(
                        model=model_id,
                        messages=[
                            {"role": "system", "content": inp.prompt},
                            {"role": "user", "content": inp.context},
                        ],
                        response_format={"type": "json_object"},
                        temperature=0.0,
                        max_tokens=self._max_tokens,
                        extra_body={
                            # reasoning_effort is per-MODEL (passed in) so the primary
                            # (gpt-oss-120b@medium) and the fallback (gpt-oss-20b@low)
                            # each run at their validated budget — see the 2026-06-16
                            # extraction-model A/B audit.  Both are REASONING models:
                            # without an explicit effort they spend the whole budget on
                            # hidden reasoning and return EMPTY content, so this MUST be
                            # set.  Bump the cache key to v2 so DeepInfra does not serve a
                            # KV-prefix cache built for the old (none-reasoning) path.
                            "reasoning_effort": reasoning_effort,
                            "prompt_cache_key": "kg_extraction_v2",
                        },
                    ),
                    timeout=self._timeout_s,
                )
                return response, attempt
            except (RetryableError, FatalError):
                # Should not originate from create(), but if a wrapped error bubbles
                # up keep its existing classification intact.
                raise
            except Exception as exc:  # — classified immediately below
                mapped = self._classify_transient(exc)
                if isinstance(mapped, FatalError):
                    # 4xx/auth/unexpected — a retry cannot help.  Surface now.
                    raise mapped from exc
                last_transient = mapped
                retry_after = mapped.retry_after if isinstance(mapped, RateLimitError) else None
                # Decide whether another attempt fits the budget.
                attempts_left = attempt < self._max_attempts
                if not attempts_left:
                    break
                backoff = self._compute_backoff(attempt, retry_after)
                elapsed = time.monotonic() - call_start
                # The next attempt needs backoff + up to one more per-attempt
                # timeout; if that would exceed the total budget, stop now.
                if elapsed + backoff + self._timeout_s > self._total_budget_s:
                    logger.warning(
                        "deepseek_extraction_retry_budget_exhausted",
                        model_id=model_id,
                        attempt=attempt,
                        elapsed_s=round(elapsed, 1),
                        budget_s=self._total_budget_s,
                    )
                    break
                logger.warning(
                    "deepseek_extraction_retrying",
                    model_id=model_id,
                    attempt=attempt,
                    max_attempts=self._max_attempts,
                    backoff_s=round(backoff, 2),
                    retry_after=retry_after,
                    error=str(mapped),
                )
                await asyncio.sleep(backoff)
        # Exhausted retries (or budget) — re-raise the last transient error so the
        # caller decides between fallback and DLQ.
        assert last_transient is not None  # loop only breaks after setting it
        raise last_transient

    async def _create_with_fallback(self, inp: ExtractionInput) -> tuple[Any, str, str, int]:
        """Run the primary model, falling back to the secondary on rate-limit.

        Returns ``(response, model_used, fallback_reason, total_attempts)``.

        Flow (Task #36):
          1. Try the PRIMARY model via :meth:`_create_with_retry` (which itself
             bound-retries transient errors).  On success => primary served it,
             reason ``none``.
          2. If the primary raises a terminal transient error AND a fallback model
             is configured AND the failure is fallback-eligible (always for 429;
             for timeout/5xx only when ``fallback_on_timeout``), re-issue the SAME
             request against the SECONDARY model with a FRESH retry budget.  On
             success => secondary served it, reason reflects WHY the primary failed
             (``rate_limit`` | ``timeout`` | ``server_error``).
          3. If there is no eligible/configured fallback, OR the fallback ALSO
             fails, re-raise the primary's terminal error so the consumer DLQs —
             never an empty result.

        ``FatalError`` (4xx/auth/parse) is NEVER retried on the fallback: a schema
        or auth problem is deterministic and would fail identically on any model.
        """
        try:
            response, attempts = await self._create_with_retry(inp, self._model_id, self._reasoning_effort)
            return response, self._model_id, _FALLBACK_NONE, attempts
        except FatalError:
            # Deterministic failure — a different model will not help.  Propagate.
            raise
        except RetryableError as primary_exc:
            reason = self._reason_for_transient(primary_exc)
            # The terminal transient error does not carry an attempt count; the
            # primary consumed at most ``self._max_attempts`` HTTP attempts.  This
            # is only used for the audit ``attempts`` metadata, so an upper-bound
            # estimate is acceptable and never under-reports the work done.
            primary_attempts = self._max_attempts
            eligible = reason == _FALLBACK_RATE_LIMIT or self._fallback_on_timeout
            if self._fallback_model_id is None or not eligible:
                # No fallback (unset, or a non-eligible timeout/5xx with the flag
                # off) — behaviour unchanged: surface the transient error so the
                # consumer retries/DLQs the whole doc.
                raise
            logger.warning(
                "deepseek_extraction_fallback_engaged",
                primary_model_id=self._model_id,
                fallback_model_id=self._fallback_model_id,
                fallback_reason=reason,
                primary_error=str(primary_exc),
            )
            try:
                fb_response, fb_attempts = await self._create_with_retry(
                    inp, self._fallback_model_id, self._fallback_reasoning_effort
                )
            except (RetryableError, FatalError):
                # The fallback ALSO failed — re-raise the PRIMARY's transient error
                # (the canonical signal: the system is saturated) so the consumer
                # DLQs rather than recording an empty result.  We log the fallback
                # failure separately so both hops are visible in the trace.
                logger.warning(
                    "deepseek_extraction_fallback_failed",
                    primary_model_id=self._model_id,
                    fallback_model_id=self._fallback_model_id,
                    fallback_reason=reason,
                )
                raise primary_exc from None
            logger.info(
                "deepseek_extraction_fallback_succeeded",
                fallback_model_id=self._fallback_model_id,
                fallback_reason=reason,
            )
            return fb_response, self._fallback_model_id, reason, primary_attempts + fb_attempts

    async def extract(self, inp: ExtractionInput) -> ExtractionOutput:
        start = time.perf_counter()
        status = "success"
        tokens_in = 0
        tokens_out = 0
        tokens_cached = 0
        # PLAN-0117 FR-1: verbatim DeepInfra ``usage.estimated_cost`` when the
        # response reports it; stays None → matrix fallback in the finally block.
        provider_cost_usd: Decimal | None = None
        # Task #36 resilience-audit metadata.  These default to "primary served it
        # in one attempt" and are overwritten by _create_with_fallback's return.
        # ``model_used`` drives BOTH the metric labels AND the usage-log row, so the
        # cost/audit always reflects the model that ACTUALLY produced the result —
        # not the configured primary.
        model_used = self._model_id
        fallback_reason = _FALLBACK_NONE
        attempts = 1
        try:
            async with self._semaphore:
                try:
                    # PLAN-0052 platform-QA round 8 (2026-05-01): adopt the
                    # JSON-mode pattern proven by sibling workers
                    # (article_relevance_scoring_worker.py:335,
                    # unresolved_resolution_worker.py:561). Without these three
                    # parameters Llama-3.1-8B is free to wrap output in markdown
                    # fences, prepend reasoning preambles, or truncate at the
                    # default token cap — all producing JSONDecodeError that
                    # the article-consumer logs as ``deep_extraction.window_failed``
                    # and silently drops. ``response_format`` forces a valid
                    # JSON object server-side, ``temperature=0`` removes
                    # sampling variance, ``max_tokens=4096`` covers the
                    # extraction schema with comfortable headroom even for
                    # articles with many relations/events/claims.
                    # extra_body (DeepInfra extensions):
                    # reasoning_effort — defaults to "low" (relation-extraction quality,
                    #   2026-06-15): a lightweight reasoning budget lifts recall and lets
                    #   the model reject co-mention hallucinations.  With json_object the
                    #   answer still lands in content (reasoning tokens are billed, not
                    #   returned).  Env-overridable to "none" for a cost-only revert.
                    # prompt_cache_key — DeepInfra caches the system-prompt prefix KV
                    #   tensors across requests sharing the same key; only new (user-role)
                    #   tokens are billed after the initial cache-miss call.
                    # asyncio.wait_for enforces a per-attempt wall-clock timeout so
                    # a stalled DeepInfra request (high TTFT under queue pressure)
                    # cannot consume the article consumer's 900s watchdog budget.
                    # _create_with_fallback bound-retries transient failures (429
                    # engine_overloaded, 5xx, connection/timeout) on the PRIMARY
                    # inside the total wall-time budget, then — on a 429 (always) or
                    # a persistent timeout/5xx (when fallback_on_timeout) — re-issues
                    # the same request against the SECONDARY model.  It returns the
                    # actual model used + WHY the fallback fired + the attempt count.
                    # Non-transient errors (4xx/auth) raise FatalError without retry.
                    response, model_used, fallback_reason, attempts = await self._create_with_fallback(inp)
                    # Capture actual token usage from API response when available.
                    # cached_tokens: DeepInfra KV prefix cache hit count — non-zero when
                    # the system prompt prefix bytes matched a prior call on the same connection.
                    if response.usage is not None:
                        tokens_in = response.usage.prompt_tokens or 0
                        tokens_out = response.usage.completion_tokens or 0
                        details = getattr(response.usage, "prompt_tokens_details", None)
                        tokens_cached = getattr(details, "cached_tokens", 0) or 0
                        # PLAN-0117 FR-1: DeepInfra returns ``estimated_cost`` on
                        # ``usage``. Capture verbatim (best-effort — a parse
                        # failure must NOT break extraction; NFR-1). Preferred
                        # over the price matrix in the finally block below.
                        provider_cost_usd = provider_cost_to_decimal(getattr(response.usage, "estimated_cost", None))
                    # With reasoning_effort=none the answer must be in content.
                    # Do NOT fall back to reasoning_content: when reasoning_effort=none fails
                    # the model puts its full thinking chain there (~6 kB of prose) which
                    # will always fail JSON parsing and trigger an incorrect Ollama fallback.
                    msg = response.choices[0].message
                    raw_response: str = msg.content or ""
                    finish_reason: str | None = getattr(response.choices[0], "finish_reason", None)
                    logger.info(
                        "deepseek_extraction_completed",
                        model_id=model_used,
                        fallback_reason=fallback_reason,
                        attempts=attempts,
                        tokens_cached=tokens_cached,
                    )
                    # Defense-in-depth: even with response_format=json_object,
                    # strip markdown fences (` ```json ... ``` `) before parsing
                    # in case a future model variant ignores the directive.
                    try:
                        result: dict[str, object] = json.loads(raw_response)
                    except json.JSONDecodeError:
                        cleaned = re.sub(
                            r"^\s*```(?:json)?\s*|\s*```\s*$",
                            "",
                            raw_response.strip(),
                        )
                        try:
                            result = json.loads(cleaned)
                        except json.JSONDecodeError as exc:
                            # Partial-JSON recovery for finish_reason=length: small models
                            # (0.8B) repeat list items until the token limit is hit,
                            # truncating mid-array. Since canonical_name / ticker / isin
                            # always appear before the aliases array, strip the incomplete
                            # aliases tail and inject [] so the core fields are preserved.
                            recovered: dict[str, object] | None = None
                            if finish_reason == "length":
                                stripped = re.sub(
                                    r',\s*"aliases"\s*:.*$',
                                    "",
                                    cleaned,
                                    flags=re.DOTALL,
                                )
                                try:
                                    _r: dict[str, object] = json.loads(stripped + "}")
                                    _r.setdefault("aliases", [])
                                    recovered = _r
                                    logger.warning(
                                        "deepseek_extraction_aliases_truncated_recovered",
                                        model_id=self._model_id,
                                        finish_reason=finish_reason,
                                    )
                                except json.JSONDecodeError:
                                    pass
                            if recovered is not None:
                                result = recovered
                            else:
                                # Surface the raw response prefix so the next
                                # regression of this class is debuggable.
                                logger.warning(
                                    "deepseek_extraction_malformed",
                                    model_id=self._model_id,
                                    raw_response_prefix=raw_response[:500],
                                    raw_response_len=len(raw_response),
                                    finish_reason=finish_reason,
                                )
                                raise FatalError(f"malformed extraction output: {exc}") from exc
                    return ExtractionOutput(
                        result=result,
                        raw_response=raw_response,
                        # model_id stays the CONFIGURED primary for backward compat
                        # (existing readers key off it); model_used carries the
                        # ACTUAL serving model for the Task #36 audit.
                        model_id=self._model_id,
                        model_used=model_used,
                        fallback_reason=fallback_reason,
                        attempts=attempts,
                        # PLAN-0117 FR-1: surface the verbatim DeepInfra cost so
                        # downstream usage-log writers (KG fallback chain, S6
                        # deep-extraction) can stamp cost_source="provider".
                        provider_cost_usd=provider_cost_usd,
                    )
                except (RetryableError, FatalError):
                    # Transient/4xx classification (and exhausted-retry) is done by
                    # _create_with_retry; JSON-parse failures raise FatalError above.
                    # Both already carry the correct retry semantics — just propagate.
                    raise
                except Exception as exc:
                    raise FatalError(f"Unexpected DeepSeek error: {exc}") from exc
        except (RetryableError, FatalError):
            status = "error"
            raise
        finally:
            if self._metrics:
                latency = time.perf_counter() - start
                # Label metrics with the ACTUAL serving model (Task #36): on a
                # fallback hop the cost/latency/token counters attribute to the
                # secondary model so dashboards show the real per-model spend.
                self._metrics.ml_api_requests_total.labels(
                    model_id=model_used, operation="extract", status=status
                ).inc()
                self._metrics.ml_api_latency_seconds.labels(model_id=model_used, operation="extract").observe(latency)
                self._metrics.ml_api_tokens_in_total.labels(model_id=model_used).inc(tokens_in)
                self._metrics.ml_api_tokens_out_total.labels(model_id=model_used).inc(tokens_out)

                # PLAN-0117 FR-1: prefer the provider-reported cost (authoritative)
                # over the price-matrix estimate; only fall back to the matrix when
                # DeepInfra did not report a cost. Never a silent $0 for a paid model.
                if provider_cost_usd is not None:
                    cost = float(provider_cost_usd)
                else:
                    from ml_clients.cost import estimate_cost  # local import avoids circular dep

                    cost = estimate_cost("deepinfra", model_used, tokens_in, tokens_out)
                self._metrics.ml_api_estimated_cost_usd_total.labels(model_id=model_used).inc(cost)
