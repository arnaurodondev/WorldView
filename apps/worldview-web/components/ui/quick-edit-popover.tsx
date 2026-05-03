/**
 * components/ui/quick-edit-popover.tsx — Inline single-field edit popover
 *
 * WHY THIS EXISTS: Finance terminals expose inline edit for position quantities,
 * price targets, and alert thresholds directly in table rows — no full dialog.
 * This component provides a lightweight Popover with a single input (NumberInput
 * for numeric values, Input for text), Save + Cancel actions, and keyboard
 * shortcuts (Enter = save, Escape = cancel).
 *
 * WHO USES IT: Holdings table inline qty edit, watchlist name inline rename,
 * alert threshold quick-edit.
 *
 * DATA SOURCE: No S9 calls — parent provides `onSave` which calls useMutation.
 *
 * DESIGN REFERENCE: PLAN-0059 F-2 Form Layer.
 */

"use client"; // WHY: uses useState for local edit value + popover open state

import * as React from "react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { NumberInput } from "@/components/ui/number-input";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Label } from "@/components/ui/label";

// ── Types ──────────────────────────────────────────────────────────────────

export interface QuickEditPopoverProps {
  /** The element that opens the popover (e.g. a row cell or icon button). */
  trigger: React.ReactNode;
  /** Current field value. Null = empty / not set. */
  value: number | string | null;
  /** "number" renders NumberInput with shorthand parsing; "text" renders plain Input. */
  type: "number" | "text";
  /** Accessible label for the input (used as aria-label and the visible label). */
  label: string;
  /** Called with the (possibly transformed) value when the user saves. */
  onSave: (value: number | string | null) => void;
  /** Called when the user cancels (Escape or Cancel button). Popover closes either way. */
  onCancel?: () => void;
  /** Show a spinner and disable inputs while a mutation is in-flight. */
  isLoading?: boolean;
  /** Number type only: minimum allowed value. */
  min?: number;
  /** Number type only: maximum allowed value. */
  max?: number;
  /** Number type only: step for keyboard increment. */
  step?: number;
  density?: "compact" | "default" | "comfortable";
  className?: string;
}

// ── Component ──────────────────────────────────────────────────────────────

export function QuickEditPopover({
  trigger,
  value,
  type,
  label,
  onSave,
  onCancel,
  isLoading = false,
  min: _min,
  max: _max,
  density = "compact",
  className,
}: QuickEditPopoverProps) {
  const [open, setOpen] = React.useState(false);
  // Local edit value — initialised from `value` when the popover opens.
  const [localValue, setLocalValue] = React.useState<number | string | null>(value);
  const inputRef = React.useRef<HTMLInputElement>(null);

  // Sync local value when the popover opens (value may have changed externally).
  React.useEffect(() => {
    if (open) {
      setLocalValue(value);
      // WHY setTimeout 0: PopoverContent renders asynchronously; the input
      // doesn't exist yet on the tick the effect fires. Deferring focus by one
      // microtask ensures the ref is populated.
      setTimeout(() => inputRef.current?.focus(), 0);
    }
  }, [open, value]);

  const handleSave = React.useCallback(() => {
    onSave(localValue);
    setOpen(false);
  }, [localValue, onSave]);

  const handleCancel = React.useCallback(() => {
    onCancel?.();
    setOpen(false);
  }, [onCancel]);

  // WHY global keydown on the popover content: Enter and Escape should work
  // regardless of which element has focus inside the popover (e.g. Save button
  // focused via Tab). Listening on the container avoids wiring each element.
  const handleKeyDown = React.useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === "Enter" && !isLoading) {
        e.preventDefault();
        handleSave();
      }
      if (e.key === "Escape") {
        e.preventDefault();
        handleCancel();
      }
    },
    [isLoading, handleSave, handleCancel],
  );

  const heightClass =
    density === "compact" ? "h-7 text-[11px]" : density === "comfortable" ? "h-10 text-[13px]" : "h-9 text-[12px]";

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>{trigger}</PopoverTrigger>

      <PopoverContent
        className={cn("w-64 p-3 space-y-3", className)}
        // WHY onKeyDown here: the PopoverContent is the focus container during
        // keyboard interaction. Catching at this level means focus can be
        // anywhere inside and Enter/Escape still work.
        onKeyDown={handleKeyDown}
        // WHY sideOffset 4: small gap between trigger and popover so they don't
        // look merged in compact density.
        sideOffset={4}
      >
        {/* Label — matches FormLabel styling for consistency with RHF forms */}
        <Label className="text-[10px] uppercase tracking-[0.06em] text-muted-foreground font-mono">
          {label}
        </Label>

        {type === "number" ? (
          // WHY NumberInput here (not plain Input): NumberInput parses
          // TradingView shorthand ("1.5m" → 1500000, "25%" → 0.25) which
          // institutional users expect everywhere they type a number.
          <NumberInput
            ref={inputRef}
            value={typeof localValue === "number" ? localValue : null}
            onValueChange={(v) => setLocalValue(v)}
            disabled={isLoading}
            density={density}
            aria-label={label}
            className="w-full"
          />
        ) : (
          <Input
            ref={inputRef}
            value={typeof localValue === "string" ? localValue : ""}
            onChange={(e) => setLocalValue(e.target.value)}
            disabled={isLoading}
            aria-label={label}
            className={cn("w-full font-mono", heightClass)}
          />
        )}

        {/* Action row — Save is primary, Cancel is ghost to de-emphasise */}
        <div className="flex items-center justify-end gap-2">
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={handleCancel}
            disabled={isLoading}
            className="h-6 px-2 text-[11px] font-mono"
          >
            Cancel
          </Button>
          <Button
            type="button"
            size="sm"
            onClick={handleSave}
            disabled={isLoading}
            // WHY font-mono: all action text in terminal UI uses monospace.
            className="h-6 px-2 text-[11px] font-mono"
          >
            {isLoading ? "Saving…" : "Save"}
          </Button>
        </div>
      </PopoverContent>
    </Popover>
  );
}
