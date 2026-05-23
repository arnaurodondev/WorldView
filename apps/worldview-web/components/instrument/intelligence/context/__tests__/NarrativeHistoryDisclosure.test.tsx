/**
 * context/__tests__/NarrativeHistoryDisclosure.test.tsx — W7 T-23
 *
 * Pins 3 contracts:
 *  1. Single version → "Only the current version exists."
 *  2. Multiple versions render in the list (≥1 row visible when accordion open).
 *  3. Empty versions → "No narrative history available."
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

vi.mock("next/navigation", () => ({
  usePathname: vi.fn(() => "/instruments/ent-001"),
  useRouter: vi.fn(() => ({ push: vi.fn() })),
  useSearchParams: vi.fn(() => new URLSearchParams()),
  useParams: vi.fn(() => ({})),
}));

const mockGateway = vi.hoisted(() => ({ getNarratives: vi.fn() }));
vi.mock("@/lib/api-client", () => ({
  useApiClient: vi.fn(() => mockGateway),
}));

import { NarrativeHistoryDisclosure } from "@/components/instrument/intelligence/context/NarrativeHistoryDisclosure";

function Wrapper({ children }: { children: ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

beforeEach(() => { mockGateway.getNarratives.mockReset(); });

describe("NarrativeHistoryDisclosure", () => {
  it("shows 'Only the current version exists.' for a single version", async () => {
    mockGateway.getNarratives.mockResolvedValue({
      versions: [{ version_id: "v1", narrative_text: "Hello world narrative.", model_id: "llm/a", generated_at: "2026-05-01T00:00:00Z" }],
    });
    render(<Wrapper><NarrativeHistoryDisclosure entityId="ent-001" /></Wrapper>);
    // Open the accordion
    const trigger = screen.getByText("NARRATIVE HISTORY");
    fireEvent.click(trigger);
    await waitFor(() => screen.getByText("Only the current version exists."));
  });

  it("shows 'No narrative history available.' for zero versions", async () => {
    mockGateway.getNarratives.mockResolvedValue({ versions: [] });
    render(<Wrapper><NarrativeHistoryDisclosure entityId="ent-001" /></Wrapper>);
    fireEvent.click(screen.getByText("NARRATIVE HISTORY"));
    await waitFor(() => screen.getByText("No narrative history available."));
  });

  it("renders version rows for multiple versions", async () => {
    mockGateway.getNarratives.mockResolvedValue({
      versions: [
        { version_id: "v1", narrative_text: "First narrative.", model_id: "llm/a", generated_at: "2026-05-01T00:00:00Z" },
        { version_id: "v2", narrative_text: "Second narrative.", model_id: "llm/b", generated_at: "2026-05-02T00:00:00Z" },
      ],
    });
    render(<Wrapper><NarrativeHistoryDisclosure entityId="ent-001" /></Wrapper>);
    fireEvent.click(screen.getByText("NARRATIVE HISTORY"));
    await waitFor(() => {
      // Each row is a button with a 32px height strip
      const rows = screen.getAllByRole("button");
      // At least 2 version buttons (plus the accordion trigger itself)
      expect(rows.length).toBeGreaterThanOrEqual(2);
    });
  });
});
