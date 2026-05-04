/**
 * .storybook/preview.ts — Global decorators and parameters for all stories
 *
 * WHY THIS EXISTS: Every story needs the app's global CSS (design tokens,
 * Tailwind utilities, custom properties) to render correctly. Without
 * importing globals.css here, components appear without any styling at all.
 *
 * WHY import '../app/globals.css': the globals.css lives in app/ (App Router
 * convention). Storybook's webpack/vite pipeline resolves this path relative
 * to .storybook/, making '../app/globals.css' the correct relative import.
 *
 * WHY backgrounds.default = 'dark': worldview enforces a permanent dark theme
 * (Midnight Pro palette, #131722 base). Defaulting to a light Storybook canvas
 * would produce misleading screenshots where text is invisible (e.g.
 * text-foreground renders ~#E2E8F0 on white = washed out). Setting the dark
 * background ensures what you see in Storybook matches production.
 */

import type { Preview } from "@storybook/react";
import "../app/globals.css";

const preview: Preview = {
  parameters: {
    // Background canvas: hardcoded to the Midnight Pro base color.
    // WHY only one value (not light + dark toggle): the app has no light theme.
    // Offering a light option would let developers accidentally design
    // components that look fine on light but break on dark — the app's only
    // real context.
    backgrounds: {
      default: "dark",
      values: [{ name: "dark", value: "#131722" }],
    },
  },
};

export default preview;
