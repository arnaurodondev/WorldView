/**
 * components/portfolio/__tests__/HoldingInstrumentTxList.test.tsx (F-007)
 *
 * WHY: Pins the three render paths:
 *  1. Shows "No transactions" when no rows match the instrumentId.
 *  2. Renders the correct rows when transactions exist for the instrument.
 *  3. Respects the `limit` prop — shows at most N rows.
 *
 * MOCKED: useAuth, createGateway.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import type { TransactionsResponse } from "@/types/api";

// ── Auth stub ─────────────────────────────────────────────────────────────────
vi.mock("@/hooks/useAuth", () => ({
  useAuth: vi.fn(() => ({
    accessToken: "test-token",
    isAuthenticated: true,
    isLoading: false,
    user: { user_id: "u1", tenant_id: "t1", email: "t@x.com", name: "T", avatar_url: null },
    setTokens: vi.fn(),
    logout: vi.fn(),
  })),
}));

// ── Gateway stub ──────────────────────────────────────────────────────────────
const mockGetTransactions = vi.fn();

const mockGateway = { getTransactions: mockGetTransactions };

vi.mock("@/lib/gateway", () => ({
  createGateway: vi.fn(() => mockGateway),
}));

// WHY also mock api-client: SUT now uses useApiClient() (D1 remediation).
vi.mock("@/lib/api-client", () => ({
  useApiClient: vi.fn(() => mockGateway),
}));

// ── SUT import ────────────────────────────────────────────────────────────────
import { HoldingInstrumentTxList } from "../HoldingInstrumentTxList";

// ── Helpers ───────────────────────────────────────────────────────────────────

function wrap(children: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

/** Minimal transaction factory. */
function makeTx(id: string, instrumentId: string, type: "BUY" | "SELL" | "DIVIDEND") {
  return {
    transaction_id: id,
    portfolio_id: "p-001",
    instrument_id: instrumentId,
    ticker: "AAPL",
    asset_class: "equity" as string | null,
    type,
    quantity: 5,
    price: 150,
    amount: 750 as number | null,
    fee: 1,
    currency: "USD",
    executed_at: "2026-05-01T14:30:00Z",
    notes: null as string | null,
    description: null as string | null | undefined,
  };
}

const TX_RESP: TransactionsResponse = {
  transactions: [
    makeTx("tx-1", "i-001", "BUY"),
    makeTx("tx-2", "i-001", "SELL"),
    makeTx("tx-3", "i-001", "DIVIDEND"),
    makeTx("tx-4", "i-002", "BUY"), // different instrument — should be filtered out
  ],
  total: 4,
  offset: 0,
  limit: 100,
};

// ── Tests ─────────────────────────────────────────────────────────────────────

describe("HoldingInstrumentTxList", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows 'No transactions' when no rows match the instrumentId", async () => {
    // WHY i-NONE: zero matching rows → empty-state branch.
    mockGetTransactions.mockResolvedValue(TX_RESP);

    render(
      wrap(
        <HoldingInstrumentTxList portfolioId="p-001" instrumentId="i-NONE" />,
      ),
    );

    await waitFor(() => {
      expect(screen.getByText("No transactions")).toBeInTheDocument();
    });
  });

  it("renders rows only for the matching instrumentId", async () => {
    mockGetTransactions.mockResolvedValue(TX_RESP);

    render(
      wrap(
        // limit=10 so all 3 matching rows appear.
        <HoldingInstrumentTxList portfolioId="p-001" instrumentId="i-001" limit={10} />,
      ),
    );

    await waitFor(() => {
      // 3 rows match i-001 (BUY, SELL, DIVIDEND). The i-002 row must NOT appear.
      const buyBadges = screen.getAllByText("BUY");
      const sellBadges = screen.getAllByText("SELL");
      const divBadges = screen.getAllByText("DIVIDEND");
      // Combined: exactly 3 type badges.
      expect(buyBadges.length + sellBadges.length + divBadges.length).toBe(3);
    });
  });

  it("respects the limit prop — shows at most N rows", async () => {
    mockGetTransactions.mockResolvedValue(TX_RESP);

    render(
      wrap(
        // limit=1 → only the most-recent transaction should appear.
        <HoldingInstrumentTxList portfolioId="p-001" instrumentId="i-001" limit={1} />,
      ),
    );

    await waitFor(() => {
      // With limit=1, only 1 type badge should be present for i-001.
      const typeBadges = [
        ...screen.queryAllByText("BUY"),
        ...screen.queryAllByText("SELL"),
        ...screen.queryAllByText("DIVIDEND"),
      ];
      expect(typeBadges).toHaveLength(1);
    });
  });

  // ── description subline (F-004 / M-003 + M-004) ──────────────────────────
  //
  // WHY: the populated-description branch had no coverage. M-003 in the QA
  // report flagged that the fixture only exercised description=null. We add
  // both the populated path and the 1000-char truncation guarantee.

  it("renders description subline with truncate + title attribute when present", async () => {
    const respWithDesc: TransactionsResponse = {
      ...TX_RESP,
      transactions: [
        { ...makeTx("tx-d1", "i-001", "DIVIDEND"), description: "Cash Dividend - AAPL" },
      ],
      total: 1,
    };
    mockGetTransactions.mockResolvedValue(respWithDesc);

    render(
      wrap(
        <HoldingInstrumentTxList portfolioId="p-001" instrumentId="i-001" limit={5} />,
      ),
    );

    // The description text appears in the DOM as a subline next to the amount.
    const desc = await screen.findByText("Cash Dividend - AAPL");
    expect(desc).toBeInTheDocument();
    // WHY check class list: the subline must wear the truncate + max-w-[200px]
    // utilities so long broker narratives don't blow out the 440px panel width.
    expect(desc.className).toContain("truncate");
    expect(desc.className).toContain("max-w-[200px]");
    // The title attribute matches the description (used as the hover tooltip
    // when the visible text is clipped by the max-w clamp).
    expect(desc.getAttribute("title")).toBe("Cash Dividend - AAPL");
  });

  it("truncates the title= attribute to 500 chars (defense-in-depth, M-004)", async () => {
    // WHY: server-side Pydantic max_length=500 is the source of truth; the
    // client-side .slice(0, 500) protects against any unexpected backfill row
    // that could otherwise bloat the DOM with a multi-KB title attribute.
    const longDesc = "A".repeat(1000);
    const respLong: TransactionsResponse = {
      ...TX_RESP,
      transactions: [
        { ...makeTx("tx-long", "i-001", "BUY"), description: longDesc },
      ],
      total: 1,
    };
    mockGetTransactions.mockResolvedValue(respLong);

    render(
      wrap(
        <HoldingInstrumentTxList portfolioId="p-001" instrumentId="i-001" limit={5} />,
      ),
    );

    const subline = await screen.findByTitle("A".repeat(500));
    expect(subline).toBeInTheDocument();
  });
});
