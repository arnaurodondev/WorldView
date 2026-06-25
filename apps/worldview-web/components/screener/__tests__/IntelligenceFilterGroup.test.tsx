/**
 * components/screener/__tests__/IntelligenceFilterGroup.test.tsx
 * (PRD-0089 Wave I-A · Block D · T-IA-12 / IB-L5 update)
 *
 * WHY THIS FILE: IntelligenceFilterGroup ships 7 filter rows. At the IB-L5c
 * baseline ALL 7 rows are live (no badge, enabled inputs) — IB-L5c wired the
 * last 2 calendar rows (upcomingEarnings / upcomingDividend). This file pins
 * that state so a regression that accidentally re-disables a live row cannot
 * ship silently, AND verifies the backendReady override still re-gates rows
 * for incident-rollback scenarios.
 *
 * Test layout:
 *   1. IB-L5c default state — all 7 rows live, 0 badges visible.
 *   2. Full override — all 7 backendReady=true → 0 badges (same as default now).
 *   3. Full override — all 7 backendReady=false → 7 badges.
 *   4. Partial override — re-gate one live row → 1 badge.
 *   5. Live rows — enabled inputs respond to onChange (incl. the 2 calendar rows).
 */

import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import {
  IntelligenceFilterGroup,
  computeRollupStaleHours,
  STALE_ROLLUP_THRESHOLD_MS,
} from "@/components/screener/IntelligenceFilterGroup";
import { DEFAULT_FILTERS } from "@/features/screener/lib/filter-state";

// ── IB-L5 default state ───────────────────────────────────────────────────────

describe("IntelligenceFilterGroup — IB-L5c default state (backendReady omitted)", () => {
  it("shows ZERO BackendPendingBadges (all 7 rows live at the IB-L5c baseline)", () => {
    // WHY 0: IB_L5_DEFAULTS now sets ALL 7 flags to true — IB-L5c wired the last
    // 2 calendar rows (upcomingEarnings + upcomingDividend), so no row is pending.
    render(
      <IntelligenceFilterGroup
        value={DEFAULT_FILTERS}
        onChange={() => {}}
      />,
    );
    // BackendPendingBadge renders with role="status" (see backend-pending-badge.tsx).
    expect(screen.queryAllByRole("status")).toHaveLength(0);
  });

  it("renders enabled number inputs for the 2 calendar rows (upcomingEarnings + upcomingDividend)", () => {
    render(
      <IntelligenceFilterGroup
        value={DEFAULT_FILTERS}
        onChange={() => {}}
      />,
    );
    // The two calendar rows are now live number inputs (no longer disabled text).
    const earningsInput = screen.getByLabelText(/maximum days until next earnings/i);
    const dividendInput = screen.getByLabelText(/maximum days until next dividend/i);
    expect(earningsInput).not.toBeDisabled();
    expect(dividendInput).not.toBeDisabled();
  });

  it("renders enabled number inputs for the 3 live numeric-range rows (newsCount7d, contradictions, llmRelevance)", () => {
    render(
      <IntelligenceFilterGroup
        value={DEFAULT_FILTERS}
        onChange={() => {}}
      />,
    );
    // WHY named aria-labels: each enabled row uses a descriptive label (not
    // the "(backend pending)" suffix). The 3 numeric rows are news, contradictions,
    // and relevance score.
    const newsInput = screen.getByLabelText(/minimum news articles/i);
    const contInput = screen.getByLabelText(/minimum recent contradiction/i);
    const relInput  = screen.getByLabelText(/minimum display relevance/i);
    expect(newsInput).not.toBeDisabled();
    expect(contInput).not.toBeDisabled();
    expect(relInput).not.toBeDisabled();
  });

  it("renders enabled checkboxes for the 2 live boolean rows (aiBrief, activeAlert)", () => {
    render(
      <IntelligenceFilterGroup
        value={DEFAULT_FILTERS}
        onChange={() => {}}
      />,
    );
    const briefCb = screen.getByLabelText(/only instruments with an ai brief/i);
    const alertCb = screen.getByLabelText(/only instruments with an active alert/i);
    expect(briefCb).not.toBeDisabled();
    expect(alertCb).not.toBeDisabled();
  });
});

// ── Full override: all backendReady=true ──────────────────────────────────────

describe("IntelligenceFilterGroup — all backendReady=true (post-L-5 final state)", () => {
  it("hides all 7 BackendPendingBadges", () => {
    render(
      <IntelligenceFilterGroup
        value={DEFAULT_FILTERS}
        onChange={() => {}}
        backendReady={{
          newsCount7d: true,
          aiBrief: true,
          activeAlert: true,
          contradictions: true,
          llmRelevance: true,
          upcomingEarnings: true,
          upcomingDividend: true,
        }}
      />,
    );
    expect(screen.queryAllByRole("status")).toHaveLength(0);
  });
});

// ── Full override: all backendReady=false ─────────────────────────────────────

describe("IntelligenceFilterGroup — all backendReady=false (original Wave I-A baseline)", () => {
  it("shows 7 BackendPendingBadges when all flags are forced false", () => {
    // WHY: test the explicit re-gating path (e.g. incident rollback scenario).
    render(
      <IntelligenceFilterGroup
        value={DEFAULT_FILTERS}
        onChange={() => {}}
        backendReady={{
          newsCount7d: false,
          aiBrief: false,
          activeAlert: false,
          contradictions: false,
          llmRelevance: false,
          upcomingEarnings: false,
          upcomingDividend: false,
        }}
      />,
    );
    expect(screen.getAllByRole("status")).toHaveLength(7);
  });

  it("all inputs are disabled when all flags are forced false", () => {
    render(
      <IntelligenceFilterGroup
        value={DEFAULT_FILTERS}
        onChange={() => {}}
        backendReady={{
          newsCount7d: false,
          aiBrief: false,
          activeAlert: false,
          contradictions: false,
          llmRelevance: false,
          upcomingEarnings: false,
          upcomingDividend: false,
        }}
      />,
    );
    // WHY /filter \(backend pending\)/i: same reason as above — isolates input
    // elements (whose aria-labels include "filter") from badge spans.
    const allPending = screen.getAllByLabelText(/filter \(backend pending\)/i);
    expect(allPending).toHaveLength(7);
    for (const input of allPending) {
      expect(input).toBeDisabled();
    }
  });
});

// ── Partial override ──────────────────────────────────────────────────────────

describe("IntelligenceFilterGroup — partial backendReady override", () => {
  it("re-gating one live row via backendReady shows exactly 1 badge", () => {
    // WHY 1: IB_L5_DEFAULTS now has all 7 rows live; overriding
    // { newsCount7d: false } re-gates exactly one row → exactly one badge.
    render(
      <IntelligenceFilterGroup
        value={DEFAULT_FILTERS}
        onChange={() => {}}
        backendReady={{ newsCount7d: false }}
      />,
    );
    expect(screen.getAllByRole("status")).toHaveLength(1);
  });
});

// ── onChange wiring ───────────────────────────────────────────────────────────

describe("IntelligenceFilterGroup — onChange wiring for live rows", () => {
  it("news count input calls onChange with updated newsCount7dMin", () => {
    const onChange = vi.fn();
    render(
      <IntelligenceFilterGroup
        value={DEFAULT_FILTERS}
        onChange={onChange}
      />,
    );
    const newsInput = screen.getByLabelText(/minimum news articles/i);
    fireEvent.change(newsInput, { target: { value: "3" } });
    // WHY: the component patches a single field and spreads the rest.
    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({ newsCount7dMin: 3 }),
    );
  });

  it("AI Brief checkbox calls onChange with hasAiBrief=true when checked", () => {
    const onChange = vi.fn();
    render(
      <IntelligenceFilterGroup
        value={DEFAULT_FILTERS}
        onChange={onChange}
      />,
    );
    const briefCb = screen.getByLabelText(/only instruments with an ai brief/i);
    fireEvent.click(briefCb);
    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({ hasAiBrief: true }),
    );
  });

  it("Active Alert checkbox calls onChange with hasActiveAlert=true when checked", () => {
    const onChange = vi.fn();
    render(
      <IntelligenceFilterGroup
        value={DEFAULT_FILTERS}
        onChange={onChange}
      />,
    );
    const alertCb = screen.getByLabelText(/only instruments with an active alert/i);
    fireEvent.click(alertCb);
    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({ hasActiveAlert: true }),
    );
  });

  it("LLM relevance input calls onChange with displayRelevance7dMin", () => {
    const onChange = vi.fn();
    render(
      <IntelligenceFilterGroup
        value={DEFAULT_FILTERS}
        onChange={onChange}
      />,
    );
    const relInput = screen.getByLabelText(/minimum display relevance/i);
    fireEvent.change(relInput, { target: { value: "0.7" } });
    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({ displayRelevance7dMin: 0.7 }),
    );
  });

  it("Contradictions input calls onChange with contradictionsMin", () => {
    const onChange = vi.fn();
    render(
      <IntelligenceFilterGroup
        value={DEFAULT_FILTERS}
        onChange={onChange}
      />,
    );
    const contInput = screen.getByLabelText(/minimum recent contradiction/i);
    fireEvent.change(contInput, { target: { value: "2" } });
    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({ contradictionsMin: 2 }),
    );
  });

  it("Upcoming earnings input calls onChange with upcomingEarningsWithinDays (IB-L5c)", () => {
    const onChange = vi.fn();
    render(
      <IntelligenceFilterGroup
        value={DEFAULT_FILTERS}
        onChange={onChange}
      />,
    );
    const earningsInput = screen.getByLabelText(/maximum days until next earnings/i);
    fireEvent.change(earningsInput, { target: { value: "7" } });
    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({ upcomingEarningsWithinDays: 7 }),
    );
  });

  it("Upcoming dividend input calls onChange with upcomingDividendWithinDays (IB-L5c)", () => {
    const onChange = vi.fn();
    render(
      <IntelligenceFilterGroup
        value={DEFAULT_FILTERS}
        onChange={onChange}
      />,
    );
    const dividendInput = screen.getByLabelText(/maximum days until next dividend/i);
    fireEvent.change(dividendInput, { target: { value: "14" } });
    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({ upcomingDividendWithinDays: 14 }),
    );
  });
});

// ── IB-L5 stale-data indicator (T-IB5-04) ─────────────────────────────────────

describe("computeRollupStaleHours — defensive freshness logic", () => {
  const NOW = Date.parse("2026-06-18T12:00:00Z");

  it("returns null for an absent / null / empty timestamp (no-op)", () => {
    expect(computeRollupStaleHours(undefined, NOW)).toBeNull();
    expect(computeRollupStaleHours(null, NOW)).toBeNull();
    expect(computeRollupStaleHours("", NOW)).toBeNull();
  });

  it("returns null for an unparseable timestamp (never crashes)", () => {
    expect(computeRollupStaleHours("not-a-date", NOW)).toBeNull();
  });

  it("returns null when the rollup is fresh (within the 25h threshold)", () => {
    const tenHoursAgo = new Date(NOW - 10 * 60 * 60 * 1000).toISOString();
    expect(computeRollupStaleHours(tenHoursAgo, NOW)).toBeNull();
  });

  it("returns the integer age in hours when stale (past 25h)", () => {
    const thirtyHoursAgo = new Date(NOW - 30 * 60 * 60 * 1000).toISOString();
    expect(computeRollupStaleHours(thirtyHoursAgo, NOW)).toBe(30);
  });

  it("uses 25h as the staleness threshold", () => {
    expect(STALE_ROLLUP_THRESHOLD_MS).toBe(25 * 60 * 60 * 1000);
    // Exactly at the threshold = still fresh (boundary is inclusive of fresh).
    const exactlyAtThreshold = new Date(NOW - STALE_ROLLUP_THRESHOLD_MS).toISOString();
    expect(computeRollupStaleHours(exactlyAtThreshold, NOW)).toBeNull();
  });
});

describe("IntelligenceFilterGroup — stale-data pill rendering", () => {
  it("does NOT render the stale pill when rollupSyncedAt is omitted", () => {
    render(<IntelligenceFilterGroup value={DEFAULT_FILTERS} onChange={() => {}} />);
    // No stale pill text anywhere (all 7 rows live → no badges either).
    expect(screen.queryByText(/stale/i)).toBeNull();
  });

  it("does NOT render the stale pill for a fresh timestamp", () => {
    const oneHourAgo = new Date(Date.now() - 60 * 60 * 1000).toISOString();
    render(
      <IntelligenceFilterGroup
        value={DEFAULT_FILTERS}
        onChange={() => {}}
        rollupSyncedAt={oneHourAgo}
      />,
    );
    expect(screen.queryByText(/stale/i)).toBeNull();
  });

  it("renders the stale pill for a >25h-old timestamp", () => {
    const thirtyHoursAgo = new Date(Date.now() - 30 * 60 * 60 * 1000).toISOString();
    render(
      <IntelligenceFilterGroup
        value={DEFAULT_FILTERS}
        onChange={() => {}}
        rollupSyncedAt={thirtyHoursAgo}
      />,
    );
    expect(screen.getByText(/\d+h stale/i)).toBeInTheDocument();
  });
});
