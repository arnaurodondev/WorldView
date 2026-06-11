/**
 * lib/api/__tests__/client-timeout.test.ts — apiFetch timeout contract (R4 item).
 *
 * WHY: apiFetch previously had NO timeout — a hung S9 connection left the
 * promise pending on browser defaults (~300s). These tests pin:
 *   1. a request exceeding `timeoutMs` rejects with GatewayTimeoutError
 *      (typed, status 408, carries the budget that was exceeded)
 *   2. `timeoutMs: 0` disables the timeout entirely (escape hatch)
 *   3. a caller-initiated abort is NOT remapped to a timeout error —
 *      cancellation must stay distinguishable from a timeout
 *   4. the default budget is wired (a signal is passed to fetch even when
 *      the caller provides none)
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import {
  apiFetch,
  GatewayError,
  GatewayTimeoutError,
  DEFAULT_TIMEOUT_MS,
} from "@/lib/api/_client";

// ── fetch mock that respects AbortSignal ──────────────────────────────────
// Simulates a HUNG connection: the promise never resolves on its own, but
// rejects with the signal's reason when aborted — exactly what the real
// fetch() does for an in-flight request.
function hungFetch(): typeof fetch {
  return vi.fn((_url: RequestInfo | URL, init?: RequestInit) => {
    return new Promise<Response>((_resolve, reject) => {
      const signal = init?.signal;
      if (!signal) return; // no signal → hangs forever (test would time out)
      if (signal.aborted) {
        reject(signal.reason);
        return;
      }
      signal.addEventListener("abort", () => reject(signal.reason));
    });
  }) as unknown as typeof fetch;
}

const realFetch = global.fetch;

beforeEach(() => {
  vi.restoreAllMocks();
});

afterEach(() => {
  global.fetch = realFetch;
});

describe("apiFetch timeout (R4 deferred item)", () => {
  it("rejects with GatewayTimeoutError when the request exceeds timeoutMs", async () => {
    global.fetch = hungFetch();

    // 20ms budget — small enough to keep the test fast, large enough to
    // not race the event loop. AbortSignal.timeout uses NATIVE timers, so
    // vi.useFakeTimers cannot drive it — a tiny real budget is the correct
    // way to test this.
    const promise = apiFetch("/v1/test-hung", { timeoutMs: 20 });

    await expect(promise).rejects.toBeInstanceOf(GatewayTimeoutError);
    await expect(promise).rejects.toMatchObject({
      name: "GatewayTimeoutError",
      status: 408,
      timeoutMs: 20,
    });
  });

  it("GatewayTimeoutError is a GatewayError (existing instanceof guards keep working)", async () => {
    global.fetch = hungFetch();
    await expect(
      apiFetch("/v1/test-hung", { timeoutMs: 20 }),
    ).rejects.toBeInstanceOf(GatewayError);
  });

  it("timeoutMs: 0 disables the timeout (no signal injected)", async () => {
    // A resolving fetch — we only inspect the init it was called with.
    const fetchSpy = vi.fn(
      async (_url: RequestInfo | URL, _init?: RequestInit) =>
        new Response(JSON.stringify({ ok: true }), { status: 200 }),
    );
    global.fetch = fetchSpy as unknown as typeof fetch;

    await apiFetch("/v1/test-ok", { timeoutMs: 0 });

    const init = fetchSpy.mock.calls[0]?.[1];
    // With the timeout disabled and no caller signal, nothing should be wired.
    expect(init?.signal == null).toBe(true);
  });

  it("passes a timeout signal to fetch by default (no caller opt-in needed)", async () => {
    const fetchSpy = vi.fn(
      async (_url: RequestInfo | URL, _init?: RequestInit) =>
        new Response(JSON.stringify({ ok: true }), { status: 200 }),
    );
    global.fetch = fetchSpy as unknown as typeof fetch;

    await apiFetch("/v1/test-default");

    const init = fetchSpy.mock.calls[0]?.[1];
    expect(init?.signal).toBeInstanceOf(AbortSignal);
    // Sanity: the default budget constant is what the module advertises.
    expect(DEFAULT_TIMEOUT_MS).toBe(15_000);
  });

  it("caller-initiated abort is NOT remapped to GatewayTimeoutError", async () => {
    global.fetch = hungFetch();

    const controller = new AbortController();
    const promise = apiFetch("/v1/test-cancelled", {
      signal: controller.signal,
      // Long budget so the timeout cannot win the race in this test.
      timeoutMs: 5_000,
    });
    controller.abort();

    // The plain AbortError must propagate unchanged — TanStack Query treats
    // it as a cancellation (silent), NOT an error state.
    await expect(promise).rejects.toSatisfy(
      (err: unknown) =>
        err instanceof DOMException &&
        err.name === "AbortError" &&
        !(err instanceof GatewayTimeoutError),
    );
  });
});
