/**
 * components/instrument/quote/__tests__/TAOverlayPanel.test.tsx
 *
 * WHY THESE TESTS EXIST (PLAN-0091 Wave F-1):
 * TAOverlayPanel is the user-facing entry point for TA overlay toggles.
 * The chip toggle → overlay computation → parent callback chain has several
 * non-obvious behaviours (Set identity, microtask scheduling, NaN stripping)
 * that warrant explicit test coverage so regressions are caught immediately.
 *
 * TEST COVERAGE:
 *   1. All 7 chips render inactive by default (no aria-pressed=true).
 *   2. Clicking a chip toggles it to active state (aria-pressed=true).
 *   3. onOverlaysChange receives at least one OverlaySeries with matching id
 *      after a chip is toggled on.
 *   4. Clicking an active chip deactivates it and onOverlaysChange is called
 *      with an empty or reduced array.
 *
 * PLAN-0091 Wave F-2 — SENTI chip additions:
 *   5. SENTI chip renders disabled (aria-disabled=true) when entityId is null.
 *   6. SENTI chip is enabled and toggleable when entityId is provided.
 *   7. Toggling SENTI with entityId calls onOverlaysChange with id="senti" and
 *      axis="right" (once sentiment data resolves from the mock).
 *   8. Sentiment data is date-aligned with bars: matched bars get net_sentiment,
 *      unmatched bars get NaN.
 *
 * NOTE ON MICROTASK SCHEDULING:
 *   TAOverlayPanel calls onOverlaysChange inside a Promise.resolve().then()
 *   microtask to avoid firing a parent setState during the child's render.
 *   Tests must flush the microtask queue after user interactions — this is done
 *   via `await act(async () => {})` (React Testing Library's act wraps the
 *   render in an async boundary that also drains pending microtasks).
 *
 * NOTE ON MOCKING useEntitySentimentTimeseries:
 *   The SENTI chip calls useEntitySentimentTimeseries from lib/api/intelligence.
 *   That hook internally uses useQuery (TanStack). Rather than wrapping every
 *   test in a QueryClientProvider, we mock the module at the top level and
 *   control the return value per test via mockReturnValue. This isolates the
 *   sentiment fetch from the TA chip logic and avoids network calls in tests.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, act } from "@testing-library/react";
import { TAOverlayPanel } from "../TAOverlayPanel";
import type { OHLCVBar } from "@/types/api";
import type { OverlaySeries } from "@/components/instrument/chart/OHLCVChart";

// ── Mock: useEntitySentimentTimeseries ────────────────────────────────────────
//
// WHY mock the whole module instead of a QueryClientProvider wrapper:
// The existing 8 F-1 tests do not use a QueryClientProvider — adding one would
// require touching every existing test call site. Mocking the hook at the module
// level lets us control its return value per test without restructuring the suite.
//
// WHY vi.hoisted: Vitest hoists vi.mock() calls before imports but the factory
// function needs to reference a vi.fn(). vi.hoisted() provides a safe way to
// create the mock fn before the import statements execute.
const mockUseSentimentTimeseries = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api/intelligence", () => ({
  useEntitySentimentTimeseries: mockUseSentimentTimeseries,
}));

// ── Fixtures ─────────────────────────────────────────────────────────────────

/** Make a minimal OHLCVBar with configurable close/volume. */
function makeBar(close: number, volume = 100): OHLCVBar {
  return { timestamp: "2026-01-01T00:00:00Z", open: close, high: close, low: close, close, volume };
}

/**
 * A bars array long enough for all TA computations to produce at least one
 * non-NaN value:
 *   EMA 200 / SMA 200 need 200 bars.
 *   RSI(14) needs 15 bars.
 *   MACD needs 33+ bars (EMA26 seed + 9-bar signal EMA seed).
 *   Bollinger(20) needs 20 bars.
 *   VWAP: defined from bar 0.
 *
 * WHY 250 bars: covers SMA 200 warm-up with 50 bars of defined values.
 */
const BARS_250: OHLCVBar[] = Array.from({ length: 250 }, (_, i) =>
  makeBar(100 + Math.sin(i / 10) * 20, 1000 + i),
);

// ── Tests ────────────────────────────────────────────────────────────────────

describe("TAOverlayPanel", () => {
  // WHY explicit type annotation: vi.fn() returns Mock<...> and the calls array
  // is typed as [OverlaySeries[]][]. The explicit type lets TypeScript verify that
  // we're calling the right overload in test assertions.
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  let onOverlaysChange: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    onOverlaysChange = vi.fn();
    // WHY default mock: the SENTI chip always calls useEntitySentimentTimeseries
    // (hooks must run unconditionally). Return { data: undefined } by default so
    // the F-1 tests that don't pass entityId still pass without sentiment data.
    mockUseSentimentTimeseries.mockReturnValue({ data: undefined });
  });

  // ── Initial render ─────────────────────────────────────────────────────────

  it("renders all 7 TA chip buttons plus the SENTI chip (8 total)", () => {
    render(<TAOverlayPanel bars={BARS_250} onOverlaysChange={onOverlaysChange} timeframe="1D" />);

    // Each chip has an aria-label of the form "Toggle <label> overlay".
    // WHY aria-label: more reliable than text content because the label
    // may change for internationalisation without breaking the test's intent.
    expect(screen.getByRole("button", { name: /Toggle EMA 20 overlay/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Toggle EMA 50 overlay/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Toggle SMA 200 overlay/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Toggle MACD overlay/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Toggle BOLL overlay/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Toggle RSI overlay/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Toggle VWAP overlay/i })).toBeInTheDocument();
    // F-2: SENTI chip should also be present in the strip.
    expect(screen.getByRole("button", { name: /Toggle SENTI overlay/i })).toBeInTheDocument();
  });

  it("all chips are inactive (aria-pressed=false) by default", () => {
    render(<TAOverlayPanel bars={BARS_250} onOverlaysChange={onOverlaysChange} timeframe="1D" />);

    // WHY getAllByRole without name filter: includes the SENTI chip which is
    // disabled (aria-disabled=true) but still has aria-pressed=false.
    // Disabled buttons are still in the accessibility tree with role=button.
    const buttons = screen.getAllByRole("button");
    // Every chip button must report aria-pressed=false initially — none are toggled.
    buttons.forEach((btn) => {
      expect(btn).toHaveAttribute("aria-pressed", "false");
    });
  });

  // ── Toggle on ─────────────────────────────────────────────────────────────

  it("clicking an inactive chip makes it active (aria-pressed=true)", async () => {
    render(<TAOverlayPanel bars={BARS_250} onOverlaysChange={onOverlaysChange} timeframe="1D" />);

    const ema20Btn = screen.getByRole("button", { name: /Toggle EMA 20 overlay/i });
    expect(ema20Btn).toHaveAttribute("aria-pressed", "false");

    // WHY act(): fireEvent triggers a React state update (setActiveChips).
    // act() flushes the update synchronously and drains microtasks.
    await act(async () => {
      fireEvent.click(ema20Btn);
    });

    expect(ema20Btn).toHaveAttribute("aria-pressed", "true");
  });

  it("clicking EMA 20 calls onOverlaysChange with an overlay whose id is 'ema-20'", async () => {
    render(<TAOverlayPanel bars={BARS_250} onOverlaysChange={onOverlaysChange} timeframe="1D" />);

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /Toggle EMA 20 overlay/i }));
    });

    // WHY: onOverlaysChange is called in a useEffect (fires after commit).
    // act(async) drains all pending effects and microtasks.
    await act(async () => {});

    expect(onOverlaysChange).toHaveBeenCalled();
    // mock.calls is [[arg0, arg1, ...], ...]. Each call is an array of arguments.
    // onOverlaysChange(overlays) has one argument, so calls[n] = [OverlaySeries[]].
    const lastCallArgs = onOverlaysChange.mock.calls[onOverlaysChange.mock.calls.length - 1];
    const overlaysArg = lastCallArgs[0] as OverlaySeries[];
    const ids = overlaysArg.map((o) => o.id);
    expect(ids).toContain("ema-20");
  });

  it("clicking BOLL calls onOverlaysChange with 3 Bollinger overlay series", async () => {
    render(<TAOverlayPanel bars={BARS_250} onOverlaysChange={onOverlaysChange} timeframe="1D" />);

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /Toggle BOLL overlay/i }));
    });
    await act(async () => {});

    const lastCallArgs = onOverlaysChange.mock.calls[onOverlaysChange.mock.calls.length - 1];
    const overlaysArg = lastCallArgs[0] as OverlaySeries[];
    const ids = overlaysArg.map((o) => o.id);
    expect(ids).toContain("boll-upper");
    expect(ids).toContain("boll-mid");
    expect(ids).toContain("boll-lower");
  });

  it("clicking VWAP adds an overlay with strokeWidth 2", async () => {
    render(<TAOverlayPanel bars={BARS_250} onOverlaysChange={onOverlaysChange} timeframe="1D" />);

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /Toggle VWAP overlay/i }));
    });
    await act(async () => {});

    const lastCallArgs = onOverlaysChange.mock.calls[onOverlaysChange.mock.calls.length - 1];
    const overlaysArg = lastCallArgs[0] as OverlaySeries[];
    const vwapOverlay = overlaysArg.find((o) => o.id === "vwap-line");
    expect(vwapOverlay).toBeDefined();
    expect(vwapOverlay?.strokeWidth).toBe(2);
  });

  // ── Toggle off ────────────────────────────────────────────────────────────

  it("clicking an active chip deactivates it (aria-pressed=false)", async () => {
    render(<TAOverlayPanel bars={BARS_250} onOverlaysChange={onOverlaysChange} timeframe="1D" />);

    const btn = screen.getByRole("button", { name: /Toggle EMA 50 overlay/i });

    // First click — activate.
    await act(async () => { fireEvent.click(btn); });
    expect(btn).toHaveAttribute("aria-pressed", "true");

    // Second click — deactivate.
    await act(async () => { fireEvent.click(btn); });
    expect(btn).toHaveAttribute("aria-pressed", "false");
  });

  it("deactivating a chip removes its overlay from onOverlaysChange result", async () => {
    render(<TAOverlayPanel bars={BARS_250} onOverlaysChange={onOverlaysChange} timeframe="1D" />);

    const btn = screen.getByRole("button", { name: /Toggle RSI overlay/i });

    // Activate.
    await act(async () => { fireEvent.click(btn); });
    await act(async () => {});
    const activateArgs = onOverlaysChange.mock.calls[onOverlaysChange.mock.calls.length - 1];
    const afterActivate = activateArgs[0] as OverlaySeries[];
    expect(afterActivate.some((o) => o.id === "rsi-14")).toBe(true);

    // Deactivate.
    await act(async () => { fireEvent.click(btn); });
    await act(async () => {});
    const deactivateArgs = onOverlaysChange.mock.calls[onOverlaysChange.mock.calls.length - 1];
    const afterDeactivate = deactivateArgs[0] as OverlaySeries[];
    expect(afterDeactivate.some((o) => o.id === "rsi-14")).toBe(false);
  });

  it("toggling multiple chips produces multiple overlay series", async () => {
    render(<TAOverlayPanel bars={BARS_250} onOverlaysChange={onOverlaysChange} timeframe="1D" />);

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /Toggle EMA 20 overlay/i }));
    });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /Toggle EMA 50 overlay/i }));
    });
    await act(async () => {});

    const lastCallArgs = onOverlaysChange.mock.calls[onOverlaysChange.mock.calls.length - 1];
    const overlaysArg = lastCallArgs[0] as OverlaySeries[];
    const ids = overlaysArg.map((o) => o.id);
    expect(ids).toContain("ema-20");
    expect(ids).toContain("ema-50");
  });

  // ── Overlay data quality ───────────────────────────────────────────────────

  it("overlay data arrays are the same length as bars", async () => {
    render(<TAOverlayPanel bars={BARS_250} onOverlaysChange={onOverlaysChange} timeframe="1D" />);

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /Toggle EMA 20 overlay/i }));
    });
    await act(async () => {});

    const lastCallArgs = onOverlaysChange.mock.calls[onOverlaysChange.mock.calls.length - 1];
    const overlaysArg = lastCallArgs[0] as OverlaySeries[];
    const ema20 = overlaysArg.find((o) => o.id === "ema-20");
    expect(ema20?.data).toHaveLength(250);
  });

  // ── SENTI chip (PLAN-0091 Wave F-2) ───────────────────────────────────────

  it("SENTI chip renders as disabled (aria-disabled, disabled attr) when entityId is null", () => {
    // WHY null (not omitted): explicitly tests the "instrument has no KG entity" case.
    // undefined is the default (prop not passed), null means "resolved but absent".
    render(
      <TAOverlayPanel
        bars={BARS_250}
        onOverlaysChange={onOverlaysChange}
        entityId={null}
        timeframe="1D"
      />,
    );

    const sentiBtn = screen.getByRole("button", { name: /Toggle SENTI overlay/i });
    // aria-disabled="true" tells screen readers this chip is unavailable.
    expect(sentiBtn).toHaveAttribute("aria-disabled", "true");
    // WHY check HTML disabled: this prevents keyboard activation (Space/Enter)
    // in addition to mouse clicks, giving full inaccessibility for no-entity case.
    expect(sentiBtn).toBeDisabled();
    // Verify it's not accidentally toggled active.
    expect(sentiBtn).toHaveAttribute("aria-pressed", "false");
  });

  it("SENTI chip renders as disabled when entityId is undefined (prop omitted)", () => {
    // WHY separate test for undefined: the prop is optional (entityId?: string | null),
    // so omitting it is a valid call pattern. Both null and undefined must disable.
    render(<TAOverlayPanel bars={BARS_250} onOverlaysChange={onOverlaysChange} timeframe="1D" />);

    const sentiBtn = screen.getByRole("button", { name: /Toggle SENTI overlay/i });
    expect(sentiBtn).toHaveAttribute("aria-disabled", "true");
    expect(sentiBtn).toBeDisabled();
  });

  it("SENTI chip is enabled (not disabled) when entityId is a non-empty string", () => {
    render(
      <TAOverlayPanel
        bars={BARS_250}
        onOverlaysChange={onOverlaysChange}
        entityId="entity-uuid-123"
        timeframe="1D"
      />,
    );

    const sentiBtn = screen.getByRole("button", { name: /Toggle SENTI overlay/i });
    // WHY check both aria-disabled and disabled absence: HTML `disabled` removes
    // the element from tab order and blocks all interaction; aria-disabled without
    // HTML disabled is for custom widgets. Our button uses native disabled, so both
    // must be absent when the chip is available.
    expect(sentiBtn).not.toHaveAttribute("aria-disabled", "true");
    expect(sentiBtn).not.toBeDisabled();
  });

  it("SENTI chip is toggleable when entityId is provided", async () => {
    render(
      <TAOverlayPanel
        bars={BARS_250}
        onOverlaysChange={onOverlaysChange}
        entityId="entity-uuid-123"
        timeframe="1D"
      />,
    );

    const sentiBtn = screen.getByRole("button", { name: /Toggle SENTI overlay/i });
    expect(sentiBtn).toHaveAttribute("aria-pressed", "false");

    await act(async () => { fireEvent.click(sentiBtn); });
    // WHY check aria-pressed=true: the chip should activate on click.
    expect(sentiBtn).toHaveAttribute("aria-pressed", "true");

    // Second click should deactivate it.
    await act(async () => { fireEvent.click(sentiBtn); });
    expect(sentiBtn).toHaveAttribute("aria-pressed", "false");
  });

  it("toggling SENTI with entityId and sentiment data produces id='senti' overlay with axis='right'", async () => {
    // WHY mock with actual data: we want to verify the overlay is built correctly
    // from resolved sentiment data. The mock simulates the hook returning data
    // immediately (as if the cache was warm — no loading state needed).
    //
    // WHY 3 points: enough to verify the alignment logic works; bars below also
    // have 3 entries so the aligned array should have 3 values.
    const ENTITY_ID = "entity-uuid-456";
    mockUseSentimentTimeseries.mockReturnValue({
      data: {
        entity_id: ENTITY_ID,
        days: 90,
        points: [
          { date: "2026-01-01", article_count: 5, avg_relevance: 0.7, positive_ratio: 0.6, negative_ratio: 0.2, avg_impact_score: 0.4 },
          { date: "2026-01-02", article_count: 3, avg_relevance: 0.6, positive_ratio: 0.3, negative_ratio: 0.5, avg_impact_score: 0.2 },
          { date: "2026-01-03", article_count: 8, avg_relevance: 0.8, positive_ratio: 0.5, negative_ratio: 0.3, avg_impact_score: 0.5 },
        ],
      },
    });

    // 3 bars whose timestamps match the 3 sentiment point dates above.
    const THREE_BARS: OHLCVBar[] = [
      { timestamp: "2026-01-01T00:00:00Z", open: 100, high: 105, low: 98, close: 102, volume: 1000 },
      { timestamp: "2026-01-02T00:00:00Z", open: 102, high: 107, low: 100, close: 105, volume: 1200 },
      { timestamp: "2026-01-03T00:00:00Z", open: 105, high: 110, low: 103, close: 108, volume: 900 },
    ];

    render(
      <TAOverlayPanel
        bars={THREE_BARS}
        onOverlaysChange={onOverlaysChange}
        entityId={ENTITY_ID}
        timeframe="1D"
      />,
    );

    const sentiBtn = screen.getByRole("button", { name: /Toggle SENTI overlay/i });
    await act(async () => { fireEvent.click(sentiBtn); });
    await act(async () => {});

    expect(onOverlaysChange).toHaveBeenCalled();
    const lastCallArgs = onOverlaysChange.mock.calls[onOverlaysChange.mock.calls.length - 1];
    const overlaysArg = lastCallArgs[0] as OverlaySeries[];

    const sentiOverlay = overlaysArg.find((o) => o.id === "senti");
    expect(sentiOverlay).toBeDefined();
    // WHY axis="right": sentiment [-1, +1] must not share the price-scale axis;
    // right axis gives it its own domain so it isn't flattened against price.
    expect(sentiOverlay?.axis).toBe("right");
  });

  it("sentiment data is date-aligned: matched bars get net_sentiment, unmatched bars get NaN", async () => {
    // WHY 4 bars but only 2 sentiment points: this is the core alignment contract.
    // Missing dates (bar 3 = "2026-01-03", bar 4 = "2026-01-04") must become NaN.
    const ENTITY_ID = "entity-uuid-789";
    mockUseSentimentTimeseries.mockReturnValue({
      data: {
        entity_id: ENTITY_ID,
        days: 90,
        points: [
          // Only 2 of 4 bar dates have sentiment data.
          { date: "2026-01-01", article_count: 5, avg_relevance: 0.7, positive_ratio: 0.8, negative_ratio: 0.1, avg_impact_score: 0.5 },
          { date: "2026-01-02", article_count: 2, avg_relevance: 0.5, positive_ratio: 0.2, negative_ratio: 0.6, avg_impact_score: 0.1 },
        ],
      },
    });

    // 4 bars: dates 01, 02 have sentiment; 03 and 04 do not.
    const FOUR_BARS: OHLCVBar[] = [
      { timestamp: "2026-01-01T00:00:00Z", open: 100, high: 105, low: 98,  close: 102, volume: 1000 },
      { timestamp: "2026-01-02T00:00:00Z", open: 102, high: 107, low: 100, close: 105, volume: 1200 },
      { timestamp: "2026-01-03T00:00:00Z", open: 105, high: 110, low: 103, close: 108, volume: 900  },
      { timestamp: "2026-01-04T00:00:00Z", open: 108, high: 112, low: 106, close: 110, volume: 800  },
    ];

    render(
      <TAOverlayPanel
        bars={FOUR_BARS}
        onOverlaysChange={onOverlaysChange}
        entityId={ENTITY_ID}
        timeframe="1D"
      />,
    );

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /Toggle SENTI overlay/i }));
    });
    await act(async () => {});

    const lastCallArgs = onOverlaysChange.mock.calls[onOverlaysChange.mock.calls.length - 1];
    const overlaysArg = lastCallArgs[0] as OverlaySeries[];
    const sentiOverlay = overlaysArg.find((o) => o.id === "senti");

    expect(sentiOverlay).toBeDefined();
    // WHY toHaveLength(4): sentimentAligned must be the same length as bars
    // so lightweight-charts can index them positionally.
    expect(sentiOverlay?.data).toHaveLength(4);

    // Bar 0 (2026-01-01): positive_ratio=0.8, negative_ratio=0.1 → net=0.7
    expect(sentiOverlay?.data[0]).toBeCloseTo(0.7);
    // Bar 1 (2026-01-02): positive_ratio=0.2, negative_ratio=0.6 → net=-0.4
    expect(sentiOverlay?.data[1]).toBeCloseTo(-0.4);
    // Bars 2 and 3 (no sentiment): must be NaN so lightweight-charts renders a gap.
    // WHY Number.isNaN (not toBe(NaN)): toBe(NaN) fails because NaN !== NaN in JS.
    expect(Number.isNaN(sentiOverlay?.data[2])).toBe(true);
    expect(Number.isNaN(sentiOverlay?.data[3])).toBe(true);
  });
});
