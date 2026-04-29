/**
 * __tests__/context-aware-starters.test.tsx — entity-aware starter questions
 *
 * WHY THIS EXISTS (PLAN-0051 T-E-5-08, T-E-5-05): "Open in Chat" buttons
 * pass ?entity_id= so the chat page can pre-load 4 entity-tailored starter
 * cards. These tests pin both the entity-present and entity-absent paths
 * so the substitution and the fallback are explicitly covered.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

vi.mock("next/navigation", () => ({
  useRouter: vi.fn(() => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn() })),
  usePathname: vi.fn(() => "/chat"),
  // useSearchParams returns the same instance per-render. We override per test.
  useSearchParams: vi.fn(() => new URLSearchParams()),
}));

vi.mock("@/lib/gateway", () => ({
  createGateway: vi.fn(() => ({
    getThreads: vi.fn().mockResolvedValue([]),
    getThread: vi.fn(),
    deleteThread: vi.fn(),
    updateThread: vi.fn(),
  })),
  GatewayError: class extends Error {
    constructor(public status: number, msg: string) {
      super(msg);
    }
  },
}));

vi.mock("@/hooks/useAuth", () => ({
  useAuth: () => ({
    accessToken: "tok",
    isAuthenticated: true,
    isLoading: false,
    user: null,
    setTokens: vi.fn(),
    logout: vi.fn(),
  }),
}));

let uuidCounter = 0;
vi.stubGlobal("crypto", { randomUUID: () => `uuid-${++uuidCounter}` });

function Wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

async function renderChat() {
  const { default: ChatPage } = await import("@/app/(app)/chat/page");
  return render(<ChatPage />, { wrapper: Wrapper });
}

beforeEach(() => {
  uuidCounter = 0;
  vi.clearAllMocks();
});

describe("Context-aware starters", () => {
  it("renders 4 entity-tailored questions when entity_id is present", async () => {
    const { useSearchParams } = await import("next/navigation");
    vi.mocked(useSearchParams).mockReturnValue(
      new URLSearchParams("entity_id=AAPL") as ReturnType<
        typeof import("next/navigation").useSearchParams
      >,
    );

    await renderChat();

    // Click new chat to land on the empty thread + starters
    fireEvent.click(screen.getByRole("button", { name: /start new chat/i }));

    // All 4 entity questions present (with the ticker baked in)
    await waitFor(() => {
      expect(
        screen.getByText("What's the latest news on AAPL?"),
      ).toBeInTheDocument();
    });
    expect(screen.getByText("Why did AAPL move today?")).toBeInTheDocument();
    expect(
      screen.getByText("What are the bull and bear cases for AAPL?"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("How does AAPL compare to its peers?"),
    ).toBeInTheDocument();
  });

  it("falls back to generic starters when no entity_id param", async () => {
    const { useSearchParams } = await import("next/navigation");
    vi.mocked(useSearchParams).mockReturnValue(
      new URLSearchParams() as ReturnType<
        typeof import("next/navigation").useSearchParams
      >,
    );

    await renderChat();

    fireEvent.click(screen.getByRole("button", { name: /start new chat/i }));

    // The generic starters are 6 items; one of them mentions "MSFT and GOOGL"
    await waitFor(() => {
      expect(
        screen.getByText(/Compare MSFT and GOOGL cloud revenue growth/i),
      ).toBeInTheDocument();
    });

    // The entity-specific phrasing should NOT be present.
    expect(
      screen.queryByText(/What's the latest news on/i),
    ).not.toBeInTheDocument();
  });
});
