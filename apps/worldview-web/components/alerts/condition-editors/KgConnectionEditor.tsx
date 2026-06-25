/**
 * components/alerts/condition-editors/KgConnectionEditor.tsx — KG_CONNECTION editor
 * (PLAN-0113 Wave 4, T-4-05).
 *
 * Emits `{ source_entity_id, target_entity_id, max_hops, relation_type? }`
 * (PRD §6.5.3 KgConnectionCondition):
 *   - source/target : TWO shared EntityPickers (real KG entity_ids)
 *   - max_hops       : 1..3 (S7 path search bound)
 *   - relation_type  : optional edge-type filter (omitted when blank)
 *
 * GUARD: source_entity_id MUST differ from target_entity_id (a node can't connect
 * to itself). When both pickers resolve to the same id we surface an inline error
 * and emit `null` so Save stays disabled.
 *
 * Emits `null` while incomplete (either picker empty) or invalid (same node twice).
 */

"use client";

import { useEffect, useState } from "react";
import { EntityPicker, type ChosenEntity } from "@/components/common/EntityPicker";
import type { KgConnectionCondition } from "@/lib/api/alertRules";
import type { ConditionEditorProps } from "./types";

export function KgConnectionEditor({
  value,
  names,
  onChange,
  onNamesChange,
}: ConditionEditorProps<KgConnectionCondition>) {
  // value may be a PARTIAL prefill (Wave 5) — the KG path-panel entry point seeds
  // BOTH source + target ids; read each defensively and use `names` for the chip.
  const [source, setSource] = useState<ChosenEntity | null>(
    value?.source_entity_id
      ? {
          entityId: value.source_entity_id,
          name: names?.[value.source_entity_id] ?? value.source_entity_id,
        }
      : null,
  );
  const [target, setTarget] = useState<ChosenEntity | null>(
    value?.target_entity_id
      ? {
          entityId: value.target_entity_id,
          name: names?.[value.target_entity_id] ?? value.target_entity_id,
        }
      : null,
  );
  const [maxHops, setMaxHops] = useState<number>(value?.max_hops ?? 3);
  const [relationType, setRelationType] = useState<string>(value?.relation_type ?? "");

  // node_a≠node_b guard — true when both chosen AND identical.
  const sameNode =
    source !== null && target !== null && source.entityId === target.entityId;

  useEffect(() => {
    const complete = source !== null && target !== null && !sameNode;
    onChange(
      complete
        ? {
            source_entity_id: source!.entityId,
            target_entity_id: target!.entityId,
            max_hops: maxHops,
            ...(relationType.trim() ? { relation_type: relationType.trim() } : {}),
          }
        : null,
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps -- onChange stable parent cb.
  }, [source, target, maxHops, relationType, sameNode]);

  // Report both live-picked entities' display names for the wizard NL summary.
  useEffect(() => {
    const next: Record<string, string> = {};
    if (source) next[source.entityId] = source.name;
    if (target) next[target.entityId] = target.name;
    if (Object.keys(next).length) onNamesChange?.(next);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- onNamesChange stable parent cb.
  }, [source, target]);

  return (
    <div className="flex flex-col gap-3">
      {/* Two entity pickers side by side. */}
      <div className="grid grid-cols-2 gap-3">
        <EntityPicker
          label="From entity"
          value={source}
          onSelect={setSource}
          onClear={() => setSource(null)}
        />
        <EntityPicker
          label="To entity"
          value={target}
          onSelect={setTarget}
          onClear={() => setTarget(null)}
        />
      </div>

      {/* node_a≠node_b inline error. */}
      {sameNode && (
        <p role="alert" className="text-[10px] text-destructive">
          The two entities must be different.
        </p>
      )}

      <div className="grid grid-cols-2 gap-3">
        <div className="flex flex-col gap-1">
          <label className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
            Within hops
          </label>
          <select
            value={maxHops}
            onChange={(e) => setMaxHops(Number(e.target.value))}
            aria-label="Max hops"
            className="h-7 rounded-[2px] border border-border bg-background px-2 text-[11px] text-foreground focus:outline-none focus:ring-1 focus:ring-primary"
          >
            {[1, 2, 3].map((h) => (
              <option key={h} value={h}>
                {h} hop{h !== 1 ? "s" : ""}
              </option>
            ))}
          </select>
        </div>

        <div className="flex flex-col gap-1">
          <label className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
            Relation type (optional)
          </label>
          <input
            type="text"
            value={relationType}
            onChange={(e) => setRelationType(e.target.value)}
            placeholder="any"
            aria-label="Relation type filter"
            className="h-7 rounded-[2px] border border-border bg-background px-2 text-[11px] text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-primary"
          />
        </div>
      </div>
    </div>
  );
}
