/**
 * app/(app)/news/page.tsx — News hub (top articles, cross-instrument)
 *
 * PLAN-0059 I-2: replaces the legacy redirect-to-/alerts with a real news
 * hub. Shows the ranked top news feed (S6 `/v1/news/top`) with a time-window
 * selector (1h / 24h / 7d), severity tier filter (LIGHT / MEDIUM / DEEP),
 * and a sentiment chip per article.
 *
 * WHY a top-level hub: news is cross-cutting — relevant from dashboard,
 * alerts, instrument detail, screener. Mounting it under /alerts (the prior
 * redirect target) coupled news to alerts-as-a-feature, which it isn't.
 *
 * Per-article detail (`/news/[id]`) and channel manager (`/news/feeds`) are
 * deferred to a follow-up. Clicks on an article currently link out to the
 * source URL (matches the existing alerts-tab behaviour).
 *
 * W4-NEWS changes (2026-05-19):
 *   FR-2.1  — py-1 → py-1.5 for 28px row height (HIGH-001)
 *   FR-2.2  — primary_entity as clickable Link to /intelligence/[id] (CRIT-001)
 *   FR-2.3  — sentiment derived from display_relevance_score when null (CRIT-002)
 *   FR-2.4  — SignalBadge replaces icon-only sentiment render (CRIT-002)
 *   FR-2.5  — window + tier + sentiment stored in URL params via nuqs (HIGH-005)
 *   FR-2.6  — sentiment filter button group (MED-007)
 *   FR-2.7  — load-more: aria-busy, 1000-article cap, tabular-nums score
 */

"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { parseAsString, useQueryState } from "nuqs";
import Link from "next/link";
import {
  ExternalLink,
  Filter,
  Newspaper,
} from "lucide-react";
import { useApiClient } from "@/lib/api-client";
import { DEFAULT_STALE } from "@/lib/api/_client";
import { qk } from "@/lib/query/keys";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { InlineEmptyState } from "@/components/data/InlineEmptyState";
import { ClusterArticlesModal } from "@/components/news/ClusterArticlesModal";
import { SignalBadge } from "@/components/ui/SignalBadge";
// DESIGN-QA N-2 (2026-06-18): the dense news row left a wide empty band between
// the (short) headline and the right-side metadata cluster. We fill that band
// with a compact price-impact micro-trend (T0→T5 windows) so the row "earns its
// width" — reusing the shared Sparkline primitive (whose empty-state was also
// cleaned up this sprint, so rows without impact data degrade to a calm flat
// baseline rather than a dotted placeholder).
import { Sparkline } from "@/components/primitives/Sparkline";
import { cn } from "@/lib/utils";
import type { RankedArticle, TopNewsParams } from "@/types/api";

// ── Local types ────────────────────────────────────────────────────────────

type WindowKey = "1h" | "24h" | "7d";
type TierFilter = "ALL" | "LIGHT" | "MEDIUM" | "DEEP";
// FR-2.6: sentiment filter options for client-side filtering
type SentimentFilter = "all" | "bullish" | "bearish" | "neutral";

const WINDOWS: Array<{ key: WindowKey; label: string; hours: number }> = [
  { key: "1h", label: "1h", hours: 1 },
  { key: "24h", label: "24h", hours: 24 },
  { key: "7d", label: "7d", hours: 168 },
];

// ── Helpers ────────────────────────────────────────────────────────────────

function formatPublishedAt(iso: string | null): string {
  if (!iso) return "—";
  const then = new Date(iso).getTime();
  const sec = Math.floor((Date.now() - then) / 1000);
  if (sec < 60) return "just now";
  if (sec < 3600) return `${Math.floor(sec / 60)}m`;
  if (sec < 86400) return `${Math.floor(sec / 3600)}h`;
  return `${Math.floor(sec / 86400)}d`;
}

/**
 * deriveSentiment — map article fields to SignalBadge's bullish/bearish/neutral.
 *
 * WHY this function (FR-2.3, CRIT-002):
 * S6 currently emits sentiment as "positive" / "negative" / "mixed" / null.
 * SignalBadge only knows "bullish" / "bearish" / "neutral".
 * For LIGHT-tier articles where sentiment is never set, we fall back to
 * display_relevance_score thresholds (≥0.7 → bullish, ≤0.3 → bearish).
 * This gives traders a visual direction signal even when S6 hasn't scored yet.
 */
function deriveSentiment(
  sentiment: "positive" | "negative" | "neutral" | "mixed" | null | undefined,
  score: number | null | undefined,
): "bullish" | "bearish" | "neutral" | null {
  // Explicit sentiment from S6 takes priority — map to SignalBadge vocabulary.
  if (sentiment === "positive") return "bullish";
  if (sentiment === "negative") return "bearish";
  if (sentiment === "neutral") return "neutral";
  // "mixed" maps to neutral (both directions, no net signal)
  if (sentiment === "mixed") return "neutral";
  // No sentiment field — derive from composite relevance score.
  if (score == null) return null; // no data at all
  if (score >= 0.7) return "bullish";
  if (score <= 0.3) return "bearish";
  return "neutral";
}

// ── Page ───────────────────────────────────────────────────────────────────

export default function NewsHubPage() {
  const gateway = useApiClient();

  // FR-2.5: window + tier stored in URL via nuqs so filter state survives
  // navigation and can be shared via URL. parseAsString with default handles
  // unknown values gracefully; we validate with WINDOWS/TIERS arrays below.
  // WHY nuqs over useState: bookmarkable links, browser back/forward, deep links.
  const [rawWindow, setWindowKey] = useQueryState(
    "window",
    parseAsString.withDefault("24h"),
  );
  const [rawTier, setTier] = useQueryState(
    "tier",
    parseAsString.withDefault("ALL"),
  );
  // FR-2.6: sentiment stored in URL for shareability; client-side only (no API param).
  const [rawSentiment, setSentimentFilter] = useQueryState(
    "sentiment",
    parseAsString.withDefault("all"),
  );

  // Validate the raw URL values against known keys to prevent URL tampering
  // from propagating invalid values to the UI or API.
  const windowKey: WindowKey =
    (["1h", "24h", "7d"] as const).includes(rawWindow as WindowKey)
      ? (rawWindow as WindowKey)
      : "24h";
  const tier: TierFilter =
    (["ALL", "LIGHT", "MEDIUM", "DEEP"] as const).includes(rawTier as TierFilter)
      ? (rawTier as TierFilter)
      : "ALL";
  const sentimentFilter: SentimentFilter =
    (["all", "bullish", "bearish", "neutral"] as const).includes(rawSentiment as SentimentFilter)
      ? (rawSentiment as SentimentFilter)
      : "all";

  // QA-iter1: explicit "Load more" pagination — was hard-capped at 50 with
  // no signal when total > 50. Now the consumer can grow the page; UI shows
  // "Showing N of M" so silent truncation is impossible.
  const [pageSize, setPageSize] = useState<number>(50);

  // P2-F: cluster modal — null = closed; non-null = open with that cluster_id.
  // WHY a single state string | null (not separate isOpen + id): the cluster_id
  // IS the open-state signal. null unambiguously means "closed".
  const [clusterModalId, setClusterModalId] = useState<string | null>(null);

  // Derive hours from the windowKey for the API call.
  const windowHours = WINDOWS.find((w) => w.key === windowKey)?.hours ?? 24;

  const params: TopNewsParams = useMemo(() => {
    return {
      hours: windowHours,
      limit: pageSize,
      ...(tier !== "ALL" ? { routing_tier: tier } : {}),
    };
  }, [windowHours, tier, pageSize]);

  const { data, isLoading, isFetching, isError, refetch } = useQuery({
    // qk.news.top accepts a generic record; cast preserves call-site clarity
    // without forcing TopNewsParams to add an index signature.
    queryKey: qk.news.top(params as unknown as Readonly<Record<string, unknown>>),
    queryFn: () => gateway.getTopNews(params),
    // QA-iter1: dropped `enabled: !!accessToken` — /v1/news/top is a public
    // endpoint per S6 contract. Gating it on auth made signed-out users see
    // a permanent skeleton (this page lives under (app)/ so it's not visible
    // to them today, but the leak would surface in any future public mount).
    // WHY DEFAULT_STALE.news (5min): canonical stale window for news endpoints.
    // Prevents the same endpoint being fetched with different staleTime values
    // by different components (HIGH-018 / FR-8.4).
    staleTime: DEFAULT_STALE.news,
    refetchInterval: DEFAULT_STALE.news,
  });

  const articles = data?.articles ?? [];

  // FR-2.6: client-side sentiment filter applied on top of API results.
  // WHY client-side (not API param): sentiment is derived, not a stored DB field.
  // Sending it to the API would require S6 to compute the same derivation we do
  // here, coupling two systems to the same heuristic. Client filter is instant.
  const filteredArticles = useMemo(() => {
    if (sentimentFilter === "all") return articles;
    return articles.filter((a: RankedArticle) => {
      const derived = deriveSentiment(a.sentiment, a.display_relevance_score);
      return derived === sentimentFilter;
    });
  }, [articles, sentimentFilter]);

  return (
    <>
    {/* P2-F: ClusterArticlesModal — rendered at page level so it can overlay
        the full news list. The Sheet backdrop requires a portal root which
        sits outside the flex column. Controlled by clusterModalId state. */}
    <ClusterArticlesModal
      clusterId={clusterModalId}
      onClose={() => setClusterModalId(null)}
    />
    <div className="flex h-full flex-col overflow-hidden">
      {/* Header */}
      <div className="flex h-7 shrink-0 items-center gap-2 border-b border-border px-3">
        <Newspaper className="h-3 w-3 text-muted-foreground" aria-hidden strokeWidth={1.5} />
        <h1 className="font-mono text-[11px] uppercase tracking-[0.08em] text-foreground">
          News
        </h1>
        {data && (
          <span className="font-mono text-[10px] tabular-nums text-muted-foreground/60">
            {data.total}
          </span>
        )}
        <div className="ml-auto flex items-center gap-2">
          {/* Time-window selector */}
          <div role="group" aria-label="Time window" className="flex gap-px">
            {WINDOWS.map((w) => (
              <button
                key={w.key}
                onClick={() => setWindowKey(w.key)}
                className={cn(
                  "rounded-[2px] px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wider transition-colors",
                  windowKey === w.key
                    ? "bg-primary/20 text-primary"
                    : "text-muted-foreground hover:text-foreground",
                )}
                aria-pressed={windowKey === w.key}
              >
                {w.label}
              </button>
            ))}
          </div>

          <span className="h-3 w-px bg-border/50" aria-hidden />

          {/* Tier filter */}
          <div className="flex items-center gap-1">
            <Filter className="h-3 w-3 text-muted-foreground/60" aria-hidden strokeWidth={1.5} />
            {(["ALL", "DEEP", "MEDIUM", "LIGHT"] as const).map((t) => (
              <button
                key={t}
                onClick={() => setTier(t)}
                className={cn(
                  "rounded-[2px] px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wider transition-colors",
                  tier === t
                    ? "text-foreground ring-1 ring-border bg-transparent"
                    : "text-muted-foreground/70 hover:text-foreground",
                )}
                aria-pressed={tier === t}
                title={`Filter to ${t} tier articles`}
              >
                {t}
              </button>
            ))}
          </div>

          <span className="h-3 w-px bg-border/50" aria-hidden />

          {/* FR-2.6: Sentiment filter button group — client-side filter derived
              from display_relevance_score when explicit sentiment is null.
              WHY here (not below header): keeps all filters in one toolbar row
              at the top, consistent with Bloomberg-style dense control bars. */}
          <div className="flex items-center gap-1">
            {(["all", "bullish", "bearish", "neutral"] as const).map((s) => (
              <button
                key={s}
                onClick={() => setSentimentFilter(s)}
                className={cn(
                  "h-6 rounded-[2px] px-2 text-[10px] uppercase tracking-wide font-mono transition-colors",
                  sentimentFilter === s
                    ? "bg-primary/10 text-primary border border-primary/20"
                    : "text-muted-foreground hover:text-foreground border border-transparent",
                )}
                aria-pressed={sentimentFilter === s}
                title={`Show ${s === "all" ? "all" : s} articles`}
              >
                {s}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Body */}
      <div className="flex-1 overflow-auto">
        {isLoading ? (
          // WHY h-6 rows (not h-12 block): article rows are single-line ~24px.
          // A 48px skeleton would shift layout when real rows arrive. Match actual height.
          <div className="divide-y divide-border/40">
            {Array.from({ length: 18 }).map((_, i) => (
              <div key={i} className="flex h-6 items-center gap-2 px-3" style={{ animationDelay: `${i * 20}ms` }}>
                <Skeleton className="h-3 w-8 shrink-0" />
                <Skeleton className="h-3 flex-1" />
                <Skeleton className="h-3 w-12 shrink-0" />
              </div>
            ))}
          </div>
        ) : isError ? (
          // WHY p-3 (was p-4): error state inside a dense article list — the
          // 12px padding visually anchors the message to the surrounding row
          // rhythm without crowding the retry button.
          <div className="flex flex-col items-start gap-2 p-3">
            <InlineEmptyState message="News failed to load — check connection." />
            <Button variant="outline" density="compact" onClick={() => refetch()}>
              Retry
            </Button>
          </div>
        ) : filteredArticles.length === 0 ? (
          <div className="flex flex-1 items-center justify-center px-4 py-12">
            <InlineEmptyState message={
              sentimentFilter !== "all"
                ? `No ${sentimentFilter} articles in this window.`
                : "No articles in this window."
            } />
          </div>
        ) : (
          <>
            <ul className="divide-y divide-border/40">
              {filteredArticles.map((a) => (
                <li key={a.article_id}>
                  {/* P2-F: pass setClusterModalId so clicking "+N sim" opens the drawer */}
                  <ArticleRow article={a} onClusterClick={setClusterModalId} />
                </li>
              ))}
            </ul>
            {/* QA-iter1: explicit pagination so silent truncation at 50
                articles is impossible. Shows count + Load-more when total>shown.
                FR-2.7: aria-busy + 1000-article cap to prevent unbounded growth. */}
            {data && (
              <div className="flex items-center justify-between border-t border-border/40 px-3 py-2 text-[10px]">
                <span className="font-mono tabular-nums text-muted-foreground">
                  Showing {filteredArticles.length}
                  {sentimentFilter !== "all" && ` ${sentimentFilter}`}
                  {" "}of {data.total}
                </span>
                {/* FR-2.7: if total loaded >= 1000, show cap message instead of button */}
                {articles.length >= 1000 ? (
                  <p className="py-0 font-mono text-[11px] text-muted-foreground">
                    Showing {articles.length.toLocaleString()} articles. Use filters to narrow results.
                  </p>
                ) : data.total > articles.length && (
                  <Button
                    density="compact"
                    variant="outline"
                    onClick={() => setPageSize((n) => n + 50)}
                    disabled={isFetching}
                    // FR-2.7: aria-busy signals screen readers that content is loading
                    aria-busy={isFetching}
                  >
                    {isFetching ? "Loading…" : "Load 50 more"}
                  </Button>
                )}
              </div>
            )}
          </>
        )}
      </div>
    </div>
    </>
  );
}

// ── Article row ────────────────────────────────────────────────────────────

function ArticleRow({
  article: a,
  onClusterClick,
}: {
  article: RankedArticle;
  // P2-F: callback to open the cluster modal. Called with the cluster_id string.
  // Optional — the chip is not rendered when cluster_size <= 1 anyway.
  onClusterClick?: (clusterId: string) => void;
}) {
  // QA-iter1: tier pill is now neutral so it doesn't visually compete with
  // the active-window selector (which uses bg-primary/20). Reserve primary
  // tint for user-controllable state; tiers are server-classified data.
  const tierClass =
    a.routing_tier === "DEEP"
      ? "text-foreground ring-1 ring-border"
      : a.routing_tier === "MEDIUM"
      ? "text-foreground bg-muted/40"
      : a.routing_tier === "LIGHT"
      ? "text-muted-foreground/60 bg-muted/20"
      : "text-muted-foreground bg-muted/20";

  // FR-2.3+2.4 (CRIT-002): derive sentiment from score when S6 hasn't set it.
  // WHY here (not just in the filter): the row renders the badge unconditionally;
  // derivation must happen at render time so the badge reflects the same value
  // used by the sentiment filter (single source of truth).
  const derivedSentiment = deriveSentiment(a.sentiment, a.display_relevance_score);

  // LIGHT tier: dim per existing convention (PRD-0027 OQ-6 → opacity 0.6).
  const isDim = a.routing_tier === "LIGHT";

  // DESIGN-QA N-2: build the price-impact micro-trend series from the T0→T5
  // windows. We anchor at 0 (publication baseline) then chart the cumulative
  // impact at T0/T1/T2/T5 so the Sparkline shows the post-publication drift.
  // WHY filter null: windows are null until OHLCV lands (< ~25h old articles);
  // a series with < 2 real points falls into the Sparkline's clean flat-baseline
  // empty state, so the gap still reads as intentional (not broken).
  const iw = a.impact_windows;
  const impactSeries = iw
    ? [0, iw.day_t0, iw.day_t1, iw.day_t2, iw.day_t5].filter(
        (v): v is number => v != null,
      )
    : [];

  // WHY single-line: Bloomberg terminal news ticker format. Two-line layout was
  // ~42px/row; single-line is ~26px/row (62% reduction). With 50 articles,
  // viewport shows all instead of needing 4+ screens of scroll.
  return (
    <a
      href={a.url ?? "#"}
      target="_blank"
      rel="noopener noreferrer"
      // QA-iter1 a11y: explicit "(opens in new tab)" cue so SR users hear
      // it before activation. Composed with the article title.
      aria-label={`${a.title ?? "(untitled)"}${a.primary_entity_symbol ? `, ${a.primary_entity_symbol}` : ""} (opens in new tab)`}
      className={cn(
        // FR-2.1 (HIGH-001): py-1 → py-1.5 for 28px row height.
        // 6px top + 6px bottom = 12px total vert padding + 16px line = 28px row.
        // WHY 28px (not 24px): density test showed 24px clipped descenders on
        // lowercase letters like "g/y/p"; 28px is the minimum safe row height.
        "block px-3 py-1.5 transition-colors hover:bg-muted/30 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-primary",
        isDim && "opacity-60",
      )}
    >
      {/* Single flex row — all metadata inline, Bloomberg ticker format. */}
      <div className="flex items-baseline gap-2">
        {/* Tier pill */}
        <span
          className={cn(
            "shrink-0 rounded-[2px] px-1 font-mono text-[9px] uppercase tracking-wider",
            tierClass,
          )}
          title={`Routing tier: ${a.routing_tier ?? "unknown"}`}
        >
          {a.routing_tier ?? "—"}
        </span>

        {/* FR-2.3+2.4 (CRIT-002): SignalBadge replaces icon-only sentiment.
            derivedSentiment is null when both explicit sentiment and score are
            unavailable — SignalBadge renders nothing in that case. */}
        <span className="shrink-0">
          <SignalBadge sentiment={derivedSentiment} />
        </span>

        {/* FR-2.2 (CRIT-001): primary entity as a Link to /intelligence/[id].
            When primary_entity_id is present, render a clickable Link so traders
            can pivot to the entity graph. Clicking must NOT follow the outer <a>
            href (article URL), so we use e.stopPropagation(). */}
        {a.primary_entity_id ? (
          <Link
            href={`/intelligence/${a.primary_entity_id}`}
            className="shrink-0 font-mono text-[10px] tabular-nums text-primary hover:underline"
            onClick={(e) => e.stopPropagation()}
            title={`View entity: ${a.primary_entity_symbol ?? a.primary_entity_id}`}
          >
            {a.primary_entity_symbol ?? a.primary_entity_id}
          </Link>
        ) : a.primary_entity_symbol ? (
          // No entity ID but we have a symbol — render plain text.
          <span className="shrink-0 font-mono text-[10px] tabular-nums text-primary">
            {a.primary_entity_symbol}
          </span>
        ) : null}

        {/* Title — fills remaining horizontal space, truncates at right cluster */}
        <span className="flex-1 truncate text-[11px] leading-snug text-foreground">
          {a.title ?? "(untitled)"}
        </span>

        {/* DESIGN-QA N-2: price-impact micro-trend — fills the dead band the
            short headlines used to leave between the title and the right cluster.
            Trend colour is the Sparkline's auto first-vs-last delta (positive
            green / negative red), giving an at-a-glance "did this move the
            stock" signal per row. Hidden on the narrowest layouts (sm:block) so
            it never crowds the title on small viewports; aria-hidden because the
            timestamp/score already carry the row's text signal for SR users. */}
        <span className="hidden shrink-0 sm:block" aria-hidden>
          <Sparkline data={impactSeries} width={56} height={14} label="price impact" />
        </span>

        {/* Right cluster — source, relevance, timestamp, external icon */}

        {/* Source label — compact uppercase chip.
            WHY source_name preferred over source_type: source_name is a
            human-readable outlet name ("Bloomberg") while source_type is a
            technical identifier ("eodhd_news"). Fall back to source_type
            when name is absent, uppercasing it so "eodhd" reads as "EODHD". */}
        {(a.source_name || a.source_type) && (
          <span className="shrink-0 rounded-[2px] border border-border/30 px-1 font-mono text-[9px] text-muted-foreground/60 uppercase tracking-wider">
            {(a.source_name ?? a.source_type ?? "").slice(0, 8)}
          </span>
        )}

        {/* FR-2.7 (LOW-003): relevance score with tabular-nums for column alignment.
            WHY Math.round (not toFixed(0)): Math.round avoids ".0" artifacts and
            returns an integer type which is safe to coerce for aria-label. */}
        {a.display_relevance_score > 0 && (
          <span className="shrink-0 rounded-[2px] bg-muted/40 px-1 font-mono text-[9px] tabular-nums text-muted-foreground">
            <span className="font-mono tabular-nums">{Math.round(a.display_relevance_score * 100)}</span>
          </span>
        )}

        {/* Cluster-size chip — "+N sim" button when near-duplicates exist.
            WHY "similar" (not "dupes"): near-duplicates are corroboration
            signals, not garbage — "similar" is descriptive, "dupes" implies
            the article itself is a duplicate which it may not be.
            WHY only when cluster_size > 1: cluster_size=1 means "alone".
            P2-F: changed from <span> to <button> so clicking opens the
            ClusterArticlesModal sheet. e.stopPropagation() prevents the outer
            <a> href from firing (article would open externally instead). */}
        {a.cluster_size != null && a.cluster_size > 1 && a.cluster_id && (
          <button
            type="button"
            className={cn(
              "shrink-0 rounded-[2px] bg-muted/40 px-1 font-mono text-[9px] tabular-nums text-muted-foreground/70",
              // WHY cursor-pointer + hover ring: this is now interactive. The hover
              // ring signals clickability without changing the terminal-density style.
              "cursor-pointer hover:bg-muted/70 hover:text-muted-foreground transition-colors",
              "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-primary/60",
            )}
            title={`${a.cluster_size - 1} similar article${a.cluster_size - 1 !== 1 ? "s" : ""} cover the same story — click to view`}
            onClick={(e) => {
              // WHY stopPropagation: the button is nested inside an <a> tag.
              // Without this, clicking the button would also trigger the <a>
              // href (opening the article in a new tab at the same time).
              e.stopPropagation();
              e.preventDefault();
              if (a.cluster_id) onClusterClick?.(a.cluster_id);
            }}
            aria-label={`View ${a.cluster_size - 1} similar article${a.cluster_size - 1 !== 1 ? "s" : ""}`}
          >
            +{a.cluster_size - 1} sim
          </button>
        )}

        {/* Timestamp */}
        <span className="shrink-0 font-mono text-[10px] tabular-nums text-muted-foreground">
          {formatPublishedAt(a.published_at)}
        </span>
        <ExternalLink className="h-3 w-3 shrink-0 text-muted-foreground/50" aria-hidden />
      </div>
    </a>
  );
}
