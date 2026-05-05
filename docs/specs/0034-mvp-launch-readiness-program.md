# PRD-0034 — MVP Launch Readiness Program

> **Document type**: Launch program meta-PRD (multi-workstream charter, not a single-feature PRD).
> **Date**: 2026-05-02
> **Status**: draft
> **Author**: Strategic investigation 2026-05-02 (synthesis of QA reports 2026-04-25..2026-05-01, PRD-0031 enhancement investigations, PLAN-0058 retrieval uplift, PLAN-0059 institutional remediation, ALERT_ENHANCEMENT_STRATEGY.md)
> **Supersedes**: nothing. **Consumes**: PLAN-0058 (retrieval+KG), PLAN-0059 (frontend institutional), partial ALERT_ENHANCEMENT_STRATEGY.md.
> **Auto-mode notice**: Phase-1 interactive Q&A was skipped. Open assumptions are listed in §14 with explicit BLOCKING / DEFERRED classification. **§14 BLOCKING items must be answered by the user before any /plan or /implement work begins.**

---

## 1. Problem Statement

The Worldview platform has reached **architectural completeness** (10 services, 6 shared libs, 5,200+ backend tests passing, 1,196 frontend tests passing, 61 healthy containers) but is **not market-ready as an MVP**. Three structural problems block credible launch in the market intelligence sector:

1. **The screen does not visibly move.** No quote WebSocket; every cell polls every 15s. Anyone trained on Bloomberg/TradingView reads "frozen / broken" within 90 seconds.
2. **The Knowledge Graph — the only real moat — is empty.** 0 rows in `relation_evidence`, 0 in `relation_summaries`, 0 nodes/edges in AGE. 7 of 11 GLiNER classes have zero canonical seeds. F-CRIT-07 silently drops ~100% of relations because of a prompt↔lookup contract mismatch (`_build_raw_relations` rejects unresolved endpoints).
3. **The instrument universe is ~80 symbols.** A retail user types in their stock, gets nothing, leaves.

Beyond these gates, multi-tenant isolation (Postgres RLS) is missing, there is no paid-tier mechanism (no Stripe, no rate limiting per tier), and the frontend gateway client (`lib/gateway.ts` 2,657 LOC, `types/api.ts` 1,401 LOC) is hand-typed with no codegen — drift is active.

This PRD defines the **6-week launch sprint** that converts the platform from "thesis-grade demo" to "credible MVP in market intelligence sector."

## 2. Target Users (Lane Decision: L1 — AI-Native Research Terminal)

The strategic investigation identified three viable lanes:

| Lane | Compete with | Key strength | Verdict |
|------|--------------|-------------|---------|
| **L1 — AI-native research terminal** | FinChat.io, AlphaSense, Sentieo, Perplexity Finance | RAG + KG + multi-source citations + sentiment-aware news | **CHOSEN** |
| L2 — Retail prosumer dashboard | Finviz, TradingView, ZeroTerminal | Charts + screener + watchlists | Rejected — needs real-time tick infra |
| L3 — News/intelligence feed | Bloomberg News, Benzinga | News pipeline + entity linking | Rejected — narrow; charts/portfolio go to waste |

**L1 chosen because**: (a) the KG and RAG are the platform's only real moat and only matter under L1; (b) the market has proven willingness to pay (FinChat.io); (c) "thesis-grade speed" is forgivable when the value prop is reasoning depth, not tick latency; (d) it leverages existing investment in S6/S7/S8 instead of obsoleting it.

**Primary user persona for MVP**:
- **Research analyst / sophisticated retail prosumer** ("Sam the Analyst")
- Subscribes to ≤2 paid finance tools today (e.g. Seeking Alpha + a chart platform)
- Researches ≤20 tickers actively, watches ≤100
- Reads news + filings + transcripts; pain is *finding the relevant claim across sources*
- Willingness to pay: $15–30/month if the tool saves them ≥1 hour/week

**Explicitly out of MVP target**:
- Day traders requiring tick-level data (L2 territory)
- Institutional hedge funds (RLS hardening + SOC2 not in scope)
- Casual retail users with no research workflow (free tier captures these but they are not the paid persona)

## 3. Functional Requirements

Organised by tier. Tier numbers map directly to launch sprint priority.

### Tier 0 — Ship-Blockers

| FR-T0-1 | Knowledge Graph entity coverage and relation persistence |
|---|---|
| | Seed all 11 GLiNER entity classes (currently 4 missing seeds: person, location, commodity, regulatory_body, macroeconomic_indicator, index, government_body). Fix F-CRIT-07 (`_build_raw_relations` accepts unresolved endpoints with a `pending` resolution row). Acceptance: `relation_evidence` ≥10K rows, AGE ≥1K nodes / ≥5K edges, ≥80% of articles produce ≥1 persisted relation. |

| FR-T0-2 | Universe expansion to 600+ instruments |
|---|---|
| | Expand from ~80 to S&P 500 + sector ETFs (~20) + top-30 crypto + top-30 macro indicators within EODHD T3 polling tier quota. Acceptance: search for any S&P 500 ticker returns the instrument page populated with ≥1y OHLCV + latest fundamentals. |

| FR-T0-3 | Visible-feature inventory and "Bloomberg theater" cull |
|---|---|
| | Hide / remove from production routes any feature that is half-shipped or known-broken: drawing tools, multi-currency, options chain, market depth panel, hotkey palette, prediction-market panel if 401-ing, anything labeled "coming soon." Replace with explicit "Pro tier — Q3" empty states. Acceptance: clickthrough audit reports zero broken features visible to a free-tier user. |

### Tier 1 — Differentiators (Reason to Choose Worldview)

| FR-T1-1 | Structured AI Brief with deterministic schema and 100% citation rate |
|---|---|
| | Brief endpoint returns `{headline, lead, sections[{title, bullets[{text, citations[{document_id, snippet, url}]}]}], confidence, generated_at}`. The `lead` is a **1-sentence-to-1-paragraph prose synthesis** (1–4 sentences, ≤600 chars) with inline `[cN]` citation markers that resolve against the top-level `citations[]` list. The `lead` is the first thing the analyst reads and may stand alone on compact surfaces (instrument subheader, chat inline, dashboard collapsed) where rendering only `{headline, lead}` satisfies the contract. Frontend renders deterministically; every bullet AND every `[cN]` marker in `lead` is click-through to source. **Revised 2026-05-03 (resolves OQ-5)**: `lead` was added because the persona §2 ("Sam the Analyst") needs prose-first synthesis (FinChat/AlphaSense/Sentieo pattern), not a pure section/bullet wall. The 1-paragraph upper bound (vs 1-sentence) accommodates large portfolios or active news days where one sentence is insufficient. Acceptance: (a) 100% of bullets have ≥1 citation; (b) 100% of `[cN]` markers in `lead` resolve to a citation in `citations[]`; (c) 0% of citations 404; (d) rendering is **consistent** across dashboard, instrument page, and chat (compact variant = headline + lead; full variant = headline + lead + sections; inline variant = lead with optional headline). "Identical layout" is explicitly relaxed to "consistent payload + variant-appropriate layout" — see W4 plan §3 for variant matrix. |

| FR-T1-2 | Hybrid retrieval (BM25 + ANN + RRF) with golden-eval CI gate |
|---|---|
| | Existing PLAN-0058 Wave C+D. Postgres `tsvector` GIN index for lexical, existing pgvector for ANN, Reciprocal Rank Fusion for combination. 50-query golden eval set with NDCG@10 / MRR / P@5 metrics; CI gate fails if NDCG@10 regresses ≥3%. Acceptance: NDCG@10 ≥0.05 absolute lift over ANN-only baseline; CI gate enforced on every PR touching `services/rag-chat/` or `libs/ml-clients/`. |

| FR-T1-3 | Full-text search across articles + filings + transcripts with entity facets |
|---|---|
| | New search route `/search?q=...&entity=...&scope=...&source_type=...&date_from=...&date_preset=...`. Backed by Postgres `tsvector` over articles + EDGAR filings (transcripts deferred — see PLAN-0064 §0 Known Limitations). Entity facet sidebar populated from KG resolution and **pinned to the authenticated user's watchlist + portfolio at the top** (Sam-persona §2: ≤20 active tickers — default scope is `watchlist` when non-empty). **Ranking** blends `ts_rank_cd × source_weight × recency_decay` so EDGAR filings outrank tied-relevance news (revised 2026-05-03 per Sam-alignment audit; previously pure `ts_rank_cd` surfaced low-authority blogs). **Saved searches** with "what's new since" unread badges (PLAN-0064 T-W6-4-04) — required for the Sam-persona retention surface; free tier 5, Pro tier 50. **Snippet popover** (PLAN-0064 T-W6-4-05) lets Sam verify a hit without leaving the results page (AlphaSense/Sentieo pattern). Acceptance: search latency p95 ≤500ms (including watchlist-scope branch with 100 entity_ids); entity facet returns ≥1 hit for any S&P 500 ticker; result list uses cursor-based infinite scroll with a 25/50/100 page-size selector; zero-result state surfaces "Recent activity on TICKER" + "Broaden filters" CTA when entity-resolved. |

### Tier 2 — Trust and Feel

| FR-T2-1 | WebSocket quote stream for visible "aliveness" |
|---|---|
| | S2 fans Alpaca WS quotes to Kafka topic `market.quote.live.v1`; S9 exposes `/v1/quotes/stream` (WebSocket) authenticated via internal JWT; frontend subscribes in chart current price, instrument header, watchlist, and dashboard pre-market movers (4 surfaces only — not every cell). Acceptance: at NYSE open, the four surfaces visibly flash green/red within 2s of price change. |

| FR-T2-2 | Multi-tenant isolation via Postgres RLS, free/paid tier gate, Stripe |
|---|---|
| | Postgres RLS policies on `portfolios`, `holdings`, `watchlists`, `alerts`, `alert_rules`, `chat_sessions`, `chat_messages`, `feedback`. Gate enforces `tenant_id = current_setting('app.tenant_id')`. JWT `tenant_id` claim → connection-level `SET app.tenant_id = ...`. Free tier: 5 watchlist symbols, 10 chat queries/day, 100 search queries/day. Pro tier ($19/month, monthly Stripe): unlimited everything. Acceptance: cross-tenant query attempts return zero rows in integration test; Stripe test-mode subscription flow works end-to-end. |

| FR-T2-3 | Visible regression cleanup |
|---|---|
| | Apply BP-302 article-consumer hang fix (already in commit `f27e266b` — redeploy + reset offset); fix F-VISUAL-002 (`--muted-foreground` divergence between `:root` and `.dark` blocks); fix F-E8 (`/undefined` race already in `f27e266b`); fix F-D4 (EU date parsing already in `f27e266b`). Acceptance: WCAG AA contrast on every `text-muted-foreground` cell; zero `/undefined` 500-errors in 24h gateway logs. |

### Tier 3 — Loved If Time Permits

| FR-T3-1 | Sentry + public status page + uptime monitor |
|---|---|
| | Sentry integration on S9 + S6 + S8 backends + worldview-web (free tier sufficient for MVP traffic); UptimeRobot probes both `S9 /healthz` (5-min, page-immediately) AND `S9 /readyz` (15-min, dependency degradation); status.<domain> rendered as an in-tree Next.js page with a server-only Route Handler proxying UptimeRobot (Atlassian Statuspage free tier was discontinued; revised 2026-05-03 per audit I-004). **Status page surfaces per-component pills** ("Platform", "Caching & rate limits", and — once W6/W4 ship — "Search", "AI Briefs"), NOT raw monitor names; an in-tree `incidents.json` allows hand-editing of an incident banner ("AI brief generation degraded — investigating") so Sam sees real comms during incidents instead of "all green". Acceptance: a synthetic exception in worldview-web is captured in Sentry within 60s; status page shows live uptime for last 30 days; Sentry `before_send` PII guard scrubs URLs containing entity tickers (PRD §9 privacy contract — no Sam research-footprint leaks to third-party SaaS). |

| FR-T3-2 | LLM-generated alert explanation field (single feature pulled from ALERT_ENHANCEMENT_STRATEGY.md) |
|---|---|
| | See §13 — only the explanation field is in scope; the rule builder is explicitly **out of scope** for MVP. |

## 4. Non-Functional Requirements

| Attribute | Target | Notes |
|-----------|--------|-------|
| **Search p95 latency** | ≤500ms | Full-text search; pagination 25/page |
| **AI Brief generation** | ≤8s end-to-end | Streamed; first content ≤3s |
| **WebSocket fan-out latency** | ≤2s | Alpaca WS → Kafka → S9 → frontend |
| **Page TTI (instrument page)** | ≤1.5s p95 | Includes batch endpoint composition |
| **Free-tier rate limits** | 10 chat / 100 search / 5 watchlist symbols | Enforced at S9 via Valkey token bucket per tenant |
| **Pro-tier rate limits** | unlimited (soft cap 1000 chat/day to prevent abuse) | |
| **RLS overhead** | ≤5% query latency | Verified on portfolio + watchlist routes |
| **Test pass rate at launch** | 100% backend + frontend + architecture | No regressions introduced by any FR |
| **Citation accuracy** | 100% bullets cite at least one document; 100% of `[cN]` markers in `lead` resolve to a citation in the top-level `citations[]` list; 0% citations return 404 | Verified in CI (schema/shape: PLAN-0062 W4-C-04; runtime LLM-judge: PLAN-0063 W5-5-02) |
| **Golden-eval NDCG@10** | ≥+0.05 absolute over ANN-only | CI-gated |
| **Observability — Sentry** | All unhandled exceptions captured | |
| **Observability — uptime** | ≥99% measured by UptimeRobot for 30 days post-launch | |

## 5. Out of Scope (Explicit Exclusions)

The following are **explicitly excluded** from the MVP launch and deferred. Each was evaluated and cut.

| Excluded | Reason |
|----------|--------|
| Drawing tools (PLAN-0050 Wave 2) | TradingView already owns this market; net-zero willingness-to-pay |
| Polymarket comprehensive ingestion (PRD-0033) | One panel ships; the rest defers; novelty signal not a paying-user driver |
| Custom alert rule builder (ALERT_ENHANCEMENT_STRATEGY.md §3.2) | Classic expert-user trap; <10% adoption realistic; replaced with 3 hand-curated alert profiles in v2 |
| One-click broker actions (ALERT_ENHANCEMENT_STRATEGY.md §3.4) | Requires SnapTrade integration (PRD-0022 blocked); fantasy until broker connection ships |
| Workspace drag-resize improvements | Pure UX polish; zero willingness-to-pay impact |
| TopBar marquee polish | Cosmetic; redundant with watchlist |
| Multi-provider OHLCV routing (PLAN-0040) | EODHD alone sufficient for MVP universe |
| SnapTrade/TastyTrade brokerage sync | Pre-requires ≥100 paid users to justify |
| Multi-currency / yield curve / futures | L1 lane does not need this; pitch as "Pro tier roadmap" |
| New alert types: PRICE_BREACH, DIVIDEND_ANNOUNCED, EARNINGS_ANNOUNCEMENT | Phase-2 post-launch; depends on price-impact worker (currently 401-ing) being unblocked first |
| Mobile native push notifications | Email + WebSocket sufficient for MVP; native push is post-product-market-fit |
| Email digest scheduling | Phase-2 |
| Institutional features (SOC2, audit logs, SSO/SAML) | Out of L1 scope; pursue only after first 100 paid users |

## 6. Workstreams (Subdivision for /plan)

This PRD does not produce a single implementation plan. It produces **9 workstreams**, each suited to its own `/plan` invocation. The workstreams are dependency-ordered.

### Workstream W1 — KG Remediation (Tier 0, FR-T0-1)
**Owner**: knowledge-graph + nlp-pipeline services. **Consumes**: `docs/audits/2026-04-30-retrieval-graph-architecture-revised.md` Phase 1; PLAN-0058 Waves A/B.
**Inputs**: existing entity-resolution cascade, GLiNER classes, `_build_raw_relations` source. **Outputs**: relation_evidence ≥10K rows, AGE ≥1K nodes, ≥80% article coverage. **Estimate**: 5 dev-days. **/plan target**: `0060-kg-remediation-mvp-plan.md`.

### Workstream W2 — Universe Expansion (Tier 0, FR-T0-2)
**Owner**: market-ingestion + market-data. **Consumes**: PLAN-0055 (already drafted), EODHD T3 polling tier. **Outputs**: ≥600 instruments with ≥1y OHLCV + latest fundamentals. **Estimate**: 3 dev-days. **/plan target**: extend `0055-backfill-source-stability-llm-provenance-plan.md`.

### Workstream W3 — Feature Cull and Empty-State Pass (Tier 0, FR-T0-3)
**Owner**: worldview-web only. **Consumes**: PLAN-0059. **Outputs**: clickthrough audit report (text doc) + frontend PR removing or hiding broken surfaces. **Estimate**: 2 dev-days. **/plan target**: inline in W4 or standalone `0061-mvp-feature-cull-plan.md`.

### Workstream W4 — Structured AI Brief (Tier 1, FR-T1-1)
**Owner**: rag-chat (S8) + api-gateway (S9) + worldview-web. **Outputs**: brief endpoint with deterministic schema + frontend rendering. **Estimate**: 3 dev-days. **/plan target**: `0062-structured-brief-plan.md`. **Needs follow-up detailed PRD** for the schema (JSON Schema + Pydantic model + frontend zod schema).

### Workstream W5 — Hybrid Retrieval + Eval Gate (Tier 1, FR-T1-2)
**Owner**: rag-chat + ml-clients. **Consumes**: PLAN-0058 Waves C+D. **Estimate**: 5 dev-days. **/plan target**: existing `0058-retrieval-and-kg-strategic-uplift-plan.md` Waves C+D (already detailed).

### Workstream W6 — Full-Text Search with Entity Facets (Tier 1, FR-T1-3)
**Owner**: content-store (S5) or new `search-service` shim + S9 + worldview-web. **Outputs**: tsvector indexes, search route, entity facet sidebar. **Estimate**: 4 dev-days. **/plan target**: `0063-full-text-search-plan.md`. **Needs follow-up detailed PRD** — this is the L1 keystone feature and warrants full schema/endpoint specification.

### Workstream W7 — WebSocket Quote Stream (Tier 2, FR-T2-1)
**Owner**: market-data (S2) + S9 + worldview-web. **Outputs**: Kafka producer fan-out from Alpaca WS + S9 WS proxy + 4 frontend subscription points. **Estimate**: 3 dev-days. **/plan target**: `0064-quote-stream-plan.md`. **Needs follow-up detailed PRD** — Avro schema for `market.quote.live.v1`, partition strategy, WS auth, reconnect/backpressure semantics.

### Workstream W8 — Multi-Tenant + Tier Gate + Stripe (Tier 2, FR-T2-2)
**Owner**: cross-cutting (every service with user data) + S9 + worldview-web. **Consumes**: PRD-0002 (multi-tenant SaaS foundation, draft) + PRD-0025 (auth foundation, shipped). **Estimate**: 5 dev-days. **/plan target**: `0065-rls-tier-stripe-plan.md`. **Needs follow-up detailed PRD** — RLS policy per table, free/Pro feature matrix, Stripe webhook design, tenant provisioning flow.

### Workstream W9 — Visible Regression Cleanup + Observability (Tier 2+3, FR-T2-3, FR-T3-1)
**Owner**: cross-cutting. **Outputs**: redeploy + offset reset, CSS fix, Sentry integration, UptimeRobot, status page. **Estimate**: 1.5 dev-days. **/plan target**: `0066-mvp-stability-observability-plan.md`.

### Workstream W10 — Alert Explanation Field Only (Tier 3, FR-T3-2)
**Owner**: alert-service (S10) + rag-chat (S8) + worldview-web. **Outputs**: `explanation` column on `alerts` table; `GenerateAlertExplanationUseCase`; frontend rendering. **Estimate**: 1.5 dev-days. **/plan target**: inline in W9 or standalone `0067-alert-explanation-plan.md`.

## 7. Dependency Graph and Sprint Calendar

```
Week 1:  W1 (KG)              W2 (Universe)         W3 (Cull)
Week 2:  W4 (Brief)           W9 (Stability)        [W3 polish]
Week 3:  W5 (Hybrid + Eval)
Week 4:  W6 (Full-Text Search) ← keystone L1 feature
Week 5:  W8 (RLS + Tier + Stripe)
Week 6:  W7 (WebSocket) + W10 (Alert Explanation) + landing rewrite + closed beta open

Hard dependencies:
- W5 depends on W1 (KG must seed entities before retrieval can use entity-aware ranking)
- W4 (brief) depends on W1 (KG must persist relations to cite from)
- W6 depends on W2 (universe must exist to search across)
- W8 must precede public launch (cannot onboard 2nd user safely without RLS)
```

If a week slips, cut from Tier 3 (W10, observability extras) first, never from Tier 0/1.

## 8. Architecture Decisions

### AD-1: This is a launch program, not a single feature
**Decision**: PRD-0034 stays at the meta-PRD level. Each workstream that needs a detailed entity/schema spec produces its own follow-up PRD-0035..PRD-0040 before its `/plan` runs.
**Rationale**: A single 100KB PRD covering 9 workstreams produces a 9-wave plan with shallow detail per wave. Splitting at workstream boundaries keeps each detailed PRD focused on one consistent domain.
**Workstreams that NEED their own detailed PRD** before /plan: W4 (brief schema), W6 (search), W7 (WS quote stream), W8 (RLS + Stripe).
**Workstreams that can go straight to /plan** without further PRD: W1, W2, W3, W5 (already detailed in PLAN-0058), W9, W10.

### AD-2: L1 lane decision (AI-native research terminal)
**Decision**: Position MVP as L1, not L2 (retail prosumer dashboard) or L3 (news feed).
**Rationale**: Documented in §2. L1 is the only lane where the existing KG/RAG investment matters and where willingness-to-pay is proven (FinChat.io comp).
**Reversibility**: Reversible up to launch. After launch, lane is sticky for ≥6 months because messaging/SEO/content all aligned.

### AD-3: Cull > finish for half-shipped features
**Decision**: Hide drawing tools, options chain, multi-currency, etc., behind "Pro Q3" empty states rather than rushing to finish them for MVP.
**Rationale**: A clean "coming soon" reads as confident roadmap; a half-broken feature reads as unreliable engineering. Same surface area, opposite emotional response.
**Trade-off**: Some users will bounce because their needed feature is "Q3." This is a smaller cohort than the cohort that would bounce on a broken feature.

### AD-4: Custom alert rules deferred; explanation field only
**Decision**: Pull only the LLM-explanation field from ALERT_ENHANCEMENT_STRATEGY.md. Defer the rule builder, condition tables, rule evaluator, and one-click actions to Phase-2 post-launch.
**Rationale**: §13 below.
**Trade-off**: Loses one differentiator vs. TradingView (custom screeners) but TradingView users don't churn to Worldview for screeners — they churn for AI explanations.

### AD-5: Free tier $0 / Pro tier $19/month; Stripe monthly only
**Decision**: Single paid tier; no annual discount at launch; no enterprise tier.
**Rationale**: Pricing experiments come post-product-market-fit. Annual + multiple tiers add complexity without evidence. $19 is below FinChat.io's $50 and well above commodity ($5–10) — anchoring as research-grade value.
**Reversibility**: Fully reversible; pricing can change weekly without code changes (Stripe price IDs in env).

### AD-6: RLS for isolation; no separate physical tenant DBs
**Decision**: Postgres row-level-security with `tenant_id` filter, not physical DB-per-tenant.
**Rationale**: Same decision as PRD-0002 (already drafted). Physical isolation is enterprise-tier work; RLS is sufficient for the L1 paid persona and the MVP scale (≤1000 paid users).

## 9. Security Analysis

| Concern | Mitigation |
|---------|-----------|
| Cross-tenant data leakage | RLS policies (W8) on every table with `tenant_id` column. Integration test: 2-tenant fixture asserts queries return zero foreign rows. |
| Stripe webhook spoofing | Verify webhook signature with Stripe-issued secret; reject on mismatch. Idempotency-key on subscription event processing. |
| Free-tier rate limit bypass | Rate limit is per `tenant_id` from internal JWT, not per IP; abuse vector requires creating multiple accounts. Add email-verification-required for paid signup. |
| Search query injection (tsvector) | Use parameterised query; escape `:` `&` `|` `!` `(` `)` from user input before passing to `to_tsquery`; or use `plainto_tsquery` which auto-escapes. |
| Alert explanation prompt injection | Untrusted alert payload goes into LLM prompt. Mitigation: structured prompt template; payload field values rendered as JSON not as instructions. Acceptable risk: explanation text is user-facing but not a privileged operation. |
| WebSocket auth | WS connection requires `Authorization: Bearer <jwt>` on initial handshake (S9 InternalJWTMiddleware applies). Reject anonymous WS. |
| Public status page leakage | Status page shows uptime only, not error details or stack traces. |

## 10. Failure Modes

| Mode | Recovery |
|------|----------|
| EODHD rate-limited during universe expansion | Backoff + resume from last `cursor`; partial completion is acceptable as long as S&P 500 finishes |
| KG seed batch fails partway | Idempotent: re-running skips already-seeded entities (UNIQUE constraint on `canonical_entities.label`) |
| Stripe webhook delivery delay | Subscription tier check falls back to `tier_cached_until` in users table; Stripe state reconciled on next webhook |
| Alpaca WS disconnect | Frontend auto-reconnects with exponential backoff (max 30s); shows "Quotes paused — reconnecting" indicator |
| Sentry quota exhausted | Free tier 5K errors/month sufficient for MVP; alert-on-quota at 80% via Sentry's own usage alert |
| LLM provider down (DeepInfra) | Brief returns `error: "Brief temporarily unavailable"` rather than a low-quality fallback; better to fail visibly than to ship hallucination |

## 11. Test Strategy

This PRD does not enumerate test cases — those belong in the workstream-level PRDs. Cross-workstream test gates:

| Gate | When | What |
|------|------|------|
| Backend regression | Every PR | `pytest` across all 10 services + libs (~5,200 tests) |
| Frontend regression | Every PR | Vitest 79 files / 1,196 tests |
| Architecture invariants | Every PR | 95-test suite (R12, R22, R25, IG-LAYER-001/002) |
| Golden-eval NDCG@10 | PR touching rag-chat or ml-clients | CI fails if NDCG@10 regresses ≥3% (W5 deliverable) |
| 2-tenant RLS integration | PR touching any table with `tenant_id` | Pytest fixture creates 2 tenants, asserts zero cross-leakage on every queried table |
| Citation accuracy | PR touching brief or chat endpoints | 50-claim fixture set; CI fails if any citation 404s or has empty `snippet` |
| Visual regression | PR touching `worldview-web/components/` | Playwright screenshots vs. baseline; manual approval on diff |
| Clickthrough audit | Every Tier 0 workstream | Manual: free-tier user clicks every visible nav item; result is a markdown report committed to `docs/audits/` |

## 12. Migration / Rollout

| Phase | Trigger | Action |
|-------|---------|--------|
| Pre-flight | All Tier 0 workstreams complete | Internal dogfood for 3 days; founder + 2 friends |
| Closed beta | All Tier 1 + Tier 2 workstreams complete | 50–100 invited users from target persona; Stripe live but free invitation codes for first 30 days |
| Public launch | 30 days into closed beta with no critical issues | Landing page live; ProductHunt + 3 finance subreddit posts + targeted X (Twitter Finance) outreach |
| Post-launch | Continuous | Weekly metric review (signups, conversions, churn, NDCG@10, error rate); monthly pricing review |

**Rollback strategy**: Each workstream is independently revertable via `git revert` of the workstream branch. RLS is the only workstream where rollback is destructive (data may already exist with `tenant_id` set); rollback plan is "fix forward, don't revert."

## 13. Evaluation of `ALERT_ENHANCEMENT_STRATEGY.md`

The user explicitly asked whether the alert strategy doc is a real moat-worthy enhancement. **Honest evaluation**:

### What the doc gets right

1. **AI-generated alert explanations are genuinely differentiating.** No major competitor (TradingView, Bloomberg, Seeking Alpha, MarketWatch) ships LLM-explained alerts. The `explanation` column is forward-compatible (nullable, default null) and the implementation cost is low (~1.5 dev-days). **Pulled into MVP as W10 / FR-T3-2.**
2. **The "alert fatigue" problem is real** and the framing ("users see HIGH CRITICAL CRITICAL with no context") is accurate to current state.
3. **The S8/S10 architecture sketch is sound** — explanation generation as a separate use case, cached in Valkey, stored on Alert row. This is the right shape.

### What the doc gets wrong

1. **It builds a rules engine on top of an empty signal pipeline.** As of 2026-05-02, `relation_evidence` = 0 rows, `article_impact_windows` = 0 rows (price-impact worker is 401-ing), AGE = 0 nodes. Until W1 lands, there are barely any signals to filter through user-defined rules. **Building rule plumbing first is putting a faucet on a closed pipe.**
2. **Custom rule builders are a classic expert-user trap.** Empirical adoption in early-stage products: 5–10% of active users, not 60% as the doc claims. The 95% who don't configure get an unchanged experience. The 5% who do configure are frequently power users who would have stayed anyway. **Net retention impact: marginal at best, deeply negative if it delays the launch.**
3. **The "60% rule adoption" success metric and "30-day churn ↓ 15%" metric are unrealistic** for a single feature in an MVP. Whoever wrote this hasn't shipped a rules engine before.
4. **One-click broker actions are fantasy.** PRD-0022 (SnapTrade) is blocked. There is no broker integration to act through. The mockup in §3.4 markets a feature that cannot exist for ≥3 months.
5. **The Phase-1 "4 weeks" budget is the entire MVP launch budget.** Spending it on alerts means cutting tick stream, RLS, KG fix, and full-text search. The opportunity cost is catastrophic.
6. **The deferred Phase-2 alert types (PRICE_BREACH, EARNINGS_ANNOUNCEMENT, DIVIDEND_ANNOUNCED) are MORE valuable than custom rules** — they're table-stakes (every TradingView competitor has them) and require no user configuration. The doc has the priority order inverted.

### Recommendation

| Item | Status |
|------|--------|
| LLM-generated alert explanations (column + use case) | **KEEP — in MVP as W10** |
| Custom alert rule builder | **DEFER — Phase-2 post-launch, possibly never** |
| Rule condition tables (`alert_rules`, `alert_rule_conditions`) | **DEFER** |
| Rule test/dry-run endpoint | **DEFER** |
| Rule UI (`<AlertRuleBuilder />`, `/alerts/rules` page) | **DEFER** |
| One-click broker actions | **KILL** until brokerage integration ships |
| New alert types (PRICE_BREACH, EARNINGS, DIVIDEND) | **DEFER to Phase-2 — but prioritise OVER rule builder when Phase-2 starts** |
| Email digest scheduling | **DEFER** |
| Mobile push | **KILL until product-market fit** |

**Replacement for custom rules in MVP**: Ship 3 hand-curated alert profiles in W10 (no UI, just defaults selectable in user settings):
- **Conservative**: only CRITICAL severity; only positive forward_guidance signals
- **Active trader**: ≥MEDIUM severity; all polarities; market_impact ≥0.5
- **Earnings season**: only earnings + guidance claim types; all severities

Same UX value at 5% the effort. **Add this as a single sub-task inside W10 if time permits.**

### Action on the source doc

The doc currently lives at `docs/specs/ALERT_ENHANCEMENT_STRATEGY.md`. Recommend:
1. Add a header at the top of that file: `> Status: PARTIAL — see PRD-0034 §13. Only LLM-explanation field accepted into MVP. Rule builder and remaining sections deferred to Phase-2 post-launch.`
2. Do **not** delete the doc; the Phase-2 design thinking is still useful when we revisit alerts after MVP traction is established.

## 14. Open Questions

### BLOCKING — must resolve before any /plan or /implement

- **OQ-1**: Confirm L1 lane (AI-native research terminal) vs. L2 (prosumer dashboard) vs. L3 (news feed). The entire workstream priority changes if you pick L2 or L3.
- **OQ-2**: Confirm $19/month Pro tier pricing or supply alternative. Stripe price IDs and landing page copy depend on this.
- **OQ-3**: Confirm closed-beta target users — which 50–100 specific people from target persona. Without this, "launch" has no audience.
- **OQ-4**: Confirm scope of W3 cull — explicit list of features to hide. I drafted one in §3 but you may want to keep some items I cut.

### DEFERRED — can be resolved during workstream PRDs

- **OQ-5**: ~~Exact JSON Schema for structured AI Brief response (W4)~~ **RESOLVED 2026-05-03** in §3 FR-T1-1: `{headline, lead, sections, confidence, generated_at}` where `lead` is a 1-sentence-to-1-paragraph synthesis with inline `[cN]` markers. PRD-0035 not required; PLAN-0062 W4 owns the Pydantic + TS implementation.
- **OQ-6**: Avro schema for `market.quote.live.v1` (W7) — fields, partition key, retention. Defer to follow-up PRD-0037.
- **OQ-7**: Search route exact query parameters and pagination semantics (W6). Defer to follow-up PRD-0036.
- **OQ-8**: RLS policy text for each table (W8). Defer to follow-up PRD-0038.
- **OQ-9**: Stripe product/price IDs and webhook event handling (W8). Defer to follow-up PRD-0038.
- **OQ-10**: Whether the 3 hand-curated alert profiles ship in W10 or are deferred to Phase-2. Recommend ship if W10 finishes ahead of schedule.
- **OQ-11**: Whether to use a managed search service (Algolia / Typesense) vs. Postgres `tsvector` for W6. Recommend Postgres for cost; revisit if latency targets miss.
- **OQ-12**: Domain name for production launch and marketing site copy. Out of engineering scope but blocks public launch.

## 15. Estimation Summary

| Workstream | Days | Tier |
|-----------|------|------|
| W1 KG remediation | 5 | T0 |
| W2 Universe expansion | 3 | T0 |
| W3 Feature cull | 2 | T0 |
| W4 Structured AI Brief | 3 | T1 |
| W5 Hybrid retrieval + eval | 5 | T1 |
| W6 Full-text search | 4 | T1 |
| W7 WebSocket quote stream | 3 | T2 |
| W8 RLS + tier + Stripe | 5 | T2 |
| W9 Stability + observability | 1.5 | T2/T3 |
| W10 Alert explanation | 1.5 | T3 |
| **Total dev-days** | **33** | |
| **Calendar weeks at 1 dev** | **~6.5** (with parallelism, calendar 6) | |
| **Calendar weeks at 1 dev, no parallelism** | ~7 | |

If calendar must compress to 4 weeks: cut W3 (do it inline during W1/W2), W6 (defer full-text search to v1.1), W10 (defer alert explanation entirely). **Do not cut W1, W2, W7, W8.**

---

## 16. Suggested Next Actions

1. **User reviews and answers OQ-1 through OQ-4** (BLOCKING).
2. **Add the deprecation header to `docs/specs/ALERT_ENHANCEMENT_STRATEGY.md`** as recommended in §13.
3. **Generate workstream-level detailed PRDs** for W4, W6, W7, W8 (the four workstreams flagged in AD-1 as needing follow-up PRDs). Suggested invocation pattern: `/prd Structured AI Brief schema (PRD-0034 W4 follow-up)`, etc.
4. **For workstreams that can go straight to /plan** (W1, W2, W3, W5, W9, W10): invoke `/plan` per workstream, which will produce dependency-ordered waves.
5. **/schedule a 6-week-out check-in agent** to verify launch metrics post-go-live (signups, NDCG@10, churn, error rate). Recommend: weekly cadence for the first 4 weeks post-launch.

---

## Appendix A — Compounding Notes

This PRD itself is a new pattern: a launch-program meta-PRD that explicitly delegates detail to workstream-level follow-up PRDs. If this pattern proves useful, consider adding a `/launch-program` skill template that codifies §1–§16 structure for future major releases.

**Compounding check**: no updates to BUG_PATTERNS / RULES / skills needed at this stage. The launch program PRD pattern (this document's structure) may be worth codifying after one full launch cycle proves it.
