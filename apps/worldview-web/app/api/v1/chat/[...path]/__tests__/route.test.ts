/**
 * app/api/v1/chat/[...path]/__tests__/route.test.ts — streaming chat proxy.
 *
 * WHAT THESE GUARD (Wave 3 — streaming-paint bug):
 * The route handler exists to take the chat SSE endpoints OFF the
 * next.config rewrite path, whose gzip compression buffered entire streams
 * (measured live: all 58 lines of an 11s stream delivered in one burst at
 * stream end). The contract pinned here:
 *
 *   1. The request is forwarded to ${API_GATEWAY_URL}/v1/chat/<path> with
 *      method, Authorization, Content-Type, and body intact.
 *   2. The response body is the UPSTREAM STREAM OBJECT ITSELF (zero-copy
 *      pipe) — never an awaited/buffered copy.
 *   3. `Cache-Control: no-cache, no-transform` is set — `no-transform` is
 *      the documented escape hatch that makes Next's compression middleware
 *      skip gzip for this response (the root cause of the buffering).
 *   4. Upstream failures map to 502 (gateway unreachable) and client aborts
 *      to 499 — never an unhandled rejection.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

import { POST, GET } from "../route";

// Helper: the Next 15 catch-all context (params is a Promise).
function ctx(path: string[]) {
  return { params: Promise.resolve({ path }) };
}

describe("chat streaming proxy route", () => {
  beforeEach(() => {
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
  });

  it("forwards POST to ${API_GATEWAY_URL}/v1/chat/<path> with auth + body, streams the upstream body back", async () => {
    vi.stubEnv("API_GATEWAY_URL", "http://gateway:8000");

    // A real ReadableStream stands in for the upstream SSE body — the
    // handler must return THIS object, not a buffered copy.
    const upstreamBody = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(new TextEncoder().encode("event: token\n"));
        controller.close();
      },
    });
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(upstreamBody, {
        status: 200,
        headers: { "content-type": "text/event-stream; charset=utf-8" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const req = new Request("http://localhost:3001/api/v1/chat/stream", {
      method: "POST",
      headers: {
        authorization: "Bearer tok-abc",
        "content-type": "application/json",
      },
      body: JSON.stringify({ message: "hi", thread_id: "t-1" }),
    });

    const res = await POST(req, ctx(["stream"]));

    // 1. Faithful upstream forwarding.
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("http://gateway:8000/v1/chat/stream");
    expect(init.method).toBe("POST");
    expect(new Headers(init.headers).get("authorization")).toBe(
      "Bearer tok-abc",
    );
    expect(init.body).toBe(JSON.stringify({ message: "hi", thread_id: "t-1" }));

    // 2. Streaming pass-through: the handler's body IS the upstream stream.
    expect(res.status).toBe(200);
    expect(res.headers.get("content-type")).toBe(
      "text/event-stream; charset=utf-8",
    );

    // 3. THE load-bearing header — no-transform disables Next's gzip
    //    (the buffering that broke live streaming for browsers).
    expect(res.headers.get("cache-control")).toBe("no-cache, no-transform");
    expect(res.headers.get("x-accel-buffering")).toBe("no");

    // The streamed bytes flow through unchanged.
    const text = await res.text();
    expect(text).toBe("event: token\n");
  });

  it("delivers SSE frames INCREMENTALLY — each upstream chunk surfaces as its own read (no buffering)", async () => {
    // REGRESSION GUARD (chat-streaming verification, 2026-06-15):
    // The whole reason this route exists is to stream frames the instant S9
    // emits them. A faithful pass-through must NOT coalesce separately-emitted
    // upstream chunks into one buffered blob. We model S8's real frame cadence
    // (status → token → done as DISTINCT enqueues) and assert the consumer
    // reads them back as DISTINCT chunks in order — proving the body is the
    // live upstream stream, not an awaited/concatenated copy.
    vi.stubEnv("API_GATEWAY_URL", "http://gateway:8000");

    const enc = new TextEncoder();
    // Three frames enqueued as three separate controller.enqueue() calls —
    // exactly how S8/sse-starlette pushes one event-block at a time.
    const frames = [
      "event: status\ndata: {\"step\": \"loading_context\"}\n\n",
      "event: token\ndata: {\"text\": \"Hello\"}\n\n",
      "event: done\ndata: {\"type\": \"done\"}\n\n",
    ];
    const upstreamBody = new ReadableStream<Uint8Array>({
      start(controller) {
        for (const f of frames) controller.enqueue(enc.encode(f));
        controller.close();
      },
    });
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(upstreamBody, {
          status: 200,
          headers: { "content-type": "text/event-stream; charset=utf-8" },
        }),
      ),
    );

    const req = new Request("http://localhost:3001/api/v1/chat/stream", {
      method: "POST",
      headers: { authorization: "Bearer tok", "content-type": "application/json" },
      body: JSON.stringify({ message: "hi", thread_id: "t-1" }),
    });
    const res = await POST(req, ctx(["stream"]));

    // Read the response body chunk-by-chunk. A buffering proxy would either
    // return one combined chunk OR (worse) gzip-wrap it; a streaming proxy
    // surfaces each enqueued frame as its own read in emission order.
    expect(res.body).not.toBeNull();
    const reader = res.body!.getReader();
    const dec = new TextDecoder();
    const received: string[] = [];
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      received.push(dec.decode(value, { stream: true }));
    }

    // Each frame arrives as its own read, in order — incremental delivery.
    expect(received).toEqual(frames);
    // And the body was never gzip-transformed (no-transform escape hatch).
    expect(res.headers.get("cache-control")).toBe("no-cache, no-transform");
  });

  it("proxies nested paths (proposals/{id}/confirm) segment-by-segment", async () => {
    vi.stubEnv("API_GATEWAY_URL", "http://gateway:8000");
    const fetchMock = vi
      .fn()
      .mockResolvedValue(new Response("{}", { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    const req = new Request(
      "http://localhost:3001/api/v1/chat/proposals/p-1/confirm",
      { method: "POST", body: "{}" },
    );
    await POST(req, ctx(["proposals", "p-1", "confirm"]));

    expect(fetchMock.mock.calls[0][0]).toBe(
      "http://gateway:8000/v1/chat/proposals/p-1/confirm",
    );
  });

  it("passes non-2xx upstream statuses through verbatim (S9 stays the authority)", async () => {
    vi.stubEnv("API_GATEWAY_URL", "http://gateway:8000");
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ detail: "unauthorized" }), {
          status: 401,
          headers: { "content-type": "application/json" },
        }),
      ),
    );

    const req = new Request("http://localhost:3001/api/v1/chat/stream", {
      method: "POST",
      body: "{}",
    });
    const res = await POST(req, ctx(["stream"]));
    // useChatStream maps 401 → "Session expired" — the proxy must not mask it.
    expect(res.status).toBe(401);
  });

  it("maps an unreachable gateway to 502 (never an unhandled rejection)", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockRejectedValue(new TypeError("fetch failed")),
    );

    const req = new Request("http://localhost:3001/api/v1/chat/stream", {
      method: "POST",
      body: "{}",
    });
    const res = await POST(req, ctx(["stream"]));
    // ≥500 → useChatStream shows "Server error — please try again."
    expect(res.status).toBe(502);
  });

  it("GET passes through for forward compatibility", async () => {
    vi.stubEnv("API_GATEWAY_URL", "http://gateway:8000");
    const fetchMock = vi
      .fn()
      .mockResolvedValue(new Response("{}", { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    const req = new Request("http://localhost:3001/api/v1/chat/health");
    const res = await GET(req, ctx(["health"]));
    expect(res.status).toBe(200);
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    // GET must not try to read a request body.
    expect(init.body).toBeUndefined();
  });
});
