/**
 * components/dashboard/PortfolioNewsWidget.tsx — Top ranked news articles
 *
 * WHY THIS EXISTS: The dashboard morning routine includes a quick news scan.
 * Showing the 4 highest-relevance articles from the S6 ranked news endpoint
 * gives the trader immediate awareness of market-moving news before navigating
 * to the full Alerts & News page.
 *
 * WHY TOP 4 ONLY: col-span-3 is compact — 4 rows at h-[22px] plus header and
 * footer fits cleanly in the Row 4 slot without overflow.
 *
 * WHY ROUTING_TIER BADGE: The tier (LIGHT/STANDARD/HIGH, mapped from DEEP) tells
 * traders at a glance how significant the S6 pipeline ranked the article —
 * no need to parse a score number.
 *
 * WHO USES IT: app/(app)/dashboard/page.tsx (Row 4, col-span-3)
 * DATA SOURCE: S9 GET /v1/news/top via createGateway().getTopNews({ limit: 10 })
 * DESIGN REFERENCE: PRD-0031 §10 Dashboard Wave 7
 */

"use client";
// WHY "use client": uses useQuery and useAuth, and ArticleRow uses click handlers.

import { useQuery } from "@tanstack/react-query";
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { Skeleton } from "@/components/ui/skeleton";
import { InlineEmptyState } from "@/components/data/InlineEmptyState";
import { formatRelativeTime } from "@/lib/utils";
import { getNewsLinkTarget, isSafeNewsUrl } from "@/hooks/useNewsLinkTarget";
import type { RankedArticle } from "@/types/api";

// ── Component ─────────────────────────────────────────────────────────────────

/**
 * PortfolioNewsWidget — top 4 ranked articles from the S6 intelligence pipeline.
 */
export function PortfolioNewsWidget() {
  const { accessToken } = useAuth();

  const { data, isLoading, isError } = useQuery({
    queryKey: ["dashboard-portfolio-news"],
    // PLAN-0050 T-F-6-02 (closes F-D-007): the widget previously showed exactly
    // 4 rows because the cell was a single-row strip. The dashboard now gives
    // this widget the full Row 4 column height, so 4 rows leaves the bottom
    // half visibly empty and forces traders to navigate to /news/top to see
    // anything beyond the headline ribbon. We now fetch 20 articles and let
    // the inner div scroll — same DB cost as the prior 10-then-slice pattern,
    // 5× more news visible per scan.
    queryFn: () => createGateway(accessToken).getTopNews({ limit: 20 }),
    enabled: !!accessToken,
    // WHY 60_000: news feed refreshes frequently; 1-min stale time ensures we
    // catch breaking stories while not hammering S9.
    staleTime: 60_000,
    refetchInterval: 60_000,
  });

  // PLAN-0050 T-F-6-02: render up to 20 — the parent widget owns the scroll.
  // We retain a hard cap so a backend bug returning thousands of articles
  // can't blow up DOM size.
  const articles = (data?.articles ?? []).slice(0, 20);

  return (
    // WHY bg-background (not bg-card): keeps all dashboard widgets visually
    // consistent — the 1px gap-px border between cells already defines the panel
    // boundary; a raised `bg-card` surface creates a second visual layer that
    // contradicts the flat Bloomberg terminal aesthetic.
    <div className="flex h-full flex-col bg-background">

      {/* ── Section header §0.9 pattern ──────────────────────────────────── */}
      <div className="flex h-6 shrink-0 items-center border-b border-border px-2">
        <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
          PORTFOLIO NEWS
        </span>
      </div>

      {/* ── Loading state ─────────────────────────────────────────────────── */}
      {/* PLAN-0050 T-F-6-02: skeleton shows 6 rows (the visible default) so
          the loading state matches the typical scroll-window the user sees,
          rather than the prior 4-row layout. */}
      {isLoading && (
        <div className="flex-1 divide-y divide-border/30">
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="flex h-[22px] items-center gap-1.5 px-2">
              <Skeleton className="h-3 w-[30px]" style={{ animationDelay: `${i * 40}ms` }} />
              <Skeleton className="h-3 flex-1" />
              <Skeleton className="h-3 w-[24px]" />
            </div>
          ))}
        </div>
      )}

      {/* ── Error / empty state ────────────────────────────────────────────── */}
      {isError && (
        <div className="flex-1 px-2">
          <InlineEmptyState message="No recent news" />
        </div>
      )}

      {!isLoading && !isError && articles.length === 0 && (
        <div className="flex-1 px-2">
          <InlineEmptyState message="No recent news" />
        </div>
      )}

      {/* ── Article rows ───────────────────────────────────────────────────── */}
      {!isLoading && !isError && articles.length > 0 && (
        <div className="flex-1 divide-y divide-border/30 overflow-auto">
          {articles.map((article) => (
            <ArticleRow key={article.article_id} article={article} />
          ))}
        </div>
      )}

    </div>
  );
}

// ── ArticleRow sub-component ──────────────────────────────────────────────────

/**
 * ArticleRow — single article entry: impact indicator + title + relative time.
 *
 * WHY show market_impact_score as dot indicators instead of a numeric score:
 * In a 22px row, "0.82" is harder to parse than 4 filled dots (●●●●○). The
 * dot pattern encodes urgency in peripheral vision — traders don't need to read
 * the exact value to know "this is high-impact" vs "background noise."
 *
 * WHY click opens in new tab: the article URL points to the original publisher
 * (Reuters, FT, etc.). Opening in the same tab would navigate the user away from
 * the dashboard — a trader wants to skim the article alongside the terminal, not
 * lose their dashboard context entirely. new-tab respects that workflow.
 *
 * WHY noopener,noreferrer: prevents the opened tab from accessing window.opener
 * (security), and omits the Referer header (privacy). Standard practice for
 * externally-linked content in financial apps.
 */
function ArticleRow({ article }: { article: RankedArticle }) {
  // ── Market impact score → dot count (0–4) ──────────────────────────────────
  // WHY 4 dots: 5 would be too wide for the 22px row. 4 dots in 7px each = 28px
  // total (fits). The mapping is: 0–0.25→1, 0.25–0.5→2, 0.5–0.75→3, 0.75+→4.
  const score = article.market_impact_score ?? article.display_relevance_score ?? 0;
  const filledDots = Math.max(1, Math.min(4, Math.ceil(score * 4)));

  // WHY color by tier (not score): routing_tier is a pre-computed editorial
  // judgement from S6 — more reliable than the raw score for visual urgency.
  const dotColor = (() => {
    switch (article.routing_tier?.toUpperCase()) {
      case "DEEP":
      case "HIGH":
        return "text-negative";      // amber/red for high-impact news
      case "MEDIUM":
        return "text-warning";       // amber for medium (notable but not urgent)
      default:
        return "text-muted-foreground"; // muted for background/low-tier
    }
  })();

  const publishedAt = article.published_at
    ? formatRelativeTime(article.published_at)
    : "—";

  // WHY click handler only fires when url is available: if S6 didn't return a
  // URL (e.g. article is from an internal source without a public URL), we
  // silently no-op rather than navigating to "#" or throwing an error.
  function handleClick() {
    // F-QA-02 fix: validate URL scheme before navigating. React's automatic
    // `javascript:` href sanitisation does NOT apply to imperative APIs like
    // window.location.href / window.open. We accept ONLY http(s) — anything
    // else (javascript:, data:, file:, vbscript:, missing) is silently dropped
    // so a malformed/malicious URL from S6 cannot execute in the user session.
    if (!isSafeNewsUrl(article.url)) return;
    // PLAN-0050 T-F-6-20: honour the user's tab-target preference. Default is
    // "new-tab" (the prior hardcoded behaviour) so existing users see no change
    // unless they opt in via Settings → Appearance.
    const pref = getNewsLinkTarget();
    if (pref === "same-tab") {
      window.location.href = article.url!;
    } else {
      window.open(article.url!, "_blank", "noopener,noreferrer");
    }
  }

  // F-QA2-02 fix: gate the row's interactivity affordances on the SAFE-URL
  // predicate, not on the bare presence of a URL. A javascript:/data:/file:
  // URL is truthy but the click handler silently no-ops post-F-QA-02; without
  // this gate, keyboard users would tab into the row and Enter would do
  // nothing — a confusing dead-zone in the focus order. Now an unsafe URL
  // makes the row fully non-interactive (no role=button, no tabIndex, no
  // hover cursor) so SR + keyboard users skip it entirely.
  const isInteractive = isSafeNewsUrl(article.url);

  return (
    // WHY h-[22px]: §0 Terminal Quality Rules mandate 22px data rows
    // WHY cursor-pointer + hover:bg-muted/30: signals interactivity to the user;
    // the faint hover tint follows the terminal hover-state convention (not a
    // full highlight — just enough to confirm the element is clickable).
    // WHY transition-colors: instant color shift feels snappy in a terminal UI;
    // duration is omitted so it uses the global transition-colors default (150ms).
    <div
      className={`flex h-[22px] items-center gap-1.5 px-2 transition-colors ${
        isInteractive ? "cursor-pointer hover:bg-muted/30" : ""
      }`}
      onClick={isInteractive ? handleClick : undefined}
      role={isInteractive ? "button" : undefined}
      // WHY tabIndex + onKeyDown: keyboard accessibility — traders using keyboard
      // navigation can Tab to each row and press Enter/Space to open the article.
      tabIndex={isInteractive ? 0 : undefined}
      onKeyDown={(e) => {
        if (isInteractive && (e.key === "Enter" || e.key === " ")) {
          e.preventDefault();
          handleClick();
        }
      }}
      aria-label={
        isInteractive && article.title ? `Open article: ${article.title}` : undefined
      }
    >

      {/* Impact dot indicator — 4 dots, filled/empty based on score */}
      {/* WHY font-mono for dots: ensures equal width per character */}
      <span className={`shrink-0 font-mono text-[9px] ${dotColor}`} aria-label={`Impact score ${filledDots}/4`} title={`Market impact: ${(score * 100).toFixed(0)}%`}>
        {"●".repeat(filledDots)}{"○".repeat(4 - filledDots)}
      </span>

      {/* Article title — truncated to single line */}
      <span
        className="flex-1 truncate text-[11px] text-foreground"
        title={article.title ?? ""}
      >
        {article.title ?? "Untitled"}
      </span>

      {/* Relative time — right-aligned, font-mono per §0 rules */}
      <span className="shrink-0 font-mono text-[10px] tabular-nums text-muted-foreground">
        {publishedAt}
      </span>

    </div>
  );
}
