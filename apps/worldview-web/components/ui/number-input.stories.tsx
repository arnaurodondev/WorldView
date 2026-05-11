/**
 * components/ui/number-input.stories.tsx — Storybook stories for NumberInput
 *
 * WHY THIS EXISTS: NumberInput parses shorthand notation (1.5m → 1500000,
 * 2% → 0.02) and shows a live parse-preview ghost while focused. Stories
 * validate the input layout (text-right tabular-nums monospace), the
 * parse-preview ghost positioning, and the error state (aria-invalid border).
 *
 * NOTE: The parse-preview ghost is only visible when the field is focused —
 * in Storybook's static canvas it won't appear unless you interact with it.
 * Use the Interactive story to see the ghost in action.
 *
 * DESIGN SYSTEM: Midnight Pro — compact density (default), tabular-nums
 */

import type { Decorator, Meta, StoryObj } from "@storybook/react";
import * as React from "react";
import { useState } from "react";
import { NumberInput } from "./number-input";

const meta: Meta<typeof NumberInput> = {
  title: "UI/NumberInput",
  component: NumberInput,
  parameters: { layout: "centered" },
  tags: ["autodocs"],
  decorators: [
    // WHY width wrapper: NumberInput is `inline-block w-full`. Without a
    // constrained parent it stretches to 100% of the Storybook canvas, which
    // makes the compact variant appear unusually wide.
    ((Story: React.ComponentType) => (
      <div className="w-40">
        <Story />
      </div>
    )) as Decorator,
  ],
};
export default meta;
type Story = StoryObj<typeof meta>;

// ── Default (null value, compact density) ────────────────────────────────────
// WHY null default: when no value has been committed the field shows an empty
// string (via formatShorthand(null) → "")), which is the correct initial state
// for a screener filter or order quantity field before the user types.
export const Default: Story = {
  args: {
    value: null,
    onValueChange: () => {},
    placeholder: "Enter value",
    density: "compact",
  },
};

// ── Pre-populated with a large number ────────────────────────────────────────
// WHY: demonstrates the shorthand formatter — the stored value 1500000 renders
// as "1.5M" in the input (formatShorthand). This verifies the formatter fires
// correctly on mount (not just on blur).
export const Populated: Story = {
  args: {
    value: 1500000,
    onValueChange: () => {},
    density: "compact",
  },
};

// ── Comfortable density ───────────────────────────────────────────────────────
// WHY: some form layouts (e.g. Order entry modal) use the comfortable density
// for better touch target size. This story checks h-10 renders correctly.
export const Comfortable: Story = {
  args: {
    value: 42.5,
    onValueChange: () => {},
    density: "comfortable",
  },
};

// ── Percentage value ──────────────────────────────────────────────────────────
// WHY: percent=true (default) means "2%" is stored as 0.02, not 2. Displaying
// 0.025 should format as "2.5%". This story validates round-trip formatting.
export const PercentValue: Story = {
  args: {
    value: 0.025,
    onValueChange: () => {},
    density: "compact",
    percent: true,
    placeholder: "e.g. 2%",
  },
};

// ── Interactive (shows parse-preview ghost) ───────────────────────────────────
// WHY: the static stories above can't show the focused state (live ghost).
// This interactive story wires real state so reviewers can type "1.5m" and
// see "≈ 1.5M" appear in the ghost preview.
export const Interactive: Story = {
  render: () => {
    // eslint-disable-next-line react-hooks/rules-of-hooks
    const [val, setVal] = useState<number | null>(null);
    return (
      <div className="flex flex-col gap-2">
        <NumberInput
          value={val}
          onValueChange={setVal}
          placeholder="Type 1.5m or 2%…"
          density="compact"
        />
        <p className="text-[11px] text-muted-foreground">
          Parsed value: {val === null ? "null" : val.toString()}
        </p>
      </div>
    );
  },
};
