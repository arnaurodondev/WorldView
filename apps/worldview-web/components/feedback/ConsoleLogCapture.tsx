/**
 * components/feedback/ConsoleLogCapture.tsx — opt-in console buffer view.
 *
 * WHY THIS EXISTS (PLAN-0053 Wave G T-G-7-03):
 * Pairs with `useConsoleCapture` (the buffer hook). The hook records;
 * this component renders a tiny IDE-styled log preview AND owns the
 * opt-in checkbox. The FeedbackModal hands it the buffer + opt-in state.
 *
 * SECURITY: This is a thin display layer. The hook scrubs Bearer tokens
 * before storing — we render trusted-but-still-defensive (no
 * dangerouslySetInnerHTML, only text nodes).
 */

"use client";

import { useId } from "react";
import type { ConsoleEntry } from "@/hooks/useConsoleCapture";

export interface ConsoleLogCaptureProps {
  /** Whether the user has opted in to attach console logs. */
  enabled: boolean;
  /** Setter for the opt-in checkbox — passed up so the parent owns truth. */
  onEnabledChange: (next: boolean) => void;
  /** The captured entries (already trimmed to the last 50 by the hook). */
  logs: ConsoleEntry[];
  /** Empty the buffer — wired to the hook's `clear()` from the parent. */
  onClear: () => void;
}

/** Map a log level to a tailwind color so error / warn / log are distinct. */
const LEVEL_COLOR: Record<ConsoleEntry["level"], string> = {
  log: "text-muted-foreground",
  warn: "text-warning",
  error: "text-destructive",
};

export function ConsoleLogCapture({
  enabled,
  onEnabledChange,
  logs,
  onClear,
}: ConsoleLogCaptureProps) {
  const checkboxId = useId();

  return (
    <div className="space-y-2 rounded-[2px] border border-border bg-card/50 p-3">
      <div className="flex items-center justify-between">
        <label
          htmlFor={checkboxId}
          className="flex cursor-pointer items-center gap-2 text-xs font-medium text-foreground"
        >
          <input
            id={checkboxId}
            type="checkbox"
            checked={enabled}
            onChange={(e) => onEnabledChange(e.target.checked)}
            className="h-3.5 w-3.5"
          />
          Attach console logs (last {logs.length || 50})
        </label>
        {enabled && logs.length > 0 && (
          <button
            type="button"
            onClick={onClear}
            className="text-[10px] text-muted-foreground underline hover:text-foreground"
          >
            Clear
          </button>
        )}
      </div>

      {/* Help text — explains why we ask. */}
      <p className="text-[10px] text-muted-foreground">
        We capture browser console output (info, warnings, errors) so we can
        reproduce the issue. Sensitive tokens are auto-redacted. Logs are not
        stored until you submit.
      </p>

      {enabled && (
        <div
          className="max-h-32 overflow-y-auto rounded-[2px] bg-background/50 p-2 font-mono text-[10px] leading-tight"
          aria-label="Captured console output"
          // WHY tabular-nums on font-mono container: dense numeric output
          // (timestamps) lines up cleanly across rows.
          style={{ fontVariantNumeric: "tabular-nums" }}
        >
          {logs.length === 0 ? (
            <span className="text-muted-foreground">No console output yet…</span>
          ) : (
            logs.map((entry, i) => (
              <div
                key={`${entry.timestamp}-${i}`}
                className={LEVEL_COLOR[entry.level]}
              >
                <span className="text-muted-foreground">
                  [{new Date(entry.timestamp).toLocaleTimeString()}]
                </span>{" "}
                <span className="uppercase">{entry.level}</span>{" "}
                {/* WHY break-all: long stack traces would overflow horizontally. */}
                <span className="break-all">{entry.message}</span>
              </div>
            ))
          )}
        </div>
      )}
    </div>
  );
}
