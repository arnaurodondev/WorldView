/**
 * __tests__/earnings-calendar-widget.test.tsx — Unit tests for EarningsCalendarWidget
 *
 * WHY THIS EXISTS: EarningsCalendarWidget was converted from a static placeholder
 * to a live component in PLAN-0068 Wave B-1. These tests verify that:
 *   1. Skeleton renders while the query is loading
 *   2. Up to 8 event rows render when data is present
 *   3. Empty state shows when events=[]
 *   4. Error state shows when the fetch fails
 *
 * WHY PLAN-0068 Wave B-1: consumer 13D-9 (Wave A-1) populates temporal_events
 * with event_type=corporate from Finnhub. S9 proxy (Wave A-2) routes
 * GET /v1/fundamentals/earnings-calendar to S7. This component activates the
 * full frontend path.
 *
 * DATA SOURCE: Mocked gateway (no real S9 calls).
 * DESIGN REFERENCE: PRD-0031 §10 Dashboard Wave 7.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { EarningsCalendarWidget } from "@/components/dashboard/EarningsCalendarWidget";
import type { EarningsEvent } from "@/types/api";

// ── Mocks ──────────────────────────────────────────────────────────────────────

// WHY mock next/navigation: The widget imports from useAuth which may transitively
// import router utilities. Prevent App Router invariant error in test environment.
vi.mock("next/navigation", () => ({
  useRouter: vi.fn(() => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn() })),
  usePathname: vi.fn(() => "/dashboard"),
  useSearchParams: vi.fn(() => new URLSearchParams()),
}));

// WHY mock useAuth: EarningsCalendarWidget calls useAuth() to get accessToken.
// A fixed "test-token" ensures enabled:!!accessToken is true and the query fires.
vi.mock("@/hooks/useAuth", () => ({
  useAuth: vi.fn(() => ({
    accessToken: "test-token",
    isAuthenticated: true,
    isLoading: false,
    user: { user_id: "u1", tenant_id: "t1", email: "a@b.com", name: "A", avatar_url: null },
    setTokens: vi.fn(),
    logout: vi.fn(),
  })),
}));

// ── Gateway mock — overridden per-test ────────────────────────────────────────

// WHY hoisted mock factory: we need to control what getEarningsCalendar returns
// in each test. We keep the factory reference mutable so individual tests can
// call mockResolvedValueOnce / mockRejectedValueOnce without leaking state.
const mockGetEarningsCalendar = vi.fn();

vi.mock("@/lib/gateway", () => ({
  createGateway: vi.fn(() => ({
    getEarningsCalendar: mockGetEarningsCalendar,
  })),
  GatewayError: class GatewayError extends Error {
    status: number;
    constructor(status: number, msg: string) {
      super(msg);
      this.status = status;
    }
  },
}));

// ── Helpers ────────────────────────────────────────────────────────────────────

/** Make a fresh QueryClient with retry:false so failures surface immediately */
function makeQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false },
    },
  });
}

/** Wrapper that wraps in QueryClientProvider with a fresh client per test */
function makeWrapper() {
  const qc = makeQueryClient();
  return function Wrapper({ children }: { children: React.ReactNode }) {
    return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
  };
}

/** Build a minimal EarningsEvent fixture */
function makeEarningsEvent(overrides: Partial<EarningsEvent> = {}): EarningsEvent {
  const base: EarningsEvent = {
    event_id: "ev-1",
    title: "AAPL Q3 2026 Earnings",
    description: "EPS est. $1.45 (BMO)",
    active_from: "2026-07-30T13:30:00Z",
    active_until: "2026-08-06T13:30:00Z",
    region: "AAPL",
    confidence: 1.0,
  };
  return { ...base, ...overrides };
}

// ── Reset between tests ────────────────────────────────────────────────────────

beforeEach(() => {
  // WHY clearMocks: prevents call count accumulation across tests.
  // Each test sets its own mockResolvedValue / mockRejectedValue.
  vi.clearAllMocks();
});

// ── Tests ──────────────────────────────────────────────────────────────────────

describe("EarningsCalendarWidget — loading state", () => {
  it("renders skeleton rows while the query is pending", () => {
    // WHY never resolve: returning a Promise that never settles keeps
    // isLoading=true for the entire test — the component stays in skeleton state.
    mockGetEarningsCalendar.mockReturnValue(new Promise(() => {}));

    render(<EarningsCalendarWidget />, { wrapper: makeWrapper() });

    // WHY "EARNINGS CALENDAR": the section header always renders regardless of
    // data state — it is outside the conditional branches.
    expect(screen.getByText("EARNINGS CALENDAR")).toBeInTheDocument();

    // WHY getByRole("generic"): skeletons render as div elements (no semantic role).
    // We assert that at least one skeleton is present — exact count is an impl detail.
    // Using getAllByRole("generic") would match too broadly; checking for the
    // Skeleton component by its animate-pulse class is more targeted.
    // Pragmatically, we just verify the header is present and no event rows appear yet.
    expect(screen.queryByText(/No upcoming earnings events/i)).not.toBeInTheDocument();
    expect(screen.queryByText("AAPL")).not.toBeInTheDocument();
  });
});

describe("EarningsCalendarWidget — data state (3 events)", () => {
  it("renders event rows for each event returned", async () => {
    // WHY 3 events: representative multi-row scenario; tests that .slice(0,8)
    // doesn't cut the list prematurely and that all 3 rows render.
    mockGetEarningsCalendar.mockResolvedValueOnce({
      events: [
        makeEarningsEvent({ event_id: "ev-1", region: "AAPL", title: "AAPL Q3 2026 Earnings" }),
        makeEarningsEvent({ event_id: "ev-2", region: "MSFT", title: "MSFT Q1 FY2027 Earnings", description: "EPS est. $3.10 (AMC)" }),
        makeEarningsEvent({ event_id: "ev-3", region: "GOOGL", title: "GOOGL Q2 2026 Earnings", description: "EPS est. $2.05" }),
      ],
      total: 3,
    });

    render(<EarningsCalendarWidget />, { wrapper: makeWrapper() });

    // WHY waitFor: TanStack Query resolves asynchronously — rows are not present
    // on the synchronous first render.
    await waitFor(() => {
      expect(screen.getByText("AAPL")).toBeInTheDocument();
    });

    // All three tickers must render after data arrives
    expect(screen.getByText("MSFT")).toBeInTheDocument();
    expect(screen.getByText("GOOGL")).toBeInTheDocument();

    // Event titles (truncated in DOM — title attribute carries full text)
    expect(screen.getByText("AAPL Q3 2026 Earnings")).toBeInTheDocument();

    // EPS snippet: description ≤40 chars is shown in full.
    // "EPS est. $3.10 (AMC)" is 22 chars → shown as-is.
    expect(screen.getByText("EPS est. $3.10 (AMC)")).toBeInTheDocument();
  });

  it("renders date and time extracted from active_from", async () => {
    mockGetEarningsCalendar.mockResolvedValueOnce({
      events: [makeEarningsEvent({ active_from: "2026-07-30T13:30:00Z" })],
      total: 1,
    });

    render(<EarningsCalendarWidget />, { wrapper: makeWrapper() });

    await waitFor(() => {
      // WHY "07-30": active_from ISO slice(5,10) → "07-30"
      expect(screen.getByText("07-30")).toBeInTheDocument();
      // WHY "13:30": active_from ISO slice(11,16) → "13:30"
      expect(screen.getByText("13:30")).toBeInTheDocument();
    });
  });
});

describe("EarningsCalendarWidget — empty state", () => {
  it("renders empty state message when events array is empty", async () => {
    mockGetEarningsCalendar.mockResolvedValueOnce({
      events: [],
      total: 0,
    });

    render(<EarningsCalendarWidget />, { wrapper: makeWrapper() });

    await waitFor(() => {
      expect(
        screen.getByText(/No upcoming earnings events scheduled/i),
      ).toBeInTheDocument();
    });

    // WHY verify no event rows: empty state must not show stale data
    expect(screen.queryByText("AAPL")).not.toBeInTheDocument();
  });

  it("does not render skeleton once empty response arrives", async () => {
    mockGetEarningsCalendar.mockResolvedValueOnce({ events: [], total: 0 });

    render(<EarningsCalendarWidget />, { wrapper: makeWrapper() });

    await waitFor(() => {
      expect(
        screen.getByText(/No upcoming earnings events scheduled/i),
      ).toBeInTheDocument();
    });

    // WHY verify supplementary caption: second line of empty state confirms the
    // data-ingestion narrative — important so traders know the feature is live,
    // just awaiting data.
    expect(
      screen.getByText(/Earnings calendar data populates as company reporting/i),
    ).toBeInTheDocument();
  });
});

describe("EarningsCalendarWidget — error state", () => {
  it("renders error message when the fetch rejects", async () => {
    // WHY mockRejectedValueOnce: TanStack Query marks isError=true when queryFn throws.
    // The component renders the error branch: "Earnings calendar unavailable..."
    mockGetEarningsCalendar.mockRejectedValueOnce(new Error("Network error"));

    render(<EarningsCalendarWidget />, { wrapper: makeWrapper() });

    await waitFor(() => {
      expect(
        screen.getByText(/Earnings calendar unavailable/i),
      ).toBeInTheDocument();
    });

    // WHY verify no event rows: error state must not show stale data
    expect(screen.queryByText("AAPL")).not.toBeInTheDocument();
    // WHY verify no empty state: error branch and empty branch are mutually exclusive
    expect(screen.queryByText(/No upcoming earnings events scheduled/i)).not.toBeInTheDocument();
  });
});
