/**
 * __tests__/workspace-share-lib.test.ts — Pure encode/decode unit tests
 *
 * WHY THIS EXISTS: encodeWorkspace + decodeWorkspace are the lowest-level
 * building blocks of the share-via-URL feature. A bug here corrupts every
 * shared workspace. Pure unit tests (no React, no DOM) verify the round-trip
 * invariant and the edge cases that the component-level tests can't easily
 * cover (corrupted input, URL-safe charset, exact size boundaries).
 *
 * COVERAGE:
 *   - encode → decode round-trip preserves the workspace exactly
 *   - encoded tokens use ONLY URL-safe characters (no +, /, =)
 *   - decode returns null for empty / corrupted / non-JSON input
 *   - decode returns null when the parsed JSON lacks required shape fields
 *   - MAX_TOKEN_CHARS constant has a sensible value (sanity check)
 *
 * DESIGN REFERENCE: PLAN-0051 §T-C-3-07
 */

import { describe, it, expect } from "vitest";
import {
  decodeWorkspace,
  encodeWorkspace,
  MAX_TOKEN_CHARS,
} from "@/lib/workspace-share";
import type { WorkspaceConfig } from "@/contexts/WorkspaceContext";

// ── Sample fixtures ──────────────────────────────────────────────────────────

const SAMPLE: WorkspaceConfig = {
  id: "ws-share-test",
  name: "Share Test",
  rows: [
    { panels: [{ id: "p-a", type: "chart" }, { id: "p-b", type: "news" }] },
    { panels: [{ id: "p-c", type: "fundamentals" }] },
  ],
  panelSizes: [[60, 40], [100]],
};

// ── Round-trip ──────────────────────────────────────────────────────────────

describe("encodeWorkspace + decodeWorkspace — round-trip", () => {
  it("preserves the workspace exactly through encode → decode", () => {
    const token = encodeWorkspace(SAMPLE);
    const decoded = decodeWorkspace(token);
    // WHY toEqual (not toBe): toBe checks identity (same object reference),
    // toEqual checks deep structural equality which is what we want for a
    // round-trip test. The decoded object is a fresh JSON.parse result.
    expect(decoded).toEqual(SAMPLE);
  });

  it("preserves nested arrays (rows + panels + panelSizes)", () => {
    const token = encodeWorkspace(SAMPLE);
    const decoded = decodeWorkspace(token);
    expect(decoded?.rows[0].panels[0].type).toBe("chart");
    expect(decoded?.panelSizes?.[0]).toEqual([60, 40]);
  });
});

// ── URL-safe charset ────────────────────────────────────────────────────────

describe("encodeWorkspace — URL-safe charset", () => {
  it("never includes +, /, or = in the encoded token", () => {
    const token = encodeWorkspace(SAMPLE);
    // WHY regex test (not includes): this catches each forbidden char in one
    // assertion and gives a clear failure message. Using `not.toMatch` would
    // produce a less descriptive failure.
    expect(token).not.toMatch(/[+/=]/);
  });

  it("uses only base64url alphabet (A-Z, a-z, 0-9, -, _)", () => {
    const token = encodeWorkspace(SAMPLE);
    // WHY anchored regex: the entire token must be in the allowed alphabet.
    // A single rogue character would fail this regex.
    expect(token).toMatch(/^[A-Za-z0-9_-]+$/);
  });
});

// ── Decode failure modes ────────────────────────────────────────────────────

describe("decodeWorkspace — failure modes", () => {
  it("returns null for an empty string", () => {
    expect(decodeWorkspace("")).toBeNull();
  });

  it("returns null for a too-short string", () => {
    expect(decodeWorkspace("ab")).toBeNull();
  });

  it("returns null for non-base64 garbage", () => {
    // WHY this exact string: contains chars not in the base64url alphabet
    // AND is long enough to pass the length check. Forces atob to fail.
    expect(decodeWorkspace("***not-valid-base64***")).toBeNull();
  });

  it("returns null when decoded JSON is missing required fields", () => {
    // WHY hand-craft a token: encode an object that's syntactically valid JSON
    // but doesn't match WorkspaceConfig shape (no rows). decodeWorkspace's
    // shape guard should reject it.
    const invalidJson = JSON.stringify({ name: "missing-rows" });
    const bytes = new TextEncoder().encode(invalidJson);
    const binary = String.fromCharCode.apply(null, Array.from(bytes));
    const b64 = btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
    expect(decodeWorkspace(b64)).toBeNull();
  });

  it("returns null when decoded JSON has a non-array rows field", () => {
    // WHY: shape guard requires rows to be an Array. An object would slip past
    // a shallow `"rows" in parsed` check; the explicit Array.isArray guard
    // catches it.
    const invalidShape = JSON.stringify({ name: "x", rows: "not-an-array" });
    const bytes = new TextEncoder().encode(invalidShape);
    const binary = String.fromCharCode.apply(null, Array.from(bytes));
    const b64 = btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
    expect(decodeWorkspace(b64)).toBeNull();
  });
});

// ── Constants ───────────────────────────────────────────────────────────────

describe("MAX_TOKEN_CHARS", () => {
  it("is 4096 (URL-safe ceiling for shared platforms)", () => {
    // WHY assert exact value: changing this constant has UX implications
    // (some users' shares would suddenly start failing). Forcing this test
    // to fail when the value changes ensures the change is intentional.
    expect(MAX_TOKEN_CHARS).toBe(4096);
  });
});
