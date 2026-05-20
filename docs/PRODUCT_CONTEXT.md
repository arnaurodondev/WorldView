# Product Context — What & Why

> **Purpose**: Stable product-level context for `/prd` sessions and new feature discussions.
> Separates *what we're building and for whom* from *how it's built* (see `MASTER_PLAN.md` for architecture).
> Read this before starting any `/prd` or product-level discussion.

---

## Vision

Worldview is a **market intelligence platform** that fuses structured financial data (OHLCV, fundamentals, corporate actions) with unstructured intelligence (news, filings, press releases) into a unified knowledge layer — queryable by APIs, visualizable in charts, and conversable through an LLM-powered chatbot with grounded, citation-backed answers.

## Target Users

| Segment | Description | Primary Journeys |
|---------|-------------|-----------------|
| **Retail Investors** | Individual investors tracking portfolios and researching companies | J1 (Charts), J2 (Fundamentals), J5 (Chatbot) |
| **Research Analysts** | Professionals needing comprehensive company intelligence | J2 (Fundamentals), J3 (News Feed), J4 (Signals), J5 (Chatbot) |
| **Quantitative Traders** | Algorithmic traders needing programmatic data access | J1 (Charts), API access |
| **Thesis Evaluators** | Academic reviewers assessing system design and implementation | All journeys |

## Core User Journeys

| # | Journey | What It Does | Success Metric |
|---|---------|-------------|----------------|
| J1 | **Interactive Charts** | TradingView-style OHLCV candlestick charts with indicators | Sub-200ms p99 latency |
| J2 | **Fundamentals Explorer** | Income statement, balance sheet, cash flow, valuation ratios, analyst consensus, dividends (18 sections) | Complete data for S&P 500 |
| J3 | **News Feed + Entity Linking** | Timeline of articles linked to companies/tickers via NLP entity extraction with sentiment and topic tags | Articles linked within 30s of ingestion |
| J4 | **Signals / Events View** | Unified event stream: structured + unstructured events, filterable by entity, sector, type, severity | Cross-source event correlation |
| J5 | **LLM Chatbot (RAG + KG)** | Hybrid retrieval (vector search + knowledge graph + SQL), grounded cited answers via streaming SSE | < 5s first token, citations on every claim |

## Non-Functional Goals

| Attribute | Target |
|-----------|--------|
| Reliability | 99.5% uptime read APIs; at-least-once Kafka with idempotent consumers |
| Latency | < 200ms p95 charts/fundamentals; < 500ms news; < 5s chatbot first token |
| Cost | $0 infra (local Docker); < $50/month cloud data APIs |
| Privacy | No PII beyond email; local Ollama as default LLM; GDPR-aware |
| Multi-tenancy | Tenant-isolated data at DB query level; no cross-tenant leakage |

## Data Sources

| Source | Type | Provider | Content |
|--------|------|----------|---------|
| EODHD | Structured + Unstructured | EODHD API | OHLCV, fundamentals, news |
| SEC EDGAR | Unstructured | SEC EDGAR EFTS | Company filings (10-K, 10-Q, 8-K) |
| Finnhub | Unstructured | Finnhub API | News articles, earnings transcripts |
| NewsAPI | Unstructured | NewsAPI.org | General financial news |

## Product Constraints

1. **Thesis scope** — Must demonstrate microservice architecture, event-driven design, and NLP/ML integration
2. **Budget** — $0 infrastructure (local Docker), minimal API costs
3. **Single developer** — All services built and maintained by one person
4. **Local-first** — Ollama for LLM, MinIO for object storage, Postgres for DB
5. **Academic timeline** — Must be demonstrably functional for thesis defense

## Key Product Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| LLM provider | DeepInfra (primary) + Ollama (GLiNER NER fallback) | DeepInfra for LLM/embeddings/extraction; Ollama for local NER only |
| Data granularity | Daily OHLCV (not intraday) | Sufficient for thesis, lower API costs |
| Multi-tenancy | Logical (shared DB, tenant_id filter) | Simpler than physical isolation for thesis scope |
| Frontend framework | Next.js 15 App Router + shadcn/ui + TanStack Query | SSR, dark theme, finance-grade UI, type-safe |
| Chat approach | RAG + Knowledge Graph hybrid | Demonstrates both retrieval paradigms |

## What This Platform Is NOT

- Not a real-time trading platform (no sub-second data)
- Not a production SaaS (thesis-grade reliability, not enterprise)
- Not a data vendor (consumes external APIs, doesn't resell data)
- Not a social platform (no user-generated content beyond chat queries)
