/**
 * contexts/WorkspaceSyncContext.tsx — Crosshair sync pub/sub for workspace chart panels
 *
 * WHY THIS EXISTS: TradingView-style "sync crosshair across panels" lets a trader
 * hover on one chart and see the vertical crosshair drawn at the same timestamp on
 * every other chart panel in the workspace. This context is the publish/subscribe
 * bus that connects them.
 *
 * WHY pub/sub with a Set of callbacks (not shared React state):
 * - We need O(1) fan-out to N subscriber charts when a crosshair move fires.
 * - Putting the crosshair position in React state would trigger re-renders of the
 *   context provider AND every subscriber on every pointer move — potentially
 *   60 fps × N charts worth of React reconciler work.
 * - Instead, subscribers register a raw callback. The broadcast() function calls
 *   each subscriber directly without going through the React render path. Charts
 *   update their TradingView lightweight-charts crosshair position imperatively via
 *   `chart.setCrosshairPosition(time, series)` — no React state needed.
 *
 * WHY syncEnabled lives in React state (not the Set):
 * - We DO want a React re-render when the toggle flips, because the WorkspaceUtilityRow
 *   button needs to reflect the current state. Only this one boolean is a true UI
 *   concern; the broadcast callbacks are invisible to React.
 *
 * DESIGN REFERENCE: PRD-0089 DESIGN-09 §A.1 sync-crosshair
 */

"use client";
// WHY "use client": creates a React context with state — browser-only.

import {
  createContext,
  useCallback,
  useContext,
  useRef,
  useState,
  type ReactNode,
} from "react";

// ── Types ──────────────────────────────────────────────────────────────────────

/** Callback signature for crosshair subscribers. */
export type CrosshairSubscriber = (time: number) => void;

export interface WorkspaceSyncContextValue {
  /** Whether crosshair sync is enabled. Controls subscribe/unsubscribe lifecycle. */
  syncEnabled: boolean;
  /** Toggle syncEnabled on/off. */
  setSyncEnabled: (enabled: boolean) => void;
  /**
   * Register a callback to be invoked when any chart broadcasts a crosshair move.
   * Returns an unsubscribe function — call it on component unmount.
   *
   * WHY return-based cleanup (not a separate unsubscribe method): mirrors
   * addEventListener / removeEventListener pattern that every React dev knows,
   * and the cleanup function can be returned directly from a useEffect.
   */
  subscribe: (cb: CrosshairSubscriber) => () => void;
  /**
   * Broadcast a crosshair position to all registered subscribers.
   * Called by OHLCVChart when the user moves the pointer over the chart.
   *
   * WHY pass sourceId: subscribers should ignore broadcasts that originated
   * from themselves (to prevent echo loops where chartA → broadcast → chartA
   * → broadcast → ...). Each chart passes its panel ID as the sourceId.
   */
  broadcast: (time: number, sourceId: string) => void;
}

// ── Context ────────────────────────────────────────────────────────────────────

const WorkspaceSyncContext = createContext<WorkspaceSyncContextValue | null>(null);

// ── Provider ───────────────────────────────────────────────────────────────────

interface WorkspaceSyncProviderProps {
  children: ReactNode;
}

export function WorkspaceSyncProvider({ children }: WorkspaceSyncProviderProps) {
  const [syncEnabled, setSyncEnabled] = useState(false);

  /**
   * WHY useRef for subscribers Map (not useState):
   * - The Map is a mutable structure; React doesn't need to know when it changes.
   * - Using useState would force a re-render every time a chart mounts/unmounts.
   * - useRef gives us a stable reference across renders — subscribe/broadcast
   *   always see the current subscriber list without closure stale-value bugs.
   *
   * WHY Map<string, CrosshairSubscriber> (not Set): we key by a unique
   * subscriber ID so we can look up and remove individual subscribers without
   * storing the callback reference in the consumer (avoids useCallback churn).
   */
  const subscribersRef = useRef<Map<string, CrosshairSubscriber>>(new Map());
  // WHY counter: cheap unique ID generator for subscriber keys.
  const counterRef = useRef(0);

  const subscribe = useCallback((cb: CrosshairSubscriber): (() => void) => {
    const id = String(++counterRef.current);
    subscribersRef.current.set(id, cb);
    // Return cleanup function — callers use this in useEffect return.
    return () => {
      subscribersRef.current.delete(id);
    };
  }, []);

  const broadcast = useCallback((time: number, sourceId: string) => {
    // WHY guard on syncEnabled: even if a chart forgets to check, we enforce
    // the toggle at the broadcast level so sync is truly off when disabled.
    if (!syncEnabled) return;

    subscribersRef.current.forEach((cb, id) => {
      // WHY skip source: prevent the broadcasting chart from receiving its
      // own event and calling setCrosshairPosition on itself — that would
      // cause a flicker or loop.
      if (id !== sourceId) {
        cb(time);
      }
    });
  }, [syncEnabled]);

  return (
    <WorkspaceSyncContext.Provider value={{ syncEnabled, setSyncEnabled, subscribe, broadcast }}>
      {children}
    </WorkspaceSyncContext.Provider>
  );
}

// ── Consumer hook ──────────────────────────────────────────────────────────────

/**
 * useWorkspaceSync — access the crosshair sync context.
 *
 * WHY throw (not return null): a chart trying to call broadcast() without a
 * provider would silently do nothing and the developer would waste time debugging
 * why sync doesn't work. A throw makes the missing provider obvious immediately.
 */
export function useWorkspaceSync(): WorkspaceSyncContextValue {
  const ctx = useContext(WorkspaceSyncContext);
  if (!ctx) {
    throw new Error("useWorkspaceSync must be used inside <WorkspaceSyncProvider>");
  }
  return ctx;
}
