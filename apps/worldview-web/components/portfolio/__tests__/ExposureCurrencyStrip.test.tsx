/**
 * components/portfolio/__tests__/ExposureCurrencyStrip.test.tsx
 * PLAN-0108 W3-T302 — ExposureCurrencyStrip 5-cell audit
 *
 * WHY THIS TEST EXISTS: PRD-0108 W3 requires the strip to render exactly 5
 * cells: INV %, CASH $, LEV ×, β-ADJ, CCY top-2. This suite verifies all
 * 5 are present in the rendered output given a realistic mock exposure response.
 *
 * STRATEGY: mock useExposure (the TanStack Query hook) so the component
 * renders without a real QueryClientProvider or gateway. This is faster and
 * more isolated than the full integration pattern — the hook is tested
 * separately via useExposure.test.ts (not yet written). We assert on visible
 * text labels because that is what a user (and screen-reader) observes.
 *
 * MOCK APPROACH:
 *   - useExposure → mocked to return a fixed ExposureResponse
 *   - @/hooks/useAuth → mocked to satisfy internal useExposure call
 *   - @/lib/gateway → mocked to avoid real HTTP
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import type { ExposureResponse } from "@/types/api";

// ── Mock useExposure directly ────────────────────────────────────────────────
// WHY mock the hook (not createGateway): ExposureCurrencyStrip only consumes
// the hook's { data, isLoading } shape. Mocking at the hook boundary avoids
// needing a full QueryClientProvider + network stub in this unit test.
vi.mock("@/hooks/useExposure", () => ({
  useExposure: vi.fn(),
}));

// WHY also mock useAuth: useExposure normally calls useAuth() internally, but
// since we're mocking useExposure entirely the auth mock is defensive — it
// prevents "useAuth must be used within AuthProvider" errors if the mock
// implementation leaks.
vi.mock("@/hooks/useAuth", () => ({
  useAuth: vi.fn(() => ({
    accessToken: "test-token",
    isAuthenticated: true,
    isLoading: false,
    user: { user_id: "u1", tenant_id: "t1", email: "t@test.com", name: "T", avatar_url: null },
    setTokens: vi.fn(),
    logout: vi.fn(),
  })),
}));

// WHY mock gateway: belt-and-suspenders against any import-time side effects.
vi.mock("@/lib/gateway", () => ({
  createGateway: vi.fn(() => ({ getExposure: vi.fn() })),
}));

// ── SUT import (after vi.mock hoisting) ────────────────────────────────────
import { ExposureCurrencyStrip, type CurrencyChip } from "../ExposureCurrencyStrip";
import { useExposure } from "@/hooks/useExposure";

// ── Fixtures ─────────────────────────────────────────────────────────────────

/**
 * Minimal ExposureResponse fixture with round numbers for easy label matching.
 *
 * WHY these values:
 *  - net_exposure_pct: 0.85  → formatPercent → "85.00%" (INV %)
 *  - cash: 15000             → formatPrice   → "$15,000.00" (CASH $)
 *  - leverage: 1.05          → toFixed(2)    → "1.05×" (LEV ×)
 */
const MOCK_EXPOSURE: ExposureResponse = {
  invested: 85000,
  cash: 15000,
  gross_exposure_pct: 0.85,
  net_exposure_pct: 0.85,
  leverage: 1.05,
  prices_stale: false,
  prices_as_of: null,
};

/**
 * Top-2 currency chips (USD dominant, EUR secondary).
 * WHY two entries: the spec requires "top-2 CCY" to be visible inline.
 */
const MOCK_CURRENCIES: CurrencyChip[] = [
  { code: "USD", pct: 0.78 },
  { code: "EUR", pct: 0.14 },
];

// ── Test helpers ──────────────────────────────────────────────────────────────

/**
 * Convenience cast — useExposure is mocked with vi.fn(); TypeScript doesn't
 * know its signature was replaced. The cast silences the "no .mockReturnValue"
 * error without loosening safety elsewhere.
 */
const mockUseExposure = useExposure as ReturnType<typeof vi.fn>;

// ── Suite ─────────────────────────────────────────────────────────────────────

describe("ExposureCurrencyStrip", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders all 5 cells: INV %, CASH $, LEV ×, β-ADJ, CCY", () => {
    // WHY: this is the primary spec-compliance test (PRD-0108 W3-T302).
    // All 5 labels must be visible simultaneously with real exposure data.
    mockUseExposure.mockReturnValue({ data: MOCK_EXPOSURE, isLoading: false });

    render(
      <ExposureCurrencyStrip
        portfolioId="p-001"
        betaAdjExposure={0.72}
        currencies={MOCK_CURRENCIES}
      />,
    );

    // Cell 1: INV % — strip should show the "INV" label
    expect(screen.getByText(/\bINV\b/)).toBeInTheDocument();

    // Cell 2: CASH $ — strip should show the "CASH" label
    expect(screen.getByText(/\bCASH\b/)).toBeInTheDocument();

    // Cell 3: LEV × — strip should show the "LEV" label with × suffix
    expect(screen.getByText(/\bLEV\b.*×/)).toBeInTheDocument();

    // Cell 4: β-ADJ — target the testid wrapper to avoid Unicode encoding issues
    // in regex matchers. The cell renders "β-ADJ <formatted pct>".
    const betaCell = screen.getByTestId("cell-beta-adj");
    expect(betaCell).toBeInTheDocument();
    // The formatted value "72.00%" should appear inside the cell.
    expect(betaCell.textContent).toMatch(/72/);

    // Cell 5: CCY — label + both currency codes should appear
    expect(screen.getByText("CCY")).toBeInTheDocument();
    expect(screen.getByText("USD")).toBeInTheDocument();
    expect(screen.getByText("EUR")).toBeInTheDocument();
  });

  it("renders β-ADJ cell with '—' when betaAdjExposure is not provided", () => {
    // WHY: when the parent has not computed beta-adjusted exposure we must
    // render "—" rather than silently substituting net_exposure_pct.
    // This guards against the silent-substitution failure pattern (MEMORY.md).
    mockUseExposure.mockReturnValue({ data: MOCK_EXPOSURE, isLoading: false });

    render(<ExposureCurrencyStrip portfolioId="p-001" />);

    const betaCell = screen.getByTestId("cell-beta-adj");
    expect(betaCell.textContent).toMatch(/—/);
  });

  it("renders '—' placeholder while loading", () => {
    // WHY: during initial fetch the strip should not flash partial data.
    // A single "—" replaces all cells to avoid layout shift.
    mockUseExposure.mockReturnValue({ data: undefined, isLoading: true });

    render(<ExposureCurrencyStrip portfolioId="p-001" />);

    // The loading "—" should appear; no INV/CASH/LEV labels yet.
    expect(screen.getByText("—")).toBeInTheDocument();
    expect(screen.queryByText(/\bINV\b/)).toBeNull();
  });

  it("renders nothing when portfolioId is null", () => {
    // WHY: null portfolioId means no portfolio is selected yet (e.g. first
    // load before the portfolio list resolves). The strip should not render
    // at all to avoid a blank 22px bar in the layout.
    mockUseExposure.mockReturnValue({ data: undefined, isLoading: false });

    const { container } = render(<ExposureCurrencyStrip portfolioId={null} />);
    expect(container.firstChild).toBeNull();
  });

  it("hides CCY section when currencies prop is omitted", () => {
    // WHY: the CCY section is optional — the parent may not have currency
    // data yet. The "CCY" label must not appear as an orphaned header.
    mockUseExposure.mockReturnValue({ data: MOCK_EXPOSURE, isLoading: false });

    render(<ExposureCurrencyStrip portfolioId="p-001" betaAdjExposure={0.85} />);

    expect(screen.queryByText("CCY")).toBeNull();
  });
});
