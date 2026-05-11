/**
 * features/chat/components/ActionConfirmModal.tsx — Write-action confirmation modal
 *
 * WHY THIS EXISTS (PLAN-0082 Wave B):
 * When the LLM determines it needs to create an alert, it does NOT execute
 * the action directly. Instead, the backend (S8 ToolExecutor) emits a
 * ``pending_action`` SSE event containing a ``proposal_id`` and the full
 * action params. The frontend shows THIS modal, which lets the user review
 * exactly what will be created before committing.
 *
 * WHY EXPLICIT CONFIRMATION (not just execute silently):
 * Write actions (create_alert, future: place_order, etc.) have real side
 * effects — they create database rows and potentially trigger downstream
 * notifications. Silently executing them on the LLM's say-so would be
 * catastrophic if the LLM hallucinated a threshold or condition.  The
 * confirmation gate turns "what the LLM says" into "what the user explicitly
 * approved" — a critical distinction for a finance-grade terminal.
 *
 * DESIGN PATTERN (Terminal Dark):
 * - 2px border radius everywhere (no `rounded-lg`)
 * - 11px data text, 13px uppercase labels (Bloomberg terminal aesthetic)
 * - bg-muted/30 param rows (visible on dark background without harsh contrast)
 * - primary (#0EA5E9) for the Confirm button, destructive (#EF5350) for Cancel
 * - Monospace font for all data values (alert parameters are machine data)
 *
 * HOW IT WORKS:
 *   1. Chat page reads `pendingAction` from `useChatStream`.
 *   2. When non-null, renders this modal (open=true).
 *   3. On "Confirm": POST /api/v1/chat/proposals/{id}/confirm with params.
 *      The response is an SSE stream — we read it and emit action_executed
 *      or action_rejected toast notifications.
 *   4. On "Cancel" / Esc: calls `onDismiss` which calls `clearPendingAction`.
 *
 * WHY params come from the SSE event (not a server lookup):
 * The ToolExecutor (S8) has no Valkey access to store proposals server-side.
 * The proposal_id is a correlation token for logging; the actual params are
 * sent back to the confirm endpoint in the request body. The action is still
 * gated behind authentication — a bad actor cannot confirm without a valid JWT.
 * See proposal.py module docstring for the full rationale.
 *
 * ACCESSIBILITY:
 * - Radix Dialog handles focus trap and Escape key automatically
 * - All interactive elements have aria-labels
 * - Screen readers get the DialogTitle + DialogDescription (required by Radix)
 */

"use client";
// WHY "use client": uses useState for async loading state, reads browser fetch
// API, and manages modal open/close transitions via Radix Dialog. None of this
// runs in a Server Component.

import { useCallback, useState } from "react";
import { AlertTriangle, CheckCircle, XCircle } from "lucide-react";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

import type { PendingActionEvent } from "@/features/chat/lib/types";

// ── Props ─────────────────────────────────────────────────────────────────────

export interface ActionConfirmModalProps {
  /**
   * The pending action event received from the ``pending_action`` SSE event.
   *
   * WHY PendingActionEvent | null (not boolean):
   * The modal needs the full event payload to render the action details and
   * to submit the correct params to the confirm endpoint. Passing null means
   * "no pending action" — the modal is closed. This removes the need for a
   * separate `open` boolean prop.
   */
  pendingAction: PendingActionEvent | null;
  /**
   * Bearer token — forwarded to the confirm endpoint.
   *
   * WHY not use getGateway(): the gateway client does not yet have a typed
   * method for the proposal confirm endpoint (it streams SSE). We call fetch()
   * directly here, the same pattern as useChatStream, and need the token.
   */
  accessToken: string | null;
  /**
   * Called when the user cancels, presses Esc, or the action completes
   * (either executed or rejected). Clears the pending action state.
   */
  onDismiss: () => void;
}

// ── Human-readable labels ─────────────────────────────────────────────────────

/**
 * TOOL_LABELS — maps internal tool names to human-readable action titles.
 *
 * WHY a separate map (not use tool name directly): tool names are snake_case
 * internal identifiers ("create_alert"). The modal title should speak the
 * user's language ("Create Alert"). Single source of truth here means we
 * never show "create_alert" raw in the UI.
 */
const TOOL_LABELS: Record<string, string> = {
  create_alert: "Create Alert",
};

/**
 * PARAM_LABELS — maps alert parameter keys to display labels with units.
 *
 * WHY include units: "threshold: 200" is ambiguous without context.
 * "Threshold: { value: 200 }" makes the machine value legible to humans.
 * The analyst can verify "yes, I want to alert when price falls below $200".
 */
const PARAM_LABELS: Record<string, string> = {
  entity_id: "Entity ID",
  condition: "Condition",
  threshold: "Threshold",
  severity: "Severity",
};

// ── Severity badge styling ────────────────────────────────────────────────────

/**
 * severityClass — color token for the alert severity badge.
 *
 * Matches the AlertSeverity enum from S10 (LOW/MEDIUM/HIGH/CRITICAL).
 * WHY color-coded: analysts scanning a confirm dialog in a fast-moving
 * market need to parse severity at a glance — color communicates urgency
 * without requiring the user to read the text carefully.
 */
function severityClass(severity: string): string {
  switch (severity.toLowerCase()) {
    case "critical":
      return "text-destructive border-destructive/40 bg-destructive/10";
    case "high":
      // WHY text-warning (was off-palette text-orange-400): "high" sits
      // between "medium" (warning) and "critical" (destructive) — the
      // amber --warning token correctly signals elevated attention without
      // crossing into red destructive territory.
      return "text-warning border-warning/40 bg-warning/10";
    case "medium":
      return "text-warning border-warning/40 bg-warning/10";
    default: // "low"
      return "text-muted-foreground border-border bg-muted/30";
  }
}

// ── Component ─────────────────────────────────────────────────────────────────

/**
 * ActionConfirmModal — confirmation gate for write-action tool calls.
 *
 * Controlled by `pendingAction` from `useChatStream`. When pendingAction is
 * non-null, the modal opens with the action details. The user confirms or
 * cancels. On confirm, the modal calls POST /api/v1/chat/proposals/{id}/confirm
 * and streams the SSE response to show success or failure inline.
 */
export function ActionConfirmModal({
  pendingAction,
  accessToken,
  onDismiss,
}: ActionConfirmModalProps) {
  // ── Local state ────────────────────────────────────────────────────────────

  /**
   * status — tracks the async confirmation request lifecycle.
   *
   * WHY not use the generic loading/error from TanStack Query:
   * This is a one-shot mutation from a modal — no cache invalidation needed,
   * no retry logic, no background refetch. useState + fetch is simpler and
   * avoids the boilerplate of wiring a useMutation here. The result is
   * displayed inline in the modal before dismissal.
   */
  const [status, setStatus] = useState<"idle" | "loading" | "success" | "error">("idle");
  const [statusMessage, setStatusMessage] = useState<string>("");

  // ── Derived ────────────────────────────────────────────────────────────────

  // The modal is "open" when there is a pending action awaiting confirmation.
  const isOpen = pendingAction !== null;

  // Human-readable action title (e.g. "Create Alert") from the tool name.
  const actionTitle = pendingAction
    ? (TOOL_LABELS[pendingAction.tool] ?? pendingAction.tool)
    : "Action";

  // ── Handlers ───────────────────────────────────────────────────────────────

  /**
   * handleOpenChange — called by Radix Dialog on Esc or overlay click.
   *
   * WHY only handle `false` (close): the Dialog never opens from here —
   * it's controlled by `isOpen` which is derived from `pendingAction`. The
   * only close path we need to handle is the user pressing Esc or clicking
   * the overlay, both of which Radix fires as `onOpenChange(false)`.
   * We ignore `true` because we never call this to open the dialog.
   */
  function handleOpenChange(open: boolean) {
    if (!open && status !== "loading") {
      // Reset status so the modal starts clean on the next pending action.
      setStatus("idle");
      setStatusMessage("");
      onDismiss();
    }
  }

  /**
   * handleDismiss — explicit Cancel button handler.
   *
   * WHY not re-use handleOpenChange: same reasoning — explicit named function
   * for the Cancel button makes the intent clear in click handlers and tests.
   */
  function handleDismiss() {
    if (status === "loading") return; // Prevent cancel during in-flight request
    setStatus("idle");
    setStatusMessage("");
    onDismiss();
  }

  /**
   * handleConfirm — submit the confirmation to the backend SSE endpoint.
   *
   * FLOW:
   *   1. POST /api/v1/chat/proposals/{proposal_id}/confirm with params body.
   *   2. Read SSE stream — look for `action_executed` or `action_rejected`.
   *   3. Show inline success/error state, then auto-dismiss after 2s on success.
   *
   * WHY manual SSE parsing (not EventSource):
   * EventSource only supports GET. We need a POST with a JSON body — same
   * pattern as useChatStream. We hand-roll the SSE parser over fetch + ReadableStream.
   *
   * WHY /api/v1/... (S9 proxy route, not S8 direct):
   * R14 — frontend always calls S9. The Next.js rewrite maps /api → gateway:8000.
   * The S9 proxy route forwards to S8 which calls S10 to execute the alert.
   */
  const handleConfirm = useCallback(async () => {
    if (!pendingAction || !accessToken || status === "loading") return;

    setStatus("loading");
    setStatusMessage("");

    try {
      // ── Build request body ────────────────────────────────────────────────
      // Mirror the `ConfirmProposalRequest` schema from proposal.py.
      // All params come from the ``pending_action`` SSE event the hook received.
      const body = {
        tool_name: pendingAction.tool,
        entity_id: String(pendingAction.params.entity_id ?? ""),
        condition: String(pendingAction.params.condition ?? ""),
        threshold: (pendingAction.params.threshold as Record<string, unknown>) ?? {},
        severity: String(pendingAction.params.severity ?? "low"),
      };

      const response = await fetch(
        `/api/v1/chat/proposals/${pendingAction.proposal_id}/confirm`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Authorization: `Bearer ${accessToken}`,
          },
          body: JSON.stringify(body),
        },
      );

      if (!response.ok) {
        // Non-2xx means the gateway rejected the request before SSE started
        // (e.g. 422 Pydantic validation error, 401 JWT expired).
        const detail = await response.text().catch(() => "Unknown error");
        setStatus("error");
        setStatusMessage(`Request failed (${response.status}): ${detail}`);
        return;
      }

      if (!response.body) {
        setStatus("error");
        setStatusMessage("No response stream from server.");
        return;
      }

      // ── Parse SSE stream ──────────────────────────────────────────────────
      // The confirm endpoint returns an SSE stream (same format as chat/stream).
      // We read until we see `action_executed`, `action_rejected`, or `[DONE]`.
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let currentEvent = "";

      outer: while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });

        // SSE lines are separated by \n. Events are separated by \n\n.
        const lines = buffer.split("\n");
        // Keep the last incomplete line in the buffer.
        buffer = lines.pop() ?? "";

        for (const line of lines) {
          const trimmed = line.trimEnd();

          if (trimmed.startsWith("event:")) {
            // Track the event type for the next `data:` line.
            currentEvent = trimmed.slice(6).trim();
          } else if (trimmed.startsWith("data:")) {
            const raw = trimmed.slice(5).trim();

            // ── [DONE] sentinel ────────────────────────────────────────────
            if (raw === "[DONE]") {
              break outer;
            }

            // ── Parse JSON payload ─────────────────────────────────────────
            let parsed: Record<string, unknown> = {};
            try {
              parsed = JSON.parse(raw) as Record<string, unknown>;
            } catch {
              // Non-JSON data line — skip
              continue;
            }

            if (currentEvent === "action_executed") {
              // Success — alert was created.
              const result = parsed as { result?: { alert_id?: string; condition?: string } };
              const alertId = result.result?.alert_id ?? "unknown";
              setStatus("success");
              setStatusMessage(`Alert created successfully (ID: ${alertId})`);
              // Auto-dismiss after 2.5s so the user sees the success state.
              setTimeout(() => {
                setStatus("idle");
                setStatusMessage("");
                onDismiss();
              }, 2500);
              break outer;
            } else if (currentEvent === "action_rejected") {
              // Failure — alert was NOT created.
              const rejection = parsed as { reason?: string };
              const reason = rejection.reason ?? "unknown";
              setStatus("error");
              setStatusMessage(`Action rejected: ${reason}. Please try again.`);
              break outer;
            }

            // Reset event name after consuming its data line
            currentEvent = "";
          }
        }
      }
    } catch (err) {
      // Network error or reader failure — show human-readable message.
      const msg = err instanceof Error ? err.message : "Network error";
      setStatus("error");
      setStatusMessage(`Failed to confirm action: ${msg}`);
    }
  }, [pendingAction, accessToken, status, onDismiss]);

  // ── Render helpers ──────────────────────────────────────────────────────────

  /**
   * renderParamRow — renders one alert parameter as a labeled monospace row.
   *
   * WHY monospace for values: alert parameters (entity_id UUIDs, condition
   * strings, threshold numbers) are machine data that analysts need to scan
   * accurately. Monospace ensures columns align and prevents variable-width
   * characters from making a UUID look like a different string.
   */
  function renderParamRow(key: string, value: unknown) {
    const label = PARAM_LABELS[key] ?? key;
    // Format complex values (threshold dict) as compact JSON.
    const displayValue =
      typeof value === "object" && value !== null
        ? JSON.stringify(value)
        : String(value ?? "—");

    // Special rendering for severity — add a color badge.
    if (key === "severity") {
      return (
        <div
          key={key}
          className="flex items-baseline justify-between gap-4 rounded-[2px] bg-muted/30 px-3 py-1.5"
        >
          <span className="shrink-0 font-mono text-[10px] uppercase tracking-[0.06em] text-muted-foreground">
            {label}
          </span>
          {/* WHY inline badge for severity (not plain text): color communicates
              urgency at a glance — analysts need fast risk assessment. */}
          <span
            className={cn(
              "rounded-[2px] border px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-[0.04em]",
              severityClass(String(value ?? "low")),
            )}
          >
            {displayValue}
          </span>
        </div>
      );
    }

    return (
      <div
        key={key}
        className="flex items-baseline justify-between gap-4 rounded-[2px] bg-muted/30 px-3 py-1.5"
      >
        <span className="shrink-0 font-mono text-[10px] uppercase tracking-[0.06em] text-muted-foreground">
          {label}
        </span>
        <span className="max-w-[220px] truncate font-mono text-[11px] text-foreground">
          {displayValue}
        </span>
      </div>
    );
  }

  // ── Render ─────────────────────────────────────────────────────────────────

  return (
    <Dialog open={isOpen} onOpenChange={handleOpenChange}>
      <DialogContent
        // WHY max-w-md (448px): the modal needs to display a UUID (entity_id),
        // a condition string, and a JSON threshold dict. 384px (max-w-sm) clips
        // UUIDs; 448px fits them with the monospace font. Bloomberg panels use
        // ~440px for confirmation modals.
        className="max-w-md"
      >
        <DialogHeader>
          {/* WHY AlertTriangle icon inline: the action has real side effects.
              The icon reinforces "this needs your attention" without being
              alarming (we use the primary color, not destructive). */}
          <DialogTitle className="flex items-center gap-2">
            <AlertTriangle
              className="h-4 w-4 text-warning"
              strokeWidth={1.5}
              aria-hidden="true"
            />
            Confirm: {actionTitle}
          </DialogTitle>
          <DialogDescription className="text-[11px]">
            {/* Show the human-readable description from the SSE event
                (e.g. "Create a price_below alert for AAPL at $180"). If absent
                OR empty, show a generic prompt — the param rows below give the
                details. WHY || (not ??): `??` only guards null/undefined; an
                empty string "" falls through and displays a blank description.
                Using || catches both missing and empty cases. */}
            {pendingAction?.description ||
              "Review the action details below before confirming."}
          </DialogDescription>
        </DialogHeader>

        {/* ── Action parameters ──────────────────────────────────────────── */}
        {/* WHY show raw params: analysts must verify EXACTLY what will be
            created — condition, threshold value, and severity. A description-
            only modal could mask a threshold of $0.01 vs $180. Showing the
            machine params is the finance-grade transparency standard. */}
        {pendingAction && (
          <div className="space-y-1">
            <p className="font-mono text-[9px] uppercase tracking-[0.08em] text-muted-foreground/60">
              Action Parameters
            </p>
            <div className="space-y-0.5">
              {/* entity_id first — establishes what instrument is affected */}
              {renderParamRow("entity_id", pendingAction.params.entity_id)}
              {renderParamRow("condition", pendingAction.params.condition)}
              {renderParamRow("threshold", pendingAction.params.threshold)}
              {renderParamRow("severity", pendingAction.params.severity)}
            </div>
          </div>
        )}

        {/* ── Status feedback ────────────────────────────────────────────── */}
        {/* WHY inline status (not toast): the modal is already focused and the
            user is waiting for feedback. An inline status message in the modal
            is immediately visible without competing with other UI elements. */}
        {status === "success" && (
          <div className="flex items-start gap-2 rounded-[2px] border border-[hsl(var(--positive))]/30 bg-[hsl(var(--positive))]/10 p-2">
            <CheckCircle
              className="mt-0.5 h-3.5 w-3.5 shrink-0 text-[hsl(var(--positive))]"
              strokeWidth={1.5}
              aria-hidden="true"
            />
            <p className="text-[11px] text-[hsl(var(--positive))]">{statusMessage}</p>
          </div>
        )}

        {status === "error" && (
          <div className="flex items-start gap-2 rounded-[2px] border border-destructive/30 bg-destructive/10 p-2">
            <XCircle
              className="mt-0.5 h-3.5 w-3.5 shrink-0 text-destructive"
              strokeWidth={1.5}
              aria-hidden="true"
            />
            <p className="text-[11px] text-destructive">{statusMessage}</p>
          </div>
        )}

        {/* ── Footer ────────────────────────────────────────────────────── */}
        <DialogFooter className="mt-2">
          {/* Cancel — always available unless the request is in-flight.
              WHY disable during loading: prevents duplicate submissions and
              avoids a race where the user cancels while the SSE stream is
              mid-read (which would leave the abort unhandled). */}
          <Button
            variant="outline"
            size="sm"
            onClick={handleDismiss}
            disabled={status === "loading" || status === "success"}
            aria-label="Cancel action"
          >
            {status === "success" ? "Close" : "Cancel"}
          </Button>

          {/* Confirm — primary action. Hidden after success (modal auto-dismisses). */}
          {status !== "success" && (
            <Button
              size="sm"
              onClick={() => void handleConfirm()}
              disabled={status === "loading" || !accessToken}
              // WHY bg-primary (blue) not destructive (red): creating an alert is
              // a positive action — the user *wants* to be notified. Red would
              // imply danger. Blue matches the primary action semantics.
              className="bg-primary text-primary-foreground hover:bg-primary/90"
              aria-label="Confirm action"
            >
              {status === "loading" ? (
                // WHY inline spinner text (not a Spinner component): the Button
                // already has fixed size; adding a Spinner SVG would shift the
                // label. A simple text state change is the minimal feedback.
                "Confirming…"
              ) : status === "error" ? (
                "Retry"
              ) : (
                "Confirm"
              )}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
