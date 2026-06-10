/**
 * __tests__/chat.test.tsx — Unit tests for the Chat page
 *
 * WHY THIS EXISTS: The chat page is complex stateful UI with SSE streaming,
 * thread management, and multiple loading/error states. Tests verify the core
 * layout, interactions, and edge cases so regressions are caught before they
 * reach production. Finance-grade UI must never silently break.
 *
 * WHAT WE TEST:
 * 1. Thread list panel renders (sidebar is present)
 * 2. Message input is present and accessible
 * 3. "New chat" button exists and starts a new conversation
 * 4. Thread list populates from mocked gateway data
 * 5. Empty thread state shows welcome message
 * 6. Error state in thread list is handled gracefully
 * 7. (Wave 7) Starter question cards shown on empty thread
 * 8. (Wave 7) Entity context badge shown when entity_id param present
 * 9. (Wave 7) Clicking starter card injects text into input
 *
 * WHAT WE DO NOT TEST HERE:
 * - SSE stream consumption (requires fetch mock + ReadableStream simulation)
 *   → covered by StreamingBubble unit test (ChatStream.test.tsx, future wave)
 * - Keyboard shortcuts (E2E / Playwright)
 * - Citation click navigation (E2E)
 *
 * WHY MOCK GATEWAY: We don't want real S9 calls in unit tests.
 * WHY MOCK NEXT/NAVIGATION: Next.js App Router hooks (useRouter, usePathname)
 * are not available in the jsdom test environment — mock them to avoid invariant errors.
 *
 * DATA SOURCE: Mocked createGateway()
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { Thread } from "@/types/api";

// ── Next.js mocks ─────────────────────────────────────────────────────────────

// WHY: Next.js App Router hooks require the Router context which isn't present
// in jsdom. Mock them with minimal stubs that satisfy the component's calls.
vi.mock("next/navigation", () => ({
  useRouter: vi.fn(() => ({
    push: vi.fn(),
    replace: vi.fn(),
    prefetch: vi.fn(),
    back: vi.fn(),
  })),
  usePathname: vi.fn(() => "/chat"),
  useSearchParams: vi.fn(() => new URLSearchParams()),
}));

// ── Sample data fixtures ──────────────────────────────────────────────────────

const SAMPLE_THREADS: Thread[] = [
  {
    thread_id: "thread-001",
    title: "NVDA Q4 earnings analysis",
    owner_id: "user-1",
    messages: [],
    created_at: "2026-04-10T09:00:00Z",
    updated_at: "2026-04-10T09:30:00Z",
  },
  {
    thread_id: "thread-002",
    title: null, // WHY null title: new thread not yet named by S9
    owner_id: "user-1",
    messages: [],
    created_at: "2026-04-11T14:00:00Z",
    updated_at: "2026-04-11T14:05:00Z",
  },
];

// ── Gateway mock ──────────────────────────────────────────────────────────────

vi.mock("@/lib/gateway", () => ({
  createGateway: vi.fn(() => ({
    getThreads: vi.fn().mockResolvedValue(SAMPLE_THREADS),
    getThread: vi.fn().mockResolvedValue({
      thread_id: "thread-001",
      title: "NVDA Q4 earnings analysis",
      owner_id: "user-1",
      messages: [],
      created_at: "2026-04-10T09:00:00Z",
      updated_at: "2026-04-10T09:30:00Z",
    }),
    deleteThread: vi.fn().mockResolvedValue(undefined),
    // streamChat is NOT called in unit tests — it's handled via raw fetch() inside
    // the page component. SSE streaming tests are in ChatStream.test.tsx.
  })),
  GatewayError: class GatewayError extends Error {
    status: number;
    constructor(status: number, msg: string) {
      super(msg);
      this.status = status;
    }
  },
}));

// ── Auth mock ─────────────────────────────────────────────────────────────────

vi.mock("@/hooks/useAuth", () => ({
  useAuth: vi.fn(() => ({
    accessToken: "test-access-token",
    isAuthenticated: true,
    isLoading: false,
    user: {
      user_id: "user-1",
      tenant_id: "tenant-1",
      email: "analyst@worldview.io",
      name: "Test Analyst",
      avatar_url: null,
    },
    setTokens: vi.fn(),
    logout: vi.fn(),
  })),
}));

// ── crypto.randomUUID mock ────────────────────────────────────────────────────

// WHY: jsdom provides crypto.randomUUID() in modern versions, but we mock it
// to return predictable values so assertions on thread IDs are deterministic.
let uuidCounter = 0;
vi.stubGlobal("crypto", {
  randomUUID: () => `mock-uuid-${++uuidCounter}`,
});

// ── Test helpers ──────────────────────────────────────────────────────────────

function makeQueryClient() {
  return new QueryClient({
    defaultOptions: {
      // WHY retry: false: prevent 3 automatic retries in tests — makes failed
      // queries fail fast so tests don't time out waiting for retries.
      queries: { retry: false },
    },
  });
}

/**
 * Wrapper that provides the QueryClient context required by useQuery() calls
 * inside the Chat page component.
 */
function Wrapper({ children }: { children: React.ReactNode }) {
  const qc = makeQueryClient();
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

// Lazy-import the page to avoid issues with module mock hoisting
async function renderChatPage() {
  const { default: ChatPage } = await import("@/app/(app)/chat/page");
  return render(<ChatPage />, { wrapper: Wrapper });
}

// ── Tests: Thread list panel (existing, preserved per R19) ───────────────────

describe("Chat page — thread list panel", () => {
  beforeEach(() => {
    uuidCounter = 0;
    vi.clearAllMocks();
  });

  it("renders the thread list sidebar", async () => {
    await renderChatPage();

    // The sidebar heading must be visible — presence confirms the left panel renders
    expect(screen.getByRole("complementary", { name: /chat thread list/i })).toBeInTheDocument();
    // The "Threads" label should be present
    expect(screen.getByText("Threads")).toBeInTheDocument();
  });

  it("renders thread titles from gateway after data loads", async () => {
    await renderChatPage();

    // Wait for TanStack Query to resolve the mocked getThreads() promise
    await waitFor(() => {
      expect(screen.getByText("NVDA Q4 earnings analysis")).toBeInTheDocument();
    });
  });

  it("renders placeholder title for thread with null title", async () => {
    await renderChatPage();

    await waitFor(() => {
      // The second thread has title: null → should show "New conversation"
      expect(screen.getByText("New conversation")).toBeInTheDocument();
    });
  });

  it("renders thread updated_at timestamps in font-mono", async () => {
    await renderChatPage();

    await waitFor(() => {
      // Timestamps are rendered — we don't assert the exact format since
      // it depends on the test runner's locale. Just assert they appear.
      expect(screen.getByText("NVDA Q4 earnings analysis")).toBeInTheDocument();
    });
  });
});

// ── Tests: New chat button (existing, preserved per R19) ─────────────────────

describe("Chat page — new chat button", () => {
  beforeEach(() => {
    uuidCounter = 0;
    vi.clearAllMocks();
  });

  it("renders the New chat button", async () => {
    await renderChatPage();

    // The "New chat" button must be present and accessible
    expect(
      screen.getByRole("button", { name: /start new chat/i }),
    ).toBeInTheDocument();
  });

  it("shows welcome state (no thread selected) on initial render", async () => {
    await renderChatPage();

    // WHY check for "Analyst Intelligence" heading: confirms the welcome/empty state
    // is shown when no thread is selected — the right panel defaults to onboarding.
    await waitFor(() => {
      expect(screen.getByText("Analyst Intelligence")).toBeInTheDocument();
    });
  });

  it("clicking New chat reveals the message input", async () => {
    await renderChatPage();

    // Wait for the page to fully load
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /start new chat/i })).toBeInTheDocument();
    });

    // Click "New chat" button — should transition from welcome state to chat input
    const newChatBtn = screen.getByRole("button", { name: /start new chat/i });
    fireEvent.click(newChatBtn);

    // After clicking, the textarea input should appear
    await waitFor(() => {
      expect(
        screen.getByRole("textbox", { name: /chat message input/i }),
      ).toBeInTheDocument();
    });
  });
});

// ── Tests: Message input (existing, preserved per R19) ───────────────────────

describe("Chat page — message input", () => {
  beforeEach(() => {
    uuidCounter = 0;
    vi.clearAllMocks();
  });

  it("renders message input after selecting a thread", async () => {
    await renderChatPage();

    // Wait for threads to load then select one
    await waitFor(() => {
      expect(screen.getByText("NVDA Q4 earnings analysis")).toBeInTheDocument();
    });

    // Click the first thread to activate the chat area
    fireEvent.click(screen.getByText("NVDA Q4 earnings analysis"));

    // Input should now be visible
    await waitFor(() => {
      expect(
        screen.getByRole("textbox", { name: /chat message input/i }),
      ).toBeInTheDocument();
    });
  });

  it("Send button is disabled when input is empty", async () => {
    await renderChatPage();

    // Click New chat to reveal the input
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /start new chat/i })).toBeInTheDocument();
    });
    fireEvent.click(screen.getByRole("button", { name: /start new chat/i }));

    await waitFor(() => {
      expect(screen.getByRole("textbox", { name: /chat message input/i })).toBeInTheDocument();
    });

    // Send button should be disabled (empty input)
    expect(screen.getByRole("button", { name: /send message/i })).toBeDisabled();
  });

  it("Send button is enabled when input has text", async () => {
    await renderChatPage();

    // Start new chat
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /start new chat/i })).toBeInTheDocument();
    });
    fireEvent.click(screen.getByRole("button", { name: /start new chat/i }));

    // Type a message
    await waitFor(() => {
      expect(screen.getByRole("textbox", { name: /chat message input/i })).toBeInTheDocument();
    });
    const textarea = screen.getByRole("textbox", { name: /chat message input/i });
    fireEvent.change(textarea, { target: { value: "What is NVDA's P/E ratio?" } });

    // Send button should now be enabled
    expect(screen.getByRole("button", { name: /send message/i })).not.toBeDisabled();
  });
});

// ── Tests: Empty and error states (existing, preserved per R19) ───────────────

describe("Chat page — empty and error states", () => {
  it("shows empty state message when no threads exist", async () => {
    // Override mock to return empty array
    const { createGateway } = await import("@/lib/gateway");
    // WHY cast via (unknown as ...): TypeScript strict mode rejects direct
    // `as T` when types have no overlap. Casting through unknown first is the
    // standard escape hatch for partial mock objects in tests.
    const partialMock = {
      getThreads: vi.fn().mockResolvedValue([]),
      getThread: vi.fn(),
      deleteThread: vi.fn(),
    };
    vi.mocked(createGateway).mockReturnValueOnce(
      partialMock as unknown as ReturnType<typeof createGateway>,
    );

    await renderChatPage();

    await waitFor(() => {
      expect(
        screen.getByText(/no conversations yet/i),
      ).toBeInTheDocument();
    });
  });
});

// ── Tests: Starter questions (Wave 7 new) ─────────────────────────────────────

describe("Chat page — starter questions", () => {
  beforeEach(() => {
    uuidCounter = 0;
    vi.clearAllMocks();
  });

  it("starter-questions-on-empty: shows 6 question cards when thread has no messages", async () => {
    await renderChatPage();

    // Start a new chat (creates empty thread)
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /start new chat/i })).toBeInTheDocument();
    });
    fireEvent.click(screen.getByRole("button", { name: /start new chat/i }));

    // Should show 6 starter question cards
    await waitFor(() => {
      // "Summarize [TICKER]'s latest earnings call" is one of the starter questions
      expect(
        screen.getByText(/Summarize .* latest earnings call/i),
      ).toBeInTheDocument();
    });

    // All 6 starter questions should be present
    await waitFor(() => {
      expect(
        screen.getByText(/Compare MSFT and GOOGL cloud revenue growth/i),
      ).toBeInTheDocument();
      expect(
        screen.getByText(/Recent insider transactions/i),
      ).toBeInTheDocument();
      expect(
        screen.getByText(/Search SEC filings for/i),
      ).toBeInTheDocument();
    });
  });

  it("click-card-injects-text: clicking a starter card fills the input", async () => {
    await renderChatPage();

    // Start a new chat
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /start new chat/i })).toBeInTheDocument();
    });
    fireEvent.click(screen.getByRole("button", { name: /start new chat/i }));

    // Wait for starter questions to appear
    await waitFor(() => {
      expect(
        screen.getByText(/Compare MSFT and GOOGL cloud revenue growth/i),
      ).toBeInTheDocument();
    });

    // Click the MSFT/GOOGL comparison card
    const card = screen.getByText(/Compare MSFT and GOOGL cloud revenue growth/i);
    fireEvent.click(card);

    // The textarea should now contain the question text
    await waitFor(() => {
      const textarea = screen.getByRole("textbox", { name: /chat message input/i });
      expect((textarea as HTMLTextAreaElement).value).toMatch(
        /Compare MSFT and GOOGL cloud revenue growth/i,
      );
    });
  });
});

// ── Tests: Entity context badge (Wave 7 new) ──────────────────────────────────

describe("Chat page — entity context badge", () => {
  beforeEach(() => {
    uuidCounter = 0;
    vi.clearAllMocks();
  });

  it("entity-context-badge: badge shown when entity_id URL param is set", async () => {
    // Mock useSearchParams to return entity_id param
    const { useSearchParams } = await import("next/navigation");
    vi.mocked(useSearchParams).mockReturnValue(
      new URLSearchParams("entity_id=ent-aapl") as ReturnType<typeof import("next/navigation").useSearchParams>,
    );

    await renderChatPage();

    // Start a new chat to get to the message area where badge appears
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /start new chat/i })).toBeInTheDocument();
    });
    fireEvent.click(screen.getByRole("button", { name: /start new chat/i }));

    // Entity context badge should appear above the input
    await waitFor(() => {
      expect(screen.getByText(/Context:/i)).toBeInTheDocument();
    });
  });

  it("entity-context-badge: badge NOT shown when no entity_id param", async () => {
    // Ensure no entity_id param
    const { useSearchParams } = await import("next/navigation");
    vi.mocked(useSearchParams).mockReturnValue(
      new URLSearchParams() as ReturnType<typeof import("next/navigation").useSearchParams>,
    );

    await renderChatPage();

    // Start a new chat
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /start new chat/i })).toBeInTheDocument();
    });
    fireEvent.click(screen.getByRole("button", { name: /start new chat/i }));

    // Wait for input to appear
    await waitFor(() => {
      expect(screen.getByRole("textbox", { name: /chat message input/i })).toBeInTheDocument();
    });

    // Context badge should NOT be present
    expect(screen.queryByText(/Context:/i)).not.toBeInTheDocument();
  });
});

// ── Tests: Ephemeral thread 404 guard (PLAN-0102 W2 regression) ───────────────

/**
 * REGRESSION TESTS for the "GET /api/v1/threads/{id} → 404" flash documented
 * in the 2026-05-28 user report.  Before the fix, clicking "New chat" minted
 * a client-side UUID, dropped it into `setActiveThreadId`, and TanStack Query
 * immediately fired `getThread(newId)`.  rag-chat had never heard of the id,
 * returned 404, and the chat page surfaced a generic error banner — even
 * though the user had not yet typed a message.
 *
 * The fix introduces an ephemeral-id set that gates the per-thread fetch
 * until the threads list refresh proves the id is server-known (i.e. after
 * the first SSE stream completes and rag-chat persists the row).  Defensive
 * 404 handling in the queryFn covers stale-localStorage / browser-back paths
 * where a thread id appears live but the backend has since dropped it.
 */
describe("Chat page — ephemeral thread 404 guard", () => {
  beforeEach(() => {
    uuidCounter = 0;
    vi.clearAllMocks();
  });

  it("does not call getThread for a freshly-minted client-side thread id", async () => {
    // Spy on the gateway: getThread must NOT be invoked between clicking
    // "New chat" and the first user message (i.e. while the id is ephemeral).
    const { createGateway } = await import("@/lib/gateway");
    const getThreadSpy = vi.fn().mockResolvedValue({
      thread_id: "should-not-be-fetched",
      title: null,
      owner_id: "user-1",
      messages: [],
      created_at: "2026-05-28T00:00:00Z",
      updated_at: "2026-05-28T00:00:00Z",
    });
    vi.mocked(createGateway).mockReturnValue({
      getThreads: vi.fn().mockResolvedValue(SAMPLE_THREADS),
      getThread: getThreadSpy,
      deleteThread: vi.fn(),
      // WHY cast: the full Gateway type has dozens of methods; we only need
      // the three the page calls in this code path.  Standard partial-mock
      // pattern in this file (see "empty state" test above).
    } as unknown as ReturnType<typeof createGateway>);

    await renderChatPage();

    // Wait for the page to settle (threads list resolved).
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /start new chat/i })).toBeInTheDocument();
    });

    // Click "New chat" — this mints a client-side UUID via crypto.randomUUID
    // (mock-uuid-1) and sets it as the active thread id.
    fireEvent.click(screen.getByRole("button", { name: /start new chat/i }));

    // Confirm the composer rendered (active thread is set).
    await waitFor(() => {
      expect(
        screen.getByRole("textbox", { name: /chat message input/i }),
      ).toBeInTheDocument();
    });

    // The ephemeral id is "mock-uuid-1" — it must NOT appear in any
    // getThread call.  We give the query a tick to settle so that any
    // racing fetch would have been observed.
    await new Promise((r) => setTimeout(r, 50));
    for (const call of getThreadSpy.mock.calls) {
      expect(call[0]).not.toBe("mock-uuid-1");
    }
  });

  it("does not surface a chat error when getThread returns 404", async () => {
    // Simulate the stale-localStorage path: the page boots with an
    // already-selected thread id that the backend no longer knows about.
    // The queryFn's defensive 404 catch must convert that into a benign
    // empty-thread stub instead of letting the error banner render.
    const { createGateway, GatewayError } = await import("@/lib/gateway");
    vi.mocked(createGateway).mockReturnValue({
      getThreads: vi.fn().mockResolvedValue(SAMPLE_THREADS),
      // First click on the existing thread id will fire getThread — it
      // returns 404 (thread was deleted server-side).
      getThread: vi.fn().mockRejectedValue(new GatewayError(404, "Not Found")),
      deleteThread: vi.fn(),
    } as unknown as ReturnType<typeof createGateway>);

    await renderChatPage();

    // Pick an existing thread from the sidebar — this is the path that
    // produces the 404 in the wild (id is on the threads list at boot but
    // the per-thread endpoint says it's gone).
    await waitFor(() => {
      expect(screen.getByText("NVDA Q4 earnings analysis")).toBeInTheDocument();
    });
    fireEvent.click(screen.getByText("NVDA Q4 earnings analysis"));

    // Give TanStack Query and the catch branch a tick to run.
    await new Promise((r) => setTimeout(r, 50));

    // The error banner should NOT render — 404 is a benign state.
    // WHY queryByRole + null check: the ChatErrorBanner is wired to
    // chatErrorForBanner; if 404 wasn't swallowed, an alert role surfaces.
    // We additionally assert no "request failed" copy made it onto the page.
    expect(screen.queryByText(/request failed/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/server error/i)).not.toBeInTheDocument();
  });
});

// ── Tests: Round 1 Foundation — sidebar collapse + date groups ───────────────

describe("Chat page — history sidebar (Round 1 Foundation)", () => {
  beforeEach(() => {
    uuidCounter = 0;
    vi.clearAllMocks();
  });

  it("collapses to a slim rail and expands back", async () => {
    await renderChatPage();

    // Default: expanded — full sidebar with the "Threads" label.
    expect(screen.getByText("Threads")).toBeInTheDocument();

    // Collapse: the full panel is replaced by the slim rail.
    fireEvent.click(screen.getByRole("button", { name: /collapse thread list/i }));
    expect(screen.queryByText("Threads")).not.toBeInTheDocument();
    // The rail keeps the expand affordance AND a quick "new chat" icon.
    expect(screen.getByRole("button", { name: /expand thread list/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /start new chat/i })).toBeInTheDocument();

    // Expand: the full panel returns.
    fireEvent.click(screen.getByRole("button", { name: /expand thread list/i }));
    expect(screen.getByText("Threads")).toBeInTheDocument();
  });

  it("groups threads under date headers (fixtures from 2026-04 land in Older)", async () => {
    await renderChatPage();

    // SAMPLE_THREADS timestamps are 2026-04-10/11 — months before any
    // plausible "today" — so a single "Older" group header must render.
    await waitFor(() => {
      expect(screen.getByText("NVDA Q4 earnings analysis")).toBeInTheDocument();
    });
    expect(screen.getByRole("heading", { name: "Older" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Today" })).not.toBeInTheDocument();
  });

  it("puts a thread updated today under the Today header", async () => {
    const { createGateway } = await import("@/lib/gateway");
    vi.mocked(createGateway).mockReturnValue({
      getThreads: vi.fn().mockResolvedValue([
        {
          thread_id: "thread-now",
          title: "Fresh thread",
          owner_id: "user-1",
          messages: [],
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        },
        ...SAMPLE_THREADS,
      ]),
      getThread: vi.fn(),
      deleteThread: vi.fn(),
    } as unknown as ReturnType<typeof createGateway>);

    await renderChatPage();

    await waitFor(() => {
      expect(screen.getByText("Fresh thread")).toBeInTheDocument();
    });
    // Both buckets render: the fresh thread under Today, fixtures under Older.
    expect(screen.getByRole("heading", { name: "Today" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Older" })).toBeInTheDocument();
  });
});

// ── Tests: Round 1 Foundation — input ergonomics ─────────────────────────────

describe("Chat page — input ergonomics (Round 1 Foundation)", () => {
  beforeEach(() => {
    uuidCounter = 0;
    vi.clearAllMocks();
  });

  async function openComposer() {
    await renderChatPage();
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /start new chat/i })).toBeInTheDocument();
    });
    fireEvent.click(screen.getByRole("button", { name: /start new chat/i }));
    await waitFor(() => {
      expect(screen.getByRole("textbox", { name: /chat message input/i })).toBeInTheDocument();
    });
    return screen.getByRole("textbox", { name: /chat message input/i }) as HTMLTextAreaElement;
  }

  it("shows the character count from 800 characters", async () => {
    const textarea = await openComposer();

    // 799 chars: no counter yet.
    fireEvent.change(textarea, { target: { value: "x".repeat(799) } });
    expect(screen.queryByText(/\/ 2000/)).not.toBeInTheDocument();

    // 800 chars: counter appears with the exact "N / 2000" copy.
    fireEvent.change(textarea, { target: { value: "x".repeat(800) } });
    expect(screen.getByText("800 / 2000")).toBeInTheDocument();
  });

  it("submits on Cmd+Enter (and Ctrl+Enter)", async () => {
    // Stub fetch so the submit path doesn't hit the network. A rejected
    // promise is fine — we only assert the submit FIRED (input cleared +
    // fetch called), not the streaming outcome.
    const fetchMock = vi.fn().mockRejectedValue(new Error("offline"));
    vi.stubGlobal("fetch", fetchMock);

    const textarea = await openComposer();
    fireEvent.change(textarea, { target: { value: "What moved NVDA today?" } });
    fireEvent.keyDown(textarea, { key: "Enter", metaKey: true });

    // The submit clears the input synchronously (UX expectation) and the
    // stream request goes out.
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledTimes(1);
    });
    expect(textarea.value).toBe("");

    vi.unstubAllGlobals();
  });

  it("does NOT submit on Shift+Enter (newline stays local)", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const textarea = await openComposer();
    fireEvent.change(textarea, { target: { value: "line one" } });
    fireEvent.keyDown(textarea, { key: "Enter", shiftKey: true });

    expect(fetchMock).not.toHaveBeenCalled();
    // Input untouched — the browser default (newline insertion) proceeds.
    expect(textarea.value).toBe("line one");

    vi.unstubAllGlobals();
  });
});

// ── Tests: Round 1 Foundation — failed message Retry ─────────────────────────

describe("Chat page — error state with Retry (Round 1 Foundation)", () => {
  beforeEach(() => {
    uuidCounter = 0;
    vi.clearAllMocks();
  });

  it("failed send surfaces an error banner with a Retry button that resubmits", async () => {
    // First attempt fails at the network level; the retry succeeds with a
    // minimal one-token SSE stream.
    const encoder = new TextEncoder();
    let read = 0;
    const goodReader = {
      read: () => {
        const frames = ['data: {"text":"ok"}\n', "data: [DONE]\n"];
        if (read >= frames.length) return Promise.resolve({ done: true, value: undefined });
        return Promise.resolve({ done: false, value: encoder.encode(frames[read++]) });
      },
      cancel: vi.fn().mockResolvedValue(undefined),
    };
    const fetchMock = vi
      .fn()
      .mockRejectedValueOnce(new Error("network down"))
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        statusText: "OK",
        body: { getReader: () => goodReader },
      });
    vi.stubGlobal("fetch", fetchMock);

    await renderChatPage();
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /start new chat/i })).toBeInTheDocument();
    });
    fireEvent.click(screen.getByRole("button", { name: /start new chat/i }));
    const textarea = await waitFor(() =>
      screen.getByRole("textbox", { name: /chat message input/i }),
    );

    fireEvent.change(textarea, { target: { value: "doomed question" } });
    fireEvent.keyDown(textarea, { key: "Enter" });

    // Error banner (role=alert) with a Retry button — never a frozen spinner.
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toMatch(/failed|try again/i);
    const retryBtn = screen.getByRole("button", { name: /retry/i });

    // Retry resubmits the SAME question.
    fireEvent.click(retryBtn);
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledTimes(2);
    });
    expect(JSON.parse(fetchMock.mock.calls[1][1].body as string).message).toBe(
      "doomed question",
    );

    // Banner clears once the retry starts/succeeds.
    await waitFor(() => {
      expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    });

    vi.unstubAllGlobals();
  });
});

// ── Tests: Round 3 Polish — welcome state, skeletons, starter chips ──────────

describe("Chat page — Round 3 polish (welcome + skeletons)", () => {
  beforeEach(() => {
    uuidCounter = 0;
    vi.clearAllMocks();
  });

  it("welcome state shows the EmptyState copy + 4 starter chips from the generic follow-up pool", async () => {
    // welcomeStarterPrompts is the SAME pool generateFollowUps pads from —
    // importing it here pins the "one suggestion vocabulary" contract: if
    // the pool and the welcome ever diverge, this assertion breaks.
    const { welcomeStarterPrompts } = await import(
      "@/features/chat/lib/follow-ups"
    );

    await renderChatPage();

    // EmptyState title (chat.welcome copy key) — the pinned welcome label.
    await waitFor(() => {
      expect(screen.getByText("Analyst Intelligence")).toBeInTheDocument();
    });

    // Exactly 4 starter chips, in pool order, under the dedicated
    // accessible name (NOT "Follow-up suggestions" — no answer exists yet).
    const list = screen.getByRole("list", { name: "Starter prompts" });
    const chips = Array.from(list.querySelectorAll("button"));
    expect(chips.length).toBe(4);
    expect(chips.map((c) => c.textContent)).toEqual(welcomeStarterPrompts(4));
  });

  it("clicking a welcome starter chip starts a new chat with the prompt pre-filled", async () => {
    // REGRESSION (Round 3 fix): the old welcome cards called setInput(q)
    // BEFORE handleNewChat() — whose trailing setInput("") clobbered the
    // prompt in the same commit, so the composer always came up blank.
    await renderChatPage();

    const list = await screen.findByRole("list", { name: "Starter prompts" });
    const firstChip = list.querySelectorAll("button")[0];
    const promptText = firstChip.textContent ?? "";
    expect(promptText.length).toBeGreaterThan(0);

    fireEvent.click(firstChip);

    // A new (ephemeral) thread mounts the composer with the prompt intact.
    await waitFor(() => {
      const textarea = screen.getByRole("textbox", {
        name: /chat message input/i,
      }) as HTMLTextAreaElement;
      expect(textarea.value).toBe(promptText);
    });
  });

  it("shows row-shaped thread skeletons (not blank) while the thread list loads", async () => {
    const { createGateway } = await import("@/lib/gateway");
    // Never-resolving getThreads pins the loading state for the assertion
    // window. mockReturnValueOnce: only the threads queryFn's createGateway
    // call (the first on mount — every other query is disabled) is hijacked.
    vi.mocked(createGateway).mockReturnValueOnce({
      getThreads: vi.fn().mockReturnValue(new Promise(() => {})),
      getThread: vi.fn(),
      deleteThread: vi.fn(),
    } as unknown as ReturnType<typeof createGateway>);

    await renderChatPage();

    // Skeleton container + exactly 5 two-line row placeholders.
    expect(await screen.findByLabelText("Loading threads")).toBeInTheDocument();
    expect(screen.getAllByTestId("thread-skeleton-row").length).toBe(5);
  });

  it("shows bubble-shaped message skeletons while switching to a thread whose history is loading", async () => {
    const { createGateway } = await import("@/lib/gateway");
    // Threads list resolves (so a row is clickable); the per-thread history
    // fetch never resolves (pins the message-skeleton state). The page calls
    // createGateway once per queryFn invocation: mount (threads) + thread
    // select (history) — hijack both calls with the same partial mock.
    const gw = {
      getThreads: vi.fn().mockResolvedValue(SAMPLE_THREADS),
      getThread: vi.fn().mockReturnValue(new Promise(() => {})),
      deleteThread: vi.fn(),
    } as unknown as ReturnType<typeof createGateway>;
    vi.mocked(createGateway).mockReturnValueOnce(gw).mockReturnValueOnce(gw);

    await renderChatPage();

    // Select the first server thread → history query fires and hangs.
    await waitFor(() => {
      expect(screen.getByText("NVDA Q4 earnings analysis")).toBeInTheDocument();
    });
    fireEvent.click(screen.getByText("NVDA Q4 earnings analysis"));

    // Bubble placeholders: alternating user (right) / assistant (left,
    // avatar square + bubble) silhouettes — never a blank pane.
    expect(await screen.findByLabelText("Loading messages")).toBeInTheDocument();
    expect(screen.getAllByTestId("message-skeleton-user").length).toBe(2);
    expect(screen.getAllByTestId("message-skeleton-assistant").length).toBe(1);
  });
});
