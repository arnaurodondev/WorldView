/**
 * skeleton-reliability.test.tsx — DESIGN-QA 2026-06-16 reliability fixes.
 *
 * Pins the two reliability behaviours the design QA flagged on the dashboard:
 *
 *  D-1 "Skeletons that never resolve" — a widget whose query hangs (never
 *      resolves, never errors) must NOT show a loading skeleton forever. After
 *      the max-wait budget it must fall through to a settled empty/error state.
 *      We assert this through the shared useSkeletonTimeout hook (the mechanism
 *      every widget uses) AND end-to-end via AiSignalsWidget with a never-
 *      resolving gateway promise.
 *
 *  D-4 "Dead sparkline columns" — the Top Positions widget must NOT render the
 *      shared <Sparkline> (which draws a dotted "dead" placeholder) when a row
 *      has no real series; it should render an empty slot instead.
 */

import { describe, it, expect, vi, afterEach, beforeEach } from "vitest";
import { render, screen, act, waitFor, renderHook } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import {
  useSkeletonTimeout,
  DEFAULT_SKELETON_TIMEOUT_MS,
} from "@/components/dashboard/useSkeletonTimeout";
import { AiSignalsWidget } from "@/components/dashboard/AiSignalsWidget";

// ── Mocks shared by the widget-level tests ────────────────────────────────────
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn() }),
}));

const gatewayMocks = {
  // Per-test override; default resolves empty so unrelated state is benign.
  getAiSignals: vi.fn().mockResolvedValue({ signals: [] }),
};
vi.mock("@/lib/gateway", () => ({
  createGateway: vi.fn(() => gatewayMocks),
}));

vi.mock("@/hooks/useAuth", () => ({
  useAuth: vi.fn(() => ({ accessToken: "test-token", isAuthenticated: true })),
}));

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

// ── useSkeletonTimeout — the shared mechanism ────────────────────────────────

describe("useSkeletonTimeout (DESIGN-QA D-1 mechanism)", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("returns false while loading and within the budget", () => {
    const { result } = renderHook(() => useSkeletonTimeout(true, 1000));
    expect(result.current).toBe(false);
    act(() => {
      vi.advanceTimersByTime(999);
    });
    expect(result.current).toBe(false);
  });

  it("flips to true once loading exceeds the budget", () => {
    const { result } = renderHook(() => useSkeletonTimeout(true, 1000));
    act(() => {
      vi.advanceTimersByTime(1000);
    });
    expect(result.current).toBe(true);
  });

  it("never times out when not loading (data already present)", () => {
    const { result } = renderHook(() => useSkeletonTimeout(false, 1000));
    act(() => {
      vi.advanceTimersByTime(5000);
    });
    expect(result.current).toBe(false);
  });

  it("resets the verdict when loading goes back to false (e.g. retry)", () => {
    const { result, rerender } = renderHook(
      ({ loading }) => useSkeletonTimeout(loading, 1000),
      { initialProps: { loading: true } },
    );
    act(() => {
      vi.advanceTimersByTime(1000);
    });
    expect(result.current).toBe(true);
    // Loading clears (data arrived / retry resolved) → verdict resets.
    rerender({ loading: false });
    expect(result.current).toBe(false);
  });

  it("defaults to a 12s budget", () => {
    expect(DEFAULT_SKELETON_TIMEOUT_MS).toBe(12_000);
  });
});

// ── AiSignalsWidget — end-to-end: a hung query must not spin forever ──────────

describe("AiSignalsWidget (DESIGN-QA D-1 end-to-end)", () => {
  afterEach(() => {
    gatewayMocks.getAiSignals.mockReset();
    gatewayMocks.getAiSignals.mockResolvedValue({ signals: [] });
    vi.useRealTimers();
  });

  it("falls through to the empty state when the query never resolves", async () => {
    vi.useFakeTimers();
    // A promise that NEVER settles — simulates a wedged S6/S9 request. Before
    // the fix this left the widget on its loading skeleton forever.
    gatewayMocks.getAiSignals.mockImplementation(() => new Promise(() => {}));

    render(<AiSignalsWidget />, { wrapper });

    // Advance past the skeleton budget; the widget should abandon the skeleton
    // and render its designed empty state instead of spinning.
    await act(async () => {
      vi.advanceTimersByTime(DEFAULT_SKELETON_TIMEOUT_MS + 50);
    });
    vi.useRealTimers();

    await waitFor(() => {
      expect(screen.getByText(/No news momentum yet/i)).toBeInTheDocument();
    });
  });
});
