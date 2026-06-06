"""Layer 2 LLM-based semantic injection classifier (E-8).

This runs AFTER Layer 1 (InputValidator regex + PII checks) passes. It calls a
small LLM to semantically classify whether the user message is a jailbreak
attempt, privilege escalation, prompt injection, or data exfiltration attempt.

Fail-closed design: any error (timeout, parse error, network, API error) causes
the classifier to return True (UNSAFE) and log a warning. This is intentional —
a transient LLM error is far less costly than allowing an injection through.

When the API key is not configured the classifier is disabled (returns False =
SAFE) and logs a warning. Operators should configure INJECTION_CLASSIFIER_MODEL
and RAG_CHAT_DEEPINFRA_API_KEY for production deployments.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from typing import TYPE_CHECKING

import structlog
from prompts.chat.safety_classifier import INJECTION_SAFETY_CLASSIFIER

from rag_chat.application.metrics.prometheus import rag_injection_classifier_indeterminate

if TYPE_CHECKING:
    from rag_chat.application.ports.cost_recorder import CostRecorder

log = structlog.get_logger(__name__)  # type: ignore[no-any-return]

# WHY this regex: some models (especially smaller ones) wrap JSON in extra
# prose like "Here is the classification: {\"label\": \"SAFE\", ...}". We
# extract the first balanced JSON object found in the response, which is
# strictly more robust than json.loads() on the whole string. Anchored to
# the OUTERMOST braces to avoid accidentally matching a nested object.
_JSON_OBJECT_RE = re.compile(r"\{[^{}]*\}", re.DOTALL)

# WHY this regex: when JSON extraction fails entirely (e.g. model returned
# only "SAFE" or "label: SAFE"), we look for the bare label keyword as a
# last-resort parse. Anchored to a word boundary so "UNSAFE" inside a
# longer word does not match. Case-insensitive to match LLM casing drift.
_BARE_LABEL_RE = re.compile(r"\b(SAFE|UNSAFE)\b", re.IGNORECASE)

# Default model for semantic injection classification. Chosen for low latency
# (~200-500ms on DeepInfra GPU) and low cost ($0.0001/M tokens for 0.8B param).
# Can be overridden via INJECTION_CLASSIFIER_MODEL env var.
_DEFAULT_CLASSIFIER_MODEL = "meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo"

# Version stamp for the classifier system prompt. Downstream caches (P2 W4
# T-W4-02 on-disk classifier-result cache) include this in the cache key so
# a prompt change invalidates stale verdicts.
#
# Format: "vN" — preserved verbatim for backwards-compatible cache keys.
# Phase 2B (2026-06-05): the canonical prompt body now lives in
# ``libs.prompts.chat.safety_classifier.INJECTION_SAFETY_CLASSIFIER`` (semver
# version "4.0"). We derive the legacy "vN" string from that template's
# semver MAJOR component so the two can never drift — bump the template
# version and this constant flips with it.
#
# Lineage:
#   v2 — FIX-LIVE-CC conditional-reasoning rewrite (2026-05-25)
#   v3 — PLAN-0097 W2 T-W2-01: relationship-discovery SAFE exemplar
#   v4 — PLAN-0103 W13 / BP-632: financial-screener SAFE exemplar
CLASSIFIER_PROMPT_VERSION = f"v{INJECTION_SAFETY_CLASSIFIER.version.split('.', 1)[0]}"

# System prompt for the classifier. Body lives in libs/prompts so it is
# content-addressable and reusable; render() collapses the doubled JSON
# braces (``{{ }}``) back to single braces so the LLM receives valid JSON
# syntax in the example line. The template has no parameters so render()
# is a pure brace-unescape pass.
_SYSTEM_PROMPT = INJECTION_SAFETY_CLASSIFIER.render()

# Timeout for the LLM call. 10 seconds is generous for a 0.8B model on GPU;
# any longer and the classifier becomes a latency bottleneck for every request.
_CLASSIFY_TIMEOUT_S = 10.0

# DeepInfra chat completions endpoint.
_DEEPINFRA_BASE_URL = "https://api.deepinfra.com/v1/openai"


class LLMInjectionClassifier:
    """Semantic injection classifier using a small LLM on DeepInfra.

    Usage::
        classifier = LLMInjectionClassifier(api_key="...", model="...")
        is_unsafe = await classifier.classify(user_message)
        if is_unsafe:
            raise PromptInjectionError("Semantic injection detected")

    Fail-closed: any exception → returns True (UNSAFE).
    No API key → returns False (disabled path) with warning logged.
    """

    def __init__(
        self,
        api_key: str | None,
        model: str | None = None,
        base_url: str = _DEEPINFRA_BASE_URL,
        *,
        cost_recorder: CostRecorder | None = None,
    ) -> None:
        # WHY store raw string (not SecretStr): this class lives in the application
        # layer; SecretStr is a pydantic infrastructure concern. The caller
        # (app.py DI wiring) extracts the raw value before passing it here.
        self._api_key = api_key or ""
        self._model = model or os.environ.get("INJECTION_CLASSIFIER_MODEL", _DEFAULT_CLASSIFIER_MODEL)
        self._base_url = base_url.rstrip("/")
        # PLAN-0107 follow-up: per-call USD cost recorder. Optional —
        # ``None`` preserves the pre-PLAN-0107 behaviour (no cost emit).
        # Production wiring in app.py injects ``app.state.cost_recorder``.
        self._cost_recorder = cost_recorder

    async def classify(self, message: str) -> bool:
        """Classify *message* for injection risk.

        Returns:
            True  — UNSAFE (injection detected or classifier error)
            False — SAFE (message passed semantic check, or classifier disabled)

        This method NEVER raises — all exceptions are caught and cause a
        fail-closed True return.
        """
        # ── PLAN-0097 W2 T-W2-04 / W3 fold: DEBUG_SKIP_CLASSIFIER short-circuit ─
        # Eval harness needs a deterministic way to bypass the Layer 2 LLM
        # call so chat-eval runs are not flaky against DeepInfra non-determinism
        # (the entire reason BP-579 / Q8 INPUT_REJECTED exists). The env-var
        # MUST be a no-op in production: gate the read on `APP_ENV != "production"`
        # so a leaked DEBUG_SKIP_CLASSIFIER=true in a prod environment cannot
        # disable Layer 2. Production deployments set APP_ENV=production via
        # the global lifespan assertion (BP-567); dev/test/eval default to
        # 'development' or 'test'.
        _app_env = os.environ.get("APP_ENV", "development")
        _skip_flag = os.environ.get("DEBUG_SKIP_CLASSIFIER", "").lower()
        if _app_env != "production" and _skip_flag in ("1", "true", "yes"):
            log.info(  # type: ignore[no-any-return]
                "debug_classifier_skipped",
                reason="DEBUG_SKIP_CLASSIFIER env-var set",
                app_env=_app_env,
            )
            return False

        # ── Layer 2 disabled path ──────────────────────────────────────────────
        if not self._api_key:
            log.warning(  # type: ignore[no-any-return]
                "llm_injection_classifier_disabled",
                reason="no_api_key",
                hint="Set RAG_CHAT_DEEPINFRA_API_KEY to enable Layer 2 semantic injection check",
            )
            return False  # disabled → treat as SAFE

        # ── LLM classification with asyncio timeout ────────────────────────────
        # WHY timeout is fail-open (not fail-closed): DeepInfra latency for the
        # classifier model occasionally exceeds 10s under load. Fail-closing on
        # timeout blocks ALL user queries whenever the model is slow — that cost
        # is higher than the marginal security risk of letting one timed-out
        # request through Layer 2 (Layer 1 regex still ran). Parse/API errors
        # remain fail-closed because they may indicate a compromised response.
        try:
            result = await asyncio.wait_for(
                self._call_llm(message),
                timeout=_CLASSIFY_TIMEOUT_S,
            )
            return result
        except TimeoutError:
            log.warning(  # type: ignore[no-any-return]
                "llm_injection_classifier_timeout_safe",
                reason="timeout",
                timeout_s=_CLASSIFY_TIMEOUT_S,
            )
            return False  # fail-open on timeout — Layer 1 already ran
        except Exception as exc:
            log.warning(  # type: ignore[no-any-return]
                "llm_injection_classifier_fail_closed",
                reason="exception",
                error=str(exc),
            )
            return True  # fail-closed on unexpected errors

    async def _call_llm(self, message: str) -> bool:
        """Make the DeepInfra API call and parse the JSON response.

        Returns True if the model labels the message UNSAFE, False if SAFE.
        Raises on any API error or parse failure (caller wraps in try/except).
        """
        import httpx

        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": message},
            ],
            # Max tokens: 64 is more than enough for {"label":"UNSAFE","reason":"..."}.
            # Keeping it small reduces latency and cost.
            "max_tokens": 64,
            "temperature": 0.0,  # deterministic classification
            # NEW-016: Qwen3 family is a reasoning model on DeepInfra. Without this
            # flag, chain-of-thought consumes the entire max_tokens budget and
            # message.content returns empty → unexpected_label → fail-closed →
            # 100% block rate on cache-cold paths (PLAN-0104 W52 regression).
            # Honoured by Qwen3.x via vLLM's chat_template_kwargs passthrough;
            # silently ignored by non-Qwen models, so safe to send unconditionally.
            "chat_template_kwargs": {"enable_thinking": False},
        }

        async with httpx.AsyncClient(
            base_url=self._base_url,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            # httpx default is 5s; we rely on asyncio.wait_for for the outer
            # timeout but also set a reasonable inner timeout so httpx does not
            # hang indefinitely if the server accepts the connection but stalls.
            timeout=httpx.Timeout(15.0),
        ) as client:
            response = await client.post("/chat/completions", json=payload)
            response.raise_for_status()

        data = response.json()

        # PLAN-0107 follow-up: per-call USD cost emit. Done BEFORE any parse
        # work so a downstream parse failure still records the API call we
        # paid for. ``thread_id=None`` because the safety classifier runs
        # before any thread context is bound (it gates the user message
        # at the front door). Tokens are sourced from the DeepInfra usage
        # block; defensive defaults of 0 cover the case where the provider
        # omits the field (treated as a failed billable call → $0).
        if self._cost_recorder is not None:
            try:
                _usage = data.get("usage") or {}
                _tokens_in = int(_usage.get("prompt_tokens", 0) or 0)
                _tokens_out = int(_usage.get("completion_tokens", 0) or 0)
                # Fire-and-forget — schedule on the running loop so we don't
                # block the safety verdict on a DB round-trip. The recorder
                # itself never raises (production impl is defensive), but we
                # still wrap create_task in try/except as a second guard
                # against synchronous construction errors.
                asyncio.create_task(  # noqa: RUF006
                    self._cost_recorder.record(
                        thread_id=None,
                        model_id=self._model,  # type: ignore[arg-type]
                        tokens_in=_tokens_in,
                        tokens_out=_tokens_out,
                        call_site="safety_classifier",
                    )
                )
            except Exception as exc:  # pragma: no cover — defence in depth
                log.warning(  # type: ignore[no-any-return]
                    "safety_classifier_cost_recorder_failed",
                    model=self._model,
                    error=str(exc),
                )

        message_obj = data["choices"][0]["message"]
        content = message_obj.get("content") or ""

        # NEW-016 defensive guard: if content is empty but the model emitted
        # reasoning_content (DeepInfra reasoning-model convention), the
        # max_tokens budget was eaten by chain-of-thought. Layer 1 already ran,
        # so fail-open with a metric instead of blocking legitimate users.
        # This catches the case where a future model swap re-enables thinking
        # despite the enable_thinking=False payload flag (silent ignore by
        # the model provider).
        if not content.strip() and message_obj.get("reasoning_content"):
            log.warning(  # type: ignore[no-any-return]
                "llm_injection_classifier_indeterminate",
                reason="empty_content_with_reasoning",
                reasoning_preview=str(message_obj.get("reasoning_content"))[:200],
            )
            rag_injection_classifier_indeterminate.inc()
            return False  # fail-open — Layer 1 already gated the message

        # The model may wrap JSON in ```json ... ``` markdown fences — strip them.
        content = content.strip()
        if content.startswith("```"):
            # Remove the opening fence (```json or ```) and closing fence (```)
            content = content.split("```", 2)[-1] if content.count("```") >= 2 else content
            # Handle ``` json { ... } ``` → strip trailing ```
            if content.endswith("```"):
                content = content[: content.rfind("```")].strip()
            # Remove optional "json" language tag on the first line
            lines = content.splitlines()
            if lines and lines[0].strip().lower() == "json":
                content = "\n".join(lines[1:]).strip()

        label = _extract_label(content)

        if label not in ("SAFE", "UNSAFE"):
            # Unexpected label — fail-closed to be safe.
            log.warning(  # type: ignore[no-any-return]
                "llm_injection_classifier_unexpected_label",
                label=label,
                raw_content=content[:200],
                # Drift detection: stamps the exact safety prompt this call
                # used (name@version#hash) so dashboards can correlate
                # unexpected-label rate with prompt rollouts.
                safety_classifier_prompt=INJECTION_SAFETY_CLASSIFIER.identifier(),
            )
            return True  # fail-closed on unexpected output

        return label == "UNSAFE"


def _extract_label(content: str) -> str:
    """Extract the SAFE / UNSAFE label from the LLM response.

    Tries three strategies in order:
      1. json.loads(content)               — strict JSON path (best).
      2. regex-match first {...} object    — JSON wrapped in extra prose.
      3. bare-word \bSAFE\b / \bUNSAFE\b   — last-resort label keyword.

    Returns the uppercase label string ("SAFE" or "UNSAFE") on success, or
    the empty string when no label can be parsed (caller treats as
    fail-closed unexpected-label).

    WHY this exists: smaller classifier models sometimes emit JSON wrapped
    in extra commentary ("Here is my classification: {...}"), or drop the
    JSON entirely and emit "Label: SAFE — the question is benign." The
    strict-only parse rejected those even when the intent was unambiguous,
    causing latency-friendly fail-closed UNSAFE on legitimate queries.
    """
    # Strategy 1: strict JSON parse.
    try:
        parsed = json.loads(content)
        label = str(parsed.get("label", "")).strip().upper()
        if label in ("SAFE", "UNSAFE"):
            return label
    except (json.JSONDecodeError, AttributeError):
        pass

    # Strategy 2: regex-extract the first {...} block and try JSON again.
    match = _JSON_OBJECT_RE.search(content)
    if match:
        try:
            parsed = json.loads(match.group(0))
            label = str(parsed.get("label", "")).strip().upper()
            if label in ("SAFE", "UNSAFE"):
                return label
        except (json.JSONDecodeError, AttributeError):
            pass

    # Strategy 3: bare-keyword search.
    bare = _BARE_LABEL_RE.search(content)
    if bare:
        return bare.group(1).upper()

    return ""


__all__ = ["CLASSIFIER_PROMPT_VERSION", "LLMInjectionClassifier"]
