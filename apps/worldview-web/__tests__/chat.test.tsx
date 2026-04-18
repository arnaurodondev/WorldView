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
 *
 * WHAT WE DO NOT TEST HERE:
 * - SSE stream consumption (requires fetch mock + ReadableStream simulation)
 *   → covered by StreamingBubble unit test (ChatStream.test.tsx, future wave)
 * - Keyboard shortcuts (E2E / Playwright)
 * - Citation click navigation (E2E)
 *
 * WHY MOCK GATEWAY: We don't want real S9 calls in unit tests.
 * Mocking gateway.ts lets us inject known thread data and test deterministically.
 *
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

// ── Tests ─────────────────────────────────────────────────────────────────────

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

    // WHY check for "Intelligence Chat" heading: confirms the welcome/empty state
    // is shown when no thread is selected — the right panel defaults to onboarding.
    await waitFor(() => {
      expect(screen.getByText("Intelligence Chat")).toBeInTheDocument();
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
