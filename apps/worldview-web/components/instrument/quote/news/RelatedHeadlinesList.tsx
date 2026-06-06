/**
 * components/instrument/quote/news/RelatedHeadlinesList.tsx
 * — Top-5 entity-tagged news mini-list (W5-T-18)
 *
 * DATA SOURCE: `data: RankedNewsResponse | null` from bundle.top_news or
 *   useQuoteSidebarData (entityNews). Zero extra fetch when seeded from bundle.
 *
 * DESIGN:
 *   - `<div data-table-grid="dense">` → 18px rows (Δ4).
 *   - Sentiment dot: categorical map → F1 color tokens (Δ29).
 *     positive→text-positive, negative→text-negative,
 *     mixed→text-warning, neutral/null→text-muted-foreground.
 *   - Click → `router.push('/news/' + article.article_id)` (Δ20).
 *   - Max 5 articles. Empty: "No related news in last 30 days."
 *   - No `rounded-*` (Δ3). text-[10px] labels (Δ2).
 *
 * WHO USES IT: QuoteTab.tsx (T-25 wiring pass).
 * LINE LIMIT: ≤ 150 LOC.
 */

"use client";
// WHY "use client": router.push() requires useRouter from next/navigation.

import { useRouter } from "next/navigation";
import type { RankedNewsResponse, RankedArticle } from "@/types/api";

// ── Helpers ───────────────────────────────────────────────────────────────────

/** Map categorical sentiment → Tailwind color class (Δ29). */
function sentimentColor(sentiment: RankedArticle["sentiment"]): string {
  switch (sentiment) {
    case "positive": return "text-positive";
    case "negative": return "text-negative";
    case "mixed":    return "text-warning";
    default:         return "text-muted-foreground/50";
  }
}

/** Dot char for sentiment. Unicode BULLET (●) at 10px. */
const SENTIMENT_DOT = "●";

/** Format relative time: e.g. "3h ago", "2d ago". */
function relTime(iso: string | null): string {
  if (!iso) return "";
  const diff = Date.now() - new Date(iso).getTime();
  const hours = Math.floor(diff / 3_600_000);
  if (hours < 24) return `${hours}h`;
  return `${Math.floor(hours / 24)}d`;
}

// ── Props ─────────────────────────────────────────────────────────────────────

interface RelatedHeadlinesListProps {
  /** Ranked articles from bundle.top_news or entityNews query. */
  data: RankedNewsResponse | null | undefined;
  /** True while the bundle or query is in-flight. */
  isLoading?: boolean;
}

// ── Component ─────────────────────────────────────────────────────────────────

export function RelatedHeadlinesList({ data, isLoading = false }: RelatedHeadlinesListProps) {
  const router = useRouter();

  // WHY optional chaining on .articles: RankedNewsResponse may arrive as `{}`
  // if the S9 endpoint returns a partial shape. data?.articles?.slice() guards
  // against "Cannot read properties of undefined (reading 'slice')".
  const articles = data?.articles?.slice(0, 5) ?? [];
  const isEmpty = !isLoading && articles.length === 0;

  return (
    <div className="border-t border-[hsl(var(--border-subtle))]">
      {/* Section header */}
      <div className="flex items-center h-[20px] px-3 border-b border-[hsl(var(--border-subtle))]">
        <span className="text-[9px] uppercase tracking-widest text-muted-foreground/60">
          Related News
        </span>
      </div>

      {/* WHY data-table-grid="dense": 18px rows (Δ4 dense variant). */}
      <div data-table-grid="dense">
        {isLoading && Array.from({ length: 5 }).map((_, i) => (
          <div key={i} role="row" className="flex items-center h-[var(--row-h,18px)] px-3">
            <span className="text-[10px] text-muted-foreground/30">—</span>
          </div>
        ))}

        {isEmpty && (
          <div className="px-3 py-2 text-[10px] text-muted-foreground/60">
            No related news in last 30 days.
          </div>
        )}

        {!isLoading && !isEmpty && articles.map((article) => (
          <div
            key={article.article_id}
            role="row"
            // WHY tabIndex+onClick: headline click → news detail route (Δ20).
            // button not used to preserve the row height (h-[var(--row-h)]).
            className="flex items-center h-[var(--row-h,18px)] px-3 gap-1.5 cursor-pointer hover:bg-muted/20"
            onClick={() => router.push(`/news/${article.article_id}`)}
            tabIndex={0}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === " ") {
                router.push(`/news/${article.article_id}`);
              }
            }}
          >
            {/* Sentiment dot (Δ29 — categorical color mapping) */}
            <span
              className={`text-[8px] shrink-0 ${sentimentColor(article.sentiment)}`}
              aria-label={`Sentiment: ${article.sentiment ?? "neutral"}`}
            >
              {SENTIMENT_DOT}
            </span>
            {/* Headline — truncated to available width */}
            <span className="text-[10px] text-foreground truncate flex-1 min-w-0">
              {article.title ?? "Untitled"}
            </span>
            {/* Relative time */}
            <span className="text-[9px] text-muted-foreground/50 shrink-0">
              {relTime(article.published_at)}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
