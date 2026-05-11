# ADR: EODHD API Failover Strategy

**Status**: Accepted
**Date**: 2026-04-24
**Deciders**: Platform Team
**Context**: PLAN-0036 — EODHD API Usage Reduction

---

### Context

EODHD is the primary market data provider for the Worldview platform. It is used for
real-time quotes, EOD bars, fundamentals, economic events, and macro indicators.

When EODHD is unavailable — due to quota exhaustion, planned maintenance, or unexpected
API changes — the platform must degrade gracefully rather than return errors to users.
Two failure modes require distinct handling:

1. **Transient unavailability** — a brief outage or rate-limit burst that resolves within minutes.
2. **Quota exhaustion** — the monthly credit budget is consumed before the billing cycle resets.

Without an explicit failover strategy, both modes would surface as HTTP 5xx errors on the
`/api/v1/quotes` endpoint, breaking the frontend entirely.

---

### Decision

The failover chain for price data (implemented in PLAN-0036 Wave 1) is:

```
1. fresh_quote    — direct EODHD real-time quote            (age < 5 min)
2. bulk_quote     — EODHD bulk snapshot                     (age < 15 min)
3. intraday_5m    — last known 5-minute intraday bar         (age < 1 hr)
4. intraday_1h    — last known 1-hour bar                   (age < 4 hr)
5. daily_close    — last EOD close                          (age < 24 hr)
6. stale_snapshot — cached PriceSnapshot from DB            (age > 24 hr, marked stale)
7. unavailable    — no data available at any freshness level
```

Each step is attempted in order. The first step that returns data wins.

Steps 1–2 require a live EODHD call. Steps 3–6 are served entirely from the local database
(`price_snapshots` and `ohlcv_bars` tables in `market_data_db`). Step 7 is returned as a
structured response (not a 5xx error) so the frontend can render a meaningful empty state.

#### Frontend display rules

| Step | Freshness class | UI treatment |
|------|----------------|--------------|
| 1–2 | `live` | Normal price color, no prefix |
| 3–4 | `intraday_stale` | Muted color, "~" prefix in IndexTicker |
| 5 | `eod` | Muted color, "~" prefix |
| 6 | `stale` | Dimmed color, "~" prefix, tooltip showing data age |
| 7 | `unavailable` | "—" placeholder, no price shown |

---

### Circuit Breaker

A circuit breaker (Valkey-backed, sliding window of 100 calls) protects against cascading
failures. It opens when either condition is met:

- **Error rate** > 50% within the sliding window, OR
- **Monthly quota** > 95% consumed (enforced via a Valkey counter reset on the 1st of each month)

When the circuit breaker is open:
- All EODHD API calls are blocked for `CIRCUIT_BREAKER_RECOVERY_SECONDS` (default: 300 s).
- Price requests fall through to steps 3–7 of the failover chain.
- The Prometheus gauge `eodhd_circuit_breaker_state` is set to `1` (open).
- An alert fires: `EodhdCircuitBreakerOpen` (see runbook `docs/runbooks/market-ingestion-operations.md`).

The circuit breaker transitions through three states:

```
closed ──(threshold exceeded)──► open ──(recovery timeout)──► half_open
  ▲                                                                │
  └──────────────(probe succeeds)─────────────────────────────────┘
```

Implementation: `services/market-ingestion/src/market_ingestion/infrastructure/adapters/circuit_breaker.py`

---

### Alternative Providers

Secondary providers are available as future fallback sources for OHLCV bars:

| Provider | Cost | Rate limit | Quality | Notes |
|----------|------|-----------|---------|-------|
| Yahoo Finance | Free | ~2,000 req/hr | Good | No API key required; adapter exists at `infrastructure/adapters/providers/yahoo.py` |
| Alpha Vantage | Free tier | 5 req/min | Good | Requires API key; `MARKET_INGESTION_ALPHA_VANTAGE_API_KEY` |
| Polygon | Paid | High | Excellent | Best for intraday data; not yet integrated |

Automatic routing to secondary providers when the EODHD circuit is open is **not yet
implemented**. When the circuit is open, prices are served from the stale PriceSnapshot
layer (steps 3–6) only. Secondary provider routing is planned for a future wave (see
PLAN-0036 Wave 4 scope note, out of scope for v1).

Manual fallback is possible by setting `MARKET_INGESTION_EODHD_ENABLED=false` and
configuring a secondary provider. See the operations runbook for emergency procedures.

---

### Consequences

#### Positive

- Platform remains functional during EODHD outages — users see stale data rather than errors.
- Monthly quota is enforced automatically — no risk of surprise overage charges.
- Graceful degradation is transparent to downstream services (market-data, S9, frontend).
- The 7-step chain can be extended in future without breaking existing consumers.

#### Negative

- Stale prices (steps 5–6) may mislead traders during extended outages (> 24 hr).
- No automatic failover to secondary providers in v1 — operator intervention required.
- The "~" prefix UX is non-standard and requires user education / tooltip documentation.
- Valkey counter is reset manually after a billing cycle reset; automation is deferred.

#### Neutral

- The PriceSnapshot table adds a small write overhead on every successful EODHD fetch.
- Derived 1W/1M bars (from daily bars) are always available regardless of EODHD state.

---

### Alternatives Considered

| Alternative | Pros | Cons | Why Rejected |
|-------------|------|------|--------------|
| Return HTTP 503 on EODHD failure | Simple; easy to reason about | Breaks frontend entirely; poor UX | Users deserve best-effort stale data |
| Auto-failover to Yahoo Finance | Transparent to users | Yahoo ToS restrictions on commercial use; reliability concerns | Deferred to future wave; not v1 scope |
| Cache all quotes in Redis with TTL | Fast reads | Memory pressure; complex invalidation; still needs a live source | PriceSnapshot in Postgres is simpler and durable |
| Raise quota limit with EODHD | No degradation | Costs money; doesn't address transient outages | Cost control is a primary requirement |

---

### References

- PLAN-0036 plan file: `docs/plans/0036-plan.md`
- Operations runbook: `docs/runbooks/market-ingestion-operations.md` (Section 6)
- Circuit breaker implementation: `services/market-ingestion/src/market_ingestion/infrastructure/adapters/circuit_breaker.py`
- PriceSnapshot entity: `services/market-data/src/market_data/domain/entities.py` (`PriceSnapshot.freshness`)
- Valkey key taxonomy: `docs/architecture/decisions/0004-valkey-key-taxonomy.md`
