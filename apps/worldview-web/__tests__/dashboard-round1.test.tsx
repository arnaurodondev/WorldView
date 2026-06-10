/**
 * __tests__/dashboard-round1.test.tsx — Round 1 foundation regression coverage
 *
 * WHY THIS EXISTS: Round 1 (2026-06-10) shipped four data-path fixes on the
 * dashboard surface. Each gets pinned here with tailored mocks (the shared
 * mocks in dashboard.test.tsx return generic fixtures that can't exercise
 * the new behaviours):
 *
 *   1. MarketSnapshotWidget — the INDICES group now contains the 4 core index
 *      proxies (SPY/QQQ/IWM/VIX) and each row renders price, day-change $,
 *      and a color-coded directional arrow + %.
 *   2. SectorHeatmapWidget — tile color intensity is PROPORTIONAL to the
 *      current payload's max |change| (not fixed ±0.5/1/2% thresholds), and
 *      tiles carry a hover tooltip (sector · % · top mover when available).
 *   3. TopMovers — Gainers/Losers shadcn Tabs; rows show ticker · name ·
 *      5-day sparkline · price · %chg; row click navigates ticker-first.
 *
 * WHY MOCK THE GATEWAY PER-SCENARIO: deterministic payloads let us assert
 * exact color buckets / tooltip strings / sparkline labels.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

// ── Next.js router mock ───────────────────────────────────────────────────────
// WHY vi.hoisted: vi.mock factories are hoisted above imports/consts — the
// shared push spy must be created in the hoisted scope so both the factory
// and the test assertions reference the SAME function instance.
const { pushMock } = vi.hoisted(() => ({ pushMock: vi.fn() }));
vi.mock("next/navigation", () => ({
  useRouter: vi.fn(() => ({ push: pushMock, replace: vi.fn(), prefetch: vi.fn() })),
  usePathname: vi.fn(() => "/dashboard"),
  useSearchParams: vi.fn(() => new URLSearchParams()),
}));

// ── Auth mock ─────────────────────────────────────────────────────────────────
vi.mock("@/hooks/useAuth", () => ({
  useAuth: vi.fn(() => ({
    accessToken: "test-token",
    isAuthenticated: true,
    isLoading: false,
    user: { user_id: "u1", tenant_id: "t1", email: "a@b.com", name: "A", avatar_url: null },
    setTokens: vi.fn(),
    logout: vi.fn(),
  })),
}));

// ── Gateway mock ──────────────────────────────────────────────────────────────
// Fixture design:
//   - TopMovers: gainers = NVDA (+5.20%, no price on the movers feed — price
//     must come from the overview batch), losers = TSLA (-3.10%, id NOT in the
//     overview batch → price renders "—").
//   - Heatmap: IT +2.00 (the max → /40), Staples +0.40 (ratio 0.2 → /10),
//     Energy -1.00 (ratio 0.5 → /30), Utilities null (muted).
//   - Snapshot: every ticker resolves; overview quote is positive
//     (price 185.50, change +2.30, +1.25%) so arrows render "▲".
vi.mock("@/lib/gateway", () => ({
  createGateway: vi.fn(() => ({
    getTopMovers: vi.fn().mockImplementation((type: "gainers" | "losers") =>
      Promise.resolve(
        type === "gainers"
          ? {
              movers: [
                {
                  instrument_id: "ins-1",
                  ticker: "NVDA",
                  name: "NVIDIA Corp",
                  price: 0, // movers feed carries no price (S3 period-movers)
                  change_pct: 5.2,
                  volume: null,
                },
              ],
              type: "gainers" as const,
            }
          : {
              movers: [
                {
                  instrument_id: "ins-2",
                  ticker: "TSLA",
                  name: "Tesla Inc",
                  price: 0,
                  change_pct: -3.1,
                  volume: null,
                },
              ],
              type: "losers" as const,
            },
      ),
    ),
    // Overview batch: only ins-1 present — exercises both the price patch
    // (NVDA → $850.00) and the "—" fallback (TSLA absent).
    getCompanyOverviewsBatch: vi.fn().mockResolvedValue({
      "ins-1": {
        instrument: {
          instrument_id: "ins-1",
          entity_id: "ins-1",
          ticker: "NVDA",
          name: "NVIDIA Corp",
          gics_sector: "Information Technology",
        },
        quote: { price: 850.0, change: 42.0, change_pct: 5.2 },
      },
    }),
    // 5-day close series — oldest-first, 5 points.
    getMarketSparklines: vi.fn().mockResolvedValue({
      "ins-1": [800, 812, 805, 830, 850],
    }),
    getMarketHeatmap: vi.fn().mockResolvedValue({
      sectors: [
        { name: "Information Technology", change_pct: 2.0, instrument_count: 67 },
        { name: "Consumer Staples", change_pct: 0.4, instrument_count: 38 },
        { name: "Energy", change_pct: -1.0, instrument_count: 23 },
        { name: "Utilities", change_pct: null, instrument_count: 30 },
      ],
    }),
    // MarketSnapshotWidget step 1: ticker → instrument_id map.
    resolveTickersBatch: vi.fn().mockImplementation((tickers: string[]) =>
      Promise.resolve(
        Object.fromEntries(tickers.map((t) => [t, `ins-${t.toLowerCase()}`])),
      ),
    ),
    // MarketSnapshotWidget step 2: per-instrument overview with a POSITIVE quote
    // so every row shows "▲ +1.25%" and "+2.30".
    getCompanyOverview: vi.fn().mockResolvedValue({
      instrument: {
        instrument_id: "ins-x",
        entity_id: "ins-x",
        ticker: "X",
        name: "X Inc",
        gics_sector: "Information Technology",
      },
      quote: { price: 185.5, change: 2.3, change_pct: 1.25 },
    }),
    refreshToken: vi.fn().mockResolvedValue({
      access_token: "tok",
      user: { user_id: "u1", tenant_id: "t1", email: "a@b.com", name: "A", avatar_url: null },
      expires_in: 900,
    }),
    logout: vi.fn(),
  })),
  GatewayError: class GatewayError extends Error {
    status: number;
    constructor(status: number, msg: string) { super(msg); this.status = status; }
  },
}));

// ── Component imports (after vi.mock) ─────────────────────────────────────────
import { TopMovers } from "@/components/dashboard/TopMovers";
import { SectorHeatmapWidget } from "@/components/dashboard/SectorHeatmapWidget";
import { MarketSnapshotWidget } from "@/components/dashboard/MarketSnapshotWidget";

// ── Wrapper ───────────────────────────────────────────────────────────────────
function wrapper({ children }: { children: ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

beforeEach(() => {
  pushMock.mockClear();
});

// ── 1. MarketSnapshotWidget — 4 core indices + arrow + change $ ──────────────

describe("MarketSnapshotWidget — Round 1 index strip", () => {
  it("renders all 4 core index tickers (SPY/QQQ/IWM/VIX)", async () => {
    render(<MarketSnapshotWidget />, { wrapper });
    await waitFor(() => {
      expect(screen.getByText("SPY")).toBeInTheDocument();
    });
    expect(screen.getByText("QQQ")).toBeInTheDocument();
    expect(screen.getByText("IWM")).toBeInTheDocument();
    expect(screen.getByText("VIX")).toBeInTheDocument();
  });

  it("renders day-change $ and a directional arrow with the % change", async () => {
    render(<MarketSnapshotWidget />, { wrapper });
    // The mock quote is +2.30 / +1.25% for every resolved row — at least one
    // row must show the signed dollar change and the up-arrow form.
    await waitFor(() => {
      expect(screen.getAllByText("+2.30").length).toBeGreaterThan(0);
    });
    const arrows = screen.getAllByText("▲ +1.25%");
    expect(arrows.length).toBeGreaterThan(0);
    // Color-coding: positive rows use the text-positive token (never raw hex).
    expect(arrows[0].className).toContain("text-positive");
  });
});

// ── 2. SectorHeatmapWidget — proportional color scale + tooltip ───────────────

describe("SectorHeatmapWidget — Round 1 proportional scale", () => {
  /** Find the tile <button> that contains the given abbreviated label. */
  function tileByLabel(label: string): HTMLElement {
    const el = screen.getByText(label).closest("button");
    if (!el) throw new Error(`tile button for ${label} not found`);
    return el;
  }

  it("saturates the payload's max |change| tile and scales the rest proportionally", async () => {
    render(<SectorHeatmapWidget />, { wrapper });
    await waitFor(() => {
      expect(screen.getByText("Tech")).toBeInTheDocument();
    });

    // maxAbs = 2.0 (Information Technology).
    // IT: ratio 1.0  → strongest positive bucket /40.
    expect(tileByLabel("Tech").className).toContain("bg-positive/40");
    // Staples: 0.4/2.0 = 0.2 → faintest bucket /10 (the OLD fixed scale would
    // have put 0.4% in the second bucket — this assertion pins the new math).
    expect(tileByLabel("Staple").className).toContain("bg-positive/10");
    // Energy: 1.0/2.0 = 0.5 → /30 negative bucket.
    expect(tileByLabel("Energy").className).toContain("bg-negative/30");
    // Utilities: null change → muted "no data" tile.
    expect(tileByLabel("Util").className).toContain("bg-muted/30");
  });

  it("exposes a hover tooltip with sector name and % change", async () => {
    render(<SectorHeatmapWidget />, { wrapper });
    await waitFor(() => {
      expect(screen.getByText("Tech")).toBeInTheDocument();
    });
    const tile = screen.getByText("Tech").closest("button");
    // The tooltip always carries "<name> <signed-pct>"; the "· Top: <ticker>"
    // suffix is appended only after the client-side sector join resolves
    // (movers + overview queries) — we assert the stable prefix.
    await waitFor(() => {
      expect(tile?.getAttribute("title")).toMatch(/^Information Technology \+2\.00%/);
    });
  });

  it("appends the top mover ticker to the tooltip once the sector join resolves", async () => {
    render(<SectorHeatmapWidget />, { wrapper });
    await waitFor(() => {
      expect(screen.getByText("Tech")).toBeInTheDocument();
    });
    const tile = screen.getByText("Tech").closest("button");
    // NVDA (gainers mock) maps to Information Technology via the overview
    // batch — once both queries land the tooltip gains the Top suffix.
    await waitFor(() => {
      expect(tile?.getAttribute("title")).toBe(
        "Information Technology +2.00% · Top: NVDA",
      );
    });
  });
});

// ── 3. TopMovers — tabs, row fields, sparkline, navigation ───────────────────

describe("TopMovers — Round 1 redesign", () => {
  it("renders gainers/losers tabs with the gainers tab active by default", async () => {
    render(<TopMovers />, { wrapper });
    const gainersTab = screen.getByRole("tab", { name: "gainers" });
    const losersTab = screen.getByRole("tab", { name: "losers" });
    expect(gainersTab).toBeInTheDocument();
    expect(losersTab).toBeInTheDocument();
    expect(gainersTab.getAttribute("aria-selected")).toBe("true");
  });

  it("renders ticker, company name, %chg and a price patched from the overview batch", async () => {
    render(<TopMovers />, { wrapper });
    await waitFor(() => {
      expect(screen.getByText("NVDA")).toBeInTheDocument();
    });
    // Name column (Round 1 — the old tile widget had no name).
    expect(screen.getByText("NVIDIA Corp")).toBeInTheDocument();
    // % change with explicit sign.
    expect(screen.getByText("+5.20%")).toBeInTheDocument();
    // Price: the movers feed carries 0 — the overview batch supplies $850.00.
    await waitFor(() => {
      expect(screen.getByText("$850.00")).toBeInTheDocument();
    });
  });

  it("renders a 5-day sparkline for each row", async () => {
    render(<TopMovers />, { wrapper });
    await waitFor(() => {
      expect(screen.getByText("NVDA")).toBeInTheDocument();
    });
    // The Sparkline primitive renders role="img" with the row's aria-label.
    await waitFor(() => {
      expect(
        screen.getByRole("img", { name: "NVDA 5-day trend" }),
      ).toBeInTheDocument();
    });
  });

  it("navigates ticker-first to the instrument page on row click", async () => {
    const user = userEvent.setup();
    render(<TopMovers />, { wrapper });
    await waitFor(() => {
      expect(screen.getByText("NVDA")).toBeInTheDocument();
    });
    await user.click(
      screen.getByRole("button", { name: "Navigate to NVDA instrument page" }),
    );
    // PRD-0089 F2 §6.6: ticker-first URL (NOT the instrument UUID).
    expect(pushMock).toHaveBeenCalledWith("/instruments/NVDA");
  });

  it("switches to losers and shows '—' when no price is available", async () => {
    const user = userEvent.setup();
    render(<TopMovers />, { wrapper });
    await waitFor(() => {
      expect(screen.getByText("NVDA")).toBeInTheDocument();
    });

    await user.click(screen.getByRole("tab", { name: "losers" }));

    await waitFor(() => {
      expect(screen.getByText("TSLA")).toBeInTheDocument();
    });
    expect(screen.getByText("Tesla Inc")).toBeInTheDocument();
    expect(screen.getByText("-3.10%")).toBeInTheDocument();
    // TSLA is NOT in the overview batch and the movers feed has no price —
    // truthfulness rule: render "—", never $0.00.
    expect(screen.getByText("—")).toBeInTheDocument();
  });
});
