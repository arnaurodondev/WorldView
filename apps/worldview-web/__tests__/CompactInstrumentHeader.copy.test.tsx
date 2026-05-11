/**
 * __tests__/CompactInstrumentHeader.copy.test.tsx —
 * click-to-copy ticker (T-F-6-17 / F-I-029) + share/copy-link (T-F-6-21 / F-I-035).
 *
 * Mocks navigator.clipboard.writeText to verify both affordances actually
 * write the expected payload, and that the visual confirm flips to the
 * Check icon. We do NOT cover the description-expand or the LiveQuoteBadge
 * compact mode here — those have their own tests.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, act } from "@testing-library/react";
import { CompactInstrumentHeader } from "@/components/instrument/CompactInstrumentHeader";

// LiveQuoteBadge is rendered by the header; stub it out so we don't have
// to wire a QueryClient for an unrelated child.
vi.mock("@/components/instrument/LiveQuoteBadge", () => ({
  LiveQuoteBadge: () => <span data-testid="live-quote-badge" />,
}));

// 52WeekRangeBar reads no contexts; rendering it is fine. WeekRangeBar
// requires no mocking but we silence its width-warning by stubbing.
vi.mock("@/components/instrument/52WeekRangeBar", () => ({
  WeekRangeBar: () => <span data-testid="week-range-bar" />,
}));

const baseProps = {
  ticker: "AAPL",
  name: "Apple Inc.",
  exchange: "NASDAQ",
  sector: "Technology",
  description: "Designs personal electronics.",
  marketCap: 3_000_000_000,
  peRatio: 28,
  dividendYield: 0.005,
  week52High: 200,
  week52Low: 150,
  price: 193.5,
  change: 2.5,
  changePct: 1.31,
  instrumentId: "i-1",
  onBack: () => {},
};

let writeText: ReturnType<typeof vi.fn>;
beforeEach(() => {
  writeText = vi.fn().mockResolvedValue(undefined);
  Object.defineProperty(navigator, "clipboard", {
    configurable: true,
    value: { writeText },
  });
  // Some tests assert window.location.href; jsdom's default is "about:blank".
  // Override only when needed — the link test sets it explicitly.
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("CompactInstrumentHeader copy affordances", () => {
  it("copies the ticker when the ticker button is clicked", async () => {
    render(<CompactInstrumentHeader {...baseProps} />);
    const btn = screen.getByRole("button", { name: /copy ticker AAPL/i });

    await act(async () => {
      fireEvent.click(btn);
    });

    expect(writeText).toHaveBeenCalledWith("AAPL");
    // After the await, the success state should already have flipped.
    expect(screen.getByRole("button", { name: /copied AAPL/i })).toBeInTheDocument();
  });

  it("copies window.location.href when the share button is clicked", async () => {
    // Override jsdom's location.href so we can assert the value passed in.
    Object.defineProperty(window, "location", {
      configurable: true,
      value: { href: "http://test/instruments/aapl?tab=overview" },
    });

    render(<CompactInstrumentHeader {...baseProps} />);
    const linkBtn = screen.getByRole("button", { name: /copy page link/i });

    await act(async () => {
      fireEvent.click(linkBtn);
    });

    expect(writeText).toHaveBeenCalledWith("http://test/instruments/aapl?tab=overview");
    expect(screen.getByRole("button", { name: /link copied/i })).toBeInTheDocument();
  });
});
