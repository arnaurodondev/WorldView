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

    // MED-005 changed the tile container from flex-wrap to CSS grid auto-fit
    // (B-2-03 fix). The gap assertion still validates the tight 2px spacing.
    const tileContainer = container.querySelector(".grid.gap-0\\.5");
    expect(tileContainer).not.toBeNull();
    const tileEl = tileContainer as HTMLElement;
    expect(tileEl.className).toMatch(/\bgap-0\.5\b/);
    expect(tileEl.className).not.toMatch(/\bgap-1\b/);
  });
});

// ── W4 COMPACT 7+6 grid (user report 2026-06-12) ──────────────────────────────
// SUPERSEDES the prior "dead-space fix (2026-06-10)" block. That fix made the
// heatmap STRETCH to fill the row's height (flex-1 + gridAutoRows minmax(40px,
// 1fr)) — but because the heatmap was the tallest cell, it DRAGGED THE WHOLE
// ROW TALL, which is the exact "row 1 has too much vertical space" the user
// reported on 2026-06-12. The new contract is the OPPOSITE: a DETERMINISTIC
// short, fixed two-row (7 + 6) grid that makes the widget compact so the row
// can collapse around it. These assertions pin that new shape.
describe("SectorHeatmapWidget — compact fixed 7+6 grid (W4 task 2a)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders exactly two fixed rows (7 tiles then 6) — not a stretchy auto-fit grid", async () => {
    const { getByTestId, findAllByLabelText } = render(
      <SectorHeatmapWidget />,
      { wrapper: ({ children }) => wrap(children) },
    );
    await findAllByLabelText(/ sector,/i);

    // The grid container is now a SHORT flex-col (shrink-0), NOT flex-1 — it
    // must not stretch to fill the row's height anymore.
    const grid = getByTestId("sector-heatmap-grid");
    expect(grid.className).toMatch(/\bshrink-0\b/);
    expect(grid.className).not.toMatch(/\bflex-1\b/);

    // Two explicit rows: row 1 has 7 equal columns, row 2 has 6. The fixture
    // has 11 sectors → row 1 gets 7, row 2 gets the remaining 4 (the slice is
    // defensive for <13 sectors), but BOTH rows exist and use repeat(N,…).
    const row1 = getByTestId("sector-heatmap-row-1");
    const row2 = getByTestId("sector-heatmap-row-2");
    expect(row1).not.toBeNull();
    expect(row2).not.toBeNull();
    // Row 1 always lays out 7 columns (the first ROW_1_TILES slice).
    expect(row1.style.gridTemplateColumns).toBe("repeat(7, minmax(0, 1fr))");
  });

  it("splits 13 sectors as 7 over 6 when the full GICS set is present", async () => {
    // A 13-sector fixture (the production reality: heatmap returns 13 sectors)
    // must produce row 1 = 7 tiles, row 2 = 6 tiles — the user's "13 sectors"
    // contract. We probe each row's direct tile children.
    const thirteen: MarketHeatmapResponse = {
      sectors: Array.from({ length: 13 }, (_, i) => ({
        name: `Sector ${i + 1}`,
        change_pct: (i % 2 === 0 ? 1 : -1) * (i + 1) * 0.1,
        instrument_count: 10 + i,
      })),
    };
    const { createGateway } = await import("@/lib/gateway");
    (createGateway as unknown as ReturnType<typeof vi.fn>).mockReturnValue({
      getMarketHeatmap: vi.fn().mockResolvedValue(thirteen),
      getTopMovers: vi.fn().mockResolvedValue({ movers: [], type: "gainers" }),
      getCompanyOverview: vi.fn().mockResolvedValue({ instrument: { gics_sector: null } }),
      getCompanyOverviewsBatch: vi.fn().mockResolvedValue({}),
    });

    const { getByTestId, findAllByLabelText } = render(
      <SectorHeatmapWidget />,
      { wrapper: ({ children }) => wrap(children) },
    );
    await findAllByLabelText(/ sector,/i);

    const row1 = getByTestId("sector-heatmap-row-1");
    const row2 = getByTestId("sector-heatmap-row-2");
    // Each row's tiles are <button> elements with a "sector," aria-label.
    const row1Tiles = row1.querySelectorAll('[aria-label*="sector,"]');
    const row2Tiles = row2.querySelectorAll('[aria-label*="sector,"]');
    expect(row1Tiles.length).toBe(7);
    expect(row2Tiles.length).toBe(6);
  });

  it("each tile has a fixed compact inline height (not h-full stretch)", async () => {
    const { findAllByLabelText } = render(
      <SectorHeatmapWidget />,
      { wrapper: ({ children }) => wrap(children) },
    );
    const tiles = await findAllByLabelText(/ sector,/i);

    for (const tile of tiles) {
      const el = tile as HTMLElement;
      // The tile now declares an EXPLICIT fixed height (the compact 26px) so
      // the widget is short — the old `h-full` stretch (which dragged the row
      // tall) must be gone.
      expect(el.className).not.toMatch(/\bh-full\b/);
      expect(el.style.height).toBe("26px");
    }
  });
});
