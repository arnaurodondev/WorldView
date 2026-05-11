/**
 * components/workspace/SymbolLinkColorPicker.tsx — Tiny color-dot picker for panel headers
 *
 * WHY THIS EXISTS: Every workspace panel header needs a one-click affordance to assign
 * the panel to a color group. A 12px clickable dot with a popover of 5 colors + "None"
 * is the standard Bloomberg pattern. Splitting this into its own file keeps
 * WorkspacePanelContainer.tsx lean and lets us reuse the picker wherever a panel-style
 * color group is needed (e.g., a future floating window).
 *
 * WHY 12px DOT (not a chip with label): the panel header is only 24px tall and densely
 * packed (icon + label + symbol indicator + maximize + close). A dot is the smallest
 * thing that still communicates "this is a color choice" and reads as interactive
 * because of the cursor change + ring focus. The popover compensates with full labels.
 *
 * WHY shadcn Popover (not custom): we already use Popover elsewhere in the codebase
 * (column settings, saved screens). Using the same primitive keeps keyboard handling
 * (Esc to close, focus trap) consistent without re-implementing portal / dismiss logic.
 *
 * WHO USES IT: WorkspacePanelContainer renders one per panel.
 * DATA SOURCE: SymbolLinkingContext (reads current color, calls setLinkColor on click).
 * DESIGN REFERENCE: PRD-0031 §5.3 Symbol linking; DESIGN_SYSTEM.md §6.13 Symbol Linking
 */

"use client";
// WHY "use client": uses useState (popover open/close) and Radix Popover (browser-only).

import { useState } from "react";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import {
  GROUP_COLOR_HEX,
  LINK_COLOR_ORDER,
  useSymbolLinking,
  type LinkColor,
} from "@/contexts/SymbolLinkingContext";
import { cn } from "@/lib/utils";

// ── Helpers ───────────────────────────────────────────────────────────────────

/**
 * Capitalised label for the popover items.
 *
 * WHY a tiny helper (not inline): pure formatting logic; isolating it keeps the JSX
 * compact and lets us swap to i18n later without touching the render tree.
 */
function colorLabel(color: LinkColor): string {
  if (color === "none") return "None";
  return color.charAt(0).toUpperCase() + color.slice(1);
}

// ── Component ─────────────────────────────────────────────────────────────────

interface SymbolLinkColorPickerProps {
  /** Stable workspace panel ID — used as the key into SymbolLinkingContext */
  panelId: string;
}

export function SymbolLinkColorPicker({ panelId }: SymbolLinkColorPickerProps) {
  const { links, setLinkColor } = useSymbolLinking();
  const currentColor: LinkColor = links[panelId]?.color ?? "none";
  // WHY local open state (not a context flag): each picker controls its own popover.
  // Lifting this would require tracking N panels' open state with no benefit.
  const [open, setOpen] = useState(false);

  /**
   * Inline-style background hex for the trigger dot.
   * WHY inline: Tailwind purges dynamic `bg-[#XXX]` classes; inline guarantees the
   * runtime hex applies regardless of build optimisation.
   */
  const triggerStyle =
    currentColor === "none" ? {} : { backgroundColor: GROUP_COLOR_HEX[currentColor] };

  function handlePick(color: LinkColor) {
    setLinkColor(panelId, color);
    // WHY auto-close after pick: matches the user's mental model — "I made my choice,
    // dismiss the menu". Keeping it open would require a second click to close.
    setOpen(false);
  }

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
          type="button"
          className={cn(
            // WHY h-2 w-2 (8px): a 12-by-12px hit target with the dot itself ~8px.
            // The h-3 w-3 padding around it gives a comfortable click zone without
            // pushing the panel chrome past 24px.
            // WHY rounded-[2px] (not rounded-full): Bloomberg terminal mandate — no
            // rounded-full on interactive controls. 2px radius still reads as a dot
            // at 8px size but follows the design system corner-radius rule.
            "h-2 w-2 rounded-[2px] shrink-0 cursor-pointer",
            "ring-offset-background focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-primary",
            // WHY border on "none": an outline-only dot reads as "no color set" without
            // requiring a separate icon. Familiar Bloomberg pattern (empty group circle).
            currentColor === "none" && "border border-border/60",
          )}
          style={triggerStyle}
          aria-label={`Symbol link group: ${colorLabel(currentColor)}`}
          aria-haspopup="menu"
        />
      </PopoverTrigger>
      <PopoverContent
        align="start"
        // WHY w-auto + min-w: the menu is short (6 items × ~80px) — let it size to its
        // content rather than reserving a wide pane that wastes vertical space.
        className="w-auto min-w-[112px] p-1 rounded-[2px] border border-border bg-card shadow-none"
        // WHY sideOffset 4: a small gap separates the popover from the trigger dot so
        // the user can see the dot they picked, while still feeling visually connected.
        sideOffset={4}
        role="menu"
      >
        <div className="flex flex-col gap-px">
          {LINK_COLOR_ORDER.map((color) => {
            const isCurrent = color === currentColor;
            return (
              <button
                key={color}
                type="button"
                role="menuitemradio"
                aria-checked={isCurrent}
                onClick={() => handlePick(color)}
                className={cn(
                  "flex items-center gap-1.5 rounded-[2px] px-1.5 py-0.5 text-left text-[10px]",
                  "text-muted-foreground hover:bg-muted/40 hover:text-foreground",
                  isCurrent && "text-foreground",
                )}
              >
                {/* Color preview swatch */}
                <span
                  className={cn(
                    "h-2 w-2 rounded-full shrink-0",
                    color === "none" && "border border-border",
                  )}
                  style={
                    color === "none"
                      ? {}
                      : { backgroundColor: GROUP_COLOR_HEX[color] }
                  }
                  aria-hidden
                />
                {colorLabel(color)}
              </button>
            );
          })}
        </div>
      </PopoverContent>
    </Popover>
  );
}
