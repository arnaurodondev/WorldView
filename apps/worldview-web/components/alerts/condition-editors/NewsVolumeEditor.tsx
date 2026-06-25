/**
 * components/alerts/condition-editors/NewsVolumeEditor.tsx — NEWS_COUNT editor
 * (PLAN-0113 Wave 4, T-4-05).
 *
 * Emits `{ entity_id, window, threshold, keyword? }` (PRD §6.5.3 NewsCountCondition):
 *   - entity_id : shared EntityPicker (real KG entity_id)
 *   - window    : one of the backend-supported windows (1h | 6h | 24h | 7d)
 *   - threshold : article count >= 1
 *   - keyword   : optional free-text filter (omitted when blank)
 *
 * Emits `null` while incomplete (no entity, or threshold < 1).
 */

"use client";

import { useEffect, useState } from "react";
import { EntityPicker, type ChosenEntity } from "@/components/common/EntityPicker";
import {
  NEWS_COUNT_WINDOWS,
  type NewsCountCondition,
  type NewsCountWindow,
} from "@/lib/api/alertRules";
import type { ConditionEditorProps } from "./types";

export function NewsVolumeEditor({
  value,
  names,
  onChange,
  onNamesChange,
}: ConditionEditorProps<NewsCountCondition>) {
  // value may be a PARTIAL prefill (Wave 5) — read each field defensively.
  const [entity, setEntity] = useState<ChosenEntity | null>(
    value?.entity_id
      ? { entityId: value.entity_id, name: names?.[value.entity_id] ?? value.entity_id }
      : null,
  );
  const [window, setWindow] = useState<NewsCountWindow>(value?.window ?? "24h");
  const [thresholdStr, setThresholdStr] = useState<string>(
    value?.threshold != null ? String(value.threshold) : "5",
  );
  const [keyword, setKeyword] = useState<string>(value?.keyword ?? "");

  useEffect(() => {
    const threshold = Number(thresholdStr);
    const complete =
      entity !== null && thresholdStr.trim() !== "" && Number.isInteger(threshold) && threshold >= 1;
    onChange(
      complete
        ? {
            entity_id: entity!.entityId,
            window,
            threshold,
            // Only include keyword when non-blank (the backend field is optional).
            ...(keyword.trim() ? { keyword: keyword.trim() } : {}),
          }
        : null,
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps -- onChange stable parent cb.
  }, [entity, window, thresholdStr, keyword]);

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
            Article count ≥
          </label>
          <input
            type="number"
            min="1"
            step="1"
            value={thresholdStr}
            onChange={(e) => setThresholdStr(e.target.value)}
            placeholder="e.g. 5"
            aria-label="Article count threshold"
            className="h-7 rounded-[2px] border border-border bg-background px-2 text-[11px] tabular-nums text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-primary"
          />
        </div>

        <div className="flex flex-col gap-1">
          <label className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
            Over window
          </label>
          <select
            value={window}
            onChange={(e) => setWindow(e.target.value as NewsCountWindow)}
            aria-label="News count window"
            className="h-7 rounded-[2px] border border-border bg-background px-2 text-[11px] text-foreground focus:outline-none focus:ring-1 focus:ring-primary"
          >
            {NEWS_COUNT_WINDOWS.map((w) => (
              <option key={w} value={w}>
                {w}
              </option>
            ))}
          </select>
        </div>
      </div>

      <div className="flex flex-col gap-1">
        <label className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
          Keyword (optional)
        </label>
        <input
          type="text"
          value={keyword}
          onChange={(e) => setKeyword(e.target.value)}
          placeholder="e.g. earnings"
          aria-label="News keyword filter"
          className="h-7 rounded-[2px] border border-border bg-background px-2 text-[11px] text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-primary"
        />
      </div>
    </div>
  );
}
