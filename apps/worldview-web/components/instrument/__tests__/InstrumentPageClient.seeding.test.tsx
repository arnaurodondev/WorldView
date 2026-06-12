/**
 * components/instrument/__tests__/InstrumentPageClient.seeding.test.tsx
 *
 * WHY THIS EXISTS (Wave-2 sidebar fix, 2026-06-10): the Statistics rail's
 * all-dash bug had two halves; this suite pins the seeding half:
 *
 *   1. The bundle's RAW fundamentals leg ({security_id, records:[…]}) must be
 *      TRANSFORMED (transformFundamentalsSections) before being seeded into
 *      qk.instruments.fundamentals — seeding the raw shape verbatim is BP-379
 *      (every consumer reads undefined → "—" for the full 1h staleTime), and
 *      NOT seeding at all left the rail dependent on a token-racing fetch
 *      that could settle into a permanent 401.
 *   2. The snapshot + share-statistics legs continue to seed verbatim (their
 *      endpoint shapes ARE the cache shapes).
 *   3. A null fundamentals leg leaves the cache untouched (the hook's own
 *      fetch remains the fallback path).
 *
 * MOCK STRATEGY: same seams as InstrumentPageClient.states.test.tsx — the
 * bundle hook is mocked, heavy children stubbed; the QueryClient is REAL and
 * captured so we can read what the seeding effect wrote.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

// ── Mocks (must precede component import) ────────────────────────────────────

vi.mock("next/navigation", () => ({
  useRouter: vi.fn(() => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn() })),
  usePathname: vi.fn(() => "/instruments/ent-1"),
  useSearchParams: vi.fn(() => new URLSearchParams()),
}));

const mockBundleHook = vi.hoisted(() => ({
  state: {
    data: undefined as unknown,
    isError: false,
    error: null as unknown,
    refetch: vi.fn(),
  },
}));
vi.mock("@/components/instrument/hooks/useInstrumentBundle", () => ({
  useInstrumentBundle: vi.fn(() => mockBundleHook.state),
}));

// Heavy children stubbed — this suite tests the seeding effect, not them.
vi.mock("@/components/instrument/header/InstrumentHeader", () => ({
  InstrumentHeader: () => <div data-testid="stub-header" />,
}));
vi.mock("@/components/instrument/brief/AiBriefBanner", () => ({
  AiBriefBanner: () => null,
}));
vi.mock("@/components/instrument/tabs/InstrumentTabs", () => ({
  InstrumentTabs: () => <div data-testid="stub-tabs" />,
}));
vi.mock("@/components/instrument/quote/QuoteTab", () => ({
  QuoteTab: () => <div data-testid="stub-quote-tab" />,
}));
vi.mock("@/components/instrument/financials/FinancialsTab", () => ({
  FinancialsTab: () => null,
}));
vi.mock("@/components/instrument/intelligence/IntelligenceTab", () => ({
  IntelligenceTab: () => null,
}));

// eslint-disable-next-line import/first
import { InstrumentPageClient } from "@/components/instrument/InstrumentPageClient";
// eslint-disable-next-line import/first
import { qk } from "@/lib/query/keys";
// eslint-disable-next-line import/first
import type { Fundamentals } from "@/types/api";

// ── Fixtures ─────────────────────────────────────────────────────────────────

/** Raw S3 all-sections leg — the EXACT shape the live bundle carries. */
const RAW_FUNDAMENTALS = {
  security_id: "ins-1",
  records: [
    // A non-singleton section first — the transformer must skip past it.
    { section: "income_statement", data: { totalRevenue: 1 } },
    {
      section: "highlights",
      ingested_at: "2026-06-10T00:00:00Z",
      data: {
        MarketCapitalization: 4_308_095_467_520,
        PERatio: 35.468,
        ReturnOnEquityTTM: 1.4147,
        DividendYield: 0.0036,
      },
    },
    { section: "valuation_ratios", data: { ForwardPE: 32.7869, PriceSalesTTM: 9.543 } },
    { section: "technicals_snapshot", data: { "52WeekHigh": 294.76, "52WeekLow": 192.8731 } },
    { section: "analyst_consensus", data: { StrongBuy: 25, Buy: 6, Hold: 15, Sell: 1, StrongSell: 1, TargetPrice: 303.3762 } },
  ],
};

function makeBundle(overrides: Record<string, unknown> = {}) {
  return {
    instrument_id: "ins-1",
    entity_id: "ent-1",
    overview: null,
    fundamentals: RAW_FUNDAMENTALS,
    fundamentals_snapshot: { instrument_id: "ins-1", eps_ttm: 8.26, beta: 1.086 },
    technicals: null,
    share_statistics: { security_id: "ins-1", records: [] },
    insider: null,
    top_news: null,
    ...overrides,
  };
}

function renderWithClient() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const view = render(
    <QueryClientProvider client={qc}>
      <InstrumentPageClient entityId="ent-1" />
    </QueryClientProvider>,
  );
  return { qc, view };
}

beforeEach(() => {
  mockBundleHook.state = { data: undefined, isError: false, error: null, refetch: vi.fn() };
});

// ── Tests ────────────────────────────────────────────────────────────────────

describe("InstrumentPageClient cache seeding (Wave-2 sidebar fix)", () => {
  it("seeds qk.instruments.fundamentals with the TRANSFORMED flat shape", async () => {
    mockBundleHook.state.data = makeBundle();
    const { qc } = renderWithClient();

    await waitFor(() => {
      const seeded = qc.getQueryData<Fundamentals>(qk.instruments.fundamentals("ins-1"));
      expect(seeded).toBeDefined();
      // FLAT fields — the raw leg has none of these at the top level, so
      // their presence proves the transform ran (BP-379 guard: a raw seed
      // would leave all of these undefined and the rail all-dash).
      expect(seeded!.market_cap).toBe(4_308_095_467_520);
      expect(seeded!.pe_ratio).toBe(35.468);
      expect(seeded!.forward_pe).toBe(32.7869);
      expect(seeded!.week_52_high).toBe(294.76);
      expect(seeded!.analyst_target_price).toBe(303.3762);
      expect(seeded!.analyst_strong_buy_count).toBe(25);
      // And the raw envelope must NOT be what landed in the cache.
      expect((seeded as unknown as Record<string, unknown>).records).toBeUndefined();
    });
  });

  it("seeds snapshot + share-statistics verbatim (endpoint shape = cache shape)", async () => {
    mockBundleHook.state.data = makeBundle();
    const { qc } = renderWithClient();

    await waitFor(() => {
      expect(qc.getQueryData(qk.instruments.fundamentalsSnapshot("ins-1"))).toMatchObject({
        eps_ttm: 8.26,
        beta: 1.086,
      });
      expect(qc.getQueryData(qk.instruments.shareStatistics("ins-1"))).toMatchObject({
        security_id: "ins-1",
      });
    });
  });

  it("leaves the fundamentals cache untouched when the bundle leg is null", async () => {
    mockBundleHook.state.data = makeBundle({ fundamentals: null });
    const { qc } = renderWithClient();

    // The OTHER seeds still run — wait for one of them, then assert the
    // fundamentals key stayed empty (the hook's own fetch is the fallback).
    await waitFor(() => {
      expect(qc.getQueryData(qk.instruments.fundamentalsSnapshot("ins-1"))).toBeDefined();
    });
    expect(qc.getQueryData(qk.instruments.fundamentals("ins-1"))).toBeUndefined();
  });
});
