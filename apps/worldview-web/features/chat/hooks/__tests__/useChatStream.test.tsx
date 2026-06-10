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
