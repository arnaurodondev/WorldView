/**
 * news/DenseArticleRow.tsx — 18px terminal-density news row for Intelligence tab
 *
 * WHY THIS EXISTS: PRD-0089 W7 — the Intelligence tab news column must show
 * ≥30 articles above the fold. At CompactArticleRow's 28px height only ~20
 * rows fit. Dropping to 18px gains 60% more rows in the same viewport, matching
 * Bloomberg TMON / Refinitiv Eikon news pane density.
 * WHO USES IT: NewsColumn (Intelligence tab news rail).
 * DATA SOURCE: RankedArticle from GET /v1/entities/{id}/news (via S9).
 * DESIGN REFERENCE: W7 design doc §3 (DenseArticleRow), PRD-0089 §6.9.
 *
 * LAYOUT (total row = 18px h):
 *   [2px stripe] [38px time] [28px src] [flex-1 headline] [20px impact]
 *
 * WHY 2px left stripe (not a dot):
 * A vertical stripe is scannable at a glance for long lists — the eye can
 * sweep down the left edge and detect a color change without focusing on
 * each row. Bloomberg uses a similar left-edge color convention.
 *
 * WHY 3-letter source (not full name):
 * Source names like "EODHD Financial News" waste 100px on a narrow rail.
 * A 3-letter code (BBG/RFN/EOD) gives the same signal in 28px, leaving more
 * room for the headline which is the primary information unit.
 */

"use client";
// WHY "use client": onClick handler requires browser event binding.

import { useMemo } from "react";
import { cn } from "@/lib/utils";
import type { RankedArticle } from "@/types/api";

export interface DenseArticleRowProps {
  readonly article: RankedArticle;
  /** Whether the row is keyboard-highlighted (j/k navigation). */
  readonly highlighted?: boolean;
}

// ── Helpers ──────────────────────────────────────────────────────────────────

/** Sentinel map: source_type → 3-char display code for the rail.
 * WHY a map (not slicing source_name): source_name is human-readable and
 * variable-length; a deterministic code ensures consistent column width. */
const SOURCE_CODE: Record<string, string> = {
  eodhd_news: "EOD",
  reuters: "RTR",
  bloomberg: "BBG",
  seekingalpha: "SA",
  wsj: "WSJ",
  ft: "FT",
  cnbc: "CNB",
  marketwatch: "MKW",
};

function getSourceCode(article: RankedArticle): string {
  // WHY try source_type first: it's the canonical technical identifier.
  // Fall back to first 3 chars of source_name for unknown types.
  if (article.source_type && article.source_type in SOURCE_CODE) {
    return SOURCE_CODE[article.source_type]!;
  }
  const name = article.source_name ?? article.source_type ?? "—";
  // WHY toUpperCase: rail convention is ALL-CAPS codes (EOD, RTR, BBG).
  return name.slice(0, 3).toUpperCase();
}

/** Sentiment → 2px left stripe color class.
 * WHY bg-muted-foreground/40 for neutral/null: a colourless stripe is less
 * distracting than an explicit grey; the user's eye rests on the coloured ones. */
function stripeClass(sentiment: RankedArticle["sentiment"]): string {
  if (sentiment === "positive") return "bg-positive";
  if (sentiment === "negative") return "bg-negative";
  return "bg-muted-foreground/40";
}

/** impact_score → color class for the score column.
 * Thresholds: ≥0.70 = positive (strong), ≥0.40 = warning (moderate),
 * else muted (weak/unknown). */
function impactColorClass(score: number | null): string {
  if (score == null) return "text-muted-foreground";
  if (score >= 0.7) return "text-positive";
  if (score >= 0.4) return "text-warning";
  return "text-muted-foreground";
}

// ── Component ─────────────────────────────────────────────────────────────────

export function DenseArticleRow({ article, highlighted = false }: DenseArticleRowProps) {
  // WHY useMemo for click: avoids allocating a new closure on every render
  // (this row is rendered 30+ times in the news rail).
  // WHY protocol check: reject javascript:/data: URLs from API to prevent injection.
  const handleClick = useMemo(() => {
    if (!article.url) return undefined;
    try {
      const parsed = new URL(article.url);
      if (!["http:", "https:"].includes(parsed.protocol)) return undefined;
    } catch {
      return undefined;
    }
    const url = article.url;
    return () => window.open(url, "_blank", "noopener,noreferrer");
  }, [article.url]);

  // Local-timezone HH:MM — traders scan in their session timezone.
  const timeLabel = article.published_at
    ? (() => {
        const d = new Date(article.published_at);
        return isNaN(d.getTime())
          ? "—"
          : d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", hour12: false });
      })()
    : "—";

  // impact_score 0.0–1.0 → 0–100 integer display (compact, no decimal noise).
  const impactLabel =
    article.impact_score != null
      ? String(Math.round(article.impact_score * 100))
      : "—";

  const srcCode = getSourceCode(article);

  return (
    <div
      onClick={handleClick}
      role={article.url ? "link" : undefined}
      tabIndex={article.url ? 0 : undefined}
      aria-label={article.title ?? undefined}
      className={cn(
        // WHY h-[18px]: target density matching plan spec (18px vs 28px compact).
        "h-[18px] flex items-center gap-1.5 border-b border-border-subtle",
        article.url && "cursor-pointer hover:bg-muted/20",
        // WHY ring + bg on highlight: ring-border is 1px visible outline;
        // bg-muted/20 gives a subtle fill for keyboard navigation feedback.
        highlighted && "ring-1 ring-border bg-muted/20",
      )}
    >
      {/* 2px sentiment stripe — full height so the color band reads as a column */}
      <span
        aria-hidden="true"
        className={cn("w-[2px] h-full self-stretch shrink-0", stripeClass(article.sentiment))}
      />

      {/* HH:MM time — fixed width keeps all columns aligned across 30+ rows */}
      <span className="w-[38px] shrink-0 text-[10px] font-mono tabular-nums text-muted-foreground">
        {timeLabel}
      </span>

      {/* 3-letter source code — truncates long source names to a predictable width */}
      <span className="w-[28px] shrink-0 text-[10px] font-mono text-muted-foreground">
        {srcCode}
      </span>

      {/* Headline — gets all remaining space; truncated to single line */}
      <span className="flex-1 text-[11px] truncate text-foreground/90">
        {article.title ?? "(untitled)"}
      </span>

      {/* Impact score 0-100 — tabular-nums for stable column width */}
      <span
        className={cn(
          "w-[20px] shrink-0 text-[10px] font-mono tabular-nums text-right",
          impactColorClass(article.impact_score),
        )}
      >
        {impactLabel}
      </span>
    </div>
  );
}
