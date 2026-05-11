/**
 * components/intelligence/KeyMetricsGrid.tsx — 2-column key metrics display
 * (PLAN-0074 Wave H T-H-05)
 *
 * WHY THIS EXISTS:
 * Entity intelligence includes entity-type-specific key metrics (e.g., for
 * a company: revenue, market cap, employee count; for a person: role, tenure).
 * The 2-column grid layout is the Bloomberg-standard way to display named
 * key/value pairs compactly in a sidebar — scannable in a glance.
 *
 * WHY 2-column (not a table):
 * A CSS grid with 2 equal columns is more responsive than a <table> in a
 * narrow sidebar. When the sidebar shrinks, grid cells wrap naturally without
 * horizontal scrollbars or overflowing text.
 *
 * WHY render unknown values:
 * key_metrics is Record<string, unknown> — S7 can store arbitrary enrichment
 * data. We render all values as strings, which handles null, numbers, booleans,
 * and short strings safely. Long values are truncated with a title tooltip.
 *
 * WHO USES IT: EntitySidebar key metrics section
 * DATA SOURCE: key_metrics from useEntityIntelligence
 */

// WHY no "use client": pure props display.

// ── Props ─────────────────────────────────────────────────────────────────────

interface KeyMetricsGridProps {
  metrics: Record<string, unknown>;
  className?: string;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

/**
 * formatMetricValue — convert unknown metric values to display strings.
 *
 * WHY: key_metrics can contain null, numbers, booleans, strings, arrays.
 * Components cannot render React elements from `unknown` directly — we need
 * to normalise to a string representation first.
 */
function formatMetricValue(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (typeof value === "number") {
    // WHY toLocaleString: large numbers like 150000000 are unreadable.
    // Intl.NumberFormat adds commas: "150,000,000"
    return value.toLocaleString("en-US", { maximumFractionDigits: 4 });
  }
  if (Array.isArray(value)) return value.join(", ");
  return String(value);
}

/**
 * formatMetricKey — convert snake_case keys to Title Case display labels.
 * "employee_count" → "Employee Count"
 */
function formatMetricKey(key: string): string {
  return key
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

// ── Component ─────────────────────────────────────────────────────────────────

export function KeyMetricsGrid({ metrics, className = "" }: KeyMetricsGridProps) {
  const entries = Object.entries(metrics);

  if (entries.length === 0) {
    return (
      <p className="text-[11px] text-muted-foreground font-mono italic">
        No key metrics available
      </p>
    );
  }

  return (
    // WHY grid-cols-2: two equal columns fit the sidebar width while keeping
    // label/value pairs horizontally adjacent for quick scanning.
    <div
      className={`grid grid-cols-2 gap-x-3 gap-y-1.5 ${className}`}
      aria-label="Key metrics"
    >
      {entries.map(([key, value]) => {
        const displayKey = formatMetricKey(key);
        const displayValue = formatMetricValue(value);

        return (
          // WHY contents (not a cell wrapper): CSS grid needs direct children as
          // cells. Using <React.Fragment key={key}> with "display:contents" child
          // lets each key-value pair span two adjacent cells correctly.
          <div key={key} className="contents">
            {/* Label cell */}
            <dt className="text-[10px] font-mono uppercase tracking-wider text-muted-foreground truncate self-center">
              {displayKey}
            </dt>
            {/* Value cell */}
            <dd
              className="text-[11px] font-mono tabular-nums text-foreground/90 truncate self-center"
              title={displayValue}
            >
              {displayValue}
            </dd>
          </div>
        );
      })}
    </div>
  );
}
