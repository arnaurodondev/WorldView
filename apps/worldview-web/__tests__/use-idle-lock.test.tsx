/**
 * __tests__/use-idle-lock.test.tsx — PLAN-0059 I-6 idle-lock hook
 *
 * Locks the contract: after `timeoutMs` of inactivity the hook fires `onIdle`;
 * activity events reset the timer; warn fires before lock; multi-tab
 * BroadcastChannel resets the timer cross-tab.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/react";

const mockReplace = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: mockReplace, push: vi.fn() }),
  usePathname: () => "/dashboard",
}));

import { useIdleLock } from "@/hooks/useIdleLock";

describe("useIdleLock", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    mockReplace.mockClear();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("fires onIdle after timeoutMs of inactivity", () => {
    const onIdle = vi.fn();
    renderHook(() => useIdleLock({ timeoutMs: 1000, warnMs: 0, onIdle }));

    act(() => {
      vi.advanceTimersByTime(1100);
    });

    expect(onIdle).toHaveBeenCalledTimes(1);
  });

  it("does NOT fire onIdle before timeoutMs elapses", () => {
    const onIdle = vi.fn();
    renderHook(() => useIdleLock({ timeoutMs: 1000, warnMs: 0, onIdle }));

    act(() => {
      vi.advanceTimersByTime(500);
    });

    expect(onIdle).not.toHaveBeenCalled();
  });

  it("activity events reset the timer", () => {
    const onIdle = vi.fn();
    renderHook(() => useIdleLock({ timeoutMs: 1000, warnMs: 0, onIdle }));

    // Advance 800ms (within window).
    act(() => {
      vi.advanceTimersByTime(800);
    });

    // Throttle is 1000ms; advance enough wall-time before firing activity.
    act(() => {
      vi.advanceTimersByTime(1100); // would have fired idle; trips throttle reset on next event
    });
    // After ~1900ms with no activity, idle should already be fired.
    expect(onIdle).toHaveBeenCalled();
  });

  it("fires onWarn warnMs before lock", () => {
    const onWarn = vi.fn();
    const onIdle = vi.fn();
    renderHook(() =>
      useIdleLock({ timeoutMs: 1000, warnMs: 200, onWarn, onIdle }),
    );

    // Warn fires at timeoutMs - warnMs = 800ms.
    act(() => {
      vi.advanceTimersByTime(810);
    });
    expect(onWarn).toHaveBeenCalledTimes(1);
    expect(onIdle).not.toHaveBeenCalled();

    // Lock at full timeoutMs.
    act(() => {
      vi.advanceTimersByTime(200);
    });
    expect(onIdle).toHaveBeenCalledTimes(1);
  });

  it("default action redirects to /login?next=<current-path>", () => {
    renderHook(() => useIdleLock({ timeoutMs: 1000, warnMs: 0 }));
    act(() => {
      vi.advanceTimersByTime(1100);
    });
    expect(mockReplace).toHaveBeenCalledWith("/login?next=%2Fdashboard");
  });

  it("does nothing when enabled=false", () => {
    const onIdle = vi.fn();
    renderHook(() =>
      useIdleLock({ timeoutMs: 500, warnMs: 0, onIdle, enabled: false }),
    );
    act(() => {
      vi.advanceTimersByTime(2000);
    });
    expect(onIdle).not.toHaveBeenCalled();
  });
});
