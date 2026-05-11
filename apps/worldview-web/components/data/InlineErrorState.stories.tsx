/**
 * components/data/InlineErrorState.stories.tsx — Storybook stories for InlineErrorState
 *
 * WHY THIS EXISTS: InlineErrorState degrades panels professionally when data
 * fails to load. Storybook validates the destructive color token (red) renders
 * with sufficient contrast on #131722 and that message text is legible without
 * a full-page error card.
 *
 * DESIGN SYSTEM: Midnight Pro dark palette — text-destructive on #131722 bg
 */

import type { Meta, StoryObj } from "@storybook/react";
import { InlineErrorState } from "./InlineErrorState";

const meta: Meta<typeof InlineErrorState> = {
  title: "Data/InlineErrorState",
  component: InlineErrorState,
  parameters: { layout: "padded" },
  tags: ["autodocs"],
};
export default meta;
type Story = StoryObj<typeof meta>;

// ── Default (generic error) ────────────────────────────────────────────────────
// WHY: uses the built-in default message "Failed to load data." — covers all
// panels that don't need a custom message (most API error states).
export const Default: Story = {
  args: {},
};

// ── Custom error message ───────────────────────────────────────────────────────
// WHY: several panels provide context-specific messages (e.g. "Failed to load
// alerts." vs. "Failed to load intelligence feed."). This story ensures the
// custom message prop overrides the default correctly.
export const CustomMessage: Story = {
  args: {
    message: "Failed to load alerts. Check your connection and try again.",
  },
};

// ── Fundamentals load failure ─────────────────────────────────────────────────
// WHY: FundamentalsTab renders InlineErrorState when the API call fails.
// This story simulates that specific use case.
export const FundamentalsError: Story = {
  args: {
    message: "Failed to load fundamentals data.",
  },
};

// ── Intelligence feed failure ─────────────────────────────────────────────────
export const IntelligenceFeedError: Story = {
  args: {
    message: "Intelligence feed unavailable. Try refreshing the page.",
  },
};
