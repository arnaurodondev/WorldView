/**
 * Entity-type design tokens (PLAN-0057 Wave F-1 / F-MAJOR audit downstream surface).
 *
 * The backend (`canonical_entities.entity_type`) emits 13 distinct values after
 * PLAN-0057 Wave A-3 seeds 7 previously-empty NER classes.  Until F-1 the
 * frontend only mapped the 4 oldest values (`company`, `person`, `event`,
 * `topic`) to colours and showed the rest in a generic grey.  This module is
 * the single source of truth — graph nodes, badges, pills, and any future
 * entity-detail page should import from here so we get one consistent palette.
 *
 * WHY a TS object (not a tailwind class map): some consumers — most notably
 * sigma.js inside `EntityGraph.tsx` — render to a WebGL canvas and need raw
 * hex values; tailwind classes would never reach the canvas.  So the tokens
 * carry the hex (`color`) for sigma plus a human label and an icon for
 * badge surfaces (badges/chips compose their own classes from foreground
 * tokens, not from this module).
 *
 * The label stays human-readable (Title Case, no underscores) so we can drop
 * the token straight into a chip/badge without per-call formatting code.
 *
 * PLAN-0087 D-F3-011: removed unused `badgeClass` field — every entry
 * defined a tailwind shorthand string but no consumer ever read it (verified
 * via grep). Keeping dead API breaks R1 (small focused diffs) and risks the
 * shorthand drifting from the rest of the design system over time.
 */

import type { LucideIcon } from "lucide-react";
import {
  Activity,
  Banknote,
  Box,
  Building2,
  Coins,
  Factory,
  Flag,
  Hammer,
  Landmark,
  Layers,
  LineChart,
  MapPin,
  Scale,
  TrendingUp,
  User2,
  Wrench,
} from "lucide-react";

export interface EntityTypeToken {
  /** Raw hex, used by sigma/canvas renderers and any inline SVG fill. */
  color: string;
  /** Human-readable label rendered as-is in chips/badges (Title Case). */
  label: string;
  /** Lucide icon used inside avatars and 24x24 type stamps. */
  icon: LucideIcon;
}
// PLAN-0057 QA A-003: a `layout` field claiming "<EntityDetailHero> dispatcher"
// previously lived here.  No EntityDetailHero exists — the field had zero
// consumers and was dead API.  When a real entity-detail hero ships, add the
// field back together with the consumer in the same PR.

// Bloomberg yellow stays reserved for the user's own tradeable instruments —
// it's the most attention-grabbing colour in the palette and we want it to
// signal "this is a security you can act on" rather than "this is a country".
const TOKENS = {
  financial_instrument: {
    color: "#FFD60A",
    label: "Instrument",
    icon: TrendingUp,
  },
  // Pre-existing canonicals (PRD-0017 §6) — sectors and industry groups
  // share the indigo family because they're conceptual buckets, not entities
  // a user can hold in a portfolio.
  // PLAN-0057 QA M-3/M-4: sector/industry_group/industry are part of the same
  // GICS hierarchy and frequently co-occur in graph payloads. Previously all
  // three used `Factory` icon and adjacent purples (#818CF8/#A78BFA/#C084FC)
  // making them visually indistinguishable. Now: same hue family (purple) but
  // separated colour weight + distinct icons (Layers → Factory → Hammer
  // mirrors the conceptual broad → narrow drill-down).
  sector: {
    color: "#6366F1", // indigo-500 — broadest bucket, deepest tone
    label: "Sector",
    icon: Layers,
  },
  industry_group: {
    color: "#A78BFA",
    label: "Industry Group",
    icon: Factory,
  },
  industry: {
    color: "#C084FC",
    label: "Industry",
    icon: Hammer,
  },
  technology_theme: {
    color: "#22D3EE",
    label: "Theme",
    icon: Wrench,
  },
  // PLAN-0057 A-3 seeds added the 9 below — F-1 makes them renderable.
  currency: {
    color: "#34D399",
    label: "Currency",
    icon: Banknote,
  },
  regulatory_body: {
    color: "#FB7185",
    label: "Regulator",
    icon: Scale,
  },
  government_body: {
    color: "#F87171",
    label: "Government",
    icon: Landmark,
  },
  location: {
    color: "#38BDF8",
    label: "Location",
    icon: MapPin,
  },
  person: {
    color: "#26A69A",
    label: "Person",
    icon: User2,
  },
  financial_institution: {
    color: "#FBBF24",
    label: "Institution",
    icon: Building2,
  },
  commodity: {
    // PLAN-0057 QA M-3: previous yellow-700 (#A16207) on bg-zinc-950 measured
    // ~3.8:1 contrast — fails WCAG AA. Bumped to amber-500 family
    // (#F59E0B → 4.7:1) which clears AA for normal text. Icon changed from
    // HardHat (often read as construction) to Coins (universal commodity glyph).
    color: "#F59E0B",
    label: "Commodity",
    icon: Coins,
  },
  macroeconomic_indicator: {
    color: "#F472B6",
    label: "Macro Indicator",
    icon: Activity,
  },
  index: {
    color: "#94A3B8",
    label: "Index",
    icon: LineChart,
  },
  // Legacy aliases retained from the EntityGraph palette so existing graph
  // payloads (which sometimes emit "company" / "event" / "topic") keep
  // rendering with sensible colours instead of falling through to default.
  company: {
    color: "#FFD60A",
    label: "Company",
    icon: TrendingUp,
  },
  event: {
    color: "#F59E0B",
    label: "Event",
    icon: Flag,
  },
  topic: {
    color: "#818CF8",
    label: "Topic",
    icon: Wrench,
  },
} satisfies Record<string, EntityTypeToken>;

const FALLBACK: EntityTypeToken = {
  color: "#6B7585",
  label: "Entity",
  // Generic Box icon — distinct from `commodity` (Coins) so an unstyled
  // type doesn't get visually confused with a real commodity entity.
  icon: Box,
};

export type KnownEntityType = keyof typeof TOKENS;

/**
 * Look up the design token for an entity_type string.
 *
 * Returns a fallback (grey, generic icon) for unknown types so renderers
 * never throw and a future backend addition surfaces visibly without
 * crashing the UI.  Treat the existence of a fallback render as a
 * tracking signal: anything grey is a type we have not styled yet.
 */
export function entityTypeToken(entityType: string | null | undefined): EntityTypeToken {
  if (!entityType) return FALLBACK;
  return (TOKENS as Record<string, EntityTypeToken>)[entityType] ?? FALLBACK;
}

/** Names of all entity types that have an explicit (non-fallback) token. */
export const KNOWN_ENTITY_TYPES = Object.keys(TOKENS) as KnownEntityType[];

/** Stable colour map keyed by entity_type — for sigma/canvas rendering. */
export const ENTITY_TYPE_COLOR_MAP: Readonly<Record<string, string>> = Object.fromEntries(
  Object.entries(TOKENS).map(([k, v]) => [k, v.color]),
);
