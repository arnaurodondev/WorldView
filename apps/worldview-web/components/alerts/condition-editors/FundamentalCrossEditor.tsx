/**
 * components/alerts/condition-editors/FundamentalCrossEditor.tsx — FUNDAMENTAL_CROSS
 * editor (PLAN-0113 Wave 4, T-4-04).
 *
 * Emits `{ instrument_id, metric_key, operator, value }`
 * (PRD §6.5.3 FundamentalCrossCondition):
 *   - instrument_id : shared InstrumentPicker (real S3 id)
 *   - metric_key    : shared MetricPicker (backend-valid S3 vocabulary key)
 *   - operator      : "above" | "below"
 *   - value         : the threshold (any number — e.g. P/E 25)
 *
 * Emits `null` while incomplete (no instrument, no metric, or blank value).
 */

"use client";
// WHY "use client": useState + useEffect (controlled form state).

import { useEffect, useState } from "react";
import { InstrumentPicker, type ChosenInstrument } from "@/components/common/InstrumentPicker";
import { MetricPicker } from "@/components/alerts/MetricPicker";
import type { CrossOperator, FundamentalCrossCondition } from "@/lib/api/alertRules";
import type { ConditionEditorProps } from "./types";

export function FundamentalCrossEditor({
  value,
  names,
  onChange,
  onNamesChange,
}: ConditionEditorProps<FundamentalCrossCondition>) {
  // value may be a PARTIAL prefill (Wave 5) — read each field defensively.
  const [instrument, setInstrument] = useState<ChosenInstrument | null>(
    value?.instrument_id
      ? {
          instrumentId: value.instrument_id,
          ticker: names?.[value.instrument_id] ?? "",
          name: names?.[value.instrument_id] ?? value.instrument_id,
        }
      : null,
  );
  const [metricKey, setMetricKey] = useState<string>(value?.metric_key ?? "");
  const [operator, setOperator] = useState<CrossOperator>(value?.operator ?? "below");
  // WHY string state: see PriceCrossEditor — keeps an empty input distinct from 0.
  // Note: fundamental values can legitimately be negative (e.g. negative EPS), so
  // we do NOT require value > 0 here, only that it is a finite number.
  const [valueStr, setValueStr] = useState<string>(
    value?.value != null ? String(value.value) : "",
  );

  useEffect(() => {
    const numeric = Number(valueStr);
    const complete =
      instrument !== null &&
      metricKey.trim() !== "" &&
      valueStr.trim() !== "" &&
      Number.isFinite(numeric);
    onChange(
      complete
        ? {
            instrument_id: instrument!.instrumentId,
            metric_key: metricKey,
            operator,
            value: numeric,
          }
        : null,
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps -- onChange stable parent cb.
  }, [instrument, metricKey, operator, valueStr]);

  // Report the live-picked instrument's display name for the wizard NL summary.
  useEffect(() => {
    if (instrument) {
      onNamesChange?.({ [instrument.instrumentId]: instrument.ticker || instrument.name });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- onNamesChange stable parent cb.
  }, [instrument]);

  return (
    <div className="flex flex-col gap-3">
      <InstrumentPicker
        label="Instrument"
        value={instrument}
        onSelect={setInstrument}
        onClear={() => setInstrument(null)}
      />

      {/* MetricPicker fetches the S3 vocabulary and emits a backend-valid key. */}
      <MetricPicker value={metricKey} onChange={setMetricKey} />

      <div className="grid grid-cols-2 gap-3">
        <div className="flex flex-col gap-1">
          <label className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
            Direction
          </label>
          <select
            value={operator}
            onChange={(e) => setOperator(e.target.value as CrossOperator)}
            aria-label="Fundamental cross direction"
            className="h-7 rounded-[2px] border border-border bg-background px-2 text-[11px] text-foreground focus:outline-none focus:ring-1 focus:ring-primary"
          >
            <option value="above">Crosses above</option>
            <option value="below">Crosses below</option>
          </select>
        </div>

        <div className="flex flex-col gap-1">
          <label className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
            Threshold
          </label>
          <input
            type="number"
            step="any"
            value={valueStr}
            onChange={(e) => setValueStr(e.target.value)}
            placeholder="e.g. 25"
            aria-label="Metric threshold"
            className="h-7 rounded-[2px] border border-border bg-background px-2 text-[11px] tabular-nums text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-primary"
          />
        </div>
      </div>
    </div>
  );
}
