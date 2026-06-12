/**
 * components/instrument/hooks/__tests__/useMetricsTableData.test.tsx
 *
 * WHY THIS EXISTS (Wave-2 sidebar fix, 2026-06-10): pins the hook's TOKEN
 * GATE — the second half of the all-dash Statistics-rail bug. With only
 * `enabled: !!instrumentId`, the fundamentals query fired on the very first
 * render BEFORE the access token hydrated, went out with no Authorization,
 * 401'd, and settled into a permanent error (TanStack does not re-run a
 * settled query when a closure variable changes — only when `enabled` flips
 * or the key changes). The bundle-seeded legs masked the failure for
 * EPS/BETA/MA rows, which is why the breakage was a confusing partial.
 *
 * CONTRACTS:
 *   1. token absent  → ZERO gateway calls (no doomed 401s fired);
 *   2. token arrives → the queries START (enabled flip re-fires them).
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

// ── Mocks ────────────────────────────────────────────────────────────────────

// Mutable token holder — tests flip it to simulate auth hydration.
const auth = vi.hoisted(() => ({ token: null as string | null }));
vi.mock("@/lib/api-client", () => ({
  useAccessToken: vi.fn(() => auth.token),
}));

const mockGateway = vi.hoisted(() => ({
  getFundamentals: vi.fn(),
  getFundamentalsSnapshot: vi.fn(),
  getTechnicals: vi.fn(),
  getShareStatistics: vi.fn(),
}));
vi.mock("@/lib/gateway", () => ({
  createGateway: vi.fn(() => mockGateway),
}));

// eslint-disable-next-line import/first
import { useMetricsTableData } from "@/components/instrument/hooks/useMetricsTableData";

// ── Helpers ──────────────────────────────────────────────────────────────────

function makeWrapper() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
  };
}

beforeEach(() => {
  auth.token = null;
  for (const fn of Object.values(mockGateway)) fn.mockReset().mockResolvedValue({});
});

// ── Tests ────────────────────────────────────────────────────────────────────

describe("useMetricsTableData token gate", () => {
  it("fires ZERO requests while the access token is absent", async () => {
    auth.token = null;
    renderHook(() => useMetricsTableData("ins-1"), { wrapper: makeWrapper() });
    // Give the (would-be) queries a tick — nothing may have fired.
    await new Promise((r) => setTimeout(r, 20));
    expect(mockGateway.getFundamentals).not.toHaveBeenCalled();
    expect(mockGateway.getFundamentalsSnapshot).not.toHaveBeenCalled();
    expect(mockGateway.getTechnicals).not.toHaveBeenCalled();
    expect(mockGateway.getShareStatistics).not.toHaveBeenCalled();
  });

  it("starts all four queries once the token arrives (enabled flip)", async () => {
    auth.token = null;
    const { rerender } = renderHook(() => useMetricsTableData("ins-1"), {
      wrapper: makeWrapper(),
    });
    expect(mockGateway.getFundamentals).not.toHaveBeenCalled();

    // Simulate auth hydration: token lands, hook re-renders, enabled flips.
    auth.token = "fresh-token";
    rerender();

    await waitFor(() => {
      expect(mockGateway.getFundamentals).toHaveBeenCalledTimes(1);
      expect(mockGateway.getFundamentalsSnapshot).toHaveBeenCalledTimes(1);
      expect(mockGateway.getTechnicals).toHaveBeenCalledTimes(1);
      expect(mockGateway.getShareStatistics).toHaveBeenCalledTimes(1);
    });
  });

  it("never fires with an empty instrumentId even when the token exists", async () => {
    auth.token = "fresh-token";
    renderHook(() => useMetricsTableData(""), { wrapper: makeWrapper() });
    await new Promise((r) => setTimeout(r, 20));
    expect(mockGateway.getFundamentals).not.toHaveBeenCalled();
  });
});
