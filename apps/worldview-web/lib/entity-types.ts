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
 * carry both a hex (`color`) and a tailwind class string (`badgeClass`) — UI
 * surfaces pick whichever fits their renderer.
 *
 * The label stays human-readable (Title Case, no underscores) so we can drop
 * the token straight into a chip/badge without per-call formatting code.
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
  /** Tailwind class fragment matching the colour — `text-x bg-y/10 border-z/30`. */
  badgeClass: string;
  /** Lucide icon used inside avatars and 24×24 type stamps. */
  icon: LucideIcon;
  /**
   * Layout variant — entity-detail pages use this to decide the hero row
   * (price chart for instruments, geo map for locations, biography for
   * persons, …).  See `<EntityDetailHero>` in apps/worldview-web for the
   * dispatch table.  Kept as a string so unknown types fall through to
   * "default" without a TypeScript error.
   */
  layout:
    | "instrument"
    | "person"
    | "geographic"
    | "regulator"
    | "macro"
    | "topic"
    | "default";
}

// Bloomberg yellow stays reserved for the user's own tradeable instruments —
// it's the most attention-grabbing colour in the palette and we want it to
// signal "this is a security you can act on" rather than "this is a country".
const TOKENS = {
  financial_instrument: {
    color: "#FFD60A",
    label: "Instrument",
    badgeClass: "text-[#FFD60A] bg-[#FFD60A]/10 border-[#FFD60A]/30",
    icon: TrendingUp,
    layout: "instrument" as const,
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
    badgeClass: "text-indigo-400 bg-indigo-400/10 border-indigo-400/30",
    icon: Layers,
    layout: "topic" as const,
  },
  industry_group: {
    color: "#A78BFA",
    label: "Industry Group",
    badgeClass: "text-violet-400 bg-violet-400/10 border-violet-400/30",
    icon: Factory,
    layout: "topic" as const,
  },
  industry: {
    color: "#C084FC",
    label: "Industry",
    badgeClass: "text-purple-400 bg-purple-400/10 border-purple-400/30",
    icon: Hammer,
    layout: "topic" as const,
  },
  technology_theme: {
    color: "#22D3EE",
    label: "Theme",
    badgeClass: "text-cyan-400 bg-cyan-400/10 border-cyan-400/30",
    icon: Wrench,
    layout: "topic" as const,
  },
  // PLAN-0057 A-3 seeds added the 9 below — F-1 makes them renderable.
  currency: {
    color: "#34D399",
    label: "Currency",
    badgeClass: "text-emerald-400 bg-emerald-400/10 border-emerald-400/30",
    icon: Banknote,
    layout: "default" as const,
  },
  regulatory_body: {
    color: "#FB7185",
    label: "Regulator",
    badgeClass: "text-rose-400 bg-rose-400/10 border-rose-400/30",
    icon: Scale,
    layout: "regulator" as const,
  },
  government_body: {
    color: "#F87171",
    label: "Government",
    badgeClass: "text-red-400 bg-red-400/10 border-red-400/30",
    icon: Landmark,
    layout: "regulator" as const,
  },
  location: {
    color: "#38BDF8",
    label: "Location",
    badgeClass: "text-sky-400 bg-sky-400/10 border-sky-400/30",
    icon: MapPin,
    layout: "geographic" as const,
  },
  person: {
    color: "#26A69A",
    label: "Person",
    badgeClass: "text-teal-400 bg-teal-400/10 border-teal-400/30",
    icon: User2,
    layout: "person" as const,
  },
  financial_institution: {
    color: "#FBBF24",
    label: "Institution",
    badgeClass: "text-amber-400 bg-amber-400/10 border-amber-400/30",
    icon: Building2,
    layout: "default" as const,
  },
  commodity: {
    // PLAN-0057 QA M-3: previous yellow-700 (#A16207) on bg-zinc-950 measured
    // ~3.8:1 contrast — fails WCAG AA. Bumped to amber-500 family
    // (#F59E0B → 4.7:1) which clears AA for normal text. Icon changed from
    // HardHat (often read as construction) to Coins (universal commodity glyph).
    color: "#F59E0B",
    label: "Commodity",
    badgeClass: "text-amber-500 bg-amber-500/10 border-amber-500/30",
    icon: Coins,
    layout: "default" as const,
  },
  macroeconomic_indicator: {
    color: "#F472B6",
    label: "Macro Indicator",
    badgeClass: "text-pink-400 bg-pink-400/10 border-pink-400/30",
    icon: Activity,
    layout: "macro" as const,
  },
  index: {
    color: "#94A3B8",
    label: "Index",
    badgeClass: "text-slate-400 bg-slate-400/10 border-slate-400/30",
    icon: LineChart,
    layout: "instrument" as const,
  },
  // Legacy aliases retained from the EntityGraph palette so existing graph
  // payloads (which sometimes emit "company" / "event" / "topic") keep
  // rendering with sensible colours instead of falling through to default.
  company: {
    color: "#FFD60A",
    label: "Company",
    badgeClass: "text-[#FFD60A] bg-[#FFD60A]/10 border-[#FFD60A]/30",
    icon: TrendingUp,
    layout: "instrument" as const,
  },
  event: {
    color: "#F59E0B",
    label: "Event",
    badgeClass: "text-amber-500 bg-amber-500/10 border-amber-500/30",
    icon: Flag,
    layout: "macro" as const,
  },
  topic: {
    color: "#818CF8",
    label: "Topic",
    badgeClass: "text-indigo-400 bg-indigo-400/10 border-indigo-400/30",
    icon: Wrench,
    layout: "topic" as const,
  },
} satisfies Record<string, EntityTypeToken>;

const FALLBACK: EntityTypeToken = {
  color: "#6B7585",
  label: "Entity",
  badgeClass: "text-muted-foreground bg-muted/30 border-border/40",
  // Generic Box icon — distinct from `commodity` (Coins) so an unstyled
  // type doesn't get visually confused with a real commodity entity.
  icon: Box,
  layout: "default",
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
