/**
 * lib/api/portfolios.ts — Portfolio CRUD + holdings + analytics + transactions.
 *
 * SCOPE: portfolio list/create/delete, holdings (raw rows; live-quote enrichment
 * happens in the page layer), performance/exposure/risk/realized-PnL analytics,
 * transactions list/create, manual position add (BUY shortcut).
 *
 * WHY one file (not split per resource): every method here ultimately routes
 * through S1 (portfolio service) and shares the same Decimal-as-string
 * deserialisation pattern. Splitting holdings/transactions/analytics into
 * separate modules would multiply the import surface without buying isolation.
 */

import type {
  Portfolio,
  Holding,
  HoldingsResponse,
  TransactionsResponse,
  TransactionRequest,
  Transaction,
  ValueHistoryResponse,
  ExposureResponse,
  RiskMetricsResponse,
  RealizedPnLResponse,
  PaginationParams,
} from "@/types/api";
import { apiFetch } from "./_client";

export function createPortfoliosApi(t: string | undefined) {
  return {
    /**
     * getPortfolios — list authenticated user's portfolios
     *
     * WHY transform: S1 returns a paginated envelope `{items: [{id, owner_id, ...}], total, limit, offset}`
     * (PaginatedResponse<PortfolioResponse>) but frontend components expect a flat `Portfolio[]`
     * with `portfolio_id` (not `id`) and an `updated_at` field. The field rename is because the
     * S1 Pydantic schema uses `id` (database convention) while the frontend type uses `portfolio_id`
     * (domain convention from PRD-0027, ADR-F-12: explicit ID naming to avoid ambiguity).
     */
    async getPortfolios(): Promise<Portfolio[]> {
      // Fetch the raw paginated response from S1 (via S9 proxy)
      const raw = await apiFetch<{
        items: Array<{
          id: string;
          tenant_id: string;
          owner_id: string;
          name: string;
          currency: string;
          status: string;
          // PLAN-0046 Wave 3 / T-46-3-04 — kind discriminator from S1.
          // Optional in the type to keep older S9 builds backward-compatible
          // during rollout; once migration 0011 is everywhere this is always set.
          kind?: "manual" | "brokerage" | "root";
          created_at: string;
        }>;
        total: number;
        limit: number;
        offset: number;
      }>("/v1/portfolios", { token: t });

      // Transform each S1 PortfolioResponse into the frontend Portfolio type
      return (raw.items ?? []).map((p) => ({
        portfolio_id: p.id,
        name: p.name,
        currency: p.currency,
        owner_id: p.owner_id,
        created_at: p.created_at,
        // WHY default: S1 does not return updated_at on PortfolioResponse (it only has created_at).
        // Use created_at as fallback so components that display "last updated" still render.
        updated_at: p.created_at,
        // Forward the kind discriminator unchanged so the page can sort the ROOT
        // entry first and disable delete on aggregate portfolios.
        kind: p.kind,
      }));
    },

    /**
     * getHoldings — holdings + P&L summary for a portfolio
     *
     * WHY transform: S1 returns a bare `HoldingResponse[]` array (not the wrapped
     * `HoldingsResponse` object the frontend expects). Each S1 holding has `id` (not
     * `holding_id`) and lacks enriched fields like `ticker`, `name`, `current_price`,
     * `unrealised_pnl` etc. — those are computed client-side from batch quotes.
     * The frontend expects `HoldingsResponse = {portfolio_id, holdings: Holding[], total_value, ...}`.
     */
    async getHoldings(portfolioId: string): Promise<HoldingsResponse> {
      // S1 used to return a plain array of HoldingResponse, but PLAN-0046 QA
      // F-011 standardised the shape to the paginated envelope
      // ``{items, total, limit, offset}``. We accept BOTH during the transition
      // window: an old gateway running a pre-F011 portfolio service still
      // works, and a new gateway against a post-F011 service unwraps ``items``.
      type RawHolding = {
        id: string;
        portfolio_id: string;
        instrument_id: string;
        quantity: string; // S1 serialises Decimal as "0.00000000" string
        average_cost: string; // same decimal string format
        currency: string;
        ticker: string | null; // from instruments table (null if not synced yet)
        name: string | null; // from instruments table
        entity_id: string | null; // from instruments table
      };
      const raw = await apiFetch<
        RawHolding[] | { items: RawHolding[]; total: number; limit: number; offset: number }
      >(`/v1/holdings/${encodeURIComponent(portfolioId)}`, { token: t });

      // Normalise both shapes into a flat array. Defensive: a malformed
      // response that isn't an array OR an envelope yields an empty list.
      const items: RawHolding[] = Array.isArray(raw)
        ? raw
        : Array.isArray((raw as { items?: unknown }).items)
          ? (raw as { items: RawHolding[] }).items
          : [];

      // Transform S1 HoldingResponse into frontend Holding type
      const holdings: Holding[] = items.map((h) => ({
        holding_id: h.id,
        portfolio_id: h.portfolio_id,
        instrument_id: h.instrument_id,
        entity_id: h.entity_id ?? "",
        ticker: h.ticker ?? "",
        name: h.name ?? "",
        // WHY parseFloat: S1 serialises Decimal fields as "0.00000000" strings (Pydantic
        // field_serializer for Numeric(18,8)). The frontend expects numbers for arithmetic.
        quantity: parseFloat(h.quantity) || 0,
        average_cost: parseFloat(h.average_cost) || 0,
        // WHY null: These fields are computed client-side from live quote data, not stored in S1.
        current_price: null,
        unrealised_pnl: null,
        unrealised_pnl_pct: null,
        portfolio_weight: null,
      }));

      return {
        portfolio_id: portfolioId,
        holdings,
        // WHY null: P&L totals require live prices which aren't available from S1.
        // The PortfolioPage component computes these after fetching batch quotes.
        total_value: null,
        total_cost: null,
        total_unrealised_pnl: null,
        total_unrealised_pnl_pct: null,
      };
    },

    /**
     * getPortfolioPerformance — period return for a portfolio.
     *
     * WHY composition endpoint (not raw proxy): S9 fetches holdings from S1 and
     * OHLCV bars from S3, then computes the weighted portfolio return. The frontend
     * cannot safely call two backend services due to CORS and auth constraints.
     *
     * Returns `covered_pct` (0-1) so the UI can show "~" prefix when < 100% of
     * positions have market data available (e.g., new tickers not yet ingested).
     */
    getPortfolioPerformance(
      portfolioId: string,
      period: "1D" | "1W" | "1M",
    ): Promise<{
      portfolio_id: string;
      period: string;
      return_pct: number;
      return_abs: number;
      covered_pct: number;
    }> {
      return apiFetch<{
        portfolio_id: string;
        period: string;
        return_pct: number;
        return_abs: number;
        covered_pct: number;
      }>(
        `/v1/portfolios/${encodeURIComponent(portfolioId)}/performance?period=${period}`,
        { token: t },
      );
    },

    /**
     * getValueHistory — equity-curve data for a portfolio.
     *
     * WHY transform: S1 serialises Decimal fields as 8-dp strings (matches
     * every other Decimal in the API). The frontend chart needs numeric
     * values so it can compute `min`, `max`, deltas — convert at the
     * gateway boundary (BP-265 awareness: never default to []; use real
     * fetched data).
     *
     * @param portfolioId resolved portfolio UUID
     * @param params from/to ISO dates (defaults applied server-side: 90d
     *   look-back, today inclusive); granularity = 1d / 1w / 1m
     */
    async getValueHistory(
      portfolioId: string,
      params: {
        from?: string;
        to?: string;
        // F-202 (QA iter-2): server now accepts ``days=N`` as an alias for
        // ``from = today - N``. The frontend uses ``days`` for fixed-period
        // toggles and omits it for "All".
        days?: number;
        granularity?: "1d" | "1w" | "1m";
      } = {},
    ): Promise<ValueHistoryResponse> {
      const qs = new URLSearchParams({
        ...(params.from ? { from: params.from } : {}),
        ...(params.to ? { to: params.to } : {}),
        ...(params.days != null ? { days: String(params.days) } : {}),
        ...(params.granularity ? { granularity: params.granularity } : {}),
      }).toString();
      const path =
        `/v1/portfolios/${encodeURIComponent(portfolioId)}/value-history` +
        (qs ? `?${qs}` : "");
      const raw = await apiFetch<{
        points: Array<{
          date: string;
          value: string;
          cost_basis: string;
          cash: string;
          // F-501 (QA iter-5): per-point data-quality flag. Optional on the
          // wire for forward-compat — older S1 builds omit it.
          data_quality?: string;
        }>;
        // F-009 (QA iter-2): empty-state hint metadata. Optional on the wire
        // for forward compat — older S1 builds don't emit it.
        metadata?: {
          last_snapshot_at: string | null;
          next_scheduled_run_utc: string | null;
        };
      }>(path, { token: t });
      // BP-265 awareness: only default `points` to [] when the server
      // genuinely omitted it (defensive); otherwise pass through what
      // we got, parsed.
      const points = (raw.points ?? []).map((p) => ({
        date: p.date,
        value: parseFloat(p.value),
        cost_basis: parseFloat(p.cost_basis),
        cash: parseFloat(p.cash),
        // F-501: default to "ok" when the server didn't emit the field so
        // downstream consumers (EquityCurveChart tooltip) can do strict
        // string comparisons without null-checking everywhere.
        data_quality: p.data_quality ?? "ok",
      }));
      // Map metadata through unchanged — undefined defaults survive so the
      // chart's empty-state code can null-check the field directly.
      return {
        points,
        metadata: raw.metadata
          ? {
              last_snapshot_at: raw.metadata.last_snapshot_at ?? null,
              next_scheduled_run_utc: raw.metadata.next_scheduled_run_utc ?? null,
            }
          : undefined,
      };
    },

    /**
     * getExposure — current invested / cash / leverage breakdown.
     *
     * S1 returns Decimal-as-string; we parseFloat for chart arithmetic.
     * Empty portfolio → all zeros (NOT NaN — see use case docstring).
     */
    async getExposure(portfolioId: string): Promise<ExposureResponse> {
      const raw = await apiFetch<{
        invested: string;
        cash: string;
        gross_exposure_pct: string;
        net_exposure_pct: string;
        leverage: string;
        // F-016 (QA 2026-04-28): two new optional fields. Older S1 builds
        // omit them entirely; the spread below treats undefined as
        // "not stale" so the UI renders no badge.
        prices_stale?: boolean;
        prices_as_of?: string | null;
      }>(`/v1/portfolios/${encodeURIComponent(portfolioId)}/exposure`, { token: t });
      return {
        invested: parseFloat(raw.invested),
        cash: parseFloat(raw.cash),
        gross_exposure_pct: parseFloat(raw.gross_exposure_pct),
        net_exposure_pct: parseFloat(raw.net_exposure_pct),
        leverage: parseFloat(raw.leverage),
        prices_stale: raw.prices_stale ?? false,
        prices_as_of: raw.prices_as_of ?? null,
      };
    },

    /**
     * getRiskMetrics — drawdown / vol / Sharpe / Sortino / beta vs SPY.
     *
     * WHY no transform: this is a pure S9 *composition* endpoint — every
     * field is already a `number | null` JSON-native value. The strip
     * component renders `null` as "—" so we don't need to coerce.
     */
    getRiskMetrics(
      portfolioId: string,
      lookbackDays = 90,
    ): Promise<RiskMetricsResponse> {
      const qs = new URLSearchParams({ lookback_days: String(lookbackDays) }).toString();
      return apiFetch<RiskMetricsResponse>(
        `/v1/portfolios/${encodeURIComponent(portfolioId)}/risk-metrics?${qs}`,
        { token: t },
      );
    },

    /**
     * getRealizedPnL — FIFO-computed realized P&L for a portfolio over a
     * date range. PLAN-0051 T-A-1-04 / T-A-1-05.
     *
     * WHY a dedicated endpoint (instead of summing client-side):
     *   1. The portfolio page's client-side approximation reuses the *current*
     *      `holdings.average_cost`, which is wrong for fully-closed positions:
     *      once the last share is sold the holding row is dropped, so the
     *      client can't recover the cost basis and silently skips that
     *      contribution. The S1 endpoint reads the full transaction history
     *      and does FIFO over closed lots, so closed-position realized P&L is
     *      finally captured.
     *   2. The endpoint also splits the total into long-term vs short-term
     *      (holding period > 365 days at sale time), which the client can't
     *      compute without storing per-lot acquisition dates.
     *
     * WHY date-range filtering server-side: the SELL transaction set can be
     * tens of thousands of rows for an active trader; filtering server-side
     * is dramatically cheaper than streaming the full history to the browser
     * just to discard rows older than the window.
     *
     * @param portfolioId  S1 portfolio ID
     * @param from         Optional ISO date "YYYY-MM-DD" (inclusive lower)
     * @param to           Optional ISO date "YYYY-MM-DD" (inclusive upper)
     */
    getRealizedPnL(
      portfolioId: string,
      from?: string,
      to?: string,
    ): Promise<RealizedPnLResponse> {
      // WHY URLSearchParams: stable, escaped, and skips undefined keys
      // automatically because we only set defined values. Hand-rolled
      // template strings made one trailing "&from=&to=" bug last quarter.
      const qs = new URLSearchParams();
      if (from) qs.set("from", from);
      if (to) qs.set("to", to);
      const suffix = qs.toString() ? `?${qs.toString()}` : "";

      return apiFetch<RealizedPnLResponse>(
        `/v1/portfolios/${encodeURIComponent(portfolioId)}/realized-pnl${suffix}`,
        { token: t },
      );
    },

    /**
     * getTransactions — paginated transaction history
     *
     * WHY transform: S1 returns `PaginatedResponse<TransactionListItem>` = `{items: [...], total, limit, offset}`
     * where each item has `id` (not `transaction_id`) and uses `transaction_type` + `direction` fields
     * instead of the frontend's single `type: "BUY" | "SELL"`. The S9 proxy forwards query params
     * to S1 unchanged, but S1 actually expects `portfolio_id` as query param plus limit/offset.
     * The S1 route reads portfolio_id from the X-Portfolio-ID header, but the S9 proxy passes
     * it as a query parameter — so the S1 handler may fail. For now we pass it as query param
     * since that's what the S9 proxy forwards.
     */
    async getTransactions(
      portfolioId: string,
      params: PaginationParams = {},
    ): Promise<TransactionsResponse> {
      const qs = new URLSearchParams({
        portfolio_id: portfolioId,
        ...(params.limit != null ? { limit: String(params.limit) } : {}),
        ...(params.offset != null ? { offset: String(params.offset) } : {}),
      }).toString();

      // S1 returns PaginatedResponse<TransactionListItem>
      const raw = await apiFetch<{
        items: Array<{
          id: string;
          portfolio_id: string;
          instrument_id: string;
          transaction_type: string;
          direction: string;
          quantity: string; // Decimal serialised as string
          price: string;
          fees: string;
          // PLAN-0046 / BP-263: S1 now returns the broker-reported cash amount
          // for transactions. It is a string (Decimal serialized) when present
          // and null when the broker omitted it or the row pre-dates Alembic
          // migration 0009. The DIVIDEND row total comes from this field.
          amount: string | null;
          currency: string;
          // F-205 (QA iter-2): S1 now populates ``ticker`` and ``name`` server-side
          // via a JOIN to the local instruments table. Both are nullable when the
          // instrument hasn't been synced yet.
          ticker: string | null;
          name: string | null;
          // PLAN-0053 T-D-4-02: asset_class surfaced via ListTransactionsUseCase
          // JOIN. Optional on the wire — older S1 builds that pre-date the
          // enrichment will simply omit it.
          asset_class?: string | null;
          executed_at: string;
          external_ref: string | null;
          created_at: string;
        }>;
        total: number;
        limit: number;
        offset: number;
      }>(`/v1/transactions?${qs}`, { token: t });

      // Transform S1 TransactionListItem into frontend Transaction type
      const transactions: Transaction[] = (raw.items ?? []).map((tx) => {
        // WHY two fields exist: S1's TransactionType is the "what" (BUY / SELL /
        // DIVIDEND / DEPOSIT / WITHDRAWAL / FEE) and TransactionDirection is the
        // "asset flow" (INFLOW = position increased, OUTFLOW = position decreased).
        // The frontend Transaction.type union is the user-facing label: BUY | SELL | DIVIDEND.
        // BP-261 (2026-04-28): the previous mapping read tx.direction.toUpperCase() and
        // produced literal "INFLOW"/"OUTFLOW" strings — never matching the BUY/SELL filter
        // buttons and breaking the DIVIDEND code-path entirely.
        const txType = (tx.transaction_type ?? "").toUpperCase();
        const txDir = (tx.direction ?? "").toUpperCase();
        // Resolution order, defensive across adapter variants:
        // 1. transaction_type === DIVIDEND → DIVIDEND (income event)
        // 2. transaction_type or direction in {BUY, SELL} → use it directly
        //    (some payloads label direction as BUY/SELL rather than INFLOW/OUTFLOW)
        // 3. direction === INFLOW → BUY; OUTFLOW → SELL (canonical S1 enum)
        // 4. fallback SELL — never emit raw INFLOW/OUTFLOW literals
        const mappedType: Transaction["type"] =
          txType === "DIVIDEND"
            ? "DIVIDEND"
            : txType === "BUY" || txDir === "BUY" || txDir === "INFLOW"
              ? "BUY"
              : txType === "SELL" || txDir === "SELL" || txDir === "OUTFLOW"
                ? "SELL"
                : "SELL";
        return {
          transaction_id: tx.id,
          portfolio_id: tx.portfolio_id,
          instrument_id: tx.instrument_id,
          // F-205 (QA iter-2): map server-side ticker through. Empty string is
          // the safe display value when the instruments cache miss left it null
          // (matches the previous BP-262 fallback so the table doesn't render
          // a literal "null"). Older S1 builds that don't yet emit the field
          // give us undefined → empty string for the same reason.
          ticker: tx.ticker ?? "",
          // PLAN-0053 T-D-4-02: forward the new field; null is the safe
          // default when the gateway upstream hasn't been re-deployed yet.
          asset_class: tx.asset_class ?? null,
          type: mappedType,
          quantity: parseFloat(tx.quantity) || 0,
          price: parseFloat(tx.price) || 0,
          fee: parseFloat(tx.fees) || 0,
          // PLAN-0046 / BP-263: map broker-reported amount through to the UI.
          // Strict null preservation — null on the wire stays null, not 0 — so the
          // table can distinguish "broker didn't tell us" from "amount is $0".
          amount: tx.amount != null ? Number(tx.amount) : null,
          currency: tx.currency,
          executed_at: tx.executed_at,
          notes: tx.external_ref,
        };
      });

      return {
        transactions,
        total: raw.total,
        offset: raw.offset,
        limit: raw.limit,
      };
    },

    /**
     * createPortfolio — create a new manually-managed portfolio
     *
     * WHY this exists: Users without a brokerage connection need a way to create a portfolio
     * manually before they can add positions. S9's POST /v1/portfolios proxy injects
     * owner_user_id from the JWT so the frontend only sends name + currency.
     *
     * WHY transform: S1 returns `PortfolioResponse` with `id` (not `portfolio_id`) and no
     * `updated_at` field — same mapping as getPortfolios(). We reuse the same shape.
     *
     * @param name     - Portfolio display name (e.g., "My Main Portfolio")
     * @param currency - 3-letter ISO currency code (default: "USD")
     */
    async createPortfolio(name: string, currency = "USD"): Promise<Portfolio> {
      // POST to S9, which injects owner_user_id from JWT before forwarding to S1
      const raw = await apiFetch<{
        id: string;
        tenant_id: string;
        owner_id: string;
        name: string;
        currency: string;
        status: string;
        created_at: string;
      }>("/v1/portfolios", {
        method: "POST",
        // WHY omit owner_user_id: S9's create_portfolio proxy reads it from the
        // verified JWT and injects it server-side. Sending it from the client would
        // be a security risk (client could supply any user_id).
        body: { name, currency },
        token: t,
      });

      // Map S1's PortfolioResponse (id) → frontend Portfolio type (portfolio_id)
      return {
        portfolio_id: raw.id,
        name: raw.name,
        currency: raw.currency,
        owner_id: raw.owner_id,
        created_at: raw.created_at,
        updated_at: raw.created_at, // S1 has no updated_at; use created_at as fallback
      };
    },

    /**
     * deletePortfolio — delete a non-root portfolio.
     *
     * F-013 (QA 2026-04-28): added so the new Delete button on the
     * portfolio page can wire up. The S9 proxy forwards to S1 which
     * archives the portfolio (soft delete) and rejects ROOT portfolios
     * with 400 + RootPortfolioNotArchivableError. The frontend disables
     * the button for root, so under normal flow only manual/brokerage
     * portfolios end up here.
     */
    deletePortfolio(portfolioId: string): Promise<void> {
      return apiFetch<void>(
        `/v1/portfolios/${encodeURIComponent(portfolioId)}`,
        { method: "DELETE", token: t },
      );
    },

    /**
     * addPosition — open a new long position by recording a BUY transaction
     *
     * WHY use addTransaction under the hood: S1 has no dedicated "add holding" endpoint.
     * Holdings are derived from transaction history — a BUY transaction creates/increases
     * a holding, a SELL reduces it. To manually open a position, we record a BUY.
     *
     * WHY instrument_id (not ticker): S1's RecordTransactionRequest requires instrument_id
     * (the UUID stored in S3). The caller must resolve ticker → instrument_id first using
     * searchInstruments(). This function expects the resolved UUID.
     *
     * @param portfolioId  - UUID of the portfolio to add the position to
     * @param instrumentId - UUID of the instrument (resolved from ticker via searchInstruments)
     * @param quantity     - Number of shares to add (must be > 0)
     * @param averageCost  - Average cost per share (price at which you bought)
     */
    async addPosition(
      portfolioId: string,
      instrumentId: string,
      quantity: number,
      averageCost: number,
    ): Promise<Transaction> {
      // Holdings in S1 are derived from transactions — a BUY creates/grows a holding.
      // We map the S1 RecordTransactionRequest shape directly (same as addTransaction).
      const s1Body = {
        portfolio_id: portfolioId,
        instrument_id: instrumentId,
        // WHY TRADE + BUY: S1 uses two separate fields for what the frontend combines as "type".
        // transaction_type=TRADE covers manual equity purchases (vs DIVIDEND, FEE, TRANSFER).
        // direction=BUY increases the holding; direction=SELL decreases it.
        transaction_type: "TRADE",
        direction: "BUY",
        quantity,
        price: averageCost,
        fees: 0, // manual entry has no brokerage fee
        currency: "USD", // default; S1 stores per-transaction currency
        executed_at: new Date().toISOString(), // "now" is the correct timestamp for manual add
        external_ref: null,
      };

      const raw = await apiFetch<{
        id: string;
        portfolio_id: string;
        instrument_id: string;
        transaction_type: string;
        direction: string;
        quantity: string;
        price: string;
        fees: string;
        currency: string;
        executed_at: string;
        created_at: string;
      }>("/v1/transactions", {
        method: "POST",
        body: s1Body,
        token: t,
      });

      return {
        transaction_id: raw.id,
        portfolio_id: raw.portfolio_id,
        instrument_id: raw.instrument_id,
        ticker: "",
        // PLAN-0053 T-D-4-02: manual-entry path doesn't get asset_class
        // back from the create-transaction response; null is the safe
        // default until the next read enriches the row.
        asset_class: null,
        type: "BUY",
        quantity: parseFloat(raw.quantity) || 0,
        price: parseFloat(raw.price) || 0,
        fee: parseFloat(raw.fees) || 0,
        // PLAN-0046 / BP-263: manual entries don't carry a broker amount —
        // the table will fall back to quantity * price for the total.
        amount: null,
        currency: raw.currency,
        executed_at: raw.executed_at,
        notes: null,
      };
    },

    /**
     * addTransaction — record a buy or sell
     *
     * WHY transform: S1's RecordTransactionRequest expects `transaction_type`, `direction`,
     * `fees` (not `fee`), and no `type` field. The S1 response uses `id` (not `transaction_id`).
     * The frontend type uses `type: "BUY"|"SELL"` as a combined field; we need to split it
     * into S1's transaction_type=TRADE + direction=BUY/SELL.
     */
    async addTransaction(tx: TransactionRequest): Promise<Transaction> {
      // Map frontend TransactionRequest to S1's RecordTransactionRequest shape
      const s1Body = {
        portfolio_id: tx.portfolio_id,
        instrument_id: tx.instrument_id,
        // WHY TRADE: S1 distinguishes transaction_type (TRADE, DIVIDEND, FEE, TRANSFER) from
        // direction (BUY, SELL). The frontend only supports manual trades, so always TRADE.
        transaction_type: "TRADE",
        direction: tx.type, // "BUY" or "SELL"
        quantity: tx.quantity,
        price: tx.price,
        fees: tx.fee ?? 0,
        currency: "USD", // Default currency — frontend type doesn't include currency on request
        executed_at: tx.executed_at ?? new Date().toISOString(),
        external_ref: tx.notes ?? null,
      };

      const raw = await apiFetch<{
        id: string;
        portfolio_id: string;
        instrument_id: string;
        transaction_type: string;
        direction: string;
        quantity: string;
        price: string;
        fees: string;
        currency: string;
        executed_at: string;
        created_at: string;
      }>("/v1/transactions", {
        method: "POST",
        body: s1Body,
        token: t,
      });

      return {
        transaction_id: raw.id,
        portfolio_id: raw.portfolio_id,
        instrument_id: raw.instrument_id,
        ticker: "",
        // PLAN-0053 T-D-4-02: see sibling addTransaction-style return above —
        // manual-entry path has no asset_class from the create response.
        asset_class: null,
        type: raw.direction.toUpperCase() as "BUY" | "SELL",
        quantity: parseFloat(raw.quantity) || 0,
        price: parseFloat(raw.price) || 0,
        fee: parseFloat(raw.fees) || 0,
        // PLAN-0046 / BP-263: manual addTransaction calls do not record an
        // explicit broker `amount`. Stay null to mark "no broker truth".
        amount: null,
        currency: raw.currency,
        executed_at: raw.executed_at,
        notes: null,
      };
    },
  };
}
