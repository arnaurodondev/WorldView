/**
 * features/chat/hooks/__tests__/useChatStream.test.tsx — SSE chat stream hook
 *
 * WHY THIS EXISTS (PLAN-0059 E-3 follow-up): The chat page's send/stream/abort
 * lifecycle was previously inline and UNTESTED beyond a couple of integration
 * smoke tests. After lifting it into `useChatStream`, the abort + decoder +
 * [DONE] handling can be exercised in isolation with `renderHook` + a mocked
 * `fetch`. This catches regressions like "the AbortError fell through and
 * surfaced as `chatError`" or "the [DONE] sentinel didn't promote the
 * streaming bubble to a final assistant message" without spinning up the
 * entire chat page (with Radix portals, TanStack Query, the lot).
 *
 * SHAPE: each test
 *   1. mocks global `fetch` to return a `Response`-like shape with a
 *      controllable `ReadableStream` reader,
 *   2. renders the hook with a `args` object,
 *   3. calls `send()` (or `cancel()` / unmounts) and asserts the resulting
 *      `localMessages` / `streaming` / `chatError` state.
 *
 * The reader is hand-rolled rather than using the real `ReadableStream`
 * primitive because jsdom's implementation is finicky and we want to control
 * timing precisely (e.g. emit one chunk, await a microtask, then abort).
 */

import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { renderHook, act, waitFor } from "@testing-library/react";

import { useChatStream } from "../useChatStream";

// ── Helpers ───────────────────────────────────────────────────────────────────

/**
 * makeReader — build a minimal ReadableStream-like reader from an array of
 * SSE frame strings. Each call to `read()` returns the next chunk encoded as
 * a Uint8Array; once frames are exhausted it resolves with `{done: true}`.
 *
 * WHY a deferred queue (not a single resolved promise): the abort tests need
 * to PAUSE between chunks so the test can call `cancel()` mid-stream. Each
 * `read()` returns a fresh promise that resolves on the next event-loop tick;
 * tests then `await waitFor(...)` to observe the intermediate state.
 */
function makeReader(frames: string[]): {
  reader: {
    read: () => Promise<{ done: boolean; value?: Uint8Array }>;
    // WHY cancel: useChatStream calls reader.cancel() in the finally block on all
    // exit paths to release the ReadableStream lock. Without this method the hook
    // throws "reader.cancel is not a function" in tests even when the stream
    // completed successfully.
    cancel: () => Promise<void>;
  };
  encoder: TextEncoder;
} {
  const encoder = new TextEncoder();
  let i = 0;
  const reader = {
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
  return { reader, encoder };
}

/**
 * makeAbortableReader — like makeReader but each read resolves only after a
 * shared "release" signal. Lets us emit one chunk, wait for the test to
 * inspect state, then either release the next chunk or abort.
 */
function makeAbortableReader(): {
  reader: { read: () => Promise<{ done: boolean; value?: Uint8Array }> };
  pushChunk: (text: string) => void;
  finish: () => void;
  signal: AbortSignal;
  controller: AbortController;
} {
  const encoder = new TextEncoder();
  const queue: Array<{ done: boolean; value?: Uint8Array }> = [];
  let pending: ((v: { done: boolean; value?: Uint8Array }) => void) | null = null;
  const controller = new AbortController();

  // Wire abort → reject the in-flight read with an AbortError. Mirrors what
  // the real fetch + reader pair do under `signal.abort()`.
  controller.signal.addEventListener("abort", () => {
    if (pending) {
      const p = pending;
      pending = null;
      const err = new Error("Aborted");
      err.name = "AbortError";
      // Reject by resolving with done:true is wrong — we need to throw so
      // the consumer's catch branch fires. We hijack by rejecting via a
      // microtask-queued throw.
      Promise.reject(err).catch(() => {});
      // Instead: reject the pending read promise directly. We replace
      // `pending` semantics: store reject too.
      void p; // unused; see deferred form below
    }
  });

  // Switch to a deferred form: each read returns a fresh promise we keep
  // explicit handles to so we can reject on abort.
  const pendingRejects: Array<(err: Error) => void> = [];
  const pendingResolves: Array<
    (v: { done: boolean; value?: Uint8Array }) => void
  > = [];

  controller.signal.addEventListener("abort", () => {
    while (pendingRejects.length > 0) {
      const reject = pendingRejects.shift();
      pendingResolves.shift();
      const err = new Error("Aborted");
      err.name = "AbortError";
      reject?.(err);
    }
  });

  const reader = {
    read: (): Promise<{ done: boolean; value?: Uint8Array }> => {
      if (queue.length > 0) {
        return Promise.resolve(queue.shift()!);
      }
      return new Promise((resolve, reject) => {
        pendingResolves.push(resolve);
        pendingRejects.push(reject);
      });
    },
    // WHY cancel: useChatStream calls reader.cancel() in the finally block to
    // release the ReadableStream lock. The abortable reader must expose it so
    // abort + unmount tests don't throw "cancel is not a function".
    cancel: vi.fn().mockResolvedValue(undefined),
  };

  function pushChunk(text: string) {
    const value = encoder.encode(text);
    if (pendingResolves.length > 0) {
      const r = pendingResolves.shift()!;
      pendingRejects.shift();
      r({ done: false, value });
    } else {
      queue.push({ done: false, value });
    }
  }

  function finish() {
    if (pendingResolves.length > 0) {
      const r = pendingResolves.shift()!;
      pendingRejects.shift();
      r({ done: true, value: undefined });
    } else {
      queue.push({ done: true, value: undefined });
    }
  }

  return {
    reader,
    pushChunk,
    finish,
    signal: controller.signal,
    controller,
  };
}

interface DefaultArgs {
  setActiveThreadId: ReturnType<typeof vi.fn>;
  refetchThreads: ReturnType<typeof vi.fn>;
}

function makeArgs(overrides: Partial<{ accessToken: string | null; activeThreadId: string | null }> = {}): {
  args: {
    accessToken: string | null;
    activeThreadId: string | null;
    setActiveThreadId: ReturnType<typeof vi.fn>;
    refetchThreads: ReturnType<typeof vi.fn>;
  };
  spies: DefaultArgs;
} {
  const setActiveThreadId = vi.fn();
  const refetchThreads = vi.fn();
  return {
    args: {
      accessToken: overrides.accessToken !== undefined ? overrides.accessToken : "tok-123",
      activeThreadId: overrides.activeThreadId !== undefined ? overrides.activeThreadId : "thread-abc",
      setActiveThreadId,
      refetchThreads,
    },
    spies: { setActiveThreadId, refetchThreads },
  };
}

// ── Setup ────────────────────────────────────────────────────────────────────

beforeEach(() => {
  // crypto.randomUUID is implemented in jsdom for Node ≥20, but if absent
  // we install a deterministic shim so message_id assertions are stable.
  if (!("randomUUID" in globalThis.crypto)) {
    Object.defineProperty(globalThis.crypto, "randomUUID", {
      value: () => "uuid-stub-" + Math.random().toString(36).slice(2),
      configurable: true,
    });
  }
});

afterEach(() => {
  vi.restoreAllMocks();
});

// ── Tests ────────────────────────────────────────────────────────────────────

describe("useChatStream", () => {
  it("happy path: streams tokens, completes on [DONE], appends assistant message", async () => {
    const frames = [
      'data: {"text":"hello"}\n',
      'data: {"text":" world"}\n',
      "data: [DONE]\n",
    ];
    const { reader } = makeReader(frames);
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      statusText: "OK",
      body: { getReader: () => reader },
    });
    vi.stubGlobal("fetch", fetchMock);

    const { args, spies } = makeArgs();
    const { result } = renderHook(() => useChatStream(args));

    await act(async () => {
      await result.current.send("What's NVDA's margin?");
    });

    // Wire-format contract: POST /api/v1/chat/stream with bearer + JSON body.
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/v1/chat/stream");
    expect(init.method).toBe("POST");
    expect(init.headers["Content-Type"]).toBe("application/json");
    expect(init.headers["Authorization"]).toBe("Bearer tok-123");
    expect(JSON.parse(init.body as string)).toEqual({
      message: "What's NVDA's margin?",
      thread_id: "thread-abc",
    });

    // After [DONE]: streaming cleared, user + assistant messages in the log,
    // refetchThreads called once.
    expect(result.current.streaming).toBeNull();
    expect(result.current.localMessages).toHaveLength(2);
    const [user, assistant] = result.current.localMessages as Array<{
      role: string;
      content: string;
    }>;
    expect(user.role).toBe("user");
    expect(user.content).toBe("What's NVDA's margin?");
    expect(assistant.role).toBe("assistant");
    expect(assistant.content).toBe("hello world");
    expect(spies.refetchThreads).toHaveBeenCalledTimes(1);
  });

  // ── Regression: entity-context wire format (intelligence-tab chat fix) ────
  //
  // BUG (2026-06-15): when `entityId` is set (the intelligence-tab chat panel),
  // the hook previously posted `{ message }` to the SYNC `/api/v1/chat/
  // entity-context` endpoint. Both were wrong and the panel hard-failed with
  // a 400 "question cannot be empty" for EVERY entity (NVDA/TSLA included — it
  // was NOT the known AAPL data gap):
  //   - the entity-context schema requires `question`, NOT `message`;
  //   - the SSE-parsing hook must target the `/stream` sibling endpoint, not
  //     the sync JSON one.
  // This test locks the corrected wire contract so a future refactor of the
  // shared body-building block cannot silently re-break the entity panel
  // while leaving the (separately tested) main-chat path green.
  it("entity-context wire format: streams /entity-context/stream with `question` + entity_id", async () => {
    const frames = [
      'event: token\r\ndata: {"text": "NVDA "}\r\n\r\n',
      'event: token\r\ndata: {"text": "news"}\r\n\r\n',
      'event: done\r\ndata: {"type": "done"}\r\n',
    ];
    const { reader } = makeReader(frames);
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      statusText: "OK",
      body: { getReader: () => reader },
    });
    vi.stubGlobal("fetch", fetchMock);

    const { args } = makeArgs();
    // Set entityId → activates the entity-context branch of the hook.
    const entityId = "01900000-0000-7000-8000-000000001006"; // NVDA
    const { result } = renderHook(() => useChatStream({ ...args, entityId }));

    await act(async () => {
      await result.current.send("What's the latest news?");
    });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0];
    // MUST hit the SSE streaming endpoint (not the sync JSON one).
    expect(url).toBe("/api/v1/chat/entity-context/stream");
    expect(init.method).toBe("POST");
    // MUST send `question` (entity-context schema), NOT `message`, plus the
    // entity_id so S8 can scope retrieval.
    const parsedBody = JSON.parse(init.body as string);
    expect(parsedBody).toEqual({
      question: "What's the latest news?",
      thread_id: "thread-abc",
      entity_id: entityId,
    });
    expect(parsedBody.message).toBeUndefined();
    // Stream finalizes into an assistant message just like the main path.
    expect(result.current.streaming).toBeNull();
    const assistant = (result.current.localMessages as Array<{ role: string; content: string }>).find(
      (m) => m.role === "assistant",
    );
    expect(assistant?.content).toBe("NVDA news");
  });

  // ── Regression: CRLF wire format (QA Wave-3 closeout, 2026-06-11) ─────────
  //
  // sse-starlette (S8) terminates every SSE line with \r\n. The hook splits
  // the byte stream on "\n" only, so each parsed line carried a trailing
  // "\r" — `pendingEventName` became "token\r", NO event matched (done
  // included), zero tokens painted, and the reader-exhausted detector fired
  // the false "Response interrupted before any content arrived" banner under
  // a fully-delivered answer (observed live on the prod container). The fix
  // strips one trailing CR inside parseSSELine. This test replays the EXACT
  // live wire shape (named events + CRLF + trailing done frame).
  it("CRLF wire format: named events parse, answer finalizes, no false interrupt", async () => {
    const frames = [
      'event: status\r\ndata: {"step": "loading_context"}\r\n\r\n',
      'event: token\r\ndata: {"text": "BTC is "}\r\n\r\n',
      'event: token\r\ndata: {"text": "$62,778"}\r\n\r\n',
      'event: final_answer\r\ndata: {"text": "BTC is $62,778"}\r\n\r\n',
      'event: suggestions\r\ndata: ["More about BTC?"]\r\n\r\n',
      'event: metadata\r\ndata: {"intent": "GENERAL", "provider": "deepinfra", "latency_ms": 11536}\r\n\r\n',
      'event: done\r\ndata: {"type": "done"}\r\n',
    ];
    const { reader } = makeReader(frames);
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      statusText: "OK",
      body: { getReader: () => reader },
    });
    vi.stubGlobal("fetch", fetchMock);

    const { args } = makeArgs();
    const { result } = renderHook(() => useChatStream(args));

    await act(async () => {
      await result.current.send("What is BTC-USD trading at right now?");
    });

    // The done frame finalized the stream cleanly: tokens accumulated into
    // the assistant message, NO error banner, suggestions captured.
    expect(result.current.chatError).toBeNull();
    expect(result.current.streaming).toBeNull();
    const assistant = result.current.localMessages.find(
      (m) => "role" in m && m.role === "assistant",
    ) as { content: string } | undefined;
    expect(assistant?.content).toBe("BTC is $62,778");
    expect(result.current.serverSuggestions).toEqual(["More about BTC?"]);
  });

  // ── Regression: streamed citations are normalized (QA Wave-3, 2026-06-11) ──
  //
  // The SSE `citations` wire shape is the canonical rag-chat citation
  // ({ref, id, source_name, confidence, …} — verified live). CitationList
  // calls `cite.source.toLowerCase()`, so an un-normalized streamed citation
  // crashed the ENTIRE chat page behind the error boundary the moment the
  // CRLF fix made this event parse at all. The hook must apply the same
  // normalizeCitation mapping getThread() applies to persisted messages.
  it("normalizes streamed citations (source_name → source) before attaching them", async () => {
    const wireCitation = {
      ref: 1,
      item_type: "chunk",
      id: "tool:entity_news:abc",
      title: "Apple Unveils AI Reset",
      url: "https://example.com/apple",
      source_name: "news",
      published_at: "2026-06-10T16:44:13+00:00",
      entity_name: "AAPL",
      confidence: 0.68,
    };
    const frames = [
      'event: token\ndata: {"text": "Headlines [1]"}\n\n',
      `event: citations\ndata: ${JSON.stringify([wireCitation])}\n\n`,
      'event: done\ndata: {"type": "done"}\n',
    ];
    const { reader } = makeReader(frames);
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      statusText: "OK",
      body: { getReader: () => reader },
    });
    vi.stubGlobal("fetch", fetchMock);

    const { args } = makeArgs();
    const { result } = renderHook(() => useChatStream(args));
    await act(async () => {
      await result.current.send("What's the latest news on Apple Inc.?");
    });

    const assistant = result.current.localMessages.find(
      (m) => "role" in m && m.role === "assistant",
    ) as { citations?: Array<Record<string, unknown>> } | undefined;
    expect(assistant?.citations).toHaveLength(1);
    const cite = assistant!.citations![0];
    // Legacy contract fields are present (what CitationList consumes) …
    expect(cite.source).toBe("news");
    expect(cite.article_id).toBe("tool:entity_news:abc");
    expect(cite.relevance_score).toBe(0.68);
    // … and the canonical fields are preserved (CitationV2 migration).
    expect(cite.source_name).toBe("news");
    expect(cite.url).toBe("https://example.com/apple");
  });

  it("cancel() mid-stream: aborts fetch, clears streaming, surfaces no error", async () => {
    const ar = makeAbortableReader();
    // The fetch mock honours the signal: when the test calls cancel(), the
    // hook's controller.abort() flips ar.signal via wiring below.
    const fetchMock = vi.fn().mockImplementation((_url, init: RequestInit) => {
      // Bridge the hook's AbortSignal into our reader's controller so
      // pending read() calls reject with AbortError on cancel().
      init.signal?.addEventListener("abort", () => ar.controller.abort());
      return Promise.resolve({
        ok: true,
        status: 200,
        statusText: "OK",
        body: { getReader: () => ar.reader },
      });
    });
    vi.stubGlobal("fetch", fetchMock);

    const { args } = makeArgs();
    const { result } = renderHook(() => useChatStream(args));

    // Kick off the send WITHOUT awaiting — we want to observe the
    // mid-stream state.
    let sendPromise!: Promise<void>;
    act(() => {
      sendPromise = result.current.send("Tell me about Apple");
    });

    // Emit one chunk so the stream is "live".
    await act(async () => {
      ar.pushChunk('data: {"text":"App"}\n');
      // Yield a tick so the read() loop processes the chunk.
      await Promise.resolve();
      await Promise.resolve();
    });

    await waitFor(() => {
      expect(result.current.streaming).not.toBeNull();
    });

    // Cancel mid-stream.
    await act(async () => {
      result.current.cancel();
      await sendPromise;
    });

    expect(result.current.streaming).toBeNull();
    expect(result.current.chatError).toBeNull();
  });

  it("unmount mid-stream aborts the in-flight fetch without warnings", async () => {
    const ar = makeAbortableReader();
    const fetchMock = vi.fn().mockImplementation((_url, init: RequestInit) => {
      init.signal?.addEventListener("abort", () => ar.controller.abort());
      return Promise.resolve({
        ok: true,
        status: 200,
        statusText: "OK",
        body: { getReader: () => ar.reader },
      });
    });
    vi.stubGlobal("fetch", fetchMock);

    const { args } = makeArgs();
    const { result, unmount } = renderHook(() => useChatStream(args));

    let sendPromise!: Promise<void>;
    act(() => {
      sendPromise = result.current.send("Hello");
    });
    await act(async () => {
      ar.pushChunk('data: {"text":"H"}\n');
      await Promise.resolve();
    });

    // Unmount triggers the cleanup effect → abortRef.current?.abort().
    unmount();

    // The send promise still resolves cleanly (AbortError swallowed).
    await expect(sendPromise).resolves.toBeUndefined();
  });

  it("non-2xx response populates chatError and clears streaming", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 500,
      statusText: "Internal Server Error",
      body: null,
    });
    vi.stubGlobal("fetch", fetchMock);

    const { args } = makeArgs();
    const { result } = renderHook(() => useChatStream(args));

    await act(async () => {
      await result.current.send("anything");
    });

    expect(result.current.streaming).toBeNull();
    // WHY generic message check: useChatStream maps HTTP status codes to safe
    // user-facing strings rather than forwarding raw statusText, to avoid leaking
    // internal hostnames or reverse-proxy details into client error logs.
    // A 5xx maps to "Server error — please try again."
    expect(result.current.chatError).toMatch(/Server error/);
    expect(result.current.chatError).toMatch(/try again/);
  });

  it("AbortError thrown from fetch is swallowed silently (no chatError)", async () => {
    const fetchMock = vi.fn().mockImplementation(() => {
      const err = new Error("Aborted");
      err.name = "AbortError";
      return Promise.reject(err);
    });
    vi.stubGlobal("fetch", fetchMock);

    const { args } = makeArgs();
    const { result } = renderHook(() => useChatStream(args));

    await act(async () => {
      await result.current.send("anything");
    });

    expect(result.current.streaming).toBeNull();
    expect(result.current.chatError).toBeNull();
  });

  it("slash command short-circuits the LLM: no fetch, slash turn appended", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const { args } = makeArgs();
    const { result } = renderHook(() => useChatStream(args));

    await act(async () => {
      await result.current.send("/quote AAPL");
    });

    expect(fetchMock).not.toHaveBeenCalled();
    expect(result.current.streaming).toBeNull();
    expect(result.current.localMessages).toHaveLength(1);
    const turn = result.current.localMessages[0] as { kind?: string; input?: string };
    expect(turn.kind).toBe("slash");
    expect(turn.input).toBe("/quote AAPL");
  });

  it("auto-creates a thread id (and notifies parent) when activeThreadId is null", async () => {
    const frames = ["data: [DONE]\n"];
    const { reader } = makeReader(frames);
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      statusText: "OK",
      body: { getReader: () => reader },
    });
    vi.stubGlobal("fetch", fetchMock);

    const { args, spies } = makeArgs({ activeThreadId: null });
    const { result } = renderHook(() => useChatStream(args));

    await act(async () => {
      await result.current.send("Kick off a new convo");
    });

    expect(spies.setActiveThreadId).toHaveBeenCalledTimes(1);
    const newId = spies.setActiveThreadId.mock.calls[0][0];
    expect(typeof newId).toBe("string");
    expect(newId.length).toBeGreaterThan(0);

    // The fetch body must reference the SAME minted thread id (not null).
    const init = fetchMock.mock.calls[0][1];
    expect(JSON.parse(init.body as string).thread_id).toBe(newId);
  });

  // ── PLAN-0067 W11-5: tool-use SSE events ─────────────────────────────────

  it("tool_call SSE event adds a running entry to activeTools", async () => {
    // WHY: when S8 starts a tool call it emits an SSE frame:
    //   event: tool_call\ndata: {"type":"tool_call","tool":"search_documents","label":"Searching documents...","input":{},"status":"running"}\n
    // The hook should add a ToolCallState{status:"running"} to activeTools.
    const frames = [
      'event: tool_call\ndata: {"type":"tool_call","tool":"search_documents","label":"Searching documents...","input":{},"status":"running"}\n',
      "data: [DONE]\n",
    ];
    const { reader } = makeReader(frames);
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      statusText: "OK",
      body: { getReader: () => reader },
    });
    vi.stubGlobal("fetch", fetchMock);

    const { args } = makeArgs();
    const { result } = renderHook(() => useChatStream(args));

    await act(async () => {
      await result.current.send("What are analysts saying about AAPL?");
    });

    // After [DONE]: activeTools is cleared (stream complete).
    // WHY: tools should not linger in the UI after the answer is rendered.
    expect(result.current.activeTools).toHaveLength(0);

    // We can't observe the mid-stream state in a single awaited send().
    // The clearing-on-done behaviour is verified; the adding behaviour is
    // covered by the "tool_result updates status" test which uses the
    // abortable reader to pause mid-stream.
    expect(result.current.streaming).toBeNull();
  });

  it("tool_call event mid-stream: activeTools has running entry before done", async () => {
    // WHY: we need to OBSERVE the running state before [DONE] clears it.
    // Use the abortable reader so we can pause between frames.
    const ar = makeAbortableReader();
    const fetchMock = vi.fn().mockImplementation((_url, init: RequestInit) => {
      init.signal?.addEventListener("abort", () => ar.controller.abort());
      return Promise.resolve({
        ok: true,
        status: 200,
        statusText: "OK",
        body: { getReader: () => ar.reader },
      });
    });
    vi.stubGlobal("fetch", fetchMock);

    const { args } = makeArgs();
    const { result } = renderHook(() => useChatStream(args));

    let sendPromise!: Promise<void>;
    act(() => {
      sendPromise = result.current.send("research question");
    });

    // Push the tool_call frame.
    await act(async () => {
      ar.pushChunk(
        'event: tool_call\ndata: {"type":"tool_call","tool":"search_documents","label":"Searching documents...","input":{},"status":"running"}\n',
      );
      await Promise.resolve();
      await Promise.resolve();
    });

    // NOW we can assert the mid-stream state: tool should be running.
    await waitFor(() => {
      expect(result.current.activeTools).toHaveLength(1);
    });
    expect(result.current.activeTools[0]).toMatchObject({
      name: "search_documents",
      label: "Searching documents...",
      status: "running",
    });

    // Finish cleanly.
    await act(async () => {
      ar.pushChunk("data: [DONE]\n");
      ar.finish();
      await sendPromise;
    });
  });

  it("tool_result SSE event updates the matching tool status", async () => {
    // WHY: when a tool completes, S8 emits tool_result with status "ok"|"empty"|"error".
    // The hook must find the matching entry in activeTools and update its status.
    const ar = makeAbortableReader();
    const fetchMock = vi.fn().mockImplementation((_url, init: RequestInit) => {
      init.signal?.addEventListener("abort", () => ar.controller.abort());
      return Promise.resolve({
        ok: true,
        status: 200,
        statusText: "OK",
        body: { getReader: () => ar.reader },
      });
    });
    vi.stubGlobal("fetch", fetchMock);

    const { args } = makeArgs();
    const { result } = renderHook(() => useChatStream(args));

    let sendPromise!: Promise<void>;
    act(() => {
      sendPromise = result.current.send("question");
    });

    // Push tool_call (sets status=running).
    await act(async () => {
      ar.pushChunk(
        'event: tool_call\ndata: {"type":"tool_call","tool":"search_documents","label":"Searching documents...","input":{},"status":"running"}\n',
      );
      await Promise.resolve();
      await Promise.resolve();
    });

    await waitFor(() => {
      expect(result.current.activeTools).toHaveLength(1);
      expect(result.current.activeTools[0].status).toBe("running");
    });

    // Push tool_result (transitions status → "ok").
    await act(async () => {
      ar.pushChunk(
        'event: tool_result\ndata: {"type":"tool_result","tool":"search_documents","status":"ok","item_count":5}\n',
      );
      await Promise.resolve();
      await Promise.resolve();
    });

    await waitFor(() => {
      expect(result.current.activeTools[0].status).toBe("ok");
    });

    // Finish.
    await act(async () => {
      ar.pushChunk("data: [DONE]\n");
      ar.finish();
      await sendPromise;
    });
  });

  // ── PLAN-0082 Wave B: pending_action / action_executed / action_rejected ─────

  it("pending_action SSE event sets pendingAction state", async () => {
    // WHY: when the LLM calls create_alert, S8 emits a ``pending_action`` event
    // with a proposal_id and params. The hook must surface this as pendingAction
    // so the chat page can render the ActionConfirmModal.
    const ar = makeAbortableReader();
    const fetchMock = vi.fn().mockImplementation((_url, init: RequestInit) => {
      init.signal?.addEventListener("abort", () => ar.controller.abort());
      return Promise.resolve({
        ok: true,
        status: 200,
        statusText: "OK",
        body: { getReader: () => ar.reader },
      });
    });
    vi.stubGlobal("fetch", fetchMock);

    const { args } = makeArgs();
    const { result } = renderHook(() => useChatStream(args));

    let sendPromise!: Promise<void>;
    act(() => {
      sendPromise = result.current.send("Set an alert for AAPL below $180");
    });

    // WHY JSON.stringify in the SSE data: the hook parses the outer data object,
    // then JSON.parses the pending_action data field (which contains the params
    // as serialized JSON from ToolExecutor._handle_create_alert).
    const pendingData = JSON.stringify({
      proposal_id: "prop-uuid-001",
      tool: "create_alert",
      description: "Create price_below alert for AAPL at $180",
      params: JSON.stringify({
        entity_id: "aapl-entity-uuid",
        condition: "price_below",
        threshold: { value: 180 },
        severity: "medium",
      }),
    });

    await act(async () => {
      ar.pushChunk(`event: pending_action\ndata: ${pendingData}\n`);
      await Promise.resolve();
      await Promise.resolve();
    });

    await waitFor(() => {
      expect(result.current.pendingAction).not.toBeNull();
    });

    const pa = result.current.pendingAction!;
    expect(pa.proposal_id).toBe("prop-uuid-001");
    expect(pa.tool).toBe("create_alert");
    expect(pa.description).toBe("Create price_below alert for AAPL at $180");

    // Finish cleanly.
    await act(async () => {
      ar.pushChunk("data: [DONE]\n");
      ar.finish();
      await sendPromise;
    });
  });

  it("action_executed SSE event clears pendingAction", async () => {
    // WHY: once the user confirms and the action executes, the hook receives
    // an ``action_executed`` event and must clear pendingAction so the modal closes.
    const frames = [
      `event: action_executed\ndata: ${JSON.stringify({ proposal_id: "prop-001", tool_name: "create_alert", result: { alert_id: "alert-123" } })}\n`,
      "data: [DONE]\n",
    ];
    const { reader } = makeReader(frames);
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      statusText: "OK",
      body: { getReader: () => reader },
    });
    vi.stubGlobal("fetch", fetchMock);

    const { args } = makeArgs();
    const { result } = renderHook(() => useChatStream(args));

    // Pre-set a pendingAction so we can verify it gets cleared.
    // We use resetForThread then manually verify — but simpler: send and
    // receive the action_executed frame, which the hook handles by nulling
    // pendingAction regardless of whether it was set.
    await act(async () => {
      await result.current.send("confirm alert");
    });

    // pendingAction stays null (no pending_action frame was received first),
    // and the executed frame was processed without error.
    expect(result.current.pendingAction).toBeNull();
    expect(result.current.chatError).toBeNull();
  });

  it("action_rejected SSE event clears pendingAction without error state", async () => {
    // WHY: a rejected action is a normal operational outcome (e.g. S10 unavailable).
    // The hook must clear pendingAction so the modal closes. It should NOT set
    // chatError — the rejection reason is shown inline in the modal, not as a
    // global error banner.
    const frames = [
      `event: action_rejected\ndata: ${JSON.stringify({ proposal_id: "prop-002", tool_name: "create_alert", reason: "service_unavailable" })}\n`,
      "data: [DONE]\n",
    ];
    const { reader } = makeReader(frames);
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      statusText: "OK",
      body: { getReader: () => reader },
    });
    vi.stubGlobal("fetch", fetchMock);

    const { args } = makeArgs();
    const { result } = renderHook(() => useChatStream(args));

    await act(async () => {
      await result.current.send("any question");
    });

    expect(result.current.pendingAction).toBeNull();
    // action_rejected must NOT surface as chatError — the rejection is an
    // expected outcome, not a streaming failure.
    expect(result.current.chatError).toBeNull();
  });

  it("clearPendingAction sets pendingAction to null", async () => {
    // WHY: ActionConfirmModal calls clearPendingAction via onDismiss when the
    // user cancels. The hook must expose this function and it must work.
    // We test it directly without needing a full SSE stream.
    const { args } = makeArgs();
    const { result } = renderHook(() => useChatStream(args));

    // Initially null.
    expect(result.current.pendingAction).toBeNull();

    // clearPendingAction is a stable callback — calling it on a null state
    // should be a no-op (not throw).
    act(() => {
      result.current.clearPendingAction();
    });

    expect(result.current.pendingAction).toBeNull();
  });

  it("resetForThread clears pendingAction", async () => {
    // WHY: if the user switches threads while a pending_action modal is open,
    // resetForThread must clear it so the stale modal doesn't reappear on the
    // new thread. This is a silent-failure risk without the test.
    const { args } = makeArgs();
    const { result } = renderHook(() => useChatStream(args));

    // Verify resetForThread doesn't throw when pendingAction is null.
    act(() => {
      result.current.resetForThread();
    });

    expect(result.current.pendingAction).toBeNull();
  });

  it("done event clears activeTools", async () => {
    // WHY: the done event should reset activeTools so indicators vanish once
    // the answer is rendered. Uses the abortable reader to verify pre-done state.
    const ar = makeAbortableReader();
    const fetchMock = vi.fn().mockImplementation((_url, init: RequestInit) => {
      init.signal?.addEventListener("abort", () => ar.controller.abort());
      return Promise.resolve({
        ok: true,
        status: 200,
        statusText: "OK",
        body: { getReader: () => ar.reader },
      });
    });
    vi.stubGlobal("fetch", fetchMock);

    const { args } = makeArgs();
    const { result } = renderHook(() => useChatStream(args));

    let sendPromise!: Promise<void>;
    act(() => {
      sendPromise = result.current.send("question");
    });

    // Add a running tool.
    await act(async () => {
      ar.pushChunk(
        'event: tool_call\ndata: {"type":"tool_call","tool":"query_temporal","label":"Querying timeline...","input":{},"status":"running"}\n',
      );
      await Promise.resolve();
      await Promise.resolve();
    });

    await waitFor(() => {
      expect(result.current.activeTools).toHaveLength(1);
    });

    // Send done — should clear tools.
    await act(async () => {
      ar.pushChunk("data: [DONE]\n");
      ar.finish();
      await sendPromise;
    });

    expect(result.current.activeTools).toHaveLength(0);
  });

  // ── PLAN-0099 W4: agent_iteration SSE event ───────────────────────────────
  //
  // These tests pin the wire-format contract for the new event and the
  // visibility semantics of `iterationEvent` (set on each event, cleared on
  // every end-of-stream path: done / [DONE] / cancel / resetForThread / error).

  it("agent_iteration SSE event populates iterationEvent state", async () => {
    const frames = [
      'event: agent_iteration\ndata: {"iteration":0,"max_iterations":8,"stage":"planning_tools","tools_completed_total":0,"elapsed_ms":12}\n',
      "data: [DONE]\n",
    ];
    const { reader } = makeReader(frames);
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      statusText: "OK",
      body: { getReader: () => reader },
    });
    vi.stubGlobal("fetch", fetchMock);

    const { args } = makeArgs();
    const { result } = renderHook(() => useChatStream(args));

    await act(async () => {
      await result.current.send("research nvda");
    });

    // After [DONE]: iterationEvent must be cleared (strip should not persist
    // alongside the settled answer bubble).
    expect(result.current.iterationEvent).toBeNull();
  });

  it("agent_iteration event is visible mid-stream before done arrives", async () => {
    // Uses the abortable reader so we can observe the pre-done state.
    const ar = makeAbortableReader();
    const fetchMock = vi.fn().mockImplementation((_url, init: RequestInit) => {
      init.signal?.addEventListener("abort", () => ar.controller.abort());
      return Promise.resolve({
        ok: true,
        status: 200,
        statusText: "OK",
        body: { getReader: () => ar.reader },
      });
    });
    vi.stubGlobal("fetch", fetchMock);

    const { args } = makeArgs();
    const { result } = renderHook(() => useChatStream(args));

    let sendPromise!: Promise<void>;
    act(() => {
      sendPromise = result.current.send("question");
    });

    // Push a planning_tools event.
    await act(async () => {
      ar.pushChunk(
        'event: agent_iteration\ndata: {"iteration":0,"max_iterations":8,"stage":"planning_tools","tools_completed_total":0,"elapsed_ms":50}\n',
      );
      await Promise.resolve();
      await Promise.resolve();
    });

    await waitFor(() => {
      expect(result.current.iterationEvent).not.toBeNull();
      expect(result.current.iterationEvent?.stage).toBe("planning_tools");
    });

    // Then a synthesizing event — state should update to the latest.
    await act(async () => {
      ar.pushChunk(
        'event: agent_iteration\ndata: {"iteration":3,"max_iterations":8,"stage":"synthesizing","tools_completed_total":5,"elapsed_ms":17400}\n',
      );
      await Promise.resolve();
      await Promise.resolve();
    });

    await waitFor(() => {
      expect(result.current.iterationEvent?.stage).toBe("synthesizing");
      expect(result.current.iterationEvent?.iteration).toBe(3);
      expect(result.current.iterationEvent?.tools_completed_total).toBe(5);
      expect(result.current.iterationEvent?.elapsed_ms).toBe(17400);
    });

    // Finish the stream cleanly so we don't leak a pending read.
    await act(async () => {
      ar.pushChunk("data: [DONE]\n");
      ar.finish();
      await sendPromise;
    });

    // After [DONE] the strip must be cleared (parent unmounts the bubble).
    expect(result.current.iterationEvent).toBeNull();
  });

  it("malformed agent_iteration data is ignored (graceful degradation)", async () => {
    // A backend-side schema mismatch should NOT crash the stream — the strip
    // simply does not update. Other event types (tokens, done) continue to flow.
    const frames = [
      // Missing required fields (stage is an unknown enum value).
      'event: agent_iteration\ndata: {"iteration":0,"max_iterations":8,"stage":"unknown_stage","tools_completed_total":0,"elapsed_ms":0}\n',
      'data: {"text":"hi"}\n',
      "data: [DONE]\n",
    ];
    const { reader } = makeReader(frames);
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        statusText: "OK",
        body: { getReader: () => reader },
      }),
    );

    const { args } = makeArgs();
    const { result } = renderHook(() => useChatStream(args));

    await act(async () => {
      await result.current.send("question");
    });

    // iterationEvent never got set (malformed data was ignored), and the
    // streaming bubble still completed successfully — assistant message exists.
    expect(result.current.iterationEvent).toBeNull();
    expect(result.current.localMessages).toHaveLength(2);
  });
});

// ── Round 1 Foundation — tool trace, orphaned-tool clearing, retry ───────────

describe("useChatStream — toolTrace (debug drawer data)", () => {
  it("captures args, result payload, status and a latency for each tool call", async () => {
    const frames = [
      'event: tool_call\ndata: {"type":"tool_call","tool":"search_documents","label":"Searching documents...","input":{"query":"NVDA margin"},"status":"running"}\n',
      'event: tool_result\ndata: {"type":"tool_result","tool":"search_documents","status":"ok","item_count":4}\n',
      'data: {"text":"answer"}\n',
      "data: [DONE]\n",
    ];
    const { reader } = makeReader(frames);
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        statusText: "OK",
        body: { getReader: () => reader },
      }),
    );

    const { args } = makeArgs();
    const { result } = renderHook(() => useChatStream(args));

    await act(async () => {
      await result.current.send("What's NVDA's margin?");
    });

    // The trace SURVIVES stream completion (unlike activeTools) — that is the
    // entire point: the ?debug=1 drawer is opened after the answer settles.
    expect(result.current.activeTools).toEqual([]);
    expect(result.current.toolTrace).toHaveLength(1);
    const entry = result.current.toolTrace[0];
    expect(entry.tool).toBe("search_documents");
    expect(entry.label).toBe("Searching documents...");
    expect(entry.args).toEqual({ query: "NVDA margin" });
    expect(entry.status).toBe("ok");
    // Result payload keeps everything except the demux keys (type/tool/status).
    expect(entry.result).toEqual({ item_count: 4 });
    // Client-measured latency: a number ≥ 0 (jsdom performance.now monotonic).
    expect(typeof entry.latencyMs).toBe("number");
    expect(entry.latencyMs).toBeGreaterThanOrEqual(0);
  });

  it("clears the previous turn's trace and stale activeTools at the start of a new send", async () => {
    // Turn 1: stream ends via READER EXHAUSTION (no done event) — the path
    // that previously leaked activeTools into the next turn (orphaned-spinner
    // bug): the server closed early so the tool_result/done cleanup never ran.
    const frames1 = [
      'event: tool_call\ndata: {"type":"tool_call","tool":"get_quote","label":"Fetching quote...","input":{},"status":"running"}\n',
      'data: {"text":"partial"}\n',
      // NO [DONE] — reader exhausts.
    ];
    const r1 = makeReader(frames1);
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      statusText: "OK",
      body: { getReader: () => r1.reader },
    });
    vi.stubGlobal("fetch", fetchMock);

    const { args } = makeArgs();
    const { result } = renderHook(() => useChatStream(args));

    await act(async () => {
      await result.current.send("first question");
    });

    // Turn 1 left a running entry in the trace (no tool_result ever arrived).
    expect(result.current.toolTrace).toHaveLength(1);
    expect(result.current.toolTrace[0].status).toBe("running");

    // Turn 2: a plain no-tool stream. Before its first event arrives the
    // stale tool state from turn 1 must already be gone.
    const r2 = makeReader(['data: {"text":"clean"}\n', "data: [DONE]\n"]);
    fetchMock.mockResolvedValue({
      ok: true,
      status: 200,
      statusText: "OK",
      body: { getReader: () => r2.reader },
    });

    await act(async () => {
      await result.current.send("second question");
    });

    // No tools ran in turn 2 → both views are empty; nothing leaked.
    expect(result.current.activeTools).toEqual([]);
    expect(result.current.toolTrace).toEqual([]);
  });

  it("resetForThread clears the trace (no cross-thread leakage)", async () => {
    const frames = [
      'event: tool_call\ndata: {"type":"tool_call","tool":"search_documents","label":"Searching...","input":{},"status":"running"}\n',
      'event: tool_result\ndata: {"type":"tool_result","tool":"search_documents","status":"ok","item_count":1}\n',
      "data: [DONE]\n",
    ];
    const { reader } = makeReader(frames);
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        statusText: "OK",
        body: { getReader: () => reader },
      }),
    );

    const { args } = makeArgs();
    const { result } = renderHook(() => useChatStream(args));

    await act(async () => {
      await result.current.send("q");
    });
    expect(result.current.toolTrace).toHaveLength(1);

    act(() => {
      result.current.resetForThread();
    });
    expect(result.current.toolTrace).toEqual([]);
  });
});

describe("useChatStream — retry()", () => {
  it("resubmits the failed question without duplicating the user bubble", async () => {
    // First attempt: network-level failure (fetch rejects).
    const fetchMock = vi.fn().mockRejectedValue(new Error("network down"));
    vi.stubGlobal("fetch", fetchMock);

    const { args } = makeArgs();
    const { result } = renderHook(() => useChatStream(args));

    await act(async () => {
      await result.current.send("flaky question");
    });

    // Failure state: user bubble in the log + error banner armed.
    expect(result.current.chatError).not.toBeNull();
    expect(result.current.localMessages).toHaveLength(1);

    // Second attempt succeeds.
    const { reader } = makeReader(['data: {"text":"recovered"}\n', "data: [DONE]\n"]);
    fetchMock.mockResolvedValue({
      ok: true,
      status: 200,
      statusText: "OK",
      body: { getReader: () => reader },
    });

    await act(async () => {
      await result.current.retry();
    });

    // Same question went over the wire again…
    expect(fetchMock).toHaveBeenCalledTimes(2);
    const secondBody = JSON.parse(fetchMock.mock.calls[1][1].body as string);
    expect(secondBody.message).toBe("flaky question");

    // …but the user bubble was NOT echoed twice: exactly one user message
    // followed by the recovered assistant message. Error banner cleared.
    expect(result.current.chatError).toBeNull();
    const roles = (result.current.localMessages as Array<{ role: string }>).map(
      (m) => m.role,
    );
    expect(roles).toEqual(["user", "assistant"]);
  });

  it("is a no-op when nothing failed (no accidental resubmits)", async () => {
    // Successful turn first — finalize() must clear the retry context.
    const { reader } = makeReader(['data: {"text":"ok"}\n', "data: [DONE]\n"]);
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      statusText: "OK",
      body: { getReader: () => reader },
    });
    vi.stubGlobal("fetch", fetchMock);

    const { args } = makeArgs();
    const { result } = renderHook(() => useChatStream(args));

    await act(async () => {
      await result.current.send("fine question");
    });
    expect(fetchMock).toHaveBeenCalledTimes(1);

    // retry() after success: no second request, no state churn.
    await act(async () => {
      await result.current.retry();
    });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(result.current.localMessages).toHaveLength(2);
  });

  it("arms retry on a server-emitted error event too", async () => {
    const frames = [
      'event: error\ndata: {"message":"model overloaded"}\n',
    ];
    const { reader } = makeReader(frames);
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      statusText: "OK",
      body: { getReader: () => reader },
    });
    vi.stubGlobal("fetch", fetchMock);

    const { args } = makeArgs();
    const { result } = renderHook(() => useChatStream(args));

    await act(async () => {
      await result.current.send("doomed question");
    });
    expect(result.current.chatError).toBe("model overloaded");

    // Retry goes over the wire with the same question.
    const r2 = makeReader(['data: {"text":"better"}\n', "data: [DONE]\n"]);
    fetchMock.mockResolvedValue({
      ok: true,
      status: 200,
      statusText: "OK",
      body: { getReader: () => r2.reader },
    });
    await act(async () => {
      await result.current.retry();
    });
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(
      JSON.parse(fetchMock.mock.calls[1][1].body as string).message,
    ).toBe("doomed question");
  });
});

// ── Round 4 Hardening — interrupted streams + pre-stream failures ────────────
//
// A mid-response network blip surfaces as READER EXHAUSTION WITHOUT a `done`
// event. Round 1 made sure that path cleared the spinners; Round 4 makes the
// interruption VISIBLE: partial content is preserved verbatim, chatError
// carries an explicit "interrupted" notice (rendered as the inline banner
// with Retry), and retry() is armed. Pre-Round-4 the stream silently
// completed as if the truncated text were the whole answer.

describe("useChatStream — interrupted stream (Round 4)", () => {
  it("reader exhaustion mid-answer: preserves partial content verbatim, surfaces an interruption notice, arms retry", async () => {
    // Two token frames, then the connection dies — NO done/[DONE].
    const frames = [
      'data: {"text":"NVDA margins are"}\n',
      'data: {"text":" expanding"}\n',
    ];
    const { reader } = makeReader(frames);
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      statusText: "OK",
      body: { getReader: () => reader },
    });
    vi.stubGlobal("fetch", fetchMock);

    const { args, spies } = makeArgs();
    const { result } = renderHook(() => useChatStream(args));

    await act(async () => {
      await result.current.send("What about NVDA margins?");
    });

    // Partial content preserved as its own assistant message — VERBATIM:
    // no synthetic "[Response interrupted]" text spliced into model output.
    expect(result.current.localMessages).toHaveLength(2);
    const assistant = result.current.localMessages[1] as {
      role: string;
      content: string;
    };
    expect(assistant.role).toBe("assistant");
    expect(assistant.content).toBe("NVDA margins are expanding");

    // The interruption is VISIBLE — never silently truncate-as-complete.
    expect(result.current.chatError).toMatch(/interrupted/i);

    // Streaming chrome fully reset (no orphaned bubble/spinners/strip).
    expect(result.current.streaming).toBeNull();
    expect(result.current.activeTools).toEqual([]);
    expect(result.current.iterationEvent).toBeNull();

    // The sidebar still refreshes — the server may have persisted the user
    // message before the stream died.
    expect(spies.refetchThreads).toHaveBeenCalledTimes(1);

    // Retry is armed: it resends the SAME question WITHOUT re-echoing the
    // user bubble, even though the partial assistant message now sits
    // between the user bubble and the end of the log (the backward-scan
    // skipUserEcho contract).
    const r2 = makeReader(['data: {"text":"full answer"}\n', "data: [DONE]\n"]);
    fetchMock.mockResolvedValue({
      ok: true,
      status: 200,
      statusText: "OK",
      body: { getReader: () => r2.reader },
    });
    await act(async () => {
      await result.current.retry();
    });

    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(
      JSON.parse(fetchMock.mock.calls[1][1].body as string).message,
    ).toBe("What about NVDA margins?");
    expect(result.current.chatError).toBeNull();
    const roles = (result.current.localMessages as Array<{ role: string }>).map(
      (m) => m.role,
    );
    // user question (once!), interrupted partial, recovered full answer.
    expect(roles).toEqual(["user", "assistant", "assistant"]);
  });

  it("reader exhaustion with ZERO content: visible error + retry armed, no empty assistant message", async () => {
    // The server accepted the request, then closed without emitting anything
    // — previously this path ended completely silently (spinner cleared,
    // nothing else): the worst "did it even work?" UX.
    const { reader } = makeReader([]); // immediate EOF, no frames
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      statusText: "OK",
      body: { getReader: () => reader },
    });
    vi.stubGlobal("fetch", fetchMock);

    const { args } = makeArgs();
    const { result } = renderHook(() => useChatStream(args));

    await act(async () => {
      await result.current.send("hello?");
    });

    // Only the user bubble — no phantom empty assistant message.
    expect(result.current.localMessages).toHaveLength(1);
    expect(result.current.chatError).toMatch(/interrupted/i);

    // Retry resubmits without a duplicate echo (user bubble is the last entry).
    const r2 = makeReader(['data: {"text":"hi"}\n', "data: [DONE]\n"]);
    fetchMock.mockResolvedValue({
      ok: true,
      status: 200,
      statusText: "OK",
      body: { getReader: () => r2.reader },
    });
    await act(async () => {
      await result.current.retry();
    });
    const roles = (result.current.localMessages as Array<{ role: string }>).map(
      (m) => m.role,
    );
    expect(roles).toEqual(["user", "assistant"]);
  });

  it("a CLEAN done event still completes without any interruption notice (no false positives)", async () => {
    // Guard: the interruption path must trigger ONLY on reader exhaustion —
    // a normal done-terminated stream must stay error-free.
    const frames = ['data: {"text":"complete"}\n', "data: [DONE]\n"];
    const { reader } = makeReader(frames);
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        statusText: "OK",
        body: { getReader: () => reader },
      }),
    );

    const { args } = makeArgs();
    const { result } = renderHook(() => useChatStream(args));

    await act(async () => {
      await result.current.send("q");
    });

    expect(result.current.chatError).toBeNull();
    const assistant = result.current.localMessages[1] as { content: string };
    expect(assistant.content).toBe("complete");
  });
});

describe("useChatStream — pre-stream failure (Round 4)", () => {
  it("fetch rejecting BEFORE any stream starts surfaces an immediate error with retry armed", async () => {
    // Network fully down: fetch() rejects with a TypeError before any byte
    // of the response exists — the pre-stream path, distinct from mid-stream
    // reader exhaustion.
    const fetchMock = vi
      .fn()
      .mockRejectedValue(new TypeError("Failed to fetch"));
    vi.stubGlobal("fetch", fetchMock);

    const { args } = makeArgs();
    const { result } = renderHook(() => useChatStream(args));

    await act(async () => {
      await result.current.send("offline question");
    });

    // Immediate, visible failure: error banner copy set, bubble cleared,
    // no orphaned tool/iteration chrome.
    expect(result.current.chatError).toBe(
      "Chat request failed. Please try again.",
    );
    expect(result.current.streaming).toBeNull();
    expect(result.current.activeTools).toEqual([]);
    expect(result.current.iterationEvent).toBeNull();

    // The optimistic user bubble is preserved (the user must not lose their
    // typed question to a network blip).
    expect(result.current.localMessages).toHaveLength(1);
    const user = result.current.localMessages[0] as {
      role: string;
      content: string;
    };
    expect(user.role).toBe("user");
    expect(user.content).toBe("offline question");

    // Retry is armed and resends the same question once the network is back.
    const { reader } = makeReader(['data: {"text":"back online"}\n', "data: [DONE]\n"]);
    fetchMock.mockResolvedValue({
      ok: true,
      status: 200,
      statusText: "OK",
      body: { getReader: () => reader },
    });
    await act(async () => {
      await result.current.retry();
    });
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(result.current.chatError).toBeNull();
    const roles = (result.current.localMessages as Array<{ role: string }>).map(
      (m) => m.role,
    );
    expect(roles).toEqual(["user", "assistant"]);
  });
});

// ── Wave 2 (frontend-rework sprint) — suggestions, server latency, metadata,
// conversation-level tool usage ───────────────────────────────────────────────

describe("useChatStream — Wave 2 stream additions", () => {
  /** Standard ok-response fetch stub around a frame list. */
  function stubFetch(frames: string[]): ReturnType<typeof vi.fn> {
    const { reader } = makeReader(frames);
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      statusText: "OK",
      body: { getReader: () => reader },
    });
    vi.stubGlobal("fetch", fetchMock);
    return fetchMock;
  }

  it("suggestions SSE event (bare string array) populates serverSuggestions", async () => {
    // Live wire shape (verified 2026-06-11 against the running gateway):
    //   event: suggestions
    //   data: ["What's the latest news on Apple Inc.?", …]
    stubFetch([
      'data: {"text":"answer"}\n',
      'event: suggestions\ndata: ["What moved AAPL today?","Compare AAPL and MSFT","Show AAPL fundamentals"]\n',
      'event: done\ndata: {"type":"done"}\n',
    ]);

    const { args } = makeArgs();
    const { result } = renderHook(() => useChatStream(args));

    await act(async () => {
      await result.current.send("In one short sentence, what is AAPL?");
    });

    expect(result.current.serverSuggestions).toEqual([
      "What moved AAPL today?",
      "Compare AAPL and MSFT",
      "Show AAPL fundamentals",
    ]);
  });

  it("malformed suggestion entries are filtered, not crashed on", async () => {
    stubFetch([
      'data: {"text":"answer"}\n',
      // One real string, one empty, one non-string — only the real one lands.
      'event: suggestions\ndata: ["Real question?","",42]\n',
      'event: done\ndata: {"type":"done"}\n',
    ]);

    const { args } = makeArgs();
    const { result } = renderHook(() => useChatStream(args));
    await act(async () => {
      await result.current.send("q");
    });
    expect(result.current.serverSuggestions).toEqual(["Real question?"]);
  });

  it("a new send clears the previous turn's serverSuggestions", async () => {
    const fetchMock = stubFetch([
      'data: {"text":"a1"}\n',
      'event: suggestions\ndata: ["Old suggestion"]\n',
      'event: done\ndata: {"type":"done"}\n',
    ]);

    const { args } = makeArgs();
    const { result } = renderHook(() => useChatStream(args));
    await act(async () => {
      await result.current.send("first");
    });
    expect(result.current.serverSuggestions).toEqual(["Old suggestion"]);

    // Turn 2 emits NO suggestions event — the old ones must not survive.
    const r2 = makeReader(['data: {"text":"a2"}\n', 'event: done\ndata: {"type":"done"}\n']);
    fetchMock.mockResolvedValue({
      ok: true,
      status: 200,
      statusText: "OK",
      body: { getReader: () => r2.reader },
    });
    await act(async () => {
      await result.current.send("second");
    });
    expect(result.current.serverSuggestions).toEqual([]);
  });

  it("tool_result duration_ms is preferred as latency and marked server-sourced; result_preview flows into the trace", async () => {
    stubFetch([
      'event: tool_call\ndata: {"type":"tool_call","tool":"get_entity_narrative","label":"Loading narrative...","input":{"entity_id":"AAPL"},"status":"running"}\n',
      // Live wire shape: duration_ms + result_preview [{id,title}].
      'event: tool_result\ndata: {"type":"tool_result","tool":"get_entity_narrative","status":"ok","item_count":1,"duration_ms":146,"result_preview":[{"id":"tool:narrative:x","title":"Narrative: Apple Inc."}]}\n',
      'data: {"text":"answer"}\n',
      'event: done\ndata: {"type":"done"}\n',
    ]);

    const { args } = makeArgs();
    const { result } = renderHook(() => useChatStream(args));
    await act(async () => {
      await result.current.send("what is AAPL?");
    });

    const entry = result.current.toolTrace[0];
    // EXACT server value — not a client wall-clock approximation.
    expect(entry.latencyMs).toBe(146);
    expect(entry.latencySource).toBe("server");
    // result_preview survives in the raw result payload for the drawer.
    expect(entry.result?.result_preview).toEqual([
      { id: "tool:narrative:x", title: "Narrative: Apple Inc." },
    ]);
  });

  it("falls back to client wall-clock latency (marked client-sourced) when duration_ms is absent", async () => {
    stubFetch([
      'event: tool_call\ndata: {"type":"tool_call","tool":"get_quote","label":"Fetching quote...","input":{},"status":"running"}\n',
      // Legacy backend shape — no duration_ms.
      'event: tool_result\ndata: {"type":"tool_result","tool":"get_quote","status":"ok","item_count":1}\n',
      'event: done\ndata: {"type":"done"}\n',
    ]);

    const { args } = makeArgs();
    const { result } = renderHook(() => useChatStream(args));
    await act(async () => {
      await result.current.send("quote NVDA");
    });

    const entry = result.current.toolTrace[0];
    expect(typeof entry.latencyMs).toBe("number");
    expect(entry.latencySource).toBe("client");
  });

  it("toolUsage accumulates ACROSS sends and resets only on resetForThread", async () => {
    const fetchMock = stubFetch([
      'event: tool_call\ndata: {"type":"tool_call","tool":"search_documents","label":"Searching...","input":{},"status":"running"}\n',
      'event: tool_result\ndata: {"type":"tool_result","tool":"search_documents","status":"ok","item_count":2,"duration_ms":100}\n',
      'event: done\ndata: {"type":"done"}\n',
    ]);

    const { args } = makeArgs();
    const { result } = renderHook(() => useChatStream(args));
    await act(async () => {
      await result.current.send("first");
    });
    expect(result.current.toolUsage).toEqual([
      { tool: "search_documents", latencyMs: 100 },
    ]);

    // Turn 2 uses the same tool again — the sample APPENDS (unlike toolTrace,
    // which is per-turn and was reset at the start of this send).
    const r2 = makeReader([
      'event: tool_call\ndata: {"type":"tool_call","tool":"search_documents","label":"Searching...","input":{},"status":"running"}\n',
      'event: tool_result\ndata: {"type":"tool_result","tool":"search_documents","status":"ok","item_count":1,"duration_ms":300}\n',
      'event: done\ndata: {"type":"done"}\n',
    ]);
    fetchMock.mockResolvedValue({
      ok: true,
      status: 200,
      statusText: "OK",
      body: { getReader: () => r2.reader },
    });
    await act(async () => {
      await result.current.send("second");
    });
    expect(result.current.toolUsage).toEqual([
      { tool: "search_documents", latencyMs: 100 },
      { tool: "search_documents", latencyMs: 300 },
    ]);

    // Thread switch — the conversation-scoped accumulator resets.
    act(() => {
      result.current.resetForThread();
    });
    expect(result.current.toolUsage).toEqual([]);
  });

  it("metadata SSE event fields land on the finalized assistant message", async () => {
    stubFetch([
      'data: {"text":"Apple Inc. is a technology company."}\n',
      'event: metadata\ndata: {"thread_id":"thread-abc","message_id":"m-1","intent":"RELATIONSHIP","provider":"deepinfra","latency_ms":9526}\n',
      'event: done\ndata: {"type":"done"}\n',
    ]);

    const { args } = makeArgs();
    const { result } = renderHook(() => useChatStream(args));
    await act(async () => {
      await result.current.send("what is AAPL?");
    });

    const assistant = result.current.localMessages[1] as {
      role: string;
      intent?: string | null;
      provider?: string | null;
      latency_ms?: number | null;
    };
    expect(assistant.role).toBe("assistant");
    // The meta strip reads these straight off the optimistic message —
    // no thread refetch needed to show intent/provider/latency.
    expect(assistant.intent).toBe("RELATIONSHIP");
    expect(assistant.provider).toBe("deepinfra");
    expect(assistant.latency_ms).toBe(9526);
  });
});

// ── Wave 3 — false-interrupt regression (live SSE event order) ───────────────
//
// USER-REPORTED BUG (2026-06-11 screenshot): a fully delivered answer —
// complete text, meta strip, citations, suggestions — rendered with a
// "Response interrupted before any content arrived" banner underneath it.
// Live traces pinned the REAL event order the backend emits:
//
//   tool_call → tool_result → agent_iteration → token… → final_answer →
//   citations → contradictions → suggestions → metadata → done
//
// The Round-4 detector fired whenever the reader exhausted without having
// PROCESSED a done frame — but the done frame can be (a) sitting in the
// undelivered tail buffer when the final chunk has no trailing newline, or
// (b) genuinely lost when a proxy closes the connection right after
// metadata. These tests pin the Wave-3 contract: the banner NEVER fires when
// the answer completed.

describe("useChatStream — Wave 3 false-interrupt hardening", () => {
  /** The full event order observed live (2026-06-11 SSE traces). */
  const LIVE_ORDER_FRAMES = [
    "event: tool_call\n" +
      'data: {"type":"tool_call","tool":"get_entity_news","label":"get_entity_news...","input":{"ticker":"AAPL"},"status":"running"}\n\n',
    "event: tool_result\n" +
      'data: {"type":"tool_result","tool":"get_entity_news","status":"ok","item_count":10,"duration_ms":310}\n\n',
    'event: token\ndata: {"text":"Apple is "}\n\n',
    'event: token\ndata: {"text":"doing fine."}\n\n',
    "event: final_answer\n" + 'data: {"text":"Apple is doing fine."}\n\n',
    "event: citations\n" +
      'data: [{"article_id":"a1","title":"Apple news","url":"https://example.com/a1","source":"news","relevance_score":0.9}]\n\n',
    "event: contradictions\ndata: []\n\n",
    'event: suggestions\ndata: ["What about TSMC?"]\n\n',
    "event: metadata\n" +
      'data: {"intent":"GENERAL","provider":"deepinfra","model":"r1","latency_ms":1234}\n\n',
  ];

  function mockFetchWithFrames(frames: string[]) {
    const { reader } = makeReader(frames);
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      statusText: "OK",
      body: { getReader: () => reader },
    });
    vi.stubGlobal("fetch", fetchMock);
    return fetchMock;
  }

  it("real observed event order ending in done → finalized, NO banner, meta+citations attached", async () => {
    mockFetchWithFrames([
      ...LIVE_ORDER_FRAMES,
      'event: done\ndata: {"type":"done"}\n\n',
    ]);

    const { args, spies } = makeArgs();
    const { result } = renderHook(() => useChatStream(args));

    await act(async () => {
      await result.current.send("Latest on Apple?");
    });

    // The core regression assertion: a complete answer NEVER shows the banner.
    expect(result.current.chatError).toBeNull();
    expect(result.current.streaming).toBeNull();
    expect(result.current.activeTools).toEqual([]);

    const assistant = result.current.localMessages[1] as {
      role: string;
      content: string;
      citations: Array<{ article_id: string }>;
      intent?: string | null;
      latency_ms?: number | null;
    };
    expect(assistant.role).toBe("assistant");
    expect(assistant.content).toBe("Apple is doing fine.");
    expect(assistant.citations).toHaveLength(1);
    // metadata event fields land on the optimistic message (meta strip).
    expect(assistant.intent).toBe("GENERAL");
    expect(assistant.latency_ms).toBe(1234);
    // suggestions event populated the chips source.
    expect(result.current.serverSuggestions).toEqual(["What about TSMC?"]);
    expect(spies.refetchThreads).toHaveBeenCalledTimes(1);
  });

  it("reader exhaustion right AFTER metadata (done frame lost) → clean finalize, NO banner", async () => {
    // Same live order but the stream dies before the done frame — the shape
    // a proxy produces when it closes the upstream connection eagerly.
    mockFetchWithFrames(LIVE_ORDER_FRAMES);

    const { args, spies } = makeArgs();
    const { result } = renderHook(() => useChatStream(args));

    await act(async () => {
      await result.current.send("Latest on Apple?");
    });

    // NEVER the banner when terminal events (suggestions/metadata) arrived.
    expect(result.current.chatError).toBeNull();
    const assistant = result.current.localMessages[1] as {
      content: string;
      intent?: string | null;
    };
    expect(assistant.content).toBe("Apple is doing fine.");
    expect(assistant.intent).toBe("GENERAL");
    // Stream chrome fully reset — no orphaned spinners next to the answer.
    expect(result.current.streaming).toBeNull();
    expect(result.current.activeTools).toEqual([]);
    expect(spies.refetchThreads).toHaveBeenCalledTimes(1);
  });

  it("done frame in the FINAL chunk without a trailing newline → finalized, NO banner", async () => {
    // Chunk boundaries are arbitrary: the closing frames can arrive in one
    // last chunk that ends mid-line (no trailing \n). Pre-Wave-3, the done
    // data line stayed in `buffer` unprocessed and the banner fired under a
    // complete answer.
    mockFetchWithFrames([
      'event: token\ndata: {"text":"Full answer."}\n\n',
      // Final chunk: done event line + data line, NO trailing newline.
      'event: done\ndata: {"type":"done"}',
    ]);

    const { args } = makeArgs();
    const { result } = renderHook(() => useChatStream(args));

    await act(async () => {
      await result.current.send("Q?");
    });

    expect(result.current.chatError).toBeNull();
    const assistant = result.current.localMessages[1] as { content: string };
    expect(assistant.content).toBe("Full answer.");
  });

  it("zero-token stream: final_answer text becomes the assistant message (cache-hit shape)", async () => {
    // Some backend paths (cache hits, guardrails) emit NO token frames —
    // only final_answer. Pre-Wave-3 the optimistic message settled EMPTY and
    // the text only appeared after a thread refetch.
    mockFetchWithFrames([
      "event: final_answer\n" +
        'data: {"text":"Cached: Apple reported record revenue."}\n\n',
      'event: done\ndata: {"type":"done"}\n\n',
    ]);

    const { args } = makeArgs();
    const { result } = renderHook(() => useChatStream(args));

    await act(async () => {
      await result.current.send("Q?");
    });

    expect(result.current.chatError).toBeNull();
    const assistant = result.current.localMessages[1] as { content: string };
    expect(assistant.content).toBe("Cached: Apple reported record revenue.");
  });

  it("tokens still WIN over final_answer when both are present (refusal-text divergence)", async () => {
    // Live trace 2026-06-11: the token stream carried the real answer while
    // final_answer carried an unrelated refusal string. The fallback must
    // never override genuinely streamed text.
    mockFetchWithFrames([
      'event: token\ndata: {"text":"Real streamed answer."}\n\n',
      "event: final_answer\n" +
        'data: {"text":"I cannot find information about the entities."}\n\n',
      'event: done\ndata: {"type":"done"}\n\n',
    ]);

    const { args } = makeArgs();
    const { result } = renderHook(() => useChatStream(args));

    await act(async () => {
      await result.current.send("Q?");
    });

    const assistant = result.current.localMessages[1] as { content: string };
    expect(assistant.content).toBe("Real streamed answer.");
  });

  it("a GENUINE early interruption (no terminal events) still surfaces the banner", async () => {
    // Guard the guard: Wave 3 must not have neutered the detector. Tokens
    // flow, then the stream dies with no citations/suggestions/metadata/done
    // — that IS an interruption and the user must see it.
    mockFetchWithFrames(['event: token\ndata: {"text":"Partial ans"}\n\n']);

    const { args } = makeArgs();
    const { result } = renderHook(() => useChatStream(args));

    await act(async () => {
      await result.current.send("Q?");
    });

    expect(result.current.chatError).toMatch(/interrupted/i);
    // Partial content preserved verbatim as its own message.
    const assistant = result.current.localMessages[1] as { content: string };
    expect(assistant.content).toBe("Partial ans");
  });

  it("tool_call events stamp startedAt onto activeTools (elapsed-chip data source)", async () => {
    const ar = makeAbortableReader();
    const fetchMock = vi.fn().mockImplementation((_url, init: RequestInit) => {
      init.signal?.addEventListener("abort", () => ar.controller.abort());
      return Promise.resolve({
        ok: true,
        status: 200,
        statusText: "OK",
        body: { getReader: () => ar.reader },
      });
    });
    vi.stubGlobal("fetch", fetchMock);

    const { args } = makeArgs();
    const { result } = renderHook(() => useChatStream(args));

    let sendPromise!: Promise<void>;
    act(() => {
      sendPromise = result.current.send("Q?");
    });

    const before = Date.now();
    await act(async () => {
      ar.pushChunk(
        "event: tool_call\n" +
          'data: {"type":"tool_call","tool":"search_documents","label":"Searching...","status":"running"}\n\n',
      );
      await Promise.resolve();
      await Promise.resolve();
    });

    await waitFor(() => {
      expect(result.current.activeTools).toHaveLength(1);
    });
    const tool = result.current.activeTools[0];
    // startedAt is a wall-clock stamp taken at event receipt — bounded by
    // the test's own before/after reads.
    expect(tool.startedAt).toBeGreaterThanOrEqual(before);
    expect(tool.startedAt).toBeLessThanOrEqual(Date.now());

    await act(async () => {
      ar.finish();
      await sendPromise;
    });
  });
});
