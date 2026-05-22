/**
 * CompanySnapshotPanel.test.tsx (T-30)
 *
 * WHY THIS EXISTS: Pins the sector/industry/country display contract.
 * Uses mocked gateway + QueryClient so no real network calls fire.
 * The "more ↓ / less ↑" toggle is also verified.
 */

import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { CompanySnapshotPanel } from "@/components/instrument/financials/sidebar/CompanySnapshotPanel";

vi.mock("@/lib/api-client", () => ({ useAccessToken: () => "mock-token" }));

const MOCK_OVERVIEW = {
  instrument: {
    instrument_id: "aapl",
    ticker: "AAPL",
    name: "Apple Inc.",
    gics_sector: "Information Technology",
    gics_industry: "Technology Hardware",
    country: "United States",
    description:
      "Apple Inc. designs, manufactures, and markets smartphones, personal computers, tablets, wearables, and accessories worldwide. It also sells related accessories and services, including AppleCare, iCloud, Apple Music, Apple TV+, Apple Arcade, Apple Fitness+, Apple News+, and Apple Card. The company is headquartered in Cupertino, California, and was founded in 1976.",
    exchange: "NASDAQ",
    currency: "USD",
    isin: null,
    description_updated_at: null,
  },
};

vi.mock("@/lib/gateway", () => ({
  createGateway: () => ({
    getCompanyOverview: vi.fn().mockResolvedValue(MOCK_OVERVIEW),
  }),
}));

function wrap(children: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

describe("CompanySnapshotPanel", () => {
  it("renders section header", async () => {
    const { findByText } = render(wrap(<CompanySnapshotPanel instrumentId="aapl" />));
    expect(await findByText("COMPANY SNAPSHOT")).toBeInTheDocument();
  });

  it("renders sector label and value", async () => {
    const { findByText } = render(wrap(<CompanySnapshotPanel instrumentId="aapl" />));
    expect(await findByText("SECTOR")).toBeInTheDocument();
    expect(await findByText("Information Technology")).toBeInTheDocument();
  });

  it("renders industry label and value", async () => {
    const { findByText } = render(wrap(<CompanySnapshotPanel instrumentId="aapl" />));
    expect(await findByText("INDUSTRY")).toBeInTheDocument();
    expect(await findByText("Technology Hardware")).toBeInTheDocument();
  });

  it("renders country", async () => {
    const { findByText } = render(wrap(<CompanySnapshotPanel instrumentId="aapl" />));
    expect(await findByText("United States")).toBeInTheDocument();
  });

  it("shows more/less toggle for long description", async () => {
    const { findByText } = render(wrap(<CompanySnapshotPanel instrumentId="aapl" />));
    const moreBtn = await findByText("more ↓");
    expect(moreBtn).toBeInTheDocument();

    await userEvent.click(moreBtn);
    expect(screen.getByText("less ↑")).toBeInTheDocument();
  });
});
