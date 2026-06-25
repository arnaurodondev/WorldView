/**
 * components/instrument/financials/__tests__/AnalystSidebar.test.tsx
 *
 * WHY THIS EXISTS (T-24 rewrite): PLAN-0089 W3 converts AnalystSidebar into a
 * 7-panel composition shell. This test verifies the composition contract:
 *
 *   1. CompanySnapshotPanel renders (COMPANY section visible)
 *   2. AnalystConsensusPanel renders consensus bar when counts are non-null
 *   3. TargetPricePanel renders the 12-MO TARGET header
 *
 * WHY mock hooks: AIBriefPanel calls useInstrumentBrief (custom hook with
 * async polling). BeatMissHistoryPanel calls useQuery. Without mocking, the
 * test would need a full TanStack Query + auth context tree. We test those
 * components individually in their own test files.
 *
 * WHY vi.mock (not render spy): the composition contract is about panel order
 * and structural presence. Mocking child components to return simple divs
 * isolates this test from child implementation details.
 */

import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";

// WHY mock the two client-side hooks panels before importing AnalystSidebar:
// AIBriefPanel uses useInstrumentBrief which has async state + useQuery.
// BeatMissHistoryPanel uses useQuery. Both require a full provider tree.
vi.mock(
  "@/components/instrument/financials/sidebar/AIBriefPanel",
  () => ({
    AIBriefPanel: () => <div data-testid="ai-brief-panel">AI Brief</div>,
  }),
);
vi.mock(
  "@/components/instrument/financials/sidebar/BeatMissHistoryPanel",
  () => ({
    BeatMissHistoryPanel: () => <div data-testid="beat-miss-panel">Beat/Miss</div>,
  }),
);

import { AnalystSidebar } from "@/components/instrument/financials/AnalystSidebar";
import type { Fundamentals, Instrument } from "@/types/api";

const FUNDAMENTALS: Partial<Fundamentals> = {
  analyst_strong_buy_count: 25,
  analyst_buy_count: 5,
  analyst_hold_count: 10,
  analyst_sell_count: 4,
  analyst_strong_sell_count: 1,
  analyst_target_price: 150.5,
  updated_at: "2026-05-19T12:00:00Z",
};

const INSTRUMENT: Partial<Instrument> = {
  ticker: "AAPL",
  name: "Apple Inc.",
  gics_sector: "Information Technology",
  gics_industry: "Technology Hardware",
  exchange: "NASDAQ",
  country: "USA",
  description: "Apple designs and sells consumer electronics.",
};

describe("AnalystSidebar (T-24 composition shell)", () => {
  it("renders the ANALYST CONSENSUS section", () => {
    render(
      <AnalystSidebar
        instrument={INSTRUMENT as Instrument}
        fundamentals={FUNDAMENTALS as Fundamentals}
        currentPrice={180.0}
        entityId="test-entity-id"
        instrumentId="test-instrument-id"
      />,
    );

    // WHY assert ANALYST CONSENSUS: this header is owned by AnalystConsensusPanel
    // and proves it rendered. If the panel is accidentally omitted from the
    // composition, this assertion catches it.
    expect(screen.getByText("ANALYST CONSENSUS")).toBeInTheDocument();
  });

  it("renders 12-MO TARGET section", () => {
    render(
      <AnalystSidebar
        instrument={INSTRUMENT as Instrument}
        fundamentals={FUNDAMENTALS as Fundamentals}
        currentPrice={180.0}
        entityId="test-entity-id"
        instrumentId="test-instrument-id"
      />,
    );

    expect(screen.getByText("12-MO TARGET")).toBeInTheDocument();
  });

  it("renders COMPANY section from CompanySnapshotPanel", () => {
    render(
      <AnalystSidebar
        instrument={INSTRUMENT as Instrument}
        fundamentals={FUNDAMENTALS as Fundamentals}
        currentPrice={180.0}
        entityId="test-entity-id"
        instrumentId="test-instrument-id"
      />,
    );

    expect(screen.getByText("COMPANY")).toBeInTheDocument();
    // WHY sector text: CompanySnapshotPanel renders the gics_sector field.
    expect(screen.getByText("Information Technology")).toBeInTheDocument();
  });

  it("handles null fundamentals gracefully", () => {
    // WHY test null case: the bundle may not resolve before the Financials tab
    // mounts. The sidebar must render empty panels, not crash.
    render(
      <AnalystSidebar
        instrument={null}
        fundamentals={null}
        currentPrice={null}
        entityId="test-entity-id"
        instrumentId="test-instrument-id"
      />,
    );

    // Sidebar shell still renders without error.
    expect(screen.getByRole("complementary")).toBeInTheDocument();
  });

  // ── Wave-2 redesign (scope item 5): the two permanent stubs are GONE ───────
  // PORTED from the deleted RevisionsPanel.test.tsx / TargetsByAnalystPanel
  // .test.tsx suites: those tests pinned that the stub headers + "pending
  // data source" footnotes rendered. The Wave-2 contract is the inverse —
  // the sidebar must NOT ship blocks of em-dashes for data that does not
  // exist in this dataset. If a real data source lands, the panel returns
  // WITH data and these assertions flip back (deliberately loud).

  it("does NOT render the dropped stub panels (ESTIMATE REVISIONS / TARGETS BY ANALYST)", () => {
    render(
      <AnalystSidebar
        instrument={INSTRUMENT as Instrument}
        fundamentals={FUNDAMENTALS as Fundamentals}
        currentPrice={180.0}
        entityId="test-entity-id"
        instrumentId="test-instrument-id"
      />,
    );

    expect(screen.queryByText("ESTIMATE REVISIONS")).not.toBeInTheDocument();
    expect(screen.queryByText("TARGETS BY ANALYST")).not.toBeInTheDocument();
    // The stub footnote copy must be gone with them.
    expect(screen.queryByText(/pending data source/i)).not.toBeInTheDocument();
  });

  it("renders exactly the 5 real panels in order (company → consensus → target → beat/miss → AI brief)", () => {
    const { container } = render(
      <AnalystSidebar
        instrument={INSTRUMENT as Instrument}
        fundamentals={FUNDAMENTALS as Fundamentals}
        currentPrice={180.0}
        entityId="test-entity-id"
        instrumentId="test-instrument-id"
      />,
    );

    // Panel-order contract: collect the recognisable marker of each panel in
    // DOM order and compare. Mocked panels expose data-testids; real panels
    // expose their header labels.
    const text = container.textContent ?? "";
    const order = [
      text.indexOf("COMPANY"),
      text.indexOf("ANALYST CONSENSUS"),
      text.indexOf("12-MO TARGET"),
      text.indexOf("Beat/Miss"), // mocked BeatMissHistoryPanel
      text.indexOf("AI Brief"), // mocked AIBriefPanel
    ];
    // Every marker present…
    for (const idx of order) expect(idx).toBeGreaterThanOrEqual(0);
    // …and strictly ascending (the composition order).
    for (let i = 1; i < order.length; i++) {
      expect(order[i]).toBeGreaterThan(order[i - 1]!);
    }
  });
});
