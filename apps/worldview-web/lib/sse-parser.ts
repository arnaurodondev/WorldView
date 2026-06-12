/**
 * lib/sse-parser.ts — Shared SSE (Server-Sent Events) line parser.
 *
 * WHY THIS EXISTS (MED-013, FR-5.6):
 * The SSE line-parsing logic was duplicated between:
 *   1. features/chat/hooks/useChatStream.ts — the main chat stream reader
 *   2. features/chat/components/ActionConfirmModal.tsx — the confirm-stream reader
 *
 * Two copies of the same wire-format parser creates protocol drift risk:
 * if the backend changes the event framing (e.g. from "event:" to "e:"),
 * the fix must land in two places. This module is the single canonical
 * parser. Both consumers import from here (migration happens in W6 when
 * useChatStream.ts and ActionConfirmModal.tsx are refactored).
 *
 * WIRE FORMAT (RFC 8895 — text/event-stream):
 *   event: <type>\n
 *   data: <payload>\n
 *   \n                  ← blank line terminates the event block
 *
 * Comments (lines starting with ":") are keep-alive pings and are ignored.
 * Lines without a colon (bare field names) are ignored per spec.
 *
 * USAGE:
 *   const event = parseSSELine("event: tool_call");
 *   // → { type: "tool_call", data: "" }
 *
 *   const event = parseSSELine("data: {\"text\": \"hello\"}");
 *   // → { type: "message", data: "{\"text\": \"hello\"}" }
 *
 *   parseSSELine("") → null
 *   parseSSELine(": keep-alive") → null
 *   parseSSELine("unrecognized-without-colon") → null
 *
 * NOTE: This parser handles individual lines, not full event blocks. The
 * caller (useChatStream / ActionConfirmModal) is responsible for accumulating
 * `event:` + `data:` lines across a block boundary and resetting between events.
 * That stateful orchestration stays in the hook/component because it is tightly
 * coupled to the streaming state machine.
 */

// ── Types ─────────────────────────────────────────────────────────────────────

/**
 * SSEEvent — parsed representation of a single SSE field line.
 *
 * WHY not a discriminated union: the type field is an arbitrary string from
 * the server. A strict union would require updating this file every time
 * the backend adds a new event type. A plain string is more forward-compatible.
 *
 * WHY include data in the line-level struct (not just at block level):
 * parseSSELine returns the value for ONE field line. For `data:` lines, the
 * value is the payload string. For `event:` lines, the value is the event name
 * (stored in `type`). Having a uniform shape lets callers pattern-match on
 * the returned object without a separate branch for "is this an event: or data: line".
 */
export interface SSEEvent {
  /**
   * The SSE event type.
   *   - For `event: foo` lines: "foo"
   *   - For `data: bar` lines (no preceding event:): "message" (RFC 8895 default)
   */
  type: string;
  /**
   * The field value.
   *   - For `data: payload` lines: the payload string (may be JSON)
   *   - For `event: foo` lines: the event name (same as `type`)
   *   - Empty string when the field had no value (e.g. bare "data:\n")
   */
  data: string;
}

// ── Parser ────────────────────────────────────────────────────────────────────

/**
 * parseSSELine — parse one line from a text/event-stream body.
 *
 * Returns null for lines that should be ignored (empty, comments, no colon).
 * Returns an SSEEvent for `event:` and `data:` field lines.
 *
 * WHY this function is pure (no side effects):
 * Purity makes it trivially testable — no mock fetch, no AbortController,
 * no React context needed. The test suite can cover all field types with
 * straightforward assertions.
 *
 * @param line — one raw line from the SSE body (no trailing \n).
 * @returns SSEEvent | null
 */
export function parseSSELine(line: string): SSEEvent | null {
  // ── Rule 0: strip ONE trailing CR (QA Wave-3 closeout, 2026-06-11) ──────
  // The SSE spec (WHATWG event-stream) allows lines to be terminated by
  // CRLF, LF, or CR — and sse-starlette (S8 rag-chat) emits CRLF. Both
  // stream readers split the byte stream on "\n" only, so every line
  // arrives here with a trailing "\r":   "event: token\r" / "data: {...}\r".
  // Without this strip the event name became "token\r", NO event ever
  // matched ("done" included), zero tokens painted, and the reader-exhausted
  // detector fired a false "Response interrupted" banner under an answer
  // that only appeared via the post-stream thread refetch (observed live on
  // the production container, 2026-06-11). Stripping exactly one CR keeps
  // payload bytes intact (a JSON payload can never legitimately END with a
  // raw CR — JSON strings escape control characters).
  if (line.endsWith("\r")) line = line.slice(0, -1);

  // ── Rule 1: blank line ─────────────────────────────────────────────────
  // Blank lines are event-block terminators in the SSE spec. The caller
  // handles block boundaries; this function ignores them at the line level.
  if (line === "") return null;

  // ── Rule 2: comment / keep-alive ──────────────────────────────────────
  // Lines starting with ":" are SSE comments (typically keep-alive pings
  // like ": heartbeat"). Ignore per RFC 8895 §9.2.
  if (line.startsWith(":")) return null;

  // ── Rule 3: field:value split ─────────────────────────────────────────
  // Find the FIRST colon only. The value may itself contain colons
  // (e.g. "data: https://example.com/path" or "data: {\"url\":\"...\"}").
  const colonIndex = line.indexOf(":");
  if (colonIndex === -1) {
    // WHY null (not error): The SSE spec says a line without a colon is a
    // field with an empty value and the field name as its own name. In
    // practice this is rare and not meaningful for our wire format — treat
    // as a no-op to avoid false-positive returns.
    return null;
  }

  const fieldName = line.slice(0, colonIndex);
  // WHY slice(colonIndex + 1): RFC 8895 §9.2 says if there is a U+0020 SPACE
  // character immediately after the colon, it must be stripped. We slice one
  // past the colon and then trimStart() to handle both "field:value" (no space,
  // some implementations) and "field: value" (with space, canonical).
  const fieldValue = line.slice(colonIndex + 1).trimStart();

  // ── event: field ──────────────────────────────────────────────────────
  if (fieldName === "event") {
    // The event name becomes the type for the upcoming data line(s).
    // We return it as both type AND data so callers that only look at `type`
    // get the event name without needing to inspect `data`.
    return { type: fieldValue, data: fieldValue };
  }

  // ── data: field ───────────────────────────────────────────────────────
  if (fieldName === "data") {
    // Default event type is "message" per RFC 8895 §9.2.3.
    // The caller is responsible for associating the pending event name from a
    // preceding `event:` line with this data payload — that stateful
    // association lives in the streaming loop.
    return { type: "message", data: fieldValue };
  }

  // ── Other fields (id:, retry:) ────────────────────────────────────────
  // We do not handle `id:` (last-event-id) or `retry:` (reconnect delay)
  // because the chat stream is a POST (no EventSource reconnect logic).
  // Return null so the caller ignores these lines.
  return null;
}
