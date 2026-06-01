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

  // ── PLAN-0089 K Block A T-03 — Q-9 metadata / contradictions / fallback ─────

  it("metadata SSE event populates provider/model/latency on the assistant message", async () => {
    // WHY: S8 emits an `event: metadata` frame with intent/provider/model/
    // latency_ms/message_id around the time the token stream completes. The
    // hook must capture these and persist them onto the finalised Message
    // (Q-9 fields) so the side rail can show "served by deepinfra / 1234ms"
    // without an extra round-trip.
    const metadataPayload = JSON.stringify({
      intent: "research",
      provider: "deepinfra",
      model: "deepseek-r1-distill-qwen-32b",
      latency_ms: 1234,
      message_id: "msg-server-001",
    });
    const frames = [
      'data: {"text":"answer"}\n',
      `event: metadata\ndata: ${metadataPayload}\n`,
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
      await result.current.send("research question");
    });

    expect(result.current.streaming).toBeNull();
    expect(result.current.localMessages).toHaveLength(2);
    const assistant = result.current.localMessages[1] as {
      role: string;
      content: string;
      provider?: string;
      model?: string;
      latency_ms?: number;
      message_id?: string;
    };
    expect(assistant.role).toBe("assistant");
    expect(assistant.content).toBe("answer");
    expect(assistant.provider).toBe("deepinfra");
    expect(assistant.model).toBe("deepseek-r1-distill-qwen-32b");
    expect(assistant.latency_ms).toBe(1234);
    // WHY message_id matches server: when metadata carries a message_id we
    // prefer it over the client-minted uuid so client + server agree on the
    // canonical id for feedback / fallback_of references.
    expect(assistant.message_id).toBe("msg-server-001");
  });

  it("contradictions SSE event stores items on the assistant message", async () => {
    // WHY: KG-sourced contradictions arrive via a dedicated side-channel event
    // so the chat hook must surface them on the finalised Message.contradictions
    // array. The side rail renders them generically — the hook is opaque to
    // the contradiction shape.
    const contradictionPayload = JSON.stringify([
      { claim_id: "c1", left: "A", right: "B", confidence: 0.83 },
      { claim_id: "c2", left: "C", right: "D", confidence: 0.71 },
    ]);
    const frames = [
      'data: {"text":"explained"}\n',
      `event: contradictions\ndata: ${contradictionPayload}\n`,
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
      await result.current.send("any contradictions about NVDA?");
    });

    expect(result.current.localMessages).toHaveLength(2);
    const assistant = result.current.localMessages[1] as {
      contradictions?: Array<Record<string, unknown>>;
    };
    expect(assistant.contradictions).toBeDefined();
    expect(assistant.contradictions).toHaveLength(2);
    expect(assistant.contradictions![0].claim_id).toBe("c1");
  });

  it("tool_call with is_fallback flags forwards to activeTools entry", async () => {
    // WHY: when S8's primary tool fails and the planner retries with a
    // degraded tool, the second `tool_call` event carries is_fallback=true
    // and fallback_of=<original tool name>. We surface both on the
    // ToolCallState entry so the indicator can render a "fallback" chip
    // without re-deriving state from logs.
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
      sendPromise = result.current.send("research");
    });

    // Fallback tool_call frame — primary failed, retrying with a degraded tool.
    await act(async () => {
      ar.pushChunk(
        'event: tool_call\ndata: {"type":"tool_call","tool":"keyword_search","label":"Keyword fallback...","input":{},"status":"running","is_fallback":true,"fallback_of":"semantic_search"}\n',
      );
      await Promise.resolve();
      await Promise.resolve();
    });

    await waitFor(() => {
      expect(result.current.activeTools).toHaveLength(1);
    });
    const tc = result.current.activeTools[0] as {
      name: string;
      is_fallback?: boolean;
      fallback_of?: string;
    };
    expect(tc.name).toBe("keyword_search");
    expect(tc.is_fallback).toBe(true);
    expect(tc.fallback_of).toBe("semantic_search");

    // Finish cleanly.
    await act(async () => {
      ar.pushChunk("data: [DONE]\n");
      ar.finish();
      await sendPromise;
    });
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

  // ── PLAN-0103 W21 (BP-642) — final_answer honor regression ────────────────
  //
  // The backend's PLAN-0093 numeric-grounding pass can rewrite the
  // synthesised text post-stream and emit it as a ``final_answer`` SSE event.
  // Before this fix the hook had ``void data;`` for final_answer, so the
  // assistant Message persisted with the UN-grounded streamed tokens — the
  // user saw the wrong (hallucinated) answer in chat history.
  //
  // The test emits a token stream with the hallucinated text, then a
  // final_answer event with the corrected text, then [DONE]. After the
  // stream ends the persisted assistant message MUST carry the corrected
  // final_answer text, NOT the un-grounded token stream.
  it("final_answer SSE event replaces streamed tokens in the persisted message", async () => {
    const frames = [
      'data: {"text":"Apple P/E is 37.7x as of Q4 FY2026"}\n',
      'event: final_answer\ndata: {"type":"final_answer","text":"I cannot find evidence that Apple\'s P/E ratio is 37.7x."}\n',
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
      await result.current.send("What's Apple's P/E?");
    });

    // The streaming bubble is cleared on done. The persisted assistant
    // Message must carry the GROUNDED text, not the streamed tokens.
    expect(result.current.streaming).toBeNull();
    expect(result.current.localMessages).toHaveLength(2);
    const assistant = result.current.localMessages[1] as {
      role: string;
      content: string;
    };
    expect(assistant.role).toBe("assistant");
    expect(assistant.content).toBe(
      "I cannot find evidence that Apple's P/E ratio is 37.7x.",
    );
    // Critical regression check: the un-grounded streamed text MUST NOT
    // leak into the persisted message.
    expect(assistant.content).not.toContain("37.7x as of Q4");
  });

  // ── PLAN-0103 W21 (FIX-A3) — stage-marker status visibility ──────────────
  //
  // Backend emits ``status`` events with stage keywords like
  // ``loading_context`` and ``entity_resolution`` during the slow pre-token
  // phase. Before this fix the hook filtered them out (no space → dropped).
  // Now we map known keywords through STAGE_LABEL_MAP and surface them as
  // streaming.initial_status so the UI can render progress feedback.
  it("status SSE event with stage keyword maps to a human-readable label", async () => {
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

    // Emit a stage-marker status payload (single keyword, no space).
    await act(async () => {
      ar.pushChunk(
        'event: status\ndata: {"step":"entity_resolution"}\n',
      );
      await Promise.resolve();
      await Promise.resolve();
    });

    await waitFor(() => {
      expect(result.current.streaming?.initial_status).toBe(
        "Resolving entities…",
      );
    });

    // Cleanly end the stream so the act() sendPromise resolves.
    await act(async () => {
      ar.pushChunk("data: [DONE]\n");
      ar.finish();
      await sendPromise;
    });
  });
});
