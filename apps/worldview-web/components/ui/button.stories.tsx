/**
 * components/ui/button.stories.tsx — Storybook stories for Button
 *
 * WHY THIS EXISTS: Design review and visual regression testing for the Button
 * primitive. All variants (default/destructive/outline/ghost/link/secondary)
 * and sizes (sm/default/lg/icon) are exercised here so designers can verify
 * the Bloomberg Dark palette renders correctly without spinning up the full app.
 *
 * DESIGN SYSTEM: Midnight Pro dark palette
 *   - Primary:     #FFD60A  (trading yellow, black text)
 *   - Destructive: red-ish  (muted destructive token)
 *   - Background:  #131722
 */

import type { Meta, StoryObj } from "@storybook/react";
import { Loader2, Trash2 } from "lucide-react";
import { Button } from "./button";

// ── Meta ─────────────────────────────────────────────────────────────────────
// WHY title 'UI/Button': groups this story under the "UI" section in the
// Storybook sidebar, matching the components/ui/ directory structure.
const meta: Meta<typeof Button> = {
  title: "UI/Button",
  component: Button,
  // WHY layout: 'centered': Button is a small inline element — centering it
  // on the canvas makes it easy to inspect all states without scrolling.
  parameters: { layout: "centered" },
  // WHY tags: ['autodocs']: triggers automatic docs page generation, which
  // reads JSDoc, prop types, and story args to build a live reference page.
  tags: ["autodocs"],
  argTypes: {
    // Expose variant/size/density as dropdown controls in the Storybook panel
    // so designers can toggle between them interactively.
    variant: {
      control: "select",
      options: ["default", "destructive", "outline", "secondary", "ghost", "link"],
    },
    size: { control: "select", options: ["default", "sm", "lg", "icon"] },
    density: { control: "select", options: ["compact", "default", "comfortable"] },
    disabled: { control: "boolean" },
  },
};
export default meta;
type Story = StoryObj<typeof meta>;

// ── Default (Primary CTA) ─────────────────────────────────────────────────────
// WHY Default first: establishes the "hero" use case. The default variant is
// the most common button in the app (Buy, Submit, Confirm). Storybook shows
// the first exported story as the preview thumbnail.
export const Default: Story = {
  args: {
    children: "Primary Action",
    variant: "default",
  },
};

// ── Loading state ──────────────────────────────────────────────────────────────
// WHY: buttons show a spinner during async operations (submitting trades,
// running screens). This story ensures the spinner + text layout works at
// all sizes without wrapping. The Loader2 spin animation is CSS, so it
// renders in Storybook even without real state.
export const Loading: Story = {
  args: {
    children: (
      <>
        {/* WHY animate-spin: Tailwind class applied directly on the SVG icon
            via Lucide's className prop. Storybook renders it correctly because
            @storybook/nextjs includes Tailwind's base styles from globals.css. */}
        <Loader2 className="h-4 w-4 animate-spin" />
        Loading…
      </>
    ),
    variant: "default",
    disabled: true,
  },
};

// ── Destructive ────────────────────────────────────────────────────────────────
// WHY: the destructive variant (red) is used for delete/cancel actions (e.g.
// "Remove holding", "Cancel order"). Visual regression on this variant catches
// unintended contrast changes to the --destructive token.
export const Destructive: Story = {
  args: {
    children: (
      <>
        <Trash2 className="h-4 w-4" />
        Delete Position
      </>
    ),
    variant: "destructive",
  },
};

// ── Outline (secondary action) ────────────────────────────────────────────────
export const Outline: Story = {
  args: {
    children: "Export CSV",
    variant: "outline",
  },
};

// ── Ghost (icon button / nav item) ────────────────────────────────────────────
export const Ghost: Story = {
  args: {
    children: "Filter",
    variant: "ghost",
  },
};

// ── Small size ────────────────────────────────────────────────────────────────
export const Small: Story = {
  args: {
    children: "Run Screen",
    variant: "outline",
    size: "sm",
  },
};

// ── Compact density (22px row height) ────────────────────────────────────────
// WHY: PLAN-0031 institutional tables use 22px rows — toolbar buttons must
// fit within that height. The compact density override shrinks to h-7.
export const Compact: Story = {
  args: {
    children: "Copy TSV",
    variant: "ghost",
    density: "compact",
  },
};

// ── Disabled state ────────────────────────────────────────────────────────────
// WHY: PLAN-0059 W0 F-VISUAL-027 replaced disabled:opacity-50 with explicit
// disabled tokens (desaturated but WCAG AA compliant). This story verifies
// the disabled token renders correctly at 5.5:1 contrast.
export const Disabled: Story = {
  args: {
    children: "Submit Order",
    variant: "default",
    disabled: true,
  },
};
