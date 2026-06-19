/**
 * ai-signals-widget.test.tsx — rendering tests for the NEWS MOMENTUM widget.
 *
 * Pins the value-delivering behaviours of the per-entity momentum feed
 * (PLAN-0099 W4):
 *  1. rows render ticker + name + the trend (↑/↓ Δ%) + the top headline;
 *  2. the trend label is color-coded semantically (rising/falling);
 *  3. the headline links OUT to the source article (target=_blank);
 *  4. clicking the ROW navigates to /instruments/[ticker];
 *  5. the trend tooltip explains the metric honestly (NOT a prediction);
 *  6. the window selector (24H / 3D / 1W) refetches with the right `hours`;
 *  7. empty state still renders (with the selector present).
 *
 * Loading / empty / error panel states are ALSO pinned by the dashboard round
 * tests (R19 — those use getAiSignals → { signals: [] } which stays valid).
 */

import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { AiSignalsWidget } from "@/components/dashboard/AiSignalsWidget";
import type { NewsMomentumItem } from "@/components/dashboard/ai-signals/types";

// ── next/navigation mock — capture row-click navigation. ──────────────────────
const mockPush = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: mockPush, replace: vi.fn(), prefetch: vi.fn() }),
}));

// ── Gateway mock — per-test data via getAiSignals(limit, hours) ───────────────
const gatewayMocks = {
  getAiSignals: vi.fn().mockResolvedValue({ signals: [] }),
};
vi.mock("@/lib/gateway", () => ({
  createGateway: vi.fn(() => gatewayMocks),
}));

// ── Auth mock — widget only reads accessToken ─────────────────────────────────
vi.mock("@/hooks/useAuth", () => ({
  useAuth: vi.fn(() => ({ accessToken: "test-token", isAuthenticated: true })),
}));

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

afterEach(() => {
  gatewayMocks.getAiSignals.mockClear();
  gatewayMocks.getAiSignals.mockResolvedValue({ signals: [] });
  mockPush.mockClear();
});

/** Momentum-row factory mirroring the live S9 payload shape. */
function item(overrides: Partial<NewsMomentumItem>): NewsMomentumItem {
  return {
    entity_id: `e-${Math.random().toString(36).slice(2)}`,
    ticker: "NVDA",
    name: "Nvidia",
    count: 6,
    prior_count: 2,
    delta: 4,
    delta_pct: 200,
    top_article: {
      id: "art-1",
      title: "Nvidia Breaks Below $200, Approaches Bear Market Territory",
      url: "https://finance.yahoo.com/markets/stocks/articles/nvidia-200.html",
      source: "yahoo",
      published_at: new Date().toISOString(),
      sentiment: "negative",
      relevance: 0.83,
    },
    ...overrides,
  };
}

describe("AiSignalsWidget — news momentum rows", () => {
  it("renders ticker, name, the trend (Δ%) and the top headline linking out", async () => {
    gatewayMocks.getAiSignals.mockResolvedValue({ signals: [item({})], window_hours: 24 });
    render(<AiSignalsWidget />, { wrapper });

    // Headline is a link OUT to the publisher (new tab).
    const link = await screen.findByRole("link", { name: /Nvidia Breaks Below \$200/i });
    expect(link).toHaveAttribute("href", "https://finance.yahoo.com/markets/stocks/articles/nvidia-200.html");
    expect(link).toHaveAttribute("target", "_blank");
    // Ticker + name + the momentum trend (↑200%) are all on the row.
    expect(screen.getByText("NVDA")).toBeInTheDocument();
    expect(screen.getByText("Nvidia")).toBeInTheDocument();
    expect(screen.getByText("↑200%")).toBeInTheDocument();
  });

  it("color-codes the trend label semantically (rising vs falling)", async () => {
    gatewayMocks.getAiSignals.mockResolvedValue({
      signals: [
        item({ entity_id: "up", ticker: "AAA", delta: 4, delta_pct: 200 }),
        item({ entity_id: "down", ticker: "BBB", count: 2, prior_count: 5, delta: -3, delta_pct: -60 }),
      ],
      window_hours: 24,
    });
    const { container } = render(<AiSignalsWidget />, { wrapper });

    await screen.findByText("AAA");
    // Semantic tokens (§15.11) — never the hsl(var()) JSX spelling.
    expect(container.querySelector(".text-positive")).not.toBeNull();
    expect(container.querySelector(".text-negative")).not.toBeNull();
    expect(container.innerHTML).not.toContain("text-[hsl(var(--positive))]");
  });

  it("shows a capped percentage (not '+N') for new coverage when the prior window was empty", async () => {
    // WHY: the display unit must be consistent across all rows in the same widget —
    // always a % (financial convention). Prior=0 is valid data (new coverage) but
    // switching to an absolute count "+N" while other rows show "↑200%" is a mixed-
    // unit bug. The raw counts are visible in the hover tooltip so nothing is lost.
    gatewayMocks.getAiSignals.mockResolvedValue({
      signals: [item({ count: 5, prior_count: 0, delta: 5, delta_pct: 500 })],
      window_hours: 24,
    });
    render(<AiSignalsWidget />, { wrapper });

    // Prior=0, delta_pct=500 → renders as "↑500%" (not the old "+5").
    expect(await screen.findByText("↑500%")).toBeInTheDocument();
    // The old absolute reading must NOT appear — it would break unit consistency.
    expect(screen.queryByText("+5")).not.toBeInTheDocument();
  });

  it("caps the momentum percentage at 999% to prevent slot overflow", async () => {
    // WHY the cap: the trend label lives in a fixed ~w-[44px] slot. An uncapped
    // delta_pct (e.g. 12 000% for a ticker going from 1→121 articles) would
    // overflow it. 999% is the maximum 3-digit % that still fits with the ↑ glyph.
    // The tooltip (trendTitle) still shows the full article counts.
    gatewayMocks.getAiSignals.mockResolvedValue({
      signals: [item({ count: 121, prior_count: 1, delta: 120, delta_pct: 12000 })],
      window_hours: 24,
    });
    render(<AiSignalsWidget />, { wrapper });

    // delta_pct=12000 → capped to ↑999%
    expect(await screen.findByText("↑999%")).toBeInTheDocument();
    // Must NOT render the raw uncapped value.
    expect(screen.queryByText("↑12000%")).not.toBeInTheDocument();
  });

  it("navigates to /instruments/[ticker] when the row is clicked", async () => {
    gatewayMocks.getAiSignals.mockResolvedValue({ signals: [item({ ticker: "TSLA" })], window_hours: 24 });
    render(<AiSignalsWidget />, { wrapper });

    const row = await screen.findByRole("button", { name: /TSLA/i });
    await userEvent.click(row);
    expect(mockPush).toHaveBeenCalledWith("/instruments/TSLA");
  });

  it("explains the trend metric honestly in a tooltip (NOT a prediction)", async () => {
    gatewayMocks.getAiSignals.mockResolvedValue({ signals: [item({})], window_hours: 24 });
    render(<AiSignalsWidget />, { wrapper });

    const trend = await screen.findByText("↑200%");
    expect(trend.getAttribute("title")).toMatch(/article/i);
    expect(trend.getAttribute("title")).toMatch(/not a prediction of price movement/i);
  });

  it("defaults to the 24H window and requests it from the gateway", async () => {
    gatewayMocks.getAiSignals.mockResolvedValue({ signals: [item({})], window_hours: 24 });
    render(<AiSignalsWidget />, { wrapper });

    await screen.findByText("NVDA");
    expect(gatewayMocks.getAiSignals).toHaveBeenCalledWith(30, 24);
    expect(screen.getByRole("button", { name: "24H" })).toHaveAttribute("aria-pressed", "true");
  });

  it("switching the window selector refetches with the new hours", async () => {
    gatewayMocks.getAiSignals.mockResolvedValue({ signals: [item({})], window_hours: 24 });
    render(<AiSignalsWidget />, { wrapper });

    await screen.findByText("NVDA");

    await userEvent.click(screen.getByRole("button", { name: "1W" }));
    await waitFor(() => {
      expect(gatewayMocks.getAiSignals).toHaveBeenCalledWith(30, 168);
    });

    await userEvent.click(screen.getByRole("button", { name: "3D" }));
    await waitFor(() => {
      expect(gatewayMocks.getAiSignals).toHaveBeenCalledWith(30, 72);
    });
  });

  it("shows the empty state (and keeps the window selector) when there is no momentum", async () => {
    gatewayMocks.getAiSignals.mockResolvedValue({ signals: [], window_hours: 24 });
    render(<AiSignalsWidget />, { wrapper });

    expect(await screen.findByText(/No news momentum yet/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "1W" })).toBeInTheDocument();
  });
});
