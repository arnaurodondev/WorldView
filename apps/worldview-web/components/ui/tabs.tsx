/**
 * components/ui/tabs.tsx — shadcn/ui Tabs (Radix UI)
 *
 * WHY THIS EXISTS: Used in Instrument Detail (Overview/Fundamentals/News/Intelligence),
 * Alerts/News page (Feed/Top Today), and Workspace panel headers.
 * Radix UI handles keyboard navigation (Arrow keys, focus management) for accessibility.
 *
 * "use client" — WHY: Radix Tabs uses internal state for active tab tracking
 * which requires browser-side rendering.
 */

"use client";

import * as React from "react";
import * as TabsPrimitive from "@radix-ui/react-tabs";
import { cn } from "@/lib/utils";

const Tabs = TabsPrimitive.Root;

const TabsList = React.forwardRef<
  React.ElementRef<typeof TabsPrimitive.List>,
  React.ComponentPropsWithoutRef<typeof TabsPrimitive.List>
>(({ className, ...props }, ref) => (
  <TabsPrimitive.List
    ref={ref}
    className={cn(
      // inline-flex h-9: compact tab bar that doesn't waste vertical space
      // bg-muted: slightly elevated from page background
      "inline-flex h-9 items-center justify-start rounded-[2px] bg-muted p-1 text-muted-foreground",
      className,
    )}
    {...props}
  />
));
TabsList.displayName = TabsPrimitive.List.displayName;

const TabsTrigger = React.forwardRef<
  React.ElementRef<typeof TabsPrimitive.Trigger>,
  React.ComponentPropsWithoutRef<typeof TabsPrimitive.Trigger>
>(({ className, ...props }, ref) => (
  <TabsPrimitive.Trigger
    ref={ref}
    className={cn(
      // WHY text-[11px] not text-xs (12px): finance mandate — all data text 11px for density.
      // text-[11px] is an explicit override to bypass Tailwind's font-size scale lookup.
      "inline-flex items-center justify-center whitespace-nowrap rounded-sm px-3 py-1.5 text-[11px] font-medium ring-offset-background transition-all",
      "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
      // PLAN-0059 W0 F-VISUAL-027: explicit tokens (was opacity-50)
      "disabled:pointer-events-none disabled:text-[hsl(var(--disabled-foreground))]",
      // Active tab: amber text on elevated muted background.
      // WHY text-primary not text-foreground: --primary is #E8A317 (amber/gold accent).
      // Previously active and inactive tabs looked nearly identical (both near-white).
      // Amber creates clear visual hierarchy — users instantly know which tab is active.
      // This affects every tab across the app: Portfolio, Instrument Detail, Alerts, Settings.
      "data-[state=active]:bg-card data-[state=active]:text-primary",
      className,
    )}
    {...props}
  />
));
TabsTrigger.displayName = TabsPrimitive.Trigger.displayName;

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
