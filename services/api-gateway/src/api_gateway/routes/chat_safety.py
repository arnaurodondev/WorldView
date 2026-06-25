"""Input-safety / prompt-injection block presentation helpers (S9).

WHY this module exists
----------------------
When a chat request trips the S8 (rag-chat) Layer-2 input-safety classifier
(prompt injection / PII), the *block itself is correct and must be preserved*:
no synthesis runs, no system prompt leaks, tools=[].  The problem this module
fixes is purely **presentation**: S8 surfaces that block as either

  - sync path  → HTTP 400 with body ``{"detail": "[PROMPT_INJECTION] ..."}``
    (a raw classifier string, or in some envelopes an empty answer field), or
  - SSE path   → ``event: error`` with ``data: {"code": "INPUT_REJECTED",
    "message": "[PROMPT_INJECTION] ..."}``

In both cases the chat UI renders **nothing the user can read** — an empty 400
reads like an outage.  This helper does NOT weaken the block; it only detects an
already-decided injection rejection and rewrites the *response body* to a clear,
worded message while keeping the machine-readable error ``code`` stable so
existing clients keep working.

File boundary: S9 (api-gateway) only.  We never re-run the classifier or change
the blocking decision — we only re-present a block that S8 already made.
"""

from __future__ import annotations

import json

# Stable machine-readable code clients already key off of.  We deliberately keep
# this UNCHANGED so the frontend / eval harness that branch on the code continue
# to recognise the rejection — only the human-readable body becomes informative.
INJECTION_BLOCK_CODE = "INPUT_REJECTED"

# Worded, user-facing explanation for a blocked input.  Concise, non-leaky
# (does not echo the attempted instruction back), and steers the user toward a
# legitimate question.  This is what the chat surface renders instead of an
# empty body.
INJECTION_BLOCK_MESSAGE = (
    "Your request was blocked by our input safety check and was not processed. "
    "Please rephrase without instructions that attempt to override the assistant, "
    "and I'll be happy to help with a market or portfolio question."
)

# Marker substrings S8 uses to signal an input-safety rejection.  We match on the
# stable error code AND the ``[PROMPT_INJECTION]`` / ``[PII_DETECTED]`` prefixes
# the classifier emits, so detection is robust to either envelope shape.
_BLOCK_MARKERS = (
    INJECTION_BLOCK_CODE,
    "PROMPT_INJECTION",
    "PII_DETECTED",
)


def _text_signals_injection_block(text: str) -> bool:
    """Return True if a response/error text indicates an input-safety block.

    Pure string test over already-extracted text — no JSON parsing here so it can
    be reused for raw bodies and for parsed SSE ``data`` payloads alike.
    """
    if not text:
        return False
    upper = text.upper()
    return any(marker in upper for marker in _BLOCK_MARKERS)


def is_injection_block_response(status_code: int, body: bytes) -> bool:
    """Detect a sync ``/v1/chat`` injection/PII block in the S8 response.

    The block is signalled by a 4xx status (S8 uses 400 for PII/injection) whose
    body carries one of the safety markers.  We accept any 4xx (not strictly 400)
    so a future status tweak on S8 does not silently regress the worded body.

    WHY parse defensively: the body may be a FastAPI ``{"detail": ...}`` envelope,
    a richer ``{"error": {"code": ...}}`` envelope, or a bare string.  We flatten
    it to text and run the marker test, falling back to the raw bytes if JSON
    decoding fails.
    """
    if status_code < 400 or status_code >= 500:
        return False
    if not body:
        return False
    try:
        decoded = body.decode("utf-8", errors="ignore")
    except (UnicodeDecodeError, AttributeError):
        return False
    # Fast path: marker present anywhere in the raw body text (covers detail
    # strings, nested error envelopes, and bare strings without extra parsing).
    return _text_signals_injection_block(decoded)


def build_injection_block_body() -> bytes:
    """Build the worded JSON body for a sync injection block.

    Shape mirrors a normal chat answer (``answer``) so the chat UI renders the
    text, AND carries the stable ``error.code`` so programmatic clients still see
    the rejection.  ``citations`` is empty (a refusal has no sources).
    """
    payload = {
        "answer": INJECTION_BLOCK_MESSAGE,
        "message": INJECTION_BLOCK_MESSAGE,
        "citations": [],
        "blocked": True,
        "error": {"code": INJECTION_BLOCK_CODE, "message": INJECTION_BLOCK_MESSAGE},
    }
    return json.dumps(payload).encode("utf-8")


def rewrite_sse_chunk_if_injection_block(chunk: bytes) -> bytes:
    """Rewrite an SSE chunk so an injection ``event: error`` carries worded text.

    The S8 emitter sends ``event: error\\ndata: {"code": ..., "message": ...}``.
    When the code/message signals an input-safety block we replace the (possibly
    raw or empty) ``message`` with the worded explanation while keeping the
    stable ``code``.  All non-matching chunks pass through unchanged.

    WHY operate at the chunk level: the gateway streams S8's SSE bytes verbatim;
    intercepting only the error frame keeps token streaming untouched and avoids
    buffering the whole response.
    """
    if not chunk:
        return chunk
    try:
        text = chunk.decode("utf-8")
    except UnicodeDecodeError:
        return chunk
    # Only the error event is a candidate; cheap guard before parsing.
    if "event: error" not in text and '"error"' not in text:
        return chunk

    out_lines: list[str] = []
    changed = False
    for line in text.split("\n"):
        # SSE data lines look like ``data: {json}``.  We only rewrite a data line
        # whose JSON payload signals an input-safety block.
        if line.startswith("data:"):
            raw = line[len("data:") :].strip()
            rewritten = _rewrite_error_data_json(raw)
            if rewritten is not None:
                out_lines.append(f"data: {rewritten}")
                changed = True
                continue
        out_lines.append(line)

    if not changed:
        return chunk
    return "\n".join(out_lines).encode("utf-8")


def _rewrite_error_data_json(raw: str) -> str | None:
    """Return a worded JSON string if ``raw`` is an injection-block error payload.

    Returns ``None`` when the payload is not an input-safety block (caller then
    leaves the original line untouched).  Preserves the stable ``code`` and any
    extra keys, only swapping in the worded ``message``.
    """
    if not _text_signals_injection_block(raw):
        return None
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    # Confirm this is really an error frame for an input-safety block (the code
    # OR the message must carry a marker) — avoids touching unrelated payloads
    # that merely mention the word elsewhere.
    code = str(data.get("code", ""))
    message = str(data.get("message", ""))
    if not (_text_signals_injection_block(code) or _text_signals_injection_block(message)):
        return None
    data["code"] = INJECTION_BLOCK_CODE  # keep the stable client-facing code
    data["message"] = INJECTION_BLOCK_MESSAGE  # worded, non-empty body
    return json.dumps(data)


__all__ = [
    "INJECTION_BLOCK_CODE",
    "INJECTION_BLOCK_MESSAGE",
    "build_injection_block_body",
    "is_injection_block_response",
    "rewrite_sse_chunk_if_injection_block",
]
