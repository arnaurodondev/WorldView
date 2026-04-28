/**
 * __tests__/RefreshAllButton.test.tsx — global refresh trigger contract.
 *
 * Pins that clicking the button calls queryClient.invalidateQueries() —
 * the entire reason this component exists.
 */

import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { RefreshAllButton } from "@/components/shell/RefreshAllButton";

function wrapper(client: QueryClient) {
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
}

describe("RefreshAllButton", () => {
  it("calls queryClient.invalidateQueries when clicked", () => {
    const client = new QueryClient();
    const spy = vi.spyOn(client, "invalidateQueries");
    render(<RefreshAllButton />, { wrapper: wrapper(client) });

    fireEvent.click(screen.getByRole("button", { name: /refresh all dashboard data/i }));
    expect(spy).toHaveBeenCalledTimes(1);
  });
});
