"use client";

/**
 * features/screener/components/RangeInput.tsx — Min/max number-pair input.
 *
 * WHY EXTRACTED (PLAN-0059 E-4): every fundamental filter on the screener
 * is a min/max range (P/E, P/B, ROE, …). Without a wrapper each filter
 * needed ~24 lines of duplicated input + label markup. Centralising the
 * ARIA + styling + parse rules here makes future filter additions a
 * one-liner.
 *
 * WHY type="number" + step="any": the user might enter integers (P/E 20),
 * decimals (yield 0.025), or percentages (revenue growth 0.15).
 * step="any" tells the browser not to apply integer-only validation.
 *
 * WHY parseValue returns undefined on empty: the FilterState uses
 * `?: number` so an empty string must clear the field, not write NaN.
 */

import { cn } from "@/lib/utils";

export interface RangeInputProps {
  label: string;
  /** Optional hint shown right of the label (e.g. "%" or "decimal") */
  hint?: string;
  /** Disable both inputs (used for backend-pending filters). */
  disabled?: boolean;
  /** Tooltip-style title shown on hover when disabled. */
  disabledReason?: string;
  min: number | undefined;
  max: number | undefined;
  onMin: (v: number | undefined) => void;
  onMax: (v: number | undefined) => void;
}

export function RangeInput({
  label,
  hint,
  disabled = false,
  disabledReason,
  min,
  max,
  onMin,
  onMax,
}: RangeInputProps) {
  // WHY parseValue: number inputs return strings; we coerce ""→undefined
  // and other strings via Number(). Non-finite (NaN/Infinity) → undefined.
  function parseValue(s: string): number | undefined {
    const trimmed = s.trim();
    if (trimmed === "") return undefined;
    const n = Number(trimmed);
    return Number.isFinite(n) ? n : undefined;
  }

  const id = `f-${label.replace(/[^a-z0-9]/gi, "-").toLowerCase()}`;

  return (
    <div className="flex items-center gap-2">
      {/* Label — fixed width so all input pairs in a section align vertically */}
      <label
        htmlFor={`${id}-min`}
        className={cn(
          "text-[10px] font-mono uppercase tracking-[0.06em] w-24 shrink-0",
          disabled ? "text-muted-foreground/50" : "text-muted-foreground",
        )}
        title={disabled ? disabledReason : undefined}
      >
        {label}
        {hint && (
          <span className="ml-1 text-muted-foreground/50 normal-case tracking-normal">
            ({hint})
          </span>
        )}
      </label>
      {/* Min/Max inputs — h-6 px-1.5 per the brief */}
      <input
        id={`${id}-min`}
        aria-label={`${label} minimum`}
        type="number"
        step="any"
        placeholder="min"
        disabled={disabled}
        title={disabled ? disabledReason : undefined}
        value={min ?? ""}
        onChange={(e) => onMin(parseValue(e.target.value))}
        className="h-6 w-20 px-1.5 text-[11px] font-mono tabular-nums bg-background border border-border rounded-[2px] text-foreground placeholder:text-muted-foreground/50 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-primary disabled:bg-[hsl(var(--disabled-bg))] disabled:text-[hsl(var(--disabled-foreground))] disabled:border-[hsl(var(--disabled-border))] disabled:cursor-not-allowed"
      />
      <span className="text-[10px] text-muted-foreground/60 font-mono">–</span>
      <input
        id={`${id}-max`}
        aria-label={`${label} maximum`}
        type="number"
        step="any"
        placeholder="max"
        disabled={disabled}
        title={disabled ? disabledReason : undefined}
        value={max ?? ""}
        onChange={(e) => onMax(parseValue(e.target.value))}
        className="h-6 w-20 px-1.5 text-[11px] font-mono tabular-nums bg-background border border-border rounded-[2px] text-foreground placeholder:text-muted-foreground/50 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-primary disabled:bg-[hsl(var(--disabled-bg))] disabled:text-[hsl(var(--disabled-foreground))] disabled:border-[hsl(var(--disabled-border))] disabled:cursor-not-allowed"
      />
      {disabled && (
        <span className="text-[9px] font-mono uppercase tracking-[0.06em] text-warning/80">
          backend pending
        </span>
      )}
    </div>
  );
}
