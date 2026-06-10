/**
 * features/chat/components/ChatContextRail.tsx — Right-side 320px context rail
 * for the Chat page.
 *
 * WHY THIS EXISTS:
 * The chat page previously had two columns (thread list | messages). Research
 * sessions benefit from a persistent ambient panel that shows _what the
 * conversation is about_ without requiring the analyst to scroll back through
 * the log: which entity is in context, what sources have been cited, whether
 * the AI found contradictory claims, and which other tickers appeared.
 *
 * WHY RIGHT RAIL (not a popover or bottom sheet):
 * Bloomberg Terminal places related context panels to the right of the primary
 * content surface. A persistent fixed-width rail is always in the same spot —
 * the analyst's eye can glance without hunting. A popover disappears when
 * dismissed; a bottom sheet shrinks the message area. The rail does neither.
 *
 * WHY 320px:
 * Fits citation titles at 10px mono without truncation for 90% of article
 * titles (≤50 chars), while leaving ≥600px for the message column even on
 * a 1280px screen (1280 - 224 sidebar - 320 rail = 736px messages).
 *
 * WHY Cmd+\ collapse:
 * Wired at the page level (not here) so the keyboard listener is centralised.
 * This component receives `isCollapsed` as a prop and renders nothing when
 * true — the parent hides the wrapper div.
 *
 * DATA FLOW:
 *   Entity card  — TanStack Query fetch via getCompanyOverview (entityId param).
 *                  Reads from cache first (qk.chat.entityResolve populates it).
 *   Citations    — pure derivation from `messages` prop (no extra fetch).
 *   Contradictions — pure derivation from `messages.content` regex scan.
 *                    (The backend doesn't yet embed a structured contradictions
 *                    field on Message; this extracts text patterns emitted by
 *                    S8 when it detects conflicting claims.)
 *   Related tickers — shared `extractTickers` lib (Round 2): $TICKER always
 *                    counts; bare TICKER tokens pass a generous noise
 *                    blocklist. Deduped, most-recent-first, capped at 8 with
 *                    an overflow count. Mini-cards only render for tickers
 *                    that RESOLVE via the instrument-search endpoint, so a
 *                    blocklist escape can never paint a phantom card.
 *
 * WHO USES IT: app/(app)/chat/page.tsx
 * DESIGN REFERENCE: Task spec §2 (context rail design block)
 */

"use client";
// WHY "use client": uses useQuery (TanStack), formatters, and passes a
// callback to the parent. All require a browser execution context.

import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { X, AlertTriangle } from "lucide-react";

import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { qk } from "@/lib/query/keys";
import { cn } from "@/lib/utils";
import { formatPrice, formatPercent, formatMarketCap, formatRatio } from "@/lib/utils";
import { Skeleton } from "@/components/ui/skeleton";
import type { Message } from "@/types/api";
// Round 2 Enhancement: single source of truth for ticker detection. Replaces
// the two inline regex passes ($TICKER + **BOLD**) this file used to carry —
// the lib adds bare-token detection behind a generous noise blocklist and
// returns a recency-ordered, capped result with an overflow count.
import { extractTickers } from "@/features/chat/lib/ticker-extract";

// ── Types ─────────────────────────────────────────────────────────────────────

export interface ChatContextRailProps {
  /** UUID from ?entity_id= URL param, or null when no entity context is set. */
  entityId: string | null;
  /**
   * All messages for the current thread (both user + assistant).
   * Used to derive citations, contradictions, and related tickers.
   * Empty array when the thread hasn't loaded yet.
   */
  messages: Message[];
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
   * free of next/navigation so it stays trivially unit-testable, and lets a
   * future embedding surface (e.g. a workspace widget) decide its own
   * navigation policy (new tab, panel swap, …).
   *
   * Optional: when omitted, cards render as static info surfaces (the
   * pre-Round-2 behaviour) — keeps other compositions compiling unchanged.
   */
  onCardClick?: (ticker: string) => void;
}

// ── Source type badge labels ──────────────────────────────────────────────────
// WHY hard-coded map (not computed): the 4 badge labels match the spec exactly.
// Anything outside the known set falls back to "SRC" so the badge always shows.
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

// ── Related ticker extraction ─────────────────────────────────────────────────
// Round 2 Enhancement: extraction moved to the shared, table-tested
// `features/chat/lib/ticker-extract.ts`. WHY the move:
//
//   - The old inline pass detected only $TICKER and **BOLD** assistant
//     tokens, so "compare NVDA with AMD" (bare, un-bolded — how analysts
//     actually type) produced ZERO detections. The lib detects bare 2–5
//     letter uppercase tokens behind a generous noise blocklist (CEO, GDP,
//     EPS, VERY, …) so plain prose mentions count too.
//   - The lib returns tickers ordered MOST-RECENT-FIRST and capped (8),
//     with an overflow count — exactly what the Entity Overview mini-card
//     section needs ("8 most recent + N more").
//   - Bold (**NVDA**) is a strict subset of the bare pattern (asterisks are
//     non-word chars, so \b matches at the token edges) — no detection was
//     lost in the consolidation.
//
// The blocklist keeps the old guarantees: a user typing "**VERY**" or an
// assistant bolding "**CEO**" never produces a chip (pinned by this file's
// existing test suite), while explicit "$F" / "$ALL" always do.

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
      <span className="font-mono text-[9px] font-semibold uppercase tracking-[0.10em] text-muted-foreground">
        {label}
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

  // WHY qk.instruments.overview (not qk.chat.entityResolve):
  // The chat page already fires getCompanyOverview for entityResolve — the
  // result is in the TanStack cache under that key. But getCompanyOverview
  // returns a CompanyOverview (instrument + quote + fundamentals). The chat
  // page uses qk.chat.entityResolve which resolves to getCompanyOverview.
  // We re-use the SAME cache key so there is exactly ONE network request for
  // the entity overview across the whole page. No duplicate fetch.
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
    return (
      <div className="space-y-1.5 px-3 py-2">
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
        <span className="max-w-[140px] truncate text-right font-mono text-[9px] text-muted-foreground">
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
                // WHY conditional colour: positive change = green (text-positive),
                // negative = red (text-negative). Neutral (0.00%) → muted.
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
            <span className="font-mono text-[9px] text-muted-foreground">
              · P/E {formatRatio(pe, "")}
            </span>
          )}
        </div>
      )}

      {/* Market cap + volume row */}
      {(mktCap !== null || vol !== null) && (
        <div className="mt-0.5 flex gap-2 font-mono text-[9px] text-muted-foreground">
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
// EntityCard is for the _primary_ entity set via ?entity_id= URL param — it
// shows the full card with volume row. EntityMiniCard is for the RELATED
// tickers detected in the conversation; each one gets a compact one-liner:
// ticker + name + price + %chg + P/E.  Keeping them separate avoids
// entangling the "primary entity" display semantics with the "ambient
// context" semantics for chat-detected entities.
//
// WHY two-step resolution (searchInstruments then getCompanyOverview):
// The related tickers in the conversation are bare strings ("NVDA", "AMD")
// not UUIDs.  S9's company-overview endpoint accepts instrument_id (UUID),
// not a ticker string.  searchInstruments(ticker, 1) returns the best-match
// instrument row which contains `instrument_id`; we then pass that to
// getCompanyOverview to get price + fundamentals.  The result is cached under
// qk.chat.tickerMini(ticker) so repeated renders for the same ticker within a
// session are served from cache without extra network calls.
//
// WHY staleTime 5min: same as EntityCard — price data is best-effort ambient
// context in the sidebar; we don't need sub-minute freshness here.

interface EntityMiniCardProps {
  /** Uppercase ticker string, e.g. "NVDA". Not a UUID. */
  ticker: string;
  /**
   * Round 2: card click → instrument page pivot. Receives the RESOLVED
   * ticker (the canonical symbol from the search result, not the raw
   * detected token) so `/instruments/[ticker]` always gets a real symbol.
   * Optional — undefined renders a non-interactive card (legacy behaviour).
   */
  onClick?: (ticker: string) => void;
}

function EntityMiniCard({ ticker, onClick }: EntityMiniCardProps) {
  const { accessToken } = useAuth();

  // Step 1 + Step 2 combined into one query using queryFn chaining:
  // searchInstruments(ticker, 1) → instrument_id → getCompanyOverview(id).
  // WHY queryFn does both: avoids a second useQuery dependency and keeps the
  // loading/error state in a single place.  The two sequential awaits are
  // cheap — the second call may hit the TanStack cache if EntityCard already
  // resolved the same instrument.
  const { data, isLoading } = useQuery({
    queryKey: qk.chat.tickerMini(ticker),
    queryFn: async () => {
      const gw = createGateway(accessToken);
      // Search for the ticker to get the canonical instrument_id.
      const searchResult = await gw.searchInstruments(ticker, 1);
      const first = searchResult.results[0];
      // If search returns nothing, abort gracefully — the mini card won't render.
      if (!first?.instrument_id) return null;
      // Fetch the full overview so we have price + fundamentals.
      return gw.getCompanyOverview(first.instrument_id);
    },
    enabled: !!accessToken && !!ticker,
    staleTime: 5 * 60_000,
  });

  if (isLoading) {
    // WHY compact skeleton: the mini card is inside a tight flex grid; a
    // full-height block skeleton would cause layout shift.  Two small lines
    // match the text layout of the populated state.
    return (
      <div className="space-y-1 rounded-[2px] border border-border/20 bg-card px-2 py-1.5">
        <Skeleton className="h-2.5 w-16 rounded-[2px]" />
        <Skeleton className="h-2 w-24 rounded-[2px]" />
      </div>
    );
  }

  // Null result means search found nothing — skip silently.
  if (!data) return null;

  const { instrument, quote, fundamentals } = data;
  const displayTicker = instrument?.ticker ?? ticker;
  const name = instrument?.name ?? "";
  const price = quote?.price ?? null;
  const changePct = quote?.change_pct ?? null;
  const pe = fundamentals?.pe_ratio ?? null;
  const mktCap = fundamentals?.market_cap ?? null;

  return (
    // Round 2: the mini-card is now a <button> — clicking it pivots to
    // /instruments/[ticker] (via the onClick callback the page wires to
    // router.push). WHY button (not <a href>): the destination is wired by
    // the parent, and a button keeps keyboard/focus semantics correct
    // without this component knowing about Next.js routing.
    // WHY w-full text-left: buttons default to centred inline sizing —
    // the card must fill the rail column and keep its left-aligned layout.
    // WHY border-border/20 bg-card: same subtle card background as EntityCard
    // so the two card types feel visually consistent despite different density.
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
        // Hover affordance only when clickable; transition-colors duration-0
        // honours the no-animation terminal mandate while keeping the class
        // structure consistent with the chips above.
        onClick && "transition-colors duration-0 hover:border-primary/40 hover:bg-muted/40",
      )}
    >
      {/* Ticker + name (truncated) */}
      <div className="flex items-baseline justify-between gap-1">
        <span className="font-mono text-[10px] font-bold text-foreground">
          {displayTicker}
        </span>
        {name && (
          <span className="max-w-[110px] truncate text-right font-mono text-[8px] text-muted-foreground">
            {name}
          </span>
        )}
      </div>

      {/* Price + change */}
      {price !== null && (
        <div className="mt-0.5 flex items-baseline gap-1">
          <span className="font-mono text-[10px] font-semibold text-foreground">
            {formatPrice(price)}
          </span>
          {changePct !== null && (
            <span
              className={cn(
                "font-mono text-[9px]",
                // WHY same colour pattern as EntityCard: positive = green,
                // negative = red, neutral = muted.  Visual consistency means
                // the analyst doesn't re-learn the colour code between cards.
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
        </div>
      )}

      {/* P/E + Mkt Cap — one compact row */}
      {(pe !== null || mktCap !== null) && (
        <div className="mt-0.5 flex gap-1.5 font-mono text-[8px] text-muted-foreground">
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
  isCollapsed: _isCollapsed,
  onClose,
  onTickerClick,
  onCardClick,
}: ChatContextRailProps) {
  // ── Derived: citations aggregated across all assistant turns ────────────
  //
  // WHY top 4 only: the rail is 320px and each citation row is 18px + padding.
  // Four rows fit comfortably without overflow. The analyst can scroll the
  // message area to read the full citation list on any individual bubble.
  //
  // WHY deduplicate by article_id: a single article may be cited in multiple
  // assistant turns (e.g. the assistant references the same 10-Q in the first
  // and third responses). Showing it twice wastes rail space and implies it's
  // two different sources.
  //
  // WHY sort by relevance_score desc: the most confident citations are most
  // useful at a glance. The analyst wants to know "what are the top sources
  // driving this conversation" — the strongest-confidence ones answer that.
  const topCitations = useMemo(() => {
    const seen = new Set<string>();
    const deduped: Array<{ article_id: string; title: string; source: string; relevance_score: number }> = [];
    for (const msg of messages) {
      if (msg.role !== "assistant") continue;
      for (const cit of msg.citations ?? []) {
        if (!seen.has(cit.article_id)) {
          seen.add(cit.article_id);
          deduped.push(cit);
        }
      }
    }
    return deduped
      .sort((a, b) => (b.relevance_score ?? 0) - (a.relevance_score ?? 0))
      .slice(0, 4);
  }, [messages]);

  // ── Derived: contradictions extracted from message content ──────────────
  const contradictions = useMemo(
    () => extractContradictions(messages),
    [messages],
  );

  // ── Derived: related tickers via the shared extractor (Round 2) ─────────
  //
  // WHY recompute on every `messages` identity change: tickers must
  // appear/update AS the conversation evolves — a follow-up question that
  // introduces $TSM must surface a TSM card without a refresh. useMemo on
  // the messages array gives exactly that (the page replaces the array on
  // every new message).
  //
  // `tickers` is deduped, most-recent-first, capped at 8; `overflow` is how
  // many additional distinct tickers were detected beyond the cap.
  const { tickers: relatedTickers, overflow: tickerOverflow } = useMemo(
    () =>
      extractTickers(
        // Message is structurally a TickerSourceMessage (role + content) —
        // no mapping needed; annotate for readers.
        messages,
      ),
    [messages],
  );

  // ── Render ─────────────────────────────────────────────────────────────

  return (
    // WHY h-full flex-col: the rail must fill the parent's full height so the
    // border-l is continuous from top to bottom. flex-col lets sections stack
    // vertically while the last section's content doesn't get clipped.
    <div className="flex h-full flex-col bg-background">
      {/* Rail header — 28px, border-b */}
      <div className="flex h-7 shrink-0 items-center justify-between border-b border-border px-3">
        <span className="font-mono text-[9px] font-semibold uppercase tracking-[0.10em] text-muted-foreground">
          Context
        </span>
        {/* WHY X button: Cmd+\ is keyboard-only. Analysts using mouse need a
            visible close affordance. The icon matches the 3.5px / 1.5 strokeWidth
            convention used across the platform's panel chrome. */}
        <button
          type="button"
          onClick={onClose}
          className="flex h-5 w-5 items-center justify-center rounded-[2px] text-muted-foreground hover:bg-muted/50 hover:text-foreground"
          aria-label="Close context rail"
        >
          <X className="h-3 w-3" strokeWidth={1.5} />
        </button>
      </div>

      {/* Scrollable body — the sections stack inside this */}
      <div className="flex-1 overflow-y-auto">
        {/* ── Entity card section ─────────────────────────────────────── */}
        {entityId && (
          <>
            <SectionHeader label={`Entity`} />
            <EntityCard entityId={entityId} />
          </>
        )}

        {/* ── Recent citations section ────────────────────────────────── */}
        {/* WHY always render the section header even when 0 citations:
            the rail looks empty and confusing without labels. When no
            citations exist, we show a muted "No sources cited yet." */}
        <SectionHeader label="Recent Citations" count={topCitations.length || undefined} />
        {topCitations.length === 0 ? (
          <p className="px-3 py-2 font-mono text-[9px] text-muted-foreground/60">
            No sources cited yet.
          </p>
        ) : (
          <div className="space-y-0 px-3 py-1">
            {topCitations.map((cit, idx) => {
              const badge = sourceBadge(cit.source);
              const score = Math.round((cit.relevance_score ?? 0) * 100);
              return (
                // WHY anchor tag (not button): citations have a URL. Wrapping in
                // <a> lets the analyst Cmd+click to open in a new tab — the
                // standard browser gesture for "open without leaving the page".
                <a
                  key={cit.article_id}
                  href="#"
                  // WHY preventDefault: we don't navigate to the citation's URL
                  // from the rail (it would leave the chat). The link is visual
                  // affordance only; the href="#" is a no-op placeholder.
                  onClick={(e) => e.preventDefault()}
                  title={cit.title}
                  className="flex items-start gap-1.5 py-1 text-foreground hover:text-primary"
                >
                  {/* Citation index */}
                  <span className="shrink-0 font-mono text-[9px] text-muted-foreground">
                    [{idx + 1}]
                  </span>
                  {/* Source type badge — SEC / EARN / NEWS / KG */}
                  <span className="shrink-0 rounded-[2px] bg-primary/10 px-1 py-0 font-mono text-[9px] text-primary">
                    {badge}
                  </span>
                  {/* Title — truncated to 2 lines */}
                  <span className="min-w-0 flex-1 font-mono text-[10px] leading-snug">
                    <span className="line-clamp-2 break-words">{cit.title}</span>
                    {/* Score as percentage — quick confidence signal */}
                    <span className="mt-0.5 block text-[9px] text-muted-foreground">
                      {score}%
                    </span>
                  </span>
                </a>
              );
            })}
          </div>
        )}

        {/* ── Contradictions section ─────────────────────────────────── */}
        {/* WHY only render when count > 0: a section reading
            "CONTRADICTIONS · 0" with no rows adds noise. Contradictions
            are high-signal — present them only when relevant. */}
        {contradictions.length > 0 && (
          <>
            <SectionHeader label="Contradictions" count={contradictions.length} />
            <div className="space-y-1 px-3 py-1">
              {contradictions.map((snippet, idx) => (
                <div
                  key={idx}
                  className="flex items-start gap-1.5 rounded-[2px] border border-warning/20 bg-warning/5 px-2 py-1"
                >
                  {/* WHY AlertTriangle: universal "warning" icon; the ⚠ text
                      character has inconsistent rendering across OS/font combos.
                      Using the lucide icon guarantees consistent sizing. */}
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

        {/* ── Related tickers section ────────────────────────────────── */}
        {relatedTickers.length > 0 && (
          <>
            <SectionHeader label="Related Tickers" count={relatedTickers.length} />
            {/* WHY flex-wrap: some threads mention 10+ tickers. Wrapping keeps all
                chips visible without requiring horizontal scroll. */}
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
                    // WHY hover:border-primary/50: matches the entity chips in
                    // the composer footer — visual language consistency.
                    "transition-colors hover:border-primary/50 hover:bg-primary/10",
                  )}
                >
                  ${ticker}
                </button>
              ))}
            </div>
          </>
        )}

        {/* ── Entity overview mini-cards ──────────────────────────────── */}
        {/*
         * Round 2 contract: render a mini-card for the 8 MOST RECENT distinct
         * tickers detected in the conversation (the extractor orders by
         * recency and caps at 8). Tickers beyond the cap surface as a muted
         * "+N more mentioned" line — the analyst knows detection happened
         * without the rail (or the backend) paying for more cards.
         *
         * WHY 8 (was 3): each EntityMiniCard fires at most two cached network
         * requests (searchInstruments + getCompanyOverview, 5-min staleTime,
         * per-ticker query keys), so 8 cards cost ≤16 requests ONCE per
         * session per ticker — acceptable for the primary added value of the
         * rail. The extractor's cap (not a slice here) is the single knob.
         *
         * VALIDATION: EntityMiniCard returns null when the ticker fails to
         * resolve via instrument search — cards only render for REAL
         * instruments, so bare-token false positives that slip past the
         * blocklist (e.g. an uncommon acronym) cost a request, not a card.
         *
         * WHY this section appears AFTER Related Tickers (not before):
         * The chips are a quick-action surface (one click → composer); the
         * mini-cards are a data surface.  Quick-actions first, data below —
         * mirrors Bloomberg's RELATED/DETAILS panel ordering convention.
         */}
        {relatedTickers.length > 0 && (
          <>
            <SectionHeader label="Entity Overview" count={relatedTickers.length} />
            {/* WHY gap-1.5 px-3: tighter than the EntityCard mx-3 my-2 to fit
                the cards in the available rail height without excessive whitespace. */}
            <div className="flex flex-col gap-1.5 px-3 py-1.5">
              {relatedTickers.map((ticker) => (
                // Round 2: cards are clickable — onCardClick pivots to the
                // instrument page (wired by the chat page to router.push).
                <EntityMiniCard key={ticker} ticker={ticker} onClick={onCardClick} />
              ))}
              {/* Overflow indicator — detected-but-not-carded ticker count.
                  WHY aria-live OFF (plain text): this updates as a side
                  effect of the conversation; announcing every change would
                  be screen-reader noise. */}
              {tickerOverflow > 0 && (
                <p className="px-1 font-mono text-[9px] text-muted-foreground/60">
                  +{tickerOverflow} more mentioned
                </p>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
