/**
 * context/__tests__/ContradictionsBlock.test.tsx — W7 T-23
 *
 * Pins 4 contracts:
 *  1. Loading state renders a Skeleton.
 *  2. Empty contradictions → "No contradictions detected."
 *  3. HIGH severity badge gets the error color class (text-negative).
 *  4. Severity is normalised case-insensitively ("high" → "HIGH").
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

const mockGateway = vi.hoisted(() => ({ getContradictions: vi.fn() }));
vi.mock("@/lib/api-client", () => ({
  useApiClient: vi.fn(() => mockGateway),
}));

import { ContradictionsBlock } from "@/components/instrument/intelligence/context/ContradictionsBlock";

function Wrapper({ children }: { children: ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

beforeEach(() => { mockGateway.getContradictions.mockReset(); });

describe("ContradictionsBlock", () => {
  it("renders skeleton while loading", () => {
    mockGateway.getContradictions.mockReturnValue(new Promise(() => {}));
    const { container } = render(
      <Wrapper><ContradictionsBlock entityId="ent-001" /></Wrapper>,
    );
    expect(container.querySelector("[data-slot='skeleton']")).not.toBeNull();
  });

  it("shows empty message when no contradictions", async () => {
    mockGateway.getContradictions.mockResolvedValue({ contradictions: [] });
    render(<Wrapper><ContradictionsBlock entityId="ent-001" /></Wrapper>);
    await waitFor(() => screen.getByText("No contradictions detected."));
  });

  it("renders HIGH severity badge with text-negative class", async () => {
    mockGateway.getContradictions.mockResolvedValue({
      contradictions: [{
        contradiction_id: "c1",
        severity: "HIGH",
        claim_a: "Revenue is $100B",
        claim_b: "Revenue is $80B",
        detected_at: "2026-05-01T00:00:00Z",
        source_a: "https://a.com",
        source_b: null,
      }],
    });
    const { container } = render(
      <Wrapper><ContradictionsBlock entityId="ent-001" /></Wrapper>,
    );
    await waitFor(() => {
      const badge = container.querySelector("[class*='text-negative']");
      expect(badge).not.toBeNull();
      expect(badge?.textContent).toBe("HIGH");
    });
  });

  it("normalises lowercase severity 'high' → 'HIGH'", async () => {
    mockGateway.getContradictions.mockResolvedValue({
      contradictions: [{
        contradiction_id: "c2",
        severity: "high",
        claim_a: "A",
        claim_b: "B",
        detected_at: "2026-05-01T00:00:00Z",
        source_a: null,
        source_b: null,
      }],
    });
    const { container } = render(
      <Wrapper><ContradictionsBlock entityId="ent-001" /></Wrapper>,
    );
    await waitFor(() => {
      const badge = container.querySelector("[class*='text-negative']");
      expect(badge?.textContent).toBe("HIGH");
    });
  });
});
