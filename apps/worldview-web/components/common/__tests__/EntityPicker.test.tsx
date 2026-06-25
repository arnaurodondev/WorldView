/**
 * components/common/__tests__/EntityPicker.test.tsx — shared entity picker
 * (PLAN-0113 W4 T-4-02).
 *
 * Verifies the picker returns the REAL KG `entity_id` (from searchFundamentals)
 * via onSelect, and that the selected chip + clear button work. We mock
 * useApiClient (the gateway) and useDebounce (identity) so the search fires
 * synchronously without a real network round-trip.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

// useDebounce → identity (no timer wait in tests).
vi.mock("@/hooks/useDebounce", () => ({
  useDebounce: (v: string) => v,
}));

// Gateway mock: searchFundamentals returns one enriched candidate carrying the
// REAL entity_id (distinct from the instrument_id) — that is what we assert flows
// through onSelect.
const searchFundamentals = vi.fn().mockResolvedValue({
  results: [
    {
      instrument_id: "i-aapl",
      entity_id: "kg-entity-aapl", // the REAL KG id (NOT the instrument id)
      ticker: "AAPL",
      name: "Apple Inc",
      exchange: "NASDAQ",
      type: "equity",
    },
  ],
  query: "app",
});

vi.mock("@/lib/api-client", () => ({
  useApiClient: () => ({ searchFundamentals }),
}));

import { EntityPicker, type ChosenEntity } from "@/components/common/EntityPicker";

function wrapper({ children }: { children: ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

describe("EntityPicker", () => {
  // WHY: searchFundamentals is a module-level mock shared across tests; reset its
  // call count so "not called" assertions don't see a prior test's call.
  beforeEach(() => searchFundamentals.mockClear());

  it("returns the REAL entity_id (not instrument_id) on select", async () => {
    const onSelect = vi.fn();
    render(
      <EntityPicker label="Entity" value={null} onSelect={onSelect} onClear={vi.fn()} />,
      { wrapper },
    );

    fireEvent.change(screen.getByLabelText(/Entity entity search/i), {
      target: { value: "app" },
    });

    // Result row appears once the (mocked) query resolves.
    const row = await screen.findByText(/Apple Inc/i);
    fireEvent.click(row);

    expect(onSelect).toHaveBeenCalledWith({
      entityId: "kg-entity-aapl",
      name: "Apple Inc",
    } satisfies ChosenEntity);
  });

  it("does not search for queries shorter than 2 chars", async () => {
    render(
      <EntityPicker label="Entity" value={null} onSelect={vi.fn()} onClear={vi.fn()} />,
      { wrapper },
    );
    fireEvent.change(screen.getByLabelText(/Entity entity search/i), {
      target: { value: "a" },
    });
    // Give any (incorrectly enabled) query a tick — it must NOT have fired.
    await waitFor(() => {
      expect(searchFundamentals).not.toHaveBeenCalled();
    });
  });

  it("renders a chip + clear button when a value is selected", () => {
    const onClear = vi.fn();
    render(
      <EntityPicker
        label="Entity"
        value={{ entityId: "kg-1", name: "Apple Inc" }}
        onSelect={vi.fn()}
        onClear={onClear}
      />,
      { wrapper },
    );
    expect(screen.getByText("Apple Inc")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Clear Entity/i }));
    expect(onClear).toHaveBeenCalled();
  });
});
