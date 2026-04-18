/**
 * components/ui/badge.tsx — shadcn/ui Badge component
 *
 * WHY THIS EXISTS: Badges are used for alert severity (CRITICAL/HIGH/MEDIUM/LOW),
 * ticker symbols, GICS sectors, and article impact indicators throughout the app.
 * Finance users need to instantly identify severity levels — the color variants
 * must be consistent across all panels.
 *
 * DESIGN REFERENCE: docs/ui/DESIGN_SYSTEM.md §4 Alert Severity Colors
 */

import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const badgeVariants = cva(
  // Base: compact, rounded, uppercase tracking for ticker/severity feel
  "inline-flex items-center rounded-md px-2 py-0.5 text-xs font-medium transition-colors focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2",
  {
    variants: {
      variant: {
        // Default — muted background, used for neutral labels
        default: "bg-primary/10 text-primary border border-primary/20",
        // Secondary — elevated muted background, for GICS sectors
        secondary: "bg-muted text-muted-foreground border border-border",
        // Destructive — for CRITICAL/HIGH alerts
        destructive: "bg-destructive/20 text-negative border border-destructive/30",
        // Outline — for ticker symbols, transparent background
        outline: "border border-border text-foreground bg-transparent",
        // Warning — for HIGH severity (amber)
        warning: "bg-warning/20 text-warning border border-warning/30",
        // Positive — for buy signals, price gains
        positive: "bg-positive/20 text-positive border border-positive/30",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  },
);

export interface BadgeProps
  extends React.HTMLAttributes<HTMLDivElement>,
    VariantProps<typeof badgeVariants> {}

function Badge({ className, variant, ...props }: BadgeProps) {
  return (
    <div className={cn(badgeVariants({ variant }), className)} {...props} />
  );
}

export { Badge, badgeVariants };
