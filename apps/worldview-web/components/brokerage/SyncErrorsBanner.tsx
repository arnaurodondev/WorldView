/**
 * SyncErrorsBanner — expandable warning banner for SnapTrade sync errors
 *
 * WHY THIS EXISTS: SnapTrade sync errors are non-blocking — a connection
 * continues syncing even if some transactions fail (e.g., unknown instrument,
 * unsupported transaction type). The user should be aware of errors but NOT
 * alarmed: these are warnings, not failures. The banner renders nothing when
 * there are no errors, so it only appears when action is warranted.
 *
 * WHY AMBER (not red): Red signals a critical failure requiring immediate
 * action. Amber communicates "something needs attention when convenient" —
 * the correct tone for partial sync errors that don't block the connection.
 *
 * COLLAPSE BEHAVIOUR: errors are collapsed by default to keep the UI compact.
 * Most users will see 0–1 errors; the expand is for debugging/transparency.
 *
 * WHO USES IT: components/brokerage/ConnectedBrokeragesList.tsx (per-row banner)
 * DATA SOURCE: hooks/use-brokerage-connections.ts → useSyncErrors
 * DESIGN REFERENCE: PRD-0022 §6.6
 */

"use client";
// WHY "use client": uses useState for expand/collapse and useSyncErrors (useQuery).

import { useState } from "react";
import { ChevronDown, ChevronUp, AlertTriangle } from "lucide-react";
import { useSyncErrors } from "@/hooks/use-brokerage-connections";
import { formatDateTime } from "@/lib/utils";

// ── Error type metadata ───────────────────────────────────────────────────────

/**
 * ERROR_TYPE_META — labels + transience flag for each sync error type
 *
 * WHY isTransient matters: finance users need to know whether to WAIT or ACT.
 *   isTransient=true  → error will resolve automatically on the next sync cycle
 *                       (e.g., market-data service was temporarily down)
 *   isTransient=false → transaction was permanently skipped and needs manual review
 *                       (e.g., instrument symbol not known to this platform)
 *
 * WHY a lookup (not inline switch): adding a new error type from S9 only
 * requires adding an entry here, not changing JSX. TypeScript's Partial<>
 * + fallback ensures unknown future types still render gracefully.
 */
const ERROR_TYPE_META: Partial<Record<string, { label: string; isTransient: boolean }>> = {
  unknown_instrument: { label: "Unknown instruments", isTransient: false },
  unsupported_type: { label: "Unsupported transaction types", isTransient: false },
  // api_error is transient — it occurs when market-data service is temporarily
  // unreachable during instrument resolution; next cycle will retry automatically.
  api_error: { label: "Service errors", isTransient: true },
  validation_error: { label: "Validation errors", isTransient: false },
};

function getErrorTypeMeta(errorType: string): { label: string; isTransient: boolean } {
  return ERROR_TYPE_META[errorType] ?? { label: errorType, isTransient: false };
}

function getErrorTypeLabel(errorType: string): string {
  return getErrorTypeMeta(errorType).label;
}

// ── ErrorRow — single error entry in the expanded list ───────────────────────

/**
 * ErrorRow — renders one sync error with type label, detail, and debug info.
 * Extracted to keep the expanded-list JSX clean and avoid repeating the row
 * structure for both transient and permanent groups.
 */
function ErrorRow({ err }: { err: { id: string; error_type: string; error_detail: string | null; snaptrade_transaction_id: string; created_at: string } }) {
  return (
    <div className="border-b border-border/30 pb-1.5 last:border-0 last:pb-0">
      {/* Error type label */}
      <p className="text-xs font-medium text-foreground">
        {getErrorTypeLabel(err.error_type)}
      </p>
      {/* Human-readable detail — may be null for api_error type */}
      {err.error_detail && (
        <p className="font-mono text-[10px] tabular-nums text-muted-foreground">
          {err.error_detail}
        </p>
      )}
      {/* SnapTrade TX ID (truncated) + timestamp — for debugging / support */}
      <div className="mt-0.5 flex items-center gap-2">
        <span className="font-mono text-[9px] tabular-nums text-muted-foreground/60">
          {/* WHY truncate: SnapTrade IDs are long UUIDs; 8 chars enough for correlation */}
          txn: {err.snaptrade_transaction_id.slice(0, 8)}…
        </span>
        <span className="font-mono text-[9px] tabular-nums text-muted-foreground/60">
          {formatDateTime(err.created_at)}
        </span>
      </div>
    </div>
  );
}

// ── Component ─────────────────────────────────────────────────────────────────

interface SyncErrorsBannerProps {
  /** The connection to fetch errors for. Must be non-empty. */
  connectionId: string;
}

export function SyncErrorsBanner({ connectionId }: SyncErrorsBannerProps) {
  const { data: errors, isLoading } = useSyncErrors(connectionId);

  // WHY collapsed by default: errors are secondary information. The user's
  // primary focus is the connection status and sync actions. They expand
  // the list when they specifically want to investigate error details.
  const [expanded, setExpanded] = useState(false);

  // ── Render nothing while loading or when no errors exist ─────────────────
  // WHY null instead of a loading skeleton: the banner is secondary UI.
  // A loading skeleton here would be distracting if the connection row
  // above it is already showing meaningful data.
  if (isLoading || !errors || errors.length === 0) {
    return null;
  }

  // ── Compute summary for the collapsed header ─────────────────────────────
  // Group errors by type to show a concise "2 unknown instruments, 1 api error" summary
  const errorCounts: Record<string, number> = {};
  for (const err of errors) {
    errorCounts[err.error_type] = (errorCounts[err.error_type] ?? 0) + 1;
  }

  // Build "2 unknown instruments, 1 validation error" summary string
  const summary = Object.entries(errorCounts)
    .map(([type, count]) => `${count} ${getErrorTypeLabel(type).toLowerCase()}`)
    .join(", ");

  // Most recent error — shown in header when collapsed
  const mostRecentError = errors[0];

  return (
    <div
      className="rounded-md border px-3 py-2"
      // WHY inline styles for amber: the amber palette isn't in the standard
      // Tailwind config (which has destructive/red for errors). These exact
      // hex values match the design system's warning amber specification.
      style={{
        borderColor: "rgba(245,158,11,0.3)",
        backgroundColor: "rgba(245,158,11,0.07)",
      }}
    >
      {/* ── Header row — always visible ────────────────────────────────── */}
      <button
        type="button"
        className="flex w-full items-center gap-2 text-left"
        onClick={() => setExpanded((prev) => !prev)}
        aria-expanded={expanded}
        // WHY aria-label: icon + text is the primary content; the label
        // gives assistive technology the full action description.
        aria-label={expanded ? "Collapse sync errors" : "Expand sync errors"}
      >
        {/* Warning triangle — amber matches the banner background */}
        <AlertTriangle
          className="h-3.5 w-3.5 shrink-0"
          aria-hidden="true"
          style={{ color: "#F59E0B" }}
        />

        {/* Summary — error count + types */}
        <span className="flex-1 text-xs" style={{ color: "#F59E0B" }}>
          {/* WHY show count first: professionals scan for "how many" before "what kind" */}
          <span className="font-semibold">{errors.length} sync error{errors.length !== 1 ? "s" : ""}</span>
          {!expanded && (
            // Show summary only when collapsed — expanded view has the full list
            <span className="ml-1 text-muted-foreground">
              ({summary})
            </span>
          )}
        </span>

        {/* Expand/collapse chevron */}
        {expanded ? (
          <ChevronUp className="h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden="true" />
        ) : (
          <ChevronDown className="h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden="true" />
        )}
      </button>

      {/* ── Most recent error preview (collapsed only) ──────────────────── */}
      {!expanded && mostRecentError.error_detail && (
        <p className="mt-1 truncate font-mono text-[10px] tabular-nums text-muted-foreground">
          Latest: {mostRecentError.error_detail}
        </p>
      )}

      {/* ── Expanded error list ──────────────────────────────────────────── */}
      {expanded && (
        <div className="mt-2 space-y-3">
          {/* WHY split into transient / permanent groups: finance users need to
              know immediately whether to WAIT (transient — retry is automatic)
              or ACT (permanent — requires investigation or manual entry). Mixing
              both in a single flat list obscures this critical signal. */}

          {/* Transient errors — will resolve on next sync cycle */}
          {errors.some((e) => getErrorTypeMeta(e.error_type).isTransient) && (
            <div>
              <p className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                Transient — will retry automatically
              </p>
              {errors
                .filter((e) => getErrorTypeMeta(e.error_type).isTransient)
                .map((err) => (
                  <ErrorRow key={err.id} err={err} />
                ))}
            </div>
          )}

          {/* Permanent errors — require manual review */}
          {errors.some((e) => !getErrorTypeMeta(e.error_type).isTransient) && (
            <div>
              <p className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                Requires review — transactions were skipped
              </p>
              {errors
                .filter((e) => !getErrorTypeMeta(e.error_type).isTransient)
                .map((err) => (
                  <ErrorRow key={err.id} err={err} />
                ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
