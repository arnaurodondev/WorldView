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
 * then append it as a query param: ws://s10/v1/alerts/stream?token=<ws_token>.
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
import { createGateway } from "@/lib/gateway";
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
  const { accessToken, isAuthenticated } = useAuth();

  const [recentAlerts, setRecentAlerts] = useState<AlertPayload[]>([]);
  const [criticalQueue, setCriticalQueue] = useState<AlertPayload[]>([]);
  const [isConnected, setIsConnected] = useState(false);

  // WHY useRef for ws instance (not useState): Changing the WebSocket reference
  // should NOT trigger a re-render — the connection state is imperative infrastructure,
  // not UI state. useRef stores it stably across renders.
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const attemptRef = useRef(0);

  /** dispatch — route an incoming alert to the correct state bucket */
  const dispatch = useCallback((alert: AlertPayload) => {
    if (alert.severity === "CRITICAL") {
      // CRITICAL alerts go to the critical queue for immediate full-screen display
      setCriticalQueue((prev) => [...prev, alert]);
    } else {
      // Non-critical alerts go to recentAlerts (capped at MAX_RECENT)
      setRecentAlerts((prev) => {
        const updated = [alert, ...prev];
        // WHY slice: avoid unbounded memory growth for long-running sessions
        return updated.slice(0, MAX_RECENT);
      });
    }
  }, []);

  /** connect — open a WebSocket to S10 with a fresh ws-token */
  const connect = useCallback(async () => {
    if (!isAuthenticated || !accessToken) return;
    if (wsRef.current?.readyState === WebSocket.OPEN) return; // already connected

    try {
      // Step 1: fetch a short-lived ws-token from S9
      // WHY fresh token on each connect: the ws-token is 30s TTL (it appears in the
      // WS URL which ends up in server logs — narrow TTL limits exposure window).
      const gw = createGateway(accessToken);
      const tokenData = await gw.getWsToken();

      // Step 2: open WebSocket directly to S10 (not through /api/ — Next.js rewrites
      // don't proxy WebSocket connections — ADR-F-02)
      const wsBase = process.env.NEXT_PUBLIC_WS_BASE_URL ?? "ws://localhost:8010";
      const ws = new WebSocket(
        `${wsBase}/v1/alerts/stream?token=${encodeURIComponent(tokenData.token)}`,
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
        setIsConnected(false);
        wsRef.current = null;

        // Schedule reconnect with exponential backoff
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
    } catch {
      // WHY: ws-token fetch failed (e.g., 401 — session expired). Retry after backoff.
      const delay = getBackoffDelay(attemptRef.current);
      attemptRef.current++;
      reconnectTimerRef.current = setTimeout(() => void connect(), delay);
    }
  }, [isAuthenticated, accessToken, dispatch]);

  // Open the WS connection when the user is authenticated
  useEffect(() => {
    if (isAuthenticated && accessToken) {
      void connect();
    }

    // Cleanup: close WS and clear reconnect timer when auth state changes or unmount
    return () => {
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
  }, [isAuthenticated, accessToken, connect]);

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
