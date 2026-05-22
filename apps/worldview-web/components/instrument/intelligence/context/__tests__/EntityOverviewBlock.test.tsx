/**
 * context/__tests__/EntityOverviewBlock.test.tsx — W7 T-23
 *
 * Pins 4 contracts:
 *  1. Renders the entity canonical_name as the heading.
 *  2. Description text (4-line clamp) is visible.
 *  3. Completeness badge shows the rounded percentage.
 *  4. ↻ refresh button is present.
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

// EntityOverviewBlock reads token via useAccessToken (not useAuth)
vi.mock("@/lib/api-client", () => ({
  useAccessToken: vi.fn(() => "tok"),
}));

// EntityOverviewBlock calls apiFetch directly from @/lib/api/_client
const mockApiFetch = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api/_client", () => ({
  apiFetch: mockApiFetch,
  GatewayError: class GatewayError extends Error {
    status: number;
    constructor(status: number, msg: string) { super(msg); this.status = status; }
  },
}));

import { EntityOverviewBlock } from "@/components/instrument/intelligence/context/EntityOverviewBlock";

function Wrapper({ children }: { children: ReactNode }) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

const mockEntity = {
  entity_id: "ent-001",
  canonical_name: "Apple Inc.",
  entity_type: "financial_instrument",
  description: "Apple designs and sells consumer electronics.",
  data_completeness: 0.85,
  metadata: {
    employee_count: 161000,
    founded_year: 1976,
    headquarters_country: "US",
  },
};

const mockIntelligence = {
  health_score: 0.8,
  confidence_breakdown: {},
  overall_health: "good",
};

beforeEach(() => {
  mockApiFetch.mockReset();
  // Route by URL path: entity detail vs. intelligence
  mockApiFetch.mockImplementation((url: string) => {
    if (url.includes("/intelligence")) return Promise.resolve(mockIntelligence);
    return Promise.resolve(mockEntity);
  });
});

describe("EntityOverviewBlock", () => {
  it("renders the entity canonical name", async () => {
    render(<Wrapper><EntityOverviewBlock entityId="ent-001" /></Wrapper>);
    await waitFor(() => screen.getByText("Apple Inc."));
  });

  it("renders the description text", async () => {
    render(<Wrapper><EntityOverviewBlock entityId="ent-001" /></Wrapper>);
    await waitFor(() =>
      screen.getByText("Apple designs and sells consumer electronics."),
    );
  });

  it("renders completeness badge with rounded percent", async () => {
    render(<Wrapper><EntityOverviewBlock entityId="ent-001" /></Wrapper>);
    await waitFor(() => screen.getByText("85% complete"));
  });

  it("includes a refresh button (↻)", async () => {
    render(<Wrapper><EntityOverviewBlock entityId="ent-001" /></Wrapper>);
    await waitFor(() => {
      const btn = screen.getByRole("button", { name: /refresh intelligence narrative/i });
      expect(btn).toBeDefined();
    });
  });
});
