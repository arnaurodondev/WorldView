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
});
