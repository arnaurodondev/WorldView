/**
 * context/__tests__/NodePathsBlock.test.tsx — W7 T-23
 *
 * Pins 3 contracts:
 *  1. Empty paths → "No paths discovered."
 *  2. Renders up to 3 path cards (slices beyond 3rd are hidden).
 *  3. Section label includes the R-3 fallback note "(paths to primary entity)".
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

vi.mock("@/hooks/useAuth", () => ({
  useAuth: vi.fn(() => ({ accessToken: "tok" })),
}));

const mockGateway = vi.hoisted(() => ({ getEntityPaths: vi.fn() }));
vi.mock("@/lib/gateway", () => ({ createGateway: vi.fn(() => mockGateway) }));

// useEntityPaths calls the gateway; mock the hook directly.
vi.mock("@/lib/api/intelligence", () => ({
  useEntityPaths: vi.fn(),
}));

import { useEntityPaths } from "@/lib/api/intelligence";
import { NodePathsBlock } from "@/components/instrument/intelligence/context/NodePathsBlock";

const mockUseEntityPaths = vi.mocked(useEntityPaths);

function Wrapper({ children }: { children: ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

beforeEach(() => { mockUseEntityPaths.mockReset(); });

function makePath(id: string) {
  return {
    insight_id: id,
    hop_count: 2,
    path_nodes: [{ id: "n1", name: "Apple" }, { id: "n2", name: "TSMC" }],
    path_edges: [{ relation_type: "SUPPLIER_OF" }],
  };
}

describe("NodePathsBlock", () => {
  it("shows 'No paths discovered.' when paths is empty", async () => {
    mockUseEntityPaths.mockReturnValue({ data: { paths: [] }, isLoading: false, isError: false } as never);
    render(<Wrapper><NodePathsBlock entityId="ent-001" selectedNodeId="node-a" /></Wrapper>);
    await waitFor(() => screen.getByText("No paths discovered."));
  });

  it("renders at most 3 path cards", async () => {
    const paths = [makePath("p1"), makePath("p2"), makePath("p3"), makePath("p4")];
    mockUseEntityPaths.mockReturnValue({ data: { paths }, isLoading: false, isError: false } as never);
    const { container } = render(
      <Wrapper><NodePathsBlock entityId="ent-001" selectedNodeId="node-a" /></Wrapper>,
    );
    // Each path renders in a div with min-h-[38px]
    const cards = container.querySelectorAll("[class*='min-h-\\[38px\\]']");
    expect(cards.length).toBe(3);
  });

  it("section label includes R-3 fallback note", () => {
    mockUseEntityPaths.mockReturnValue({ data: { paths: [] }, isLoading: false, isError: false } as never);
    render(<Wrapper><NodePathsBlock entityId="ent-001" selectedNodeId="node-a" /></Wrapper>);
    expect(screen.getByText(/paths to primary entity/i)).toBeDefined();
  });
});
