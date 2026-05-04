/**
 * components/ui/tooltip.tsx — shadcn/ui Tooltip primitive
 *
 * WHY THIS EXISTS: @radix-ui/react-tooltip is already installed but had no
 * shadcn wrapper component. The filter bar Info icons need a hover tooltip
 * that follows the terminal design system (muted bg, sharp corners, mono 10px).
 *
 * WHO USES IT: features/screener/components/RangeInput.tsx (metric explanations)
 * DESIGN REFERENCE: DESIGN_SYSTEM.md §0.1 typography, §0.3 dark theme
 */

"use client";
// WHY "use client": Radix tooltip uses browser focus/hover events that are
// not available in Server Components.

import * as React from "react";
import * as TooltipPrimitive from "@radix-ui/react-tooltip";

import { cn } from "@/lib/utils";

// Re-export the provider so callers can wrap their subtrees once.
const TooltipProvider = TooltipPrimitive.Provider;

const Tooltip = TooltipPrimitive.Root;

const TooltipTrigger = TooltipPrimitive.Trigger;

const TooltipContent = React.forwardRef<
  React.ElementRef<typeof TooltipPrimitive.Content>,
  React.ComponentPropsWithoutRef<typeof TooltipPrimitive.Content>
>(({ className, sideOffset = 4, ...props }, ref) => (
  <TooltipPrimitive.Portal>
    <TooltipPrimitive.Content
      ref={ref}
      sideOffset={sideOffset}
      className={cn(
        // WHY bg-card border-border: matches the terminal panel surface rather
        // than a popover-style floating card — keeps tooltip visually on-theme.
        // WHY rounded-none: PRD-0031 §0 bans rounded corners on data chrome.
        // WHY max-w-[220px]: long tooltip copy wraps neatly without exceeding
        // the screener filter column width.
        "z-50 max-w-[220px] rounded-[2px] bg-card border border-border/80 px-2 py-1.5",
        "text-[10px] font-mono leading-relaxed text-foreground/80 shadow-md",
        "animate-in fade-in-0 zoom-in-95",
        "data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=closed]:zoom-out-95",
        "data-[side=bottom]:slide-in-from-top-2 data-[side=left]:slide-in-from-right-2",
        "data-[side=right]:slide-in-from-left-2 data-[side=top]:slide-in-from-bottom-2",
        className,
      )}
      {...props}
    />
  </TooltipPrimitive.Portal>
));
TooltipContent.displayName = TooltipPrimitive.Content.displayName;

export { Tooltip, TooltipTrigger, TooltipContent, TooltipProvider };
