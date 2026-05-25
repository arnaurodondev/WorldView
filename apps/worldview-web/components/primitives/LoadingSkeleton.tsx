/**
 * components/primitives/LoadingSkeleton.tsx — variant-driven loading visuals
 *
 * WHY THIS EXISTS: PRD-0089 F1 §3.2 — every loading state needs to be
 * shaped like the eventual real content: a skeleton row for tables, an
 * em-dash for missing cells, a gray block for charts, a dotted line for
 * sparklines. Centralising the four variants keeps the loading "shape"
 * consistent so analysts immediately know what's coming.
 * WHO USES IT: every TanStack Query consumer in the app — wraps the
 *   `isLoading` branch.
 * DATA SOURCE: Pure presentational.
 * DESIGN REFERENCE: PRD-0089 F1 §3.2 (LoadingSkeleton row).
 */

import type { ReactNode } from "react";

type SkeletonVariant = "table-row" | "cell" | "chart-block" | "sparkline-dotted";

interface LoadingSkeletonProps {
  readonly variant: SkeletonVariant;
  /** Number of repetitions (e.g. 10 placeholder table rows). Defaults to 1. */
  readonly count?: number;
}

function renderOne(variant: SkeletonVariant, key: number): ReactNode {
  switch (variant) {
    case "table-row":
      // 20px row with a pulsing muted bar inside — mimics a real row's height.
      return (
        <div key={key} role="row" className="flex h-[20px] items-center border-b border-border-subtle px-1.5">
          <div className="h-[10px] w-full bg-muted/50 animate-skeleton-pulse" />
        </div>
      );
    case "cell":
      // The classic finance em-dash placeholder, faded.
      return (
        <span key={key} className="font-mono text-[11px] text-muted-foreground/50">—</span>
      );
    case "chart-block":
      // A muted block matching typical chart aspect ratio.
      return (
        <div key={key} className="h-[120px] w-full bg-muted/30 animate-skeleton-pulse" />
      );
    case "sparkline-dotted":
      // A dotted line matching the Sparkline empty-state, so loading and
      // empty are visually distinct (loading pulses, empty doesn't).
      return (
        <svg key={key} width={40} height={16} role="img" aria-label="loading sparkline">
          <line
            x1={0}
            x2={40}
            y1={8}
            y2={8}
            stroke="currentColor"
            strokeDasharray="2 2"
            className="text-muted-foreground/30 animate-skeleton-pulse"
          />
        </svg>
      );
  }
}

export function LoadingSkeleton({ variant, count = 1 }: LoadingSkeletonProps): ReactNode {
  if (count === 1) return renderOne(variant, 0);
  const items: ReactNode[] = [];
  for (let i = 0; i < count; i++) {
    items.push(renderOne(variant, i));
  }
  return <>{items}</>;
}
