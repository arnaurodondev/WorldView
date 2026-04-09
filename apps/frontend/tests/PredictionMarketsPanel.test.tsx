import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { PredictionMarketsPanel, formatCloseTime } from "../src/components/PredictionMarketsPanel";
import type { PredictionMarketSummary } from "../src/lib/gateway-client";

vi.mock("../src/lib/gateway-client", () => ({
  gateway: {
    getPredictionMarkets: vi.fn(),
  },
}));

// Import after mock so we get the mocked version
import { gateway } from "../src/lib/gateway-client";

const mockedGetMarkets = vi.mocked(gateway.getPredictionMarkets);

function makeMarket(overrides: Partial<PredictionMarketSummary> = {}): PredictionMarketSummary {
  return {
    market_id: "market-1",
    question: "Will Bitcoin exceed $100k by end of 2026?",
    outcomes: [
      { name: "Yes", token_id: "t1", price: 0.72 },
      { name: "No", token_id: "t2", price: 0.28 },
    ],
    volume_24h: 1_200_000,
    close_time: new Date(Date.now() + 3 * 24 * 60 * 60 * 1000).toISOString(),
    resolution_status: "open",
    resolved_answer: null,
    updated_at: new Date().toISOString(),
    ...overrides,
  };
}

function renderPanel() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <PredictionMarketsPanel />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("PredictionMarketsPanel", () => {
  it("renders_skeleton_while_loading", () => {
    mockedGetMarkets.mockReturnValue(new Promise(() => {})); // never resolves
    renderPanel();
    // Three skeleton divs rendered; heading is present, no market cards
    expect(screen.getByText("Prediction Markets")).toBeInTheDocument();
    expect(screen.queryByText("No active prediction markets")).not.toBeInTheDocument();
    expect(screen.queryByText("Failed to load prediction markets")).not.toBeInTheDocument();
  });

  it("renders_market_cards_on_success", async () => {
    const markets = [makeMarket({ market_id: "m1" }), makeMarket({ market_id: "m2", question: "Will ETH flip BTC?" })];
    mockedGetMarkets.mockResolvedValue({ items: markets, total: 2, limit: 20, offset: 0 });

    renderPanel();

    await waitFor(() => {
      expect(screen.getByText("Will Bitcoin exceed $100k by end of 2026?")).toBeInTheDocument();
      expect(screen.getByText("Will ETH flip BTC?")).toBeInTheDocument();
    });
  });

  it("renders_empty_state_when_no_markets", async () => {
    mockedGetMarkets.mockResolvedValue({ items: [], total: 0, limit: 20, offset: 0 });

    renderPanel();

    await waitFor(() => {
      expect(screen.getByText("No active prediction markets")).toBeInTheDocument();
    });
  });

  it("renders_error_state_on_api_failure", async () => {
    mockedGetMarkets.mockRejectedValue(new Error("Network error"));

    renderPanel();

    await waitFor(() => {
      expect(screen.getByText("Failed to load prediction markets")).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
    });
  });

  it("probability_bar_proportional_to_price", async () => {
    mockedGetMarkets.mockResolvedValue({
      items: [makeMarket({ outcomes: [{ name: "Yes", token_id: "t1", price: 0.72 }, { name: "No", token_id: "t2", price: 0.28 }] })],
      total: 1,
      limit: 20,
      offset: 0,
    });

    renderPanel();

    await waitFor(() => {
      const bar = screen.getByTestId("probability-bar-fill");
      const width = (bar as HTMLElement).style.width;
      const pct = parseFloat(width);
      expect(pct).toBeGreaterThanOrEqual(70);
    });
  });

  it("close_time_formatted_as_relative", () => {
    const threeDaysFromNow = new Date(Date.now() + 3 * 24 * 60 * 60 * 1000).toISOString();
    expect(formatCloseTime(threeDaysFromNow)).toBe("closes in 3 days");
  });
});
