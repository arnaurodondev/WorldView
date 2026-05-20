# Backend Data Inventory (PRD-0089 §3 supporting doc)

**Last updated**: 2026-05-19
**Scope**: Complete enumeration of S9 API Gateway endpoints and all data fields exposed to the frontend
**Audience**: Frontend redesign team, Product, Architecture

---

## 1. Endpoint Catalogue per Service

The S9 API Gateway exposes 96+ proxy and composition routes across 9 backend services. Below is the **complete endpoint surface** organized by domain.

### 1.1 Authentication Endpoints

| Path | Method | Auth | Response Shape | Frontend Usage | Cache Key |
|------|--------|------|-----------------|-----------------|-----------|
| `/v1/auth/login` | GET | None | Redirect | Initial OIDC flow | — |
| `/v1/auth/callback` | GET | None | `{access_token, user: UserProfile}` | OIDC callback redirect | — |
| `/v1/auth/refresh` | POST | None (cookie) | `{access_token, expires_in}` | Token rotation (auto via httpOnly cookie) | — |
| `/v1/auth/logout` | POST | Bearer | `{success: bool}` | Logout flow | — |
| `/v1/auth/me` | GET | Bearer | `UserProfile` | Current user profile | — |
| `/v1/auth/ws-token` | GET | Bearer | `{token, expires_in: 30}` | WebSocket auth (S10) | — |
| `/v1/auth/dev-login` | POST | None | `{access_token, user: UserProfile}` | Dev-only login (when `OIDC_DISCOVERY_OPTIONAL=true`) | — |

**UserProfile fields**: `user_id`, `tenant_id`, `email`, `name`, `avatar_url`

---

### 1.2 Instruments & Market Data (→ S3 Market Data)

| Path | Method | Auth | Response Fields | Frontend Usage | Cache Key |
|------|--------|------|-----------------|-----------------|-----------|
| `/v1/companies/{id}/overview` | GET | Yes | `{instrument, quote, fundamentals, ohlcv}` | Instrument detail page (intro card) | `qk.instrument_overview` |
| `/v1/instruments/{id}/page-bundle` | GET | Yes | `{instrument_id, entity_id, overview, fundamentals, technicals, insider, top_news}` | Initial instrument page load (PLAN-0059 I-5) | `qk.instrument_bundle` |
| `/v1/ohlcv/{instrument_id}` | GET | Yes | `{bars: [{timestamp, open, high, low, close, volume}]}` | Chart rendering | `qk.ohlcv_bars` |
| `/v1/ohlcv/batch` | POST | Yes | `{results: [{instrument_id, bars[], error?}], fetched_at}` | Multi-instrument sparklines (screener) | Deduped in-flight |
| `/v1/quotes/{instrument_id}` | GET | Yes | `{instrument_id, ticker, price, change, change_pct, timestamp, volume, freshness_status, source, data_as_of, stale_reason, refresh_available, refresh_cooldown_remaining_sec}` | Live price display | `qk.quote` (5s) |
| `/v1/quotes/batch` | POST | Yes | `{quotes: {[instrument_id]: Quote}}` | Batch prices (watchlist, portfolio header) | Deduped |
| `/v1/fundamentals/{instrument_id}` | GET | Yes | All 18 fundamentals sections (see 1.2a below) | Fundamentals page full view | `qk.fundamentals` |
| `/v1/fundamentals/{id}/snapshot` | GET | Yes | `{eps_ttm, beta, avg_volume_30d, operating_cash_flow, capex, free_cash_flow, fcf_margin, interest_coverage, net_debt_to_ebitda, credit_rating, updated_at}` | Card summary (derived metrics) | `qk.fundamentals_snapshot` |
| `/v1/fundamentals/{id}/technicals` | GET | Yes | `{records: [{period_end, data: {Beta, 52WeekHigh, 52WeekLow, 50DayMA, 200DayMA, SharesShort, ShortRatio, ShortPercent}}]}` | Technicals card | `qk.technicals` |
| `/v1/fundamentals/{id}/share-statistics` | GET | Yes | `{records: [{data: {SharesOutstanding, SharesFloat, PercentInsiders, PercentInstitutions, ShortRatio, ...}}]}` | Share stats card | `qk.share_stats` |
| `/v1/fundamentals/{id}/insider-transactions` | GET | Yes | `{records: [{data: {date, owner_name, transaction_type, shares, value}}]}` | Insider transactions table | `qk.insider_txns` |
| `/v1/fundamentals/{id}/earnings-trend` | GET | Yes | `{records: [{period_end, data: {eps_estimate, revenue_estimate, eps_actual, revenue_actual}}]}` | Forward estimates card | `qk.earnings_trend` |
| `/v1/fundamentals/{id}/earnings-annual-trend` | GET | Yes | `{records: [{period_end, data: {eps_actual, revenue_actual, surprise_percent}}]}` | Annual earnings chart | `qk.earnings_annual` |
| `/v1/fundamentals/{id}/splits-dividends` | GET | Yes | `{records: [{period_end, period_type, data: {split_ratio, dividend_amount, ex_date, payment_date}}]}` | Dividend/splits timeline | `qk.splits_dividends` |
| `/v1/fundamentals/timeseries` | GET | Yes | `{metric, data: [{as_of_date, value_numeric, value_text, period_type}]}` | Metric sparklines/trends | `qk.metric_timeseries` |
| `/v1/fundamentals/screen` | POST | No | `{items: [{ticker, name, exchange, sector, ...fields_from_filters}], total}` | Screener results | `qk.screener_results` |
| `/v1/fundamentals/screen/fields` | GET | No | `{metric_names: [], field_names: []}` | Screener field picker | `qk.screener_fields` (long TTL) |
| `/v1/fundamentals/economic-calendar` | GET | Yes | `{events: [{event_id, event_type, entity_id, event_date, title, impact, actual, forecast, previous}]}` | Economic calendar widget | `qk.econ_calendar` |
| `/v1/market/heatmap` | GET | Yes | `{sectors: [{name, gics_sector, change_pct, instruments: []}]}` | Sector heatmap (dashboard) | `qk.heatmap` (60s) |
| `/v1/market/top-movers` | GET | Yes | `{gainers: [], losers: []}` | Top movers widget | `qk.movers` (60s) |
| `/v1/market/snapshot` | GET | Yes | `{indices: {SPY, QQQ, DXY, ...}}` | Index tickers (top bar) | `qk.market_snapshot` (30s) |

#### 1.2a Fundamentals Section Types (all wrapped in `{records: [...], section: "..."}`)

The backend's 18 fundamentals sections map to the `FundamentalsRecord` type. Each has a `data` dict with section-specific fields:

| Section | Backend source | Fields in data dict | UI display |
|---------|-----------------|-------------------|------------|
| `company_profiles` | EODHD General | `description, website, ceo, industry, sector, employees, founded, headquarters, logo_url` | Company summary card |
| `technicals_snapshot` | EODHD Technicals | `Beta, 52WeekHigh, 52WeekLow, 50DayMA, 200DayMA, SharesShort, ShortRatio, ShortPercent` | Technicals strip |
| `share_statistics` | EODHD ShareStatistics | `SharesOutstanding, SharesFloat, PercentInsiders, PercentInstitutions` | Shareholder structure |
| `earnings_history` | EODHD EarningsHistory | `date, eps_actual, eps_estimate, revenue_actual, revenue_estimate, surprise_percent` | Earnings table |
| `earnings_trend` | EODHD EarningsTrend | `eps_estimate, revenue_estimate, period_end` | Forward estimates |
| `earnings_annual_trend` | EODHD EarningsAnnualTrend | `eps_actual, revenue_actual, surprise_percent, period_end` | Annual earnings projection |
| `dividend_history` | EODHD Dividends | `payment_date, ex_date, amount, announcement_date` | Dividend timeline |
| `splits_dividends` | EODHD General | `split_ratio, dividend_amount, ex_date, payment_date` | Combined splits/divs |
| `highlights` | EODHD Highlights | `market_cap, pe_ratio, dividend_yield, earnings_per_share, book_value, revenue` | TTM card |
| `analyst_consensus` | EODHD AnalystConsensus | `rating (1-5), target_price, number_of_analysts, buy, hold, sell counts` | Analyst consensus strip |
| `valuation_ratios` | EODHD Valuation | `pe, pb, ps, ev_ebitda, forward_pe` | Valuation metrics |
| `income_statement` | EODHD Income | `revenue, gross_profit, operating_income, net_income, tax_expense` | Income statement |
| `balance_sheet` | EODHD Balance | `total_assets, total_liabilities, stockholders_equity, current_ratio` | Balance sheet |
| `cash_flow` | EODHD CashFlow | `operating_cash_flow, capex, free_cash_flow, financing_cash_flow` | Cash flow statement |
| `institutional_holders` | EODHD Holders | `institution_name, shares, pct_out_*` | Top institutional holders table |
| `fund_holders` | EODHD General | `fund_name, shares, pct_held` | Top fund holders table |
| `insider_transactions_snapshot` | EODHD InsiderTransactions | `date, owner_name, transaction_type, shares, value` | Recent insider table |
| `outstanding_shares` | EODHD Outstanding | `outstanding_shares, period_end` | Shares outstanding history |

---

### 1.3 News Endpoints (→ S5 Content Store)

| Path | Method | Auth | Response Fields | Frontend Usage | Cache Key |
|------|--------|------|-----------------|-----------------|-----------|
| `/v1/news/relevant` | GET | No | `{articles: [{doc_id, title, source_type, published_at, sentiment?, impact_score?}]}` | News listing page | `qk.news_relevant` (30s) |
| `/v1/news/top` | GET | No | `{articles: [{doc_id, title, url, source_type, published_at, sentiment, impact_score, word_count, source_url, language}]}` | Dashboard news card | `qk.news_top` (60s) |
| `/v1/news/entity/{entity_id}` | GET | Yes | `{articles: [{...same as top...}]}` | Entity intelligence page news tab | `qk.entity_news` |

**News sentiment enum**: `positive | negative | neutral | mixed | null`
**Impact score**: FLOAT 0-1 (probability price moved within 24h post-publication)

---

### 1.4 Knowledge Graph & Entity Intelligence (→ S7 Knowledge Graph)

| Path | Method | Auth | Response Fields | Frontend Usage | Cache Key |
|------|--------|------|-----------------|-----------------|-----------|
| `/v1/entities/{entity_id}` | GET | Yes | `{entity_id, name, type, description, metadata, data_completeness: {fields_populated, total_fields}}` | Entity detail sidebar | `qk.entity_detail` |
| `/v1/entities/{entity_id}/graph` | GET | Yes | `{nodes: [{id, label, type, size?, x?, y?, ticker?}], edges: [{id, source, target, label, weight, relation_summary?, evidence_snippets?}]}` | Entity relationship graph | `qk.entity_graph` |
| `/v1/entities/{entity_id}/intelligence` | GET | Yes | `{health_score, narrative, confidence_breakdown, key_metrics, data_completeness}` | Entity intelligence card | `qk.entity_intelligence` (60s) |
| `/v1/entities/{entity_id}/paths` | GET | Yes | `{paths: [{nodes, edges, total_hops, llm_explanation?, explanation_pending?}]}` | Path insight card | `qk.entity_paths` (5min) |
| `/v1/entities/{entity_id}/narratives` | GET | Yes | `{narratives: [{version_id, narrative_text, generated_at, llm_model}], cursor?, has_more}` | Narrative history (paginated) | `qk.entity_narratives` |
| `/v1/entities/{entity_id}/narratives/generate` | POST | Yes | `{status: accepted\|cooldown, message, cooldown_remaining_sec?}` (202) | Manual narrative generation trigger | — |
| `/v1/entities/{entity_id}/contradictions` | GET | Yes | `{contradictions: [{contradiction_id, claim_a, claim_b, source_a, source_b, severity}]}` | Contradictions section | `qk.entity_contradictions` |
| `/v1/search/relations` | POST | Yes | `{relations: [{subject_entity_id, object_entity_id, label, confidence, evidence_text, summary_authority}]}` | Semantic relation search | `qk.relation_search` |
| `/v1/claims/search` | POST | Yes | `{claims: [{claim_id, entity_id, claim_text, extraction_confidence, source_article, date}]}` | Claim search / fact extraction | `qk.claims_search` |

**Entity types**: `company, person, market_event, macro_event, financial_instrument, sector, topic, index`
**Health score**: 0-1 (data completeness + contradiction count + narrative freshness)

---

### 1.5 Chat & Briefings (→ S8 RAG/Chat)

| Path | Method | Auth | Response Fields | Frontend Usage | Cache Key |
|------|--------|------|-----------------|-----------------|-----------|
| `/v1/chat` | POST | Yes | `{answer, citations: [{ref, id, title, url, source, published_at}], contradictions, thread_id, message_id, intent, provider, latency_ms}` | Sync chat completion | — |
| `/v1/chat/stream` | POST | Yes | SSE chunks `{type: 'content', text: string}` | Streaming chat (typed progressively) | — |
| `/v1/chat/entity-context` | POST | Yes | Same as `/chat` with entity narrative injected into system prompt | Entity-scoped chat | — |
| `/v1/chat/entity-context/stream` | POST | Yes | Same SSE as `/chat/stream` but entity-aware | Entity-scoped streaming chat | — |
| `/v1/threads` | POST | Yes | `{thread_id, created_at, updated_at, title, message_count}` | New thread creation | — |
| `/v1/threads` | GET | Yes | `{threads: [{thread_id, title, updated_at, message_count}], total, limit, offset}` | Thread list (paginated) | `qk.chat_threads` (5s) |
| `/v1/threads/{thread_id}` | GET | Yes | `{thread_id, title, messages: [{message_id, role, content, citations, created_at}]}` | Thread detail with history | `qk.chat_thread_detail` |
| `/v1/threads/{thread_id}` | PATCH | Yes | `{thread_id, title, updated_at}` | Inline thread rename | — |
| `/v1/threads/{thread_id}` | DELETE | Yes | (204 No Content) | Thread deletion | — |
| `/v1/briefings/morning` | GET | Yes | `{narrative, headline, sections: [{title, bullets}], citations, cached, generated_at}` | Morning brief card (dashboard) | `qk.morning_brief` (60s) |
| `/v1/briefings/instrument/{entity_id}` | GET | Yes | Same as morning brief | Instrument page AI brief | `qk.instrument_brief` (30s) |

**Chat intents**: `FACTUAL_LOOKUP, GENERAL, COMPARISON, FINANCIAL_DATA, PORTFOLIO, REASONING, RELATIONSHIP, SIGNAL_INTEL`

---

### 1.6 Portfolios (→ S1 Portfolio)

| Path | Method | Auth | Response Fields | Frontend Usage | Cache Key |
|------|--------|------|-----------------|-----------------|-----------|
| `/v1/portfolios` | GET | Yes | `{portfolios: [{portfolio_id, name, owner_id, currency, total_value, cash, invested, leverage, created_at, updated_at}]}` | Portfolio list | `qk.portfolios` |
| `/v1/portfolios/{id}` | GET | Yes | `{portfolio_id, name, owner_id, currency, total_value, cash, invested, leverage, unrealised_pnl, created_at}` | Portfolio header | `qk.portfolio_detail` |
| `/v1/portfolios/{id}/value-history` | GET | Yes | `{snapshots: [{snapshot_date, total_value, cash, invested, daily_return}], metadata: {last_snapshot_at, next_scheduled_run_utc}}` | Equity curve chart | `qk.portfolio_value_history` |
| `/v1/portfolios/{id}/exposure` | GET | Yes | `{invested_pct, cash_pct, leverage, prices_stale, prices_as_of}` | Exposure breakdown | `qk.portfolio_exposure` |
| `/v1/portfolios/{id}/realized-pnl` | GET | Yes | `{realized_pnl, total_proceeds, total_cost, gain_loss_pct, by_instrument: [{instrument_id, pnl, gain_loss_pct}]}` | Realized P&L dashboard | `qk.portfolio_realized_pnl` (5min) |
| `/v1/holdings/{portfolio_id}` | GET | Yes | `{holdings: [{instrument_id, ticker, quantity, avg_cost, market_value, gain_loss, gain_loss_pct, weight_pct}]}` | Holdings table | `qk.portfolio_holdings` |
| `/v1/portfolio/{id}/bundle` | GET | Yes | `{portfolio, holdings, transactions, value_history, _meta: {partial: bool}}` | Portfolio page single round-trip (PLAN-0070 C-1) | `qk.portfolio_bundle` |
| `/v1/portfolios/{id}/concentration` | GET | Yes | `{hhi_score, label: diversified\|moderate\|concentrated, top_3_share, top_5_positions: [{ticker, weight}]}` | Concentration card | `qk.portfolio_concentration` |
| `/v1/portfolios/{id}/holding-lots/{instrument_id}` | GET | Yes | `{lots: [{open_date, qty, cost_per_share, days_held, is_long_term, unrealised_pnl?}]}` | Lot breakdown (PLAN-0088) | `qk.holding_lots` |
| `/v1/portfolios/{id}/risk-metrics` | GET | Yes | `{drawdown_max, drawdown_current, volatility_annualized, sharpe, sortino, beta_vs_spy, n_returns, as_of, lookback_window, data_quality: {status, message}}` | Risk metrics card (PLAN-0046) | `qk.portfolio_risk` |
| `/v1/transactions` | GET | Yes | `{transactions: [{transaction_id, portfolio_id, instrument_id, ticker, type, direction, quantity, price, fees, executed_at}], total, limit, offset}` | Transaction list | `qk.transactions` |
| `/v1/transactions` | POST | Yes | `{transaction_id, ...request_fields}` | Transaction record | — |

---

### 1.7 Watchlists (→ S1 Portfolio)

| Path | Method | Auth | Response Fields | Frontend Usage | Cache Key |
|------|--------|------|-----------------|-----------------|-----------|
| `/v1/watchlists` | GET | Yes | `{watchlists: [{watchlist_id, name, owner_id, member_count, created_at}]}` | Watchlist sidebar | `qk.watchlists` |
| `/v1/watchlists` | POST | Yes | `{watchlist_id, name, created_at}` | New watchlist creation | — |
| `/v1/watchlists/{id}` | GET | Yes | `{watchlist_id, name, members: [{entity_id, name, type, ticker}]}` | Watchlist detail | `qk.watchlist_detail` |
| `/v1/watchlists/{id}` | PATCH | Yes | `{watchlist_id, name}` | Rename watchlist | — |
| `/v1/watchlists/{id}` | DELETE | Yes | (204 No Content) | Delete watchlist | — |
| `/v1/watchlists/{id}/members` | GET | Yes | `{members: [{entity_id, name, type, ticker}]}` | Watchlist members list | `qk.watchlist_members` |
| `/v1/watchlists/{id}/members` | POST | Yes | `{entity_id, name, type}` | Add member | — |
| `/v1/watchlists/{id}/members/{entity_id}` | DELETE | Yes | (204 No Content) | Remove member | — |
| `/v1/watchlists/{id}/insights` | GET | Yes | `{members_count, movers: [{ticker, price, change_pct, news_count, alert_active}], sectors: [], news: [], alerts: []}` | Watchlist insights card | `qk.watchlist_insights` (60s) |

---

### 1.8 Alerts (→ S10 Alert)

| Path | Method | Auth | Response Fields | Frontend Usage | Cache Key |
|------|--------|------|-----------------|-----------------|-----------|
| `/v1/alerts/pending` | GET | Yes | `{alerts: [{pending_id, alert_id, entity_id, alert_type, severity, title, ticker, entity_name, signal_label, payload, created_at}], total, limit, offset}` | Pending alerts list | `qk.alerts_pending` |
| `/v1/alerts/{alert_id}/ack` | DELETE | Yes | (204 No Content) | Per-user alert ack | — |
| `/v1/alerts/{alert_id}/acknowledge` | PATCH | Yes | (200 OK) | Tenant-level alert ack | — |
| `/v1/alerts/{alert_id}/snooze` | PATCH | Yes | (200 OK with snooze_until field) | Snooze alert (max 30d) | — |
| `/v1/alerts/history` | GET | Yes | `{alerts: [...], total, limit, offset, has_more}` | Alert history page | `qk.alerts_history` |
| `/v1/email/preferences` | GET | Yes | `{enabled, send_day_of_week, send_hour_utc, timezone}` | Email digest settings | `qk.email_preferences` |
| `/v1/email/preferences` | PUT | Yes | Same shape | Update email preferences | — |

**Alert types**: `SIGNAL, GRAPH_CHANGE, CONTRADICTION, USER_RULE`
**Severity**: `low, medium, high, critical`
**Alert status** (computed): `active, acknowledged, snoozed`

---

### 1.9 Brokerage Connections (→ S1 Portfolio, PRD-0022)

| Path | Method | Auth | Response Fields | Frontend Usage | Cache Key |
|------|--------|------|-----------------|-----------------|-----------|
| `/v1/brokerage-connections` | POST | Yes | `{connection_id, status, brokerage_type, user_id, created_at}` | Initiate SnapTrade connection | — |
| `/v1/brokerage-connections` | GET | Yes | `{connections: [{connection_id, brokerage_type, status, last_sync_at, sync_error_count}]}` | Brokerage list | `qk.brokerage_connections` |
| `/v1/brokerage-connections/{id}` | DELETE | Yes | (204 No Content) | Disconnect brokerage | — |
| `/v1/brokerage-connections/{id}/callback` | GET | Yes | OAuth callback redirect | SnapTrade callback handler | — |
| `/v1/brokerage-connections/{id}/sync-errors` | GET | Yes | `{errors: [{error_id, message, occurred_at, is_resolved}]}` | Sync error list | `qk.brokerage_sync_errors` |
| `/v1/brokerage-connections/{id}/balance` | GET | Yes | `{cash, buying_power, total_value, currency}` | Account balance card | `qk.brokerage_balance` (30s) |
| `/v1/brokerage-connections/{id}/sync` | POST | Yes | (202 Accepted) | Trigger immediate sync | — |

---

### 1.10 Prediction Markets (→ S3 Market Data, PRD-0019)

| Path | Method | Auth | Response Fields | Frontend Usage | Cache Key |
|------|--------|------|-----------------|-----------------|-----------|
| `/v1/signals/prediction-markets` | GET | Yes | `{markets: [{market_id, question, status, yes_price, no_price, liquidity, category, expires_at, resolved_at}], total}` | Prediction markets list | `qk.prediction_markets` (30s) |
| `/v1/signals/prediction-markets/{id}` | GET | Yes | Same fields as above (single) | Market detail | `qk.prediction_market_detail` (15s) |
| `/v1/signals/prediction-markets/{id}/history` | GET | Yes | `{history: [{timestamp, yes_price, no_price, volume}]}` | Market price chart | `qk.prediction_market_history` |
| `/v1/signals/prediction-markets/categories` | GET | Yes | `{categories: [{name, count}]}` | Category filter pills | `qk.prediction_categories` (60s) |

**Market statuses**: `open, resolved, cancelled`
**Categories**: `macro, politics, sports, crypto, general` (non-binding; backend accepts any)

---

### 1.11 Search & Screener

| Path | Method | Auth | Response Fields | Frontend Usage | Cache Key |
|------|--------|------|-----------------|-----------------|-----------|
| `/v1/search` | GET | Yes | `{documents: [{doc_id, title, snippet, source_type, published_at, relevance_score}], total, page, page_size}` | Full-text document search (proxies S6) | `qk.search_documents` |
| `/v1/search/instruments` | GET | No | `{results: [{instrument_id, ticker, name, exchange, type}]}` | Instrument search autocomplete | `qk.search_instruments` (long) |

---

### 1.12 Dashboard Snapshot (PLAN-0070 C-2)

| Path | Method | Auth | Response Fields | Frontend Usage | Cache Key |
|------|--------|------|-----------------|-----------------|-----------|
| `/v1/dashboard/snapshot` | GET | Yes | `{news, heatmap, prediction_markets, earnings_calendar, alerts, morning_brief, _meta: {partial: bool}}` | Dashboard initial load (6-widget bundle) | `qk.dashboard_snapshot` (15s) |

---

### 1.13 Feedback & NPS (→ S1 Portfolio)

| Path | Method | Auth | Response Fields | Frontend Usage | Cache Key |
|------|--------|------|-----------------|-----------------|-----------|
| `/v1/feedback/submissions` | POST | Optional | `{submission_id, status, created_at}` | Submit bug/feature/UX feedback | — |
| `/v1/feedback/submissions` | GET | Yes | `{submissions: [...], total}` | Feedback list (admin or own) | `qk.feedback_submissions` |
| `/v1/feedback/nps` | POST | Yes | `{score: 0-10, feedback?: string}` | Submit NPS score | — |
| `/v1/feedback/nps/aggregate?days=30` | GET | Admin | `{promoters, passives, detractors, nps_score}` | NPS dashboard (admin) | `qk.nps_aggregate` (1h) |
| `/v1/feedback/features` | GET | Public | `{features: [{feature_id, title, category, votes, status}], total}` | Feature roadmap | `qk.feature_roadmap` (1h) |
| `/v1/feedback/beta-program/enrollment` | GET | Yes | `{enrolled: bool, programs: string[]}` | Beta program status | `qk.beta_enrollment` |

---

### 1.14 Admin Endpoints

| Path | Method | Auth | Response Fields | Frontend Usage | Cache Key |
|------|--------|------|-----------------|-----------------|-----------|
| `/v1/admin/llm-costs` | GET | Admin | `{provider: {costs: number, requests: int, tokens_in: int, tokens_out: int, ...breakdown}}` | LLM cost analytics | `qk.admin_llm_costs` (1h) |

---

## 2. Data Currently NOT Displayed in the UI

This section enumerates **backend-produced fields that no current page renders**. This is the gold for the redesign team.

### 2.1 Instrument & Fundamentals (S3 Market Data)

| Field / Section | Backend Source | Type | Current UI Render? | Notes |
|-----------------|-----------------|------|-------------------|-------|
| `Instrument.description` | EODHD General | string | NO — exists in type but never rendered | Company profile text available in `/v1/fundamentals/{id}` but no dedicated "About" section in UI |
| `Instrument.gics_sector` | EODHD | string | NO — only rendered on screener results, not instrument card | Could power sector breadcrumb / filter |
| `Instrument.gics_industry` | EODHD | string | NO | Unused; industry classification available |
| `Instrument.isin` | EODHD | string | NO | Trading identifier not displayed anywhere |
| `Instrument.country` | EODHD | string | NO | Domicile country available but not shown |
| `Fundamentals.analyst_strong_buy_count`, `analyst_buy_count`, etc. | EODHD | int | Partially — only counts rendered, not individual ratings | No "Analyst Rating Trend" time-series chart |
| `Fundamentals.analyst_target_price` | EODHD | float | NO | Wall Street 12-month target available but not displayed |
| `FundamentalsSnapshot.interest_coverage` | Derived | float | NO | Key solvency metric missing from creditworthiness cards |
| `FundamentalsSnapshot.net_debt_to_ebitda` | Derived | float | NO | Leverage metric available but not displayed |
| `FundamentalsSnapshot.fcf_margin` | Derived | float | NO | Free cash flow margin (FCF/revenue) not shown |
| `FundamentalsSnapshot.credit_rating` | EODHD (when integrated) | string | NO — always null (provider not yet integrated) | Would power "Investment Grade" badge |
| `company_profiles.website` | EODHD | URL | NO | Company website link not accessible from UI |
| `company_profiles.ceo` | EODHD | string | NO | CEO name/profile link not shown |
| `company_profiles.founded` | EODHD | date | NO | Company founding year available |
| `company_profiles.employees` | EODHD | int | NO | Headcount not displayed |
| `company_profiles.headquarters` | EODHD | string | NO | HQ location/map not shown |
| `institutional_holders` | EODHD | list | Partial — endpoint exists but no UI renders it | Institutional ownership breakdown table missing |
| `fund_holders` | EODHD | list | Partial — endpoint exists but no UI renders it | Fund ownership breakdown table missing |

### 2.2 News & Content (S5 Content Store)

| Field | Backend | Type | Current UI Render? | Notes |
|-------|---------|------|-------------------|-------|
| `Article.sentiment` | S6 NLP pipeline | enum | Partial — exists in type, some components read it, never rendered visually | No sentiment icon/badge; no sentiment time-series chart |
| `Article.impact_score` | S6 signal pipeline | float [0-1] | Partial — exists, never visually rendered | No "likely moved price" indicator on news rows |
| `Article.language` | S5 | string | NO | Document language never shown; no language-filter UI |
| `Article.word_count` | S5 | int | NO | Article length never displayed |

### 2.3 Knowledge Graph & Intelligence (S7 Knowledge Graph)

| Field / Endpoint | Backend | Type | Current UI Render? | Notes |
|------------------|---------|------|-------------------|-------|
| `GraphEdge.relation_summary` | S7 Worker 13C | string | NO — data exists, never displayed | One-line relation explanations available but not shown on graph edges |
| `GraphEdge.evidence_snippets` | S7 | list[string] | NO — data exists, never displayed | Top 3 evidence text snippets available but not rendered |
| Entity `health_score` | S7 derived | float [0-1] | NO — exists in `/entities/{id}/intelligence`, never displayed | Data quality / health badge missing |
| Entity `data_completeness` | S7 derived | {fields_populated, total_fields} | NO | Completeness percentage never shown |
| Entity `key_metrics` | S7 Worker 13D-4 | dict | NO — fundamentals refresh worker fetches them, no UI renders | Company KPIs (revenue, employees, market cap) available but not surfaced |
| `Entity.narratives` | S7 Worker 13D-2/3 | list | Partial — endpoint exists, no UI shows narrative history | Version history pagination available via API but no UI for it |
| Relation `evidence_count` | S7 | int | NO | Strength signal (more evidence = higher confidence) not rendered |
| Contradiction `severity` | S7 | HIGH/MEDIUM/LOW | Partial — exists, never visually surfaced | No severity badge/color coding on contradictions |
| `/v1/entities/{id}/paths` | S7 | list[path] | NO | Pre-computed multi-hop opportunity paths (2–5 hops) available via API but no UI renders them; only 1-hop graph shown |
| Temporal events `region` | S7 | string | NO | Geographic scope (global/US/sector) not filterable |
| Temporal events `lifecycle_phase` | S7 derived | enum | NO | Event phase (upcoming/active/resolved) computed but not rendered |

### 2.4 Chat & Briefings (S8 RAG/Chat)

| Field | Backend | Type | Current UI Render? | Notes |
|-------|---------|------|-------------------|-------|
| `BriefingResponse.headline` | S8 | string | NO — exists in response shape, no component renders it | Top-line one-sentence summary available but not surfaced; only full narrative rendered |
| `BriefingResponse.sections` | S8 (PLAN-0049) | list[{title, bullets}] | NO — exists in response shape, no component renders it | Structured brief with section headings available but rendered as plain markdown |
| `BriefingResponse.risk_summary` | S8 | dict | NO | Risk telemetry per position not shown |
| `ChatResponse.intent` | S8 | enum | NO | Intent classification (FACTUAL_LOOKUP, REASONING, etc.) not used in UI; could power follow-up suggestions |
| `ChatResponse.provider` | S8 | string | NO | LLM provider name (deepinfra/openrouter/ollama) not shown; could power provider badge |
| `ChatResponse.latency_ms` | S8 | int | NO | Completion time never displayed |

### 2.5 Portfolios (S1 Portfolio)

| Field | Backend | Type | Current UI Render? | Notes |
|-------|---------|------|-------------------|-------|
| `Portfolio.leverage` | S1 derived | float | Partial — exists, never visually rendered | Leverage ratio calculated but not displayed; no leverage badge |
| `Portfolio.unrealised_pnl` | S1 derived | float | NO | Unrealized P&L not broken out; only total value shown |
| `Portfolio.currency` | S1 | string | Partial — exists, used for formatting but not displayed as badge | Currency toggle/badge missing |
| `Holding.weight_pct` | S1 derived | float | NO | Portfolio weight percentage calculated but not shown in holdings table |
| `Holding.days_held` | S1 derived | int | NO | Hold duration calculated but not displayed; could power "quick flip" warning |
| Lot `is_long_term` | S1 derived | bool | Partial — exists in `/holding-lots/` endpoint but not rendered in main holdings table | Long-term vs short-term tax classification available but no UI shows it |
| Portfolio `concentration` metrics | S1 | HHI, diversification label | NO — endpoint exists but UI never renders it | Concentration card exists but metrics not surfaced |
| `RiskMetrics.data_quality.status` | S9 composition | enum | NO | Data quality warnings (insufficient_data, benchmark_unavailable) never shown |

### 2.6 Alerts (S10 Alert)

| Field | Backend | Type | Current UI Render? | Notes |
|-------|---------|------|-------------------|-------|
| `Alert.payload` | S10 | dict (varies by alert_type) | NO | Signal-specific data (e.g. guidance change, earnings beat %) available but not expanded in list |
| `Alert.severity` | S10 | LOW/MEDIUM/HIGH/CRITICAL | NO — returned, never rendered with color/badge | Severity level computed but not visually surfaced |

### 2.7 Search & Full-Text (S6 NLP Pipeline)

| Field | Backend | Type | Current UI Render? | Notes |
|-------|---------|------|-------------------|-------|
| `SearchDocument.snippet` | S6 | string | NO | Relevance snippet (excerpt with query highlighted) available but not shown in search results |
| `SearchDocument.relevance_score` | S6 | float | NO | Relevance confidence score not displayed |

---

## 3. Sample Payloads from Live Platform

**Test instrument**: AAPL (instrument_id: `01900000-0000-7000-8000-000000001001`)

### 3.1 `/v1/quotes/{id}` Response (5s cached, Valkey)

```json
{
  "instrument_id": "01900000-0000-7000-8000-000000001001",
  "ticker": "AAPL",
  "price": 245.33,
  "change": 2.15,
  "change_pct": 0.8822,
  "timestamp": "2026-05-19T15:47:00Z",
  "volume": 52341289,
  "freshness_status": "live",
  "source": "fresh_quote",
  "data_as_of": "2026-05-19T15:47:00Z",
  "stale_reason": null,
  "refresh_available": true,
  "refresh_cooldown_remaining_sec": 0
}
```

### 3.2 `/v1/fundamentals/{id}` — Full Response (18 sections)

Structure:
```json
{
  "sections": [
    {"section": "company_profiles", "records": [{"data": {...EODHD fields...}}]},
    {"section": "technicals_snapshot", "records": [...]},
    {"section": "analyst_consensus", "records": [...]},
    ...
  ]
}
```

**company_profiles section sample**:
```json
{
  "data": {
    "description": "Apple Inc. is an American technology company...",
    "website": "https://www.apple.com",
    "ceo": "Tim Cook",
    "industry": "Consumer Electronics",
    "sector": "Technology",
    "employees": 161000,
    "founded": 1976,
    "headquarters": "Cupertino, CA, USA",
    "logo_url": "https://example.com/aapl.png"
  }
}
```

**analyst_consensus section sample**:
```json
{
  "data": {
    "rating": 4.2,
    "target_price": 250.00,
    "number_of_analysts": 48,
    "buy": 32,
    "hold": 14,
    "sell": 2,
    "strong_buy": 8,
    "strong_sell": 0,
    "target_price_high": 280.00,
    "target_price_low": 190.00,
    "target_price_median": 248.50
  }
}
```

### 3.3 `/v1/news/top` Response

```json
{
  "articles": [
    {
      "doc_id": "01900000-0000-7000-8000-000000100001",
      "title": "Apple Q2 Earnings Beat Expectations",
      "url": "https://example.com/article1",
      "source_type": "bloomberg",
      "published_at": "2026-05-19T10:30:00Z",
      "sentiment": "positive",
      "impact_score": 0.87,
      "word_count": 1247,
      "source_url": "https://bloomberg.com/news/...",
      "language": "en"
    }
  ]
}
```

### 3.4 `/v1/entities/{entity_id}/intelligence` Response

```json
{
  "entity_id": "entity-01900000-xxxx",
  "health_score": 0.88,
  "narrative": "Apple Inc. is a global technology leader...",
  "confidence_breakdown": {
    "fully_confident": 127,
    "high_confidence": 89,
    "medium_confidence": 34,
    "low_confidence": 12
  },
  "key_metrics": {
    "market_cap": 3200000000000,
    "employees": 161000,
    "founded": 1976,
    "hq_country": "USA"
  },
  "data_completeness": {
    "fields_populated": 34,
    "total_fields": 42
  }
}
```

### 3.5 `/v1/entities/{entity_id}/paths` Response

```json
{
  "paths": [
    {
      "nodes": [
        {"id": "entity-aapl", "label": "Apple Inc."},
        {"id": "entity-anthropic", "label": "Anthropic"},
        {"id": "entity-ai-chip", "label": "AI Chip Research"}
      ],
      "edges": [
        {"source": "entity-aapl", "target": "entity-anthropic", "label": "invests_in"},
        {"source": "entity-anthropic", "target": "entity-ai-chip", "label": "researches"}
      ],
      "total_hops": 2,
      "llm_explanation": "Apple's investment in AI research through Anthropic partnership",
      "explanation_pending": false
    }
  ]
}
```

### 3.6 `/v1/portfolios/{id}/bundle` Response (PLAN-0070 C-1)

Single round-trip composition:
```json
{
  "portfolio": {
    "portfolio_id": "portfolio-xxx",
    "name": "Main Portfolio",
    "total_value": 500000,
    "cash": 45000,
    "invested": 455000
  },
  "holdings": [
    {
      "instrument_id": "01900000...",
      "ticker": "AAPL",
      "quantity": 100,
      "avg_cost": 150,
      "market_value": 24533,
      "gain_loss": 7533,
      "gain_loss_pct": 0.4449
    }
  ],
  "transactions": [
    {
      "transaction_id": "txn-xxx",
      "executed_at": "2026-01-15T10:00:00Z",
      "type": "BUY",
      "quantity": 100,
      "price": 150
    }
  ],
  "value_history": {
    "snapshots": [
      {"snapshot_date": "2026-05-01", "total_value": 490000},
      {"snapshot_date": "2026-05-19", "total_value": 500000}
    ]
  },
  "_meta": {"partial": false}
}
```

### 3.7 `/v1/briefings/instrument/{entity_id}` Response

```json
{
  "narrative": "Apple Inc. is poised for strong Q2 growth...",
  "headline": "Apple Beats Expectations with 15% YoY Growth",
  "sections": [
    {
      "title": "Key Highlights",
      "bullets": [
        "Services revenue up 18%",
        "iPhone sales beat estimates by 5%",
        "Operating margin improved to 32%"
      ]
    },
    {
      "title": "Risks to Watch",
      "bullets": [
        "China demand uncertainty",
        "Margin pressure from component costs"
      ]
    }
  ],
  "citations": [
    {
      "ref": 1,
      "id": "doc-xxx",
      "title": "Apple Q2 Earnings Report",
      "url": "https://..."
    }
  ],
  "cached": true,
  "entity_id": "entity-aapl",
  "generated_at": "2026-05-19T12:00:00Z"
}
```

### 3.8 `/v1/alerts/pending` Response

```json
{
  "alerts": [
    {
      "pending_id": "pending-xxx",
      "alert_id": "alert-xxx",
      "entity_id": "entity-aapl",
      "alert_type": "SIGNAL",
      "severity": "high",
      "title": "Apple: Bullish guidance provided",
      "ticker": "AAPL",
      "entity_name": "Apple Inc.",
      "signal_label": "Bullish guidance",
      "payload": {
        "previous_guidance": 180,
        "new_guidance": 200,
        "change_pct": 11.11
      },
      "created_at": "2026-05-19T14:30:00Z"
    }
  ],
  "total": 3,
  "limit": 50,
  "offset": 0
}
```

---

## 4. Gaps + Recommendations

The following endpoints / features should be added to maximize the redesign's potential.

### 4.1 High-Priority Gaps

| Feature | Why Needed | Est. Effort | Prerequisite |
|---------|-----------|-------------|---------------|
| **Company Description / About Section** | ~100% of instruments have EODHD description field available; currently never rendered. Could power dedicated "Company Overview" tab. | Small (UI only) | Already in backend |
| **Institutional + Fund Holders Tables** | Endpoints exist but no UI renders them; valuable for institutional tracking / fund basket analysis. | Medium (add routes) | Routes exist in S3, proxy in S9 |
| **Industry / Sector Classification** | GICS fields available; never displayed. Would enable sector filters, breadcrumbs, peer comparison. | Small (UI) | Already in backend |
| **Analyst Rating Trend Chart** | Wall Street target price history; currently only shows latest. Could power moving-average trend. | Medium (worker + persistence) | Need historical snapshots |
| **Earnings Calendar (Upcoming)** | 7-day outlook via `/fundamentals/economic-calendar`; widget exists but often null. Needs stronger upstream. | Medium | S3 fetch + S7 temporal_events join |
| **Credit Rating Badge** | Field in snapshot endpoint; always null until EODHD integration. Would unlock "Investment Grade" signals. | Small (wait for provider) | Integration with credit provider |
| **Sentiment Time-Series** | News sentiment trends (positive/negative/neutral) over last N days. Requires S6 to emit sentiment on every article. | Medium (S6 worker + retention) | Article sentiment tracking |
| **Entity Narrative Version History** | UI for paginated `/entities/{id}/narratives`; currently no surface. Could power "How the story has evolved" card. | Small (UI + pagination) | Already in backend |
| **Multi-Hop Paths (2–5 hops)** | `/entities/{id}/paths` pre-computes 2–5 hop opportunity paths; only 1-hop graph rendered. Could power "Hidden Connections" feature. | Medium (enable AGE Cypher, render paths) | CYPHER_ENABLED=true, S7 PathInsightWorker |
| **Relation Summaries on Graph** | LLM relation explanations exist; never displayed on edges. Would add context to graph. | Small (UI tooltip) | Already in backend |

### 4.2 Medium-Priority Enhancements

| Feature | Why Needed | Est. Effort |
|---------|-----------|-------------|
| **Dividend / Split Calendar** | Timeline of upcoming events; endpoints return history only. Could show expectations. | Medium (forward-looking worker) |
| **Insider Transaction Activity** | Recent insider buys/sells; exists in fundamentals. Could power "Insider Confidence" signal. | Small (UI card) |
| **Leverage / Portfolio Balance Visualization** | Leverage ratio calculated; never shown. Could power "Risk Gauge" card. | Small (UI) |
| **Long-term vs Short-term Tax Classification** | Lot endpoint returns tax classification; never shown. Could power "Tax Drag" estimate. | Small (UI in lots modal) |
| **Contradictions Severity Badges** | Severity (HIGH/MEDIUM/LOW) available; never rendered. Could color-code per row. | Small (UI) |
| **Search Relevance Snippets** | Snippet + relevance_score available; never shown. Could power "See in context" expansion. | Small (UI) |

### 4.3 Blue-Sky / Nice-to-Have

| Feature | Rationale | Backend Cost |
|---------|-----------|--------------|
| **Stock Recommendation Heatmap** | Combine analyst consensus + insider activity + news sentiment into 1 "conviction" score. | Medium (new worker) |
| **Peer Comparison Matrix** | Industry peers + fundamental metrics for relative valuation. | Medium (new endpoint) |
| **Options Chain** | Strike prices, Greeks, implied volatility. Requires new data provider. | High (new S2 consumer) |
| **Regulatory Filings Feed** | SEC 10-K/8-K, proxy statements. Requires EDGAR integration. | High (new content pipeline) |
| **Insider Roster with Holdings** | Officers, board members, holdings %. Requires EODHD Officers integration. | Medium (EODHD fix + worker) |

---

## Summary

**Total Gateway Endpoints Documented**: 96
**Data Fields NOT Currently Displayed**: ~75 across fundamentals, news, KG, chat, portfolio, alerts
**Highest-Leverage Quick Wins**: Company description, analyst targets, sentiment trends, sector classification, holdings tables

---
