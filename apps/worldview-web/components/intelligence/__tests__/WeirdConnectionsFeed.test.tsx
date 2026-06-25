/**
 * components/intelligence/__tests__/WeirdConnectionsFeed.test.tsx (PLAN-0112 T-5-03)
 *
 * Pins the feed's three load-bearing contracts:
 *  1. Ranked connections render (path chain + endpoint deep-links + headline %).
 *  2. The four sub-scores (REL / UNEXP / DIST / NEW) are shown.
 *  3. Empty + error states render their named messages.
 *
 * WHY mock useWeirdConnections (not fetch): we are testing the COMPONENT's
 * rendering of the data, not the hook's URL building (that lives in
 * intelligence-hooks.test.ts). Mocking the hook keeps this test focused and fast.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";

vi.mock("@/lib/api/intelligence", () => ({
  useWeirdConnections: vi.fn(),
}));

// next/link → plain anchor so the deep-links render without a Next router.
vi.mock("next/link", () => ({
  default: ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}));

import { useWeirdConnections } from "@/lib/api/intelligence";
import { WeirdConnectionsFeed } from "@/components/intelligence/WeirdConnectionsFeed";

const mockHook = vi.mocked(useWeirdConnections);

function sampleResponse() {
  return {
    connections: [
      {
        path_nodes: [
          { entity_id: "a", name: "Apple", entity_type: "company" },
          { entity_id: "b", name: "Anthropic", entity_type: "company" },
        ],
        path_edges: [{ relation_type: "PARTNER_OF", confidence: 0.8 }],
        hop_count: 1,
        reliability: 0.8,
        unexpectedness: 0.9,
        semantic_distance: 0.7,
        novelty: 0.2,
        weirdness: 0.71,
        src_entity_id: "a",
        dst_entity_id: "b",
        computed_at: "2026-06-12T00:00:00Z",
      },
    ],
    total: 1,
    freshness_ts: "2026-06-12T00:00:00Z",
  };
}

beforeEach(() => mockHook.mockReset());

describe("WeirdConnectionsFeed", () => {
  it("renders ranked connections with endpoints and the sub-score breakdown", () => {
    mockHook.mockReturnValue({
      data: sampleResponse(),
      isLoading: false,
      isError: false,
    } as never);

    render(<WeirdConnectionsFeed />);

    // Endpoint deep-link names appear.
    expect(screen.getAllByText("Apple").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Anthropic").length).toBeGreaterThan(0);

    // Headline weirdness % (0.71 → 71%).
    expect(screen.getByText("71%")).toBeDefined();

    // The four sub-score labels render (proof the breakdown is wired).
    expect(screen.getByText("REL")).toBeDefined();
    expect(screen.getByText("UNEXP")).toBeDefined();
    expect(screen.getByText("DIST")).toBeDefined();
    expect(screen.getByText("NEW")).toBeDefined();

    // Total summary line.
    expect(screen.getByText(/1 ranked connections/)).toBeDefined();
  });

  it("renders the empty state when there are no connections", () => {
    mockHook.mockReturnValue({
      data: { connections: [], total: 0, freshness_ts: null },
      isLoading: false,
      isError: false,
    } as never);

    render(<WeirdConnectionsFeed />);
    expect(
      screen.getByText("No weird connections match the current filters"),
    ).toBeDefined();
  });

  it("renders the error state on failure", () => {
    mockHook.mockReturnValue({
      data: undefined,
      isLoading: false,
      isError: true,
    } as never);

    render(<WeirdConnectionsFeed />);
    expect(screen.getByText("Failed to load weird connections")).toBeDefined();
  });

  it("renders loading skeletons while fetching", () => {
    mockHook.mockReturnValue({
      data: undefined,
      isLoading: true,
      isError: false,
    } as never);

    const { container } = render(<WeirdConnectionsFeed />);
    // The filter bar still renders; the body shows skeletons (no data rows).
    expect(screen.getByText("Min weirdness")).toBeDefined();
    expect(
      container.querySelectorAll('[data-slot="skeleton"]').length,
    ).toBeGreaterThan(0);
  });
});
