/**
 * graph/GraphStats.tsx — 18px graph statistics strip (W7 T-07)
 *
 * WHY THIS EXISTS: PRD-0089 W7 — analysts need a quick glance at graph
 * characteristics (size, depth, fetch speed) to decide whether to drill deeper
 * or switch to a different view. Bloomberg KNOWLEDGEBOND shows a node count
 * in its header; we mirror that convention with a compact mono strip.
 *
 * WHO USES IT: GraphColumn (Intelligence tab center column).
 * DATA SOURCE: Derived from the EntityGraph response (node/edge count) and
 *   client-side performance.now() measurement (latencyMs).
 * DESIGN REFERENCE: W7 design doc §4 (GraphStats strip, 18px).
 */

import type { ReactNode } from "react";

export interface GraphStatsProps {
  readonly nodeCount: number;
  readonly edgeCount: number;
  readonly depth: number;
  /** Null while the first fetch is in-flight; populated after the first graph loads. */
  readonly latencyMs: number | null;
}

// ── Component ─────────────────────────────────────────────────────────────────

/**
 * GraphStats — single-line stats strip displayed between the brief and toolbar.
 *
 * WHY fixed h-[18px]: matches DenseArticleRow height so the eye calibrates
 * to 18px as the platform's "data-row" height across contexts.
 * WHY tabular-nums: the number values change every time the user switches
 * depth — tabular-nums prevents the strip from shifting horizontally.
 */
export function GraphStats({
  nodeCount,
  edgeCount,
  depth,
  latencyMs,
}: GraphStatsProps): ReactNode {
  const latencyLabel = latencyMs !== null ? `${latencyMs} ms` : "—";

  return (
    <div
      className="h-[18px] flex items-center text-[10px] font-mono tabular-nums text-muted-foreground px-1"
      aria-label={`Graph: ${nodeCount} nodes, ${edgeCount} edges, depth ${depth}, ${latencyLabel}`}
    >
      {/* WHY · separator: minimal punctuation that reads as a list without
          adding box/column chrome. Same convention as the brief footer strip. */}
      {nodeCount} nodes · {edgeCount} edges · depth {depth} · {latencyLabel}
    </div>
  );
}
