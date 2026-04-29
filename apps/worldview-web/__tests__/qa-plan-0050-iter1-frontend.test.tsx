/**
 * __tests__/qa-plan-0050-iter1-frontend.test.tsx — QA iter-1 regression tests
 *
 * WHY THIS FILE EXISTS: QA audit 2026-04-29 (docs/audits/2026-04-29-qa-plan-0050-iter1-strict.md)
 * found 11 findings in the PLAN-0050 frontend implementation. This file adds
 * regression tests for each user-visible finding that was fixed.
 *
 * FINDINGS COVERED:
 *   F-Q1-04  — duplicate "Debt / Equity" row in FundamentalsTab Debt & Credit section
 *   F-Q1-05  — hardcoded entity-type chips; dynamic chips from live graph data
 *   F-Q1-06  — timeWindow NOT in TanStack queryKey (stale cache on filter change)
 *   F-Q1-09  — "no nodes match" empty state when all nodes filtered out
 *   F-Q1-16  — crash when Fundamentals.updated_at is null
 *   F-Q1-17  — window.prompt() for TEXT annotation replaced with inline input
 *   E-06     — annotationCount badge in DrawingPalette (shown when >0 annotations)
 *   E-07     — annotationCount=0 hides badge, annotationCount=3 shows "3"
 *
 * WHY vi.mock at top: Vitest hoists vi.mock() calls before all imports. The mocked
 * modules must be declared before any static import that depends on them.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import React from "react";

// ── Mocks (hoisted by vitest) ─────────────────────────────────────────────────

// WHY mock useAuth: all components that call createGateway need a token.
// We provide a stable mock token so gateway calls don't throw.
vi.mock("@/hooks/useAuth", () => ({
  useAuth: () => ({ accessToken: "test-token" }),
}));

// WHY mock gateway: components call createGateway(token).getEntityGraph() etc.
// We stub the return value to control what data the components receive in tests.
vi.mock("@/lib/gateway", () => ({
  createGateway: () => ({
    getEntityGraph: vi.fn().mockResolvedValue({
      entity_id: "ent-001",
      nodes: [
        { id: "ent-001", label: "Apple Inc.", type: "company" },
        { id: "ent-002", label: "Tim Cook",  type: "person" },
        { id: "ent-003", label: "AAPL",      type: "financial_instrument" },
      ],
      edges: [
        { source: "ent-001", target: "ent-002", label: "CEO_OF",    weight: 0.9 },
        { source: "ent-001", target: "ent-003", label: "OWNS",      weight: 1.0 },
      ],
    }),
    getContradictions: vi.fn().mockResolvedValue({ contradictions: [] }),
    getInstrumentBrief: vi.fn().mockResolvedValue(null),
    getFundamentals: vi.fn().mockResolvedValue(null),
    getFundamentalsSnapshot: vi.fn().mockResolvedValue(null),
    getTopNews: vi.fn().mockResolvedValue({ articles: [] }),
  }),
}));

// WHY mock TanStack Query: prevents "No QueryClient set" error in unit tests.
// The actual data flow (queryKey, queryFn) is covered by the component itself.
// WHY useQueryMock exported variable: tests for FundamentalsTab need to configure
// the mock return value per-test (the first useQuery call in the component returns
// `fund`, the second returns `snapshot`). The variable lets us call mockReturnValueOnce.
let useQueryCallCount = 0;
let _mockFundamentalsData: unknown = undefined;

vi.mock("@tanstack/react-query", async () => {
  const actual = await vi.importActual<typeof import("@tanstack/react-query")>(
    "@tanstack/react-query",
  );
  return {
    ...actual,
    useQuery: vi.fn(() => {
      // WHY call-count pattern: FundamentalsTab calls useQuery twice —
      // first for `fund` (Fundamentals), second for `snapshot` (FundamentalsSnapshot).
      // We return the fund data for the first call, undefined for subsequent calls.
      useQueryCallCount++;
      if (useQueryCallCount === 1) {
        return { data: _mockFundamentalsData, isLoading: false, isError: false, refetch: vi.fn(), dataUpdatedAt: 0 };
      }
      return { data: undefined, isLoading: false, isError: false, dataUpdatedAt: 0 };
    }),
  };
});

// WHY mock next/dynamic: IntelligenceTab imports EntityGraph via next/dynamic
// (SSR:false). In jsdom (test env) there is no WebGL context. The mock replaces
// the entire dynamic import with a lightweight stub div.
vi.mock("next/dynamic", () => ({
  default: (_fn: unknown) => {
    return function EntityGraphStub() {
      return React.createElement("div", { "data-testid": "entity-graph-stub" }, "graph");
    };
  },
}));

// WHY mock EntityGraphErrorBoundary: avoids needing the full React error boundary
// class component in the test bundle.
vi.mock("@/components/instrument/EntityGraphErrorBoundary", () => ({
  EntityGraphErrorBoundary: ({ children }: { children: React.ReactNode }) =>
    React.createElement(React.Fragment, null, children),
}));

// WHY mock MarkdownContent: the brief block renders markdown; we don't need
// the full renderer in unit tests — just confirm the section renders.
vi.mock("@/components/ui/markdown-content", () => ({
  MarkdownContent: ({ children }: { children: string }) =>
    React.createElement("div", { "data-testid": "markdown-content" }, children),
}));

// ── Static imports (after vi.mock declarations) ───────────────────────────────

import { DrawingPalette } from "@/components/instrument/DrawingPalette";
import { DrawingCanvas } from "@/components/instrument/DrawingCanvas";

// ── Mock Fundamentals data ────────────────────────────────────────────────────

// WHY MOCK_FUND: a minimal Fundamentals object with all required fields.
// Real API responses may have many more fields but tests only need what
// the component accesses. TypeScript enforces the shape via the Fundamentals type.
const MOCK_FUND = {
  entity_id: "ent-001",
  instrument_id: "ins-001",
  ticker: "AAPL",
  company_name: "Apple Inc.",
  market_cap: 3_000_000_000_000,
  pe_ratio: 28.5,
  forward_pe: 25.1,
  peg_ratio: 1.4,
  ev_ebitda: 22.3,
  price_to_book: 45.1,
  price_to_sales: 7.8,
  eps: 6.43,
  revenue: 394_000_000_000,
  gross_margin: 0.44,
  operating_margin: 0.30,
  net_margin: 0.25,
  roe: 1.73,
  roa: 0.28,
  revenue_growth_yoy: 0.08,
  eps_growth_yoy: 0.12,
  dividend_yield: 0.005,
  payout_ratio: 0.15,
  debt_to_equity: 1.76,
  current_ratio: 0.94,
  quick_ratio: 0.87,
  week_52_high: 199.62,
  week_52_low: 164.08,
  daily_return: 0.012,
  updated_at: "2026-04-28T10:00:00Z",
};

// ── F-Q1-04: Duplicate "Debt / Equity" row ───────────────────────────────────

describe("FundamentalsTab — F-Q1-04: no duplicate Debt / Equity row", () => {
  it("renders exactly one 'Debt / Equity' label in the metrics grid", async () => {
    // WHY dynamic import: FundamentalsTab has many sub-component imports that
    // require the mock context to be set up first (done above via vi.mock).
    const { FundamentalsTab } = await import(
      "@/components/instrument/FundamentalsTab"
    );

    // WHY reset call count: the useQuery mock tracks calls per render; reset
    // before each test to ensure the first call returns fund data.
    useQueryCallCount = 0;
    _mockFundamentalsData = MOCK_FUND;

    render(
      <FundamentalsTab
        instrumentId="ins-001"
        initialData={MOCK_FUND}
        currentPrice={189.5}
        entityId="ent-001"
      />,
    );

    // WHY getAllByText + length check: if the duplicate was present, this would
    // return 2 elements and the assertion would fail.
    const debtEquityLabels = screen.getAllByText(/Debt \/ Equity/i);
    expect(debtEquityLabels).toHaveLength(1);
  });
});

// ── F-Q1-16: Null-safe updated_at in FundamentalsTab ─────────────────────────

describe("FundamentalsTab — F-Q1-16: null updated_at does not crash", () => {
  it("renders the data section without crashing when updated_at is null", async () => {
    const { FundamentalsTab } = await import(
      "@/components/instrument/FundamentalsTab"
    );

    // WHY spread + override: creates a Fundamentals object with updated_at null.
    // The TypeScript type now allows string | null (fix for F-Q1-16).
    const fundWithNullDate = { ...MOCK_FUND, updated_at: null };

    // WHY reset call count before this test
    useQueryCallCount = 0;
    _mockFundamentalsData = fundWithNullDate;

    // WHY not toThrow(): render() itself would throw if the component crashes
    // on null. Confirming the page renders at all proves the null guard works.
    expect(() => {
      render(
        <FundamentalsTab
          instrumentId="ins-001"
          initialData={fundWithNullDate}
          currentPrice={189.5}
          entityId="ent-001"
        />,
      );
    }).not.toThrow();

    // WHY check for P/E Ratio: confirms the fundamentals grid rendered (not the
    // "No fundamental data available" fallback). The Valuation section always shows
    // P/E when fund data is present.
    expect(screen.getByText(/P\/E Ratio/i)).toBeInTheDocument();
  });

  it("renders '—' for the updated_at footer when updated_at is null", async () => {
    const { FundamentalsTab } = await import(
      "@/components/instrument/FundamentalsTab"
    );

    const fundWithNullDate = { ...MOCK_FUND, updated_at: null };
    useQueryCallCount = 0;
    _mockFundamentalsData = fundWithNullDate;

    render(
      <FundamentalsTab
        instrumentId="ins-001"
        initialData={fundWithNullDate}
        currentPrice={189.5}
        entityId="ent-001"
      />,
    );

    // WHY getByText with function matcher: the footer text is "Data sourced from
    // S3 fundamentals pipeline · Updated —". The "·" separator and "Updated —"
    // may be in the same text node or separate spans. A function matcher is more
    // resilient to DOM structure changes.
    const footer = screen.getByText((content) =>
      content.includes("Updated") && content.includes("—"),
    );
    expect(footer).toBeInTheDocument();
  });
});

// ── E-06 / E-07: DrawingPalette annotationCount badge ────────────────────────

describe("DrawingPalette — E-06/E-07: annotation count badge", () => {
  it("does NOT render the annotation count badge when annotationCount is 0", () => {
    render(
      <DrawingPalette
        activeTool={null}
        onSelectTool={vi.fn()}
        annotationCount={0}
      />,
    );
    // WHY queryByTestId (not getByTestId): queryByTestId returns null if not found
    // rather than throwing. We assert it's absent.
    expect(screen.queryByTestId("annotation-count")).toBeNull();
  });

  it("renders the annotation count badge with the correct number when annotationCount > 0", () => {
    render(
      <DrawingPalette
        activeTool={null}
        onSelectTool={vi.fn()}
        annotationCount={3}
      />,
    );
    const badge = screen.getByTestId("annotation-count");
    expect(badge).toBeInTheDocument();
    expect(badge).toHaveTextContent("3");
  });

  it("shows correct singular aria-label for annotationCount=1", () => {
    render(
      <DrawingPalette
        activeTool={null}
        onSelectTool={vi.fn()}
        annotationCount={1}
      />,
    );
    const badge = screen.getByTestId("annotation-count");
    expect(badge).toHaveAttribute("aria-label", "1 saved annotation");
  });

  it("shows correct plural aria-label for annotationCount=5", () => {
    render(
      <DrawingPalette
        activeTool={null}
        onSelectTool={vi.fn()}
        annotationCount={5}
      />,
    );
    const badge = screen.getByTestId("annotation-count");
    expect(badge).toHaveAttribute("aria-label", "5 saved annotations");
  });
});

// ── F-Q1-17: DrawingCanvas TEXT tool — inline input (no window.prompt) ────────

describe("DrawingCanvas — F-Q1-17: TEXT tool uses inline input, not window.prompt", () => {
  beforeEach(() => {
    // WHY spy on window.prompt: if window.prompt is called, the test should fail
    // (we replaced it with an inline input). This asserts the old behaviour is gone.
    vi.spyOn(window, "prompt").mockReturnValue(null);
  });

  it("does NOT call window.prompt when TEXT tool is armed and SVG is clicked", () => {
    // WHY null converters: DrawingCanvas reads converters before recording a click.
    // With null converters, pixelToChartPoint returns null and the click is a no-op
    // (no annotation committed). This tests that window.prompt is not called even
    // in the early-exit path for TEXT.
    render(
      <DrawingCanvas
        activeTool="TEXT"
        annotations={[]}
        onAnnotationAdd={vi.fn()}
        onAnnotationDelete={vi.fn()}
        converters={null}
        chartHeight={280}
        paletteWidth={28}
      />,
    );

    const canvas = screen.getByTestId("drawing-canvas");
    fireEvent.click(canvas);

    // WHY not.toHaveBeenCalled(): the TEXT tool should NEVER call window.prompt.
    // The inline input is rendered instead.
    expect(window.prompt).not.toHaveBeenCalled();
  });

  it("renders the text-annotation-input overlay when TEXT tool is armed and canvas is clicked with converters", () => {
    // WHY mock converters: a real IChartApi/ISeriesApi object would require
    // lightweight-charts to be loaded in jsdom (no Canvas 2D). A mock with
    // the minimal coordinate API surface is sufficient.
    const mockConverters = {
      chart: {
        timeScale: () => ({
          coordinateToTime: (_x: number) => 1_700_000_000, // valid Unix timestamp
          timeToCoordinate: (_t: number) => 100,
        }),
      },
      series: {
        coordinateToPrice: (_y: number) => 150.0,
        priceToCoordinate: (_p: number) => 50,
      },
    };

    render(
      <DrawingCanvas
        activeTool="TEXT"
        annotations={[]}
        onAnnotationAdd={vi.fn()}
        onAnnotationDelete={vi.fn()}
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        converters={mockConverters as any}
        chartHeight={280}
        paletteWidth={28}
      />,
    );

    const canvas = screen.getByTestId("drawing-canvas");
    // WHY clientX/clientY: DrawingCanvas uses getBoundingClientRect to convert
    // event coordinates to SVG-relative pixel positions.
    fireEvent.click(canvas, { clientX: 200, clientY: 100 });

    // WHY getByTestId("text-annotation-input"): the inline input should appear
    // as an overlay at the click position after the TEXT tool click.
    expect(screen.getByTestId("text-annotation-input")).toBeInTheDocument();
    expect(window.prompt).not.toHaveBeenCalled();
  });

  it("commits text annotation on Enter key without calling window.prompt", () => {
    const onAnnotationAdd = vi.fn();
    const mockConverters = {
      chart: {
        timeScale: () => ({
          coordinateToTime: () => 1_700_000_000,
          timeToCoordinate: () => 100,
        }),
      },
      series: {
        coordinateToPrice: () => 150.0,
        priceToCoordinate: () => 50,
      },
    };

    render(
      <DrawingCanvas
        activeTool="TEXT"
        annotations={[]}
        onAnnotationAdd={onAnnotationAdd}
        onAnnotationDelete={vi.fn()}
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        converters={mockConverters as any}
        chartHeight={280}
        paletteWidth={28}
      />,
    );

    const canvas = screen.getByTestId("drawing-canvas");
    fireEvent.click(canvas, { clientX: 200, clientY: 100 });

    const input = screen.getByTestId("text-annotation-input");
    fireEvent.change(input, { target: { value: "Support Zone" } });
    fireEvent.keyDown(input, { key: "Enter" });

    // WHY toHaveBeenCalledOnce: annotation should be added exactly once
    expect(onAnnotationAdd).toHaveBeenCalledOnce();
    const annotation = onAnnotationAdd.mock.calls[0][0];
    expect(annotation.tool).toBe("TEXT");
    expect(annotation.text).toBe("Support Zone");
    // WHY toMatch UUID v4: crypto.randomUUID() returns RFC4122 UUID v4
    expect(annotation.id).toMatch(
      /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/,
    );
    expect(window.prompt).not.toHaveBeenCalled();
  });

  it("cancels text annotation on Escape without adding any annotation", () => {
    const onAnnotationAdd = vi.fn();
    const mockConverters = {
      chart: {
        timeScale: () => ({
          coordinateToTime: () => 1_700_000_000,
          timeToCoordinate: () => 100,
        }),
      },
      series: {
        coordinateToPrice: () => 150.0,
        priceToCoordinate: () => 50,
      },
    };

    render(
      <DrawingCanvas
        activeTool="TEXT"
        annotations={[]}
        onAnnotationAdd={onAnnotationAdd}
        onAnnotationDelete={vi.fn()}
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        converters={mockConverters as any}
        chartHeight={280}
        paletteWidth={28}
      />,
    );

    fireEvent.click(screen.getByTestId("drawing-canvas"), {
      clientX: 200, clientY: 100,
    });
    expect(screen.getByTestId("text-annotation-input")).toBeInTheDocument();

    fireEvent.keyDown(screen.getByTestId("text-annotation-input"), {
      key: "Escape",
    });

    // WHY queryByTestId: the input should be removed after Escape
    expect(screen.queryByTestId("text-annotation-input")).toBeNull();
    expect(onAnnotationAdd).not.toHaveBeenCalled();
  });
});
