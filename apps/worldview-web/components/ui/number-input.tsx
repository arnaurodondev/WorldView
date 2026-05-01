/**
 * components/ui/number-input.tsx — Number input with TradingView shorthand parsing
 *
 * WHY THIS EXISTS: Plain `<Input type="number">` rejects user-friendly shorthand
 * like "1.5m" or "+2%". Institutional traders type fast — they expect the input
 * to interpret what they meant. This component:
 *   1. Accepts any string (text input under the hood) so shorthand isn't blocked.
 *   2. Parses on blur via lib/format/parse-shorthand.
 *   3. Re-formats to the canonical display (e.g. "1.5M") so the user sees what
 *      was understood.
 *   4. Fires onChange with the *numeric* value — consumers always get a number.
 *
 * USAGE:
 *   <NumberInput value={qty} onValueChange={setQty} placeholder="0" />
 *   <NumberInput percent value={pct} onValueChange={setPct} />
 *
 * USED BY (planned): screener filter price/cap thresholds, alert-rule threshold
 * input, trade-ticket quantity input, position-size editor.
 */

"use client";

import * as React from "react";
import { cn } from "@/lib/utils";
import { parseShorthand, formatShorthand } from "@/lib/format/parse-shorthand";
import { inputVariants, type InputDensity } from "./input";

export interface NumberInputProps
  extends Omit<React.InputHTMLAttributes<HTMLInputElement>, "value" | "onChange" | "type"> {
  /** Current numeric value. `null` means "no value entered". */
  value: number | null;
  /** Called with the parsed numeric value. `null` means cleared. */
  onValueChange: (value: number | null) => void;
  /** If true, "%" suffix returns fraction (2% → 0.02). Default true. */
  percent?: boolean;
  /** If true, "bps" suffix returns fraction (25bps → 0.0025). Default true. */
  bps?: boolean;
  /** Density variant; defaults to compact (matches institutional 22px row height). */
  density?: InputDensity;
  /**
   * Display formatter — called when the input is *not* focused. Default:
   * formatShorthand. Pass a custom formatter for currency-prefixed display
   * (e.g. `(v) => v == null ? "" : `$${v.toFixed(2)}`)`).
   */
  format?: (value: number | null) => string;
}

/**
 * NumberInput — a lifted-state input that round-trips parse <-> format.
 *
 * The internal "raw" string is what the user is currently typing. On blur, we
 * parse it, fire onValueChange, and re-format to the canonical display. While
 * focused, the raw string is preserved so the user can edit freely without
 * the formatter fighting their cursor.
 */
export const NumberInput = React.forwardRef<HTMLInputElement, NumberInputProps>(
  ({ value, onValueChange, percent = true, bps = true, density = "compact", format, className, onBlur, onFocus, onKeyDown, ...props }, ref) => {
    const formatter = format ?? formatShorthand;

    // raw = what's in the input box right now. Synced from value when not focused.
    const [raw, setRaw] = React.useState<string>(() => formatter(value));
    const [focused, setFocused] = React.useState(false);

    // When the parent updates `value` and we're not focused, mirror it.
    // WHY guard on focused: don't overwrite the user mid-typing.
    React.useEffect(() => {
      if (!focused) {
        setRaw(formatter(value));
      }
    }, [value, formatter, focused]);

    function commit(input: string) {
      const parsed = parseShorthand(input, { percentAsFraction: percent, bpsAsFraction: bps });
      onValueChange(parsed);
      // After commit, sync display to canonical form.
      setRaw(formatter(parsed));
    }

    return (
      <input
        ref={ref}
        type="text"
        inputMode="decimal"
        // WHY autocomplete=off: numeric finance inputs should not autofill from
        // unrelated browser memory.
        autoComplete="off"
        // WHY spellCheck=false: shorthand like "1.5m" triggers underline squiggles.
        spellCheck={false}
        value={raw}
        onChange={(e) => setRaw(e.target.value)}
        onFocus={(e) => {
          setFocused(true);
          // Select-all on focus matches Bloomberg / TradingView behavior — fast
          // overwrite without manual selection.
          e.currentTarget.select();
          onFocus?.(e);
        }}
        onBlur={(e) => {
          setFocused(false);
          commit(e.currentTarget.value);
          onBlur?.(e);
        }}
        onKeyDown={(e) => {
          // WHY commit on Enter: matches Bloomberg "press Enter to apply".
          if (e.key === "Enter") {
            commit(e.currentTarget.value);
          }
          // WHY Escape reverts: cancels in-progress edit, restores last committed value.
          if (e.key === "Escape") {
            setRaw(formatter(value));
            e.currentTarget.blur();
          }
          onKeyDown?.(e);
        }}
        className={cn(
          inputVariants({ density }),
          // Right-align by default — numeric values read better right-aligned in tables.
          "text-right tabular-nums font-mono",
          className,
        )}
        {...props}
      />
    );
  },
);
NumberInput.displayName = "NumberInput";
