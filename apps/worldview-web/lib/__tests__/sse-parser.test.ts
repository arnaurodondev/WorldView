/**
 * lib/__tests__/sse-parser.test.ts — parseSSELine contract tests.
 *
 * WHY NOW (QA Wave-3 closeout, 2026-06-11): the parser had no dedicated test
 * file, and a missing case — CRLF line termination — broke the ENTIRE chat
 * streaming surface in production. sse-starlette (S8) emits "event: x\r\n";
 * both stream readers split on "\n", so every line reached the parser with a
 * trailing "\r" and no event name ever matched. These tests pin the full
 * line-level contract including the CR-strip rule.
 */

import { describe, it, expect } from "vitest";
import { parseSSELine } from "@/lib/sse-parser";

describe("parseSSELine", () => {
  // ── Canonical LF-terminated lines (pre-existing behaviour) ────────────────
  it("parses an event: line into its type", () => {
    expect(parseSSELine("event: tool_call")).toEqual({
      type: "tool_call",
      data: "tool_call",
    });
  });

  it("parses a data: line as the default 'message' type", () => {
    expect(parseSSELine('data: {"text": "hi"}')).toEqual({
      type: "message",
      data: '{"text": "hi"}',
    });
  });

  it("keeps colons inside the value intact", () => {
    expect(parseSSELine("data: https://example.com/x")?.data).toBe(
      "https://example.com/x",
    );
  });

  it("ignores blank lines, comments, and colon-less lines", () => {
    expect(parseSSELine("")).toBeNull();
    expect(parseSSELine(": keep-alive")).toBeNull();
    expect(parseSSELine("garbage-without-colon")).toBeNull();
  });

  it("ignores id:/retry: fields", () => {
    expect(parseSSELine("id: 42")).toBeNull();
    expect(parseSSELine("retry: 3000")).toBeNull();
  });

  // ── CRLF wire format (the QA Wave-3 regression) ───────────────────────────
  it("strips a trailing CR from event: lines (CRLF wire format)", () => {
    expect(parseSSELine("event: token\r")).toEqual({
      type: "token",
      data: "token",
    });
  });

  it("strips a trailing CR from data: lines (CRLF wire format)", () => {
    expect(parseSSELine('data: {"text": "hi"}\r')).toEqual({
      type: "message",
      data: '{"text": "hi"}',
    });
  });

  it("treats a lone CR as a blank line (CRLF block terminator)", () => {
    expect(parseSSELine("\r")).toBeNull();
  });

  it("treats a CR-terminated comment as a comment", () => {
    expect(parseSSELine(": ping - 2026-06-11\r")).toBeNull();
  });

  it("strips only ONE trailing CR (payload bytes stay intact)", () => {
    // A payload that itself ends with an escaped CR sequence is untouched —
    // only the single wire-format CR is removed.
    expect(parseSSELine('data: {"text": "line\\r"}\r')?.data).toBe(
      '{"text": "line\\r"}',
    );
  });
});
