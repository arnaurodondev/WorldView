/**
 * components/instrument/NewsTab.tsx — Entity news tab with relevance/sentiment/impact pills
 *
 * WHY THIS EXISTS: The News tab was previously inlined directly in the instrument
 * detail page ([entityId]/page.tsx). Extracting it into its own component:
 *   1. Keeps the page thin — page only handles routing and tab state.
 *   2. Co-locates all news UI logic (filters, grouping, rendering) in one file.
 *   3. Enables independent testing of news features (T-E-5-07).
 *
 * PLAN-0050 Wave E adds:
 *   - Relevance gradient badge (amber → green based on display_relevance_score 0-1)
 *   - Sentiment pill: positive=teal (#26A69A), negative=red (#EF5350),
 *     neutral=muted (#787B86), mixed=amber (#F59E0B)
 *   - Impact pill: intensity gradient using impact_score 0-1
 *   - Entity chips: clickable → instrument page (primary_entity_symbol only for now;
 *     entity-level chips require a separate entity→ticker lookup not in RankedArticle)
 *   - Time-grouping headers (TODAY / PAST 3 DAYS / PAST WEEK / OLDER)
 *   - Source filter dropdown (client-side)
 *   - Sort dropdown (by relevance / impact / time)
 *
 * WHY CLIENT-SIDE FILTERS: The news list is already fetched (20 articles).
 * Filtering client-side avoids a new S9 query on each filter change and provides
 * instant feedback without a loading state — important for the filter UX.
 *
 * WHO USES IT: app/(app)/instruments/[entityId]/page.tsx (News tab)
 * DATA SOURCE: S9 GET /v1/news/entity/{entityId} → RankedArticle[]
 * DESIGN REFERENCE: PRD-0050 Wave E §T-E-5-03
 */

"use client";
// WHY "use client": uses useQuery for data fetching + useState for filter controls.

import { useState, useMemo, useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { useRouter, useParams } from "next/navigation";
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { Skeleton } from "@/components/ui/skeleton";
import { InlineEmptyState } from "@/components/data/InlineEmptyState";
import { ClusterArticlesModal } from "@/components/news/ClusterArticlesModal";
import { formatRelativeTime, cn, safeExternalUrl } from "@/lib/utils";
import { ExternalLink } from "lucide-react";
import type { RankedArticle } from "@/types/api";

// ── Props ─────────────────────────────────────────────────────────────────────

interface NewsTabProps {
  /** KG entity_id for this instrument — used to fetch entity-scoped articles. */
  entityId: string;
}

// ── Sort options ──────────────────────────────────────────────────────────────

type SortKey = "relevance" | "impact" | "time";

/** Maps the dropdown value to a human label. */
const SORT_LABELS: Record<SortKey, string> = {
  relevance: "Relevance",
  impact: "Impact",
  time: "Newest",
};

// ── Sentiment pill config ─────────────────────────────────────────────────────
// WHY Midnight Pro palette: positive=#26A69A (teal), negative=#EF5350 (red),
// neutral=#787B86 (muted), mixed=#F59E0B (amber) — per PLAN-0050 design spec.
// Using inline hex in style={{ color }} because Tailwind's JIT doesn't guarantee
// the exact Midnight Pro values are in the generated CSS unless used in a component
// that was previously compiled. The CSS vars approach (text-[hsl(var(--positive))])
// is safer when CSS vars are defined — see globals.css for --positive / --negative.

const SENTIMENT_CONFIG: Record<
  NonNullable<RankedArticle["sentiment"]>,
  { label: string; className: string; bgClass: string }
> = {
  positive: {
    label: "POS",
    // WHY text-positive: uses CSS var --positive which maps to #26A69A in globals.css
    className: "text-positive",
    bgClass: "bg-positive/15",
  },
  negative: {
    label: "NEG",
    className: "text-negative",
    bgClass: "bg-negative/15",
  },
  neutral: {
    label: "NEU",
    // WHY text-muted-foreground: neutral sentiment is visually subdued (#787B86)
    className: "text-muted-foreground",
    bgClass: "bg-muted",
  },
  mixed: {
    label: "MIX",
    // WHY text-warning: mixed sentiment uses amber (#F59E0B) — caution color
    className: "text-warning",
    bgClass: "bg-warning/15",
  },
};

// ── Time-grouping helpers ─────────────────────────────────────────────────────

type TimeGroup = "TODAY" | "PAST 3 DAYS" | "PAST WEEK" | "OLDER";

/** Categorise an article's published_at into a display group. */
function getTimeGroup(publishedAt: string | null): TimeGroup {
  if (!publishedAt) return "OLDER";
  const ageMs = Date.now() - new Date(publishedAt).getTime();
  const DAY_MS = 24 * 60 * 60 * 1000;
  if (ageMs < DAY_MS) return "TODAY";
  if (ageMs < 3 * DAY_MS) return "PAST 3 DAYS";
  if (ageMs < 7 * DAY_MS) return "PAST WEEK";
  return "OLDER";
}

/** Ordered list of time groups for consistent header rendering. */
const TIME_GROUP_ORDER: TimeGroup[] = ["TODAY", "PAST 3 DAYS", "PAST WEEK", "OLDER"];

// ── Source monogram ───────────────────────────────────────────────────────────

/**
 * Curated domain-to-monogram map for well-known financial publishers.
 *
 * WHY curated map (not just first-2-letters): domain stems produce poor results
 * for many outlets. "bloomberg.com" → "BL" is wrong; the brand abbreviation is
 * "BB". The map covers the top publishers found in S6's source_name field.
 * Any domain NOT in the map falls back to first-2-letters of the domain stem.
 */
const DOMAIN_MONOGRAM_MAP: Record<string, string> = {
  "bloomberg.com": "BB",
  "reuters.com": "RE",
  "wsj.com": "WJ",
  "ft.com": "FT",
  "cnbc.com": "CN",
  "seekingalpha.com": "SA",
  "marketwatch.com": "MW",
  "barrons.com": "BA",
  "businessinsider.com": "BI",
  "nytimes.com": "NY",
  "techcrunch.com": "TC",
  "theguardian.com": "GD",
  "forbes.com": "FB",
  "fortune.com": "FU",
  "economist.com": "EC",
};

/**
 * getSourceMonogram — derive a 2-letter monogram from an article URL.
 *
 * WHY from URL (not source_name): source_name is free-text from EODHD which
 * varies ("Bloomberg L.P.", "Bloomberg", "Bloomberg News"). The domain is
 * canonical and stable. We parse the hostname, strip "www.", and check the
 * curated map first; unknown domains get the first 2 letters of the stem.
 *
 * Examples:
 *   "https://www.bloomberg.com/…" → "BB"  (curated)
 *   "https://rare-publisher.com/…" → "RA"  (stem fallback)
 */
function getSourceMonogram(url: string | null | undefined): string {
  if (!url) return "??";
  try {
    const hostname = new URL(url).hostname.replace(/^www\./, "");
    if (DOMAIN_MONOGRAM_MAP[hostname]) {
      return DOMAIN_MONOGRAM_MAP[hostname];
    }
    // Fallback: take first 2 chars of the domain stem (part before first ".")
    // WHY split("-")[0] — "rare-publisher.com" splits on "." → "rare-publisher";
    // we use the first 2 chars of the FULL stem (including hyphens) to match
    // the test expectation: "rare-publisher.com" → "RA".
    const stem = hostname.split(".")[0];
    return stem.slice(0, 2).toUpperCase();
  } catch {
    return "??";
  }
}

// ── Narrative chips ───────────────────────────────────────────────────────────

/**
 * Narrative chip definitions — keyword groups that map to a chip label.
 *
 * WHY keyword detection on title (not body): S9 returns truncated articles;
 * the title is always present. Keyword detection on the title is fast
 * (client-side) and produces useful chips without additional S9 calls.
 *
 * WHY case-insensitive regex: title casing varies by outlet
 * ("Earnings beat" vs "EARNINGS BEAT").
 */
const NARRATIVE_CHIPS: Array<{ pattern: RegExp; label: string }> = [
  // EARNINGS: "earnings", "EPS", "beat", "miss" in earnings context
  { pattern: /\bearnings\b|\beps\b/i, label: "EARNINGS" },
  // M&A: "acqui" covers acquire/acquisition; "merger" covers merger/mergers
  { pattern: /\bacqui|\bmerger\b|\bm&a\b/i, label: "M&A" },
  // GUIDANCE: forward-looking statements
  { pattern: /\bguidance\b|\boutlook\b|\bforecast\b/i, label: "GUIDANCE" },
  // MACRO: central bank / rates / economic data
  { pattern: /\bfed\b|\binterest rate|\binflation\b|\bgdp\b|\bcpi\b/i, label: "MACRO" },
  // REGULATORY: antitrust, SEC, regulatory scrutiny
  { pattern: /\bregulat|\bantitrust\b|\bsec\b|\bfda\b/i, label: "REG" },
];

/**
 * getNarrativeChips — derive applicable chip labels from an article title.
 *
 * Returns a deduplicated list of chip labels (e.g., ["EARNINGS"]) based
 * on which NARRATIVE_CHIPS patterns match the title.
 */
function getNarrativeChips(title: string | null | undefined): string[] {
  if (!title) return [];
  return NARRATIVE_CHIPS
    .filter(({ pattern }) => pattern.test(title))
    .map(({ label }) => label);
}

// ── Relevance badge ───────────────────────────────────────────────────────────

/**
 * RelevanceBadge — gradient amber→green badge based on display_relevance_score.
 *
 * WHY gradient (not fixed colour): display_relevance_score is a continuous 0-1
 * signal. A fixed colour wastes that information. A smooth gradient from amber (low
 * relevance) to green (high relevance) lets analysts instantly assess article quality
 * while scanning a list of 20 articles.
 *
 * Thresholds:
 *   ≥ 0.70 → positive (teal/green) — high market-relevant signal
 *   ≥ 0.40 → warning (amber) — moderate signal
 *   < 0.40 → muted — low signal (routing-only or LIGHT-tier article)
 */
function RelevanceBadge({ score }: { score: number }) {
  const className = cn(
    // WHY font-mono tabular-nums: numeric scores should align when stacked in a list
    "shrink-0 rounded-[2px] px-1.5 py-0.5 font-mono text-[9px] tabular-nums font-semibold",
    score >= 0.70
      ? "bg-positive/15 text-positive"
      : score >= 0.40
        ? "bg-warning/15 text-warning"
        : "bg-muted text-muted-foreground",
  );
  // WHY multiply ×100 + toFixed(0): display as integer percentage (e.g., "74" not "0.74")
  return (
    <span className={className} aria-label="relevance score">
      {(score * 100).toFixed(0)}
    </span>
  );
}

// ── Sentiment pill ────────────────────────────────────────────────────────────

/**
 * SentimentPill — compact pill for article sentiment classification.
 *
 * WHY 3-character labels (POS/NEG/NEU/MIX): saves horizontal space in the
 * article row. "positive" at 8 chars would push the impact pill off-screen on
 * narrow viewports. "POS" at 3 chars is readable for domain experts.
 */
function SentimentPill({ sentiment }: { sentiment: NonNullable<RankedArticle["sentiment"]> }) {
  const config = SENTIMENT_CONFIG[sentiment];
  return (
    <span
      className={cn(
        "shrink-0 rounded-[2px] px-1.5 py-0.5 font-mono text-[9px] font-semibold uppercase",
        config.bgClass,
        config.className,
      )}
      aria-label={`sentiment ${sentiment}`}
    >
      {config.label}
    </span>
  );
}

// ── Impact pill ───────────────────────────────────────────────────────────────

/**
 * ImpactPill — shows impact_score (0-1) with a colour intensity gradient.
 *
 * WHY SEPARATE from relevance badge: impact_score comes from price-window data
 * (how much the stock actually moved) while display_relevance_score is the
 * composite weighted signal. Both are useful independently:
 *   - High relevance + low impact: article was expected to matter but didn't move the price yet.
 *   - Low relevance + high impact: unexpected price move — potential noise or outlier signal.
 *
 * Thresholds mirror relevance badge for visual consistency:
 *   ≥ 0.70 → positive (strong price move: > 3.5% of the 5% cap)
 *   ≥ 0.40 → warning (moderate move: 2–3.5%)
 *   < 0.40 → muted (minor move or pre-25h article)
 */
function ImpactPill({ score }: { score: number }) {
  const className = cn(
    "shrink-0 rounded-[2px] px-1.5 py-0.5 font-mono text-[9px] tabular-nums font-semibold",
    score >= 0.70
      ? "bg-positive/10 text-positive"
      : score >= 0.40
        ? "bg-warning/10 text-warning"
        : "bg-muted/80 text-muted-foreground",
  );
  return (
    <span className={className} aria-label="impact score">
      {/* WHY Δ prefix: the delta symbol signals "price movement" to finance users. */}
      Δ{(score * 100).toFixed(0)}
    </span>
  );
}

// ── ArticleRow ────────────────────────────────────────────────────────────────

/**
 * ArticleRow — full article card with all Wave E pills.
 *
 * Layout:
 *   [relevance badge] [sentiment pill] [impact pill]  · · · · · · [time]
 *   [title — external link, 2-line clamp]
 *   [monogram] [source name] [narrative chips] [primary entity chip]
 *
 * WHY 3-row layout (not compact 22px InstrumentTopNews row): the News tab has
 * full vertical space and analysts want more context per article than the
 * Overview panel's scannable 22px row.
 *
 * WHY monogram (T-E-5-05): a 2-letter badge gives analysts an instant visual
 * anchor to source without reading the full name. Pattern from financial
 * terminals (Bloomberg uses "BN" for Bloomberg News headers).
 *
 * WHY narrative chips (T-E-5-05): keyword-detected chips (EARNINGS, M&A, etc.)
 * allow analysts to scan a list and filter by event type at a glance — faster
 * than reading titles when looking for earnings articles.
 */
function ArticleRow({
  article,
  onEntityClick,
  onClusterClick,
}: {
  article: RankedArticle;
  onEntityClick: (entityId: string) => void;
  // P2-F: called with cluster_id when the user clicks the "+N similar" chip.
  // Optional — chip is not rendered when cluster_size <= 1 or cluster_id is null.
  onClusterClick?: (clusterId: string) => void;
}) {
  // Derive monogram and narrative chips from article data.
  // WHY computed inside ArticleRow (not in the parent useMemo): narrative chips
  // are article-specific and only needed during rendering; computing them here
  // avoids polluting the sorted/filtered array shapes.
  const monogram = getSourceMonogram(article.url);
  const narrativeChips = getNarrativeChips(article.title);

  return (
    <article
      className={cn(
        // WHY py-1.5 (was py-2): NewsTab lives inside the instrument detail page
        // where vertical space is constrained. 6px vert padding (up from 8px) gives
        // ~2px back per row without losing readability on 11px text.
        "border-b border-border/30 px-3 py-1.5 hover:bg-muted/30 transition-colors",
        // WHY opacity-60 for LIGHT tier: LIGHT articles are low-signal;
        // de-emphasising them lets analysts focus on MEDIUM/DEEP articles.
        article.routing_tier === "LIGHT" && "opacity-60",
      )}
    >
      {/* ── Row 1: pills + timestamp ─────────────────────────────────────── */}
      <div className="mb-0.5 flex items-center gap-1.5">
        {/* Relevance badge — always shown when score is available */}
        {article.display_relevance_score != null && (
          <RelevanceBadge score={article.display_relevance_score} />
        )}

        {/* Sentiment pill — shown only when scored (not null) */}
        {article.sentiment != null && (
          <SentimentPill sentiment={article.sentiment} />
        )}

        {/* Impact pill — shown only when price windows have been computed */}
        {article.impact_score != null && (
          <ImpactPill score={article.impact_score} />
        )}

        {/* Spacer: push timestamp to the right */}
        <span className="flex-1" />

        {/* Relative published time */}
        <time
          dateTime={article.published_at ?? undefined}
          className="font-mono text-[10px] tabular-nums text-muted-foreground shrink-0"
        >
          {formatRelativeTime(article.published_at)}
        </time>
      </div>

      {/* ── Row 2: article title (external link) ────────────────────────── */}
      {/* WHY group class: enables group-hover on the external link icon */}
      <a
        href={safeExternalUrl(article.url)}
        target="_blank"
        rel="noopener noreferrer"
        // WHY text-[11px] (was 13px): NewsTab is an instrument-detail sub-panel;
        // using the same 11px data text density as other instrument panels (OHLCV,
        // fundamentals) keeps the tab visually consistent and maximises rows shown.
        className="group mb-0.5 block text-[11px] font-medium leading-snug text-foreground hover:text-primary transition-colors"
        aria-label={article.title ?? "Untitled article"}
      >
        <span className="flex items-start gap-1">
          <span className="line-clamp-2 flex-1">{article.title ?? "Untitled"}</span>
          {/* External link icon — fades in on hover */}
          <ExternalLink
            className="mt-0.5 h-3 w-3 shrink-0 text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100"
            aria-hidden="true"
          />
        </span>
      </a>

      {/* ── Row 3: monogram + source name + narrative chips + entity chip ── */}
      <div className="flex items-center gap-2 flex-wrap">
        {/* Source monogram badge — 2-letter abbreviation for the publisher.
            WHY aria-label="Source: {source_name}": screen readers announce
            the full name; sighted users see the compact monogram. The test
            asserts getByLabelText("Source: Bloomberg").toHaveTextContent("BB").
            WHY monogram always renders (even without source_name): the URL
            always provides a domain to derive the monogram from. */}
        <span
          aria-label={`Source: ${article.source_name ?? "Unknown"}`}
          className={cn(
            "shrink-0 rounded-[2px] px-1.5 py-0.5 font-mono text-[9px] font-bold",
            "bg-muted/60 text-muted-foreground border border-border/40",
            // WHY uppercase: monograms are conventionally uppercase (BB, RE, FT)
            "uppercase tracking-widest",
          )}
        >
          {monogram}
        </span>

        {/* Source name — the outlet that published this article */}
        {article.source_name && (
          <span className="text-[10px] uppercase tracking-wider text-muted-foreground">
            {article.source_name}
          </span>
        )}

        {/* Narrative chips — keyword-detected event type badges.
            WHY these chips (not manual tagging): S9 doesn't provide event-type
            classification for articles. Client-side keyword detection on the
            title is fast (~0ms) and produces high-precision chips for the most
            common event types (earnings, M&A, guidance, macro, regulatory). */}
        {narrativeChips.map((chip) => (
          <span
            key={chip}
            className={cn(
              "shrink-0 rounded-[2px] px-1.5 py-0.5 font-mono text-[9px] font-semibold",
              // WHY distinct colour per chip family: EARNINGS=amber (financial event),
              // M&A=purple (corporate action), GUIDANCE=blue, MACRO=slate, REG=red.
              // Using bg-primary/15 + text-primary as a unified accent for Wave E
              // to avoid adding many new CSS vars; can be colour-coded per chip in Wave F.
              "bg-primary/15 text-primary",
            )}
          >
            {chip}
          </span>
        ))}

        {/* Entity chip — clickable → instrument page for the primary entity.
            WHY primary_entity_symbol (not primary_entity_id for the label):
            entity_id is a UUID — not human-readable. The ticker symbol (e.g., "AAPL")
            is the canonical display in a financial terminal.
            WHY onClick for navigation: we use router.push so the user stays in the
            Next.js SPA (no full page reload). */}
        {article.primary_entity_symbol && article.primary_entity_id && (
          <button
            onClick={() => onEntityClick(article.primary_entity_id!)}
            className={cn(
              "rounded-[2px] border border-border/50 bg-muted/30 px-1.5 py-0.5",
              "font-mono text-[10px] tabular-nums text-foreground",
              "hover:border-primary/50 hover:text-primary transition-colors",
            )}
            aria-label={`Navigate to ${article.primary_entity_symbol} instrument page`}
          >
            {article.primary_entity_symbol}
          </button>
        )}

        {/* Cluster-size chip — "+N similar" button for near-duplicate corroboration.
            WHY only cluster_size > 1 and cluster_id: cluster_size=1 = no siblings.
            WHY muted style (not primary): this is informational metadata, not
            an actionable signal like the entity chip or narrative chips.
            P2-F: changed from <span> to <button> — clicking opens the
            ClusterArticlesModal sheet. */}
        {article.cluster_size != null && article.cluster_size > 1 && article.cluster_id && (
          <button
            type="button"
            className={cn(
              "shrink-0 rounded-[2px] px-1.5 py-0.5 font-mono text-[9px] tabular-nums",
              "bg-muted/50 text-muted-foreground border border-border/30",
              // WHY cursor-pointer + hover: now interactive, signals clickability.
              "cursor-pointer hover:bg-muted/80 hover:text-foreground transition-colors",
              "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-primary/60",
            )}
            title={`${article.cluster_size - 1} similar article${article.cluster_size - 1 !== 1 ? "s" : ""} detected — click to view`}
            onClick={() => {
              if (article.cluster_id) onClusterClick?.(article.cluster_id);
            }}
            aria-label={`View ${article.cluster_size - 1} similar article${article.cluster_size - 1 !== 1 ? "s" : ""}`}
          >
            +{article.cluster_size - 1} similar
          </button>
        )}
      </div>
    </article>
  );
}

// ── TimeGroupHeader ───────────────────────────────────────────────────────────

/**
 * TimeGroupHeader — sticky section divider showing the time bucket label.
 *
 * WHY sticky (not static): as users scroll a long news list, the group header
 * tells them which time period they're currently in without scrolling back up.
 * WHY top-0: sticks to the top of the overflow-auto container inside the tab.
 */
function TimeGroupHeader({ label }: { label: TimeGroup }) {
  return (
    <div className="sticky top-0 z-10 border-b border-border/40 bg-background/95 px-3 py-0.5 backdrop-blur-sm">
      <span className="text-[9px] font-semibold uppercase tracking-[0.1em] text-muted-foreground">
        {label}
      </span>
    </div>
  );
}

// ── NewsTab component ─────────────────────────────────────────────────────────

const NEWS_PAGE_SIZE = 20;

export function NewsTab({ entityId }: NewsTabProps) {
  const { accessToken } = useAuth();
  const router = useRouter();

  // WHY useParams: the News tab needs instrumentId to build the per-instrument
  // sessionStorage key ("news-filters-{instrumentId}"). The component only
  // receives entityId as a prop (it's the KG entity ID used for the news query).
  // instrumentId comes from the route param via useParams so we can build the
  // correct storage key without threading an extra prop through the page.
  const params = useParams();
  const instrumentId = typeof params?.instrumentId === "string" ? params.instrumentId : null;

  // ── SessionStorage key ─────────────────────────────────────────────────────
  // WHY per-instrument key (not shared "news-filters"): each instrument page
  // should remember the last filter the analyst used for THAT instrument,
  // not a global filter that would override the choice for every instrument.
  const storageKey = instrumentId ? `news-filters-${instrumentId}` : null;

  // ── Pagination state ───────────────────────────────────────────────────────
  const [newsOffset, setNewsOffset] = useState(0);

  // ── Filter + sort state — initialised from sessionStorage if present ───────
  // WHY lazy initialiser for useState (function form): we read sessionStorage
  // exactly once at mount time. The function form prevents re-reading on every
  // render. If sessionStorage has no entry, defaults are "all" / "relevance".
  const [sourceFilter, setSourceFilter] = useState<string>(() => {
    if (!storageKey || typeof window === "undefined") return "all";
    try {
      const raw = window.sessionStorage.getItem(storageKey);
      if (!raw) return "all";
      const parsed = JSON.parse(raw) as { sourceFilter?: string; sortKey?: string };
      return parsed.sourceFilter ?? "all";
    } catch {
      return "all";
    }
  });

  const [sortKey, setSortKey] = useState<SortKey>(() => {
    if (!storageKey || typeof window === "undefined") return "relevance";
    try {
      const raw = window.sessionStorage.getItem(storageKey);
      if (!raw) return "relevance";
      const parsed = JSON.parse(raw) as { sourceFilter?: string; sortKey?: string };
      const sk = parsed.sortKey;
      // WHY type guard: JSON.parse returns unknown; guard to valid SortKey values.
      if (sk === "relevance" || sk === "impact" || sk === "time") return sk;
      return "relevance";
    } catch {
      return "relevance";
    }
  });

  // ── Persist filter state to sessionStorage on change ──────────────────────
  // WHY useEffect (not inline in the onChange handlers): both sourceFilter and
  // sortKey changes should write to sessionStorage together so the stored object
  // is always the full current state, not a partial update from one field.
  useEffect(() => {
    if (!storageKey || typeof window === "undefined") return;
    try {
      window.sessionStorage.setItem(
        storageKey,
        JSON.stringify({ sourceFilter, sortKey }),
      );
    } catch {
      // WHY silent catch: sessionStorage may be unavailable in private browsing
      // or quota-exceeded. Filter persistence is a UX enhancement, not critical.
    }
  }, [storageKey, sourceFilter, sortKey]);

  // ── Data fetch ─────────────────────────────────────────────────────────────
  const { data: newsResp, isLoading, isError } = useQuery({
    queryKey: ["entity-news-tab", entityId, newsOffset],
    queryFn: () =>
      createGateway(accessToken).getEntityNews(entityId, {
        limit: NEWS_PAGE_SIZE,
        offset: newsOffset,
        // WHY display_relevance_score: S6 endpoint sorts by this composite signal;
        // we'll re-sort client-side anyway to support impact/time sort keys.
        order_by: "display_relevance_score",
      }),
    enabled: !!accessToken && !!entityId,
    staleTime: 2 * 60_000,
  });

  // WHY useMemo for articles: newsResp?.articles ?? [] creates a new array reference
  // on every render (the nullish-coalescing fallback [] is a new literal each call).
  // Downstream useMemos that depend on [articles] would re-run every render even
  // if the data hasn't changed. Memoising here breaks the reference churn.
  const articles = useMemo(() => newsResp?.articles ?? [], [newsResp]);

  // ── Derive unique source names for the source filter dropdown ─────────────
  // WHY useMemo: avoids recomputing on every render when only sort/filter changes.
  const sourceNames = useMemo(() => {
    const names = new Set<string>();
    for (const a of articles) {
      if (a.source_name) names.add(a.source_name);
    }
    return Array.from(names).sort();
  }, [articles]);

  // ── Apply source filter ────────────────────────────────────────────────────
  const filtered = useMemo(
    () =>
      sourceFilter === "all"
        ? articles
        : articles.filter((a) => a.source_name === sourceFilter),
    [articles, sourceFilter],
  );

  // ── Apply sort ─────────────────────────────────────────────────────────────
  const sorted = useMemo(() => {
    const copy = [...filtered];
    if (sortKey === "relevance") {
      // WHY nullsLast: articles without a relevance score (routing-only) sink to bottom
      copy.sort((a, b) => (b.display_relevance_score ?? 0) - (a.display_relevance_score ?? 0));
    } else if (sortKey === "impact") {
      // WHY nullsLast: articles without price windows (< 25h old) sink to bottom
      copy.sort((a, b) => (b.impact_score ?? -1) - (a.impact_score ?? -1));
    } else {
      // time: newest first; null published_at sinks to bottom
      copy.sort((a, b) => {
        const ta = a.published_at ? new Date(a.published_at).getTime() : 0;
        const tb = b.published_at ? new Date(b.published_at).getTime() : 0;
        return tb - ta;
      });
    }
    return copy;
  }, [filtered, sortKey]);

  // ── Group by time period ───────────────────────────────────────────────────
  // WHY Map (not object): preserves insertion order of keys, which we rely on
  // when iterating TIME_GROUP_ORDER to render headers in chronological order.
  const grouped = useMemo(() => {
    const map = new Map<TimeGroup, RankedArticle[]>();
    for (const group of TIME_GROUP_ORDER) map.set(group, []);
    for (const a of sorted) {
      const group = getTimeGroup(a.published_at);
      map.get(group)!.push(a);
    }
    return map;
  }, [sorted]);

  // P2-F: cluster modal — null = closed; non-null = open with that cluster_id.
  // WHY defined here (not in ArticleCard): the modal needs to be mounted outside
  // the scrollable news list so the Sheet portal can overlay the full tab panel.
  const [clusterModalId, setClusterModalId] = useState<string | null>(null);

  // ── Navigate to entity instrument page ─────────────────────────────────────
  // WHY separate handler (not inline): makes the intent explicit and prevents
  // the JSX from becoming too verbose with routing logic inline.
  function handleEntityClick(entityId: string) {
    router.push(`/instruments/${encodeURIComponent(entityId)}`);
  }

  // ── Render ─────────────────────────────────────────────────────────────────

  return (
    <>
    {/* P2-F: ClusterArticlesModal — mounted outside the scrollable list so the
        Sheet portal can overlay the full tab panel without being clipped. */}
    <ClusterArticlesModal
      clusterId={clusterModalId}
      onClose={() => setClusterModalId(null)}
    />
    <div className="flex flex-col">

      {/* ── Filter + sort toolbar ─────────────────────────────────────────── */}
      {/* WHY h-9 (not p-2): compact terminal controls — exact 36px height.
          T-F-6-13 (news date filter ARIA label): no date-range filter control
          was added in Wave E — the current toolbar contains only a source filter
          and a sort dropdown. Both have appropriate aria-label attributes.
          Finding closed: date filter is a deferred UX enhancement (no D-ticket
          exists for it yet). The existing controls already meet ARIA standards. */}
      <div className="flex items-center gap-2 border-b border-border px-3 h-9 shrink-0">

        {/* Source filter dropdown — lists unique source_name values */}
        <select
          value={sourceFilter}
          onChange={(e) => setSourceFilter(e.target.value)}
          className={cn(
            "h-7 bg-background border border-border rounded-[2px]",
            "text-[11px] font-mono px-2 text-foreground",
            // WHY focus:outline-none + focus:ring: removes browser default outline,
            // replaces with our ring so it fits the terminal design system.
            "focus:outline-none focus:ring-1 focus:ring-primary/50",
          )}
          aria-label="Filter articles by source"
        >
          <option value="all">All sources</option>
          {sourceNames.map((name) => (
            <option key={name} value={name}>
              {name}
            </option>
          ))}
        </select>

        {/* Sort dropdown */}
        <select
          value={sortKey}
          onChange={(e) => setSortKey(e.target.value as SortKey)}
          className={cn(
            "h-7 bg-background border border-border rounded-[2px]",
            "text-[11px] font-mono px-2 text-foreground",
            "focus:outline-none focus:ring-1 focus:ring-primary/50",
          )}
          aria-label="Sort articles"
        >
          {(Object.keys(SORT_LABELS) as SortKey[]).map((key) => (
            <option key={key} value={key}>
              Sort: {SORT_LABELS[key]}
            </option>
          ))}
        </select>

        {/* Article count — always visible, reflects filtered count */}
        <span
          className="font-mono text-[10px] tabular-nums text-muted-foreground ml-auto"
          aria-live="polite"
        >
          {sorted.length} articles
        </span>
      </div>

      {/* ── Loading state ─────────────────────────────────────────────────── */}
      {isLoading && !newsResp && (
        <div>
          {Array.from({ length: 5 }).map((_, i) => (
            <div key={i} className="px-3 py-2 border-b border-border/30">
              {/* WHY 3 skeleton rows: mirrors the 3-row ArticleRow layout */}
              <div className="mb-1 flex items-center gap-1.5">
                <Skeleton className="h-3 w-6" />
                <Skeleton className="h-3 w-8" />
                <span className="flex-1" />
                <Skeleton className="h-3 w-12" />
              </div>
              <Skeleton className="mb-1 h-4 w-3/4" />
              <Skeleton className="h-3 w-1/3" />
            </div>
          ))}
        </div>
      )}

      {/* ── Error state ───────────────────────────────────────────────────── */}
      {isError && !isLoading && (
        <InlineEmptyState
          message="Failed to load news. Please try again."
          className="px-3"
        />
      )}

      {/* ── Empty state: no articles after filter ─────────────────────────── */}
      {!isLoading && !isError && sorted.length === 0 && (
        <InlineEmptyState
          message={
            sourceFilter !== "all"
              ? `No ${sourceFilter} articles for this entity.`
              : "No news articles available for this entity."
          }
          className="px-3"
        />
      )}

      {/* ── Article list grouped by time period ──────────────────────────── */}
      {!isLoading && !isError && sorted.length > 0 && (
        <div>
          {TIME_GROUP_ORDER.map((group) => {
            const groupArticles = grouped.get(group) ?? [];
            // WHY skip empty groups (not render empty header): showing "OLDER" with no
            // articles beneath it is confusing — skip the header when the group is empty.
            if (groupArticles.length === 0) return null;
            return (
              <div key={group}>
                <TimeGroupHeader label={group} />
                {groupArticles.map((article) => (
                  <ArticleRow
                    key={article.article_id}
                    article={article}
                    onEntityClick={handleEntityClick}
                    // P2-F: wire cluster chip → modal
                    onClusterClick={setClusterModalId}
                  />
                ))}
              </div>
            );
          })}

          {/* ── Load more pagination ────────────────────────────────────── */}
          {newsResp && newsOffset + NEWS_PAGE_SIZE < newsResp.total && (
            <div className="flex justify-center px-3 py-2">
              <button
                onClick={() => setNewsOffset((o) => o + NEWS_PAGE_SIZE)}
                className={cn(
                  "rounded-[2px] border border-border/50 px-3 py-1",
                  "text-[11px] text-muted-foreground hover:border-border hover:text-foreground",
                  "transition-colors",
                )}
              >
                Load more articles
              </button>
            </div>
          )}
        </div>
      )}
    </div>
    </>
  );
}
