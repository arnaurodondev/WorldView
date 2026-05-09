/**
 * components/intelligence/SourceDistributionList.tsx — Evidence source breakdown bars
 * (PLAN-0074 Wave H T-H-05)
 *
 * WHY CSS WIDTH BARS (not a chart library):
 * Source distribution is a simple proportional list — each row shows a source
 * name and its percentage of total evidence. CSS `width: X%` on a coloured div
 * achieves this with zero JavaScript, zero library dependency, and perfect
 * accessibility (the text content is already readable by screen readers).
 * recharts is not allowed (removed from package.json).
 *
 * WHY THIS MATTERS TO ANALYSTS:
 * A relation with 90% of its evidence from a single Reuters article is weaker
 * than one backed by 40 independent sources across SEC filings, news, and
 * earnings call transcripts. The source distribution visualises this evidence
 * diversity in the sidebar.
 *
 * WHO USES IT: EntitySidebar confidence section
 * DATA SOURCE: confidence_breakdown.source_distribution from useEntityIntelligence
 */

// WHY no "use client": pure props display, no hooks.

import type { SourceSharePublic } from "@/types/intelligence";

// ── Props ─────────────────────────────────────────────────────────────────────

interface SourceDistributionListProps {
  distribution: SourceSharePublic[];
  className?: string;
}

// ── Source type colors ────────────────────────────────────────────────────────

function sourceBarClass(sourceType: string | null): string {
  // WHY semantic colour mapping: same as EvidenceTab source badges for visual consistency.
  // Analysts develop a mental model of "blue=filing, amber=news, purple=social"
  // across the entire intelligence page.
  // WHY accent-ai for filing, primary for news, muted for social:
  // Uses design token semantic colors instead of raw Tailwind colors
  // (required by PLAN-0071 P1-4 lint rule). accent-ai (the AI/data color)
  // maps well to "structured data" (filings). primary (amber) is news.
  switch (sourceType?.toLowerCase()) {
    case "filing": return "bg-accent-ai/70";
    case "news":   return "bg-primary/70";
    case "social": return "bg-muted-foreground/50";
    default:       return "bg-muted-foreground/30";
  }
}

// ── Component ─────────────────────────────────────────────────────────────────

export function SourceDistributionList({
  distribution,
  className = "",
}: SourceDistributionListProps) {
  if (!distribution || distribution.length === 0) {
    return (
      <p className="text-[11px] text-muted-foreground font-mono">No source data</p>
    );
  }

  return (
    <div className={`space-y-1.5 ${className}`} aria-label="Evidence source distribution">
      {distribution.map((source, i) => {
        const label = source.source_name ?? source.source_type ?? "Unknown";
        const pct = Math.min(100, Math.max(0, source.pct));

        return (
          <div key={`${source.source_type}-${i}`} className="space-y-0.5">
            {/* Source label + count row */}
            <div className="flex items-center justify-between">
              <span className="text-[11px] font-mono text-foreground/80 truncate">
                {label}
              </span>
              <span className="text-[10px] font-mono tabular-nums text-muted-foreground shrink-0 ml-2">
                {source.count} · {pct.toFixed(1)}%
              </span>
            </div>

            {/* CSS width bar — no JavaScript, no chart library */}
            {/* WHY bg-muted track: gives visual context for the empty portion
                without being distracting. The filled portion uses semantic colors. */}
            <div
              className="w-full h-1 bg-muted/50 rounded-full overflow-hidden"
              role="progressbar"
              aria-valuenow={Math.round(pct)}
              aria-valuemin={0}
              aria-valuemax={100}
              aria-label={`${label}: ${pct.toFixed(1)}%`}
            >
              <div
                className={`h-full rounded-full ${sourceBarClass(source.source_type)}`}
                style={{ width: `${pct}%` }}
              />
            </div>
          </div>
        );
      })}
    </div>
  );
}
