/**
 * graphFilterUtils.ts — pure helpers for sigma edge/node filtering.
 *
 * WHY STANDALONE: matchesRelFilter has no sigma/WebGL dependency, so it can
 * be unit-tested in jsdom without triggering sigma's WebGL2RenderingContext
 * require. Keeping it separate also lets FilterController import it without
 * pulling in the full sigma bundle during tests.
 */

import type { RelationFilter } from "./GraphControls";

// WHY pattern-based (not exact-match): relation labels vary by data source.
// "CEO_OF", "EXECUTIVE_CHAIR", "CHIEF_EXEC" all map to "executive".
//
// PLAN-0099 W4 FIX (filters-don't-fully-work): the patterns below were tuned to
// a hand-picked set of label variants and silently MISSED the canonical KG
// relation labels actually emitted by S7 for the AAPL-scale graph. Confirmed
// live (2026-06-12) the real edge labels are: supplier_of, competes_with,
// listed_on, operates_in_country, partner_of, has_executive, owns_stake_in,
// employs, headquartered_in, regulates, investment_in, produces, is_in_sector,
// analyst_rating. The most damaging miss was the INVESTOR pill: it checked for
// "OWNED" but the data uses "OWNS_STAKE_IN" / "INVESTMENT_IN" — so selecting
// "investor" hid the very ownership edges the analyst wanted. Each branch below
// now lists the concrete canonical labels first, then keeps the broader
// substring fallbacks for forward-compat with other data sources.
export function matchesRelFilter(label: string, filter: RelationFilter): boolean {
  const upper = label.toUpperCase();
  switch (filter) {
    case "all": return true;
    case "executive":
      // Canonical: HAS_EXECUTIVE, EMPLOYS. Fallbacks: title fragments.
      return upper.includes("HAS_EXECUTIVE") || upper.includes("EMPLOYS") ||
        upper.includes("CEO") || upper.includes("CFO") || upper.includes("CTO") ||
        upper.includes("COO") || upper.includes("CHAIR") || upper.includes("EXEC") ||
        upper.includes("OFFICER") || upper.includes("DIRECTOR");
    case "investor":
      // Canonical: OWNS_STAKE_IN, INVESTMENT_IN. The original "OWNED" check did
      // NOT match "OWNS_STAKE_IN" (no "OWNED" substring) — the headline bug.
      return upper.includes("INVEST") || upper.includes("OWNS_STAKE") ||
        upper.includes("OWNS") || upper.includes("STAKE") ||
        upper.includes("SHAREHOLDER") || upper.includes("HOLDS") ||
        upper.includes("OWNED");
    case "supplier":
      // Canonical: SUPPLIER_OF / SUPPLIER, PRODUCES, PARTNER_OF (supply-chain).
      return upper.includes("SUPPL") || upper.includes("MANUFACTUR") ||
        upper.includes("PRODUCES") || upper.includes("PARTNER");
    case "customer":
      return upper.includes("CUSTOMER") || upper.includes("CLIENT") || upper.includes("USES");
    case "competitor":
      // Canonical: COMPETES_WITH.
      return upper.includes("COMPET") || upper.includes("RIVAL");
    default:
      return true;
  }
}

/**
 * isEdgeVisible — SINGLE source of truth for "does this edge survive the current
 * relation-pill + strength filters?".
 *
 * WHY EXTRACTED (KG filter bug, 2026-06-23): the visibility predicate used to be
 * inlined in THREE places inside FilterController:
 *   (1) the visible-edge-count effect (the "X of Y edges" badge), and
 *   (2) the sigma edgeReducer (what the canvas actually hides), and now
 *   (3) the new orphan-node computation that hides nodes left with zero visible
 *       edges.
 * If those copies drift (e.g. a weight-unit fix lands in one but not another),
 * the badge count, the painted edges, and the hidden nodes silently disagree —
 * exactly the class of bug that let the original "filter does nothing to nodes"
 * issue ship. Centralising the predicate here guarantees all three agree.
 *
 * @param label   raw edge relation label (any case; we upper-case internally)
 * @param weight  edge weight in graph units (0–1)
 * @param filter  the active relation pill ("all" | "executive" | …)
 * @param minWeight strength-slider value in PERCENT (0–100). The graph stores
 *   weight in 0–1, so we compare against minWeight/100 — mirroring the original
 *   edgeReducer's `weight < minWeight / 100` check exactly.
 */
export function isEdgeVisible(
  label: string,
  weight: number,
  filter: RelationFilter,
  minWeight: number,
): boolean {
  // WHY minWeight / 100: slider stores 0–100, graph stores 0–1 weight.
  if (weight < minWeight / 100) return false;
  // The "all" pill matches every relation type; only the strength floor applies.
  if (filter !== "all" && !matchesRelFilter(label, filter)) return false;
  return true;
}
