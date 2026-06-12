/**
 * tailwind.config.ts — Tailwind CSS v3 configuration with Terminal Dark palette
 *
 * WHY THIS EXISTS: Maps the Worldview "Terminal Dark" design token system to
 * Tailwind utility classes. The CSS variables (--background, --primary, etc.)
 * are defined in app/globals.css and referenced here so every shadcn/ui
 * component automatically uses the correct Terminal Dark colors.
 *
 * CRITICAL: Never use Tailwind's default slate-950 or blue-500.
 * Use the semantic tokens: bg-background, text-primary, bg-card, etc.
 * Never reference old Bloomberg Dark values: #0A0E14, #E8A317, #E0DDD4.
 *
 * DESIGN REFERENCE: docs/ui/DESIGN_SYSTEM.md §2 (Color Palette — Terminal Dark)
 */

import type { Config } from "tailwindcss";
import { fontFamily } from "tailwindcss/defaultTheme";

const config: Config = {
  // Dark mode via class strategy — we set class="dark" permanently on <html>
  // There is no light mode toggle (ADR-F-04)
  darkMode: ["class"],

  // Scan all app + component files for Tailwind class usage.
  //
  // BUG FIX (2026-06-11, Wave 3 portfolio layout): `./features/**` was MISSING
  // from this list. Tailwind JIT only generates CSS for classes it finds in
  // scanned files — any class used EXCLUSIVELY inside features/ (e.g. the
  // portfolio overview band's `xl:grid-cols-3`, the Analytics tab's
  // `lg:col-span-9`) was silently never emitted, so those layouts collapsed
  // to stacked full-width blocks at every viewport. The bug is invisible in
  // unit tests (jsdom doesn't apply CSS) and only shows up as broken layout
  // in the browser. Guarded by __tests__/tailwind-content-coverage.test.ts,
  // which fails if any directory containing className usage is not scanned.
  content: [
    "./pages/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "./app/**/*.{ts,tsx}",
    "./lib/**/*.{ts,tsx}",
    "./hooks/**/*.{ts,tsx}",
    "./features/**/*.{ts,tsx}",
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
          // R4 deferred item: AA-passing tertiary dim (replaces the WCAG-failing
          // text-muted-foreground/70|60|50 opacity steps on informational text).
          // Class form: text-muted-foreground-dim. See globals.css token comment.
          "foreground-dim": "hsl(var(--muted-foreground-dim))",
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

        // PRD-0089 F1: cell-grid border tokens for data-table-grid surfaces.
        // border-strong is the visible inner cell line (Bloomberg "STAT" panels
        // use a comparable shade); border-subtle is the row divider.  Components
        // never reach for hardcoded #37373B / #1E1E22 — they use these utilities.
        "border-strong": "hsl(var(--border-strong))",
        "border-subtle": "hsl(var(--border-subtle))",
      },
      borderRadius: {
        // PRD-0089 F1: every alias collapses to 0 except `full` (dots/avatars).
        // Why explicitly map sm/md/lg/xl/2xl/3xl instead of just leaving them
        // out: Tailwind's `extend` is ADDITIVE — unspecified keys fall back to
        // framework defaults (sm=2px through 3xl=24px). To enforce the
        // sharp-corner contract even before PRs C-G strip the class strings,
        // every alias must explicitly resolve to 0 at the utility level.
        // Bloomberg / Refinitiv / IBKR TWS / Eikon panels: all 0px radius.
        none: "0",
        sm: "0",
        DEFAULT: "0",
        md: "0",
        lg: "0",
        xl: "0",
        "2xl": "0",
        "3xl": "0",
        full: "9999px",
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
      // PRD-0089 F1: zero shadows on Terminal Dark.
      // Why map every Tailwind shadow alias to "none": components that still
      // reference shadow-sm / shadow-md / shadow-lg should compile (class
      // strings remain valid) but render no elevation. Bloomberg/Eikon panels
      // never use box-shadow for chrome — only 1px borders. Eliminates the
      // dead-code documentation lie of "shadows are reset in globals.css"
      // (that runtime reset still exists for defense-in-depth, but now the
      // Tailwind utility itself emits `box-shadow: none`).
      boxShadow: {
        none: "none",
        sm: "none",
        DEFAULT: "none",
        md: "none",
        lg: "none",
        xl: "none",
        "2xl": "none",
        inner: "none",
      },
      // PRD-0089 F1 NFR-6: named transition tokens. Tier-1 (affordance) and
      // Tier-2 (chrome state) live here. Components MUST use these instead
      // of `transition-all` (banned by post-F1 arch-test lockdown) because
      // `transition-all` accidentally animates layout properties (width,
      // height, max-h) which produces Tier-0 violations.
      transitionProperty: {
        // Tier-1: color/border-color only — for row hover, button hover,
        // focus-ring intro. Ceiling 100ms (see transitionDuration below).
        "color-only": "color, background-color, border-color, fill, stroke",
        // Tier-2: chrome state — adds opacity for popover/dropdown fade-in.
        // Ceiling 200ms.
        "color-and-opacity":
          "color, background-color, border-color, opacity",
      },
      transitionDuration: {
        // Explicit ms tokens reinforcing the 4-tier animation policy.
        // 75/100 = Tier-1; 150/200 = Tier-2. Anything ≥300ms blocked by
        // the no-off-palette-colors arch-test post-F1 lockdown.
        "75": "75ms",
        "100": "100ms",
        "150": "150ms",
        "200": "200ms",
      },
      // WHY grid-cols-14: Intelligence tab uses a 14-column grid (4+7+3 layout)
      // for higher density than the previous 12-col split. Literal string
      // `grid-cols-14` required so Tailwind JIT scanner picks it up at build
      // time (dynamic `grid-cols-${n}` is NOT scanned by JIT).
      gridTemplateColumns: {
        "14": "repeat(14, minmax(0, 1fr))",
      },
    },
  },
  plugins: [
    // tailwindcss-animate: required by shadcn/ui components (Dialog, Sheet, etc.)
    require("tailwindcss-animate"),
  ],
};

export default config;
