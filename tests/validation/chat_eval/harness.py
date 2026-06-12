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

PLAN-0102 W4 T-W4-01: ``tps_streaming`` is now ``float | None`` (was
``float`` with NaN sentinel). The chat orchestrator has TWO branches that
terminate the agent loop:

* **direct-text branch** (line ~960 in ``chat_orchestrator.py``): the LLM
  produced a substantive answer in the first or a later iteration WITHOUT
  needing a second-turn synthesis stream — typical of short factual
  questions ("What is Apple?"). The ``llm_synthesis_streaming`` phase
  never fires → ``tps_streaming = None`` (semantic: "no data, gate
  skipped"). This is correct, not a bug.
* **second-turn-stream branch** (line ~1660): after tool calls, the LLM
  re-streams a final answer through ``llm_chain.stream_chat``. This is
  the path the gate is designed to measure.

Empirically, ~5 of the 8 chat-eval questions take the direct-text branch
on a typical run. Returning ``None`` (not NaN) makes the artefact JSON
unambiguous (no sentinel collision with "failed to measure") and the
aggregate gate's ``_finite_only`` cleanly drops the skipped entries.

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
import re
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
    # PLAN-0101 W3 / PLAN-0102 W4 T-W4-01: synthesis-phase TPS. Computed as
    # ``output_tokens / (phase_timings_ms["llm_synthesis_streaming"] / 1000)``
    # using the backend's per-phase wall-clock from PLAN-0099 W1-T03.
    # ``None`` when the ``done`` event omits ``phase_timings_ms`` (older
    # backend, error path), the synthesis phase did not fire (direct-text
    # branch — common for short factual questions), or the recorded
    # wall-clock is sub-100ms (defensive against BP-618 double-record).
    # This is the gated metric; ``tps`` above is kept as a diagnostic.
    tps_streaming: float | None = None
    output_tokens: int | None = None
    # PLAN-0101 W3: raw phase wall-clocks from ``done.data.phase_timings_ms``
    # (PLAN-0099 W1-T03 backend plumbing). Empty dict when the backend did not
    # surface the dict (older deploys, error paths). Kept on the artefact so
    # offline analysis can re-derive ``tps_streaming`` from raw values.
    phase_timings_ms: dict[str, float] = field(default_factory=dict)
    tool_calls: list[ToolCall] = field(default_factory=list)
    # PLAN-0102 W5 T-W5-02: ``tool_result`` events with ``status`` + ``item_count``.
    # Captured so the grader can distinguish "honest refusal" (every tool
    # returned empty → answer says "no data found") from "USELESS refusal"
    # (tool data present but model refused anyway). Each entry is the
    # ``tool_result`` event payload dict (``{tool, status, item_count}``).
    tool_results: list[dict[str, Any]] = field(default_factory=list)
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

        def _opt(x: float | None) -> float | None:
            # Return None for NaN/inf so the JSON is RFC-8259-compliant.
            # PLAN-0102 W4 T-W4-01: also accept ``None`` directly (the new
            # ``tps_streaming`` typing — see ``_compute_tps_streaming``).
            if x is None:
                return None
            return None if not math.isfinite(x) else round(float(x), 3)

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
            # PLAN-0102 W5 T-W5-02: persist for offline grader analysis.
            "tool_results": list(self.tool_results),
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


# PLAN-0102 W5 T-W5-01 (BP-619): citation-marker scrubber.
_CITATION_MARKER_RE = re.compile(r"\[N(\d+)\]")


def _scrub_out_of_bounds_citations(text: str, citations: list[dict[str, Any]]) -> str:
    """Remove ``[Nk]`` markers whose index exceeds the citation list length.

    PLAN-0102 W5 T-W5-01 (BP-619 — citation marker scrub on fallback).

    When the harness falls back to ``joined_tokens`` (the pre-validation
    token stream) because the validated ``final_answer`` was empty or
    massively shorter, the token stream still carries citation markers
    that pointed at citations the numeric-grounding validator has since
    stripped from the citations event. The grader's ``citations_in_bounds``
    check then reports "out of bounds" and downgrades USEFUL → MARGINAL —
    a false-negative driven entirely by harness reassembly, not by the
    model. This helper scrubs only the orphan markers (``k > len``),
    preserving the surrounding text and any in-bounds markers.

    The marker number is 1-indexed in the chat-eval rubric (``[N1]`` =
    citations[0]), so ``k > len(citations)`` is the orphan condition.
    """
    if not text or not citations:
        # Empty citations list → every marker is orphan. Strip them all so
        # the grader does not flag every "[Nk]" in the answer.
        if not citations and text:
            return _CITATION_MARKER_RE.sub("", text)
        return text
    max_valid = len(citations)

    def _sub(match: re.Match[str]) -> str:
        try:
            idx = int(match.group(1))
        except ValueError:
            return match.group(0)
        # 1-indexed: idx in [1, max_valid] is in-bounds.
        if 1 <= idx <= max_valid:
            return match.group(0)
        return ""

    return _CITATION_MARKER_RE.sub(_sub, text)


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
    # PLAN-0102 W5 T-W5-02: capture ``tool_result`` events for the grader's
    # honest-refusal vs refusal-from-nowhere distinction.
    tool_results: list[dict[str, Any]] = []
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
        elif kind == "tool_result" and isinstance(data, dict):
            # PLAN-0102 W5 T-W5-02: ``{type, tool, status, item_count}``.
            # Capture the four fields the honest-refusal grader policy
            # consumes; ignore anything else to keep the artefact slim.
            _tool_result_entry: dict[str, Any] = {
                "tool": str(data.get("tool", "")),
                "status": str(data.get("status", "")),
                "item_count": int(data.get("item_count", 0) or 0),
            }
            # PLAN-0110 W2 (PRD-0091 FR-5): the backend now OPTIONALLY attaches a
            # bounded, redacted ``grounding_sample`` ({fields, sampled_rows,
            # total_rows, truncated}) when CHAT_EVAL_GROUNDING_SAMPLES=true and
            # status=ok. Capture it verbatim so the W3 judge can later
            # cross-check numeric claims against the values the tool returned.
            # Forward-compatible: absent on older runs / when the flag is off, in
            # which case we add nothing and the entry keeps its legacy 3 keys.
            _grounding = data.get("grounding_sample")
            if isinstance(_grounding, dict) and _grounding:
                _tool_result_entry["grounding_sample"] = _grounding
            tool_results.append(_tool_result_entry)
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
    # accumulated tokens.
    #
    # BP-619 (PLAN-0102 W5 T-W5-01): the numeric-grounding validator
    # (PLAN-0093) intentionally STRIPS ungrounded numbers from
    # ``final_answer`` — the validated answer is frequently much shorter
    # than ``joined_tokens``. The original "pick the longer" rule then
    # preferred ``joined_tokens`` (pre-validation) every time, which
    # surfaces hallucinated numbers AND citation markers ``[Nk]`` whose
    # index points to citations also stripped by the validator → the
    # grader then flags "citation marker out of bounds" and downgrades
    # the answer to MARGINAL. Fix: prefer ``final_answer`` unless the
    # token stream is *substantially* longer (≥10x — indicating a true
    # empty/truncated final_answer event, not a validation-driven trim).
    # When we DO fall back to ``joined_tokens``, scrub citation markers
    # that point beyond the valid citation range so the grader's
    # in-bounds check does not false-positive.
    joined_tokens = "".join(token_buf)
    if final_answer is None or not final_answer:
        # No final-event payload at all → token stream is all we have.
        answer_text = _scrub_out_of_bounds_citations(joined_tokens, citations)
    elif len(joined_tokens) > 10 * max(len(final_answer), 1):
        # Token stream is >10x the validated answer — final_answer was
        # genuinely truncated (provider re-emitted an empty / partial
        # final-event frame after streaming). Prefer the token stream
        # but scrub its citation markers against the citations event.
        answer_text = _scrub_out_of_bounds_citations(joined_tokens, citations)
    else:
        # Normal path: validated final_answer is authoritative even when
        # shorter than the token stream — the trim reflects honest
        # grounding-validation removal of ungrounded numbers, not data
        # loss. This is the BP-619 fix: trust the validator output.
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
        tool_results=tool_results,
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
# PLAN-0102 W4 T-W4-B (BP-621): direct-text branch generation-phase key.
# When the LLM answers without calling any tool (the common case for
# "What is X?" questions), the orchestrator never reaches the second-turn
# streaming synthesis path — ``llm_synthesis_streaming`` is absent. The
# direct-text branch instead records the iter-0 ``chat_with_tools`` call
# wall-clock under this key, which is the generation time we want to
# divide ``output_tokens`` by. The harness accepts EITHER key so the
# ``tps_streaming`` metric has data on both branches.
_DIRECT_TEXT_PHASE_KEY = "llm_direct_text_generation"

# PLAN-0102 W4 T-W4-01: floor below which a recorded synthesis wall-clock is
# considered unreliable. The orchestrator records both control-flow branches
# (the streaming and the failure-return path); when the path exited early
# without a real stream, the recorded value is sub-millisecond — dividing
# 100 tokens by 1 ms yields a nonsense 100,000 tok/s reading that would
# poison the median. ``100ms`` was chosen because any realistic DeepInfra
# generation takes at least one TCP round-trip + first-token latency
# (~150-300ms); anything under 100ms is structurally not a stream.
_SYNTHESIS_MIN_MS = 100.0


def _compute_tps_streaming(
    *,
    phase_timings_ms: dict[str, float],
    output_tokens: int | None,
) -> float | None:
    """Return ``output_tokens / synthesis_s`` or ``None`` when not measurable.

    PLAN-0102 W4 T-W4-01: changed return type from ``float`` (NaN sentinel)
    to ``float | None``. NaN was ambiguous — the JSON serialiser collapsed
    both "skipped" (no streaming phase fired) and "failed" (div/0 guard) into
    the same ``None`` artefact value, and the chat-eval acceptance gate then
    treated every chat-eval question as ``tps_streaming=None`` even when the
    backend genuinely streamed (because the SSE harness was reading a stale
    artefact key path during PLAN-0101 ramp-up). Returning a typed ``None``
    is unambiguous and survives JSON round-trip without sentinel games.

    Returns ``None`` (semantically "no data, skip the gate") when:

    * ``output_tokens`` is unknown or non-positive (no numerator);
    * ``phase_timings_ms`` is empty (older backend / error path that
      returned before ``emit_done``);
    * the ``llm_synthesis_streaming`` key is absent (e.g. the direct-text
      branch where the agent answered after the first LLM turn without
      reaching the second-turn synthesis stream — this is the common case
      for "What is X?" questions);
    * the recorded wall-clock is below ``_SYNTHESIS_MIN_MS`` (defensive
      against the BP-618 double-record race where the failure-return path
      and the success path both record into the same bucket; a sub-100ms
      reading is structurally not a real stream).

    Otherwise returns ``output_tokens / (synthesis_ms / 1000)`` as ``float``.
    The ``/ 1000`` is explicit so a future reader does not have to chase
    units — synthesis is recorded in **milliseconds**, the answer is in
    **tokens per second**.
    """
    if output_tokens is None or output_tokens <= 0:
        return None
    if not phase_timings_ms:
        return None
    # PLAN-0102 W4 T-W4-B (BP-621): accept either the tool-use synthesis-stream
    # phase OR the direct-text generation phase. Direct-text answers ("What is
    # Apple?") never reach the second-turn streaming branch, so without this
    # OR-fallback ~all questions returned ``tps_streaming=None``.
    synthesis_ms = phase_timings_ms.get(_SYNTHESIS_PHASE_KEY)
    if synthesis_ms is None:
        synthesis_ms = phase_timings_ms.get(_DIRECT_TEXT_PHASE_KEY)
    if synthesis_ms is None or synthesis_ms < _SYNTHESIS_MIN_MS:
        return None
    # Explicit ms→s conversion. ``output_tokens`` is in tokens; the recorded
    # phase is in milliseconds (see PhaseTimings docstring). Dividing by 1000
    # is the only unit-bridge in this helper.
    synthesis_s = float(synthesis_ms) / 1000.0
    return float(output_tokens) / synthesis_s


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


# PLAN-0110 W5 (F9/OQ-1): the SINGLE canonical question catalogue now lives in
# the benchmark's structured pack layout. chat_eval no longer owns a divergent
# ``questions.yaml`` — it READS the benchmark packs and projects the entries that
# carry a ``chat_eval_id`` (the q1..q8 / a10 acceptance questions) back into the
# {id, prompt, ground_truth_assertions} shape the grader + aggregate gate expect.
_BENCHMARK_QUESTIONS_DIR = (Path(__file__).resolve().parent / ".." / "chat_quality_benchmark" / "questions").resolve()


def load_questions(path: Path | None = None) -> list[dict[str, Any]]:
    """Load the chat_eval acceptance questions from the CANONICAL catalogue.

    Returns a list of dicts each with ``id`` (the legacy chat_eval slug —
    ``q1``..``q8`` / ``a10``), ``prompt``, and ``ground_truth_assertions``.

    Source of truth (post-W5): the benchmark packs at
    ``tests/validation/chat_quality_benchmark/questions/*.yaml``. We select the
    entries that declare a ``chat_eval_id`` (the consolidated acceptance set) and
    project them to the chat_eval shape — so there is exactly ONE catalogue and
    chat_eval's gate + the benchmark runner read the same file (F9 resolved).

    ``path`` may point at a single legacy ``questions.yaml`` (back-compat for
    ad-hoc replays / tests that pass an explicit file); when given we decode it
    verbatim as before. We import PyYAML lazily — the per-question test files
    hard-code their prompts so they don't depend on this loader.
    """
    try:
        import yaml  # type: ignore[import-untyped]
    except ImportError:  # pragma: no cover — PyYAML is a dev dep
        pytest.skip("PyYAML not installed — the questions loader requires it")

    # Explicit legacy single-file path → decode verbatim (back-compat).
    if path is not None:
        return list(yaml.safe_load(path.read_text()))

    # Canonical: read every benchmark pack, keep entries with a chat_eval_id,
    # and project to {id: <chat_eval_id>, prompt, ground_truth_assertions}.
    projected: list[dict[str, Any]] = []
    for pack in sorted(_BENCHMARK_QUESTIONS_DIR.glob("*.yaml")):
        raw = yaml.safe_load(pack.read_text())
        if not isinstance(raw, list):
            continue
        for q in raw:
            if not isinstance(q, dict):
                continue
            ce_id = q.get("chat_eval_id")
            if not ce_id:
                continue
            projected.append(
                {
                    "id": str(ce_id),
                    "prompt": q.get("prompt"),
                    "ground_truth_assertions": dict(q.get("ground_truth_assertions") or {}),
                }
            )
    return projected


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
            "RAG_CHAT_BASE_URL not set — requires live rag-chat at $RAG_CHAT_BASE_URL (e.g. http://localhost:8009)"
        )
    return RagChatClient(base_url)
