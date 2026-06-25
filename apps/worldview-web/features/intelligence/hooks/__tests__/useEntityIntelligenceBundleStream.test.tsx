/**
 * useEntityIntelligenceBundleStream.test.tsx — PLAN-0099 W4 follow-up R2
 *
 * WHY THIS EXISTS: the SSE consumer logic (fetch + ReadableStream + line
 * parser + cache hydration) is the single most fragile part of the
 * streaming bundle path. A regression here silently breaks per-widget
 * cache hydration and the page falls back to firing N independent
 * fetches — exactly the cost the bundle was built to eliminate.
 *
 * Mirrors the pattern in `features/chat/hooks/__tests__/useChatStream.test.tsx`:
 * hand-rolled `ReadableStream`-shaped reader so we can control framing
 * precisely without jsdom's flaky implementation.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

import { useEntityIntelligenceBundleStream } from "../useEntityIntelligenceBundleStream";

// ── Mocks ─────────────────────────────────────────────────────────────────────

// useAuth is only needed for the accessToken value — stub it so the hook's
// enabled-gate flips true without dragging in NextAuth / cookies.
vi.mock("@/hooks/useAuth", () => ({
  useAuth: () => ({ accessToken: "test-token" }),
}));

// ── Helpers ───────────────────────────────────────────────────────────────────

/**
 * makeReader — minimal ReadableStream-like reader emitting SSE frames as
 * UTF-8 chunks. Once frames are exhausted, signals `{done: true}`.
 *
 * Why a deferred queue: matches the pattern in useChatStream tests so
 * future test authors can copy/paste between them without surprises.
 */
function makeReader(frames: string[]) {
  const encoder = new TextEncoder();
  let i = 0;
  return {
    read: () => {
      if (i >= frames.length) {
        return Promise.resolve({ done: true, value: undefined });
      }
      const chunk = encoder.encode(frames[i]);
      i += 1;
      return Promise.resolve({ done: false, value: chunk });
    },
    cancel: vi.fn().mockResolvedValue(undefined),
  };
}

/**
 * wrapper — TanStack QueryClientProvider needed by useQueryClient inside
 * the hook. A fresh client per test prevents cache leakage across cases.
 */
function makeWrapper() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const Wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
  return { Wrapper, qc };
}

// ── Tests ─────────────────────────────────────────────────────────────────────

const ENTITY_ID = "01930000-0000-7000-8000-000000000001";

beforeEach(() => {
  vi.useRealTimers();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("useEntityIntelligenceBundleStream", () => {
  it("hydrates per-widget caches as legs arrive and marks allDone on 'done'", async () => {
    // Wire frames: one event per leg, then a done event. Each block ends
    // with the spec-mandated double newline to terminate the SSE block.
    const frames = [
      'event: leg\ndata: {"leg":"detail","value":{"canonical_name":"Apple"}}\n\n',
      'event: leg\ndata: {"leg":"brief","value":{"narrative":"hi"}}\n\n',
      'event: leg\ndata: {"leg":"paths","value":{"paths":[]}}\n\n',
      'event: leg\ndata: {"leg":"intelligence_summary","value":{"health_score":0.7}}\n\n',
      // graph_d2 left out intentionally to also assert the hook tolerates a
      // missing leg (the streaming variant may drop legs that fail outright).
      'event: done\ndata: {"partial":false}\n\n',
    ];
    const reader = makeReader(frames);
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      statusText: "OK",
      body: { getReader: () => reader },
    });
    vi.stubGlobal("fetch", fetchMock);

    const { Wrapper, qc } = makeWrapper();
    const { result } = renderHook(
      () => useEntityIntelligenceBundleStream(ENTITY_ID),
      { wrapper: Wrapper },
    );

    // Wait for the stream to complete.
    await waitFor(() => expect(result.current.allDone).toBe(true));

    expect(result.current.error).toBeNull();
    // 4 legs arrived (graph_d2 was omitted from the script).
    expect(result.current.legsLoaded.size).toBe(4);
    expect(result.current.legsLoaded.has("detail")).toBe(true);
    expect(result.current.legsLoaded.has("brief")).toBe(true);
    expect(result.current.legsLoaded.has("paths")).toBe(true);
    expect(result.current.legsLoaded.has("intelligence_summary")).toBe(true);

    // Cache hydration: each leg's value was written under the exact key the
    // matching widget reads. Same keys as useEntityIntelligenceBundle.ts.
    expect(qc.getQueryData(["entity-detail", ENTITY_ID])).toEqual({
      canonical_name: "Apple",
    });
    expect(qc.getQueryData(["entity-paths", ENTITY_ID, {}])).toEqual({
      paths: [],
    });
    expect(qc.getQueryData(["entity-intelligence", ENTITY_ID])).toEqual({
      health_score: 0.7,
    });

    // Verify the request shape: GET with bearer + Accept SSE.
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe(`/api/v1/entities/${ENTITY_ID}/intelligence-bundle/stream`);
    expect(init.method).toBe("GET");
    expect(init.headers.Authorization).toBe("Bearer test-token");
    expect(init.headers.Accept).toBe("text/event-stream");
  });

  it("does NOT hydrate cache for legs with null value (failed legs)", async () => {
    // A failed leg arrives as {leg, value: null, error: ...}. The hook
    // must still record it in legsLoaded (so the caller can render the
    // error state) but MUST NOT write null into the cache — otherwise the
    // widget treats the cache as resolved and skips its own retry fetch.
    const frames = [
      'event: leg\ndata: {"leg":"detail","value":null,"error":"TimeoutException"}\n\n',
      'event: done\ndata: {"partial":false}\n\n',
    ];
    const reader = makeReader(frames);
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        statusText: "OK",
        body: { getReader: () => reader },
      }),
    );

    const { Wrapper, qc } = makeWrapper();
    const { result } = renderHook(
      () => useEntityIntelligenceBundleStream(ENTITY_ID),
      { wrapper: Wrapper },
    );

    await waitFor(() => expect(result.current.allDone).toBe(true));

    // Failed leg is recorded as loaded (attempted).
    expect(result.current.legsLoaded.has("detail")).toBe(true);
    // But NOT hydrated — getQueryData returns undefined (never been set).
    expect(qc.getQueryData(["entity-detail", ENTITY_ID])).toBeUndefined();
  });
});
