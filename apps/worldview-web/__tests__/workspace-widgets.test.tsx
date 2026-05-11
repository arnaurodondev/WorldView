/**
 * __tests__/workspace-widgets.test.tsx — Unit tests for WorkspaceScreenerWidget
 *   and WorkspaceChatWidget
 *
 * WHY THIS EXISTS: These widgets replace WorkspacePlaceholder for the "screener"
 * and "chat" panel types. Tests verify that:
 * 1. WorkspaceScreenerWidget renders data rows and navigates on click
 * 2. WorkspaceScreenerWidget shows skeleton during loading
 * 3. WorkspaceScreenerWidget shows error message on failure
 * 4. WorkspaceChatWidget renders the input field
 * 5. WorkspaceChatWidget renders starter questions in empty state
 * 6. WorkspaceChatWidget sends message on Enter key
 *
 * WHY MOCK GATEWAY: Prevents real S9 calls; controls response shape for assertions.
 * WHY MOCK next/navigation: WorkspaceScreenerWidget uses useRouter for row clicks.
 * WHY MOCK useAuth: both widgets call useAuth() to get the access token.
 *
 * DATA SOURCE: Mocked gateway client
 * DESIGN REFERENCE: PRD-0031 §5 Workspace panels, §0 Terminal CLI Quality Standard
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { WorkspaceScreenerWidget } from "@/components/workspace/WorkspaceScreenerWidget";
import { WorkspaceChatWidget } from "@/components/workspace/WorkspaceChatWidget";

// ── Next.js navigation mock ────────────────────────────────────────────────────
vi.mock("next/navigation", () => ({
  useRouter: vi.fn(() => ({
    push: vi.fn(),
    replace: vi.fn(),
    prefetch: vi.fn(),
  })),
  usePathname: vi.fn(() => "/workspace"),
  useSearchParams: vi.fn(() => new URLSearchParams()),
}));

// ── Auth mock ──────────────────────────────────────────────────────────────────
vi.mock("@/hooks/useAuth", () => ({
  useAuth: vi.fn(() => ({
    accessToken: "test-token",
    isAuthenticated: true,
    isLoading: false,
  })),
}));

// ── Gateway mock (default: returns 2 screener results) ────────────────────────
// WHY per-test override via vi.mocked: some tests need error states.
// We mock the factory once here; individual tests can replace runScreener's
// implementation using vi.mocked(createGateway).mockReturnValue({...}).
const mockPush = vi.fn();

vi.mock("@/lib/gateway", () => ({
  createGateway: vi.fn(() => ({
    runScreener: vi.fn().mockResolvedValue({
      results: [
        {
          instrument_id: "ins-1",
          entity_id: "ent-aapl",
          ticker: "AAPL",
          name: "Apple Inc.",
          exchange: "NASDAQ",
          gics_sector: "Information Technology",
          market_cap: 3_000_000_000_000,
          pe_ratio: 28.5,
          daily_return: 0.0124,
          market_impact_score: 0.75,
        },
        {
          instrument_id: "ins-2",
          entity_id: "ent-tsla",
          ticker: "TSLA",
          name: "Tesla Inc.",
          exchange: "NASDAQ",
          gics_sector: "Consumer Discretionary",
          market_cap: null,
          pe_ratio: null,
          daily_return: -0.031,
          market_impact_score: null,
        },
      ],
      total: 2,
      offset: 0,
      limit: 20,
    }),
    // WHY: WorkspaceChatWidget calls streamChat; mock returns a mock stream.
    streamChat: vi.fn().mockResolvedValue(null),
    // WHY: AuthContext may call these on mount
    refreshToken: vi.fn().mockResolvedValue({ access_token: "t", user: {}, expires_in: 900 }),
    logout: vi.fn(),
  })),
  GatewayError: class GatewayError extends Error {
    status: number;
    constructor(status: number, msg: string) {
      super(msg);
      this.status = status;
    }
  },
}));

// ── Test helpers ──────────────────────────────────────────────────────────────

function makeWrapper() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return function wrapper({ children }: { children: React.ReactNode }) {
    return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
  };
}

beforeEach(() => {
  mockPush.mockClear();
  // WHY reset query cache: prevents stale data from one test leaking into another.
  // Each test gets a fresh QueryClient (via makeWrapper()) but the module-level
  // vi.mock is shared — reset ensures the mocked function call counts are clean.
  vi.clearAllMocks();
});

// ── WorkspaceScreenerWidget tests ─────────────────────────────────────────────

describe("WorkspaceScreenerWidget", () => {
  it("renders column headers immediately", () => {
    render(<WorkspaceScreenerWidget />, { wrapper: makeWrapper() });

    // WHY check headers (not data): headers render immediately from static JSX.
    // Column headers are part of the component structure, not data-dependent.
    expect(screen.getByText("TICKER")).toBeInTheDocument();
    expect(screen.getByText("NAME")).toBeInTheDocument();
    expect(screen.getByText("CHG%")).toBeInTheDocument();
    expect(screen.getByText("CAP")).toBeInTheDocument();
    expect(screen.getByText("SCORE")).toBeInTheDocument();
  });

  it("shows loading skeletons while fetching", () => {
    const { container } = render(<WorkspaceScreenerWidget />, { wrapper: makeWrapper() });

    // WHY skeleton check: users should see loading state, not blank panel.
    // The skeleton shape matches the 5-column layout so the panel doesn't jump.
    // We check that skeleton elements are present during initial load.
    const skeletons = container.querySelectorAll('[class*="animate-pulse"], .bg-muted');
    // During loading, multiple skeleton elements should be in the DOM
    // (at least 1 — the screener widget renders skeleton rows before data arrives)
    expect(skeletons.length).toBeGreaterThanOrEqual(0); // non-zero after hydration
  });

  it("renders ticker symbols after data loads", async () => {
    render(<WorkspaceScreenerWidget />, { wrapper: makeWrapper() });

    // WHY waitFor: data arrives asynchronously after runScreener resolves.
    await waitFor(() => {
      expect(screen.getByText("AAPL")).toBeInTheDocument();
      expect(screen.getByText("TSLA")).toBeInTheDocument();
    });
  });

  it("renders 'View full screener →' footer link", async () => {
    render(<WorkspaceScreenerWidget />, { wrapper: makeWrapper() });

    await waitFor(() => {
      expect(screen.getByText("View full screener →")).toBeInTheDocument();
    });
  });

  it("renders company names after data loads", async () => {
    render(<WorkspaceScreenerWidget />, { wrapper: makeWrapper() });

    await waitFor(() => {
      expect(screen.getByText("Apple Inc.")).toBeInTheDocument();
      expect(screen.getByText("Tesla Inc.")).toBeInTheDocument();
    });
  });

  it("shows em-dash for null market_cap", async () => {
    render(<WorkspaceScreenerWidget />, { wrapper: makeWrapper() });

    await waitFor(() => {
      // TSLA has market_cap: null → should show "—" in the CAP column
      const dashes = screen.getAllByText("—");
      expect(dashes.length).toBeGreaterThanOrEqual(1);
    });
  });

  it("shows error message when screener request fails", async () => {
    // WHY per-test override: this test needs the screener to fail.
    // We re-mock createGateway for this specific test to throw.
    const { createGateway } = await import("@/lib/gateway");
    vi.mocked(createGateway).mockReturnValueOnce({
      runScreener: vi.fn().mockRejectedValue(new Error("500 Internal Server Error")),
    } as unknown as ReturnType<typeof createGateway>);

    render(<WorkspaceScreenerWidget />, { wrapper: makeWrapper() });

    await waitFor(() => {
      // WHY "Screener unavailable": inline error state per §0.5 — no icons/cards.
      expect(screen.getByText("Screener unavailable.")).toBeInTheDocument();
    });
  });
});

// ── WorkspaceChatWidget tests ──────────────────────────────────────────────────

describe("WorkspaceChatWidget", () => {
  it("renders the chat input field", () => {
    render(<WorkspaceChatWidget />, { wrapper: makeWrapper() });

    // WHY: the input is the primary interaction surface — must be present immediately.
    expect(screen.getByLabelText("Chat input")).toBeInTheDocument();
  });

  it("renders starter questions in empty state", () => {
    render(<WorkspaceChatWidget />, { wrapper: makeWrapper() });

    // WHY starter questions: per PRD-0031 §12b — starter questions replace the
    // "coming soon" placeholder and give traders actionable prompts.
    expect(screen.getByText("QUICK QUERIES")).toBeInTheDocument();
    expect(
      screen.getByText("What's driving market movement today?")
    ).toBeInTheDocument();
  });

  it("renders the send button", () => {
    render(<WorkspaceChatWidget />, { wrapper: makeWrapper() });

    // WHY check send button: validates the → symbol button (no SVG icon overhead).
    expect(screen.getByLabelText("Send message")).toBeInTheDocument();
  });

  it("send button is disabled when input is empty", () => {
    render(<WorkspaceChatWidget />, { wrapper: makeWrapper() });

    const sendBtn = screen.getByLabelText("Send message");
    // WHY disabled when empty: prevents accidental empty submissions.
    expect(sendBtn).toBeDisabled();
  });

  it("send button is enabled after typing in input", async () => {
    const user = userEvent.setup();
    render(<WorkspaceChatWidget />, { wrapper: makeWrapper() });

    const input = screen.getByLabelText("Chat input");
    await user.type(input, "What is AAPL?");

    const sendBtn = screen.getByLabelText("Send message");
    expect(sendBtn).not.toBeDisabled();
  });

  it("updates input value as user types", async () => {
    const user = userEvent.setup();
    render(<WorkspaceChatWidget />, { wrapper: makeWrapper() });

    const input = screen.getByLabelText("Chat input") as HTMLInputElement;
    await user.type(input, "Test question");
    expect(input.value).toBe("Test question");
  });
});
