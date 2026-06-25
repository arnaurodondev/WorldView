/**
 * __tests__/useSkeletonTimeout.test.tsx — DESIGN-QA I-1 (2026-06-18).
 *
 * Pins the Intelligence-tab "skeleton must not spin forever" guard: the hook
 * returns false while a load is within budget, flips to true once the load has
 * stayed pending past the budget, and RESETS when loading goes back to false
 * (so a Retry gets the full budget again).
 */

import { describe, it, expect, vi, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import {
  useSkeletonTimeout,
  DEFAULT_SKELETON_TIMEOUT_MS,
} from "@/components/instrument/intelligence/useSkeletonTimeout";

afterEach(() => vi.useRealTimers());

describe("useSkeletonTimeout", () => {
  it("returns false while loading is within the budget", () => {
    vi.useFakeTimers();
    const { result } = renderHook(() => useSkeletonTimeout(true));
    expect(result.current).toBe(false);
    act(() => vi.advanceTimersByTime(DEFAULT_SKELETON_TIMEOUT_MS - 1));
    expect(result.current).toBe(false);
  });

  it("flips to true once loading exceeds the budget", () => {
    vi.useFakeTimers();
    const { result } = renderHook(() => useSkeletonTimeout(true));
    act(() => vi.advanceTimersByTime(DEFAULT_SKELETON_TIMEOUT_MS + 1));
    expect(result.current).toBe(true);
  });

  it("never times out when not loading", () => {
    vi.useFakeTimers();
    const { result } = renderHook(() => useSkeletonTimeout(false));
    act(() => vi.advanceTimersByTime(DEFAULT_SKELETON_TIMEOUT_MS * 3));
    expect(result.current).toBe(false);
  });

  it("resets the verdict when loading returns to false (Retry path)", () => {
    vi.useFakeTimers();
    const { result, rerender } = renderHook(
      ({ loading }) => useSkeletonTimeout(loading),
      { initialProps: { loading: true } },
    );
    act(() => vi.advanceTimersByTime(DEFAULT_SKELETON_TIMEOUT_MS + 1));
    expect(result.current).toBe(true);
    // Data arrives / Retry resolves → loading false → verdict resets.
    rerender({ loading: false });
    expect(result.current).toBe(false);
  });

  it("honours a custom budget", () => {
    vi.useFakeTimers();
    const { result } = renderHook(() => useSkeletonTimeout(true, 2_000));
    act(() => vi.advanceTimersByTime(1_500));
    expect(result.current).toBe(false);
    act(() => vi.advanceTimersByTime(600));
    expect(result.current).toBe(true);
  });
});
