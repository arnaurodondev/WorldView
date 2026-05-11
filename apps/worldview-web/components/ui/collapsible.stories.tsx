/**
 * components/ui/collapsible.stories.tsx — Storybook stories for Collapsible
 *
 * WHY THIS EXISTS: Collapsible (Radix-based) is used in the instrument Overview
 * tab's right sidebar to collapse/expand Competitors and News zones. Stories
 * validate the open/closed states and the trigger affordance (ChevronDown icon)
 * under the Midnight Pro palette.
 *
 * WHY render functions instead of args: Collapsible requires controlled
 * (defaultOpen) or uncontrolled (open + onOpenChange) state — there's no
 * single flat prop that Storybook Controls can set for "collapsed" vs "expanded"
 * without wiring useState. Render functions are the idiomatic pattern for
 * stateful primitives in Storybook.
 *
 * DESIGN SYSTEM: Midnight Pro dark palette (#131722 bg, border-border separators)
 */

import type { Decorator, Meta, StoryObj } from "@storybook/react";
import * as React from "react";
import { useState } from "react";
import { ChevronDown } from "lucide-react";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "./collapsible";

// ── Meta ─────────────────────────────────────────────────────────────────────
// WHY component: Collapsible (Root): the Root is the only entry point that
// Storybook's autodocs can introspect for prop types. The Trigger and Content
// sub-components are composed in each story.
const meta: Meta<typeof Collapsible> = {
  title: "UI/Collapsible",
  component: Collapsible,
  parameters: { layout: "centered" },
  tags: ["autodocs"],
  decorators: [
    // WHY fixed width: Collapsible content uses block layout. Without a width
    // constraint the story renders full-canvas width, which isn't representative
    // of its real context (a 280px sidebar column).
    ((Story: React.ComponentType) => (
      <div className="w-72 bg-card border border-border rounded-[2px] p-0">
        <Story />
      </div>
    )) as Decorator,
  ],
};
export default meta;
type Story = StoryObj<typeof meta>;

// ── Collapsed (default closed) ────────────────────────────────────────────────
// WHY defaultOpen={false}: shows the component in its initial state on page
// load — header visible, content hidden. Designers can verify the trigger
// looks correct before any interaction.
export const Collapsed: Story = {
  render: () => (
    <Collapsible defaultOpen={false}>
      {/* WHY flex items-center justify-between: matches the Overview sidebar
          header layout (label on left, chevron on right). */}
      <CollapsibleTrigger className="flex w-full items-center justify-between px-3 py-2 text-[11px] uppercase tracking-[0.08em] text-muted-foreground hover:text-foreground transition-colors">
        <span>Competitors</span>
        {/* WHY no rotate class here: Radix doesn't expose data-state on the
            trigger in static Storybook without interaction. The actual app
            component in FundamentalsTab uses data-[state=open]:rotate-180.
            This story shows the initial state only. */}
        <ChevronDown className="h-3 w-3 shrink-0" />
      </CollapsibleTrigger>
      <CollapsibleContent>
        <div className="px-3 py-2 text-[11px] text-muted-foreground border-t border-border">
          Content is visible when expanded.
        </div>
      </CollapsibleContent>
    </Collapsible>
  ),
};

// ── Expanded (defaultOpen) ────────────────────────────────────────────────────
// WHY defaultOpen={true}: shows the content zone visible — lets designers
// review the expanded state typography and spacing.
export const Expanded: Story = {
  render: () => (
    <Collapsible defaultOpen={true}>
      <CollapsibleTrigger className="flex w-full items-center justify-between px-3 py-2 text-[11px] uppercase tracking-[0.08em] text-muted-foreground hover:text-foreground transition-colors">
        <span>Key Metrics</span>
        <ChevronDown className="h-3 w-3 shrink-0" />
      </CollapsibleTrigger>
      <CollapsibleContent>
        <div className="px-3 pb-3 pt-1 border-t border-border space-y-1">
          {/* WHY tabular-nums: metric values are numbers that must align vertically */}
          {[
            { label: "P/E Ratio", value: "28.4×" },
            { label: "EPS (TTM)", value: "$6.43" },
            { label: "Revenue", value: "$394.3B" },
            { label: "Net Margin", value: "25.3%" },
          ].map(({ label, value }) => (
            <div key={label} className="flex items-center justify-between text-[11px]">
              <span className="text-muted-foreground">{label}</span>
              <span className="tabular-nums font-mono">{value}</span>
            </div>
          ))}
        </div>
      </CollapsibleContent>
    </Collapsible>
  ),
};

// ── Interactive (toggle state) ────────────────────────────────────────────────
// WHY: the static stories (Collapsed/Expanded) can't demonstrate the open/close
// transition. This story wires controlled state so reviewers can click the
// trigger and see the content animate in/out.
export const Interactive: Story = {
  render: () => {
    // eslint-disable-next-line react-hooks/rules-of-hooks
    const [open, setOpen] = useState(false);
    return (
      <Collapsible open={open} onOpenChange={setOpen}>
        <CollapsibleTrigger className="flex w-full items-center justify-between px-3 py-2 text-[11px] uppercase tracking-[0.08em] text-muted-foreground hover:text-foreground transition-colors">
          <span>Recent News</span>
          <ChevronDown
            className={`h-3 w-3 shrink-0 transition-transform duration-200 ${open ? "rotate-180" : ""}`}
          />
        </CollapsibleTrigger>
        <CollapsibleContent>
          <div className="px-3 pb-2 pt-1 border-t border-border text-[11px] text-muted-foreground space-y-1">
            <p>Apple reports Q1 2026 earnings beat.</p>
            <p>Tim Cook comments on AI strategy shift.</p>
            <p>iPhone 17 supply chain expansion confirmed.</p>
          </div>
        </CollapsibleContent>
      </Collapsible>
    );
  },
};
