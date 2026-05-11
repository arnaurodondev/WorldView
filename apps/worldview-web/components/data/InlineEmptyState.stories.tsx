/**
 * components/data/InlineEmptyState.stories.tsx — Storybook stories for InlineEmptyState
 *
 * WHY THIS EXISTS: InlineEmptyState is the standard empty indicator for all
 * data panels (Holdings, Alerts, News, etc.). Storybook lets us verify it
 * stays compact (single-line) and readable (muted-foreground on #131722) across
 * all message lengths without loading a real panel.
 *
 * DESIGN SYSTEM: Midnight Pro dark palette — text-muted-foreground on #131722 bg
 */

import type { Meta, StoryObj } from "@storybook/react";
import { InlineEmptyState } from "./InlineEmptyState";

const meta: Meta<typeof InlineEmptyState> = {
  title: "Data/InlineEmptyState",
  component: InlineEmptyState,
  // WHY layout: 'padded': slightly wider than 'centered' — the empty state is
  // a block-level paragraph that needs horizontal room to show realistic message lengths.
  parameters: { layout: "padded" },
  tags: ["autodocs"],
};
export default meta;
type Story = StoryObj<typeof meta>;

// ── Default ────────────────────────────────────────────────────────────────────
// WHY this message: "No holdings yet." is the most common use case (empty
// portfolio). It exercises the minimal one-sentence format.
export const Default: Story = {
  args: {
    message: "No holdings yet.",
  },
};

// ── Short message ─────────────────────────────────────────────────────────────
// WHY: covers cases like "No alerts." (Alerts panel) where the message is even
// shorter than the default. Verifies the component doesn't add extra padding.
export const ShortMessage: Story = {
  args: {
    message: "No alerts.",
  },
};

// ── Long message ──────────────────────────────────────────────────────────────
// WHY: some panels include a helpful hint in the empty state (e.g. screener
// over-filtered). This story ensures the text wraps cleanly without breaking
// the panel layout.
export const LongMessage: Story = {
  args: {
    message:
      "No instruments match your current filters. Try widening your criteria or clearing all active filters.",
  },
};

// ── Custom className (reduced padding) ────────────────────────────────────────
// WHY: some call sites (e.g. IntelligenceTab) pass className="py-2" to reduce
// vertical space. This story verifies the override works without side effects.
export const CompactPadding: Story = {
  args: {
    message: "No intelligence items.",
    className: "py-2",
  },
};
