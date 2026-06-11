/**
 * __tests__/chat-suggestions-preference.test.tsx — Wave 2 (frontend-rework
 * sprint): the chat page PREFERS server-emitted follow-up suggestions (the
 * `suggestions` SSE event, Wave-1 backend) over the client-side
 * generateFollowUps() templates, and falls back when the server sent none.
 *
 * STRATEGY: mock useChatStream wholesale — the page's preference logic is a
 * pure derivation over the hook's outputs (serverSuggestions + localMessages),
 * so driving the hook's return value directly pins the preference contract
 * without SSE plumbing (the event handling itself is covered in
 * features/chat/hooks/__tests__/useChatStream.test.tsx).
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { HotkeyProvider } from "@/contexts/HotkeyContext";
import { HotkeyRegistry } from "@/lib/hotkey-registry";
import type { Message } from "@/types/api";

// ── Next.js mocks ─────────────────────────────────────────────────────────────

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

// ── Gateway / auth mocks ──────────────────────────────────────────────────────

vi.mock("@/lib/gateway", () => ({
  createGateway: vi.fn(() => ({
    getThreads: vi.fn().mockResolvedValue([]),
    getThread: vi.fn().mockResolvedValue(null),
    deleteThread: vi.fn().mockResolvedValue(undefined),
  })),
  GatewayError: class GatewayError extends Error {},
}));

vi.mock("@/hooks/useAuth", () => ({
  useAuth: vi.fn(() => ({
    accessToken: "test-access-token",
    isAuthenticated: true,
    isLoading: false,
    user: { user_id: "u-1", tenant_id: "t-1", email: "a@b.c", name: "A" },
    setTokens: vi.fn(),
    logout: vi.fn(),
  })),
}));

// ── useChatStream mock — the knob under test ──────────────────────────────────

const ASSISTANT_MESSAGE: Message = {
  message_id: "m-2",
  thread_id: "thread-001",
  role: "assistant",
  content: "Apple Inc. (AAPL) is a technology company.",
  created_at: "2026-06-11T00:00:01Z",
  citations: [],
};

const USER_MESSAGE: Message = {
  message_id: "m-1",
  thread_id: "thread-001",
  role: "user",
  content: "In one short sentence, what is AAPL?",
  created_at: "2026-06-11T00:00:00Z",
  citations: [],
};

// Mutable per-test return shape for the mocked hook.
const hookState = {
  serverSuggestions: [] as string[],
};

vi.mock("@/features/chat/hooks/useChatStream", () => ({
  useChatStream: vi.fn(() => ({
    localMessages: [USER_MESSAGE, ASSISTANT_MESSAGE],
    setLocalMessages: vi.fn(),
    streaming: null,
    chatError: null,
    setChatError: vi.fn(),
    isStreaming: false,
    activeTools: [],
    pendingAction: null,
    clearPendingAction: vi.fn(),
    iterationEvent: null,
    toolTrace: [],
    serverSuggestions: hookState.serverSuggestions,
    toolUsage: [],
    send: vi.fn(),
    retry: vi.fn(),
    cancel: vi.fn(),
    resetForThread: vi.fn(),
  })),
}));

// ── Harness ───────────────────────────────────────────────────────────────────

function Wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return (
    <QueryClientProvider client={qc}>
      <HotkeyProvider registry={new HotkeyRegistry()}>{children}</HotkeyProvider>
    </QueryClientProvider>
  );
}

async function renderChatPageWithThread() {
  const { default: ChatPage } = await import("@/app/(app)/chat/page");
  const view = render(<ChatPage />, { wrapper: Wrapper });
  // The follow-up chips only render inside an ACTIVE thread. The mocked
  // hook always returns a settled conversation; activate a thread by
  // clicking "New chat" (mocked localMessages render regardless of id).
  const newChat = await screen.findAllByRole("button", {
    name: /start new chat/i,
  });
  newChat[0].click();
  return view;
}

// ── Tests ─────────────────────────────────────────────────────────────────────

describe("Chat page — server suggestions preference (Wave 2)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders the SERVER suggestions when the hook surfaced them", async () => {
    hookState.serverSuggestions = [
      "What's the latest news on Apple Inc.?",
      "How has AAPL performed recently?",
      "How do Apple Inc.'s fundamentals look?",
    ];
    await renderChatPageWithThread();

    // All three server chips render verbatim — no client templates.
    await waitFor(() => {
      expect(
        screen.getByText("What's the latest news on Apple Inc.?"),
      ).toBeInTheDocument();
    });
    expect(screen.getByText("How has AAPL performed recently?")).toBeInTheDocument();
    expect(
      screen.getByText("How do Apple Inc.'s fundamentals look?"),
    ).toBeInTheDocument();
  });

  it("falls back to the client generator when the server sent none", async () => {
    hookState.serverSuggestions = [];
    const { generateFollowUps } = await import("@/features/chat/lib/follow-ups");
    const { extractTickers } = await import("@/features/chat/lib/ticker-extract");

    // Compute the EXACT client fallback for this conversation — same inputs
    // the page memo derives (settled messages, no tools, no citations).
    const expected = generateFollowUps({
      answerText: ASSISTANT_MESSAGE.content,
      tickers: extractTickers([USER_MESSAGE, ASSISTANT_MESSAGE]).tickers,
      citationTitles: [],
      toolsUsed: [],
    });
    expect(expected.length).toBeGreaterThan(0);

    await renderChatPageWithThread();

    await waitFor(() => {
      expect(screen.getByText(expected[0])).toBeInTheDocument();
    });
  });
});
