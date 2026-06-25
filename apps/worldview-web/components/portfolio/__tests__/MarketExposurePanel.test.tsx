/**
 * components/portfolio/__tests__/MarketExposurePanel.test.tsx
 * (2026-06-10 sprint, Wave 2 — overview band panel #1.)
 *
 * WHY: the panel replaces the one-line ExposureCurrencyStrip. These tests
 * pin the four states (data / loading skeleton / named error + retry /
 * β-adj null path) and the buying-power fallback semantics.
 *
 * MOCKED: useExposure at the hook boundary (same pattern as
 * holdings-tab.test.tsx) — the underlying query is covered by the shared
 * hook's own behaviour and the gateway transform tests.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";

// ── useExposure mock ──────────────────────────────────────────────────────────
const mockUseExposure = vi.fn();
vi.mock("@/hooks/useAuth", () => ({
  useAuth: vi.fn(() => ({ accessToken: "test-token" })),
}));
vi.mock("@/hooks/useExposure", () => ({
  useExposure: (...args: unknown[]) => mockUseExposure(...args),
}));

import { MarketExposurePanel } from "../MarketExposurePanel";

// ── Fixtures ──────────────────────────────────────────────────────────────────

const EXPOSURE = {
  invested: 73_302.53,
  cash: 1_500,
  gross_exposure_pct: 1.0,
  net_exposure_pct: 1.0,
  leverage: 1.3,
  prices_stale: false,
  prices_as_of: null,
  // number | null: the older-build fallback test below overrides this to null.
  buying_power: 1_500 as number | null,
};

function mockState(state: Partial<{
  data: typeof EXPOSURE | undefined;
  isLoading: boolean;
  isError: boolean;
}>) {
  mockUseExposure.mockReturnValue({
    data: undefined,
    isLoading: false,
    isError: false,
    refetch: vi.fn(),
    ...state,
  });
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("MarketExposurePanel", () => {
  it("renders every exposure figure from the endpoint data", () => {
    mockState({ data: EXPOSURE });
    render(<MarketExposurePanel portfolioId="p-1" betaAdjExposure={0.97} />);

    expect(screen.getByText("Market Exposure")).toBeInTheDocument();
    // Dollar column.
    expect(screen.getByText("Invested")).toBeInTheDocument();
    expect(screen.getByText("$73,302.53")).toBeInTheDocument();
    // CASH and BUYING PWR both show $1,500 (v1: equal by definition).
    expect(screen.getAllByText("$1,500.00").length).toBeGreaterThanOrEqual(2);
    // Ratio column.
    expect(screen.getByText("Leverage")).toBeInTheDocument();
    expect(screen.getByText("1.30×")).toBeInTheDocument();
    // β-adj from the parent-computed prop (fraction → percent).
    expect(screen.getByText("+97.00%")).toBeInTheDocument();
  });

  it("β-adj renders an em-dash (never substitutes net exposure) when null", () => {
    mockState({ data: EXPOSURE });
    render(<MarketExposurePanel portfolioId="p-1" betaAdjExposure={null} />);
    expect(screen.getByText("β-adj")).toBeInTheDocument();
    expect(screen.getByText("—")).toBeInTheDocument();
  });

  it("falls back to cash for buying power when the server omits the field", () => {
    mockState({ data: { ...EXPOSURE, buying_power: null } });
    render(<MarketExposurePanel portfolioId="p-1" />);
    // BUYING PWR shows the cash figure — the v1-identical fallback.
    expect(screen.getAllByText("$1,500.00").length).toBeGreaterThanOrEqual(2);
  });

  it("shows a shape-matched skeleton while loading (DS §6.2)", () => {
    mockState({ isLoading: true });
    render(<MarketExposurePanel portfolioId="p-1" />);
    expect(screen.getByTestId("market-exposure-skeleton")).toBeInTheDocument();
  });

  it("named error state offers an in-place retry wired to refetch", () => {
    const refetch = vi.fn();
    mockUseExposure.mockReturnValue({
      data: undefined,
      isLoading: false,
      isError: true,
      refetch,
    });
    render(<MarketExposurePanel portfolioId="p-1" />);

    expect(screen.getByTestId("market-exposure-error")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /retry loading exposure/i }));
    expect(refetch).toHaveBeenCalledTimes(1);
  });

  it("renders nothing without a portfolio id (no fabricated panel)", () => {
    mockState({ data: EXPOSURE });
    const { container } = render(<MarketExposurePanel portfolioId={null} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("surfaces the stale-prices caveat in the header when flagged", () => {
    mockState({ data: { ...EXPOSURE, prices_stale: true } });
    render(<MarketExposurePanel portfolioId="p-1" />);
    expect(screen.getByText("stale prices")).toBeInTheDocument();
  });
});
