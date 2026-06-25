/**
 * PeerComparisonTable.test.tsx — peer relative-value panel contracts
 * (Wave-2 redesign, scope item 4; the OLD table shipped with no test —
 * this suite is net-new coverage).
 *
 * CONTRACTS:
 *   1. Self row renders FIRST, highlighted, with live LAST / DAY % from the
 *      page quote and the ◆ subject marker.
 *   2. All 8 peers from the Wave-1 endpoint render with their LAST / DAY % /
 *      MKT CAP / P/E / 1Y RET cells (nullable fields → "—").
 *   3. Clicking a peer row navigates to /instruments/{ticker}; clicking the
 *      self row does NOT navigate.
 *   4. Day % is colour-coded (already-percent input); 1Y RET is decimal
 *      input (0.57 → "+57.02%").
 *   5. The shared industry renders once in the header meta (not per row).
 *   6. Loading → shape-matched skeleton; no data at all → named empty text.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";

import type { Fundamentals, Quote } from "@/types/api";
import type { PeersV2Response } from "@/components/instrument/financials/usePeers";

// ── Mocks ────────────────────────────────────────────────────────────────────

const mockPush = vi.hoisted(() => vi.fn());
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: mockPush }),
}));

const mockPeersQuery = vi.hoisted(() => ({
  state: {
    data: undefined as PeersV2Response | undefined,
    isLoading: false,
  },
}));

// Mock the hook seam (not apiFetch): the table's contract is "render what
// usePeers returns" — the fetcher itself is a 4-line apiFetch wrapper.
vi.mock("@/components/instrument/financials/usePeers", async (importOriginal) => {
  const actual =
    await importOriginal<typeof import("@/components/instrument/financials/usePeers")>();
  return { ...actual, usePeers: () => mockPeersQuery.state };
});

// eslint-disable-next-line import/first
import { PeerComparisonTable } from "@/components/instrument/financials/PeerComparisonTable";

// ── Fixtures ─────────────────────────────────────────────────────────────────

const FUNDAMENTALS = {
  instrument_id: "i-self",
  ticker: "AAPL",
  name: "Apple Inc",
  market_cap: 3.2e12,
  pe_ratio: 28.4,
} as unknown as Fundamentals;

const QUOTE = {
  instrument_id: "i-self",
  ticker: "AAPL",
  price: 213.55,
  change: 1.2,
  change_pct: 0.56,
  timestamp: "2026-06-10T15:00:00Z",
  volume: 1000,
} as Quote;

/** 8 peers mirroring the live Wave-1 response (NVDA has full data; the rest
 *  exercise the nullable return_1y / change_pct / last_price fields). */
function eightPeers(): PeersV2Response {
  const bare = (ticker: string, i: number) => ({
    instrument_id: `i-${ticker}`,
    ticker,
    name: `${ticker} Corp`,
    market_cap: (8 - i) * 1e11,
    pe_ratio: 20 + i,
    return_1y: null,
    change_pct: null,
    last_price: null,
  });
  return {
    instrument_id: "i-self",
    industry: "Technology",
    peers: [
      {
        instrument_id: "i-NVDA",
        ticker: "NVDA",
        name: "NVIDIA Corporation",
        market_cap: 5.05e12,
        pe_ratio: 31.9,
        return_1y: 0.570155,
        change_pct: 1.61,
        last_price: 222.82,
      },
      ...["MSFT", "TSM", "AVGO", "MU", "AMD", "ASML"].map(bare),
      bare("ORCL", 7),
    ],
  };
}

beforeEach(() => {
  mockPush.mockReset();
  mockPeersQuery.state = { data: eightPeers(), isLoading: false };
});

function renderTable() {
  return render(
    <PeerComparisonTable fundamentals={FUNDAMENTALS} quote={QUOTE} instrumentId="i-self" />,
  );
}

// ── Tests ────────────────────────────────────────────────────────────────────

describe("PeerComparisonTable (Wave-2)", () => {
  it("renders the self row first, highlighted, with live LAST / DAY %", () => {
    renderTable();
    const selfRow = screen.getByTestId("peer-row-AAPL");
    expect(selfRow.className).toContain("bg-muted/30");
    expect(selfRow).toHaveTextContent("◆");
    // Live quote values on the subject row (the old table rendered "—").
    expect(selfRow).toHaveTextContent("$213.55");
    expect(selfRow).toHaveTextContent("+0.56%");
    // First data row in the document order is the self row.
    const rows = screen.getAllByRole("row").filter((r) => r.dataset.testid?.startsWith("peer-row"));
    expect(rows[0]).toBe(selfRow);
  });

  it("renders all 8 peers with the upgraded columns", () => {
    renderTable();
    for (const t of ["NVDA", "MSFT", "TSM", "AVGO", "MU", "AMD", "ASML", "ORCL"]) {
      expect(screen.getByTestId(`peer-row-${t}`)).toBeInTheDocument();
    }
    const nvda = screen.getByTestId("peer-row-NVDA");
    expect(nvda).toHaveTextContent("$222.82"); // LAST
    expect(nvda).toHaveTextContent("+1.61%"); // DAY % (already-percent input)
    expect(nvda).toHaveTextContent("+57.02%"); // 1Y RET (decimal input ×100)
    expect(nvda).toHaveTextContent("31.9"); // P/E
  });

  it("renders em-dashes for peers without OHLCV coverage (nullable fields)", () => {
    renderTable();
    // TSM has null last/day%/1y → its row carries dashes, not zeros.
    expect(screen.getByTestId("peer-row-TSM")).toHaveTextContent("—");
  });

  it("navigates on peer row click but never on the self row", () => {
    renderTable();
    fireEvent.click(screen.getByTestId("peer-row-NVDA"));
    expect(mockPush).toHaveBeenCalledWith("/instruments/NVDA");
    mockPush.mockReset();
    fireEvent.click(screen.getByTestId("peer-row-AAPL"));
    expect(mockPush).not.toHaveBeenCalled();
  });

  it("supports keyboard navigation (Enter on a focused peer row)", () => {
    renderTable();
    fireEvent.keyDown(screen.getByTestId("peer-row-MSFT"), { key: "Enter" });
    expect(mockPush).toHaveBeenCalledWith("/instruments/MSFT");
  });

  it("renders the shared industry once in the header meta (not a per-row column)", () => {
    renderTable();
    expect(screen.getByText(/Technology · by market cap/)).toBeInTheDocument();
    // SECTOR is no longer a column.
    expect(screen.queryByText("SECTOR")).not.toBeInTheDocument();
  });

  it("renders the row-count footer", () => {
    renderTable();
    expect(screen.getByText(/8 peers · click row to navigate/)).toBeInTheDocument();
  });

  it("shows a shape-matched skeleton while loading", () => {
    mockPeersQuery.state = { data: undefined, isLoading: true };
    renderTable();
    expect(screen.getByRole("status", { name: /loading peer comparison/i })).toBeInTheDocument();
  });

  it("shows the named empty text when there are no rows at all", () => {
    mockPeersQuery.state = { data: undefined, isLoading: false };
    render(<PeerComparisonTable fundamentals={null} quote={null} instrumentId="i-self" />);
    expect(screen.getByText("No peer data available")).toBeInTheDocument();
  });

  // ── Wave-4 interactivity: click-to-sort peer columns ────────────────────────

  /** Peer tickers in DOM (row) order, EXCLUDING the pinned self row. */
  function peerTickerOrder(): string[] {
    return screen
      .getAllByRole("row")
      .map((r) => r.dataset.testid)
      .filter((id): id is string => !!id && id.startsWith("peer-row-") && id !== "peer-row-AAPL")
      .map((id) => id.replace("peer-row-", ""));
  }

  it("keeps the subject (AAPL) pinned first even after sorting", () => {
    renderTable();
    // Sort by P/E ascending (MSFT has the lowest P/E among peers at 20).
    const peHeader = screen.getByRole("button", { name: /p\/e/i });
    fireEvent.click(peHeader); // numeric default = desc
    fireEvent.click(peHeader); // → asc
    // Self row is still the FIRST data row regardless of sort.
    const allRows = screen
      .getAllByRole("row")
      .filter((r) => r.dataset.testid?.startsWith("peer-row"));
    expect(allRows[0]).toBe(screen.getByTestId("peer-row-AAPL"));
  });

  it("re-ranks the peers by P/E ascending on a header click", () => {
    renderTable();
    const peHeader = screen.getByRole("button", { name: /p\/e/i });
    fireEvent.click(peHeader); // desc
    fireEvent.click(peHeader); // asc → MSFT(20) first among peers
    expect(peerTickerOrder()[0]).toBe("MSFT");
  });

  it("re-ranks the peers by 1Y return descending (NVDA leads, nulls last)", () => {
    renderTable();
    // Only NVDA has a non-null return_1y; everyone else is null → bottom.
    fireEvent.click(screen.getByRole("button", { name: /1y ret/i }));
    expect(peerTickerOrder()[0]).toBe("NVDA");
  });
});
