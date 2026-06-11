/**
 * features/chat/components/ChatContextRail.tsx — Right-side 320px context rail
 * for the Chat page.
 *
 * WHY THIS EXISTS:
 * Research sessions benefit from a persistent ambient panel that shows _what
 * the conversation is about_ without requiring the analyst to scroll back
 * through the log: which entities are in play (with live quotes), what
 * sources ground the answers, whether the AI found contradictory claims, and
 * which platform tools produced the answers.
 *
 * WAVE-2 REWORK (frontend-rework sprint — "the rail must carry the value"):
 *   1. ENTITY OVERVIEW cards now fetch via the Wave-1 backend endpoint
 *      GET /v1/companies/by-ticker/{ticker}/overview — ONE request per ticker
 *      (replaces the searchInstruments → getCompanyOverview two-step), and
 *      render a 5-day sparkline from the ohlcv bars the overview already
 *      includes (zero extra requests).
 *   2. CONVERSATION SOURCES replaces the old "Recent Citations" — citations
 *      aggregated across the WHOLE conversation, deduped by source document,
 *      each row showing source badge / title / reference count, clicking
 *      opens the source URL in a new tab. The rail becomes the session's
 *      running bibliography.
 *   3. TOOLS USED — which platform tools answered (from tool_result SSE
 *      events incl. the new server-measured duration_ms): one row per tool
 *      with invocation count + average latency, linking to the ?debug=1
 *      tool-trace drawer for the full per-call record.
 *   4. Named cold state — an empty conversation shows "Context appears as
 *      you chat" instead of a wall of empty section headers.
 *
 * WHY RIGHT RAIL (not a popover or bottom sheet):
 * Bloomberg Terminal places related context panels to the right of the
 * primary content surface. A persistent fixed-width rail is always in the
 * same spot — the analyst's eye can glance without hunting.
 *
 * WHY 320px:
 * Fits citation titles at 10px mono without truncation for 90% of article
 * titles (≤50 chars), while leaving ≥600px for the message column even on
 * a 1280px screen (1280 - 224 sidebar - 320 rail = 736px messages).
 *
 * DATA FLOW:
 *   Entity card    — TanStack Query via getCompanyOverview (entityId param).
 *   Mini-cards     — TanStack Query via getCompanyOverviewByTicker (1 req).
 *   Sources        — pure derivation from `messages` (conversation-derive.ts).
 *   Tools used     — pure derivation from `toolUsage` (conversation-derive.ts);
 *                    samples accumulated by useChatStream across turns.
 *   Contradictions — pure derivation from `messages.content` regex scan.
 *   Related tickers — shared `extractTickers` lib.
 *
 * WHO USES IT: app/(app)/chat/page.tsx
 * DESIGN REFERENCE: frontend-rework Wave-2 task spec §2 (context rail value)
 */

"use client";
// WHY "use client": uses useQuery (TanStack), formatters, and passes a
// callback to the parent. All require a browser execution context.

import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { X, AlertTriangle, PanelRight } from "lucide-react";

import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { qk } from "@/lib/query/keys";
import { cn } from "@/lib/utils";
import { formatPrice, formatPercent, formatMarketCap, formatRatio } from "@/lib/utils";
import { Skeleton } from "@/components/ui/skeleton";
// Wave 2: shared trend-tinted mini-chart — same primitive the watchlist /
// holdings / top-movers rows use, so the rail's sparklines read identically
// to every other 5-day trend on the platform.
import { Sparkline } from "@/components/primitives/Sparkline";
// Wave 2: named cold state for the empty conversation (DS §15.12) — copy key
// chat.rail-empty ("Context appears as you chat").
import { EmptyState } from "@/components/primitives/EmptyState";
import type { Message } from "@/types/api";
// Round 2 Enhancement: single source of truth for ticker detection.
import { extractTickers } from "@/features/chat/lib/ticker-extract";
// Wave 2: conversation-level aggregations (sources bibliography + tool
// usage summary) — pure, table-tested derivations.
import {
  DEFAULT_SOURCE_CAP,
  aggregateConversationSources,
  summarizeToolUsage,
} from "@/features/chat/lib/conversation-derive";
import type { ToolUsageSample } from "@/features/chat/lib/types";

// ── Types ─────────────────────────────────────────────────────────────────────

export interface ChatContextRailProps {
  /** UUID from ?entity_id= URL param, or null when no entity context is set. */
  entityId: string | null;
  /**
   * All messages for the current thread (both user + assistant).
   * Used to derive sources, contradictions, and related tickers.
   * Empty array when the thread hasn't loaded yet.
   */
  messages: Message[];
  /**
   * Completed tool invocations across the conversation (Wave 2 — from
   * useChatStream.toolUsage). Drives the TOOLS USED section. Optional so
   * legacy compositions (and most tests) compile unchanged; absent ⇒ the
   * section simply never renders.
   */
  toolUsage?: ToolUsageSample[];
  /**
   * Whether the rail is collapsed. When true the PARENT hides the wrapper
   * div (width → 0). This prop drives the collapse icon state only.
   */
  isCollapsed: boolean;
  /** Called when the user clicks the × button to collapse the rail. */
  onClose: () => void;
  /**
   * Called when the user clicks a related ticker chip.
   * Intended to append " $TICKER" to the chat composer.
   */
  onTickerClick: (ticker: string) => void;
  /**
   * Called when the user clicks an Entity Overview mini-card (Round 2).
   * The page wires this to `router.push("/instruments/<ticker>")` so a card
   * click pivots straight to the instrument detail page.
   *
   * WHY a callback (not a router.push inside this component): keeps the rail
   * free of next/navigation so it stays trivially unit-testable.
   *
   * Optional: when omitted, cards render as static info surfaces.
   */
  onCardClick?: (ticker: string) => void;
  /**
   * Whether ?debug=1 is active (Wave 2 — Tools Used footer). When true the
   * footer reminds the analyst the ⌘D chord opens the per-call trace; when
   * false it links to `debugHref` to enable the trace surface.
   */
  isDebug?: boolean;
  /**
   * Pre-built href that re-opens the CURRENT view with ?debug=1 appended
   * (the page owns URL construction — the rail stays next/navigation-free).
   * Absent ⇒ the enable-trace link is not rendered.
   */
  debugHref?: string;
}

// ── Source type badge labels ──────────────────────────────────────────────────
// WHY hard-coded map (not computed): the 4 badge labels match the spec exactly.
// Anything outside the known set falls back to a 4-char uppercase slice so the
// badge always shows.
const SOURCE_BADGE_MAP: Record<string, string> = {
  sec: "SEC",
  earnings: "EARN",
  earn: "EARN",
  news: "NEWS",
  eodhd_news: "NEWS",
  knowledge_graph: "KG",
  kg: "KG",
};

/** Derive a 2–4 char badge label from a raw source string. */
function sourceBadge(source: string): string {
  const key = source.toLowerCase().replace(/[^a-z_]/g, "");
  return SOURCE_BADGE_MAP[key] ?? source.slice(0, 4).toUpperCase();
}

// ── Contradiction extraction ──────────────────────────────────────────────────
// WHY regex extraction (not a structured field):
// The Message type does not carry a `contradictions` field today. S8 emits
// contradiction notices inline in the assistant response text when
// `get_contradictions` returns results. The pattern is:
//   "⚠ <claim A> vs <claim B>"   OR   "Contradiction: <claim A> — <claim B>"
// We fish for these patterns to surface them in the rail. False positives are
// low-risk: the worst case is showing an extra warning chip the analyst can
// ignore. False negatives are also acceptable — this is "best effort" ambient
// context, not a gate.
const CONTRADICTION_RE =
  /(?:⚠\s*|contradiction:\s*)([^.\n]{10,120})/gi;

/** Extract brief contradiction snippets from assistant message content. */
function extractContradictions(messages: Message[]): string[] {
  const snippets: string[] = [];
  for (const msg of messages) {
    if (msg.role !== "assistant") continue;
    let m: RegExpExecArray | null;
    // Reset lastIndex on each message (global flag re-use guard).
    const re = new RegExp(CONTRADICTION_RE.source, "gi");
    while ((m = re.exec(msg.content)) !== null) {
      const snippet = m[1].trim();
      if (snippet.length > 0) snippets.push(snippet);
    }
  }
  // Deduplicate — same contradiction text appearing in multiple messages.
  return [...new Set(snippets)];
}

// ── Section header sub-component ─────────────────────────────────────────────

interface SectionHeaderProps {
  label: string;
  count?: number;
}

function SectionHeader({ label, count }: SectionHeaderProps) {
  return (
    // WHY border-t on every section: visual separation prevents the compact
    // rail content from bleeding together. border-border/30 is subtle — the
    // section label carries most of the visual weight.
    <div className="flex items-center justify-between border-t border-border/30 px-3 py-1.5">
      <span className="flex items-center gap-1.5">
        {/* Wave-2 accent header (sprint convention "accent headers on rail
            sections"): a 2px primary tick anchors each section label — same
            visual language as the platform's selected-row treatment (2px
            primary left-border, DS §selection) scaled down to a label glyph.
            aria-hidden: purely decorative; the text carries the meaning. */}
        <span
          aria-hidden="true"
          className="h-2.5 w-0.5 shrink-0 bg-primary"
          data-testid="rail-section-accent"
        />
        {/* Round 3 typography: section labels match the app-wide
            widget-header pattern (sans 9px uppercase tracking-[0.08em]) —
            mono is for NUMERIC DATA (ADR-F-15), not headings. */}
        <span className="text-[9px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
          {label}
        </span>
      </span>
      {count !== undefined && (
        <span className="rounded-[2px] bg-muted px-1 py-0 font-mono text-[9px] text-muted-foreground">
          {count}
        </span>
      )}
    </div>
  );
}

// ── Entity card section ───────────────────────────────────────────────────────

interface EntityCardProps {
  entityId: string;
}

function EntityCard({ entityId }: EntityCardProps) {
  const { accessToken } = useAuth();

  const { data, isLoading } = useQuery({
    // WHY qk.chat.entityResolve: the chat page already populates this cache
    // entry with getCompanyOverview(entityId). Sharing the key avoids a
    // second network request for the same data.
    queryKey: qk.chat.entityResolve(entityId),
    queryFn: () => createGateway(accessToken).getCompanyOverview(entityId),
    enabled: !!accessToken && !!entityId,
    staleTime: 5 * 60_000,
  });

  if (isLoading) {
    // Round 3 skeleton polish: the loading state wears the SAME card chrome
    // (mx-3 my-2 border bg-card) as the populated card below, so the card
    // doesn't "materialise" with a border+background pop when data lands.
    return (
      <div
        className="mx-3 my-2 space-y-1.5 rounded-[2px] border border-border/20 bg-card px-3 py-2"
        data-testid="entity-card-skeleton"
        aria-label="Loading entity overview"
      >
        <Skeleton className="h-3 w-24 rounded-[2px]" />
        <Skeleton className="h-3 w-32 rounded-[2px]" />
        <Skeleton className="h-3 w-20 rounded-[2px]" />
      </div>
    );
  }

  if (!data) return null;

  const { instrument, quote, fundamentals } = data;
  const ticker = instrument?.ticker ?? "—";
  const price = quote?.price ?? null;
  const changePct = quote?.change_pct ?? null;
  const pe = fundamentals?.pe_ratio ?? null;
  const mktCap = fundamentals?.market_cap ?? null;
  const vol = quote?.volume ?? null;

  return (
    // WHY bg-card border-border/20: the entity card is the most prominent
    // element in the rail. A subtle card background differentiates it from
    // the plain rail bg without creating a harsh contrast.
    <div className="mx-3 my-2 rounded-[2px] border border-border/20 bg-card px-3 py-2">
      {/* Ticker + name row */}
      <div className="flex items-baseline justify-between">
        <span className="font-mono text-[11px] font-bold text-foreground">
          {ticker}
        </span>
        {/* Company name is prose, not a numeric — sans (ADR-F-15). */}
        <span className="max-w-[140px] truncate text-right text-[9px] text-muted-foreground">
          {instrument?.name ?? ""}
        </span>
      </div>

      {/* Price + change row */}
      {price !== null && (
        <div className="mt-1 flex items-baseline gap-1.5">
          <span className="font-mono text-[11px] font-semibold text-foreground">
            {formatPrice(price)}
          </span>
          {changePct !== null && (
            <span
              className={cn(
                "font-mono text-[10px]",
                // Positive change = green, negative = red, neutral = muted.
                changePct > 0
                  ? "text-positive"
                  : changePct < 0
                    ? "text-negative"
                    : "text-muted-foreground",
              )}
            >
              {changePct > 0 ? "+" : ""}
              {formatPercent(changePct / 100)}
            </span>
          )}
          {pe !== null && (
            // ADR-F-15 §15.9: P/E is a FINANCIAL VALUE — 10px minimum.
            <span className="font-mono text-[10px] text-muted-foreground">
              · P/E {formatRatio(pe, "")}
            </span>
          )}
        </div>
      )}

      {/* Market cap + volume row — financial values, 10px data minimum. */}
      {(mktCap !== null || vol !== null) && (
        <div className="mt-0.5 flex gap-2 font-mono text-[10px] text-muted-foreground">
          {mktCap !== null && <span>Mkt cap {formatMarketCap(mktCap)}</span>}
          {vol !== null && <span>Vol {formatMarketCap(vol)}</span>}
        </div>
      )}
    </div>
  );
}

// ── Entity mini-card (per-ticker compact overview) ───────────────────────────
//
// WHY EntityMiniCard (distinct from EntityCard above):
// EntityCard is for the _primary_ entity set via ?entity_id= URL param.
// EntityMiniCard is for the tickers detected in the conversation; each one
// gets a compact card: ticker + name + price + %chg + P/E + mkt cap + a
// 5-day sparkline. Keeping them separate avoids entangling the "primary
// entity" display semantics with the "ambient context" semantics.
//
// WAVE-2 FETCH REWORK — single request per ticker:
// The old implementation chained searchInstruments(ticker, 1) →
// getCompanyOverview(instrument_id): TWO round-trips per card, and the
// search step could mis-resolve ("AAPL" → best fuzzy match). The Wave-1
// backend added GET /v1/companies/by-ticker/{ticker}/overview which resolves
// the ticker server-side (S3 + KG alias fallback) and returns the composed
// overview in ONE call; 404 (unknown ticker) maps to null at the API
// boundary so unresolved tickers still cost no card and no error chrome.
//
// WHY the sparkline is "free": the overview response already embeds the
// last ~60 1D ohlcv bars (the instrument page's mini chart uses them). We
// slice the last 5 closes — no second request, no batch endpoint needed.
//
// WHY staleTime 5min: price data is best-effort ambient context in the
// sidebar; we don't need sub-minute freshness here.

interface EntityMiniCardProps {
  /** Uppercase ticker string, e.g. "NVDA". Not a UUID. */
  ticker: string;
  /**
   * Round 2: card click → instrument page pivot. Receives the RESOLVED
   * ticker (canonical symbol from the overview, not the raw detected token)
   * so `/instruments/[ticker]` always gets a real symbol.
   * Optional — undefined renders a non-interactive card.
   */
  onClick?: (ticker: string) => void;
}

/** How many trailing daily closes feed the mini-card sparkline. */
const SPARKLINE_DAYS = 5;

function EntityMiniCard({ ticker, onClick }: EntityMiniCardProps) {
  const { accessToken } = useAuth();

  const { data, isLoading } = useQuery({
    // WHY keep qk.chat.tickerMini: the key identifies "overview for this
    // ticker in chat context" — the fetch mechanism changing underneath
    // (two-step → by-ticker) doesn't change the cache identity.
    queryKey: qk.chat.tickerMini(ticker),
    // Wave 2: ONE request. Returns null on 404 (unresolvable ticker) so the
    // card silently doesn't render — same contract as the old search-miss.
    queryFn: () => createGateway(accessToken).getCompanyOverviewByTicker(ticker),
    enabled: !!accessToken && !!ticker,
    staleTime: 5 * 60_000,
  });

  if (isLoading) {
    // WHY compact skeleton: the mini card is inside a tight flex grid; a
    // full-height block skeleton would cause layout shift. Two small lines
    // match the text layout of the populated state.
    return (
      <div className="space-y-1 rounded-[2px] border border-border/20 bg-card px-2 py-1.5">
        <Skeleton className="h-2.5 w-16 rounded-[2px]" />
        <Skeleton className="h-2 w-24 rounded-[2px]" />
      </div>
    );
  }

  // Null result means the ticker resolved to nothing — skip silently.
  if (!data) return null;

  const { instrument, quote, fundamentals, ohlcv } = data;
  const displayTicker = instrument?.ticker ?? ticker;
  const name = instrument?.name ?? "";
  const price = quote?.price ?? null;
  const changePct = quote?.change_pct ?? null;
  const pe = fundamentals?.pe_ratio ?? null;
  const mktCap = fundamentals?.market_cap ?? null;
  // Wave 2: last 5 daily closes from the bars the overview already carries.
  // <2 points → no line (the Sparkline primitive needs two to draw); we
  // render nothing rather than a misleading single-dot artefact.
  const sparkData = (ohlcv?.bars ?? [])
    .slice(-SPARKLINE_DAYS)
    .map((b) => b.close)
    .filter((c): c is number => typeof c === "number");

  return (
    // Round 2: the mini-card is a <button> — clicking it pivots to
    // /instruments/[ticker] (via the onClick callback the page wires to
    // router.push). WHY button (not <a href>): the destination is wired by
    // the parent, and a button keeps keyboard/focus semantics correct
    // without this component knowing about Next.js routing.
    <button
      type="button"
      data-testid="entity-mini-card"
      onClick={() => onClick?.(displayTicker)}
      // Disable interactive affordances when no handler is wired — a focus
      // ring + pointer cursor on an inert card would be a lying affordance.
      disabled={!onClick}
      aria-label={`Open ${displayTicker} instrument page`}
      title={onClick ? `Open /instruments/${displayTicker}` : undefined}
      className={cn(
        "w-full rounded-[2px] border border-border/20 bg-card px-2 py-1.5 text-left",
        // Hover affordance only when clickable; keyboard focus ring matches
        // the platform's interactive-surface treatment.
        onClick &&
          "transition-colors duration-0 hover:border-primary/40 hover:bg-muted focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-primary",
      )}
    >
      {/* Ticker + name (truncated) */}
      <div className="flex items-baseline justify-between gap-1">
        <span className="font-mono text-[10px] font-bold text-foreground">
          {displayTicker}
        </span>
        {name && (
          // Company name is non-data metadata → 9px sans (ADR-F-15).
          <span className="max-w-[110px] truncate text-right text-[9px] text-muted-foreground">
            {name}
          </span>
        )}
      </div>

      {/* Price + change + 5-day sparkline */}
      {price !== null && (
        <div className="mt-0.5 flex items-baseline gap-1">
          <span className="font-mono text-[10px] font-semibold text-foreground">
            {formatPrice(price)}
          </span>
          {changePct !== null && (
            <span
              className={cn(
                // ADR-F-15 §15.9: %chg is a financial value → 10px minimum.
                "font-mono text-[10px]",
                changePct > 0
                  ? "text-positive"
                  : changePct < 0
                    ? "text-negative"
                    : "text-muted-foreground",
              )}
            >
              {changePct > 0 ? "+" : ""}
              {formatPercent(changePct / 100)}
            </span>
          )}
          {/* Wave 2: 5-day trend, right-aligned. WHY ml-auto self-center: the
              sparkline is a glyph, not text — centring it vertically against
              the baseline row keeps the 16px SVG from stretching the row.
              Trend colour is computed by the primitive (±0.1% rule). */}
          {sparkData.length >= 2 && (
            <span className="ml-auto self-center" data-testid="mini-card-sparkline">
              <Sparkline
                data={sparkData}
                label={`${displayTicker} 5-day trend`}
              />
            </span>
          )}
        </div>
      )}

      {/* P/E + Mkt Cap — one compact row (financial values, 10px floor). */}
      {(pe !== null || mktCap !== null) && (
        <div className="mt-0.5 flex gap-1.5 font-mono text-[10px] text-muted-foreground">
          {pe !== null && <span>P/E {formatRatio(pe, "")}</span>}
          {mktCap !== null && <span>Cap {formatMarketCap(mktCap)}</span>}
        </div>
      )}
    </button>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

export function ChatContextRail({
  entityId,
  messages,
  toolUsage = [],
  isCollapsed: _isCollapsed,
  onClose,
  onTickerClick,
  onCardClick,
  isDebug = false,
  debugHref,
}: ChatContextRailProps) {
  // ── Derived: conversation sources (Wave 2) ───────────────────────────────
  //
  // Citations aggregated across ALL assistant turns, deduped by source
  // document (url, else article_id), counted per reference, ordered by
  // count desc then best relevance desc — the conversation's bibliography.
  // The full distinct count feeds the section header badge; the rendered
  // rows are capped (rail height budget).
  const conversationSources = useMemo(
    () => aggregateConversationSources(messages),
    [messages],
  );
  const visibleSources = conversationSources.slice(0, DEFAULT_SOURCE_CAP);

  // ── Derived: tools used summary (Wave 2) ─────────────────────────────────
  const toolRows = useMemo(() => summarizeToolUsage(toolUsage), [toolUsage]);

  // ── Derived: contradictions extracted from message content ──────────────
  const contradictions = useMemo(
    () => extractContradictions(messages),
    [messages],
  );

  // ── Derived: related tickers via the shared extractor (Round 2) ─────────
  //
  // WHY recompute on every `messages` identity change: tickers must
  // appear/update AS the conversation evolves — a follow-up question that
  // introduces $TSM must surface a TSM card without a refresh.
  //
  // `tickers` is deduped, most-recent-first, capped at 8; `overflow` is how
  // many additional distinct tickers were detected beyond the cap.
  const { tickers: relatedTickers, overflow: tickerOverflow } = useMemo(
    () => extractTickers(messages),
    [messages],
  );

  // Wave 2: cold state — nothing to derive context FROM yet. Entity context
  // via ?entity_id= still counts as content (the primary card renders).
  const isCold = messages.length === 0 && !entityId;

  // ── Render ─────────────────────────────────────────────────────────────

  return (
    // WHY h-full flex-col: the rail must fill the parent's full height so the
    // border-l is continuous from top to bottom.
    <div className="flex h-full flex-col bg-background">
      {/* Rail header — 28px, border-b */}
      <div className="flex h-7 shrink-0 items-center justify-between border-b border-border px-3">
        {/* Panel header: widget-header pattern (10px sans uppercase), one
            step above the 9px section labels below. */}
        <span className="text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
          Context
        </span>
        {/* WHY X button: Cmd+\ is keyboard-only. Analysts using mouse need a
            visible close affordance. */}
        <button
          type="button"
          onClick={onClose}
          className="flex h-5 w-5 items-center justify-center rounded-[2px] text-muted-foreground hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-primary"
          aria-label="Close context rail"
        >
          <X className="h-3 w-3" strokeWidth={1.5} />
        </button>
      </div>

      {/* Scrollable body — the sections stack inside this */}
      <div className="flex-1 overflow-y-auto">
        {/* ── Wave 2: named cold state ─────────────────────────────────── */}
        {/* WHY a single named state instead of stacked "No X yet" rows: an
            empty conversation used to render three section headers over
            three flavours of nothing — the rail read as broken. One state
            that NAMES the panel's future value reads as "waiting". */}
        {isCold ? (
          <div className="px-2 py-6" data-testid="rail-cold-state">
            <EmptyState
              condition="empty-cold-start"
              copyKey="chat.rail-empty"
              icon={PanelRight}
            />
          </div>
        ) : (
          <>
            {/* ── Entity card section (primary ?entity_id= context) ────── */}
            {entityId && (
              <>
                <SectionHeader label="Entity" />
                <EntityCard entityId={entityId} />
              </>
            )}

            {/* ── Conversation sources (Wave 2) ─────────────────────────── */}
            {/* WHY always render the section header even with 0 sources: the
                rail looks confusing without labels mid-conversation. When no
                citations exist yet we show a muted named line. */}
            <SectionHeader
              label="Conversation Sources"
              count={conversationSources.length || undefined}
            />
            {visibleSources.length === 0 ? (
              <p className="px-3 py-2 font-mono text-[9px] text-muted-foreground/60">
                No sources cited yet.
              </p>
            ) : (
              <div className="space-y-0 px-3 py-1">
                {visibleSources.map((src, idx) => {
                  const badge = sourceBadge(src.source);
                  const row = (
                    <>
                      {/* Source rank index — terminal convention. */}
                      <span className="shrink-0 font-mono text-[9px] text-muted-foreground">
                        [{idx + 1}]
                      </span>
                      {/* Source type badge — SEC / EARN / NEWS / KG */}
                      <span className="shrink-0 rounded-[2px] bg-primary/10 px-1 py-0 font-mono text-[9px] text-primary">
                        {badge}
                      </span>
                      {/* Title + reference count */}
                      <span className="min-w-0 flex-1 font-mono text-[10px] leading-snug">
                        <span className="line-clamp-2 break-words">
                          {src.title || src.source}
                        </span>
                        {/* Reference count — "how load-bearing is this
                            source". Mono (numeric, ADR-F-15). */}
                        <span className="mt-0.5 block text-[9px] text-muted-foreground">
                          ×{src.count} reference{src.count === 1 ? "" : "s"}
                        </span>
                      </span>
                    </>
                  );
                  // WHY two render shapes: external sources (url) are REAL
                  // links — open in a new tab (standard research gesture,
                  // never navigates the chat away). In-platform sources
                  // (KG citations, url=null) have nothing to open — render
                  // a plain row, not a dead link.
                  return src.url ? (
                    <a
                      key={src.key}
                      href={src.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      title={src.title}
                      data-testid="conversation-source-row"
                      className="flex items-start gap-1.5 py-1 text-foreground hover:text-primary focus-visible:outline-1 focus-visible:outline-primary focus-visible:outline-offset-[-1px]"
                    >
                      {row}
                    </a>
                  ) : (
                    <div
                      key={src.key}
                      title={src.title}
                      data-testid="conversation-source-row"
                      className="flex items-start gap-1.5 py-1 text-foreground"
                    >
                      {row}
                    </div>
                  );
                })}
                {/* Overflow — distinct sources beyond the rendered cap. */}
                {conversationSources.length > visibleSources.length && (
                  <p className="px-1 py-0.5 font-mono text-[9px] text-muted-foreground/60">
                    +{conversationSources.length - visibleSources.length} more
                    sources
                  </p>
                )}
              </div>
            )}

            {/* ── Contradictions section ───────────────────────────────── */}
            {/* WHY only render when count > 0: contradictions are
                high-signal — present them only when relevant. */}
            {contradictions.length > 0 && (
              <>
                <SectionHeader
                  label="Contradictions"
                  count={contradictions.length}
                />
                <div className="space-y-1 px-3 py-1">
                  {contradictions.map((snippet, idx) => (
                    <div
                      key={idx}
                      className="flex items-start gap-1.5 rounded-[2px] border border-warning/20 bg-warning/5 px-2 py-1"
                    >
                      <AlertTriangle
                        className="mt-0.5 h-2.5 w-2.5 shrink-0 text-warning"
                        strokeWidth={1.5}
                      />
                      <p className="font-mono text-[10px] leading-snug text-foreground">
                        {snippet}
                      </p>
                    </div>
                  ))}
                </div>
              </>
            )}

            {/* ── Related tickers section ──────────────────────────────── */}
            {relatedTickers.length > 0 && (
              <>
                <SectionHeader
                  label="Related Tickers"
                  count={relatedTickers.length}
                />
                {/* WHY flex-wrap: some threads mention 10+ tickers. */}
                <div className="flex flex-wrap gap-1 px-3 py-2">
                  {relatedTickers.map((ticker) => (
                    <button
                      key={ticker}
                      type="button"
                      onClick={() => onTickerClick(ticker)}
                      title={`Append $${ticker} to composer`}
                      className={cn(
                        "rounded-[2px] border border-border/70 bg-muted/30",
                        "px-1.5 py-0.5 font-mono text-[11px] tabular-nums text-primary",
                        "transition-colors hover:border-primary/50 hover:bg-primary/10",
                        "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-primary",
                      )}
                    >
                      ${ticker}
                    </button>
                  ))}
                </div>
              </>
            )}

            {/* ── Entity overview mini-cards ───────────────────────────── */}
            {/*
             * One card per detected ticker (8 most recent, extractor-capped),
             * each a SINGLE by-ticker overview request (Wave 2). Tickers that
             * fail to resolve (404 → null) render nothing — bare-token false
             * positives cost a request, never a phantom card.
             *
             * WHY AFTER Related Tickers: the chips are a quick-action surface
             * (one click → composer); the cards are a data surface. Quick
             * actions first, data below — Bloomberg's RELATED/DETAILS order.
             */}
            {relatedTickers.length > 0 && (
              <>
                <SectionHeader
                  label="Entity Overview"
                  count={relatedTickers.length}
                />
                <div className="flex flex-col gap-1.5 px-3 py-1.5">
                  {relatedTickers.map((ticker) => (
                    <EntityMiniCard
                      key={ticker}
                      ticker={ticker}
                      onClick={onCardClick}
                    />
                  ))}
                  {tickerOverflow > 0 && (
                    <p className="px-1 font-mono text-[9px] text-muted-foreground/60">
                      +{tickerOverflow} more mentioned
                    </p>
                  )}
                </div>
              </>
            )}

            {/* ── Tools used (Wave 2) ──────────────────────────────────── */}
            {/* Which platform tools produced the conversation's answers —
                one row per tool: name, invocation count, avg server-measured
                latency. Rendered only once at least one tool completed (a
                permanently-empty section would be noise on pure-LLM chats). */}
            {toolRows.length > 0 && (
              <>
                <SectionHeader label="Tools Used" count={toolRows.length} />
                <div className="px-3 py-1" data-testid="tools-used-section">
                  {toolRows.map((row) => (
                    <div
                      key={row.tool}
                      data-testid="tool-usage-row"
                      className="flex items-baseline gap-1.5 py-0.5"
                    >
                      {/* Raw tool name — the precise identifier, mono. */}
                      <span className="min-w-0 flex-1 truncate font-mono text-[10px] text-foreground">
                        {row.tool}
                      </span>
                      {/* Invocation count — numeric, mono. */}
                      <span className="shrink-0 font-mono text-[9px] text-muted-foreground">
                        ×{row.count}
                      </span>
                      {/* Average latency — server-measured duration_ms.
                          "—" when no sample carried a latency. */}
                      <span className="w-14 shrink-0 text-right font-mono text-[10px] tabular-nums text-muted-foreground">
                        {row.avgLatencyMs !== null
                          ? `${row.avgLatencyMs} ms`
                          : "—"}
                      </span>
                    </div>
                  ))}
                  {/* Footer — route to the per-call trace. With ?debug=1
                      active the ⌘D chord opens the ToolTraceDrawer; without
                      it we link to the debug-enabled URL (page-built href so
                      the active thread survives the reload). */}
                  {isDebug ? (
                    <p className="pt-1 font-mono text-[9px] text-muted-foreground/60">
                      ⌘D opens the per-call trace
                    </p>
                  ) : debugHref ? (
                    <a
                      href={debugHref}
                      data-testid="tools-debug-link"
                      className="block pt-1 font-mono text-[9px] text-muted-foreground/60 underline-offset-2 hover:text-primary hover:underline focus-visible:outline-1 focus-visible:outline-primary"
                    >
                      Inspect per-call trace (?debug=1)
                    </a>
                  ) : null}
                </div>
              </>
            )}
          </>
        )}
      </div>
    </div>
  );
}
