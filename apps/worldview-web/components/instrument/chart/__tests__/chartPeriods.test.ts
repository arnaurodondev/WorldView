/**
 * components/instrument/chart/__tests__/chartPeriods.test.ts
 *
 * WHY THIS EXISTS (Round-1 Foundation): the period → fetch-params presets are
 * the contract between the chart toolbar and the S9 price-history endpoint.
 * These tests pin two load-bearing invariants:
 *   1. The cache-sharing scheme — 1M/3M/1Y MUST share the daily-bar resolution
 *      and the SAME fetch window so switching among them never refetches
 *      (requirement 5). If a preset edit splits the window, switching periods
 *      silently starts firing extra network calls.
 *   2. The fetch window always covers the visible window — otherwise the
 *      chart would window a range with no data in it (blank canvas class).
 */

import { describe, it, expect } from "vitest";
import {
  CHART_PERIODS,
  CHART_PERIOD_PRESETS,
  DEFAULT_CHART_PERIOD,
  periodStartIso,
} from "@/components/instrument/chart/chartPeriods";

describe("chartPeriods presets", () => {
  it("exposes exactly the 6 required periods in display order", () => {
    expect(CHART_PERIODS).toEqual(["1D", "1W", "1M", "3M", "1Y", "5Y"]);
  });

  it("1M / 3M / 1Y share one daily-bar cache slot (same timeframe + fetch window)", () => {
    const m1 = CHART_PERIOD_PRESETS["1M"];
    const m3 = CHART_PERIOD_PRESETS["3M"];
    const y1 = CHART_PERIOD_PRESETS["1Y"];
    // Same timeframe → same qk.instruments.ohlcv(id, tf) cache key.
    expect(m1.timeframe).toBe("1D");
    expect(m3.timeframe).toBe("1D");
    expect(y1.timeframe).toBe("1D");
    // Same fetch window → identical queryFn params → one shared fetch.
    expect(m1.fetchDaysBack).toBe(m3.fetchDaysBack);
    expect(m3.fetchDaysBack).toBe(y1.fetchDaysBack);
  });

  it("every preset fetches at least as far back as it shows (no empty window)", () => {
    for (const period of CHART_PERIODS) {
      const preset = CHART_PERIOD_PRESETS[period];
      expect(preset.fetchDaysBack).toBeGreaterThanOrEqual(preset.visibleDays);
    }
  });

  it("intraday periods use intraday resolutions", () => {
    expect(CHART_PERIOD_PRESETS["1D"].timeframe).toBe("5M");
    expect(CHART_PERIOD_PRESETS["1W"].timeframe).toBe("1H");
    expect(CHART_PERIOD_PRESETS["5Y"].timeframe).toBe("1W");
  });

  it("periodStartIso returns a UTC date-only string N days back", () => {
    // Fixed clock so the assertion is deterministic.
    const now = new Date("2026-06-10T12:00:00Z");
    // 1D preset fetches 3 days back → 2026-06-07.
    expect(periodStartIso("1D", now)).toBe("2026-06-07");
    // Date-only format (stable query-string within a calendar day).
    expect(periodStartIso("1Y", now)).toMatch(/^\d{4}-\d{2}-\d{2}$/);
  });

  // ── Wave-4 default-view contract (2026-06-12) ──────────────────────────────
  // The default view must load ~500 bars and show ~200. These tests pin the
  // preset values that make that true so a future preset edit can't silently
  // revert to the old sparse 1D/5M default.

  it("DEFAULT_CHART_PERIOD is a daily-bar period (not the sparse 5M intraday default)", () => {
    // The old default ("1D" → 5M) showed only ~10-30 candles. The new default
    // must use the daily resolution so a meaningful price history loads.
    expect(CHART_PERIOD_PRESETS[DEFAULT_CHART_PERIOD].timeframe).toBe("1D");
  });

  it("the default period windows the visible range to ~200 BARS (not days)", () => {
    // visibleBars is the bar-count window the chart applies via
    // setVisibleLogicalRange — the only way to promise an exact opening candle
    // count regardless of how many calendar days those bars span.
    expect(CHART_PERIOD_PRESETS[DEFAULT_CHART_PERIOD].visibleBars).toBe(200);
  });

  it("the daily-bar fetch window is wide enough to load ~500 bars behind the visible window", () => {
    // ~500 trading days needs ~730 calendar days (markets closed ~30% of days).
    // A window narrower than this could never load 500 daily bars, so panning
    // back from the ~200 visible bars would hit the start of the data
    // immediately — the regression this guards against.
    const preset = CHART_PERIOD_PRESETS[DEFAULT_CHART_PERIOD];
    expect(preset.fetchDaysBack).toBeGreaterThanOrEqual(700);
    // The fetch window must exceed the visible bar budget with room to pan.
    // (730 calendar days ≈ 500 trading days ≫ the 200 visible bars.)
    expect(preset.visibleBars).toBeLessThan(preset.fetchDaysBack);
  });

  it("intraday periods do NOT set visibleBars (they window by trading session)", () => {
    // 1D / 1W window by time (one session / one week) — a bar-count window
    // would be wrong there. Only the daily default opts into bar-count windowing.
    expect(CHART_PERIOD_PRESETS["1D"].visibleBars).toBeUndefined();
    expect(CHART_PERIOD_PRESETS["1W"].visibleBars).toBeUndefined();
  });
});
