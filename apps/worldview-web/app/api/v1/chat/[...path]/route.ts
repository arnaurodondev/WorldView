/**
 * app/api/v1/chat/[...path]/route.ts — Streaming-safe proxy for ALL chat
 * endpoints (`/api/v1/chat/stream`, `/api/v1/chat/entity-context`,
 * `/api/v1/chat/proposals/{id}/confirm`, and any future chat routes).
 *
 * WHY THIS EXISTS (frontend-rework Wave 3 — streaming-paint bug):
 * Every other `/api/*` request reaches S9 through the `rewrites()` proxy in
 * next.config.ts. That proxy is fine for request/response JSON — but it is
 * BROKEN for Server-Sent Events in production, and the failure mode is
 * invisible in curl-based testing:
 *
 *   1. Browsers always send `Accept-Encoding: gzip, br` (fetch() cannot
 *      override it — Accept-Encoding is a forbidden request header).
 *   2. The Next.js production server has `compress: true` (default), so the
 *      proxied `text/event-stream` response gets wrapped in gzip.
 *   3. zlib output is BUFFERED: compressed bytes are only flushed when the
 *      internal buffer fills or the stream ends. SSE events are tiny, so the
 *      buffer never fills mid-stream.
 *
 * MEASURED LIVE (2026-06-11, worldview-web container, port 3001):
 *   - curl WITHOUT Accept-Encoding → events arrive incrementally (tool_call
 *     at t=8.4s, tokens at t=24.9s, done at t=53.3s). Looks healthy.
 *   - curl WITH `Accept-Encoding: gzip` (= what every real browser sends) →
 *     response carries `Content-Encoding: gzip` and ALL 58 lines of an
 *     11-second stream arrive in ONE burst at t=10.968s — the user stares at
 *     a blank bubble for the whole answer, then everything pops in at once.
 *     No token-by-token text, no live tool indicators: exactly the reported
 *     "streaming is not working" symptom. And when that buffered connection
 *     dies mid-stream, the reader exhausts with ZERO delivered events →
 *     the "Response interrupted before any content arrived" banner fires
 *     even though the answer completed (and is then back-filled by the
 *     thread refetch, producing the contradictory screenshot).
 *
 * THE FIX: App Router route handlers take precedence over `rewrites()`, so
 * this file intercepts every `/api/v1/chat/*` request and proxies it manually
 * with `fetch()` + a pass-through `ReadableStream` body. Two properties make
 * the stream flow byte-for-byte:
 *
 *   - `Cache-Control: no-cache, no-transform` — the `compression` middleware
 *     Next uses for `compress: true` honours `no-transform` and skips gzip
 *     entirely (this is the documented escape hatch for SSE).
 *   - The upstream body is forwarded as a stream (not awaited into a buffer),
 *     so each SSE frame is flushed to the client the moment S9 emits it.
 *
 * WHY a catch-all (not one file per endpoint): the chat surface has three
 * SSE endpoints today (stream, entity-context, proposals/{id}/confirm) and
 * the rewrite fallback would silently re-introduce the gzip bug for any new
 * one. A single faithful proxy keeps every current AND future chat endpoint
 * on the streaming-safe path.
 *
 * SECURITY:
 *   - Auth is forwarded verbatim (`Authorization` header) — S9 still does
 *     all token validation; this layer adds no trust.
 *   - Path segments are re-encoded with encodeURIComponent so a crafted
 *     URL cannot traverse outside `/v1/chat/` on the gateway.
 *   - The upstream base comes from API_GATEWAY_URL (same env var the
 *     rewrite uses) — never from user input.
 *
 * WHO USES IT: useChatStream (stream / entity-context), AskAiPanel (stream),
 * ActionConfirmModal (proposals/{id}/confirm).
 */

// WHY force-dynamic: a proxied chat stream must never be statically cached —
// each request is a live POST to S9. (POST handlers are dynamic by default;
// this makes the invariant explicit and covers any future GET addition.)
export const dynamic = "force-dynamic";

// WHY nodejs runtime (explicit): the proxy relies on Node's fetch streaming
// the upstream body. Pinning the runtime guards against an accidental future
// `runtime = "edge"` flip changing buffering semantics under us.
export const runtime = "nodejs";

/**
 * Resolve the S9 gateway base URL — the SAME source the next.config rewrite
 * uses, so this proxy and the rewrite always point at the same backend.
 */
function gatewayBase(): string {
  return process.env.API_GATEWAY_URL ?? "http://localhost:8000";
}

/**
 * proxyChat — forward one request to `${API_GATEWAY_URL}/v1/chat/<path>` and
 * stream the response back without buffering or compression.
 *
 * @param req      Incoming request (body is read fully — chat request bodies
 *                 are small JSON payloads; only the RESPONSE needs streaming).
 * @param segments Catch-all path segments after `/api/v1/chat/`.
 */
async function proxyChat(req: Request, segments: string[]): Promise<Response> {
  // Re-encode each segment defensively. Next has already split on "/" so a
  // segment cannot contain a path separator, but encoding keeps characters
  // like "#" or "?" from terminating the upstream path early.
  const path = segments.map(encodeURIComponent).join("/");

  // Forward only the headers the gateway needs. We deliberately do NOT
  // forward Accept-Encoding: the upstream hop is localhost/docker-network —
  // compression there buys nothing and an upstream-gzipped body would defeat
  // the whole point of this proxy.
  const headers = new Headers();
  const auth = req.headers.get("authorization");
  if (auth) headers.set("authorization", auth);
  headers.set(
    "content-type",
    req.headers.get("content-type") ?? "application/json",
  );
  // Advertise SSE support explicitly — matches what the browser sent.
  headers.set("accept", req.headers.get("accept") ?? "text/event-stream");

  let upstream: Response;
  try {
    upstream = await fetch(`${gatewayBase()}/v1/chat/${path}`, {
      method: req.method,
      headers,
      // WHY await req.text() (not req.body pass-through): request bodies here
      // are small JSON ({message, thread_id}); buffering them avoids the
      // half-duplex stream plumbing Node fetch requires for streamed request
      // bodies. The response side is where streaming matters.
      body: req.method === "GET" || req.method === "HEAD" ? undefined : await req.text(),
      // Abort the upstream call when the browser disconnects (user pressed
      // "Stop generating", navigated away, or closed the tab) — otherwise S9
      // would keep generating tokens into a dead socket.
      signal: req.signal,
      cache: "no-store",
    });
  } catch (err) {
    // AbortError = the CLIENT went away; nobody is listening for a response,
    // but we must still return one to satisfy the handler contract. 499 is
    // the conventional "client closed request" status.
    if (err instanceof Error && err.name === "AbortError") {
      return new Response(null, { status: 499 });
    }
    // Gateway unreachable — surface a 502 the frontend error path understands
    // (useChatStream maps >=500 to "Server error — please try again.").
    return new Response(
      JSON.stringify({ detail: "Upstream gateway unreachable" }),
      { status: 502, headers: { "content-type": "application/json" } },
    );
  }

  // Mirror the upstream response: status + content-type pass through; body
  // is the upstream ReadableStream itself (zero-copy pipe, flushes per chunk).
  const responseHeaders = new Headers();
  responseHeaders.set(
    "content-type",
    upstream.headers.get("content-type") ?? "application/json",
  );
  // THE LOAD-BEARING HEADER: `no-transform` makes Next's compression
  // middleware skip gzip for this response, so SSE frames reach the browser
  // the instant S9 emits them instead of sitting in a zlib buffer until the
  // stream ends. `no-cache` keeps any intermediary from caching a stream.
  responseHeaders.set("cache-control", "no-cache, no-transform");
  // Belt-and-braces for nginx-style reverse proxies in front of the app
  // (mirrors what S9 itself sends on the direct connection).
  responseHeaders.set("x-accel-buffering", "no");

  return new Response(upstream.body, {
    status: upstream.status,
    headers: responseHeaders,
  });
}

/**
 * Next 15 catch-all context — `params` is a Promise in the App Router.
 * Typed inline (not NextRequest) so the handler is trivially unit-testable
 * with a plain `Request` + a resolved params object.
 */
interface ChatProxyContext {
  params: Promise<{ path: string[] }>;
}

/** All chat endpoints today are POST (stream, entity-context, confirm). */
export async function POST(req: Request, ctx: ChatProxyContext): Promise<Response> {
  const { path } = await ctx.params;
  return proxyChat(req, path ?? []);
}

/**
 * GET pass-through for forward compatibility — there are no GET chat routes
 * today, but the rewrite this handler shadows WOULD have proxied one. A
 * future GET endpoint must not silently 405 because this file exists.
 */
export async function GET(req: Request, ctx: ChatProxyContext): Promise<Response> {
  const { path } = await ctx.params;
  return proxyChat(req, path ?? []);
}
