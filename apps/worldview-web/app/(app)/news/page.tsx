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
 */

"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  ExternalLink,
  Filter,
  Newspaper,
  TrendingDown,
  TrendingUp,
  Zap,
} from "lucide-react";
import { useApiClient } from "@/lib/api-client";
import { qk } from "@/lib/query/keys";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { InlineEmptyState } from "@/components/data/InlineEmptyState";
import { cn } from "@/lib/utils";
import type { RankedArticle, TopNewsParams } from "@/types/api";

// ── Local types ────────────────────────────────────────────────────────────

type WindowKey = "1h" | "24h" | "7d";
type TierFilter = "ALL" | "LIGHT" | "MEDIUM" | "DEEP";

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

// ── Page ───────────────────────────────────────────────────────────────────

export default function NewsHubPage() {
  const gateway = useApiClient();
  const [windowKey, setWindowKey] = useState<WindowKey>("24h");
  const [tier, setTier] = useState<TierFilter>("ALL");
  // QA-iter1: explicit "Load more" pagination — was hard-capped at 50 with
  // no signal when total > 50. Now the consumer can grow the page; UI shows
  // "Showing N of M" so silent truncation is impossible.
  const [pageSize, setPageSize] = useState<number>(50);

  const params: TopNewsParams = useMemo(() => {
    const hours = WINDOWS.find((w) => w.key === windowKey)?.hours ?? 24;
    return {
      hours,
      limit: pageSize,
      ...(tier !== "ALL" ? { routing_tier: tier } : {}),
    };
  }, [windowKey, tier, pageSize]);

  const { data, isLoading, isFetching, isError, refetch } = useQuery({
    // qk.news.top accepts a generic record; cast preserves call-site clarity
    // without forcing TopNewsParams to add an index signature.
    queryKey: qk.news.top(params as unknown as Readonly<Record<string, unknown>>),
    queryFn: () => gateway.getTopNews(params),
    // QA-iter1: dropped `enabled: !!accessToken` — /v1/news/top is a public
    // endpoint per S6 contract. Gating it on auth made signed-out users see
    // a permanent skeleton (this page lives under (app)/ so it's not visible
    // to them today, but the leak would surface in any future public mount).
    staleTime: 60_000,
    refetchInterval: 60_000,
  });

  const articles = data?.articles ?? [];

  return (
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
        </div>
      </div>

      {/* Body */}
      <div className="flex-1 overflow-auto">
        {isLoading ? (
          <div className="space-y-1 p-2">
            {Array.from({ length: 12 }).map((_, i) => (
              <Skeleton key={i} className="h-12" style={{ animationDelay: `${i * 30}ms` }} />
            ))}
          </div>
        ) : isError ? (
          <div className="flex flex-col items-start gap-2 p-4">
            <InlineEmptyState message="News failed to load — check connection." />
            <Button variant="outline" density="compact" onClick={() => refetch()}>
              Retry
            </Button>
          </div>
        ) : articles.length === 0 ? (
          <div className="flex flex-1 items-center justify-center px-4 py-12">
            <InlineEmptyState message="No articles in this window." />
          </div>
        ) : (
          <>
            <ul className="divide-y divide-border/40">
              {articles.map((a) => (
                <li key={a.article_id}>
                  <ArticleRow article={a} />
                </li>
              ))}
            </ul>
            {/* QA-iter1: explicit pagination so silent truncation at 50
                articles is impossible. Shows count + Load-more when total>shown. */}
            {data && (
              <div className="flex items-center justify-between border-t border-border/40 px-3 py-2 text-[10px]">
                <span className="font-mono tabular-nums text-muted-foreground">
                  Showing {articles.length} of {data.total}
                </span>
                {data.total > articles.length && (
                  <Button
                    density="compact"
                    variant="outline"
                    onClick={() => setPageSize((n) => n + 50)}
                    disabled={isFetching}
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
  );
}

// ── Article row ────────────────────────────────────────────────────────────

function ArticleRow({ article: a }: { article: RankedArticle }) {
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

  const sentimentIcon =
    a.sentiment === "positive" ? (
      <TrendingUp className="h-3 w-3 text-positive" aria-label="Positive sentiment" strokeWidth={1.5} />
    ) : a.sentiment === "negative" ? (
      <TrendingDown className="h-3 w-3 text-negative" aria-label="Negative sentiment" strokeWidth={1.5} />
    ) : a.sentiment === "mixed" ? (
      <Zap className="h-3 w-3 text-warning" aria-label="Mixed sentiment" strokeWidth={1.5} />
    ) : null;

  // LIGHT tier: dim per existing convention (PRD-0027 OQ-6 → opacity 0.6).
  const isDim = a.routing_tier === "LIGHT";

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
        // WHY py-1 (was py-1.5): single-line rows need less vertical padding.
        // 4px top + 4px bottom = 8px total vert padding + 16px line = 24px row.
        "block px-3 py-1 transition-colors hover:bg-muted/30 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-primary",
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

        {/* Sentiment + primary entity */}
        <span className="shrink-0">{sentimentIcon}</span>
        {a.primary_entity_symbol && (
          <span className="shrink-0 font-mono text-[10px] tabular-nums text-primary">
            {a.primary_entity_symbol}
          </span>
        )}

        {/* Title — fills remaining horizontal space, truncates at right cluster */}
        <span className="flex-1 truncate text-[11px] leading-snug text-foreground">
          {a.title ?? "(untitled)"}
        </span>

        {/* Right cluster — source, relevance, timestamp, external icon */}

        {/* Source name — compact label before timestamp */}
        {(a.source_name || a.source_type) && (
          <span className="shrink-0 font-mono text-[9px] text-muted-foreground/60 uppercase tracking-wider">
            {(a.source_name ?? a.source_type ?? "").slice(0, 12)}
          </span>
        )}

        {/* Relevance score badge — only when > 0 */}
        {a.display_relevance_score > 0 && (
          <span className="shrink-0 rounded-[2px] bg-muted/40 px-1 font-mono text-[9px] tabular-nums text-muted-foreground">
            {(a.display_relevance_score * 100).toFixed(0)}
          </span>
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
