/**
 * components/ui/period-selector.stories.tsx — Storybook stories for PeriodSelector
 *
 * WHY THIS EXISTS: PeriodSelector is a shared pill-row widget used in heatmap,
 * equity curve, and premarket movers. Stories validate the active pill (primary/20
 * tint + primary text) vs. inactive pill (muted-foreground) contrast under the
 * Midnight Pro dark background, and that all common period sets render without
 * wrapping.
 *
 * DESIGN SYSTEM: Midnight Pro — active: bg-primary/20 text-primary;
 *                               inactive: text-muted-foreground
 */

import type { Meta, StoryObj } from "@storybook/react";
import { useState } from "react";
import { PeriodSelector } from "./period-selector";

const meta: Meta<typeof PeriodSelector> = {
  title: "UI/PeriodSelector",
  component: PeriodSelector,
  parameters: { layout: "centered" },
  tags: ["autodocs"],
};
export default meta;
type Story = StoryObj<typeof meta>;

// ── Standard market periods (1D / 1W / 1M / 3M / 1Y) ────────────────────────
// WHY this is the primary story: it matches the most common call site (sector
// heatmap widget) with 1D selected by default — the most-used period on open.
export const Standard: Story = {
  args: {
    periods: ["1D", "1W", "1M", "3M", "1Y"] as const,
    selected: "1D",
    onSelect: () => {},
  },
};

// ── Extended periods (adds YTD and 5Y) ───────────────────────────────────────
// WHY: some widgets (equity curve) expose a longer date range. This verifies
// the pill row doesn't overflow or wrap at 7 items.
export const Extended: Story = {
  args: {
    periods: ["1D", "1W", "1M", "3M", "YTD", "1Y", "5Y"] as const,
    selected: "1M",
    onSelect: () => {},
  },
};

// ── Short periods only (intraday) ─────────────────────────────────────────────
export const Intraday: Story = {
  args: {
    periods: ["5m", "15m", "1h", "4h", "1D"] as const,
    selected: "1h",
    onSelect: () => {},
  },
};

// ── Interactive story (useState) ──────────────────────────────────────────────
// WHY: the args stories above use a no-op onSelect. This story wires real state
// so reviewers can click pills and see the active state update in the canvas.
// Uses a render function pattern because story args don't support hooks.
export const Interactive: Story = {
  render: () => {
    // eslint-disable-next-line react-hooks/rules-of-hooks
    const [period, setPeriod] = useState<string>("1M");
    return (
      <PeriodSelector
        periods={["1D", "1W", "1M", "3M", "1Y"]}
        selected={period}
        onSelect={setPeriod}
        ariaLabel="Chart period"
      />
    );
  },
};
