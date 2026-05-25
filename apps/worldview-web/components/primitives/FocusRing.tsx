/**
 * components/primitives/FocusRing.tsx — 3-tier focus-ring class catalogue
 *
 * WHY THIS EXISTS: PRD-0089 F1 §3.2 — the focus ring is 3-tier (table-row
 * hairline / input ring-1 / chrome CTA ring-2). Centralising the class
 * strings prevents per-page drift. Bloomberg uses the same tiered focus
 * pattern: subtle on data rows, prominent on chrome buttons.
 * WHO USES IT: any component that needs to add a focus visual to a
 *   focusable element — rows, inputs, CTAs.
 * DATA SOURCE: Pure constants — not a React component.
 * DESIGN REFERENCE: PRD-0089 F1 §3.2 (FocusRing row) + §2.6 (animation
 *   tier policy — focus rings use Tier-1 color transitions).
 *
 * Usage:
 *   <div className={`flex ${FocusRing.T1_TABLE_ROW}`} />
 *   <input className={FocusRing.T2_INPUT} />
 *   <button className={FocusRing.T3_CHROME_CTA} />
 */

export const FocusRing = {
  /** Tier-1: inset hairline outline — for table rows.  No visual chrome. */
  T1_TABLE_ROW:
    "focus:outline-1 focus:outline-primary focus:outline-offset-[-1px] focus-visible:outline-1 focus-visible:outline-primary focus-visible:outline-offset-[-1px]",
  /** Tier-2: 1px ring around inputs / select triggers / search box. */
  T2_INPUT: "focus:ring-1 focus:ring-primary focus-visible:ring-1 focus-visible:ring-primary",
  /** Tier-3: 2px ring with offset — for chrome CTAs (top-bar buttons, etc.). */
  T3_CHROME_CTA:
    "focus:ring-2 focus:ring-primary focus:ring-offset-2 focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2",
} as const;

export type FocusRingTier = keyof typeof FocusRing;
