"""HTTP harness for the rag-chat regression suite (PLAN-0093 Wave G-3 T-G-3-01).

PLAN-0101 W3 — TPS metric redesign
----------------------------------
The original TPS formula was ``output_tokens / (latency_s - ttft_s)``. After
PLAN-0100 W2 broadened TTFT to "first user-visible event" (which now includes
``tool_call`` / ``status`` pills firing within ~1 s), the (e2e - ttft)
denominator is dominated by **tool execution** (often 30-60 s), not synthesis.
The number therefore stopped measuring stream throughput — it measures tool
latency. The aggregate gate kept failing on legitimate tool-heavy questions.

Fix (PLAN-0101 W3): emit a second metric ``tps_streaming`` computed against
the backend-reported ``llm_synthesis_streaming`` phase wall-clock (plumbed by
PLAN-0099 W1-T03 through ``chat_orchestrator.py`` → ``emit_done`` →
``done.data.phase_timings_ms``). ``tps`` is preserved on the artefact for
historical comparison but is no longer gated. See
``docs/audits/2026-05-28-plan-0101-tps-metric-redesign.md``.

This module is the single entry point every Q1..Q8 + survey test uses to fire
a chat question and capture the full response. It does three things:

1. Bootstraps a dev JWT via ``POST /v1/auth/dev-login`` on the S9 API gateway.
   (Dev-login is hard-gated to non-production environments — see
   ``services/api-gateway/src/api_gateway/routes/auth.py:dev_login``.)
2. Fires the question against the streaming endpoint
   ``POST /v1/chat/stream`` and reassembles the SSE event stream so we
   recover the full token text, tool_call events, citations, metadata.
3. Persists the per-question artefact JSON under
   ``tests/validation/chat_eval/runs/<run_ts>/q<N>.json`` so failures
   are diagnosable and the weak-point report can post-process them.

Why the streaming endpoint
--------------------------
The synchronous ``POST /v1/chat`` (proxied to S8 ``/api/v1/chat``) returns
only ``answer + citations + contradictions + metadata`` — tool_call event
names are stripped. The streaming endpoint preserves the full SSE event
sequence including every ``tool_call`` event with the canonical tool name
from ``capability_manifest.yaml``. We need the tool name list to assert on
tool routing (e.g. "Q1 must call ``compare_entities``"); therefore we drive
the harness off the SSE stream and reassemble a synchronous view.

Skipping
--------
We never decorate tests with ``@pytest.mark.skip`` (R19). Instead the
``RagChatClient`` factory inspects ``RAG_CHAT_BASE_URL`` at *runtime* and
raises ``pytest.skip(...)`` from the fixture, so collection always succeeds.
"""

from __future__ import annotations

import json
import math
import os
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

# ---------------------------------------------------------------------------
# PLAN-0099 W1 T-W1-03 — Latency metric (initial design).
# PLAN-0100 W2 T-W2-02 — TTFT semantics broadened to "first user-visible
# event" (content tokens OR tool-status labels OR pre-tool status).
#
# We measure three things now:
#   * ttft_s        — time-to-first-token: wall-clock from request submit to
#                     the first SSE event that is USER-VISIBLE in the chat
#                     UI — i.e. content tokens (``token``, ``delta``,
#                     ``text``, ``final_answer``) OR tool-status labels
#                     (``tool_call``) OR pre-tool aggregate badge
#                     (``status`` — emitted with summary text once
#                     iteration-0 LLM decides on tools, see
#                     ``chat_orchestrator.py``). This matches what real
#                     users see: pills for tool-use turns render via
#                     ``ToolCallIndicator`` long before synthesis begins,
#                     so counting only content tokens overstated TTFT on
#                     tool-using questions (p95 = 69.7s observed).
#   * output_tokens — pulled from the provider's usage envelope when present
#                     (``metadata.usage.output_tokens`` or any event's
#                     ``data.usage.output_tokens``), otherwise estimated
#                     from the joined answer length using a 4-chars/token
#                     heuristic (no tiktoken dep is in the repo).
#   * tps           — output_tokens / (e2e_s - ttft_s) when both are valid
#                     and e2e > ttft; else ``None``.
#
# The end-to-end ``latency_s`` is still recorded for diagnostics, but the
# acceptance gate now uses TTFT-p95 + TPS-p50 + a relaxed E2E-p99 watchdog
# (see ``test_aggregate_score.py``). Rationale: end-to-end is contaminated
# by tool fan-out + query complexity; TTFT + TPS measure the user-facing
# responsiveness signals directly. The 5s p95 gate still holds — but now
# means "first user-visible label arrives in <5s" instead of "first content
# token in <5s". See:
# ``docs/audits/2026-05-27-plan-0099-latency-metric-redesign.md`` and
# ``docs/audits/2026-05-27-plan-0100-latency-structural.md`` §A.
# ---------------------------------------------------------------------------

# Event kinds whose ``data`` payload carries USER-VISIBLE output.
# The first event whose kind is in this set defines the TTFT boundary.
# PLAN-0100 W2 T-W2-02: added ``tool_call`` (pills render immediately via
# ToolCallIndicator) and ``status`` (aggregate "Loading <tools>…" badge
# emitted by chat_orchestrator right after iteration-0's tool plan).
_CONTENT_EVENT_KINDS: frozenset[str] = frozenset({"token", "delta", "text", "final_answer", "tool_call", "status"})

# Chars-per-token estimate for the fallback path when the provider does not
# emit a usage envelope. 4.0 is the textbook GPT-style English approximation;
# we floor at 1 token so a degenerate one-char answer still yields a valid
# (if pessimistic) tokens-per-second number.
_CHARS_PER_TOKEN_FALLBACK = 4.0

# ---------------------------------------------------------------------------
# Tunables.
# ---------------------------------------------------------------------------

# Default HTTP timeout per question. The audit reports show p99 ≤ 60s in the
# steady state; we give a 90s headroom so a slow LLM cold-start doesn't fail
# the harness itself — the *content* test asserts on the 60s p99 SLO.
_DEFAULT_TIMEOUT_S = 90.0

# Where per-question artefacts land. Bound to a single run-timestamp dir so
# diffing across runs is straightforward.
_RUNS_ROOT = Path(__file__).parent / "runs"


# ---------------------------------------------------------------------------
# Lazy httpx import — keep collection working when httpx is somehow missing.
# ---------------------------------------------------------------------------


def _import_httpx():  # type: ignore[no-untyped-def]
    """Import httpx lazily so collection still works if the dep is missing."""
    try:
        import httpx  # — lazy by design
    except ImportError:  # pragma: no cover — httpx is in the venv
        pytest.skip("httpx not installed — chat-eval harness requires httpx")
    return httpx


# ---------------------------------------------------------------------------
# Public dataclasses — what the tests assert on.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ToolCall:
    """One ``tool_call`` SSE event captured during the stream."""

    name: str
    # The arguments dict the LLM sent — kept as-is for forensic inspection
    # (e.g. "did the LLM pass sector=Semiconductors to screen_universe?").
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass
class ChatRunResult:
    """Full outcome of one chat question — what tests assert on.

    Fields:
        question:     the verbatim user prompt.
        status_code:  HTTP status of the *initial* stream response (200 on
                      success, 503 on PROVIDER_UNAVAILABLE error event, etc.).
        latency_s:    wall-clock seconds from request-out to last event
                      (end-to-end, diagnostic-only after PLAN-0099 W1).
        ttft_s:       time-to-first-token in seconds — wall-clock from
                      request submit to the FIRST SSE event whose payload
                      carries rendered content (``token``/``delta``/``text``/
                      ``final_answer``). ``nan`` if no content frame arrived
                      (error event, empty stream). See module docstring.
        tps:          tokens-per-second over the generation window
                      (TTFT → end of stream). ``nan`` if TTFT or output_tokens
                      could not be determined, or if the window is zero.
        output_tokens: token count used for TPS — pulled from the provider
                      usage envelope when present (``data.usage.output_tokens``
                      on the final event, or ``metadata.usage.output_tokens``),
                      otherwise estimated from joined answer text using a
                      4-chars-per-token heuristic. ``None`` if not computed.
        answer_text:  reassembled response text (preferring final_answer
                      event over the token stream).
        tool_calls:   ordered list of ``tool_call`` events.
        citations:    citation objects from the ``citations`` event.
        contradictions: contradiction objects (rarely populated outside Q7).
        metadata:     final metadata event payload (provider, intent, ids).
        error:        error event payload if one was emitted (else None).
        raw_events:   complete SSE event log — kept for diff / replay.
        event_timings: ordered list of ``(event_kind, t_recv_us)`` tuples
                      recorded harness-side as each SSE frame arrived;
                      ``t_recv_us`` is microseconds since request submit.
                      Used to compute TTFT / TPS and to debug stalls.
    """

    question: str
    status_code: int
    latency_s: float
    answer_text: str
    ttft_s: float = float("nan")
    tps: float = float("nan")
    # PLAN-0101 W3: synthesis-phase TPS. Computed as
    # ``output_tokens / (phase_timings_ms["llm_synthesis_streaming"] / 1000)``
    # using the backend's per-phase wall-clock from PLAN-0099 W1-T03. NaN when
    # the ``done`` event omits ``phase_timings_ms`` (older backend, error
    # path) or when the synthesis phase wall-clock is zero. This is the gated
    # metric; ``tps`` above is kept as a diagnostic.
    tps_streaming: float = float("nan")
    output_tokens: int | None = None
    # PLAN-0101 W3: raw phase wall-clocks from ``done.data.phase_timings_ms``
    # (PLAN-0099 W1-T03 backend plumbing). Empty dict when the backend did not
    # surface the dict (older deploys, error paths). Kept on the artefact so
    # offline analysis can re-derive ``tps_streaming`` from raw values.
    phase_timings_ms: dict[str, float] = field(default_factory=dict)
    tool_calls: list[ToolCall] = field(default_factory=list)
    citations: list[dict[str, Any]] = field(default_factory=list)
    contradictions: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    error: dict[str, Any] | None = None
    raw_events: list[dict[str, Any]] = field(default_factory=list)
    event_timings: list[tuple[str, int]] = field(default_factory=list)

    def tools_called(self) -> list[str]:
        """Convenience: list of tool names in invocation order (may repeat)."""
        return [tc.name for tc in self.tool_calls]

    def to_json_dict(self) -> dict[str, Any]:
        """Serialise to a JSON-safe dict (for the per-question artefact).

        NaN floats are serialised as ``None`` rather than the non-compliant
        ``NaN`` JSON token, so downstream tools (jq, JS) don't choke. The
        ``ttft_s`` / ``tps`` / ``output_tokens`` fields are included even
        when missing so artefact schemas stay stable across runs.
        """

        def _opt(x: float) -> float | None:
            # Return None for NaN/inf so the JSON is RFC-8259-compliant.
            return None if (x is None or not math.isfinite(x)) else round(float(x), 3)

        return {
            "question": self.question,
            "status_code": self.status_code,
            "latency_s": round(self.latency_s, 3),
            "ttft_s": _opt(self.ttft_s),
            "tps": _opt(self.tps),
            # PLAN-0101 W3: new gated metric. Sits alongside ``tps`` so
            # historical runs remain comparable; old artefacts simply omit
            # the key and will deserialise with NaN-equivalent ``None``.
            "tps_streaming": _opt(self.tps_streaming),
            "phase_timings_ms": dict(self.phase_timings_ms),
            "output_tokens": self.output_tokens,
            "answer_text": self.answer_text,
            "tool_calls": [{"name": tc.name, "arguments": tc.arguments} for tc in self.tool_calls],
            "citations": self.citations,
            "contradictions": self.contradictions,
            "metadata": self.metadata,
            "error": self.error,
            "raw_events": self.raw_events,
            # event_timings is forensic-only; emit as list-of-lists for JSON.
            "event_timings": [[kind, t_us] for kind, t_us in self.event_timings],
        }


# ---------------------------------------------------------------------------
# Client.
# ---------------------------------------------------------------------------


class RagChatClient:
    """Thin sync HTTP client wrapping ``POST /v1/auth/dev-login`` + chat stream.

    Designed for pytest: one instance per test session, reused across all
    questions. ``base_url`` defaults to ``http://localhost:8009`` (the dev
    S9 gateway port) when the env var is missing.

    The class is intentionally tiny — we don't pull in pytest-asyncio just
    to call two HTTP endpoints. The streaming reader uses ``iter_lines``
    on a sync ``httpx.Client``.
    """

    def __init__(self, base_url: str, *, timeout_s: float = _DEFAULT_TIMEOUT_S) -> None:
        httpx = _import_httpx()
        self._base_url = base_url.rstrip("/")
        # We pre-build the client so connections are reused across questions.
        # ``follow_redirects=True`` is defensive — the dev-login route returns
        # 200 directly, but a future deployment behind a reverse proxy might
        # redirect.
        self._client = httpx.Client(
            base_url=self._base_url,
            timeout=httpx.Timeout(timeout_s),
            follow_redirects=True,
        )
        self._access_token: str | None = None

    # ── Auth ──────────────────────────────────────────────────────────────

    def login(self) -> str:
        """POST /v1/auth/dev-login → cache and return the access token.

        Idempotent: caches the token on first call. Returns the bearer token
        suitable for an ``Authorization: Bearer …`` header.
        """
        if self._access_token is not None:
            return self._access_token

        httpx = _import_httpx()
        try:
            resp = self._client.post("/v1/auth/dev-login")
        except httpx.RequestError as exc:
            pytest.skip(f"could not reach rag-chat at {self._base_url!r}: {exc}")

        if resp.status_code != 200:
            pytest.skip(
                f"dev-login failed (status={resp.status_code}) — "
                f"rag-chat at {self._base_url!r} may not be in dev mode. "
                f"Body: {resp.text[:200]}"
            )

        body = resp.json()
        token = body.get("access_token")
        if not isinstance(token, str):
            pytest.skip(f"dev-login returned no access_token: {body!r}")
        self._access_token = token
        return token

    # ── Chat ──────────────────────────────────────────────────────────────

    def ask(self, question: str, *, entity_ids: list[str] | None = None) -> ChatRunResult:
        """Fire one chat question against the streaming endpoint.

        Returns a :class:`ChatRunResult` regardless of outcome — even on
        ``error`` events we return a populated result (with ``error`` set
        and ``status_code=503``) so tests can assert on the failure mode.

        On HTTP errors before the stream even opens (network, 401, etc.)
        we raise ``pytest.skip`` so the suite doesn't pretend to test
        something that never reached the LLM.
        """
        token = self.login()
        httpx = _import_httpx()

        # PLAN-0095 W3 T-W3-03: ALWAYS attach a fresh thread_id per ask() call.
        # The rag-chat completion cache keys on sha256(message:thread_id); when
        # thread_id is omitted the key collapses to sha256(message:None) and
        # later runs of the same prompt serve a stale cached answer from an
        # earlier session, masking regressions (audit §5; iter3_top5 "Unity
        # Software" artefact). The conftest header documented this invariant
        # but did not enforce it — this line promotes it from advisory to law.
        payload = {
            "message": question,
            "entity_ids": entity_ids or [],
            "thread_id": str(uuid4()),
        }
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        }

        start = time.monotonic()
        # Refresh-on-401: dev-login mints a 5-min user JWT (gateway _USER_TTL=300s).
        # The chained Q1..Q8 + adversarial + 75-query weak-point survey runs >5 min
        # in one pytest invocation, so the cached token silently expires partway
        # through and every later request 401s. On 401, drop the cache, re-login,
        # rebuild headers, retry once.
        for _attempt in range(2):
            try:
                with self._client.stream("POST", "/v1/chat/stream", json=payload, headers=headers) as resp:
                    status = resp.status_code
                    if status == 401 and _attempt == 0:
                        self._access_token = None
                        token = self.login()
                        headers["Authorization"] = f"Bearer {token}"
                        continue
                    if status != 200:
                        body_preview = b""
                        try:
                            body_preview = resp.read()[:500]
                        except Exception:  # noqa: S110 — diagnostic-only; pass is intentional
                            pass
                        return ChatRunResult(
                            question=question,
                            status_code=status,
                            latency_s=time.monotonic() - start,
                            answer_text="",
                            error={
                                "code": "HTTP_ERROR",
                                "message": body_preview.decode(errors="replace"),
                            },
                        )
                    # SSE format: alternating ``event: …`` / ``data: …`` / blank
                    # lines. We accumulate one event at a time via tiny state
                    # machine — no aiohttp/SSE-client dep needed.
                    events, timings = _read_sse_events(resp, start)
                    return _events_to_result(
                        question,
                        status,
                        events,
                        time.monotonic() - start,
                        timings,
                    )
            except httpx.RequestError as exc:
                pytest.skip(f"chat request failed: {exc}")
                raise  # pragma: no cover — pytest.skip raises, unreachable
        # Defensive — loop only exits via return; this satisfies the type checker.
        raise RuntimeError("unreachable: stream loop exited without return")

    # ── Lifecycle ─────────────────────────────────────────────────────────

    def close(self) -> None:
        """Close the underlying httpx client."""
        self._client.close()


# ---------------------------------------------------------------------------
# SSE parsing helpers.
# ---------------------------------------------------------------------------


def _read_sse_events(
    resp: Any,
    request_start: float,
) -> tuple[list[dict[str, Any]], list[tuple[str, int]]]:
    """Convert an httpx streaming response into a (events, timings) pair.

    SSE wire format (per W3C):
      ``event: <name>\\n``
      ``data: <json or text>\\n``
      ``\\n``  (blank line — terminator)

    ``data:`` may repeat across multiple lines (concatenated) but our emitter
    always writes a single JSON blob per event, so a simple two-line buffer
    is sufficient.

    PLAN-0099 W1 T-W1-03: ``request_start`` is the ``time.monotonic()``
    snapshot taken right before the stream POST. For every completed SSE
    frame we record ``(event_kind, t_recv_us)`` where ``t_recv_us`` is the
    receive-time relative to ``request_start`` in microseconds. The list
    is returned alongside the parsed events so downstream code can compute
    TTFT / TPS without re-walking the network. Microseconds (not seconds)
    are used to avoid float drift on small (~10ms) gaps.
    """
    events: list[dict[str, Any]] = []
    timings: list[tuple[str, int]] = []
    current: dict[str, str] = {}
    for raw_line in resp.iter_lines():
        # httpx >= 0.27 yields str; older yields bytes. Normalise.
        if isinstance(raw_line, bytes):
            line = raw_line.decode("utf-8", errors="replace")
        else:
            line = raw_line
        if line == "":
            # End of one event.
            if current:
                ev = _parse_event(current)
                events.append(ev)
                # Receive-time stamped when the terminator (blank line) lands;
                # this is the most consistent definition of "frame arrived".
                t_recv_us = int((time.monotonic() - request_start) * 1_000_000)
                timings.append((str(ev.get("event", "")), t_recv_us))
                current = {}
            continue
        if line.startswith("event:"):
            current["event"] = line[len("event:") :].strip()
        elif line.startswith("data:"):
            # Concatenate multi-line data fields with a literal newline
            # (W3C SSE rule §9.2). Our emitter sends single-line JSON so
            # this branch rarely fires.
            existing = current.get("data", "")
            piece = line[len("data:") :].lstrip()
            current["data"] = existing + ("\n" if existing else "") + piece
        # Lines starting with ":" are comments per W3C — ignore.
    # Flush a trailing event if the server closed without the terminator.
    if current:
        ev = _parse_event(current)
        events.append(ev)
        t_recv_us = int((time.monotonic() - request_start) * 1_000_000)
        timings.append((str(ev.get("event", "")), t_recv_us))
    return events, timings


def _parse_event(raw: dict[str, str]) -> dict[str, Any]:
    """Try to JSON-decode the ``data`` payload; fall back to raw string."""
    out: dict[str, Any] = {"event": raw.get("event", "")}
    data_str = raw.get("data", "")
    try:
        out["data"] = json.loads(data_str)
    except (json.JSONDecodeError, ValueError):
        out["data"] = data_str
    return out


def _events_to_result(
    question: str,
    status_code: int,
    events: list[dict[str, Any]],
    latency_s: float,
    event_timings: list[tuple[str, int]] | None = None,
) -> ChatRunResult:
    """Fold a stream of SSE events into a single :class:`ChatRunResult`.

    ``event_timings`` is a parallel list to ``events`` (same length, same
    order) of ``(event_kind, t_recv_us)`` tuples produced by
    :func:`_read_sse_events`. When omitted (legacy callers / unit tests
    that construct ``events`` synthetically) TTFT and TPS are reported as
    ``nan`` and ``None`` respectively — the existing assertions on
    ``answer_text`` / ``tool_calls`` / ``citations`` continue to pass.
    """
    token_buf: list[str] = []
    final_answer: str | None = None
    tool_calls: list[ToolCall] = []
    citations: list[dict[str, Any]] = []
    contradictions: list[dict[str, Any]] = []
    metadata: dict[str, Any] = {}
    error: dict[str, Any] | None = None
    timings: list[tuple[str, int]] = list(event_timings or [])

    # Track the provider usage envelope if any event carries it. We accept
    # either shape: ``data.usage.output_tokens`` (per-event, OpenAI-style)
    # or ``metadata.usage.output_tokens`` (final metadata event). First
    # non-None value wins; ties don't matter because at most one event
    # type emits it in practice.
    usage_output_tokens: int | None = None

    # PLAN-0101 W3: per-phase wall-clocks emitted by the backend on the
    # ``done`` SSE event (see ``sse_emitter.emit_done`` +
    # ``chat_orchestrator._phase_snapshot``). When absent (older backend,
    # error path that did not reach ``emit_done``) we keep an empty dict and
    # ``tps_streaming`` collapses to NaN.
    phase_timings_ms: dict[str, float] = {}

    for ev in events:
        kind = ev.get("event", "")
        data = ev.get("data")
        # Provider usage envelope sniff (any frame may carry it).
        if isinstance(data, dict):
            usage = data.get("usage")
            if isinstance(usage, dict):
                ot = usage.get("output_tokens")
                if isinstance(ot, int) and ot >= 0 and usage_output_tokens is None:
                    usage_output_tokens = ot
        if kind == "token" and isinstance(data, dict):
            token_buf.append(str(data.get("text", "")))
        elif kind == "final_answer" and isinstance(data, dict):
            final_answer = str(data.get("text", ""))
        elif kind == "tool_call" and isinstance(data, dict):
            # ``data`` shape from sse_emitter.emit_tool_call: {tool, label, input}
            tool_name = str(data.get("tool", data.get("name", "")))
            args = data.get("input") or data.get("arguments") or {}
            if not isinstance(args, dict):
                args = {"_raw": args}
            tool_calls.append(ToolCall(name=tool_name, arguments=args))
        elif kind == "citations" and isinstance(data, list):
            citations = data
        elif kind == "contradictions" and isinstance(data, list):
            contradictions = data
        elif kind == "metadata" and isinstance(data, dict):
            metadata = data
        elif kind == "done" and isinstance(data, dict):
            # PLAN-0101 W3: harvest the per-phase wall-clock dict for
            # ``tps_streaming``. Backend may also attach it to other frames
            # in future; ``done`` is the authoritative carrier today.
            pt = data.get("phase_timings_ms")
            if isinstance(pt, dict):
                # Cast values to float defensively — backend currently emits
                # floats but some intermediate consumers (e.g. ujson) round
                # to int.  Reject non-numeric entries silently.
                for _k, _v in pt.items():
                    if isinstance(_v, int | float) and not isinstance(_v, bool):
                        phase_timings_ms[str(_k)] = float(_v)
        elif kind == "error" and isinstance(data, dict):
            error = data
            # Map the documented error codes to an effective HTTP status
            # so downstream tests can assert on 503 vs 200 cleanly.
            code = str(data.get("code", "")).upper()
            if code in {"PROVIDER_UNAVAILABLE", "INTERNAL_ERROR"}:
                status_code = 503
            elif code in {"RATE_LIMIT_EXCEEDED"}:
                status_code = 429
            elif code in {"INPUT_REJECTED"}:
                status_code = 400

    # BP-613 (PLAN-0101 Wave 3): answer-assembly fallback.
    #
    # In the Q8 isolated-vs-aggregate flake the orchestrator streamed a
    # complete answer via ``token`` events but the final ``final_answer``
    # event arrived with an empty payload — the harness then surfaced
    # ``answer_text=""`` (graded USELESS) even though every token had
    # already been observed. Token-stream contents are authoritative
    # whenever the final-event payload is missing or shorter than the
    # accumulated tokens. Pick the LONGER non-empty option so a truncated
    # / empty ``final_answer`` event can never erase a streamed answer.
    joined_tokens = "".join(token_buf)
    if final_answer is None or not final_answer:
        answer_text = joined_tokens
    elif len(joined_tokens) > len(final_answer):
        # Provider re-emitted a truncated final answer after streaming;
        # prefer the more complete token concatenation.
        answer_text = joined_tokens
    else:
        answer_text = final_answer

    # Also accept the usage envelope from the final metadata event payload
    # (some providers attach it there instead of per-token frames).
    if usage_output_tokens is None:
        meta_usage = metadata.get("usage") if isinstance(metadata, dict) else None
        if isinstance(meta_usage, dict):
            ot = meta_usage.get("output_tokens")
            if isinstance(ot, int) and ot >= 0:
                usage_output_tokens = ot

    ttft_s, tps, output_tokens = _compute_ttft_and_tps(
        timings=timings,
        latency_s=latency_s,
        answer_text=answer_text,
        usage_output_tokens=usage_output_tokens,
    )

    # PLAN-0101 W3: synthesis-phase TPS using the backend ``llm_synthesis_streaming``
    # wall-clock. ``output_tokens`` is the same denominator-numerator that fed
    # the legacy ``tps`` field above — only the time window changes.
    tps_streaming = _compute_tps_streaming(
        phase_timings_ms=phase_timings_ms,
        output_tokens=output_tokens,
    )

    return ChatRunResult(
        question=question,
        status_code=status_code,
        latency_s=latency_s,
        ttft_s=ttft_s,
        tps=tps,
        tps_streaming=tps_streaming,
        output_tokens=output_tokens,
        phase_timings_ms=phase_timings_ms,
        answer_text=answer_text,
        tool_calls=tool_calls,
        citations=citations,
        contradictions=contradictions,
        metadata=metadata,
        error=error,
        raw_events=events,
        event_timings=timings,
    )


# ---------------------------------------------------------------------------
# TTFT / TPS computation (pure — unit-testable without a live server).
# ---------------------------------------------------------------------------


def _estimate_tokens_from_text(text: str) -> int:
    """Heuristic token count when the provider does not emit a usage envelope.

    Repository has no tiktoken dep, so we approximate with the standard
    ``ceil(chars / 4)`` rule — close enough for English LLM output. Floored
    at 1 so a one-character answer still gives a finite TPS rather than
    dividing by zero.
    """
    if not text:
        return 0
    return max(1, int(math.ceil(len(text) / _CHARS_PER_TOKEN_FALLBACK)))


def _compute_ttft_and_tps(
    *,
    timings: list[tuple[str, int]],
    latency_s: float,
    answer_text: str,
    usage_output_tokens: int | None,
) -> tuple[float, float, int | None]:
    """Return ``(ttft_s, tps, output_tokens)`` from a parsed SSE stream.

    TTFT
        First timing entry whose event kind is in :data:`_CONTENT_EVENT_KINDS`.
        Converted from microseconds-since-request-start to seconds. ``nan``
        when no content frame arrived (error path, empty stream, or the
        harness was called with synthetic events lacking timings).

    output_tokens
        Provider usage envelope wins when present; otherwise we estimate
        from the joined answer text via :func:`_estimate_tokens_from_text`.
        ``None`` only when the answer is empty AND no usage envelope was
        emitted (TPS then collapses to ``nan``).

    TPS
        ``output_tokens / (latency_s - ttft_s)`` when both are finite,
        ``output_tokens > 0``, and the generation window is positive.
        ``nan`` otherwise — the aggregate gate drops nans before
        percentile math, so a single error-path run cannot poison the
        median.
    """
    # TTFT: scan for the first content-bearing frame.
    ttft_s = float("nan")
    for kind, t_us in timings:
        if kind in _CONTENT_EVENT_KINDS:
            ttft_s = t_us / 1_000_000.0
            break

    # Output tokens: envelope wins; otherwise estimate.
    if usage_output_tokens is not None:
        output_tokens: int | None = usage_output_tokens
    elif answer_text:
        output_tokens = _estimate_tokens_from_text(answer_text)
    else:
        output_tokens = None

    # TPS: only valid when we know both bookends of the generation window.
    tps = float("nan")
    if output_tokens is not None and output_tokens > 0 and math.isfinite(ttft_s) and latency_s > ttft_s:
        tps = output_tokens / (latency_s - ttft_s)

    return ttft_s, tps, output_tokens


# PLAN-0101 W3 — synthesis-phase TPS.
_SYNTHESIS_PHASE_KEY = "llm_synthesis_streaming"


def _compute_tps_streaming(
    *,
    phase_timings_ms: dict[str, float],
    output_tokens: int | None,
) -> float:
    """Return ``output_tokens / phase_timings_ms[llm_synthesis_streaming]`` (seconds).

    Returns ``nan`` when:

    * the backend did not surface ``phase_timings_ms`` (older deploy, error
      path that returned before ``emit_done``);
    * the ``llm_synthesis_streaming`` key is absent (e.g. a refusal that
      short-circuited before the second-turn stream began);
    * the recorded wall-clock is zero or negative (defensive — would div/0);
    * ``output_tokens`` is unknown or non-positive.

    These collapses are semantically identical to "no data" — the aggregate
    gate drops NaNs before taking the median (same policy as ``tps``), so a
    single error-path run cannot poison the median in either direction.
    """
    if output_tokens is None or output_tokens <= 0:
        return float("nan")
    if not phase_timings_ms:
        return float("nan")
    synthesis_ms = phase_timings_ms.get(_SYNTHESIS_PHASE_KEY)
    if synthesis_ms is None or synthesis_ms <= 0:
        return float("nan")
    return float(output_tokens) / (float(synthesis_ms) / 1000.0)


# ---------------------------------------------------------------------------
# Artefact persistence.
# ---------------------------------------------------------------------------


def _run_dir(run_ts: str | None = None) -> Path:
    """Return (and create on demand) the run directory for this test session.

    The directory name encodes the UTC timestamp at session start. A single
    pytest invocation reuses the same directory across all per-question
    tests so the post-run report can ``ls`` once.
    """
    ts = run_ts or datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%SZ")
    out = _RUNS_ROOT / ts
    out.mkdir(parents=True, exist_ok=True)
    return out


def save_result(result: ChatRunResult, *, slot: str, run_ts: str | None = None) -> Path:
    """Persist a :class:`ChatRunResult` JSON artefact to the run directory.

    ``slot`` is the per-question filename stem (``q1``, ``q4_v3``,
    ``survey_AAPL_REVENUE_v1``, etc.). The file name is sanitized to
    ``[A-Za-z0-9_.-]`` for cross-platform safety.
    """
    safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in slot)
    target = _run_dir(run_ts) / f"{safe}.json"
    target.write_text(json.dumps(result.to_json_dict(), indent=2, sort_keys=True))
    return target


# ---------------------------------------------------------------------------
# Question loader.
# ---------------------------------------------------------------------------


def load_questions(path: Path | None = None) -> list[dict[str, Any]]:
    """Load the 8 audit questions + ground-truth from ``questions.yaml``.

    Returns the raw decoded YAML structure: a list of dicts each with
    ``id``, ``prompt``, optional ``entity_ids``, and ``ground_truth_assertions``.

    We import PyYAML lazily — the rest of the harness works without it,
    and the per-question test files have their prompts hard-coded so
    they don't depend on this loader.
    """
    src = path or (Path(__file__).parent / "questions.yaml")
    try:
        import yaml  # type: ignore[import-untyped]
    except ImportError:  # pragma: no cover — PyYAML is a dev dep
        pytest.skip("PyYAML not installed — questions.yaml loader requires it")
    return list(yaml.safe_load(src.read_text()))


# ---------------------------------------------------------------------------
# Module-level singleton helper used by conftest.py.
# ---------------------------------------------------------------------------


def make_client_or_skip() -> RagChatClient:
    """Return a :class:`RagChatClient` or call ``pytest.skip`` if no base URL.

    Centralised so every test file that imports the harness gets the same
    skip message and never accidentally builds a client without a URL.
    """
    base_url = os.environ.get("RAG_CHAT_BASE_URL")
    if not base_url:
        pytest.skip(
            "RAG_CHAT_BASE_URL not set — requires live rag-chat at " "$RAG_CHAT_BASE_URL (e.g. http://localhost:8009)"
        )
    return RagChatClient(base_url)
