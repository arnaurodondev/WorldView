/**
 * components/ui/number-input.tsx — Number input with TradingView shorthand parsing
 *
 * WHY THIS EXISTS: Plain `<Input type="number">` rejects user-friendly shorthand
 * like "1.5m" or "+2%". Institutional traders type fast — they expect the input
 * to interpret what they meant. This component:
 *   1. Accepts any string (text input under the hood) so shorthand isn't blocked.
 *   2. Parses on blur (via lib/format/parse-shorthand).
 *   3. Re-formats to canonical display (e.g. "1.5M") so user sees what was understood.
 *   4. Fires onValueChange with the *numeric* value — consumers always get a number.
 *
 * QA-iter1 fixes:
 *   - aria-invalid wired when raw text is non-empty AND parses to null (a11y).
 *   - Live parse-preview ghost shown to the right while focused so the user
 *     can see what the parser interprets BEFORE blur (UX win).
 *   - Parent-clamp race: when commit() updates parent and parent clamps the
 *     value, we mirror the clamped value back into raw on next render even
 *     while still focused — using a `committedRef` cycle counter to detect
 *     external value changes vs our own commit.
 */

"use client";

import * as React from "react";
import { cn } from "@/lib/utils";
import { parseShorthand, formatShorthand } from "@/lib/format/parse-shorthand";
import { inputVariants, type InputDensity } from "./input";

export interface NumberInputProps
  extends Omit<React.InputHTMLAttributes<HTMLInputElement>, "value" | "onChange" | "type"> {
  value: number | null;
  onValueChange: (value: number | null) => void;
  /**
   * If true, "%" suffix returns fraction (2% → 0.02). Default true.
   * BE EXPLICIT at call sites that store literal percent (e.g. allocation slider
   * 0–100) — silently dividing by 100 has burned us before.
   */
  percent?: boolean;
  /** If true, "bps" suffix returns fraction (25bps → 0.0025). Default true. */
  bps?: boolean;
  density?: InputDensity;
  /** Display formatter when not focused. Default: formatShorthand. */
  format?: (value: number | null) => string;
  /** Show parse-preview ghost while focused. Default true. */
  showParsePreview?: boolean;
}

export const NumberInput = React.forwardRef<HTMLInputElement, NumberInputProps>(
  (
    {
      value,
      onValueChange,
      percent = true,
      bps = true,
      density = "compact",
      format,
      showParsePreview = true,
      className,
      onBlur,
      onFocus,
      onKeyDown,
      ...props
    },
    ref,
  ) => {
    const formatter = format ?? formatShorthand;

    const [raw, setRaw] = React.useState<string>(() => formatter(value));
    const [focused, setFocused] = React.useState(false);

    // Track the last value WE committed; lets us tell our own commit-driven
    // value-prop change apart from a parent-driven external change. When the
    // parent clamps our committed value (e.g. Math.min(parsed, max)), the new
    // value differs from `lastCommittedRef`, so we re-mirror raw even while
    // focused.
    const lastCommittedRef = React.useRef<number | null>(value);

    React.useEffect(() => {
      // External change (parent reset, parent clamp): re-mirror display.
      if (value !== lastCommittedRef.current) {
        setRaw(formatter(value));
        lastCommittedRef.current = value;
      } else if (!focused) {
        // Stable value, not focused → also keep display in sync if formatter
        // changed (rare, e.g. currency option).
        setRaw(formatter(value));
      }
    }, [value, formatter, focused]);

    function commit(input: string) {
      const parsed = parseShorthand(input, { percentAsFraction: percent, bpsAsFraction: bps });
      lastCommittedRef.current = parsed;
      onValueChange(parsed);
      setRaw(formatter(parsed));
    }

    // Live parse during typing — used only for the preview ghost; does NOT
    // call onValueChange (commit happens on blur/Enter).
    const livePreview = React.useMemo(() => {
      if (!showParsePreview || !focused || !raw.trim()) return null;
      const parsed = parseShorthand(raw, {
        percentAsFraction: percent,
        bpsAsFraction: bps,
      });
      if (parsed === null) return null;
      const formatted = formatShorthand(parsed);
      // Don't show the preview when the formatted form equals what the user typed.
      if (formatted === raw.trim()) return null;
      return formatted;
    }, [raw, focused, percent, bps, showParsePreview]);

    // aria-invalid: text typed but unparseable.
    const isInvalid = focused
      ? raw.trim() !== "" && parseShorthand(raw, { percentAsFraction: percent, bpsAsFraction: bps }) === null
      : false;

    return (
      <span className="relative inline-block w-full">
        <input
          ref={ref}
          type="text"
          inputMode="decimal"
          autoComplete="off"
          spellCheck={false}
          aria-invalid={isInvalid || undefined}
          value={raw}
          onChange={(e) => setRaw(e.target.value)}
          onFocus={(e) => {
            setFocused(true);
            e.currentTarget.select();
            onFocus?.(e);
          }}
          onBlur={(e) => {
            setFocused(false);
            commit(e.currentTarget.value);
            onBlur?.(e);
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              commit(e.currentTarget.value);
            }
            if (e.key === "Escape") {
              setRaw(formatter(value));
              e.currentTarget.blur();
            }
            onKeyDown?.(e);
          }}
          className={cn(
            inputVariants({ density }),
            "text-right tabular-nums font-mono",
            isInvalid && "border-destructive focus-visible:ring-destructive",
            // Reserve right-padding for the parse-preview ghost.
            livePreview && "pr-14",
            className,
          )}
          {...props}
        />
        {livePreview && (
          <span
            aria-hidden
            className="pointer-events-none absolute right-2 top-0 flex h-full items-center text-[10px] text-muted-foreground/70 tabular-nums font-mono"
          >
            ≈ {livePreview}
          </span>
        )}
      </span>
    );
  },
);
NumberInput.displayName = "NumberInput";
