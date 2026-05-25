/**
 * components/chat/SlashCommandCard.tsx — Inline structured cards for slash commands
 *
 * WHY THIS EXISTS (PLAN-0051 T-E-5-01):
 * When the user types "/quote AAPL", "/portfolio", etc. the chat page renders
 * THIS component instead of streaming an LLM response. Each `kind` switches
 * to a small data-grade widget that fetches from the gateway directly.
 * The card looks like an assistant message in the conversation log so the
 * thread reads naturally — but it never round-trips to the LLM.
 *
 * WHY KEEP CARDS SMALL: chat messages should feel like quick answers. We pack
 * the headline numbers (price, change, volume; total value, day P&L; top 5
 * news; …) into a single compact panel. Anything richer should link out to
 * the dedicated full page.
 *
 * WHY useQuery (not useEffect+fetch): we want TanStack's caching, retry, and
 * loading state machine. A user typing /quote AAPL twice in a row should hit
 * the cache, not re-fetch. staleTime values are tuned per data freshness.
 *
 * WHO USES IT: app/(app)/chat/page.tsx renders one per slash-command turn.
 */

"use client";
// WHY "use client": every card uses useQuery from TanStack which requires
// the React context. The whole tree is interactive, never SSR.

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import {
  AlertCircle,
  Briefcase,
  Newspaper,
  Search,
  TrendingUp,
  ListChecks,
} from "lucide-react";

import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
// QA A-F-001/F-002 (2026-05-21): shared selection contract.
import { qk } from "@/lib/query/keys";
import { useResolvedPortfolioId } from "@/hooks/useResolvedPortfolioId";
import {
  formatPrice,
  formatPercentDirect,
  formatVolume,
  formatPercent,
  cn,
  safeExternalUrl,
} from "@/lib/utils";
import type { ParsedCommand } from "@/lib/chat/slash-commands";
import type {
  Quote,
  Portfolio,
  HoldingsResponse,
  RankedNewsResponse,
  Watchlist,
  AlertsResponse,
} from "@/types/api";

// ── Props ─────────────────────────────────────────────────────────────────────

export interface SlashCommandCardProps {
  command: ParsedCommand;
}

// ── Card chrome ───────────────────────────────────────────────────────────────

/**
 * CardShell — shared wrapper that mirrors the assistant-message bubble.
 *
 * WHY mimic the assistant bubble: the card sits in the chat log right where
 * an assistant answer would sit. Visually it should read as "the assistant
 * pulled this data for you" — same width cap, same muted background, same
 * left-aligned bot icon. Slight colour shift (border-primary/20) gives a
 * subtle hint that this is a structured card, not free-form text.
 */
function CardShell({
  icon,
  title,
  children,
}: {
  icon: React.ReactNode;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex flex-col items-start gap-1">
      <div className="flex max-w-[90%] items-end gap-2">
        <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-[2px] bg-primary/20">
          {icon}
        </div>
        <div
          className={cn(
            "min-w-[280px] rounded-[2px] border border-primary/20 bg-muted px-3 py-2",
            "font-mono tabular-nums text-foreground",
          )}
        >
          {/* Header: small uppercase label so the user can see at a glance which
              command produced the card. */}
          <div className="mb-1.5 text-[10px] uppercase tracking-[0.06em] text-muted-foreground">
            {title}
          </div>
          {children}
        </div>
      </div>
    </div>
  );
}

/**
 * CardSkeleton — pulsing placeholder for loading state. Matches the height
 * of a typical card so the chat log doesn't jump when data resolves.
 */
function CardSkeleton({ rows = 3 }: { rows?: number }) {
  return (
    <div className="space-y-1">
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="h-3 w-full rounded-[2px] bg-muted-foreground/10" />
      ))}
    </div>
  );
}

/**
 * CardError — minimal error display. We intentionally do not include a retry
 * button — the user can just rerun the slash command from the input.
 */
function CardError({ message }: { message: string }) {
  return (
    <div className="text-[11px] text-destructive">
      {message}
    </div>
  );
}

// ── Quote card ────────────────────────────────────────────────────────────────

/**
 * QuoteCard — "/quote AAPL" → real-time quote + change% + volume
 *
 * WHY ticker as instrument_id: S9's /v1/quotes/{instrument_id} accepts both
 * UUID and ticker symbols (verified via gateway tests). Avoids a separate
 * search round-trip for the common case.
 *
 * WHY staleTime 5_000ms: quotes are real-time-ish but the gateway already
 * caches at 5s in Valkey. Matching the upstream cache means re-issuing the
 * same /quote command twice doesn't fight the cache.
 */
function QuoteCard({ ticker }: { ticker: string }) {
  const { accessToken } = useAuth();
  const { data, isLoading, error } = useQuery<Quote>({
    queryKey: ["slash-quote", ticker, accessToken],
    queryFn: () => createGateway(accessToken).getQuote(ticker),
    enabled: !!accessToken,
    // WHY 5s: matches S9 Valkey TTL — repeated quote commands in a session
    // hit the cache, not a fresh upstream call.
    staleTime: 5_000,
  });

  return (
    <CardShell icon={<TrendingUp className="h-3.5 w-3.5 text-primary" strokeWidth={1.5} />} title={`Quote: ${ticker}`}>
      {isLoading && <CardSkeleton rows={2} />}
      {error && <CardError message="Failed to load quote." />}
      {data && (
        <div className="flex items-center gap-3 text-[11px]">
          {/* Price headline */}
          <div className="text-[11px] font-semibold text-foreground">
            {formatPrice(data.price)}
          </div>
          {/* Change pill — green/red coloured per change direction */}
          <div
            className={cn(
              "rounded-[2px] px-1.5 py-0.5 text-[11px]",
              data.change_pct >= 0
                ? "bg-positive/10 text-positive"
                : "bg-negative/10 text-negative",
            )}
          >
            {formatPercentDirect(data.change_pct)}
          </div>
          {/* Volume — compact format because tight horizontal layout */}
          <div className="text-[11px] text-muted-foreground">
            Vol {formatVolume(data.volume ?? 0)}
          </div>
        </div>
      )}
    </CardShell>
  );
}

// ── Portfolio card ───────────────────────────────────────────────────────────

/**
 * PortfolioCard — "/portfolio" → top portfolio's headline value + day P&L
 *
 * WHY default portfolio (first one): MVP scope. Multi-portfolio resolution
 * by name is a future enhancement; today the user typically has one or two.
 */
function PortfolioCard() {
  const { accessToken } = useAuth();
  // QA A-F-001 (2026-05-21): central qk.portfolios.list() shares cache
  // with PortfolioSwitcher / dashboard widgets; pre-fix the bare
  // `["slash-portfolios", accessToken]` key forked the cache.
  const { data: portfolios, isLoading: pLoading } = useQuery<Portfolio[]>({
    queryKey: qk.portfolios.list(),
    queryFn: () => createGateway(accessToken).getPortfolios(),
    enabled: !!accessToken,
    staleTime: 30_000,
  });

  // QA A-F-002 (2026-05-21): respect the PortfolioSwitcher chip
  // selection. Pre-fix the chat slash command always targeted
  // portfolios[0] regardless of which portfolio the user had picked
  // in the TopBar.
  const resolvedPortfolioId = useResolvedPortfolioId(portfolios);
  const portfolio =
    portfolios?.find((p) => p.portfolio_id === resolvedPortfolioId) ?? null;

  const { data: holdings, isLoading: hLoading, error } = useQuery<HoldingsResponse>({
    queryKey: ["slash-holdings", portfolio?.portfolio_id, accessToken],
    queryFn: () => createGateway(accessToken).getHoldings(portfolio!.portfolio_id),
    enabled: !!accessToken && !!portfolio,
    staleTime: 15_000, // WHY 15s: holdings aggregate price ticks; semi-fresh.
  });

  return (
    <CardShell icon={<Briefcase className="h-3.5 w-3.5 text-primary" strokeWidth={1.5} />} title="Portfolio summary">
      {(pLoading || hLoading) && <CardSkeleton rows={3} />}
      {error && <CardError message="Failed to load portfolio." />}
      {!pLoading && !portfolio && !error && (
        <div className="text-[11px] text-muted-foreground">No portfolio yet.</div>
      )}
      {holdings && portfolio && (
        <div className="grid grid-cols-3 gap-3 text-[11px]">
          <div>
            <div className="text-[10px] uppercase text-muted-foreground">Total value</div>
            <div className="text-[11px] font-semibold text-foreground">
              {formatPrice(holdings.total_value)}
            </div>
          </div>
          <div>
            <div className="text-[10px] uppercase text-muted-foreground">Unreal P&amp;L</div>
            <div
              className={cn(
                "text-[11px] font-semibold",
                (holdings.total_unrealised_pnl ?? 0) >= 0
                  ? "text-positive"
                  : "text-negative",
              )}
            >
              {formatPrice(holdings.total_unrealised_pnl)}
              {holdings.total_unrealised_pnl_pct != null && (
                <span className="ml-1 text-[11px]">
                  ({formatPercent(holdings.total_unrealised_pnl_pct / 100)})
                </span>
              )}
            </div>
          </div>
          <div>
            <div className="text-[10px] uppercase text-muted-foreground">Holdings</div>
            <div className="text-[11px] font-semibold text-foreground">
              {holdings.holdings.length}
            </div>
          </div>
        </div>
      )}
    </CardShell>
  );
}

// ── News card ─────────────────────────────────────────────────────────────────

/**
 * NewsCard — "/news" or "/news SECTOR=tech" → 5 most recent ranked articles
 *
 * WHY top-news endpoint (not legacy news): the ranked endpoint already gives
 * us display_relevance_score + sentiment + source so we can render a richer
 * pill per row without extra calls.
 *
 * WHY ignore SECTOR= for now (best-effort): the ranked endpoint takes hours
 * + min_display_score, not a sector filter. We accept the param to keep the
 * parser permissive but a future wave can pipe SECTOR into the request.
 */
function NewsCard({ params }: { params: Record<string, string> }) {
  const { accessToken } = useAuth();
  // Accept the param even though we don't push it through (yet) — keeps the
  // queryKey unique so /news SECTOR=tech and /news fetch independent caches.
  const { data, isLoading, error } = useQuery<RankedNewsResponse>({
    queryKey: ["slash-news-top", params.sector ?? null, accessToken],
    queryFn: () => createGateway(accessToken).getTopNews({ hours: 24, limit: 5 }),
    enabled: !!accessToken,
    staleTime: 60_000, // 1 min — news cards refresh on every send anyway.
  });

  return (
    <CardShell icon={<Newspaper className="h-3.5 w-3.5 text-primary" strokeWidth={1.5} />} title="Recent news">
      {isLoading && <CardSkeleton rows={5} />}
      {error && <CardError message="Failed to load news." />}
      {data && (
        <ul className="space-y-1 text-[11px]">
          {data.articles.slice(0, 5).map((a) => (
            <li key={a.article_id} className="flex items-start gap-2">
              {/* Sentiment pill — positive/negative/neutral colour cue */}
              <span
                className={cn(
                  "mt-0.5 shrink-0 rounded-[2px] px-1 text-[9px] uppercase",
                  a.sentiment === "positive" && "bg-positive/15 text-positive",
                  a.sentiment === "negative" && "bg-negative/15 text-negative",
                  (!a.sentiment || a.sentiment === "neutral" || a.sentiment === "mixed") &&
                    "bg-muted-foreground/10 text-muted-foreground",
                )}
              >
                {a.sentiment ?? "—"}
              </span>
              <a
                href={safeExternalUrl(a.url ?? "")}
                target="_blank"
                rel="noopener noreferrer"
                className="flex-1 truncate text-foreground hover:text-primary"
              >
                {a.title ?? "Untitled"}
              </a>
              <span className="shrink-0 text-[10px] text-muted-foreground">
                {a.source_name ?? "—"}
              </span>
            </li>
          ))}
        </ul>
      )}
    </CardShell>
  );
}

// ── Watchlist card ───────────────────────────────────────────────────────────

/**
 * WatchlistCard — "/watchlist <NAME>" → members + per-row price/change.
 *
 * WHY name lookup: the user types the watchlist NAME, not its UUID. We
 * fetch the list of all watchlists, find the matching one (case-insensitive),
 * and fall through gracefully if no match.
 */
function WatchlistCard({ name }: { name: string }) {
  const { accessToken } = useAuth();
  const { data: lists, isLoading: lLoading } = useQuery<Watchlist[]>({
    queryKey: ["slash-watchlists", accessToken],
    queryFn: () => createGateway(accessToken).getWatchlists(),
    enabled: !!accessToken,
    staleTime: 60_000,
  });

  const matched = lists?.find(
    (w) => w.name.toLowerCase() === name.toLowerCase(),
  );

  return (
    <CardShell
      icon={<ListChecks className="h-3.5 w-3.5 text-primary" strokeWidth={1.5} />}
      title={`Watchlist: ${name}`}
    >
      {lLoading && <CardSkeleton rows={3} />}
      {!lLoading && !matched && (
        <div className="text-[11px] text-muted-foreground">
          No watchlist named &ldquo;{name}&rdquo;.
        </div>
      )}
      {matched && (
        <ul className="space-y-0.5 text-[11px]">
          {matched.members.slice(0, 8).map((m) => (
            <li
              key={m.entity_id}
              className="flex items-center justify-between gap-2"
            >
              <span className="font-semibold text-foreground">
                {m.ticker ?? "—"}
              </span>
              <span className="truncate text-muted-foreground">{m.name}</span>
            </li>
          ))}
          {matched.members.length === 0 && (
            <li className="text-muted-foreground">Empty watchlist.</li>
          )}
        </ul>
      )}
    </CardShell>
  );
}

// ── Alerts card ───────────────────────────────────────────────────────────────

/**
 * AlertsCard — "/alerts" → top 5 active (pending) alerts
 *
 * WHY pending only: active = unacknowledged. A trader using "/alerts"
 * wants the action queue, not historical noise.
 */
function AlertsCard() {
  const { accessToken } = useAuth();
  const { data, isLoading, error } = useQuery<AlertsResponse>({
    queryKey: ["slash-alerts-pending", accessToken],
    queryFn: () => createGateway(accessToken).getPendingAlerts({ limit: 5 }),
    enabled: !!accessToken,
    staleTime: 15_000,
  });

  return (
    <CardShell icon={<AlertCircle className="h-3.5 w-3.5 text-primary" strokeWidth={1.5} />} title="Active alerts">
      {isLoading && <CardSkeleton rows={3} />}
      {error && <CardError message="Failed to load alerts." />}
      {data && data.alerts.length === 0 && (
        <div className="text-[11px] text-muted-foreground">No active alerts.</div>
      )}
      {data && data.alerts.length > 0 && (
        <ul className="space-y-0.5 text-[11px]">
          {data.alerts.slice(0, 5).map((a) => (
            <li key={a.alert_id} className="flex items-center gap-2">
              <span
                className={cn(
                  "rounded-[2px] px-1 text-[9px] uppercase",
                  a.severity === "CRITICAL" && "bg-negative/20 text-negative",
                  a.severity === "HIGH" && "bg-warning/20 text-warning",
                  a.severity === "MEDIUM" && "bg-warning/10 text-warning",
                  a.severity === "LOW" && "bg-muted-foreground/15 text-muted-foreground",
                )}
              >
                {a.severity}
              </span>
              <span className="font-semibold text-foreground">
                {a.ticker ?? a.entity_id.slice(0, 6)}
              </span>
              <span className="flex-1 truncate text-muted-foreground">
                {a.title ?? a.signal_label ?? a.alert_type}
              </span>
            </li>
          ))}
        </ul>
      )}
    </CardShell>
  );
}

// ── Screener card ────────────────────────────────────────────────────────────

/**
 * ScreenerCard — "/screener" → static link card to the screener page.
 *
 * WHY just a link: the screener has rich filtering UX that doesn't fit a
 * compact card. Pointing the user to the dedicated page is the right answer.
 */
function ScreenerCard() {
  return (
    <CardShell icon={<Search className="h-3.5 w-3.5 text-primary" strokeWidth={1.5} />} title="Screener">
      <Link
        href="/screener"
        className="text-[11px] text-primary hover:text-primary/80"
      >
        Open screener →
      </Link>
    </CardShell>
  );
}

// ── Dispatcher ───────────────────────────────────────────────────────────────

/**
 * SlashCommandCard — main entry. Switches on the parsed command kind and
 * renders the matching card. Unknown kinds render a tiny diagnostic note
 * (which should never be hit in practice — parseInput already filters
 * unknown verbs to `null`, in which case the chat page never invokes this
 * component).
 */
export function SlashCommandCard({ command }: SlashCommandCardProps) {
  switch (command.kind) {
    case "quote":
      return <QuoteCard ticker={command.params.ticker ?? ""} />;
    case "portfolio":
      return <PortfolioCard />;
    case "news":
      return <NewsCard params={command.params} />;
    case "watchlist":
      return <WatchlistCard name={command.params.name ?? ""} />;
    case "alerts":
      return <AlertsCard />;
    case "screener":
      return <ScreenerCard />;
    default:
      return (
        <CardShell icon={<Search className="h-3.5 w-3.5 text-primary" strokeWidth={1.5} />} title="Unknown command">
          <CardError message={`Unknown slash command: /${command.kind}`} />
        </CardShell>
      );
  }
}
