# Data Providers Guide — Credentials, Pricing & Contact Strategy

> **Purpose**: Reference for all external data providers used by the worldview platform.
> Covers: how to get credentials, subscription plans, cost estimates, CEO/founder info,
> and a detailed contact strategy for academic discounts and relationship building.
>
> **Last updated**: 2026-04-09

---

## Table of Contents

1. [Provider Inventory](#1-provider-inventory)
2. [Market Data Providers](#2-market-data-providers)
   - [EODHD](#21-eodhd-primary---market-data--news)
   - [Alpha Vantage](#22-alpha-vantage---market-data-fallback)
   - [Polygon.io / Massive](#23-polygonio-now-massive---market-data-stub)
   - [Finnhub](#24-finnhub---financial-news--earnings)
3. [News & Filing Providers](#3-news--filing-providers)
   - [NewsAPI](#31-newsapi---news-articles)
   - [SEC EDGAR](#32-sec-edgar---sec-filings)
4. [Email Providers](#4-email-providers)
   - [Resend](#41-resend---primary-email)
   - [SendGrid](#42-sendgrid---secondary-email)
   - [Brevo](#43-brevo---smtp-relay-alternative)
5. [LLM Providers](#5-llm-providers)
   - [DeepInfra](#51-deepinfra---llm-chat-primary)
   - [OpenRouter](#52-openrouter---llm-chat-fallback)
   - [Groq](#53-groq---llm-chat-fallback-2)
   - [Google Gemini](#54-google-gemini---entity-descriptions)
6. [Prediction Market Providers](#6-prediction-market-providers)
   - [Polymarket](#61-polymarket---prediction-markets)
7. [Brokerage Integration Providers](#7-brokerage-integration-providers)
   - [SnapTrade](#71-snaptrade---brokerage-sync)
8. [Cost Estimate Summary](#8-cost-estimate-summary)
9. [EODHD — Deep Dive Contact Strategy](#9-eodhd--deep-dive-contact-strategy)

---

## 1. Provider Inventory

| Provider | Category | Service | Status | Env Var |
|----------|----------|---------|--------|---------|
| EODHD | Market Data + News | S2, S3, S4, S7 | Active | `EODHD_API_KEY` |
| Alpha Vantage | Market Data | S2 | Active (fallback) | `MARKET_INGESTION_ALPHA_VANTAGE_API_KEY` |
| Polygon.io (Massive) | Market Data | S2 | Stub | `MARKET_INGESTION_POLYGON_API_KEY` |
| Finnhub | News + Earnings | S4 | Active | `FINNHUB_API_KEY` |
| NewsAPI | News | S4 | Active (dev only) | `NEWSAPI_KEY` |
| SEC EDGAR | SEC Filings | S4 | Active | `SEC_EDGAR_USER_AGENT` |
| Resend | Email | S10 | Active (primary) | `ALERT_RESEND_API_KEY` |
| SendGrid | Email | S10 | Active (secondary) | `ALERT_SENDGRID_API_KEY` |
| Brevo | Email (SMTP) | S10 | Alternative | `ALERT_BREVO_SMTP_KEY` |
| DeepInfra | LLM Chat | S8 | Active | `RAG_CHAT_DEEPINFRA_API_KEY` |
| OpenRouter | LLM Chat | S8 | Active (fallback) | `RAG_CHAT_OPENROUTER_API_KEY` |
| Groq | LLM Chat | S8 | Active (fallback 2) | `RAG_CHAT_GROQ_API_KEY` |
| Google Gemini | Entity Descriptions | S7 | Configured/disabled | `KNOWLEDGE_GRAPH_GEMINI_API_KEY` |
| Polymarket | Prediction Markets | S4 | Active (read-only) | *(none required for read)* |
| SnapTrade | Brokerage Sync | S1 | PRD-0022 | `SNAPTRADE_CLIENT_ID`, `SNAPTRADE_CONSUMER_KEY` |

---

## 2. Market Data Providers

### 2.1 EODHD (Primary — Market Data + News)

**Website**: https://eodhd.com

#### Getting Credentials
1. Register at https://eodhd.com/register (email, Google, or GitHub OAuth)
2. API key is **generated instantly** — no credit card required
3. A `demo` API key also works without an account (limited to 6 tickers: AAPL.US, TSLA.US, AMZN.US, VTI.US, BTC-USD.CC, EURUSD.FOREX)
4. Set `EODHD_API_KEY=<your_key>` in your environment

#### Subscription Plans (EUR)

| Plan | Monthly | Annual | Daily Calls | Key Data Types |
|------|---------|--------|-------------|----------------|
| **Free** | €0 | — | 20 | EOD 1yr, demo tickers only |
| EOD All World | €19.99 | €199.90 | 100,000 | 30yr OHLCV all tickers |
| EOD + Intraday | €29.99 | €299.90 | 100,000 | + intraday, technicals, screener |
| **Fundamentals Feed** | **€59.99** | **€599.90** | 100,000 | + fundamentals, insider transactions, macro indicators, calendars |
| **All-In-One** | **€99.99** | **€999.90** | 100,000 | + financial news, real-time WebSocket |
| Internal Use | €399 | €3,990 | Unlimited | Commercial license |
| Enterprise | €2,499 | €24,990 | Unlimited | Full enterprise |

#### Which Plan Does This Project Need?

The project uses EODHD for:
- **S4 (content-ingestion)**: Financial news (`/api/news` endpoint)
- **S7 (knowledge-graph)**: Fundamentals, macro indicators, insider transactions
- **S2 (market-ingestion)**: EOD OHLCV data

The **Fundamentals Feed (€59.99/mo)** covers everything except news. If S4's EODHD news adapter is used, upgrade to **All-In-One (€99.99/mo)**.

#### Academic Discount
- **50% off for 12 months** for students and educators
- After 12 months: full price applies automatically
- Contact: `anna@eodhistoricaldata.com`
- University partnerships page: https://eodhd.com/lp/universities

#### Founder & Team
| Role | Name | LinkedIn |
|------|------|---------|
| **CEO & Founder** | Denis Alaev | https://linkedin.com/in/denisalaev/ |
| CTO | Evgenii Elesin | — |
| Partnership Manager | Anna Vakhova | anna@eodhistoricaldata.com |

**Company profile**: Bootstrapped from a €10/month server (2015), now ~$3.5M ARR, ~15 employees, headquartered in Lyon, France. No VC funding. Denis previously worked at Yandex, Mail.ru, and Ahrefs.

> See [Section 9](#9-eodhd--deep-dive-contact-strategy) for the full contact strategy including email templates and relationship-building recommendations.

---

### 2.2 Alpha Vantage — Market Data Fallback

**Website**: https://alphavantage.co

#### Getting Credentials
1. Go to https://alphavantage.co/support/ → "Get free API key"
2. Select category "Student", enter your email — key delivered instantly
3. No credit card required

#### Plans

| Plan | Monthly | Annual | Rate Limit |
|------|---------|--------|-----------|
| Free | $0 | — | 5 req/min, **25 req/day** |
| Plan 1 | $49.99 | $499/yr | 75 req/min, unlimited |
| Plan 2 | $99.99 | $999/yr | 150 req/min |
| Plan 3 | $149.99 | $1,499/yr | 300 req/min |
| Plan 4 | $199.99 | $1,999/yr | 600 req/min |
| Plan 5 | $249.99 | $2,499/yr | 1,200 req/min |

All tiers include: OHLCV (20+ years history), fundamentals, indicators, forex, crypto, commodities, macro, earnings transcripts. Free tier is rate-limited to 25 req/day (too slow for production ingestion).

#### CEO/Founder
**Olivier Porté** — Harvard AB/MBA, former Morgan Stanley. YC alumnus. LinkedIn: https://linkedin.com/in/olivier-porte/

No academic discount program. The free tier (25 req/day) is the practical student offering.

---

### 2.3 Polygon.io (now Massive) — Market Data Stub

**Website**: https://polygon.io (redirects to https://massive.com)

> **Note**: Polygon.io rebranded to **Massive** on October 30, 2025. All existing API keys and integrations continue working.

#### Getting Credentials
1. Sign up at https://polygon.io → email + password, API key issued instantly
2. No credit card required for the free tier

#### Plans (Stocks)

| Plan | Monthly | Data | Rate Limit |
|------|---------|------|-----------|
| Basic (Free) | $0 | EOD only | 5 req/min |
| Starter | ~$29 | 15-min delayed, 5yr history | Unlimited |
| Developer | ~$79–$200 | Real-time, tick data, 15yr history | Unlimited |
| Advanced | ~$500 | Full history, market events | Unlimited |

Multi-asset bundles (stocks + options + crypto + forex) can exceed $500–$1,000+/month.

**Student discount**: **20% off** via Student Beans (https://studentbeans.com). Education partnerships page: https://massive.com/education

#### CEO/Founder
**Quinton Pike** — Founder. Ex-Google, ex-CNN. LinkedIn: https://linkedin.com/in/quintonpike

> Currently only a stub adapter in S2 (raises `ProviderUnavailable`). Implement when needed. Starter (~$29/mo) is sufficient for 15-min delayed data.

---

### 2.4 Finnhub — Financial News + Earnings

**Website**: https://finnhub.io

#### Getting Credentials
1. Register at https://finnhub.io/register — email only, no credit card
2. Verify email
3. API key available immediately in the dashboard
4. Authenticate via `token` query param or `X-Finnhub-Token` header

#### Plans

| Plan | Monthly | Rate Limit | Notes |
|------|---------|-----------|-------|
| **Free** | **$0** | **60 req/min** | Company news, SEC filings, insider transactions, real-time US quotes, earnings transcripts, alternative data |
| Market Data Basic | $49.99 | Higher | More international coverage |
| Fundamental Data Tier 1 | $50.00 | — | Deeper financials |
| Estimates Tier 1 | $75.00 | — | Analyst estimates |
| All-in-One | $3,500/mo | — | Institutional |

**The free tier is sufficient for this project.** S4 uses Finnhub for company news and earnings transcripts. The TokenBucket rate limiter is already configured at 55 req/min (just under the 60/min free limit).

> **Warning**: Finnhub has historically moved previously-free endpoints to paid. The free tier is generous but not guaranteed to stay that way long-term.

#### Founders
**Spencer Sands + Tri Do** (co-founders, 2019, US). Both keep a low public profile. No academic discount.

---

## 3. News & Filing Providers

### 3.1 NewsAPI — News Articles

**Website**: https://newsapi.org

#### Getting Credentials
1. Register at https://newsapi.org/register — email + password, no credit card
2. API key available immediately

#### Plans

| Plan | Monthly | Requests | Notes |
|------|---------|---------|-------|
| **Developer (Free)** | **$0** | 100 req/day | **Dev/testing only — production use prohibited** |
| Business | $449 | 250K/month | Real-time, 5yr history, CORS |
| Advanced | $1,749 | 2M/month | — |
| Enterprise | Custom | Unlimited | — |

> **Critical**: The Developer plan explicitly prohibits production and staging use (per Terms of Service). The jump to $449/month Business is steep. Recommendation: use Finnhub and EODHD news as primary providers; keep NewsAPI as development/testing only.

#### CEO/Founder
Unknown. The company (Paris/France, UK legal) has zero public attribution — no named founders, no About page. No contact channel identified.

---

### 3.2 SEC EDGAR — SEC Filings

**Website**: https://efts.sec.gov / https://data.sec.gov

#### Getting Credentials
**Completely free. No API key, no account, no payment required.**

The only requirement is a descriptive `User-Agent` header on every HTTP request:
```
User-Agent: CompanyName contact@email.com
```

Set `SEC_EDGAR_USER_AGENT="YourName your@email.com"` in your environment.

#### Rate Limits
- **10 requests per second per IP** (hard limit)
- Add ~100ms delay between requests; cache responses locally

#### Key Endpoints

| Endpoint | Purpose |
|----------|---------|
| `data.sec.gov/submissions/{CIK}.json` | Filing history per company |
| `data.sec.gov/api/xbrl/companyfacts/{CIK}.json` | All structured financial data |
| `efts.sec.gov/hits.json` | Full-text search across filings |

No subscription, no CEO to contact. Managed by the U.S. Securities and Exchange Commission.

---

## 4. Email Providers

### 4.1 Resend — Primary Email

**Website**: https://resend.com

#### Getting Credentials
1. Sign up at https://resend.com (email or GitHub/Google OAuth)
2. Dashboard → API Keys → Create API Key
3. Add and verify a sending domain (DNS: SPF, DKIM, DMARC)
4. Can test with `onboarding@resend.dev` immediately without domain verification

#### Plans

| Plan | Monthly | Emails/Month | Daily Cap |
|------|---------|-------------|-----------|
| **Free** | **$0** | **3,000** | 100/day |
| Pro | $20 | 50,000 | None |
| Pro | $35 | 100,000 | None |
| Scale | $90–$1,150 | 100K–2.5M | None |
| Enterprise | Custom | Custom | Custom |

**Free tier is sufficient for thesis-scale usage** (3,000 emails/month, 1 domain).

#### CEO/Founder
**Zeno Rocha** — Brazilian engineer, San Francisco. Creator of Dracula Theme and Clipboard.js. Raised $18M Series A. LinkedIn: https://linkedin.com/in/zenorocha/

---

### 4.2 SendGrid — Secondary Email

**Website**: https://sendgrid.com (Twilio company)

#### Getting Credentials
1. Sign up at https://sendgrid.com or https://twilio.com
2. Settings → API Keys → Create API Key
3. Verify sender identity (single sender or full domain authentication)

#### Plans

| Plan | Price | Volume | Notes |
|------|-------|--------|-------|
| **Free Trial** | $0 | 100/day | **60-day trial only** — permanent free tier removed May 27, 2025 |
| Essentials | $19.95/mo | ~50K/mo | — |
| Pro | $89.95/mo | ~1.5M/mo | Dedicated IP |

> **The permanent SendGrid free tier was removed on May 27, 2025.** Resend (3,000 free/month, permanent) is the better choice as primary email provider for this project, which is already reflected in the current implementation.

#### Current CEO
**Khozema Shipchandler** (Twilio CEO since 2024).

---

### 4.3 Brevo — SMTP Relay (Alternative)

**Website**: https://brevo.com (formerly Sendinblue)

> Brevo is an alternative SMTP relay option to Resend/SendGrid. The codebase currently uses Resend as primary; use Brevo if you need a higher free daily cap or an SMTP relay protocol (vs REST API).

#### Getting Credentials
1. Sign up at https://app.brevo.com (email or Google/Facebook OAuth) — no credit card
2. Verify your email address
3. Dashboard → SMTP & API → SMTP Keys → Generate a New SMTP Key
4. Store the key immediately — Brevo only shows the full key once at creation time

**Important: use the SMTP key, not the API key**, when configuring SMTP relay. They are different credentials.

#### SMTP Connection Settings

| Setting | Value |
|---------|-------|
| SMTP Host | `smtp-relay.brevo.com` |
| SMTP Port | `587` (TLS/STARTTLS), `465` (SSL), or `2525` |
| SMTP User | Your Brevo account login email address |
| SMTP Password | Your SMTP key (not your Brevo password, not the API key) |

Set `ALERT_BREVO_SMTP_KEY=<your_smtp_key>` and `ALERT_BREVO_SMTP_LOGIN=<your_login_email>` in your environment.

#### Plans

| Plan | Monthly | Emails/Day | Emails/Month | Notes |
|------|---------|-----------|-------------|-------|
| **Free** | **$0** | **300** | ~9,000 | No credit card; includes full API + SMTP + webhooks |
| Starter | $9 | Unlimited | 5,000 | Remove daily cap |
| Business | $18 | Unlimited | 20,000 | Marketing automation |
| Enterprise | Custom | Unlimited | Custom | — |

**The free tier (300 emails/day) exceeds thesis-scale usage** and is sufficient as a backup to Resend. If Resend's 100/day cap is a bottleneck during testing, switch to Brevo free tier.

---

## 5. LLM Providers

### 5.1 DeepInfra — LLM Chat (Primary)

**Website**: https://deepinfra.com

#### Getting Credentials
1. Sign up at https://deepinfra.com (email/Google/GitHub)
2. Dashboard → API Keys → Create
3. Use `https://api.deepinfra.com/v1/openai` (OpenAI-compatible)
4. Small free trial credit on signup, no card required initially

#### Pricing (pay-per-token)

| Model | Input/1M tokens | Output/1M tokens |
|-------|----------------|-----------------|
| DeepSeek R1 Distill Qwen 32B | **$0.27** | **$0.27** |

**DeepStart program**: Startups can apply for up to **1 billion free tokens** at https://deepinfra.com/deepstart

#### CEO/Founder
**Nikola Borisov** — co-founder, ex-HalloApp, Northwestern University. Raised $28.6M (a16z, Felicis). LinkedIn: https://linkedin.com/in/nikola-borisov/

---

### 5.2 OpenRouter — LLM Chat (Fallback 1)

**Website**: https://openrouter.ai

#### Getting Credentials
1. Sign up at https://openrouter.ai (email/Google/GitHub) — no credit card for free tier
2. Dashboard → Keys → Create Key
3. Use `https://openrouter.ai/api/v1` as base URL (OpenAI-compatible)
4. Set `Authorization: Bearer <key>` on all requests

#### Free Tier
- Small initial credit granted to new accounts for testing (amount varies)
- 25+ free models available indefinitely (rate-limited to 50 req/day; 1,000 req/day if you have purchased ≥$10 of credits)
- Free model rate limits are **not suitable for production** use

#### Pricing (pay-per-token)

| Model | Input/1M tokens | Output/1M tokens |
|-------|----------------|-----------------|
| DeepSeek R1 Distill Qwen 32B | **$0.29** | **$0.29** |
| DeepSeek R1 (full) | $0.70 | $2.50 |

Credits purchased with a **5.5% platform fee** ($0.80 minimum). No monthly commitment. BYOK (Bring Your Own Key) program: 1M free requests/month for users who supply their own provider keys.

DeepInfra is ~7% cheaper than OpenRouter for the same 32B distill model; OpenRouter is used as fallback only.

#### CEO/Founder
**Alex Atallah** — co-founder of OpenSea (NFT marketplace). Raised $40M (a16z, Menlo). LinkedIn: https://linkedin.com/in/alexatallah/

---

### 5.3 Groq — LLM Chat (Fallback 2)

**Website**: https://console.groq.com

> Groq uses custom LPU (Language Processing Unit) hardware for ultra-low-latency inference. It is listed as a third-tier fallback in the S8 LLM chain (after DeepInfra and OpenRouter).

#### Getting Credentials
1. Sign up at https://console.groq.com (email or Google/GitHub OAuth) — no credit card required
2. Dashboard → API Keys → Create API Key
3. Use `https://api.groq.com/openai/v1` as base URL (OpenAI-compatible)
4. Set `Authorization: Bearer <key>` on all requests
5. Set `RAG_CHAT_GROQ_API_KEY=<your_key>` in your environment

#### Free Tier Rate Limits (as of April 2026)

Rate limits apply at the **organization level** (not per key). Free tier caps:

| Model | RPM | TPM | TPD |
|-------|-----|-----|-----|
| llama-3.3-70b-versatile | 30 | 12,000 | 100,000 |
| llama-3.1-8b-instant | 30 | 6,000 | 500,000 |
| qwen/qwen3-32b | 60 | 6,000 | 500,000 |
| meta-llama/llama-4-scout-17b | 30 | 30,000 | 500,000 |

> **Note**: DeepSeek R1 on Groq may not be available on the free tier or may have separate limits. Check the current model list at https://console.groq.com/settings/limits. These limits are sufficient for thesis-scale fallback usage (rare invocations only).

#### Pricing (paid tier)
Pay-per-token after free limits. Developer Tier (optional, ~$10/month) provides 10x higher rate limits. Check https://console.groq.com/docs/rate-limits for exact current numbers.

---

### 5.4 Google Gemini — Entity Descriptions

**Website**: https://aistudio.google.com

#### Getting Credentials
1. Go to https://aistudio.google.com → sign in with Google account
2. Click "Get API key" → "Create API key"
3. Select or create a Google Cloud project
4. Copy the 40-character key
5. No credit card required; billing only needed above free tier limits

> **Model ID Note**: The config references `gemini-3.1-flash-lite` but the correct API model ID is
> `gemini-3.1-flash-lite-preview` (released March 3, 2026, in preview). Update `KNOWLEDGE_GRAPH_GEMINI_API_KEY`
> usage in S7 config accordingly.

#### Pricing

| Model | Input/1M tokens | Output/1M tokens | Free Tier |
|-------|----------------|-----------------|-----------|
| Gemini 3.1 Flash-Lite Preview | $0.25 | $1.50 | Yes (rate-limited) |
| Gemini 2.5 Flash-Lite | $0.10 | $0.40 | Yes |
| Gemini 2.5 Flash | $0.30 | $2.50 | Yes |

> **Warning**: Gemini 2.0 Flash is **deprecated and shuts down June 1, 2026**. If any service depends on it, migrate to Gemini 2.5 Flash-Lite.

#### Leadership
**Sir Demis Hassabis** — CEO of Google DeepMind (Nobel laureate, co-founder of DeepMind). Manages all Gemini development.

---

## 6. Prediction Market Providers

### 6.1 Polymarket — Prediction Markets

**Website**: https://polymarket.com / **CLOB API**: https://clob.polymarket.com

> Used in PRD-0019 (S4 new adapter, S3 consumer + API). Polymarket runs on Polygon (MATIC) blockchain with a Central Limit Order Book (CLOB) for binary prediction markets.

#### Authentication Requirements

**Read-only market data: NO authentication required.**

The following endpoints are fully public and require no API key, wallet, or account:
- `GET /markets` — list all markets
- `GET /markets/{condition_id}` — single market details
- `GET /book?token_id=<id>` — order book (bids/asks)
- `GET /price?token_id=<id>&side=buy&size=10` — current price
- `GET /prices-history?market=<id>&interval=1h` — price history
- Gamma API: `https://gamma-api.polymarket.com/markets` — richer market metadata

**Trading/authenticated endpoints** (not used by this project):
- Placing orders, canceling orders, checking balances — require L1 + L2 authentication
- L1: Ethereum wallet (private key, EIP-712 signature)
- L2: API credentials (apiKey + secret + passphrase) generated from L1 via `createOrDeriveApiKey()`
- Signing: HMAC-SHA256 per request

#### Getting Read-Only Access
No signup, no account, no API key needed. Simply make HTTP GET requests to the CLOB API:

```
GET https://clob.polymarket.com/markets
GET https://gamma-api.polymarket.com/markets?active=true&limit=100
```

Set a descriptive `User-Agent` header as a courtesy (e.g., `worldview-content-ingestion/1.0`).

#### Rate Limits
No documented public rate limit for read endpoints. Apply standard courtesy throttling (~2–5 req/sec).

#### SDK
Official Python client: `py-clob-client` (https://github.com/Polymarket/py-clob-client). For read-only use, direct `httpx` calls are simpler.

---

## 7. Brokerage Integration Providers

### 7.1 SnapTrade — Brokerage Sync

**Website**: https://snaptrade.com / **Docs**: https://docs.snaptrade.com

> Used in PRD-0022 (S1 BrokerageConnection entity, BrokerageTransactionSyncWorker, read-only brokerage sync). SnapTrade is a brokerage aggregation API (similar to Plaid for investments) that connects to 50+ North American brokerages.

#### Credential Structure

SnapTrade uses two layers of credentials:

| Credential | What It Is | Where It Lives |
|------------|------------|----------------|
| `clientId` | Your application identifier | `SNAPTRADE_CLIENT_ID` env var |
| `consumerKey` | Your application secret (HMAC signing key) | `SNAPTRADE_CONSUMER_KEY` env var |
| `userId` | Per end-user identifier (you generate) | stored in DB per user |
| `userSecret` | Per end-user secret (SnapTrade generates) | stored in DB per user |

**The `consumerKey` is sensitive** — treat like a private key. All API requests are signed using HMAC-SHA256 with the consumerKey.

#### Getting Credentials
1. Register at https://app.snaptrade.com/dashboard
2. **Verify your email** — you cannot create API keys until your email is verified
3. Dashboard → Settings → API Keys → Generate API Key
4. Copy both `clientId` and `consumerKey` immediately; the `consumerKey` may not be fully shown again
5. Set env vars: `SNAPTRADE_CLIENT_ID=<clientId>` and `SNAPTRADE_CONSUMER_KEY=<consumerKey>`

#### Plans

| Plan | Monthly | Connected Users | Rate Limit | Notes |
|------|---------|----------------|-----------|-------|
| **Free** | **$0** | **Up to 5 brokerage connections** | 250 req/min | All features; sufficient for thesis (PRD-0022 caps at 5 users) |
| Pay As You Go | $2/connected user/month | Unlimited | 250 req/min | No commitment |
| Custom | Contact sales | Unlimited | Higher | Volume discounts, dedicated support |

> **The free tier (5 connections) is exactly what PRD-0022 targets.** The $0 Free plan includes real-time data, read + trading, and full API access.

#### Sandbox / Testing
No separate sandbox environment. For testing without a live brokerage account:
1. Create an Alpaca Paper Trading account (free at https://alpaca.markets)
2. In the SnapTrade Connection Portal, select "Alpaca Paper" as the institution
3. This provides paper/simulated brokerage data without real money

#### SDK
Official Python SDK: `snaptrade-python-sdk` on PyPI. Initialize with `clientId` and `consumerKey`:
```python
from snaptrade_client import SnapTrade
client = SnapTrade(client_id=SNAPTRADE_CLIENT_ID, consumer_key=SNAPTRADE_CONSUMER_KEY)
```

---

## 8. Cost Estimate Summary

Minimum monthly cost to run in production (cheapest viable plan per provider):

| Provider | Cheapest Production Plan | Monthly Cost | Notes |
|----------|--------------------------|-------------|-------|
| **EODHD** | Fundamentals Feed | **€59.99** | Covers fundamentals, macro, insider. Add All-In-One (€99.99) for news too |
| EODHD (academic) | Fundamentals Feed w/ 50% discount | **€29.99** | Apply at anna@eodhistoricaldata.com |
| Alpha Vantage | Free / Plan 1 | $0–$49.99 | Free tier (25 req/day) OK for dev |
| Polygon.io | Free / Starter | $0–$29 | Stub in code; free EOD is fine |
| **Finnhub** | **Free** | **$0** | 60 req/min; sufficient for S4 |
| **NewsAPI** | Developer (dev only) | **$0** | Dev only; cannot use in production |
| **SEC EDGAR** | Free forever | **$0** | Government API; no account needed |
| **Resend** | Free | **$0** | 3,000/month; sufficient for thesis |
| SendGrid | Free trial (60 days) | $0 → $19.95 | Trial only; use Resend as primary |
| **Brevo** | Free | **$0** | 300 emails/day (~9K/month); SMTP relay |
| **DeepInfra** | Pay-per-use | **~$1–5/mo** | At thesis usage levels ($0.27/1M tokens) |
| OpenRouter | Pay-per-use | **~$1–5/mo** | Fallback 1; similar cost to DeepInfra |
| **Groq** | Free tier | **$0** | Fallback 2; free RPM/TPD limits fine for fallback |
| **Google Gemini** | Free tier | **$0** | Rate-limited free tier fine for thesis |
| **Polymarket** | Free (no account) | **$0** | Public read API; no credentials needed |
| **SnapTrade** | Free (≤5 connections) | **$0** | Free tier sufficient per PRD-0022 cap |

**Estimated minimum monthly cost:**
- Without academic discount: **~€65–75/month** (mainly EODHD)
- With EODHD 50% academic discount: **~€35–45/month** (for 12 months)
- After academic period: **~€65–75/month**
- All other providers: **$0** at thesis scale

---

## 9. EODHD — Deep Dive Contact Strategy

This section analyzes the strategic decision of how to approach Denis Alaev (CEO) and Anna Vakhova
(Partnership Manager) at EODHD, and what you should aim to get from that relationship beyond just a free key.

---

### 9.1 The Two-Track Decision: Anna vs Denis

There are two distinct goals here that require different channels:

| Goal | Best Channel | Why |
|------|-------------|-----|
| Get a free or discounted API key ASAP | **Email Anna** | She is the designated academic/university contact and can approve discounts directly |
| Build a relationship, get mentorship, explore collaboration | **LinkedIn → Denis** | He's the founder; the conversation you want to have is founder-to-founder, not transactional |

**Recommendation: pursue both tracks in parallel**, starting with Anna on the same day you connect with Denis on LinkedIn. They serve different purposes and there is no conflict in doing both.

---

### 9.2 Why Anna Is the Right First Step for the Discount

Anna Vakhova handles university partnerships. Her email (`anna@eodhistoricaldata.com`) is publicly listed on EODHD's university page for exactly this kind of request. She can:

- Approve the 50% academic discount immediately
- Potentially approve a temporary free key if you explain the thesis timeline
- Escalate to Denis if your project is interesting enough

This is the **fastest path to getting a working API key**. Send this email first.

**Anna email template:**

```
Subject: Final Thesis Project — Academic Access Request

Hi Anna,

I'm a final-year university student working on my thesis project: a market intelligence
platform that aggregates financial data, runs NLP pipelines, and surfaces insights via
RAG-based chat. EODHD is central to the project — I'm using the fundamentals feed,
macro indicators, and insider transactions APIs.

I came across the university partnerships page and wanted to inquire about academic
access or the 50% student discount. The project runs until [month/year], and I'm
working on it independently as a thesis (though I'm excited about its potential beyond
that).

I'd be happy to share more details about the project if useful. Would the academic
discount apply to my situation, or is there a more appropriate arrangement for
individual thesis students?

Thank you,
[Your name]
[University + department]
[LinkedIn or GitHub profile]
```

Keep it short. No need to oversell. The academic discount program exists precisely for this.

---

### 9.3 Why Denis Is Worth Contacting — and What You Actually Want

Denis Alaev is not a typical "enterprise CEO" you need a warm intro to reach. He's a bootstrapped founder who:

- Started EODHD on a €10/month server and grew it to $3.5M ARR with ~15 people
- Has spoken publicly about the journey (The New Stack, Starter Story interviews)
- Has a professional but approachable LinkedIn presence
- Runs a data infrastructure business — he understands technical builders

Contacting him is **reasonable and likely to get a response**, especially if you lead with something genuine.

**What you can realistically get from Denis:**

| What | Realism | How to frame it |
|------|---------|----------------|
| Extended/free API key | High | You're already getting this via Anna; Denis could greenlight a longer free period |
| 30-minute call / video chat | Medium-High | Bootstrapped founders often enjoy talking to builders using their product |
| Advice on building a data startup | High | He built exactly this and loves to talk about it |
| Insight into the financial data industry | High | He has 10+ years of experience in this niche |
| Mentorship or ongoing relationship | Medium | Depends on chemistry and your follow-through |
| Investment interest / involvement | Low (for now) | Too early; don't mention this in the first message |

---

### 9.4 LinkedIn Message to Denis — Strategy

**When to send**: After you've emailed Anna (so your key situation is handled separately), and after you've done some reading on Denis's background (The New Stack article, Starter Story interview).

**What NOT to do**:
- Don't lead with "I want you to get involved in my startup" — too forward for a cold message
- Don't ask for a free API key in the LinkedIn message — that's Anna's territory
- Don't send a wall of text — founders get these; they ignore them
- Don't pitch the startup angle in the first message

**What to do**:
- Reference something specific from his public writing (e.g., the bootstrapping story)
- Be clear you're a student building something real, not just doing a course project
- Ask for a short call — "20 minutes, any time that works for you"
- Express genuine curiosity about his experience, not just what you can get

**LinkedIn message template:**

```
Hi Denis,

I read your interview with The New Stack about bootstrapping EODHD from a $10 server —
genuinely impressive, and the focus on data quality over feature bloat resonated with
how I'm approaching my own project.

I'm a final-year student building a market intelligence platform for my thesis —
10 microservices, Kafka pipelines, NLP/RAG layer, fundamentals + macro + insider
data from EODHD. The architecture is production-grade (hexagonal, Avro schemas,
event sourcing) even though it's academic right now.

If you have 20 minutes sometime, I'd love to hear how you navigated the early decisions
around data sourcing and pricing strategy — the kinds of things that aren't in blog posts.
No pitch, just curiosity.

[Your name]
```

**Why this works**:
1. References specific content he published — shows you did homework, not a mass blast
2. Describes the project technically — establishes credibility without overselling
3. The ask ("20 minutes") is small and specific
4. "No pitch, just curiosity" removes the commercial pressure that makes founders ignore messages

---

### 9.5 The Call — What to Talk About

If Denis agrees to a call, here's what's worth covering:

**Questions to ask him:**

1. *"When you started, how did you think about what data to include vs what to leave out for the first version? I'm wrestling with scope decisions now."* — Opens a conversation about product strategy from his experience.

2. *"How did you handle the reliability and freshness guarantees when EODHD data was early-stage? Did you have SLAs?"* — Technical question that shows you understand the hard problems.

3. *"The financial data space feels crowded from the outside — Bloomberg Terminal, Refinitiv, etc. How did you position EODHD against the incumbents?"* — Market positioning question; he'll have strong opinions.

4. *"What do you wish you'd known about pricing data to customers before you launched?"* — This is where you listen carefully. Relevant if you go the startup route.

5. *"Is there anything about the product you'd build differently knowing what you know now?"* — Founders love this question.

**What to share about your project**:
- Brief overview (don't demo-dump)
- The specific ways you're using EODHD (shows you're a real power user)
- What makes the platform different from a data aggregator (the RAG + NLP intelligence layer)

**What NOT to bring up on the first call**:
- Asking him to invest or get involved formally
- Asking for free API access (Anna is handling that)
- Anything about competitors or EODHD pricing being too high

---

### 9.6 Long-Term: Can You Get Denis Involved?

**The honest assessment**: Asking a CEO to "get involved" in a thesis project is a very high ask for a cold relationship. However, the path to getting there is realistic if you play it over time:

```
Email Anna → get discount/free key
  ↓
LinkedIn message to Denis → get a call
  ↓
Have a genuine conversation; follow up with what you learned
  ↓
Share a progress update 1-2 months later ("thought you'd find this interesting")
  ↓
If the project develops past thesis → re-engage with concrete ask
```

The key insight is: **Denis is more likely to get involved if he's watched you build something over several months** than if you ask him in the first conversation. Make the relationship real before making a big ask.

Also worth noting: Denis's company is in the data infrastructure space. If worldview ever becomes a startup, a partnership with EODHD (licensing, white-labeling, integration showcase) is more realistic than Denis becoming a co-founder or investor. Keep that in mind as the relationship develops.

---

### 9.7 Summary: Action Plan

| Action | When | Channel | Expected Outcome |
|--------|------|---------|-----------------|
| Email Anna for academic discount | Today | anna@eodhistoricaldata.com | 50% discount or free key for thesis period |
| Register for demo key | Today | eodhd.com/register | Unblocked immediately for dev |
| Connect with Denis on LinkedIn | This week | LinkedIn | Opens the door for a call |
| Send Denis a short LinkedIn message | After connection accepted | LinkedIn | Request 20-min call |
| Have the call | Within 2-3 weeks | Video call | Advice, insight, relationship |
| Follow up with project update | 4-6 weeks later | Email / LinkedIn | Keep the relationship warm |
| Re-engage about startup plans | When thesis is done / MVP ready | Direct email | Explore formal collaboration |

---

*This document is for internal reference only. Do not commit API keys or credentials to the repository.*
