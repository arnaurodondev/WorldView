/**
 * components/portfolio/HoldingNewsList.tsx — compact per-instrument news list
 * (PRD-0089 SA-B)
 *
 * WHY THIS EXISTS: The HoldingDetailPanel needs a quick-scan recent news list
 * for a specific instrument. The instrument detail page has a full news tab,
 * but a preview of 5 headlines directly in the slide-over reduces the need to
 * navigate away just to see "did anything happen with this stock today?".
 *
 * DATA SOURCE: GET /v1/news/entity/{instrumentId}?limit=N
 *   (S9 → S6 NLP pipeline; returns RankedArticle[] sorted by relevance score)
 *   The instrumentId is used as the entity_id here — S9 accepts the instrument's
 *   canonical entity_id. Holdings rows carry entity_id from overviews; we receive
 *   the instrumentId (UUID) and use it directly as the entity parameter.
 *
 * NOTE on entity_id vs instrument_id: the news endpoint is keyed by entity_id.
 * In PRD-0089 F2, entity_id == instrument_id for tradable securities (unified
 * namespace). The caller (HoldingDetailPanel) passes holding.instrumentId which
 * is the canonical entity UUID for the news query.
 *
 * WHO USES IT: HoldingDetailPanel (section 6)
 * DESIGN REFERENCE: PRD-0089 SA-B §D
 */

"use client";
// WHY "use client": useQuery + useRouter are browser-only hooks.

import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useApiClient } from "@/lib/api-client";
import { qk } from "@/lib/query/keys";
import type { RankedNewsResponse } from "@/types/api";

// ── Props ─────────────────────────────────────────────────────────────────────

interface HoldingNewsListProps {
  instrumentId: string;
  /** Max headlines to show. Defaults to 5. */
  limit?: number;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

/**
 * Relative time label for a published_at ISO string.
 *
 * WHY inline (not DataFreshnessPill): DataFreshnessPill renders a <span> with
 * `title=` tooltip. Here we just need the string value to embed in a flex row
 * alongside the source name.
 */
function relativeAge(isoString: string | null): string {
  if (!isoString) return "";
  const ms = Date.now() - new Date(isoString).getTime();
  if (ms < 0) return "just now";
  if (ms < 60_000) return `${Math.floor(ms / 1000)}s ago`;
  if (ms < 3_600_000) return `${Math.floor(ms / 60_000)}m ago`;
  if (ms < 86_400_000) return `${Math.floor(ms / 3_600_000)}h ago`;
  return `${Math.floor(ms / 86_400_000)}d ago`;
}

// ── Component ─────────────────────────────────────────────────────────────────

export function HoldingNewsList({
  instrumentId,
  limit = 5,
}: HoldingNewsListProps) {
  const apiClient = useApiClient();
  const router = useRouter();

  // WHY qk.news.holdingNewsTop (D12 remediation): the previous
  // qk.news.forEntity(instrumentId) key collided with the IntelligenceTab
  // news list which fetches the same entity feed with a different (larger)
  // limit. Both consumers wrote into the same cache slot causing whichever
  // fetched first to win. The dedicated holdingNewsTop key encodes the
  // limit so per-holding panels cache independently from IntelligenceTab.
  const { data, isLoading, isError } = useQuery<RankedNewsResponse>({
    queryKey: qk.news.holdingNewsTop(instrumentId, limit),
    queryFn: () => apiClient.getEntityNews(instrumentId, { limit }),
    enabled: Boolean(instrumentId),
    staleTime: 300_000, // 5 min — news doesn't change second-to-second
  });

  // ── Loading skeleton ──────────────────────────────────────────────────────
  if (isLoading) {
    return (
      <div className="px-3 py-2 space-y-1">
        {Array.from({ length: limit }).map((_, i) => (
          <div key={i} className="space-y-px">
            {/* Headline skeleton — wider */}
            <div className="h-[12px] w-full animate-pulse rounded bg-muted" />
            {/* Source+age skeleton — narrower */}
            <div className="h-[10px] w-24 animate-pulse rounded bg-muted" />
          </div>
        ))}
      </div>
    );
  }

  // ── Error state ───────────────────────────────────────────────────────────
  // WHY a dedicated branch (per design §7): a failed news fetch should tell
  // the user the feed is temporarily unavailable rather than silently falling
  // through to "No recent news" which implies "no news exists for this stock".
  if (isError) {
    return (
      <div className="px-3 py-2 font-mono text-[11px] text-negative">
        News feed temporarily unavailable
      </div>
    );
  }

  const articles = (data?.articles ?? []).slice(0, limit);

  // ── Empty state ───────────────────────────────────────────────────────────
  if (articles.length === 0) {
    return (
      <div className="px-3 py-2 font-mono text-[11px] text-muted-foreground">
        No recent news
      </div>
    );
  }

  // ── Render ────────────────────────────────────────────────────────────────
  return (
    <div className="divide-y divide-border/50">
      {articles.map((article) => (
        // WHY a <button> (not <a href={article.url}>): the task spec requires
        // navigating to the instrument page (not the article URL). Instrument
        // navigation keeps the user inside the app where context is preserved.
        // If the article URL were needed, the full IntelligenceTab handles that.
        <button
          key={article.article_id}
          type="button"
          onClick={() => router.push(`/instruments/${encodeURIComponent(instrumentId)}`)}
          className="w-full text-left px-3 py-1.5 hover:bg-muted/30 transition-colors group"
          // WHY aria-label: the button text is a headline that may be truncated;
          // including the full title in aria-label gives screen readers the full
          // content even when the visual display is cut off.
          aria-label={article.title ?? "News article"}
        >
          {/* Headline — single line, truncated with ellipsis */}
          <p className="truncate text-[11px] text-foreground group-hover:text-primary transition-colors">
            {article.title ?? "Untitled article"}
          </p>

          {/* Source + age — subdued metadata line */}
          <p className="text-[10px] text-muted-foreground mt-px">
            {[
              article.source_name ?? article.source_type ?? "",
              relativeAge(article.published_at),
            ]
              .filter(Boolean)
              .join(" · ")}
          </p>
        </button>
      ))}
    </div>
  );
}
