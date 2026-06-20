/**
 * components/alerts/AlertsList.tsx — Severity-grouped alert list with ACK/Snooze
 *
 * WHY THIS EXISTS: The Alerts tab in app/(app)/alerts/page.tsx needs a client
 * component to hold filter state, ACK/snooze state, and data-fetching. Extracting
 * it here keeps the page file thin (route metadata + layout only) while the
 * interaction logic lives in a testable, reusable component.
 *
 * WHY SEVERITY-GROUPED (not chronological): Institutional alert systems group by
 * severity so CRITICAL issues are always visible at the top regardless of when
 * they arrived. Bloomberg's alert panel uses the same pattern — traders don't
 * miss CRITICAL alerts buried under a stream of LOW ones.
 *
 * WHY localStorage FOR ACK/SNOOZE STATE: Alert acknowledgement is a UI-level
 * convenience state, not persisted to S9. The API only returns pending alerts;
 * storing ACK/snooze in localStorage means the state survives page refreshes
 * without a backend round-trip. Trade-off: doesn't sync across devices.
 *
 * WHY CLIENT: useState (filter + ack/snooze state), useQuery (data), useRouter (navigation).
 *
 * WHO USES IT: app/(app)/alerts/page.tsx
 * DATA SOURCE: S9 GET /api/v1/alerts/pending (gateway.getPendingAlerts)
 * DESIGN REFERENCE: PRD-0031 §11 Alerts Wave 7
 */

"use client";
// WHY "use client": uses useState (ack/snooze state), useQuery (data), useRouter (URL updates).

import { useState, useCallback, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { useAlertActions } from "@/hooks/useAlertActions";
import { SeverityBadge } from "@/components/alerts/SeverityBadge";
import { AlertDetailSheet } from "@/components/alerts/AlertDetailSheet";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { formatRelativeTime, cn } from "@/lib/utils";
// roadmap item #2 / A-1 / B2: pure helpers that turn an Alert into the distinct,
// scannable columns the row renders (subject, humanised type, "what changed"
// summary). Kept in a separate module so they're unit-tested in isolation and
// stay in lock-step with the sidebar's formatAlertTitle composer.
import { alertSubject, alertSummary, humaniseAlertType } from "@/components/alerts/alert-row-content";
import { InlineEmptyState } from "@/components/data/InlineEmptyState";
// WHY sonner toast: consistent toast pattern across the app (SemanticHoldingsTable uses same import).
import { toast } from "sonner";
import type { AlertSeverity, Alert } from "@/types/api";

// ── Constants ─────────────────────────────────────────────────────────────────

/**
 * SEVERITY_ORDER — render order for severity groups.
 * WHY CRITICAL first: highest-priority alerts must be at the top regardless
 * of arrival time — traders scan from top-down.
 */
const SEVERITY_ORDER: AlertSeverity[] = ["CRITICAL", "HIGH", "MEDIUM", "LOW"];

/**
 * sevDotColor — color class for the section header dot indicator.
 * WHY bg-negative for CRITICAL: red = danger is universal. bg-warning for HIGH
 * (amber) signals "attention needed". muted for MEDIUM/LOW reduces visual noise.
 */
const SEV_DOT_COLOR: Record<AlertSeverity, string> = {
  CRITICAL: "bg-negative",
  HIGH: "bg-warning",
  MEDIUM: "bg-primary",
  LOW: "bg-muted-foreground",
};

/**
 * SEV_STRIPE_COLOR — left edge severity stripe colour (DESIGN-QA A-2).
 * WHY a left stripe (in addition to the dot): the audit flagged that "all rows
 * read the same muted tone despite a MEDIUM label". A 2px coloured stripe down
 * the left edge of each row makes the severity scannable as a vertical band —
 * the eye picks out the cluster of red CRITICAL stripes without reading. Uses
 * the same semantic tokens as the dot so the two cues never disagree.
 */
const SEV_STRIPE_COLOR: Record<AlertSeverity, string> = {
  CRITICAL: "border-l-negative",
  HIGH: "border-l-warning",
  MEDIUM: "border-l-primary",
  LOW: "border-l-muted-foreground/50",
};

/** localStorage keys for persistence */
const LS_ACK_KEY = "worldview-alert-ack";
const LS_SNOOZE_KEY = "worldview-alert-snooze";

// ── Persistence helpers ────────────────────────────────────────────────────────

/** Safe localStorage.getItem with JSON parse fallback */
function safeJsonGet<T>(key: string, fallback: T): T {
  try {
    const stored = localStorage.getItem(key);
    return stored ? (JSON.parse(stored) as T) : fallback;
  } catch {
    return fallback;
  }
}

// ── Component ─────────────────────────────────────────────────────────────────

/**
 * AlertsListProps — externally-controlled selection via the parent route.
 *
 * WHY a `selectedId` prop (not internal state): the parent /alerts route reads
 * `?selected=` from the URL and passes it down. This makes deep-linking from
 * RecentAlerts (Dashboard) and refreshing the page Just Work — the URL is the
 * single source of truth for "which alert is open in the detail sheet".
 */
export interface AlertsListProps {
  /** Alert id selected via the ?selected= URL param, or null when none. */
  selectedId?: string | null;
  /**
   * PRD-0089 Wave J: optional severity filter from the keyboard pill strip.
   * When set, only alerts of this severity are shown in the active groups.
   * null / undefined = show all severities (no filter).
   *
   * WHY prop (not internal state): the parent page owns the pill strip and its
   * keyboard shortcuts, so the severity filter lives up in the page and is
   * pushed down here as a controlled prop.
   */
  filterSeverity?: AlertSeverity | null;
}

export function AlertsList({ selectedId = null, filterSeverity = null }: AlertsListProps = {}) {
  const { accessToken } = useAuth();
  const router = useRouter();

  // PLAN-0051 T-D-4-03: backend-synced ack + snooze (with localStorage
  // fallback when the endpoints return 404). The hook hides the sync logic
  // so the existing handlers stay terse.
  const alertActions = useAlertActions();

  // Track which alerts are persisted only client-side (backend 404). Used
  // to render a small "(local only)" badge so the user understands the
  // ACK won't sync across devices until the backend ships.
  const [localOnlyIds, setLocalOnlyIds] = useState<Set<string>>(new Set());
  // PLAN-0053 T-A-1-08: surfaces ACK/snooze backend failures to the user via
  // a transient inline banner. Without this, optimistic-update rollback was
  // invisible (the alert just "snapped back") and users blamed the UI.
  const [actionError, setActionError] = useState<string | null>(null);

  // ── ACK state — set of acknowledged alert_ids ──────────────────────────────
  // WHY lazy initialiser for localStorage: avoids reading localStorage on every
  // render. The function runs once on mount only.
  const [acknowledged, setAcknowledged] = useState<Set<string>>(() => {
    const stored = safeJsonGet<string[]>(LS_ACK_KEY, []);
    return new Set(stored);
  });

  // ── Snooze state — map of alert_id → expiry timestamp (ms) ────────────────
  // WHY Map<string, number>: fast lookup by alert_id; value is unix ms timestamp.
  const [snoozed, setSnoozed] = useState<Map<string, number>>(() => {
    const stored = safeJsonGet<Record<string, number>>(LS_SNOOZE_KEY, {});
    return new Map(Object.entries(stored));
  });

  // ── Acknowledged section collapsed state ──────────────────────────────────
  // WHY collapsed by default: acknowledged alerts are "done" — they should not
  // distract from active alerts. User must opt-in to review them.
  const [ackCollapsed, setAckCollapsed] = useState(true);

  // ── Bulk-select state (PLAN-0053 T-F-6-03) ────────────────────────────────
  // WHY a Set of alert_ids: O(1) membership tests + the bulk toolbar needs to
  // know how many are selected. We do NOT persist this in localStorage — it
  // resets on refresh by design. Selection is an in-flight workflow, not a
  // setting; persisting would surprise users who expect a fresh slate.
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());

  /** Toggle a single id in the selection set. */
  const toggleSelected = useCallback((alertId: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(alertId)) next.delete(alertId);
      else next.add(alertId);
      return next;
    });
  }, []);

  /** Clear the entire selection set. Used after bulk-ACK and on Clear button. */
  const clearSelection = useCallback(() => {
    setSelectedIds(new Set());
  }, []);

  // ── Data fetching ────────────────────────────────────────────────────────────
  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ["alerts-pending-page", { limit: 50 }],
    queryFn: () => createGateway(accessToken).getPendingAlerts({ limit: 50 }),
    enabled: !!accessToken,
    // WHY staleTime: 0: alerts are real-time; always show fresh data on re-focus
    staleTime: 0,
    refetchOnWindowFocus: true,
  });

  // ── Derived state ──────────────────────────────────────────────────────────

  // WHY useMemo: `data?.alerts ?? []` would otherwise produce a fresh array
  // identity on every render, invalidating the selectedAlert useMemo + any
  // child memo dependent on the list. Memoising on `data?.alerts` stabilises
  // the reference between fetches.
  const allAlerts = useMemo<Alert[]>(() => data?.alerts ?? [], [data?.alerts]);
  const now = Date.now();

  /**
   * isVisible — determines if an alert should appear in the active groups.
   * Acknowledged and non-expired snoozed alerts are filtered out.
   */
  const isVisible = useCallback(
    (alert: Alert): boolean => {
      if (acknowledged.has(alert.alert_id)) return false;
      const snoozeExpiry = snoozed.get(alert.alert_id);
      if (snoozeExpiry !== undefined && now < snoozeExpiry) return false;
      return true;
    },
    [acknowledged, snoozed, now],
  );

  /** Active alerts grouped by severity.
   *
   * F-302 fix (PLAN-0048 QA iter-1): the backend returns severity as a
   * lowercase StrEnum value ("low", "medium", "high", "critical") but the
   * SEVERITY_ORDER constant uses the uppercase union from the typed Alert
   * model. The previous strict-equality check was always false, so every
   * group rendered empty and the page showed "No pending alerts" while 45
   * pending alerts were sitting in the API response.
   *
   * Normalising via toUpperCase() on both sides makes the comparison
   * case-insensitive without requiring the backend to change. RecentAlerts
   * already does the same normalisation (line 91) — we mirror that pattern
   * here so both surfaces behave identically.
   */
  const activeAlertsBySeverity = SEVERITY_ORDER.reduce<Record<AlertSeverity, Alert[]>>(
    (acc, sev) => {
      acc[sev] = allAlerts.filter(
        (a) => (a.severity ?? "").toUpperCase() === sev && isVisible(a),
      );
      return acc;
    },
    { CRITICAL: [], HIGH: [], MEDIUM: [], LOW: [] },
  );

  /** Acknowledged alerts — shown in collapsed section at bottom */
  const acknowledgedAlerts = allAlerts.filter((a) => acknowledged.has(a.alert_id));

  // PLAN-0051 T-D-4-04: snoozed-alerts derivation lives here only
  // implicitly — they are filtered out of the active groups via isVisible()
  // and re-surfaced in the dedicated Snoozed tab via AlertHistoryTab
  // (which queries /v1/alerts/history?status=snoozed). Keeping the snooze
  // localStorage map as the source of truth would diverge from the backend;
  // we let the server-side history endpoint render the dedicated tab.

  // ── ACK handlers ──────────────────────────────────────────────────────────

  /**
   * Acknowledge a single alert — adds to local Set + fires backend PATCH.
   *
   * PLAN-0051 T-D-4-03: ACK is now backend-synced. The localStorage write
   * still happens up-front so the UI updates instantly; the backend call
   * runs in the background. On 404 (endpoint not deployed) we mark the
   * alert `_localOnly` so the user sees a "(local only)" badge.
   */
  const handleAck = useCallback(
    (alertId: string) => {
      // Optimistic local update — UI moves the alert to the Acknowledged
      // section immediately, regardless of network outcome.
      setAcknowledged((prev) => {
        const next = new Set(prev);
        next.add(alertId);
        try {
          localStorage.setItem(LS_ACK_KEY, JSON.stringify([...next]));
        } catch { /* ignore localStorage quota errors */ }
        return next;
      });
      // Fire-and-forget backend sync. We don't await so the click handler
      // remains synchronous (matching the parent's expected signature).
      void alertActions.ack(alertId).then((res) => {
        // PLAN-0053 T-A-1-08: rollback the optimistic ACK if the backend
        // genuinely failed (5xx / network). Previously the localStorage stayed
        // dirty while the DB was still pending — multi-device divergence on
        // page refresh. ``localOnly`` (404 fallback) is treated as a success
        // signal because the user's intent is captured on this device.
        if (res.localOnly) {
          setLocalOnlyIds((prev) => {
            const next = new Set(prev);
            next.add(alertId);
            return next;
          });
        } else if (!res.ok) {
          setAcknowledged((prev) => {
            const next = new Set(prev);
            next.delete(alertId);
            try {
              localStorage.setItem(LS_ACK_KEY, JSON.stringify([...next]));
            } catch { /* ignore */ }
            return next;
          });
          setActionError(res.error || "Failed to acknowledge alert");
          // Auto-dismiss the inline error after 4 seconds.
          window.setTimeout(() => setActionError(null), 4000);
        }
      });
    },
    [alertActions],
  );

  /**
   * Bulk-ACK every currently selected alert (PLAN-0053 T-F-6-03).
   *
   * WHY mirror handleAckAll's optimistic + per-id sync pattern: keeps backend
   * sync semantics identical (some ACKs succeed, others fall back to
   * local-only) — the user's mental model is "bulk == many singles in one
   * click". Rolling our own happy-path-only behaviour would diverge from the
   * single-row case and create surprises (e.g. one row ACKs but bulk doesn't).
   */
  const handleAckSelected = useCallback(() => {
    const ids = [...selectedIds];
    if (ids.length === 0) return;
    setAcknowledged((prev) => {
      const next = new Set(prev);
      ids.forEach((id) => next.add(id));
      try {
        localStorage.setItem(LS_ACK_KEY, JSON.stringify([...next]));
      } catch { /* ignore */ }
      return next;
    });
    ids.forEach((id) => {
      void alertActions.ack(id).then((res) => {
        if (res.localOnly) {
          setLocalOnlyIds((prev) => {
            const next = new Set(prev);
            next.add(id);
            return next;
          });
        }
      });
    });
    clearSelection();
  }, [selectedIds, alertActions, clearSelection]);

  /** Acknowledge all alerts of a given severity level */
  const handleAckAll = useCallback(
    (severity: AlertSeverity) => {
      const targetIds = (activeAlertsBySeverity[severity] ?? []).map((a) => a.alert_id);
      setAcknowledged((prev) => {
        const next = new Set(prev);
        targetIds.forEach((id) => next.add(id));
        try {
          localStorage.setItem(LS_ACK_KEY, JSON.stringify([...next]));
        } catch { /* ignore */ }
        return next;
      });
      // Fire backend ACK for every target id. Parallel so batch ACK still
      // feels instant — failures fall back to local-only per-id.
      targetIds.forEach((id) => {
        void alertActions.ack(id).then((res) => {
          if (res.localOnly) {
            setLocalOnlyIds((prev) => {
              const next = new Set(prev);
              next.add(id);
              return next;
            });
          }
        });
      });
    },
    [activeAlertsBySeverity, alertActions],
  );

  /**
   * Snooze an alert for N minutes — stores expiry timestamp + fires backend.
   *
   * PLAN-0051 T-D-4-03: snooze is now backend-synced via PATCH /snooze. We
   * still update localStorage immediately so the row dims without waiting
   * for the network round-trip.
   */
  const handleSnooze = useCallback(
    (alertId: string, minutes: number) => {
      const until = new Date(Date.now() + minutes * 60 * 1000);
      setSnoozed((prev) => {
        const next = new Map(prev);
        next.set(alertId, until.getTime());
        try {
          localStorage.setItem(
            LS_SNOOZE_KEY,
            JSON.stringify(Object.fromEntries(next)),
          );
        } catch { /* ignore */ }
        return next;
      });
      void alertActions.snooze(alertId, until).then((res) => {
        // PLAN-0053 T-A-1-08: rollback snooze on backend failure (mirrors handleAck).
        if (res.localOnly) {
          setLocalOnlyIds((prev) => {
            const next = new Set(prev);
            next.add(alertId);
            return next;
          });
        } else if (!res.ok) {
          setSnoozed((prev) => {
            const next = new Map(prev);
            next.delete(alertId);
            try {
              localStorage.setItem(
                LS_SNOOZE_KEY,
                JSON.stringify(Object.fromEntries(next)),
              );
            } catch { /* ignore */ }
            return next;
          });
          setActionError(res.error || "Failed to snooze alert");
          window.setTimeout(() => setActionError(null), 4000);
        }
      });
    },
    [alertActions],
  );

  // ── Selection handlers (PLAN-0048 Wave B-3) ───────────────────────────────

  /**
   * Update the URL ?selected= param via router.replace.
   *
   * WHY router.replace (not push): opening / closing the sheet should not
   * pollute browser history with a separate entry per alert — the back
   * button must jump back to the page the user came from, not iterate
   * through every alert they viewed.
   */
  const handleSelect = useCallback(
    (alertId: string) => {
      router.replace(`/alerts?selected=${encodeURIComponent(alertId)}`);
    },
    [router],
  );

  /** Close the detail sheet — strips the ?selected= param. */
  const handleCloseSheet = useCallback(() => {
    router.replace("/alerts");
  }, [router]);

  // Resolve the currently selected Alert from the loaded list. WHY useMemo:
  // `allAlerts` rebuilds on every fetch; we only want to recompute the lookup
  // when the data or the selectedId actually changes.
  const selectedAlert = useMemo<Alert | null>(() => {
    if (!selectedId) return null;
    return allAlerts.find((a) => a.alert_id === selectedId) ?? null;
  }, [selectedId, allAlerts]);

  // ── Loading state ────────────────────────────────────────────────────────────
  if (isLoading) {
    return (
      <div className="divide-y divide-border/30" aria-busy="true" aria-label="Loading alerts">
        {Array.from({ length: 5 }).map((_, i) => (
          <div key={i} className="flex h-[20px] items-center gap-3 px-2">
            <Skeleton className="h-4 w-10" />
            <Skeleton className="h-3 w-12" />
            <Skeleton className="h-3 flex-1" />
            <Skeleton className="h-3 w-8" />
          </div>
        ))}
      </div>
    );
  }

  // ── Error state ──────────────────────────────────────────────────────────────
  if (isError) {
    return (
      <div className="rounded-[2px] border border-destructive/30 bg-destructive/10 p-3">
        <p className="text-xs text-destructive">Failed to load alerts</p>
        <Button
          variant="ghost"
          size="sm"
          className="mt-1 h-6 px-0 text-xs"
          onClick={() => void refetch()}
        >
          Retry
        </Button>
      </div>
    );
  }

  // ── Determine if all groups are empty ─────────────────────────────────────
  const hasActiveAlerts = SEVERITY_ORDER.some(
    (sev) => (activeAlertsBySeverity[sev]?.length ?? 0) > 0,
  );

  return (
    <div>

      {/* ── Action error banner (PLAN-0053 T-A-1-08) ──────────────────────── */}
      {actionError && (
        <div
          role="alert"
          className="mb-1 flex h-7 items-center justify-between border-b border-negative/40 bg-negative/10 px-2 text-[11px] text-negative"
        >
          <span>{actionError}</span>
          <button
            onClick={() => setActionError(null)}
            aria-label="Dismiss error"
            className="text-negative/70 hover:text-negative"
          >
            ×
          </button>
        </div>
      )}

      {/* ── Bulk action toolbar (PLAN-0053 T-F-6-03) ──────────────────────── */}
      {/* WHY only when N≥1 selected: at zero selection the toolbar would be
          dead chrome. Hiding it keeps vertical density at the default state
          (terminal-grade) and lets the toolbar appear as a clear progressive-
          disclosure cue when the user starts checking boxes. */}
      {selectedIds.size > 0 && (
        <div
          role="toolbar"
          aria-label="Bulk alert actions"
          className="mb-1 flex h-7 items-center justify-between border-b border-primary/40 bg-primary/5 px-2 text-[11px]"
        >
          <span className="font-mono tabular-nums text-foreground">
            {selectedIds.size} selected
          </span>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={handleAckSelected}
              className="rounded-[2px] border border-primary/40 bg-primary/10 px-2 py-0.5 text-[10px] uppercase tracking-[0.06em] text-primary hover:bg-primary/20"
              aria-label={`Acknowledge ${selectedIds.size} selected alerts`}
            >
              ACK Selected
            </button>
            <button
              type="button"
              onClick={clearSelection}
              className="text-[10px] uppercase tracking-[0.06em] text-muted-foreground hover:text-foreground"
              aria-label="Clear alert selection"
            >
              Clear
            </button>
          </div>
        </div>
      )}

      {/* ── All-clear state ───────────────────────────────────────────────── */}
      {!hasActiveAlerts && acknowledgedAlerts.length === 0 && (
        <InlineEmptyState message="No pending alerts — you're all caught up." />
      )}

      {/* ── Severity groups ────────────────────────────────────────────────── */}
      {SEVERITY_ORDER.map((sev) => {
        // PRD-0089 Wave J: honour the filterSeverity prop from the pill strip.
        // WHY filter here (not in activeAlertsBySeverity derivation): the severity
        // groups already compute all severities. Filtering at render time means we
        // don't need to recompute the memoized group map when the pill changes.
        if (filterSeverity && filterSeverity !== sev) return null;

        const sevAlerts = activeAlertsBySeverity[sev] ?? [];
        if (sevAlerts.length === 0) return null;

        return (
          <div key={sev} className="mb-0">

            {/* Severity group header — sticky so it stays visible when scrolling */}
            <div
              className={cn(
                "sticky top-0 z-10 flex h-6 items-center justify-between border-b border-border bg-background px-2",
                "text-[10px] uppercase tracking-[0.08em]",
                sev === "CRITICAL"
                  ? "text-negative"
                  : sev === "HIGH"
                    ? "text-warning"
                    : "text-muted-foreground",
              )}
            >
              {/* Severity label with dot indicator and count */}
              <span className="flex items-center gap-1.5">
                {/* WHY inline dot: color-coded dot is a faster visual scan signal
                    than text alone — traders recognise the pattern in milliseconds */}
                <span className={cn("h-1.5 w-1.5 rounded-full", SEV_DOT_COLOR[sev])} />
                {sev} ({sevAlerts.length})
              </span>

              {/* ACK ALL — acknowledges every alert in this severity group */}
              <button
                className="normal-case tracking-normal text-muted-foreground hover:text-foreground"
                onClick={() => handleAckAll(sev)}
                aria-label={`Acknowledge all ${sev} alerts`}
              >
                ACK ALL
              </button>
            </div>

            {/* Alert rows for this severity */}
            <ul className="divide-y divide-border/30" role="list" aria-label={`${sev} alerts`}>
              {sevAlerts.map((alert) => (
                <AlertRow
                  key={alert.alert_id}
                  alert={alert}
                  // PLAN-0048 Wave B-3: clicking a row now updates the URL
                  // ?selected= param instead of navigating to /instruments.
                  // router.replace (not push) keeps history clean — opening
                  // and closing the sheet shouldn't pollute the back-button
                  // history with one entry per alert.
                  onSelect={() => handleSelect(alert.alert_id)}
                  onAck={() => handleAck(alert.alert_id)}
                  onSnooze={(minutes) => handleSnooze(alert.alert_id, minutes)}
                  // PRD-0089 Wave J: hover dismiss action
                  // WHY fire-and-forget backend call with toast: the endpoint
                  // `DELETE /v1/alerts/{id}` may not be deployed yet (§C.3).
                  // We do an optimistic local ACK + attempt backend delete.
                  // show a toast regardless so the user gets confirmation.
                  onDismiss={() => {
                    // Optimistic: ACK locally so the row disappears immediately.
                    handleAck(alert.alert_id);
                    // WHY cast to any: gateway doesn't expose deleteAlert yet (§C.3 backend gap).
                    // The optional-chain guard prevents a runtime crash; the cast silences TS.
                    // When the endpoint ships, replace with a properly typed gateway method.
                    // eslint-disable-next-line @typescript-eslint/no-explicit-any
                    const gw = createGateway(accessToken) as any;
                    if (typeof gw.deleteAlert === "function") {
                      void (gw.deleteAlert(alert.alert_id) as Promise<unknown>)
                        .catch(() => { /* ignore — backend endpoint may be absent */ });
                    }
                    toast("Alert dismissed");
                  }}
                  // PRD-0089 Wave J: hover View action — navigate to instrument page
                  // WHY only when entity_id is present: navigating to /instruments/undefined
                  // would 404. We check entity_id before providing the handler.
                  onView={alert.entity_id ? () => {
                    router.push(`/instruments/${alert.entity_id}`);
                  } : undefined}
                  localOnly={localOnlyIds.has(alert.alert_id)}
                  // PLAN-0053 T-F-6-03: bulk-select wiring. The checkbox is
                  // always rendered so the user can multi-select without a
                  // separate "enter selection mode" click — same affordance
                  // as Gmail / Slack inboxes.
                  selected={selectedIds.has(alert.alert_id)}
                  onToggleSelected={() => toggleSelected(alert.alert_id)}
                />
              ))}
            </ul>

          </div>
        );
      })}

      {/* ── Acknowledged section — collapsed by default ───────────────────── */}
      {acknowledgedAlerts.length > 0 && (
        <div>

          {/* Acknowledged group header — collapsible */}
          <button
            type="button"
            className={cn(
              "sticky top-0 z-10 flex h-6 w-full items-center justify-between border-b border-border",
              "bg-background px-2 text-[10px] uppercase tracking-[0.08em] text-muted-foreground",
            )}
            onClick={() => setAckCollapsed((prev) => !prev)}
            aria-expanded={!ackCollapsed}
          >
            <span>
              Acknowledged ({acknowledgedAlerts.length})
            </span>
            {/* WHY chevron: communicates collapsibility per affordance convention */}
            <span className="font-mono text-[10px] text-muted-foreground/60">
              {ackCollapsed ? "▸" : "▾"}
            </span>
          </button>

          {/* Acknowledged rows — hidden when collapsed */}
          {!ackCollapsed && (
            <ul className="divide-y divide-border/30 opacity-50" role="list" aria-label="Acknowledged alerts">
              {acknowledgedAlerts.map((alert) => (
                <AlertRow
                  key={alert.alert_id}
                  alert={alert}
                  onSelect={() => handleSelect(alert.alert_id)}
                  onAck={() => handleAck(alert.alert_id)}
                  onSnooze={(minutes) => handleSnooze(alert.alert_id, minutes)}
                  localOnly={localOnlyIds.has(alert.alert_id)}
                  dimmed
                />
              ))}
            </ul>
          )}

        </div>
      )}

      {/* PLAN-0048 Wave B-3: AlertDetailSheet is rendered alongside the list so
          the detail panel slides in over the page when ?selected={id} is in the
          URL. We resolve the selected Alert from the loaded data here so the
          sheet has access to ack/snooze handlers + the full payload. */}
      <AlertDetailSheet
        alert={selectedAlert}
        open={Boolean(selectedAlert)}
        onClose={handleCloseSheet}
        onAck={handleAck}
        onSnooze={handleSnooze}
      />

    </div>
  );
}

// ── AlertRow sub-component ────────────────────────────────────────────────────

/**
 * AlertRow — single alert with severity dot, ticker, type, body, time, ACK dropdown.
 *
 * WHY ACK DropdownMenu (not two separate buttons): a single dropdown for
 * Acknowledge + Snooze options keeps the row compact (single ACK ▾ button)
 * while exposing multiple time-window snooze choices.
 */
export interface AlertRowProps {
  alert: Alert;
  /** Open the detail sheet for this alert (PLAN-0048 Wave B-3). */
  onSelect: () => void;
  onAck: () => void;
  onSnooze: (minutes: number) => void;
  /**
   * PRD-0089 Wave J: called when the user clicks "Dismiss" in the hover action strip.
   * Maps to DELETE /v1/alerts/{id}. Stub (no-op + toast) when the backend is absent.
   */
  onDismiss?: () => void;
  /**
   * PRD-0089 Wave J: called when the user clicks "View" in the hover action strip.
   * Navigates to the instrument page for alert.entity_id. No-op when entity_id absent.
   */
  onView?: () => void;
  /**
   * PLAN-0051 T-D-4-03: when true, render a "(local only)" badge next to the
   * alert label so the user knows the ACK/snooze didn't sync to the backend.
   */
  localOnly?: boolean;
  /**
   * PLAN-0051 T-D-4-03: when true, dim the row (opacity-60) — used by the
   * Snoozed tab so muted rows still appear but recede visually.
   */
  dimmed?: boolean;
  /** PLAN-0053 T-F-6-03: row is in the bulk-select set. */
  selected?: boolean;
  /** PLAN-0053 T-F-6-03: parent toggles bulk-select for this row. */
  onToggleSelected?: () => void;
}

/**
 * minutesUntilEndOfDay — quick-snooze helper for the "until EOD" option.
 *
 * WHY local time: end-of-day means "the user's evening", not 00:00 UTC. We
 * compute a local Date for tonight at 23:59 and diff against now.
 *
 * WHY exported: the Snooze popover composer in AlertRow + the AlertDetailSheet
 * footer (future) both need the same value.
 */
export function minutesUntilEndOfDay(now: Date = new Date()): number {
  const eod = new Date(now);
  eod.setHours(23, 59, 0, 0);
  return Math.max(1, Math.round((eod.getTime() - now.getTime()) / 60_000));
}

export function AlertRow({
  alert,
  onSelect,
  onAck,
  onSnooze,
  onDismiss,
  onView,
  localOnly,
  dimmed,
  selected = false,
  onToggleSelected,
}: AlertRowProps) {
  // F-302 follow-up: backend severity may arrive lowercase. SEV_DOT_COLOR is
  // keyed by the uppercase union — looking up `alert.severity` directly when
  // the value is "low" returns undefined and renders an unstyled bg. Normalise
  // once here so the dot is always coloured correctly.
  const severityKey = ((alert.severity ?? "").toUpperCase() || "LOW") as AlertSeverity;

  // ── Derived row columns (roadmap item #2 / A-1 / B2) ──────────────────────
  // WHY compute these once, up-front: the row is rendered ~30× and these pure
  // helpers walk the fallback ladder; computing them here keeps the JSX terse
  // and makes the "what each column shows" contract explicit.
  //
  //   subject  → the ticker / entity the alert is about (own column).
  //   typeLabel→ humanised alert_type ("GRAPH CHANGE") for the TYPE chip.
  //   summary  → the one-line "what changed" string that fills the dead band.
  const subject = alertSubject(alert);
  const typeLabel = humaniseAlertType(alert.alert_type);
  const summary = alertSummary(alert);

  return (
    <li>
      {/* WHY flex h-[22px]: terminal 22px row per §0 quality rules.
          dimmed=true (snoozed / acked) drops opacity to 60% so the row
          remains scannable but visibly de-emphasised.

          A-2 left severity stripe: border-l-2 + a per-severity colour turns the
          list into a scannable vertical band of severity — the eye finds the
          cluster of red CRITICAL stripes without reading any text. */}
      <div
        className={cn(
          // WHY group: Tailwind group enables group-hover:flex on the action strip
          // children, so Dismiss/Snooze/View appear ONLY on row hover.
          "group flex h-[22px] w-full items-center gap-2 border-b border-l-2 border-border/30 px-2 hover:bg-muted/40",
          // A-2: the left edge carries the severity colour (stripe).
          SEV_STRIPE_COLOR[severityKey],
          dimmed && "opacity-60",
          // PLAN-0053 T-F-6-03: tint selected rows so the bulk set is visible
          // even when the checkbox column scrolls out of view (rare in this
          // layout but cheap to express).
          selected && "bg-primary/5",
        )}
      >

        {/* PLAN-0053 T-F-6-03: bulk-select checkbox.
            WHY only render when onToggleSelected is provided: the same AlertRow
            component is reused for the Acknowledged group where bulk-select
            doesn't make sense (those alerts are already done). */}
        {onToggleSelected && (
          <input
            type="checkbox"
            checked={selected}
            onChange={onToggleSelected}
            // WHY stopPropagation: clicking the checkbox should NOT also fire
            // the row's onSelect (which would open the AlertDetailSheet).
            onClick={(e) => e.stopPropagation()}
            className="h-3 w-3 shrink-0 accent-primary"
            aria-label={`Select alert ${alert.alert_id}`}
          />
        )}

        {/* Severity dot — quick visual severity scan (kept alongside the badge:
            the dot is the fast pre-attentive cue, the badge is the explicit
            label for users who read it). */}
        <span className={cn("h-1.5 w-1.5 shrink-0 rounded-full", SEV_DOT_COLOR[severityKey])} />

        {/* A-2: severity badge is now VISIBLE (was sr-only). The audit flagged
            that "all rows read the same muted tone despite a MEDIUM label" — the
            coloured chip carries the severity palette into the row body so a
            scan distinguishes CRIT/HIGH/MED/LOW at a glance. A fixed-width
            wrapper keeps the following columns aligned across rows.
            WHY pass the normalised uppercase key: SeverityBadge's lookup tables
            are keyed by the uppercase union even when the backend sends "low"
            (F-302). This also satisfies the tests asserting on CRIT/HIGH/MED. */}
        <span className="flex w-[40px] shrink-0 justify-start">
          <SeverityBadge severity={severityKey} size="sm" />
        </span>

        {/* Subject column — ticker / entity the alert is about. Fixed width +
            tabular-nums so tickers line up vertically into a scannable column.
            Renders the `—` null sentinel (DESIGN_SYSTEM) when no subject is
            known, instead of collapsing the column and misaligning the row.
            WHY rendered exactly once: the previous row rendered the raw ticker
            here AND repeated it inside the body string — duplication that broke
            single-match `getByText("AAPL")` scans and wasted width. */}
        <span
          className={cn(
            "w-[52px] shrink-0 truncate font-mono text-[10px] font-semibold tabular-nums",
            subject ? "text-foreground" : "text-muted-foreground/50",
          )}
          title={subject ?? undefined}
        >
          {subject ?? "—"}
        </span>

        {/* TYPE chip — humanised alert_type as a compact classifier tag. Fixed
            width keeps the summary column's left edge aligned across all rows
            (the core "scannable feed" requirement). uppercase + tracking reads
            as a field code, not prose. */}
        <span
          className="w-[88px] shrink-0 truncate text-[9px] uppercase tracking-[0.06em] text-muted-foreground"
          title={typeLabel || undefined}
        >
          {typeLabel || "—"}
        </span>

        {/* "What changed" summary — the one-line body that fills the previously
            dead horizontal band, making each row differentiated and scannable
            (roadmap item #2 / A-1 / B2). Sourced from alert.body when present,
            otherwise composed via the SAME formatAlertTitle ladder the sidebar
            ALARMS panel uses, so the surfaces never drift and a bare
            "<SEVERITY> signal" string can never appear.

            Click opens AlertDetailSheet via the URL ?selected= contract (B-3)
            rather than navigating away — the trader keeps the list in view
            behind the sheet. */}
        <button
          type="button"
          onClick={onSelect}
          className="min-w-0 flex-1 truncate text-left text-[11px] text-foreground"
          title={summary}
          aria-label={`Open alert ${alert.alert_id}`}
        >
          {summary}
        </button>

        {/* Relative timestamp */}
        <time
          dateTime={alert.created_at}
          className="shrink-0 font-mono text-[10px] tabular-nums text-muted-foreground"
        >
          {formatRelativeTime(alert.created_at)}
        </time>

        {/* localOnly badge — surfaces when ACK/snooze couldn't sync to backend */}
        {localOnly && (
          <span
            className="shrink-0 rounded-[2px] border border-border/40 px-1 text-[9px] uppercase tracking-[0.08em] text-muted-foreground/80"
            title="Stored in browser only — backend endpoint not yet shipped"
          >
            local only
          </span>
        )}

        {/* ── PRD-0089 Wave J: hover action strip ─────────────────────────── */}
        {/*
         * WHY hidden by default / shown on group-hover: the row is already dense
         * (22px). Showing action buttons only on hover preserves readability when
         * scanning the full list — the buttons appear precisely when the user's
         * pointer indicates intent to act.
         *
         * WHY group-hover:flex (not group-hover:block): the strip is a flex row
         * of three buttons that need to lay out side by side.
         *
         * WHY absolute positioning (right-side push via ml-auto): the actions
         * overlay the rightmost portion of the row rather than pushing content
         * left, which would cause the row to re-flow on hover.
         */}
        <div className="ml-auto hidden shrink-0 items-center gap-1 group-hover:flex">

          {/* Dismiss button — calls onDismiss (DELETE /v1/alerts/{id}) */}
          {onDismiss && (
            <button
              type="button"
              onClick={(e) => { e.stopPropagation(); onDismiss(); }}
              className="rounded-[2px] border border-border/40 bg-muted/40 px-1.5 text-[9px] uppercase
                         tracking-[0.06em] text-muted-foreground hover:border-negative/40 hover:text-negative"
              aria-label="Dismiss this alert"
            >
              Dismiss
            </button>
          )}

          {/* Snooze quick-action (1h) — label omits "1h" to avoid collision with the
              dropdown's "Snooze 1h" menu item when both are rendered in the same tree. */}
          <button
            type="button"
            onClick={(e) => { e.stopPropagation(); onSnooze(60); }}
            className="rounded-[2px] border border-border/40 bg-muted/40 px-1.5 text-[9px] uppercase
                       tracking-[0.06em] text-muted-foreground hover:text-foreground"
            aria-label="Snooze this alert for 1 hour"
          >
            Snooze
          </button>

          {/* View button — navigate to instrument page for the alert's entity */}
          {onView && (
            <button
              type="button"
              onClick={(e) => { e.stopPropagation(); onView(); }}
              className="rounded-[2px] border border-border/40 bg-muted/40 px-1.5 text-[9px] uppercase
                         tracking-[0.06em] text-muted-foreground hover:text-foreground"
              aria-label="View instrument page for this alert"
            >
              View
            </button>
          )}
        </div>

        {/* ACK / Snooze dropdown.
            PLAN-0051 T-D-4-03: snooze options expanded to 15m/1h/EOD/24h
            plus a "Custom…" entry that pops a small datetime picker. The
            "until EOD" entry uses minutesUntilEndOfDay() so the duration
            scales with the time of day (morning → big, evening → tiny). */}
        <div className="relative shrink-0">
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              {/* WHY rounded-[2px]: design system 2px radius rule */}
              <button
                type="button"
                className="rounded-[2px] border border-border/40 bg-muted/40 px-1.5 text-[10px] text-muted-foreground hover:text-foreground"
                aria-label="Acknowledge or snooze alert"
              >
                ACK ▾
              </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem className="text-[11px]" onClick={onAck}>
                Acknowledge
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem
                className="text-[11px]"
                onClick={() => onSnooze(15)}
                aria-label="Snooze 15 minutes"
              >
                Snooze 15m
              </DropdownMenuItem>
              <DropdownMenuItem
                className="text-[11px]"
                onClick={() => onSnooze(60)}
              >
                Snooze 1h
              </DropdownMenuItem>
              {/* PLAN-0053 T-F-6-01: 4h is the most common "deferred response"
                  bucket per institutional UX research — long enough to skip a
                  market session, short enough to re-surface before close. */}
              <DropdownMenuItem
                className="text-[11px]"
                onClick={() => onSnooze(240)}
                aria-label="Snooze 4 hours"
              >
                Snooze 4h
              </DropdownMenuItem>
              <DropdownMenuItem
                className="text-[11px]"
                onClick={() => onSnooze(minutesUntilEndOfDay())}
                aria-label="Snooze until end of day"
              >
                Snooze until EOD
              </DropdownMenuItem>
              <DropdownMenuItem
                className="text-[11px]"
                onClick={() => onSnooze(1440)}
              >
                Snooze 24h
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              {/* Custom datetime picker — uses a native datetime-local prompt
                  so we don't pull in another popover dep. The picker is a
                  one-shot native dialog; cancel = no-op. */}
              <DropdownMenuItem
                className="text-[11px]"
                onSelect={(e) => {
                  // WHY preventDefault: we open a native prompt; without
                  // preventDefault the dropdown closes BEFORE the prompt
                  // appears and focus restoration becomes confusing.
                  e.preventDefault();
                  const value = window.prompt(
                    "Snooze until (YYYY-MM-DDTHH:MM, local time):",
                    new Date(Date.now() + 60 * 60_000).toISOString().slice(0, 16),
                  );
                  if (!value) return;
                  const target = new Date(value);
                  if (isNaN(target.getTime())) return;
                  const minutes = Math.max(1, Math.round((target.getTime() - Date.now()) / 60_000));
                  onSnooze(minutes);
                }}
                aria-label="Snooze custom datetime"
              >
                Snooze custom…
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>

      </div>

      {/* NOTE: the previously sr-only SeverityBadge (kept only so tests could
          assert on CRIT/HIGH/MED text) is gone — the badge is now rendered
          VISIBLY in the row body above (A-2), so the test assertions still find
          the CRIT/HIGH/MED text while users finally see the severity palette. */}

    </li>
  );
}
