/**
 * components/alerts/AlertDetailSheet.tsx — Right-anchored alert detail panel
 *
 * WHY THIS EXISTS (PLAN-0048 Wave B-3):
 * Before this wave, clicking an alert row navigated to /instruments/{entity_id},
 * which is a destructive context switch — the trader loses sight of their
 * other alerts. The Sheet keeps the AlertsList in view while exposing the full
 * payload, source event_id, related-entity link, and ack/snooze controls.
 *
 * URL CONTRACT: this component is *controlled* by the parent route via
 * ?selected={alert_id}. Closing the sheet (any path: ESC, X, overlay click)
 * MUST clear the param so refresh-friendly URLs round-trip cleanly.
 *
 * WHO USES IT: app/(app)/alerts/page.tsx (Wave B-3)
 * DATA SOURCE: receives the Alert object directly (already loaded by AlertsList).
 * DESIGN REFERENCE: PLAN-0048 §B-3 + DESIGN_SYSTEM.md §2-3 (Midnight Pro tokens).
 */

"use client";
// WHY "use client": uses Sheet (Radix Dialog client runtime) and onClose callbacks.

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { ExternalLink, MessageSquare, Plus, Settings } from "lucide-react";
import { Sheet, SheetContent, SheetDescription, SheetFooter, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Button } from "@/components/ui/button";
import { SeverityBadge } from "@/components/alerts/SeverityBadge";
import { RuleManagerDialog } from "@/components/alerts/RuleManagerDialog";
import { AddToWatchlistDialog } from "@/components/alerts/AddToWatchlistDialog";
import { formatRelativeTime, cn } from "@/lib/utils";
import type { Alert } from "@/types/api";

// ── Props ─────────────────────────────────────────────────────────────────────

/**
 * Props for AlertDetailSheet.
 *
 * WHY `alert` may be null: the sheet is mounted continuously by the page so we
 * can animate open/close. When `selectedId` doesn't match any loaded alert, we
 * pass null and the sheet stays closed.
 */
interface AlertDetailSheetProps {
  /** The selected alert, or null if none / not yet loaded. */
  alert: Alert | null;
  /** True when the sheet should be open. Driven by parent ?selected param. */
  open: boolean;
  /** Called when the user dismisses the sheet (ESC, X, overlay click, etc.). */
  onClose: () => void;
  /** Acknowledge the alert. Parent handles localStorage persistence (R19). */
  onAck: (alertId: string) => void;
  /** Snooze for `minutes` minutes. Parent handles localStorage persistence. */
  onSnooze: (alertId: string, minutes: number) => void;
}

// ── Component ─────────────────────────────────────────────────────────────────

export function AlertDetailSheet({ alert, open, onClose, onAck, onSnooze }: AlertDetailSheetProps) {
  // Derive enriched fields from the payload (PLAN-0048 Wave B-1).
  // WHY `as Record<string, unknown>` then cast each field: the DB stores the
  // payload as a free-form jsonb column. We narrow per-field to keep the
  // contract honest: any malformed shape just renders as missing/dash.
  const payload = (alert?.payload as Record<string, unknown> | undefined) ?? {};
  const entityName = typeof payload.entity_name === "string" ? payload.entity_name : null;
  const ticker = typeof payload.ticker === "string" ? payload.ticker : null;
  const signalLabel = typeof payload.signal_label === "string" ? payload.signal_label : null;
  const sourceEventId = typeof payload.event_id === "string" ? payload.event_id : null;

  return (
    <Sheet
      open={open}
      // WHY onOpenChange callback: Radix fires this for ALL close paths (X, ESC,
      // overlay). Routing the close through a single callback means the parent
      // only has to clear the URL param once.
      onOpenChange={(next) => {
        if (!next) onClose();
      }}
    >
      <SheetContent side="right" className="flex flex-col gap-0 p-0">

        {/* ── Header strip ────────────────────────────────────────────────── */}
        {/* WHY h-10 + border-b: matches terminal section-header convention used
            in DESIGN_SYSTEM §2 (sticky 24-40px header strip per panel). */}
        <SheetHeader className="border-b border-border px-4 py-2.5">
          <SheetTitle className="text-sm">
            {/* WHY the ticker (when present) leads — it's the primary identifier
                for traders, faster to scan than the canonical name */}
            {ticker ? (
              <span className="font-mono tabular-nums">{ticker}</span>
            ) : entityName ? (
              <span>{entityName}</span>
            ) : (
              <span className="text-muted-foreground">Alert detail</span>
            )}
            {alert && (
              <span className="ml-2 align-middle">
                <SeverityBadge severity={alert.severity} size="sm" />
              </span>
            )}
          </SheetTitle>
          <SheetDescription>
            {/* signal_label is the human-readable summary */}
            {signalLabel ?? alert?.alert_type ?? "—"}
          </SheetDescription>
        </SheetHeader>

        {/* ── Body — scrollable when payload is large ─────────────────────── */}
        {/* WHY flex-1 + overflow-y-auto: long jsonb payloads (e.g. graph events
            with many fields) shouldn't push the footer off-screen. */}
        <div className="flex-1 overflow-y-auto px-4 py-3">

          {/* PLAN-0051 T-D-4-05: Suggested Actions — quick links a trader runs
              after seeing an alert. Rendered above metadata so the most useful
              actions are immediately visible without scrolling. */}
          {alert && <SuggestedActions alert={alert} />}

          {!alert ? (
            // WHY this state exists: a deep-link to ?selected={id} where the id
            // hasn't been loaded yet (or has been ack-filtered out) renders an
            // explicit message rather than silently rendering an empty sheet.
            <p className="text-xs text-muted-foreground">
              Alert not found. It may have been acknowledged or expired.
            </p>
          ) : (
            <dl className="space-y-3 text-[11px]">

              {/* Top-of-fold summary fields */}
              <DetailRow label="Severity" value={alert.severity} />
              <DetailRow label="Alert type" value={alert.alert_type} />
              {entityName && <DetailRow label="Entity" value={entityName} />}

              {/* WHY tabular-nums on timestamps + IDs: monospace digit alignment
                  per CLAUDE.md (frontend constraints) — IDs don't visually drift. */}
              <DetailRow
                label="Created"
                value={
                  <span className="font-mono tabular-nums" title={alert.created_at}>
                    {formatRelativeTime(alert.created_at)}
                  </span>
                }
              />

              {sourceEventId && (
                <DetailRow
                  label="Source event"
                  value={
                    <span className="break-all font-mono tabular-nums text-muted-foreground">
                      {sourceEventId}
                    </span>
                  }
                />
              )}

              {alert.entity_id && (
                <DetailRow
                  label="Related"
                  value={
                    // WHY <Link> (not <a>): Next.js client-side nav avoids a
                    // full page reload — keeps Sheet animation snappy on close.
                    <Link
                      href={`/instruments/${encodeURIComponent(alert.entity_id)}`}
                      className="text-primary underline-offset-2 hover:underline"
                    >
                      View instrument →
                    </Link>
                  }
                />
              )}

              {/* Raw payload pretty-printed.
                  WHY collapsed under <details>: the average payload is 5-15
                  fields, but graph.state.changed events can have 30+. Collapsing
                  keeps the top-of-fold focused on the curated fields above. */}
              <details className="mt-2">
                <summary className="cursor-pointer select-none text-[10px] uppercase tracking-[0.08em] text-muted-foreground hover:text-foreground">
                  Raw payload
                </summary>
                <pre
                  // WHY whitespace-pre-wrap + break-all: JSON values can include
                  // long URLs/UUIDs that would otherwise overflow the viewport.
                  className={cn(
                    "mt-2 max-h-[40vh] overflow-auto rounded-[2px] border border-border/40 bg-muted/30",
                    "p-2 text-[10px] leading-tight text-muted-foreground",
                    "whitespace-pre-wrap break-all font-mono",
                  )}
                >
                  {JSON.stringify(alert.payload ?? {}, null, 2)}
                </pre>
              </details>
            </dl>
          )}
        </div>

        {/* ── Footer — Ack / Snooze buttons ───────────────────────────────── */}
        {/* WHY footer (not header): the actions are user-initiated and should
            be the last thing the user sees after reading the payload, matching
            the natural top-to-bottom reading flow. */}
        {alert && (
          <SheetFooter className="border-t border-border px-4 py-2.5">
            <Button
              variant="outline"
              size="sm"
              className="h-7 rounded-[2px] text-[11px]"
              onClick={() => onSnooze(alert.alert_id, 60)}
            >
              Snooze 1h
            </Button>
            <Button
              variant="outline"
              size="sm"
              className="h-7 rounded-[2px] text-[11px]"
              onClick={() => onSnooze(alert.alert_id, 1440)}
            >
              Snooze 24h
            </Button>
            <Button
              size="sm"
              className="h-7 rounded-[2px] text-[11px]"
              onClick={() => {
                onAck(alert.alert_id);
                onClose();
              }}
            >
              Acknowledge
            </Button>
          </SheetFooter>
        )}

      </SheetContent>
    </Sheet>
  );
}

// ── SuggestedActions (PLAN-0051 T-D-4-05) ────────────────────────────────────

/**
 * SuggestedActions — context-sensitive quick actions for the open alert.
 *
 * WHY four buttons (View / Watchlist / Rule / Chat): these are the most
 * common follow-ups after a trader inspects an alert. View Instrument is
 * the deep-dive; Add to Watchlist captures rising interest; Set Alert Rule
 * codifies "tell me again next time"; Open in Chat lets the AI summarise
 * context without leaving the desk.
 *
 * WHY DISABLED-WITH-TOOLTIP (rather than hidden): consistency — buttons
 * always present, but greyed-out when context is missing. This teaches
 * the user what's possible even when this particular alert can't trigger
 * the action.
 */
function SuggestedActions({ alert }: { alert: Alert }) {
  const router = useRouter();
  const [watchlistOpen, setWatchlistOpen] = useState(false);

  // Some alerts target an entity that isn't an instrument (e.g. macro events
  // with a region key, or graph events for sectors). The "View Instrument"
  // button must be disabled in that case.
  // WHY heuristic on entity_id: the typed Alert model doesn't carry
  // entity_type, so we infer "is instrument" from "entity_id present + ticker
  // present". Macro/region events have a non-empty entity_id but no ticker.
  const hasEntity = Boolean(alert.entity_id);
  const hasInstrument = hasEntity && Boolean(alert.ticker || (alert.payload?.ticker as string | undefined));
  const entityId = alert.entity_id;

  /** Navigate to /instrument/{entity_id}. Disabled when no instrument. */
  function handleViewInstrument() {
    if (!hasInstrument || !entityId) return;
    router.push(`/instruments/${encodeURIComponent(entityId)}`);
  }

  /**
   * handleOpenInChat — navigate to /chat with entity_id + a starter that
   * carries this specific alert id so the AI can fetch the full context.
   *
   * WHY query-string params (not POST body): /chat is a route, not an API.
   * A bookmarkable URL means the user can resume the conversation.
   */
  function handleOpenInChat() {
    const search = new URLSearchParams();
    if (entityId) search.set("entity_id", entityId);
    search.set("starter", `alert_${alert.alert_id}`);
    router.push(`/chat?${search.toString()}`);
  }

  return (
    <div className="mb-3 rounded-[2px] border border-border/40 bg-muted/10 p-2">
      <div className="mb-1.5 text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
        Suggested actions
      </div>
      <div className="flex flex-wrap gap-1">
        {/* View instrument — only when we know it's an instrument entity */}
        <ActionButton
          icon={<ExternalLink className="h-3 w-3" aria-hidden="true" />}
          label="View instrument"
          onClick={handleViewInstrument}
          disabled={!hasInstrument}
          disabledReason={!hasEntity ? "Alert has no entity" : "Entity is not an instrument"}
        />

        {/* Add to watchlist — needs an entity_id of any type */}
        <ActionButton
          icon={<Plus className="h-3 w-3" aria-hidden="true" />}
          label="Add to watchlist"
          onClick={() => setWatchlistOpen(true)}
          disabled={!hasEntity}
          disabledReason="Alert has no entity"
        />

        {/* Set alert rule — opens the manager pre-filled with the entity
            search if we have a ticker. */}
        <RuleManagerDialog
          prefillEntity={alert.ticker ?? undefined}
          trigger={
            <button
              type="button"
              className="flex items-center gap-1 rounded-[2px] border border-border/40 bg-muted/20 px-2 py-1 text-[10px] text-foreground hover:bg-muted/40"
            >
              <Settings className="h-3 w-3" aria-hidden="true" />
              Set alert rule
            </button>
          }
        />

        {/* Open in chat — requires an entity to be useful */}
        <ActionButton
          icon={<MessageSquare className="h-3 w-3" aria-hidden="true" />}
          label="Open in chat"
          onClick={handleOpenInChat}
          disabled={!hasEntity}
          disabledReason="Alert has no entity"
        />
      </div>

      {/* AddToWatchlist dialog — controlled */}
      <AddToWatchlistDialog
        open={watchlistOpen}
        onClose={() => setWatchlistOpen(false)}
        entityId={entityId}
        entityLabel={alert.ticker ?? alert.entity_name ?? null}
      />
    </div>
  );
}

/**
 * ActionButton — uniform button styling for the SuggestedActions row.
 *
 * WHY a sub-component: four variants share the same shape. Centralising the
 * disabled affordance here means every button gets the same tooltip pattern
 * for free.
 */
function ActionButton({
  icon,
  label,
  onClick,
  disabled,
  disabledReason,
}: {
  icon: React.ReactNode;
  label: string;
  onClick: () => void;
  disabled?: boolean;
  disabledReason?: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      title={disabled ? disabledReason : label}
      className={cn(
        "flex items-center gap-1 rounded-[2px] border border-border/40 px-2 py-1 text-[10px]",
        disabled
          ? "cursor-not-allowed bg-muted/10 text-muted-foreground/50"
          : "bg-muted/20 text-foreground hover:bg-muted/40",
      )}
      aria-label={label}
    >
      {icon}
      {label}
    </button>
  );
}

// ── DetailRow ────────────────────────────────────────────────────────────────

/**
 * DetailRow — label/value pair using <dt>/<dd> for semantic correctness.
 *
 * WHY a sub-component (not inline JSX): the same shape repeats 5+ times in the
 * sheet body and consistency in label width / font is easier to enforce here.
 */
function DetailRow({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-baseline gap-3">
      {/* w-24 keeps labels in a left-aligned column so values line up vertically.
          Uppercase + tracking matches DESIGN_SYSTEM §2 metadata pattern. */}
      <dt className="w-24 shrink-0 text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
        {label}
      </dt>
      <dd className="min-w-0 flex-1 text-[11px] text-foreground">{value}</dd>
    </div>
  );
}
