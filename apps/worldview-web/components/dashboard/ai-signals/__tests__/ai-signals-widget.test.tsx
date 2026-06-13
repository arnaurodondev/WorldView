/**
 * ai-signals-widget.test.tsx — rendering tests for the NEWS MOMENTUM widget
 * (2026-06-12 Wave-4 pivot).
 *
 * Pins the value-delivering behaviours the pivot introduced:
 *  1. rows render the real HEADLINE, source, honest relevance % and time;
 *  2. each row links OUT to the source article (target=_blank);
 *  3. the sentiment dot is color-coded semantically (positive/negative);
 *  4. the relevance tooltip explains the metric honestly (NOT a prediction);
 *  5. the window selector (24H / 3D / 1W) refetches with the right `hours`;
 *  6. empty + error states still render (with the selector present).
 *
 * Loading / empty / error panel states are ALSO pinned by
 * __tests__/dashboard-round3.test.tsx and dashboard-round4.test.tsx (R19 —
 * those tests use getAiSignals → { signals: [] } which stays valid here).
 */

import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { AiSignalsWidget } from "@/components/dashboard/AiSignalsWidget";
import type { NewsMomentumItem } from "@/components/dashboard/ai-signals/types";

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
});

/** News-momentum item factory mirroring the live S9 payload shape. */
function item(overrides: Partial<NewsMomentumItem>): NewsMomentumItem {
  return {
    article_id: `art-${Math.random().toString(36).slice(2)}`,
    title: "Nvidia Breaks Below $200, Approaches Bear Market Territory",
    url: "https://finance.yahoo.com/markets/stocks/articles/nvidia-200.html",
    source: "yahoo",
    published_at: new Date().toISOString(),
    sentiment: "negative",
    relevance: 0.83,
    routing_tier: "deep",
    market_impact_score: null,
    ...overrides,
  };
}

describe("AiSignalsWidget — news momentum rows", () => {
  it("renders the headline, source, honest relevance % and links to the article", async () => {
    gatewayMocks.getAiSignals.mockResolvedValue({ signals: [item({})], window_hours: 72 });
    render(<AiSignalsWidget />, { wrapper });

    // The headline is the row's primary content — the event itself.
    const link = await screen.findByRole("link", {
      name: /Nvidia Breaks Below \$200/i,
    });
    // Row links OUT to the source publisher (new tab).
    expect(link).toHaveAttribute("href", "https://finance.yahoo.com/markets/stocks/articles/nvidia-200.html");
    expect(link).toHaveAttribute("target", "_blank");
    // Source label + honest relevance % both present.
    expect(screen.getByText("yahoo")).toBeInTheDocument();
    expect(screen.getByText("83%")).toBeInTheDocument();
  });

  it("explains the relevance metric honestly in a tooltip (title attribute)", async () => {
    gatewayMocks.getAiSignals.mockResolvedValue({ signals: [item({})], window_hours: 72 });
    render(<AiSignalsWidget />, { wrapper });

    const pct = await screen.findByText("83%");
    expect(pct.getAttribute("title")).toMatch(/relevance/i);
    // Crucially: it must say what the number is NOT (the old 95% bug).
    expect(pct.getAttribute("title")).toMatch(/not a prediction of price movement/i);
  });

  it("color-codes the sentiment dot semantically (positive vs negative)", async () => {
    gatewayMocks.getAiSignals.mockResolvedValue({
      signals: [
        item({ title: "Up story", sentiment: "positive", url: "https://x.com/up" }),
        item({ title: "Down story", sentiment: "negative", url: "https://x.com/down" }),
      ],
      window_hours: 72,
    });
    const { container } = render(<AiSignalsWidget />, { wrapper });

    await screen.findByRole("link", { name: /Up story/i });
    // Semantic tokens (§15.11) — never the hsl(var()) JSX spelling.
    expect(container.querySelector(".text-positive")).not.toBeNull();
    expect(container.querySelector(".text-negative")).not.toBeNull();
    expect(container.innerHTML).not.toContain("text-[hsl(var(--positive))]");
  });

  it("defaults to the 3D (72h) window and requests it from the gateway", async () => {
    gatewayMocks.getAiSignals.mockResolvedValue({ signals: [item({})], window_hours: 72 });
    render(<AiSignalsWidget />, { wrapper });

    await screen.findByRole("link", { name: /Nvidia/i });
    // Default call: limit=30, hours=72.
    expect(gatewayMocks.getAiSignals).toHaveBeenCalledWith(30, 72);
    // The 3D toggle is the active (pressed) window.
    expect(screen.getByRole("button", { name: "3D" })).toHaveAttribute("aria-pressed", "true");
  });

  it("switching the window selector refetches with the new hours", async () => {
    gatewayMocks.getAiSignals.mockResolvedValue({ signals: [item({})], window_hours: 72 });
    render(<AiSignalsWidget />, { wrapper });

    await screen.findByRole("link", { name: /Nvidia/i });

    // Click 1W → refetch with hours=168.
    await userEvent.click(screen.getByRole("button", { name: "1W" }));
    await waitFor(() => {
      expect(gatewayMocks.getAiSignals).toHaveBeenCalledWith(30, 168);
    });

    // Click 24H → refetch with hours=24.
    await userEvent.click(screen.getByRole("button", { name: "24H" }));
    await waitFor(() => {
      expect(gatewayMocks.getAiSignals).toHaveBeenCalledWith(30, 24);
    });
  });

  it("renders a non-link row (still showing the headline) when the article has no URL", async () => {
    gatewayMocks.getAiSignals.mockResolvedValue({
      signals: [item({ title: "Headline without a link", url: null })],
      window_hours: 72,
    });
    render(<AiSignalsWidget />, { wrapper });

    expect(await screen.findByText("Headline without a link")).toBeInTheDocument();
    // No anchor for a URL-less row.
    expect(screen.queryByRole("link", { name: /Headline without a link/i })).not.toBeInTheDocument();
  });

  it("shows the empty state (and keeps the window selector) when there is no news", async () => {
    gatewayMocks.getAiSignals.mockResolvedValue({ signals: [], window_hours: 24 });
    render(<AiSignalsWidget />, { wrapper });

    // Empty copy hints at widening the window. Title is intentionally distinct
    // from PortfolioNewsWidget's "No recent news" (dashboard.no-news) to keep
    // getByText unambiguous when both empty states render together.
    expect(await screen.findByText(/No news momentum yet/i)).toBeInTheDocument();
    // Selector is still operable so the user can recover.
    expect(screen.getByRole("button", { name: "1W" })).toBeInTheDocument();
  });
});
