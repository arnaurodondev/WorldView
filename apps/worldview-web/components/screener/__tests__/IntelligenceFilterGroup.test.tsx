/**
 * components/screener/__tests__/IntelligenceFilterGroup.test.tsx
 * (PRD-0089 Wave I-A · Block D · T-IA-12 / IB-L5 update)
 *
 * WHY THIS FILE: IntelligenceFilterGroup ships 7 filter rows. In the IB-L5
 * baseline 5 rows are live (no badge, enabled inputs) and 2 remain backend-
 * pending (badge, disabled input). This file pins both states so a regression
 * that accidentally re-disables a live row (or enables a pending one) cannot
 * ship silently.
 *
 * Test layout:
 *   1. IB-L5 default state — 5 live rows, 2 pending, 2 badges visible.
 *   2. Full override — all 7 backendReady=true → 0 badges.
 *   3. Full override — all 7 backendReady=false → 7 badges.
 *   4. Partial override — re-gate one live row → back to 3 badges.
 *   5. Live rows — enabled inputs respond to onChange.
 *   6. Pending rows — inputs are disabled.
 */

import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { IntelligenceFilterGroup } from "@/components/screener/IntelligenceFilterGroup";
import { DEFAULT_FILTERS } from "@/features/screener/lib/filter-state";

// ── IB-L5 default state ───────────────────────────────────────────────────────

describe("IntelligenceFilterGroup — IB-L5 default state (backendReady omitted)", () => {
  it("shows exactly 2 BackendPendingBadges (upcomingEarnings + upcomingDividend)", () => {
    // WHY 2: IB_L5_DEFAULTS sets newsCount7d/aiBrief/activeAlert/contradictions/
    // llmRelevance to true; only upcomingEarnings and upcomingDividend remain false.
    render(
      <IntelligenceFilterGroup
        value={DEFAULT_FILTERS}
        onChange={() => {}}
      />,
    );
    // BackendPendingBadge renders with role="status" (see backend-pending-badge.tsx).
    expect(screen.getAllByRole("status")).toHaveLength(2);
  });

  it("renders 2 disabled text inputs for the 2 pending rows", () => {
    render(
      <IntelligenceFilterGroup
        value={DEFAULT_FILTERS}
        onChange={() => {}}
      />,
    );
    // WHY /filter \(backend pending\)/i (not /backend pending/i): the
    // BackendPendingBadge itself also carries aria-label="Backend pending".
    // Using the input-specific pattern (which includes the word "filter")
    // isolates just the <input> elements without picking up the badge spans.
    const pendingInputs = screen.getAllByLabelText(/filter \(backend pending\)/i);
    expect(pendingInputs).toHaveLength(2);
    for (const input of pendingInputs) {
      expect(input).toBeDisabled();
    }
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
  it("re-gating one live row via backendReady adds 1 badge (total 3)", () => {
    // WHY: verifies the merge logic — IB_L5_DEFAULTS has 5 live rows;
    // overriding { newsCount7d: false } should give 3 badges (2 defaults + 1 re-gated).
    render(
      <IntelligenceFilterGroup
        value={DEFAULT_FILTERS}
        onChange={() => {}}
        backendReady={{ newsCount7d: false }}
      />,
    );
    expect(screen.getAllByRole("status")).toHaveLength(3);
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
});
