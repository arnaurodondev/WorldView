# EODHD Endpoints Canonical Reference

- Generated from eodhd-claude-skills endpoint docs on 2026-03-13.
- Source folder: /Users/arnaurodon/Projects/University/Final Thesis/eodhd-claude-skills/skills/eodhd-api/references/endpoints
- Endpoint count: 72
- Scope: endpoint purpose, inputs (parameters), and outputs (response shapes), plus method/auth/URL metadata.
- Usage: reference this file from execution prompts and implementation notes when endpoint contract details are needed.

## Index

| Endpoint | Slug | Source file |
|---|---|---|
| [Bulk Fundamentals API](#bulk-fundamentals) | bulk-fundamentals | `/Users/arnaurodon/Projects/University/Final Thesis/eodhd-claude-skills/skills/eodhd-api/references/endpoints/bulk-fundamentals.md` |
| [Cboe Index Data API](#cboe-index-data) | cboe-index-data | `/Users/arnaurodon/Projects/University/Final Thesis/eodhd-claude-skills/skills/eodhd-api/references/endpoints/cboe-index-data.md` |
| [Cboe Indices List API](#cboe-indices-list) | cboe-indices-list | `/Users/arnaurodon/Projects/University/Final Thesis/eodhd-claude-skills/skills/eodhd-api/references/endpoints/cboe-indices-list.md` |
| [Financial News API](#company-news) | company-news | `/Users/arnaurodon/Projects/University/Final Thesis/eodhd-claude-skills/skills/eodhd-api/references/endpoints/company-news.md` |
| [Earnings Trends API](#earnings-trends) | earnings-trends | `/Users/arnaurodon/Projects/University/Final Thesis/eodhd-claude-skills/skills/eodhd-api/references/endpoints/earnings-trends.md` |
| [Economic Events API](#economic-events) | economic-events | `/Users/arnaurodon/Projects/University/Final Thesis/eodhd-claude-skills/skills/eodhd-api/references/endpoints/economic-events.md` |
| [Exchange Details API (Trading Hours, Stock Market Holidays)](#exchange-details) | exchange-details | `/Users/arnaurodon/Projects/University/Final Thesis/eodhd-claude-skills/skills/eodhd-api/references/endpoints/exchange-details.md` |
| [Exchange Symbol List API](#exchange-tickers) | exchange-tickers | `/Users/arnaurodon/Projects/University/Final Thesis/eodhd-claude-skills/skills/eodhd-api/references/endpoints/exchange-tickers.md` |
| [Exchanges List API](#exchanges-list) | exchanges-list | `/Users/arnaurodon/Projects/University/Final Thesis/eodhd-claude-skills/skills/eodhd-api/references/endpoints/exchanges-list.md` |
| [Fundamentals Data API](#fundamentals-data) | fundamentals-data | `/Users/arnaurodon/Projects/University/Final Thesis/eodhd-claude-skills/skills/eodhd-api/references/endpoints/fundamentals-data.md` |
| [Historical Market Capitalization API](#historical-market-cap) | historical-market-cap | `/Users/arnaurodon/Projects/University/Final Thesis/eodhd-claude-skills/skills/eodhd-api/references/endpoints/historical-market-cap.md` |
| [Historical Stock Prices API (End-of-Day)](#historical-stock-prices) | historical-stock-prices | `/Users/arnaurodon/Projects/University/Final Thesis/eodhd-claude-skills/skills/eodhd-api/references/endpoints/historical-stock-prices.md` |
| [Illio Market Insights — Best and Worst Days API](#illio-market-insights-best-worst) | illio-market-insights-best-worst | `/Users/arnaurodon/Projects/University/Final Thesis/eodhd-claude-skills/skills/eodhd-api/references/endpoints/illio-market-insights-best-worst.md` |
| [Illio Market Insights — Beta Bands API](#illio-market-insights-beta-bands) | illio-market-insights-beta-bands | `/Users/arnaurodon/Projects/University/Final Thesis/eodhd-claude-skills/skills/eodhd-api/references/endpoints/illio-market-insights-beta-bands.md` |
| [Illio Market Insights — Largest Volatility Change API](#illio-market-insights-largest-volatility) | illio-market-insights-largest-volatility | `/Users/arnaurodon/Projects/University/Final Thesis/eodhd-claude-skills/skills/eodhd-api/references/endpoints/illio-market-insights-largest-volatility.md` |
| [Illio Market Insights — Performance vs Market API](#illio-market-insights-performance) | illio-market-insights-performance | `/Users/arnaurodon/Projects/University/Final Thesis/eodhd-claude-skills/skills/eodhd-api/references/endpoints/illio-market-insights-performance.md` |
| [Illio Market Insights — Risk-Return API](#illio-market-insights-risk-return) | illio-market-insights-risk-return | `/Users/arnaurodon/Projects/University/Final Thesis/eodhd-claude-skills/skills/eodhd-api/references/endpoints/illio-market-insights-risk-return.md` |
| [Illio Market Insights — Volatility Bands API](#illio-market-insights-volatility) | illio-market-insights-volatility | `/Users/arnaurodon/Projects/University/Final Thesis/eodhd-claude-skills/skills/eodhd-api/references/endpoints/illio-market-insights-volatility.md` |
| [Illio Performance Insights API](#illio-performance-insights) | illio-performance-insights | `/Users/arnaurodon/Projects/University/Final Thesis/eodhd-claude-skills/skills/eodhd-api/references/endpoints/illio-performance-insights.md` |
| [Illio Risk Insights API](#illio-risk-insights) | illio-risk-insights | `/Users/arnaurodon/Projects/University/Final Thesis/eodhd-claude-skills/skills/eodhd-api/references/endpoints/illio-risk-insights.md` |
| [Index Components API](#index-components) | index-components | `/Users/arnaurodon/Projects/University/Final Thesis/eodhd-claude-skills/skills/eodhd-api/references/endpoints/index-components.md` |
| [List of Indices with Details API](#indices-list) | indices-list | `/Users/arnaurodon/Projects/University/Final Thesis/eodhd-claude-skills/skills/eodhd-api/references/endpoints/indices-list.md` |
| [Insider Transactions API](#insider-transactions) | insider-transactions | `/Users/arnaurodon/Projects/University/Final Thesis/eodhd-claude-skills/skills/eodhd-api/references/endpoints/insider-transactions.md` |
| [Intraday Historical Data API](#intraday-historical-data) | intraday-historical-data | `/Users/arnaurodon/Projects/University/Final Thesis/eodhd-claude-skills/skills/eodhd-api/references/endpoints/intraday-historical-data.md` |
| [Investverte ESG List Companies API](#investverte-esg-list-companies) | investverte-esg-list-companies | `/Users/arnaurodon/Projects/University/Final Thesis/eodhd-claude-skills/skills/eodhd-api/references/endpoints/investverte-esg-list-companies.md` |
| [Investverte ESG List Countries API](#investverte-esg-list-countries) | investverte-esg-list-countries | `/Users/arnaurodon/Projects/University/Final Thesis/eodhd-claude-skills/skills/eodhd-api/references/endpoints/investverte-esg-list-countries.md` |
| [Investverte ESG List Sectors API](#investverte-esg-list-sectors) | investverte-esg-list-sectors | `/Users/arnaurodon/Projects/University/Final Thesis/eodhd-claude-skills/skills/eodhd-api/references/endpoints/investverte-esg-list-sectors.md` |
| [Investverte ESG View Company API](#investverte-esg-view-company) | investverte-esg-view-company | `/Users/arnaurodon/Projects/University/Final Thesis/eodhd-claude-skills/skills/eodhd-api/references/endpoints/investverte-esg-view-company.md` |
| [Investverte ESG View Country API](#investverte-esg-view-country) | investverte-esg-view-country | `/Users/arnaurodon/Projects/University/Final Thesis/eodhd-claude-skills/skills/eodhd-api/references/endpoints/investverte-esg-view-country.md` |
| [Investverte ESG View Sector API](#investverte-esg-view-sector) | investverte-esg-view-sector | `/Users/arnaurodon/Projects/University/Final Thesis/eodhd-claude-skills/skills/eodhd-api/references/endpoints/investverte-esg-view-sector.md` |
| [Live/Real-Time Price Data API](#live-price-data) | live-price-data | `/Users/arnaurodon/Projects/University/Final Thesis/eodhd-claude-skills/skills/eodhd-api/references/endpoints/live-price-data.md` |
| [Macro Indicator API](#macro-indicator) | macro-indicator | `/Users/arnaurodon/Projects/University/Final Thesis/eodhd-claude-skills/skills/eodhd-api/references/endpoints/macro-indicator.md` |
| [Marketplace Tick Data API (US Stock Market)](#marketplace-tick-data) | marketplace-tick-data | `/Users/arnaurodon/Projects/University/Final Thesis/eodhd-claude-skills/skills/eodhd-api/references/endpoints/marketplace-tick-data.md` |
| [News Word Weights API](#news-word-weights) | news-word-weights | `/Users/arnaurodon/Projects/University/Final Thesis/eodhd-claude-skills/skills/eodhd-api/references/endpoints/news-word-weights.md` |
| [Praams Bank Balance Sheet by ISIN API](#praams-bank-balance-sheet-by-isin) | praams-bank-balance-sheet-by-isin | `/Users/arnaurodon/Projects/University/Final Thesis/eodhd-claude-skills/skills/eodhd-api/references/endpoints/praams-bank-balance-sheet-by-isin.md` |
| [Praams Bank Balance Sheet by Ticker API](#praams-bank-balance-sheet-by-ticker) | praams-bank-balance-sheet-by-ticker | `/Users/arnaurodon/Projects/University/Final Thesis/eodhd-claude-skills/skills/eodhd-api/references/endpoints/praams-bank-balance-sheet-by-ticker.md` |
| [Praams Bank Income Statement by ISIN API](#praams-bank-income-statement-by-isin) | praams-bank-income-statement-by-isin | `/Users/arnaurodon/Projects/University/Final Thesis/eodhd-claude-skills/skills/eodhd-api/references/endpoints/praams-bank-income-statement-by-isin.md` |
| [Praams Bank Income Statement by Ticker API](#praams-bank-income-statement-by-ticker) | praams-bank-income-statement-by-ticker | `/Users/arnaurodon/Projects/University/Final Thesis/eodhd-claude-skills/skills/eodhd-api/references/endpoints/praams-bank-income-statement-by-ticker.md` |
| [Praams Bond Analysis by ISIN API](#praams-bond-analyze-by-isin) | praams-bond-analyze-by-isin | `/Users/arnaurodon/Projects/University/Final Thesis/eodhd-claude-skills/skills/eodhd-api/references/endpoints/praams-bond-analyze-by-isin.md` |
| [Praams Multi-Factor Bond Report by ISIN API](#praams-report-bond-by-isin) | praams-report-bond-by-isin | `/Users/arnaurodon/Projects/University/Final Thesis/eodhd-claude-skills/skills/eodhd-api/references/endpoints/praams-report-bond-by-isin.md` |
| [Praams Multi-Factor Equity Report by ISIN API](#praams-report-equity-by-isin) | praams-report-equity-by-isin | `/Users/arnaurodon/Projects/University/Final Thesis/eodhd-claude-skills/skills/eodhd-api/references/endpoints/praams-report-equity-by-isin.md` |
| [Praams Multi-Factor Equity Report by Ticker API](#praams-report-equity-by-ticker) | praams-report-equity-by-ticker | `/Users/arnaurodon/Projects/University/Final Thesis/eodhd-claude-skills/skills/eodhd-api/references/endpoints/praams-report-equity-by-ticker.md` |
| [Praams Equity Risk & Return Scoring by ISIN API](#praams-risk-scoring-by-isin) | praams-risk-scoring-by-isin | `/Users/arnaurodon/Projects/University/Final Thesis/eodhd-claude-skills/skills/eodhd-api/references/endpoints/praams-risk-scoring-by-isin.md` |
| [Praams Equity Risk & Return Scoring by Ticker API](#praams-risk-scoring-by-ticker) | praams-risk-scoring-by-ticker | `/Users/arnaurodon/Projects/University/Final Thesis/eodhd-claude-skills/skills/eodhd-api/references/endpoints/praams-risk-scoring-by-ticker.md` |
| [Praams Smart Investment Screener Bond API](#praams-smart-investment-screener-bond) | praams-smart-investment-screener-bond | `/Users/arnaurodon/Projects/University/Final Thesis/eodhd-claude-skills/skills/eodhd-api/references/endpoints/praams-smart-investment-screener-bond.md` |
| [Praams Smart Investment Screener Equity API](#praams-smart-investment-screener-equity) | praams-smart-investment-screener-equity | `/Users/arnaurodon/Projects/University/Final Thesis/eodhd-claude-skills/skills/eodhd-api/references/endpoints/praams-smart-investment-screener-equity.md` |
| [Sentiment Data API](#sentiment-data) | sentiment-data | `/Users/arnaurodon/Projects/University/Final Thesis/eodhd-claude-skills/skills/eodhd-api/references/endpoints/sentiment-data.md` |
| [Stock Market Logos API (SVG Extension)](#stock-market-logos-svg) | stock-market-logos-svg | `/Users/arnaurodon/Projects/University/Final Thesis/eodhd-claude-skills/skills/eodhd-api/references/endpoints/stock-market-logos-svg.md` |
| [Stock Market Logos API](#stock-market-logos) | stock-market-logos | `/Users/arnaurodon/Projects/University/Final Thesis/eodhd-claude-skills/skills/eodhd-api/references/endpoints/stock-market-logos.md` |
| [Stock Screener API](#stock-screener-data) | stock-screener-data | `/Users/arnaurodon/Projects/University/Final Thesis/eodhd-claude-skills/skills/eodhd-api/references/endpoints/stock-screener-data.md` |
| [Stocks From Search API](#stocks-from-search) | stocks-from-search | `/Users/arnaurodon/Projects/University/Final Thesis/eodhd-claude-skills/skills/eodhd-api/references/endpoints/stocks-from-search.md` |
| [Symbol Change History API](#symbol-change-history) | symbol-change-history | `/Users/arnaurodon/Projects/University/Final Thesis/eodhd-claude-skills/skills/eodhd-api/references/endpoints/symbol-change-history.md` |
| [Technical Indicators API](#technical-indicators) | technical-indicators | `/Users/arnaurodon/Projects/University/Final Thesis/eodhd-claude-skills/skills/eodhd-api/references/endpoints/technical-indicators.md` |
| [TradingHours List All Markets API](#tradinghours-list-markets) | tradinghours-list-markets | `/Users/arnaurodon/Projects/University/Final Thesis/eodhd-claude-skills/skills/eodhd-api/references/endpoints/tradinghours-list-markets.md` |
| [TradingHours Lookup Markets API](#tradinghours-lookup-markets) | tradinghours-lookup-markets | `/Users/arnaurodon/Projects/University/Final Thesis/eodhd-claude-skills/skills/eodhd-api/references/endpoints/tradinghours-lookup-markets.md` |
| [TradingHours Get Market Details API](#tradinghours-market-details) | tradinghours-market-details | `/Users/arnaurodon/Projects/University/Final Thesis/eodhd-claude-skills/skills/eodhd-api/references/endpoints/tradinghours-market-details.md` |
| [TradingHours Market Status Details API](#tradinghours-market-status) | tradinghours-market-status | `/Users/arnaurodon/Projects/University/Final Thesis/eodhd-claude-skills/skills/eodhd-api/references/endpoints/tradinghours-market-status.md` |
| [Historical & Upcoming Dividends API](#upcoming-dividends) | upcoming-dividends | `/Users/arnaurodon/Projects/University/Final Thesis/eodhd-claude-skills/skills/eodhd-api/references/endpoints/upcoming-dividends.md` |
| [Historical & Upcoming Earnings API](#upcoming-earnings) | upcoming-earnings | `/Users/arnaurodon/Projects/University/Final Thesis/eodhd-claude-skills/skills/eodhd-api/references/endpoints/upcoming-earnings.md` |
| [Historical & Upcoming IPOs API](#upcoming-ipos) | upcoming-ipos | `/Users/arnaurodon/Projects/University/Final Thesis/eodhd-claude-skills/skills/eodhd-api/references/endpoints/upcoming-ipos.md` |
| [Historical & Upcoming Splits API](#upcoming-splits) | upcoming-splits | `/Users/arnaurodon/Projects/University/Final Thesis/eodhd-claude-skills/skills/eodhd-api/references/endpoints/upcoming-splits.md` |
| [US Live Extended Quotes API (Live v2)](#us-live-extended-quotes) | us-live-extended-quotes | `/Users/arnaurodon/Projects/University/Final Thesis/eodhd-claude-skills/skills/eodhd-api/references/endpoints/us-live-extended-quotes.md` |
| [US Options Contracts API](#us-options-contracts) | us-options-contracts | `/Users/arnaurodon/Projects/University/Final Thesis/eodhd-claude-skills/skills/eodhd-api/references/endpoints/us-options-contracts.md` |
| [US Options EOD (End-of-Day) API](#us-options-eod) | us-options-eod | `/Users/arnaurodon/Projects/University/Final Thesis/eodhd-claude-skills/skills/eodhd-api/references/endpoints/us-options-eod.md` |
| [US Options Underlying Symbols API](#us-options-underlyings) | us-options-underlyings | `/Users/arnaurodon/Projects/University/Final Thesis/eodhd-claude-skills/skills/eodhd-api/references/endpoints/us-options-underlyings.md` |
| [Tick Data API](#us-tick-data) | us-tick-data | `/Users/arnaurodon/Projects/University/Final Thesis/eodhd-claude-skills/skills/eodhd-api/references/endpoints/us-tick-data.md` |
| [User Details API](#user-details) | user-details | `/Users/arnaurodon/Projects/University/Final Thesis/eodhd-claude-skills/skills/eodhd-api/references/endpoints/user-details.md` |
| [US Treasury Bill Rates API](#ust-bill-rates) | ust-bill-rates | `/Users/arnaurodon/Projects/University/Final Thesis/eodhd-claude-skills/skills/eodhd-api/references/endpoints/ust-bill-rates.md` |
| [US Treasury Long-Term Rates API](#ust-long-term-rates) | ust-long-term-rates | `/Users/arnaurodon/Projects/University/Final Thesis/eodhd-claude-skills/skills/eodhd-api/references/endpoints/ust-long-term-rates.md` |
| [US Treasury Real Yield Rates API (Par Real Yield Curve)](#ust-real-yield-rates) | ust-real-yield-rates | `/Users/arnaurodon/Projects/University/Final Thesis/eodhd-claude-skills/skills/eodhd-api/references/endpoints/ust-real-yield-rates.md` |
| [US Treasury Yield Rates API (Par Yield Curve)](#ust-yield-rates) | ust-yield-rates | `/Users/arnaurodon/Projects/University/Final Thesis/eodhd-claude-skills/skills/eodhd-api/references/endpoints/ust-yield-rates.md` |
| [WebSockets Real-Time Data API](#websockets-realtime) | websockets-realtime | `/Users/arnaurodon/Projects/University/Final Thesis/eodhd-claude-skills/skills/eodhd-api/references/endpoints/websockets-realtime.md` |

---

## Bulk Fundamentals API

<a id="bulk-fundamentals"></a>

### Endpoint Metadata

| Field | Value |
|---|---|
| Status | complete |
| Source | financial-apis (Fundamentals API) |
| Docs | https://eodhd.com/financial-apis/bulk-fundamentals-api |
| Provider | EODHD |
| Base URL | https://eodhd.com/api |
| Path | /bulk-fundamentals/{EXCHANGE} |
| Method | GET |
| Auth | api_token (query) |
| Slug | `bulk-fundamentals` |
| Source File | `/Users/arnaurodon/Projects/University/Final Thesis/eodhd-claude-skills/skills/eodhd-api/references/endpoints/bulk-fundamentals.md` |

### Purpose

Download fundamental data for hundreds of companies in a single request. Returns General info, Highlights, Valuation, Technicals, Splits/Dividends, Earnings (last 4 quarters), and full Financials (Balance Sheet, Cash Flow, Income Statement) with last 4 quarters and last 4 years of history. Available only via the Extended Fundamentals subscription plan (contact support@eodhistoricaldata.com).

### Inputs

| Parameter | Required | Type | Description |
|-----------|----------|------|-------------|
| api_token | Yes | string | Your API access token |
| {EXCHANGE} | Yes | path | Exchange code (e.g., NASDAQ, NYSE, US, LSE). US exchanges can be addressed separately: NASDAQ, NYSE, BATS, AMEX |
| symbols | No | string | Comma-separated list of specific symbols (e.g., AAPL.US,MSFT.US). When specified, the exchange code in the path is ignored |
| offset | No | integer | Starting symbol position for pagination (default: 0) |
| limit | No | integer | Number of symbols to return (default: 500, max: 500) |
| fmt | No | string | Response format: json (recommended) or csv (default) |
| version | No | string | Set to "1.2" for output closer to the single-symbol Fundamentals API template (includes Earnings Trends). JSON only |

### Outputs

```json
{
  "0": {
    "General": {
      "Code": "AAPL",
      "Type": "Common Stock",
      "Name": "Apple Inc",
      "Exchange": "NASDAQ",
      "CurrencyCode": "USD",
      "CountryName": "USA",
      "CountryISO": "US",
      "ISIN": "US0378331005",
      "PrimaryTicker": "AAPL.US",
      "CUSIP": "037833100",
      "Sector": "Technology",
      "Industry": "Consumer Electronics",
      "Description": "Apple Inc. designs, manufactures...",
      "FullTimeEmployees": 150000,
      "UpdatedAt": "2026-02-15"
    },
    "Highlights": {
      "MarketCapitalization": 3759435415552,
      "MarketCapitalizationMln": 3759435.4156,
      "EBITDA": 152901992448,
      "PERatio": 32.3772,
      "PEGRatio": 2.3096,
      "WallStreetTargetPrice": 292.1462,
      "BookValue": 5.998,
      "DividendShare": 1.03,
      "DividendYield": 0.0039,
      "EarningsShare": 7.9,
      "EPSEstimateCurrentYear": 8.4911,
      "EPSEstimateNextYear": 9.313,
      "MostRecentQuarter": "2025-12-31",
      "ProfitMargin": 0.2704,
      "OperatingMarginTTM": 0.3537,
      "ReturnOnAssetsTTM": 0.2438,
      "ReturnOnEquityTTM": 1.5202,
      "RevenueTTM": 435617005568,
      "DilutedEpsTTM": 7.9,
      "QuarterlyEarningsGrowthYOY": 0.183
    },
    "Valuation": {
      "TrailingPE": 32.3772,
      "ForwardPE": 30.2115,
      "PriceSalesTTM": 8.6301,
      "PriceBookMRQ": 42.5801,
      "EnterpriseValueRevenue": 8.6745,
      "EnterpriseValueEbitda": 24.7135
    },
    "Technicals": {
      "Beta": 1.107,
      "52WeekHigh": 288.3502,
      "52WeekLow": 168.4757,
      "50DayMA": 267.4752,
      "200DayMA": 240.0591,
      "SharesShort": 116854414,
      "ShortRatio": 2.36,
      "ShortPercent": 0.008
    },
    "SplitsDividends": {
      "ForwardAnnualDividendRate": 1.04,
      "ForwardAnnualDividendYield": 0.0041,
      "PayoutRatio": 0.1315,
      "DividendDate": "2026-02-12",
      "ExDividendDate": "2026-02-09",
      "LastSplitFactor": "4:1",
      "LastSplitDate": "2020-08-31"
    },
    "Earnings": {
      "Last_0": {
        "reportDate": "2026-01-29",
        "date": "2025-12-31",
        "epsActual": 2.84,
        "epsEstimate": 2.67,
        "epsDifference": 0.17,
        "surprisePercent": 6.367
      },
      "Last_1": { "reportDate": "2025-10-30", "date": "2025-09-30", "epsActual": 1.64, "epsEstimate": 1.60, "epsDifference": 0.04, "surprisePercent": 2.5 },
      "Last_2": { "reportDate": "2025-07-31", "date": "2025-06-30", "epsActual": 1.40, "epsEstimate": 1.35, "epsDifference": 0.05, "surprisePercent": 3.7 },
      "Last_3": { "reportDate": "2025-05-01", "date": "2025-03-31", "epsActual": 1.65, "epsEstimate": 1.62, "epsDifference": 0.03, "surprisePercent": 1.85 }
    },
    "Financials": {
      "Balance_Sheet": {
        "currency_symbol": "USD",
        "quarterly_last_0": { "date": "2025-12-31", "totalAssets": "379297000000.00", "totalLiab": "302083000000.00" },
        "quarterly_last_1": { "date": "2025-09-30", "totalAssets": "364980000000.00", "totalLiab": "290437000000.00" },
        "quarterly_last_2": { "date": "2025-06-30", "totalAssets": "352583000000.00", "totalLiab": "279414000000.00" },
        "quarterly_last_3": { "date": "2025-03-31", "totalAssets": "337411000000.00", "totalLiab": "268158000000.00" },
        "yearly_last_0": { "date": "2025-09-30", "totalAssets": "364980000000.00", "totalLiab": "290437000000.00" },
        "yearly_last_1": { "date": "2024-09-30", "totalAssets": "352583000000.00", "totalLiab": "279414000000.00" },
        "yearly_last_2": { "date": "2023-09-30", "totalAssets": "337411000000.00", "totalLiab": "268158000000.00" },
        "yearly_last_3": { "date": "2022-09-30", "totalAssets": "352755000000.00", "totalLiab": "302083000000.00" }
      },
      "Cash_Flow": { "currency_symbol": "USD", "quarterly_last_0": { "date": "2025-12-31", "totalCashFromOperatingActivities": "39895000000.00" } },
      "Income_Statement": { "currency_symbol": "USD", "quarterly_last_0": { "date": "2025-12-31", "totalRevenue": "124300000000.00" } }
    }
  },
  "1": { "General": { "Code": "MSFT", "Name": "Microsoft Corporation" } }
}
```

### Output Format

The response is a JSON object keyed by numeric index ("0", "1", ...). Each entry contains the following sections:

**General fields:**

| Field | Type | Description |
|-------|------|-------------|
| Code | string | Ticker symbol |
| Type | string | Instrument type (e.g., Common Stock) |
| Name | string | Company name |
| Exchange | string | Exchange name |
| CurrencyCode | string | Trading currency (ISO alpha-3) |
| CountryName | string | Country name |
| CountryISO | string | Country ISO code |
| OpenFigi | string | OpenFIGI identifier |
| ISIN | string | International Securities Identification Number |
| LEI | string | Legal Entity Identifier |
| PrimaryTicker | string | Primary ticker in EODHD format |
| CUSIP | string | CUSIP identifier |
| Sector | string | Company sector |
| Industry | string | Company industry |
| Description | string | Company description |
| FullTimeEmployees | integer | Number of full-time employees |
| UpdatedAt | string (YYYY-MM-DD) | Last update date |

**Highlights fields:**

| Field | Type | Description |
|-------|------|-------------|
| MarketCapitalization | integer | Market cap in currency units |
| MarketCapitalizationMln | float | Market cap in millions |
| EBITDA | integer | EBITDA |
| PERatio | float | Price-to-earnings ratio |
| PEGRatio | float | Price/earnings-to-growth ratio |
| WallStreetTargetPrice | float | Analyst consensus target price |
| BookValue | float | Book value per share |
| DividendShare | float | Dividend per share |
| DividendYield | float | Dividend yield (decimal) |
| EarningsShare | float | Earnings per share (TTM) |
| EPSEstimateCurrentYear | float | EPS estimate for current fiscal year |
| EPSEstimateNextYear | float | EPS estimate for next fiscal year |
| EPSEstimateNextQuarter | float | EPS estimate for next quarter |
| MostRecentQuarter | string (YYYY-MM-DD) | Most recent quarter end date |
| ProfitMargin | float | Net profit margin (decimal) |
| OperatingMarginTTM | float | Operating margin TTM (decimal) |
| ReturnOnAssetsTTM | float | Return on assets TTM (decimal) |
| ReturnOnEquityTTM | float | Return on equity TTM (decimal) |
| RevenueTTM | integer | Revenue TTM |
| RevenuePerShareTTM | float | Revenue per share TTM |
| QuarterlyRevenueGrowthYOY | float | Quarterly revenue growth YoY (decimal) |
| GrossProfitTTM | integer | Gross profit TTM |
| DilutedEpsTTM | float | Diluted EPS TTM |
| QuarterlyEarningsGrowthYOY | float | Quarterly earnings growth YoY (decimal) |

**Valuation fields:**

| Field | Type | Description |
|-------|------|-------------|
| TrailingPE | float | Trailing P/E ratio |
| ForwardPE | float | Forward P/E ratio |
| PriceSalesTTM | float | Price-to-sales TTM |
| PriceBookMRQ | float | Price-to-book MRQ |
| EnterpriseValueRevenue | float | EV/Revenue |
| EnterpriseValueEbitda | float | EV/EBITDA |

**Technicals fields:**

| Field | Type | Description |
|-------|------|-------------|
| Beta | float | Beta coefficient |
| 52WeekHigh | float | 52-week high price |
| 52WeekLow | float | 52-week low price |
| 50DayMA | float | 50-day moving average |
| 200DayMA | float | 200-day moving average |
| SharesShort | integer | Shares sold short |
| SharesShortPriorMonth | integer | Shares short prior month |
| ShortRatio | float | Short ratio (days to cover) |
| ShortPercent | float | Short interest as percent of float |

**Earnings fields (Last_0 through Last_3):**

| Field | Type | Description |
|-------|------|-------------|
| reportDate | string (YYYY-MM-DD) | Earnings report date |
| date | string (YYYY-MM-DD) | Quarter end date |
| epsActual | float | Actual EPS |
| epsEstimate | float | Estimated EPS |
| epsDifference | float | EPS surprise (actual - estimate) |
| surprisePercent | float | Surprise percentage |

**Financials (Balance_Sheet, Cash_Flow, Income_Statement):**

Each section contains `quarterly_last_0` through `quarterly_last_3` and `yearly_last_0` through `yearly_last_3`. Fields match the standard Fundamentals API with values as stringified numbers.

### Example Requests

```bash
# All NASDAQ stocks (first 500)
curl "https://eodhd.com/api/bulk-fundamentals/NASDAQ?api_token=YOUR_TOKEN&fmt=json"

# Specific symbols (exchange code in path is ignored)
curl "https://eodhd.com/api/bulk-fundamentals/NASDAQ?symbols=AAPL.US,MSFT.US&api_token=YOUR_TOKEN&fmt=json"

# Paginated: 100 symbols starting from position 500
curl "https://eodhd.com/api/bulk-fundamentals/NASDAQ?offset=500&limit=100&api_token=YOUR_TOKEN&fmt=json"

# Version 1.2 output (closer to single-symbol fundamentals template)
curl "https://eodhd.com/api/bulk-fundamentals/NASDAQ?symbols=AAPL.US&version=1.2&api_token=YOUR_TOKEN&fmt=json"

# Using the helper client (exchange-based)
python eodhd_client.py --endpoint bulk-fundamentals --symbol NASDAQ --limit 100

# Using the helper client (specific symbols via --symbols)
python eodhd_client.py --endpoint bulk-fundamentals --symbol NASDAQ --symbols AAPL.US,MSFT.US
```

### Notes

- **Plan requirement**: Requires the Extended Fundamentals subscription plan (contact support@eodhistoricaldata.com)
- **API call cost**: 100 API calls per request. When `symbols` parameter is used, cost is 100 + number of symbols (e.g., 3 symbols = 103 calls)
- **Stocks only**: ETFs and Mutual Funds are not supported
- **Pagination**: Default offset=0, limit=500. Maximum limit is 500 (values above are reset to 500)
- **US exchanges**: NASDAQ, NYSE (or NYSE MKT), BATS, AMEX can be addressed separately in addition to the general "US" code
- **Default format**: CSV. Always add `fmt=json` for JSON output (strongly recommended)
- **Historical data**: Limited to last 4 quarters and last 4 years
- **Version 1.2**: Add `version=1.2` for output closer to single-symbol Fundamentals API (includes Earnings Trends). JSON only
- **When `symbols` is specified**: The exchange code in the path is ignored
- The response is an object keyed by numeric index ("0", "1", ...), not an array

### HTTP Status Codes

The API returns standard HTTP status codes to indicate success or failure:

| Status Code | Meaning | Description |
|-------------|---------|-------------|
| **200** | OK | Request succeeded. Data returned successfully. |
| **402** | Payment Required | API limit used up. Upgrade plan or wait for limit reset. |
| **403** | Unauthorized | Invalid API key. Check your `api_token` parameter. |
| **429** | Too Many Requests | Exceeded rate limit (requests per minute). Slow down requests. |

### Error Response Format

When an error occurs, the API returns a JSON response with error details:

```json
{
  "error": "Error message description",
  "code": 403
}
```

### Handling Errors

**Python Example**:
```python
import requests

def make_api_request(url, params):
    try:
        response = requests.get(url, params=params)
        response.raise_for_status()  # Raises HTTPError for bad status codes
        return response.json()
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 402:
            print("Error: API limit exceeded. Please upgrade your plan.")
        elif e.response.status_code == 403:
            print("Error: Invalid API key. Check your credentials.")
        elif e.response.status_code == 429:
            print("Error: Rate limit exceeded. Please slow down your requests.")
        else:
            print(f"HTTP Error: {e}")
        return None
    except requests.exceptions.RequestException as e:
        print(f"Request failed: {e}")
        return None
```

**Best Practices**:
- Always check status codes before processing response data
- Implement exponential backoff for 429 errors
- Cache responses to reduce API calls
- Monitor your API usage in the user dashboard
- Use `fmt=json` for all requests
- Use `symbols` parameter to minimize API call cost when you need specific companies
- Paginate large exchanges with `offset` and `limit` to manage response size

---

## Cboe Index Data API

<a id="cboe-index-data"></a>

### Endpoint Metadata

| Field | Value |
|---|---|
| Status | complete |
| Source | financial-apis (CBOE Europe Indices API beta) |
| Docs | https://eodhd.com/financial-apis/cboe-europe-indices-api-beta |
| Provider | EODHD |
| Base URL | https://eodhd.com/api |
| Path | /cboe/index |
| Method | GET |
| Auth | api_token (query) |
| Slug | `cboe-index-data` |
| Source File | `/Users/arnaurodon/Projects/University/Final Thesis/eodhd-claude-skills/skills/eodhd-api/references/endpoints/cboe-index-data.md` |

### Purpose

Return detailed index feed data for a single CBOE index on a specific date and
feed type, including index-level fields and full component composition.

### Inputs

| Parameter | Required | Type | Description |
|-----------|----------|------|-------------|
| filter[index_code] | Yes | string | CBOE index code (e.g., BAT20N) |
| filter[feed_type] | Yes | string | Feed type (e.g., snapshot_official_closing) |
| filter[date] | Yes | string | Date in YYYY-MM-DD format |
| api_token | Yes | string | EODHD API key |
| fmt | No | string | Output format: 'json' or 'xml' (default json) |

### Outputs

- meta.total: integer (usually 1).
- data[]: array of index feeds.
  - data[].id: feed identifier.
  - data[].type: "cboe-index".
  - data[].attributes.region: region of the index.
  - data[].attributes.index_code: CBOE index code.
  - data[].attributes.feed_type: feed type.
  - data[].attributes.date: YYYY-MM-DD.
  - data[].attributes.index_close: number.
  - data[].attributes.index_divisor: number.
  - data[].attributes.effective_date: nullable.
  - data[].attributes.review_date: nullable.
  - data[].components[]: list of constituents.
    - components[].id: component identifier.
    - components[].type: "cboe-index-component".
    - components[].attributes.symbol: ticker (often with suffix).
    - components[].attributes.isin: ISIN.
    - components[].attributes.name: company name.
    - components[].attributes.equity: equity identifier/description.
    - components[].attributes.sedol: nullable.
    - components[].attributes.cusip: CUSIP.
    - components[].attributes.country: issuer country.
    - components[].attributes.revenue_country: nullable.
    - components[].attributes.closing_price: number.
    - components[].attributes.currency: currency code.
    - components[].attributes.closing_factor: number.
    - components[].attributes.total_shares: integer.
    - components[].attributes.market_cap: number.
    - components[].attributes.market_cap_free_float: number.
    - components[].attributes.free_float_factor: number.
    - components[].attributes.weighting_cap_factor: number.
    - components[].attributes.index_weighting: number.
    - components[].attributes.index_shares: number.
    - components[].attributes.index_value: number.
    - components[].attributes.sector: string.

### Example Requests

```bash
curl "https://eodhd.com/api/cboe/index?filter[index_code]=BDE30P&filter[feed_type]=snapshot_official_closing&filter[date]=2017-02-01&api_token=YOUR_API_KEY&fmt=json"
```

### Notes

- **Subscription**: Available in plans that include CBOE data. Check your subscription for access.
- API call consumption: 10 calls per request.
- Use `/cboe/indices` first to discover supported index_code values.

### HTTP Status Codes

The API returns standard HTTP status codes to indicate success or failure:

| Status Code | Meaning | Description |
|-------------|---------|-------------|
| **200** | OK | Request succeeded. Data returned successfully. |
| **402** | Payment Required | API limit used up. Upgrade plan or wait for limit reset. |
| **403** | Unauthorized | Invalid API key. Check your `api_token` parameter. |
| **429** | Too Many Requests | Exceeded rate limit (requests per minute). Slow down requests. |

### Error Response Format

When an error occurs, the API returns a JSON response with error details:

```json
{
  "error": "Error message description",
  "code": 403
}
```

### Handling Errors

**Python Example**:
```python
import requests

def make_api_request(url, params):
    try:
        response = requests.get(url, params=params)
        response.raise_for_status()  # Raises HTTPError for bad status codes
        return response.json()
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 402:
            print("Error: API limit exceeded. Please upgrade your plan.")
        elif e.response.status_code == 403:
            print("Error: Invalid API key. Check your credentials.")
        elif e.response.status_code == 429:
            print("Error: Rate limit exceeded. Please slow down your requests.")
        else:
            print(f"HTTP Error: {e}")
        return None
    except requests.exceptions.RequestException as e:
        print(f"Request failed: {e}")
        return None
```

**Best Practices**:
- Always check status codes before processing response data
- Implement exponential backoff for 429 errors
- Cache responses to reduce API calls
- Monitor your API usage in the user dashboard

---

## Cboe Indices List API

<a id="cboe-indices-list"></a>

### Endpoint Metadata

| Field | Value |
|---|---|
| Status | complete |
| Source | financial-apis (CBOE Europe Indices API beta) |
| Docs | https://eodhd.com/financial-apis/cboe-europe-indices-api-beta |
| Provider | EODHD |
| Base URL | https://eodhd.com/api |
| Path | /cboe/indices |
| Method | GET |
| Auth | api_token (query) |
| Slug | `cboe-indices-list` |
| Source File | `/Users/arnaurodon/Projects/University/Final Thesis/eodhd-claude-skills/skills/eodhd-api/references/endpoints/cboe-indices-list.md` |

### Purpose

Return the full list of CBOE indices available via EODHD, including the latest
close and divisor plus basic metadata needed to select an index code for the
feed endpoint.

### Inputs

| Parameter | Required | Type | Description |
|-----------|----------|------|-------------|
| api_token | Yes | string | EODHD API key |
| fmt | No | string | Output format: 'json' or 'xml' (default json) |
| pagination | No | — | Follow the URL in links.next until null (no manual params) |

### Outputs

- meta.total: integer total returned in this response.
- data[]: array of index entries.
  - data[].id: EODHD index identifier (often same as index_code).
  - data[].type: "cboe-index".
  - data[].attributes.region: country/region.
  - data[].attributes.index_code: CBOE index code.
  - data[].attributes.feed_type: latest feed type.
  - data[].attributes.date: YYYY-MM-DD.
  - data[].attributes.index_close: number.
  - data[].attributes.index_divisor: number.
- links.next: string or null pagination URL.

### Example Requests

```bash
curl "https://eodhd.com/api/cboe/indices?api_token=YOUR_API_KEY&fmt=json"
```

### Notes

- **Subscription**: Available in plans that include CBOE data. Check your subscription for access.
- API call consumption: 10 calls per request.
- Use this endpoint to discover supported indices and the index_code for
  the detailed feed endpoint.

### HTTP Status Codes

The API returns standard HTTP status codes to indicate success or failure:

| Status Code | Meaning | Description |
|-------------|---------|-------------|
| **200** | OK | Request succeeded. Data returned successfully. |
| **402** | Payment Required | API limit used up. Upgrade plan or wait for limit reset. |
| **403** | Unauthorized | Invalid API key. Check your `api_token` parameter. |
| **429** | Too Many Requests | Exceeded rate limit (requests per minute). Slow down requests. |

### Error Response Format

When an error occurs, the API returns a JSON response with error details:

```json
{
  "error": "Error message description",
  "code": 403
}
```

### Handling Errors

**Python Example**:
```python
import requests

def make_api_request(url, params):
    try:
        response = requests.get(url, params=params)
        response.raise_for_status()  # Raises HTTPError for bad status codes
        return response.json()
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 402:
            print("Error: API limit exceeded. Please upgrade your plan.")
        elif e.response.status_code == 403:
            print("Error: Invalid API key. Check your credentials.")
        elif e.response.status_code == 429:
            print("Error: Rate limit exceeded. Please slow down your requests.")
        else:
            print(f"HTTP Error: {e}")
        return None
    except requests.exceptions.RequestException as e:
        print(f"Request failed: {e}")
        return None
```

**Best Practices**:
- Always check status codes before processing response data
- Implement exponential backoff for 429 errors
- Cache responses to reduce API calls
- Monitor your API usage in the user dashboard

---

## Financial News API

<a id="company-news"></a>

### Endpoint Metadata

| Field | Value |
|---|---|
| Status | complete |
| Source | financial-apis (Financial News Feed and Stock News Sentiment data API) |
| Docs | https://eodhd.com/financial-apis/financial-news-api |
| Provider | EODHD |
| Base URL | https://eodhd.com/api |
| Path | /news |
| Method | GET |
| Auth | api_token (query) |
| Slug | `company-news` |
| Source File | `/Users/arnaurodon/Projects/University/Final Thesis/eodhd-claude-skills/skills/eodhd-api/references/endpoints/company-news.md` |

### Purpose

Returns the latest financial news headlines and full articles for a given ticker symbol or topic tag.
Includes sentiment analysis scores for each article. Useful for news monitoring, sentiment analysis,
event detection, and market context.

**API Call Consumption**: 5 API calls per request + 5 API calls per ticker.
Example: 10 API calls for one request with two tickers.

### Inputs

| Parameter | Required | Type | Description |
|-----------|----------|------|-------------|
| s | Yes (if t not set) | string | Ticker code (e.g., AAPL.US) |
| t | Yes (if s not set) | string | Topic tag (e.g., technology, earnings) |
| from | No | string (YYYY-MM-DD) | Start date for filtering news |
| to | No | string (YYYY-MM-DD) | End date for filtering news |
| limit | No | integer | Number of results (default: 50, min: 1, max: 1000) |
| offset | No | integer | Offset for pagination (default: 0) |
| fmt | No | string | Response format: json or xml (default: json) |
| api_token | Yes | string | Your API access token |

**Note**: At least one of `s` (ticker) or `t` (tag) is required.

### Outputs

Array of news article objects:

```json
[
  {
    "date": "2026-02-09T17:09:51+00:00",
    "title": "Stock Market Today: Dow Firm As Nvidia, Microsoft Jump",
    "content": "Full article body text...",
    "link": "https://finance.yahoo.com/...",
    "symbols": ["AAPL.US", "MSFT.US", "NVDA.US"],
    "tags": ["ENERGY", "STOCK-MARKET", "TECH"],
    "sentiment": {
      "polarity": -0.026,
      "neg": 0.084,
      "neu": 0.837,
      "pos": 0.08
    }
  }
]
```

### Field Descriptions

| Field | Type | Description |
|-------|------|-------------|
| date | string (ISO 8601) | Publication date and time |
| title | string | Headline of the news article |
| content | string | Full article body |
| link | string | Direct URL to the article |
| symbols | array | Ticker symbols mentioned in the article |
| tags | array | Topic tags (may be empty) |
| sentiment | object | Sentiment scores (see below) |

### Sentiment Object

| Field | Type | Description |
|-------|------|-------------|
| polarity | float | Overall sentiment score (-1 to +1) |
| neg | float | Negative sentiment probability (0 to 1) |
| neu | float | Neutral sentiment probability (0 to 1) |
| pos | float | Positive sentiment probability (0 to 1) |

### Example Requests

```bash
# News for a specific symbol
curl "https://eodhd.com/api/news?s=AAPL.US&offset=0&limit=10&api_token=demo&fmt=json"

# News for multiple symbols
curl "https://eodhd.com/api/news?s=AAPL.US,MSFT.US&limit=20&api_token=demo&fmt=json"

# News by topic tag
curl "https://eodhd.com/api/news?t=technology&limit=10&api_token=demo&fmt=json"

# News with date range
curl "https://eodhd.com/api/news?s=AAPL.US&from=2025-01-01&to=2025-01-31&api_token=demo&fmt=json"

# Using the helper client
python eodhd_client.py --endpoint news --symbol AAPL.US --limit 10

# With date filtering
python eodhd_client.py --endpoint news --symbol TSLA.US --from-date 2025-01-01 --to-date 2025-01-31 --limit 20
```

### Notes

- Sentiment `polarity` ranges from -1 (very negative) to +1 (very positive)
- `neg`, `neu`, `pos` probabilities sum to approximately 1.0
- News is aggregated from multiple financial news portals
- AI-powered tags make search more flexible beyond standard 50 tags
- Content may be truncated for some sources
- Use pagination (`offset`, `limit`) for large result sets
- Available in: Standalone package, All-In-One, EOD Historical Data, Fundamentals Data Feed, Free plan
- **One topic per request**: You can request only one tag/topic per API request.
- **Timezone**: All news timestamps are in **UTC**.
- **Sentiment thresholds**: In general, if the polarity is positive it is "good" news, and if negative it is "bad" news. There is no fixed threshold — polarity sign indicates direction.

### HTTP Status Codes

The API returns standard HTTP status codes to indicate success or failure:

| Status Code | Meaning | Description |
|-------------|---------|-------------|
| **200** | OK | Request succeeded. Data returned successfully. |
| **402** | Payment Required | API limit used up. Upgrade plan or wait for limit reset. |
| **403** | Unauthorized | Invalid API key. Check your `api_token` parameter. |
| **429** | Too Many Requests | Exceeded rate limit (requests per minute). Slow down requests. |

### Error Response Format

When an error occurs, the API returns a JSON response with error details:

```json
{
  "error": "Error message description",
  "code": 403
}
```

### Handling Errors

**Python Example**:
```python
import requests

def make_api_request(url, params):
    try:
        response = requests.get(url, params=params)
        response.raise_for_status()  # Raises HTTPError for bad status codes
        return response.json()
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 402:
            print("Error: API limit exceeded. Please upgrade your plan.")
        elif e.response.status_code == 403:
            print("Error: Invalid API key. Check your credentials.")
        elif e.response.status_code == 429:
            print("Error: Rate limit exceeded. Please slow down your requests.")
        else:
            print(f"HTTP Error: {e}")
        return None
    except requests.exceptions.RequestException as e:
        print(f"Request failed: {e}")
        return None
```

**Best Practices**:
- Always check status codes before processing response data
- Implement exponential backoff for 429 errors
- Cache responses to reduce API calls
- Monitor your API usage in the user dashboard

---

## Earnings Trends API

<a id="earnings-trends"></a>

### Endpoint Metadata

| Field | Value |
|---|---|
| Status | complete |
| Source | financial-apis (Calendar API) |
| Docs | https://eodhd.com/financial-apis/calendar-upcoming-earnings-ipos-and-splits |
| Provider | EODHD |
| Base URL | https://eodhd.com/api |
| Path | /calendar/trends |
| Method | GET |
| Auth | api_token (query) |
| Slug | `earnings-trends` |
| Source File | `/Users/arnaurodon/Projects/University/Final Thesis/eodhd-claude-skills/skills/eodhd-api/references/endpoints/earnings-trends.md` |

### Purpose

Returns forward-looking and historical earnings trend points for one or more symbols. Each symbol returns a list of dated items that indicate whether that point is an estimate or an actual. The endpoint is JSON-only. Available in All-In-One, Fundamentals Data Feed plans and via "Financial Events (Calendar) & News Feed" plans.

### Inputs

| Parameter | Required | Type | Description |
|-----------|----------|------|-------------|
| api_token | Yes | string | Your API key |
| symbols | Yes | string | One or more tickers, comma-separated (example: AAPL.US,MSFT.US,AI.PA) |
| fmt | No | string | json only |

### Outputs

```json
{
  "type": "Trends",
  "description": "Historical and upcoming earning trends",
  "symbols": "AAPL.US,MSFT.US,AI.PA",
  "trends": [
    [
      {
        "code": "AAPL.US",
        "date": "2026-09-30",
        "period": "+1y",
        "growth": "0.0846",
        "earningsEstimateAvg": "7.9816",
        "earningsEstimateLow": "7.1300",
        "earningsEstimateHigh": "9.0000",
        "earningsEstimateYearAgoEps": "7.3676",
        "earningsEstimateNumberOfAnalysts": "40.0000",
        "earningsEstimateGrowth": "0.0833",
        "revenueEstimateAvg": "437035017610.00",
        "revenueEstimateLow": "408100000000.00",
        "revenueEstimateHigh": "477463000000.00",
        "revenueEstimateYearAgoEps": null,
        "revenueEstimateNumberOfAnalysts": "41.00",
        "revenueEstimateGrowth": "0.0527",
        "epsTrendCurrent": "7.9816",
        "epsTrend7daysAgo": "7.9628",
        "epsTrend30daysAgo": "7.9665",
        "epsTrend60daysAgo": "7.8069",
        "epsTrend90daysAgo": "7.8143",
        "epsRevisionsUpLast7days": "1.0000",
        "epsRevisionsUpLast30days": "4.0000",
        "epsRevisionsDownLast30days": "2.0000"
      }
    ]
  ]
}
```

### Output Format

**Top-level fields:**

| Field | Type | Description |
|-------|------|-------------|
| type | string | Constant label of the payload (example: Trends) |
| description | string | Human-readable description of the dataset |
| symbols | string | Comma-separated list of requested tickers |
| trends | array of arrays | For each symbol, an array of trend records. The i-th inner array corresponds to the i-th symbol in the symbols list. Each record is a trend item (see fields below) |

**Trend item fields:**

| Field | Type | Description |
|-------|------|-------------|
| code | string | Ticker code for this record (EODHD format) |
| date | string (YYYY-MM-DD) | Anchor date of the estimate window (quarter or year end) |
| period | string | Relative horizon: 0q (current quarter), +1q (next quarter), 0y (current FY), +1y (next FY) |
| growth | number (stringified) or null | Overall EPS growth vs prior comparable period |
| earningsEstimateAvg | number (stringified) | Consensus EPS |
| earningsEstimateLow | number (stringified) | Low EPS estimate |
| earningsEstimateHigh | number (stringified) | High EPS estimate |
| earningsEstimateYearAgoEps | number (stringified) or null | EPS for the comparable prior period |
| earningsEstimateNumberOfAnalysts | number (stringified) | Analyst count for EPS estimate |
| earningsEstimateGrowth | number (stringified) or null | EPS growth vs prior comparable period |
| revenueEstimateAvg | number (stringified) | Consensus revenue |
| revenueEstimateLow | number (stringified) | Low revenue estimate |
| revenueEstimateHigh | number (stringified) | High revenue estimate |
| revenueEstimateYearAgoEps | number (stringified) or null | Revenue for the comparable prior period (if available) |
| revenueEstimateNumberOfAnalysts | number (stringified) | Analyst count for revenue estimate |
| revenueEstimateGrowth | number (stringified) or null | Revenue growth vs prior comparable period |
| epsTrendCurrent | number (stringified) | Current EPS consensus for this period |
| epsTrend7daysAgo | number (stringified) | EPS consensus 7 days ago |
| epsTrend30daysAgo | number (stringified) | EPS consensus 30 days ago |
| epsTrend60daysAgo | number (stringified) | EPS consensus 60 days ago |
| epsTrend90daysAgo | number (stringified) | EPS consensus 90 days ago |
| epsRevisionsUpLast7days | number (stringified) | Upward EPS revisions in last 7 days |
| epsRevisionsUpLast30days | number (stringified) | Upward EPS revisions in last 30 days |
| epsRevisionsDownLast30days | number (stringified) or null | Downward EPS revisions in last 30 days |

### Example Requests

```bash
# Trends for multiple symbols
curl "https://eodhd.com/api/calendar/trends?symbols=AAPL.US,MSFT.US,AI.PA&api_token=demo&fmt=json"

# Trends for specific symbols
curl "https://eodhd.com/api/calendar/trends?symbols=F.US,AI.PA&api_token=demo&fmt=json"

# Using the helper client
python eodhd_client.py --endpoint calendar/trends --symbols F.US,AI.PA
```

### Notes

- JSON-only due to nested structure
- If a provided symbol has no data, it may be omitted from the response
- To paginate large symbol sets, split your symbols into batches (for example, 50–100 per call)
- Each symbol gets its own array in the `trends` array
- Period values: 0q (current quarter), +1q (next quarter), 0y (current fiscal year), +1y (next fiscal year)
- All numeric values are returned as stringified numbers
- **Field naming**: `revenueEstimateYearAgoEps` is named as-is in the upstream API response (the `Eps` suffix is a known misnomer)
- API call consumption: 1 call per request

### HTTP Status Codes

The API returns standard HTTP status codes to indicate success or failure:

| Status Code | Meaning | Description |
|-------------|---------|-------------|
| **200** | OK | Request succeeded. Data returned successfully. |
| **402** | Payment Required | API limit used up. Upgrade plan or wait for limit reset. |
| **403** | Unauthorized | Invalid API key. Check your `api_token` parameter. |
| **429** | Too Many Requests | Exceeded rate limit (requests per minute). Slow down requests. |

### Error Response Format

When an error occurs, the API returns a JSON response with error details:

```json
{
  "error": "Error message description",
  "code": 403
}
```

### Handling Errors

**Python Example**:
```python
import requests

def make_api_request(url, params):
    try:
        response = requests.get(url, params=params)
        response.raise_for_status()  # Raises HTTPError for bad status codes
        return response.json()
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 402:
            print("Error: API limit exceeded. Please upgrade your plan.")
        elif e.response.status_code == 403:
            print("Error: Invalid API key. Check your credentials.")
        elif e.response.status_code == 429:
            print("Error: Rate limit exceeded. Please slow down your requests.")
        else:
            print(f"HTTP Error: {e}")
        return None
    except requests.exceptions.RequestException as e:
        print(f"Request failed: {e}")
        return None
```

**Best Practices**:
- Always check status codes before processing response data
- Implement exponential backoff for 429 errors
- Cache responses to reduce API calls
- Monitor your API usage in the user dashboard

---

## Economic Events API

<a id="economic-events"></a>

### Endpoint Metadata

| Field | Value |
|---|---|
| Status | complete |
| Source | financial-apis (Economic Events Data API) |
| Docs | https://eodhd.com/financial-apis/economic-events-data-api |
| Provider | EODHD |
| Base URL | https://eodhd.com/api |
| Path | /economic-events |
| Method | GET |
| Auth | api_token (query) |
| Slug | `economic-events` |
| Source File | `/Users/arnaurodon/Projects/University/Final Thesis/eodhd-claude-skills/skills/eodhd-api/references/endpoints/economic-events.md` |

### Purpose

Fetches economic events and indicators by date range, country, and comparison type.
Includes actual values, estimates, and changes for events like GDP releases, employment data,
inflation reports, and central bank decisions. Useful for macro analysis and event-driven trading.

### Inputs

| Parameter | Required | Type | Description |
|-----------|----------|------|-------------|
| api_token | Yes | string | Your API key for authentication |
| from | No | string (YYYY-MM-DD) | Start date for data retrieval |
| to | No | string (YYYY-MM-DD) | End date for data retrieval |
| country | No | string | ISO 3166-1 alpha-2 country code (e.g., 'US', 'GB', 'DE') |
| comparison | No | string | Comparison type: 'mom' (month-over-month), 'qoq' (quarter-over-quarter), 'yoy' (year-over-year) |
| offset | No | integer | Data offset (0-1000). Default: 0 |
| limit | No | integer | Number of results (0-1000). Default: 50 |
| fmt | No | string | Output format: 'json' or 'csv'. Default: 'json' |

### Outputs

Array of economic event objects:

```json
[
  {
    "type": "Nonfarm Payrolls",
    "comparison": null,
    "period": "May",
    "country": "US",
    "date": "2025-06-03 16:30:00",
    "actual": 275,
    "previous": 256,
    "estimate": 250,
    "change": 19,
    "change_percentage": 7.42
  },
  {
    "type": "CPI",
    "comparison": "yoy",
    "period": "May",
    "country": "US",
    "date": "2025-06-12 12:30:00",
    "actual": 3.2,
    "previous": 3.4,
    "estimate": 3.3,
    "change": -0.2,
    "change_percentage": -5.88
  }
]
```

### Field Descriptions

| Field | Type | Description |
|-------|------|-------------|
| type | string | Event type (e.g., 'Nonfarm Payrolls', 'CPI', 'GDP') |
| comparison | string/null | Comparison type: 'mom', 'qoq', 'yoy', or null |
| period | string/null | Period for the data (e.g., 'May', 'Q1') |
| country | string | ISO 3166 country code |
| date | string (datetime) | Event date and time (YYYY-MM-DD HH:MM:SS) |
| actual | number/null | Actual reported value |
| previous | number/null | Previous period's value |
| estimate | number/null | Consensus estimate |
| change | number/null | Change from previous value |
| change_percentage | number/null | Percentage change from previous |

### Common Event Types

- Employment: Nonfarm Payrolls, Unemployment Rate, Initial Jobless Claims
- Inflation: CPI, PPI, PCE Price Index
- Growth: GDP, Industrial Production, Retail Sales
- Manufacturing: ISM Manufacturing PMI, Durable Goods Orders
- Housing: Existing Home Sales, Building Permits, Housing Starts
- Central Bank: Fed Interest Rate Decision, ECB Rate Decision

### Example Requests

```bash
# Economic events for the next week
curl "https://eodhd.com/api/economic-events?api_token=demo&fmt=json"

# US events for specific date range
curl "https://eodhd.com/api/economic-events?country=US&from=2025-01-01&to=2025-01-31&api_token=demo&fmt=json"

# Year-over-year comparisons only
curl "https://eodhd.com/api/economic-events?comparison=yoy&limit=20&api_token=demo&fmt=json"

# German events with pagination
curl "https://eodhd.com/api/economic-events?country=DE&limit=50&offset=0&api_token=demo&fmt=json"

# Using the helper client
python eodhd_client.py --endpoint economic-events --from-date 2025-01-01 --to-date 2025-01-31
```

### Notes

- `actual` is null for upcoming events not yet released
- Times are in the format 'YYYY-MM-DD HH:MM:SS' (typically UTC)
- Country codes use ISO 3166-1 alpha-2 (US, GB, DE, JP, CN, etc.)
- Use `comparison` filter to get only specific comparison types
- Maximum 1000 results per request; use offset for pagination
- API call consumption: 1 call per request
- **Timezone**: All event timestamps are in **UTC**.
- **From/to parameters and limit**: By default, the API returns only 50 events per response. To access older events, use the `&limit=` parameter and specify `from` and `to` dates precisely. For example, to retrieve events from the year 2020, use both `&from=2020-01-01&to=2020-12-31` along with an appropriate limit.
- **Offset beyond 1000**: If the maximum offset of 1000 is not enough, use the `from` and `to` parameters in conjunction with `offset` to paginate deeper into history by narrowing the date range.
- **Data depth**: Economic events data is available from **2020** onwards.

### HTTP Status Codes

The API returns standard HTTP status codes to indicate success or failure:

| Status Code | Meaning | Description |
|-------------|---------|-------------|
| **200** | OK | Request succeeded. Data returned successfully. |
| **402** | Payment Required | API limit used up. Upgrade plan or wait for limit reset. |
| **403** | Unauthorized | Invalid API key. Check your `api_token` parameter. |
| **429** | Too Many Requests | Exceeded rate limit (requests per minute). Slow down requests. |

### Error Response Format

When an error occurs, the API returns a JSON response with error details:

```json
{
  "error": "Error message description",
  "code": 403
}
```

### Handling Errors

**Python Example**:
```python
import requests

def make_api_request(url, params):
    try:
        response = requests.get(url, params=params)
        response.raise_for_status()  # Raises HTTPError for bad status codes
        return response.json()
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 402:
            print("Error: API limit exceeded. Please upgrade your plan.")
        elif e.response.status_code == 403:
            print("Error: Invalid API key. Check your credentials.")
        elif e.response.status_code == 429:
            print("Error: Rate limit exceeded. Please slow down your requests.")
        else:
            print(f"HTTP Error: {e}")
        return None
    except requests.exceptions.RequestException as e:
        print(f"Request failed: {e}")
        return None
```

**Best Practices**:
- Always check status codes before processing response data
- Implement exponential backoff for 429 errors
- Cache responses to reduce API calls
- Monitor your API usage in the user dashboard

---

## Exchange Details API (Trading Hours, Stock Market Holidays)

<a id="exchange-details"></a>

### Endpoint Metadata

| Field | Value |
|---|---|
| Status | complete |
| Source | financial-apis |
| Provider | EODHD |
| Base URL | `https://eodhd.com/api` |
| Path | `/exchange-details/{EXCHANGE_CODE}` |
| Method | GET |
| Auth | `api_token` query parameter |
| Slug | `exchange-details` |
| Source File | `/Users/arnaurodon/Projects/University/Final Thesis/eodhd-claude-skills/skills/eodhd-api/references/endpoints/exchange-details.md` |

### Purpose

Get detailed information about a specific exchange, including:

- **Timezone** — the timezone of the exchange
- **isOpen** — boolean indicating if the exchange is open right now or closed
- **Trading hours and working days** — open/close hours in exchange timezone (may include lunch hours)
- **Exchange holidays** — official and bank holidays (6 months back and 6 months forward by default)
- **Early close days** — days when the exchange closes early
- **ActiveTickers** — tickers with any activity for the past two months
- **UpdatedTickers** — tickers updated for the current day
- **PreviousDayUpdatedTickers** — tickers updated the previous day

### Inputs

### Required

| Parameter | Type | Description |
|-----------|------|-------------|
| `api_token` | string | Your API key |

### Path Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `EXCHANGE_CODE` | string | Exchange code (e.g., `US`, `LSE`, `XETRA`) |

### Optional

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `from` | string | 6 months before today | Start date for holidays (`YYYY-MM-DD`) |
| `to` | string | 6 months after today | End date for holidays (`YYYY-MM-DD`) |
| `fmt` | string | `csv` | Response format: `json` or `csv` |

### Outputs

```json
{
  "Name": "USA Stocks",
  "Code": "US",
  "OperatingMIC": "XNAS, XNYS, OTCM",
  "Country": "USA",
  "Currency": "USD",
  "Timezone": "America/New_York",
  "isOpen": true,
  "TradingHours": {
    "Open": "09:30:00",
    "Close": "16:00:00",
    "OpenUTC": "14:30:00",
    "CloseUTC": "21:00:00",
    "WorkingDays": "Mon,Tue,Wed,Thu,Fri"
  },
  "ExchangeHolidays": {
    "0": {
      "Holiday": "Labour Day",
      "Date": "2025-09-01",
      "Type": "official"
    },
    "1": {
      "Holiday": "Thanksgiving Day",
      "Date": "2025-11-27",
      "Type": "official"
    }
  },
  "ExchangeEarlyCloseDays": {},
  "ActiveTickers": 49762,
  "PreviousDayUpdatedTickers": 48278,
  "UpdatedTickers": 0
}
```

### Response Field Definitions

| Field | Type | Description |
|-------|------|-------------|
| `Name` | string | Full exchange name |
| `Code` | string | Exchange short code |
| `OperatingMIC` | string | Market Identifier Code(s) |
| `Country` | string | Country of the exchange |
| `Currency` | string | Primary trading currency |
| `Timezone` | string | Exchange timezone (IANA format) |
| `isOpen` | boolean | Whether the exchange is currently open |
| `TradingHours` | object | Open/close times in local and UTC |
| `TradingHours.Open` | string | Market open time (local timezone, `HH:MM:SS`) |
| `TradingHours.Close` | string | Market close time (local timezone, `HH:MM:SS`) |
| `TradingHours.OpenUTC` | string | Market open time (UTC, `HH:MM:SS`) |
| `TradingHours.CloseUTC` | string | Market close time (UTC, `HH:MM:SS`) |
| `TradingHours.WorkingDays` | string | Comma-separated trading days |
| `ExchangeHolidays` | object | Map of holidays with name, date, and type |
| `ExchangeHolidays.*.Holiday` | string | Holiday name |
| `ExchangeHolidays.*.Date` | string | Holiday date (`YYYY-MM-DD`) |
| `ExchangeHolidays.*.Type` | string | Holiday type: `official` or `bank` |
| `ExchangeEarlyCloseDays` | object | Map of early close days (same structure as holidays) |
| `ActiveTickers` | integer | Tickers with activity in past 2 months |
| `PreviousDayUpdatedTickers` | integer | Tickers updated previous day |
| `UpdatedTickers` | integer | Tickers updated today |

### Holiday Types

| Type | Description |
|------|-------------|
| `official` | Official market holiday — exchange fully closed |
| `bank` | Bank holiday — some countries (e.g., UK) have these; exchange may still operate |

### Example Requests

### Get exchange details with default holiday range

```bash
curl "https://eodhd.com/api/exchange-details/US?api_token=YOUR_API_TOKEN&fmt=json"
```

### Get exchange details with custom holiday date range

```bash
curl "https://eodhd.com/api/exchange-details/US?api_token=YOUR_API_TOKEN&fmt=json&from=2017-01-01&to=2021-01-01"
```

### Python client

```bash
python eodhd_client.py --endpoint exchanges-details --symbol US
```

### Python (requests)

```python
import requests

url = "https://eodhd.com/api/exchange-details/US"
params = {
    "api_token": "YOUR_API_TOKEN",
    "fmt": "json"
}
response = requests.get(url, params=params)
data = response.json()

# Check if exchange is open
print(f"Exchange open: {data['isOpen']}")
print(f"Trading hours: {data['TradingHours']['Open']} - {data['TradingHours']['Close']}")
print(f"Active tickers: {data['ActiveTickers']}")

# List upcoming holidays
for key, holiday in data['ExchangeHolidays'].items():
    print(f"  {holiday['Date']}: {holiday['Holiday']} ({holiday['Type']})")
```

### Notes

- **Default format is CSV**: Always pass `fmt=json` for programmatic access. Without it, the API returns CSV which is harder to parse.
- Exchange holidays default to 6 months back and 6 months forward from the current date
- Use `from` and `to` parameters to query historical or future holiday data
- Holiday types: `official` (exchange fully closed) and `bank` (varies by country)
- `TradingHours` may include lunch hours for exchanges that have trading breaks (e.g., some Asian markets)
- `isOpen` reflects the real-time status at the time of the API call
- All exchanges supported by EODHD are available through this endpoint

### HTTP Status Codes

The API returns standard HTTP status codes to indicate success or failure:

| Status Code | Meaning | Description |
|-------------|---------|-------------|
| **200** | OK | Request succeeded. Data returned successfully. |
| **402** | Payment Required | API limit used up. Upgrade plan or wait for limit reset. |
| **403** | Unauthorized | Invalid API key. Check your `api_token` parameter. |
| **429** | Too Many Requests | Exceeded rate limit (requests per minute). Slow down requests. |

### Error Response Format

When an error occurs, the API returns a JSON response with error details:

```json
{
  "error": "Error message description",
  "code": 403
}
```

### Handling Errors

**Python Example**:
```python
import requests

def make_api_request(url, params):
    try:
        response = requests.get(url, params=params)
        response.raise_for_status()  # Raises HTTPError for bad status codes
        return response.json()
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 402:
            print("Error: API limit exceeded. Please upgrade your plan.")
        elif e.response.status_code == 403:
            print("Error: Invalid API key. Check your credentials.")
        elif e.response.status_code == 429:
            print("Error: Rate limit exceeded. Please slow down your requests.")
        else:
            print(f"HTTP Error: {e}")
        return None
    except requests.exceptions.RequestException as e:
        print(f"Request failed: {e}")
        return None
```

**Best Practices**:
- Always check status codes before processing response data
- Implement exponential backoff for 429 errors
- Cache responses to reduce API calls
- Monitor your API usage in the user dashboard

---

## Exchange Symbol List API

<a id="exchange-tickers"></a>

### Endpoint Metadata

| Field | Value |
|---|---|
| Status | complete |
| Source | financial-apis (Exchanges API) |
| Docs | https://eodhd.com/financial-apis/exchanges-api-list-of-tickers-and-trading-hours |
| Provider | EODHD |
| Base URL | https://eodhd.com/api |
| Path | /exchange-symbol-list/{EXCHANGE} |
| Method | GET |
| Auth | api_token (query) |
| Slug | `exchange-tickers` |
| Source File | `/Users/arnaurodon/Projects/University/Final Thesis/eodhd-claude-skills/skills/eodhd-api/references/endpoints/exchange-tickers.md` |

### Purpose

Fetches the complete list of ticker symbols available on a specific exchange, including
symbol codes, names, countries, exchanges, currencies, and instrument types. Useful for
discovering tradable instruments and building symbol universes.

### Inputs

| Parameter | Required | Type | Description |
|-----------|----------|------|-------------|
| {EXCHANGE} | Yes | path | Exchange code (e.g., 'US', 'LSE', 'XETRA') |
| api_token | Yes | string | Your API key for authentication |
| fmt | No | string | Output format: 'json' or 'csv'. Defaults to 'json' |

### Outputs

```json
[
  {
    "Code": "AAPL",
    "Name": "Apple Inc",
    "Country": "USA",
    "Exchange": "NASDAQ",
    "Currency": "USD",
    "Type": "Common Stock",
    "Isin": "US0378331005"
  },
  {
    "Code": "MSFT",
    "Name": "Microsoft Corporation",
    "Country": "USA",
    "Exchange": "NASDAQ",
    "Currency": "USD",
    "Type": "Common Stock",
    "Isin": "US5949181045"
  },
  {
    "Code": "SPY",
    "Name": "SPDR S&P 500 ETF Trust",
    "Country": "USA",
    "Exchange": "NYSE ARCA",
    "Currency": "USD",
    "Type": "ETF",
    "Isin": "US78462F1030"
  }
]
```

### Field Descriptions

| Field | Type | Description |
|-------|------|-------------|
| Code | string | Ticker symbol |
| Name | string | Company or instrument name |
| Country | string | Country of incorporation/listing |
| Exchange | string | Specific exchange within the market |
| Currency | string | Trading currency |
| Type | string | Instrument type (see below) |
| Isin | string/null | International Securities Identification Number |

### Instrument Types

| Type | Description |
|------|-------------|
| Common Stock | Regular equity shares |
| ETF | Exchange Traded Fund |
| FUND | Mutual fund |
| Preferred Stock | Preferred equity shares |
| REIT | Real Estate Investment Trust |
| Bond | Fixed income security |
| Index | Market index |
| Currency | Foreign exchange pair |
| Cryptocurrency | Digital currency |

### Example Requests

```bash
# All US tickers
curl "https://eodhd.com/api/exchange-symbol-list/US?api_token=demo&fmt=json"

# London Stock Exchange tickers
curl "https://eodhd.com/api/exchange-symbol-list/LSE?api_token=demo&fmt=json"

# Frankfurt (XETRA) tickers
curl "https://eodhd.com/api/exchange-symbol-list/XETRA?api_token=demo&fmt=json"

# Using the helper client
python eodhd_client.py --endpoint exchange-symbol-list --symbol US
```

### Notes

- Full symbol format: `{Code}.{EXCHANGE}` (e.g., `AAPL.US`, `BMW.XETRA`)
- US exchange includes NYSE, NASDAQ, and AMEX (8000+ symbols)
- Large exchanges may return thousands of symbols
- `Type` field helps filter by instrument category
- `Isin` provides cross-reference to international databases
- Some symbols may be delisted but still in historical data
- API call consumption: 1 call per request
- Consider caching results as symbol lists don't change frequently

### HTTP Status Codes

The API returns standard HTTP status codes to indicate success or failure:

| Status Code | Meaning | Description |
|-------------|---------|-------------|
| **200** | OK | Request succeeded. Data returned successfully. |
| **402** | Payment Required | API limit used up. Upgrade plan or wait for limit reset. |
| **403** | Unauthorized | Invalid API key. Check your `api_token` parameter. |
| **429** | Too Many Requests | Exceeded rate limit (requests per minute). Slow down requests. |

### Error Response Format

When an error occurs, the API returns a JSON response with error details:

```json
{
  "error": "Error message description",
  "code": 403
}
```

### Handling Errors

**Python Example**:
```python
import requests

def make_api_request(url, params):
    try:
        response = requests.get(url, params=params)
        response.raise_for_status()  # Raises HTTPError for bad status codes
        return response.json()
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 402:
            print("Error: API limit exceeded. Please upgrade your plan.")
        elif e.response.status_code == 403:
            print("Error: Invalid API key. Check your credentials.")
        elif e.response.status_code == 429:
            print("Error: Rate limit exceeded. Please slow down your requests.")
        else:
            print(f"HTTP Error: {e}")
        return None
    except requests.exceptions.RequestException as e:
        print(f"Request failed: {e}")
        return None
```

**Best Practices**:
- Always check status codes before processing response data
- Implement exponential backoff for 429 errors
- Cache responses to reduce API calls
- Monitor your API usage in the user dashboard

---

## Exchanges List API

<a id="exchanges-list"></a>

### Endpoint Metadata

| Field | Value |
|---|---|
| Status | complete |
| Source | financial-apis (Exchanges API) |
| Docs | https://eodhd.com/financial-apis/exchanges-api-list-of-tickers-and-trading-hours |
| Provider | EODHD |
| Base URL | https://eodhd.com/api |
| Path | /exchanges-list |
| Method | GET |
| Auth | api_token (query) |
| Slug | `exchanges-list` |
| Source File | `/Users/arnaurodon/Projects/University/Final Thesis/eodhd-claude-skills/skills/eodhd-api/references/endpoints/exchanges-list.md` |

### Purpose

Fetches a list of all supported stock exchanges with their codes, names, countries,
currencies, and operating hours. Useful for discovering available markets and understanding
exchange metadata before querying market data.

### Inputs

| Parameter | Required | Type | Description |
|-----------|----------|------|-------------|
| api_token | Yes | string | Your API key for authentication |
| fmt | No | string | Output format: 'json' or 'csv'. Defaults to 'json' |

### Outputs

```json
[
  {
    "Name": "USA Stocks",
    "Code": "US",
    "OperatingMIC": "XNAS, XNYS, OTCM",
    "Country": "USA",
    "Currency": "USD",
    "CountryISO2": "US",
    "CountryISO3": "USA"
  },
  {
    "Name": "London Exchange",
    "Code": "LSE",
    "OperatingMIC": "XLON",
    "Country": "UK",
    "Currency": "GBP",
    "CountryISO2": "GB",
    "CountryISO3": "GBR"
  },
  {
    "Name": "Government Bonds",
    "Code": "GBOND",
    "OperatingMIC": null,
    "Country": "Unknown",
    "Currency": "Unknown",
    "CountryISO2": "",
    "CountryISO3": ""
  }
]
```

### Field Descriptions

| Field | Type | Description |
|-------|------|-------------|
| Name | string | Full name of the exchange |
| Code | string | EODHD exchange code (used in symbol suffix) |
| OperatingMIC | string or null | ISO 10383 Market Identifier Code(s). Can be comma-separated for combined exchanges (e.g., `"XNAS, XNYS, OTCM"`), or `null` for virtual exchanges (GBOND, MONEY, EUFUND) |
| Country | string | Country name (or `"Unknown"` for virtual exchanges) |
| Currency | string | Primary trading currency (or `"Unknown"` for virtual exchanges) |
| CountryISO2 | string | ISO 3166-1 alpha-2 country code (empty string for virtual exchanges) |
| CountryISO3 | string | ISO 3166-1 alpha-3 country code (empty string for virtual exchanges) |

### Common Exchange Codes

| Code | Exchange |
|------|----------|
| US | USA Stocks (NYSE, NASDAQ, OTC Markets combined) |
| LSE | London Exchange |
| XETRA | XETRA Stock Exchange (Germany) |
| PA | Euronext Paris |
| TO | Toronto Exchange |
| TW | Taiwan Stock Exchange |
| KO | Korea Stock Exchange |
| SHG | Shanghai Stock Exchange |
| SHE | Shenzhen Stock Exchange |
| AU | Australian Securities Exchange |
| SA | Sao Paulo Exchange (B3) |
| MC | Madrid Exchange |
| AS | Euronext Amsterdam |
| JSE | Johannesburg Exchange |
| FOREX | Forex |
| CC | Cryptocurrencies |
| GBOND | Government Bonds |

### Example Requests

```bash
# List all exchanges
curl "https://eodhd.com/api/exchanges-list?api_token=demo&fmt=json"

# Using the helper client
python eodhd_client.py --endpoint exchanges-list
```

### Notes

- Exchange codes are used as suffixes in symbol identifiers (e.g., `AAPL.US`, `BMW.XETRA`)
- The `US` code combines NYSE, NASDAQ, and AMEX into a single virtual exchange
- MIC codes follow ISO 10383 standard for market identification
- Exchange list is relatively static; cache results when appropriate
- Use exchange codes with `exchange-symbol-list` endpoint to get tickers
- API call consumption: 1 call per request

### HTTP Status Codes

The API returns standard HTTP status codes to indicate success or failure:

| Status Code | Meaning | Description |
|-------------|---------|-------------|
| **200** | OK | Request succeeded. Data returned successfully. |
| **402** | Payment Required | API limit used up. Upgrade plan or wait for limit reset. |
| **403** | Unauthorized | Invalid API key. Check your `api_token` parameter. |
| **429** | Too Many Requests | Exceeded rate limit (requests per minute). Slow down requests. |

### Error Response Format

For authentication errors (invalid/expired token), the API returns plain text `Unauthenticated` (not JSON). For other errors, the API may return JSON:

```
Unauthenticated
```

### Handling Errors

**Python Example**:
```python
import requests

def make_api_request(url, params):
    try:
        response = requests.get(url, params=params)
        response.raise_for_status()  # Raises HTTPError for bad status codes
        return response.json()
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 402:
            print("Error: API limit exceeded. Please upgrade your plan.")
        elif e.response.status_code == 403:
            print("Error: Invalid API key. Check your credentials.")
        elif e.response.status_code == 429:
            print("Error: Rate limit exceeded. Please slow down your requests.")
        else:
            print(f"HTTP Error: {e}")
        return None
    except requests.exceptions.RequestException as e:
        print(f"Request failed: {e}")
        return None
```

**Best Practices**:
- Always check status codes before processing response data
- Implement exponential backoff for 429 errors
- Cache responses to reduce API calls
- Monitor your API usage in the user dashboard

---

## Fundamentals Data API

<a id="fundamentals-data"></a>

### Endpoint Metadata

| Field | Value |
|---|---|
| Status | complete |
| Source | financial-apis (Fundamental Data API) |
| Docs | https://eodhd.com/financial-apis/stock-etfs-fundamental-data-feeds |
| Provider | EODHD |
| Base URL | https://eodhd.com/api |
| Path | /fundamentals/{SYMBOL} |
| Method | GET |
| Auth | api_token (query) |
| Slug | `fundamentals-data` |
| Source File | `/Users/arnaurodon/Projects/University/Final Thesis/eodhd-claude-skills/skills/eodhd-api/references/endpoints/fundamentals-data.md` |

### Purpose

Return comprehensive fundamental data for a company including financial statements,
valuation metrics, earnings history, dividends, and company profile information.

### Inputs

| Parameter | Required | Type | Description |
|-----------|----------|------|-------------|
| api_token | Yes | string | EODHD API key |
| {SYMBOL} | Yes | string | Symbol with exchange suffix (e.g., AAPL.US) |
| filter | No | string | Comma-separated list of sections to return (e.g., General,Highlights,Valuation) |
| fmt | No | string | Output format: 'json' or 'csv'. Defaults to 'json' |

### Outputs

Large nested JSON object containing multiple sections:

```json
{
  "General": {
    "Code": "AAPL",
    "Name": "Apple Inc",
    "Exchange": "NASDAQ",
    "CurrencyCode": "USD",
    "Sector": "Technology",
    "Industry": "Consumer Electronics",
    "Description": "...",
    "FullTimeEmployees": 164000,
    "IPODate": "1980-12-12",
    "WebURL": "https://www.apple.com"
  },
  "Highlights": {
    "MarketCapitalization": 2500000000000,
    "EBITDA": 130000000000,
    "PERatio": 28.5,
    "PEGRatio": 2.1,
    "WallStreetTargetPrice": 195.0,
    "BookValue": 4.25,
    "DividendShare": 0.96,
    "DividendYield": 0.005,
    "EarningsShare": 6.15,
    "EPSEstimateCurrentYear": 6.50,
    "EPSEstimateNextYear": 7.20,
    "MostRecentQuarter": "2024-09-30",
    "ProfitMargin": 0.255,
    "OperatingMarginTTM": 0.302,
    "ReturnOnAssetsTTM": 0.215,
    "ReturnOnEquityTTM": 1.475,
    "RevenueTTM": 385000000000,
    "RevenuePerShareTTM": 24.50,
    "QuarterlyRevenueGrowthYOY": 0.08,
    "GrossProfitTTM": 170000000000,
    "DilutedEpsTTM": 6.15
  },
  "Valuation": {
    "TrailingPE": 28.5,
    "ForwardPE": 26.2,
    "PriceSalesTTM": 6.5,
    "PriceBookMRQ": 41.5,
    "EnterpriseValue": 2600000000000,
    "EnterpriseValueRevenue": 6.75,
    "EnterpriseValueEbitda": 20.0
  },
  "SharesStats": {
    "SharesOutstanding": 15700000000,
    "SharesFloat": 15650000000,
    "PercentInsiders": 0.07,
    "PercentInstitutions": 60.5,
    "SharesShort": 120000000,
    "ShortRatio": 1.5,
    "ShortPercentOfFloat": 0.008
  },
  "Financials": {
    "Balance_Sheet": { "quarterly": [...], "yearly": [...] },
    "Income_Statement": { "quarterly": [...], "yearly": [...] },
    "Cash_Flow": { "quarterly": [...], "yearly": [...] }
  },
  "Earnings": {
    "History": [...],
    "Trend": [...],
    "Annual": [...]
  },
  "outstandingShares": { "annual": [...], "quarterly": [...] }
}
```

### Example Requests

```bash
# Full fundamentals for AAPL
curl "https://eodhd.com/api/fundamentals/AAPL.US?api_token=demo&fmt=json"

# Only highlights and valuation
curl "https://eodhd.com/api/fundamentals/AAPL.US?api_token=demo&filter=Highlights,Valuation"

# Using the helper client
python eodhd_client.py --endpoint fundamentals --symbol AAPL.US
```

### Notes

- Returns extensive data; use filter parameter to reduce payload size
- Financial statements include quarterly and yearly data going back several years
- Currency is in the company's reporting currency (check CurrencyCode)
- Some fields may be null for companies that don't report certain metrics
- ETFs have different structure focusing on holdings and asset allocation
- Mutual funds have NAV history and expense ratio information
- API call consumption: 10 calls per request regardless of sections filtered

### HTTP Status Codes

The API returns standard HTTP status codes to indicate success or failure:

| Status Code | Meaning | Description |
|-------------|---------|-------------|
| **200** | OK | Request succeeded. Data returned successfully. |
| **402** | Payment Required | API limit used up. Upgrade plan or wait for limit reset. |
| **403** | Unauthorized | Invalid API key. Check your `api_token` parameter. |
| **429** | Too Many Requests | Exceeded rate limit (requests per minute). Slow down requests. |

### Error Response Format

When an error occurs, the API returns a JSON response with error details:

```json
{
  "error": "Error message description",
  "code": 403
}
```

### Handling Errors

**Python Example**:
```python
import requests

def make_api_request(url, params):
    try:
        response = requests.get(url, params=params)
        response.raise_for_status()  # Raises HTTPError for bad status codes
        return response.json()
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 402:
            print("Error: API limit exceeded. Please upgrade your plan.")
        elif e.response.status_code == 403:
            print("Error: Invalid API key. Check your credentials.")
        elif e.response.status_code == 429:
            print("Error: Rate limit exceeded. Please slow down your requests.")
        else:
            print(f"HTTP Error: {e}")
        return None
    except requests.exceptions.RequestException as e:
        print(f"Request failed: {e}")
        return None
```

**Best Practices**:
- Always check status codes before processing response data
- Implement exponential backoff for 429 errors
- Cache responses to reduce API calls
- Monitor your API usage in the user dashboard

---

## Historical Market Capitalization API

<a id="historical-market-cap"></a>

### Endpoint Metadata

| Field | Value |
|---|---|
| Status | complete |
| Source | financial-apis |
| Docs | https://eodhd.com/financial-apis/historical-market-capitalization-api |
| Provider | EODHD |
| Base URL | `https://eodhd.com/api` |
| Path | `/historical-market-cap/{TICKER_CODE}` |
| Method | GET |
| Auth | `api_token` query parameter |
| Slug | `historical-market-cap` |
| Source File | `/Users/arnaurodon/Projects/University/Final Thesis/eodhd-claude-skills/skills/eodhd-api/references/endpoints/historical-market-cap.md` |

### Purpose

Provides weekly market capitalization data for US stocks (NYSE and NASDAQ) from 2019 onward. Useful for historical trend analysis, portfolio management, backtesting, and cross-company valuation comparisons.

**Key characteristics**:
- **Weekly frequency** — one data point per week (typically Thursday/Friday)
- **US stocks only** — NYSE and NASDAQ listed stocks
- **Historical depth** — data available from 2019 onward
- **Values in raw USD** — not millions or billions (divide by `1e9` for billions)

### Inputs

### Required

| Parameter | Type | Description |
|-----------|------|-------------|
| `{TICKER_CODE}` | path string | Ticker with exchange suffix (e.g., `AAPL.US`). For US stocks, suffix can be omitted (`AAPL`) |
| `api_token` | string | Your API key |

### Optional

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `from` | string | `2019-01-01` | Start date (`YYYY-MM-DD`). Earliest available data if omitted |
| `to` | string | Latest | End date (`YYYY-MM-DD`). Latest available data if omitted |
| `fmt` | string | `json` | Output format: `json` or `csv` |

### Outputs

Returns a JSON object with numeric keys, where each entry contains a date and market cap value:

```json
{
  "0": {
    "date": "2020-01-09",
    "value": 1357426280000
  },
  "1": {
    "date": "2020-01-16",
    "value": 1382020671500
  },
  "2": {
    "date": "2020-01-23",
    "value": 1396784480400
  }
}
```

### Response Field Definitions

| Field | Type | Description |
|-------|------|-------------|
| `date` | string | Weekly date (`YYYY-MM-DD`) |
| `value` | number | Market capitalization in raw USD. Example: `1357426280000` = $1.357 trillion |

### CSV Response

When using `fmt=csv`:

```csv
date,value
2020-01-09,1357426280000
2020-01-16,1382020671500
2020-01-23,1396784480400
```

### Example Requests

### Get all available data for Apple

```bash
curl "https://eodhd.com/api/historical-market-cap/AAPL.US?api_token=demo&fmt=json"
```

### Specific date range

```bash
curl "https://eodhd.com/api/historical-market-cap/AAPL.US?api_token=demo&from=2020-01-05&to=2020-03-10&fmt=json"
```

### US ticker shorthand (omit .US)

```bash
curl "https://eodhd.com/api/historical-market-cap/AAPL?api_token=demo&from=2023-01-01&to=2023-12-31"
```

### Python (requests)

```python
import requests

url = "https://eodhd.com/api/historical-market-cap/AAPL.US"
params = {
    "api_token": "YOUR_API_TOKEN",
    "from": "2023-01-01",
    "to": "2023-12-31",
    "fmt": "json"
}
response = requests.get(url, params=params)
data = response.json()

# Iterate over weekly data points
for key, entry in data.items():
    value_billions = entry["value"] / 1e9
    print(f"{entry['date']}: ${value_billions:.2f}B")
```

### Notes

- **Response format**: Returns an object keyed by index (e.g., `{"0": {...}, "1": {...}}`), not an array. Iterate over values or convert to a list.
- **Weekly data** — not daily. Typically one point per week on Thursday/Friday
- **US only** — NYSE and NASDAQ. International stocks not currently supported
- **Values in raw USD** — divide by `1e9` for billions, `1e12` for trillions
- **10 API calls per request** — plan accordingly for multi-ticker analysis (10 tickers = 100 calls)
- **From 2019** — no data available before 2019
- **Ticker shorthand** — for US stocks, `.US` suffix can be omitted
- **Demo access** — `api_token=demo` works for `AAPL.US` only
- **Fundamentals API alternative** — for current/quarterly market cap, use the Fundamentals API (`/fundamentals/{SYMBOL}`), which provides more precise point-in-time values synchronized with earnings. This endpoint is better for weekly trend analysis over longer periods

### HTTP Status Codes

The API returns standard HTTP status codes to indicate success or failure:

| Status Code | Meaning | Description |
|-------------|---------|-------------|
| **200** | OK | Request succeeded. Data returned successfully. |
| **402** | Payment Required | API limit used up. Upgrade plan or wait for limit reset. |
| **403** | Unauthorized | Invalid API key. Check your `api_token` parameter. |
| **429** | Too Many Requests | Exceeded rate limit (requests per minute). Slow down requests. |

### Error Response Format

When an error occurs, the API returns a JSON response with error details:

```json
{
  "error": "Error message description",
  "code": 403
}
```

### Handling Errors

**Python Example**:
```python
import requests

def make_api_request(url, params):
    try:
        response = requests.get(url, params=params)
        response.raise_for_status()  # Raises HTTPError for bad status codes
        return response.json()
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 402:
            print("Error: API limit exceeded. Please upgrade your plan.")
        elif e.response.status_code == 403:
            print("Error: Invalid API key. Check your credentials.")
        elif e.response.status_code == 429:
            print("Error: Rate limit exceeded. Please slow down your requests.")
        else:
            print(f"HTTP Error: {e}")
        return None
    except requests.exceptions.RequestException as e:
        print(f"Request failed: {e}")
        return None
```

**Best Practices**:
- Always check status codes before processing response data
- Implement exponential backoff for 429 errors
- Cache responses to reduce API calls
- Monitor your API usage in the user dashboard

---

## Historical Stock Prices API (End-of-Day)

<a id="historical-stock-prices"></a>

### Endpoint Metadata

| Field | Value |
|---|---|
| Status | complete |
| Source | financial-apis (End-Of-Day Historical Stock Market Data API) |
| Docs | https://eodhd.com/financial-apis/api-for-historical-data-and-volumes |
| Provider | EODHD |
| Base URL | https://eodhd.com/api |
| Path | /eod/{SYMBOL} |
| Method | GET |
| Auth | api_token (query) |
| Slug | `historical-stock-prices` |
| Source File | `/Users/arnaurodon/Projects/University/Final Thesis/eodhd-claude-skills/skills/eodhd-api/references/endpoints/historical-stock-prices.md` |

### Purpose

Fetches end-of-day historical OHLCV (Open, High, Low, Close, Volume) data for a symbol,
with optional date range, period aggregation, and output format controls. The primary
endpoint for historical price analysis, backtesting, and charting.

### Inputs

| Parameter | Required | Type | Description |
|-----------|----------|------|-------------|
| {SYMBOL} | Yes | path | Ticker with exchange suffix (e.g., 'AAPL.US', 'BMW.XETRA') |
| api_token | Yes | string | Your API key for authentication |
| from | No | string (YYYY-MM-DD) | Start date. Defaults to earliest available |
| to | No | string (YYYY-MM-DD) | End date. Defaults to latest available |
| period | No | string | Aggregation period: 'd' (daily), 'w' (weekly), 'm' (monthly). Default: 'd' |
| order | No | string | Sort order: 'a' (ascending), 'd' (descending). Default: 'a' |
| fmt | No | string | Output format: 'json' or 'csv'. Default: 'csv' |
| filter | No | string | Return single value: 'last_close' or 'last_volume' (requires fmt=json) |

### Outputs

```json
[
  {
    "date": "2025-01-02",
    "open": 182.15,
    "high": 185.60,
    "low": 181.50,
    "close": 184.25,
    "adjusted_close": 184.25,
    "volume": 45678900
  },
  {
    "date": "2025-01-03",
    "open": 184.50,
    "high": 186.90,
    "low": 183.20,
    "close": 186.75,
    "adjusted_close": 186.75,
    "volume": 52341200
  }
]
```

### Field Descriptions

| Field | Type | Description |
|-------|------|-------------|
| date | string (date) | Trading date (YYYY-MM-DD) |
| open | number | Opening price |
| high | number | Highest price during the period |
| low | number | Lowest price during the period |
| close | number | Closing price (unadjusted) |
| adjusted_close | number | Close adjusted for splits and dividends |
| volume | integer | Trading volume (adjusted for splits) |

### Adjustment Notes

- `open`, `high`, `low`, `close`: Raw/unadjusted prices
- `adjusted_close`: Adjusted for stock splits and dividends
- `volume`: Adjusted for stock splits only
- For accurate historical comparisons, use `adjusted_close`

### Example Requests

```bash
# Full history for Apple
curl "https://eodhd.com/api/eod/AAPL.US?api_token=demo&fmt=json"

# Specific date range
curl "https://eodhd.com/api/eod/AAPL.US?from=2020-01-05&to=2020-02-10&api_token=demo&fmt=json"

# Weekly aggregation
curl "https://eodhd.com/api/eod/MSFT.US?from=2024-01-01&to=2024-12-31&period=w&api_token=demo&fmt=json"

# Monthly aggregation
curl "https://eodhd.com/api/eod/GOOGL.US?from=2020-01-01&period=m&api_token=demo&fmt=json"

# Just the last close price
curl "https://eodhd.com/api/eod/NVDA.US?filter=last_close&api_token=demo&fmt=json"

# Descending order (most recent first)
curl "https://eodhd.com/api/eod/TSLA.US?order=d&api_token=demo&fmt=json"

# Using the helper client
python eodhd_client.py --endpoint eod --symbol AAPL.US --from-date 2025-01-01 --to-date 2025-01-31
```

### Notes

- **Default format is CSV**: Always pass `fmt=json` for programmatic access. Without it, the API returns CSV which is harder to parse.
- API call consumption: 1 call per request (any length of history)
- Symbol format: `{TICKER}.{EXCHANGE}` (e.g., `AAPL.US`, `BMW.XETRA`, `BTC-USD.CC`)
- Free plan: Limited to 1 year of historical data
- Data typically available 15 minutes after market close for US major exchanges (NYSE, NASDAQ), and 2-3 hours after close for all other exchanges
- Weekends and holidays have no data (trading days only)
- **Trading days with zero volume**: Some trading days may appear with 0 volume ("flat candles" with repeated prices). This varies by ticker because different data sources handle zero-volume days differently — some include them, some omit them. EODHD's goal is to clean up and omit zero-volume days over time, but this is not yet complete for all tickers. **Recommended workaround**: Simply filter out any days with `volume == 0` in your data processing. This does not affect data accuracy.
- **US volumes at 4:30 PM EST**: Volume figures for US stocks may initially appear incorrect shortly after market close. EODHD first receives data from the Nasdaq Basic Feed (with Nasdaq-only volumes), then later re-updates from the CTA/UTP aggregated data feed (which must wait for post-market data). The final, accurate volume figures are available after this second update.
- For intraday data, use the `/intraday/{SYMBOL}` endpoint
- For real-time quotes, use the `/real-time/{SYMBOL}` endpoint

### HTTP Status Codes

The API returns standard HTTP status codes to indicate success or failure:

| Status Code | Meaning | Description |
|-------------|---------|-------------|
| **200** | OK | Request succeeded. Data returned successfully. |
| **402** | Payment Required | API limit used up. Upgrade plan or wait for limit reset. |
| **403** | Unauthorized | Invalid API key. Check your `api_token` parameter. |
| **429** | Too Many Requests | Exceeded rate limit (requests per minute). Slow down requests. |

### Error Response Format

When an error occurs, the API returns a JSON response with error details:

```json
{
  "error": "Error message description",
  "code": 403
}
```

### Handling Errors

**Python Example**:
```python
import requests

def make_api_request(url, params):
    try:
        response = requests.get(url, params=params)
        response.raise_for_status()  # Raises HTTPError for bad status codes
        return response.json()
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 402:
            print("Error: API limit exceeded. Please upgrade your plan.")
        elif e.response.status_code == 403:
            print("Error: Invalid API key. Check your credentials.")
        elif e.response.status_code == 429:
            print("Error: Rate limit exceeded. Please slow down your requests.")
        else:
            print(f"HTTP Error: {e}")
        return None
    except requests.exceptions.RequestException as e:
        print(f"Request failed: {e}")
        return None
```

**Best Practices**:
- Always check status codes before processing response data
- Implement exponential backoff for 429 errors
- Cache responses to reduce API calls
- Monitor your API usage in the user dashboard

---

## Illio Market Insights — Best and Worst Days API

<a id="illio-market-insights-best-worst"></a>

### Endpoint Metadata

| Field | Value |
|---|---|
| Status | complete |
| Source | marketplace (illio) |
| Provider | illio via EODHD Marketplace |
| Base URL | `https://eodhd.com/api/mp/illio/chapters` |
| Path | `/best-and-worst/{id}` |
| Method | GET |
| Auth | `api_token` query parameter |
| Slug | `illio-market-insights-best-worst` |
| Source File | `/Users/arnaurodon/Projects/University/Final Thesis/eodhd-claude-skills/skills/eodhd-api/references/endpoints/illio-market-insights-best-worst.md` |

### Purpose

Returns data about instruments with the largest one-day gains and losses over the last year. Identifies which index constituents had the biggest single-day price swings, useful for understanding potential future moves and managing risk.

**Use cases**:
- Identify stocks with the largest single-day price moves
- Assess tail risk for individual constituents
- Screen for event-driven volatility and momentum
- Understand historical price shock magnitude for position sizing

### Inputs

### Path (required)

| Parameter | Type | Constraints | Description |
|-----------|------|-------------|-------------|
| `id` | string | enum: `SnP500`, `DJI`, `NDX` | Index watchlist identifier |

- `SnP500` — S&P 500 Index
- `DJI` — Dow Jones Industrial Average
- `NDX` — Nasdaq-100 Index

### Query (required)

| Parameter | Type | Description |
|-----------|------|-------------|
| `api_token` | string | Your API key |

### Outputs

```json
{
  "insightId": "BEST_AND_WORST_DAYS",
  "categoryId": "PERFORMANCE",
  "title": "Largest 1 Day Moves",
  "watchlistName": "US 500 Stocks",
  "insight": {
    "id": "BEST_AND_WORST_DAYS",
    "title": "Which of these instruments had the largest one day moves over the last year?",
    "whyImportant": "When considering allocations or strategies, you should be mindful of these large single day swings.",
    "description": "Over the last year, FISV had the largest one day gain and GL had the largest one day loss.",
    "stats": [
      { "text": "Over the last year, FISV, SMCI and DELL had the largest one-day gains with 75.7%, 35.9% and 31.6%." }
    ]
  },
  "chart": {
    "title": "Largest 1 Day Moves Over Past Year",
    "data": {
      "best": [
        { "label": "Fiserv Inc.", "value": 75.7 }
      ],
      "worst": [
        { "label": "Globe Life Inc", "value": -53.1 }
      ]
    }
  }
}
```

### Response Field Definitions

| Field | Type | Description |
|-------|------|-------------|
| `insightId` | string | Always `"BEST_AND_WORST_DAYS"` |
| `categoryId` | string | Always `"PERFORMANCE"` |
| `title` | string | Human-readable insight title |
| `watchlistName` | string | Name of the index |
| `insight.id` | string | Insight identifier |
| `insight.title` | string | Question the insight answers |
| `insight.whyImportant` | string | Explanation of why this metric matters |
| `insight.description` | string | Summary identifying the best and worst performers |
| `insight.stats[]` | array | Key statistics — top 3 gains and top 3 losses with percentages |
| `chart.title` | string | Chart title |
| `chart.data.best[]` | array | Instruments with the largest one-day **gains** |
| `chart.data.best[].label` | string | Instrument name |
| `chart.data.best[].value` | float | Largest single-day gain (%) — positive |
| `chart.data.worst[]` | array | Instruments with the largest one-day **losses** |
| `chart.data.worst[].label` | string | Instrument name |
| `chart.data.worst[].value` | float | Largest single-day loss (%) — negative |

> **Note**: Unlike other illio endpoints, this response uses `chart.data.best[]` and `chart.data.worst[]` instead of `chart.data.items[]`.

### Example Requests

### Get S&P 500 best and worst days

```bash
curl "https://eodhd.com/api/mp/illio/chapters/best-and-worst/SnP500?api_token=YOUR_API_TOKEN"
```

### Get Nasdaq-100 best and worst days

```bash
curl "https://eodhd.com/api/mp/illio/chapters/best-and-worst/NDX?api_token=YOUR_API_TOKEN"
```

### Demo access

```bash
curl "https://eodhd.com/api/mp/illio/chapters/best-and-worst/SnP500?api_token=demo"
```

### Notes

- **Marketplace product**: Requires a separate illio marketplace subscription, not included in main EODHD plans.
- **Top movers**: The `best` and `worst` arrays are sorted by magnitude — largest moves first.
- **One-year lookback**: Data covers the last year of trading.
- **Stats include top 3**: The `stats` array provides the top 3 gainers and top 3 losers with their percentages.
- **Supported indices**: S&P 500 (`SnP500`), Dow Jones (`DJI`), Nasdaq-100 (`NDX`).
- **Disclaimer**: Data does not constitute financial advice or investment recommendations.

### HTTP Status Codes

| Status Code | Meaning | Description |
|-------------|---------|-------------|
| **200** | OK | Request succeeded. Data returned successfully. |
| **401** | Unauthorized | Invalid or missing API key. |
| **403** | Forbidden | No access to this marketplace product. |
| **429** | Too Many Requests | Rate limit exceeded (1,000 req/min or 100,000 calls/24h). |

---

## Illio Market Insights — Beta Bands API

<a id="illio-market-insights-beta-bands"></a>

### Endpoint Metadata

| Field | Value |
|---|---|
| Status | complete |
| Source | marketplace (illio) |
| Provider | illio via EODHD Marketplace |
| Base URL | `https://eodhd.com/api/mp/illio/chapters` |
| Path | `/beta-bands/{id}` |
| Method | GET |
| Auth | `api_token` query parameter |
| Slug | `illio-market-insights-beta-bands` |
| Source File | `/Users/arnaurodon/Projects/University/Final Thesis/eodhd-claude-skills/skills/eodhd-api/references/endpoints/illio-market-insights-beta-bands.md` |

### Purpose

Returns data about how instruments react to overall market movements based on their Beta values. Beta measures an instrument's sensitivity to market moves — a beta of 1.0 means the instrument moves in line with the market, >1.0 means it amplifies market moves, <1.0 means it dampens them.

**Use cases**:
- Identify high-beta stocks that amplify market moves (useful in bull markets)
- Find low-beta or negative-beta stocks for defensive positioning (useful in bear markets)
- Construct beta-neutral or beta-tilted portfolios
- Understand portfolio sensitivity to broad market direction

### Inputs

### Path (required)

| Parameter | Type | Constraints | Description |
|-----------|------|-------------|-------------|
| `id` | string | enum: `SnP500`, `DJI`, `NDX` | Index watchlist identifier |

- `SnP500` — S&P 500 Index
- `DJI` — Dow Jones Industrial Average
- `NDX` — Nasdaq-100 Index

### Query (required)

| Parameter | Type | Description |
|-----------|------|-------------|
| `api_token` | string | Your API key |

### Outputs

```json
{
  "insightId": "BETA_BANDS",
  "categoryId": "RISK",
  "title": "Market Impact Bands",
  "watchlistName": "US 500 Stocks",
  "insight": {
    "id": "BETA_BANDS",
    "title": "How do these instruments react when the overall markets moves?",
    "whyImportant": "Beta tells you how much the instrument reacts to a move in the overall market.",
    "description": "When the market moves by 10.0%, 72.0% of these instruments are likely to move by less.",
    "stats": [
      { "text": "The most concentrated Beta bracket is 0.00 to 0.75." }
    ]
  },
  "chart": {
    "title": "Beta Bands",
    "data": {
      "items": [
        { "label": "Ameriprise Financial Inc", "value": 0.89 }
      ]
    }
  }
}
```

### Response Field Definitions

| Field | Type | Description |
|-------|------|-------------|
| `insightId` | string | Always `"BETA_BANDS"` |
| `categoryId` | string | Always `"RISK"` |
| `title` | string | Human-readable insight title |
| `watchlistName` | string | Name of the index |
| `insight.id` | string | Insight identifier |
| `insight.title` | string | Question the insight answers |
| `insight.whyImportant` | string | Explanation of what beta measures |
| `insight.description` | string | Summary — what percentage of instruments move less than the market |
| `insight.stats[]` | array | Key statistics — most concentrated beta bracket, highest/lowest beta instruments |
| `chart.title` | string | Chart title |
| `chart.data.items[]` | array | All instruments with their beta values |
| `chart.data.items[].label` | string | Instrument name |
| `chart.data.items[].value` | float | Beta value relative to the index |

### Beta Value Interpretation

| Beta Range | Meaning |
|------------|---------|
| > 1.0 | Amplifies market moves (e.g., 1.5 = moves 15% when market moves 10%) |
| = 1.0 | Moves in line with the market |
| 0.0 – 1.0 | Dampens market moves (e.g., 0.5 = moves 5% when market moves 10%) |
| < 0.0 | Moves inversely to the market |

### Example Requests

### Get S&P 500 beta bands

```bash
curl "https://eodhd.com/api/mp/illio/chapters/beta-bands/SnP500?api_token=YOUR_API_TOKEN"
```

### Get Nasdaq-100 beta bands

```bash
curl "https://eodhd.com/api/mp/illio/chapters/beta-bands/NDX?api_token=YOUR_API_TOKEN"
```

### Demo access

```bash
curl "https://eodhd.com/api/mp/illio/chapters/beta-bands/SnP500?api_token=demo"
```

### Notes

- **Marketplace product**: Requires a separate illio marketplace subscription, not included in main EODHD plans.
- **Flat list**: Unlike some other illio endpoints, the `items[]` array is a flat list of instruments with beta values (not bucketed).
- **Negative beta**: Some instruments may have negative beta values, meaning they tend to move inversely to the market.
- **Expected range**: Most instruments have beta between 0.75 and 1.25. Values outside this range indicate unusually high or low market sensitivity.
- **Bull vs bear**: In bull markets, prefer high-beta instruments for amplified upside. In bear markets, prefer low-beta for reduced downside.
- **All constituents included**: Every member of the selected index appears in the response.
- **Supported indices**: S&P 500 (`SnP500`), Dow Jones (`DJI`), Nasdaq-100 (`NDX`).
- **Disclaimer**: Data does not constitute financial advice or investment recommendations.

### HTTP Status Codes

| Status Code | Meaning | Description |
|-------------|---------|-------------|
| **200** | OK | Request succeeded. Data returned successfully. |
| **401** | Unauthorized | Invalid or missing API key. |
| **403** | Forbidden | No access to this marketplace product. |
| **429** | Too Many Requests | Rate limit exceeded (1,000 req/min or 100,000 calls/24h). |

---

## Illio Market Insights — Largest Volatility Change API

<a id="illio-market-insights-largest-volatility"></a>

### Endpoint Metadata

| Field | Value |
|---|---|
| Status | complete |
| Source | marketplace (illio) |
| Provider | illio via EODHD Marketplace |
| Base URL | `https://eodhd.com/api/mp/illio/chapters` |
| Path | `/volume/{id}` |
| Method | GET |
| Auth | `api_token` query parameter |
| Slug | `illio-market-insights-largest-volatility` |
| Source File | `/Users/arnaurodon/Projects/University/Final Thesis/eodhd-claude-skills/skills/eodhd-api/references/endpoints/illio-market-insights-largest-volatility.md` |

### Purpose

Returns data about instruments with the largest changes in volatility over the past year. Shows which constituents experienced significant increases or decreases in 100-day volatility, helping users focus on names where risk characteristics are shifting.

**Use cases**:
- Identify stocks with rapidly increasing or decreasing volatility
- Detect regime changes in individual names (e.g., post-earnings, sector rotation)
- Screen for names entering or exiting high-volatility regimes
- Adjust position sizing based on changing volatility profiles

### Inputs

### Path (required)

| Parameter | Type | Constraints | Description |
|-----------|------|-------------|-------------|
| `id` | string | enum: `SnP500`, `DJI`, `NDX` | Index watchlist identifier |

- `SnP500` — S&P 500 Index
- `DJI` — Dow Jones Industrial Average
- `NDX` — Nasdaq-100 Index

### Query (required)

| Parameter | Type | Description |
|-----------|------|-------------|
| `api_token` | string | Your API key |

### Outputs

```json
{
  "insightId": "LARGEST_VOL_MOVE",
  "categoryId": "RISK",
  "title": "Largest Volatility Change",
  "watchlistName": "US 500 Stocks",
  "insight": {
    "id": "LARGEST_VOL_MOVE",
    "title": "Which instruments have had the biggest changes in volatility?",
    "whyImportant": "This helps you focus on those instruments which, over the past year, have experienced a significant change in the amount they move per day.",
    "description": "Over the past year, 51.4% of these instruments had a volatility increase and 48.6% of these instruments had a volatility decrease.",
    "stats": [
      { "text": "Over the past year, the 100d volatility of Fiserv Inc. increased from 0% to 122.2%. This absolute increase of 122.2% is the largest of all the instruments." }
    ]
  },
  "chart": {
    "title": "Largest Increase and Decrease in Volatility Over The Past Year",
    "data": {
      "items": [
        {
          "code": "Volatility Increase",
          "label": "Volatility Increase",
          "value": 60.4,
          "instruments": [
            { "label": "Seagate Technology PLC", "value": 48.3 }
          ]
        },
        {
          "code": "Volatility Decrease",
          "label": "Volatility Decrease",
          "value": 39.6,
          "instruments": [
            { "label": "Tesla Inc", "value": -26.8 }
          ]
        }
      ]
    }
  }
}
```

### Response Field Definitions

| Field | Type | Description |
|-------|------|-------------|
| `insightId` | string | Always `"LARGEST_VOL_MOVE"` |
| `categoryId` | string | Always `"RISK"` |
| `title` | string | Human-readable insight title |
| `watchlistName` | string | Name of the index |
| `insight.id` | string | Insight identifier |
| `insight.title` | string | Question the insight answers |
| `insight.whyImportant` | string | Explanation of why volatility changes matter |
| `insight.description` | string | Summary — percentage of instruments with increasing/decreasing volatility |
| `insight.stats[]` | array | Key statistics — largest absolute increase and decrease with from/to values |
| `chart.title` | string | Chart title |
| `chart.data.items[]` | array | Two buckets: Volatility Increase and Volatility Decrease |
| `chart.data.items[].code` | string | Bucket identifier (`"Volatility Increase"` or `"Volatility Decrease"`) |
| `chart.data.items[].label` | string | Display label for the bucket |
| `chart.data.items[].value` | float | Percentage of instruments in this bucket |
| `chart.data.items[].instruments[]` | array | Instruments in this bucket, sorted by magnitude |
| `chart.data.items[].instruments[].label` | string | Instrument name |
| `chart.data.items[].instruments[].value` | float | Absolute change in 100-day volatility (percentage points). Positive = increase, negative = decrease |

### Example Requests

### Get S&P 500 largest volatility changes

```bash
curl "https://eodhd.com/api/mp/illio/chapters/volume/SnP500?api_token=YOUR_API_TOKEN"
```

### Get Nasdaq-100 largest volatility changes

```bash
curl "https://eodhd.com/api/mp/illio/chapters/volume/NDX?api_token=YOUR_API_TOKEN"
```

### Demo access

```bash
curl "https://eodhd.com/api/mp/illio/chapters/volume/SnP500?api_token=demo"
```

### Notes

- **Marketplace product**: Requires a separate illio marketplace subscription, not included in main EODHD plans.
- **URL path is `/volume/`**: Despite being a volatility endpoint, the URL path uses `/volume/{id}`.
- **100-day volatility**: The change is measured as the absolute difference in 100-day rolling volatility over the past year.
- **Two buckets**: Instruments are split into "Volatility Increase" and "Volatility Decrease" groups.
- **Stats detail from/to**: The stats text includes the starting and ending volatility values for the largest movers.
- **Sorted by magnitude**: Instruments within each bucket are sorted by the size of their volatility change (largest first).
- **Supported indices**: S&P 500 (`SnP500`), Dow Jones (`DJI`), Nasdaq-100 (`NDX`).
- **Disclaimer**: Data does not constitute financial advice or investment recommendations.

> **Note**: Despite the filename, this endpoint serves volume data (path: `/volume/`), not volatility data.

### HTTP Status Codes

| Status Code | Meaning | Description |
|-------------|---------|-------------|
| **200** | OK | Request succeeded. Data returned successfully. |
| **401** | Unauthorized | Invalid or missing API key. |
| **403** | Forbidden | No access to this marketplace product. |
| **429** | Too Many Requests | Rate limit exceeded (1,000 req/min or 100,000 calls/24h). |

---

## Illio Market Insights — Performance vs Market API

<a id="illio-market-insights-performance"></a>

### Endpoint Metadata

| Field | Value |
|---|---|
| Status | complete |
| Source | marketplace (illio) |
| Provider | illio via EODHD Marketplace |
| Base URL | `https://eodhd.com/api/mp/illio/chapters` |
| Path | `/performance/{id}` |
| Method | GET |
| Auth | `api_token` query parameter |
| Slug | `illio-market-insights-performance` |
| Source File | `/Users/arnaurodon/Projects/University/Final Thesis/eodhd-claude-skills/skills/eodhd-api/references/endpoints/illio-market-insights-performance.md` |

### Purpose

Returns data about how instruments performed compared to the market over the last year. Shows the percentage of constituents that outperformed, underperformed, or performed in line with their index, along with per-instrument relative performance values.

**Use cases**:
- Identify which index constituents outperformed or underperformed the market
- Assess market breadth — how many stocks are driving index performance
- Screen for momentum/contrarian ideas based on relative performance
- Research articles and market commentary

### Inputs

### Path (required)

| Parameter | Type | Constraints | Description |
|-----------|------|-------------|-------------|
| `id` | string | enum: `SnP500`, `DJI`, `NDX` | Index watchlist identifier |

- `SnP500` — S&P 500 Index
- `DJI` — Dow Jones Industrial Average
- `NDX` — Nasdaq-100 Index

### Query (required)

| Parameter | Type | Description |
|-----------|------|-------------|
| `api_token` | string | Your API key |

### Outputs

```json
{
  "insightId": "PERFORMANCE_VS_MARKET",
  "categoryId": "PERFORMANCE",
  "title": "Performance vs Market",
  "watchlistName": "US 500 Stocks",
  "insight": {
    "id": "PERFORMANCE_VS_MARKET",
    "title": "How did these instruments perform compared to the market?",
    "whyImportant": "To help you see in one place how all the instruments in the group have performed relative to the market.",
    "description": "Over the last year, excluding any income, most of the instruments underperformed their market.",
    "stats": [
      { "text": "29.44% of instruments outperformed their market." }
    ]
  },
  "chart": {
    "title": "Relative Performance Vs The Market",
    "data": {
      "items": [
        {
          "code": "Out-performed the market",
          "label": "Out-performed the market",
          "value": 29.44,
          "instruments": [
            { "label": "Ameriprise Financial Inc", "value": 21.89 }
          ]
        },
        {
          "code": "Under-performed the market",
          "label": "Under-performed the market",
          "value": 57.43,
          "instruments": [
            { "label": "Adobe Systems Incorporated", "value": -43.28 }
          ]
        },
        {
          "code": "Performed in line with the market",
          "label": "Performed in line with the market",
          "value": 1.98,
          "instruments": [
            { "label": "Exelon Corporation", "value": 14.59 }
          ]
        }
      ]
    }
  }
}
```

### Response Field Definitions

| Field | Type | Description |
|-------|------|-------------|
| `insightId` | string | Always `"PERFORMANCE_VS_MARKET"` |
| `categoryId` | string | Always `"PERFORMANCE"` |
| `title` | string | Human-readable insight title |
| `watchlistName` | string | Name of the index (e.g., "Nasdaq 100", "US 500 Stocks") |
| `insight.id` | string | Insight identifier |
| `insight.title` | string | Question the insight answers |
| `insight.whyImportant` | string | Explanation of why this metric matters |
| `insight.description` | string | Summary of findings |
| `insight.stats[]` | array | Key statistics as text strings |
| `chart.title` | string | Chart title |
| `chart.data.items[]` | array | Performance buckets |
| `chart.data.items[].code` | string | Bucket identifier (e.g., "Out-performed the market") |
| `chart.data.items[].label` | string | Display label for the bucket |
| `chart.data.items[].value` | float | Percentage of instruments in this bucket |
| `chart.data.items[].instruments[]` | array | List of instruments in this bucket |
| `chart.data.items[].instruments[].label` | string | Instrument name |
| `chart.data.items[].instruments[].value` | float | Relative performance vs market (%) |

### Example Requests

### Get S&P 500 performance vs market

```bash
curl "https://eodhd.com/api/mp/illio/chapters/performance/SnP500?api_token=YOUR_API_TOKEN"
```

### Get Nasdaq-100 performance vs market

```bash
curl "https://eodhd.com/api/mp/illio/chapters/performance/NDX?api_token=YOUR_API_TOKEN"
```

### Demo access

```bash
curl "https://eodhd.com/api/mp/illio/chapters/performance/SnP500?api_token=demo"
```

### Notes

- **Marketplace product**: Requires a separate illio marketplace subscription, not included in main EODHD plans.
- **Three buckets**: Instruments are categorized as outperforming, underperforming, or in line (within +/-2%) with the market.
- **Relative performance**: `instruments[].value` is the relative total performance vs the market over the last year (positive = outperformed, negative = underperformed).
- **All constituents listed**: Every constituent of the index is included in the response, grouped by performance bucket.
- **Supported indices**: S&P 500 (`SnP500`), Dow Jones (`DJI`), Nasdaq-100 (`NDX`).
- **Disclaimer**: Data does not constitute financial advice or investment recommendations.

### HTTP Status Codes

| Status Code | Meaning | Description |
|-------------|---------|-------------|
| **200** | OK | Request succeeded. Data returned successfully. |
| **401** | Unauthorized | Invalid or missing API key. |
| **403** | Forbidden | No access to this marketplace product. |
| **429** | Too Many Requests | Rate limit exceeded (1,000 req/min or 100,000 calls/24h). |

---

## Illio Market Insights — Risk-Return API

<a id="illio-market-insights-risk-return"></a>

### Endpoint Metadata

| Field | Value |
|---|---|
| Status | complete |
| Source | marketplace (illio) |
| Provider | illio via EODHD Marketplace |
| Base URL | `https://eodhd.com/api/mp/illio/chapters` |
| Path | `/risk/{id}` |
| Method | GET |
| Auth | `api_token` query parameter |
| Slug | `illio-market-insights-risk-return` |
| Source File | `/Users/arnaurodon/Projects/University/Final Thesis/eodhd-claude-skills/skills/eodhd-api/references/endpoints/illio-market-insights-risk-return.md` |

### Purpose

Returns data about the risk-return tradeoffs of instruments in the specified index. Shows each constituent's return, volatility, and risk-return ratio, helping users identify instruments that reward well (or poorly) for the risk taken.

**Use cases**:
- Identify stocks with the best risk-adjusted returns
- Screen for high-Sharpe-ratio ideas within an index
- Compare return-per-unit-of-risk across all constituents
- Portfolio construction — favor instruments with ratio > 1

### Inputs

### Path (required)

| Parameter | Type | Constraints | Description |
|-----------|------|-------------|-------------|
| `id` | string | enum: `SnP500`, `DJI`, `NDX` | Index watchlist identifier |

- `SnP500` — S&P 500 Index
- `DJI` — Dow Jones Industrial Average
- `NDX` — Nasdaq-100 Index

### Query (required)

| Parameter | Type | Description |
|-----------|------|-------------|
| `api_token` | string | Your API key |

### Outputs

```json
{
  "insightId": "RISK_RETURN",
  "categoryId": "RISK",
  "title": "Risk-return",
  "watchlistName": "US 500 Stocks",
  "insight": {
    "id": "RISK_RETURN",
    "title": "What are the instrument risk-return tradeoffs?",
    "whyImportant": "Instruments with a risk-return ratio greater than 1 reward you well for the risk you take and instruments below 1 do not reward you well for the risk you take.",
    "description": "The top 3 instruments by Risk Return ratio are Targa Resources Inc, Vistra Energy Corp and Palantir Technologies Inc. Class A Common Stock.",
    "stats": [
      { "text": "The top 3 instruments by Risk Return are Targa Resources Inc, Vistra Energy Corp and Palantir Technologies Inc. Class A Common Stock with 6.97, 5.75 and 5.21 respectively." }
    ]
  },
  "chart": {
    "title": "Risk-Return Ratios",
    "data": {
      "items": [
        {
          "label": "Ameriprise Financial Inc",
          "return": 49.97,
          "volatility": 21.44,
          "ratio": 2.33126
        }
      ]
    }
  }
}
```

### Response Field Definitions

| Field | Type | Description |
|-------|------|-------------|
| `insightId` | string | Always `"RISK_RETURN"` |
| `categoryId` | string | Always `"RISK"` |
| `title` | string | Human-readable insight title |
| `watchlistName` | string | Name of the index |
| `insight.id` | string | Insight identifier |
| `insight.title` | string | Question the insight answers |
| `insight.whyImportant` | string | Explanation of risk-return ratio interpretation |
| `insight.description` | string | Summary — top 3 instruments by ratio |
| `insight.stats[]` | array | Key statistics — top 3 and bottom 3 by risk-return ratio |
| `chart.title` | string | Chart title |
| `chart.data.items[]` | array | All instruments with risk-return data |
| `chart.data.items[].label` | string | Instrument name |
| `chart.data.items[].return` | float | Total return over the last year (%) |
| `chart.data.items[].volatility` | float | Annualized volatility (%) |
| `chart.data.items[].ratio` | float | Risk-return ratio (return / volatility). >1 = well rewarded, <1 = poorly rewarded |

### Example Requests

### Get S&P 500 risk-return data

```bash
curl "https://eodhd.com/api/mp/illio/chapters/risk/SnP500?api_token=YOUR_API_TOKEN"
```

### Get Nasdaq-100 risk-return data

```bash
curl "https://eodhd.com/api/mp/illio/chapters/risk/NDX?api_token=YOUR_API_TOKEN"
```

### Demo access

```bash
curl "https://eodhd.com/api/mp/illio/chapters/risk/SnP500?api_token=demo"
```

### Notes

- **Marketplace product**: Requires a separate illio marketplace subscription, not included in main EODHD plans.
- **Ratio interpretation**: Ratio > 1 means the instrument rewards you well for the risk taken. Ratio < 1 (or negative) means the risk is not well compensated.
- **Three data points per instrument**: Each item includes `return`, `volatility`, and `ratio` — suitable for scatter plot visualization.
- **Negative ratios**: Instruments with negative returns will have negative ratios, indicating loss relative to risk.
- **One-year lookback**: Return and volatility are calculated over the last year.
- **All constituents included**: Every member of the selected index appears in the response.
- **Supported indices**: S&P 500 (`SnP500`), Dow Jones (`DJI`), Nasdaq-100 (`NDX`).
- **Disclaimer**: Data does not constitute financial advice or investment recommendations.

### HTTP Status Codes

| Status Code | Meaning | Description |
|-------------|---------|-------------|
| **200** | OK | Request succeeded. Data returned successfully. |
| **401** | Unauthorized | Invalid or missing API key. |
| **403** | Forbidden | No access to this marketplace product. |
| **429** | Too Many Requests | Rate limit exceeded (1,000 req/min or 100,000 calls/24h). |

---

## Illio Market Insights — Volatility Bands API

<a id="illio-market-insights-volatility"></a>

### Endpoint Metadata

| Field | Value |
|---|---|
| Status | complete |
| Source | marketplace (illio) |
| Provider | illio via EODHD Marketplace |
| Base URL | `https://eodhd.com/api/mp/illio/chapters` |
| Path | `/volatility/{id}` |
| Method | GET |
| Auth | `api_token` query parameter |
| Slug | `illio-market-insights-volatility` |
| Source File | `/Users/arnaurodon/Projects/University/Final Thesis/eodhd-claude-skills/skills/eodhd-api/references/endpoints/illio-market-insights-volatility.md` |

### Purpose

Returns data about instruments' volatility compared to the market over the last year. Shows each constituent's annualized volatility alongside the market's volatility, helping users understand each instrument's risk and implied daily move potential.

**Use cases**:
- Compare individual stock volatility to the overall market
- Identify high- and low-volatility constituents for strategy construction
- Estimate implied daily moves based on annualized volatility
- Assess portfolio risk exposure across index members

### Inputs

### Path (required)

| Parameter | Type | Constraints | Description |
|-----------|------|-------------|-------------|
| `id` | string | enum: `SnP500`, `DJI`, `NDX` | Index watchlist identifier |

- `SnP500` — S&P 500 Index
- `DJI` — Dow Jones Industrial Average
- `NDX` — Nasdaq-100 Index

### Query (required)

| Parameter | Type | Description |
|-----------|------|-------------|
| `api_token` | string | Your API key |

### Outputs

```json
{
  "insightId": "VOLATILITY_BANDS_MARKET",
  "categoryId": "RISK",
  "title": "Volatility and Day moves",
  "watchlistName": "US 500 Stocks",
  "insight": {
    "id": "VOLATILITY_BANDS_MARKET",
    "title": "Volatility and Day moves",
    "whyImportant": "This helps you understand each instrument's risk in the context of the amount it could move on an average day. The volatility bands are based on a typical balanced multi-asset portfolio.",
    "description": "Over the last year, the market had a volatility of 12.75%. 495 out of 496 instruments (99.8%) in this index have a volatility above the market.",
    "stats": [
      { "text": "The instrument with the highest volatility is SMCI at 119.65%. This implies a potential daily move of 7.42%." }
    ]
  },
  "chart": {
    "title": "Volatility Compared To The Market",
    "data": {
      "items": [
        { "symbol": "Market", "group": "MARKET", "value": 23.35 },
        { "symbol": "Apple Inc", "group": "Shares", "value": 31.98 },
        { "symbol": "NVIDIA Corporation", "group": "Shares", "value": 44.38 }
      ]
    }
  }
}
```

### Response Field Definitions

| Field | Type | Description |
|-------|------|-------------|
| `insightId` | string | Always `"VOLATILITY_BANDS_MARKET"` |
| `categoryId` | string | Always `"RISK"` |
| `title` | string | Human-readable insight title |
| `watchlistName` | string | Name of the index |
| `insight.id` | string | Insight identifier |
| `insight.title` | string | Insight title |
| `insight.whyImportant` | string | Explanation of why volatility matters |
| `insight.description` | string | Summary — market volatility, number of instruments above/below it |
| `insight.stats[]` | array | Key statistics — highest/lowest volatility instruments and implied daily moves |
| `chart.title` | string | Chart title |
| `chart.data.items[]` | array | All instruments plus the market benchmark |
| `chart.data.items[].symbol` | string | Instrument name (or `"Market"` for the benchmark) |
| `chart.data.items[].group` | string | `"MARKET"` for the benchmark, `"Shares"` for instruments |
| `chart.data.items[].value` | float | Annualized volatility (%) |

> The first item in `items[]` with `group: "MARKET"` represents the overall market/index volatility. All other items are individual constituents.

### Example Requests

### Get S&P 500 volatility bands

```bash
curl "https://eodhd.com/api/mp/illio/chapters/volatility/SnP500?api_token=YOUR_API_TOKEN"
```

### Get Nasdaq-100 volatility bands

```bash
curl "https://eodhd.com/api/mp/illio/chapters/volatility/NDX?api_token=YOUR_API_TOKEN"
```

### Demo access

```bash
curl "https://eodhd.com/api/mp/illio/chapters/volatility/SnP500?api_token=demo"
```

### Notes

- **Marketplace product**: Requires a separate illio marketplace subscription, not included in main EODHD plans.
- **Market benchmark**: The first item with `group: "MARKET"` is the index-level volatility. Compare individual instruments against this value.
- **Implied daily move**: Annualized volatility can be converted to an implied daily move by dividing by sqrt(252). For example, 23.35% annualized ≈ 1.47% daily.
- **One-year lookback**: Volatility is calculated over the last year of trading data.
- **All constituents included**: Every member of the selected index appears in the response.
- **Supported indices**: S&P 500 (`SnP500`), Dow Jones (`DJI`), Nasdaq-100 (`NDX`).
- **Disclaimer**: Data does not constitute financial advice or investment recommendations.

### HTTP Status Codes

| Status Code | Meaning | Description |
|-------------|---------|-------------|
| **200** | OK | Request succeeded. Data returned successfully. |
| **401** | Unauthorized | Invalid or missing API key. |
| **403** | Forbidden | No access to this marketplace product. |
| **429** | Too Many Requests | Rate limit exceeded (1,000 req/min or 100,000 calls/24h). |

---

## Illio Performance Insights API

<a id="illio-performance-insights"></a>

### Endpoint Metadata

| Field | Value |
|---|---|
| Status | complete |
| Source | marketplace (illio) |
| Provider | illio via EODHD Marketplace |
| Base URL | `https://eodhd.com/api/mp/illio/categories` |
| Path | `/performance/{id}` |
| Method | GET |
| Auth | `api_token` query parameter |
| Slug | `illio-performance-insights` |
| Source File | `/Users/arnaurodon/Projects/University/Final Thesis/eodhd-claude-skills/skills/eodhd-api/references/endpoints/illio-performance-insights.md` |

### Purpose

Returns comprehensive performance filter data for all constituents of a given index. Provides multiple insight categories covering market outperformance, price returns, total returns, distance to highs/lows, up/down day analysis, and average move sizes — all across multiple time periods.

**Use cases**:
- Screen for outperformers/underperformers across multiple timeframes (1d to 5y)
- Identify instruments closest to breaking out above highs or below lows
- Analyze up/down day patterns and average move sizes
- Compare price return vs total return (with income/dividends)
- Research and article enrichment with ranked constituent data

### Inputs

### Path (required)

| Parameter | Type | Constraints | Description |
|-----------|------|-------------|-------------|
| `id` | string | enum: `SnP500`, `DJI`, `NDX` | Index watchlist identifier |

- `SnP500` — S&P 500 Index
- `DJI` — Dow Jones Industrial Average
- `NDX` — Nasdaq-100 Index

### Query (required)

| Parameter | Type | Description |
|-----------|------|-------------|
| `api_token` | string | Your API key |

### Outputs

The response contains a `watchlist` object and an `insight[]` array. Each insight has an `id`, `title`, and `chart[]` array with time-period breakdowns. Each chart entry contains `rows[]` with `"Highest"` and `"Lowest"` ranked instruments (top 10 each).

```json
{
  "watchlist": {
    "displayName": "US 500 Stocks",
    "id": "SnP500"
  },
  "insight": [
    {
      "id": "PERFORMANCE_VS_MARKET",
      "title": "Largest Market Out and Under Performers",
      "chart": [
        {
          "subTitle": null,
          "whyImportant": "This helps you assess whether the instrument has beaten the market over the last year...",
          "rows": [
            {
              "label": "Highest",
              "instruments": [
                {
                  "instrumentId": 4115,
                  "name": "Palantir Technologies Inc. Class A Common Stock",
                  "label": "PLTR",
                  "value": "+310.3%",
                  "icon": "images/logos/eod/PLTR.US.png"
                }
              ]
            },
            {
              "label": "Lowest",
              "instruments": [ ... ]
            }
          ],
          "children": []
        }
      ]
    }
  ]
}
```

### Top-Level Fields

| Field | Type | Description |
|-------|------|-------------|
| `watchlist.displayName` | string | Human-readable index name (e.g., "Nasdaq 100") |
| `watchlist.id` | string | Watchlist identifier matching the path parameter |
| `insight[]` | array | Array of insight categories (see below) |

### Insight Object

| Field | Type | Description |
|-------|------|-------------|
| `insight[].id` | string | Insight identifier (see Insight Categories table) |
| `insight[].title` | string | Human-readable insight title |
| `insight[].chart[]` | array | Time-period breakdowns for this insight |

### Chart Object

| Field | Type | Description |
|-------|------|-------------|
| `chart[].subTitle` | string or null | Time period label (e.g., "1 month", "3 months", "1 Year", "Year to Date"). `null` for insights without time periods |
| `chart[].whyImportant` | string | Explanation of what this metric measures |
| `chart[].rows[]` | array | Contains `"Highest"` and `"Lowest"` ranked lists |
| `chart[].children[]` | array | Always empty in current implementation |

### Row / Instrument Object

| Field | Type | Description |
|-------|------|-------------|
| `rows[].label` | string | `"Highest"` or `"Lowest"` |
| `rows[].instruments[]` | array | Top 10 instruments for this ranking |
| `instruments[].instrumentId` | integer | Internal instrument identifier |
| `instruments[].name` | string | Full instrument name |
| `instruments[].label` | string | Ticker symbol (e.g., `"AAPL.US"`, `"PLTR"`) |
| `instruments[].value` | string | Formatted value with sign and % (e.g., `"+310.3%"`, `"-72.8%"`, `"156"`) |
| `instruments[].icon` | string or null | Path to instrument logo image (may be `null`) |

### Example Requests

### Get S&P 500 performance insights

```bash
curl "https://eodhd.com/api/mp/illio/categories/performance/SnP500?api_token=YOUR_API_TOKEN"
```

### Get Nasdaq-100 performance insights

```bash
curl "https://eodhd.com/api/mp/illio/categories/performance/NDX?api_token=YOUR_API_TOKEN"
```

### Demo access

```bash
curl "https://eodhd.com/api/mp/illio/categories/performance/SnP500?api_token=demo"
```

### Notes

- **Marketplace product**: Requires a separate illio marketplace subscription, not included in main EODHD plans.
- **URL path uses `/categories/`**: This endpoint is at `/api/mp/illio/categories/performance/{id}`, not `/chapters/` like the other illio Market Insights endpoints.
- **Large response**: The response contains 9 insight categories with multiple time periods each, totaling a significant amount of data per request. Cache responses where possible.
- **Top 10 per rank**: Each `rows[]` entry contains up to 10 instruments for both "Highest" and "Lowest" rankings.
- **String-formatted values**: Unlike other illio endpoints that return numeric values, `instruments[].value` is a pre-formatted string (e.g., `"+310.3%"`, `"156"`). Parse accordingly.
- **Breakout/breakdown distance**: For `POTENTIAL_BREAK_OUTS` and `POTENTIAL_BREAK_DOWNS`, lower values in "Highest" mean the instrument is closest to the high/low (most likely to break out/down).
- **Up/Down days**: `UP_DAYS` and `DOWN_DAYS` values are integer counts (as strings), not percentages.
- **Supported indices**: S&P 500 (`SnP500`), Dow Jones (`DJI`), Nasdaq-100 (`NDX`).
- **Disclaimer**: Data does not constitute financial advice or investment recommendations.

### HTTP Status Codes

| Status Code | Meaning | Description |
|-------------|---------|-------------|
| **200** | OK | Request succeeded. Data returned successfully. |
| **401** | Unauthorized | Invalid or missing API key. |
| **403** | Forbidden | No access to this marketplace product. |
| **429** | Too Many Requests | Rate limit exceeded (1,000 req/min or 100,000 calls/24h). |

---

## Illio Risk Insights API

<a id="illio-risk-insights"></a>

### Endpoint Metadata

| Field | Value |
|---|---|
| Status | complete |
| Source | marketplace (illio) |
| Provider | illio via EODHD Marketplace |
| Base URL | `https://eodhd.com/api/mp/illio/categories` |
| Path | `/risk/{id}` |
| Method | GET |
| Auth | `api_token` query parameter |
| Slug | `illio-risk-insights` |
| Source File | `/Users/arnaurodon/Projects/University/Final Thesis/eodhd-claude-skills/skills/eodhd-api/references/endpoints/illio-risk-insights.md` |

### Purpose

Returns comprehensive risk filter data for all constituents of a given index. Provides multiple insight categories covering beta analysis (market, upside, downside), risk-return ratios, volatility metrics, correlation to the market, and average daily moves — all across multiple time periods.

**Use cases**:
- Screen for high-beta or low-beta instruments across multiple timeframes (6m to 5y)
- Identify instruments with the best or worst risk-return trade-offs
- Analyze upside vs downside beta asymmetry for individual equities
- Track volatility changes to spot instruments becoming more or less risky
- Measure correlation to the market to find natural portfolio hedges
- Estimate expected daily price moves based on annualized volatility
- Research and article enrichment with ranked constituent risk data

### Inputs

### Path (required)

| Parameter | Type | Constraints | Description |
|-----------|------|-------------|-------------|
| `id` | string | enum: `SnP500`, `DJI`, `NDX` | Index watchlist identifier |

- `SnP500` — S&P 500 Index
- `DJI` — Dow Jones Industrial Average
- `NDX` — Nasdaq-100 Index

### Query (required)

| Parameter | Type | Description |
|-----------|------|-------------|
| `api_token` | string | Your API key |

### Outputs

The response contains a `watchlist` object and an `insight[]` array. Each insight has an `id`, `title`, and `chart[]` array with time-period breakdowns. Each chart entry contains `rows[]` with `"Highest"` and `"Lowest"` ranked instruments (top 10 each).

```json
{
  "watchlist": {
    "displayName": "Nasdaq 100",
    "id": "NDX"
  },
  "insight": [
    {
      "id": "MARKET_IMPACT",
      "title": "Market Impact (Beta)",
      "chart": [
        {
          "subTitle": "6 months",
          "whyImportant": "Beta tells you how much the instrument's price moves compared to a move in the overall market based on the last six months...",
          "rows": [
            {
              "label": "Highest",
              "instruments": [
                {
                  "instrumentId": 5176,
                  "name": "Micron Technology Inc",
                  "label": "MU.US",
                  "value": "2.5x",
                  "icon": "images/logos/eod/MU.US.png"
                }
              ]
            },
            {
              "label": "Lowest",
              "instruments": [ ... ]
            }
          ],
          "children": []
        }
      ]
    }
  ]
}
```

### Top-Level Fields

| Field | Type | Description |
|-------|------|-------------|
| `watchlist.displayName` | string | Human-readable index name (e.g., "Nasdaq 100") |
| `watchlist.id` | string | Watchlist identifier matching the path parameter |
| `insight[]` | array | Array of insight categories (see below) |

### Insight Object

| Field | Type | Description |
|-------|------|-------------|
| `insight[].id` | string | Insight identifier (see Insight Categories table) |
| `insight[].title` | string | Human-readable insight title |
| `insight[].chart[]` | array | Time-period breakdowns for this insight |

### Chart Object

| Field | Type | Description |
|-------|------|-------------|
| `chart[].subTitle` | string or null | Time period label (e.g., "6 months", "1 year", "3 years", "30 days"). `null` for insights without time periods |
| `chart[].whyImportant` | string | Explanation of what this metric measures and why it matters |
| `chart[].rows[]` | array | Contains `"Highest"` and `"Lowest"` ranked lists |
| `chart[].children[]` | array | Always empty in current implementation |

### Row / Instrument Object

| Field | Type | Description |
|-------|------|-------------|
| `rows[].label` | string | `"Highest"` or `"Lowest"` |
| `rows[].instruments[]` | array | Top 10 instruments for this ranking |
| `instruments[].instrumentId` | integer | Internal instrument identifier |
| `instruments[].name` | string | Full instrument name |
| `instruments[].label` | string | Ticker symbol with exchange suffix (e.g., `"MU.US"`, `"PLTR.US"`) |
| `instruments[].value` | string | Formatted value with unit suffix (e.g., `"2.5x"`, `"85.9%"`, `"+62.0%"`, `"0.83x"`, `"5.3%"`, `"1.3"`) |
| `instruments[].icon` | string or null | Path to instrument logo image (may be `null`) |

### Example Requests

### Get S&P 500 risk insights

```bash
curl "https://eodhd.com/api/mp/illio/categories/risk/SnP500?api_token=YOUR_API_TOKEN"
```

### Get Nasdaq-100 risk insights

```bash
curl "https://eodhd.com/api/mp/illio/categories/risk/NDX?api_token=YOUR_API_TOKEN"
```

### Get Dow Jones risk insights

```bash
curl "https://eodhd.com/api/mp/illio/categories/risk/DJI?api_token=YOUR_API_TOKEN"
```

### Demo access

```bash
curl "https://eodhd.com/api/mp/illio/categories/risk/SnP500?api_token=demo"
```

### Notes

- **Marketplace product**: Requires a separate illio marketplace subscription, not included in main EODHD plans.
- **URL path uses `/categories/`**: This endpoint is at `/api/mp/illio/categories/risk/{id}`, not `/chapters/` like the other illio Market Insights endpoints.
- **Large response**: The response contains 12 insight categories with multiple time periods each, totaling a significant amount of data per request. Cache responses where possible.
- **Top 10 per rank**: Each `rows[]` entry contains up to 10 instruments for both "Highest" and "Lowest" rankings.
- **String-formatted values**: All `instruments[].value` fields are pre-formatted strings. Beta values use `"x"` suffix (e.g., `"2.5x"`), volatility/change values use `"%"` suffix (e.g., `"85.9%"`, `"+62.0%"`), risk-return values are plain numbers (e.g., `"1.3"`), correlation values use `"x"` suffix (e.g., `"0.83x"`). Parse accordingly.
- **Signed values**: Volatility change values include explicit `+`/`-` signs (e.g., `"+62.0%"`, `"-21.9%"`). Beta and correlation values may be negative without a sign prefix (e.g., `"-0.4x"`).
- **Asymmetric beta analysis**: Compare `UPSIDE_IMPACT` and `DOWNSIDE_IMPACT` for the same instrument and timeframe to assess beta asymmetry — ideally an instrument has high upside beta and low downside beta.
- **Risk-return interpretation**: For `RISK_RETURN`, values > 1 indicate the instrument's return exceeds its volatility (favorable). For `RISK_RETURN_VS_MARKET`, values > 0 indicate the instrument's risk-return exceeds the market's (outperformance on a risk-adjusted basis).
- **Volatility change periods**: `VOLATILITY_CHANGE` and `VOLATILITY_CHANGE_PERCENTAGE` compare a period with the immediately preceding period of equal length (e.g., last 30 days vs prior 30 days).
- **Supported indices**: S&P 500 (`SnP500`), Dow Jones (`DJI`), Nasdaq-100 (`NDX`).
- **Disclaimer**: Data does not constitute financial advice or investment recommendations.

### HTTP Status Codes

| Status Code | Meaning | Description |
|-------------|---------|-------------|
| **200** | OK | Request succeeded. Data returned successfully. |
| **401** | Unauthorized | Invalid or missing API key. |
| **403** | Forbidden | No access to this marketplace product. |
| **429** | Too Many Requests | Rate limit exceeded (1,000 req/min or 100,000 calls/24h). |

---

## Index Components API

<a id="index-components"></a>

### Endpoint Metadata

| Field | Value |
|---|---|
| Status | complete |
| Source | marketplace (Indices Historical Constituents Data API) |
| Docs | https://eodhd.com/financial-apis/indices-constituents-api |
| Provider | EODHD (via Unicorn Bay / S&P Global) |
| Base URL | https://eodhd.com/api |
| Path | /mp/unicornbay/spglobal/comp/{symbol} |
| Method | GET |
| Auth | api_token (query) |
| Slug | `index-components` |
| Source File | `/Users/arnaurodon/Projects/University/Final Thesis/eodhd-claude-skills/skills/eodhd-api/references/endpoints/index-components.md` |

### Purpose

Return the current list of components for each of the 100+ indices from the
"List of Indices with Details" endpoint. For 30 major S&P and Dow Jones indices,
the endpoint offers 2-12 years of historical changes, marking each addition and
exclusion of a component with the corresponding date. For minor indices, data
completeness varies.

### Inputs

- Required:
  - symbol: index ID from the List of Indices endpoint (e.g. "GSPC.INDX").
    Placed in the URL path.
  - api_token: EODHD API key.
- Optional:
  - fmt: "json" (default and only supported format).

### Outputs

JSON object with three top-level sections:

### General
- Code: string - short index code (e.g. "GSPC").
- Type: string - always "INDEX".
- Name: string - full index name (e.g. "S&P 500 Index").
- Exchange: string - always "INDX".
- MarketCap: number - total market cap of the index.
- CurrencyCode: string - ISO currency code (e.g. "USD").
- CurrencyName: string - full currency name (e.g. "US Dollar").
- CurrencySymbol: string - currency symbol (e.g. "$").
- CountryName: string - country name (e.g. "USA") or "Unknown".
- CountryISO: string - ISO country code (e.g. "US") or "NA".
- OpenFigi: string or null - OpenFIGI identifier.

### Components
Object keyed by sequential string indices ("0", "1", ...). Each entry:
- Code: string - ticker symbol (e.g. "AAPL").
- Exchange: string - exchange code (e.g. "US").
- Name: string - company name.
- Sector: string or null - sector classification.
- Industry: string or null - industry classification.
- Weight: number or null - component weight in the index.

### HistoricalTickerComponents
Object keyed by sequential string indices ("0", "1", ...). Each entry:
- Code: string - ticker symbol.
- Name: string - company name.
- StartDate: string or null - date added to the index (YYYY-MM-DD).
- EndDate: string or null - date removed from the index (YYYY-MM-DD), null if still active.
- IsActiveNow: integer - 1 if the company is currently part of the index, 0 otherwise.
- IsDelisted: integer - 1 if the company is no longer traded in general, 0 otherwise.

### Example Requests

```bash
curl "https://eodhd.com/api/mp/unicornbay/spglobal/comp/GSPC.INDX?fmt=json&api_token=YOUR_API_KEY"
```

### Notes

- **Note**: This endpoint may return `401 Unauthorized` and `404 Not Found` in addition to the standard `402`/`403` codes used by most other endpoints.
- This is a Marketplace product: 1 API request = 10 API calls.
- Limits: 100,000 API calls per 24 hours; 1,000 API requests per minute.
- Only JSON format is supported.
- The symbol parameter value comes from the ID field of the List of Indices
  endpoint (e.g. "GSPC.INDX", "DJI.INDX", "SPSIAD.INDX").
- IsActiveNow indicates whether the company is still part of the index.
- IsDelisted indicates whether the company is still being traded in general.
- For 30 major S&P and DJ indices, historical data spans 2-12 years.
- EODHD users with access to Fundamental data (All-in-one & Fundamental data
  plans) can also access the same Index Components data via the Fundamental
  endpoint: /api/fundamentals/{symbol}?api_token={EODToken}

### HTTP Status Codes

The API returns standard HTTP status codes to indicate success or failure:

| Status Code | Meaning | Description |
|-------------|---------|-------------|
| **200** | OK | Request succeeded. Data returned successfully. |
| **401** | Unauthorized | Invalid API key. Check your `api_token` parameter. |
| **403** | Forbidden | Access denied. Check your subscription. |
| **404** | Not Found | Index symbol not found. Check the symbol parameter. |
| **429** | Too Many Requests | Exceeded rate limit (requests per minute). Slow down requests. |

### Error Response Format

When an error occurs, the API returns a JSON response with error details:

```json
{
  "error": "Error message description",
  "code": 403
}
```

### Handling Errors

**Python Example**:
```python
import requests

def make_api_request(url, params):
    try:
        response = requests.get(url, params=params)
        response.raise_for_status()  # Raises HTTPError for bad status codes
        return response.json()
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 401:
            print("Error: Invalid API key. Check your credentials.")
        elif e.response.status_code == 403:
            print("Error: Access denied. Check your subscription.")
        elif e.response.status_code == 404:
            print("Error: Index symbol not found.")
        elif e.response.status_code == 429:
            print("Error: Rate limit exceeded. Please slow down your requests.")
        else:
            print(f"HTTP Error: {e}")
        return None
    except requests.exceptions.RequestException as e:
        print(f"Request failed: {e}")
        return None
```

**Best Practices**:
- Always check status codes before processing response data
- Implement exponential backoff for 429 errors
- Cache responses to reduce API calls
- Monitor your API usage in the user dashboard

---

## List of Indices with Details API

<a id="indices-list"></a>

### Endpoint Metadata

| Field | Value |
|---|---|
| Status | complete |
| Source | marketplace (Indices Historical Constituents Data API) |
| Docs | https://eodhd.com/financial-apis/indices-constituents-api |
| Provider | EODHD (via Unicorn Bay / S&P Global) |
| Base URL | https://eodhd.com/api |
| Path | /mp/unicornbay/spglobal/list |
| Method | GET |
| Auth | api_token (query) |
| Slug | `indices-list` |
| Source File | `/Users/arnaurodon/Projects/University/Final Thesis/eodhd-claude-skills/skills/eodhd-api/references/endpoints/indices-list.md` |

### Purpose

Return end-of-day essential details for 100+ indices: Global S&P and Dow Jones
Indexes, including S&P 500, 600, 100, 400, and 21 Key Industry indices with
fields such as Value, Market Cap, Divisor, Daily Return, Adjusted Market Cap
and more. Data is sourced from S&P Global and structured in JSON format.

### Inputs

- Required:
  - api_token: EODHD API key.
- Optional:
  - fmt: "json" (default and only supported format).

### Outputs

JSON array of index objects. Each object contains:
- ID: string - full index identifier (e.g. "GSPC.INDX").
- Code: string - short index code (e.g. "GSPC").
- Name: string - human-readable index name (e.g. "S&P 500").
- Constituents: integer - number of current constituents.
- Value: number - current index value.
- MarketCap: number or null - total market cap.
- Divisor: number or null - index divisor.
- DailyReturn: number - daily return as a decimal (e.g. -0.0043).
- Dividend: number or null - dividend value.
- AdjustedMarketCap: number or null - adjusted market cap.
- AdjustedDivisor: number or null - adjusted divisor.
- AdjustedConstituents: integer - adjusted number of constituents.
- CurrencyCode: string - ISO currency code (e.g. "USD", "ILS", "CAD", "JPY").
- CurrencyName: string - full currency name (e.g. "US Dollar").
- CurrencySymbol: string - currency symbol (e.g. "$").
- LastUpdate: string - date of last update in YYYY-MM-DD format.

### Example Requests

```bash
curl "https://eodhd.com/api/mp/unicornbay/spglobal/list?fmt=json&api_token=YOUR_API_KEY"
```

### Notes

- **Note**: This endpoint may return `401 Unauthorized` in addition to the standard `402`/`403` codes used by most other endpoints.
- This is a Marketplace product: 1 API request = 10 API calls.
- Limits: 100,000 API calls per 24 hours; 1,000 API requests per minute.
- Only JSON format is supported.
- Covers 100+ indices including S&P 500, S&P 600, S&P 100, S&P 400, and
  21 key industry indices, plus Dow Jones Industrial, Transportation,
  Utility, and Composite averages.
- Indices are available in multiple currencies (USD, CAD, ILS, JPY) and
  variants (Price, Total Return, Net Total Return, Hedged).
- The ID field (e.g. "GSPC.INDX") is used as the symbol parameter for the
  Index Components endpoint.

### HTTP Status Codes

The API returns standard HTTP status codes to indicate success or failure:

| Status Code | Meaning | Description |
|-------------|---------|-------------|
| **200** | OK | Request succeeded. Data returned successfully. |
| **401** | Unauthorized | Invalid API key. Check your `api_token` parameter. |
| **403** | Forbidden | Access denied. Check your subscription. |
| **429** | Too Many Requests | Exceeded rate limit (requests per minute). Slow down requests. |

### Error Response Format

When an error occurs, the API returns a JSON response with error details:

```json
{
  "error": "Error message description",
  "code": 403
}
```

### Handling Errors

**Python Example**:
```python
import requests

def make_api_request(url, params):
    try:
        response = requests.get(url, params=params)
        response.raise_for_status()  # Raises HTTPError for bad status codes
        return response.json()
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 401:
            print("Error: Invalid API key. Check your credentials.")
        elif e.response.status_code == 403:
            print("Error: Access denied. Check your subscription.")
        elif e.response.status_code == 429:
            print("Error: Rate limit exceeded. Please slow down your requests.")
        else:
            print(f"HTTP Error: {e}")
        return None
    except requests.exceptions.RequestException as e:
        print(f"Request failed: {e}")
        return None
```

**Best Practices**:
- Always check status codes before processing response data
- Implement exponential backoff for 429 errors
- Cache responses to reduce API calls
- Monitor your API usage in the user dashboard

---

## Insider Transactions API

<a id="insider-transactions"></a>

### Endpoint Metadata

| Field | Value |
|---|---|
| Status | complete |
| Source | financial-apis (Insider Transactions API) |
| Docs | https://eodhd.com/financial-apis/insider-transactions-api |
| Provider | EODHD |
| Base URL | https://eodhd.com/api |
| Path | /insider-transactions |
| Method | GET |
| Auth | api_token (query) |
| Slug | `insider-transactions` |
| Source File | `/Users/arnaurodon/Projects/University/Final Thesis/eodhd-claude-skills/skills/eodhd-api/references/endpoints/insider-transactions.md` |

### Purpose

Fetches insider trading activity including purchases, sales, and option exercises by company
executives, directors, and major shareholders. Useful for tracking insider sentiment,
identifying unusual trading patterns, and fundamental analysis.

### Inputs

| Parameter | Required | Type | Description |
|-----------|----------|------|-------------|
| api_token | Yes | string | Your API key for authentication |
| code | No | string | Ticker symbol with exchange suffix (e.g., 'AAPL.US') |
| from | No | string (YYYY-MM-DD) | Start date for transaction data |
| to | No | string (YYYY-MM-DD) | End date for transaction data |
| limit | No | integer | Number of results to return. Default: 100 |
| fmt | No | string | Output format: 'json' or 'csv'. Default: 'json' |

### Outputs

```json
[
  {
    "code": "AAPL.US",
    "date": "2025-01-15",
    "reportDate": "2025-01-17",
    "ownerName": "John Smith",
    "ownerCik": "0001234567",
    "ownerTitle": "Chief Executive Officer",
    "transactionDate": "2025-01-15",
    "transactionCode": "P",
    "transactionAmount": 5000,
    "transactionPrice": 185.50,
    "transactionAcquiredDisposed": "A",
    "postTransactionAmount": 150000,
    "secLink": "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=..."
  }
]
```

### Field Descriptions

| Field | Type | Description |
|-------|------|-------------|
| code | string | Ticker symbol with exchange suffix |
| date | string (date) | Date record was added to database |
| reportDate | string (date) | SEC filing date |
| ownerName | string | Name of the insider |
| ownerCik | string | SEC Central Index Key for the insider |
| ownerTitle | string | Position/title at the company |
| transactionDate | string (date) | Date transaction was executed |
| transactionCode | string | SEC transaction code (see below) |
| transactionAmount | number | Number of shares in transaction |
| transactionPrice | number/null | Price per share (null for gifts/awards) |
| transactionAcquiredDisposed | string | 'A' (acquired) or 'D' (disposed) |
| postTransactionAmount | number | Total shares held after transaction |
| secLink | string | Link to SEC filing |

### Transaction Codes

| Code | Description |
|------|-------------|
| P | Open market or private purchase |
| S | Open market or private sale |
| A | Grant, award, or acquisition (non-purchase) |
| D | Sale to issuer |
| F | Tax withholding |
| M | Exercise of derivative security |
| C | Conversion of derivative security |
| G | Gift |
| J | Other acquisition or disposition |
| K | Equity swap or similar transaction |
| V | Transaction voluntary reported earlier than required |

### Common Owner Titles

- Chief Executive Officer (CEO)
- Chief Financial Officer (CFO)
- Chief Operating Officer (COO)
- Director
- 10% Owner (major shareholder)
- President
- General Counsel
- VP, Sales/Engineering/etc.

### Example Requests

```bash
# All recent insider transactions
curl "https://eodhd.com/api/insider-transactions?api_token=demo&fmt=json"

# Insider transactions for specific company
curl "https://eodhd.com/api/insider-transactions?code=AAPL.US&api_token=demo&fmt=json"

# Transactions for date range
curl "https://eodhd.com/api/insider-transactions?code=MSFT.US&from=2025-01-01&to=2025-01-31&api_token=demo&fmt=json"

# Limit results
curl "https://eodhd.com/api/insider-transactions?code=TSLA.US&limit=50&api_token=demo&fmt=json"

# Using the helper client
python eodhd_client.py --endpoint insider-transactions --symbol AAPL.US --from-date 2025-01-01 --limit 50
```

### Notes

- Insider transactions are filed with SEC within 2 business days (Form 4)
- `transactionCode` 'P' (purchase) and 'S' (sale) are most significant for sentiment
- Large purchases by multiple insiders may signal confidence
- Scheduled sales (10b5-1 plans) are less meaningful than discretionary sales
- `transactionPrice` may be null for stock grants, awards, or gifts
- Use `postTransactionAmount` to see total insider holdings
- Required fields: code, ownerName, transactionDate, transactionCode, transactionAmount
- API call consumption: 1 call per request
- **Coverage**: Data is available for the **past year** for **US companies only**, sourced from SEC Form 4 filings. Non-US markets are not covered.

### HTTP Status Codes

The API returns standard HTTP status codes to indicate success or failure:

| Status Code | Meaning | Description |
|-------------|---------|-------------|
| **200** | OK | Request succeeded. Data returned successfully. |
| **402** | Payment Required | API limit used up. Upgrade plan or wait for limit reset. |
| **403** | Unauthorized | Invalid API key. Check your `api_token` parameter. |
| **429** | Too Many Requests | Exceeded rate limit (requests per minute). Slow down requests. |

### Error Response Format

When an error occurs, the API returns a JSON response with error details:

```json
{
  "error": "Error message description",
  "code": 403
}
```

### Handling Errors

**Python Example**:
```python
import requests

def make_api_request(url, params):
    try:
        response = requests.get(url, params=params)
        response.raise_for_status()  # Raises HTTPError for bad status codes
        return response.json()
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 402:
            print("Error: API limit exceeded. Please upgrade your plan.")
        elif e.response.status_code == 403:
            print("Error: Invalid API key. Check your credentials.")
        elif e.response.status_code == 429:
            print("Error: Rate limit exceeded. Please slow down your requests.")
        else:
            print(f"HTTP Error: {e}")
        return None
    except requests.exceptions.RequestException as e:
        print(f"Request failed: {e}")
        return None
```

**Best Practices**:
- Always check status codes before processing response data
- Implement exponential backoff for 429 errors
- Cache responses to reduce API calls
- Monitor your API usage in the user dashboard

---

## Intraday Historical Data API

<a id="intraday-historical-data"></a>

### Endpoint Metadata

| Field | Value |
|---|---|
| Status | complete |
| Source | financial-apis (Intraday Historical Data API) |
| Docs | https://eodhd.com/financial-apis/intraday-historical-data-api |
| Provider | EODHD |
| Base URL | https://eodhd.com/api |
| Path | /intraday/{SYMBOL} |
| Method | GET |
| Auth | api_token (query) |
| Slug | `intraday-historical-data` |
| Source File | `/Users/arnaurodon/Projects/University/Final Thesis/eodhd-claude-skills/skills/eodhd-api/references/endpoints/intraday-historical-data.md` |

### Purpose

Fetches intraday historical OHLCV data for a symbol with configurable intervals (1m, 5m, 1h).
Essential for day traders, algorithmic traders, and analysts who need short-term price data
for backtesting strategies, identifying volatility periods, and analyzing rapid market movements.

### Inputs

| Parameter | Required | Type | Description |
|-----------|----------|------|-------------|
| {SYMBOL} | Yes | path | Symbol with exchange suffix (e.g., 'AAPL.US', 'AAPL.MX') |
| api_token | Yes | string | Your API key for authentication |
| interval | No | string | Interval: '1m' (1-minute), '5m' (5-minute), '1h' (1-hour). Default: '5m' |
| fmt | No | string | Output format: 'json' or 'csv'. Default: 'json' |
| from | No | integer | Start time as Unix timestamp (UTC) |
| to | No | integer | End time as Unix timestamp (UTC) |
| split-dt | No | integer | If set to 1, splits datetime into separate 'date' and 'time' fields (for Zorro software) |

### Outputs

### Standard Response (JSON)

```json
[
  {
    "timestamp": 1627911000,
    "gmtoffset": 0,
    "datetime": "2021-08-02 13:30:00",
    "open": 146.36,
    "high": 146.949996,
    "low": 146.089996,
    "close": 146.419998,
    "volume": 3930530
  },
  {
    "timestamp": 1627911300,
    "gmtoffset": 0,
    "datetime": "2021-08-02 13:35:00",
    "open": 146.449798,
    "high": 146.449798,
    "low": 145.539993,
    "close": 145.580001,
    "volume": 2639916
  }
]
```

### With split-dt=1 (separate date/time fields)

```json
[
  {
    "timestamp": 1627911000,
    "gmtoffset": 0,
    "date": "2021-08-02",
    "time": "13:30:00",
    "open": 146.36,
    "high": 146.949996,
    "low": 146.089996,
    "close": 146.419998,
    "volume": 3930530
  }
]
```

### CSV Response

```csv
Timestamp,Gmtoffset,Datetime,Open,High,Low,Close,Volume
1627911000,0,"2021-08-02 13:30:00",146.36,146.949996,146.089996,146.419998,3930530
1627911300,0,"2021-08-02 13:35:00",146.449798,146.449798,145.539993,145.580001,2639916
```

### Field Descriptions

| Field | Type | Description |
|-------|------|-------------|
| timestamp | integer | Unix timestamp (UTC) |
| gmtoffset | integer | GMT offset applied (usually 0 for UTC) |
| datetime | string | Timestamp in 'YYYY-MM-DD HH:MM:SS' format (UTC) |
| date | string | Date only (when split-dt=1) |
| time | string | Time only (when split-dt=1) |
| open | number | Opening price of the interval |
| high | number | Highest price within the interval |
| low | number | Lowest price within the interval |
| close | number | Closing price of the interval |
| volume | integer | Trading volume during the interval |

### Example Requests

```bash
# 5-minute bars for AAPL (default interval)
curl "https://eodhd.com/api/intraday/AAPL.US?api_token=demo&fmt=json"

# 1-minute bars
curl "https://eodhd.com/api/intraday/AAPL.US?api_token=demo&fmt=json&interval=1m"

# 1-hour bars
curl "https://eodhd.com/api/intraday/AAPL.US?api_token=demo&fmt=json&interval=1h"

# Specific date range (Unix timestamps)
curl "https://eodhd.com/api/intraday/AAPL.US?api_token=demo&fmt=json&from=1627896900&to=1627916900"

# Split date and time (for Zorro software)
curl "https://eodhd.com/api/intraday/AAPL.US?api_token=demo&fmt=json&from=1627896900&to=1627916900&split-dt=1"

# CSV format
curl "https://eodhd.com/api/intraday/AAPL.US?api_token=demo&fmt=csv&from=1627896900&to=1627916900"

# Using the helper client
python eodhd_client.py --endpoint intraday --symbol AAPL.US --interval 5m
```

### Notes

- **All data is in UTC timezone** - timestamps are Unix format, gmtoffset is typically 0
- **API call consumption**: 5 calls per request
- **Plans required**: EOD+Intraday - All World Extended, All-in-One
- **US stocks**: Include pre-market and after-hours data (for 1m interval)
- **Data finalization**: 2-3 hours after market close
- **Volume**: Actual traded volume for that interval
- **Gaps**: Data may have gaps for low-volume periods or market closures
- **Default range**: Last 120 days if no from/to specified
- **Intraday data is unadjusted**: Prices are not adjusted for splits or dividends. To adjust, use the splits/dividends data (https://eodhd.com/financial-apis/api-splits-dividends) or obtain a coefficient from the EOD API: `k = adjusted_close / close`, then `adjusted_open = open * k`, `adjusted_high = high * k`, `adjusted_low = low * k`. Calculate `k` for **each day** as it changes on every split or dividend. See also the [Data Adjustment Guide](../general/data-adjustment-guide.md).
- **Timestamp meaning**: The timestamp is the **opening** of the candle. The data relates to the interval starting at that timestamp.
- **Missing 1-minute bars**: Pre-market 1-minute data for stocks can have gaps due to low volume. Data within regular market hours is usually complete for top stocks.
- **Null values**: Low-volume stocks that may have no trades for several days can return null values in intraday data.
- **Funds**: Intraday data is available for funds.
- **UTC vs EST offset**: UTC does not observe daylight saving time, but New York does. The difference between UTC and Eastern time is either 5 hours (EST, November–March) or 4 hours (EDT, March–November). Account for this when converting timestamps.
- **1-minute vs 5-minute data sources**: 1-minute and 5-minute data currently come from different sources. 1-minute data comes from the consolidated CTA/UTP feed (aggregated from all US exchanges, including pre/post-market). 5-minute data comes from a single venue. EODHD recommends using **1-minute intervals** as the more comprehensive and precise option.
- **1-minute close vs EOD close**: The daily closing price is formed from the closing auction, while the last 1-minute candle is simply the last candle of the day. These may differ. The Intraday API is not intended for obtaining the official daily close price.
- **CTA/UTP consolidated data**: EODHD uses consolidated data from CTA/UTP feeds, which aggregates data from all US exchanges. Minor discrepancies with other sources may occur if they use data from a single exchange only.

### HTTP Status Codes

The API returns standard HTTP status codes to indicate success or failure:

| Status Code | Meaning | Description |
|-------------|---------|-------------|
| **200** | OK | Request succeeded. Data returned successfully. |
| **402** | Payment Required | API limit used up. Upgrade plan or wait for limit reset. |
| **403** | Unauthorized | Invalid API key. Check your `api_token` parameter. |
| **429** | Too Many Requests | Exceeded rate limit (requests per minute). Slow down requests. |

### Error Response Format

When an error occurs, the API returns a JSON response with error details:

```json
{
  "error": "Error message description",
  "code": 403
}
```

### Handling Errors

**Python Example**:
```python
import requests

def make_api_request(url, params):
    try:
        response = requests.get(url, params=params)
        response.raise_for_status()  # Raises HTTPError for bad status codes
        return response.json()
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 402:
            print("Error: API limit exceeded. Please upgrade your plan.")
        elif e.response.status_code == 403:
            print("Error: Invalid API key. Check your credentials.")
        elif e.response.status_code == 429:
            print("Error: Rate limit exceeded. Please slow down your requests.")
        else:
            print(f"HTTP Error: {e}")
        return None
    except requests.exceptions.RequestException as e:
        print(f"Request failed: {e}")
        return None
```

**Best Practices**:
- Always check status codes before processing response data
- Implement exponential backoff for 429 errors
- Cache responses to reduce API calls
- Monitor your API usage in the user dashboard

---

## Investverte ESG List Companies API

<a id="investverte-esg-list-companies"></a>

### Endpoint Metadata

| Field | Value |
|---|---|
| Status | complete |
| Source | marketplace (Investverte API) |
| Docs | https://eodhd.com/financial-apis/esg-data-api |
| Provider | Investverte via EODHD Marketplace |
| Base URL | `https://eodhd.com/api/mp/investverte` |
| Path | `/companies` |
| Method | GET |
| Auth | `api_token` query parameter |
| Slug | `investverte-esg-list-companies` |
| Source File | `/Users/arnaurodon/Projects/University/Final Thesis/eodhd-claude-skills/skills/eodhd-api/references/endpoints/investverte-esg-list-companies.md` |

### Purpose

Returns the full list of companies available in the Investverte ESG dataset. Each entry contains a ticker symbol and company name, allowing users to discover which companies have ESG data and obtain the symbol needed to query detailed ESG ratings via the View Company endpoint.

**Use cases**:
- Discover which companies have ESG data available
- Obtain the correct symbol identifier for use with the ESG View Company endpoint
- Build a universe of ESG-rated companies for screening or portfolio construction
- Browse companies across global exchanges (US, HK, KS, KQ, SZ, SS, L, F, T, KL, TW, SA, etc.)

### Inputs

### Query (required)

| Parameter | Type | Description |
|-----------|------|-------------|
| `api_token` | string | Your API key |

### Outputs

JSON array of company objects. Each object contains:

| Field | Type | Description |
|-------|------|-------------|
| `symbol` | string | Ticker symbol with exchange suffix (e.g. `"AAPL.US"`, `"000001.SZ"`, `"0439.HK"`) |
| `name` | string | Full company name |

The symbol uses the standard EODHD format `{TICKER}.{EXCHANGE}` and can be passed directly to the ESG View Company endpoint.

### Example Requests

```bash
curl "https://eodhd.com/api/mp/investverte/companies?api_token=YOUR_API_TOKEN"
```

### Notes

- **Marketplace product**: Requires a separate Investverte marketplace subscription, not included in main EODHD plans.
- **Global coverage**: Includes companies from many exchanges worldwide — US, HK, SZ, SS (China), KS/KQ (Korea), T (Japan), KL (Malaysia), TW/TWO (Taiwan), SA (Brazil), L/F (UK/Germany), MI (Italy), ST/HE (Nordics), OL (Norway), WA (Poland), MC (Spain), BO/NS (India), SN (Chile), and more.
- **Symbol format**: Uses standard EODHD `{TICKER}.{EXCHANGE}` format. The symbol value can be used directly with the Investverte ESG View Company endpoint.
- **No pagination parameters**: The endpoint returns the full list in a single response.
- **ESG Data by Investverte** provides detailed ESG ratings, comprehensive company information, and sector-specific analysis for sustainable investment decisions.

### HTTP Status Codes

| Status Code | Meaning | Description |
|-------------|---------|-------------|
| **200** | OK | Request succeeded. Data returned successfully. |
| **401** | Unauthorized | Invalid or missing API key. |
| **403** | Forbidden | No access to this marketplace product. |
| **429** | Too Many Requests | Rate limit exceeded (1,000 req/min or 100,000 calls/24h). |

### Error Response Format

When an error occurs, the API returns a JSON response with error details:

```json
{
  "error": "Error message description",
  "code": 403
}
```

### Handling Errors

**Python Example**:
```python
import requests

def make_api_request(url, params):
    try:
        response = requests.get(url, params=params)
        response.raise_for_status()  # Raises HTTPError for bad status codes
        return response.json()
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 401:
            print("Error: Invalid API key. Check your credentials.")
        elif e.response.status_code == 403:
            print("Error: No access to Investverte marketplace product.")
        elif e.response.status_code == 429:
            print("Error: Rate limit exceeded. Please slow down your requests.")
        else:
            print(f"HTTP Error: {e}")
        return None
    except requests.exceptions.RequestException as e:
        print(f"Request failed: {e}")
        return None
```

**Best Practices**:
- Always check status codes before processing response data
- Implement exponential backoff for 429 errors
- Cache responses to reduce API calls — the company list doesn't change frequently
- Monitor your API usage in the user dashboard

---

## Investverte ESG List Countries API

<a id="investverte-esg-list-countries"></a>

### Endpoint Metadata

| Field | Value |
|---|---|
| Status | complete |
| Source | marketplace (Investverte API) |
| Docs | https://eodhd.com/financial-apis/esg-data-api |
| Provider | Investverte via EODHD Marketplace |
| Base URL | `https://eodhd.com/api/mp/investverte` |
| Path | `/countries` |
| Method | GET |
| Auth | `api_token` query parameter |
| Slug | `investverte-esg-list-countries` |
| Source File | `/Users/arnaurodon/Projects/University/Final Thesis/eodhd-claude-skills/skills/eodhd-api/references/endpoints/investverte-esg-list-countries.md` |

### Purpose

Returns the full list of countries available in the Investverte ESG dataset. Each entry contains a two-letter country code and a country name, allowing users to discover which countries have ESG data and obtain the code needed to query country-level ESG details via the View Country endpoint.

**Use cases**:
- Discover which countries have ESG data available
- Obtain the correct country code for use with the ESG View Country endpoint
- Filter or group ESG-rated companies by country
- Build geographic views of ESG coverage for research or portfolio construction

### Inputs

### Query (required)

| Parameter | Type | Description |
|-----------|------|-------------|
| `api_token` | string | Your API key |

### Outputs

JSON array of country objects. Each object contains:

| Field | Type | Description |
|-------|------|-------------|
| `country_code` | string | Two-letter country code (generally ISO 3166-1 alpha-2, with some special codes) |
| `country_descr` | string | Human-readable country name |

### Special codes

| Code | Meaning |
|------|---------|
| `XX` | Not Recognized - Emerging |
| `XZ` | Not Recognized - Developed |

### Note on encoding

Some country names contain XML-encoded characters (e.g. `_x002C_` for commas, `_x0028_`/`_x0029_` for parentheses, `_x002F_` for slashes). These should be decoded when displaying to users.

### Example Requests

```bash
curl "https://eodhd.com/api/mp/investverte/countries?api_token=YOUR_API_TOKEN"
```

### Notes

- **Marketplace product**: Requires a separate Investverte marketplace subscription, not included in main EODHD plans.
- **Broad coverage**: Covers 170+ countries and territories worldwide, from major economies (US, GB, JP, CN, DE) to smaller territories (GI, GG, JE, IM, etc.).
- **Country codes**: Generally follow ISO 3166-1 alpha-2 standard. Two non-standard codes exist: `XX` (Not Recognized - Emerging) and `XZ` (Not Recognized - Developed) for companies that cannot be mapped to a specific country.
- **XML-encoded characters**: Some `country_descr` values contain XML entity references (e.g. `Congo_x002C_ The Democratic Republic of the`, `Croatia _x0028_Hrvatska_x0029_`). These should be decoded for display.
- **No pagination parameters**: The endpoint returns the full list in a single response.
- The `country_code` value can be used with the Investverte ESG View Country endpoint to retrieve country-level ESG data.

### HTTP Status Codes

| Status Code | Meaning | Description |
|-------------|---------|-------------|
| **200** | OK | Request succeeded. Data returned successfully. |
| **401** | Unauthorized | Invalid or missing API key. |
| **403** | Forbidden | No access to this marketplace product. |
| **429** | Too Many Requests | Rate limit exceeded (1,000 req/min or 100,000 calls/24h). |

### Error Response Format

When an error occurs, the API returns a JSON response with error details:

```json
{
  "error": "Error message description",
  "code": 403
}
```

### Handling Errors

**Python Example**:
```python
import requests

def make_api_request(url, params):
    try:
        response = requests.get(url, params=params)
        response.raise_for_status()  # Raises HTTPError for bad status codes
        return response.json()
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 401:
            print("Error: Invalid API key. Check your credentials.")
        elif e.response.status_code == 403:
            print("Error: No access to Investverte marketplace product.")
        elif e.response.status_code == 429:
            print("Error: Rate limit exceeded. Please slow down your requests.")
        else:
            print(f"HTTP Error: {e}")
        return None
    except requests.exceptions.RequestException as e:
        print(f"Request failed: {e}")
        return None
```

**Best Practices**:
- Always check status codes before processing response data
- Implement exponential backoff for 429 errors
- Cache responses to reduce API calls — the country list doesn't change frequently
- Monitor your API usage in the user dashboard

---

## Investverte ESG List Sectors API

<a id="investverte-esg-list-sectors"></a>

### Endpoint Metadata

| Field | Value |
|---|---|
| Status | complete |
| Source | marketplace (Investverte API) |
| Docs | https://eodhd.com/financial-apis/esg-data-api |
| Provider | Investverte via EODHD Marketplace |
| Base URL | `https://eodhd.com/api/mp/investverte` |
| Path | `/sectors` |
| Method | GET |
| Auth | `api_token` query parameter |
| Slug | `investverte-esg-list-sectors` |
| Source File | `/Users/arnaurodon/Projects/University/Final Thesis/eodhd-claude-skills/skills/eodhd-api/references/endpoints/investverte-esg-list-sectors.md` |

### Purpose

Returns the full list of sectors available in the Investverte ESG dataset.
Each entry contains a sector name, allowing users to discover which sectors
have ESG data and obtain the sector identifier needed to query sector-level
ESG details via the View Sector endpoint.

**Use cases**:
- Discover which sectors have ESG data available
- Obtain the correct sector name for use with the ESG View Sector endpoint
- Filter or group ESG-rated companies by sector
- Build sector-level ESG analysis for portfolio construction or research

### Inputs

### Query (required)

| Parameter | Type | Description |
|-----------|------|-------------|
| `api_token` | string | Your API key |

### Outputs

JSON array of sector objects. Each object contains:

| Field | Type | Description |
|-------|------|-------------|
| `sector` | string | Sector name (e.g. `"Technology"`, `"Banking"`, `"Healthcare"`) |

### Example Requests

```bash
curl "https://eodhd.com/api/mp/investverte/sectors?api_token=YOUR_API_TOKEN"
```

### Notes

- **Marketplace product**: Requires a separate Investverte marketplace subscription, not included in main EODHD plans.
- **53 sectors**: The dataset covers 53 sectors ranging from broad categories (e.g. `Technology`, `Energy`, `Healthcare`) to specific industries (e.g. `Semiconductors`, `Biotechnology`, `Marine`).
- **"Unknown" sector**: Companies that cannot be classified into a specific sector are grouped under `"Unknown"`.
- **No pagination parameters**: The endpoint returns the full list in a single response.
- The `sector` value can be used with the Investverte ESG View Sector endpoint to retrieve sector-level ESG data.

### HTTP Status Codes

| Status Code | Meaning | Description |
|-------------|---------|-------------|
| **200** | OK | Request succeeded. Data returned successfully. |
| **401** | Unauthorized | Invalid or missing API key. |
| **403** | Forbidden | No access to this marketplace product. |
| **429** | Too Many Requests | Rate limit exceeded (1,000 req/min or 100,000 calls/24h). |

### Error Response Format

When an error occurs, the API returns a JSON response with error details:

```json
{
  "error": "Error message description",
  "code": 403
}
```

### Handling Errors

**Python Example**:
```python
import requests

def make_api_request(url, params):
    try:
        response = requests.get(url, params=params)
        response.raise_for_status()  # Raises HTTPError for bad status codes
        return response.json()
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 401:
            print("Error: Invalid API key. Check your credentials.")
        elif e.response.status_code == 403:
            print("Error: No access to Investverte marketplace product.")
        elif e.response.status_code == 429:
            print("Error: Rate limit exceeded. Please slow down your requests.")
        else:
            print(f"HTTP Error: {e}")
        return None
    except requests.exceptions.RequestException as e:
        print(f"Request failed: {e}")
        return None
```

**Best Practices**:
- Always check status codes before processing response data
- Implement exponential backoff for 429 errors
- Cache responses to reduce API calls — the sector list doesn't change frequently
- Monitor your API usage in the user dashboard

---

## Investverte ESG View Company API

<a id="investverte-esg-view-company"></a>

### Endpoint Metadata

| Field | Value |
|---|---|
| Status | complete |
| Source | marketplace (Investverte API) |
| Docs | https://eodhd.com/financial-apis/esg-data-api |
| Provider | Investverte via EODHD Marketplace |
| Base URL | `https://eodhd.com/api/mp/investverte` |
| Path | `/esg/{symbol}` |
| Method | GET |
| Auth | `api_token` query parameter |
| Slug | `investverte-esg-view-company` |
| Source File | `/Users/arnaurodon/Projects/University/Final Thesis/eodhd-claude-skills/skills/eodhd-api/references/endpoints/investverte-esg-view-company.md` |

### Purpose

Returns detailed ESG (Environmental, Social, Governance) ratings for a
specific company. Provides individual E, S, and G pillar scores plus the
composite ESG score, broken down by year and reporting frequency (full year
or quarterly). When called without filters, returns the full historical time
series across all available years and frequencies.

**Use cases**:
- Assess a company's ESG performance across all three pillars
- Track ESG score trends over time (annual and quarterly)
- Compare E, S, G pillar strengths and weaknesses within a company
- Benchmark a company's ESG profile against peers or country/sector averages
- Support ESG-driven investment screening and due diligence

### Inputs

### Path (required)

| Parameter | Type | Description |
|-----------|------|-------------|
| `symbol` | string | Company ticker symbol (e.g. `AAPL`, `MSFT`, `000039.SZ`). Use tickers from the List Companies endpoint. Note: the exchange suffix is included for non-US symbols but omitted for US symbols. |

### Query (required)

| Parameter | Type | Description |
|-----------|------|-------------|
| `api_token` | string | Your API key |

### Query (optional)

| Parameter | Type | Values | Description |
|-----------|------|--------|-------------|
| `year` | number | e.g. `2014`, `2021`, `2024` | Filter to a specific year |
| `frequency` | string | `FY`, `Q1`, `Q2`, `Q3`, `Q4` | Filter to a specific reporting frequency |

- `FY` = Full Year
- `Q1`..`Q4` = Quarterly periods
- When both `year` and `frequency` are provided, a single record is returned.
- When neither is provided, the full time series (all years, all frequencies) is returned.

### Outputs

JSON array of ESG rating objects. Each object contains:

| Field | Type | Description |
|-------|------|-------------|
| `e` | number | Environmental pillar score |
| `s` | number | Social pillar score |
| `g` | number | Governance pillar score |
| `esg` | number | Composite ESG score |
| `year` | integer | Year of the data point |
| `frequency` | string | Reporting frequency: `"FY"`, `"Q1"`, `"Q2"`, `"Q3"`, or `"Q4"` |

### Example Requests

### Get all historical ESG data for a US company

```bash
curl "https://eodhd.com/api/mp/investverte/esg/AAPL?api_token=YOUR_API_TOKEN"
```

### Get ESG data for a specific year and frequency

```bash
curl "https://eodhd.com/api/mp/investverte/esg/AAPL?year=2021&frequency=FY&api_token=YOUR_API_TOKEN"
```

### Get ESG data for a non-US company

```bash
curl "https://eodhd.com/api/mp/investverte/esg/000039.SZ?api_token=YOUR_API_TOKEN"
```

### Notes

- **Marketplace product**: Requires a separate Investverte marketplace subscription, not included in main EODHD plans.
- **Symbol format**: US companies use the bare ticker (e.g. `AAPL`, `MSFT`). Non-US companies include the exchange suffix (e.g. `000039.SZ`, `0439.HK`). Use the List Companies endpoint to get the correct symbol.
- **Data range**: Historical data can span over 10 years (e.g. 2012–2024), varying by company.
- **Quarterly vs annual scores**: Quarterly (Q1-Q4) scores may remain constant between annual updates; the FY score typically reflects updated analysis.
- **Score interpretation**: All scores (E, S, G, ESG) are numeric values typically in the 50-70 range. Higher scores indicate better performance.
- **Pillar scores**: `e` = Environmental, `s` = Social, `g` = Governance. The composite `esg` is derived from all three pillars.
- **Full time series**: Without `year`/`frequency` filters, the response includes 5 records per year (FY + Q1-Q4) across all available years — potentially 50+ records per company.

### HTTP Status Codes

| Status Code | Meaning | Description |
|-------------|---------|-------------|
| **200** | OK | Request succeeded. Data returned successfully. |
| **401** | Unauthorized | Invalid or missing API key. |
| **403** | Forbidden | No access to this marketplace product. |
| **404** | Not Found | Company symbol not found. |
| **429** | Too Many Requests | Rate limit exceeded (1,000 req/min or 100,000 calls/24h). |

### Error Response Format

When an error occurs, the API returns a JSON response with error details:

```json
{
  "error": "Error message description",
  "code": 403
}
```

### Handling Errors

**Python Example**:
```python
import requests

def make_api_request(url, params):
    try:
        response = requests.get(url, params=params)
        response.raise_for_status()  # Raises HTTPError for bad status codes
        return response.json()
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 401:
            print("Error: Invalid API key. Check your credentials.")
        elif e.response.status_code == 403:
            print("Error: No access to Investverte marketplace product.")
        elif e.response.status_code == 404:
            print("Error: Company symbol not found.")
        elif e.response.status_code == 429:
            print("Error: Rate limit exceeded. Please slow down your requests.")
        else:
            print(f"HTTP Error: {e}")
        return None
    except requests.exceptions.RequestException as e:
        print(f"Request failed: {e}")
        return None
```

**Best Practices**:
- Always check status codes before processing response data
- Implement exponential backoff for 429 errors
- Cache responses to reduce API calls — company ESG scores update infrequently
- Monitor your API usage in the user dashboard

---

## Investverte ESG View Country API

<a id="investverte-esg-view-country"></a>

### Endpoint Metadata

| Field | Value |
|---|---|
| Status | complete |
| Source | marketplace (Investverte API) |
| Docs | https://eodhd.com/financial-apis/esg-data-api |
| Provider | Investverte via EODHD Marketplace |
| Base URL | `https://eodhd.com/api/mp/investverte` |
| Path | `/country/{symbol}` |
| Method | GET |
| Auth | `api_token` query parameter |
| Slug | `investverte-esg-view-country` |
| Source File | `/Users/arnaurodon/Projects/University/Final Thesis/eodhd-claude-skills/skills/eodhd-api/references/endpoints/investverte-esg-view-country.md` |

### Purpose

Returns ESG ratings aggregated at the country level. Provides the mean and
median ESG scores for all companies in a given country, broken down by year
and reporting frequency (full year or quarterly). When called without filters,
returns the full historical time series across all available years and
frequencies.

**Use cases**:
- Track a country's ESG performance over time
- Compare ESG trends across countries
- Analyze quarterly vs annual ESG score fluctuations
- Research geographic ESG patterns for investment strategies
- Benchmark a company's ESG score against its country's average

### Inputs

### Path (required)

| Parameter | Type | Description |
|-----------|------|-------------|
| `symbol` | string | Country code from the List Countries endpoint (e.g. `US`, `GB`, `DE`, `JP`) |

### Query (required)

| Parameter | Type | Description |
|-----------|------|-------------|
| `api_token` | string | Your API key |

### Query (optional)

| Parameter | Type | Values | Description |
|-----------|------|--------|-------------|
| `year` | number | e.g. `2014`, `2021`, `2024` | Filter to a specific year |
| `frequency` | string | `FY`, `Q1`, `Q2`, `Q3`, `Q4` | Filter to a specific reporting frequency |

- `FY` = Full Year
- `Q1`..`Q4` = Quarterly periods
- When both `year` and `frequency` are provided, a single record is returned.
- When neither is provided, the full time series (all years, all frequencies) is returned.

### Outputs

JSON array of ESG rating objects. Each object contains:

| Field | Type | Description |
|-------|------|-------------|
| `symbol` | string | Country code (e.g. `"US"`) |
| `name` | string | Country name (e.g. `"United States of America"`) |
| `mean` | number | Mean ESG score across all companies in the country for the period |
| `median` | number | Median ESG score across all companies in the country for the period |
| `year` | integer | Year of the data point |
| `frequency` | string | Reporting frequency: `"FY"`, `"Q1"`, `"Q2"`, `"Q3"`, or `"Q4"` |

### Example Requests

### Get all historical ESG data for a country

```bash
curl "https://eodhd.com/api/mp/investverte/country/US?api_token=YOUR_API_TOKEN"
```

### Get ESG data for a specific year and frequency

```bash
curl "https://eodhd.com/api/mp/investverte/country/US?year=2021&frequency=FY&api_token=YOUR_API_TOKEN"
```

### Get ESG data for a specific year (all frequencies)

```bash
curl "https://eodhd.com/api/mp/investverte/country/GB?year=2022&api_token=YOUR_API_TOKEN"
```

### Notes

- **Marketplace product**: Requires a separate Investverte marketplace subscription, not included in main EODHD plans.
- **Data range**: Historical data spans from 2015 to the current year, with both annual (FY) and quarterly (Q1-Q4) breakdowns.
- **Country codes**: Use the two-letter codes from the List Countries endpoint (e.g. `US`, `GB`, `DE`, `JP`, `CN`).
- **Score interpretation**: ESG scores are numeric values (typically in the 50-70 range based on observed US data). Higher scores indicate better ESG performance.
- **Mean vs median**: The `mean` gives the average ESG score across all companies in the country; the `median` gives the middle value, which is less affected by outliers.
- **Full time series**: Without `year`/`frequency` filters, the response includes 5 records per year (FY + Q1-Q4) across all available years — potentially 50+ records.

### HTTP Status Codes

| Status Code | Meaning | Description |
|-------------|---------|-------------|
| **200** | OK | Request succeeded. Data returned successfully. |
| **401** | Unauthorized | Invalid or missing API key. |
| **403** | Forbidden | No access to this marketplace product. |
| **404** | Not Found | Country symbol not found. |
| **429** | Too Many Requests | Rate limit exceeded (1,000 req/min or 100,000 calls/24h). |

### Error Response Format

When an error occurs, the API returns a JSON response with error details:

```json
{
  "error": "Error message description",
  "code": 403
}
```

### Handling Errors

**Python Example**:
```python
import requests

def make_api_request(url, params):
    try:
        response = requests.get(url, params=params)
        response.raise_for_status()  # Raises HTTPError for bad status codes
        return response.json()
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 401:
            print("Error: Invalid API key. Check your credentials.")
        elif e.response.status_code == 403:
            print("Error: No access to Investverte marketplace product.")
        elif e.response.status_code == 404:
            print("Error: Country symbol not found.")
        elif e.response.status_code == 429:
            print("Error: Rate limit exceeded. Please slow down your requests.")
        else:
            print(f"HTTP Error: {e}")
        return None
    except requests.exceptions.RequestException as e:
        print(f"Request failed: {e}")
        return None
```

**Best Practices**:
- Always check status codes before processing response data
- Implement exponential backoff for 429 errors
- Cache responses to reduce API calls — country ESG scores update infrequently
- Monitor your API usage in the user dashboard

---

## Investverte ESG View Sector API

<a id="investverte-esg-view-sector"></a>

### Endpoint Metadata

| Field | Value |
|---|---|
| Status | complete |
| Source | marketplace (Investverte API) |
| Docs | https://eodhd.com/financial-apis/esg-data-api |
| Provider | Investverte via EODHD Marketplace |
| Base URL | `https://eodhd.com/api/mp/investverte` |
| Path | `/sector/{symbol}` |
| Method | GET |
| Auth | `api_token` query parameter |
| Slug | `investverte-esg-view-sector` |
| Source File | `/Users/arnaurodon/Projects/University/Final Thesis/eodhd-claude-skills/skills/eodhd-api/references/endpoints/investverte-esg-view-sector.md` |

### Purpose

Returns ESG score time series for a specific sector, along with the parent
industry group for comparison. The response provides arrays of ESG scores
aligned to a `years` array of time period labels (`YYYY-FY` or `YYYY-Q#`),
covering both annual and quarterly data from 2015 onwards.

**Use cases**:
- Track a sector's ESG score trend over time
- Compare a sector's ESG performance to its parent industry group
- Identify which periods have data gaps (null values)
- Research sector-level ESG patterns for investment strategies
- Benchmark a company's ESG score against its sector average

### Inputs

### Path (required)

| Parameter | Type | Description |
|-----------|------|-------------|
| `symbol` | string | Sector name from the List Sectors endpoint (e.g. `Airlines`, `Technology`, `Banking`). URL-encode names with special characters (e.g. `Aerospace%20%26%20Defense`). |

### Query (required)

| Parameter | Type | Description |
|-----------|------|-------------|
| `api_token` | string | Your API key |

### Outputs

JSON object with three top-level fields:

| Field | Type | Description |
|-------|------|-------------|
| `find` | boolean | `true` if the sector was found, `false` otherwise |
| `industry` | object | ESG score arrays keyed by sector/industry name |
| `years` | array of strings | Time period labels aligned to the score arrays |

### `industry` object

Contains one or more keys, each mapping to an array of numbers (or `null`).
The keys are **sub-industries** and **related industry groups** within the
queried sector. For example:

- Querying `Airlines` returns keys like `"Airlines"` and `"Transportation"`.
- Querying `Technology` returns sub-industry keys like `"Software—Infrastructure"`, `"Semiconductors"`, `"Electronic Components"`, etc.
- Querying `Aerospace & Defense` returns keys like `"Capital Goods"` and `"Scientific & Technical Instruments"`.

Each array has the same length as the `years` array. Values are:
- A number (ESG score) when data is available for that period.
- `null` when no data is available for that period.

### `years` array

Strings in the format `"YYYY-FY"` or `"YYYY-Q#"` where `#` is 1-4. Example entries:
- `"2015-FY"` — Full year 2015
- `"2015-Q1"` — First quarter 2015
- `"2024-Q4"` — Fourth quarter 2024

The array covers all periods from 2015 to the current year, with 5 entries per year (FY + Q1-Q4).

### Example Requests

```bash
curl "https://eodhd.com/api/mp/investverte/sector/Airlines?api_token=YOUR_API_TOKEN"
```

### URL-encoded sector name

```bash
curl "https://eodhd.com/api/mp/investverte/sector/Aerospace%20%26%20Defense?api_token=YOUR_API_TOKEN"
```

### Notes

- **Marketplace product**: Requires a separate Investverte marketplace subscription, not included in main EODHD plans.
- **Response format differs from other Investverte endpoints**: Unlike the View Company and View Country endpoints (which return arrays of flat records), this endpoint returns a structured object with parallel arrays.
- **Sub-industries**: The `industry` object keys are sub-industries and related groups within the queried sector. Simple sectors like `Airlines` may return the sector itself plus a parent group (e.g. `Transportation`). Broader sectors like `Technology` return many sub-industries (e.g. `Semiconductors`, `Software—Application`, etc.).
- **Null values**: `null` entries indicate no data is available for that time period. Quarterly data may have more nulls than annual (FY) data.
- **Score interpretation**: ESG scores are numeric values (typically in the 50-80 range). Higher scores indicate better ESG performance.
- **URL encoding**: Sector names containing spaces or special characters must be URL-encoded in the path (e.g. `Hotels%2C%20Restaurants%20%26%20Leisure`).
- **Data alignment**: To map scores to periods, zip the `industry[sector_name]` array with the `years` array — they are always the same length.

### HTTP Status Codes

| Status Code | Meaning | Description |
|-------------|---------|-------------|
| **200** | OK | Request succeeded. Data returned successfully. |
| **401** | Unauthorized | Invalid or missing API key. |
| **403** | Forbidden | No access to this marketplace product. |
| **404** | Not Found | Sector symbol not found. |
| **429** | Too Many Requests | Rate limit exceeded (1,000 req/min or 100,000 calls/24h). |

### Error Response Format

When an error occurs, the API returns a JSON response with error details:

```json
{
  "error": "Error message description",
  "code": 403
}
```

### Handling Errors

**Python Example**:
```python
import requests

def make_api_request(url, params):
    try:
        response = requests.get(url, params=params)
        response.raise_for_status()  # Raises HTTPError for bad status codes
        return response.json()
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 401:
            print("Error: Invalid API key. Check your credentials.")
        elif e.response.status_code == 403:
            print("Error: No access to Investverte marketplace product.")
        elif e.response.status_code == 404:
            print("Error: Sector not found.")
        elif e.response.status_code == 429:
            print("Error: Rate limit exceeded. Please slow down your requests.")
        else:
            print(f"HTTP Error: {e}")
        return None
    except requests.exceptions.RequestException as e:
        print(f"Request failed: {e}")
        return None
```

**Best Practices**:
- Always check status codes before processing response data
- Implement exponential backoff for 429 errors
- Cache responses to reduce API calls — sector ESG scores update infrequently
- Monitor your API usage in the user dashboard

---

## Live/Real-Time Price Data API

<a id="live-price-data"></a>

### Endpoint Metadata

| Field | Value |
|---|---|
| Status | complete |
| Source | financial-apis (Live Stock Prices API) |
| Docs | https://eodhd.com/financial-apis/live-realtime-stocks-api |
| Provider | EODHD |
| Base URL | https://eodhd.com/api |
| Path | /real-time/{SYMBOL} |
| Method | GET |
| Auth | api_token (query) |
| Slug | `live-price-data` |
| Source File | `/Users/arnaurodon/Projects/University/Final Thesis/eodhd-claude-skills/skills/eodhd-api/references/endpoints/live-price-data.md` |

### Purpose

Return real-time (delayed 15-20 minutes for most exchanges) quote data
for a symbol including last price, change, volume, and trading range.

### Inputs

| Parameter | Required | Type | Description |
|-----------|----------|------|-------------|
| api_token | Yes | string | EODHD API key |
| {SYMBOL} | Yes | string | Symbol with exchange suffix (e.g., AAPL.US) |
| fmt | No | string | Output format: 'csv' or 'json' (default csv) |
| s | No | string | Additional symbols for batch request (comma-separated) |
| ex | No | string | Set to `US` to fetch aggregated live data for all U.S. exchanges in a single request (consumes 100 API calls) |

### Outputs

Single quote object or array for batch requests:

```json
{
  "code": "AAPL",
  "timestamp": 1609459200,
  "gmtoffset": -18000,
  "open": 132.43,
  "high": 134.50,
  "low": 131.80,
  "close": 133.72,
  "volume": 98425000,
  "previousClose": 131.96,
  "change": 1.76,
  "change_p": 1.33
}
```

For batch requests with `s` parameter:
```json
[
  {"code": "AAPL", "close": 133.72, ...},
  {"code": "MSFT", "close": 222.42, ...}
]
```

### Example Requests

```bash
# Single symbol real-time quote
curl "https://eodhd.com/api/real-time/AAPL.US?api_token=demo&fmt=json"

# Batch request for multiple symbols
curl "https://eodhd.com/api/real-time/AAPL.US?s=MSFT.US,GOOGL.US&api_token=demo&fmt=json"

# Bulk request for all US exchanges (consumes 100 API calls)
curl "https://eodhd.com/api/real-time/AAPL.US?ex=US&api_token=demo&fmt=json"

# Using the helper client
python eodhd_client.py --endpoint real-time --symbol AAPL.US
```

### Notes

- Data is delayed 15-20 minutes for most exchanges (real-time requires premium)
- `change` is absolute price change from previous close
- `change_p` is percentage change from previous close
- Timestamp is Unix epoch in seconds
- During market hours, data updates frequently; after hours shows last traded
- Batch requests support up to 15-20 symbols per call
- Works for stocks, ETFs, indices, forex, and crypto (exchange-dependent)
- API call consumption: 1 call per ticker in the request (e.g., 10 symbols = 10 calls)
- **Premarket data**: This API only works during trading hours. For pre-market and after-hours data, use the WebSockets API.
- **"Close" is the live price**: In this API, the `close` field represents the current live price during market hours.
- **Bulk live (real-time) API**: Add `ex=US` to the URL to fetch aggregated live data for all U.S. exchanges in a single request. Only available for US exchanges. Consumes **100 API calls** per request. Available in: All-In-One, EOD Historical Data: All World, EOD+Intraday: All World Extended, and Free plans.
- **Mutual funds live data**: Live data is not available for mutual funds. Mutual fund prices do not change during the day (see OHLC data for mutual funds). The live API's "current" price for mutual funds is updated at end of day — same as EOD data.

### HTTP Status Codes

The API returns standard HTTP status codes to indicate success or failure:

| Status Code | Meaning | Description |
|-------------|---------|-------------|
| **200** | OK | Request succeeded. Data returned successfully. |
| **402** | Payment Required | API limit used up. Upgrade plan or wait for limit reset. |
| **403** | Unauthorized | Invalid API key. Check your `api_token` parameter. |
| **429** | Too Many Requests | Exceeded rate limit (requests per minute). Slow down requests. |

### Error Response Format

When an error occurs, the API returns a JSON response with error details:

```json
{
  "error": "Error message description",
  "code": 403
}
```

### Handling Errors

**Python Example**:
```python
import requests

def make_api_request(url, params):
    try:
        response = requests.get(url, params=params)
        response.raise_for_status()  # Raises HTTPError for bad status codes
        return response.json()
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 402:
            print("Error: API limit exceeded. Please upgrade your plan.")
        elif e.response.status_code == 403:
            print("Error: Invalid API key. Check your credentials.")
        elif e.response.status_code == 429:
            print("Error: Rate limit exceeded. Please slow down your requests.")
        else:
            print(f"HTTP Error: {e}")
        return None
    except requests.exceptions.RequestException as e:
        print(f"Request failed: {e}")
        return None
```

**Best Practices**:
- Always check status codes before processing response data
- Implement exponential backoff for 429 errors
- Cache responses to reduce API calls
- Monitor your API usage in the user dashboard

---

## Macro Indicator API

<a id="macro-indicator"></a>

### Endpoint Metadata

| Field | Value |
|---|---|
| Status | complete |
| Source | financial-apis (Macroeconomics Data API) |
| Docs | https://eodhd.com/financial-apis/macroeconomics-data-and-macro-indicators-api |
| Provider | EODHD |
| Base URL | https://eodhd.com/api |
| Path | /macro-indicator/{COUNTRY} |
| Method | GET |
| Auth | api_token (query) |
| Slug | `macro-indicator` |
| Source File | `/Users/arnaurodon/Projects/University/Final Thesis/eodhd-claude-skills/skills/eodhd-api/references/endpoints/macro-indicator.md` |

### Purpose

Retrieve macroeconomic indicators for countries including GDP, inflation, unemployment,
interest rates, trade balance, and other economic metrics from sources like the World Bank.

### Inputs

| Parameter | Required | Type | Description |
|-----------|----------|------|-------------|
| api_token | Yes | string | EODHD API key |
| {COUNTRY} | Yes | string | ISO 3166-1 alpha-3 country code (e.g., USA, GBR, DEU, JPN, CHN) |
| indicator | No | string | Specific indicator code (see list below) |
| fmt | No | string | Output format: 'csv' or 'json' (default csv) |

### Outputs

Array of time-series data points:

```json
[
  {
    "CountryCode": "USA",
    "CountryName": "United States",
    "Indicator": "gdp_current_usd",
    "Date": "2023-12-31",
    "Period": "2023",
    "Value": 25462700000000
  }
]
```

When no specific indicator is provided, returns all available indicators as an object with arrays per indicator:
```json
{
  "CountryCode": "USA",
  "CountryName": "United States",
  "gdp_current_usd": [
    {"CountryCode": "USA", "Date": "2023-12-31", "Period": "2023", "Value": 25462700000000},
    {"CountryCode": "USA", "Date": "2022-12-31", "Period": "2022", "Value": 25744100000000}
  ],
  "inflation_consumer_prices_annual": [
    {"CountryCode": "USA", "Date": "2023-12-31", "Period": "2023", "Value": 4.1178}
  ]
}
```

### Example Requests

```bash
# All macro indicators for USA
curl "https://eodhd.com/api/macro-indicator/USA?api_token=demo&fmt=json"

# Specific indicator: GDP growth
curl "https://eodhd.com/api/macro-indicator/USA?api_token=demo&fmt=json&indicator=gdp_growth_annual"

# Inflation for Germany
curl "https://eodhd.com/api/macro-indicator/DEU?api_token=demo&fmt=json&indicator=inflation_consumer_prices_annual"

# Using the helper client
python eodhd_client.py --endpoint macro-indicator --symbol USA --indicator gdp_current_usd
```

### Notes

- Country codes use ISO 3166-1 alpha-3 format (USA, GBR, DEU, JPN, CHN, etc.)
- Data is typically annual, with varying historical depth by indicator
- Some indicators may have gaps or missing years
- Values are in the units specified by the indicator (%, USD, count, etc.)
- Data sourced from World Bank and other official sources
- API call consumption: 1 call per request
- **Data sources**: EODHD uses more than 5 sources for macroeconomic data and compiles it internally. The primary source is the [World Bank](https://www.worldbank.org/en/home), supplemented by government news and publications.
- **Fertility indicator**: The `fertility_rate` indicator represents the **birth rate** (total fertility rate per woman).

### HTTP Status Codes

The API returns standard HTTP status codes to indicate success or failure:

| Status Code | Meaning | Description |
|-------------|---------|-------------|
| **200** | OK | Request succeeded. Data returned successfully. |
| **402** | Payment Required | API limit used up. Upgrade plan or wait for limit reset. |
| **403** | Unauthorized | Invalid API key. Check your `api_token` parameter. |
| **429** | Too Many Requests | Exceeded rate limit (requests per minute). Slow down requests. |

### Error Response Format

When an error occurs, the API returns a JSON response with error details:

```json
{
  "error": "Error message description",
  "code": 403
}
```

### Handling Errors

**Python Example**:
```python
import requests

def make_api_request(url, params):
    try:
        response = requests.get(url, params=params)
        response.raise_for_status()  # Raises HTTPError for bad status codes
        return response.json()
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 402:
            print("Error: API limit exceeded. Please upgrade your plan.")
        elif e.response.status_code == 403:
            print("Error: Invalid API key. Check your credentials.")
        elif e.response.status_code == 429:
            print("Error: Rate limit exceeded. Please slow down your requests.")
        else:
            print(f"HTTP Error: {e}")
        return None
    except requests.exceptions.RequestException as e:
        print(f"Request failed: {e}")
        return None
```

**Best Practices**:
- Always check status codes before processing response data
- Implement exponential backoff for 429 errors
- Cache responses to reduce API calls
- Monitor your API usage in the user dashboard

---

## Marketplace Tick Data API (US Stock Market)

<a id="marketplace-tick-data"></a>

### Endpoint Metadata

| Field | Value |
|---|---|
| Status | complete |
| Source | marketplace (Unicorn Bay) |
| Provider | Unicorn Bay via EODHD Marketplace |
| Base URL | `https://eodhd.com/api/mp/unicornbay/tickdata` |
| Path | `/ticks` |
| Method | GET |
| Auth | `api_token` query parameter |
| Slug | `marketplace-tick-data` |
| Source File | `/Users/arnaurodon/Projects/University/Final Thesis/eodhd-claude-skills/skills/eodhd-api/references/endpoints/marketplace-tick-data.md` |

### Purpose

Provides comprehensive **tick-by-tick** (trade-level) data for US stock market tickers with millisecond-precision timestamps, prices, and volumes. Each tick record represents an individual trade execution.

**Use cases**:
- High-frequency trading analysis
- Backtesting strategies at trade-level granularity
- Market microstructure research
- Order flow and liquidity analysis
- Spread and slippage studies

### Inputs

### Required

| Parameter | Type | Constraints | Description |
|-----------|------|-------------|-------------|
| `api_token` | string | — | Your API key |
| `s` | string | max 30 chars | Ticker symbol (e.g., `AAPL`, `MSFT`, `GOOGL`) |

### Optional

| Parameter | Type | Constraints | Default | Description |
|-----------|------|-------------|---------|-------------|
| `from` | integer | max 4294967295 | Yesterday start of day | Start timestamp (Unix timestamp in **seconds**) |
| `to` | integer | max 4294967295 | Yesterday end of day | End timestamp (Unix timestamp in **seconds**) |
| `limit` | integer | 1–10000 | All ticks in range | Maximum number of ticks to return. If 0 or omitted, returns all ticks in the time range |

### Outputs

The response contains **columnar arrays** — each field is an array of values aligned by index (index 0 across all fields = first tick, index 1 = second tick, etc.):

```json
{
  "ts": [1694077201147, 1694077206102, 1694077206102],
  "price": [177.88, 177.95, 177.97],
  "shares": [1, 50, 50],
  "mkt": ["K", "Q", "Q"],
  "seq": [1434370, 1436393, 1436394],
  "sl": ["@ TI", "@ TI", "@ TI"],
  "sub_mkt": ["", "", ""]
}
```

### Response Field Definitions

| Field | Type | Description |
|-------|------|-------------|
| `ts` | integer[] | Timestamp in **milliseconds** (Unix epoch). Note: `from`/`to` params are in seconds, but response timestamps are in milliseconds |
| `price` | float[] | Trade execution price |
| `shares` | integer[] | Number of shares traded in this tick |
| `mkt` | string[] | Market identifier code (exchange where the trade executed) |
| `seq` | integer[] | Sequence number (unique ordering of trades within the day) |
| `sl` | string[] | Source/location identifier |
| `sub_mkt` | string[] | Sub-market identifier (may be empty) |

### Market Identifier Codes (`mkt`)

Common values for the `mkt` field:

| Code | Exchange |
|------|----------|
| `Q` | NASDAQ |
| `K` | NYSE (Arca) |
| `P` | NYSE Arca |
| `N` | NYSE |
| `Z` | BATS |
| `V` | IEX |

### Example Requests

### Get 10 ticks for AAPL in a time window

```bash
curl "https://eodhd.com/api/mp/unicornbay/tickdata/ticks?s=AAPL&from=1694077200&to=1694080800&limit=10&api_token=YOUR_API_TOKEN"
```

### Demo access

```bash
curl "https://eodhd.com/api/mp/unicornbay/tickdata/ticks?s=AAPL&from=1694077200&to=1694080800&limit=10&api_token=demo"
```

### Python (requests)

```python
import requests
from datetime import datetime, timedelta

# Define time range (e.g., yesterday 9:30 AM to 10:00 AM ET)
url = "https://eodhd.com/api/mp/unicornbay/tickdata/ticks"
params = {
    "s": "AAPL",
    "from": 1694077200,    # Unix timestamp in seconds
    "to": 1694080800,      # Unix timestamp in seconds
    "limit": 100,
    "api_token": "YOUR_API_TOKEN"
}

response = requests.get(url, params=params)
data = response.json()

# Data is columnar — iterate by index
for i in range(len(data["ts"])):
    ts_ms = data["ts"][i]
    price = data["price"][i]
    shares = data["shares"][i]
    mkt = data["mkt"][i]
    ts_str = datetime.fromtimestamp(ts_ms / 1000).strftime("%H:%M:%S.%f")[:-3]
    print(f"{ts_str} | ${price:.2f} | {shares:>5} shares | {mkt}")
```

**Output example**:
```
09:00:01.147 | $177.88 |     1 shares | K
09:00:06.102 | $177.95 |    50 shares | Q
09:00:06.102 | $177.97 |    50 shares | Q
09:00:06.102 | $177.96 |    50 shares | P
09:00:06.102 | $177.97 |    50 shares | P
09:00:06.102 | $177.97 |     6 shares | P
09:00:06.996 | $177.98 |    10 shares | Q
09:00:06.996 | $177.98 |    50 shares | Q
09:00:06.996 | $177.99 |    40 shares | Q
09:00:06.996 | $177.98 |    50 shares | P
```

### Notes

- **Columnar response format**: Unlike most EODHD endpoints that return arrays of objects, this endpoint returns an object of arrays (columnar). All arrays are the same length and aligned by index.
- **Timestamp units differ**: `from`/`to` parameters use **seconds**, but response `ts` field is in **milliseconds**. Divide `ts` by 1000 to convert to seconds.
- **US stocks only**: Covers thousands of US stock tickers (NYSE, NASDAQ, etc.)
- **Demo tickers**: Test with `api_token=demo` using AAPL, MSFT, GOOGL, and other popular US stocks.
- **Marketplace rate limits**: The 24-hour call limit is counted separately from your main EODHD plan quota.
- **Default time range**: If `from`/`to` are omitted, defaults to yesterday's full trading day.
- **Coverage**: Historical tick data with millisecond precision. Each tick = one individual trade execution.

### HTTP Status Codes

| Status Code | Meaning | Description |
|-------------|---------|-------------|
| **200** | OK | Request succeeded. Tick data returned. |
| **401** | Unauthorized | Invalid or missing API key |
| **403** | Forbidden | No access to this marketplace product |
| **422** | Unprocessable Entity | Invalid parameters (e.g., bad ticker, invalid timestamp) |
| **429** | Too Many Requests | Rate limit exceeded (1,000 req/min or 100,000 calls/24h) |

---

## News Word Weights API

<a id="news-word-weights"></a>

### Endpoint Metadata

| Field | Value |
|---|---|
| Status | complete |
| Source | financial-apis (Financial News Feed and Stock News Sentiment data API) |
| Docs | https://eodhd.com/financial-apis/financial-news-api |
| Provider | EODHD |
| Base URL | https://eodhd.com/api |
| Path | /news-word-weights |
| Method | GET |
| Auth | api_token (query) |
| Slug | `news-word-weights` |
| Source File | `/Users/arnaurodon/Projects/University/Final Thesis/eodhd-claude-skills/skills/eodhd-api/references/endpoints/news-word-weights.md` |

### Purpose

Provides a weighted list of the most relevant words found in financial news articles about a specific
stock ticker over a defined date range. Each word is scored based on its frequency and significance
across the processed news. Useful for trend analysis, NLP input, thematic clustering, and identifying
key topics driving market narratives.

**Note**: This endpoint uses AI to process hundreds or thousands of articles, which may result in
longer response times. If you encounter timeouts, narrow the date range or focus on specific tickers.

**API Call Consumption**: 5 API calls per request + 5 API calls per ticker.

### Inputs

| Parameter | Required | Type | Description |
|-----------|----------|------|-------------|
| s | Yes | string | Ticker symbol to analyze (e.g., AAPL.US) |
| filter[date_from] | No | string (YYYY-MM-DD) | Start date for filtering news |
| filter[date_to] | No | string (YYYY-MM-DD) | End date for filtering news |
| page[limit] | No | integer | Number of top words to return |
| api_token | Yes | string | Your API access token |
| fmt | No | string | Response format: json (default) |

### Outputs

```json
{
  "data": {
    "appl": 0.01933,
    "tariff": 0.01893,
    "stock": 0.01889,
    "trump": 0.01114,
    "companies": 0.00989,
    "market": 0.00927,
    "china": 0.00792,
    "trade": 0.00719,
    "ai": 0.00607,
    "price": 0.00579
  },
  "meta": {
    "news_processed": 300,
    "news_found": 5860
  },
  "links": {
    "next": null
  }
}
```

### Field Descriptions

| Field | Type | Description |
|-------|------|-------------|
| data | object | Key-value pairs of words and their weights |
| meta.news_found | integer | Total number of articles matched |
| meta.news_processed | integer | Number of articles successfully processed |
| links.next | string or null | URL to next page of results (if available) |

### Word Weight Interpretation

- Weights are relative scores (typically 0.001 to 0.02 range)
- Higher weights indicate more frequent and significant terms
- Words are stemmed/normalized (e.g., "apple" → "appl")
- Stop words and common terms are filtered out

### Example Requests

```bash
# Top 10 words for AAPL over a week
curl "https://eodhd.com/api/news-word-weights?s=AAPL.US&filter[date_from]=2025-04-08&filter[date_to]=2025-04-16&page[limit]=10&api_token=demo&fmt=json"

# Top 20 words for TSLA over a month
curl "https://eodhd.com/api/news-word-weights?s=TSLA.US&filter[date_from]=2025-01-01&filter[date_to]=2025-01-31&page[limit]=20&api_token=demo&fmt=json"

# Top 50 words for crypto
curl "https://eodhd.com/api/news-word-weights?s=BTC-USD.CC&filter[date_from]=2025-01-01&filter[date_to]=2025-01-15&page[limit]=50&api_token=demo&fmt=json"
```

### Notes

- **Performance**: AI processing may cause longer response times; narrow date ranges for faster responses
- **Word Stemming**: Words are normalized (e.g., "companies" → "compani", "trading" → "trade")
- **Coverage**: `news_found` vs `news_processed` indicates processing coverage
- Weights are relative within a response; compare rankings, not absolute values
- Empty periods or tickers with no news will return minimal data
- Useful for building word clouds, topic models, and sentiment dashboards
- Available in: Standalone package, All-In-One, EOD Historical Data, Fundamentals Data Feed, Free plan

### HTTP Status Codes

The API returns standard HTTP status codes to indicate success or failure:

| Status Code | Meaning | Description |
|-------------|---------|-------------|
| **200** | OK | Request succeeded. Data returned successfully. |
| **402** | Payment Required | API limit used up. Upgrade plan or wait for limit reset. |
| **403** | Unauthorized | Invalid API key. Check your `api_token` parameter. |
| **429** | Too Many Requests | Exceeded rate limit (requests per minute). Slow down requests. |

### Error Response Format

When an error occurs, the API returns a JSON response with error details:

```json
{
  "error": "Error message description",
  "code": 403
}
```

### Handling Errors

**Python Example**:
```python
import requests

def make_api_request(url, params):
    try:
        response = requests.get(url, params=params)
        response.raise_for_status()  # Raises HTTPError for bad status codes
        return response.json()
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 402:
            print("Error: API limit exceeded. Please upgrade your plan.")
        elif e.response.status_code == 403:
            print("Error: Invalid API key. Check your credentials.")
        elif e.response.status_code == 429:
            print("Error: Rate limit exceeded. Please slow down your requests.")
        else:
            print(f"HTTP Error: {e}")
        return None
    except requests.exceptions.RequestException as e:
        print(f"Request failed: {e}")
        return None
```

**Best Practices**:
- Always check status codes before processing response data
- Implement exponential backoff for 429 errors
- Cache responses to reduce API calls
- Monitor your API usage in the user dashboard

---

## Praams Bank Balance Sheet by ISIN API

<a id="praams-bank-balance-sheet-by-isin"></a>

### Endpoint Metadata

| Field | Value |
|---|---|
| Status | complete |
| Source | marketplace (PRAAMS API) |
| Docs | https://eodhd.com/financial-apis/equity-risk-return-scoring-api |
| Provider | PRAAMS via EODHD Marketplace |
| Base URL | `https://eodhd.com/api/mp/praams` |
| Path | `/bank/balance_sheet/isin/{isin}` |
| Method | GET |
| Auth | `api_token` query parameter |
| Slug | `praams-bank-balance-sheet-by-isin` |
| Source File | `/Users/arnaurodon/Projects/University/Final Thesis/eodhd-claude-skills/skills/eodhd-api/references/endpoints/praams-bank-balance-sheet-by-isin.md` |

### Purpose

Returns the balance sheet data for a bank based on the specified ISIN code.
The response provides both annual (FY) and quarterly balance sheet data formatted
specifically for bank analysis, using a unique methodology created and validated
by CFA charterholders with 20+ years of experience in bank analysis.

This is the ISIN-based variant of the Bank Balance Sheet API. It returns the
same data structure as the ticker-based endpoint but accepts an ISIN identifier
instead. The ISIN is resolved to the corresponding bank and the same balance
sheet data is returned.

Unlike standard corporate balance sheets, this endpoint presents bank financials
in a format that reflects the business specifics of banking institutions,
including key banking metrics such as loans (gross and net with provisions),
deposits, interest-earning assets, interest-bearing liabilities, securities
REPO positions, and investment portfolio.

**Use cases**:
- Analyze bank balance sheets using ISIN identifiers for international lookups
- Track loan book growth and provisioning adequacy (gross loans, provisions, net loans)
- Monitor deposit base and funding stability
- Evaluate interest-earning assets vs interest-bearing liabilities (NIM analysis)
- Assess securities REPO positions (both asset and liability side)
- Track investment portfolio size and composition
- Analyze capital adequacy via total equity trends
- Monitor debt structure (short-term vs long-term)
- Build financial models for banking institutions

### Inputs

### Path (required)

| Parameter | Type | Description |
|-----------|------|-------------|
| `isin` | string | ISIN code of the bank (e.g. `US46625H1005`, `US0605051046`, `US9497461015`) |

### Query (required)

| Parameter | Type | Description |
|-----------|------|-------------|
| `api_token` | string | Your API key (or `demo` for demo ISINs) |

### Outputs

JSON object with top-level envelope:

| Field | Type | Description |
|-------|------|-------------|
| `success` | boolean | `true` if request succeeded |
| `message` | string | Status message (empty on success) |
| `errors` | array | Error objects with `code` and `description` (empty on success) |
| `items` | array | Array of balance sheet records (annual and quarterly) |

> **Note**: The response uses `items` (plural), not `item` (singular) as in the PRAAMS equity/bond endpoints.

### `items[]` record fields

Each record in the `items` array represents one reporting period. All monetary values are in the bank's reporting currency (typically USD).

#### Period identification

| Field | Type | Description |
|-------|------|-------------|
| `date` | string | Period end date in ISO 8601 format (e.g. `"2024-12-31T00:00:00"`) |
| `period` | string | Period identifier: `"FY"` for full year, `"Q1"`–`"Q4"` for quarters |
| `isQuarter` | boolean | `true` for quarterly data, `false` for annual data |

#### Loan book

| Field | Type | Description |
|-------|------|-------------|
| `loansGross` | number \| null | Gross loans before provisions. May be absent in some older quarterly records. |
| `loanProvisions` | number \| null | Loan loss provisions (allowance for credit losses). May be absent in some older quarterly records. |
| `netLoan` | number \| null | Net loans after provisions (`loansGross - loanProvisions`). May be absent in some older quarterly records. |

#### Cash and interbank

| Field | Type | Description |
|-------|------|-------------|
| `cashAndEquivalents` | number \| null | Cash and cash equivalents. May be absent in some older quarterly records. |
| `depositsWithBanksNet` | number \| null | Net deposits with other banks. May be absent in some older quarterly records. |

#### Securities and investments

| Field | Type | Description |
|-------|------|-------------|
| `securitiesRepoAssets` | number \| null | Securities purchased under agreements to resell (repo assets). May be absent in some older quarterly records. |
| `longTermInvestments` | number | Long-term investments |
| `investmentPortfolio` | number | Investment portfolio (same value as `longTermInvestments`) |

#### Total assets

| Field | Type | Description |
|-------|------|-------------|
| `totalAssets` | number | Total assets |
| `receivables` | number | Receivables |
| `otherAssets` | number | Other assets (balancing item; may be negative) |

#### Liabilities — deposits and funding

| Field | Type | Description |
|-------|------|-------------|
| `deposits` | number \| null | Customer deposits. May be absent in some older quarterly records. |
| `securitiesRepoEquity` | number \| null | Securities sold under agreements to repurchase (repo liabilities). May be absent in some older quarterly records. |
| `tradingLiabilities` | number \| null | Trading liabilities. May be absent in some older quarterly records. |
| `securityLiabilities` | number \| null | Security liabilities (same value as `tradingLiabilities`). May be absent in some older quarterly records. |
| `payables` | number \| null | Payables. May be absent in some older quarterly records. |

#### Liabilities — debt

| Field | Type | Description |
|-------|------|-------------|
| `shortTermDebt` | number | Short-term debt |
| `longTermDebt` | number | Long-term debt |

#### Equity and totals

| Field | Type | Description |
|-------|------|-------------|
| `totalEquity` | number | Total shareholders' equity |
| `totalEquityAndLiabilities` | number | Total equity and liabilities (should equal `totalAssets`) |
| `otherLiabilities` | number | Other liabilities (balancing item; may be negative) |

#### Analytical aggregates

| Field | Type | Description |
|-------|------|-------------|
| `interestEarningAssets` | number | Total interest-earning assets |
| `interestBearingLiabilities` | number | Total interest-bearing liabilities |

### Example Requests

```bash
curl "https://eodhd.com/api/mp/praams/bank/balance_sheet/isin/US46625H1005?api_token=YOUR_API_TOKEN"
```

### Demo access

```bash
curl "https://eodhd.com/api/mp/praams/bank/balance_sheet/isin/US46625H1005?api_token=demo"
```

### Notes

- **Marketplace product**: Requires a separate PRAAMS Bank Financials marketplace subscription, not included in main EODHD plans.
- **ISIN-based variant**: This endpoint returns identical data to the ticker-based endpoint (`/bank/balance_sheet/ticker/{ticker}`) but accepts an ISIN code instead. For example, `US46625H1005` resolves to the same data as ticker `JPM`.
- **Bank-specific format**: Unlike standard corporate balance sheets, this endpoint uses a banking-specific methodology. Key banking metrics include Loans (gross/net with provisions), Deposits, Securities REPO (assets and liabilities), Investment Portfolio, Interest-Earning Assets, and Interest-Bearing Liabilities.
- **Demo ISINs**: `US46625H1005` (JPMorgan Chase), `US0605051046` (Bank of America), and `US9497461015` (Wells Fargo) are available with `api_token=demo`.
- **Coverage**: All regional and global banks and banking financial institutions, including banking conglomerates from North America, Europe, UK, and Asia.
- **Mixed annual and quarterly data**: The `items` array contains both FY (annual) and Q1–Q4 (quarterly) records. Use `isQuarter` or `period` to filter.
- **Record ordering**: Records are returned with annual (FY) records first, followed by quarterly records. Within each group, records are ordered chronologically by `date`.
- **Incomplete older quarterly records**: Some older quarterly records (particularly Q4 2020, Q4 2021) contain significantly fewer fields — typically only `longTermInvestments`, `investmentPortfolio`, `totalAssets`, `receivables`, `otherAssets`, `shortTermDebt`, `longTermDebt`, `totalEquity`, `totalEquityAndLiabilities`, `otherLiabilities`, `interestEarningAssets`, and `interestBearingLiabilities`. Fields like `loansGross`, `netLoan`, `deposits`, `cashAndEquivalents`, `depositsWithBanksNet`, `securitiesRepoAssets`, `tradingLiabilities`, `securitiesRepoEquity`, and `payables` are absent in these records.
- **Balancing items**: `otherAssets` and `otherLiabilities` serve as balancing items and may be negative. In older quarterly records with fewer breakdowns, these values can be very large as they absorb all unbroken-out items.
- **Duplicate fields**: `investmentPortfolio` always equals `longTermInvestments`. `securityLiabilities` always equals `tradingLiabilities`. Both pairs are provided for convenience.
- **Balance sheet identity**: `totalAssets` should equal `totalEquityAndLiabilities` in each record.
- **Key metric definitions**:
  - **Net Loans** = Gross Loans − Loan Provisions
  - **Interest-Earning Assets** = assets that generate interest income (loans, investments, interbank deposits, repo assets)
  - **Interest-Bearing Liabilities** = liabilities that incur interest expense (deposits, debt, repo liabilities)
  - **NIM proxy**: Use `interestEarningAssets` and `interestBearingLiabilities` together with income statement data to compute net interest margin
- **Currency**: All monetary values are in the bank's reporting currency (USD for US banks).
- **Related endpoints**: Use the Bank Balance Sheet by Ticker endpoint for ticker-based lookups (see praams-bank-balance-sheet-by-ticker.md). Use the Bank Income Statement endpoints for complementary income statement data.

### HTTP Status Codes

| Status Code | Meaning | Description |
|-------------|---------|-------------|
| **200** | OK | Request succeeded. Data returned successfully. |
| **401** | Unauthorized | Invalid or missing API key. |
| **415** | Wrong Token | Token format is invalid. |
| **420** | Operation Cancelled | Request was cancelled. |
| **430** | Data Not Found | ISIN not found in PRAAMS bank database. |

### Error Response Format

When an error occurs, the API returns a JSON response:

```json
{
  "success": false,
  "message": "Error description",
  "errors": [
    {
      "code": "ERROR_CODE",
      "description": "Detailed error description"
    }
  ],
  "items": null
}
```

### Handling Errors

**Python Example**:
```python
import requests

def make_api_request(url, params):
    try:
        response = requests.get(url, params=params)
        response.raise_for_status()
        data = response.json()
        if not data.get("success"):
            errors = data.get("errors", [])
            for err in errors:
                print(f"API Error [{err.get('code')}]: {err.get('description')}")
            return None
        return data
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 401:
            print("Error: Invalid API key. Check your credentials.")
        elif e.response.status_code == 415:
            print("Error: Wrong token format.")
        elif e.response.status_code == 430:
            print("Error: ISIN not found in PRAAMS bank database.")
        else:
            print(f"HTTP Error: {e}")
        return None
    except requests.exceptions.RequestException as e:
        print(f"Request failed: {e}")
        return None
```

**Best Practices**:
- Always check `success` field in the response before processing `items`
- Implement exponential backoff for rate limit errors
- Cache responses to reduce API calls — bank financials update quarterly
- Use `isQuarter` to separate annual and quarterly data for analysis
- Monitor your API usage in the user dashboard

---

## Praams Bank Balance Sheet by Ticker API

<a id="praams-bank-balance-sheet-by-ticker"></a>

### Endpoint Metadata

| Field | Value |
|---|---|
| Status | complete |
| Source | marketplace (PRAAMS API) |
| Docs | https://eodhd.com/financial-apis/equity-risk-return-scoring-api |
| Provider | PRAAMS via EODHD Marketplace |
| Base URL | `https://eodhd.com/api/mp/praams` |
| Path | `/bank/balance_sheet/ticker/{ticker}` |
| Method | GET |
| Auth | `api_token` query parameter |
| Slug | `praams-bank-balance-sheet-by-ticker` |
| Source File | `/Users/arnaurodon/Projects/University/Final Thesis/eodhd-claude-skills/skills/eodhd-api/references/endpoints/praams-bank-balance-sheet-by-ticker.md` |

### Purpose

Returns the balance sheet data for a bank based on the specified ticker symbol.
The response provides both annual (FY) and quarterly balance sheet data formatted
specifically for bank analysis, using a unique methodology created and validated
by CFA charterholders with 20+ years of experience in bank analysis.

Unlike standard corporate balance sheets, this endpoint presents bank financials
in a format that reflects the business specifics of banking institutions,
including key banking metrics such as loans (gross and net with provisions),
deposits, interest-earning assets, interest-bearing liabilities, securities
REPO positions, and investment portfolio.

**Use cases**:
- Analyze bank balance sheets in a proper banking format (not corporate format)
- Track loan book growth and provisioning adequacy (gross loans, provisions, net loans)
- Monitor deposit base and funding stability
- Evaluate interest-earning assets vs interest-bearing liabilities (NIM analysis)
- Assess securities REPO positions (both asset and liability side)
- Track investment portfolio size and composition
- Analyze capital adequacy via total equity trends
- Monitor debt structure (short-term vs long-term)
- Build financial models for banking institutions

### Inputs

### Path (required)

| Parameter | Type | Description |
|-----------|------|-------------|
| `ticker` | string | Ticker symbol for the bank (e.g. `JPM`, `BAC`, `WFC`) |

### Query (required)

| Parameter | Type | Description |
|-----------|------|-------------|
| `api_token` | string | Your API key (or `demo` for demo tickers) |

### Outputs

JSON object with top-level envelope:

| Field | Type | Description |
|-------|------|-------------|
| `success` | boolean | `true` if request succeeded |
| `message` | string | Status message (empty on success) |
| `errors` | array | Error objects with `code` and `description` (empty on success) |
| `items` | array | Array of balance sheet records (annual and quarterly) |

> **Note**: The response uses `items` (plural), not `item` (singular) as in the PRAAMS equity/bond endpoints.

### `items[]` record fields

Each record in the `items` array represents one reporting period. All monetary values are in the bank's reporting currency (typically USD).

#### Period identification

| Field | Type | Description |
|-------|------|-------------|
| `date` | string | Period end date in ISO 8601 format (e.g. `"2024-12-31T00:00:00"`) |
| `period` | string | Period identifier: `"FY"` for full year, `"Q1"`–`"Q4"` for quarters |
| `isQuarter` | boolean | `true` for quarterly data, `false` for annual data |

#### Loan book

| Field | Type | Description |
|-------|------|-------------|
| `loansGross` | number \| null | Gross loans before provisions. May be absent in some older quarterly records. |
| `loanProvisions` | number \| null | Loan loss provisions (allowance for credit losses). May be absent in some older quarterly records. |
| `netLoan` | number \| null | Net loans after provisions (`loansGross - loanProvisions`). May be absent in some older quarterly records. |

#### Cash and interbank

| Field | Type | Description |
|-------|------|-------------|
| `cashAndEquivalents` | number \| null | Cash and cash equivalents. May be absent in some older quarterly records. |
| `depositsWithBanksNet` | number \| null | Net deposits with other banks. May be absent in some older quarterly records. |

#### Securities and investments

| Field | Type | Description |
|-------|------|-------------|
| `securitiesRepoAssets` | number \| null | Securities purchased under agreements to resell (repo assets). May be absent in some older quarterly records. |
| `longTermInvestments` | number | Long-term investments |
| `investmentPortfolio` | number | Investment portfolio (same value as `longTermInvestments`) |

#### Total assets

| Field | Type | Description |
|-------|------|-------------|
| `totalAssets` | number | Total assets |
| `receivables` | number | Receivables |
| `otherAssets` | number | Other assets (balancing item; may be negative) |

#### Liabilities — deposits and funding

| Field | Type | Description |
|-------|------|-------------|
| `deposits` | number \| null | Customer deposits. May be absent in some older quarterly records. |
| `securitiesRepoEquity` | number \| null | Securities sold under agreements to repurchase (repo liabilities). May be absent in some older quarterly records. |
| `tradingLiabilities` | number \| null | Trading liabilities. May be absent in some older quarterly records. |
| `securityLiabilities` | number \| null | Security liabilities (same value as `tradingLiabilities`). May be absent in some older quarterly records. |
| `payables` | number \| null | Payables. May be absent in some older quarterly records. |

#### Liabilities — debt

| Field | Type | Description |
|-------|------|-------------|
| `shortTermDebt` | number | Short-term debt |
| `longTermDebt` | number | Long-term debt |

#### Equity and totals

| Field | Type | Description |
|-------|------|-------------|
| `totalEquity` | number | Total shareholders' equity |
| `totalEquityAndLiabilities` | number | Total equity and liabilities (should equal `totalAssets`) |
| `otherLiabilities` | number | Other liabilities (balancing item; may be negative) |

#### Analytical aggregates

| Field | Type | Description |
|-------|------|-------------|
| `interestEarningAssets` | number | Total interest-earning assets |
| `interestBearingLiabilities` | number | Total interest-bearing liabilities |

### Example Requests

```bash
curl "https://eodhd.com/api/mp/praams/bank/balance_sheet/ticker/JPM?api_token=YOUR_API_TOKEN"
```

### Demo access

```bash
curl "https://eodhd.com/api/mp/praams/bank/balance_sheet/ticker/JPM?api_token=demo"
```

### Notes

- **Marketplace product**: Requires a separate PRAAMS Bank Financials marketplace subscription, not included in main EODHD plans.
- **Bank-specific format**: Unlike standard corporate balance sheets, this endpoint uses a banking-specific methodology. Key banking metrics include Loans (gross/net with provisions), Deposits, Securities REPO (assets and liabilities), Investment Portfolio, Interest-Earning Assets, and Interest-Bearing Liabilities.
- **Demo tickers**: `JPM` (JPMorgan Chase), `BAC` (Bank of America), and `WFC` (Wells Fargo) are available with `api_token=demo`.
- **Coverage**: All regional and global banks and banking financial institutions, including banking conglomerates from North America, Europe, UK, and Asia.
- **Mixed annual and quarterly data**: The `items` array contains both FY (annual) and Q1–Q4 (quarterly) records. Use `isQuarter` or `period` to filter.
- **Record ordering**: Records are returned with annual (FY) records first, followed by quarterly records. Within each group, records are ordered chronologically by `date`.
- **Incomplete older quarterly records**: Some older quarterly records (particularly Q4 2020, Q4 2021) contain significantly fewer fields — typically only `longTermInvestments`, `investmentPortfolio`, `totalAssets`, `receivables`, `otherAssets`, `shortTermDebt`, `longTermDebt`, `totalEquity`, `totalEquityAndLiabilities`, `otherLiabilities`, `interestEarningAssets`, and `interestBearingLiabilities`. Fields like `loansGross`, `netLoan`, `deposits`, `cashAndEquivalents`, `depositsWithBanksNet`, `securitiesRepoAssets`, `tradingLiabilities`, `securitiesRepoEquity`, and `payables` are absent in these records.
- **Balancing items**: `otherAssets` and `otherLiabilities` serve as balancing items and may be negative. In older quarterly records with fewer breakdowns, these values can be very large as they absorb all unbroken-out items.
- **Duplicate fields**: `investmentPortfolio` always equals `longTermInvestments`. `securityLiabilities` always equals `tradingLiabilities`. Both pairs are provided for convenience.
- **Balance sheet identity**: `totalAssets` should equal `totalEquityAndLiabilities` in each record.
- **Key metric definitions**:
  - **Net Loans** = Gross Loans − Loan Provisions
  - **Interest-Earning Assets** = assets that generate interest income (loans, investments, interbank deposits, repo assets)
  - **Interest-Bearing Liabilities** = liabilities that incur interest expense (deposits, debt, repo liabilities)
  - **NIM proxy**: Use `interestEarningAssets` and `interestBearingLiabilities` together with income statement data to compute net interest margin
- **Currency**: All monetary values are in the bank's reporting currency (USD for US banks).
- **Related endpoints**: Use the Bank Income Statement endpoint for the complementary income statement data. Use the Bank Balance Sheet by ISIN endpoint for ISIN-based lookups (see praams-bank-balance-sheet-by-isin.md).

### HTTP Status Codes

| Status Code | Meaning | Description |
|-------------|---------|-------------|
| **200** | OK | Request succeeded. Data returned successfully. |
| **401** | Unauthorized | Invalid or missing API key. |
| **415** | Wrong Token | Token format is invalid. |
| **420** | Operation Cancelled | Request was cancelled. |
| **430** | Data Not Found | Ticker not found in PRAAMS bank database. |

### Error Response Format

When an error occurs, the API returns a JSON response:

```json
{
  "success": false,
  "message": "Error description",
  "errors": [
    {
      "code": "ERROR_CODE",
      "description": "Detailed error description"
    }
  ],
  "items": null
}
```

### Handling Errors

**Python Example**:
```python
import requests

def make_api_request(url, params):
    try:
        response = requests.get(url, params=params)
        response.raise_for_status()
        data = response.json()
        if not data.get("success"):
            errors = data.get("errors", [])
            for err in errors:
                print(f"API Error [{err.get('code')}]: {err.get('description')}")
            return None
        return data
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 401:
            print("Error: Invalid API key. Check your credentials.")
        elif e.response.status_code == 415:
            print("Error: Wrong token format.")
        elif e.response.status_code == 430:
            print("Error: Ticker not found in PRAAMS bank database.")
        else:
            print(f"HTTP Error: {e}")
        return None
    except requests.exceptions.RequestException as e:
        print(f"Request failed: {e}")
        return None
```

**Best Practices**:
- Always check `success` field in the response before processing `items`
- Implement exponential backoff for rate limit errors
- Cache responses to reduce API calls — bank financials update quarterly
- Use `isQuarter` to separate annual and quarterly data for analysis
- Monitor your API usage in the user dashboard

---

## Praams Bank Income Statement by ISIN API

<a id="praams-bank-income-statement-by-isin"></a>

### Endpoint Metadata

| Field | Value |
|---|---|
| Status | complete |
| Source | marketplace (PRAAMS API) |
| Docs | https://eodhd.com/financial-apis/equity-risk-return-scoring-api |
| Provider | PRAAMS via EODHD Marketplace |
| Base URL | `https://eodhd.com/api/mp/praams` |
| Path | `/bank/income_statement/isin/{isin}` |
| Method | GET |
| Auth | `api_token` query parameter |
| Slug | `praams-bank-income-statement-by-isin` |
| Source File | `/Users/arnaurodon/Projects/University/Final Thesis/eodhd-claude-skills/skills/eodhd-api/references/endpoints/praams-bank-income-statement-by-isin.md` |

### Purpose

Returns the income statement data for a bank based on the specified ISIN code.
The response provides both annual (FY) and quarterly financial data formatted
specifically for bank analysis, using a unique methodology created and validated
by CFA charterholders with 20+ years of experience in bank analysis.

This is the ISIN-based variant of the Bank Income Statement API. It returns
the same data structure as the ticker-based endpoint but accepts an ISIN
identifier instead. The ISIN is resolved to the corresponding bank and the
same income statement data is returned.

Unlike standard corporate income statements, this endpoint presents bank
financials in a format that reflects the business specifics of banking
institutions, including key banking metrics such as net interest income,
net fee & commission income, RIBPT, IBPT, and provisioning.

**Use cases**:
- Analyze bank income statements using ISIN identifiers for international lookups
- Track core revenue trends (net interest income + net fee & commission income)
- Monitor net interest income and interest margin dynamics
- Evaluate provisioning levels and credit loss trends
- Assess recurring vs non-recurring income composition
- Compare RIBPT (Recurring Income Before Provisioning and Taxes) across periods
- Track dividend per share (DPS) history
- Analyze quarterly and annual financial trends for banks
- Build financial models for banking institutions

### Inputs

### Path (required)

| Parameter | Type | Description |
|-----------|------|-------------|
| `isin` | string | ISIN code of the bank (e.g. `US46625H1005`, `US0605051046`, `US9497461015`) |

### Query (required)

| Parameter | Type | Description |
|-----------|------|-------------|
| `api_token` | string | Your API key (or `demo` for demo ISINs) |

### Outputs

JSON object with top-level envelope:

| Field | Type | Description |
|-------|------|-------------|
| `success` | boolean | `true` if request succeeded |
| `message` | string | Status message (empty on success) |
| `errors` | array | Error objects with `code` and `description` (empty on success) |
| `items` | array | Array of income statement records (annual and quarterly) |

> **Note**: The response uses `items` (plural), not `item` (singular) as in the PRAAMS equity/bond endpoints.

### `items[]` record fields

Each record in the `items` array represents one reporting period. All monetary values are in the bank's reporting currency (typically USD).

#### Period identification

| Field | Type | Description |
|-------|------|-------------|
| `date` | string | Period end date in ISO 8601 format (e.g. `"2024-12-31T00:00:00"`) |
| `period` | string | Period identifier: `"FY"` for full year, `"Q1"`–`"Q4"` for quarters |
| `isQuarter` | boolean | `true` for quarterly data, `false` for annual data |

#### Revenue and income metrics

| Field | Type | Description |
|-------|------|-------------|
| `interestIncome` | number | Total interest income |
| `interestExpense` | number | Total interest expense |
| `netInterestIncome` | number | Net interest income (`interestIncome - interestExpense`) |
| `netFeeAndCommission` | number \| null | Net fee and commission income. May be absent in some quarterly records. |
| `coreRevenue` | number \| null | Core revenue (`netInterestIncome + netFeeAndCommission`). May be absent when `netFeeAndCommission` is not broken out. |
| `nonRecurringIncome` | number \| null | Non-recurring/non-operating income. May be absent in some quarterly records. |

#### Profitability metrics

| Field | Type | Description |
|-------|------|-------------|
| `ribpt` | number \| null | Recurring Income Before Provisioning and Taxes. May be absent in some quarterly records. |
| `ibpt` | number | Income Before Provisioning and Taxes |
| `preTaxProfit` | number | Pre-tax profit (income before taxes) |
| `incomeTaxExpense` | number | Income tax expense |
| `netProfit` | number | Net profit (bottom line) |

#### Provisioning and credit losses

| Field | Type | Description |
|-------|------|-------------|
| `creditLossesProvision` | number | Credit loss provisions (negative = provision charge, positive = provision release) |
| `provisioning` | number | Provisioning amount (positive = provision charge, negative = provision release). Inverse sign convention from `creditLossesProvision`. |

#### Expenses

| Field | Type | Description |
|-------|------|-------------|
| `nonInterestExpenses` | number | Total non-interest expenses (operating expenses) |
| `operatingExpenses` | number | Operating expenses (same value as `nonInterestExpenses`) |

#### Special items and dividends

| Field | Type | Description |
|-------|------|-------------|
| `specialIncomeCharges` | number \| null | Special/one-time income or charges (positive = income, negative = charge). Not present in all records. |
| `dps` | number | Dividend per share for the period |

### Example Requests

```bash
curl "https://eodhd.com/api/mp/praams/bank/income_statement/isin/US46625H1005?api_token=YOUR_API_TOKEN"
```

### Demo access

```bash
curl "https://eodhd.com/api/mp/praams/bank/income_statement/isin/US46625H1005?api_token=demo"
```

### Notes

- **Marketplace product**: Requires a separate PRAAMS Bank Financials marketplace subscription, not included in main EODHD plans.
- **ISIN-based variant**: This endpoint returns identical data to the ticker-based endpoint (`/bank/income_statement/ticker/{ticker}`) but accepts an ISIN code instead. For example, `US46625H1005` resolves to the same data as ticker `JPM`.
- **Bank-specific format**: Unlike standard corporate income statements, this endpoint uses a banking-specific methodology that correctly represents bank financials. Key banking metrics include Net Interest Income, Net Fee & Commission Income, RIBPT, IBPT, and Provisioning.
- **Demo ISINs**: `US46625H1005` (JPMorgan Chase), `US0605051046` (Bank of America), and `US9497461015` (Wells Fargo) are available with `api_token=demo`.
- **Coverage**: All regional and global banks and banking financial institutions, including banking conglomerates from North America, Europe, UK, and Asia.
- **Mixed annual and quarterly data**: The `items` array contains both FY (annual) and Q1–Q4 (quarterly) records. Use `isQuarter` or `period` to filter.
- **Record ordering**: Records are returned with annual (FY) records first, followed by quarterly records. Within each group, records are ordered chronologically by `date`.
- **Incomplete quarterly records**: Some older quarterly records (particularly Q4 and early quarters) may lack certain fields like `netFeeAndCommission`, `coreRevenue`, `ribpt`, and `nonRecurringIncome`. These fields are simply absent from those records, not null.
- **Provisioning sign conventions**: `creditLossesProvision` uses negative for charges and positive for releases. `provisioning` uses the opposite convention (positive for charges, negative for releases). Both represent the same underlying data.
- **Quarterly scaling anomaly**: Some older quarterly records (e.g. Q4 2020, Q4 2021, Q4 2022) may show `nonInterestExpenses`, `operatingExpenses`, `creditLossesProvision`, and `provisioning` scaled by a factor of 100x compared to expected values. This appears to be a data presentation characteristic — use the annual (FY) figures as the authoritative source.
- **specialIncomeCharges**: This field is not present in all records. When present, positive values represent one-time income and negative values represent one-time charges.
- **Key metric definitions**:
  - **Core Revenue** = Net Interest Income + Net Fee & Commission Income
  - **RIBPT** (Recurring Income Before Provisioning and Taxes) = Core Revenue − Operating Expenses
  - **IBPT** (Income Before Provisioning and Taxes) = RIBPT + Non-Recurring Income
  - **Net Interest Income** = Interest Income − Interest Expense
- **Currency**: All monetary values are in the bank's reporting currency (USD for US banks).
- **Related endpoints**: Use the Bank Income Statement by Ticker endpoint for ticker-based lookups (see praams-bank-income-statement-by-ticker.md). Use the Bank Balance Sheet endpoints for complementary balance sheet data.

### HTTP Status Codes

| Status Code | Meaning | Description |
|-------------|---------|-------------|
| **200** | OK | Request succeeded. Data returned successfully. |
| **401** | Unauthorized | Invalid or missing API key. |
| **415** | Wrong Token | Token format is invalid. |
| **420** | Operation Cancelled | Request was cancelled. |
| **430** | Data Not Found | ISIN not found in PRAAMS bank database. |

### Error Response Format

When an error occurs, the API returns a JSON response:

```json
{
  "success": false,
  "message": "Error description",
  "errors": [
    {
      "code": "ERROR_CODE",
      "description": "Detailed error description"
    }
  ],
  "items": null
}
```

### Handling Errors

**Python Example**:
```python
import requests

def make_api_request(url, params):
    try:
        response = requests.get(url, params=params)
        response.raise_for_status()
        data = response.json()
        if not data.get("success"):
            errors = data.get("errors", [])
            for err in errors:
                print(f"API Error [{err.get('code')}]: {err.get('description')}")
            return None
        return data
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 401:
            print("Error: Invalid API key. Check your credentials.")
        elif e.response.status_code == 415:
            print("Error: Wrong token format.")
        elif e.response.status_code == 430:
            print("Error: ISIN not found in PRAAMS bank database.")
        else:
            print(f"HTTP Error: {e}")
        return None
    except requests.exceptions.RequestException as e:
        print(f"Request failed: {e}")
        return None
```

**Best Practices**:
- Always check `success` field in the response before processing `items`
- Implement exponential backoff for rate limit errors
- Cache responses to reduce API calls — bank financials update quarterly
- Use `isQuarter` to separate annual and quarterly data for analysis
- Monitor your API usage in the user dashboard

---

## Praams Bank Income Statement by Ticker API

<a id="praams-bank-income-statement-by-ticker"></a>

### Endpoint Metadata

| Field | Value |
|---|---|
| Status | complete |
| Source | marketplace (PRAAMS API) |
| Docs | https://eodhd.com/financial-apis/equity-risk-return-scoring-api |
| Provider | PRAAMS via EODHD Marketplace |
| Base URL | `https://eodhd.com/api/mp/praams` |
| Path | `/bank/income_statement/ticker/{ticker}` |
| Method | GET |
| Auth | `api_token` query parameter |
| Slug | `praams-bank-income-statement-by-ticker` |
| Source File | `/Users/arnaurodon/Projects/University/Final Thesis/eodhd-claude-skills/skills/eodhd-api/references/endpoints/praams-bank-income-statement-by-ticker.md` |

### Purpose

Returns the income statement data for a bank based on the specified ticker
symbol. The response provides both annual (FY) and quarterly financial data
formatted specifically for bank analysis, using a unique methodology created
and validated by CFA charterholders with 20+ years of experience in bank
analysis.

Unlike standard corporate income statements, this endpoint presents bank
financials in a format that reflects the business specifics of banking
institutions, including key banking metrics such as net interest income,
net fee & commission income, RIBPT, IBPT, and provisioning.

**Use cases**:
- Analyze bank income statements in a proper banking format (not corporate format)
- Track core revenue trends (net interest income + net fee & commission income)
- Monitor net interest income and interest margin dynamics
- Evaluate provisioning levels and credit loss trends
- Assess recurring vs non-recurring income composition
- Compare RIBPT (Recurring Income Before Provisioning and Taxes) across periods
- Track dividend per share (DPS) history
- Analyze quarterly and annual financial trends for banks
- Build financial models for banking institutions

### Inputs

### Path (required)

| Parameter | Type | Description |
|-----------|------|-------------|
| `ticker` | string | Ticker symbol for the bank (e.g. `JPM`, `BAC`, `WFC`) |

### Query (required)

| Parameter | Type | Description |
|-----------|------|-------------|
| `api_token` | string | Your API key (or `demo` for demo tickers) |

### Outputs

JSON object with top-level envelope:

| Field | Type | Description |
|-------|------|-------------|
| `success` | boolean | `true` if request succeeded |
| `message` | string | Status message (empty on success) |
| `errors` | array | Error objects with `code` and `description` (empty on success) |
| `items` | array | Array of income statement records (annual and quarterly) |

> **Note**: The response uses `items` (plural), not `item` (singular) as in the PRAAMS equity/bond endpoints.

### `items[]` record fields

Each record in the `items` array represents one reporting period. All monetary values are in the bank's reporting currency (typically USD).

#### Period identification

| Field | Type | Description |
|-------|------|-------------|
| `date` | string | Period end date in ISO 8601 format (e.g. `"2024-12-31T00:00:00"`) |
| `period` | string | Period identifier: `"FY"` for full year, `"Q1"`–`"Q4"` for quarters |
| `isQuarter` | boolean | `true` for quarterly data, `false` for annual data |

#### Revenue and income metrics

| Field | Type | Description |
|-------|------|-------------|
| `interestIncome` | number | Total interest income |
| `interestExpense` | number | Total interest expense |
| `netInterestIncome` | number | Net interest income (`interestIncome - interestExpense`) |
| `netFeeAndCommission` | number \| null | Net fee and commission income. May be absent in some quarterly records. |
| `coreRevenue` | number \| null | Core revenue (`netInterestIncome + netFeeAndCommission`). May be absent when `netFeeAndCommission` is not broken out. |
| `nonRecurringIncome` | number \| null | Non-recurring/non-operating income. May be absent in some quarterly records. |

#### Profitability metrics

| Field | Type | Description |
|-------|------|-------------|
| `ribpt` | number \| null | Recurring Income Before Provisioning and Taxes. May be absent in some quarterly records. |
| `ibpt` | number | Income Before Provisioning and Taxes |
| `preTaxProfit` | number | Pre-tax profit (income before taxes) |
| `incomeTaxExpense` | number | Income tax expense |
| `netProfit` | number | Net profit (bottom line) |

#### Provisioning and credit losses

| Field | Type | Description |
|-------|------|-------------|
| `creditLossesProvision` | number | Credit loss provisions (negative = provision charge, positive = provision release) |
| `provisioning` | number | Provisioning amount (positive = provision charge, negative = provision release). Inverse sign convention from `creditLossesProvision`. |

#### Expenses

| Field | Type | Description |
|-------|------|-------------|
| `nonInterestExpenses` | number | Total non-interest expenses (operating expenses) |
| `operatingExpenses` | number | Operating expenses (same value as `nonInterestExpenses`) |

#### Special items and dividends

| Field | Type | Description |
|-------|------|-------------|
| `specialIncomeCharges` | number \| null | Special/one-time income or charges (positive = income, negative = charge). Not present in all records. |
| `dps` | number | Dividend per share for the period |

### Example Requests

```bash
curl "https://eodhd.com/api/mp/praams/bank/income_statement/ticker/JPM?api_token=YOUR_API_TOKEN"
```

### Demo access

```bash
curl "https://eodhd.com/api/mp/praams/bank/income_statement/ticker/JPM?api_token=demo"
```

### Notes

- **Marketplace product**: Requires a separate PRAAMS Bank Financials marketplace subscription, not included in main EODHD plans.
- **Bank-specific format**: Unlike standard corporate income statements, this endpoint uses a banking-specific methodology that correctly represents bank financials. Key banking metrics include Net Interest Income, Net Fee & Commission Income, RIBPT, IBPT, and Provisioning.
- **Demo tickers**: `JPM` (JPMorgan Chase), `BAC` (Bank of America), and `WFC` (Wells Fargo) are available with `api_token=demo`.
- **Coverage**: All regional and global banks and banking financial institutions, including banking conglomerates from North America, Europe, UK, and Asia.
- **Mixed annual and quarterly data**: The `items` array contains both FY (annual) and Q1–Q4 (quarterly) records. Use `isQuarter` or `period` to filter.
- **Record ordering**: Records are returned with annual (FY) records first, followed by quarterly records. Within each group, records are ordered chronologically by `date`.
- **Incomplete quarterly records**: Some older quarterly records (particularly Q4 and early quarters) may lack certain fields like `netFeeAndCommission`, `coreRevenue`, `ribpt`, and `nonRecurringIncome`. These fields are simply absent from those records, not null.
- **Provisioning sign conventions**: `creditLossesProvision` uses negative for charges and positive for releases. `provisioning` uses the opposite convention (positive for charges, negative for releases). Both represent the same underlying data.
- **Quarterly scaling anomaly**: Some older quarterly records (e.g. Q4 2020, Q4 2021, Q4 2022) may show `nonInterestExpenses`, `operatingExpenses`, `creditLossesProvision`, and `provisioning` scaled by a factor of 100x compared to expected values. This appears to be a data presentation characteristic — use the annual (FY) figures as the authoritative source.
- **specialIncomeCharges**: This field is not present in all records. When present, positive values represent one-time income and negative values represent one-time charges.
- **Key metric definitions**:
  - **Core Revenue** = Net Interest Income + Net Fee & Commission Income
  - **RIBPT** (Recurring Income Before Provisioning and Taxes) = Core Revenue − Operating Expenses
  - **IBPT** (Income Before Provisioning and Taxes) = RIBPT + Non-Recurring Income
  - **Net Interest Income** = Interest Income − Interest Expense
- **Currency**: All monetary values are in the bank's reporting currency (USD for US banks).
- **Related endpoints**: Use the Bank Balance Sheet endpoint for the complementary balance sheet data. Use the Bank Income Statement by ISIN endpoint for ISIN-based lookups.

### HTTP Status Codes

| Status Code | Meaning | Description |
|-------------|---------|-------------|
| **200** | OK | Request succeeded. Data returned successfully. |
| **401** | Unauthorized | Invalid or missing API key. |
| **415** | Wrong Token | Token format is invalid. |
| **420** | Operation Cancelled | Request was cancelled. |
| **430** | Data Not Found | Ticker not found in PRAAMS bank database. |

### Error Response Format

When an error occurs, the API returns a JSON response:

```json
{
  "success": false,
  "message": "Error description",
  "errors": [
    {
      "code": "ERROR_CODE",
      "description": "Detailed error description"
    }
  ],
  "items": null
}
```

### Handling Errors

**Python Example**:
```python
import requests

def make_api_request(url, params):
    try:
        response = requests.get(url, params=params)
        response.raise_for_status()
        data = response.json()
        if not data.get("success"):
            errors = data.get("errors", [])
            for err in errors:
                print(f"API Error [{err.get('code')}]: {err.get('description')}")
            return None
        return data
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 401:
            print("Error: Invalid API key. Check your credentials.")
        elif e.response.status_code == 415:
            print("Error: Wrong token format.")
        elif e.response.status_code == 430:
            print("Error: Ticker not found in PRAAMS bank database.")
        else:
            print(f"HTTP Error: {e}")
        return None
    except requests.exceptions.RequestException as e:
        print(f"Request failed: {e}")
        return None
```

**Best Practices**:
- Always check `success` field in the response before processing `items`
- Implement exponential backoff for rate limit errors
- Cache responses to reduce API calls — bank financials update quarterly
- Use `isQuarter` to separate annual and quarterly data for analysis
- Monitor your API usage in the user dashboard

---

## Praams Bond Analysis by ISIN API

<a id="praams-bond-analyze-by-isin"></a>

### Endpoint Metadata

| Field | Value |
|---|---|
| Status | complete |
| Source | marketplace (PRAAMS API) |
| Docs | https://eodhd.com/financial-apis/equity-risk-return-scoring-api |
| Provider | PRAAMS via EODHD Marketplace |
| Base URL | `https://eodhd.com/api/mp/praams` |
| Path | `/analyse/bond/{isin}` |
| Method | GET |
| Auth | `api_token` query parameter |
| Slug | `praams-bond-analyze-by-isin` |
| Source File | `/Users/arnaurodon/Projects/University/Final Thesis/eodhd-claude-skills/skills/eodhd-api/references/endpoints/praams-bond-analyze-by-isin.md` |

### Purpose

Returns comprehensive risk and return analytics for a specific bond identified
by its ISIN code. The response includes the proprietary PRAAMS Ratio, individual
risk and return scores across 12 dimensions, coupon details, profitability
metrics of the issuer, growth momentum, market view with spread/yield analysis,
performance history, and detailed textual descriptions — providing CFA-level
bond analysis in a single API call.

This endpoint is the bond-specific counterpart to the equity ISIN endpoint.
It shares a similar overall structure but includes bond-specific sections
(`coupon`, `marketView`, `bondType`) and omits equity-specific sections
(`analystView`, `dividend`).

**Use cases**:
- Instant risk-return assessment of any bond using the PRAAMS Ratio (1-10 scale)
- ISIN-based bond lookup for global fixed income securities
- Detailed breakdown of 12 scoring dimensions (coupon, valuation, volatility, solvency, etc.)
- Credit risk assessment including subordination and recovery rate analysis
- Spread analysis vs peer bonds with similar risk profiles
- Stress testing and volatility scoring for bond price risk
- Issuer profitability analysis with margins, RoE, RoA, RoCE, and RoIC/WACC
- Issuer growth momentum analysis (Revenue, EPS, EBITDA, FCF trends)
- Country and liquidity risk profiling
- Call risk assessment for callable bonds

### Inputs

### Path (required)

| Parameter | Type | Description |
|-----------|------|-------------|
| `isin` | string | ISIN code of the bond (e.g. `US7593518852`, `US91282CJN20`) |

### Query (required)

| Parameter | Type | Description |
|-----------|------|-------------|
| `api_token` | string | Your API key (or `demo` for demo ISINs) |

### Outputs

JSON object with top-level envelope:

| Field | Type | Description |
|-------|------|-------------|
| `success` | boolean | `true` if request succeeded |
| `message` | string | Status message (empty on success) |
| `errors` | array | Error objects with `code` and `description` (empty on success) |
| `item` | object | The main data payload |

### `item` object

Contains the following sections:

#### `item.asset`

| Field | Type | Description |
|-------|------|-------------|
| `ticker` | string | Bond description/name (e.g. `"RGA float 15-Oct-52"`) |
| `name` | string | Issuer name |
| `isin` | string | ISIN identifier |
| `companyDescription` | string | Issuer company description |
| `isActivelyTrading` | boolean | Whether the bond is currently trading |
| `assetId` | integer | Internal PRAAMS asset ID |
| `ratio` | integer | The PRAAMS Ratio (1-10 scale; higher = better risk-return). May be `0` when insufficient data. |
| `watchList` | boolean | Watchlist flag |
| `isBond` | boolean | Always `true` for bonds |
| `bondType` | string | Bond classification (e.g. `"Corporate"`) |
| `isFinancial` | boolean | Whether the issuer is in the financial sector |

> **Note**: Unlike equities, the `ticker` field contains a descriptive bond name (coupon type, maturity date) rather than a stock ticker symbol. The `isBond` field is always `true`.

#### `item.description`

| Field | Type | Description |
|-------|------|-------------|
| `assetClass` | string | Always `"bond"` |
| `country` | string | Country code (e.g. `"US"`) |
| `sector` | string | Sector name (e.g. `"Financial Services"`) |
| `regionIds` | array of integers | Region identifiers |
| `countryId` | integer | Country identifier |
| `sectorId` | integer | Sector identifier |
| `industryId` | integer | Industry identifier |
| `cohortId` | integer | Bond cohort/peer group identifier |
| `currencyId` | string | Currency code (e.g. `"USD"`) |
| `otherRisks` | object | `{short, long}` — other risk assessment (subordination, call risk, etc.) |
| `countryRisks` | object | `{short, long}` — country risk assessment |
| `liquidityRisk` | object | `{short, long}` — liquidity risk assessment |
| `stressTest` | object | `{short, long}` — stress test assessment |
| `volatility` | object | `{short, long}` — volatility assessment |
| `solvency` | object | `{short, long}` — solvency/default risk assessment |

Each risk object contains `short` (one-word rating like "Negligible", "Very low", "Small", "Moderate", "Considerable", "Very high", "No data") and `long` (detailed explanation).

> **Bond-specific fields**: `cohortId` is unique to the bond endpoint and identifies the peer group for spread comparisons. The `otherRisks` section often contains subordination and call risk details. The `solvency` section includes recovery rate estimates for subordinated bonds.

#### `item.profile`

| Field | Type | Description |
|-------|------|-------------|
| `companyProfileDescription` | object | `{short, long}` — issuer company profile descriptions |
| `finStatementAnalysisShort` | string | Short financial statement analysis (may be empty) |
| `finStatementAnalysis` | string | Financial analysis notes (e.g. `"Next call date 15-Oct-27"`) |

> **Note**: The bond profile does not include `parentAsset` or `parentNote` fields (unlike the equity ISIN endpoint). The `finStatementAnalysis` field may contain bond-specific notes such as the next call date.

#### `item.scores`

12 scoring dimensions, each an integer (1-10 scale). For bonds, the scoring dimensions differ slightly from equities:

| Field | Type | Description |
|-------|------|-------------|
| `marketView` | integer | Market view/spread score (bond-specific, replaces `analystView`) |
| `coupon` | integer | Coupon score (bond-specific, replaces `dividends`) |
| `valuation` | integer | Valuation score |
| `performance` | integer | Performance score |
| `profitability` | integer | Issuer profitability score |
| `growthMom` | integer | Issuer growth momentum score |
| `other` | integer | Other risks score |
| `countryRisk` | integer | Country risk score |
| `liquidity` | integer | Liquidity risk score |
| `stressTest` | integer | Stress test score |
| `volatility` | integer | Volatility score |
| `solvency` | integer | Solvency/default risk score |

A score of `0` indicates insufficient data for that dimension.

> **Score interpretation**: For risk dimensions (volatility, stressTest, liquidity, solvency, countryRisk, other), lower scores indicate lower risk. For return dimensions (valuation, performance, profitability, growthMom, marketView, coupon), higher scores indicate better return prospects. A score of `0` means "no data".

#### `item.keyFactors`

| Field | Type | Description |
|-------|------|-------------|
| `risk.characteristic` | string | Overall risk characterization (e.g. `"Considerable"`) |
| `risk.factors[]` | array | Key risk factors with `priority`, `text`, and `icon` (true=positive) |
| `return.characteristic` | string | Overall return characterization (e.g. `"Average"`) |
| `return.factors[]` | array | Key return factors with `priority`, `text`, and `icon` (true=positive) |

#### `item.valuation`

For bonds, valuation may be a simple text description rather than the structured multiples object used for equities:

| Field | Type | Description |
|-------|------|-------------|
| `short` | string | Valuation summary (e.g. `"No data"`) |
| `long` | string | Detailed valuation description |

> **Note**: When the bond is not actively trading, valuation returns a flat `{short, long}` object instead of the equity-style object with `descriptionShort`, `wams`, and `valuations[]`.

#### `item.performance`

| Field | Type | Description |
|-------|------|-------------|
| `description` | object | `{short, long}` — performance summary |
| `byPeriods[]` | array | Period returns with `period`, `asset` (decimal), `peers` (decimal). Empty array when no data available. |

#### `item.marketView` (bond-specific)

Replaces `analystView` from the equity endpoint. Provides spread and yield analysis vs peer bonds:

| Field | Type | Description |
|-------|------|-------------|
| `description` | object | `{short, long}` — market view summary with peer spread context |
| `yearSpreadHistory[]` | array | Historical spread data points (empty when insufficient data) |
| `yearPriceHistory[]` | array | Historical price data points (empty when insufficient data) |
| `yearYieldHistory[]` | array | Historical yield data points (empty when insufficient data) |
| `yearPeersSpreadHistory[]` | array | Peer group spread history (empty when insufficient data) |
| `firstSpreadDateInArray` | string | Start date of spread data (ISO 8601 format) |
| `lastSpreadDateInArray` | string | End date of spread data (ISO 8601 format) |
| `leftPeersValue` | number | Lower bound of comparable peer spread range (bps) |
| `rightPeersValue` | number | Upper bound of comparable peer spread range (bps) |

> **Spread interpretation**: The `leftPeersValue` and `rightPeersValue` define the spread range for comparable bonds. A spread below `leftPeersValue` generally means the bond is "expensive", while a spread above `rightPeersValue` implies the bond is "cheap".

#### `item.profitability`

Issuer profitability metrics (same structure as equity endpoint):

| Field | Type | Description |
|-------|------|-------------|
| `description` | string | Profitability summary (e.g. `"Average"`) |
| `profitability[]` | array | Metrics (RoE, RoA, RoCE) with `name`, `description`, `assets` and `peers` objects containing TTM/NTM values and scores |
| `profitabilityGraph[]` | array | Margin graphs (Net margin, EBITDA margin) with `name`, `shortDesc`, and `graph[]` containing historical data points |
| `roICWACC` | object | RoIC/WACC analysis with `description` `{short, long}` and `score` |
| `profitabilityPeerMargins[]` | array | Peer margin comparison with `name`, `scoreTTM`, `scoreNTM` |

#### `item.growthMomentum`

Issuer growth metrics (same structure as equity endpoint):

| Field | Type | Description |
|-------|------|-------------|
| `description` | string | Growth summary (e.g. `"Average"`) |
| `absDescription` | string | Absolute growth description |
| `chgDescription` | string | Growth rate change description |
| `currencySize` | string | Currency for size metrics |
| `growthMomentum[]` | array | Metrics (EPS, Revenue, EBITDA, FCF) with `name`, `graph[]` and `growthRatesGraph[]` |

Each metric's `graph[]` contains `{order, label, value, isPrediction}` data points. The `growthRatesGraph[]` contains the same structure with year-over-year growth rates as decimals.

#### `item.coupon` (bond-specific)

Replaces `dividend` from the equity endpoint. Provides coupon details:

| Field | Type | Description |
|-------|------|-------------|
| `short` | string | Coupon characterization (e.g. `"Reasonable"`) |
| `long` | string | Detailed coupon description including formula for floating-rate bonds |

> **Floating-rate bonds**: For floating-rate bonds, the `long` field describes the coupon formula (e.g. "7.125% from settlement date until 15.10.2027, then 5Y UST Yield + 3.456% to maturity").

### Example Requests

```bash
curl "https://eodhd.com/api/mp/praams/analyse/bond/US7593518852?api_token=YOUR_API_TOKEN"
```

### Demo access

```bash
curl "https://eodhd.com/api/mp/praams/analyse/bond/US7593518852?api_token=demo"
```

### Notes

- **Marketplace product**: Requires a separate PRAAMS marketplace subscription, not included in main EODHD plans.
- **PRAAMS Ratio**: The flagship metric (`item.asset.ratio`) summarizes 470+ metrics into a single 1-10 score. Higher is better. For bonds with insufficient trading data, this may be `0`.
- **Bond vs Equity differences**: The bond endpoint uses `marketView` (spread/yield analysis) instead of `analystView`, `coupon` instead of `dividend`, and includes `bondType` and `cohortId`. The `assetClass` is `"bond"` and `isBond` is `true`.
- **Demo ISINs**: `US7593518852` (RGA corporate bond) and `US91282CJN20` are available with `api_token=demo`.
- **Coverage**: Part of the 120,000+ global equities and bonds coverage. Use the equity ISIN endpoint for equity analysis (see praams-risk-scoring-by-isin.md).
- **Score of 0**: A score of `0` in `item.scores` indicates insufficient data for that dimension. This is common for illiquid bonds where market data is sparse (e.g. `marketView: 0`, `valuation: 0`, `performance: 0`, `liquidity: 0`).
- **Subordinated bonds**: The `otherRisks` and `solvency` descriptions provide detailed subordination analysis, including expected recovery rates (typically 15-20% for subordinated bonds).
- **Callable bonds**: Call risk is documented in `otherRisks.long` and the next call date appears in `profile.finStatementAnalysis`.
- **Floating-rate bonds**: The `coupon` section describes the full coupon formula, including the fixed-rate period and the floating-rate formula after the reset date.
- **Peer spread range**: `marketView.leftPeersValue` and `rightPeersValue` (in basis points) define the fair value range for comparable bonds. Below the range = expensive; above = cheap.
- **Valuation format**: Unlike equities (which return structured multiples), bond valuation may return a simple `{short, long}` text object when insufficient trading data is available.
- **Profitability and growth**: These sections analyze the bond **issuer's** financial health, not the bond itself. They share the same structure as the equity endpoint.
- **Rich text descriptions**: Most sections include `short` (headline) and `long` (detailed paragraph) descriptions suitable for display to end users.
- **Related endpoints**: Use `/analyse/equity/isin/{isin}` for equity ISIN lookups and `/analyse/equity/ticker/{ticker}` for equity ticker lookups.

### HTTP Status Codes

| Status Code | Meaning | Description |
|-------------|---------|-------------|
| **200** | OK | Request succeeded. Data returned successfully. |
| **401** | Unauthorized | Invalid or missing API key. |
| **415** | Wrong Token | Token format is invalid. |
| **420** | Operation Cancelled | Request was cancelled. |
| **430** | Data Not Found | ISIN not found in PRAAMS database. |

### Error Response Format

When an error occurs, the API returns a JSON response:

```json
{
  "success": false,
  "message": "Error description",
  "errors": [
    {
      "code": "ERROR_CODE",
      "description": "Detailed error description"
    }
  ],
  "item": null
}
```

### Handling Errors

**Python Example**:
```python
import requests

def make_api_request(url, params):
    try:
        response = requests.get(url, params=params)
        response.raise_for_status()
        data = response.json()
        if not data.get("success"):
            errors = data.get("errors", [])
            for err in errors:
                print(f"API Error [{err.get('code')}]: {err.get('description')}")
            return None
        return data
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 401:
            print("Error: Invalid API key. Check your credentials.")
        elif e.response.status_code == 415:
            print("Error: Wrong token format.")
        elif e.response.status_code == 430:
            print("Error: ISIN not found in PRAAMS database.")
        else:
            print(f"HTTP Error: {e}")
        return None
    except requests.exceptions.RequestException as e:
        print(f"Request failed: {e}")
        return None
```

**Best Practices**:
- Always check `success` field in the response before processing `item`
- Implement exponential backoff for rate limit errors
- Cache responses to reduce API calls — PRAAMS data updates daily
- Monitor your API usage in the user dashboard

---

## Praams Multi-Factor Bond Report by ISIN API

<a id="praams-report-bond-by-isin"></a>

### Endpoint Metadata

| Field | Value |
|---|---|
| Status | complete |
| Source | marketplace (PRAAMS API) |
| Docs | https://eodhd.com/marketplace/unicornbay/praams/docs |
| Provider | PRAAMS via EODHD Marketplace |
| Base URL | `https://eodhd.com/api/mp/praams` |
| Path | `/reports/bond/{isin}` |
| Method | GET |
| Auth | `api_token` query parameter |
| Slug | `praams-report-bond-by-isin` |
| Source File | `/Users/arnaurodon/Projects/University/Final Thesis/eodhd-claude-skills/skills/eodhd-api/references/endpoints/praams-report-bond-by-isin.md` |

### Purpose

Generates and downloads a multi-page PDF investment report for a specific bond
identified by its ISIN code. The report contains concise visual and descriptive
information covering 6 return factors and 6 risk factors.

**Return factors**: valuation, performance, analyst/market view, profitability, growth, and dividends/coupons.

**Risk factors**: default, volatility, stress-test, selling difficulty, country, and other risks.

Each report is an asset class-specific analytical summary — bond reports differ from
equity reports. Reports are updated daily with new prices, financials, dividends,
and corporate actions.

**Use cases**:
- Download a PDF investment report on any bond using its ISIN
- Share bond analysis with colleagues or clients
- Get a quick visual summary of bond risk and return factors
- Analyze corporate and sovereign bonds from global markets

**Disclaimer**: The product does not constitute financial advice or investment recommendations. Trading involves risk, and users should carefully evaluate their own financial situation before engaging in any trades.

### Inputs

### Path (required)

| Parameter | Type | Description |
|-----------|------|-------------|
| `isin` | string | ISIN code of the bond (e.g. `US7593518852`, `US91282CJN20`, `US59018YTM39`) |

### Query

| Parameter | Required | Type | Description |
|-----------|----------|------|-------------|
| `api_token` | Yes | string | Your API key (or `demo` for demo ISINs) |
| `email` | Yes | string | Email address for notifications or confirmations |
| `isFull` | No | boolean | Whether to generate the full report or a partial report |

### Example Requests

```bash
# Demo access
curl -o PRAAMS_bond_report.pdf "https://eodhd.com/api/mp/praams/reports/bond/US7593518852?isFull=false&email=test@test.com&api_token=demo"

# Production access (Bank of America bond, 6.05% coupon, maturing 1 June 2034)
curl -o PRAAMS_bond_report.pdf "https://eodhd.com/api/mp/praams/reports/bond/US59018YTM39?isFull=false&email=test@test.com&api_token=YOUR_API_TOKEN"
```

### Python Example

```python
import requests

def download_bond_report_by_isin(isin, email, api_token, is_full=False, output_path=None):
    """Download a PRAAMS bond PDF report by ISIN."""
    url = f"https://eodhd.com/api/mp/praams/reports/bond/{isin}"
    params = {
        "api_token": api_token,
        "email": email,
        "isFull": str(is_full).lower()
    }

    response = requests.get(url, params=params)
    response.raise_for_status()

    if output_path is None:
        output_path = f"PRAAMS_bond_report_{isin}.pdf"

    with open(output_path, "wb") as f:
        f.write(response.content)

    return output_path

# Demo usage
path = download_bond_report_by_isin("US7593518852", "test@test.com", "demo")
print(f"Report saved to: {path}")
```

### Notes

- **Marketplace product**: Requires a separate PRAAMS marketplace subscription, not included in main EODHD plans.
- **PDF response**: Unlike most EODHD endpoints that return JSON, this endpoint returns a binary PDF file. Use appropriate file handling (binary write mode).
- **Demo ISINs**: `US7593518852` and `US91282CJN20` are available with `api_token=demo`.
- **Daily updates**: Reports are regenerated daily with latest prices, financials, dividends, and corporate actions.
- **Bond-specific**: Bond reports differ from equity reports — they include coupon analysis, spread comparisons, and credit risk assessment instead of dividend and analyst view sections.
- **ISIN required**: Bonds are identified by ISIN only (no ticker-based lookup for bonds).
- **Related endpoints**: Use `/reports/equity/ticker/{ticker}` for equity reports by ticker (see praams-report-equity-by-ticker.md). Use `/reports/equity/isin/{isin}` for equity reports by ISIN (see praams-report-equity-by-isin.md).

### HTTP Status Codes

| Status Code | Meaning | Description |
|-------------|---------|-------------|
| **200** | OK | PDF file returned successfully. |
| **401** | Unauthorized | Invalid or missing API key. |
| **415** | Wrong Token | Token format is invalid. |
| **420** | Operation Cancelled | Request was cancelled. |
| **430** | Data Not Found | ISIN not found in PRAAMS database. |

---

## Praams Multi-Factor Equity Report by ISIN API

<a id="praams-report-equity-by-isin"></a>

### Endpoint Metadata

| Field | Value |
|---|---|
| Status | complete |
| Source | marketplace (PRAAMS API) |
| Docs | https://eodhd.com/marketplace/unicornbay/praams/docs |
| Provider | PRAAMS via EODHD Marketplace |
| Base URL | `https://eodhd.com/api/mp/praams` |
| Path | `/reports/equity/isin/{isin}` |
| Method | GET |
| Auth | `api_token` query parameter |
| Slug | `praams-report-equity-by-isin` |
| Source File | `/Users/arnaurodon/Projects/University/Final Thesis/eodhd-claude-skills/skills/eodhd-api/references/endpoints/praams-report-equity-by-isin.md` |

### Purpose

Generates and downloads a multi-page PDF investment report for a specific equity
identified by its ISIN code. The report contains concise visual and descriptive
information covering 6 return factors and 6 risk factors.

**Return factors**: valuation, performance, analyst/market view, profitability, growth, and dividends/coupons.

**Risk factors**: default, volatility, stress-test, selling difficulty, country, and other risks.

Each report is an industry-specific and asset class-specific analytical summary.
Reports for bank and corporate entities will be different. Reports are updated daily
with new prices, financials, dividends, and corporate actions.

**Use cases**:
- Download a PDF investment report for any equity using its ISIN code
- Share multi-factor analysis with colleagues or clients
- ISIN-based lookup for international equities or bonds that share the same ISIN
- Get a quick visual summary of risk and return factors

**Disclaimer**: The product does not constitute financial advice or investment recommendations. Trading involves risk, and users should carefully evaluate their own financial situation before engaging in any trades.

### Inputs

### Path (required)

| Parameter | Type | Description |
|-----------|------|-------------|
| `isin` | string | ISIN code of the equity (e.g. `US0378331005`, `US88160R1014`, `US0231351067`) |

### Query

| Parameter | Required | Type | Description |
|-----------|----------|------|-------------|
| `api_token` | Yes | string | Your API key (or `demo` for demo ISINs) |
| `email` | Yes | string | Email address for notifications or confirmations |
| `isFull` | No | boolean | Whether to generate the full report or a partial report |

### Example Requests

```bash
# Demo access (Apple by ISIN)
curl -o PRAAMS_report_AAPL.pdf "https://eodhd.com/api/mp/praams/reports/equity/isin/US0378331005?isFull=false&email=test@test.com&api_token=demo"

# Production access
curl -o PRAAMS_report.pdf "https://eodhd.com/api/mp/praams/reports/equity/isin/US59018YTM39?isFull=false&email=test@test.com&api_token=YOUR_API_TOKEN"
```

### Python Example

```python
import requests

def download_equity_report_by_isin(isin, email, api_token, is_full=False, output_path=None):
    """Download a PRAAMS equity PDF report by ISIN."""
    url = f"https://eodhd.com/api/mp/praams/reports/equity/isin/{isin}"
    params = {
        "api_token": api_token,
        "email": email,
        "isFull": str(is_full).lower()
    }

    response = requests.get(url, params=params)
    response.raise_for_status()

    if output_path is None:
        output_path = f"PRAAMS_report_{isin}.pdf"

    with open(output_path, "wb") as f:
        f.write(response.content)

    return output_path

# Demo usage
path = download_equity_report_by_isin("US0378331005", "test@test.com", "demo")
print(f"Report saved to: {path}")
```

### Notes

- **Marketplace product**: Requires a separate PRAAMS marketplace subscription, not included in main EODHD plans.
- **PDF response**: Unlike most EODHD endpoints that return JSON, this endpoint returns a binary PDF file. Use appropriate file handling (binary write mode).
- **Demo ISINs**: `US0378331005` (Apple), `US88160R1014` (Tesla), and `US0231351067` (Amazon) are available with `api_token=demo`.
- **Daily updates**: Reports are regenerated daily with latest prices, financials, dividends, and corporate actions.
- **Industry-specific**: Reports are tailored to the industry — a bank report will differ from a non-financial corporate report.
- **ISIN vs Ticker**: Use this endpoint when you have an ISIN code. Use `/reports/equity/ticker/{ticker}` for ticker-based lookups (see praams-report-equity-by-ticker.md).
- **Related endpoints**: Use `/reports/bond/isin/{isin}` for bond reports (see praams-report-bond-by-isin.md).

### HTTP Status Codes

| Status Code | Meaning | Description |
|-------------|---------|-------------|
| **200** | OK | PDF file returned successfully. |
| **401** | Unauthorized | Invalid or missing API key. |
| **415** | Wrong Token | Token format is invalid. |
| **420** | Operation Cancelled | Request was cancelled. |
| **430** | Data Not Found | ISIN not found in PRAAMS database. |

---

## Praams Multi-Factor Equity Report by Ticker API

<a id="praams-report-equity-by-ticker"></a>

### Endpoint Metadata

| Field | Value |
|---|---|
| Status | complete |
| Source | marketplace (PRAAMS API) |
| Docs | https://eodhd.com/marketplace/unicornbay/praams/docs |
| Provider | PRAAMS via EODHD Marketplace |
| Base URL | `https://eodhd.com/api/mp/praams` |
| Path | `/reports/equity/ticker/{ticker}` |
| Method | GET |
| Auth | `api_token` query parameter |
| Slug | `praams-report-equity-by-ticker` |
| Source File | `/Users/arnaurodon/Projects/University/Final Thesis/eodhd-claude-skills/skills/eodhd-api/references/endpoints/praams-report-equity-by-ticker.md` |

### Purpose

Generates and downloads a multi-page PDF investment report for a specific equity
identified by its ticker symbol. The report contains concise visual and descriptive
information covering 6 return factors and 6 risk factors.

**Return factors**: valuation, performance, analyst/market view, profitability, growth, and dividends/coupons.

**Risk factors**: default, volatility, stress-test, selling difficulty, country, and other risks.

Each report is an industry-specific and asset class-specific analytical summary.
Reports for bank and corporate entities will be different. Reports are updated daily
with new prices, financials, dividends, and corporate actions.

**Use cases**:
- Download a PDF investment report on any equity for offline reading
- Share multi-factor analysis with colleagues or clients
- Get a quick visual summary of risk and return factors
- Industry-specific analysis (bank reports differ from corporate reports)

**Disclaimer**: The product does not constitute financial advice or investment recommendations. Trading involves risk, and users should carefully evaluate their own financial situation before engaging in any trades.

### Inputs

### Path (required)

| Parameter | Type | Description |
|-----------|------|-------------|
| `ticker` | string | Ticker symbol of the equity (e.g. `AAPL`, `TSLA`, `AMZN`) |

### Query

| Parameter | Required | Type | Description |
|-----------|----------|------|-------------|
| `api_token` | Yes | string | Your API key (or `demo` for demo tickers) |
| `email` | Yes | string | Email address for notifications or confirmations |
| `isFull` | No | boolean | Whether to generate the full report or a partial report |

### Example Requests

```bash
# Demo access
curl -o PRAAMS_report_AAPL.pdf "https://eodhd.com/api/mp/praams/reports/equity/ticker/AAPL?isFull=false&email=test@test.com&api_token=demo"

# Production access
curl -o PRAAMS_report_AAPL.pdf "https://eodhd.com/api/mp/praams/reports/equity/ticker/AAPL?isFull=false&email=test@test.com&api_token=YOUR_API_TOKEN"
```

### Python Example

```python
import requests

def download_equity_report_by_ticker(ticker, email, api_token, is_full=False, output_path=None):
    """Download a PRAAMS equity PDF report by ticker."""
    url = f"https://eodhd.com/api/mp/praams/reports/equity/ticker/{ticker}"
    params = {
        "api_token": api_token,
        "email": email,
        "isFull": str(is_full).lower()
    }

    response = requests.get(url, params=params)
    response.raise_for_status()

    if output_path is None:
        output_path = f"PRAAMS_report_{ticker}.pdf"

    with open(output_path, "wb") as f:
        f.write(response.content)

    return output_path

# Demo usage
path = download_equity_report_by_ticker("AAPL", "test@test.com", "demo")
print(f"Report saved to: {path}")
```

### Notes

- **Marketplace product**: Requires a separate PRAAMS marketplace subscription, not included in main EODHD plans.
- **PDF response**: Unlike most EODHD endpoints that return JSON, this endpoint returns a binary PDF file. Use appropriate file handling (binary write mode).
- **Demo tickers**: `AAPL`, `TSLA`, and `AMZN` are available with `api_token=demo`.
- **Daily updates**: Reports are regenerated daily with latest prices, financials, dividends, and corporate actions.
- **Industry-specific**: Reports are tailored to the industry — a bank report will differ from a non-financial corporate report.
- **Related endpoints**: Use `/reports/equity/isin/{isin}` for ISIN-based equity reports (see praams-report-equity-by-isin.md). Use `/reports/bond/isin/{isin}` for bond reports (see praams-report-bond-by-isin.md).

### HTTP Status Codes

| Status Code | Meaning | Description |
|-------------|---------|-------------|
| **200** | OK | PDF file returned successfully. |
| **401** | Unauthorized | Invalid or missing API key. |
| **415** | Wrong Token | Token format is invalid. |
| **420** | Operation Cancelled | Request was cancelled. |
| **430** | Data Not Found | Ticker not found in PRAAMS database. |

---

## Praams Equity Risk & Return Scoring by ISIN API

<a id="praams-risk-scoring-by-isin"></a>

### Endpoint Metadata

| Field | Value |
|---|---|
| Status | complete |
| Source | marketplace (PRAAMS API) |
| Docs | https://eodhd.com/financial-apis/equity-risk-return-scoring-api |
| Provider | PRAAMS via EODHD Marketplace |
| Base URL | `https://eodhd.com/api/mp/praams` |
| Path | `/analyse/equity/isin/{isin}` |
| Method | GET |
| Auth | `api_token` query parameter |
| Slug | `praams-risk-scoring-by-isin` |
| Source File | `/Users/arnaurodon/Projects/University/Final Thesis/eodhd-claude-skills/skills/eodhd-api/references/endpoints/praams-risk-scoring-by-isin.md` |

### Purpose

Returns comprehensive risk and return analytics for a specific equity
identified by its ISIN code. The response includes the proprietary PRAAMS
Ratio, individual risk and return scores across 12 dimensions, valuation
multiples, profitability metrics, growth momentum, dividend data, analyst
views, performance history, company profile, and detailed textual descriptions
— providing CFA-level analysis in a single API call.

This is the ISIN-based variant of the PRAAMS Equity Risk & Return Scoring API.
It returns the same data structure as the ticker-based endpoint but accepts
an ISIN identifier instead. The response resolves the ISIN to its associated
ticker(s) and returns analysis for the primary listing.

**Use cases**:
- Instant risk-return assessment of any equity using the PRAAMS Ratio (1-10 scale)
- ISIN-based lookups for international equities where ticker symbols vary by exchange
- Detailed breakdown of 12 scoring dimensions (valuation, profitability, volatility, solvency, etc.)
- Valuation analysis with TTM and NTM multiples (P/E, PEG, P/B, P/S, P/FCF, EV/EBITDA)
- Performance tracking vs sector/industry peers
- Profitability analysis with margins, RoE, RoA, RoCE, and RoIC/WACC
- Growth momentum analysis (Revenue, EPS, EBITDA, FCF trends)
- Dividend history and yield analysis
- Analyst consensus price targets and recommendations
- Risk profiling: volatility, stress testing, liquidity, solvency, country risk
- Cross-listing discovery via the `profile.parentAsset` field

### Inputs

### Path (required)

| Parameter | Type | Description |
|-----------|------|-------------|
| `isin` | string | ISIN code of the equity (e.g. `US88160R1014`, `US0378331005`, `US0231351067`) |

### Query (required)

| Parameter | Type | Description |
|-----------|------|-------------|
| `api_token` | string | Your API key (or `demo` for demo ISINs) |

### Outputs

JSON object with top-level envelope:

| Field | Type | Description |
|-------|------|-------------|
| `success` | boolean | `true` if request succeeded |
| `message` | string | Status message (empty on success) |
| `errors` | array | Error objects with `code` and `description` (empty on success) |
| `item` | object | The main data payload |

### `item` object

Contains the following sections:

#### `item.asset`

| Field | Type | Description |
|-------|------|-------------|
| `ticker` | string | Resolved ticker symbol (e.g. `TL0.DE` for TSLA's German listing) |
| `name` | string | Company name |
| `isin` | string | ISIN identifier |
| `companyDescription` | string | Brief company description |
| `isActivelyTrading` | boolean | Whether the stock is currently trading |
| `assetId` | integer | Internal PRAAMS asset ID |
| `ratio` | integer | The PRAAMS Ratio (1-10 scale; higher = better risk-return) |
| `watchList` | boolean | Watchlist flag |
| `isBond` | boolean | Always `false` for equities |
| `isFinancial` | boolean | Whether the company is in the financial sector |

> **Note**: The `ticker` field may resolve to a non-US listing (e.g. `TL0.DE` for Tesla on the German exchange) depending on which exchange the ISIN maps to.

#### `item.description`

| Field | Type | Description |
|-------|------|-------------|
| `assetClass` | string | Always `"equity"` |
| `country` | string | Country code (e.g. `"US"`) |
| `sector` | string | Sector name (e.g. `"Consumer Cyclical"`) |
| `regionIds` | array of integers | Region identifiers |
| `countryId` | integer | Country identifier |
| `sectorId` | integer | Sector identifier |
| `industryId` | integer | Industry identifier |
| `currencyId` | string | Currency code (e.g. `"EUR"`, `"USD"`) |
| `otherRisks` | object | `{short, long}` — other risk assessment |
| `countryRisks` | object | `{short, long}` — country risk assessment |
| `liquidityRisk` | object | `{short, long}` — liquidity risk assessment |
| `stressTest` | object | `{short, long}` — stress test assessment |
| `volatility` | object | `{short, long}` — volatility assessment |
| `solvency` | object | `{short, long}` — solvency/default risk assessment |

Each risk object contains `short` (one-word rating like "Negligible", "Very low", "Small", "Modest", "Meaningful", "Limited") and `long` (detailed explanation).

#### `item.profile`

| Field | Type | Description |
|-------|------|-------------|
| `companyProfileDescription` | object | `{short, long}` — company profile descriptions |
| `parentNote` | string | Note about primary listing association (e.g. "This stock is associated with Tesla, Inc.. The primary listing...is TSLA.") |
| `finStatementAnalysisShort` | string | Short financial statement analysis (may be empty) |
| `finStatementAnalysis` | string | Full financial statement analysis (may be empty) |
| `parentAsset` | object | Parent/primary listing information |

##### `item.profile.parentAsset`

| Field | Type | Description |
|-------|------|-------------|
| `keyId` | integer | Internal key ID |
| `rank` | integer | Ranking value |
| `isin` | string | ISIN of the parent/primary listing |
| `assetName` | string | Ticker of the primary listing (e.g. `"TSLA"`) |
| `issuerName` | string | Issuer/company name |
| `mainRatio` | integer | PRAAMS Ratio for the primary listing |
| `watchList` | boolean | Watchlist flag |
| `isBond` | boolean | Bond flag |
| `isSovereign` | boolean | Sovereign entity flag |
| `isUncategorized` | boolean | Uncategorized flag |
| `isETF` | boolean | ETF flag |
| `isCustom` | boolean | Custom asset flag |
| `isParent` | boolean | Whether this is the parent listing |
| `groupSize` | integer | Number of listings in the group |
| `children` | array | Child listings (usually empty) |
| `searchOrder` | number | Search ordering value |
| `etfAssetWeight` | number | ETF weight (0.0 for non-ETFs) |

#### `item.scores`

12 scoring dimensions, each an integer (1-10 scale, lower = better for risk, higher = better for return):

| Field | Type | Description |
|-------|------|-------------|
| `valuation` | integer | Valuation score |
| `performance` | integer | Performance score |
| `profitability` | integer | Profitability score |
| `growthMom` | integer | Growth momentum score |
| `other` | integer | Other risks score |
| `countryRisk` | integer | Country risk score |
| `liquidity` | integer | Liquidity risk score |
| `stressTest` | integer | Stress test score |
| `volatility` | integer | Volatility score |
| `solvency` | integer | Solvency/default risk score |
| `analystView` | integer | Analyst view score |
| `dividends` | integer | Dividend score |

#### `item.keyFactors`

| Field | Type | Description |
|-------|------|-------------|
| `risk.characteristic` | string | Overall risk characterization (e.g. `"Limited"`) |
| `risk.factors[]` | array | Key risk factors with `priority`, `text`, and `icon` (true=positive) |
| `return.characteristic` | string | Overall return characterization (e.g. `"Modest"`) |
| `return.factors[]` | array | Key return factors with `priority`, `text`, and `icon` (true=positive) |

#### `item.valuation`

| Field | Type | Description |
|-------|------|-------------|
| `descriptionShort` | object | `{short, long}` — valuation summary |
| `wams` | integer | Weighted average multiple score |
| `valuations[]` | array | Individual multiples with `name`, `score`, `ttm`, `ntm` |

Multiples include: P/E, PEG, P/B, P/S, P/FCF, EV/EBITDA. Note that `ntm` may be absent for some multiples (e.g. PEG, P/B, P/FCF).

#### `item.performance`

| Field | Type | Description |
|-------|------|-------------|
| `description` | object | `{short, long}` — performance summary |
| `byPeriods[]` | array | Period returns with `period`, `asset` (decimal), `peers` (decimal) |

#### `item.analystView`

| Field | Type | Description |
|-------|------|-------------|
| `description` | object | `{short, long}` — analyst consensus summary |
| `priceTarget` | object | `{currency, average, min, max}` — consensus price targets |
| `yearPriceHistory[]` | array | Price history data points `{id, value}` |
| `analystViewYearPriceHistory[]` | array | Analyst target price history `{id, value}` |
| `currency` | string | Currency of price history (may differ from `priceTarget.currency`) |
| `analystViewCurrency` | string | Currency of analyst price targets |

> **Note**: The ISIN endpoint may return `currency` and `analystViewCurrency` as different values (e.g. `"EUR"` for price history and `"USD"` for analyst targets) when the resolved listing trades in a different currency than the primary market.

#### `item.profitability`

| Field | Type | Description |
|-------|------|-------------|
| `description` | string | Profitability summary (e.g. `"Good"`) |
| `profitability[]` | array | Metrics (RoE, RoA, RoCE) with `name`, `description`, `assets` and `peers` objects containing TTM/NTM values and scores |
| `profitabilityGraph[]` | array | Margin graphs (Net margin, EBITDA margin) with `name`, `shortDesc`, and `graph[]` containing historical data points |
| `roICWACC` | object | RoIC/WACC analysis with `description` `{short, long}` and `score` |
| `profitabilityPeerMargins[]` | array | Peer margin comparison with `name`, `scoreTTM`, `scoreNTM` |

#### `item.growthMomentum`

| Field | Type | Description |
|-------|------|-------------|
| `description` | string | Growth summary (e.g. `"Average"`) |
| `absDescription` | string | Absolute growth description |
| `chgDescription` | string | Growth rate change description |
| `currencySize` | string | Currency for size metrics |
| `growthMomentum[]` | array | Metrics (EPS, Revenue, EBITDA, FCF) with `name`, `graph[]` and `growthRatesGraph[]` |

Each metric's `graph[]` contains `{order, label, value, isPrediction}` data points. The `growthRatesGraph[]` contains the same structure with year-over-year growth rates as decimals.

#### `item.dividend`

| Field | Type | Description |
|-------|------|-------------|
| `description` | object | `{short, long}` — dividend summary |
| `currency` | string | Dividend currency |
| `dividendPaid[]` | array | DPS history `{order, label, isPrediction}` — `value` field present only when dividends are paid |
| `annualDividendPayments[]` | array | Annual payments history `{order, label, isPrediction}` — `value` field present only when dividends are paid |
| `dividendYield[]` | array | Yield history `{order, label, isPrediction}` — `value` field present only when dividends are paid |
| `dividendsLast3Y` | number | Cumulative DPS over last 3 years (0.0 if no dividends) |
| `dividendsLast5Y` | number | Cumulative DPS over last 5 years (0.0 if no dividends) |

> **Note**: For non-dividend-paying stocks, the `dividendPaid`, `annualDividendPayments`, and `dividendYield` arrays contain entries with `order`, `label`, and `isPrediction` but no `value` field.

### Example Requests

```bash
curl "https://eodhd.com/api/mp/praams/analyse/equity/isin/US88160R1014?api_token=YOUR_API_TOKEN"
```

### Demo access

```bash
curl "https://eodhd.com/api/mp/praams/analyse/equity/isin/US88160R1014?api_token=demo"
```

### Notes

- **Marketplace product**: Requires a separate PRAAMS marketplace subscription, not included in main EODHD plans.
- **PRAAMS Ratio**: The flagship metric (`item.asset.ratio`) summarizes 470+ metrics into a single 1-10 score. Higher is better.
- **ISIN resolution**: The ISIN may resolve to a non-primary listing (e.g. `US88160R1014` resolves to `TL0.DE` rather than `TSLA`). The `profile.parentAsset` field indicates the primary listing. The `mainRatio` on the parent may differ from the `ratio` on the resolved listing.
- **Demo ISINs**: `US0378331005` (AAPL), `US88160R1014` (TSLA), and `US0231351067` (AMZN) are available with `api_token=demo`.
- **Coverage**: 120,000+ global equities. Use the ticker-based endpoint for direct ticker lookups (see praams-risk-scoring-by-ticker.md).
- **Profile section**: The ISIN endpoint includes an `item.profile` section (with `parentAsset`, `parentNote`, `companyProfileDescription`) that provides cross-listing information. This section may not be present in the ticker-based endpoint.
- **Currency differences**: When the ISIN resolves to a non-US listing, `description.currencyId` and `analystView.currency` may report in the local exchange currency (e.g. `EUR`), while `analystView.analystViewCurrency` and `profitability` metrics report in `USD`.
- **Score scale**: All 12 dimension scores in `item.scores` are integers. For risk dimensions (volatility, stressTest, liquidity, solvency, countryRisk, other), lower scores indicate lower risk. For return dimensions (valuation, performance, profitability, growthMom, analystView, dividends), higher scores indicate better return prospects.
- **Rich text descriptions**: Most sections include `short` (headline) and `long` (detailed paragraph) descriptions suitable for display to end users.
- **Peer comparisons**: Profitability and performance sections include peer benchmark data for the same sector/industry.
- **TTM vs NTM**: Valuation and profitability metrics include both trailing twelve months (TTM) and next twelve months (NTM, consensus estimates). Some multiples may lack NTM values.
- **Non-dividend stocks**: For companies that do not pay dividends, dividend arrays contain entries without `value` fields, and `dividendsLast3Y`/`dividendsLast5Y` are `0.0`.
- **Related endpoint**: Use `/analyse/equity/ticker/{ticker}` for ticker-based lookups (see praams-risk-scoring-by-ticker.md).

### HTTP Status Codes

| Status Code | Meaning | Description |
|-------------|---------|-------------|
| **200** | OK | Request succeeded. Data returned successfully. |
| **401** | Unauthorized | Invalid or missing API key. |
| **415** | Wrong Token | Token format is invalid. |
| **420** | Operation Cancelled | Request was cancelled. |
| **430** | Data Not Found | ISIN not found in PRAAMS database. |

### Error Response Format

When an error occurs, the API returns a JSON response:

```json
{
  "success": false,
  "message": "Error description",
  "errors": [
    {
      "code": "ERROR_CODE",
      "description": "Detailed error description"
    }
  ],
  "item": null
}
```

### Handling Errors

**Python Example**:
```python
import requests

def make_api_request(url, params):
    try:
        response = requests.get(url, params=params)
        response.raise_for_status()
        data = response.json()
        if not data.get("success"):
            errors = data.get("errors", [])
            for err in errors:
                print(f"API Error [{err.get('code')}]: {err.get('description')}")
            return None
        return data
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 401:
            print("Error: Invalid API key. Check your credentials.")
        elif e.response.status_code == 415:
            print("Error: Wrong token format.")
        elif e.response.status_code == 430:
            print("Error: ISIN not found in PRAAMS database.")
        else:
            print(f"HTTP Error: {e}")
        return None
    except requests.exceptions.RequestException as e:
        print(f"Request failed: {e}")
        return None
```

**Best Practices**:
- Always check `success` field in the response before processing `item`
- Implement exponential backoff for rate limit errors
- Cache responses to reduce API calls — PRAAMS data updates daily
- Monitor your API usage in the user dashboard

---

## Praams Equity Risk & Return Scoring by Ticker API

<a id="praams-risk-scoring-by-ticker"></a>

### Endpoint Metadata

| Field | Value |
|---|---|
| Status | complete |
| Source | marketplace (PRAAMS API) |
| Docs | https://eodhd.com/financial-apis/equity-risk-return-scoring-api |
| Provider | PRAAMS via EODHD Marketplace |
| Base URL | `https://eodhd.com/api/mp/praams` |
| Path | `/analyse/equity/ticker/{ticker}` |
| Method | GET |
| Auth | `api_token` query parameter |
| Slug | `praams-risk-scoring-by-ticker` |
| Source File | `/Users/arnaurodon/Projects/University/Final Thesis/eodhd-claude-skills/skills/eodhd-api/references/endpoints/praams-risk-scoring-by-ticker.md` |

### Purpose

Returns comprehensive risk and return analytics for a specific equity
identified by its ticker symbol. The response includes the proprietary PRAAMS
Ratio, individual risk and return scores across 12 dimensions, valuation
multiples, profitability metrics, growth momentum, dividend data, analyst
views, performance history, and detailed textual descriptions — providing
CFA-level analysis in a single API call.

**Use cases**:
- Instant risk-return assessment of any equity using the PRAAMS Ratio (1-10 scale)
- Detailed breakdown of 12 scoring dimensions (valuation, profitability, volatility, solvency, etc.)
- Valuation analysis with TTM and NTM multiples (P/E, PEG, P/B, P/S, P/FCF, EV/EBITDA)
- Performance tracking vs sector/industry peers
- Profitability analysis with margins, RoE, RoA, RoCE, and RoIC/WACC
- Growth momentum analysis (Revenue, EPS, EBITDA, FCF trends)
- Dividend history and yield analysis
- Analyst consensus price targets and recommendations
- Risk profiling: volatility, stress testing, liquidity, solvency, country risk

### Inputs

### Path (required)

| Parameter | Type | Description |
|-----------|------|-------------|
| `ticker` | string | Ticker symbol of the equity (e.g. `AAPL`, `TSLA`, `AMZN`) |

### Query (required)

| Parameter | Type | Description |
|-----------|------|-------------|
| `api_token` | string | Your API key (or `demo` for demo tickers) |

### Outputs

JSON object with top-level envelope:

| Field | Type | Description |
|-------|------|-------------|
| `success` | boolean | `true` if request succeeded |
| `message` | string | Status message (empty on success) |
| `errors` | array | Error objects with `code` and `description` (empty on success) |
| `item` | object | The main data payload |

### `item` object

Contains the following sections:

#### `item.asset`

| Field | Type | Description |
|-------|------|-------------|
| `ticker` | string | Ticker symbol |
| `name` | string | Company name |
| `isin` | string | ISIN identifier |
| `companyDescription` | string | Brief company description |
| `isActivelyTrading` | boolean | Whether the stock is currently trading |
| `assetId` | integer | Internal PRAAMS asset ID |
| `ratio` | integer | The PRAAMS Ratio (1-10 scale; higher = better risk-return) |
| `watchList` | boolean | Watchlist flag |
| `isBond` | boolean | Always `false` for equities |
| `isFinancial` | boolean | Whether the company is in the financial sector |

#### `item.description`

| Field | Type | Description |
|-------|------|-------------|
| `assetClass` | string | Always `"equity"` |
| `country` | string | Country code (e.g. `"US"`) |
| `sector` | string | Sector name (e.g. `"Technology"`) |
| `regionIds` | array of integers | Region identifiers |
| `countryId` | integer | Country identifier |
| `sectorId` | integer | Sector identifier |
| `industryId` | integer | Industry identifier |
| `currencyId` | string | Currency code (e.g. `"USD"`) |
| `otherRisks` | object | `{short, long}` — other risk assessment |
| `countryRisks` | object | `{short, long}` — country risk assessment |
| `liquidityRisk` | object | `{short, long}` — liquidity risk assessment |
| `stressTest` | object | `{short, long}` — stress test assessment |
| `volatility` | object | `{short, long}` — volatility assessment |
| `solvency` | object | `{short, long}` — solvency/default risk assessment |

Each risk object contains `short` (one-word rating like "Negligible", "Low", "Limited") and `long` (detailed explanation).

#### `item.scores`

12 scoring dimensions, each an integer (1-10 scale, lower = better for risk, higher = better for return):

| Field | Type | Description |
|-------|------|-------------|
| `valuation` | integer | Valuation score |
| `performance` | integer | Performance score |
| `profitability` | integer | Profitability score |
| `growthMom` | integer | Growth momentum score |
| `other` | integer | Other risks score |
| `countryRisk` | integer | Country risk score |
| `liquidity` | integer | Liquidity risk score |
| `stressTest` | integer | Stress test score |
| `volatility` | integer | Volatility score |
| `solvency` | integer | Solvency/default risk score |
| `analystView` | integer | Analyst view score |
| `dividends` | integer | Dividend score |

#### `item.keyFactors`

| Field | Type | Description |
|-------|------|-------------|
| `risk.characteristic` | string | Overall risk characterization (e.g. `"Low"`) |
| `risk.factors[]` | array | Key risk factors with `priority`, `text`, and `icon` (true=positive) |
| `return.characteristic` | string | Overall return characterization (e.g. `"Average"`) |
| `return.factors[]` | array | Key return factors with `priority`, `text`, and `icon` (true=positive) |

#### `item.valuation`

| Field | Type | Description |
|-------|------|-------------|
| `descriptionShort` | object | `{short, long}` — valuation summary |
| `wams` | integer | Weighted average multiple score |
| `valuations[]` | array | Individual multiples with `name`, `score`, `ttm`, `ntm` |

Multiples include: P/E, PEG, P/B, P/S, P/FCF, EV/EBITDA.

#### `item.performance`

| Field | Type | Description |
|-------|------|-------------|
| `description` | object | `{short, long}` — performance summary |
| `byPeriods[]` | array | Period returns with `period`, `asset` (decimal), `peers` (decimal) |

#### `item.analystView`

| Field | Type | Description |
|-------|------|-------------|
| `description` | object | `{short, long}` — analyst consensus summary |
| `priceTarget` | object | `{currency, average, min, max}` — consensus price targets |
| `yearPriceHistory[]` | array | Price history data points `{id, value}` |
| `currency` | string | Currency of prices |

#### `item.profitability`

| Field | Type | Description |
|-------|------|-------------|
| `description` | string | Profitability summary (e.g. `"Very strong"`) |
| `profitability[]` | array | Metrics (RoE, RoA, RoCE) with asset/peers TTM/NTM values and scores |
| `profitabilityGraph[]` | array | Margin graphs (Net margin, EBITDA margin) with historical data |
| `roICWACC` | object | RoIC/WACC analysis with `description` and `score` |

#### `item.growthMomentum`

| Field | Type | Description |
|-------|------|-------------|
| `description` | string | Growth summary (e.g. `"Average"`) |
| `absDescription` | string | Absolute growth description |
| `chgDescription` | string | Growth rate change description |
| `currencySize` | string | Currency for size metrics |
| `growthMomentum[]` | array | Metrics (EPS, Revenue, EBITDA, FCF) with `graph[]` and `growthRatesGraph[]` |

#### `item.dividend`

| Field | Type | Description |
|-------|------|-------------|
| `description` | object | `{short, long}` — dividend summary |
| `currency` | string | Dividend currency |
| `dividendPaid[]` | array | DPS history `{order, label, value, isPrediction}` |
| `annualDividendPayments[]` | array | Annual payments history |
| `dividendYield[]` | array | Yield history |
| `averageFrequency` | number | Average annual dividend payment frequency |
| `dividendsLast3Y` | number | Cumulative DPS over last 3 years |
| `dividendsLast5Y` | number | Cumulative DPS over last 5 years |

### Example Requests

```bash
curl "https://eodhd.com/api/mp/praams/analyse/equity/ticker/AAPL?api_token=YOUR_API_TOKEN"
```

### Demo access

```bash
curl "https://eodhd.com/api/mp/praams/analyse/equity/ticker/AAPL?api_token=demo"
```

### Notes

- **Marketplace product**: Requires a separate PRAAMS marketplace subscription, not included in main EODHD plans.
- **PRAAMS Ratio**: The flagship metric (`item.asset.ratio`) summarizes 470+ metrics into a single 1-10 score. Higher is better.
- **Demo tickers**: `AAPL`, `TSLA`, and `AMZN` are available with `api_token=demo`.
- **Coverage**: 120,000+ global equities. Use the ISIN-based endpoint for bond analysis.
- **Score scale**: All 12 dimension scores in `item.scores` are integers. For risk dimensions (volatility, stressTest, liquidity, solvency, countryRisk, other), lower scores indicate lower risk. For return dimensions (valuation, performance, profitability, growthMom, analystView, dividends), higher scores indicate better return prospects.
- **Rich text descriptions**: Most sections include `short` (headline) and `long` (detailed paragraph) descriptions suitable for display to end users.
- **Peer comparisons**: Profitability and performance sections include peer benchmark data for the same sector/industry.
- **TTM vs NTM**: Valuation and profitability metrics include both trailing twelve months (TTM) and next twelve months (NTM, consensus estimates).
- **Related endpoint**: Use `/analyse/equity/isin/{isin}` for ISIN-based lookups (see praams-risk-scoring-by-isin.md).

### HTTP Status Codes

| Status Code | Meaning | Description |
|-------------|---------|-------------|
| **200** | OK | Request succeeded. Data returned successfully. |
| **401** | Unauthorized | Invalid or missing API key. |
| **415** | Wrong Token | Token format is invalid. |
| **420** | Operation Cancelled | Request was cancelled. |
| **430** | Data Not Found | Ticker not found in PRAAMS database. |

### Error Response Format

When an error occurs, the API returns a JSON response:

```json
{
  "success": false,
  "message": "Error description",
  "errors": [
    {
      "code": "ERROR_CODE",
      "description": "Detailed error description"
    }
  ],
  "item": null
}
```

### Handling Errors

**Python Example**:
```python
import requests

def make_api_request(url, params):
    try:
        response = requests.get(url, params=params)
        response.raise_for_status()
        data = response.json()
        if not data.get("success"):
            errors = data.get("errors", [])
            for err in errors:
                print(f"API Error [{err.get('code')}]: {err.get('description')}")
            return None
        return data
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 401:
            print("Error: Invalid API key. Check your credentials.")
        elif e.response.status_code == 415:
            print("Error: Wrong token format.")
        elif e.response.status_code == 430:
            print("Error: Ticker not found in PRAAMS database.")
        else:
            print(f"HTTP Error: {e}")
        return None
    except requests.exceptions.RequestException as e:
        print(f"Request failed: {e}")
        return None
```

**Best Practices**:
- Always check `success` field in the response before processing `item`
- Implement exponential backoff for rate limit errors
- Cache responses to reduce API calls — PRAAMS data updates daily
- Monitor your API usage in the user dashboard

---

## Praams Smart Investment Screener Bond API

<a id="praams-smart-investment-screener-bond"></a>

### Endpoint Metadata

| Field | Value |
|---|---|
| Status | complete |
| Source | marketplace (PRAAMS API) |
| Docs | https://eodhd.com/financial-apis/equity-risk-return-scoring-api |
| Provider | PRAAMS via EODHD Marketplace |
| Base URL | `https://eodhd.com/api/mp/praams` |
| Path | `/explore/bond` |
| Method | POST |
| Auth | `api_token` query parameter |
| Slug | `praams-smart-investment-screener-bond` |
| Source File | `/Users/arnaurodon/Projects/University/Final Thesis/eodhd-claude-skills/skills/eodhd-api/references/endpoints/praams-smart-investment-screener-bond.md` |

### Purpose

Returns a filtered, paginated list of bonds matching user-defined criteria
across 12 risk-return dimensions, geography, sector, currency, yield, and
duration. This is a smart screener covering 120,000+ instruments including
corporate and sovereign bonds from US, UK, Europe, China, India, Middle East,
Asia & Oceania, LatAm, and Africa (both OTC and exchange-traded).

Users can find trade ideas like "bonds of European banks with high yields
with good growth loved by market analysts" in several seconds.

**Use cases**:
- Screen bonds by any combination of 12 risk-return scoring dimensions (1-7 scale)
- Filter by PRAAMS Ratio (mainRatio) for quick risk-return quality screening
- Filter by region, country, sector, and industry
- Filter by currency (ISO Alpha-3 codes)
- Filter by yield range and duration range
- Exclude subordinated bonds or perpetuals
- Paginate through large result sets with `skip`/`take`
- Sort results by any field using `orderBy`
- Build custom bond screening tools and watchlists

### Inputs

### Query (required)

| Parameter | Type | Description |
|-----------|------|-------------|
| `api_token` | string | Your API key |

### Query (optional — pagination)

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `skip` | integer | 0 | Number of records to skip |
| `take` | integer | — | Number of records to retrieve |

### Request Body (JSON) — Scoring Filters

All scoring filters use a 1-7 integer scale. Provide `*Min` and/or `*Max` to define a range. All are optional and nullable.

#### PRAAMS Ratio

| Field | Type | Description |
|-------|------|-------------|
| `mainRatioMin` | integer \| null | Minimum PRAAMS Ratio (1-7) |
| `mainRatioMax` | integer \| null | Maximum PRAAMS Ratio (1-7) |

#### Return factors (1-7)

| Field | Type | Description |
|-------|------|-------------|
| `valuationMin` / `valuationMax` | integer \| null | Valuation score range |
| `performanceMin` / `performanceMax` | integer \| null | Performance score range |
| `profitabilityMin` / `profitabilityMax` | integer \| null | Profitability score range |
| `growthMomMin` / `growthMomMax` | integer \| null | Growth momentum score range |
| `marketViewMin` / `marketViewMax` | integer \| null | Market view score range (bond-specific, replaces analystView) |
| `couponsMin` / `couponsMax` | integer \| null | Coupon score range (bond-specific, replaces dividends) |
| `analystViewMin` / `analystViewMax` | integer \| null | Analyst view score range |
| `dividendsMin` / `dividendsMax` | integer \| null | Dividends score range |

#### Risk factors (1-7)

| Field | Type | Description |
|-------|------|-------------|
| `otherMin` / `otherMax` | integer \| null | Other risks score range |
| `countryRiskMin` / `countryRiskMax` | integer \| null | Country risk score range |
| `liquidityMin` / `liquidityMax` | integer \| null | Liquidity risk score range |
| `stressTestMin` / `stressTestMax` | integer \| null | Stress test score range |
| `volatilityMin` / `volatilityMax` | integer \| null | Volatility score range |
| `solvencyMin` / `solvencyMax` | integer \| null | Solvency/default risk score range |

### Request Body (JSON) — Classification Filters

| Field | Type | Description |
|-------|------|-------------|
| `regions` | array of integers \| null | Region IDs (see Reference Tables below) |
| `countries` | array of integers \| null | Country IDs (see Reference Tables below) |
| `sectors` | array of integers \| null | Sector IDs (see Reference Tables below) |
| `industries` | array of integers \| null | Industry IDs (see Reference Tables below) |
| `capitalisation` | array of integers \| null | Market cap categories: `1`=Small, `2`=Mid, `3`=Large |
| `currency` | array of strings \| null | ISO Alpha-3 currency codes (e.g. `["EUR", "USD"]`) |

### Request Body (JSON) — Bond-Specific Filters

| Field | Type | Description |
|-------|------|-------------|
| `yieldMin` | integer \| null | Minimum yield filter |
| `yieldMax` | integer \| null | Maximum yield filter |
| `durationMin` | integer \| null | Minimum duration filter |
| `durationMax` | integer \| null | Maximum duration filter |
| `excludeSubordinated` | boolean \| null | Exclude subordinated bonds |
| `excludePerpetuals` | boolean \| null | Exclude perpetual bonds |

### Request Body (JSON) — Sorting

| Field | Type | Description |
|-------|------|-------------|
| `orderBy` | string \| null | Field name to sort results by |

### Outputs

JSON object with top-level envelope:

| Field | Type | Description |
|-------|------|-------------|
| `success` | boolean | `true` if request succeeded |
| `message` | string | Status message (empty on success) |
| `errors` | array | Error objects (empty on success) |
| `item` | object | The main data payload |

### `item` object

| Field | Type | Description |
|-------|------|-------------|
| `peers` | array | Array of matching bond records |
| `totalCount` | integer | Total number of matching bonds (for pagination) |

### `item.peers[]` record

Each peer record contains:

#### `assetInfo` object

| Field | Type | Description |
|-------|------|-------------|
| `assetId` | integer | Internal PRAAMS asset ID |
| `ratio` | integer | PRAAMS Ratio (1-10 scale) |
| `watchList` | boolean | Watchlist flag |
| `isBond` | boolean | Always `true` for bond screener |
| `bondType` | string | Bond classification (e.g. `"Corporate"`) |
| `isFinancial` | boolean | Whether the issuer is in the financial sector |
| `ticker` | string | Bond description (e.g. `"ACA.PA 1.3% 08-Feb-27"`) |
| `name` | string | Issuer name |
| `isin` | string | ISIN identifier |
| `companyDescription` | string | Issuer description (may be empty) |
| `isActivelyTrading` | boolean | Whether the bond is currently trading |

#### Scoring fields (top-level in peer record)

| Field | Type | Description |
|-------|------|-------------|
| `riskWatch` | string | Overall risk characterization (e.g. `"Limited"`) |
| `returnWatch` | string | Overall return characterization (e.g. `"Strong"`) |
| `amountOutstanding` | integer | Amount outstanding category |
| `marketView` | integer | Market view score (bond-specific) |
| `coupon` | integer | Coupon score (bond-specific) |
| `valuation` | integer | Valuation score |
| `performance` | integer | Performance score |
| `profitability` | integer | Issuer profitability score |
| `growthMom` | integer | Issuer growth momentum score |
| `other` | integer | Other risks score |
| `countryRisk` | integer | Country risk score |
| `liquidity` | integer | Liquidity risk score |
| `stressTest` | integer | Stress test score |
| `volatility` | integer | Volatility score |
| `solvency` | integer | Solvency/default risk score |

### Example Requests

```bash
curl -X POST \
  'https://eodhd.com/api/mp/praams/explore/bond?skip=0&take=3&api_token=YOUR_API_TOKEN' \
  -H 'Content-Type: application/json' \
  -d '{
    "growthMomMin": 4,
    "growthMomMax": 7,
    "regions": [3],
    "sectors": [6],
    "currency": ["EUR"],
    "marketViewMin": 4,
    "marketViewMax": 7,
    "yieldMin": 7,
    "yieldMax": 15
  }'
```

### Notes

- **Marketplace product**: Requires a separate PRAAMS Smart Investment Screener marketplace subscription, not included in main EODHD plans.
- **POST method**: Unlike most EODHD endpoints, this is a POST endpoint with a JSON request body for filters. The `api_token` is still passed as a query parameter.
- **At least one filter required**: The request body must contain at least one filter (regions, sectors, currency, or any `*Min`/`*Max` scoring field).
- **Scoring scale**: All `*Min`/`*Max` scoring filters use a 1-7 integer scale. For risk dimensions, lower = less risky. For return dimensions, higher = better.
- **Bond-specific fields**: The bond screener includes `marketView` (instead of `analystView`), `coupon` (instead of `dividends`), `amountOutstanding`, `bondType`, and bond-specific filters (`yieldMin`/`yieldMax`, `durationMin`/`durationMax`, `excludeSubordinated`, `excludePerpetuals`).
- **Pagination**: Use `skip` and `take` query parameters. The response `totalCount` tells you how many total matches exist.
- **Coverage**: Corporate and sovereign bonds from US, UK, Europe, China, India, Middle East, Asia & Oceania, LatAm, and Africa — both OTC and exchange-traded.
- **Currency filter**: Uses ISO Alpha-3 currency codes (e.g. `"EUR"`, `"USD"`, `"GBP"`).
- **Scoring scales**: Filter parameters accept values 1-7 (risk tolerance/investment preference), while response `ratio` values are on a 1-10 scale (composite scoring). These are different scales serving different purposes.
- **Related endpoint**: Use `/explore/equity` for equity screening (see praams-smart-investment-screener-equity.md).

### HTTP Status Codes

| Status Code | Meaning | Description |
|-------------|---------|-------------|
| **200** | OK | Request succeeded. Data returned successfully. |
| **401** | Unauthorized | Invalid or missing API key. |
| **415** | Unsupported Media Type | Wrong content type (must be `application/json`). |
| **420** | Operation Cancelled | Request was cancelled. |
| **430** | Data Not Found | No data found for the given filters. |

### Error Response Format

When an error occurs, the API returns a JSON response:

```json
{
  "success": false,
  "message": "Error description",
  "errors": [
    {
      "code": "ERROR_CODE",
      "description": "Detailed error description"
    }
  ],
  "item": null
}
```

### Handling Errors

**Python Example**:
```python
import requests

def make_api_request(url, params, json_body):
    try:
        response = requests.post(url, params=params, json=json_body)
        response.raise_for_status()
        data = response.json()
        if not data.get("success"):
            errors = data.get("errors", [])
            for err in errors:
                print(f"API Error [{err.get('code')}]: {err.get('description')}")
            return None
        return data
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 401:
            print("Error: Invalid API key. Check your credentials.")
        elif e.response.status_code == 415:
            print("Error: Content-Type must be application/json.")
        elif e.response.status_code == 430:
            print("Error: No data found for the given filters.")
        else:
            print(f"HTTP Error: {e}")
        return None
    except requests.exceptions.RequestException as e:
        print(f"Request failed: {e}")
        return None
```

**Best Practices**:
- Always check `success` field in the response before processing `item`
- Use `totalCount` for pagination logic
- Implement exponential backoff for rate limit errors
- Start with broad filters, then narrow down to find specific trade ideas
- Monitor your API usage in the user dashboard

---

## Praams Smart Investment Screener Equity API

<a id="praams-smart-investment-screener-equity"></a>

### Endpoint Metadata

| Field | Value |
|---|---|
| Status | complete |
| Source | marketplace (PRAAMS API) |
| Docs | https://eodhd.com/financial-apis/equity-risk-return-scoring-api |
| Provider | PRAAMS via EODHD Marketplace |
| Base URL | `https://eodhd.com/api/mp/praams` |
| Path | `/explore/equity` |
| Method | POST |
| Auth | `api_token` query parameter |
| Slug | `praams-smart-investment-screener-equity` |
| Source File | `/Users/arnaurodon/Projects/University/Final Thesis/eodhd-claude-skills/skills/eodhd-api/references/endpoints/praams-smart-investment-screener-equity.md` |

### Purpose

Returns a filtered, paginated list of equities matching user-defined criteria
across 12 risk-return dimensions, geography, sector, currency, and market
capitalization. This is a smart screener covering 120,000+ instruments
including stocks from US, UK, Europe, China, India, Middle East, Asia & Oceania,
LatAm, and Africa (including small & micro-caps).

Users can find trade ideas like "undervalued Chinese IT stocks with high
dividends and low credit risk" in several seconds.

**Use cases**:
- Screen equities by any combination of 12 risk-return scoring dimensions (1-7 scale)
- Filter by PRAAMS Ratio (mainRatio) for quick risk-return quality screening
- Filter by region, country, sector, and industry
- Filter by market capitalization (small, mid, large)
- Filter by currency (ISO Alpha-3 codes)
- Paginate through large result sets with `skip`/`take`
- Sort results by any field using `orderBy`
- Build custom equity screening tools and watchlists

### Inputs

### Query (required)

| Parameter | Type | Description |
|-----------|------|-------------|
| `api_token` | string | Your API key |

### Query (optional — pagination)

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `skip` | integer | 0 | Number of records to skip |
| `take` | integer | — | Number of records to retrieve |

### Request Body (JSON) — Scoring Filters

All scoring filters use a 1-7 integer scale. Provide `*Min` and/or `*Max` to define a range. All are optional and nullable.

#### PRAAMS Ratio

| Field | Type | Description |
|-------|------|-------------|
| `mainRatioMin` | integer \| null | Minimum PRAAMS Ratio (1-7) |
| `mainRatioMax` | integer \| null | Maximum PRAAMS Ratio (1-7) |

#### Return factors (1-7)

| Field | Type | Description |
|-------|------|-------------|
| `valuationMin` / `valuationMax` | integer \| null | Valuation score range |
| `performanceMin` / `performanceMax` | integer \| null | Performance score range |
| `profitabilityMin` / `profitabilityMax` | integer \| null | Profitability score range |
| `growthMomMin` / `growthMomMax` | integer \| null | Growth momentum score range |
| `analystViewMin` / `analystViewMax` | integer \| null | Analyst view score range |
| `dividendsMin` / `dividendsMax` | integer \| null | Dividends score range |

#### Risk factors (1-7)

| Field | Type | Description |
|-------|------|-------------|
| `otherMin` / `otherMax` | integer \| null | Other risks score range |
| `countryRiskMin` / `countryRiskMax` | integer \| null | Country risk score range |
| `liquidityMin` / `liquidityMax` | integer \| null | Liquidity risk score range |
| `stressTestMin` / `stressTestMax` | integer \| null | Stress test score range |
| `volatilityMin` / `volatilityMax` | integer \| null | Volatility score range |
| `solvencyMin` / `solvencyMax` | integer \| null | Solvency/default risk score range |

### Request Body (JSON) — Classification Filters

| Field | Type | Description |
|-------|------|-------------|
| `regions` | array of integers \| null | Region IDs (see Reference Tables below) |
| `countries` | array of integers \| null | Country IDs (see Reference Tables below) |
| `sectors` | array of integers \| null | Sector IDs (see Reference Tables below) |
| `industries` | array of integers \| null | Industry IDs (see Reference Tables below) |
| `capitalisation` | array of integers \| null | Market cap categories: `1`=Small, `2`=Mid, `3`=Large |
| `currency` | array of strings \| null | ISO Alpha-3 currency codes (e.g. `["USD", "CNY"]`) |

### Request Body (JSON) — Sorting

| Field | Type | Description |
|-------|------|-------------|
| `orderBy` | string \| null | Field name to sort results by |

### Outputs

JSON object with top-level envelope:

| Field | Type | Description |
|-------|------|-------------|
| `success` | boolean | `true` if request succeeded |
| `message` | string | Status message (empty on success) |
| `errors` | array | Error objects (empty on success) |
| `item` | object | The main data payload |

### `item` object

| Field | Type | Description |
|-------|------|-------------|
| `peers` | array | Array of matching equity records |
| `totalCount` | integer | Total number of matching equities (for pagination) |

### `item.peers[]` record

Each peer record contains:

#### `assetInfo` object

| Field | Type | Description |
|-------|------|-------------|
| `assetId` | integer | Internal PRAAMS asset ID |
| `ratio` | integer | PRAAMS Ratio (1-10 scale) |
| `watchList` | boolean | Watchlist flag |
| `isBond` | boolean | Always `false` for equity screener |
| `isFinancial` | boolean | Whether the company is in the financial sector |
| `ticker` | string | Ticker symbol (e.g. `"688618.SS"`, `"AACAF"`) |
| `name` | string | Company name |
| `isin` | string | ISIN identifier |
| `companyDescription` | string | Company description (may be empty) |
| `isActivelyTrading` | boolean | Whether the stock is currently trading |

#### Scoring fields (top-level in peer record)

| Field | Type | Description |
|-------|------|-------------|
| `riskWatch` | string | Overall risk characterization (e.g. `"High"`, `"Moderate"`) |
| `returnWatch` | string | Overall return characterization (e.g. `"Average"`, `"Favourable"`) |
| `marketCap` | integer | Market cap category (1=Small, 2=Mid, 3=Large) |
| `analystView` | integer | Analyst view score (0 = no data) |
| `dividends` | integer | Dividends score |
| `valuation` | integer | Valuation score |
| `performance` | integer | Performance score |
| `profitability` | integer | Profitability score |
| `growthMom` | integer | Growth momentum score |
| `other` | integer | Other risks score |
| `countryRisk` | integer | Country risk score |
| `liquidity` | integer | Liquidity risk score |
| `stressTest` | integer | Stress test score |
| `volatility` | integer | Volatility score |
| `solvency` | integer | Solvency/default risk score |

### Example Requests

```bash
curl -X POST \
  'https://eodhd.com/api/mp/praams/explore/equity?skip=0&take=3&api_token=YOUR_API_TOKEN' \
  -H 'Content-Type: application/json' \
  -d '{
    "solvencyMin": 1,
    "solvencyMax": 4,
    "countries": [23],
    "sectors": [10],
    "dividendsMin": 4,
    "dividendsMax": 7
  }'
```

### Notes

- **Marketplace product**: Requires a separate PRAAMS Smart Investment Screener marketplace subscription, not included in main EODHD plans.
- **POST method**: Unlike most EODHD endpoints, this is a POST endpoint with a JSON request body for filters. The `api_token` is still passed as a query parameter.
- **At least one filter required**: The request body must contain at least one filter (countries, sectors, currency, or any `*Min`/`*Max` scoring field).
- **Scoring scale**: All `*Min`/`*Max` scoring filters use a 1-7 integer scale. For risk dimensions, lower = less risky. For return dimensions, higher = better.
- **Equity-specific fields**: The equity screener uses `analystView` (instead of `marketView`), `dividends` (instead of `coupon`), and `marketCap` (instead of `amountOutstanding`). It does not have bond-specific filters like yield, duration, excludeSubordinated, or excludePerpetuals.
- **Score of 0**: A score of `0` in the response (e.g. `analystView: 0`) indicates insufficient data for that dimension.
- **Pagination**: Use `skip` and `take` query parameters. The response `totalCount` tells you how many total matches exist. For example, with `totalCount: 71`, you can page through with `skip=0&take=20`, `skip=20&take=20`, etc.
- **Coverage**: Stocks from US, UK, Europe, China, India, Middle East, Asia & Oceania, LatAm, and Africa, including small & micro-caps.
- **Currency filter**: Uses ISO Alpha-3 currency codes (e.g. `"USD"`, `"EUR"`, `"CNY"`).
- **Scoring scales**: Filter parameters accept values 1-7 (risk tolerance/investment preference), while response `ratio` values are on a 1-10 scale (composite scoring). These are different scales serving different purposes.
- **Related endpoint**: Use `/explore/bond` for bond screening (see praams-smart-investment-screener-bond.md).

### HTTP Status Codes

| Status Code | Meaning | Description |
|-------------|---------|-------------|
| **200** | OK | Request succeeded. Data returned successfully. |
| **401** | Unauthorized | Invalid or missing API key. |
| **415** | Unsupported Media Type | Wrong content type (must be `application/json`). |
| **420** | Operation Cancelled | Request was cancelled. |
| **430** | Data Not Found | No data found for the given filters. |

### Error Response Format

When an error occurs, the API returns a JSON response:

```json
{
  "success": false,
  "message": "Error description",
  "errors": [
    {
      "code": "ERROR_CODE",
      "description": "Detailed error description"
    }
  ],
  "item": null
}
```

### Handling Errors

**Python Example**:
```python
import requests

def make_api_request(url, params, json_body):
    try:
        response = requests.post(url, params=params, json=json_body)
        response.raise_for_status()
        data = response.json()
        if not data.get("success"):
            errors = data.get("errors", [])
            for err in errors:
                print(f"API Error [{err.get('code')}]: {err.get('description')}")
            return None
        return data
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 401:
            print("Error: Invalid API key. Check your credentials.")
        elif e.response.status_code == 415:
            print("Error: Content-Type must be application/json.")
        elif e.response.status_code == 430:
            print("Error: No data found for the given filters.")
        else:
            print(f"HTTP Error: {e}")
        return None
    except requests.exceptions.RequestException as e:
        print(f"Request failed: {e}")
        return None
```

**Best Practices**:
- Always check `success` field in the response before processing `item`
- Use `totalCount` for pagination logic
- Implement exponential backoff for rate limit errors
- Start with broad filters, then narrow down to find specific trade ideas
- Monitor your API usage in the user dashboard

---

## Sentiment Data API

<a id="sentiment-data"></a>

### Endpoint Metadata

| Field | Value |
|---|---|
| Status | complete |
| Source | financial-apis (Financial News Feed and Stock News Sentiment data API) |
| Docs | https://eodhd.com/financial-apis/financial-news-api |
| Provider | EODHD |
| Base URL | https://eodhd.com/api |
| Path | /sentiments |
| Method | GET |
| Auth | api_token (query) |
| Slug | `sentiment-data` |
| Source File | `/Users/arnaurodon/Projects/University/Final Thesis/eodhd-claude-skills/skills/eodhd-api/references/endpoints/sentiment-data.md` |

### Purpose

Get aggregated daily sentiment scores for one or more financial instruments (stocks, ETFs, crypto, forex).
Sentiment scores are calculated from news and social media, normalized on a scale from -1 (very negative)
to +1 (very positive). Useful for sentiment trend analysis, trading signals, and market mood tracking.

**API Call Consumption**: 5 API calls per request + 5 API calls per ticker.

### Inputs

| Parameter | Required | Type | Description |
|-----------|----------|------|-------------|
| s | Yes | string | One or more comma-separated tickers (e.g., AAPL.US,BTC-USD.CC) |
| from | No | string (YYYY-MM-DD) | Start date for filtering sentiment data |
| to | No | string (YYYY-MM-DD) | End date for filtering sentiment data |
| api_token | Yes | string | Your API access token |
| fmt | No | string | Response format: json (default) |

### Outputs

Sentiment data is grouped by ticker symbol. Each entry represents one day's aggregated sentiment:

```json
{
  "BTC-USD.CC": [
    {
      "date": "2022-02-22",
      "count": 8,
      "normalized": -0.1811
    },
    {
      "date": "2022-02-21",
      "count": 5,
      "normalized": 0.2824
    }
  ],
  "AAPL.US": [
    {
      "date": "2022-02-22",
      "count": 23,
      "normalized": 0.6152
    },
    {
      "date": "2022-02-21",
      "count": 23,
      "normalized": 0.3668
    }
  ]
}
```

### Field Descriptions

| Field | Type | Description |
|-------|------|-------------|
| date | string (YYYY-MM-DD) | Date of sentiment aggregation |
| count | integer | Number of articles used for sentiment calculation |
| normalized | float | Sentiment score between -1 (very negative) and +1 (very positive) |

### Sentiment Score Interpretation

| Score Range | Interpretation |
|-------------|----------------|
| 0.6 to 1.0 | Very positive sentiment |
| 0.2 to 0.6 | Positive sentiment |
| -0.2 to 0.2 | Neutral sentiment |
| -0.6 to -0.2 | Negative sentiment |
| -1.0 to -0.6 | Very negative sentiment |

### Example Requests

```bash
# Single ticker sentiment
curl "https://eodhd.com/api/sentiments?s=AAPL.US&from=2025-01-01&to=2025-01-31&api_token=demo&fmt=json"

# Multiple tickers sentiment
curl "https://eodhd.com/api/sentiments?s=btc-usd.cc,aapl.us&from=2022-01-01&to=2022-02-22&api_token=demo&fmt=json"

# Crypto sentiment
curl "https://eodhd.com/api/sentiments?s=BTC-USD.CC,ETH-USD.CC&from=2025-01-01&to=2025-01-15&api_token=demo&fmt=json"

# Using the helper client
python eodhd_client.py --endpoint sentiment --symbol AAPL.US --from-date 2025-01-01 --to-date 2025-01-31

# Multiple symbols
python eodhd_client.py --endpoint sentiment --symbol "AAPL.US,MSFT.US,GOOGL.US" --from-date 2025-01-01
```

### Notes

- Sentiment is aggregated daily from news articles and social media mentions
- `count` indicates data quality - higher counts mean more reliable sentiment scores
- Days with no news coverage may be missing from the response
- Sentiment scores are normalized: -1 = very negative, 0 = neutral, +1 = very positive
- Works for stocks, ETFs, cryptocurrencies, and forex pairs
- Results are sorted by date (most recent first)
- Available in: Standalone package, All-In-One, EOD Historical Data, Fundamentals Data Feed, Free plan
- **Symbols limit**: Maximum **100 symbols** per request.
- **News sources**: Built upon news collected by EODHD. The news is English-language based but not limited to US-only sources.
- **Data depth**: Sentiment data is available from **2018** onwards.
- **Analysis technique**: Sentiment analysis uses NLP-based techniques similar to NLTK sentiment analysis (see: https://www.digitalocean.com/community/tutorials/how-to-perform-sentiment-analysis-in-python-3-using-the-natural-language-toolkit-nltk).

### HTTP Status Codes

The API returns standard HTTP status codes to indicate success or failure:

| Status Code | Meaning | Description |
|-------------|---------|-------------|
| **200** | OK | Request succeeded. Data returned successfully. |
| **402** | Payment Required | API limit used up. Upgrade plan or wait for limit reset. |
| **403** | Unauthorized | Invalid API key. Check your `api_token` parameter. |
| **429** | Too Many Requests | Exceeded rate limit (requests per minute). Slow down requests. |

### Error Response Format

When an error occurs, the API returns a JSON response with error details:

```json
{
  "error": "Error message description",
  "code": 403
}
```

### Handling Errors

**Python Example**:
```python
import requests

def make_api_request(url, params):
    try:
        response = requests.get(url, params=params)
        response.raise_for_status()  # Raises HTTPError for bad status codes
        return response.json()
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 402:
            print("Error: API limit exceeded. Please upgrade your plan.")
        elif e.response.status_code == 403:
            print("Error: Invalid API key. Check your credentials.")
        elif e.response.status_code == 429:
            print("Error: Rate limit exceeded. Please slow down your requests.")
        else:
            print(f"HTTP Error: {e}")
        return None
    except requests.exceptions.RequestException as e:
        print(f"Request failed: {e}")
        return None
```

**Best Practices**:
- Always check status codes before processing response data
- Implement exponential backoff for 429 errors
- Cache responses to reduce API calls
- Monitor your API usage in the user dashboard

---

## Stock Market Logos API (SVG Extension)

<a id="stock-market-logos-svg"></a>

### Endpoint Metadata

| Field | Value |
|---|---|
| Status | complete |
| Source | marketplace (Unicorn Data Services) |
| Docs | https://eodhd.com/financial-apis/stock-market-logos-api |
| Provider | Unicorn Data Services via EODHD Marketplace |
| Base URL | `https://eodhd.com/api` |
| Path | `/logo-svg/{symbol}` |
| Method | GET |
| Auth | `api_token` query parameter |
| Slug | `stock-market-logos-svg` |
| Source File | `/Users/arnaurodon/Projects/University/Final Thesis/eodhd-claude-skills/skills/eodhd-api/references/endpoints/stock-market-logos-svg.md` |

### Purpose

Returns the logo image in SVG format for a specified stock exchange ticker symbol.
SVG format is only available for US and TO (Toronto) exchanges. This endpoint is
useful for applications that need scalable vector graphics for high-resolution
displays, printing, or responsive layouts where logos need to scale without
quality loss.

This is an extended version of the Stock Market Logos API (see stock-market-logos.md
for the PNG version covering 60+ exchanges).

**Use cases**:
- Display company logos at any resolution without quality loss
- Build high-DPI / Retina-ready financial dashboards
- Generate print-quality reports and presentations with company logos
- Use in responsive web designs where logos need to scale dynamically

### Inputs

### Path (required)

| Parameter | Type | Description |
|-----------|------|-------------|
| `symbol` | string | Ticker symbol in `{ticker}.{exchange}` format. SVG is only available for US and TO exchanges (e.g. `AAPL.US`, `MSFT.US`, `SHOP.TO`) |

### Query (required)

| Parameter | Type | Description |
|-----------|------|-------------|
| `api_token` | string | Your API key (or `demo` for demo access) |

### Example Requests

```bash
# Download Apple logo (SVG)
curl -o AAPL_logo.svg "https://eodhd.com/api/logo-svg/AAPL.US?api_token=demo"

# Download Microsoft logo (SVG)
curl -o MSFT_logo.svg "https://eodhd.com/api/logo-svg/MSFT.US?api_token=demo"

# Download Shopify logo (Toronto)
curl -o SHOP_logo.svg "https://eodhd.com/api/logo-svg/SHOP.TO?api_token=demo"
```

### Python Example

```python
import requests

def download_logo_svg(symbol, api_token, output_path=None):
    """Download a company logo as SVG."""
    url = f"https://eodhd.com/api/logo-svg/{symbol}"
    params = {"api_token": api_token}

    response = requests.get(url, params=params)
    response.raise_for_status()

    if output_path is None:
        ticker = symbol.replace(".", "_")
        output_path = f"{ticker}_logo.svg"

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(response.text)

    return output_path

# Demo usage
path = download_logo_svg("AAPL.US", "demo")
print(f"Logo saved to: {path}")
```

### Batch Download Example

```python
import requests
import time

def download_logos_svg_batch(symbols, api_token, output_dir="."):
    """Download SVG logos for multiple symbols."""
    for symbol in symbols:
        url = f"https://eodhd.com/api/logo-svg/{symbol}"
        params = {"api_token": api_token}

        try:
            response = requests.get(url, params=params)
            response.raise_for_status()

            ticker = symbol.replace(".", "_")
            path = f"{output_dir}/{ticker}_logo.svg"
            with open(path, "w", encoding="utf-8") as f:
                f.write(response.text)
            print(f"Downloaded: {symbol}")
        except requests.exceptions.HTTPError as e:
            print(f"Failed: {symbol} - {e}")

        time.sleep(0.1)  # Rate limiting

# Usage (US and TO exchanges only)
symbols = ["AAPL.US", "MSFT.US", "TSLA.US", "AMZN.US", "SHOP.TO"]
download_logos_svg_batch(symbols, "YOUR_API_TOKEN")
```

### Notes

- **URL path**: This endpoint uses `/logo-svg/` (not `/mp/` like other Marketplace products).
- **Marketplace product**: Requires a separate Unicorn Data Services marketplace subscription, not included in main EODHD plans.
- **SVG response**: Unlike most EODHD endpoints that return JSON, this endpoint returns an SVG XML document. Use text mode for writing (not binary).
- **Limited exchange coverage**: SVG format is only available for US and TO exchanges. For other exchanges, use the PNG endpoint (`/logo/{symbol}`).
- **Scalable**: SVG logos can be scaled to any size without quality loss, unlike the fixed 200x200px PNG logos.
- **Symbol format**: Use the standard `{ticker}.{exchange}` format (e.g. `AAPL.US`, `SHOP.TO`).
- **Demo access**: The demo API key works with any supported ticker.
- **Related endpoint**: Use `/logo/{symbol}` for PNG logos covering 60+ exchanges (see stock-market-logos.md).

### HTTP Status Codes

| Status Code | Meaning | Description |
|-------------|---------|-------------|
| **200** | OK | SVG image returned successfully. |
| **401** | Unauthorized | Invalid or missing API key. |
| **403** | Forbidden | Access denied (subscription required). |
| **404** | Not Found | Logo not available for the specified ticker. |
| **429** | Too Many Requests | Rate limit exceeded. |

---

## Stock Market Logos API

<a id="stock-market-logos"></a>

### Endpoint Metadata

| Field | Value |
|---|---|
| Status | complete |
| Source | marketplace (Unicorn Data Services) |
| Docs | https://eodhd.com/financial-apis/stock-market-logos-api |
| Provider | Unicorn Data Services via EODHD Marketplace |
| Base URL | `https://eodhd.com/api` |
| Path | `/logo/{symbol}` |
| Method | GET |
| Auth | `api_token` query parameter |
| Slug | `stock-market-logos` |
| Source File | `/Users/arnaurodon/Projects/University/Final Thesis/eodhd-claude-skills/skills/eodhd-api/references/endpoints/stock-market-logos.md` |

### Purpose

Returns the logo image for a specified stock exchange ticker symbol as a 200x200px
PNG file with transparency. The largest collection of 40,000+ stock market company
logos available via a single API endpoint, covering 60+ exchanges worldwide.

**Use cases**:
- Display company logos alongside stock information in applications
- Build visually rich financial dashboards and portfolio trackers
- Enhance stock screener or watchlist UIs with company branding
- Generate reports or presentations with company logos

### Inputs

### Path (required)

| Parameter | Type | Description |
|-----------|------|-------------|
| `symbol` | string | Ticker symbol in `{ticker}.{exchange}` format (e.g. `AAPL.US`, `BMW.XETRA`, `0700.HK`) |

### Query (required)

| Parameter | Type | Description |
|-----------|------|-------------|
| `api_token` | string | Your API key (or `demo` for demo access) |

### Example Requests

```bash
# Download Apple logo
curl -o AAPL_logo.png "https://eodhd.com/api/logo/AAPL.US?api_token=demo"

# Download BMW logo (XETRA)
curl -o BMW_logo.png "https://eodhd.com/api/logo/BMW.XETRA?api_token=demo"

# Download Tencent logo (Hong Kong)
curl -o Tencent_logo.png "https://eodhd.com/api/logo/0700.HK?api_token=demo"
```

### Python Example

```python
import requests

def download_logo(symbol, api_token, output_path=None):
    """Download a company logo as PNG."""
    url = f"https://eodhd.com/api/logo/{symbol}"
    params = {"api_token": api_token}

    response = requests.get(url, params=params)
    response.raise_for_status()

    if output_path is None:
        ticker = symbol.replace(".", "_")
        output_path = f"{ticker}_logo.png"

    with open(output_path, "wb") as f:
        f.write(response.content)

    return output_path

# Demo usage
path = download_logo("AAPL.US", "demo")
print(f"Logo saved to: {path}")
```

### Batch Download Example

```python
import requests
import time

def download_logos_batch(symbols, api_token, output_dir="."):
    """Download logos for multiple symbols."""
    for symbol in symbols:
        url = f"https://eodhd.com/api/logo/{symbol}"
        params = {"api_token": api_token}

        try:
            response = requests.get(url, params=params)
            response.raise_for_status()

            ticker = symbol.replace(".", "_")
            path = f"{output_dir}/{ticker}_logo.png"
            with open(path, "wb") as f:
                f.write(response.content)
            print(f"Downloaded: {symbol}")
        except requests.exceptions.HTTPError as e:
            print(f"Failed: {symbol} - {e}")

        time.sleep(0.1)  # Rate limiting

# Usage
symbols = ["AAPL.US", "MSFT.US", "TSLA.US", "AMZN.US", "GOOGL.US"]
download_logos_batch(symbols, "YOUR_API_TOKEN")
```

### Notes

- **URL path**: This endpoint uses `/logo/` (not `/mp/` like other Marketplace products).
- **Marketplace product**: Requires a separate Unicorn Data Services marketplace subscription, not included in main EODHD plans.
- **PNG response**: Unlike most EODHD endpoints that return JSON, this endpoint returns a binary PNG image. Use appropriate file handling (binary write mode).
- **Image format**: All logos are 200x200px PNG files with transparency.
- **Symbol format**: Use the standard `{ticker}.{exchange}` format (e.g. `AAPL.US`, `BMW.XETRA`).
- **Full ticker list**: Available as an Excel file (logos_list.xlsx) from the Marketplace product page.
- **Caching**: Logo images change infrequently. Cache aggressively to reduce API calls.
- **Demo access**: The demo API key works with any supported ticker.

### HTTP Status Codes

| Status Code | Meaning | Description |
|-------------|---------|-------------|
| **200** | OK | PNG image returned successfully. |
| **401** | Unauthorized | Invalid or missing API key. |
| **403** | Forbidden | Access denied (subscription required). |
| **404** | Not Found | Logo not available for the specified ticker. |
| **429** | Too Many Requests | Rate limit exceeded. |

---

## Stock Screener API

<a id="stock-screener-data"></a>

### Endpoint Metadata

| Field | Value |
|---|---|
| Status | complete |
| Source | financial-apis (Stock Market Screener API) |
| Docs | https://eodhd.com/financial-apis/stock-market-screener-api |
| Provider | EODHD |
| Base URL | https://eodhd.com/api |
| Path | /screener |
| Method | GET |
| Auth | api_token (query) |
| Slug | `stock-screener-data` |
| Source File | `/Users/arnaurodon/Projects/University/Final Thesis/eodhd-claude-skills/skills/eodhd-api/references/endpoints/stock-screener-data.md` |

### Purpose

Screen and filter stocks based on fundamental metrics, market cap, sector, exchange,
and other criteria. Returns a list of matching symbols with key metrics.

### Inputs

| Parameter | Required | Type | Description |
|-----------|----------|------|-------------|
| api_token | Yes | string | EODHD API key |
| sort | No | string | Field to sort by (e.g., market_capitalization, name) |
| order | No | string | Sort order: 'a' (ascending) or 'd' (descending) |
| limit | No | integer | Number of results (default 50, max 100) |
| offset | No | integer | Pagination offset |
| filters | No | string | JSON array of filter conditions (see below) |

### Outputs

Array of matching stocks with key metrics:

```json
{
  "count": 150,
  "data": [
    {
      "code": "AAPL",
      "name": "Apple Inc",
      "exchange": "NASDAQ",
      "sector": "Technology",
      "industry": "Consumer Electronics",
      "market_capitalization": 2500000000000,
      "earnings_share": 6.15,
      "dividend_yield": 0.005,
      "pe": 28.5,
      "peg": 2.1,
      "pb": 41.5,
      "ps": 6.5,
      "roe": 147.5,
      "roa": 21.5,
      "beta": 1.25,
      "refund_1d_p": 0.5,
      "refund_5d_p": 2.1,
      "refund_ytd_p": 15.3
    }
  ]
}
```

### Example Requests

```bash
# Large-cap tech stocks
curl 'https://eodhd.com/api/screener?api_token=demo&fmt=json&filters=[["market_capitalization",">",100000000000],["sector","=","Technology"]]'

# High dividend yield stocks
curl 'https://eodhd.com/api/screener?api_token=demo&fmt=json&filters=[["dividend_yield",">",0.04]]&sort=dividend_yield&order=d'

# Low P/E stocks in US market
curl 'https://eodhd.com/api/screener?api_token=demo&fmt=json&filters=[["exchange","=","us"],["pe",">",0],["pe","<",15]]&limit=20'

# Using the helper client (basic)
python eodhd_client.py --endpoint screener --limit 20
```

### Notes

- Filters must be URL-encoded when passed as query parameters
- Maximum 100 results per request; use offset for pagination
- Sorting by metrics helps prioritize results
- Null values may exist for stocks missing certain metrics
- Screener data is updated daily
- API call consumption: 1 call per request
- **Latest day only**: The screener works only for the **latest trading day**. It is not possible to screen based on a specific past date. Historical screening is not supported.

### HTTP Status Codes

The API returns standard HTTP status codes to indicate success or failure:

| Status Code | Meaning | Description |
|-------------|---------|-------------|
| **200** | OK | Request succeeded. Data returned successfully. |
| **402** | Payment Required | API limit used up. Upgrade plan or wait for limit reset. |
| **403** | Unauthorized | Invalid API key. Check your `api_token` parameter. |
| **429** | Too Many Requests | Exceeded rate limit (requests per minute). Slow down requests. |

### Error Response Format

When an error occurs, the API returns a JSON response with error details:

```json
{
  "error": "Error message description",
  "code": 403
}
```

### Handling Errors

**Python Example**:
```python
import requests

def make_api_request(url, params):
    try:
        response = requests.get(url, params=params)
        response.raise_for_status()  # Raises HTTPError for bad status codes
        return response.json()
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 402:
            print("Error: API limit exceeded. Please upgrade your plan.")
        elif e.response.status_code == 403:
            print("Error: Invalid API key. Check your credentials.")
        elif e.response.status_code == 429:
            print("Error: Rate limit exceeded. Please slow down your requests.")
        else:
            print(f"HTTP Error: {e}")
        return None
    except requests.exceptions.RequestException as e:
        print(f"Request failed: {e}")
        return None
```

**Best Practices**:
- Always check status codes before processing response data
- Implement exponential backoff for 429 errors
- Cache responses to reduce API calls
- Monitor your API usage in the user dashboard

---

## Stocks From Search API

<a id="stocks-from-search"></a>

### Endpoint Metadata

| Field | Value |
|---|---|
| Status | complete |
| Source | financial-apis |
| Docs | https://eodhd.com/financial-apis/search-api-for-stocks-etfs-mutual-funds-bonds-and-indices |
| Provider | EODHD |
| Base URL | `https://eodhd.com/api` |
| Path | `/search/{query_string}` |
| Method | GET |
| Auth | `api_token` query parameter |
| Slug | `stocks-from-search` |
| Source File | `/Users/arnaurodon/Projects/University/Final Thesis/eodhd-claude-skills/skills/eodhd-api/references/endpoints/stocks-from-search.md` |

### Purpose

Searches for financial instruments by ticker symbol, company name, or ISIN.
Returns a list of matching assets including stocks, ETFs, mutual funds, bonds,
and indices across all supported exchanges.

The search engine automatically adjusts behavior based on the input string and
considers asset popularity using metrics like market capitalization and trading
volume. Results can be filtered by asset type or exchange.

**Use cases**:
- Look up assets by ticker code (e.g. `AAPL`)
- Search by company name (e.g. `Apple Inc`)
- Resolve an ISIN to all exchange listings (e.g. `US0378331005`)
- Build autocomplete/typeahead for asset selection UIs
- Filter search results by asset type (stock, etf, fund, bond, index, crypto)
- Filter search results by exchange code (US, XETRA, LSE, etc.)
- Find all cross-listed instances of a security across exchanges

### Inputs

### Path (required)

| Parameter | Type | Description |
|-----------|------|-------------|
| `query_string` | string | The search input. Can be a ticker symbol, company name, or ISIN (e.g. `AAPL`, `Apple Inc`, `US0378331005`) |

### Query (required)

| Parameter | Type | Description |
|-----------|------|-------------|
| `api_token` | string | Your API key |

### Query (format)

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `fmt` | string | `json` | Response format. Use `json` |

### Query (optional)

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `limit` | integer | 15 | Maximum number of results to return (max 500) |
| `bonds_only` | integer | 0 | Set to `1` to include only bonds in the results |
| `exchange` | string | — | Filter results by exchange code (e.g. `US`, `PA`, `FOREX`, `NYSE`, `NASDAQ`) |
| `type` | string | — | Filter by asset type: `all`, `stock`, `etf`, `fund`, `bond`, `index`, `crypto` |

### Outputs

JSON array of matching instrument objects:

### Instrument object

| Field | Type | Description |
|-------|------|-------------|
| `Code` | string | Ticker symbol of the asset (e.g. `"AAPL"`, `"APC"`, `"0R2V"`) |
| `Exchange` | string | Exchange code where the asset is listed (e.g. `"US"`, `"XETRA"`, `"LSE"`) |
| `Name` | string | Full name of the instrument (e.g. `"Apple Inc"`) |
| `Type` | string | Type of asset (e.g. `"Common Stock"`, `"ETF"`, `"Fund"`, `"Bond"`) |
| `Country` | string | Country of the exchange (e.g. `"USA"`, `"Germany"`, `"UK"`) |
| `Currency` | string | Currency in which the asset is traded (e.g. `"USD"`, `"EUR"`, `"CAD"`) |
| `ISIN` | string \| null | ISIN code if available, `null` otherwise |
| `previousClose` | number | Previous closing price |
| `previousCloseDate` | string | Date of the previous close price (e.g. `"2026-02-13"`) |
| `isPrimary` | boolean | `true` if this is the primary exchange for the asset |

### Example Requests

Search by ticker code:
```bash
curl "https://eodhd.com/api/search/AAPL?api_token=YOUR_API_TOKEN&fmt=json"
```

Search by company name:
```bash
curl "https://eodhd.com/api/search/Apple%20Inc?api_token=YOUR_API_TOKEN&fmt=json"
```

Search by ISIN:
```bash
curl "https://eodhd.com/api/search/US0378331005?api_token=YOUR_API_TOKEN&fmt=json"
```

Search with a limit of 1 result:
```bash
curl "https://eodhd.com/api/search/Apple%20Inc?limit=1&api_token=YOUR_API_TOKEN&fmt=json"
```

Search for bonds only:
```bash
curl "https://eodhd.com/api/search/AAPL?bonds_only=1&api_token=YOUR_API_TOKEN&fmt=json"
```

Filter by exchange:
```bash
curl "https://eodhd.com/api/search/AAPL?exchange=US&api_token=YOUR_API_TOKEN&fmt=json"
```

Filter by asset type:
```bash
curl "https://eodhd.com/api/search/AAPL?type=stock&api_token=YOUR_API_TOKEN&fmt=json"
```

### Notes

- **Active tickers only**: The API searches among active (currently trading) tickers only.
- **Demo key not supported**: The demo API key does not work for the Search API. You must register for a free API token.
- **Response is a JSON array**: Unlike many EODHD endpoints, the response is a raw JSON array (not wrapped in an envelope object).
- **Bonds excluded by default**: When using `type=all` or no type filter, bonds are excluded from results. Use `type=bond` or `bonds_only=1` to include bonds.
- **ISIN returns all listings**: Searching by ISIN returns all exchange listings for that security. Use the `isPrimary` field to identify the primary listing, or filter with `exchange` to narrow results.
- **Cross-listed tickers**: The same security may appear with different ticker codes on different exchanges (e.g. `AAPL` on US, `APC` on XETRA, `0R2V` on LSE).
- **Search engine**: EODHD uses a professional search engine ([SphinxSearch](http://sphinxsearch.com/)) with sophisticated search rules that take into account market capitalization (converted to USD) and average trading volume over the past 10 days. The ticker code is the primary ranking parameter. For example, searching "VISA" returns that ticker first because it is a valid ticker code on some markets, even though Visa Inc.'s primary ticker is `V`.
- **Search by ISIN**: Tickers are searchable by their ISINs via the Search API and the main page search tool. However, ISINs are not unique — the same ISIN can exist on different exchanges (e.g., `AAPL.US` and `AAPL.MX`). EODHD uses `TICKER + EXCHANGE` as the unique identifier, consistent with other data providers.
- **Special characters in names**: Some company names contain characters that are difficult for the search engine to interpret (e.g., the apostrophe in "Lowe's Companies"). In most cases the search works perfectly, but such names may produce unexpected results.
- **Multiple tickers**: The search input is a single string. It returns results relevant to that string as a whole. Entering two different ticker codes will not return two separate results — it will likely return no results. Search is one query at a time.
- **Related endpoint**: There is a separate ID mapping endpoint to retrieve common identifiers (CUSIP, ISIN, OpenFigi, LEI, and CIK) for a symbol or by a specific identifier.

### HTTP Status Codes

The API returns standard HTTP status codes to indicate success or failure:

| Status Code | Meaning | Description |
|-------------|---------|-------------|
| **200** | OK | Request succeeded. Data returned successfully. |
| **402** | Payment Required | API limit used up. Upgrade plan or wait for limit reset. |
| **403** | Unauthorized | Invalid API key. Check your `api_token` parameter. |
| **429** | Too Many Requests | Exceeded rate limit (requests per minute). Slow down requests. |

### Error Response Format

When an error occurs, the API returns a JSON response with error details:

```json
{
  "error": "Error message description",
  "code": 403
}
```

### Handling Errors

**Python Example**:
```python
import requests

def make_api_request(url, params):
    try:
        response = requests.get(url, params=params)
        response.raise_for_status()  # Raises HTTPError for bad status codes
        return response.json()
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 402:
            print("Error: API limit exceeded. Please upgrade your plan.")
        elif e.response.status_code == 403:
            print("Error: Invalid API key. Check your credentials.")
        elif e.response.status_code == 429:
            print("Error: Rate limit exceeded. Please slow down your requests.")
        else:
            print(f"HTTP Error: {e}")
        return None
    except requests.exceptions.RequestException as e:
        print(f"Request failed: {e}")
        return None
```

**Best Practices**:
- Always check status codes before processing response data
- Implement exponential backoff for 429 errors
- Cache responses to reduce API calls
- Use `isPrimary` to identify the main listing when searching by ISIN
- Monitor your API usage in the user dashboard

---

## Symbol Change History API

<a id="symbol-change-history"></a>

### Endpoint Metadata

| Field | Value |
|---|---|
| Status | complete |
| Source | financial-apis |
| Provider | EODHD |
| Base URL | `https://eodhd.com/api` |
| Path | `/symbol-change-history` |
| Method | GET |
| Auth | `api_token` query parameter |
| Slug | `symbol-change-history` |
| Source File | `/Users/arnaurodon/Projects/University/Final Thesis/eodhd-claude-skills/skills/eodhd-api/references/endpoints/symbol-change-history.md` |

### Purpose

Get the history of ticker symbol changes (renames). When a company rebrands, merges, or restructures, its ticker symbol may change. This endpoint tracks those changes so you can maintain data continuity.

**Key details**:
- History available from **2022-07-22** onward
- Updated on a **daily** basis
- **US exchanges only** for now (other exchanges coming)

### Inputs

### Required

| Parameter | Type | Description |
|-----------|------|-------------|
| `api_token` | string | Your API key |

### Optional

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `from` | string | — | Start date (`YYYY-MM-DD`). History starts from `2022-07-22` |
| `to` | string | — | End date (`YYYY-MM-DD`) |
| `fmt` | string | `csv` | Response format: `json` or `csv` |

### Outputs

Returns a JSON array of symbol change records:

```json
[
  {
    "exchange": "US",
    "old_symbol": "CBTX",
    "new_symbol": "STEL",
    "company_name": "Stellar Bancorp, Inc. Common Stock",
    "effective": "2022-10-03"
  },
  {
    "exchange": "US",
    "old_symbol": "XPER",
    "new_symbol": "ADEA",
    "company_name": "Adeia Inc. Common Stock",
    "effective": "2022-10-03"
  },
  {
    "exchange": "US",
    "old_symbol": "LLL",
    "new_symbol": "JXJT",
    "company_name": "JX Luxventure Limited Common Stock",
    "effective": "2022-10-10"
  }
]
```

### Response Field Definitions

| Field | Type | Description |
|-------|------|-------------|
| `exchange` | string | Exchange code (currently always `US`) |
| `old_symbol` | string | Previous ticker symbol |
| `new_symbol` | string | New ticker symbol |
| `company_name` | string | Full company name |
| `effective` | string | Date the change took effect (`YYYY-MM-DD`) |

### Example Requests

### Get symbol changes for a date range

```bash
curl "https://eodhd.com/api/symbol-change-history?from=2022-10-01&to=2022-10-15&api_token=YOUR_API_TOKEN&fmt=json"
```

### Get recent symbol changes (with demo key)

```bash
curl "https://eodhd.com/api/symbol-change-history?from=2022-10-01&api_token=demo&fmt=json"
```

### Python (requests)

```python
import requests

url = "https://eodhd.com/api/symbol-change-history"
params = {
    "api_token": "YOUR_API_TOKEN",
    "from": "2022-10-01",
    "to": "2022-10-15",
    "fmt": "json"
}
response = requests.get(url, params=params)
changes = response.json()

for change in changes:
    print(f"{change['effective']}: {change['old_symbol']} → {change['new_symbol']} ({change['company_name']})")
```

### Notes

- **Default format is CSV**: Always pass `fmt=json` for programmatic access. Without it, the API returns CSV which is harder to parse.
- History starts from **2022-07-22** — no data available before this date
- **US exchanges only** — other exchanges are planned
- Updated daily
- Includes all types of symbol changes: rebrands, mergers, SPACs, ETF renames
- Warrants and other derivative instruments are also tracked (e.g., `CNTQW` → `DFLIW`)

### HTTP Status Codes

The API returns standard HTTP status codes to indicate success or failure:

| Status Code | Meaning | Description |
|-------------|---------|-------------|
| **200** | OK | Request succeeded. Data returned successfully. |
| **402** | Payment Required | API limit used up. Upgrade plan or wait for limit reset. |
| **403** | Unauthorized | Invalid API key. Check your `api_token` parameter. |
| **429** | Too Many Requests | Exceeded rate limit (requests per minute). Slow down requests. |

### Error Response Format

When an error occurs, the API returns a JSON response with error details:

```json
{
  "error": "Error message description",
  "code": 403
}
```

### Handling Errors

**Python Example**:
```python
import requests

def make_api_request(url, params):
    try:
        response = requests.get(url, params=params)
        response.raise_for_status()  # Raises HTTPError for bad status codes
        return response.json()
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 402:
            print("Error: API limit exceeded. Please upgrade your plan.")
        elif e.response.status_code == 403:
            print("Error: Invalid API key. Check your credentials.")
        elif e.response.status_code == 429:
            print("Error: Rate limit exceeded. Please slow down your requests.")
        else:
            print(f"HTTP Error: {e}")
        return None
    except requests.exceptions.RequestException as e:
        print(f"Request failed: {e}")
        return None
```

**Best Practices**:
- Always check status codes before processing response data
- Implement exponential backoff for 429 errors
- Cache responses to reduce API calls
- Monitor your API usage in the user dashboard

---

## Technical Indicators API

<a id="technical-indicators"></a>

### Endpoint Metadata

| Field | Value |
|---|---|
| Status | complete |
| Source | financial-apis (Technical Indicators API) |
| Docs | https://eodhd.com/financial-apis/technical-indicators-api |
| Provider | EODHD |
| Base URL | https://eodhd.com/api |
| Path | /technical/{SYMBOL} |
| Method | GET |
| Auth | api_token (query) |
| Slug | `technical-indicators` |
| Source File | `/Users/arnaurodon/Projects/University/Final Thesis/eodhd-claude-skills/skills/eodhd-api/references/endpoints/technical-indicators.md` |

### HTTP Status Codes

The API returns standard HTTP status codes to indicate success or failure:

| Status Code | Meaning | Description |
|-------------|---------|-------------|
| **200** | OK | Request succeeded. Data returned successfully. |
| **402** | Payment Required | API limit used up. Upgrade plan or wait for limit reset. |
| **403** | Unauthorized | Invalid API key. Check your `api_token` parameter. |
| **429** | Too Many Requests | Exceeded rate limit (requests per minute). Slow down requests. |

### Error Response Format

When an error occurs, the API returns a JSON response with error details:

```json
{
  "error": "Error message description",
  "code": 403
}
```

### Handling Errors

**Python Example**:
```python
import requests

def make_api_request(url, params):
    try:
        response = requests.get(url, params=params)
        response.raise_for_status()  # Raises HTTPError for bad status codes
        return response.json()
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 402:
            print("Error: API limit exceeded. Please upgrade your plan.")
        elif e.response.status_code == 403:
            print("Error: Invalid API key. Check your credentials.")
        elif e.response.status_code == 429:
            print("Error: Rate limit exceeded. Please slow down your requests.")
        else:
            print(f"HTTP Error: {e}")
        return None
    except requests.exceptions.RequestException as e:
        print(f"Request failed: {e}")
        return None
```

**Best Practices**:
- Always check status codes before processing response data
- Implement exponential backoff for 429 errors
- Cache responses to reduce API calls
- Monitor your API usage in the user dashboard

---

## TradingHours List All Markets API

<a id="tradinghours-list-markets"></a>

### Endpoint Metadata

| Field | Value |
|---|---|
| Status | complete |
| Source | marketplace (TradingHours) |
| Docs | https://eodhd.com/marketplace/tradinghours/options/docs |
| Provider | TradingHours via EODHD Marketplace |
| Base URL | `https://eodhd.com/api/mp/tradinghours` |
| Path | `/markets` |
| Method | GET |
| Auth | `api_token` query parameter |
| Slug | `tradinghours-list-markets` |
| Source File | `/Users/arnaurodon/Projects/University/Final Thesis/eodhd-claude-skills/skills/eodhd-api/references/endpoints/tradinghours-list-markets.md` |

### Purpose

Returns a list of all available markets with their FinIDs, exchange names, MICs,
asset types, and holiday coverage dates. Use this endpoint to discover which markets
are available and find the correct `{FinID}` for use with other TradingHours endpoints.

Each unique trading schedule or trading calendar is identified by a unique `{FinID}`.
Most exchanges have several different trading schedules for equities, bonds, futures, etc.
If you use `{MIC}` in place of the `{FinID}`, the system will select the closest match.

To find the correct `{FinID}`, look at `exchange`, `market`, and `products` fields.

**Use cases**:
- Discover available markets and their FinIDs
- Map MIC codes to FinIDs for use with status and details endpoints
- Check holiday data coverage range for each market
- Filter markets by access tier (Core, Extended, All)

### Inputs

### Query

| Parameter | Required | Type | Default | Description |
|-----------|----------|------|---------|-------------|
| `api_token` | Yes | string | — | Your API key (or `demo` for demo access) |
| `group` | No | string | `all` | Which group of markets to show. One of: `core`, `extended`, `all`, `allowed` |

The `allowed` group returns only markets your subscription has access to.

### Example Requests

```bash
# List all Core (G20+) markets
curl "https://eodhd.com/api/mp/tradinghours/markets?group=core&api_token=YOUR_API_TOKEN"

# List all available markets
curl "https://eodhd.com/api/mp/tradinghours/markets?group=all&api_token=YOUR_API_TOKEN"

# List only markets you have access to
curl "https://eodhd.com/api/mp/tradinghours/markets?group=allowed&api_token=demo"
```

### Example Response (Core group, truncated)

```json
{
  "data": [
    {
      "fin_id": "AU.ASX",
      "exchange": "ASX Australian Securities Exchange",
      "market": "Cash Market",
      "products": "Shares, ETPs, Hybrid Securities, A-REITs, etc",
      "mic": "XASX",
      "asset_type": "Equities",
      "group": "Core",
      "permanently_closed": null,
      "holidays_min_date": "2000-01-03",
      "holidays_max_date": "2028-12-29"
    },
    {
      "fin_id": "US.NYSE",
      "exchange": "New York Stock Exchange",
      "market": "Canonical",
      "products": null,
      "mic": "XNYS",
      "asset_type": "Securities",
      "group": "Core",
      "permanently_closed": null,
      "holidays_min_date": "2000-01-17",
      "holidays_max_date": "2033-12-26"
    }
  ]
}
```

### Python Example

```python
import requests

def list_markets(api_token, group="all"):
    """List all available TradingHours markets."""
    url = "https://eodhd.com/api/mp/tradinghours/markets"
    params = {
        "api_token": api_token,
        "group": group
    }

    response = requests.get(url, params=params)
    response.raise_for_status()

    return response.json()["data"]

# List Core (G20+) markets
markets = list_markets("YOUR_API_TOKEN", group="core")
for m in markets:
    print(f"{m['fin_id']:15} {m['exchange']:45} MIC: {m['mic']}")
```

### Notes

- **Marketplace product**: Requires a separate TradingHours marketplace subscription, not included in main EODHD plans.
- **FinID vs MIC**: FinIDs are more granular than MICs — they uniquely identify distinct trading schedules. MICs alone may not be sufficient to distinguish all schedules.
- **Access tiers**: Your subscription determines which markets you can access. Use `group=allowed` to see only your accessible markets.
- **Related endpoints**: Use the FinID from this endpoint with `/markets/details` (see tradinghours-market-details.md), `/markets/status` (see tradinghours-market-status.md), and `/markets/lookup` (see tradinghours-lookup-markets.md).

### HTTP Status Codes

| Status Code | Meaning | Description |
|-------------|---------|-------------|
| **200** | OK | Market list returned successfully. |
| **401** | Unauthorized | Invalid or missing API key. |
| **403** | Forbidden | Access denied (subscription required). |
| **429** | Too Many Requests | Rate limit exceeded. |

---

## TradingHours Lookup Markets API

<a id="tradinghours-lookup-markets"></a>

### Endpoint Metadata

| Field | Value |
|---|---|
| Status | complete |
| Source | marketplace (TradingHours) |
| Docs | https://eodhd.com/marketplace/tradinghours/options/docs |
| Provider | TradingHours via EODHD Marketplace |
| Base URL | `https://eodhd.com/api/mp/tradinghours` |
| Path | `/markets/lookup` |
| Method | GET |
| Auth | `api_token` query parameter |
| Slug | `tradinghours-lookup-markets` |
| Source File | `/Users/arnaurodon/Projects/University/Final Thesis/eodhd-claude-skills/skills/eodhd-api/references/endpoints/tradinghours-lookup-markets.md` |

### Purpose

Searches for markets based on any attribute such as exchange name, market name,
security description, MIC, or country. Returns matching markets with their FinIDs
and metadata.

Each unique trading schedule or trading calendar is identified by a unique `{FinID}`.
Most exchanges have several different trading schedules for equities, bonds, futures, etc.
In total, TradingHours tracks over 900 different trading schedules.

This endpoint allows you to easily search for the exact trading calendar you need.

**Use cases**:
- Search for markets by exchange name, country, or MIC code
- Find the correct FinID for a specific trading venue
- Discover available trading schedules for a particular exchange
- Filter search results by access tier

### Inputs

### Query

| Parameter | Required | Type | Default | Description |
|-----------|----------|------|---------|-------------|
| `api_token` | Yes | string | — | Your API key (or `demo` for demo access) |
| `q` | No | string | — | Free-form search term (exchange name, market name, MIC, country, etc.) |
| `group` | No | string | `all` | Which group of markets to search. One of: `core`, `extended`, `all`, `allowed` |

### Example Requests

```bash
# Search for Japanese markets
curl "https://eodhd.com/api/mp/tradinghours/markets/lookup?q=japan&api_token=YOUR_API_TOKEN"

# Search for markets by MIC code
curl "https://eodhd.com/api/mp/tradinghours/markets/lookup?q=XNYS&api_token=YOUR_API_TOKEN"

# Search within Core tier only
curl "https://eodhd.com/api/mp/tradinghours/markets/lookup?q=NYSE&group=core&api_token=YOUR_API_TOKEN"

# Demo access
curl "https://eodhd.com/api/mp/tradinghours/markets/lookup?q=name&group=allowed&api_token=demo"
```

### Example Response

```json
{
  "data": [
    {
      "fin_id": "US.NYSE",
      "exchange": "New York Stock Exchange",
      "market": "Canonical",
      "products": null,
      "mic": "XNYS",
      "asset_type": "Securities",
      "group": "Core",
      "permanently_closed": null,
      "holidays_min_date": "2000-01-17",
      "holidays_max_date": "2033-12-26"
    }
  ]
}
```

### Python Example

```python
import requests

def lookup_markets(query, api_token, group="all"):
    """Search for TradingHours markets by name, MIC, country, etc."""
    url = "https://eodhd.com/api/mp/tradinghours/markets/lookup"
    params = {
        "api_token": api_token,
        "q": query,
        "group": group
    }

    response = requests.get(url, params=params)
    response.raise_for_status()

    return response.json()["data"]

# Search for German markets
markets = lookup_markets("germany", "YOUR_API_TOKEN", group="core")
for m in markets:
    print(f"{m['fin_id']:15} {m['exchange']:45} MIC: {m['mic']}")
```

### Notes

- **Marketplace product**: Requires a separate TradingHours marketplace subscription, not included in main EODHD plans.
- **Free-form search**: The `q` parameter searches across all market attributes — exchange name, market name, product description, MIC, and country.
- **No query returns all**: If `q` is omitted, behaves like the List All Markets endpoint (see tradinghours-list-markets.md).
- **FinID vs MIC**: FinIDs are more granular than MICs. Use FinIDs with other TradingHours endpoints for precise results.
- **Related endpoints**: Use the FinID from search results with `/markets/details` (see tradinghours-market-details.md) and `/markets/status` (see tradinghours-market-status.md).

### HTTP Status Codes

| Status Code | Meaning | Description |
|-------------|---------|-------------|
| **200** | OK | Search results returned successfully. |
| **401** | Unauthorized | Invalid or missing API key. |
| **403** | Forbidden | Access denied (subscription required). |
| **429** | Too Many Requests | Rate limit exceeded. |

---

## TradingHours Get Market Details API

<a id="tradinghours-market-details"></a>

### Endpoint Metadata

| Field | Value |
|---|---|
| Status | complete |
| Source | marketplace (TradingHours) |
| Docs | https://eodhd.com/marketplace/tradinghours/options/docs |
| Provider | TradingHours via EODHD Marketplace |
| Base URL | `https://eodhd.com/api/mp/tradinghours` |
| Path | `/markets/details` |
| Method | GET |
| Auth | `api_token` query parameter |
| Slug | `tradinghours-market-details` |
| Source File | `/Users/arnaurodon/Projects/University/Final Thesis/eodhd-claude-skills/skills/eodhd-api/references/endpoints/tradinghours-market-details.md` |

### Purpose

Returns detailed information about one or more markets identified by their FinID,
including country code, timezone, weekend definition, MIC codes, and more. Use this
endpoint to get the full profile of a market or trading venue.

**Use cases**:
- Get timezone and weekend definition for a specific market
- Identify the country and MIC codes for a trading venue
- Look up exchange acronyms and product descriptions
- Check if a market has been permanently closed

### Inputs

### Query

| Parameter | Required | Type | Description |
|-----------|----------|------|-------------|
| `api_token` | Yes | string | Your API key (or `demo` for demo access) |
| `fin_id` | Yes | string | Market FinID(s) to get details for (e.g. `us.nyse`). Case-insensitive. |

### Example Requests

```bash
# Get details for NYSE
curl "https://eodhd.com/api/mp/tradinghours/markets/details?fin_id=us.nyse&api_token=demo"

# Get details for Tokyo Stock Exchange
curl "https://eodhd.com/api/mp/tradinghours/markets/details?fin_id=jp.jpx&api_token=YOUR_API_TOKEN"
```

### Example Response

```json
{
  "data": [
    {
      "fin_id": "US.NYSE",
      "country_code": "US",
      "exchange": "New York Stock Exchange",
      "market": "Canonical",
      "products": null,
      "mic": "XNYS",
      "mic_extended": "XNYS",
      "acronym": "NYSE",
      "asset_type": "Securities",
      "memo": "Canonical",
      "permanently_closed": null,
      "timezone": "America/New_York",
      "weekend_definition": "Sat-Sun",
      "holidays_min_date": "2000-01-17",
      "holidays_max_date": "2033-12-26"
    }
  ]
}
```

### Python Example

```python
import requests

def get_market_details(fin_id, api_token):
    """Get detailed information about a market by FinID."""
    url = "https://eodhd.com/api/mp/tradinghours/markets/details"
    params = {
        "api_token": api_token,
        "fin_id": fin_id
    }

    response = requests.get(url, params=params)
    response.raise_for_status()

    return response.json()["data"]

# Get NYSE details
details = get_market_details("us.nyse", "demo")
for market in details:
    print(f"Exchange:  {market['exchange']}")
    print(f"FinID:     {market['fin_id']}")
    print(f"Timezone:  {market['timezone']}")
    print(f"MIC:       {market['mic']}")
    print(f"Weekend:   {market['weekend_definition']}")
```

### Notes

- **Marketplace product**: Requires a separate TradingHours marketplace subscription, not included in main EODHD plans.
- **Case-insensitive**: The `fin_id` parameter is case-insensitive (`us.nyse` and `US.NYSE` both work).
- **Timezone**: The `timezone` field uses IANA timezone identifiers, useful for converting market times to local time.
- **Weekend definition**: Most markets use `Sat-Sun`, but some Middle Eastern markets may use `Fri-Sat`.
- **Related endpoints**: Use `/markets` (see tradinghours-list-markets.md) or `/markets/lookup` (see tradinghours-lookup-markets.md) to find FinIDs. Use `/markets/status` (see tradinghours-market-status.md) for real-time open/closed status.

### HTTP Status Codes

| Status Code | Meaning | Description |
|-------------|---------|-------------|
| **200** | OK | Market details returned successfully. |
| **401** | Unauthorized | Invalid or missing API key. |
| **403** | Forbidden | Access denied (subscription required). |
| **429** | Too Many Requests | Rate limit exceeded. |

---

## TradingHours Market Status Details API

<a id="tradinghours-market-status"></a>

### Endpoint Metadata

| Field | Value |
|---|---|
| Status | complete |
| Source | marketplace (TradingHours) |
| Docs | https://eodhd.com/marketplace/tradinghours/options/docs |
| Provider | TradingHours via EODHD Marketplace |
| Base URL | `https://eodhd.com/api/mp/tradinghours` |
| Path | `/markets/status` |
| Method | GET |
| Auth | `api_token` query parameter |
| Slug | `tradinghours-market-status` |
| Source File | `/Users/arnaurodon/Projects/University/Final Thesis/eodhd-claude-skills/skills/eodhd-api/references/endpoints/tradinghours-market-status.md` |

### Purpose

Returns the real-time current status of one or more markets, including whether the
market is open or closed, when it opens or closes next, the current trading phase
(pre-trading, post-trading, etc.), and any holidays or irregular schedules in effect.

**Use cases**:
- Build real-time market status dashboards
- Add countdowns or market status indicators to websites or applications
- Activate trading algorithms when markets open
- Detect market holidays and half-days programmatically
- Cache-friendly polling with the `until` field

### Inputs

### Query

| Parameter | Required | Type | Description |
|-----------|----------|------|-------------|
| `api_token` | Yes | string | Your API key (or `demo` for demo access) |
| `fin_id` | Yes | string | Market FinID(s) to check status for (e.g. `us.nyse`). Case-insensitive. |

### Example Requests

```bash
# Check NYSE status
curl "https://eodhd.com/api/mp/tradinghours/markets/status?fin_id=us.nyse&api_token=demo"

# Check Tokyo Stock Exchange status
curl "https://eodhd.com/api/mp/tradinghours/markets/status?fin_id=jp.jpx&api_token=YOUR_API_TOKEN"
```

### Example Response (Market Closed — Holiday)

```json
{
  "data": {
    "US.NYSE": {
      "fin_id": "US.NYSE",
      "exchange": "New York Stock Exchange",
      "market": "Canonical",
      "products": null,
      "timezone": "America/New_York",
      "status": "Closed",
      "reason": "Washington's Birthday",
      "until": "2026-02-17T04:00:00-05:00",
      "next_bell": "2026-02-17T09:30:00-05:00"
    }
  }
}
```

### Example Response (Market Open)

```json
{
  "data": {
    "US.NYSE": {
      "fin_id": "US.NYSE",
      "exchange": "New York Stock Exchange",
      "market": "Canonical",
      "products": null,
      "timezone": "America/New_York",
      "status": "Open",
      "reason": null,
      "until": "2026-02-18T16:00:00-05:00",
      "next_bell": "2026-02-18T16:00:00-05:00"
    }
  }
}
```

### Example Response (Half-Day / Partial Holiday)

```json
{
  "data": {
    "US.NYSE": {
      "fin_id": "US.NYSE",
      "exchange": "New York Stock Exchange",
      "market": "Canonical",
      "products": null,
      "timezone": "America/New_York",
      "status": "Open",
      "reason": "Market Holiday - Primary Trading Session (Partial)",
      "until": "2020-11-27T12:45:00-05:00",
      "next_bell": "2020-11-27T13:00:00-05:00"
    }
  }
}
```

### Python Example

```python
import requests
from datetime import datetime

def get_market_status(fin_id, api_token):
    """Get real-time market status by FinID."""
    url = "https://eodhd.com/api/mp/tradinghours/markets/status"
    params = {
        "api_token": api_token,
        "fin_id": fin_id
    }

    response = requests.get(url, params=params)
    response.raise_for_status()

    return response.json()["data"]

# Check NYSE status
status_data = get_market_status("us.nyse", "demo")
nyse = status_data["US.NYSE"]

print(f"Market:    {nyse['exchange']}")
print(f"Status:    {nyse['status']}")
print(f"Reason:    {nyse['reason'] or 'Normal schedule'}")
print(f"Until:     {nyse['until']}")
print(f"Next Bell: {nyse['next_bell']}")
```

### Caching Example

```python
import requests
from datetime import datetime, timezone

def get_market_status_cached(fin_id, api_token, cache={}):
    """Get market status with caching based on 'until' field."""
    cache_key = fin_id.upper()

    if cache_key in cache:
        cached = cache[cache_key]
        until = datetime.fromisoformat(cached["until"])
        if datetime.now(timezone.utc) < until:
            return cached

    url = "https://eodhd.com/api/mp/tradinghours/markets/status"
    params = {"api_token": api_token, "fin_id": fin_id}

    response = requests.get(url, params=params)
    response.raise_for_status()

    data = response.json()["data"]
    status = data[cache_key]
    cache[cache_key] = status

    return status
```

### Notes

- **Marketplace product**: Requires a separate TradingHours marketplace subscription, not included in main EODHD plans.
- **Caching**: Results will not change until the `until` timestamp. Cache aggressively using this field to minimize API calls and avoid rate limits.
- **Holidays only**: This API accounts for previously-scheduled holidays and half-days but does **not** factor in circuit breakers or trading halts.
- **No time parameter**: The current endpoint does not support a `time` query parameter for historical status lookups. Contact tradinghours.com for enterprise offers.
- **Response structure**: Unlike other TradingHours endpoints that return `data` as an array, this endpoint returns `data` as an object keyed by FinID.
- **Related endpoints**: Use `/markets` (see tradinghours-list-markets.md) or `/markets/lookup` (see tradinghours-lookup-markets.md) to find FinIDs. Use `/markets/details` (see tradinghours-market-details.md) for static market information like timezone and weekend definition.

### HTTP Status Codes

| Status Code | Meaning | Description |
|-------------|---------|-------------|
| **200** | OK | Market status returned successfully. |
| **401** | Unauthorized | Invalid or missing API key. |
| **403** | Forbidden | Access denied (subscription required). |
| **429** | Too Many Requests | Rate limit exceeded. |

---

## Historical & Upcoming Dividends API

<a id="upcoming-dividends"></a>

### Endpoint Metadata

| Field | Value |
|---|---|
| Status | complete |
| Source | financial-apis (Calendar API) |
| Docs | https://eodhd.com/financial-apis/calendar-upcoming-earnings-ipos-and-splits |
| Provider | EODHD |
| Base URL | https://eodhd.com/api |
| Path | /calendar/dividends |
| Method | GET |
| Auth | api_token (query) |
| Slug | `upcoming-dividends` |
| Source File | `/Users/arnaurodon/Projects/University/Final Thesis/eodhd-claude-skills/skills/eodhd-api/references/endpoints/upcoming-dividends.md` |

### Purpose

Returns a calendar of dividend dates filtered by symbol or by date. Supports pagination. Available in All-In-One, Fundamentals Data Feed plans and via "Financial Events (Calendar) & News Feed" plans.

For dividend details, navigate to the Corporate Actions: Splits and Dividends API.

### Inputs

| Parameter | Required | Type | Description |
|-----------|----------|------|-------------|
| api_token | Yes | string | Your API key |
| filter[symbol] | Conditional | string | Limit results to a single ticker. Required if filter[date_eq] is not provided |
| filter[date_eq] | Conditional | string (YYYY-MM-DD) | Exact dividend date. Required if filter[symbol] is not provided |
| filter[date_from] | No | string (YYYY-MM-DD) | Return dividends on or after this date |
| filter[date_to] | No | string (YYYY-MM-DD) | Return dividends on or before this date |
| page[limit] | No | integer (1–1000, default 1000) | Max results per page |
| page[offset] | No | integer (default 0) | Offset for pagination |
| fmt | No | string | json only |

### Outputs

```json
{
  "meta": {
    "total": 3,
    "offset": 0,
    "limit": 1000,
    "symbol": "AAPL.US",
    "date_eq": null
  },
  "data": [
    { "date": "2025-08-11", "symbol": "AAPL.US", "amount": 0.25, "currency": "USD" },
    { "date": "2025-05-12", "symbol": "AAPL.US", "amount": 0.25, "currency": "USD" },
    { "date": "2025-02-10", "symbol": "AAPL.US", "amount": 0.25, "currency": "USD" }
  ],
  "links": {
    "next": null
  }
}
```

### Output Format

**Meta object:**

| Field | Type | Description |
|-------|------|-------------|
| total | integer | Total number of results across all pages |
| limit | integer | Max number of results returned in this page |
| offset | integer | Offset used for this page |
| symbol | string or null | Echo of requested symbol, if provided |
| date_eq | string or null | Echo of requested exact date, if provided |

**Data array:**

Each item in the data array:

| Field | Type | Description |
|-------|------|-------------|
| date | string (YYYY-MM-DD) | Dividend date |
| symbol | string | Ticker |
| amount | number | Dividend amount per share (split-adjusted) |
| currency | string | Dividend currency (ISO Alpha-3, e.g. USD) |

**Links object:**

| Field | Type | Description |
|-------|------|-------------|
| next | string or null | URL to the next page, or null if none |

### Example Requests

```bash
# By symbol
curl "https://eodhd.com/api/calendar/dividends?filter[symbol]=AAPL.US&api_token=demo&fmt=json"

# By date window
curl "https://eodhd.com/api/calendar/dividends?filter[symbol]=AAPL.US&filter[date_from]=2025-01-01&filter[date_to]=2025-12-31&api_token=demo&fmt=json"

# By exact date
curl "https://eodhd.com/api/calendar/dividends?filter[date_eq]=2026-01-01&api_token=demo&fmt=json"

# With pagination
curl "https://eodhd.com/api/calendar/dividends?filter[symbol]=AAPL.US&page[limit]=10&page[offset]=0&api_token=demo&fmt=json"

# Using the helper client
python eodhd_client.py --endpoint calendar/dividends --symbol AAPL.US
```

### Notes

- At least one of `filter[symbol]` or `filter[date_eq]` must be provided
- Use `page[limit]` and `page[offset]` for large datasets
- `filter[date_from]` and `filter[date_to]` can be used together (with `filter[symbol]`) to narrow the range
- The `links.next` field provides the URL for the next page of results
- JSON-only format
- This endpoint returns dates only; for full dividend details (amounts, payment dates, etc.), use the Corporate Actions: Splits and Dividends API
- API call consumption: 1 call per request
- **Dividend currency**: By default, the currency is the same as for end-of-day data in most cases. However, if it differs, the `currency` field in the dividend data indicates the actual currency.
- **YOC (Yield on Cost)**: EODHD provides dividends and daily stock prices. To calculate YOC, divide the latest dividend amount by the stock price on a given day. This must be calculated on your side.
- **Adjusted dividends**: All dividends provided by EODHD are **split-adjusted**.

### HTTP Status Codes

The API returns standard HTTP status codes to indicate success or failure:

| Status Code | Meaning | Description |
|-------------|---------|-------------|
| **200** | OK | Request succeeded. Data returned successfully. |
| **402** | Payment Required | API limit used up. Upgrade plan or wait for limit reset. |
| **403** | Unauthorized | Invalid API key. Check your `api_token` parameter. |
| **429** | Too Many Requests | Exceeded rate limit (requests per minute). Slow down requests. |

### Error Response Format

When an error occurs, the API returns a JSON response with error details:

```json
{
  "error": "Error message description",
  "code": 403
}
```

### Handling Errors

**Python Example**:
```python
import requests

def make_api_request(url, params):
    try:
        response = requests.get(url, params=params)
        response.raise_for_status()  # Raises HTTPError for bad status codes
        return response.json()
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 402:
            print("Error: API limit exceeded. Please upgrade your plan.")
        elif e.response.status_code == 403:
            print("Error: Invalid API key. Check your credentials.")
        elif e.response.status_code == 429:
            print("Error: Rate limit exceeded. Please slow down your requests.")
        else:
            print(f"HTTP Error: {e}")
        return None
    except requests.exceptions.RequestException as e:
        print(f"Request failed: {e}")
        return None
```

**Best Practices**:
- Always check status codes before processing response data
- Implement exponential backoff for 429 errors
- Cache responses to reduce API calls
- Monitor your API usage in the user dashboard

---

## Historical & Upcoming Earnings API

<a id="upcoming-earnings"></a>

### Endpoint Metadata

| Field | Value |
|---|---|
| Status | complete |
| Source | financial-apis (Calendar Earnings API) |
| Docs | https://eodhd.com/financial-apis/calendar-upcoming-earnings-ipos-and-splits |
| Provider | EODHD |
| Base URL | https://eodhd.com/api |
| Path | /calendar/earnings |
| Method | GET |
| Auth | api_token (query) |
| Slug | `upcoming-earnings` |
| Source File | `/Users/arnaurodon/Projects/University/Final Thesis/eodhd-claude-skills/skills/eodhd-api/references/endpoints/upcoming-earnings.md` |

### Purpose

Returns historical and upcoming earnings dates with key fields (company symbol, report date/time, and additional metadata when available). Use either a date window or a symbol list. Available in All-In-One, Fundamentals Data Feed plans and via "Financial Events (Calendar) & News Feed" plans.

### Inputs

| Parameter | Required | Type | Description |
|-----------|----------|------|-------------|
| api_token | Yes | string | Your API key for authentication |
| from | No | string (YYYY-MM-DD) | Start date. Default: today |
| to | No | string (YYYY-MM-DD) | End date. Default: today + 7 days |
| symbols | No | string | One or more tickers (comma-separated). If set, from/to are ignored. Example: AAPL.US,MSFT.US,AI.PA |
| fmt | No | string | Output format: json or csv (default) |

### Outputs

```json
{
  "type": "Earnings",
  "description": "Historical and upcoming Earnings",
  "from": "2018-12-02",
  "to": "2018-12-06",
  "earnings": [
    {
      "code": "PIGEF.US",
      "report_date": "2018-12-02",
      "date": "2018-09-30",
      "before_after_market": "AfterMarket",
      "currency": "USD",
      "actual": 34.52,
      "estimate": 36.73,
      "difference": -2.21,
      "percent": -6.0169
    },
    {
      "code": "ANTM.JK",
      "report_date": "2018-12-02",
      "date": "2018-09-30",
      "before_after_market": "AfterMarket",
      "currency": "IDR",
      "actual": 11.9295,
      "estimate": null,
      "difference": 0,
      "percent": null
    }
  ]
}
```

### Output Format

**Top-level fields:**

| Field | Type | Description |
|-------|------|-------------|
| type | string | Constant label of the payload (example: "Earnings") |
| description | string | Human-readable description of the dataset |
| from | string (YYYY-MM-DD), optional | Start date of the requested range (present for date-window queries) |
| to | string (YYYY-MM-DD), optional | End date of the requested range (present for date-window queries) |
| symbols | string, optional | Comma-separated list of requested tickers (present for symbol-list queries) |
| earnings | array of objects | List of earnings records returned by the query |

**Earnings record fields:**

| Field | Type | Description |
|-------|------|-------------|
| code | string | Ticker in EODHD format |
| report_date | string (YYYY-MM-DD) | Date when the company reported/announced results |
| date | string (YYYY-MM-DD) | Fiscal period end date the result refers to |
| before_after_market | string or null | Report timing relative to market hours (e.g., BeforeMarket, AfterMarket), or null if unknown |
| currency | string or null | Reporting currency for EPS |
| actual | number or null | Reported EPS (or metric used by the feed) |
| estimate | number or null | Consensus EPS estimate, if available |
| difference | number or null | actual − estimate |
| percent | number or null | Surprise in percent (difference / estimate * 100), when estimate is available |

### Example Requests

```bash
# By symbol
curl "https://eodhd.com/api/calendar/earnings?symbols=AAPL.US,MSFT.US,AI.PA&api_token=demo&fmt=json"

# By date window
curl "https://eodhd.com/api/calendar/earnings?from=2026-02-10&to=2026-02-10&api_token=demo&fmt=json"

# Default (today + 7 days)
curl "https://eodhd.com/api/calendar/earnings?api_token=demo&fmt=json"

# Using the helper client
python eodhd_client.py --endpoint calendar/earnings --from-date 2026-02-10 --to-date 2026-02-10
```

### Notes

- **Default format is CSV**: Always pass `fmt=json` for programmatic access. Without it, the API returns CSV which is harder to parse.
- Without dates, default window is "today +7 days"
- When using `symbols` parameter, `from` and `to` parameters are ignored
- `before_after_market` indicates when earnings are released relative to market hours
- `actual` will be null for upcoming (not yet reported) earnings
- `percent` shows earnings surprise: positive = beat, negative = miss
- API call consumption: 1 call per request
- Data available from the beginning up to several months into the future

### HTTP Status Codes

The API returns standard HTTP status codes to indicate success or failure:

| Status Code | Meaning | Description |
|-------------|---------|-------------|
| **200** | OK | Request succeeded. Data returned successfully. |
| **402** | Payment Required | API limit used up. Upgrade plan or wait for limit reset. |
| **403** | Unauthorized | Invalid API key. Check your `api_token` parameter. |
| **429** | Too Many Requests | Exceeded rate limit (requests per minute). Slow down requests. |

### Error Response Format

When an error occurs, the API returns a JSON response with error details:

```json
{
  "error": "Error message description",
  "code": 403
}
```

### Handling Errors

**Python Example**:
```python
import requests

def make_api_request(url, params):
    try:
        response = requests.get(url, params=params)
        response.raise_for_status()  # Raises HTTPError for bad status codes
        return response.json()
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 402:
            print("Error: API limit exceeded. Please upgrade your plan.")
        elif e.response.status_code == 403:
            print("Error: Invalid API key. Check your credentials.")
        elif e.response.status_code == 429:
            print("Error: Rate limit exceeded. Please slow down your requests.")
        else:
            print(f"HTTP Error: {e}")
        return None
    except requests.exceptions.RequestException as e:
        print(f"Request failed: {e}")
        return None
```

**Best Practices**:
- Always check status codes before processing response data
- Implement exponential backoff for 429 errors
- Cache responses to reduce API calls
- Monitor your API usage in the user dashboard

---

## Historical & Upcoming IPOs API

<a id="upcoming-ipos"></a>

### Endpoint Metadata

| Field | Value |
|---|---|
| Status | complete |
| Source | financial-apis (Calendar API) |
| Docs | https://eodhd.com/financial-apis/calendar-upcoming-earnings-ipos-and-splits |
| Provider | EODHD |
| Base URL | https://eodhd.com/api |
| Path | /calendar/ipos |
| Method | GET |
| Auth | api_token (query) |
| Slug | `upcoming-ipos` |
| Source File | `/Users/arnaurodon/Projects/University/Final Thesis/eodhd-claude-skills/skills/eodhd-api/references/endpoints/upcoming-ipos.md` |

### Purpose

Returns historical and upcoming IPOs in a date window. Items may include filing/amended dates, expected or effective first trading date, price range or offer price, and share count. The response supports JSON (recommended for full field coverage). Available in All-In-One, Fundamentals Data Feed plans and via "Financial Events (Calendar) & News Feed" plans.

Data available from January 2015 and up to 2-3 weeks into the future.

### Inputs

| Parameter | Required | Type | Description |
|-----------|----------|------|-------------|
| api_token | Yes | string | Your API key |
| from | No | string (YYYY-MM-DD) | Start date for data retrieval (YYYY-MM-DD). Default: today |
| to | No | string (YYYY-MM-DD) | End date for data retrieval (YYYY-MM-DD). Default: today + 7 days |
| fmt | No | string | json or csv (default) |

### Outputs

```json
{
  "type": "IPOs",
  "description": "Historical and upcoming IPOs",
  "from": "2018-12-02",
  "to": "2018-12-06",
  "ipos": [
    {
      "code": "603629.SHG",
      "name": "Jiangsu Lettall Electronic Co Ltd",
      "exchange": "Shanghai",
      "currency": "CNY",
      "start_date": "2018-12-11",
      "filing_date": "2017-06-15",
      "amended_date": "2018-12-03",
      "price_from": 0,
      "price_to": 0,
      "offer_price": 0,
      "shares": 25000000,
      "deal_type": "Expected"
    },
    {
      "code": "SPK.MC",
      "name": "Solarpack Corporacion Tecnologica S.A",
      "exchange": "MCE",
      "currency": "EUR",
      "start_date": "2018-12-03",
      "filing_date": "2018-11-05",
      "amended_date": "2018-11-20",
      "price_from": 0,
      "price_to": 0,
      "offer_price": 0,
      "shares": 0,
      "deal_type": "Expected"
    }
  ]
}
```

### Output Format

**Top-level fields:**

| Field | Type | Description |
|-------|------|-------------|
| type | string | Constant label of the payload (example: IPOs) |
| description | string | Human-readable description of the dataset |
| from | string (YYYY-MM-DD) | Start date used for the query |
| to | string (YYYY-MM-DD) | End date used for the query |
| ipos | array of objects | List of IPO records for the window |

**IPO record fields:**

| Field | Type | Description |
|-------|------|-------------|
| code | string | Ticker in EODHD format |
| name | string or null | Company name |
| exchange | string or null | Listing exchange |
| currency | string or null | Trading currency |
| start_date | string (YYYY-MM-DD) or null | Expected/effective first trading date (if known) |
| filing_date | string (YYYY-MM-DD) or null | Initial filing date |
| amended_date | string (YYYY-MM-DD) or null | Latest amended filing date |
| price_from | number | Lower end of indicated price range (0 if not provided) |
| price_to | number | Upper end of indicated price range (0 if not provided) |
| offer_price | number | Final priced offer (0 if not priced yet) |
| shares | number | Shares offered (0 if not provided) |
| deal_type | string | Lifecycle state such as Filed, Expected, Amended, Priced |

### Example Requests

```bash
# IPOs for default window (today + 7 days)
curl "https://eodhd.com/api/calendar/ipos?api_token=demo&fmt=json"

# IPOs for specific date range
curl "https://eodhd.com/api/calendar/ipos?from=2018-12-02&to=2018-12-06&api_token=demo&fmt=json"

# Using the helper client
python eodhd_client.py --endpoint calendar/ipos --from-date 2026-02-10 --to-date 2026-02-17
```

### Notes

- **Default format is CSV**: Always pass `fmt=json` for programmatic access. Without it, the API returns CSV which is harder to parse.
- Numbers may be 0 when the value is unknown or not yet set (for example before pricing)
- `start_date` may be null for filings without a scheduled first trading date
- Use `deal_type` to track lifecycle changes (for example, Amended or Priced updates)
- Deal type values include: Filed, Expected, Amended, Priced
- `offer_price` is 0 until the IPO is priced (usually day before or day of listing)
- `price_from` and `price_to` represent the expected pricing range from prospectus
- Data available from January 2015 and up to 2-3 weeks into the future
- API call consumption: 1 call per request
- **N/A on upcoming IPOs**: A `n/a` value for the ticker code means the future ticker was not yet known when the entry was added. Some filed IPOs never become listed (e.g., a company may file but never get approved). To find the actual ticker code for a successful IPO, use the company name from this API to look it up via the **Search API**.
- **Bulk calendar for IPOs**: The Calendar IPO API is essentially a bulk endpoint — it provides data for upcoming IPOs across **all exchanges** when no symbol filter is applied.

### HTTP Status Codes

The API returns standard HTTP status codes to indicate success or failure:

| Status Code | Meaning | Description |
|-------------|---------|-------------|
| **200** | OK | Request succeeded. Data returned successfully. |
| **402** | Payment Required | API limit used up. Upgrade plan or wait for limit reset. |
| **403** | Unauthorized | Invalid API key. Check your `api_token` parameter. |
| **429** | Too Many Requests | Exceeded rate limit (requests per minute). Slow down requests. |

### Error Response Format

When an error occurs, the API returns a JSON response with error details:

```json
{
  "error": "Error message description",
  "code": 403
}
```

### Handling Errors

**Python Example**:
```python
import requests

def make_api_request(url, params):
    try:
        response = requests.get(url, params=params)
        response.raise_for_status()  # Raises HTTPError for bad status codes
        return response.json()
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 402:
            print("Error: API limit exceeded. Please upgrade your plan.")
        elif e.response.status_code == 403:
            print("Error: Invalid API key. Check your credentials.")
        elif e.response.status_code == 429:
            print("Error: Rate limit exceeded. Please slow down your requests.")
        else:
            print(f"HTTP Error: {e}")
        return None
    except requests.exceptions.RequestException as e:
        print(f"Request failed: {e}")
        return None
```

**Best Practices**:
- Always check status codes before processing response data
- Implement exponential backoff for 429 errors
- Cache responses to reduce API calls
- Monitor your API usage in the user dashboard

---

## Historical & Upcoming Splits API

<a id="upcoming-splits"></a>

### Endpoint Metadata

| Field | Value |
|---|---|
| Status | complete |
| Source | financial-apis (Calendar API) |
| Docs | https://eodhd.com/financial-apis/calendar-upcoming-earnings-ipos-and-splits |
| Provider | EODHD |
| Base URL | https://eodhd.com/api |
| Path | /calendar/splits |
| Method | GET |
| Auth | api_token (query) |
| Slug | `upcoming-splits` |
| Source File | `/Users/arnaurodon/Projects/University/Final Thesis/eodhd-claude-skills/skills/eodhd-api/references/endpoints/upcoming-splits.md` |

### Purpose

Returns historical and upcoming stock splits and reverse splits for selected symbols or a date window. Each item includes the effective split date and the ratio (for example 4:1). Available in All-In-One, Fundamentals Data Feed plans and via "Financial Events (Calendar) & News Feed" plans.

Data available from January 2015 to several months into the future. For full historical data, see the Splits and Dividends API.

### Inputs

| Parameter | Required | Type | Description |
|-----------|----------|------|-------------|
| api_token | Yes | string | Your API key |
| symbols | No | string | Comma-separated list of tickers in EODHD format (e.g., TSLA.US or TSLA.US,AAPL.US) |
| from | Conditional | string (YYYY-MM-DD) | Start of the calendar window. Required if symbols not provided |
| to | Conditional | string (YYYY-MM-DD) | End of the calendar window. Required if symbols not provided |
| fmt | No | string | json or csv (default) |

### Outputs

```json
{
  "type": "Splits",
  "description": "Historical and upcoming splits",
  "from": "2025-10-13",
  "to": "2025-10-20",
  "splits": [
    {
      "code": "0698.HK",
      "split_date": "2025-10-13",
      "optionable": "N",
      "old_shares": 50,
      "new_shares": 1
    },
    {
      "code": "1449.TW",
      "split_date": "2025-10-13",
      "optionable": "N",
      "old_shares": 1000,
      "new_shares": 1032
    }
  ]
}
```

### Output Format

**Top-level fields:**

| Field | Type | Description |
|-------|------|-------------|
| type | string | Constant label of the payload (example: Splits) |
| description | string | Human-readable description of the dataset |
| from | string (YYYY-MM-DD) | Start date of the requested range |
| to | string (YYYY-MM-DD) | End date of the requested range |
| splits | array of objects | List of split records within the range |

**Split record fields:**

| Field | Type | Description |
|-------|------|-------------|
| code | string | Ticker in EODHD format |
| split_date | string (YYYY-MM-DD) | Effective date of the split |
| optionable | string | Indicates if the stock is optionable: "Y" or "N" |
| old_shares | number | Number of old shares before the split |
| new_shares | number | Number of new shares after the split |

### Understanding Split Ratios

- **Forward split**: Each share becomes multiple shares (new_shares > old_shares)
  - Example: old_shares: 1, new_shares: 5 (5-for-1 split)
  - Price divides: $1000 stock becomes $200 after 5-for-1 split

- **Reverse split**: Multiple shares become fewer shares (new_shares < old_shares)
  - Example: old_shares: 65, new_shares: 1 (1-for-65 reverse split)
  - Price multiplies: $2 stock becomes $130 after 1-for-65 reverse split

### Example Requests

```bash
# By symbol with date window (CSV format)
curl "https://eodhd.com/api/calendar/splits?symbols=TSLA.US&from=2010-01-01&to=2030-01-01&api_token=demo"

# By symbol with date window (JSON format)
curl "https://eodhd.com/api/calendar/splits?symbols=TSLA.US&from=2010-01-01&to=2030-01-01&api_token=demo&fmt=json"

# By date window (all symbols)
curl "https://eodhd.com/api/calendar/splits?from=2024-01-01&to=2024-01-03&api_token=demo&fmt=json"

# Using the helper client
python eodhd_client.py --endpoint calendar/splits --symbols TSLA.US --from-date 2010-01-01 --to-date 2030-01-01
```

### Notes

- **Default format is CSV**: Always pass `fmt=json` for programmatic access. Without it, the API returns CSV which is harder to parse.
- Forward splits (new_shares > old_shares) are more common for high-priced stocks
- Reverse splits (new_shares < old_shares) often indicate struggling companies trying to meet exchange listing requirements
- Historical prices are typically split-adjusted automatically in EOD data
- Use `old_shares`/`new_shares` for split ratio calculations
- Data available from January 2015 to several months into the future
- For full historical data, use the Splits and Dividends API
- When using `symbols` parameter, you can also specify `from` and `to` dates for filtering
- API call consumption: 1 call per request
- **Historical splits before 2015**: The Calendar Splits API was designed primarily for **upcoming** splits. It does not support splits before 2015. For historical split data, use the **Splits and Dividends API** (`/div/{TICKER}` or `/splits/{TICKER}`) or the **EOD Bulk API** with `type=splits`. The Calendar API is recommended for upcoming splits; the other APIs for historical data.
- **Historical splits by exchange**: To download historical splits for an entire exchange, use the Bulk API: https://eodhd.com/knowledgebase/bulk-api-eod-splits-dividends/

### HTTP Status Codes

The API returns standard HTTP status codes to indicate success or failure:

| Status Code | Meaning | Description |
|-------------|---------|-------------|
| **200** | OK | Request succeeded. Data returned successfully. |
| **402** | Payment Required | API limit used up. Upgrade plan or wait for limit reset. |
| **403** | Unauthorized | Invalid API key. Check your `api_token` parameter. |
| **429** | Too Many Requests | Exceeded rate limit (requests per minute). Slow down requests. |

### Error Response Format

When an error occurs, the API returns a JSON response with error details:

```json
{
  "error": "Error message description",
  "code": 403
}
```

### Handling Errors

**Python Example**:
```python
import requests

def make_api_request(url, params):
    try:
        response = requests.get(url, params=params)
        response.raise_for_status()  # Raises HTTPError for bad status codes
        return response.json()
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 402:
            print("Error: API limit exceeded. Please upgrade your plan.")
        elif e.response.status_code == 403:
            print("Error: Invalid API key. Check your credentials.")
        elif e.response.status_code == 429:
            print("Error: Rate limit exceeded. Please slow down your requests.")
        else:
            print(f"HTTP Error: {e}")
        return None
    except requests.exceptions.RequestException as e:
        print(f"Request failed: {e}")
        return None
```

**Best Practices**:
- Always check status codes before processing response data
- Implement exponential backoff for 429 errors
- Cache responses to reduce API calls
- Monitor your API usage in the user dashboard

---

## US Live Extended Quotes API (Live v2)

<a id="us-live-extended-quotes"></a>

### Endpoint Metadata

| Field | Value |
|---|---|
| Status | complete |
| Source | financial-apis (Live Data API) |
| Docs | https://eodhd.com/financial-apis/live-realtime-stocks-api |
| Provider | EODHD |
| Base URL | https://eodhd.com/api |
| Path | /us-quote-delayed |
| Method | GET |
| Auth | api_token (query) |
| Slug | `us-live-extended-quotes` |
| Source File | `/Users/arnaurodon/Projects/University/Final Thesis/eodhd-claude-skills/skills/eodhd-api/references/endpoints/us-live-extended-quotes.md` |

### Purpose

Returns delayed quote snapshots for one or more US stock symbols. Each quote includes last trade price with event time, full bid/ask with sizes and timestamps, intraday change, rolling averages (50/100/200-day), 52-week extremes, market cap, P/E ratios, dividend data, and issuer reference fields. Batch requests are supported via comma-separated tickers. This is the "Live v2" endpoint, focused on US equities with richer quote-level detail than the Live v1 OHLCV endpoint. Available in All-In-One, EOD Historical Data: All World, EOD + Intraday: All World Extended, and Free plans.

### Inputs

| Parameter | Required | Type | Description |
|-----------|----------|------|-------------|
| api_token | Yes | string | Your API access token |
| s | Yes | string | One or more symbols separated by commas (e.g., AAPL.US or AAPL.US,TSLA.US) |
| page[limit] | No | integer | Number of symbols per page (max 100) |
| page[offset] | No | integer | Offset for pagination |
| fmt | No | string | Response format: json (default) or csv |

### Outputs

```json
{
  "meta": { "count": 2 },
  "data": {
    "AAPL.US": {
      "symbol": "AAPL.US",
      "exchange": "XNAS",
      "isoExchange": "XNAS",
      "bzExchange": "NASDAQ",
      "otcMarket": "",
      "otcTier": "",
      "type": "STOCK",
      "name": "Apple",
      "companyStandardName": "Apple Inc",
      "description": "Apple Inc. - Common Stock",
      "sector": "Information Technology",
      "industry": "Technology Hardware, Storage & Peripherals",
      "open": 204.505,
      "high": 207.88,
      "low": 201.675,
      "bidPrice": 203.28,
      "bidSize": 4,
      "bidTime": 1754339351000,
      "askPrice": 203.32,
      "askSize": 1,
      "askTime": 1754339341000,
      "size": 7225981,
      "lastTradePrice": 203.32,
      "lastTradeTime": 1754339340000,
      "volume": 73006032,
      "change": 0.94,
      "changePercent": 0.46,
      "previousClosePrice": 202.38,
      "previousCloseDate": "2026-02-12 16:00:00",
      "fiftyDayAveragePrice": 205.28,
      "hundredDayAveragePrice": 206.37,
      "twoHundredDayAveragePrice": 221.53,
      "averageVolume": 48512910,
      "fiftyTwoWeekHigh": 260.1,
      "fiftyTwoWeekLow": 169.2101,
      "marketCap": 3054287882360,
      "sharesOutstanding": 14681140000,
      "sharesFloat": 14672068878,
      "pe": 30.710167,
      "forwardPE": 25.974,
      "dividendYield": 0.51,
      "dividend": 1.04,
      "payoutRatio": 0.1304,
      "ethPrice": 203.32,
      "ethVolume": 8738316,
      "ethTime": 1754339340000,
      "currency": "USD",
      "issuerName": "Apple Inc",
      "primary": true,
      "shortDescription": "Ordinary Shares",
      "issuerShortName": "Apple",
      "timestamp": 1754339340
    },
    "TSLA.US": {
      "symbol": "TSLA.US",
      "exchange": "XNAS",
      "name": "Tesla Inc",
      "lastTradePrice": 245.11,
      "lastTradeTime": 1754339340000,
      "bidPrice": 245.09,
      "askPrice": 245.12,
      "volume": 51234567,
      "change": -1.22,
      "changePercent": -0.49,
      "currency": "USD",
      "timestamp": 1754339340
    }
  },
  "links": { "next": null }
}
```

### Output Format

**Top-level fields:**

| Field | Type | Description |
|-------|------|-------------|
| meta.count | integer | Number of returned symbols |
| data | object | A per-symbol object keyed by requested symbols |
| links.next | string or null | URL to the next page of results, if available |

**Per-symbol fields (data[symbol]):**

| Field | Type | Description |
|-------|------|-------------|
| symbol | string | Instrument code (e.g., AAPL.US) |
| exchange | string | Exchange MIC code (e.g., XNAS) |
| isoExchange | string | ISO-style exchange identifier |
| bzExchange | string | Human-readable exchange name |
| otcMarket | string or null | OTC market name if applicable |
| otcTier | string or null | OTC market tier if applicable |
| type | string | Instrument type (e.g., STOCK) |
| name | string | Company name |
| companyStandardName | string | Standardized issuer name |
| description | string | Short description of the instrument |
| sector | string | GICS or internal sector mapping |
| industry | string | GICS or internal industry mapping |
| open | float | Session open price |
| high | float | Session high price |
| low | float | Session low price |
| bidPrice | float | Best bid price |
| bidSize | integer | Best bid size |
| bidTime | integer (ms) | Timestamp of last bid update (Unix ms) |
| askPrice | float | Best ask price |
| askSize | integer | Best ask size |
| askTime | integer (ms) | Timestamp of last ask update (Unix ms) |
| size | integer | Last trade size (if provided) |
| lastTradePrice | float | Last trade price |
| lastTradeTime | integer (ms) | Timestamp of last trade (Unix ms) |
| volume | float | Cumulative session volume |
| change | float | Absolute day change vs previous close |
| changePercent | float | Percent day change vs previous close |
| previousClosePrice | float | Previous close price |
| previousCloseDate | string (YYYY-MM-DD HH:MM:SS) | Previous close date and time (UTC) |
| fiftyDayAveragePrice | float | 50-day moving average price |
| hundredDayAveragePrice | float | 100-day moving average price |
| twoHundredDayAveragePrice | float | 200-day moving average price |
| averageVolume | integer | Average daily volume |
| fiftyTwoWeekHigh | float | 52-week high price |
| fiftyTwoWeekLow | float | 52-week low price |
| marketCap | integer | Market capitalization |
| sharesOutstanding | integer | Shares outstanding |
| sharesFloat | integer | Free float shares |
| pe | float | Trailing price-to-earnings ratio |
| forwardPE | float | Forward price-to-earnings ratio |
| dividendYield | float | Dividend yield in percent (decimal form, e.g., 0.51 = 0.51%, not 51%) |
| dividend | float | Dividend per share (TTM or latest) |
| payoutRatio | float | Dividend payout ratio (percent) |
| ethPrice | float | Extended hours last price (if available) |
| ethVolume | integer | Extended hours volume |
| ethTime | integer (ms) | Extended hours last trade time (Unix ms) |
| currency | string | Trading currency (ISO alpha-3) |
| issuerName | string | Issuer name |
| primary | boolean | Whether this is the primary listing |
| shortDescription | string | Short instrument description |
| issuerShortName | string | Short issuer name |
| timestamp | integer (s) | Snapshot timestamp (Unix seconds) |

### Example Requests

```bash
# Single symbol quote
curl "https://eodhd.com/api/us-quote-delayed?s=AAPL.US&api_token=YOUR_TOKEN&fmt=json"

# Multiple symbols in one request
curl "https://eodhd.com/api/us-quote-delayed?s=AAPL.US,TSLA.US,MSFT.US&api_token=YOUR_TOKEN&fmt=json"

# With pagination
curl "https://eodhd.com/api/us-quote-delayed?s=AAPL.US,TSLA.US&api_token=YOUR_TOKEN&page[limit]=50&page[offset]=0&fmt=json"

# Using the helper client
python eodhd_client.py --endpoint us-quote-delayed --symbol AAPL.US

# Multiple symbols via helper client
python eodhd_client.py --endpoint us-quote-delayed --symbol AAPL.US,TSLA.US,MSFT.US
```

### Notes

- API call consumption: 1 API call per ticker in the request
- Quotes are delayed (exchange-compliant), not real-time
- Batch requests supported via comma-separated symbols (max 100 per page)
- JSON is the default format; CSV is also supported via `fmt=csv`
- The `data` field is an object keyed by symbol, not an array
- Extended hours fields (`ethPrice`, `ethVolume`, `ethTime`) are available when pre/post-market data exists
- Timestamps: `bidTime`, `askTime`, `lastTradeTime`, `ethTime` are in Unix milliseconds; `timestamp` is in Unix seconds
- **Live v2 vs Live v1**: Live v2 (this endpoint) provides quote-level detail (bid/ask, trade timestamps, fundamentals) for US stocks. Live v1 (`/real-time/{symbol}`) provides minute OHLCV bars across multiple asset classes without bid/ask or trade event timestamps

### HTTP Status Codes

The API returns standard HTTP status codes to indicate success or failure:

| Status Code | Meaning | Description |
|-------------|---------|-------------|
| **200** | OK | Request succeeded. Data returned successfully. |
| **402** | Payment Required | API limit used up. Upgrade plan or wait for limit reset. |
| **403** | Unauthorized | Invalid API key. Check your `api_token` parameter. |
| **429** | Too Many Requests | Exceeded rate limit (requests per minute). Slow down requests. |

### Error Response Format

When an error occurs, the API returns a JSON response with error details:

```json
{
  "error": "Error message description",
  "code": 403
}
```

### Handling Errors

**Python Example**:
```python
import requests

def make_api_request(url, params):
    try:
        response = requests.get(url, params=params)
        response.raise_for_status()  # Raises HTTPError for bad status codes
        return response.json()
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 402:
            print("Error: API limit exceeded. Please upgrade your plan.")
        elif e.response.status_code == 403:
            print("Error: Invalid API key. Check your credentials.")
        elif e.response.status_code == 429:
            print("Error: Rate limit exceeded. Please slow down your requests.")
        else:
            print(f"HTTP Error: {e}")
        return None
    except requests.exceptions.RequestException as e:
        print(f"Request failed: {e}")
        return None
```

**Best Practices**:
- Always check status codes before processing response data
- Implement exponential backoff for 429 errors
- Cache responses to reduce API calls
- Monitor your API usage in the user dashboard

---

## US Options Contracts API

<a id="us-options-contracts"></a>

### Endpoint Metadata

| Field | Value |
|---|---|
| Status | complete |
| Source | marketplace (US Stock Options Data API by Unicornbay) |
| Docs | https://eodhd.com/financial-apis/us-stock-options-data-api |
| Provider | EODHD Marketplace |
| Base URL | https://eodhd.com/api |
| Path | /mp/unicornbay/options/contracts |
| Method | GET |
| Auth | api_token (query) |
| Slug | `us-options-contracts` |
| Source File | `/Users/arnaurodon/Projects/University/Final Thesis/eodhd-claude-skills/skills/eodhd-api/references/endpoints/us-options-contracts.md` |

### Purpose

Fetches a list of options contracts based on various filters such as underlying symbol,
expiration dates, strike price range, and contract type (call or put). Includes current
pricing, Greeks, volume, open interest, and 40+ fields of options data. Covers 6,000+
US tickers with 2-year history and 1.5M daily bid/ask/trade events.

### Inputs

| Parameter | Required | Type | Description |
|-----------|----------|------|-------------|
| api_token | Yes | string | Your API key for authentication |
| filter[contract] | No | string | Filter by specific contract name (e.g., 'AAPL270115P00450000') |
| filter[underlying_symbol] | No | string | Filter by underlying stock symbol (e.g., 'AAPL') |
| filter[exp_date_eq] | No | string (YYYY-MM-DD) | Filter contracts expiring on exact date |
| filter[exp_date_from] | No | string (YYYY-MM-DD) | Filter contracts expiring from date onwards |
| filter[exp_date_to] | No | string (YYYY-MM-DD) | Filter contracts expiring up to date |
| filter[tradetime_eq] | No | string (YYYY-MM-DD) | Filter by exact trade time date |
| filter[tradetime_from] | No | string (YYYY-MM-DD) | Filter by trade time from date onwards |
| filter[tradetime_to] | No | string (YYYY-MM-DD) | Filter by trade time up to date |
| filter[type] | No | string | Contract type: 'put' or 'call' |
| filter[strike_eq] | No | number | Filter by exact strike price |
| filter[strike_from] | No | number | Filter by strike price from value onwards |
| filter[strike_to] | No | number | Filter by strike price up to value |
| sort | No | string | Sort order: 'exp_date', 'strike', '-exp_date', '-strike' |
| page[offset] | No | integer | Pagination offset (default: 0, max: 10000) |
| page[limit] | No | integer | Results per page (default: 1000, max: 1000) |
| fields[options-contracts] | No | string | Comma-separated list of fields to include |

### Outputs

```json
{
  "meta": {
    "offset": 0,
    "limit": 2,
    "total": 19058,
    "fields": ["contract", "underlying_symbol", "exp_date", "type", "strike", "..."]
  },
  "data": [
    {
      "id": "AAPL270115C00450000",
      "type": "options-contracts",
      "attributes": {
        "contract": "AAPL270115C00450000",
        "underlying_symbol": "AAPL",
        "exp_date": "2027-01-15",
        "expiration_type": "monthly",
        "type": "call",
        "strike": 450,
        "exchange": "NASDAQ",
        "currency": "USD",
        "open": 0.95,
        "high": 1.00,
        "low": 0.89,
        "last": 0.89,
        "last_size": 1,
        "change": -0.03,
        "pctchange": -3.26,
        "previous": 0.92,
        "previous_date": "2026-02-06",
        "bid": 0.89,
        "bid_date": "2026-02-06 20:59:59",
        "bid_size": 37,
        "ask": 0.92,
        "ask_date": "2026-02-06 20:59:59",
        "ask_size": 17,
        "moneyness": -0.62,
        "volume": 180,
        "volume_change": 95,
        "volume_pctchange": 111.76,
        "open_interest": 16229,
        "open_interest_change": 2,
        "open_interest_pctchange": 0.01,
        "volatility": 0.2445,
        "volatility_change": -0.0042,
        "volatility_pctchange": -1.69,
        "theoretical": 0.89,
        "delta": 0.036776,
        "gamma": 0.001221,
        "theta": -0.008551,
        "vega": 0.216526,
        "rho": 0.087534,
        "tradetime": "2026-02-06",
        "vol_oi_ratio": 0.01,
        "dte": 342,
        "midpoint": 0.91
      }
    }
  ],
  "links": {
    "next": "https://eodhd.com/api/mp/unicornbay/options/contracts?...&page[offset]=2"
  }
}
```

### Field Descriptions

| Field | Type | Description |
|-------|------|-------------|
| contract | string | OCC contract identifier (SYMBOL + YYMMDD + C/P + strike*1000) |
| underlying_symbol | string | Underlying stock ticker |
| exp_date | string (date) | Expiration date (YYYY-MM-DD) |
| expiration_type | string | Expiration type: 'monthly', 'weekly', 'quarterly' |
| type | string | Contract type: 'call' or 'put' |
| strike | number | Strike price |
| exchange | string | Exchange (e.g., 'NASDAQ') |
| currency | string | Currency (e.g., 'USD') |
| open | number | Opening price |
| high | number | High price |
| low | number | Low price |
| last | number | Last traded price |
| last_size | integer | Size of last trade |
| change | number | Price change from previous |
| pctchange | number | Percentage change |
| previous | number | Previous day's close |
| previous_date | string | Date of previous close |
| bid | number | Current bid price |
| bid_date | string | Timestamp of bid |
| bid_size | integer | Bid size |
| ask | number | Current ask price |
| ask_date | string | Timestamp of ask |
| ask_size | integer | Ask size |
| moneyness | number | Moneyness ratio (negative = OTM, positive = ITM) |
| volume | integer | Trading volume |
| volume_change | integer | Volume change from previous |
| volume_pctchange | number | Volume percentage change |
| open_interest | integer | Open interest |
| open_interest_change | integer | OI change from previous |
| open_interest_pctchange | number | OI percentage change |
| volatility | number | Implied volatility |
| volatility_change | number | IV change |
| volatility_pctchange | number | IV percentage change |
| theoretical | number | Theoretical option price |
| delta | number | Delta Greek |
| gamma | number | Gamma Greek |
| theta | number | Theta Greek (time decay) |
| vega | number | Vega Greek (volatility sensitivity) |
| rho | number | Rho Greek (interest rate sensitivity) |
| tradetime | string (date) | Date of last market activity |
| vol_oi_ratio | number | Volume/Open Interest ratio |
| dte | integer | Days to expiration |
| midpoint | number | Midpoint of bid/ask |

### Example Requests

```bash
# All options contracts for AAPL
curl "https://eodhd.com/api/mp/unicornbay/options/contracts?filter[underlying_symbol]=AAPL&api_token=demo&page[limit]=10"

# Specific contract
curl "https://eodhd.com/api/mp/unicornbay/options/contracts?filter[contract]=AAPL270115C00450000&api_token=demo"

# AAPL puts with strike $450 expiring on specific date
curl "https://eodhd.com/api/mp/unicornbay/options/contracts?filter[underlying_symbol]=AAPL&filter[strike_eq]=450&filter[type]=put&filter[exp_date_eq]=2027-01-15&api_token=demo"

# Calls with strikes between $120-$130
curl "https://eodhd.com/api/mp/unicornbay/options/contracts?filter[underlying_symbol]=AAPL&filter[type]=call&filter[strike_from]=120&filter[strike_to]=130&api_token=demo"

# Sorted by expiration date descending, specific fields only
curl "https://eodhd.com/api/mp/unicornbay/options/contracts?filter[underlying_symbol]=AAPL&sort=-exp_date&fields[options-contracts]=contract,bid_date,open,high,low,last&page[limit]=5&api_token=demo"
```

### Notes

- **Marketplace Product**: This is a marketplace API (path: `/mp/unicornbay/...`)
- **Coverage**: 6,000+ US tickers, 1.5M daily events, 2-year history
- **Tradetime field**: May represent actual trade or last bid/ask update - check volume > 0 to confirm actual trade
- **Null values**: Some fields return null if data unavailable
- **Pagination**: Max 10,000 offset, 1,000 results per page
- **Sorting**: Use '-' prefix for descending order (e.g., '-exp_date')
- **API call consumption**: 1 request = 10 API calls
- **Rate limits**: 100,000 calls/24h, 1,000 requests/minute

### HTTP Status Codes

The API returns standard HTTP status codes to indicate success or failure:

| Status Code | Meaning | Description |
|-------------|---------|-------------|
| **200** | OK | Request succeeded. Data returned successfully. |
| **402** | Payment Required | API limit used up. Upgrade plan or wait for limit reset. |
| **403** | Unauthorized | Invalid API key. Check your `api_token` parameter. |
| **429** | Too Many Requests | Exceeded rate limit (requests per minute). Slow down requests. |

### Error Response Format

When an error occurs, the API returns a JSON response with error details:

```json
{
  "error": "Error message description",
  "code": 403
}
```

### Handling Errors

**Python Example**:
```python
import requests

def make_api_request(url, params):
    try:
        response = requests.get(url, params=params)
        response.raise_for_status()  # Raises HTTPError for bad status codes
        return response.json()
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 402:
            print("Error: API limit exceeded. Please upgrade your plan.")
        elif e.response.status_code == 403:
            print("Error: Invalid API key. Check your credentials.")
        elif e.response.status_code == 429:
            print("Error: Rate limit exceeded. Please slow down your requests.")
        else:
            print(f"HTTP Error: {e}")
        return None
    except requests.exceptions.RequestException as e:
        print(f"Request failed: {e}")
        return None
```

**Best Practices**:
- Always check status codes before processing response data
- Implement exponential backoff for 429 errors
- Cache responses to reduce API calls
- Monitor your API usage in the user dashboard

---

## US Options EOD (End-of-Day) API

<a id="us-options-eod"></a>

### Endpoint Metadata

| Field | Value |
|---|---|
| Status | complete |
| Source | marketplace (US Stock Options Data API by Unicornbay) |
| Docs | https://eodhd.com/financial-apis/us-stock-options-data-api |
| Provider | EODHD Marketplace |
| Base URL | https://eodhd.com/api |
| Path | /mp/unicornbay/options/eod |
| Method | GET |
| Auth | api_token (query) |
| Slug | `us-options-eod` |
| Source File | `/Users/arnaurodon/Projects/University/Final Thesis/eodhd-claude-skills/skills/eodhd-api/references/endpoints/us-options-eod.md` |

### Purpose

Returns all available end-of-day (EOD) trades or bid data for stock options contracts.
Provides historical daily snapshots including trade timestamps, prices, volumes, bid/ask prices,
Greeks, and contract details. Useful for analyzing daily performance, building historical
volatility surfaces, and backtesting options strategies.

### Inputs

| Parameter | Required | Type | Description |
|-----------|----------|------|-------------|
| api_token | Yes | string | Your API key for authentication |
| filter[contract] | No | string | Filter by specific contract name (e.g., 'AAPL270115P00450000') |
| filter[underlying_symbol] | No | string | Filter by underlying stock symbol (e.g., 'AAPL') |
| filter[exp_date_eq] | No | string (YYYY-MM-DD) | Filter contracts expiring on exact date |
| filter[exp_date_from] | No | string (YYYY-MM-DD) | Filter contracts expiring from date onwards |
| filter[exp_date_to] | No | string (YYYY-MM-DD) | Filter contracts expiring up to date |
| filter[tradetime_eq] | No | string (YYYY-MM-DD) | Filter by exact trade time date |
| filter[tradetime_from] | No | string (YYYY-MM-DD) | Filter by trade time from date onwards |
| filter[tradetime_to] | No | string (YYYY-MM-DD) | Filter by trade time up to date |
| filter[type] | No | string | Contract type: 'put' or 'call' |
| filter[strike_eq] | No | number | Filter by exact strike price |
| filter[strike_from] | No | number | Filter by strike price from value onwards |
| filter[strike_to] | No | number | Filter by strike price up to value |
| sort | No | string | Sort order: 'exp_date', 'strike', '-exp_date', '-strike' |
| page[offset] | No | integer | Pagination offset (default: 0, max: 10000) |
| page[limit] | No | integer | Results per page (default: 1000, max: 1000) |
| fields[options-eod] | No | string | Comma-separated list of fields to include |
| compact | No | boolean | Enable compact mode (1=true) to minimize response size |

### Outputs

### Normal Mode

```json
{
  "meta": {
    "offset": 0,
    "limit": 5,
    "total": 355,
    "fields": ["contract", "underlying_symbol", "exp_date", "..."]
  },
  "data": [
    {
      "id": "AAPL270115P00450000-2026-02-06",
      "type": "options-eod",
      "attributes": {
        "contract": "AAPL270115P00450000",
        "underlying_symbol": "AAPL",
        "exp_date": "2027-01-15",
        "expiration_type": "monthly",
        "type": "put",
        "strike": 450,
        "exchange": "NASDAQ",
        "currency": "USD",
        "open": 0,
        "high": 0,
        "low": 0,
        "last": 245.9,
        "last_size": 0,
        "change": 0,
        "pctchange": 0,
        "previous": 0,
        "previous_date": null,
        "bid": 170.2,
        "bid_date": "2026-02-06 21:00:01",
        "bid_size": 11,
        "ask": 173.3,
        "ask_date": "2026-02-06 21:00:01",
        "ask_size": 111,
        "moneyness": 0.62,
        "volume": 0,
        "volume_change": 0,
        "volume_pctchange": 0,
        "open_interest": 0,
        "open_interest_change": 0,
        "open_interest_pctchange": 0,
        "volatility": 0,
        "volatility_change": 0,
        "volatility_pctchange": 0,
        "theoretical": 0,
        "delta": 0,
        "gamma": 0,
        "theta": 0,
        "vega": 0,
        "rho": 0,
        "tradetime": "2025-06-08",
        "vol_oi_ratio": 0,
        "dte": 342,
        "midpoint": 171.75
      }
    }
  ],
  "links": {
    "next": "https://eodhd.com/api/mp/unicornbay/options/eod?...&page[offset]=5"
  }
}
```

### Compact Mode (compact=1)

Returns data as arrays without field names to minimize response size:

```json
{
  "meta": {
    "fields": ["contract", "exp_date", "strike", "bid", "ask", "..."]
  },
  "data": [
    ["AAPL270115P00450000", "2027-01-15", 450, 170.2, 173.3, ...]
  ]
}
```

### Field Descriptions

| Field | Type | Description |
|-------|------|-------------|
| contract | string | OCC contract identifier |
| underlying_symbol | string | Underlying stock ticker |
| exp_date | string (date) | Expiration date |
| expiration_type | string | 'monthly', 'weekly', 'quarterly' |
| type | string | 'call' or 'put' |
| strike | number | Strike price |
| exchange | string | Exchange code |
| currency | string | Currency (USD) |
| open | number | Opening price for the day |
| high | number | High price for the day |
| low | number | Low price for the day |
| last | number | Last traded price |
| last_size | integer | Size of last trade |
| change | number | Price change |
| pctchange | number | Percentage change |
| previous | number | Previous close |
| previous_date | string | Previous close date |
| bid | number | EOD bid price |
| bid_date | string | Bid timestamp |
| bid_size | integer | Bid size |
| ask | number | EOD ask price |
| ask_date | string | Ask timestamp |
| ask_size | integer | Ask size |
| moneyness | number | Moneyness ratio |
| volume | integer | Daily volume |
| volume_change | integer | Volume change |
| volume_pctchange | number | Volume % change |
| open_interest | integer | Open interest |
| open_interest_change | integer | OI change |
| open_interest_pctchange | number | OI % change |
| volatility | number | Implied volatility |
| volatility_change | number | IV change |
| volatility_pctchange | number | IV % change |
| theoretical | number | Theoretical price |
| delta | number | Delta Greek |
| gamma | number | Gamma Greek |
| theta | number | Theta Greek |
| vega | number | Vega Greek |
| rho | number | Rho Greek |
| tradetime | string (date) | Last market activity date |
| vol_oi_ratio | number | Volume/OI ratio |
| dte | integer | Days to expiration |
| midpoint | number | Bid/ask midpoint |

### Example Requests

```bash
# Historical EOD data for specific contract
curl "https://eodhd.com/api/mp/unicornbay/options/eod?filter[contract]=AAPL270115P00450000&page[limit]=5&sort=-exp_date&api_token=demo"

# EOD data with specific fields
curl "https://eodhd.com/api/mp/unicornbay/options/eod?filter[contract]=AAPL270115P00450000&fields[options-eod]=contract,bid_date,open,high,low,last&page[limit]=100&api_token=demo"

# EOD data in compact mode (reduced response size)
curl "https://eodhd.com/api/mp/unicornbay/options/eod?filter[underlying_symbol]=AAPL&filter[type]=call&compact=1&page[limit]=100&api_token=demo"

# Filter by tradetime range
curl "https://eodhd.com/api/mp/unicornbay/options/eod?filter[underlying_symbol]=AAPL&filter[tradetime_from]=2025-01-01&filter[tradetime_to]=2025-01-31&api_token=demo"
```

### Notes

- **Marketplace Product**: This is a marketplace API (path: `/mp/unicornbay/...`)
- **Historical Data**: Returns daily snapshots - each record represents one day's EOD data
- **ID Format**: `{contract}-{date}` (e.g., 'AAPL270115P00450000-2026-02-06')
- **Compact Mode**: Use `compact=1` to reduce response size for high-volume requests
- **Zero Values**: Greeks and volatility may be zero for illiquid contracts
- **Pagination**: Max 10,000 offset, 1,000 results per page
- **API call consumption**: 1 request = 10 API calls
- **Rate limits**: 100,000 calls/24h, 1,000 requests/minute
- **History**: 2-year historical depth available

### HTTP Status Codes

The API returns standard HTTP status codes to indicate success or failure:

| Status Code | Meaning | Description |
|-------------|---------|-------------|
| **200** | OK | Request succeeded. Data returned successfully. |
| **402** | Payment Required | API limit used up. Upgrade plan or wait for limit reset. |
| **403** | Unauthorized | Invalid API key. Check your `api_token` parameter. |
| **429** | Too Many Requests | Exceeded rate limit (requests per minute). Slow down requests. |

### Error Response Format

When an error occurs, the API returns a JSON response with error details:

```json
{
  "error": "Error message description",
  "code": 403
}
```

### Handling Errors

**Python Example**:
```python
import requests

def make_api_request(url, params):
    try:
        response = requests.get(url, params=params)
        response.raise_for_status()  # Raises HTTPError for bad status codes
        return response.json()
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 402:
            print("Error: API limit exceeded. Please upgrade your plan.")
        elif e.response.status_code == 403:
            print("Error: Invalid API key. Check your credentials.")
        elif e.response.status_code == 429:
            print("Error: Rate limit exceeded. Please slow down your requests.")
        else:
            print(f"HTTP Error: {e}")
        return None
    except requests.exceptions.RequestException as e:
        print(f"Request failed: {e}")
        return None
```

**Best Practices**:
- Always check status codes before processing response data
- Implement exponential backoff for 429 errors
- Cache responses to reduce API calls
- Monitor your API usage in the user dashboard

---

## US Options Underlying Symbols API

<a id="us-options-underlyings"></a>

### Endpoint Metadata

| Field | Value |
|---|---|
| Status | complete |
| Source | marketplace (US Stock Options Data API by Unicornbay) |
| Docs | https://eodhd.com/financial-apis/us-stock-options-data-api |
| Provider | EODHD Marketplace |
| Base URL | https://eodhd.com/api |
| Path | /mp/unicornbay/options/underlying-symbols |
| Method | GET |
| Auth | api_token (query) |
| Slug | `us-options-underlyings` |
| Source File | `/Users/arnaurodon/Projects/University/Final Thesis/eodhd-claude-skills/skills/eodhd-api/references/endpoints/us-options-underlyings.md` |

### Purpose

Retrieves a list of all US stock tickers for which options data is available. Returns
the complete universe of supported underlying symbols for the options API. Essential for
discovering which stocks have options coverage before making contract or EOD data requests.

### Inputs

| Parameter | Required | Type | Description |
|-----------|----------|------|-------------|
| api_token | Yes | string | Your API key for authentication |

### Outputs

```json
{
  "meta": {
    "total": 6479,
    "fields": ["underlying_symbol"],
    "compact": true
  },
  "data": [
    "A",
    "AA",
    "AAAU",
    "AACT",
    "AADI",
    "AAL",
    "AAMI",
    "AAN",
    "AAOI",
    "AAON",
    "AAP",
    "AAPB",
    "AAPD",
    "AAPL",
    "AAPU",
    "AAPW",
    "AAPX",
    "AAPY",
    "..."
  ],
  "links": {
    "next": null
  }
}
```

### Field Descriptions

| Field | Type | Description |
|-------|------|-------------|
| meta.total | integer | Total number of supported underlying symbols |
| meta.fields | array | Fields included in response |
| meta.compact | boolean | Response is in compact format |
| data | array | List of ticker symbols with options data |
| links.next | string/null | URL for next page (null if all data returned) |

### Example Requests

```bash
# Get all underlying symbols with options data
curl "https://eodhd.com/api/mp/unicornbay/options/underlying-symbols?api_token=demo"
```

### Notes

- **Coverage**: 6,000+ US tickers with options data
- **Marketplace Product**: This is a marketplace API (path: `/mp/unicornbay/...`)
- **Compact Format**: Response is always in compact array format
- **Complete List**: Returns all symbols in a single response (no pagination needed typically)
- **Update Frequency**: Symbol list updated as new options become available
- **API call consumption**: 1 request = 10 API calls
- **Rate limits**: 100,000 calls/24h, 1,000 requests/minute
- **Caching**: Symbol list is relatively stable; cache results when appropriate

### HTTP Status Codes

The API returns standard HTTP status codes to indicate success or failure:

| Status Code | Meaning | Description |
|-------------|---------|-------------|
| **200** | OK | Request succeeded. Data returned successfully. |
| **402** | Payment Required | API limit used up. Upgrade plan or wait for limit reset. |
| **403** | Unauthorized | Invalid API key. Check your `api_token` parameter. |
| **429** | Too Many Requests | Exceeded rate limit (requests per minute). Slow down requests. |

### Error Response Format

When an error occurs, the API returns a JSON response with error details:

```json
{
  "error": "Error message description",
  "code": 403
}
```

### Handling Errors

**Python Example**:
```python
import requests

def make_api_request(url, params):
    try:
        response = requests.get(url, params=params)
        response.raise_for_status()  # Raises HTTPError for bad status codes
        return response.json()
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 402:
            print("Error: API limit exceeded. Please upgrade your plan.")
        elif e.response.status_code == 403:
            print("Error: Invalid API key. Check your credentials.")
        elif e.response.status_code == 429:
            print("Error: Rate limit exceeded. Please slow down your requests.")
        else:
            print(f"HTTP Error: {e}")
        return None
    except requests.exceptions.RequestException as e:
        print(f"Request failed: {e}")
        return None
```

**Best Practices**:
- Always check status codes before processing response data
- Implement exponential backoff for 429 errors
- Cache responses to reduce API calls
- Monitor your API usage in the user dashboard

---

## Tick Data API

<a id="us-tick-data"></a>

### Endpoint Metadata

| Field | Value |
|---|---|
| Status | complete |
| Source | financial-apis (Intraday Historical Data API) |
| Docs | https://eodhd.com/financial-apis/intraday-historical-data-api |
| Provider | EODHD |
| Base URL | https://eodhd.com/api |
| Path | /ticks/{SYMBOL} |
| Method | GET |
| Auth | api_token (query) |
| Slug | `us-tick-data` |
| Source File | `/Users/arnaurodon/Projects/University/Final Thesis/eodhd-claude-skills/skills/eodhd-api/references/endpoints/us-tick-data.md` |

### Purpose

Fetches tick-by-tick trade data for a symbol, providing the most granular level of market data.
Each tick represents a single trade execution with timestamp, price, and volume. Useful for
high-frequency analysis, market microstructure research, and detailed intraday pattern analysis.

### Inputs

| Parameter | Required | Type | Description |
|-----------|----------|------|-------------|
| {SYMBOL} | Yes | path | Ticker symbol with exchange suffix (e.g., 'AAPL.US') |
| api_token | Yes | string | Your API key for authentication |
| from | No | integer/string | Start time as Unix timestamp in seconds, or date (YYYY-MM-DD) |
| to | No | integer/string | End time as Unix timestamp in seconds, or date (YYYY-MM-DD) |
| limit | No | integer | Number of ticks to return. Default: 100, Max: 10000 |
| fmt | No | string | Output format: 'json' or 'csv'. Default: 'json' |

### Outputs

```json
[
  {
    "timestamp": 1704888000,
    "gmtoffset": -18000,
    "datetime": "2025-01-10 09:30:00",
    "price": 185.25,
    "volume": 500,
    "mkt": "Q",
    "sl": "@",
    "seq": 1
  },
  {
    "timestamp": 1704888001,
    "gmtoffset": -18000,
    "datetime": "2025-01-10 09:30:01",
    "price": 185.30,
    "volume": 200,
    "mkt": "T",
    "sl": " ",
    "seq": 2
  },
  {
    "timestamp": 1704888002,
    "gmtoffset": -18000,
    "datetime": "2025-01-10 09:30:02",
    "price": 185.28,
    "volume": 1000,
    "mkt": "D",
    "sl": "T",
    "seq": 3
  }
]
```

### Field Descriptions

| Field | Type | Description |
|-------|------|-------------|
| timestamp | integer | Unix timestamp of the trade |
| gmtoffset | integer | GMT offset in seconds for the exchange |
| datetime | string | Human-readable datetime (YYYY-MM-DD HH:MM:SS) |
| price | number | Trade execution price |
| volume | integer | Number of shares traded |
| mkt | string | Market center code (see market center table below). `D` = dark pool |
| sl | string | Sale condition code (exchange-specific trade condition flags) |
| seq | integer | Sequence number for ordering ticks within the same timestamp |

### Example Requests

```bash
# Recent ticks for AAPL (last 100)
curl "https://eodhd.com/api/ticks/AAPL.US?api_token=demo&fmt=json"

# Ticks with limit
curl "https://eodhd.com/api/ticks/AAPL.US?limit=1000&api_token=demo&fmt=json"

# Ticks for specific date (Unix timestamps)
curl "https://eodhd.com/api/ticks/MSFT.US?from=1704888000&to=1704974400&api_token=demo&fmt=json"

# Ticks for date range
curl "https://eodhd.com/api/ticks/GOOGL.US?from=2025-01-10&to=2025-01-10&limit=5000&api_token=demo&fmt=json"
```

### Notes

- Tick data provides trade-level granularity (every individual trade)
- Data volume is very high; use `limit` parameter to control response size
- Unix timestamps in `from`/`to` allow precise time windows
- `gmtoffset` helps convert to local exchange time
- Not all symbols have tick data available; primarily US equities
- Data retention varies; recent data is most reliably available
- For OHLCV bars, use the intraday endpoint instead
- API call consumption: Higher than standard endpoints due to data volume
- Maximum 10,000 ticks per request
- **Building OHLCV from ticks**: Aggregating OHLCV data from tick data is not simply taking the first/max/min/last prices. The process depends on the **sale-condition** of each tick — many ticks may be excluded from the calculation based on conditions from the exchanges. See: https://www.utpplan.com/DOC/UtpBinaryOutputSpec.pdf
- **Timestamps: seconds vs milliseconds**: The `from` and `to` parameters must be specified in **seconds** (Unix timestamp). The result timestamps are returned in **milliseconds**.
- **Dark pool ticks**: Ticks where the market center (`mkt`) field contains `D` are **dark pool** trades (off-exchange).
- **Market center (`mkt`) field codes**:

| Code | Exchange |
|------|----------|
| X | NASDAQ |
| T | NASDAQ |
| B | NASDAQ |
| Q | NASDAQ |
| R | NASDAQ |
| N | NYSE |
| C | NYSE |
| P | NYSE |
| A | NYSE |
| K | CBOE |
| Y | CBOE |
| J | CBOE |
| W | CBOE |
| Z | CBOE |
| V | IEX |
| S, u, U, ?, a | OTC |

### HTTP Status Codes

The API returns standard HTTP status codes to indicate success or failure:

| Status Code | Meaning | Description |
|-------------|---------|-------------|
| **200** | OK | Request succeeded. Data returned successfully. |
| **402** | Payment Required | API limit used up. Upgrade plan or wait for limit reset. |
| **403** | Unauthorized | Invalid API key. Check your `api_token` parameter. |
| **429** | Too Many Requests | Exceeded rate limit (requests per minute). Slow down requests. |

### Error Response Format

When an error occurs, the API returns a JSON response with error details:

```json
{
  "error": "Error message description",
  "code": 403
}
```

### Handling Errors

**Python Example**:
```python
import requests

def make_api_request(url, params):
    try:
        response = requests.get(url, params=params)
        response.raise_for_status()  # Raises HTTPError for bad status codes
        return response.json()
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 402:
            print("Error: API limit exceeded. Please upgrade your plan.")
        elif e.response.status_code == 403:
            print("Error: Invalid API key. Check your credentials.")
        elif e.response.status_code == 429:
            print("Error: Rate limit exceeded. Please slow down your requests.")
        else:
            print(f"HTTP Error: {e}")
        return None
    except requests.exceptions.RequestException as e:
        print(f"Request failed: {e}")
        return None
```

**Best Practices**:
- Always check status codes before processing response data
- Implement exponential backoff for 429 errors
- Cache responses to reduce API calls
- Monitor your API usage in the user dashboard

---

## User Details API

<a id="user-details"></a>

### Endpoint Metadata

| Field | Value |
|---|---|
| Status | complete |
| Source | financial-apis (User API) |
| Docs | https://eodhd.com/financial-apis/user-api |
| Provider | EODHD |
| Base URL | https://eodhd.com/api |
| Path | /internal-user |
| Method | GET |
| Auth | api_token (query) |
| Slug | `user-details` |
| Source File | `/Users/arnaurodon/Projects/University/Final Thesis/eodhd-claude-skills/skills/eodhd-api/references/endpoints/user-details.md` |

### Purpose

Returns account details for the subscriber associated with the given API token. Use this endpoint to verify authentication, check remaining API quota, monitor daily usage, retrieve subscription information, and check Marketplace subscription status including reset times. No symbol or additional parameters are required.

> **Note**: The actual endpoint path is `/api/internal-user`. The legacy `/api/user` path may also work but `/api/internal-user` returns the complete response including `availableDataFeeds` and `availableMarketplaceDataFeeds`.

### Inputs

| Parameter | Required | Type | Description |
|-----------|----------|------|-------------|
| api_token | Yes | string | Your API access token |

### Outputs

```json
{
  "name": "Helmut Schiller",
  "email": "helmut.shiller@gmx.de",
  "subscriptionType": "monthly",
  "paymentMethod": "PayPal",
  "apiRequests": 5301,
  "apiRequestsDate": "2026-01-25",
  "dailyRateLimit": 100000,
  "extraLimit": 500,
  "inviteToken": null,
  "inviteTokenClicked": 0,
  "subscriptionMode": "paid",
  "canManageOrganizations": false,
  "availableDataFeeds": [
    "Bulk Splits and Dividends API",
    "News API",
    "EOD Historical Data",
    "Search API",
    "dividends",
    "Dividends Data Feed",
    "Split Data Feed",
    "Live (delayed) Data API",
    "CBOE Data API",
    "Sentiment Data API",
    "Exchanges List API",
    "Daily Treasury Bill Rates",
    "Daily Treasury Real Long-Term Rates, Daily Treasury Long-Term Rates",
    "Daily Treasury Par Yield Curve Rates",
    "Daily Treasury Par Real Yield Curve Rates"
  ],
  "availableMarketplaceDataFeeds": {
    "dailyRateLimit": 100000,
    "requestsSpent": 80,
    "timeToReset": "19:01 GMT+0000",
    "subscriptions": ["US Stock Options Data API"]
  }
}
```

> **Note**: When no Marketplace subscriptions are active, `availableMarketplaceDataFeeds` is an empty array `[]` instead of an object.

### Output Format

| Field | Type | Description |
|-------|------|-------------|
| name | string | Name of the subscriber associated with the API token |
| email | string | Email of the subscriber associated with the API token |
| subscriptionType | string | Subscription type (e.g., monthly, yearly, commercial) |
| paymentMethod | string | Payment method (e.g., PayPal, Stripe, Wire, Not Available) |
| apiRequests | integer | Number of API calls on the latest day of API usage. Resets at midnight GMT, but shows the previous day's count until a new request is made after reset |
| apiRequestsDate | string (YYYY-MM-DD) | Date of the latest API request |
| dailyRateLimit | integer | Maximum number of API calls allowed per day for the main subscription |
| extraLimit | integer | Remaining amount of additionally purchased API calls |
| inviteToken | string\|null | Invitation token for the affiliate program |
| inviteTokenClicked | integer | Number of invite token clicks |
| subscriptionMode | string | Subscription mode: `demo`, `free`, or `paid` |
| canManageOrganizations | boolean | Whether the user can manage organizations |
| availableDataFeeds | array | List of available data feed names for the main subscription |
| availableMarketplaceDataFeeds | object\|array | Marketplace subscription info (object when active, empty array `[]` when none) |

### Marketplace Data Feeds Object

When Marketplace subscriptions are active, `availableMarketplaceDataFeeds` is an object:

| Field | Type | Description |
|-------|------|-------------|
| dailyRateLimit | integer | Maximum daily API calls per Marketplace subscription (100,000) |
| requestsSpent | integer | Number of Marketplace API calls used in the current 24-hour period |
| timeToReset | string | Time when all Marketplace subscription limits reset (e.g., `19:01 GMT+0000`). Shared across all Marketplace products — based on when the user first made any Marketplace API request. |
| subscriptions | array | List of active Marketplace subscription names |

### Example Requests

```bash
# Get user details (recommended endpoint)
curl "https://eodhd.com/api/internal-user?api_token=YOUR_TOKEN"

# Using the demo key
curl "https://eodhd.com/api/internal-user?api_token=demo"

# Using the helper client
python eodhd_client.py --endpoint user
```

### Notes

- No symbol or date parameters are required
- The `apiRequests` counter resets at midnight GMT each day (for the main subscription)
- The count shown reflects the latest day any request was made; it does not update until a new request occurs after the midnight reset
- API calls vs API requests: some endpoints consume more than 1 API call per request (see rate-limits.md for details)
- Useful for verifying that your API token is valid and checking remaining quota before making data requests
- API call consumption: 1 call per request
- **Marketplace limits**: The `availableMarketplaceDataFeeds.timeToReset` field shows when all Marketplace subscription limits reset. Each Marketplace subscription has its own separate 100,000-call limit, but they all share the same reset time.
- **Marketplace reset time**: The reset time is based on when the user first made any Marketplace API request. All Marketplace subscriptions reset at this same time every 24 hours.

### HTTP Status Codes

The API returns standard HTTP status codes to indicate success or failure:

| Status Code | Meaning | Description |
|-------------|---------|-------------|
| **200** | OK | Request succeeded. Data returned successfully. |
| **402** | Payment Required | API limit used up. Upgrade plan or wait for limit reset. |
| **403** | Unauthorized | Invalid API key. Check your `api_token` parameter. |
| **429** | Too Many Requests | Exceeded rate limit (requests per minute). Slow down requests. |

### Error Response Format

When an error occurs, the API returns a JSON response with error details:

```json
{
  "error": "Error message description",
  "code": 403
}
```

### Handling Errors

**Python Example**:
```python
import requests

def make_api_request(url, params):
    try:
        response = requests.get(url, params=params)
        response.raise_for_status()  # Raises HTTPError for bad status codes
        return response.json()
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 402:
            print("Error: API limit exceeded. Please upgrade your plan.")
        elif e.response.status_code == 403:
            print("Error: Invalid API key. Check your credentials.")
        elif e.response.status_code == 429:
            print("Error: Rate limit exceeded. Please slow down your requests.")
        else:
            print(f"HTTP Error: {e}")
        return None
    except requests.exceptions.RequestException as e:
        print(f"Request failed: {e}")
        return None
```

**Best Practices**:
- Always check status codes before processing response data
- Implement exponential backoff for 429 errors
- Cache responses to reduce API calls
- Monitor your API usage in the user dashboard

---

## US Treasury Bill Rates API

<a id="ust-bill-rates"></a>

### Endpoint Metadata

| Field | Value |
|---|---|
| Status | complete |
| Source | financial-apis (US Treasury API) |
| Docs | https://eodhd.com/financial-apis/us-treasury-interest-rates-api |
| Provider | EODHD |
| Base URL | https://eodhd.com/api |
| Path | /ust/bill-rates |
| Method | GET |
| Auth | api_token (query) |
| Slug | `ust-bill-rates` |
| Source File | `/Users/arnaurodon/Projects/University/Final Thesis/eodhd-claude-skills/skills/eodhd-api/references/endpoints/ust-bill-rates.md` |

### Purpose

Provides Daily Treasury Bill Rates (T-Bills): discount and coupon rates, average rates, maturity, and CUSIP. These time series are widely used for macro research, fixed-income analytics, discounting/cost of capital, yield curve modeling, and building risk-free rate baselines in trading/portfolio systems. Available in All-In-One, EOD Historical Data: All World, EOD + Intraday: All World Extended, and Free plans.

### Inputs

| Parameter | Required | Type | Description |
|-----------|----------|------|-------------|
| api_token | Yes | string | Your API key |
| filter[year] | No | integer | Filter by year (1900 – current year + 1). If not mentioned – current year |
| page[limit] | No | integer | Number of records per page |
| page[offset] | No | integer | Offset for pagination |
| fmt | No | string | Output format: 'json' |

### Outputs

```json
{
  "meta": {
    "total": 120
  },
  "data": [
    {
      "date": "2026-01-02",
      "tenor": "4WK",
      "discount": 3.58,
      "coupon": 3.64,
      "avg_discount": 3.58,
      "avg_coupon": 3.64,
      "maturity_date": "2026-02-03",
      "cusip": "912797SJ7"
    },
    {
      "date": "2026-01-02",
      "tenor": "8WK",
      "discount": 3.57,
      "coupon": 3.64,
      "avg_discount": 3.57,
      "avg_coupon": 3.64,
      "maturity_date": "2026-03-03",
      "cusip": "912797ST5"
    }
  ],
  "links": {
    "next": null
  }
}
```

### Output Format

**Top-level fields:**

| Field | Type | Description |
|-------|------|-------------|
| meta | object | Metadata including total record count |
| data | array | Array of bill rate records |
| links | object | Pagination links (next page URL or null) |

**Data item fields:**

| Field | Type | Description |
|-------|------|-------------|
| date | string (YYYY-MM-DD) | Observation date |
| tenor | string | Bill tenor (e.g., 4WK, 8WK, 13WK, 17WK, 26WK, 52WK) |
| discount | number | Discount rate |
| coupon | number | Coupon equivalent rate |
| avg_discount | number | Average discount rate |
| avg_coupon | number | Average coupon equivalent rate |
| maturity_date | string (YYYY-MM-DD) | Maturity date |
| cusip | string | CUSIP identifier |

### Example Requests

```bash
# Bill rates for 2012
curl "https://eodhd.com/api/ust/bill-rates?api_token=YOUR_TOKEN&filter[year]=2012&page[limit]=100&page[offset]=0"

# Bill rates for current year
curl "https://eodhd.com/api/ust/bill-rates?api_token=YOUR_TOKEN"

# Using the helper client
python eodhd_client.py --endpoint ust/bill-rates --filter-year 2012 --limit 100
```

### Notes

- Returns data grouped by date and tenor
- Common tenors include 4WK, 8WK, 13WK, 17WK, 26WK, and 52WK
- If `filter[year]` is omitted, defaults to the current year
- Pagination is supported via `page[limit]` and `page[offset]`
- API call consumption: 1 call per request
- Part of the US Treasury (UST) Interest Rates API (beta)

### HTTP Status Codes

The API returns standard HTTP status codes to indicate success or failure:

| Status Code | Meaning | Description |
|-------------|---------|-------------|
| **200** | OK | Request succeeded. Data returned successfully. |
| **402** | Payment Required | API limit used up. Upgrade plan or wait for limit reset. |
| **403** | Unauthorized | Invalid API key. Check your `api_token` parameter. |
| **429** | Too Many Requests | Exceeded rate limit (requests per minute). Slow down requests. |

### Error Response Format

When an error occurs, the API returns a JSON response with error details:

```json
{
  "error": "Error message description",
  "code": 403
}
```

### Handling Errors

**Python Example**:
```python
import requests

def make_api_request(url, params):
    try:
        response = requests.get(url, params=params)
        response.raise_for_status()  # Raises HTTPError for bad status codes
        return response.json()
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 402:
            print("Error: API limit exceeded. Please upgrade your plan.")
        elif e.response.status_code == 403:
            print("Error: Invalid API key. Check your credentials.")
        elif e.response.status_code == 429:
            print("Error: Rate limit exceeded. Please slow down your requests.")
        else:
            print(f"HTTP Error: {e}")
        return None
    except requests.exceptions.RequestException as e:
        print(f"Request failed: {e}")
        return None
```

**Best Practices**:
- Always check status codes before processing response data
- Implement exponential backoff for 429 errors
- Cache responses to reduce API calls
- Monitor your API usage in the user dashboard

---

## US Treasury Long-Term Rates API

<a id="ust-long-term-rates"></a>

### Endpoint Metadata

| Field | Value |
|---|---|
| Status | complete |
| Source | financial-apis (US Treasury API) |
| Docs | https://eodhd.com/financial-apis/us-treasury-interest-rates-api |
| Provider | EODHD |
| Base URL | https://eodhd.com/api |
| Path | /ust/long-term-rates |
| Method | GET |
| Auth | api_token (query) |
| Slug | `ust-long-term-rates` |
| Source File | `/Users/arnaurodon/Projects/University/Final Thesis/eodhd-claude-skills/skills/eodhd-api/references/endpoints/ust-long-term-rates.md` |

### Purpose

Provides long-term Treasury rates. This feed combines "Daily Treasury Real Long-Term Rate Averages" and "Daily Treasury Long-Term Rates" into one dataset. Rate types include BC_20year, Over_10_Years, and Real_Rate. Used for macro research, fixed-income analytics, discounting/cost of capital, and building risk-free rate baselines. Available in All-In-One, EOD Historical Data: All World, EOD + Intraday: All World Extended, and Free plans.

### Inputs

| Parameter | Required | Type | Description |
|-----------|----------|------|-------------|
| api_token | Yes | string | Your API key |
| filter[year] | No | integer | Filter by year (1900 – current year + 1). If not mentioned – current year |
| page[limit] | No | integer | Number of results per page |
| page[offset] | No | integer | Pagination offset |
| fmt | No | string | Output format: 'json' |

### Outputs

```json
{
  "meta": {
    "total": 60
  },
  "data": [
    {
      "date": "2026-01-02",
      "rate_type": "BC_20year",
      "rate": 4.81,
      "extrapolation_factor": null
    },
    {
      "date": "2026-01-02",
      "rate_type": "Over_10_Years",
      "rate": 4.78,
      "extrapolation_factor": null
    },
    {
      "date": "2026-01-02",
      "rate_type": "Real_Rate",
      "rate": 2.55,
      "extrapolation_factor": null
    }
  ],
  "links": {
    "next": null
  }
}
```

### Output Format

**Top-level fields:**

| Field | Type | Description |
|-------|------|-------------|
| meta | object | Metadata including total record count |
| data | array | Array of long-term rate records |
| links | object | Pagination links (next page URL or null) |

**Data item fields:**

| Field | Type | Description |
|-------|------|-------------|
| date | string (YYYY-MM-DD) | Observation date |
| rate_type | string | Rate series identifier (BC_20year, Over_10_Years, Real_Rate) |
| rate | number | Rate value |
| extrapolation_factor | number or null | Extrapolation factor where applicable |

### Example Requests

```bash
# Long-term rates for 2020
curl "https://eodhd.com/api/ust/long-term-rates?api_token=YOUR_TOKEN&filter[year]=2020"

# Long-term rates for current year
curl "https://eodhd.com/api/ust/long-term-rates?api_token=YOUR_TOKEN"

# Using the helper client
python eodhd_client.py --endpoint ust/long-term-rates --filter-year 2020
```

### Notes

- Returns three rate types per observation date: BC_20year, Over_10_Years, and Real_Rate
- BC_20year: Treasury 20-year constant maturity rate
- Over_10_Years: Composite rate over 10-year maturity
- Real_Rate: Real long-term rate average
- If `filter[year]` is omitted, defaults to the current year
- The extrapolation_factor field may be null for most records
- API call consumption: 1 call per request
- Part of the US Treasury (UST) Interest Rates API (beta)

### HTTP Status Codes

The API returns standard HTTP status codes to indicate success or failure:

| Status Code | Meaning | Description |
|-------------|---------|-------------|
| **200** | OK | Request succeeded. Data returned successfully. |
| **402** | Payment Required | API limit used up. Upgrade plan or wait for limit reset. |
| **403** | Unauthorized | Invalid API key. Check your `api_token` parameter. |
| **429** | Too Many Requests | Exceeded rate limit (requests per minute). Slow down requests. |

### Error Response Format

When an error occurs, the API returns a JSON response with error details:

```json
{
  "error": "Error message description",
  "code": 403
}
```

### Handling Errors

**Python Example**:
```python
import requests

def make_api_request(url, params):
    try:
        response = requests.get(url, params=params)
        response.raise_for_status()  # Raises HTTPError for bad status codes
        return response.json()
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 402:
            print("Error: API limit exceeded. Please upgrade your plan.")
        elif e.response.status_code == 403:
            print("Error: Invalid API key. Check your credentials.")
        elif e.response.status_code == 429:
            print("Error: Rate limit exceeded. Please slow down your requests.")
        else:
            print(f"HTTP Error: {e}")
        return None
    except requests.exceptions.RequestException as e:
        print(f"Request failed: {e}")
        return None
```

**Best Practices**:
- Always check status codes before processing response data
- Implement exponential backoff for 429 errors
- Cache responses to reduce API calls
- Monitor your API usage in the user dashboard

---

## US Treasury Real Yield Rates API (Par Real Yield Curve)

<a id="ust-real-yield-rates"></a>

### Endpoint Metadata

| Field | Value |
|---|---|
| Status | complete |
| Source | financial-apis (US Treasury API) |
| Docs | https://eodhd.com/financial-apis/us-treasury-interest-rates-api |
| Provider | EODHD |
| Base URL | https://eodhd.com/api |
| Path | /ust/real-yield-rates |
| Method | GET |
| Auth | api_token (query) |
| Slug | `ust-real-yield-rates` |
| Source File | `/Users/arnaurodon/Projects/University/Final Thesis/eodhd-claude-skills/skills/eodhd-api/references/endpoints/ust-real-yield-rates.md` |

### Purpose

Provides Daily Treasury Par Real Yield Curve Rates (real yield curve by tenor). Returns inflation-adjusted yields across maturities from 5 years to 30 years. Used for real return analysis, inflation expectations (comparing nominal vs real yields), TIPS pricing, and macro research. Available in All-In-One, EOD Historical Data: All World, EOD + Intraday: All World Extended, and Free plans.

### Inputs

| Parameter | Required | Type | Description |
|-----------|----------|------|-------------|
| api_token | Yes | string | Your API key |
| filter[year] | No | integer | Filter by year (1900 – current year + 1). If not mentioned – current year |
| page[limit] | No | integer | Number of results per page |
| page[offset] | No | integer | Pagination offset |
| fmt | No | string | Output format: 'json' |

### Outputs

```json
{
  "meta": {
    "total": 100
  },
  "data": [
    {
      "date": "2026-01-02",
      "tenor": "5Y",
      "rate": 1.46
    },
    {
      "date": "2026-01-02",
      "tenor": "7Y",
      "rate": 1.69
    },
    {
      "date": "2026-01-02",
      "tenor": "10Y",
      "rate": 1.94
    },
    {
      "date": "2026-01-02",
      "tenor": "20Y",
      "rate": 2.39
    },
    {
      "date": "2026-01-02",
      "tenor": "30Y",
      "rate": 2.63
    }
  ],
  "links": {
    "next": null
  }
}
```

### Output Format

**Top-level fields:**

| Field | Type | Description |
|-------|------|-------------|
| meta | object | Metadata including total record count |
| data | array | Array of real yield rate records |
| links | object | Pagination links (next page URL or null) |

**Data item fields:**

| Field | Type | Description |
|-------|------|-------------|
| date | string (YYYY-MM-DD) | Observation date |
| tenor | string | Tenor (e.g., 5Y, 7Y, 10Y, 20Y, 30Y) |
| rate | number | Real yield for the given tenor |

### Example Requests

```bash
# Real yield rates for 2024
curl "https://eodhd.com/api/ust/real-yield-rates?api_token=YOUR_TOKEN&filter[year]=2024"

# Real yield rates for current year
curl "https://eodhd.com/api/ust/real-yield-rates?api_token=YOUR_TOKEN"

# Using the helper client
python eodhd_client.py --endpoint ust/real-yield-rates --filter-year 2024
```

### Notes

- Returns five tenors per observation date: 5Y, 7Y, 10Y, 20Y, and 30Y
- Real yields reflect inflation-adjusted returns (derived from TIPS)
- Comparing nominal yields (from yield-rates endpoint) with real yields gives implied inflation expectations (breakeven inflation)
- If `filter[year]` is omitted, defaults to the current year
- API call consumption: 1 call per request
- Part of the US Treasury (UST) Interest Rates API (beta)

### HTTP Status Codes

The API returns standard HTTP status codes to indicate success or failure:

| Status Code | Meaning | Description |
|-------------|---------|-------------|
| **200** | OK | Request succeeded. Data returned successfully. |
| **402** | Payment Required | API limit used up. Upgrade plan or wait for limit reset. |
| **403** | Unauthorized | Invalid API key. Check your `api_token` parameter. |
| **429** | Too Many Requests | Exceeded rate limit (requests per minute). Slow down requests. |

### Error Response Format

When an error occurs, the API returns a JSON response with error details:

```json
{
  "error": "Error message description",
  "code": 403
}
```

### Handling Errors

**Python Example**:
```python
import requests

def make_api_request(url, params):
    try:
        response = requests.get(url, params=params)
        response.raise_for_status()  # Raises HTTPError for bad status codes
        return response.json()
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 402:
            print("Error: API limit exceeded. Please upgrade your plan.")
        elif e.response.status_code == 403:
            print("Error: Invalid API key. Check your credentials.")
        elif e.response.status_code == 429:
            print("Error: Rate limit exceeded. Please slow down your requests.")
        else:
            print(f"HTTP Error: {e}")
        return None
    except requests.exceptions.RequestException as e:
        print(f"Request failed: {e}")
        return None
```

**Best Practices**:
- Always check status codes before processing response data
- Implement exponential backoff for 429 errors
- Cache responses to reduce API calls
- Monitor your API usage in the user dashboard

---

## US Treasury Yield Rates API (Par Yield Curve)

<a id="ust-yield-rates"></a>

### Endpoint Metadata

| Field | Value |
|---|---|
| Status | complete |
| Source | financial-apis (US Treasury API) |
| Docs | https://eodhd.com/financial-apis/us-treasury-interest-rates-api |
| Provider | EODHD |
| Base URL | https://eodhd.com/api |
| Path | /ust/yield-rates |
| Method | GET |
| Auth | api_token (query) |
| Slug | `ust-yield-rates` |
| Source File | `/Users/arnaurodon/Projects/University/Final Thesis/eodhd-claude-skills/skills/eodhd-api/references/endpoints/ust-yield-rates.md` |

### Purpose

Provides Daily Treasury Par Yield Curve Rates (nominal yield curve by tenor). Returns the full nominal yield curve across multiple maturities from 1 month to 30 years. Used for yield curve modeling, fixed-income pricing, term structure analysis, and macro research. Available in All-In-One, EOD Historical Data: All World, EOD + Intraday: All World Extended, and Free plans.

### Inputs

| Parameter | Required | Type | Description |
|-----------|----------|------|-------------|
| api_token | Yes | string | Your API key |
| filter[year] | No | integer | Filter by year (1900 – current year + 1). If not mentioned – current year |
| page[limit] | No | integer | Number of results per page |
| page[offset] | No | integer | Pagination offset |
| fmt | No | string | Output format: 'json' |

### Outputs

```json
{
  "meta": {
    "total": 280
  },
  "data": [
    {
      "date": "2026-01-02",
      "tenor": "1M",
      "rate": 3.72
    },
    {
      "date": "2026-01-02",
      "tenor": "3M",
      "rate": 3.65
    },
    {
      "date": "2026-01-02",
      "tenor": "6M",
      "rate": 3.58
    },
    {
      "date": "2026-01-02",
      "tenor": "1Y",
      "rate": 3.47
    },
    {
      "date": "2026-01-02",
      "tenor": "2Y",
      "rate": 3.24
    },
    {
      "date": "2026-01-02",
      "tenor": "10Y",
      "rate": 3.15
    },
    {
      "date": "2026-01-02",
      "tenor": "30Y",
      "rate": 3.40
    }
  ],
  "links": {
    "next": null
  }
}
```

### Output Format

**Top-level fields:**

| Field | Type | Description |
|-------|------|-------------|
| meta | object | Metadata including total record count |
| data | array | Array of yield rate records |
| links | object | Pagination links (next page URL or null) |

**Data item fields:**

| Field | Type | Description |
|-------|------|-------------|
| date | string (YYYY-MM-DD) | Observation date |
| tenor | string | Tenor (e.g., 1M, 1.5M, 2M, 3M, 4M, 6M, 1Y, 2Y, 3Y, 5Y, 7Y, 10Y, 20Y, 30Y) |
| rate | number | Par yield for the given tenor |

### Example Requests

```bash
# Yield rates for 2023
curl "https://eodhd.com/api/ust/yield-rates?api_token=YOUR_TOKEN&filter[year]=2023"

# Yield rates for current year
curl "https://eodhd.com/api/ust/yield-rates?api_token=YOUR_TOKEN"

# Using the helper client
python eodhd_client.py --endpoint ust/yield-rates --filter-year 2023
```

### Notes

- Returns multiple tenors per observation date, covering the full yield curve
- Available tenors include: 1M, 1.5M, 2M, 3M, 4M, 6M, 1Y, 2Y, 3Y, 5Y, 7Y, 10Y, 20Y, 30Y
- If `filter[year]` is omitted, defaults to the current year
- Useful for constructing yield curves, calculating spreads (e.g., 2Y-10Y spread), and term structure analysis
- API call consumption: 1 call per request
- Part of the US Treasury (UST) Interest Rates API (beta)

### HTTP Status Codes

The API returns standard HTTP status codes to indicate success or failure:

| Status Code | Meaning | Description |
|-------------|---------|-------------|
| **200** | OK | Request succeeded. Data returned successfully. |
| **402** | Payment Required | API limit used up. Upgrade plan or wait for limit reset. |
| **403** | Unauthorized | Invalid API key. Check your `api_token` parameter. |
| **429** | Too Many Requests | Exceeded rate limit (requests per minute). Slow down requests. |

### Error Response Format

When an error occurs, the API returns a JSON response with error details:

```json
{
  "error": "Error message description",
  "code": 403
}
```

### Handling Errors

**Python Example**:
```python
import requests

def make_api_request(url, params):
    try:
        response = requests.get(url, params=params)
        response.raise_for_status()  # Raises HTTPError for bad status codes
        return response.json()
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 402:
            print("Error: API limit exceeded. Please upgrade your plan.")
        elif e.response.status_code == 403:
            print("Error: Invalid API key. Check your credentials.")
        elif e.response.status_code == 429:
            print("Error: Rate limit exceeded. Please slow down your requests.")
        else:
            print(f"HTTP Error: {e}")
        return None
    except requests.exceptions.RequestException as e:
        print(f"Request failed: {e}")
        return None
```

**Best Practices**:
- Always check status codes before processing response data
- Implement exponential backoff for 429 errors
- Cache responses to reduce API calls
- Monitor your API usage in the user dashboard

---

## WebSockets Real-Time Data API

<a id="websockets-realtime"></a>

### Endpoint Metadata

| Field | Value |
|---|---|
| Status | complete |
| Source | financial-apis |
| Provider | EODHD (sourced from Finage, proxied via EODHD ACDC service) |
| Base URL | `wss://ws.eodhistoricaldata.com` |
| Path | `/ws/{market}` where market is `us`, `us-quote`, `forex`, or `crypto` |
| Method | WebSocket (persistent connection) |
| Auth | `api_token` query parameter validated during handshake |
| Slug | `websockets-realtime` |
| Source File | `/Users/arnaurodon/Projects/University/Final Thesis/eodhd-claude-skills/skills/eodhd-api/references/endpoints/websockets-realtime.md` |
