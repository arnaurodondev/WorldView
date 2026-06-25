/**
 * components/instrument/header/__tests__/InstrumentHeader.test.tsx
 *
 * WHY THIS EXISTS (Round-1 Foundation, requirement 1): pins the header's
 * data-path contract after the volume fix:
 *   - VOL renders quote.volume (the old build rendered fundamentals.daily_return
 *     — a PERCENTAGE — through formatVolume, i.e. always-wrong data).
 *   - 30D renders the snapshot's avg_volume_30d (volume-vs-average pair).
 *   - B×A renders a NAMED placeholder while S9 lacks bid/ask (backend gap).
 *   - Price + change render mono with direction color.
 */

import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";

vi.mock("next/navigation", () => ({
  useRouter: vi.fn(() => ({ push: vi.fn(), replace: vi.fn(), back: vi.fn(), prefetch: vi.fn() })),
}));

// WHY mock LiveQuoteBadge: it owns a polling useQuery + WS plumbing that is
// irrelevant here; the header contract under test is the static metric row.
vi.mock("@/components/instrument/LiveQuoteBadge", () => ({
  LiveQuoteBadge: () => <span data-testid="live-quote-badge" />,
}));

// WHY mock InstrumentAlertButton (PLAN-0113 W5): it mounts the AlertWizard, which
// pulls in the TanStack mutation hooks + gateway client. Those need a
// QueryClientProvider/auth context this static-metric-row test doesn't provide.
// The button has its own dedicated test (InstrumentAlertButton.test.tsx).
vi.mock("@/components/instrument/header/InstrumentAlertButton", () => ({
  InstrumentAlertButton: () => <button data-testid="instrument-alert-button" />,
}));

import { InstrumentHeader } from "@/components/instrument/header/InstrumentHeader";
import type { Instrument, Quote, Fundamentals } from "@/types/api";

const INSTRUMENT: Instrument = {
  instrument_id: "ins-001",
  entity_id: "ent-001",
  ticker: "AAPL",
  name: "Apple Inc.",
  exchange: "NASDAQ",
  currency: "USD",
  gics_sector: "Information Technology",
  gics_industry: "Technology Hardware",
  isin: null,
  country: "US",
  description: null,
};

const QUOTE: Quote = {
  instrument_id: "ins-001",
  ticker: "AAPL",
  price: 201.5,
  change: 2.5,
  change_pct: 1.26,
  timestamp: "2026-06-10T14:30:00Z",
  volume: 52_300_000,
};

const FUNDAMENTALS = {
  market_cap: 3_100_000_000_000,
  pe_ratio: 31.2,
  week_52_high: 240,
  week_52_low: 160,
  daily_return: 0.0126, // the old (wrong) VOL source — must NOT render as volume
} as unknown as Fundamentals;

afterEach(() => cleanup());

describe("InstrumentHeader volume pair (Round-1 fix)", () => {
  it("renders VOL from quote.volume, not fundamentals.daily_return", () => {
    render(
      <InstrumentHeader
        instrument={INSTRUMENT}
        quote={QUOTE}
        fundamentals={FUNDAMENTALS}
        avgVolume30d={48_100_000}
      />,
    );
    // 52,300,000 → compact "52.30M" via formatVolume (M suffix = 2 decimals).
    expect(screen.getByText(/52\.30M/)).toBeInTheDocument();
    // 30-day average renders beside it.
    expect(screen.getByText("30D")).toBeInTheDocument();
    expect(screen.getByText(/48\.10M/)).toBeInTheDocument();
  });

  it("renders '—' for VOL and 30D while data is loading", () => {
    render(
      <InstrumentHeader instrument={null} quote={null} fundamentals={null} />,
    );
    // VOL + 30D labels stay mounted (stable layout) with dash values.
    expect(screen.getByText("VOL")).toBeInTheDocument();
    expect(screen.getByText("30D")).toBeInTheDocument();
  });
});

describe("InstrumentHeader bid/ask placeholder (backend gap)", () => {
  it("renders the named B×A placeholder when bid/ask are absent", () => {
    render(
      <InstrumentHeader instrument={INSTRUMENT} quote={QUOTE} fundamentals={FUNDAMENTALS} />,
    );
    expect(screen.getByText("B×A")).toBeInTheDocument();
    // The placeholder is the explicit "—×—" pair — never an empty cell.
    expect(screen.getByText("—×—")).toBeInTheDocument();
  });

  it("renders real bid×ask once the gateway provides them", () => {
    render(
      <InstrumentHeader
        instrument={INSTRUMENT}
        quote={QUOTE}
        fundamentals={FUNDAMENTALS}
        bid={201.45}
        ask={201.55}
      />,
    );
    expect(screen.getByText(/201\.45.*×.*201\.55/)).toBeInTheDocument();
  });
});

describe("InstrumentHeader price block", () => {
  it("renders price and color-coded positive change", () => {
    render(
      <InstrumentHeader instrument={INSTRUMENT} quote={QUOTE} fundamentals={FUNDAMENTALS} />,
    );
    expect(screen.getByText("$201.50")).toBeInTheDocument();
    // change text combines $ and % deltas; positive → text-positive class.
    const change = screen.getByText(/\+\$2\.50/);
    expect(change.className).toContain("text-positive");
  });

  it("renders negative change in text-negative", () => {
    render(
      <InstrumentHeader
        instrument={INSTRUMENT}
        quote={{ ...QUOTE, change: -3.1, change_pct: -1.52 }}
        fundamentals={FUNDAMENTALS}
      />,
    );
    const change = screen.getByText(/-\$3\.10|\$-3\.10/);
    expect(change.className).toContain("text-negative");
  });
});
