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
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

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
      <ChatPage />
    </QueryClientProvider>,
  );
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
