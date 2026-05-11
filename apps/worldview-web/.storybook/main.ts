/**
 * .storybook/main.ts — Storybook 8 configuration for worldview-web
 *
 * WHY THIS EXISTS: Storybook provides a sandboxed development environment
 * for UI primitives, enabling design review and visual regression testing
 * without spinning up the full Next.js + API stack.
 *
 * WHY @storybook/nextjs framework: it handles Next.js-specific features
 * (App Router, Image, fonts, CSS modules) automatically, so stories work
 * the same way components do in the real app — no manual mocking of Next
 * internals (next/navigation, next/image, etc.).
 *
 * Stories are co-located with components rather than a top-level /stories
 * directory, so each component's story is discoverable next to its source.
 */

import type { StorybookConfig } from "@storybook/nextjs";

const config: StorybookConfig = {
  // Glob patterns for story files — co-located with components and features.
  // WHY .@(ts|tsx) not .{ts,tsx}: Storybook uses micromatch which prefers
  // the brace-expansion @() syntax for OR matching in this context.
  stories: [
    "../components/**/*.stories.@(ts|tsx)",
    "../features/**/*.stories.@(ts|tsx)",
  ],

  addons: [
    // WHY addon-essentials: ships Controls, Actions, Docs, Backgrounds,
    // Viewport — the full set of standard Storybook panels with zero config.
    "@storybook/addon-essentials",
    // WHY addon-interactions: enables play() functions for user-interaction
    // testing (click, type, hover) directly inside Storybook.
    "@storybook/addon-interactions",
  ],

  framework: {
    name: "@storybook/nextjs",
    options: {},
  },

  // WHY autodocs: 'tag': generates a docs page automatically for any story
  // that adds the 'autodocs' tag — opt-in per component rather than global,
  // so we don't get noisy empty docs for simple wrappers.
  docs: { autodocs: "tag" },
};

export default config;
