# Brief Vector Descriptions Evaluation
**Date:** 2026-06-14
**Scope:** Should the three entity vector descriptions be fed into the morning portfolio brief and/or instrument brief?

---

## 1. Data Model: Exact Table & Column Names

All three descriptions live in `intelligence_db.entity_embedding_state` (PK: `entity_id, view_type`):

| `view_type` | Conceptual Role | Key Column | Freshness (Worker) |
|---|---|---|---|
| `definition` | What the entity IS — business description from EODHD | `source_text` | 90-day + event-triggered (Worker 13D-1 `DefinitionRefreshWorker`) |
| `narrative` | Current thematic context — competitors, AI exposure, strategic positioning (LLM-generated) | `source_text` | Weekly Sunday 03:00 UTC (Worker 13D-3 `NarrativeGenerationWorker`) |
| `fundamentals_ohlcv` | Financial state — long business description + revenue/margins/P/E in structured prose | `source_text` | 3h (Worker 13F `EmbeddingRefreshWorker` refreshes embeddings; content generated on each fundamentals ingest) |

The narrative text also lives in `entity_narrative_versions.narrative_text` (current version: `is_current = true`), and is accessible via `GET /api/v1/entities/{id}/intelligence` → `current_narrative.narrative_text`.

The three `source_text` fields are NOT currently exposed via any S7 API endpoint (only the narrative is, via the intelligence endpoint). The `fundamentals_ohlcv` and `definition` source_texts are KG-internal.

---

## 2. Content Quality & Freshness Snapshot

### Population Rates (financial_instrument entities only)
| `view_type` | Total rows | Populated (>50 chars) | Empty/stub |
|---|---|---|---|
| `definition` | 4752 | 612 (12.9%) | 4140 |
| `fundamentals_ohlcv` | 4752 | 615 (12.9%) | 4137 |
| `narrative` | 4752 | 2840 (59.8%) | 1912 |

**Key insight**: Only the top-tier seeded entities (the 10 seed canonicals + enriched entities) have all three. Narrative is by far the best-populated (60%), followed by definition/fundamentals (both ~13%).

### Sample Texts for Demo Holdings (GOOGL/AAPL/JPM/TSLA)

**`definition` (~296-327 chars, last refreshed 2026-05-25)**
Dry 1-3 sentence EODHD business blurb. Example (AAPL): "Apple Inc. designs, manufactures, and markets smartphones, personal computers, tablets, wearables, and accessories worldwide."

**`narrative` (~447-637 chars, last refreshed 2026-05-21)**
LLM-generated thematic context. Quality is MODERATE. Examples:
- AAPL: mentions MSFT competition and AI exposure. Useful framing.
- GOOGL: mentions AI in advertising and MSFT competition. Generic but grounded.
- JPM: mentions AI with 60% confidence. Reasonably specific.
- TSLA: mentions EV focus and AI integration. Thin (70 words).
- Model: `meta-llama/Meta-Llama-3.1-8B-Instruct` — smaller/cheaper model, narratives show it.
- **CRITICAL STALENESS**: All four generated 2026-05-21 — 24 days old. Weekly Sunday cadence means they lag recent news materially (e.g., no mention of Q2 earnings, tariff developments, AI-product launches since late May).

**`fundamentals_ohlcv` (~1496-2072 chars, last refreshed 2026-06-12 to 2026-06-14)**
Rich structured prose: full EODHD business description + 4 financial metrics (Revenue, Gross Margin, Net Margin, P/E). Example (AAPL): Revenue $451.44B, Gross Margin 49.3%, Net Margin 26.6%, P/E 35.2. This is the freshest and most factually dense of the three.

### Freshness Summary
- `definition`: ~20 days stale (last 2026-05-25) — fine for identity facts, bad for any dynamic info
- `narrative`: ~24 days stale (all 2026-05-21) — worse than a week-old newspaper; could inject noise into "why" reasoning for current events
- `fundamentals_ohlcv`: ~2-48 hours fresh (2026-06-12 to 2026-06-14) — the only genuinely fresh description

---

## 3. What Each Brief Already Includes Today

### Morning Portfolio Brief (context blocks in prompt v4.7)
| Context Block | Source | What it contains |
|---|---|---|
| `portfolio_context` | S1 | Holdings + overnight P&L + sector mix + per-holding `related:[cN]` + `sector:` attribution lines |
| `news_context` | S6 | Up to 12 news articles, deduped, relevance-ranked, with per-holding fan-out (4 articles × up to 15 holdings) |
| `alerts_context` | S5 | Active alerts (≤8, severity≥medium) |
| `market_overview` | S3 | SPY/QQQ/VIX tape + per-holding quotes |
| `events_context` | S7 | Earnings/analyst/corporate events (entity-scoped) + macro/economic events (unscoped, Fed/CPI) |

**NOT currently included**: entity descriptions, entity narratives, fundamentals state.

### Instrument Brief (context blocks in prompt v4.0)
| Context Block | Source | What it contains |
|---|---|---|
| `entity_context` | S7 egocentric graph | Entity name + type + ticker (3 lines only — very sparse) |
| `fundamentals_context` | S3 | Market cap, Revenue TTM, margins, P/E, EPS, consensus target — 7-10 structured metrics |
| `news_context` | S6 | Up to 30 entity-specific articles |
| `events_context` | S7 | Events for this entity (30-day window) |
| `relationships_context` | S7 egocentric graph | Top 10 KG relations as markdown table |
| ANN chunks | S6 | Up to 12 semantic chunks from SEC filings/earnings transcripts |

**NOT currently included**: definition text, narrative text, fundamentals_ohlcv prose.

---

## 4. Reachability from rag-chat

### What's already accessible
- **Narrative** via `S7IntelligenceClient.get_entity_intelligence()` → `GET /api/v1/entities/{id}/intelligence` → `current_narrative.narrative_text`. The client exists and works. The tool `get_entity_intelligence` in the chat pipeline already calls this.
- **Definition** (`canonical_entities.description`): accessible via `GET /api/v1/entities/{id}` (returned as `description` field in `EntityPublic`). The S7 client already calls this for `gather_instrument_context` (via `get_egocentric_graph` which returns the center node).
- **`fundamentals_ohlcv` source_text**: NOT exposed via any existing S7 or S9 endpoint. Would require a new endpoint.

### What's missing / new plumbing required
| Description | Current state | Plumbing needed |
|---|---|---|
| Entity definition | Accessible via `EntityPublic.description` | Zero — S7 already returns this |
| Narrative | Accessible via intelligence endpoint | Zero — already fetched by tool registry, new brief wiring needed |
| `fundamentals_ohlcv` prose | NOT exposed | New S7 endpoint: `GET /api/v1/entities/{id}/embedding-descriptions` → returns all 3 `source_text` values; OR add to existing intelligence endpoint |

---

## 5. Token Budget Analysis

### Morning Brief (portfolio brief)
- Current context: ~800-1500 tokens (12 news × ~50 tokens + portfolio + tape + events)
- Adding descriptions: for a 10-holding portfolio, 3 descriptions × 10 holdings = 30 blobs
  - definition: 30 × ~60 tokens = 1800 tokens
  - narrative: 30 × ~130 tokens = 3900 tokens
  - fundamentals_ohlcv: 30 × ~350 tokens = 10500 tokens
- **Token verdict**: feeding all 3 per-holding is impractical (15K+ new tokens for 10 positions). Even narrative-only is 3.9K additional tokens — costly and likely noise given 24-day staleness.

### Instrument Brief (single entity)
- Current context: ~1500-2500 tokens (30 news articles + fundamentals highlights + relationships + ANN chunks)
- Adding descriptions for ONE entity:
  - definition: ~60 tokens — trivial
  - narrative: ~130 tokens — trivial
  - fundamentals_ohlcv prose: ~350 tokens — manageable
- **Token verdict**: all three descriptions for a single entity total ~540 tokens on top of a ~2000-token context. Budget-safe.

---

## 6. Recommendation

### Instrument Brief — **P1 USEFUL** (definition + narrative; fundamentals_ohlcv conditional)

**Definition**: Feed it. The current `entity_context` block for the instrument brief is 3 lines (name/type/ticker). Adding the definition ~60-token blurb would give the LLM the entity's actual business identity — needed for "Entity Overview" section accuracy. It's already in the graph response (`EntityPublic.description`); just pass it through `format_entity_context()`. **Zero integration cost.** The definition is stable (90-day cadence) and appropriate for a slow-moving "what is this company" answer.

**Narrative**: Feed it. The instrument brief has a "Recent Developments" section that currently leans on news articles only. The narrative (~130 tokens) provides thematic framing (AI exposure, competitive positioning) that is genuinely NOT in the structured fundamentals or news articles — especially for explaining "why" something is moving in a sector/theme context. Integration cost: the S7IntelligenceClient already fetches it. Need to add it to `gather_instrument_context()` (one extra S7 call that could be parallelized with existing calls) and add a new `entity_narrative` slot in the prompt.
- **Caveat**: narratives are 24 days stale for the demo set. The brief should note this or the prompt should instruct the LLM to treat it as "background context" not current news.

**`fundamentals_ohlcv` prose**: SKIP for now. The instrument brief already has `format_fundamentals()` pulling the exact same financial metrics from EODHD in a cleaner structured format. The prose version is redundant with the existing structured metrics block and would add ~350 tokens of overlap. Only re-evaluate if EODHD fundamentals endpoint ever goes stale.

### Morning Portfolio Brief — **P2 / NOT RECOMMENDED (for descriptions 1 & 2); P2 CONDITIONAL (for narrative)**

**Definition**: NOT recommended for the portfolio brief. The morning brief doesn't need to describe what Apple IS — the portfolio holder already knows their holdings. Token cost vs. signal value is unfavorable at scale.

**`fundamentals_ohlcv` prose**: NOT recommended. The morning brief doesn't render fundamental details per holding; it renders P&L moves and news attribution. This description would be noise.

**Narrative (selective / top-N only)**: Conditionally useful — P2. If the morning brief were extended to include a one-line "entity thematic context" per holding when no direct news is found (rung 4 of the attribution ladder: currently "idiosyncratic — no identifiable driver"), the narrative could upgrade that to "thematic: AI-infrastructure exposure (no direct news today)". However:
1. Staleness (24 days) risks injecting outdated context as if current
2. Token cost for 10+ holdings is 1300+ tokens just for narratives
3. The current attribution ladder (entity news → sector → macro → idiosyncratic) already covers the case when there's no news
- **Verdict**: defer. Implement only after addressing narrative freshness (daily rather than weekly cadence) and only for the top 5 holdings by portfolio weight.

---

## Summary

| Brief | Description | Verdict | Priority | Integration Cost |
|---|---|---|---|---|
| Instrument | `definition` (entity_description) | FEED IT | P1 | Zero — already in graph response; add 1 line to formatter |
| Instrument | `narrative` (EES `narrative` source_text) | FEED IT with staleness caveat | P1 | Low — 1 extra S7 call (parallelizable); new prompt slot |
| Instrument | `fundamentals_ohlcv` prose | SKIP — redundant with structured metrics | N/A | Medium (new S7 endpoint needed anyway) |
| Morning | `definition` | SKIP — not useful at portfolio scale | N/A | — |
| Morning | `narrative` | CONDITIONAL — only after daily refresh cadence | P2 | Medium — token budget risk, staleness risk |
| Morning | `fundamentals_ohlcv` | SKIP | N/A | — |
