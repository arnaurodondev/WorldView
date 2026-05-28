/**
 * components/portfolio/__tests__/HoldingLotsPanel.test.tsx (PRD-0089 Wave G SA-A)
 *
 * WHY: pins the narrow variant column-set contract. The wide variant exposes
 * a "DAYS" column; the narrow variant intentionally hides it to fit inside
 * the Holding Detail slide-over (≈360px wide). If a future refactor accidentally
 * brings the column back in narrow mode, this test fails — preventing silent
 * layout overflow in the side-panel consumer (HoldingDetailPanel).
 *
 * MOCKED: useAuth, createGateway (we only assert header columns, not data
 * rows, so a single deterministic API response is enough).
 */

import { describe, it, expect, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import type { Holding, BatchQuoteResponse } from "@/types/api";

// ── Auth stub ─────────────────────────────────────────────────────────────────
// WHY identical shape to the other __tests__ in this folder: HoldingLotsPanel
// reads accessToken from useAuth and gates the query on its presence.
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
// WHY return a single lot: we want a deterministic render so we can scan the
// header row for the presence/absence of "DAYS" — not to assert per-row content.
const mockGetHoldingLots = vi.fn(async () => ({
  portfolio_id: "p-001",
  instrument_id: "i-aapl",
  lots: [
    {
      open_date: "2024-01-15",
      qty: 10,
      cost_per_share: 150,
      days_held: 300,
      is_long_term: true,
      unrealised_pnl: 500,
    },
  ],
  short_term_qty: 0,
  long_term_qty: 10,
  total_cost: 1500,
}));

vi.mock("@/lib/gateway", () => ({
  createGateway: vi.fn(() => ({
    getHoldingLots: mockGetHoldingLots,
  })),
}));

// ── SUT import ────────────────────────────────────────────────────────────────
import { HoldingLotsPanel } from "../HoldingLotsPanel";

// ── Helpers ───────────────────────────────────────────────────────────────────

function wrap(children: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

const HOLDING: Holding = {
  holding_id: "h-1",
  portfolio_id: "p-001",
  instrument_id: "i-aapl",
  entity_id: "e-aapl",
  ticker: "AAPL",
  name: "Apple Inc.",
  quantity: 10,
  average_cost: 150,
};

// BatchQuoteResponse["quotes"] is a Record<instrumentId, Quote>. Casting to the
// indexable shape keeps the test concise without dragging in the full Quote type.
const QUOTES = {
  "i-aapl": { price: 200 },
} as unknown as BatchQuoteResponse["quotes"];

// ── Tests ─────────────────────────────────────────────────────────────────────

describe("HoldingLotsPanel narrow variant", () => {
  it("hides the Days Held column when variant='narrow'", async () => {
    render(
      wrap(
        <HoldingLotsPanel
          portfolioId="p-001"
          holdings={[HOLDING]}
          quotes={QUOTES}
          variant="narrow"
        />,
      ),
    );

    // WHY waitFor: the lots fetch is async — the header columns only render
    // once data lands (the loading branch shows skeletons, not headers).
    await waitFor(() => {
      // OPEN DATE is always present — confirms the data-loaded branch rendered.
      expect(screen.getByText("OPEN DATE")).toBeInTheDocument();
    });

    // WHY assert absence: the "DAYS" header is the canonical signal for the
    // wide-variant Days Held column. In narrow mode it must not be in the DOM
    // — querying confirms layout intent at the column level.
    expect(screen.queryByText("DAYS")).not.toBeInTheDocument();
  });

  it("shows the Days Held column in default (wide) variant", async () => {
    render(
      wrap(
        <HoldingLotsPanel
          portfolioId="p-001"
          holdings={[HOLDING]}
          quotes={QUOTES}
        />,
      ),
    );

    // WHY check both columns: pins that the wide variant is the default
    // (regression guard if someone flips the default to "narrow").
    await waitFor(() => {
      expect(screen.getByText("OPEN DATE")).toBeInTheDocument();
      expect(screen.getByText("DAYS")).toBeInTheDocument();
    });
  });
});
