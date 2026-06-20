/**
 * components/watchlist/__tests__/WatchlistMemberRows.test.tsx
 *
 * WHY THIS EXISTS: WatchlistMemberRows is the LIVE member grid that replaced the
 * old static (no-price) members table. These tests pin its core behaviours:
 *   - renders one row per mover with ticker / name / live price / day change,
 *   - sorts rows by absolute day-change (most active first),
 *   - shows the alert dot only for members with a pending alert,
 *   - handles null price/change gracefully ("—").
 *
 * It is pure presentation (no query), so we only need to mock next/navigation
 * for the "use client" router dependency.
 */

import { describe, it, expect, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import { WatchlistMemberRows } from "../WatchlistMemberRows";
import type { WatchlistMoverEnriched } from "@/types/api";

// ── Mock navigation — component calls useRouter() for row clicks. ──────────────
vi.mock("next/navigation", () => ({
  useRouter: vi.fn(() => ({
    push: vi.fn(),
    replace: vi.fn(),
    prefetch: vi.fn(),
    back: vi.fn(),
  })),
}));

// ── Fixtures ──────────────────────────────────────────────────────────────────

function mover(over: Partial<WatchlistMoverEnriched>): WatchlistMoverEnriched {
  return {
    instrument_id: "i-1",
    entity_id: "e-1",
    ticker: "AAPL",
    name: "Apple Inc.",
    sector: "Information Technology",
    price: 299.24,
    change_pct: 0.95,
    news_count_24h: 0,
    has_active_alert: false,
    top_news_title: null,
    top_news_url: null,
    ...over,
  };
}

// ── Tests ─────────────────────────────────────────────────────────────────────

describe("WatchlistMemberRows", () => {
  it("renders one data row per mover with ticker, name and price", () => {
    render(
      <WatchlistMemberRows
        movers={[
          mover({ instrument_id: "i-1", ticker: "AAPL", name: "Apple Inc.", price: 299.24 }),
          mover({ instrument_id: "i-2", ticker: "MSFT", name: "Microsoft Corp.", price: 393.83 }),
        ]}
      />,
    );

    expect(screen.getByText("AAPL")).toBeInTheDocument();
    expect(screen.getByText("Apple Inc.")).toBeInTheDocument();
    expect(screen.getByText("MSFT")).toBeInTheDocument();
    // Price is formatted via formatPrice (USD) — assert the numeric substring.
    expect(screen.getByText(/299\.24/)).toBeInTheDocument();
  });

  it("sorts rows by absolute day-change descending (most active first)", () => {
    render(
      <WatchlistMemberRows
        movers={[
          mover({ instrument_id: "i-1", ticker: "AAPL", change_pct: 0.5 }),
          mover({ instrument_id: "i-2", ticker: "MSFT", change_pct: -4.2 }),
          mover({ instrument_id: "i-3", ticker: "GOOGL", change_pct: 2.1 }),
        ]}
      />,
    );

    // Collect tickers in DOM order; the header row has no ticker cell text match
    // for these symbols, so querying by the known tickers is unambiguous.
    const tickers = ["AAPL", "MSFT", "GOOGL"].map((t) => screen.getByText(t));
    // MSFT (|4.2|) > GOOGL (|2.1|) > AAPL (|0.5|).
    const order = tickers
      .sort((a, b) => a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING ? -1 : 1)
      .map((el) => el.textContent);
    expect(order).toEqual(["MSFT", "GOOGL", "AAPL"]);
  });

  it("renders an alert affordance only for members with an active alert", () => {
    render(
      <WatchlistMemberRows
        movers={[
          mover({ instrument_id: "i-1", ticker: "AAPL", has_active_alert: true }),
          mover({ instrument_id: "i-2", ticker: "MSFT", has_active_alert: false }),
        ]}
      />,
    );

    // Exactly one "Active alert" icon should be present (the AAPL row).
    expect(screen.getAllByLabelText("Active alert")).toHaveLength(1);
  });

  it("renders an em-dash for null price and change", () => {
    render(
      <WatchlistMemberRows
        movers={[mover({ instrument_id: "i-1", ticker: "TSLA", price: null, change_pct: null })]}
      />,
    );

    const row = screen.getByText("TSLA").closest('[role="row"]') as HTMLElement;
    // Both the price and day-change cells fall back to "—".
    expect(within(row).getAllByText("—").length).toBeGreaterThanOrEqual(2);
  });
});
