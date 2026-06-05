/**
 * components/instrument/shared/DataTimestamp.tsx — "Data as of …" footer
 *
 * WHY THIS EXISTS: every data panel surfaces freshness so analysts can trust
 * (or distrust) the values. Centralises formatting and null-handling so
 * panels just pass an ISO timestamp. WHO USES IT: MetricsTable footer,
 * FlatMetricsGrid footer, IncomeStatementFY, ShareStatistics, etc.
 * DATA SOURCE: Pure presentational primitive (receives ISO string).
 * DESIGN REFERENCE: docs/specs/0088-…-redesign.md §6.11 (Time/source row).
 * TARGET READER: junior Next.js dev. Intl.DateTimeFormat = browser-native,
 * SSR-safe, no extra dep. API timestamps are always UTC (R7).
 */

interface DataTimestampProps {
  /** ISO 8601 timestamp string, or `null` if no data is available. */
  readonly updatedAt: string | null;
  /** Optional Tailwind overrides. */
  readonly className?: string;
}

const FORMATTER = new Intl.DateTimeFormat("en-US", { year: "numeric", month: "short", day: "numeric" });

export function DataTimestamp({ updatedAt, className = "" }: DataTimestampProps) {
  const text = updatedAt ? `Data as of ${FORMATTER.format(new Date(updatedAt))}` : "Data not yet available";
  return <p className={`text-[10px] text-muted-foreground px-3 py-2 ${className}`}>{text}</p>;
}
