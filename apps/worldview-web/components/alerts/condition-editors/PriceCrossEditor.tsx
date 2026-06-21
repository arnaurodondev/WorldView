/**
 * components/alerts/condition-editors/PriceCrossEditor.tsx — PRICE_CROSS editor
 * (PLAN-0113 Wave 4, T-4-04).
 *
 * Emits `{ instrument_id, operator, value }` (PRD §6.5.3 PriceCrossCondition):
 *   - instrument_id : chosen via the shared InstrumentPicker (real S3 id)
 *   - operator      : "above" | "below"
 *   - value         : a positive price level
 *
 * The editor reports the condition up via `onChange` whenever a field changes,
 * emitting `null` while incomplete (no instrument, or value <= 0) so the wizard
 * keeps Save disabled.
 */

"use client";
// WHY "use client": uses useState + useEffect (controlled form state).

import { useEffect, useState } from "react";
import { InstrumentPicker, type ChosenInstrument } from "@/components/common/InstrumentPicker";
import type { CrossOperator, PriceCrossCondition } from "@/lib/api/alertRules";
import type { ConditionEditorProps } from "./types";

export function PriceCrossEditor({
  value,
  names,
  onChange,
  onNamesChange,
}: ConditionEditorProps<PriceCrossCondition>) {
  // WHY local chip state for the instrument: the picker needs a display name, but
  // the condition only carries the id. We keep both — the chip name is presentation
  // only and never leaves the component. `names` (Wave 5) lets a prefilled id show
  // its ticker/name instead of a raw UUID.
  const [instrument, setInstrument] = useState<ChosenInstrument | null>(
    value?.instrument_id
      ? {
          instrumentId: value.instrument_id,
          ticker: names?.[value.instrument_id] ?? "",
          name: names?.[value.instrument_id] ?? value.instrument_id,
        }
      : null,
  );
  const [operator, setOperator] = useState<CrossOperator>(value?.operator ?? "above");
  // WHY string state for the number input: an empty input is "" (not 0), so the
  // user can clear it without it snapping to 0. We parse on emit.
  const [valueStr, setValueStr] = useState<string>(value ? String(value.value) : "");

  // Emit the structured condition (or null) whenever any field changes.
  useEffect(() => {
    const numeric = Number(valueStr);
    const complete = instrument !== null && valueStr.trim() !== "" && numeric > 0;
    onChange(
      complete
        ? { instrument_id: instrument!.instrumentId, operator, value: numeric }
        : null,
    );
    // onChange is a stable parent callback; including it would re-fire on every
    // parent render, so it is intentionally omitted from the dependency array.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [instrument, operator, valueStr]);

  // Report the live-picked instrument's display name so the wizard summary reads
  // its ticker (e.g. "AAPL"), not the raw UUID (PLAN-0113 QA fix).
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

      {/* Operator + value row. */}
      <div className="grid grid-cols-2 gap-3">
        <div className="flex flex-col gap-1">
          <label className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
            Direction
          </label>
          <select
            value={operator}
            onChange={(e) => setOperator(e.target.value as CrossOperator)}
            aria-label="Price cross direction"
            className="h-7 rounded-[2px] border border-border bg-background px-2 text-[11px] text-foreground focus:outline-none focus:ring-1 focus:ring-primary"
          >
            <option value="above">Crosses above</option>
            <option value="below">Crosses below</option>
          </select>
        </div>

        <div className="flex flex-col gap-1">
          <label className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
            Price level
          </label>
          <input
            type="number"
            min="0"
            step="any"
            value={valueStr}
            onChange={(e) => setValueStr(e.target.value)}
            placeholder="e.g. 250"
            aria-label="Price level"
            className="h-7 rounded-[2px] border border-border bg-background px-2 text-[11px] tabular-nums text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-primary"
          />
        </div>
      </div>
    </div>
  );
}
