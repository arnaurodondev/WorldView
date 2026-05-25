/**
 * components/portfolio/__tests__/ConcentrationWidget.test.tsx
 *
 * WHY THIS EXISTS: ConcentrationWidget renders differently based on the
 * `label` field from the API ("diversified" / "moderate" / "concentrated" /
 * "empty"). Each label maps to a different colour class. These tests pin those
 * contracts so a refactor of the colour mapping doesn't silently drop the
 * severity colouring.
 *
 * MOCKED MODULES:
 *  - @/hooks/useAuth  → stub token.
 *  - @/lib/gateway    → stub getConcentration so we control responses per-test.
 *
 * DATA SOURCE: mocked ConcentrationResponse
 * DESIGN REFERENCE: PLAN-0091 Wave B-1 §Concentration widget
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

// ── Auth stub ────────────────────────────────────────────────────────────────

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

// ── Gateway stub ─────────────────────────────────────────────────────────────

const mockGetConcentration = vi.fn();

vi.mock("@/lib/gateway", () => ({
  createGateway: vi.fn(() => ({
    getConcentration: mockGetConcentration,
  })),
}));

// ── SUT import ───────────────────────────────────────────────────────────────

import { ConcentrationWidget } from "../ConcentrationWidget";

// ── Helpers ──────────────────────────────────────────────────────────────────

function wrap(children: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

// Baseline ConcentrationResponse — a diversified portfolio.
const BASE_CONCENTRATION = {
  portfolio_id: "p1",
  hhi: 850,
  label: "diversified" as const,
  top_3_share_pct: 35.4,
  positions_count: 12,
  top_positions: [
    { instrument_id: "i1", weight_pct: 14.2 },
    { instrument_id: "i2", weight_pct: 11.1 },
    { instrument_id: "i3", weight_pct: 10.1 },
  ],
  prices_stale: false,
};

// ── Tests ────────────────────────────────────────────────────────────────────

describe("ConcentrationWidget", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders loading state while query is pending", () => {
    // Keep query in pending state for the entire test.
    mockGetConcentration.mockReturnValue(new Promise(() => {}));

    render(wrap(<ConcentrationWidget portfolioId="p1" />));

    expect(screen.getByTestId("concentration-widget")).toBeInTheDocument();

    // WHY data-testid: Tailwind classes are not computed in jsdom.
    // The skeleton container has data-testid="concentration-skeleton".
    expect(screen.getByTestId("concentration-skeleton")).toBeInTheDocument();
  });

  it("renders 'diversified' label with muted colour class", async () => {
    mockGetConcentration.mockResolvedValue({
      ...BASE_CONCENTRATION,
      label: "diversified",
    });

    render(wrap(<ConcentrationWidget portfolioId="p1" />));

    await waitFor(() => {
      expect(screen.getByTestId("hhi-label")).toBeInTheDocument();
    });

    const labelEl = screen.getByTestId("hhi-label");
    expect(labelEl.textContent?.toLowerCase()).toContain("diversified");
    // WHY check class directly: the colour contract is load-bearing —
    // "diversified" MUST use text-muted-foreground (not green/amber/red).
    expect(labelEl.className).toContain("text-muted-foreground");
  });

  it("renders 'concentrated' label with red colour class", async () => {
    mockGetConcentration.mockResolvedValue({
      ...BASE_CONCENTRATION,
      hhi: 4200,
      label: "concentrated" as const,
    });

    render(wrap(<ConcentrationWidget portfolioId="p1" />));

    await waitFor(() => {
      expect(screen.getByTestId("hhi-label")).toBeInTheDocument();
    });

    const labelEl = screen.getByTestId("hhi-label");
    expect(labelEl.textContent?.toLowerCase()).toContain("concentrated");
    // "concentrated" → text-[#EF5350] (red) per the labelClass() mapping.
    expect(labelEl.className).toContain("text-[#EF5350]");
  });

  it("renders top-3 share percentage correctly", async () => {
    mockGetConcentration.mockResolvedValue({
      ...BASE_CONCENTRATION,
      top_3_share_pct: 42.7,
    });

    render(wrap(<ConcentrationWidget portfolioId="p1" />));

    await waitFor(() => {
      expect(screen.getByTestId("top3-share")).toBeInTheDocument();
    });

    // WHY textContent check: toFixed(1) formats 42.7 as "42.7"; the "%"
    // suffix is appended inline so the full rendered string is "42.7%".
    const top3El = screen.getByTestId("top3-share");
    expect(top3El.textContent).toContain("42.7");
    expect(top3El.textContent).toContain("%");
  });

  it("renders 'moderate' label with amber colour class", async () => {
    mockGetConcentration.mockResolvedValue({
      ...BASE_CONCENTRATION,
      hhi: 1800,
      label: "moderate" as const,
    });

    render(wrap(<ConcentrationWidget portfolioId="p1" />));

    await waitFor(() => {
      expect(screen.getByTestId("hhi-label")).toBeInTheDocument();
    });

    const labelEl = screen.getByTestId("hhi-label");
    expect(labelEl.textContent?.toLowerCase()).toContain("moderate");
    // "moderate" → text-[#FFB000] (amber) per labelClass().
    expect(labelEl.className).toContain("text-[#FFB000]");
  });
});
