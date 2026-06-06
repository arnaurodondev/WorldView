/**
 * components/primitives/DenseArticleRow.tsx — 18px terminal-grade news row
 *
 * WHY THIS EXISTS: PRD-0089 F1 §3.2 — Intelligence, Quote, Dashboard, and
 * News page all render the same shape of "news row": narrow time + source
 * + headline + optional score. Centralising prevents the four pages from
 * diverging on row height, color of the sentiment stripe, or where the
 * routing-tier chip lives. Bloomberg TOP / Refinitiv News use ~18px rows.
 * WHO USES IT: Dashboard news widget, Quote tab brief footer, Intelligence
 *   article stream, dedicated News page.
 * DATA SOURCE: Caller passes a RankedArticle. Routing-tier and cluster
 *   come from /v1/articles/ranked composite_score + cluster_id.
 * DESIGN REFERENCE: PRD-0089 F1 §3.2 (DenseArticleRow row).
 */

import type { ReactNode } from "react";

// Subset of the canonical RankedArticle shape — keeps the primitive
// independent of the full type so per-page agents can pass either the
// canonical type or a structurally compatible subset.
interface RankedArticle {
  readonly id: string;
  readonly title: string;
  readonly source: string;
  readonly publishedAt: string;
  readonly url?: string;
  /** -1.0 → +1.0 sentiment score from /v1/articles/ranked.sentiment. */
  readonly sentiment?: number | null;
  readonly ticker?: string | null;
  readonly routingTier?: "T0" | "T1" | "T2" | "T3";
  readonly cluster?: string | null;
}

interface DenseArticleRowProps {
  readonly article: RankedArticle;
  /** "terminal" = 18px hyper-dense; "compact" = 22px (default Worldview). */
  readonly density?: "terminal" | "compact";
  readonly withTicker?: boolean;
  readonly withRoutingTier?: boolean;
  readonly withCluster?: boolean;
}

// Format an ISO date to "HH:mm" for the leftmost time column.
function formatTime(iso: string): string {
  try {
    return new Date(iso).toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", hour12: false });
  } catch {
    return "—";
  }
}

// Map sentiment → left-edge stripe color. Null/undefined → muted (no signal).
function sentimentStripeClass(sentiment?: number | null): string {
  if (sentiment === undefined || sentiment === null) return "bg-muted-foreground/30";
  if (sentiment >= 0.15) return "bg-positive";
  if (sentiment <= -0.15) return "bg-negative";
  return "bg-muted-foreground/30";
}

export function DenseArticleRow({
  article,
  density = "terminal",
  withTicker = false,
  withRoutingTier = false,
  withCluster = false,
}: DenseArticleRowProps): ReactNode {
  const heightClass = density === "terminal" ? "h-[18px]" : "h-[22px]";
  // WHY 2px stripe (not 4px): plan FU-5.4 — the strip is informational, not
  // decorative. 2px is enough to register sentiment at a glance without
  // stealing horizontal pixels from the headline.
  return (
    <div
      role="row"
      className={`group flex ${heightClass} items-center gap-1.5 border-b border-border-subtle px-1.5 text-[11px] transition-color-only duration-100 hover:bg-muted/50`}
    >
      <span className={`h-full w-[2px] ${sentimentStripeClass(article.sentiment)}`} aria-hidden="true" />
      <span className="w-[42px] shrink-0 font-mono tabular-nums text-muted-foreground">{formatTime(article.publishedAt)}</span>
      {withTicker ? (
        <span className="w-[48px] shrink-0 font-mono text-foreground">{article.ticker ?? "—"}</span>
      ) : null}
      <span className="w-[80px] shrink-0 truncate text-muted-foreground">{article.source}</span>
      {article.url ? (
        <a
          href={article.url}
          target="_blank"
          rel="noopener noreferrer"
          className="flex-1 truncate text-foreground transition-color-only duration-100 group-hover:text-primary"
        >
          {article.title}
        </a>
      ) : (
        <span className="flex-1 truncate text-foreground">{article.title}</span>
      )}
      {withRoutingTier && article.routingTier ? (
        <span className="w-[24px] shrink-0 font-mono text-[10px] uppercase text-muted-foreground">{article.routingTier}</span>
      ) : null}
      {withCluster && article.cluster ? (
        <span className="w-[64px] shrink-0 truncate text-[10px] text-muted-foreground">{article.cluster}</span>
      ) : null}
    </div>
  );
}
