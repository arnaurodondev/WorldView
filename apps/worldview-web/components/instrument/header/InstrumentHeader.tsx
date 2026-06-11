/**
 * components/instrument/header/InstrumentHeader.tsx — sticky 36px page header
 *
 * WHY THIS EXISTS: PRD-0088 §6.4 — Bloomberg-style compact header pinned
 * while scrolling; mono numbers, color-coded P&L, 60×6px WeekRangeMini.
 * WHO USES IT: components/instrument/InstrumentPageClient.tsx (T-A-05).
 * DATA SOURCE: bundle.overview.instrument + quote + fundamentals.
 * DESIGN REFERENCE: docs/specs/0088-…-redesign.md §6.4 + §6.11.
 * TARGET READER: junior Next.js dev — all numeric cells use
 *              `font-mono tabular-nums` so digits line up vertically.
 */

"use client";
// WHY "use client": LiveQuoteBadge child polls via useQuery; the back
// button uses Next router. Both require the client runtime.

import { ChevronLeft } from "lucide-react";
import { useRouter } from "next/navigation";
import { LiveQuoteBadge } from "@/components/instrument/LiveQuoteBadge";
import {
  formatPrice,
  formatPercentDirect,
  formatMarketCap,
  formatVolume,
  formatRatio,
  priceChangeClass,
} from "@/lib/utils";
import type { Instrument, Quote, Fundamentals } from "@/types/api";
import { WeekRangeMini } from "./WeekRangeMini";

interface InstrumentHeaderProps {
  // WHY instrument is now nullable (audit 2026-05-20): the page-bundle request
  // can still be in flight when the parent first paints, and the prior strict
  // `Instrument` type forced InstrumentPageClient to gate the entire header
  // behind `bundle?.overview?.instrument` — making the sticky 36px row vanish
  // for the ~200ms warm-up window. Accepting null here lets us render the
  // chrome (back button + "—" fallbacks) immediately and fill values in place.
  readonly instrument: Instrument | null;
  readonly quote: Quote | null;
  readonly fundamentals: Fundamentals | null;
  /**
   * 30-day average daily volume from the page-bundle's fundamentals snapshot
   * (snapshot.avg_volume_30d). Round-1 requirement: the header shows today's
   * volume AGAINST its 30-day average so unusual activity is scannable.
   * Null while the bundle loads or when the backfill hasn't run.
   */
  readonly avgVolume30d?: number | null;
  /**
   * Best bid / best ask from the S9 quote payload (Wave-1 2026-06 backend).
   * NULLABLE BY DESIGN: most dev-data price sources are close snapshots
   * (intraday_1h_close / daily_close) that have no order book — the fields
   * are only populated when a fresh order-book quote backs the price. When
   * null the cell renders an honest "—×—" with a tooltip explaining why
   * (never a fake spread, never a blank).
   */
  readonly bid?: number | null;
  readonly ask?: number | null;
}

export function InstrumentHeader({
  instrument,
  quote,
  fundamentals,
  avgVolume30d = null,
  bid = null,
  ask = null,
}: InstrumentHeaderProps) {
  const router = useRouter();

  // WHY destructure with fallbacks: any sub-resource may be null while
  // the page is still warming up (quote arrives ~100ms after the
  // overview bundle). Rendering "—" placeholders keeps the layout
  // height stable so no jank when values arrive.
  const price = quote?.price ?? null;
  const change = quote?.change ?? null;
  const changePct = quote?.change_pct ?? null;
  // Round-1 fix: real session volume from the quote. The previous build
  // rendered fundamentals.daily_return through formatVolume as a "VOL proxy"
  // — a RETURN PERCENTAGE formatted as share count, i.e. always wrong.
  const volume = quote?.volume ?? null;

  // "VOL 52.3M / 30D 48.1M" — today's volume against its 30-day average.
  // WHY a ratio in the tooltip (not inline): the 36px header is too dense for
  // a third number; hover reveals "109% of 30-day average" for the curious.
  const volRatioTitle =
    volume != null && avgVolume30d != null && avgVolume30d > 0
      ? `${Math.round((volume / avgVolume30d) * 100)}% of 30-day average volume`
      : "Today's volume vs 30-day average";

  // Bid/ask spread — real values when the quote source carries an order book;
  // a NAMED "—×—" placeholder (with the reason in the tooltip) when it
  // doesn't. See the props doc: null is an honest state, not a bug.
  const bidAskText =
    bid != null && ask != null
      ? `${formatPrice(bid)}×${formatPrice(ask)}`
      : "—×—";
  const bidAskTitle =
    bid != null && ask != null
      ? `Spread ${formatPrice(Math.max(0, ask - bid))}`
      : "No live bid/ask — the current price source is a close snapshot without an order book";

  // WHY change_pct is already a percent (e.g. 1.42 means 1.42%):
  // S9 Quote returns it that way — see types/api.ts line 168. Use
  // formatPercentDirect (NOT formatPercent which expects a 0..1 ratio).
  const changeText = change != null && changePct != null
    ? `${change >= 0 ? "+" : ""}${formatPrice(change)} (${formatPercentDirect(changePct)})`
    : "—";

  return (
    // WHY sticky top-0 z-30: the header must stay pinned during scroll.
    // z-30 sits above tab content (z-10) but below modal overlays (z-50).
    // h-9 = 36px exactly (Tailwind: 9 × 4px = 36px) per spec §6.4.
    <header className="sticky top-0 z-30 flex h-9 items-center gap-4 border-b border-border bg-background px-3">
      {/* ── Left cluster: back button + ticker + exchange + company name ── */}
      <button
        type="button"
        onClick={() => router.back()}
        className="text-muted-foreground transition-colors hover:text-foreground"
        aria-label="Go back"
      >
        <ChevronLeft className="size-4" />
      </button>
      {/* WHY font-mono on ticker: tickers are conceptually code (AAPL, MSFT).
          Mono spacing matches the rest of the numeric row and is the
          IBM Plex Mono standard from docs/ui/DESIGN_SYSTEM.md §3. */}
      <span className="text-[13px] font-semibold tracking-wide font-mono">
        {instrument?.ticker ?? "—"}
      </span>
      {instrument?.exchange && (
        <span className="rounded-[2px] bg-muted/30 px-1.5 text-[10px] text-muted-foreground">
          {instrument.exchange}
        </span>
      )}
      <span className="max-w-[200px] truncate text-[11px] text-muted-foreground">
        {instrument?.name ?? ""}
      </span>

      {/* ── Right cluster: price + change + CAP/VOL/P/E + range bar + badge ── */}
      {/* WHY ml-auto: pushes the entire right cluster against the right edge
          without needing a 2-column grid. */}
      <div className="ml-auto flex items-center gap-3">
        <span className="text-[13px] font-semibold font-mono tabular-nums">
          {price != null ? formatPrice(price) : "—"}
        </span>
        <span className={`text-[12px] font-mono tabular-nums ${priceChangeClass(change)}`}>
          {changeText}
        </span>

        {/* WHY a thin separator pipe: spec §6.4 — visually splits price
            block from the secondary CAP/VOL/PE cluster. */}
        <span aria-hidden="true" className="text-muted-foreground/30">|</span>

        {/* Bid×ask cell — named placeholder until S9 exposes bid/ask (see
            props doc). title explains WHY it's empty so the dash is a state,
            not a mystery. */}
        <MetricCell label="B×A" value={bidAskText} title={bidAskTitle} />

        <MetricCell label="CAP" value={formatMarketCap(fundamentals?.market_cap ?? null)} />
        {/* Round-1 fix: VOL now reads quote.volume (real session volume).
            The old code formatted fundamentals.daily_return (a percentage!)
            through formatVolume — a nonsense number whenever it rendered. */}
        <MetricCell label="VOL" value={formatVolume(volume)} title={volRatioTitle} />
        {/* 30-day average volume — the comparison anchor for VOL. Data path:
            bundle.fundamentals_snapshot.avg_volume_30d → InstrumentPageClient
            → this prop. */}
        <MetricCell label="30D" value={formatVolume(avgVolume30d)} title={volRatioTitle} />
        <MetricCell label="P/E" value={formatRatio(fundamentals?.pe_ratio ?? null)} />

        <WeekRangeMini
          high={fundamentals?.week_52_high ?? null}
          low={fundamentals?.week_52_low ?? null}
          current={price}
        />

        {/* WHY compact mode: we already render price + change inline above,
            so LiveQuoteBadge only contributes the freshness dot + badge —
            no duplicate price display. */}
        {/* WHY guard on instrument_id: LiveQuoteBadge subscribes to a WS feed
            keyed off the id — no point firing the subscription before we know it. */}
        {instrument?.instrument_id && (
          <LiveQuoteBadge instrumentId={instrument.instrument_id} initialPrice={price} compact />
        )}
      </div>
    </header>
  );
}

// WHY a tiny internal helper: the B×A/CAP/VOL/30D/PE cells all share the same
// (10px muted label + 11px mono value) shape. Inlining the JSX 5x would
// add visual noise without saving any complexity.
// WHY optional `title`: VOL/30D expose the volume-vs-average ratio on hover
// and B×A explains its placeholder — native tooltips cost zero layout.
function MetricCell({ label, value, title }: {
  readonly label: string;
  readonly value: string;
  readonly title?: string;
}) {
  return (
    <span className="flex items-baseline gap-1" title={title}>
      <span className="text-[10px] text-muted-foreground">{label}</span>
      <span className="text-[11px] font-mono tabular-nums">{value}</span>
    </span>
  );
}
