/**
 * components/instrument/__tests__/InstrumentPageClient.states.test.tsx
 *
 * WHY THIS EXISTS (Round-4 hardening, items 1a + 1c): before this round the
 * page shell DISCARDED the bundle query's error channel — a bogus ticker
 * (404) or an S9 outage (5xx) left the analyst on a permanent "—" header
 * with empty tabs (the children's `enabled` guards never fired because
 * instrumentId stayed empty). These tests pin the two new contracts:
 *
 *   1. 404 GatewayError → the named <InstrumentNotFound> surface renders,
 *      with the attempted ticker and the screener escape hatch (the F2
 *      step-10 primitive that existed but was never wired).
 *   2. Any other error → a named page-level error with a Retry button that
 *      refires the bundle query.
 *   3. Happy path regression guard: with a resolved bundle neither error
 *      surface renders (the tabs strip does).
 *
 * MOCK STRATEGY: the bundle hook is mocked at its seam (the component's only
 * data dependency); the four heavy children (header/banner/tabs/tab bodies)
 * are stubbed so the test doesn't drag in lightweight-charts / sigma.js.
 * GatewayError is the REAL class from lib/gateway so the instanceof check in
 * the component is exercised for real.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

// ── Mocks (must precede component import) ────────────────────────────────────

vi.mock("next/navigation", () => ({
  useRouter: vi.fn(() => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn() })),
  usePathname: vi.fn(() => "/instruments/ZZZZ"),
  useSearchParams: vi.fn(() => new URLSearchParams()),
}));

// Bundle hook seam — each test sets the state it needs.
const mockBundleHook = vi.hoisted(() => ({
  state: {
    data: undefined as unknown,
    isError: false,
    error: null as unknown,
    refetch: vi.fn(),
  },
}));
vi.mock("@/components/instrument/hooks/useInstrumentBundle", () => ({
  useInstrumentBundle: vi.fn(() => mockBundleHook.state),
}));

// Heavy children stubbed: this suite tests the SHELL's branching, not them.
vi.mock("@/components/instrument/header/InstrumentHeader", () => ({
  InstrumentHeader: () => <div data-testid="stub-header" />,
}));
vi.mock("@/components/instrument/brief/AiBriefBanner", () => ({
  AiBriefBanner: () => null,
}));
vi.mock("@/components/instrument/tabs/InstrumentTabs", () => ({
  InstrumentTabs: () => <div data-testid="stub-tabs" />,
}));
vi.mock("@/components/instrument/quote/QuoteTab", () => ({
  QuoteTab: () => <div data-testid="stub-quote-tab" />,
}));
vi.mock("@/components/instrument/financials/FinancialsTab", () => ({
  FinancialsTab: () => null,
}));
vi.mock("@/components/instrument/intelligence/IntelligenceTab", () => ({
  IntelligenceTab: () => null,
}));

// IMPORTANT: imports AFTER mocks. GatewayError stays REAL (instanceof check).
// eslint-disable-next-line import/first
import { GatewayError } from "@/lib/gateway";
// eslint-disable-next-line import/first
import { InstrumentPageClient } from "@/components/instrument/InstrumentPageClient";

// ── Helpers ──────────────────────────────────────────────────────────────────

function Wrapper({ children }: { children: ReactNode }) {
  // The shell calls useQueryClient for cache priming — a real provider is
  // simpler (and more faithful) than mocking @tanstack/react-query.
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

beforeEach(() => {
  mockBundleHook.state = {
    data: undefined,
    isError: false,
    error: null,
    refetch: vi.fn(),
  };
});

// ── Tests ────────────────────────────────────────────────────────────────────

describe("InstrumentPageClient error recovery (Round-4 items 1a/1c)", () => {
  it("renders the named InstrumentNotFound surface on a 404 bundle error", () => {
    mockBundleHook.state.isError = true;
    mockBundleHook.state.error = new GatewayError(404, "Instrument not found: ZZZZ");

    render(<InstrumentPageClient entityId="ZZZZ" />, { wrapper: Wrapper });

    // The F2-step-10 primitive: badge + attempted ticker + screener CTA.
    expect(screen.getByTestId("instrument-not-found")).toBeInTheDocument();
    expect(screen.getByText("ZZZZ")).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: /browse all instruments/i }),
    ).toHaveAttribute("href", "/screener");
    // No dead chrome around the 404 — the tabs strip must NOT render.
    expect(screen.queryByTestId("stub-tabs")).toBeNull();
  });

  it("renders a named page error with a working Retry on a non-404 failure", () => {
    const refetch = vi.fn();
    mockBundleHook.state.isError = true;
    mockBundleHook.state.error = new GatewayError(503, "gateway unavailable");
    mockBundleHook.state.refetch = refetch;

    render(<InstrumentPageClient entityId="AAPL" />, { wrapper: Wrapper });

    expect(screen.getByTestId("instrument-page-error")).toBeInTheDocument();
    // 5xx is transient — it must NOT claim the ticker doesn't exist.
    expect(screen.queryByTestId("instrument-not-found")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /retry/i }));
    expect(refetch).toHaveBeenCalled();
  });

  it("renders a page error (not a white page) for non-GatewayError failures", () => {
    // e.g. a TypeError thrown inside fetch plumbing — must still surface.
    mockBundleHook.state.isError = true;
    mockBundleHook.state.error = new TypeError("Failed to fetch");

    render(<InstrumentPageClient entityId="AAPL" />, { wrapper: Wrapper });

    expect(screen.getByTestId("instrument-page-error")).toBeInTheDocument();
  });

  it("renders the normal shell (no error surfaces) when the bundle resolves", () => {
    mockBundleHook.state.data = {
      instrument_id: "ins-001",
      overview: null,
      top_news: null,
    };

    render(<InstrumentPageClient entityId="AAPL" />, { wrapper: Wrapper });

    expect(screen.getByTestId("stub-tabs")).toBeInTheDocument();
    expect(screen.getByTestId("stub-quote-tab")).toBeInTheDocument();
    expect(screen.queryByTestId("instrument-not-found")).toBeNull();
    expect(screen.queryByTestId("instrument-page-error")).toBeNull();
  });
});
