/**
 * tailwind.config.ts — Tailwind CSS v3 configuration with Bloomberg Dark palette
 *
 * WHY THIS EXISTS: Maps the Worldview "Bloomberg Dark" design token system to
 * Tailwind utility classes. The CSS variables (--background, --primary, etc.)
 * are defined in app/globals.css and referenced here so every shadcn/ui
 * component automatically uses the correct Bloomberg Dark colors.
 *
 * CRITICAL: Never use Tailwind's default slate-950 or blue-500.
 * Use the semantic tokens: bg-background, text-primary, bg-card, etc.
 *
 * DESIGN REFERENCE: docs/ui/DESIGN_SYSTEM.md §2 (Color Palette)
 */

import type { Config } from "tailwindcss";
import { fontFamily } from "tailwindcss/defaultTheme";

const config: Config = {
  // Dark mode via class strategy — we set class="dark" permanently on <html>
  // There is no light mode toggle (ADR-F-04)
  darkMode: ["class"],

  // Scan all app + component files for Tailwind class usage
  content: [
    "./pages/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "./app/**/*.{ts,tsx}",
    "./lib/**/*.{ts,tsx}",
    "./hooks/**/*.{ts,tsx}",
  ],
  prefix: "",
  theme: {
    container: {
      center: true,
      padding: "2rem",
      screens: { "2xl": "1400px" },
    },
    extend: {
      colors: {
        // Semantic color tokens — all backed by CSS variables in globals.css
        // This is why we never write hardcoded hex in components: the tokens
        // automatically switch if we ever need to adjust the palette.
        border: "hsl(var(--border))",
        input: "hsl(var(--input))",
        ring: "hsl(var(--ring))",
        background: "hsl(var(--background))",
        foreground: "hsl(var(--foreground))",
        primary: {
          DEFAULT: "hsl(var(--primary))",
          foreground: "hsl(var(--primary-foreground))",
        },
        secondary: {
          DEFAULT: "hsl(var(--secondary))",
          foreground: "hsl(var(--secondary-foreground))",
        },
        destructive: {
          DEFAULT: "hsl(var(--destructive))",
          foreground: "hsl(var(--destructive-foreground))",
        },
        muted: {
          DEFAULT: "hsl(var(--muted))",
          foreground: "hsl(var(--muted-foreground))",
        },
        accent: {
          DEFAULT: "hsl(var(--accent))",
          foreground: "hsl(var(--accent-foreground))",
        },
        popover: {
          DEFAULT: "hsl(var(--popover))",
          foreground: "hsl(var(--popover-foreground))",
        },
        card: {
          DEFAULT: "hsl(var(--card))",
          foreground: "hsl(var(--card-foreground))",
        },

        // Financial domain tokens — no equivalent in standard Tailwind
        // positive = teal-green (price up, portfolio gain)
        // negative = muted red (price down, loss)
        // warning = amber (medium severity alerts)
        positive: "hsl(var(--positive))",
        negative: "hsl(var(--negative))",
        warning: "hsl(var(--warning))",

        // Surface elevation tokens — explicit surface-level steps for
        // components that need more granularity than card/muted (e.g.,
        // nested panels, tertiary backgrounds). Defined in globals.css.
        "surface-2": "hsl(var(--surface-2))",
        "surface-3": "hsl(var(--surface-3))",
      },
      borderRadius: {
        lg: "var(--radius)",
        md: "calc(var(--radius) - 2px)",
        sm: "calc(var(--radius) - 4px)",
      },
      fontFamily: {
        // IBM Plex Sans for UI labels and prose — loaded via next/font/google
        sans: ["var(--font-sans)", ...fontFamily.sans],
        // IBM Plex Mono for ALL numeric values (prices, %, quantities, dates)
        // This is the single highest-impact change for professional appearance (ADR-F-15)
        mono: ["var(--font-mono)", ...fontFamily.mono],
      },
      keyframes: {
        // Used by shadcn/ui Accordion component
        "accordion-down": {
          from: { height: "0" },
          to: { height: "var(--radix-accordion-content-height)" },
        },
        "accordion-up": {
          from: { height: "var(--radix-accordion-content-height)" },
          to: { height: "0" },
        },
        // Flash overlay entrance animation — fast (150ms) for urgent alerts
        "flash-in": {
          from: { opacity: "0", transform: "translateY(-4px)" },
          to: { opacity: "1", transform: "translateY(0)" },
        },
        // Skeleton pulse — slower than default, less distracting for finance users
        "skeleton-pulse": {
          "0%, 100%": { opacity: "1" },
          "50%": { opacity: "0.4" },
        },
      },
      animation: {
        "accordion-down": "accordion-down 0.2s ease-out",
        "accordion-up": "accordion-up 0.2s ease-out",
        "flash-in": "flash-in 0.15s ease-out",
        "skeleton-pulse": "skeleton-pulse 2s ease-in-out infinite",
      },
    },
  },
  plugins: [
    // tailwindcss-animate: required by shadcn/ui components (Dialog, Sheet, etc.)
    require("tailwindcss-animate"),
  ],
};

export default config;
