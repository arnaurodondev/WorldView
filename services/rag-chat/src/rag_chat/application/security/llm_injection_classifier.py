"""Layer 2 LLM-based semantic injection classifier (E-8).

This runs AFTER Layer 1 (InputValidator regex + PII checks) passes. It calls a
small LLM to semantically classify whether the user message is a jailbreak
attempt, privilege escalation, prompt injection, or data exfiltration attempt.

Verdict semantics (two distinct failure classes — do NOT conflate them):

* The classifier RAN and produced a verdict → ``classify()`` returns
  ``True`` (UNSAFE / injection) or ``False`` (SAFE). Genuine PARSE failures and
  unexpected labels (the model answered, but with garbage) remain fail-closed
  as ``True`` — a corrupt classifier *response* is treated as a possible
  injection signal.

* The classifier could NOT RUN because its provider was unavailable or the
  transport failed (HTTP 402/429/5xx, connect error, network error). This is
  raised as ``ClassifierUnavailableError`` — NEVER mislabelled as injection.
  The API layer maps it to a distinct ``CLASSIFIER_UNAVAILABLE`` error ("input
  safety check temporarily unavailable, please retry"), not "Semantic injection
  detected". Default policy is still fail-closed (reject), but HONEST. Set
  ``RAG_CHAT_CLASSIFIER_FAIL_OPEN=true`` to fail open during an incident; we
  NEVER default to fail-open (that would let injections through during an
  outage).

WHY this design (the bug it fixes): the old code caught EVERY exception and
returned ``True`` (UNSAFE). A DeepInfra ``402 Payment Required`` billing blip
therefore rejected EVERY chat request as ``[PROMPT_INJECTION] Semantic injection
detected`` — a misleading message that hid a billing/outage incident behind a
fake security signal.

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

from rag_chat.application.metrics.prometheus import (
    rag_injection_classifier_indeterminate,
    rag_injection_classifier_unavailable,
)
from rag_chat.domain.errors import ClassifierUnavailableError

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


class _ClassifierTransportError(Exception):
    """Internal sentinel: the classifier provider was unavailable / transport failed.

    Raised inside ``_call_llm`` for HTTP status errors (402/429/5xx and any other
    non-2xx) and connect/network errors. ``classify()`` catches it to apply the
    fail-open/closed policy and surface ``ClassifierUnavailableError`` to the
    caller — distinct from a genuine injection verdict.

    Carries a bounded ``reason`` ("http_status" | "connect_error" |
    "network_error" | "unknown_transport_error") and an optional ``status`` HTTP
    code for metric labelling.
    """

    def __init__(self, reason: str, *, status: int | None = None, detail: str = "") -> None:
        super().__init__(detail or reason)
        self.reason = reason
        self.status = status
        self.detail = detail


def _classifier_fail_open() -> bool:
    """Read the RAG_CHAT_CLASSIFIER_FAIL_OPEN hot-toggle (default: fail-closed).

    Per-call env read (same pattern as DEBUG_SKIP_CLASSIFIER /
    RAG_COMPLETION_CACHE_DISABLED) so ops can flip the closed-vs-open policy
    during a provider incident without a redeploy. ANY value other than an
    explicit truthy spelling means fail-closed-but-honest — we NEVER default to
    fail-open.
    """
    return os.environ.get("RAG_CHAT_CLASSIFIER_FAIL_OPEN", "").strip().lower() in ("1", "true", "yes")


def _classifier_retry_attempts() -> int:
    """Read RAG_CHAT_CLASSIFIER_RETRY_ATTEMPTS (default 1, clamped to [0, 3]).

    Bounded retry on a transient transport failure BEFORE declaring the
    classifier unavailable. Clamped defensively so a fat-fingered env var cannot
    turn the safety gate into a latency amplifier.
    """
    raw = os.environ.get("RAG_CHAT_CLASSIFIER_RETRY_ATTEMPTS", "1").strip()
    try:
        return max(0, min(3, int(raw)))
    except ValueError:
        return 1


class LLMInjectionClassifier:
    """Semantic injection classifier using a small LLM on DeepInfra.

    Usage::
        classifier = LLMInjectionClassifier(api_key="...", model="...")
        is_unsafe = await classifier.classify(user_message)
        if is_unsafe:
            raise PromptInjectionError("Semantic injection detected")

    Verdict vs availability (do NOT conflate):
      * Genuine verdict → returns True (UNSAFE) / False (SAFE).
      * Parse failure / unexpected label → fail-closed True (verdict-side).
      * Provider unavailable / transport error → raises
        ``ClassifierUnavailableError`` (default fail-closed-but-honest; set
        ``RAG_CHAT_CLASSIFIER_FAIL_OPEN=true`` to fail open instead).
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
            True  — UNSAFE: a genuine injection verdict, OR a corrupt classifier
                    response (parse failure / unexpected label → fail-closed).
            False — SAFE: message passed the semantic check, classifier is
                    disabled (no API key), timed out (fail-open), or the
                    classifier was unavailable AND fail-open policy is active.

        Raises:
            ClassifierUnavailableError — the classifier could NOT RUN (provider
                unavailable / transport error: HTTP 402/429/5xx, connect or
                network error) AND the default fail-closed-but-honest policy is
                active (``RAG_CHAT_CLASSIFIER_FAIL_OPEN`` unset/false). This is
                DISTINCT from a genuine injection verdict — callers must surface
                it as ``CLASSIFIER_UNAVAILABLE``, never as injection.

        This method never raises for a genuine injection verdict (returns True)
        nor for parse/timeout errors — only the provider-unavailability path can
        raise, and only under the fail-closed-but-honest policy.
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

        # ── LLM classification with asyncio timeout + bounded retry ────────────
        # Three distinct outcomes are handled below — they are NOT the same:
        #
        #   1. TIMEOUT → fail-OPEN (return False). DeepInfra latency for the
        #      classifier occasionally exceeds 10s under load; blocking ALL user
        #      queries whenever the model is slow costs more than the marginal
        #      risk of one timed-out request slipping past Layer 2 (Layer 1 regex
        #      still ran). Unchanged behaviour.
        #
        #   2. TRANSPORT / PROVIDER UNAVAILABILITY (HTTP 402/429/5xx, connect or
        #      network error) → the classifier COULD NOT RUN. This is NOT an
        #      injection signal. We retry a bounded number of times, then apply
        #      the fail-open/closed policy and raise ClassifierUnavailableError
        #      (default) so the user sees an ACCURATE "safety check temporarily
        #      unavailable" message — never "Semantic injection detected". This
        #      is the bug fix.
        #
        #   3. PARSE / UNEXPECTED-LABEL (the model answered with garbage) → still
        #      fail-CLOSED as an injection verdict (return True). A corrupt
        #      classifier *response* may indicate a compromised/poisoned answer.
        #
        # ``_call_llm`` raises ``_ClassifierTransportError`` for case 2 and
        # returns a bool for cases 1/3.
        _max_retries = _classifier_retry_attempts()
        _last_transport: _ClassifierTransportError | None = None
        for _attempt in range(_max_retries + 1):
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
            except _ClassifierTransportError as exc:
                # Provider unavailable / transport failure — retry within budget,
                # then fall through to the unavailability policy below.
                _last_transport = exc
                if _attempt < _max_retries:
                    log.warning(  # type: ignore[no-any-return]
                        "llm_injection_classifier_transport_retry",
                        reason=exc.reason,
                        status=exc.status,
                        attempt=_attempt + 1,
                        max_retries=_max_retries,
                    )
                    continue
                break
            except Exception as exc:
                # Genuine parse / unexpected-response error (NOT a transport
                # failure) — fail-closed as an injection verdict. A corrupt
                # classifier response is treated as a possible injection signal.
                log.warning(  # type: ignore[no-any-return]
                    "llm_injection_classifier_fail_closed",
                    reason="exception",
                    error=str(exc),
                )
                return True  # fail-closed on unexpected (non-transport) errors

        # ── Classifier UNAVAILABLE: provider/transport error, retries exhausted ─
        assert _last_transport is not None  # loop only breaks here with a transport error
        rag_injection_classifier_unavailable.labels(
            reason=_last_transport.reason,
            status=str(_last_transport.status) if _last_transport.status is not None else "n/a",
        ).inc()

        if _classifier_fail_open():
            # Operator opted into fail-open for the duration of the incident.
            log.warning(  # type: ignore[no-any-return]
                "llm_injection_classifier_unavailable_fail_open",
                reason=_last_transport.reason,
                status=_last_transport.status,
                policy="fail_open",
            )
            return False  # SAFE — Layer 1 regex/PII already ran

        # Default policy: fail-closed-but-HONEST. Reject the request, but with an
        # accurate, distinct error — NOT a fake "injection detected" verdict.
        log.warning(  # type: ignore[no-any-return]
            "llm_injection_classifier_unavailable_fail_closed",
            reason=_last_transport.reason,
            status=_last_transport.status,
            policy="fail_closed_honest",
        )
        raise ClassifierUnavailableError(
            "Input safety check temporarily unavailable, please retry.",
            details={"reason": _last_transport.reason, "status": _last_transport.status},
        )

    async def _call_llm(self, message: str) -> bool:
        """Make the DeepInfra API call and parse the JSON response.

        Returns True if the model labels the message UNSAFE, False if SAFE.

        Raises:
            _ClassifierTransportError — provider unavailable / transport failure
                (HTTP 402/429/5xx or any non-2xx, connect error, network error).
                Signals "the classifier could not run" — NOT an injection. The
                caller maps this to the fail-open/closed unavailability policy.
            Exception — genuine parse failures (malformed JSON, missing keys)
                propagate so the caller fails CLOSED as an injection verdict.
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
            # Transport / provider-availability errors (the bug fix): a non-2xx
            # status (402 Payment Required, 429 rate-limit, 5xx outage) or a
            # connect/network failure means the classifier COULD NOT RUN. We
            # re-raise these as _ClassifierTransportError so classify() can apply
            # the unavailability policy instead of mislabelling them as injection.
            try:
                response = await client.post("/chat/completions", json=payload)
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                # 402/429/5xx and any other non-2xx — provider rejected/failed.
                _status = exc.response.status_code if exc.response is not None else None
                raise _ClassifierTransportError("http_status", status=_status, detail=str(exc)) from exc
            except httpx.ConnectError as exc:
                raise _ClassifierTransportError("connect_error", detail=str(exc)) from exc
            except httpx.TransportError as exc:
                # Covers ReadTimeout, network errors, protocol errors, etc.
                raise _ClassifierTransportError("network_error", detail=str(exc)) from exc
            except httpx.HTTPError as exc:
                # Any other httpx-layer error not caught above — still "could not run".
                raise _ClassifierTransportError("unknown_transport_error", detail=str(exc)) from exc

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
