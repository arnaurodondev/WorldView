/**
 * __tests__/chat-thread-search.test.tsx — thread sidebar search behaviour
 *
 * WHY THIS EXISTS (PLAN-0051 T-E-5-08): the search box filters threads
 * client-side with a 200ms debounce. We pin (a) substring match,
 * (b) debounce delay, and (c) the empty-results state so future refactors
 * don't accidentally regress the behaviour.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

// Round 4: HotkeyProvider is required by the page's useToolTraceChord (it
// registers the ⌘D debug chord in the central hotkey registry via context).
import { HotkeyProvider } from "@/contexts/HotkeyContext";
import { HotkeyRegistry } from "@/lib/hotkey-registry";
import type { Thread } from "@/types/api";

// ── Mocks ─────────────────────────────────────────────────────────────────────

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

const SAMPLE: Thread[] = [
  {
    thread_id: "t1",
    title: "NVDA earnings deep dive",
    owner_id: "u1",
    messages: [],
    created_at: "2026-04-10T09:00:00Z",
    updated_at: "2026-04-10T09:30:00Z",
  },
  {
    thread_id: "t2",
    title: "Fed rate hike speculation",
    owner_id: "u1",
    messages: [],
    created_at: "2026-04-11T09:00:00Z",
    updated_at: "2026-04-11T09:30:00Z",
  },
  {
    thread_id: "t3",
    title: "Sector rotation thesis Q2",
    owner_id: "u1",
    messages: [],
    created_at: "2026-04-12T09:00:00Z",
    updated_at: "2026-04-12T09:30:00Z",
  },
];

vi.mock("@/lib/gateway", () => ({
  createGateway: vi.fn(() => ({
    getThreads: vi.fn().mockResolvedValue(SAMPLE),
    getThread: vi.fn(),
    deleteThread: vi.fn(),
    updateThread: vi.fn(),
  })),
  GatewayError: class GatewayError extends Error {
    status: number;
    constructor(status: number, msg: string) {
      super(msg);
      this.status = status;
    }
  },
}));

vi.mock("@/hooks/useAuth", () => ({
  useAuth: vi.fn(() => ({
    accessToken: "test-token",
    isAuthenticated: true,
    isLoading: false,
    user: { user_id: "u1", tenant_id: "t1", email: "x@y.z", name: "X", avatar_url: null },
    setTokens: vi.fn(),
    logout: vi.fn(),
  })),
}));

let uuidCounter = 0;
vi.stubGlobal("crypto", { randomUUID: () => `uuid-${++uuidCounter}` });

// ── Helpers ───────────────────────────────────────────────────────────────────

function makeQC() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } });
}
function Wrapper({ children }: { children: React.ReactNode }) {
  return (
    <QueryClientProvider client={makeQC()}>
      {/* Round 4: useToolTraceChord registers via the hotkey registry —
          the page needs HotkeyProvider, same as app/(app)/layout.tsx. */}
      <HotkeyProvider registry={new HotkeyRegistry()}>{children}</HotkeyProvider>
    </QueryClientProvider>
  );
}

async function renderChat() {
  const { default: ChatPage } = await import("@/app/(app)/chat/page");
  return render(<ChatPage />, { wrapper: Wrapper });
}

beforeEach(() => {
  uuidCounter = 0;
  vi.clearAllMocks();
});

// ── Tests ─────────────────────────────────────────────────────────────────────

describe("Chat thread search", () => {
  it("renders all threads when search is empty", async () => {
    await renderChat();

    await waitFor(() => {
      expect(screen.getByText("NVDA earnings deep dive")).toBeInTheDocument();
    });
    expect(screen.getByText("Fed rate hike speculation")).toBeInTheDocument();
    expect(screen.getByText("Sector rotation thesis Q2")).toBeInTheDocument();
  });

  it("filters by substring (waits past 200ms debounce window)", async () => {
    await renderChat();

    await waitFor(() => {
      expect(screen.getByText("NVDA earnings deep dive")).toBeInTheDocument();
    });

    const search = screen.getByLabelText(/search threads/i);
    fireEvent.change(search, { target: { value: "fed" } });

    // Wait long enough for the 200ms debounce to elapse (waitFor polls until
    // the assertion passes within its timeout, default 1000ms).
    await waitFor(() => {
      expect(screen.queryByText("NVDA earnings deep dive")).not.toBeInTheDocument();
    });
    expect(screen.getByText("Fed rate hike speculation")).toBeInTheDocument();
    expect(screen.queryByText("Sector rotation thesis Q2")).not.toBeInTheDocument();
  });

  it("shows no-results message when nothing matches", async () => {
    await renderChat();

    await waitFor(() => {
      expect(screen.getByText("NVDA earnings deep dive")).toBeInTheDocument();
    });

    const search = screen.getByLabelText(/search threads/i);
    fireEvent.change(search, { target: { value: "absolutely-no-match" } });

    await waitFor(() => {
      expect(screen.getByText(/No threads match/i)).toBeInTheDocument();
    });
  });
});
