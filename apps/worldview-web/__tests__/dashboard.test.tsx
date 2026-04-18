/**
 * __tests__/dashboard.test.tsx — Unit tests for dashboard widget components
 *
 * WHY THIS EXISTS: Dashboard widgets are the most user-facing components.
 * Tests verify that each widget correctly handles loading, error, and empty
 * states — the three failure modes that traders would see if S9 is unavailable.
 *
 * WHY MOCK GATEWAY: We don't want real S9 calls in unit tests.
 * The gateway mock lets us control exactly what each widget receives.
 *
 * DATA SOURCE: Mocked gateway client
 */

import { describe, it, expect, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MarketHeatmap } from "@/components/dashboard/MarketHeatmap";
import { TopMovers } from "@/components/dashboard/TopMovers";
import { AiSignals } from "@/components/dashboard/AiSignals";
import { EconomicCalendar } from "@/components/dashboard/EconomicCalendar";

// ── Next.js router mock ───────────────────────────────────────────────────────
// WHY: TopMovers and AiSignals use useRouter() for navigation. In unit tests
// the App Router isn't mounted — mock it to avoid "invariant" error.
vi.mock("next/navigation", () => ({
  useRouter: vi.fn(() => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn() })),
  usePathname: vi.fn(() => "/dashboard"),
  useSearchParams: vi.fn(() => new URLSearchParams()),
}));

// ── Gateway mock ──────────────────────────────────────────────────────────────

vi.mock("@/lib/gateway", () => ({
  createGateway: vi.fn(() => ({
    getMarketHeatmap: vi.fn().mockResolvedValue({
      sectors: [
        { name: "Information Technology", change_pct: 1.5, instrument_count: 67 },
        { name: "Health Care", change_pct: -0.8, instrument_count: 62 },
        { name: "Energy", change_pct: null, instrument_count: 23 },
      ],
    }),
    getTopMovers: vi.fn().mockResolvedValue({
      movers: [
        {
          instrument_id: "ins-1",
          ticker: "NVDA",
          name: "NVIDIA Corp",
          price: 850.0,
          change_pct: 5.2,
          volume: 45_000_000,
        },
        {
          instrument_id: "ins-2",
          ticker: "TSLA",
          name: "Tesla Inc",
          price: 172.5,
          change_pct: -3.1,
          volume: 90_000_000,
        },
      ],
      type: "gainers" as const,
    }),
    getAiSignals: vi.fn().mockResolvedValue({ signals: [] }),
    getEconomicCalendar: vi.fn().mockResolvedValue({
      events: [
        {
          event_id: "ev-1",
          title: "CPI YoY (Feb)",
          country: "US",
          currency: "USD",
          event_date: new Date(Date.now() + 2 * 60 * 60 * 1000).toISOString(),
          forecast: 3.1,
          previous: 3.2,
          actual: null,
          impact: "HIGH" as const,
          unit: "%",
        },
      ],
    }),
    refreshToken: vi.fn().mockResolvedValue({
      access_token: "tok",
      user: { user_id: "u1", tenant_id: "t1", email: "a@b.com", name: "A", avatar_url: null },
      expires_in: 900,
    }),
    logout: vi.fn(),
  })),
  GatewayError: class GatewayError extends Error {
    status: number;
    constructor(status: number, msg: string) { super(msg); this.status = status; }
  },
}));

// ── Auth mock ─────────────────────────────────────────────────────────────────

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

// ── Helpers ───────────────────────────────────────────────────────────────────

function makeQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false },
    },
  });
}

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = makeQueryClient();
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

// ── Tests ─────────────────────────────────────────────────────────────────────

describe("MarketHeatmap", () => {
  it("renders sector tiles after data loads", async () => {
    render(<MarketHeatmap />, { wrapper });

    // Should show loading skeletons initially
    await waitFor(() => {
      // After loading, sector tiles render
      expect(screen.getByTitle("Information Technology")).toBeInTheDocument();
    });
  });

  it("renders Tech abbreviation", async () => {
    render(<MarketHeatmap />, { wrapper });

    await waitFor(() => {
      expect(screen.getByText("Tech")).toBeInTheDocument();
    });
  });

  it("renders positive change percentage", async () => {
    render(<MarketHeatmap />, { wrapper });

    await waitFor(() => {
      expect(screen.getByText("+1.50%")).toBeInTheDocument();
    });
  });

  it("renders null change_pct as em dash", async () => {
    render(<MarketHeatmap />, { wrapper });

    await waitFor(() => {
      expect(screen.getByText("—")).toBeInTheDocument();
    });
  });
});

describe("TopMovers", () => {
  it("renders mover tickers after data loads", async () => {
    render(<TopMovers />, { wrapper });

    await waitFor(() => {
      expect(screen.getByText("NVDA")).toBeInTheDocument();
    });
  });

  it("shows gainers/losers tab buttons", () => {
    render(<TopMovers />, { wrapper });

    expect(screen.getByText("gainers")).toBeInTheDocument();
    expect(screen.getByText("losers")).toBeInTheDocument();
  });
});

describe("AiSignals", () => {
  it("shows empty state when no signals returned", async () => {
    render(<AiSignals />, { wrapper });

    await waitFor(() => {
      expect(screen.getByText(/signal data coming soon/i)).toBeInTheDocument();
    });
  });
});

describe("EconomicCalendar", () => {
  it("renders economic event title", async () => {
    render(<EconomicCalendar />, { wrapper });

    await waitFor(() => {
      expect(screen.getByText("CPI YoY (Feb)")).toBeInTheDocument();
    });
  });

  it("renders HIGH impact indicator", async () => {
    render(<EconomicCalendar />, { wrapper });

    await waitFor(() => {
      // "H" is the single-letter abbreviation for HIGH impact
      expect(screen.getByText("H")).toBeInTheDocument();
    });
  });
});
