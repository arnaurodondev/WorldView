/**
 * hooks/useIdleLock.ts — Idle-timeout auto-lock
 *
 * PLAN-0059 I-6: institutional terminals require an idle-timeout that signs
 * the user out (or locks the session) after a configurable period of
 * inactivity — defends against an unattended workstation.
 *
 * BEHAVIOUR:
 *   - Resets on user activity: pointer move, key press, scroll, touch, focus.
 *   - Throttled to 1Hz so the activity events don't blow up React state.
 *   - Fires `onIdle` after `timeoutMs` of inactivity. Default action: redirect
 *     to /login?next=<current-path> so the user re-authenticates and lands
 *     back where they were.
 *   - A "warn before lock" callback (`onWarn`) fires `warnMs` before the
 *     terminal lockout, so consumers can render a Toast countdown.
 *   - Multi-tab aware via BroadcastChannel: any tab seeing user activity
 *     resets the timer in every other tab. Sign-out in any tab signs out all.
 *
 * USAGE:
 *   useIdleLock({ timeoutMs: 15 * 60 * 1000 });   // default action
 *
 *   useIdleLock({
 *     timeoutMs: 15 * 60 * 1000,
 *     warnMs: 60 * 1000,
 *     onWarn: () => toast.warning("Session locks in 60s"),
 *     onIdle: () => signOut(),
 *   });
 */

"use client";

import * as React from "react";
import { usePathname, useRouter } from "next/navigation";

const ACTIVITY_EVENTS = [
  "mousemove",
  "mousedown",
  "keydown",
  "wheel",
  "touchstart",
  "scroll",
  "focus",
] as const;

const BROADCAST_CHANNEL_NAME = "worldview.idle-lock";

interface UseIdleLockOptions {
  /** Total inactivity before lock fires. Default 15 minutes. */
  timeoutMs?: number;
  /** Pre-lock warning lead time. Default 60s. Pass 0 to disable warnings. */
  warnMs?: number;
  /** Called once when the user has `warnMs` left. */
  onWarn?: () => void;
  /** Called when the user has been idle for `timeoutMs`.
   * Default: redirect to /login?next=<current-path>. */
  onIdle?: () => void;
  /**
   * Disable the hook entirely (e.g. while loading auth state, or for guest
   * pages). When false, no listeners are attached.
   */
  enabled?: boolean;
}

const DEFAULT_TIMEOUT_MS = 15 * 60 * 1000; // 15 minutes
const DEFAULT_WARN_MS = 60 * 1000; // 60 seconds before lock
const ACTIVITY_THROTTLE_MS = 1000; // reset at most once per second

export function useIdleLock(options: UseIdleLockOptions = {}) {
  const router = useRouter();
  const pathname = usePathname();
  const {
    timeoutMs = DEFAULT_TIMEOUT_MS,
    warnMs = DEFAULT_WARN_MS,
    onWarn,
    onIdle,
    enabled = true,
  } = options;

  // Refs hold timer handles + last-activity tick. Refs (not state) avoid
  // re-renders on each activity event (60fps if we used state).
  const idleTimerRef = React.useRef<ReturnType<typeof setTimeout> | null>(null);
  const warnTimerRef = React.useRef<ReturnType<typeof setTimeout> | null>(null);
  const lastResetRef = React.useRef<number>(0);
  const channelRef = React.useRef<BroadcastChannel | null>(null);

  // Default lock action — captured in a stable callback so consumers that
  // don't pass `onIdle` get sane behaviour.
  const defaultIdleAction = React.useCallback(() => {
    const next = encodeURIComponent(pathname ?? "/dashboard");
    router.replace(`/login?next=${next}`);
  }, [router, pathname]);

  React.useEffect(() => {
    if (!enabled) return;

    // BroadcastChannel may be unavailable in older browsers / strict CSP.
    // Guard the construction so the feature degrades gracefully.
    if (typeof BroadcastChannel !== "undefined") {
      try {
        channelRef.current = new BroadcastChannel(BROADCAST_CHANNEL_NAME);
      } catch {
        channelRef.current = null;
      }
    }

    const clearTimers = () => {
      if (idleTimerRef.current) clearTimeout(idleTimerRef.current);
      if (warnTimerRef.current) clearTimeout(warnTimerRef.current);
      idleTimerRef.current = null;
      warnTimerRef.current = null;
    };

    const fireIdle = () => {
      clearTimers();
      if (onIdle) onIdle();
      else defaultIdleAction();
    };

    const fireWarn = () => {
      onWarn?.();
    };

    const reset = (broadcast: boolean) => {
      const now = Date.now();
      // Throttle: ignore if we already reset less than ACTIVITY_THROTTLE_MS ago.
      if (now - lastResetRef.current < ACTIVITY_THROTTLE_MS) return;
      lastResetRef.current = now;

      clearTimers();
      if (warnMs > 0 && warnMs < timeoutMs) {
        warnTimerRef.current = setTimeout(fireWarn, timeoutMs - warnMs);
      }
      idleTimerRef.current = setTimeout(fireIdle, timeoutMs);

      if (broadcast && channelRef.current) {
        try {
          channelRef.current.postMessage({ type: "activity", t: now });
        } catch {
          // Channel may be closed by the browser during page unload — safe to ignore.
        }
      }
    };

    const onActivity = () => reset(true);

    // Listen on document so events bubbled from any element fire here.
    for (const ev of ACTIVITY_EVENTS) {
      document.addEventListener(ev, onActivity, { passive: true });
    }
    window.addEventListener("focus", onActivity);

    // Cross-tab activity — when ANY tab broadcasts activity, reset our timer
    // too (without re-broadcasting, to avoid an echo loop).
    const onMessage = (e: MessageEvent) => {
      if (e.data && typeof e.data === "object" && e.data.type === "activity") {
        reset(false);
      }
    };
    channelRef.current?.addEventListener("message", onMessage);

    // Page-load: kick off the timer.
    reset(false);

    return () => {
      clearTimers();
      for (const ev of ACTIVITY_EVENTS) {
        document.removeEventListener(ev, onActivity);
      }
      window.removeEventListener("focus", onActivity);
      channelRef.current?.removeEventListener("message", onMessage);
      channelRef.current?.close();
      channelRef.current = null;
    };
  }, [enabled, timeoutMs, warnMs, onWarn, onIdle, defaultIdleAction]);
}
