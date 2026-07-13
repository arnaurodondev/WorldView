"""DeepInfra description adapter — entity description generation via OpenAI-compatible endpoint.

Primary model : Qwen/Qwen3-235B-A22B-Instruct-2507
Fallback model: Qwen/Qwen3-32B

Both Qwen3 models can emit <think>…</think> reasoning blocks; the adapter strips
these before returning the plain-text description.

Cost cap: same atomic Valkey INCRBYFLOAT-then-check pattern as GeminiDescriptionAdapter
(G-005 fix). The monthly budget key is shared with the gemini adapter key prefix so
the combined description spend is tracked under one counter.
"""

from __future__ import annotations

import re
import time
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

import structlog

from ml_clients.errors import FatalError
from ml_clients.pricing import provider_cost_to_decimal

if TYPE_CHECKING:
    import asyncio

    from ml_clients.description_client import CostTrackerProtocol
    from ml_clients.usage_log import LlmUsageLogProtocol

logger = structlog.get_logger()

_DEFAULT_PRIMARY_MODEL_ID = "Qwen/Qwen3-235B-A22B-Instruct-2507"
_DEFAULT_FALLBACK_MODEL_ID = "Qwen/Qwen3-32B"
_DEFAULT_BASE_URL = "https://api.deepinfra.com/v1/openai"
_DEFAULT_MAX_MONTHLY_USD = 10.0
_DEFAULT_TIMEOUT_S = 60.0  # description calls are simpler than extraction; 60 s is generous

# Monthly cost key in Valkey (shared namespace with gemini adapter)
_COST_KEY_PREFIX = "s7:desc:cost"

# Default estimated output tokens for pre-call cost reservation
_DEFAULT_ESTIMATED_OUTPUT_TOKENS = 120

# Regex to strip Qwen3 / DeepSeek thinking blocks
_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)

# PRD-0073 §12 (F-SEC-02 / F-S01 / F-A05): sanitize entity name before prompt insertion.
# Mirrors ``prompts.knowledge.entity_enrichment.sanitize_entity_name`` (kept inline to
# avoid adding ``prompts`` as an ml-clients runtime dependency). Strips ASCII control
# characters (\x00-\x1f), DEL (\x7f), and angle brackets (< >) so a malicious
# ``canonical_name`` cannot close the surrounding ``<entity>`` delimiter or break out
# with ``\n\nIgnore previous instructions``-style payloads.
_NAME_CONTROL_CHAR_RE = re.compile(r"[\x00-\x1f\x7f<>]")
_NAME_MAX_LEN = 200  # matches sanitize_entity_name cap

# News-grounding (PRD description audit 2026-06-17): cap on each evidence snippet
# and the number of snippets injected into the prompt. The live A/B showed 3
# snippets is enough to anchor the description in real facts; more just bloats
# the prompt (and the KV-cache miss) without measurable fabrication gain.
_NEWS_SNIPPET_MAX_LEN = 300
_NEWS_MAX_SNIPPETS = 3


def _sanitize_entity_name(name: str) -> str:
    """Strip control chars + angle brackets and cap at 200 chars (PRD-0073 §12)."""
    return _NAME_CONTROL_CHAR_RE.sub("", name)[:_NAME_MAX_LEN]


def _build_news_block(news_context: list[str] | None) -> str:
    """Render the news-grounding block appended to the user turn.

    When ``news_context`` carries snippets we inject up to ``_NEWS_MAX_SNIPPETS``
    of them so the model paraphrases real facts instead of fabricating. Each
    snippet is *untrusted* (it comes from upstream news extraction →
    ``relation_evidence_raw.evidence_text``) so it is sanitized with the same
    ``_NAME_CONTROL_CHAR_RE`` used for the entity name (strips control chars +
    angle brackets so a malicious snippet can't break out of the data block or
    inject ``Ignore previous instructions``-style payloads) and truncated to
    ``_NEWS_SNIPPET_MAX_LEN`` chars.

    When ``news_context`` is None/empty we inject the no-news guard instead: the
    live A/B (2026-06-17) showed 78% of obscure entities have no corroborating
    news, and confidently fabricating biographies for them is the single worst
    KG-quality failure — so the guard is a first-class branch, not an afterthought.
    """
    snippets = [s for s in (news_context or []) if s and s.strip()]
    if not snippets:
        return (
            "\n\n## No corroborating news found. If you are not independently certain of "
            "specific facts about this entity, describe only its general category and type — "
            "do not invent roles, titles, affiliations, or biographical detail."
        )
    lines = [
        "\n\n## Recent news context (ground your description in these facts; state nothing they do not support):",
    ]
    for snippet in snippets[:_NEWS_MAX_SNIPPETS]:
        safe = _NAME_CONTROL_CHAR_RE.sub("", snippet)[:_NEWS_SNIPPET_MAX_LEN]
        lines.append(f"- {safe}")
    return "\n".join(lines)


# System prompt — static across all calls so DeepInfra can KV-cache it.
# Structured as: role → output format → anti-hallucination rules → examples.
# Examples follow the EODHD company-description style (factual, present-tense,
# 2-3 sentences) so the model produces consistent output for both ticker and
# non-ticker entities.
_SYSTEM_PROMPT = """\
You are a financial knowledge-base writer for a professional market intelligence platform.

## Task
Write a concise, factual 2-3 sentence description of a financial or economic entity.

## Output format
- Plain text only — no markdown, no JSON, no bullet points, no headers
- Exactly 2-3 sentences; do not pad or truncate
- Present tense for ongoing entities; past tense only for dissolved ones

## Anti-hallucination rules
- State only well-established, publicly verifiable facts
- Never invent specific figures: stock prices, market-cap numbers, P/E ratios, revenue, headcount
- Never fabricate founding dates, executive names, or addresses you are not certain about
- Do not describe recent events, earnings reports, or price movements
- Do not confuse similarly-named entities (e.g. "Alphabet Inc." ≠ "Google LLC")
- For obscure or ambiguous entities, describe the general category rather than guessing specifics
- For people, describe only their known public role; never speculate on personal history

## Examples

### Company with ticker (follow the EODHD description style exactly)
Input: Apple Inc. (entity_type: company; ticker: AAPL; exchange: NASDAQ)
Output: Apple Inc. designs, manufactures, and markets smartphones, personal computers, tablets, \
wearables, and accessories worldwide, and also provides AppleCare support, cloud services, and \
operates platforms including the App Store, Apple Music, Apple TV+, and Apple Pay. The company, \
headquartered in Cupertino, California, serves consumers, small and mid-sized businesses, and \
education, enterprise, and government customers across its iPhone, Mac, iPad, Wearables, and \
Services segments. Apple is a constituent of major indices such as the S&P 500 and NASDAQ-100 \
and is consistently ranked among the world's most valuable companies by market capitalisation.

### Currency (non-ticker entity)
Input: Euro (entity_type: currency)
Output: The euro (EUR) is the official currency of the eurozone, used by 20 of the 27 European \
Union member states, and is governed by the European Central Bank. It is the second most traded \
currency in global foreign exchange markets and serves as a major international reserve currency \
alongside the US dollar. The euro was introduced in 1999 as a cashless accounting currency and \
entered physical circulation as banknotes and coins in 2002.

### Financial regulator / government body
Input: U.S. Securities and Exchange Commission (entity_type: regulatory_body)
Output: The U.S. Securities and Exchange Commission (SEC) is an independent federal agency \
responsible for enforcing federal securities laws, regulating securities markets, and protecting \
investors. Established by the Securities Exchange Act of 1934, it oversees stock exchanges, \
broker-dealers, investment advisers, and public company reporting. The SEC's core mandate is to \
maintain fair, orderly, and efficient capital markets.

### Person
Input: Warren Buffett (entity_type: person)
Output: Warren Buffett is an American investor and business magnate who serves as Chairman and \
Chief Executive Officer of Berkshire Hathaway, the diversified holding company he has led since \
1965. He is widely regarded as one of the most successful investors in history, known for his \
value-investing philosophy and long-term approach to capital allocation. Buffett is also a \
prominent philanthropist, having pledged the majority of his wealth to charitable foundations.\
"""


def _month_key() -> str:
    now = datetime.now(tz=UTC)
    return f"{_COST_KEY_PREFIX}:{now.strftime('%Y-%m')}"


def _estimate_cost_local(model_id: str, tokens_in: int, tokens_out: int) -> float:
    """Local cost estimation (avoids circular import with cost.py)."""
    from ml_clients.cost import estimate_cost

    return estimate_cost("deepinfra", model_id, tokens_in, tokens_out)


def _strip_think_blocks(text: str) -> str:
    """Remove Qwen3 <think>…</think> reasoning blocks from the output."""
    return _THINK_RE.sub("", text).strip()


class DeepInfraDescriptionAdapter:
    """Generates entity descriptions via DeepInfra (Qwen3-235B-A22B primary, Qwen3-32B fallback).

    Args:
    ----
        api_key:          DeepInfra API key.
        primary_model_id: Primary model (default: Qwen/Qwen3-235B-A22B-Instruct-2507).
        fallback_model_id: Fallback model (default: Qwen/Qwen3-32B).
        base_url:         OpenAI-compatible base URL (default: DeepInfra).
        semaphore:        Concurrency limiter (keyword-only, required).
        cost_tracker:     Valkey client for monthly cost cap (optional; fail-open when None).
        max_monthly_usd:  Monthly spend cap in USD (default: $10.0).
        usage_logger:     Optional LLM usage logger (fire-and-forget).
        timeout_s:        Per-request HTTP timeout in seconds (default: 60).

    """

    def __init__(
        self,
        api_key: str,
        primary_model_id: str = _DEFAULT_PRIMARY_MODEL_ID,
        fallback_model_id: str = _DEFAULT_FALLBACK_MODEL_ID,
        base_url: str = _DEFAULT_BASE_URL,
        *,
        semaphore: asyncio.Semaphore,
        cost_tracker: CostTrackerProtocol | None = None,
        max_monthly_usd: float = _DEFAULT_MAX_MONTHLY_USD,
        usage_logger: LlmUsageLogProtocol | None = None,
        timeout_s: float = _DEFAULT_TIMEOUT_S,
    ) -> None:
        try:
            import openai as _openai
        except ImportError as exc:
            raise FatalError("openai package not installed; install ml-clients[openai]") from exc

        self._primary_model_id = primary_model_id
        self._fallback_model_id = fallback_model_id
        self._semaphore = semaphore
        self._cost_tracker = cost_tracker
        self._max_monthly_usd = max_monthly_usd
        self._usage_logger = usage_logger
        self._openai = _openai
        # Persistent client enables connection pool reuse and DeepInfra KV prefix caching.
        self._client = _openai.AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=_openai.Timeout(connect=5.0, read=timeout_s, write=30.0, pool=5.0),
        )

    async def aclose(self) -> None:
        await self._client.close()

    async def generate_description(
        self,
        entity_id: str,
        canonical_name: str,
        entity_type: str,
        context_hints: dict[str, str],
        news_context: list[str] | None = None,
    ) -> str | None:
        """Generate a world-knowledge description using Qwen3 via DeepInfra.

        Tries the primary model first; falls back to the secondary model on any error.
        Returns None (without calling the API) when the monthly cost cap is exceeded.

        ``news_context`` (optional): recent news snippets about this entity. When
        present they are injected as a grounding block so the model paraphrases
        real facts; when absent a no-news guard tells the model to stay generic.
        """
        prompt = _build_prompt(canonical_name, entity_type, context_hints, news_context)

        # Atomic cost-cap reserve before any API call
        reserved, estimated_cost = await self._reserve_cost(prompt)
        if not reserved:
            logger.warning(
                "deepinfra_description_cost_cap_exceeded",
                entity_id=entity_id,
                max_monthly_usd=self._max_monthly_usd,
            )
            return None

        # Try primary, then fallback
        for model_id in (self._primary_model_id, self._fallback_model_id):
            result = await self._call_model(model_id, prompt, entity_id, entity_type)
            if result is not None:
                # result = (text, tokens_in, tokens_out, provider_cost_usd)
                await self._adjust_cost(estimated_cost, model_id, result[1], result[2], result[3])
                return result[0]

        # Both models failed — undo reservation
        await self._undo_reservation(estimated_cost)
        return None

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _call_model(
        self,
        model_id: str,
        prompt: str,
        entity_id: str,
        entity_type: str,
    ) -> tuple[str, int, int, Decimal | None] | None:
        """Call one model; return (text, tokens_in, tokens_out, provider_cost) or None.

        PLAN-0117 FR-1: the 4th tuple element is the verbatim DeepInfra
        ``usage.estimated_cost`` (``Decimal``) when reported, else ``None``.
        """
        start = time.perf_counter()
        status = "success"
        tokens_in = 0
        tokens_out = 0
        provider_cost_usd: Decimal | None = None
        try:
            async with self._semaphore:
                response = await self._client.chat.completions.create(
                    model=model_id,
                    messages=[
                        {"role": "system", "content": _SYSTEM_PROMPT},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.3,
                    max_tokens=256,
                    # prompt_cache_key: hint for DeepInfra server-side KV prefix caching.
                    # Do NOT add reasoning_effort=none here — Qwen3 models return '\n'
                    # (empty) with that flag set, causing silent fallback to Qwen3-32B
                    # which also produces malformed word-per-line output (BP-339).
                    extra_body={"prompt_cache_key": "entity_description_v1"},
                )
                raw: str = response.choices[0].message.content or ""
                if response.usage is not None:
                    tokens_in = response.usage.prompt_tokens or 0
                    tokens_out = response.usage.completion_tokens or 0
                    # PLAN-0117 FR-1: capture provider cost verbatim (best-effort).
                    provider_cost_usd = provider_cost_to_decimal(getattr(response.usage, "estimated_cost", None))

                description = _strip_think_blocks(raw)
                if not description:
                    logger.warning(
                        "deepinfra_description_empty",
                        entity_id=entity_id,
                        model_id=model_id,
                    )
                    return None

                logger.info(
                    "deepinfra_description_generated",
                    entity_id=entity_id,
                    entity_type=entity_type,
                    model_id=model_id,
                )
                return description, tokens_in, tokens_out, provider_cost_usd

        except (self._openai.RateLimitError, self._openai.APIConnectionError, self._openai.APITimeoutError) as exc:
            status = "error"
            logger.warning("deepinfra_description_retryable", model_id=model_id, error=str(exc))
            return None
        except self._openai.APIStatusError as exc:
            status = "error"
            logger.warning("deepinfra_description_api_error", model_id=model_id, status_code=exc.status_code)
            return None
        except Exception as exc:
            status = "error"
            logger.warning("deepinfra_description_unexpected", model_id=model_id, error=str(exc))
            return None
        finally:
            if status == "error" and self._usage_logger is not None:
                import asyncio as _asyncio

                _asyncio.create_task(  # noqa: RUF006
                    self._usage_logger.log(
                        model_id=model_id,
                        provider="deepinfra",
                        capability="description",
                        tokens_in=0,
                        tokens_out=0,
                        latency_ms=int((time.perf_counter() - start) * 1000),
                        estimated_cost_usd=0.0,
                        success=False,
                        error_code="model_error",
                    ),
                )

    async def _reserve_cost(self, prompt: str) -> tuple[bool, float]:
        if self._cost_tracker is None:
            return True, 0.0
        estimated = _estimate_cost_local(
            self._primary_model_id,
            len(prompt) // 4,
            _DEFAULT_ESTIMATED_OUTPUT_TOKENS,
        )
        if estimated == 0.0:
            # Model pricing not in cost.py yet — allow call, don't track
            return True, 0.0
        key = _month_key()
        cap_threshold = self._max_monthly_usd * 0.95
        try:
            new_total = await self._cost_tracker.incrbyfloat(key, estimated)
            if new_total >= cap_threshold:
                await self._cost_tracker.incrbyfloat(key, -estimated)
                return False, estimated
            return True, estimated
        except Exception as exc:
            logger.warning("deepinfra_desc_cost_reserve_failed", error=str(exc))
            return True, 0.0

    async def _adjust_cost(
        self,
        estimated: float,
        model_id: str,
        tokens_in: int,
        tokens_out: int,
        provider_cost_usd: Decimal | None = None,
    ) -> None:
        # PLAN-0117 FR-1/FR-2: prefer the provider-reported cost (authoritative)
        # over the price-matrix estimate; stamp provenance so a paid model is never
        # a silent $0. Matrix fallback only when DeepInfra omitted the cost.
        if provider_cost_usd is not None:
            actual = float(provider_cost_usd)
            cost_source = "provider"
        else:
            actual = _estimate_cost_local(model_id, tokens_in, tokens_out)
            cost_source = "pricematrix"
        if self._usage_logger is not None:
            import asyncio as _asyncio

            _asyncio.create_task(  # noqa: RUF006
                self._usage_logger.log(
                    model_id=model_id,
                    provider="deepinfra",
                    capability="description",
                    tokens_in=tokens_in,
                    tokens_out=tokens_out,
                    latency_ms=0,
                    estimated_cost_usd=actual,
                    success=True,
                    cost_source=cost_source,
                ),
            )
        if self._cost_tracker is None or estimated == 0.0:
            return
        delta = actual - estimated
        if abs(delta) < 0.000001:
            return
        try:
            await self._cost_tracker.incrbyfloat(_month_key(), delta)
        except Exception as exc:
            logger.warning("deepinfra_desc_cost_adjust_failed", error=str(exc))

    async def _undo_reservation(self, estimated_cost: float) -> None:
        if self._cost_tracker is None or estimated_cost == 0.0:
            return
        try:
            await self._cost_tracker.incrbyfloat(_month_key(), -estimated_cost)
        except Exception as exc:
            logger.warning("deepinfra_desc_cost_undo_failed", error=str(exc))


def _build_prompt(
    canonical_name: str,
    entity_type: str,
    context_hints: dict[str, str],
    news_context: list[str] | None = None,
) -> str:
    """Build the user-turn entity request. The system prompt supplies task + examples.

    PRD-0073 §12 (F-SEC-02 / F-S01 / F-A05): the ``canonical_name`` originates from
    upstream extraction (EODHD scrapes / NLP pipeline) and is therefore untrusted.
    We strip control characters + angle brackets via ``_sanitize_entity_name`` and
    wrap the result in ``<entity>...</entity>`` delimiters so the LLM treats the
    contents as data rather than instructions. ``entity_type`` is constrained to a
    fixed enum upstream but is also length-capped defensively. Context-hint values
    are length-capped per key/value to bound prompt size.

    ``news_context`` (optional): when supplied, ``_build_news_block`` appends a
    grounding block of sanitized recent-news snippets; when None/empty it appends
    the no-news guard. The base line stays first so the static portion of the user
    turn is stable. (The system prompt itself is never mutated — keeping it static
    preserves DeepInfra's server-side KV-cache.)
    """
    safe_name = _sanitize_entity_name(canonical_name)
    safe_type = entity_type[:64]
    # Append context hints inline so the model has ticker/exchange/ISIN when available.
    hints_str = "; ".join(f"{k[:64]}: {str(v)[:256]}" for k, v in context_hints.items()) if context_hints else ""
    context_part = f"; {hints_str}" if hints_str else ""
    # Wrap the (untrusted) name in <entity> delimiters per PRD-0073 §12.
    base = f"Write a description for: <entity>{safe_name}</entity> (entity_type: {safe_type}{context_part})"
    return base + _build_news_block(news_context)
