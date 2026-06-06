/**
 * components/primitives/DataFreshnessPill.tsx — relative + absolute UTC pill
 *
 * WHY THIS EXISTS: PRD-0089 F1 §3.2 + FU-3.6 — every banner that exposes
 * "last updated" must show a relative phrase ("3 min ago") for quick
 * scanning and an absolute UTC tooltip ("2026-05-20 14:21:08 UTC") on
 * hover for analyst-precision. Bloomberg/Refinitiv banners follow the
 * same hybrid convention.
 * WHO USES IT: Quote tab brief banner, Financials updated-at footer,
 *   Intelligence brief footer, Portfolio overview banner.
 * DATA SOURCE: Caller passes a Date or ISO string from any endpoint that
 *   exposes a timestamp.
 * DESIGN REFERENCE: PRD-0089 F1 §3.2 (DataFreshnessPill row) + FU-3.6
 *   freshness conventions.
 */

import type { ReactNode } from "react";

interface DataFreshnessPillProps {
  /** Last-updated timestamp (Date or ISO string). */
  readonly lastUpdated: Date | string;
  /** Display mode. Defaults to "relative" with absolute as title=. */
  readonly format?: "relative" | "absolute";
}

function toDate(value: Date | string): Date {
  return value instanceof Date ? value : new Date(value);
}

// Build a short relative label from a delta in ms.  We deliberately stop
// at "d ago" — anything older deserves "stale", not a 14-day pill.
function relativeLabel(ms: number): string {
  if (ms < 0) return "just now";
  if (ms < 60_000) return `${Math.floor(ms / 1000)}s ago`;
  if (ms < 3_600_000) return `${Math.floor(ms / 60_000)}m ago`;
  if (ms < 86_400_000) return `${Math.floor(ms / 3_600_000)}h ago`;
  return `${Math.floor(ms / 86_400_000)}d ago`;
}

// Build the absolute UTC string Bloomberg-style: "YYYY-MM-DD HH:mm:ss UTC".
function absoluteUtc(d: Date): string {
  return `${d.toISOString().replace("T", " ").replace(/\.\d+Z$/, "")} UTC`;
}

export function DataFreshnessPill({ lastUpdated, format = "relative" }: DataFreshnessPillProps): ReactNode {
  const d = toDate(lastUpdated);
  if (Number.isNaN(d.getTime())) {
    return <span className="font-mono text-[10px] text-muted-foreground/50">—</span>;
  }
  const absolute = absoluteUtc(d);
  // Compute the relative phrase against "now" at render time. SSR will see
  // a slightly different value than CSR; that's acceptable for a freshness
  // pill — Next.js will hydrate and update on the next render tick.
  const ms = Date.now() - d.getTime();
  const display = format === "absolute" ? absolute : relativeLabel(ms);
  return (
    <span
      title={absolute}
      className="font-mono text-[10px] text-muted-foreground"
      aria-label={`Last updated ${absolute}`}
    >
      {display}
    </span>
  );
}
