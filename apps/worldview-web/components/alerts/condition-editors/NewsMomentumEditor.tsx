/**
 * components/alerts/condition-editors/NewsMomentumEditor.tsx — NEWS_MOMENTUM editor
 * (PLAN-0113 Wave 4, T-4-05).
 *
 * Emits `{ entity_id, window_hours, delta_pct, min_count }`
 * (PRD §6.5.3 NewsMomentumCondition):
 *   - entity_id    : shared EntityPicker (real KG entity_id)
 *   - window_hours : one of the trending windows (24 | 72 | 168) — closed set
 *   - delta_pct    : momentum surge threshold (e.g. +50)
 *   - min_count    : min article count to suppress 1→2 noise (>= 1, default 2)
 *
 * Emits `null` while incomplete (no entity, blank delta, or min_count < 1).
 */

"use client";

import { useEffect, useState } from "react";
import { EntityPicker, type ChosenEntity } from "@/components/common/EntityPicker";
import {
  NEWS_MOMENTUM_WINDOW_HOURS,
  type NewsMomentumCondition,
  type NewsMomentumWindowHours,
} from "@/lib/api/alertRules";
import type { ConditionEditorProps } from "./types";

export function NewsMomentumEditor({
  value,
  names,
  onChange,
  onNamesChange,
}: ConditionEditorProps<NewsMomentumCondition>) {
  // value may be a PARTIAL prefill (Wave 5) — read each field defensively.
  const [entity, setEntity] = useState<ChosenEntity | null>(
    value?.entity_id
      ? { entityId: value.entity_id, name: names?.[value.entity_id] ?? value.entity_id }
      : null,
  );
  const [windowHours, setWindowHours] = useState<NewsMomentumWindowHours>(
    value?.window_hours ?? 24,
  );
  const [deltaStr, setDeltaStr] = useState<string>(
    value?.delta_pct != null ? String(value.delta_pct) : "50",
  );
  const [minCountStr, setMinCountStr] = useState<string>(
    value?.min_count != null ? String(value.min_count) : "2",
  );

  useEffect(() => {
    const deltaPct = Number(deltaStr);
    const minCount = Number(minCountStr);
    const complete =
      entity !== null &&
      deltaStr.trim() !== "" &&
      Number.isFinite(deltaPct) &&
      minCountStr.trim() !== "" &&
      Number.isInteger(minCount) &&
      minCount >= 1;
    onChange(
      complete
        ? {
            entity_id: entity!.entityId,
            window_hours: windowHours,
            delta_pct: deltaPct,
            min_count: minCount,
          }
        : null,
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps -- onChange stable parent cb.
  }, [entity, windowHours, deltaStr, minCountStr]);

  // Report the live-picked entity's display name for the wizard NL summary.
  useEffect(() => {
    if (entity) onNamesChange?.({ [entity.entityId]: entity.name });
    // eslint-disable-next-line react-hooks/exhaustive-deps -- onNamesChange stable parent cb.
  }, [entity]);

  return (
    <div className="flex flex-col gap-3">
      <EntityPicker
        label="Entity"
        value={entity}
        onSelect={setEntity}
        onClear={() => setEntity(null)}
      />

      <div className="grid grid-cols-2 gap-3">
        <div className="flex flex-col gap-1">
          <label className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
            Momentum Δ% ≥
          </label>
          <input
            type="number"
            step="any"
            value={deltaStr}
            onChange={(e) => setDeltaStr(e.target.value)}
            placeholder="e.g. 50"
            aria-label="Momentum delta percent"
            className="h-7 rounded-[2px] border border-border bg-background px-2 text-[11px] tabular-nums text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-primary"
          />
        </div>

        <div className="flex flex-col gap-1">
          <label className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
            Over window
          </label>
          <select
            value={windowHours}
            onChange={(e) =>
              setWindowHours(Number(e.target.value) as NewsMomentumWindowHours)
            }
            aria-label="News momentum window hours"
            className="h-7 rounded-[2px] border border-border bg-background px-2 text-[11px] text-foreground focus:outline-none focus:ring-1 focus:ring-primary"
          >
            {NEWS_MOMENTUM_WINDOW_HOURS.map((h) => (
              <option key={h} value={h}>
                {h}h
              </option>
            ))}
          </select>
        </div>
      </div>

      <div className="flex flex-col gap-1">
        <label className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
          Min article count
        </label>
        <input
          type="number"
          min="1"
          step="1"
          value={minCountStr}
          onChange={(e) => setMinCountStr(e.target.value)}
          placeholder="e.g. 2"
          aria-label="Minimum article count"
          className="h-7 rounded-[2px] border border-border bg-background px-2 text-[11px] tabular-nums text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-primary"
        />
      </div>
    </div>
  );
}
