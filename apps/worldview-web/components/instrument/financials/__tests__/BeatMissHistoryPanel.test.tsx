/**
 * BeatMissHistoryPanel.test.tsx (T-30)
 *
 * WHY THIS EXISTS: Pins the beat/miss caption contract. When earnings history
 * returns with surprise data, the panel must render "NB / NM last NY" and the
 * sparkline. Tests use mocked gateway + QueryClient so no network calls fire.
 */

import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { BeatMissHistoryPanel } from "@/components/instrument/financials/sidebar/BeatMissHistoryPanel";

// Mock auth + gateway so useQuery resolves instantly from inline data.
vi.mock("@/lib/api-client", () => ({ useAccessToken: () => "mock-token" }));

const MOCK_EARNINGS = {
  records: [
    { data: { date: "2021-09-30", epsActual: 1.24, epsEstimate: 1.10, surprisePercent: 12.7 } },
    { data: { date: "2022-09-30", epsActual: 1.29, epsEstimate: 1.27, surprisePercent: 1.6 } },
    { data: { date: "2023-09-30", epsActual: 1.46, epsEstimate: 1.39, surprisePercent: 5.0 } },
    { data: { date: "2024-09-30", epsActual: 0.97, epsEstimate: 1.00, surprisePercent: -3.0 } },
  ],
};

vi.mock("@/lib/gateway", () => ({
  createGateway: () => ({
    getEarningsHistory: vi.fn().mockResolvedValue(MOCK_EARNINGS),
  }),
}));

function wrap(children: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

describe("BeatMissHistoryPanel", () => {
  it("renders section header", async () => {
    const { findByText } = render(wrap(<BeatMissHistoryPanel instrumentId="aapl" />));
    expect(await findByText("EPS BEAT / MISS")).toBeInTheDocument();
  });

  it("renders beat count after data loads", async () => {
    const { findByText } = render(wrap(<BeatMissHistoryPanel instrumentId="aapl" />));
    // 3 beats out of 4 records with surprise → "3B"
    expect(await findByText("3B")).toBeInTheDocument();
  });

  it("renders miss count after data loads", async () => {
    const { findByText } = render(wrap(<BeatMissHistoryPanel instrumentId="aapl" />));
    // 1 miss out of 4 records → "1M"
    expect(await findByText("1M")).toBeInTheDocument();
  });
});
