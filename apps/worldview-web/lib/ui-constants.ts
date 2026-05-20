/**
 * lib/ui-constants.ts — Canonical UI density and layout constants.
 *
 * WHY THIS EXISTS (DS-012, FR-10.6):
 * Before this module, density-defining class strings (row height, font size,
 * padding, border-radius) were redeclared independently in Button, Input,
 * DateRangePicker, and 4+ other components. Each redeclaration created drift:
 *   - Button used `h-7 px-2 text-[11px]` for compact
 *   - DateRangePicker used `h-7 px-3 text-xs` (different padding, different size token)
 *   - TransactionsTable rows used `h-[22px] py-0.5` (correct) in one file,
 *     `h-8 py-1` (wrong: 32px, not 22px) in another
 *
 * The DENSITY_CLASSES record is the authoritative mapping from surface name
 * to the Tailwind class string that implements it. Import it wherever a
 * surface's density class is needed.
 *
 * REFERENCE: PRD frontend platform hardening §6.N "Visual Density Reference"
 *
 * USAGE:
 *   import { DENSITY_CLASSES } from "@/lib/ui-constants";
 *   <tr className={DENSITY_CLASSES.tableRow}>...</tr>
 *   <button className={cn(DENSITY_CLASSES.buttonCompact, "bg-primary")}>...</button>
 *
 * WHY `as const`: the values are literal string types, not `string`. This lets
 * TypeScript enforce that surface names are used correctly (typos become
 * "property does not exist on type" errors).
 */

// ── Visual Density Reference (DESIGN_SYSTEM.md §6.N) ────────────────────────

/**
 * DENSITY_CLASSES — per-surface Tailwind class strings for the Terminal Dark
 * density system.
 *
 * Heights are in px (not rem) for pixel-precise grid alignment — see globals.css
 * comment on structural density tokens for the rationale.
 *
 * These classes represent the MINIMUM chrome for each surface. Consumers may
 * extend with additional classes (color, hover state, etc.) via `cn()`.
 */
export const DENSITY_CLASSES = {
  /**
   * tableRow — 22px data row for Holdings, Transactions, Screener results.
   * WHY 22px (not 24px or h-8/32px): PRD-0031 mandates 22px data rows for
   * institutional density. Bloomberg Terminal uses 22-24px rows. h-8 (32px)
   * is the shadcn default — too spacious for a finance terminal.
   */
  tableRow: "h-[22px] px-2 py-0.5 text-[11px]",

  /**
   * articleRow — 28px news / article feed row.
   * WHY 28px (not 22px): articles contain multi-line text (headline + source).
   * The 28px row height (py-1.5) gives minimum breathing room for two-line
   * content without expanding to card-style padding. Matches CompactArticleRow.
   */
  articleRow: "px-3 py-1.5 text-[11px]",

  /**
   * tabBar — tab strip (32px, h-8).
   * WHY h-8 (32px): shadcn/ui Tabs uses h-8 by default; this is the one
   * component where the 32px chrome is correct — tab strips should be taller
   * than data rows to provide a distinct navigation region.
   */
  tabBar: "h-8 px-3 text-[11px]",

  /**
   * headerTopbar — top chrome bar.
   * Height is controlled via `--topbar-height` CSS variable (36px in PRD-0031,
   * currently 44px in globals.css from an earlier wave — see DESIGN_SYSTEM.md
   * §2.1 for the canonical value). Font is slightly larger than data rows (12px)
   * to give the topbar's market data and controls visual hierarchy.
   */
  headerTopbar: "px-3 text-[12px]", // height via --topbar-height CSS var

  /**
   * banner — collapsed notification / status banner.
   * WHY 24px: banners are secondary UI chrome; they should recede from the data.
   * A 24px height sits between data rows (22px) and compact buttons (28px).
   */
  banner: "h-6 px-2 text-[10px] rounded-[2px]",

  /**
   * sidebarItem — navigation item in the sidebar.
   * WHY 28px (py-1.5): slightly taller than data rows so touch targets are
   * comfortable (28px meets WCAG 2.2 minimum 24px touch target). The 2px
   * border-radius matches the global --radius token.
   */
  sidebarItem: "px-2 py-1.5 text-[11px] rounded-[2px]",

  /**
   * cardDefault — card body padding and base font size.
   * WHY p-3 (not p-4): 12px padding (p-3) vs 16px (p-4). The 4px difference
   * across every card on the dashboard saves ~40px of vertical space per row —
   * one extra metric panel fitting above the fold on a 1080p display.
   */
  cardDefault: "p-3 text-[12px] rounded-[2px]",

  /**
   * buttonDefault — standard action button (36px, matches --topbar-height intent).
   * Aligns with shadcn/ui `size="default"` (h-9 = 36px) with terminal-sharp corners.
   */
  buttonDefault: "h-9 px-3 text-[12px] rounded-[2px]",

  /**
   * buttonCompact — compact action button for dense toolbars and table actions.
   * WHY h-7 (28px): fits within a 32px tab bar or 22px row without overflowing.
   * Matches shadcn/ui `size="sm"` height but with tighter padding (px-2 vs px-3).
   */
  buttonCompact: "h-7 px-2 text-[11px] rounded-[2px]",

  /**
   * badge — status label / pill.
   * WHY text-[10px]: badges are secondary information (severity tier, entity type).
   * The 10px minimum (DESIGN_SYSTEM §3.2) applies; 9px is reserved for chart axis
   * labels only, not for interactive badge content.
   */
  badge: "px-1.5 py-0.5 text-[10px] rounded-full",
} as const;

// ── Type exports ──────────────────────────────────────────────────────────────

/** Union of all valid density surface names. */
export type DensitySurface = keyof typeof DENSITY_CLASSES;
