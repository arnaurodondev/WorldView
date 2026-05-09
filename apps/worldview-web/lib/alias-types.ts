/**
 * Alias-type design tokens (PLAN-0057 Wave F-2 / F-MAJOR-09 downstream surface).
 *
 * After PLAN-0057 Wave C-3 the backend `entity_aliases` table now carries five
 * additional alias_types beyond `EXACT` / `TICKER` / `EXCHANGE_TICKER` /
 * `ISIN`:
 *
 *   - `CUSIP`           — US/Canada 9-character security identifier
 *   - `FIGI`            — Bloomberg Open Symbology (12 char)
 *   - `LEI`             — Legal Entity Identifier (20 char)
 *   - `PRIMARY_TICKER`  — exchange-disambiguated ticker (e.g. `AAPL.US`)
 *   - `NAME`            — alternate display name (e.g. `Apple` for `Apple Inc.`)
 *
 * UX requirement (per audit + Checkpoint A decision #3): each new alias_type
 * gets its own *subtly* differentiated pill so analysts can tell at a glance
 * which identifier system a row belongs to without obscuring the value.  The
 * differentiation is deliberately low-contrast — these are reference tokens,
 * not call-to-action chips.
 */

export interface AliasTypeToken {
  /** Short human label rendered as the pill's leading text (e.g. "ISIN"). */
  label: string;
  /**
   * Tailwind classes for the pill chrome — kept low-contrast so a long alias
   * list doesn't drown out the surrounding entity-detail copy.  The
   * convention: `text-x bg-x/10 border-x/30` matching the entity-type palette.
   */
  className: string;
  /**
   * Sort priority — lower = renders earlier when an entity-detail page lists
   * all aliases.  We want primary identifiers (EXACT, TICKER, PRIMARY_TICKER)
   * before reference identifiers (ISIN, CUSIP, FIGI, LEI), with NAME and
   * EXCHANGE_TICKER slotting in between for visual grouping.
   */
  sortIndex: number;
}

// PLAN-0087 D-F3-002: alias pill classes were using off-palette Tailwind
// shorthand (amber-300/400, zinc-300, sky-400, cyan-400, emerald-400,
// violet-400). The Terminal Dark token vocabulary is narrower, so we collapse
// the alias families into three semantic tiers:
//   • Primary identifiers (TICKER / PRIMARY_TICKER / EXCHANGE_TICKER) → primary token
//     (Bloomberg yellow); they're the most analyst-visible identifier and earn
//     the strongest CTA-adjacent tint.
//   • Display names (NAME / EXACT) → foreground (neutral, uncoloured pill).
//   • Reference identifiers (ISIN / CUSIP / FIGI / LEI) → muted-foreground;
//     they're scannable but should sit visually behind the primary identifiers.
// Subtle differentiation within tiers comes from the alpha on `border-` /
// `bg-` rather than competing hues — the Terminal Dark direction is
// deliberately monochromatic for reference data.
const TOKENS = {
  EXACT: {
    label: "Exact",
    className: "text-foreground bg-foreground/5 border-border/40",
    sortIndex: 0,
  },
  TICKER: {
    label: "Ticker",
    className: "text-primary bg-primary/10 border-primary/30",
    sortIndex: 10,
  },
  PRIMARY_TICKER: {
    label: "Primary",
    className: "text-primary bg-primary/15 border-primary/40",
    sortIndex: 11,
  },
  EXCHANGE_TICKER: {
    label: "Exchange",
    className: "text-primary bg-primary/5 border-primary/25",
    sortIndex: 12,
  },
  NAME: {
    label: "Name",
    className: "text-foreground bg-foreground/5 border-border/30",
    sortIndex: 20,
  },
  ISIN: {
    label: "ISIN",
    className: "text-muted-foreground bg-muted/30 border-border/40",
    sortIndex: 30,
  },
  CUSIP: {
    label: "CUSIP",
    className: "text-muted-foreground bg-muted/30 border-border/40",
    sortIndex: 31,
  },
  FIGI: {
    label: "FIGI",
    className: "text-muted-foreground bg-muted/30 border-border/40",
    sortIndex: 32,
  },
  LEI: {
    label: "LEI",
    className: "text-muted-foreground bg-muted/30 border-border/40",
    sortIndex: 33,
  },
} satisfies Record<string, AliasTypeToken>;

const FALLBACK: AliasTypeToken = {
  label: "Alias",
  className: "text-muted-foreground bg-muted/20 border-border/30",
  sortIndex: 100,
};

export type KnownAliasType = keyof typeof TOKENS;

/** Look up the pill token for an alias_type. Unknown types fall back gracefully. */
export function aliasTypeToken(aliasType: string | null | undefined): AliasTypeToken {
  if (!aliasType) return FALLBACK;
  return (TOKENS as Record<string, AliasTypeToken>)[aliasType] ?? FALLBACK;
}

export const KNOWN_ALIAS_TYPES = Object.keys(TOKENS) as KnownAliasType[];

/**
 * Sort an array of alias rows by `alias_type` (primary identifiers first,
 * then names, then reference identifiers).  Stable order within the same
 * type is preserved by the caller (we use `sortIndex` only).
 */
export function sortAliasesByType<T extends { alias_type: string | null | undefined }>(
  aliases: T[],
): T[] {
  return [...aliases].sort(
    (a, b) => aliasTypeToken(a.alias_type).sortIndex - aliasTypeToken(b.alias_type).sortIndex,
  );
}
