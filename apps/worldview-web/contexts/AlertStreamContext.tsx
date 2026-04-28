/**
 * contexts/AlertStreamContext.tsx — Real-time alert state manager
 *
 * WHY THIS EXISTS: S10 pushes alerts over WebSocket. Multiple components need
 * access to the alert stream: TopBar (badge count), FlashOverlay (critical alerts),
 * AlertsPage (full list). React Context propagates this state to all consumers
 * without prop drilling.
 *
 * WHY CONTEXT + HOOK (not TanStack Query):
 * WebSocket streams are push-based (server → client), not request-based.
 * TanStack Query is for pull-based (client → server) data. Real-time WebSocket
 * state lives in React context because it's client-driven and event-sourced.
 *
 * WS TOKEN PATTERN (ADR-F-02):
 * Browsers cannot set custom headers on WebSocket connections (unlike fetch).
 * S10 requires auth. Solution: fetch a short-lived ws-token (30s TTL) from S9,
 * then append it as a query param: ws://s10/api/v1/alerts/stream?token=<ws_token>.
 * On each reconnect: fetch a fresh ws-token (the old one expired in 30s).
 *
 * RECONNECT BACKOFF:
 * 1s → 2s → 4s → 8s → 16s → 30s (cap). Prevents hammering S10 on network issues.
 *
 * WHO USES IT: TopBar (unread count), FlashOverlay (critical queue), AlertsPage (list)
 * DATA SOURCE: S10 WebSocket stream + S9 GET /api/v1/auth/ws-token
 * DESIGN REFERENCE: PRD-0028 §6.6 Flow 5, ADR-F-02
 */

"use client";
// WHY "use client": WebSocket is a browser-only API. Also uses useRef, useEffect,
// useState, createContext — all client-side React.

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { createGateway, GatewayError } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import type { AlertPayload } from "@/types/alerts";

// ── Context type ──────────────────────────────────────────────────────────────

interface AlertStreamContextValue {
  /** Last 50 non-critical alerts (newest first) */
  recentAlerts: AlertPayload[];
  /** CRITICAL alerts awaiting display in FlashOverlay */
  criticalQueue: AlertPayload[];
  /** Called by FlashOverlay after showing (and dismissing) the first critical alert */
  dequeueCritical: () => void;
  /** Count of unread alerts (for TopBar badge) */
  unreadCount: number;
  /** Whether the WS is currently connected */
  isConnected: boolean;
}

const AlertStreamContext = createContext<AlertStreamContextValue | null>(null);

// ── Constants ─────────────────────────────────────────────────────────────────

/** Maximum alerts to keep in recentAlerts before evicting the oldest */
const MAX_RECENT = 50;

/** Backoff schedule: attempt index → delay in ms */
const BACKOFF_MS = [1_000, 2_000, 4_000, 8_000, 16_000, 30_000];

function getBackoffDelay(attempt: number): number {
  // WHY cap at last entry: 30s is a reasonable max — longer is UX-unfriendly
  return BACKOFF_MS[Math.min(attempt, BACKOFF_MS.length - 1)] ?? 30_000;
}

// ── Provider ──────────────────────────────────────────────────────────────────

interface AlertStreamProviderProps {
  children: ReactNode;
}

export function AlertStreamProvider({ children }: AlertStreamProviderProps) {
  // WHY isLoading: guard connect() from firing while AuthProvider's initial
  // refresh check is still in flight. Without this, a stale isAuthenticated=true
  // value from a previous render cycle could trigger a premature WS connection
  // before the new auth check resolves — DS-010 fix.
  const { accessToken, isAuthenticated, isLoading } = useAuth();

  const [recentAlerts, setRecentAlerts] = useState<AlertPayload[]>([]);
  const [criticalQueue, setCriticalQueue] = useState<AlertPayload[]>([]);
  const [isConnected, setIsConnected] = useState(false);

  // WHY useRef for ws instance (not useState): Changing the WebSocket reference
  // should NOT trigger a re-render — the connection state is imperative infrastructure,
  // not UI state. useRef stores it stably across renders.
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const attemptRef = useRef(0);
  // WHY isMountedRef: guards against scheduling a reconnect after the component
  // unmounts. Without this, the onclose handler (still captured on the stack)
  // can call connect() after cleanup runs, causing a "state update on unmounted
  // component" warning and a dangling WebSocket. Set to false in cleanup.
  const isMountedRef = useRef(true);

  /** dispatch — route an incoming alert to the correct state bucket */
  const dispatch = useCallback((alert: AlertPayload) => {
    // F-301 fix (PLAN-0048 QA iter-1): the S10 WebSocket payload uses
    // `alert_id` while the AlertPayload type expects `id`. Without aliasing,
    // every WS-sourced alert ended up with `id === undefined`, and the
    // dashboard RecentAlerts widget rendered deep-links as
    // `?selected=undefined` — clicking landed users on a sheet that could
    // not resolve any alert. Normalising at the dispatch boundary means
    // every consumer downstream sees a non-null `id` regardless of which
    // wire shape (legacy `id` or new `alert_id`) the server sends.
    // We cast through `unknown` because TypeScript does not know the
    // server may add fields beyond the typed union.
    const raw = alert as AlertPayload & { alert_id?: string };
    const id = alert.id ?? raw.alert_id ?? "";
    // WHY toUpperCase(): S10 AlertSeverity StrEnum emits lowercase ("critical") but
    // AlertPayload.severity is typed as uppercase union ("CRITICAL"). Normalise here
    // so the CRITICAL routing check and downstream severityColor() calls both work.
    const normalised: AlertPayload = {
      ...alert,
      id,
      severity: (alert.severity?.toUpperCase() ?? "LOW") as AlertPayload["severity"],
    };
    if (normalised.severity === "CRITICAL") {
      // CRITICAL alerts go to the critical queue for immediate full-screen display
      setCriticalQueue((prev) => [...prev, normalised]);
    } else {
      // Non-critical alerts go to recentAlerts (capped at MAX_RECENT)
      setRecentAlerts((prev) => {
        const updated = [normalised, ...prev];
        // WHY slice: avoid unbounded memory growth for long-running sessions
        return updated.slice(0, MAX_RECENT);
      });
    }
  }, []);

  /** connect — open a WebSocket to S10 with a fresh ws-token */
  const connect = useCallback(async () => {
    // WHY check isLoading: AuthProvider fires a POST /auth/refresh on mount.
    // Until it resolves (isLoading = false), isAuthenticated may reflect stale
    // state from a previous render. Prevent premature connection during that window.
    if (!isAuthenticated || !accessToken || isLoading) return;
    if (wsRef.current?.readyState === WebSocket.OPEN) return; // already connected

    try {
      // Step 1: fetch a short-lived ws-token from S9
      // WHY fresh token on each connect: the ws-token is 30s TTL (it appears in the
      // WS URL which ends up in server logs — narrow TTL limits exposure window).
      const gw = createGateway(accessToken);
      const tokenData = await gw.getWsToken();

      // Step 2: open WebSocket directly to S10 (not through /api/ — Next.js rewrites
      // don't proxy WebSocket connections — ADR-F-02)
      // WHY /api/v1/alerts/stream (not /v1/alerts/stream): S10's APIRouter uses
      // prefix="/api/v1", so the full registered path is /api/v1/alerts/stream.
      // Using the bare /v1/... path produces an HTTP 403 because Starlette rejects
      // unmatched WebSocket upgrade requests with 403 (not 404).
      const wsBase = process.env.NEXT_PUBLIC_WS_BASE_URL ?? "ws://localhost:8010";
      const ws = new WebSocket(
        `${wsBase}/api/v1/alerts/stream?token=${encodeURIComponent(tokenData.token)}`,
      );

      ws.onopen = () => {
        setIsConnected(true);
        attemptRef.current = 0; // reset backoff on successful connection
      };

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data as string) as AlertPayload;
          dispatch(data);
        } catch {
          // WHY silently ignore: malformed messages from S10 should not crash the app
          // Logging would be appropriate here in production (structlog equivalent)
        }
      };

      ws.onclose = () => {
        // Guard: if the component has already unmounted (cleanup ran), do not
        // schedule another reconnect. Without this check, a close event that fires
        // after unmount would call connect(), mutate wsRef, and set React state on
        // an unmounted component — causing a memory leak and a React warning.
        if (!isMountedRef.current) return;

        setIsConnected(false);
        wsRef.current = null;

        // Schedule reconnect with exponential backoff.
        // WHY clearTimeout first: if connect() is called concurrently (e.g., auth
        // token refresh re-triggers the effect), a stale timer from the previous
        // attempt could still be pending. Clearing it prevents multiple concurrent
        // reconnect timers from accumulating and hammering S10.
        if (reconnectTimerRef.current) {
          clearTimeout(reconnectTimerRef.current);
        }
        const delay = getBackoffDelay(attemptRef.current);
        attemptRef.current++;

        reconnectTimerRef.current = setTimeout(() => {
          void connect();
        }, delay);
      };

      ws.onerror = () => {
        // WHY: onerror always fires before onclose — just close cleanly to trigger reconnect
        ws.close();
      };

      wsRef.current = ws;
    } catch (err) {
      // WHY: ws-token fetch failed.
      // DS-009 fix: distinguish 401 (session expired — no point retrying) from
      // transient errors (503, network failure — backoff and retry).
      if (err instanceof GatewayError && err.status === 401) {
        // Session is expired. The auth context's silent refresh should handle
        // re-authentication. No point retrying here — we'd just keep getting 401.
        // The AlertStreamProvider will reconnect when accessToken changes.
        setIsConnected(false);
        return;
      }
      // Transient error (503, network unreachable): retry with backoff.
      if (!isMountedRef.current) return; // guard against unmounted component
      if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current);
      const delay = getBackoffDelay(attemptRef.current);
      attemptRef.current++;
      reconnectTimerRef.current = setTimeout(() => void connect(), delay);
    }
  }, [isAuthenticated, accessToken, dispatch, isLoading]);

  // Open the WS connection when the user is authenticated AND auth check complete
  useEffect(() => {
    // WHY check !isLoading: mirrors the guard inside connect() — only attempt
    // connection once AuthProvider has finished its initial refresh check.
    if (isAuthenticated && accessToken && !isLoading) {
      void connect();
    }

    // Cleanup: close WS and clear reconnect timer when auth state changes or unmount
    return () => {
      // Signal to all pending onclose handlers that the component is gone.
      // This prevents any in-flight close event from scheduling a reconnect
      // after we have already cleaned up (see DS-002 fix: isMountedRef check
      // at the top of the onclose handler).
      isMountedRef.current = false;

      if (reconnectTimerRef.current) {
        clearTimeout(reconnectTimerRef.current);
        reconnectTimerRef.current = null;
      }
      if (wsRef.current) {
        // WHY close before clearing ref: prevents the onclose handler from triggering
        // a reconnect after we've intentionally disconnected
        wsRef.current.onclose = null;
        wsRef.current.close();
        wsRef.current = null;
      }
      setIsConnected(false);
    };
  }, [isAuthenticated, accessToken, connect, isLoading]);

  // Dequeue: called by FlashOverlay after displaying (and dismissing) the first alert
  const dequeueCritical = useCallback(() => {
    setCriticalQueue((prev) => prev.slice(1)); // remove first item (oldest/next to show)
  }, []);

  return (
    <AlertStreamContext.Provider
      value={{
        recentAlerts,
        criticalQueue,
        dequeueCritical,
        unreadCount: recentAlerts.length,
        isConnected,
      }}
    >
      {children}
    </AlertStreamContext.Provider>
  );
}

// ── Consumer hook ─────────────────────────────────────────────────────────────

export function useAlertStream(): AlertStreamContextValue {
  const ctx = useContext(AlertStreamContext);
  if (!ctx) {
    throw new Error(
      "useAlertStream must be used inside <AlertStreamProvider>. " +
        "Add AlertStreamProvider to app/providers.tsx.",
    );
  }
  return ctx;
}
