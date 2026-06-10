/**
 * components/instrument/quote/bottom/WhatsMovingStrip.tsx
 * — Top-3 "what's moving" news strip (W5-T-21)
 *
 * DATA SOURCE: `data: RankedNewsResponse | null` from bundle.top_news.
 *   Zero extra fetch — the bundle already delivers top-N entity news.
 *
 * DESIGN:
 *   - `data-table-grid` → 20px rows (Δ4).
 *   - Sentiment dot (Δ29) + headline truncated + relative time.
 *   - Click → `/news/{article_id}` (Δ20). No `rounded-*` (Δ3).
 *   - Empty: "No recent news." (3 rows not 5 — space budget in triple strip).
 *
 * WHO USES IT: BottomTripleStrip.tsx (T-22).
 * LINE LIMIT: ≤ 110 LOC.
 */

"use client";

import { useRouter } from "next/navigation";
import type { RankedNewsResponse, RankedArticle } from "@/types/api";

// ── Helpers ───────────────────────────────────────────────────────────────────

function sentimentColor(s: RankedArticle["sentiment"]): string {
  switch (s) {
    case "positive": return "text-positive";
    case "negative": return "text-negative";
    case "mixed":    return "text-warning";
    default:         return "text-muted-foreground/40";
  }
}

function relTime(iso: string | null): string {
  if (!iso) return "";
  const h = Math.floor((Date.now() - new Date(iso).getTime()) / 3_600_000);
  return h < 24 ? `${h}h` : `${Math.floor(h / 24)}d`;
}

// ── Props ─────────────────────────────────────────────────────────────────────

interface WhatsMovingStripProps {
  data: RankedNewsResponse | null | undefined;
  isLoading?: boolean;
}

// ── Component ─────────────────────────────────────────────────────────────────

export function WhatsMovingStrip({ data, isLoading = false }: WhatsMovingStripProps) {
  const router = useRouter();
  // WHY optional chaining on .articles: RankedNewsResponse may arrive as `{}` if
  // the endpoint returns a partial shape (e.g. catch-all mock). data?.articles
  // would be undefined → .slice() crash. data?.articles?.slice() is safe.
  const articles = data?.articles?.slice(0, 3) ?? [];
  const isEmpty = !isLoading && articles.length === 0;

  return (
    <div>
      {/* Column header */}
      <div className="flex items-center h-[20px] px-2 border-b border-[hsl(var(--border-subtle))]">
        <span className="text-[9px] uppercase tracking-widest text-muted-foreground/60">
          What&apos;s Moving
        </span>
      </div>

      <div data-table-grid>
        {isLoading && Array.from({ length: 3 }).map((_, i) => (
          <div key={i} role="row" className="flex items-center h-[var(--row-h,20px)] px-2">
            <span className="text-[10px] text-muted-foreground/30">—</span>
          </div>
        ))}

        {isEmpty && (
          <div className="px-2 py-2 text-[10px] text-muted-foreground/60">
            No recent news.
          </div>
        )}

        {!isLoading && !isEmpty && articles.map((article) => (
          <div
            key={article.article_id}
            role="row"
            className="flex items-center h-[var(--row-h,20px)] px-2 gap-1.5 cursor-pointer hover:bg-muted/20"
            onClick={() => router.push(`/news/${article.article_id}`)}
            tabIndex={0}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === " ") {
                router.push(`/news/${article.article_id}`);
              }
            }}
          >
            {/* Sentiment dot (Δ29) */}
            <span className={`text-[8px] shrink-0 ${sentimentColor(article.sentiment)}`}>●</span>
            {/* Headline */}
            <span className="text-[10px] text-foreground truncate flex-1 min-w-0">
              {article.title ?? "Untitled"}
            </span>
            {/* Relative time — Round-3 item 2 (ADR-F-15): timestamps are
                numerics → font-mono tabular-nums so the right-aligned column
                of "2h/3d" labels doesn't jitter across rows. */}
            <span className="font-mono tabular-nums text-[9px] text-muted-foreground/50 shrink-0">
              {relTime(article.published_at)}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
