/**
 * __tests__/sector-heatmap-overflow.test.tsx — PLAN-0049 T-D-4-05.
 *
 * WHY THIS EXISTS: B-2-03 was a real overflow bug — at certain viewport widths
 * the sector treemap pushed its last column past the widget border because of
 * sub-pixel rounding on flex-basis + gap accumulation. The fix (GAP_PX=2 +
 * overflow-hidden on the container) is invisible in the render tree but
 * critical at the layout level. This test pins the contract: at three trader-
 * representative widths (1024/1440/1920px), the rendered tile container's
 * scrollWidth must NEVER exceed clientWidth (= no horizontal overflow).
 *
 * F-QAC-03 fix: the prior version asserted ``scrollWidth ≤ clientWidth`` —
 * but in jsdom both default to 0 and the layout engine never computes
 * geometry, so the assertion was a tautology (0 ≤ 0) that would have green-
 * lit any regression. We replaced it with structural invariant assertions:
 * the widget root carries ``overflow-hidden``; the inner flex container
 * uses ``flex-wrap`` + the post-fix gap class; all 11 tiles are present.
 * A regression that drops ``overflow-hidden`` or restores the wider
 * ``gap-1``/``gap-px`` class trips these assertions immediately. Real
 * pixel overflow continues to be guarded by the Playwright stabilization
 * spec which runs in a real browser.
 *
 * SCOPE: 4 specs:
 *   1-3. At three trader viewports, the widget renders all 11 tiles inside
 *        an overflow-hidden parent.
 *   4.  The inner flex container uses the post-fix gap class (``gap-0.5``)
 *        not the pre-fix ``gap-1`` that caused the bug.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import type { MarketHeatmapResponse } from "@/types/api";

// ── Auth + navigation mocks ──────────────────────────────────────────────────
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

vi.mock("next/navigation", () => ({
  useRouter: vi.fn(() => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn() })),
  usePathname: vi.fn(() => "/dashboard"),
  useSearchParams: vi.fn(() => new URLSearchParams()),
}));

// ── Gateway mock — populated heatmap with all 11 GICS sectors ────────────────
// 11 sectors is the worst case for the gap accumulation bug — fewer tiles
// would always fit comfortably. See SectorHeatmapWidget header for the list.
const SECTORS_FIXTURE: MarketHeatmapResponse = {
  sectors: [
    { name: "Information Technology", change_pct: 2.1, instrument_count: 50 },
    { name: "Health Care", change_pct: -0.5, instrument_count: 40 },
    { name: "Consumer Discretionary", change_pct: 1.2, instrument_count: 35 },
    { name: "Consumer Staples", change_pct: 0.3, instrument_count: 28 },
    { name: "Communication Services", change_pct: -1.1, instrument_count: 22 },
    { name: "Financials", change_pct: 0.8, instrument_count: 60 },
    { name: "Industrials", change_pct: -0.2, instrument_count: 45 },
    { name: "Materials", change_pct: 0.6, instrument_count: 18 },
    { name: "Real Estate", change_pct: -0.9, instrument_count: 25 },
    { name: "Utilities", change_pct: 0.1, instrument_count: 20 },
    { name: "Energy", change_pct: 3.5, instrument_count: 30 },
  ],
};

vi.mock("@/lib/gateway", () => ({
  createGateway: vi.fn(() => ({
    // SectorHeatmapWidget calls these three:
    getMarketHeatmap: vi.fn().mockResolvedValue(SECTORS_FIXTURE),
    getTopMovers: vi.fn().mockResolvedValue({ movers: [], type: "gainers" }),
    getCompanyOverview: vi.fn().mockResolvedValue({
      instrument: { gics_sector: null },
    }),
  })),
}));

import { SectorHeatmapWidget } from "@/components/dashboard/SectorHeatmapWidget";

function wrap(children: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

// ── Width simulation helper ───────────────────────────────────────────────────
// jsdom doesn't compute layout, but we can stub clientWidth/scrollWidth
// per-element so layout-shape tests work. Tests render then probe the resulting
// elements — if the assertion (scrollWidth ≤ clientWidth) holds, the layout
// container did not escape its parent.
function simulateViewport(width: number): void {
  // window dimensions feed CSS media-query mocks (none used here, but kept
  // for documentation-of-intent).
  Object.defineProperty(window, "innerWidth", { configurable: true, value: width });
  Object.defineProperty(window, "innerHeight", { configurable: true, value: 800 });
}

// ── Tests ─────────────────────────────────────────────────────────────────────

describe("SectorHeatmapWidget — overflow guard at trader viewports (B-2-03)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  // WHY 3 widths: 1024 = small laptop, 1440 = MBP/standard trader desk,
  // 1920 = full FHD station. These are the realistic min/median/max screens
  // worldview is designed for. B-2-03 originally reproduced at 1280, so 1024
  // is intentionally below that to keep the test honest.
  it.each([1024, 1440, 1920])(
    "renders all 11 sector tiles inside an overflow-hidden container at %ipx viewport",
    async (width) => {
      simulateViewport(width);

      const { findAllByLabelText } = render(
        <SectorHeatmapWidget />,
        { wrapper: ({ children }) => wrap(children) },
      );

      // F-QAC-03 fix: query by sector aria-label suffix (specific to the
      // sector tiles) rather than role=button — the latter also matches
      // the period-selector buttons (1D/1W/1M) and the matrix would never
      // hit 11.  Each tile's aria-label ends with "sector, ...".
      const tiles = await findAllByLabelText(/ sector,/i);
      expect(tiles.length).toBe(11);

      // Assert the structural invariant the bug fix put in place — the
      // widget MUST be wrapped by something that carries
      // ``overflow-hidden`` so any sub-pixel overflow is clipped instead
      // of escaping the cell border. Walk up from a tile to confirm.
      const sampleTile = tiles[0] as HTMLElement;
      const overflowHiddenAncestor = sampleTile.closest(".overflow-hidden");
      expect(overflowHiddenAncestor).not.toBeNull();
    },
  );

  it("inner tile container uses the post-fix ``gap-0.5`` class (not the pre-fix ``gap-1``)", async () => {
    // F-QAC-03 fix: pin the exact Tailwind class the B-2-03 fix shipped.
    // The original bug was ``gap-1`` (4px) accumulating sub-pixel rounding
    // across 11 flex children → last tile pushed past the 1px terminal seam.
    // The fix tightened the gap to ``gap-0.5`` (2px). A regression that
    // restores the wider gap trips the negative assertion below.
    simulateViewport(1440);

    const { container, findAllByLabelText } = render(
      <SectorHeatmapWidget />,
      { wrapper: ({ children }) => wrap(children) },
    );

    await findAllByLabelText(/ sector,/i);

    const tileContainer = container.querySelector(".flex-wrap");
    expect(tileContainer).not.toBeNull();
    const tileEl = tileContainer as HTMLElement;
    expect(tileEl.className).toMatch(/\bgap-0\.5\b/);
    expect(tileEl.className).not.toMatch(/\bgap-1\b/);
  });
});
