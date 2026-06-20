/**
 * components/portfolio/__tests__/ConcentrationSectorTeaseStrip.test.tsx
 * (PLAN-0108 W3 T-3-03)
 *
 * WHY: Verifies the HHI badge classification chip renders the correct label and
 * color class for all three brackets, the top-3 sector tease, and the positions
 * count ("names") display.
 *
 * MOCKED:
 *   - useAuth  — always returns a stable accessToken so useQuery fires.
 *   - createGateway — returns a stub getConcentration that resolves to test data
 *     synchronously via Promise.resolve.
 *
 * WHY real QueryClientProvider (not mocked):
 *   TanStack Query's cache key deduplication behaviour is part of the contract;
 *   wrapping with a fresh QueryClient per test ensures isolation without
 *   mocking internals.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import type { AllocationSlice } from "@/features/portfolio/lib/kpi";

// ── Stable auth stub ──────────────────────────────────────────────────────────
vi.mock("@/hooks/useAuth", () => ({
  useAuth: vi.fn(() => ({
    accessToken: "test-token",
    isAuthenticated: true,
    isLoading: false,
    user: { user_id: "u1", tenant_id: "t1", email: "t@x.com", name: "Test", avatar_url: null },
    setTokens: vi.fn(),
    logout: vi.fn(),
  })),
}));

// ── Gateway mock factory — overridden per test ────────────────────────────────
// WHY module-level mock (not inline): vi.mock is hoisted to top of file by Vite
// transformer; the mock factory captures mockGetConcentration by reference so
// individual tests can swap the resolved value via mockResolvedValue().
const mockGetConcentration = vi.fn();
vi.mock("@/lib/gateway", () => ({
  createGateway: vi.fn(() => ({
    getConcentration: mockGetConcentration,
  })),
}));

// ── Component under test ──────────────────────────────────────────────────────
import { ConcentrationSectorTeaseStrip } from "../ConcentrationSectorTeaseStrip";

// ── Test helpers ──────────────────────────────────────────────────────────────

/** Fresh QueryClient per test — prevents cache bleed between test cases. */
function makeWrapper() {
  const qc = new QueryClient({
    defaultOptions: {
      queries: {
        // WHY retry:0 + gcTime:0: prevents background refetch retries from
        // emitting async warnings in test output after the test has completed.
        retry: 0,
        gcTime: 0,
      },
    },
  });
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
  };
}

/** Minimal ConcentrationResponse for a given HHI value. */
function makeConc(hhi: number, positionsCount = 5) {
  return {
    portfolio_id: "p1",
    hhi,
    label: "moderate" as const,
    top_3_share_pct: 60,
    positions_count: positionsCount,
    top_positions: [],
    prices_stale: false,
  };
}

/** Minimal sector slices — 3 entries, pct is a 0-1 fraction (BP-487). */
const MOCK_SECTORS: AllocationSlice[] = [
  { label: "Technology", value: 50000, pct: 0.5 },
  { label: "Health Care", value: 30000, pct: 0.3 },
  { label: "Financials", value: 20000, pct: 0.2 },
];

// ── Tests ─────────────────────────────────────────────────────────────────────

beforeEach(() => {
  vi.clearAllMocks();
});

describe("ConcentrationSectorTeaseStrip renders low HHI badge", () => {
  it("shows 'low' badge when HHI=800 (< 1000 threshold)", async () => {
    // WHY HHI=800: clearly below the 1000 boundary; badge must show "low".
    mockGetConcentration.mockResolvedValue(makeConc(800));

    render(
      <ConcentrationSectorTeaseStrip portfolioId="p1" bySector={MOCK_SECTORS} />,
      { wrapper: makeWrapper() },
    );

    // Wait for the async query to resolve and the badge to appear in the DOM.
    const badge = await waitFor(() => screen.getByTestId("hhi-badge"));
    expect(badge).toBeDefined();
    expect(badge.textContent?.toLowerCase()).toBe("low");

    // WHY check class string: the badge's visual meaning is encoded in its
    // Tailwind classes; a wrong class would render the correct text in the
    // wrong color, which is a silent UX regression.
    expect(badge.className).toMatch(/positive/);

    // Sanity: raw HHI number is visible alongside the badge.
    expect(screen.getByText(/HHI 800/)).toBeDefined();
  });
});

describe("ConcentrationSectorTeaseStrip renders moderate HHI badge", () => {
  it("shows 'moderate' badge when HHI=1500 (1000–2500 bracket)", async () => {
    // WHY HHI=1500: midpoint of the moderate bracket; tests the lower boundary
    // (1000) implicitly — boundary case 999 → low, 1000 → moderate.
    mockGetConcentration.mockResolvedValue(makeConc(1500));

    render(
      <ConcentrationSectorTeaseStrip portfolioId="p1" bySector={MOCK_SECTORS} />,
      { wrapper: makeWrapper() },
    );

    const badge = await waitFor(() => screen.getByTestId("hhi-badge"));
    expect(badge.textContent?.toLowerCase()).toBe("moderate");
    expect(badge.className).toMatch(/warning/);
    expect(screen.getByText(/HHI 1500/)).toBeDefined();
  });
});

describe("ConcentrationSectorTeaseStrip renders high HHI badge", () => {
  it("shows 'high' badge when HHI=3000 (> 2500 threshold)", async () => {
    // WHY HHI=3000: above the 2500 boundary; badge must show "high" in red.
    mockGetConcentration.mockResolvedValue(makeConc(3000));

    render(
      <ConcentrationSectorTeaseStrip portfolioId="p1" bySector={MOCK_SECTORS} />,
      { wrapper: makeWrapper() },
    );

    const badge = await waitFor(() => screen.getByTestId("hhi-badge"));
    expect(badge.textContent?.toLowerCase()).toBe("high");
    expect(badge.className).toMatch(/negative/);
    expect(screen.getByText(/HHI 3000/)).toBeDefined();
  });
});

describe("ConcentrationSectorTeaseStrip boundary conditions", () => {
  it("renders 'low' at exactly HHI=999", async () => {
    mockGetConcentration.mockResolvedValue(makeConc(999));
    render(
      <ConcentrationSectorTeaseStrip portfolioId="p1" bySector={MOCK_SECTORS} />,
      { wrapper: makeWrapper() },
    );
    const badge = await waitFor(() => screen.getByTestId("hhi-badge"));
    expect(badge.textContent?.toLowerCase()).toBe("low");
  });

  it("renders 'moderate' at exactly HHI=1000 (lower boundary)", async () => {
    mockGetConcentration.mockResolvedValue(makeConc(1000));
    render(
      <ConcentrationSectorTeaseStrip portfolioId="p1" bySector={MOCK_SECTORS} />,
      { wrapper: makeWrapper() },
    );
    const badge = await waitFor(() => screen.getByTestId("hhi-badge"));
    expect(badge.textContent?.toLowerCase()).toBe("moderate");
  });

  it("renders 'high' at exactly HHI=2500 (upper boundary)", async () => {
    mockGetConcentration.mockResolvedValue(makeConc(2500));
    render(
      <ConcentrationSectorTeaseStrip portfolioId="p1" bySector={MOCK_SECTORS} />,
      { wrapper: makeWrapper() },
    );
    const badge = await waitFor(() => screen.getByTestId("hhi-badge"));
    expect(badge.textContent?.toLowerCase()).toBe("high");
  });
});

describe("ConcentrationSectorTeaseStrip sector tease", () => {
  it("shows top-3 sector abbreviations and percentages", async () => {
    mockGetConcentration.mockResolvedValue(makeConc(1500));

    render(
      <ConcentrationSectorTeaseStrip portfolioId="p1" bySector={MOCK_SECTORS} />,
      { wrapper: makeWrapper() },
    );

    // WHY waitFor: query resolves async; sectors are shown in both loading and loaded states
    // but the structure may differ. After resolution we get the full layout.
    await waitFor(() => screen.getByTestId("hhi-badge"));

    // Top-3 labels truncated to 4 chars and uppercased.
    // WHY text match with partial: the element contains "TECH" + space + percent string.
    expect(screen.getByText(/TECH/)).toBeDefined();
    expect(screen.getByText(/HEAL/)).toBeDefined();
    expect(screen.getByText(/FINA/)).toBeDefined();

    // BP-487 regression guard: pct is a 0-1 fraction (0.5) and must render as
    // "+50.0%" via formatPercent (× 100). The pre-fix formatPercentDirect bug
    // rendered the raw value as "+0.5%". Pin the rendered percentages so a
    // scale regression fails loudly.
    expect(screen.getByText(/TECH\s+\+50\.0%/)).toBeDefined();
    expect(screen.getByText(/HEAL\s+\+30\.0%/)).toBeDefined();
    expect(screen.getByText(/FINA\s+\+20\.0%/)).toBeDefined();
  });

  it("shows positions count ('names') from the API", async () => {
    mockGetConcentration.mockResolvedValue(makeConc(1200, 12));

    render(
      <ConcentrationSectorTeaseStrip portfolioId="p1" bySector={MOCK_SECTORS} />,
      { wrapper: makeWrapper() },
    );

    await waitFor(() => screen.getByTestId("hhi-badge"));

    // WHY query for "names" substring: the positions_count element renders as
    // "<count> <span>names</span>" so querying by the "names" label is more
    // stable than a numeric regex that also matches "1200" in "HHI 1200".
    // We confirm both the count (12) and the label ("names") are present.
    const namesEl = screen.getAllByText(/names/i)[0];
    expect(namesEl).toBeDefined();
    // The parent span contains the count "12" as direct text node.
    expect(namesEl.parentElement?.textContent).toMatch(/12/);
  });

  it("renders em-dash placeholder when no sectors and no conc data", () => {
    // WHY portfolioId=null: disables the query (enabled=false); conc stays undefined.
    // WHY empty bySector: nothing to show — strip should stay at h-[22px] with a dash.
    render(
      <ConcentrationSectorTeaseStrip portfolioId={null} bySector={[]} />,
      { wrapper: makeWrapper() },
    );

    // The em-dash "—" is always rendered as the fallback.
    expect(screen.getByText("—")).toBeDefined();
  });
});
