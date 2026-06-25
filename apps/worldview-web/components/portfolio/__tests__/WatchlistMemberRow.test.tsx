/**
 * components/portfolio/__tests__/WatchlistMemberRow.test.tsx
 * (2026-06-10 sprint — watchlist density pass.)
 *
 * WHY: the row gained three surfaces (5-day sparkline, VOL cell, explicit
 * open-instrument affordance) and lost the arbitrary NAME width cap. These
 * tests pin:
 *   1. Sparkline renders from real data; dotted no-data line when absent.
 *   2. Volume renders compact ("45M") and "—" for null (dev feed reality).
 *   3. The ↗ button navigates via onRowClick WITHOUT firing the row click
 *      twice; delete still stops propagation.
 *   4. NAME carries the full name in a tooltip (truncation contract).
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";

import { WatchlistMemberRow } from "../watchlists/WatchlistMemberRow";
import type { WatchlistMember } from "@/types/api";

// ── Fixtures ──────────────────────────────────────────────────────────────────

const MEMBER: WatchlistMember = {
  entity_id: "e-1",
  instrument_id: "i-1",
  ticker: "AAPL",
  name: "Apple Inc. (a deliberately long company name for truncation)",
  added_at: "2026-06-01T00:00:00Z",
  resolution: "resolved",
};

const QUOTE = { price: 185.5, change: 1.5, change_pct: 0.82, volume: 45_000_000 };

function renderRow(
  overrides: Partial<Parameters<typeof WatchlistMemberRow>[0]> = {},
) {
  const onRowClick = vi.fn();
  const onDelete = vi.fn();
  render(
    <table>
      <tbody>
        <WatchlistMemberRow
          member={MEMBER}
          quote={QUOTE}
          sparkline={[180, 182, 181, 184, 185.5]}
          onRowClick={onRowClick}
          onDelete={onDelete}
          isDeleting={false}
          {...overrides}
        />
      </tbody>
    </table>,
  );
  return { onRowClick, onDelete };
}

beforeEach(() => vi.clearAllMocks());

describe("WatchlistMemberRow — density pass", () => {
  it("renders price, day Δ$ and Δ% from the live quote", () => {
    renderRow();
    expect(screen.getByText("$185.50")).toBeInTheDocument();
    expect(screen.getByText("+0.82%")).toBeInTheDocument();
    expect(screen.getByText("+$1.50")).toBeInTheDocument();
  });

  it("renders the 5-day sparkline from real data", () => {
    renderRow();
    expect(
      screen.getByRole("img", { name: /AAPL 5-day trend/i }),
    ).toBeInTheDocument();
  });

  it("renders the dotted no-data sparkline when the series is absent (never blank)", () => {
    renderRow({ sparkline: undefined });
    // The Sparkline primitive renders its dotted <2-point fallback under the
    // SAME aria-label (the row always supplies one) — the cell is never a
    // blank box where data is expected (finance UX rule in the primitive).
    const svg = screen.getByRole("img", { name: /AAPL 5-day trend/i });
    // Dotted fallback = a <line> with strokeDasharray, not a <path> series.
    expect(svg.querySelector("line")).not.toBeNull();
    expect(svg.querySelector("path")).toBeNull();
  });

  it("formats volume compactly and renders '—' for null volume", () => {
    renderRow();
    expect(screen.getByText("45M")).toBeInTheDocument();
  });

  it("renders '—' volume when the quote has no volume (dev feed reality)", () => {
    renderRow({ quote: { ...QUOTE, volume: null } });
    // VOL cell — at least one explicit em-dash for the null figure.
    expect(screen.getAllByText("—").length).toBeGreaterThanOrEqual(1);
  });

  it("↗ button opens the instrument via onRowClick exactly once (stopPropagation)", () => {
    const { onRowClick } = renderRow();
    fireEvent.click(
      screen.getByRole("button", { name: /open AAPL instrument page/i }),
    );
    expect(onRowClick).toHaveBeenCalledTimes(1);
    expect(onRowClick).toHaveBeenCalledWith("i-1");
  });

  it("delete button fires onDelete without navigating", () => {
    const { onRowClick, onDelete } = renderRow();
    fireEvent.click(
      screen.getByRole("button", { name: /remove AAPL from watchlist/i }),
    );
    expect(onDelete).toHaveBeenCalledWith("e-1");
    expect(onRowClick).not.toHaveBeenCalled();
  });

  it("NAME cell carries the FULL name in a tooltip (truncation contract)", () => {
    renderRow();
    const nameCell = screen.getByText(MEMBER.name);
    expect(nameCell).toHaveAttribute("title", MEMBER.name);
    // The arbitrary max-w-[180px] cap is gone — flex sizing only.
    expect(nameCell.className).not.toContain("max-w-[180px]");
  });
});
