/**
 * components/instrument/quote/__tests__/QuoteTab.layout.test.tsx
 *
 * WHY THIS EXISTS (scroll-affordance regression, 2026-06-12):
 * The Quote tab's right STATISTICS rail (MetricsTable + CompanyAboutCard) has
 * more content on a typical large-cap (AAPL: Valuation → Profitability →
 * Leverage → 52-Week → Ownership → Technicals → Analyst Consensus → Target →
 * sector/industry/description) than fits the viewport. The rail is a CSS-GRID
 * ITEM, whose default `min-height: auto` prevented it from shrinking below its
 * content height — so `overflow-y-auto` never engaged and the lower sections
 * spilled past the parent's `h-full overflow-hidden` and were CLIPPED (visible
 * but unreachable, no scrollbar).
 *
 * The fix adds `min-h-0` to the rail so the grid item can shrink to its track
 * height and `overflow-y-auto` engages. This suite pins the load-bearing
 * layout classes so a future refactor can't silently drop the scroll
 * affordance and re-clip the rail.
 *
 * MOCK STRATEGY: every child is mocked to a trivial marker element — this is a
 * PURE LAYOUT test (we assert container classes, not child behaviour), so we
 * deliberately avoid pulling in the children's data/query dependencies.
 */

import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";

import { QuoteTab } from "@/components/instrument/quote/QuoteTab";

// ── Child mocks ────────────────────────────────────────────────────────────
// Each child becomes a marker so QuoteTab renders without any query/runtime
// dependency — we only care about the layout containers it wraps them in.
vi.mock("@/components/instrument/chart/OHLCVChart", () => ({
  OHLCVChart: () => <div data-testid="ohlcv-chart" />,
}));
vi.mock("@/components/instrument/quote/stats/KeyStatsBar", () => ({
  KeyStatsBar: () => <div data-testid="key-stats-bar" />,
}));
vi.mock("@/components/instrument/quote/strips/IntradayStatsStrip", () => ({
  IntradayStatsStrip: () => <div data-testid="intraday-stats-strip" />,
}));
vi.mock("@/components/instrument/quote/strips/ReturnsStrip", () => ({
  ReturnsStrip: () => <div data-testid="returns-strip" />,
}));
vi.mock("@/components/instrument/quote/strips/PeersTable", () => ({
  PeersTable: () => <div data-testid="peers-table" />,
}));
vi.mock("@/components/instrument/quote/strips/PriceLevelsPanel", () => ({
  PriceLevelsPanel: () => <div data-testid="price-levels-panel" />,
}));
vi.mock("@/components/instrument/quote/bottom/WhatsMovingStrip", () => ({
  WhatsMovingStrip: () => <div data-testid="whats-moving-strip" />,
}));
// The two children that actually live INSIDE the scrollable rail — we mark
// them so we can assert they are descendants of the scroll container.
vi.mock("@/components/instrument/quote/metrics/MetricsTable", () => ({
  MetricsTable: () => <div data-testid="metrics-table" />,
}));
vi.mock("@/components/instrument/quote/about/CompanyAboutCard", () => ({
  CompanyAboutCard: () => <div data-testid="company-about-card" />,
}));

function renderQuoteTab() {
  return render(
    <QuoteTab
      instrumentId="i-1"
      entityId="e-1"
      fundamentals={null}
      quote={null}
      bundle={null}
    />,
  );
}

describe("QuoteTab — right STATISTICS rail scroll affordance", () => {
  it("wraps the rail's children in a single independently-scrollable container", () => {
    renderQuoteTab();

    // The rail is the nearest common ancestor of MetricsTable + CompanyAboutCard.
    const metricsTable = screen.getByTestId("metrics-table");
    const aboutCard = screen.getByTestId("company-about-card");
    const rail = metricsTable.parentElement;

    expect(rail).not.toBeNull();
    // Both rail children share the same scroll container (one column, one scroll).
    expect(aboutCard.parentElement).toBe(rail);
  });

  it("gives the rail BOTH overflow-y-auto AND min-h-0 (the bug fix)", () => {
    renderQuoteTab();

    const rail = screen.getByTestId("metrics-table").parentElement;

    // overflow-y-auto = the scroll affordance itself (the visible scrollbar).
    expect(rail).toHaveClass("overflow-y-auto");
    // min-h-0 = the load-bearing fix: without it the grid item refuses to
    // shrink below its content height and overflow-y-auto never engages, so
    // the lower sections (Target/sector/description) get clipped & unreachable.
    expect(rail).toHaveClass("min-h-0");
  });

  it("keeps the chart in a SEPARATE bounded track so the rail fix can't shrink it", () => {
    renderQuoteTab();

    // The chart lives in the left grid column, wrapped in flex-1 min-h-0 — it
    // fills its own pane and is unaffected by the rail's overflow behaviour.
    const chartWrapper = screen.getByTestId("ohlcv-chart").parentElement;
    expect(chartWrapper).toHaveClass("flex-1");
    expect(chartWrapper).toHaveClass("min-h-0");
  });
});
