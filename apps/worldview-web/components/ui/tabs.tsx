/**
 * components/ui/tabs.tsx — shadcn/ui Tabs (Radix UI)
 *
 * WHY THIS EXISTS: Used in Instrument Detail (Overview/Fundamentals/News/Intelligence),
 * Alerts/News page (Feed/Top Today), and Workspace panel headers.
 * Radix UI handles keyboard navigation (Arrow keys, focus management) for accessibility.
 *
 * PLAN-0071 P1-7: Added `terminal` variant — underline indicator, no pill background.
 * The terminal variant matches the Bloomberg-style tab bar: flat bg, amber bottom-border
 * on active tab, no rounded corners or elevated background.
 *
 * "use client" — WHY: Radix Tabs uses internal state for active tab tracking
 * which requires browser-side rendering.
 */

"use client";

import * as React from "react";
import * as TabsPrimitive from "@radix-ui/react-tabs";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const Tabs = TabsPrimitive.Root;

// ── TabsList variants ────────────────────────────────────────────────────────

const tabsListVariants = cva(
  "inline-flex items-center justify-start text-muted-foreground",
  {
    variants: {
      variant: {
        // Default: elevated muted background pill row (existing behavior)
        default: "h-9 rounded-[2px] bg-muted p-1",
        // Terminal: flat bottom-border line, no background, no padding.
        // WHY: Bloomberg-grade tab bars use an underline indicator, not pills.
        // The border-b on the list creates the full-width baseline; each active
        // trigger overrides its own segment with border-primary.
        terminal: "h-8 border-b border-border bg-transparent p-0",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  },
);

interface TabsListProps
  extends React.ComponentPropsWithoutRef<typeof TabsPrimitive.List>,
    VariantProps<typeof tabsListVariants> {}

const TabsList = React.forwardRef<
  React.ElementRef<typeof TabsPrimitive.List>,
  TabsListProps
>(({ className, variant, ...props }, ref) => (
  <TabsPrimitive.List
    ref={ref}
    className={cn(tabsListVariants({ variant }), className)}
    {...props}
  />
));
TabsList.displayName = TabsPrimitive.List.displayName;

// ── TabsTrigger variants ─────────────────────────────────────────────────────

const tabsTriggerVariants = cva(
  // WHY text-[11px] not text-xs (12px): finance mandate — all data text 11px for density.
  "inline-flex items-center justify-center whitespace-nowrap text-[11px] font-medium ring-offset-background transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:pointer-events-none disabled:text-[hsl(var(--disabled-foreground))]",
  {
    variants: {
      variant: {
        // Default: pill with elevated background on active tab.
        // WHY data-[state=active]:text-primary: --primary is amber/gold.
        // Amber creates clear visual hierarchy over near-white inactive tabs.
        default:
          "rounded-sm px-3 py-1.5 data-[state=active]:bg-card data-[state=active]:text-primary",
        // Terminal: underline indicator, no background on active tab.
        // WHY rounded-none: terminal panels have zero border radius.
        // WHY -mb-px: pulls the bottom border of the trigger to overlap the
        // TabsList border-b, creating a seamless "selected underline" effect
        // without a double border on the inactive baseline.
        terminal:
          "rounded-none border-b-2 border-transparent bg-transparent px-3 h-8 -mb-px text-muted-foreground hover:text-foreground data-[state=active]:border-primary data-[state=active]:text-foreground data-[state=active]:bg-transparent data-[state=active]:shadow-none",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  },
);

interface TabsTriggerProps
  extends React.ComponentPropsWithoutRef<typeof TabsPrimitive.Trigger>,
    VariantProps<typeof tabsTriggerVariants> {}

const TabsTrigger = React.forwardRef<
  React.ElementRef<typeof TabsPrimitive.Trigger>,
  TabsTriggerProps
>(({ className, variant, ...props }, ref) => (
  <TabsPrimitive.Trigger
    ref={ref}
    className={cn(tabsTriggerVariants({ variant }), className)}
    {...props}
  />
));
TabsTrigger.displayName = TabsPrimitive.Trigger.displayName;

// ── TabsContent ──────────────────────────────────────────────────────────────

const TabsContent = React.forwardRef<
  React.ElementRef<typeof TabsPrimitive.Content>,
  React.ComponentPropsWithoutRef<typeof TabsPrimitive.Content>
>(({ className, ...props }, ref) => (
  <TabsPrimitive.Content
    ref={ref}
    className={cn(
      "mt-2 ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
      // WHY data-[state=inactive]:!hidden: Radix sets hidden="" on inactive panels, which relies
      // on the UA stylesheet [hidden]{display:none}. Tailwind display classes (flex, grid, block)
      // on the caller's className override UA styles and make the inactive panel visible.
      // This !important guard re-applies display:none for inactive tabs regardless of any
      // display class in the caller's className. (BP-381)
      "data-[state=inactive]:!hidden",
      className,
    )}
    {...props}
  />
));
TabsContent.displayName = TabsPrimitive.Content.displayName;

export { Tabs, TabsList, TabsTrigger, TabsContent };
