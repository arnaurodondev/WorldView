import { useQuery } from "@tanstack/react-query";
import { gateway, OutcomePrice, PredictionMarketSummary } from "../lib/gateway-client";

// ── Helpers ──────────────────────────────────────────────

function formatVolume(vol: number | null): string {
  if (vol === null) return "—";
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    notation: "compact",
    maximumFractionDigits: 1,
  }).format(vol);
}

// eslint-disable-next-line react-refresh/only-export-components
export function formatCloseTime(isoDate: string | null): string | null {
  if (!isoDate) return null;
  const diffMs = new Date(isoDate).getTime() - Date.now();
  if (diffMs <= 0) return "closed";
  const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));
  if (diffDays === 0) return "closes today";
  if (diffDays === 1) return "closes in 1 day";
  return `closes in ${diffDays} days`;
}

function yesOutcome(outcomes: OutcomePrice[]): OutcomePrice | null {
  return outcomes.find((o) => o.name.toLowerCase() === "yes") ?? outcomes[0] ?? null;
}

// ── Skeleton ─────────────────────────────────────────────

function SkeletonRow() {
  return (
    <div
      style={{
        height: 72,
        background: "var(--border, #e5e7eb)",
        borderRadius: 6,
        marginBottom: "0.75rem",
        opacity: 0.5,
      }}
    />
  );
}

// ── Market card ───────────────────────────────────────────

function MarketCard({ market }: { market: PredictionMarketSummary }) {
  const yes = yesOutcome(market.outcomes);
  const yesPct = yes ? Math.round(yes.price * 100) : 0;
  const closeLabel = market.close_time ? formatCloseTime(market.close_time) : null;

  const truncatedQuestion =
    market.question.length > 120 ? market.question.slice(0, 120) + "…" : market.question;

  return (
    <div
      style={{
        border: "1px solid var(--border, #e5e7eb)",
        borderRadius: 6,
        padding: "0.75rem 1rem",
        marginBottom: "0.75rem",
      }}
    >
      <p
        title={market.question}
        style={{ margin: "0 0 0.5rem", fontSize: "0.875rem", fontWeight: 500 }}
      >
        {truncatedQuestion}
      </p>

      {/* Probability bar */}
      <div
        style={{
          height: 8,
          background: "var(--border, #e5e7eb)",
          borderRadius: 4,
          overflow: "hidden",
          marginBottom: "0.4rem",
        }}
      >
        <div
          data-testid="probability-bar-fill"
          style={{
            width: `${yesPct}%`,
            height: "100%",
            background: yesPct >= 50 ? "#22c55e" : "#ef4444",
            borderRadius: 4,
          }}
        />
      </div>

      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          fontSize: "0.75rem",
          color: "var(--text-secondary, #6b7280)",
        }}
      >
        <span>
          {market.outcomes.map((o) => `${Math.round(o.price * 100)}% ${o.name}`).join(" · ")}
        </span>
        <span>
          {closeLabel && <span>{closeLabel}</span>}
          {market.volume_24h !== null && (
            <span style={{ marginLeft: closeLabel ? "0.5rem" : 0 }}>
              Vol: {formatVolume(market.volume_24h)}
            </span>
          )}
        </span>
      </div>
    </div>
  );
}

// ── Panel ─────────────────────────────────────────────────

export function PredictionMarketsPanel() {
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ["prediction-markets"],
    queryFn: () => gateway.getPredictionMarkets({ status: "open", limit: 20 }),
    refetchInterval: 5 * 60 * 1000,
  });

  const items = data?.items ?? [];
  const sorted = [...items].sort((a, b) => {
    if (a.volume_24h === null && b.volume_24h === null) return 0;
    if (a.volume_24h === null) return 1;
    if (b.volume_24h === null) return -1;
    return b.volume_24h - a.volume_24h;
  });

  return (
    <section style={{ marginTop: "2rem" }}>
      <h3
        style={{
          margin: "0 0 1rem",
          borderTop: "1px solid var(--border, #e5e7eb)",
          paddingTop: "0.75rem",
        }}
      >
        Prediction Markets
      </h3>

      {isLoading && (
        <>
          <SkeletonRow />
          <SkeletonRow />
          <SkeletonRow />
        </>
      )}

      {error && !isLoading && (
        <div style={{ textAlign: "center", color: "var(--text-secondary, #6b7280)" }}>
          <p>Failed to load prediction markets</p>
          <button
            onClick={() => void refetch()}
            style={{ color: "var(--accent, #4f8ef7)", background: "none", border: "none", cursor: "pointer" }}
          >
            Retry
          </button>
        </div>
      )}

      {!isLoading && !error && sorted.length === 0 && (
        <p style={{ textAlign: "center", color: "var(--text-secondary, #6b7280)" }}>
          No active prediction markets
        </p>
      )}

      {!isLoading && !error && sorted.map((market) => (
        <MarketCard key={market.market_id} market={market} />
      ))}
    </section>
  );
}
