/**
 * app/(app)/chat/__tests__/thread-param.test.tsx — Round 2 Enhancement.
 *
 * WHAT THESE GUARD:
 *   1. ?thread=<id> deep-link consumption — the command palette navigates to
 *      /chat?thread=<id> (Round 1 contract); the page must activate that
 *      thread on mount (fetch its history, render the conversation, skip the
 *      "no thread selected" empty state).
 *   2. No param → the empty state renders exactly as before (regression).
 *   3. Suggested follow-up chips render under the latest settled assistant
 *      answer, and clicking one submits it as the next message over the
 *      chat-stream endpoint.
 *
 * MOCKING MIRRORS app/(app)/portfolio/__tests__: gateway, auth and router are
 * stubbed; TanStack Query gets a real QueryClientProvider (retry off) so the
 * page's useQuery wiring is exercised for real.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, fireEvent, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

// Round 4: the page's useToolTraceChord now registers through the central
// hotkey registry (useHotkeyScope), which throws without a provider — the
// page must be rendered inside HotkeyProvider, exactly as in app/(app)/layout.
import { HotkeyProvider } from "@/contexts/HotkeyContext";
import { HotkeyRegistry } from "@/lib/hotkey-registry";

import type { Thread } from "@/types/api";

// ── Hoisted mock handles ──────────────────────────────────────────────────────
// WHY vi.hoisted: vi.mock factories are hoisted above this module's body —
// referencing plain module-level consts from inside a factory risks a TDZ
// crash depending on when the factory executes. vi.hoisted creates the
// handles in the same hoisted phase, making the reference unconditionally safe.
const h = vi.hoisted(() => ({
  pushMock: vi.fn(),
  getThreadMock: vi.fn(),
  getThreadsMock: vi.fn(),
}));
const { pushMock, getThreadMock, getThreadsMock } = h;

// ── Next.js navigation mock ───────────────────────────────────────────────────
// WHY a mutable holder: each test sets `currentSearch` BEFORE rendering so the
// same mock serves both the with-param and without-param cases. Read lazily
// (inside the arrow) so the hoisted factory never touches it at define time.
let currentSearch = "";
vi.mock("next/navigation", () => ({
  useRouter: vi.fn(() => ({
    push: pushMock,
    replace: vi.fn(),
    prefetch: vi.fn(),
  })),
  usePathname: vi.fn(() => "/chat"),
  useSearchParams: vi.fn(() => new URLSearchParams(currentSearch)),
}));

// ── Auth mock ─────────────────────────────────────────────────────────────────
vi.mock("@/hooks/useAuth", () => ({
  useAuth: vi.fn(() => ({
    accessToken: "test-token",
    isAuthenticated: true,
    isLoading: false,
    user: { user_id: "u1", tenant_id: "t1", email: "a@b.c", name: "Tester" },
  })),
}));

// ── Gateway mock ──────────────────────────────────────────────────────────────
// The deep-linked thread the page must load. Last message is an ASSISTANT
// turn so the Round-2 follow-up chips render beneath it.
const THREAD_FIXTURE: Thread = {
  thread_id: "t-123",
  title: "Deep-linked thread",
  owner_id: "u1",
  created_at: "2026-06-09T10:00:00Z",
  updated_at: "2026-06-09T10:05:00Z",
  messages: [
    {
      message_id: "m-1",
      thread_id: "t-123",
      role: "user",
      content: "What moved $NVDA today?",
      created_at: "2026-06-09T10:00:00Z",
      citations: [],
    },
    {
      message_id: "m-2",
      thread_id: "t-123",
      role: "assistant",
      content: "NVDA rose on datacenter demand.",
      created_at: "2026-06-09T10:01:00Z",
      citations: [],
    },
  ],
};

// Default-arm the hoisted handles (re-armed in beforeEach after clearAllMocks).
getThreadMock.mockResolvedValue(THREAD_FIXTURE);
getThreadsMock.mockResolvedValue([THREAD_FIXTURE]);

vi.mock("@/lib/gateway", () => ({
  createGateway: vi.fn(() => ({
    getThreads: getThreadsMock,
    getThread: getThreadMock,
    // Context-rail resolvers: resolve nothing so no mini-cards render and no
    // unhandled rejections leak into the output. The rail behaviour itself is
    // covered by ChatContextRail.test.tsx.
    searchInstruments: vi.fn().mockResolvedValue({ results: [], query: "" }),
    getCompanyOverview: vi.fn().mockResolvedValue(null),
    deleteThread: vi.fn(),
    updateThread: vi.fn(),
  })),
}));

import ChatPage from "@/app/(app)/chat/page";

// ── Helpers ───────────────────────────────────────────────────────────────────

function renderPage() {
  const qc = new QueryClient({
    // retry off: a failing query must fail FAST in tests, not after 3 backoffs.
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      {/* Fresh registry per render — avoids cross-test binding pollution
          through the process-wide singleton. */}
      <HotkeyProvider registry={new HotkeyRegistry()}>
        <ChatPage />
      </HotkeyProvider>
    </QueryClientProvider>,
  );
}

/**
 * hangingSseResponse — an SSE response whose reader NEVER resolves a read.
 * Keeps the stream "in flight" indefinitely so tests can observe the
 * mid-stream UI (StreamingBubble + typing indicator). The page's unmount
 * cleanup aborts the fetch, so nothing leaks past the test.
 */
function hangingSseResponse(): Partial<Response> {
  return {
    ok: true,
    status: 200,
    body: new ReadableStream<Uint8Array>({
      start() {
        // Never enqueue, never close — read() stays pending forever.
      },
    }),
  };
}

/** Minimal SSE stream that closes immediately — exercises the clean-EOF path
 *  of useChatStream without needing token frames. */
function emptySseResponse(): Partial<Response> {
  return {
    ok: true,
    status: 200,
    body: new ReadableStream<Uint8Array>({
      start(controller) {
        controller.close();
      },
    }),
  };
}

describe("ChatPage ?thread= deep link (Round 2)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // Re-arm resolved values cleared by clearAllMocks (it wipes impls set
    // via mockResolvedValue on hoisted fns? No — clear only wipes call
    // history; the resolved values persist. Re-arming is belt-and-braces
    // against a future switch to resetAllMocks.)
    getThreadMock.mockResolvedValue(THREAD_FIXTURE);
    getThreadsMock.mockResolvedValue([THREAD_FIXTURE]);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("activates the thread from ?thread=<id> and fetches its history", async () => {
    currentSearch = "thread=t-123";
    renderPage();

    // The per-thread query must fire with the deep-linked id.
    await waitFor(() => expect(getThreadMock).toHaveBeenCalledWith("t-123"));

    // The conversation renders: thread title (appears in BOTH the sidebar
    // ThreadItem and the header strip — hence findAllByText) + the
    // historical messages back-filled into the log.
    const titles = await screen.findAllByText("Deep-linked thread");
    expect(titles.length).toBeGreaterThanOrEqual(1);
    expect(
      await screen.findByText("What moved $NVDA today?"),
    ).toBeInTheDocument();

    // The "no thread selected" empty state must NOT render.
    expect(screen.queryByText("New conversation")).not.toBeInTheDocument();
  });

  it("shows the empty state when no ?thread= param is present", async () => {
    currentSearch = "";
    renderPage();

    // Empty state CTA renders; no per-thread fetch fires.
    expect(await screen.findByText("New conversation")).toBeInTheDocument();
    expect(getThreadMock).not.toHaveBeenCalled();
  });

  it("renders follow-up chips under the settled assistant answer and submits on click", async () => {
    currentSearch = "thread=t-123";
    // Stub fetch BEFORE render: clicking a chip fires the SSE POST.
    const fetchMock = vi.fn().mockResolvedValue(emptySseResponse());
    vi.stubGlobal("fetch", fetchMock);

    renderPage();

    // Wait for the history to land (last entry = assistant → chips appear).
    const chipList = await screen.findByRole("list", {
      name: "Follow-up suggestions",
    });
    const chips = chipList.querySelectorAll("button");
    // Generator returns exactly 3; presenter renders all of them (3 ≤ cap 4).
    expect(chips.length).toBe(3);

    // Clicking a chip submits its text as the next message on the stream
    // endpoint — the core "chip = next question" contract.
    const chipText = chips[0].textContent ?? "";
    fireEvent.click(chips[0]);
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/v1/chat/stream",
        expect.objectContaining({
          method: "POST",
          body: expect.stringContaining(JSON.stringify(chipText).slice(1, -1)),
        }),
      );
    });

    // Once the next message is sent the chips disappear (the optimistic user
    // bubble is now the last log entry, so the assistant-last guard fails).
    await waitFor(() => {
      expect(
        screen.queryByRole("list", { name: "Follow-up suggestions" }),
      ).not.toBeInTheDocument();
    });
  });
});

// ── Round 4 Hardening — aria-live strategy + thread-load failure ─────────────

describe("ChatPage message log live region (Round 4 a11y)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    getThreadMock.mockResolvedValue(THREAD_FIXTURE);
    getThreadsMock.mockResolvedValue([THREAD_FIXTURE]);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("settled messages live inside a polite role=log; the streaming bubble stays OUTSIDE it", async () => {
    currentSearch = "thread=t-123";
    // A stream that never produces a token — keeps the StreamingBubble (and
    // its typing indicator) mounted while we inspect the DOM topology.
    const fetchMock = vi.fn().mockResolvedValue(hangingSseResponse());
    vi.stubGlobal("fetch", fetchMock);

    renderPage();

    // The settled history renders inside the live log region. role="log" has
    // implicit aria-live=polite; we pin the EXPLICIT attribute so a refactor
    // can't silently downgrade the announcement contract.
    const log = await screen.findByRole("log", { name: "Conversation messages" });
    expect(log.getAttribute("aria-live")).toBe("polite");
    // Use findByText (not getByText): the role=log container mounts as soon as
    // the page renders, but the settled history message text is appended a tick
    // later once the thread fixture resolves. Under slow/parallel CI the
    // synchronous getByText raced the async render and intermittently threw
    // "unable to find element" at this line. findByText retries until the
    // message lands inside the log, preserving the same assertion contract.
    expect(
      await within(log).findByText("NVDA rose on datacenter demand."),
    ).toBeInTheDocument();

    // Start a stream (follow-up chip click → send). The in-flight bubble must
    // render OUTSIDE the live region — THIS is the announce-on-completion
    // strategy: if the StreamingBubble sat inside role=log, every SSE token
    // mutation would be announced, making long answers unusable under a
    // screen reader. Completion re-enters the log as ONE appended message.
    const chipList = await screen.findByRole("list", {
      name: "Follow-up suggestions",
    });
    fireEvent.click(chipList.querySelectorAll("button")[0]);

    const typing = await screen.findByLabelText("AI is generating a response");
    expect(log.contains(typing)).toBe(false);
  });
});

describe("ChatPage thread-LIST failure (Round 4 error recovery)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    getThreadMock.mockResolvedValue(THREAD_FIXTURE);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("shows a sidebar error with Retry while the composer path stays usable", async () => {
    currentSearch = "";
    // The threads list GET fails (network / 500). The sidebar must surface
    // an explicit error + Retry — and CRUCIALLY the rest of the page keeps
    // working: the user can still start a new conversation and type.
    getThreadsMock.mockRejectedValue(new Error("network down"));

    renderPage();

    // Sidebar error state with a Retry CTA (pre-existing UI — this test pins
    // it so a refactor can't silently drop the recovery affordance).
    expect(
      await screen.findByText(/failed to load threads/i),
    ).toBeInTheDocument();
    const retry = screen.getByRole("button", { name: "Retry" });

    // Composer still usable: the welcome CTA opens a new conversation and
    // the message input is enabled — a failed history fetch never locks the
    // user out of chatting.
    fireEvent.click(screen.getByRole("button", { name: /new conversation/i }));
    expect(await screen.findByLabelText("Chat message input")).toBeEnabled();

    // Retry re-fires the threads query.
    const callsBefore = getThreadsMock.mock.calls.length;
    fireEvent.click(retry);
    await waitFor(() => {
      expect(getThreadsMock.mock.calls.length).toBeGreaterThan(callsBefore);
    });
  });
});

describe("ChatPage thread-load failure (Round 4 error recovery)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    getThreadsMock.mockResolvedValue([THREAD_FIXTURE]);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("renders an error state with Retry instead of a blank conversation, and keeps the composer usable", async () => {
    currentSearch = "thread=t-123";
    // The history GET fails (network blip / 404 / 500) — previously this fell
    // through to the starter-question grid, presenting the failure as a
    // brand-new empty conversation.
    getThreadMock.mockRejectedValue(new Error("boom"));

    renderPage();

    // Explicit error surface with a Retry CTA…
    const errorBox = await screen.findByTestId("thread-load-error");
    expect(errorBox).toHaveTextContent(/couldn.t load this conversation/i);
    const retryButton = within(errorBox).getByRole("button", { name: "Retry" });

    // …and NOT the starter grid (the blank-conversation masquerade). The
    // string is the first entry of STARTER_QUESTIONS (features/chat/lib/
    // starters.ts) — the grid's most stable sentinel.
    expect(
      screen.queryByText("What are the key risks for [TICKER] next quarter?"),
    ).not.toBeInTheDocument();

    // The composer must stay usable — error recovery never locks out sending.
    expect(screen.getByLabelText("Chat message input")).toBeEnabled();

    // Retry re-fires the query.
    getThreadMock.mockResolvedValue(THREAD_FIXTURE);
    fireEvent.click(retryButton);
    await waitFor(() => {
      expect(getThreadMock.mock.calls.length).toBeGreaterThanOrEqual(2);
    });
    // Recovery: the history lands and the error state clears.
    expect(
      await screen.findByText("NVDA rose on datacenter demand."),
    ).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.queryByTestId("thread-load-error")).not.toBeInTheDocument();
    });
  });
});
