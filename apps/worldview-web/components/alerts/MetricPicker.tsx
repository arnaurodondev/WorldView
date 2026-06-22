/**
 * components/alerts/MetricPicker.tsx — fundamental-metric selector for the
 * FundamentalCross alert editor (PLAN-0113 Wave 4, T-4-02).
 *
 * WHY THIS EXISTS:
 * The FUNDAMENTAL_CROSS rule keys on a `metric_key` (e.g. "pe_ratio"). The
 * backend validates that key against S3's canonical fundamentals vocabulary
 * (`GET /v1/fundamentals/screen/fields`). If the UI offered a free-text box or a
 * hard-coded list, a typo'd / stale key would 400 at create time. This picker
 * fetches the SAME vocabulary the backend validates against and emits only
 * backend-valid `metric_key` values — eliminating that mismatch class entirely.
 *
 * WHY NOT hard-code from `features/screener/lib/filter-state.ts`:
 * That file is the screener's UI filter catalogue, which can drift from the S3
 * field metadata. The plan is explicit: read the live `screen/fields` source.
 *
 * WHY only `type === "number"` fields: a fundamental CROSS compares a metric to a
 * numeric threshold (above/below). String / select fields (sector, country) are
 * not "cross-able", so we filter them out of the options.
 *
 * DESIGN: native <select> at the project's h-7 / 11px form density (matches the
 * other alert editors). shadcn/ui Select is heavier than needed for a single
 * dropdown; the codebase uses native selects in the alert dialogs already.
 */

"use client";
// WHY "use client": uses useAuthedQuery (TanStack) — browser-only.

import { useAuthedQuery } from "@/lib/api-client";
import { qk } from "@/lib/query/keys";
import { DEFAULT_STALE } from "@/lib/api/_client";
import type { ScreenerField } from "@/types/api";

export interface MetricPickerProps {
  /** Currently-selected metric_key, or "" when nothing is chosen. */
  value: string;
  /** Called with a backend-valid metric_key when the user picks one. */
  onChange: (metricKey: string) => void;
}

/**
 * MetricPicker — dropdown of S3 fundamental metrics → emits a valid `metric_key`.
 */
export function MetricPicker({ value, onChange }: MetricPickerProps) {
  // Fetch the canonical screener field metadata (the same source the backend
  // validates `metric_key` against). 6h stale: field definitions almost never
  // change intra-day (matches DEFAULT_STALE.screenerFields).
  const { data, isLoading, isError } = useAuthedQuery<ScreenerField[]>({
    queryKey: qk.screener.fields(),
    queryFn: (gw) => gw.getScreenerFields(),
    staleTime: DEFAULT_STALE.screenerFields,
  });

  // Only numeric fields are "cross-able" against a threshold.
  const numericFields = (data ?? []).filter((f) => f.type === "number");

  return (
    <div className="flex flex-col gap-1">
      <label className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
        Metric
      </label>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        disabled={isLoading || isError}
        aria-label="Fundamental metric"
        className="h-7 rounded-[2px] border border-border bg-background px-2 text-[11px] text-foreground focus:outline-none focus:ring-1 focus:ring-primary disabled:text-[hsl(var(--disabled-foreground))] disabled:cursor-not-allowed"
      >
        {/* Placeholder option — value "" is not a valid metric_key, so the
            wizard's Save button stays disabled until a real metric is chosen. */}
        <option value="">
          {isLoading
            ? "Loading metrics…"
            : isError
              ? "Failed to load metrics"
              : "Select a metric…"}
        </option>
        {numericFields.map((f) => (
          // WHY value={f.name}: `name` is the canonical metric_key the backend
          // expects (e.g. "pe_ratio"); `label` is the human display string.
          <option key={f.name} value={f.name}>
            {f.label}
          </option>
        ))}
      </select>
    </div>
  );
}
