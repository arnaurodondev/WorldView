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
export function matchesRelFilter(label: string, filter: RelationFilter): boolean {
  const upper = label.toUpperCase();
  switch (filter) {
    case "all": return true;
    case "executive":
      return upper.includes("CEO") || upper.includes("CFO") || upper.includes("CTO") ||
        upper.includes("COO") || upper.includes("CHAIR") || upper.includes("EXEC") ||
        upper.includes("OFFICER") || upper.includes("DIRECTOR");
    case "investor":
      return upper.includes("INVEST") || upper.includes("SHAREHOLDER") ||
        upper.includes("HOLDS") || upper.includes("OWNED");
    case "supplier":
      return upper.includes("SUPPL") || upper.includes("MANUFACTUR") || upper.includes("PRODUCES");
    case "customer":
      return upper.includes("CUSTOMER") || upper.includes("CLIENT") || upper.includes("USES");
    case "competitor":
      return upper.includes("COMPET") || upper.includes("RIVAL");
    default:
      return true;
  }
}
