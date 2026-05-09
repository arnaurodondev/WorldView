/**
 * app/(app)/prediction-markets/page.tsx — Prediction Markets browser
 *
 * WHY THIS EXISTS: The PredictionMarketsWidget on the dashboard links to this page
 * via `<Link href="/prediction-markets">`. Without this page, that link returns a
 * Next.js 404 (BP-383: missing page linked from dashboard widget).
 *
 * DATA SOURCE: S9 GET /v1/signals/prediction-markets via gateway.getPredictionMarkets().
 * Populated by the content-ingestion Polymarket adapter (gamma-api.polymarket.com
 * → market.prediction.v1 Kafka → S3 market-data DB).
 *
 * DESIGN: Full-page browser with category filter pills, text search, and a
 * probability bar per market. Matches the terminal dark aesthetic (11px mono, 22px rows).
 */

"use client";
// WHY "use client": uses useQuery for paginated market data + useState for filters.

import { useQuery } from "@tanstack/react-query";
import { useState, useMemo } from "react";
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { Skeleton } from "@/components/ui/skeleton";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
// HF-10: shared compact-currency formatter for "$1.2M" / "$42.5K" output.
import { formatCompactCurrency } from "@/lib/format";
import { TrendingUp, Search, AlertCircle } from "lucide-react";
import type { PredictionMarket } from "@/types/api";

// ── Category filter pills ─────────────────────────────────────────────────────

// WHY "all" sentinel: gateway doesn't support null category param; we use "all"
// client-side to mean "show everything" and filter on market.category locally.
const CATEGORIES = ["all", "politics", "crypto", "sports", "macro"] as const;
type Category = (typeof CATEGORIES)[number];

// ── Probability bar ───────────────────────────────────────────────────────────

function ProbabilityBar({ probability }: { probability: number }) {
  // WHY clamp: Polymarket prices can briefly exceed [0,1] during liquidity events.
  const pct = Math.round(Math.min(1, Math.max(0, probability)) * 100);
  const barClass =
    pct >= 70
      ? "bg-[hsl(142,76%,36%)]" // green — high YES probability
      : pct >= 40
        ? "bg-[hsl(45,93%,47%)]" // yellow — uncertain
        : "bg-[hsl(0,72%,51%)]"; // red — low probability

  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 flex-1 rounded-full bg-muted/40">
        <div className={cn("h-full rounded-full transition-all", barClass)} style={{ width: `${pct}%` }} />
      </div>
      <span className="w-9 text-right font-mono text-[11px] tabular-nums text-foreground">{pct}%</span>
    </div>
  );
}

// ── Market row ────────────────────────────────────────────────────────────────

function MarketRow({ market }: { market: PredictionMarket }) {
  const volume = market.volume_usd ?? 0;
  // HF-10: delegate to the shared formatter ("$1.2M" / "$42.5K" / "$847.00").
  const formattedVolume = formatCompactCurrency(volume, "USD", { maxDecimals: 1 });

  const closeDate = market.resolution_date ? new Date(market.resolution_date) : null;
  const daysLeft = closeDate
    ? Math.max(0, Math.round((closeDate.getTime() - Date.now()) / 86_400_000))
    : null;

  // WHY link to polymarket.com: the prediction markets page is a read-only view;
  // trading happens on Polymarket's platform. market.url is pre-built by the gateway.
  const handleRowClick = () => {
    if (market.url) window.open(market.url, "_blank", "noopener,noreferrer");
  };

  return (
    <div
      role={market.url ? "link" : undefined}
      onClick={market.url ? handleRowClick : undefined}
      className={cn(
        "grid grid-cols-[1fr_160px_80px_80px] items-center gap-3 border-b border-border/30 px-4 py-2.5",
        market.url && "cursor-pointer hover:bg-card/60",
      )}
    >
      {/* Question + category badge */}
      <div className="min-w-0">
        <p className="truncate text-[11px] text-foreground">{market.title}</p>
        {market.category && (
          <span className="mt-0.5 inline-block font-mono text-[9px] uppercase tracking-wider text-muted-foreground">
            {market.category}
          </span>
        )}
      </div>

      {/* YES probability bar */}
      <ProbabilityBar probability={market.yes_probability} />

      {/* 24h volume */}
      <span className="text-right font-mono text-[10px] tabular-nums text-muted-foreground">{formattedVolume}</span>

      {/* Days until close */}
      <span className="text-right font-mono text-[10px] tabular-nums text-muted-foreground">
        {daysLeft !== null ? `${daysLeft}d` : "—"}
      </span>
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function PredictionMarketsPage() {
  const { accessToken } = useAuth();
  const [search, setSearch] = useState("");
  const [category, setCategory] = useState<Category>("all");

  // WHY limit=200: load a large set of open markets once; client-side filter is
  // fast at this scale (~200 records). Avoids re-fetching on each category switch.
  const { data, isLoading, isError } = useQuery({
    queryKey: ["prediction-markets-page"],
    queryFn: () =>
      createGateway(accessToken).getPredictionMarkets({ status: "open", limit: 200 }),
    enabled: !!accessToken,
    staleTime: 60_000,
  });

  const markets: PredictionMarket[] = useMemo(() => {
    if (!data?.markets) return [];
    let result = data.markets;

    // Client-side category filter — keeps the API call simple (single fetch)
    if (category !== "all") {
      result = result.filter((m) => m.category?.toLowerCase() === category);
    }

    // Text search on title + category
    if (search.trim()) {
      const q = search.toLowerCase();
      result = result.filter(
        (m) =>
          m.title.toLowerCase().includes(q) ||
          (m.category ?? "").toLowerCase().includes(q),
      );
    }

    return result;
  }, [data, category, search]);

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-hidden bg-background">

      {/* ── Page header ─────────────────────────────────────────────────────── */}
      <div className="border-b border-border/50 px-5 py-3">
        <div className="flex items-center gap-2">
          <TrendingUp className="h-4 w-4 text-muted-foreground" strokeWidth={1.5} />
          <h1 className="text-[11px] font-medium uppercase tracking-[0.1em] text-foreground">
            Prediction Markets
          </h1>
          {data?.total != null && (
            <Badge variant="outline" className="ml-auto font-mono text-[9px]">
              {data.total.toLocaleString()} open
            </Badge>
          )}
        </div>

        {/* Category pills + search */}
        <div className="mt-2.5 flex items-center gap-2">
          <div className="flex gap-1">
            {CATEGORIES.map((cat) => (
              <button
                key={cat}
                onClick={() => setCategory(cat)}
                className={cn(
                  "rounded-[2px] px-2 py-0.5 font-mono text-[9px] uppercase tracking-wider transition-colors",
                  category === cat
                    ? "bg-[hsl(45,93%,47%)] text-black"
                    : "bg-muted/30 text-muted-foreground hover:bg-muted/60 hover:text-foreground",
                )}
              >
                {cat}
              </button>
            ))}
          </div>

          <div className="relative ml-auto w-52">
            <Search className="absolute left-2 top-1/2 h-3 w-3 -translate-y-1/2 text-muted-foreground" strokeWidth={1.5} />
            <Input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search markets…"
              autoComplete="off"
              className="h-6 pl-6 font-mono text-[10px]"
            />
          </div>
        </div>
      </div>

      {/* ── Column headers ───────────────────────────────────────────────────── */}
      <div className="grid grid-cols-[1fr_160px_80px_80px] gap-3 border-b border-border/50 px-4 py-1.5">
        {(["Question", "YES probability", "24h Vol", "Closes"] as const).map((label) => (
          <span
            key={label}
            className={cn(
              "font-mono text-[9px] uppercase tracking-wider text-muted-foreground",
              label !== "Question" && "text-right",
            )}
          >
            {label}
          </span>
        ))}
      </div>

      {/* ── Market list ─────────────────────────────────────────────────────── */}
      <div className="flex-1 overflow-y-auto">
        {isLoading &&
          Array.from({ length: 14 }).map((_, i) => (
            <div key={i} className="border-b border-border/30 px-4 py-2.5">
              <Skeleton className="h-3 w-3/4" />
              <Skeleton className="mt-1.5 h-1.5 w-full" />
            </div>
          ))}

        {isError && !isLoading && (
          <div className="flex flex-col items-center justify-center gap-2 py-16 text-muted-foreground">
            <AlertCircle className="h-5 w-5" strokeWidth={1.5} />
            <p className="text-[11px]">Failed to load prediction markets</p>
            <p className="text-[10px] text-muted-foreground/60">
              The Polymarket data pipeline may still be populating.
            </p>
          </div>
        )}

        {!isLoading && !isError && markets.length === 0 && (
          <div className="flex flex-col items-center justify-center gap-2 py-16 text-muted-foreground">
            <TrendingUp className="h-5 w-5" strokeWidth={1.5} />
            <p className="text-[11px]">
              {search || category !== "all" ? "No markets match your filters" : "No prediction markets available"}
            </p>
            {!search && category === "all" && (
              <p className="text-[10px] text-muted-foreground/60">
                Run <code className="font-mono text-[9px]">make seed</code> to populate Polymarket data.
              </p>
            )}
          </div>
        )}

        {!isLoading && !isError && markets.map((m) => (
          <MarketRow key={m.market_id} market={m} />
        ))}
      </div>
    </div>
  );
}
