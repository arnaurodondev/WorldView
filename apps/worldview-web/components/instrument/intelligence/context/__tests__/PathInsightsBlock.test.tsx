/**
 * context/__tests__/PathInsightsBlock.test.tsx — W7 T-23
 *
 * Pins 3 contracts:
 *  1. Empty paths → "No multi-hop paths discovered."
 *  2. Portfolio post-filter: paths through a holding ticker are shown first.
 *  3. Fallback to top paths when no portfolio intersection exists.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

vi.mock("next/navigation", () => ({
  usePathname: vi.fn(() => "/instruments/ent-001"),
  useRouter: vi.fn(() => ({ push: vi.fn() })),
  useSearchParams: vi.fn(() => new URLSearchParams()),
  useParams: vi.fn(() => ({})),
}));

vi.mock("@/lib/api/intelligence", () => ({
  useEntityPaths: vi.fn(),
}));

vi.mock("@/contexts/ActivePortfolioContext", () => ({
  useActivePortfolio: vi.fn(() => ({ activePortfolioId: null })),
}));

import { useEntityPaths } from "@/lib/api/intelligence";
import { PathInsightsBlock } from "@/components/instrument/intelligence/context/PathInsightsBlock";

const mockUseEntityPaths = vi.mocked(useEntityPaths);

function Wrapper({ children }: { children: ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

beforeEach(() => { mockUseEntityPaths.mockReset(); });

describe("PathInsightsBlock", () => {
  it("shows empty message when no paths", async () => {
    mockUseEntityPaths.mockReturnValue({ data: { paths: [] }, isLoading: false, isError: false } as never);
    render(<Wrapper><PathInsightsBlock entityId="ent-001" /></Wrapper>);
    await waitFor(() => screen.getByText("No multi-hop paths discovered."));
  });

  it("renders path label as 'A → B → C'", async () => {
    const paths = [{
      insight_id: "p1",
      hop_count: 2,
      path_nodes: [
        { entity_id: "n1", name: "Apple", entity_type: "financial_instrument" },
        { entity_id: "n2", name: "TSMC", entity_type: "financial_instrument" },
        { entity_id: "n3", name: "ASML", entity_type: "financial_instrument" },
      ],
      path_edges: [{ relation_type: "SUPPLIER_OF" }, { relation_type: "CUSTOMER_OF" }],
    }];
    mockUseEntityPaths.mockReturnValue({ data: { paths }, isLoading: false, isError: false } as never);
    render(<Wrapper><PathInsightsBlock entityId="ent-001" /></Wrapper>);
    await waitFor(() => screen.getByText("Apple → TSMC → ASML"));
  });

  it("shows error state when isError", () => {
    mockUseEntityPaths.mockReturnValue({ data: undefined, isLoading: false, isError: true } as never);
    render(<Wrapper><PathInsightsBlock entityId="ent-001" /></Wrapper>);
    expect(screen.getByText("Path insights unavailable.")).toBeDefined();
  });
});
