"use client";

/**
 * features/screener/components/CoverageToggles.tsx — Coverage filter
 * toggles (PRD-0089 Wave I-B Block IB-L1 · T-IB-03).
 *
 * WHY: Wave L-1 backend added `has_fundamentals` and `has_ohlcv` boolean
 * predicates against the instruments table. The most common analyst
 * gesture is "exclude crypto / forex / synthetic instruments" — both
 * toggles ON achieves that in one click.
 *
 * WHY only two states (off=ignore / on=require), not tri-state:
 *   - The Wave L-1 query only branches on `is not None` then equality —
 *     setting `false` would mean "require ZERO fundamentals / OHLCV",
 *     which has no analyst use-case (you'd never search FOR instruments
 *     with no data).
 *   - The design (08-screener.md §Coverage) confirms two switches with
 *     no "exclude" path.
 * Therefore: undefined = filter not active; true = require coverage.
 * The off-state writes `undefined` (not `false`) so the backend ignores
 * the field entirely.
 *
 * NO BackendPendingBadge — Wave L-1 shipped 2026-05-25.
 */

import { Switch } from "@/components/ui/switch";
import type { FilterState } from "@/features/screener/lib/filter-state";

export interface CoverageTogglesProps {
  /** Current value — undefined or true (false is never written). */
  hasFundamentals: FilterState["hasFundamentals"];
  hasOhlcv: FilterState["hasOhlcv"];
  /** Called with a partial FilterState patch (mirrors the bar's `patch()`). */
  onChange: (patch: Partial<FilterState>) => void;
}

export function CoverageToggles({
  hasFundamentals,
  hasOhlcv,
  onChange,
}: CoverageTogglesProps) {
  return (
    <div className="flex items-center gap-4 px-2 py-1" role="group" aria-label="Coverage filters">
      <label className="text-[10px] font-mono uppercase tracking-[0.06em] text-muted-foreground w-20 shrink-0">
        Coverage
      </label>

      {/* ── Has Fundamentals toggle ─────────────────────────────────── */}
      <label className="flex items-center gap-2 cursor-pointer">
        <Switch
          checked={hasFundamentals === true}
          // WHY undefined-on-off: see file header. The Wave L-1 query
          // ignores the field when None; writing `false` would actively
          // exclude instruments WITH fundamentals — never desired.
          onCheckedChange={(checked) =>
            onChange({ hasFundamentals: checked ? true : undefined })
          }
          aria-label="Require fundamentals coverage"
        />
        <span className="text-[11px] font-mono text-foreground">
          Has Fundamentals
        </span>
      </label>

      {/* ── Has OHLCV toggle ────────────────────────────────────────── */}
      <label className="flex items-center gap-2 cursor-pointer">
        <Switch
          checked={hasOhlcv === true}
          onCheckedChange={(checked) =>
            onChange({ hasOhlcv: checked ? true : undefined })
          }
          aria-label="Require OHLCV coverage"
        />
        <span className="text-[11px] font-mono text-foreground">
          Has OHLCV
        </span>
      </label>
    </div>
  );
}
