/**
 * components/ui/card.tsx — shadcn/ui Card component
 *
 * WHY THIS EXISTS: Cards are the primary container for every data panel in the
 * dashboard, screener results, instrument detail sections, etc. Using a
 * consistent Card component ensures all panels share the same bg-card background
 * (#111113) and border styling from the Terminal Dark palette.
 *
 * Finance UX note: Cards should have minimal padding (p-3 not p-6) to maximise
 * data density. CardHeader has a border-b separator and px-3 py-2 for tight headers.
 * Use CardHeader + CardContent for labelled sections.
 *
 * WHY rounded-[2px] (not rounded-lg or rounded-xl): --radius is now 0.125rem (2px)
 * to match Bloomberg/tastytrade terminal aesthetic. Near-zero radius makes panels
 * feel like grid cells in a data terminal, not floating consumer-app cards.
 * rounded-[2px] is an explicit override to bypass Tailwind's radius scale lookup
 * (rounded-lg etc.) and apply exactly 2px regardless of how the scale is configured.
 *
 * DESIGN REFERENCE: docs/ui/DESIGN_SYSTEM.md §2.3 Background Elevation Hierarchy
 */

import * as React from "react";
import { cn } from "@/lib/utils";

const Card = React.forwardRef<
  HTMLDivElement,
  React.HTMLAttributes<HTMLDivElement>
>(({ className, ...props }, ref) => (
  <div
    ref={ref}
    className={cn(
      // WHY rounded-[2px] not rounded-lg: --radius dropped from 0.375rem (6px) to
      // 0.125rem (2px). rounded-lg resolves via Tailwind's borderRadius scale which
      // now maps to 2px anyway, but using the explicit [2px] value makes the intent
      // crystal-clear in code review and prevents accidental drift if the scale
      // changes. WHY no shadow-sm: terminal panels don't cast shadows — shadows add
      // perceived depth/floating that conflicts with the flat, dense grid aesthetic.
      // Borders (#27272A) are the sole separation mechanism between panels.
      "rounded-[2px] border border-border bg-card text-card-foreground",
      className,
    )}
    {...props}
  />
));
Card.displayName = "Card";

const CardHeader = React.forwardRef<
  HTMLDivElement,
  React.HTMLAttributes<HTMLDivElement>
>(({ className, ...props }, ref) => (
  <div
    ref={ref}
    // WHY border-b border-border/40: subtle visual separator between card header
    // and content — key finding from the V-2 data density audit. Professional
    // finance terminals always separate title from content area.
    // WHY px-3 py-2 (not p-4): tighter padding increases data density for
    // Bloomberg-grade terminal aesthetic.
    className={cn("flex flex-col space-y-1.5 px-3 py-2 border-b border-border/40", className)}
    {...props}
  />
));
CardHeader.displayName = "CardHeader";

const CardTitle = React.forwardRef<
  HTMLParagraphElement,
  React.HTMLAttributes<HTMLHeadingElement>
>(({ className, ...props }, ref) => (
  <h3
    ref={ref}
    // text-sm font-medium: compact card titles — finance panels don't need large headings
    className={cn("text-sm font-medium leading-none tracking-tight", className)}
    {...props}
  />
));
CardTitle.displayName = "CardTitle";

const CardDescription = React.forwardRef<
  HTMLParagraphElement,
  React.HTMLAttributes<HTMLParagraphElement>
>(({ className, ...props }, ref) => (
  <p
    ref={ref}
    className={cn("text-xs text-muted-foreground", className)}
    {...props}
  />
));
CardDescription.displayName = "CardDescription";

const CardContent = React.forwardRef<
  HTMLDivElement,
  React.HTMLAttributes<HTMLDivElement>
>(({ className, ...props }, ref) => (
  // WHY p-3 pt-0 (not p-4 pt-0): reduced padding for higher data density.
  // pt-0 prevents double-spacing between CardHeader bottom border and content.
  <div ref={ref} className={cn("p-3 pt-0", className)} {...props} />
));
CardContent.displayName = "CardContent";

const CardFooter = React.forwardRef<
  HTMLDivElement,
  React.HTMLAttributes<HTMLDivElement>
>(({ className, ...props }, ref) => (
  <div
    ref={ref}
    className={cn("flex items-center p-3 pt-0", className)}
    {...props}
  />
));
CardFooter.displayName = "CardFooter";

export { Card, CardHeader, CardFooter, CardTitle, CardDescription, CardContent };
