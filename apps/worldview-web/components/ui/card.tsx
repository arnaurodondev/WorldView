/**
 * components/ui/card.tsx — shadcn/ui Card component
 *
 * WHY THIS EXISTS: Cards are the primary container for every data panel in the
 * dashboard, screener results, instrument detail sections, etc. Using a
 * consistent Card component ensures all panels share the same bg-card background
 * (#111820) and border styling from the Bloomberg Dark palette.
 *
 * Finance UX note: Cards should have minimal padding (p-3 not p-6) to maximise
 * data density. CardHeader has a border-b separator and px-3 py-2 for tight headers.
 * Use CardHeader + CardContent for labelled sections.
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
      "rounded-lg border border-border bg-card text-card-foreground shadow-sm",
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
