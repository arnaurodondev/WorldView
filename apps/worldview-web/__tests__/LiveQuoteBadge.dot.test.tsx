/**
 * __tests__/LiveQuoteBadge.dot.test.tsx — compact-mode status dot mapping.
 *
 * F-QA-08 closes the test gap on the 5-bucket freshness status → CSS class
 * translation introduced for the always-visible 6px status dot. A future
 * refactor that mistypes "recent" as "recents" would otherwise ship silently.
 */

import { describe, it, expect, vi } from "vitest";
import { render, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

// Mock gateway BEFORE importing the badge so the createGateway() callsite
// resolves to our stub. Each test sets `freshness_status` on the returned
// quote to drive the dot colour mapping.
const mockGetQuote = vi.fn();
vi.mock("@/lib/gateway", () => ({
  createGateway: () => ({ getQuote: mockGetQuote }),
}));

// useAuth would otherwise require AuthContext.
vi.mock("@/hooks/useAuth", () => ({
  useAuth: () => ({ accessToken: "tok" }),
}));

import { LiveQuoteBadge } from "@/components/instrument/LiveQuoteBadge";

function makeWrapper() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
}

const baseQuote = {
  instrument_id: "i-1",
  ticker: "AAPL",
  price: 100,
  change: 1,
  change_pct: 1,
  timestamp: "2026-04-29T12:00:00Z",
  volume: null,
};

// Each row pins the freshness_status → dot Tailwind class. Querying the
// dot via container.querySelector is fine because there is exactly one
// 6×6 rounded element in compact mode.
const cases: Array<{ status: string | null; expectedClass: string; label: string }> = [
  { status: "live",        expectedClass: "bg-positive",         label: "live → positive" },
  { status: "recent",      expectedClass: "bg-positive",         label: "recent → positive" },
  { status: "delayed",     expectedClass: "bg-warning",          label: "delayed → warning" },
  { status: "stale",       expectedClass: "bg-negative",         label: "stale → negative" },
  { status: "unavailable", expectedClass: "bg-muted-foreground", label: "unavailable → muted" },
  { status: null,          expectedClass: "bg-positive",         label: "null falls back to live" },
];

describe("LiveQuoteBadge compact dot mapping", () => {
  for (const { status, expectedClass, label } of cases) {
    it(label, async () => {
      mockGetQuote.mockResolvedValue({ ...baseQuote, freshness_status: status });
      const { container } = render(
        <LiveQuoteBadge instrumentId="i-1" compact />,
        { wrapper: makeWrapper() },
      );

      // Wait for the query to resolve so the dot renders.
      await waitFor(() => {
        const dot = container.querySelector("span.h-\\[6px\\].w-\\[6px\\]");
        expect(dot).toBeTruthy();
      });

      const dot = container.querySelector("span.h-\\[6px\\].w-\\[6px\\]");
      expect(dot?.className).toContain(expectedClass);
    });
  }

  it("aria-hidden on the dot so SR users hear the StaleBadge text only", async () => {
    mockGetQuote.mockResolvedValue({ ...baseQuote, freshness_status: "live" });
    const { container } = render(
      <LiveQuoteBadge instrumentId="i-1" compact />,
      { wrapper: makeWrapper() },
    );
    await waitFor(() => {
      const dot = container.querySelector("span.h-\\[6px\\].w-\\[6px\\]");
      expect(dot?.getAttribute("aria-hidden")).toBe("true");
    });
  });
});
