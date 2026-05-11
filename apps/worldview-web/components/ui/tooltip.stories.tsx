/**
 * components/ui/tooltip.stories.tsx — Storybook stories for Tooltip
 *
 * WHY THIS EXISTS: Tooltip is used throughout the screener filter bar (metric
 * explanation overlays) and chart controls. Stories validate the styled
 * TooltipContent (bg-card border-border, rounded-[2px], 10px mono text) renders
 * correctly on the Midnight Pro dark background.
 *
 * WHY render functions (not args): Tooltip requires a trigger element and a
 * Provider wrapper — these can't be expressed as flat Storybook args. The render
 * pattern is idiomatic for compound components.
 *
 * DESIGN SYSTEM: Midnight Pro — bg-card border-border, font-mono text-[10px],
 *                               max-w-[220px], rounded-[2px] (no border radius)
 */

import type { Decorator, Meta, StoryObj } from "@storybook/react";
import * as React from "react";
import { Info } from "lucide-react";
import { Button } from "./button";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "./tooltip";

const meta: Meta<typeof Tooltip> = {
  title: "UI/Tooltip",
  component: Tooltip,
  parameters: {
    layout: "centered",
    // WHY backgrounds.default: tooltip uses Portal rendering — it renders
    // outside its trigger's DOM subtree. The dark background must be set
    // globally so the portal also appears on the dark canvas.
  },
  tags: ["autodocs"],
  decorators: [
    // WHY TooltipProvider wrapper: Radix Tooltip requires a Provider ancestor
    // (DelayDurationContext). Without it the tooltip never opens. Each story
    // is wrapped here so the decorator applies to all stories in this file.
    ((Story: React.ComponentType) => (
      <TooltipProvider>
        <Story />
      </TooltipProvider>
    )) as Decorator,
  ],
};
export default meta;
type Story = StoryObj<typeof meta>;

// ── Default (icon trigger with metric explanation) ────────────────────────────
// WHY: the primary use case is screener filter Info icons that explain metrics
// (e.g. "P/E Ratio: Price divided by trailing 12-month earnings per share").
// This story matches that exact pattern.
export const Default: Story = {
  render: () => (
    <Tooltip>
      <TooltipTrigger asChild>
        {/* WHY asChild: renders the trigger onto the child <Button> element so
            the button keeps its own HTML semantics (button[type=button]) rather
            than being nested inside another button. */}
        <Button variant="ghost" size="icon" aria-label="P/E Ratio info">
          <Info className="h-3 w-3 text-muted-foreground" />
        </Button>
      </TooltipTrigger>
      <TooltipContent>
        Price-to-Earnings ratio: share price divided by trailing 12-month EPS.
        Higher = more expensive relative to earnings.
      </TooltipContent>
    </Tooltip>
  ),
};

// ── Text trigger ──────────────────────────────────────────────────────────────
// WHY: some triggers are text labels (e.g. column headers that need definition
// overlays). This story validates that plain text triggers work without an icon.
export const TextTrigger: Story = {
  render: () => (
    <Tooltip>
      <TooltipTrigger asChild>
        <button
          type="button"
          className="text-[11px] font-mono text-muted-foreground underline decoration-dotted hover:text-foreground"
        >
          EV/EBITDA
        </button>
      </TooltipTrigger>
      <TooltipContent>
        Enterprise Value divided by EBITDA. A valuation multiple that accounts
        for debt and cash; useful for comparing companies across capital structures.
      </TooltipContent>
    </Tooltip>
  ),
};

// ── Long content (max-w-[220px] wrapping) ────────────────────────────────────
// WHY: TooltipContent has max-w-[220px] to stay within the screener filter
// column width. This story verifies long explanations wrap cleanly rather than
// extending off-screen.
export const LongContent: Story = {
  render: () => (
    <Tooltip>
      <TooltipTrigger asChild>
        <Button variant="ghost" size="icon" aria-label="Debt/EBITDA info">
          <Info className="h-3 w-3 text-muted-foreground" />
        </Button>
      </TooltipTrigger>
      <TooltipContent>
        Net Debt / EBITDA: leverage ratio showing how many years of operating
        earnings it would take to repay net debt. Below 2× is generally
        considered conservative. Above 4× may signal stress in cyclical sectors.
      </TooltipContent>
    </Tooltip>
  ),
};

// ── Side variations ────────────────────────────────────────────────────────────
// WHY: TooltipContent supports side=top|bottom|left|right. In the screener
// sidebar, tooltips appear on the right of the filter column to avoid clipping
// at the left edge. This story validates right-side placement.
export const SideRight: Story = {
  render: () => (
    <Tooltip>
      <TooltipTrigger asChild>
        <Button variant="ghost" size="icon" aria-label="Revenue info">
          <Info className="h-3 w-3 text-muted-foreground" />
        </Button>
      </TooltipTrigger>
      <TooltipContent side="right">
        Trailing twelve months total revenue in USD.
      </TooltipContent>
    </Tooltip>
  ),
};
