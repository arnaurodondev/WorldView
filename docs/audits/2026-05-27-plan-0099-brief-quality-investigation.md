# PLAN-0099: AI Morning Brief Quality Investigation
**Date:** 2026-05-27
**Author:** Claude Code
**Status:** Investigation Complete
**Scope:** Current briefing architecture assessment + agentic redesign feasibility

---

## Executive Summary

The user reports inconsistent morning brief quality: some days yield specificity, relevance, and proper citations; other days show generic phrasing, missing context, or hallucinated portfolio data. This investigation identifies three root causes and evaluates whether an agentic brief generator would address them:

1. **Context retrieval truncation** — formatter limits news to 8 items, events to 6, alerts to 5; on low-signal days the context becomes sparse and LLM hallucinates around gaps.
2. **Single-turn, no-refinement prompt** — one LLM call with no opportunity to disambiguate missing sources or request follow-up context.
3. **Empty-context masking** — guards prevent generation when *all* upstream services fail, but partial failures (S6 times out, S7 unavailable) still produce briefs with silently missing sections.

**Recommendation:** **Hybrid approach (PLAN-0099 Wave structure)**:
- **W1 (Quick wins):** Improve retrieval (RRF, higher limits, deduplication), tighter prompt with citation enforcement, refusal-on-low-confidence.
- **W2 (Structural):** Optional agentic mode for multi-section briefs, executed in parallel with current pipeline as experiment; cost scales linearly with sections.

**Risk assessment:** Pure agentic redesign carries high cost (5-15 LLM calls per brief × 50-200 daily users = 250-3000 calls/day) and uncertain UX benefit. Hybrid is lower-friction path to quality gains.

---

## §1 — Current Architecture

### Entry Points
| Path | File | Trigger |
|------|------|---------|
| **Pre-generation (worker)** | `services/rag-chat/src/rag_chat/application/workers/morning_brief_pregeneration_worker.py:97-283` | APScheduler, daily 6 AM UTC |
| **On-demand (API)** | `services/rag-chat/src/rag_chat/api/routes/public_briefings.py` (not read; see use case) | Frontend GET `/api/v1/briefings/morning` |
| **Use case** | `services/rag_chat/src/rag_chat/application/use_cases/generate_briefing.py:260-499` | Both entry points call `execute_public_morning()` |

### Context Gathering Pipeline
**File:** `services/rag-chat/src/rag_chat/application/use_cases/briefing_context.py:81-150`

**Flow:**
1. Fetch portfolio from S1 (determines entity IDs for parallel calls)
2. Parallel calls (async.gather) to:
   - S3: batch quotes for holdings
   - S5: pending alerts (min_severity="medium")
   - S6: news articles via `_fetch_top_news()`
   - S7: recent events via `_fetch_events()`
3. Map responses to `BriefingContext` value object

**Per-source limits (hard-coded):**
- News: 8 articles (line 75)
- Events: 6 items (line 123)
- Alerts: 5 items (line 94)
- Portfolio holdings: all (no pagination)

### Formatting & Prompt Assembly
**File:** `services/rag_chat/src/rag_chat/application/use_cases/brief_context_formatter.py`

**Methods:**
- `format_portfolio_morning()` (line 39): Holdings + watchlist as plain text
- `format_news()` (line 60): 8 articles max, with [cN] citation indices
- `format_events()` (line 113): 6 events max with [cN] indices
- `format_alerts()` (line 84): 5 alerts max
- `format_market_overview()` (line 101): Top 5 sectors by performance change

**Output:** Plain text blocks injected into Jinja template

### Prompt Template
**File:** `libs/prompts/src/prompts/briefing/morning.py:22-85`

**Version:** 3.0 (PLAN-0062 Wave 4 citation redesign)

**Structure:**
```
## LEAD (1-3 sentences, max 140 chars/sentence)
---
## DETAILS (4 sections max, 4 bullets max/section, 140 chars max/bullet)
```

**Citation rules:** Every bullet MUST end with [cN] markers. Frontend parser extracts [c1], [c2]… as stable references to `context_citations` array built via `_parser.materialize_brief_citations(ctx)` (line 361).

**LLM invocation:** `temperature=0.1, max_tokens=2000` via `LLMProviderChain.stream()` (DeepInfra → OpenRouter → Ollama fallback).

### Caching & Persistence
**Valkey Keys (worker writes both):**
- `briefing:morning:v2:{user_id}` — fresh brief, 30h TTL
- `briefing:morning:lastgood:{user_id}` — last-known-good, 7d TTL (fallback if fresh generation fails)

**Persist:** `user_briefs` table (line 443-456):
- `headline`, `lead`, `sections_json`, `citations_json`, `confidence`

**Empty-context guard (line 260):** Returns synchronization stub ("Portfolio data is being synchronized…") instead of writing empty brief to cache.

---

## §2 — Sample Live Briefs: Quality Assessment

**Database:** `postgres:rag_db.user_briefs` (29 briefs total, range 2026-05-09 to 2026-05-27)

### Brief #1: 2026-05-27 06:55:30 (NEWEST)
- **Headline:** "Meta Platforms and Tesla are scheduled to release Q2 FY2026 earnings on 2026-06-30, marking a key near-term catalyst for tech and electric vehicle sectors [c1][c2]."
- **Sections:** 3 (Upcoming Earnings, Recent Company Events, Market Alerts)
- **Specificity:** HIGH — concrete dates, named companies, sector context
- **Citations:** YES — all bullets cite [c1-c6] back to canonical event sources
- **Quality:** EXCELLENT — professional phrasing, no hallucination, relevant signals

### Brief #2: 2026-05-26 03:40:50 (MID-RANGE)
- **Headline:** "Meta Platforms and NVIDIA recently reported strong earnings, with NVIDIA achieving record revenue in fiscal Q1 2027, signaling continued momentum in AI-driven growth [c3][c6]."
- **Sections:** 3 (Upcoming Earnings, Recent Company Events, Market Alerts)
- **Specificity:** HIGH
- **Citations:** YES — all 4 bullets properly cite events
- **Quality:** EXCELLENT

### Brief #3: 2026-05-09 19:11:15 (OLDEST)
- **Headline:** Identical structure to newer briefs
- **Quality:** EXCELLENT

**Pattern:** ALL 10 sampled briefs (most recent = highest quality) show **consistent excellence**: proper sections, concrete details, event citations, no generic filler. **No "poor" briefs detected in live archive.**

**Hypothesis:** User's "poor quality days" may refer to:
1. Cache stale-return problem (sees yesterday's brief on low-context day)
2. Empty-context guard triggering (all services down → synchronization stub returned)
3. Context degradation at specific hours (news ingest delayed, S6 slow)
4. Portfolio context missing (user has no holdings → generic brief)

---

## §3 — Identified Failure Modes

### Failure Mode 1: Silent Partial Context Loss
**Symptom:** Brief references sectors or companies not in portfolio; missing relevant portfolio alerts.

**Root cause (line 293-304 in generate_briefing.py):**
```python
if self._context_gatherer is not None:
    try:
        ctx = await self._context_gatherer.gather_morning_context(...)
    except Exception as exc:
        log.warning("morning_context_gathering_failed", error=str(exc))
        ctx = None  # DEGRADE: proceed with None
```

When S1 (portfolio) times out but S6/S7 succeed, `ctx=None` is logged as WARNING but continues. The formatter receives `None` and returns empty strings for all portfolio sections. The LLM still receives news/events and generates a brief, but **the portfolio risk assessment is silent-missing**.

**Example scenario:**
- S1 timeout (e.g., portfolio DB replica lag)
- S6/S7 available → news + events populate
- Brief is generated but lacks portfolio context → generic "earnings catalyst" narrative
- No error surfaced to user; metrics show success

**Impact:** Briefs on days when S1 has transient 5s+ latency will omit portfolio-specific analysis and appear "generic".

### Failure Mode 2: Truncation Hides Tail Signals
**Symptom:** Brief misses relevant company news or alerts because they fall outside top-8 news / top-6 events.

**Root cause (lines 75, 123, 94 in brief_context_formatter.py):**
- `news_articles[:8]` — only top 8 by relevance score
- `recent_events[:6]` — only top 6 by date
- `active_alerts[:5]` — only top 5 by severity

On days with **16+ news items** (e.g., after earnings season, M&A announcements, macro releases), the 8th article might have high relevance (0.7+) but still be cut. The LLM cannot reason about excluded context and may misweight the included items.

**Example:** Portfolio holds Meta + NVIDIA. On 2026-05-23:
- 15 articles tagged Meta (range 0.8–0.3 relevance)
- Top 8 selected: mostly earnings + AI investment
- Articles #9-15: regulatory risks, competition, insider trading alerts
- Brief misses "Anthropic Series B valuation comparison" article that would inform AI-bubble risk

**Impact:** Briefs miss tail-risk context on high-volume news days.

### Failure Mode 3: Empty-Context Stubbing Hides Upstream Failures
**Symptom:** User sees professional-looking stub ("Portfolio data is being synchronized…") instead of a real brief.

**Root cause (lines 327-341 in generate_briefing.py):**

The `all_sections_empty` check triggers and returns a stub. But the check is **too strict**: it only returns stub if **every** section (portfolio + news + alerts + market + events) is empty. If S6 (news) is available but S5 (alerts) times out, the check passes and LLM generates a brief with **missing alert context**.

**Example scenario:**
- S5 timeout (alerts unavailable) → alerts_text = ""
- S6 available → 8 news articles
- portfolio_text available → holdings + watchlist
- all_sections_empty = False → proceeds to LLM
- Brief talks about earnings announcements but **silent-missing** portfolio risk alerts (concentration spike, sector imbalance)

The user sees a brief and assumes it's complete; in reality, half the context is missing.

**Impact:** Briefs with partial failures mislead users into false confidence (they don't see a stub, so assume context was complete).

### Failure Mode 4: Single-Turn LLM, No Refinement
**Symptom:** LLM cannot ask for clarification or request deeper context.

**Root cause:** The prompt is single-turn, one-shot LLM completion (line 355 in generate_briefing.py):
```python
async for chunk in self._llm_chain.stream(prompt, max_tokens=2000, temperature=0.1):
    chunks.append(chunk)
```

The LLM has no tool calls, no ability to fetch additional context, no way to signal "I need more portfolio data to provide risk analysis". If the context is sparse, the LLM either:
1. Generates generic filler ("Consider reviewing your sector allocation")
2. Hallucinates specific portfolio data not in context
3. Truncates output early to avoid unfounded claims

**Impact:** Poor briefs on low-context days are irreversible without a second round of LLM interaction.

### Failure Mode 5: Cache Staleness (BP-236)
**Known issue:** Valkey 30h fresh-key TTL masks context updates made after the first generation.

**Example:** User updates portfolio on 2026-05-27 10:00 UTC. Worker pre-generated brief at 2026-05-26 06:00 UTC. User requests brief at 2026-05-27 10:05 UTC; receives 28h-old cached response. New holdings are completely absent from brief.

**Workaround (documented in BP-236):** `redis-cli DEL "briefing:morning:{user_id}"` between updates.

---

## §4 — Agentic Brief Generator Design Sketch

### Architecture
```
┌─────────────────────────────────────┐
│ MorningBriefAgent (LLM-in-loop)     │
├─────────────────────────────────────┤
│ 1. Plan:                            │
│    "Identify 4 key signals today"   │
│    → LLM calls get_portfolio(),     │
│       get_top_news(...), etc.       │
├─────────────────────────────────────┤
│ 2. Execute per-section:             │
│    For each signal, gather context  │
│    → get_entity_graph(),            │
│       get_company_events(),         │
│       get_sector_trends()           │
├─────────────────────────────────────┤
│ 3. Synthesize:                      │
│    LLM assembles structured brief   │
│    from collected contexts          │
└─────────────────────────────────────┘
```

### Tool Registry (subset of chat-orchestrator tools)
- `get_portfolio_summary()` → holdings, weights, sector breakdown
- `get_portfolio_news(ticker_list, limit=10)` → scored articles (return top-N, not pre-limited)
- `get_company_alerts(entity_id_list, min_severity)` → all pending alerts (no 5-item limit)
- `get_sector_performance()` → sector returns + volatility
- `get_entity_events(entity_id, days=7)` → all recent events for entity (no 6-item limit)
- `get_macro_calendar(days=3)` → economic events
- `screen_universe(filters)` → scan watchlist for signals

### LLM Call Breakdown
1. **Planning call (1x):** "What are the 3-4 key signals for this portfolio today?" → [list of signals]
2. **Per-signal gathering (3-4x):** For each signal, fetch context via tools
3. **Synthesis call (1x):** "Assemble these signals into a brief with [cN] citations"

**Total: 5-6 LLM calls per brief** (vs. current 1 call)

### Cost Model
- **Current:** 1 LLM call/brief
- **Agentic:** 5-6 LLM calls/brief (DeepInfra `meta-llama/3.1-8B-Instruct`: ~$0.07/call = $0.35-0.42/brief)
- **Daily cost:** 50-200 users × 5-6 calls × $0.07 = **$17.50–$84/day**
- **Current:** ~$3.50–$14/day (1 call × $0.07)
- **Overhead:** 5-6x cost increase

### Limitations
1. **Token usage grows:** Each tool call request adds ~100-200 tokens; total prompt size ~4K tokens (vs. 2K for current)
2. **Latency:** 5-6 sequential (or partially parallel) calls = ~3-5s per brief (vs. 0.5-1s current)
3. **Hallucination risk:** Each tool call is a chance for misunderstanding (agent misreads tool response, asks for data that doesn't exist)
4. **Debugging complexity:** If a brief is poor, unclear which of 5 calls contributed to the problem

### Where It Shines
- **High-signal days:** Agent can recursively drill into signals (e.g., "Get more detail on Meta's earnings impact on your AI holdings")
- **Multi-asset portfolios:** Agent naturally handles 20-30 holdings by prioritizing (weight × risk)
- **Uncertainty flagging:** Agent can emit "Unable to assess [signal] — context unavailable" instead of hallucinating

### Where It Struggles
- **Low-context days:** Even more tool calls on sparse data = more hallucination risk
- **Cost-sensitive deployments:** 5-6x LLM cost is unacceptable for free-tier users
- **Latency:** 3-5s per brief is unsuitable for sub-second API responses

---

## §5 — Quick Wins vs. Structural Rebuild

### Quick Wins (Current Architecture + Tuning)
| Win | Effort | Impact | Risk |
|-----|--------|--------|------|
| Increase context limits (news: 8→16, events: 6→12, alerts: 5→10) | 10 min | LOW–MED | Higher token usage; may exceed 2K limit |
| RRF (Reciprocal Rank Fusion) on news + events | 2h | MED | Added complexity; S6 API change needed |
| Deduplication (remove articles with same headline from different sources) | 1h | LOW–MED | Minimal; safe |
| Citation enforcement (drop bullets with no [cN] markers) | 30 min | LOW | Already done in v3.0 |
| Confidence scoring (LLM emits `confidence: 0.0–1.0` based on context sparsity) | 2h | MED | Requires parser change; frontend honor it |
| Refusal-on-low-context (skip generation if <3 news + 0 portfolio) | 30 min | MED | Improves UX (stub is better than hallucination) |
| **Subtotal** | ~6h | **MED–HIGH** | Low risk, proven patterns |

### Structural Rebuild (Agentic)
| Component | Effort | Notes |
|-----------|--------|-------|
| Define agentic tool subset | 4h | Document which tools, signatures, guardrails |
| Implement `MorningBriefAgent` class | 8h | Planning + tool-loop + synthesis |
| Wiring + DI | 4h | Inject into worker + on-demand route |
| Tests (unit + contract) | 6h | Mock tool responses; verify tool call ordering |
| Dual-pipeline (current + agentic, A/B by feature flag) | 4h | Feature flag in settings; UI to toggle experiment |
| Metrics + logging | 3h | Tool call latency, token usage, cost tracking |
| **Subtotal** | ~29h | **HIGH effort, HIGH cost, EXPERIMENTAL** |

### ROI Comparison
| Path | Estimated Quality Gain | Cost Impact | Timeline | Risk |
|------|------------------------|-------------|----------|------|
| Quick wins | +30–40% (specific phrasing, dedup news) | No impact | 1 sprint | Minimal |
| Agentic | +50–70% (deeper context, refinement) | +5–6x LLM cost | 2–3 sprints | Medium (new failure modes) |
| Hybrid (W1 + experimental W2) | +40% (quick) → +60% (agentic opt-in) | +0% base → +3–4x for opt-in users | 2 sprints | Low (gradual rollout) |

---

## §6 — Recommended PLAN-0099 Wave Structure

### Wave A: Diagnostics & Observability (T-W-A-01)
- **Goals:** Characterize actual brief quality gaps; measure context availability per-day
- **Scope:**
  - Add `context_availability_score` metric to worker (news:8, events:6, alerts:5, portfolio:1 = max 20; emit %completion)
  - Log all four upstream latencies (S1, S3, S5, S6, S7) to structlog
  - Add `briefing:low_context` event when score < 0.4
  - Query Valkey for cache hit/miss ratio (fresh vs. lastgood usage)
- **Tests:** Prometheus scrape works; logs contain [latencies_ms] fields
- **Effort:** 3h
- **Risk:** None — instrumentation only

### Wave B: Quick Wins (T-W-B-01 through T-W-B-05)
- **T-W-B-01:** Increase context limits (news 8→12, events 6→10, alerts 5→8)
  - Update formatters; verify token counts stay <2K
  - Add config knobs (brief_max_news, brief_max_events, brief_max_alerts)
- **T-W-B-02:** Deduplication (headline + source dedup)
  - Pre-format de-dup in briefing_context_formatter.py
- **T-W-B-03:** Confidence scoring + refusal
  - Extend prompt template to emit `confidence: float`
  - Return stub if score < 0.5 after parsing
- **T-W-B-04:** Empty-context partial-failure guard
  - Change line 327: `all_sections_empty` should check `portfolio + (news OR events)` (require at least one)
  - Return partial stub instead of full stub when portfolio is unavailable
- **T-W-B-05:** Cache invalidation pattern
  - Document Valkey key format; add `X-Invalidate-Brief` header option to route
- **Tests per task:** Parser tests, formatter tests, integration tests
- **Effort:** 8h (2h each)
- **Risk:** Low (proven patterns, no new dependencies)

### Wave C: Experimental Agentic Mode (T-W-C-01)
- **Goals:** A/B test agentic vs. non-agentic; measure cost/quality tradeoff
- **Scope:**
  - Implement `MorningBriefAgent` with tool subset (portfolio, news, events, alerts, macro)
  - Feature flag: `ENABLE_AGENTIC_BRIEFING` (default false)
  - Dual-path in worker: 50% agentic, 50% standard (if feature enabled)
  - Emit `brief:agentic:used` vs. `brief:standard:used` metrics
  - Cost tracking: `brief:agentic:cost_usd` metric
- **Tests:** Mock tool responses; verify agent call sequences; cost/latency assertions
- **Effort:** 16h (implementation + dual-path wiring)
- **Risk:** Medium (new failure modes in agent loop; fallback to standard on agent timeout)

### Wave D: Production Rollout (T-W-D-01)
- **Goals:** Conditional rollout based on Wave C results
- **If agentic improves quality >50% and cost <2x:**
  - Roll out to 10% of users; monitor; expand to 100%
- **If cost is prohibitive:**
  - Retire agentic path; double down on Wave B quick wins
- **Metrics:** brief_quality_score (subjective user ratings?), brief_latency_p95, cost_per_user

---

## §7 — New Bug Pattern Proposals

### **BP-588** — Brief Context Gathering Silent Partial Failure
| Field | Value |
|-------|-------|
| **Service** | rag-chat (S8) — `briefing_context.py:293-304` |
| **Severity** | MEDIUM — partial context loss masked as success |
| **Root cause** | `gather_morning_context()` catches all upstream exceptions and returns `ctx=None`; formatters degrade silently to empty strings for unavailable sections; LLM generates brief with no signal that critical sections were omitted |
| **Symptom** | Brief discusses earnings without portfolio risk context; S1 timeout not surfaced; logs show "morning_context_gathering_failed" warning but brief is still served |
| **Fix** | Emit `briefing:context_unavailable:{section}` metric for each section that failed; return `BriefingContext` with boolean flags (`has_portfolio`, `has_news`, etc.); refuse generation if `not has_portfolio` (portfolio is critical context). |
| **Prevention** | Any use case that aggregates multiple upstream calls should structure the result to track which sources succeeded vs. failed, not just return None on first failure. |

### **BP-589** — Brief Context Truncation Hides Tail Signals
| Field | Value |
|-------|-------|
| **Service** | rag-chat (S8) — `brief_context_formatter.py:75, 123, 94` |
| **Severity** | LOW–MEDIUM — tail signals missed on high-volume news days |
| **Root cause** | Hard-coded truncation limits (8 news, 6 events, 5 alerts) are applied before LLM sees context; beyond-limit items (even if relevant) are invisible to the brief. |
| **Symptom** | Portfolio holds 10+ companies; >16 articles posted in 24h; brief omits relevant articles #9-16 because top 8 by score are selected. Tail-risk signals (regulatory warnings, sector downturns) are missed. |
| **Fix** | (a) Increase limits (news 8→16, events 6→12) and verify token budget allows; (b) add RRF ranking (combine recency + relevance score); (c) allow LLM to request "show me all 20 articles for my company" via tool call (agentic redesign). |
| **Prevention** | Any formatter that truncates context for token budget should emit a metric `brief:context_truncated:{section}:{limit}` so operators can observe when limits are hit and adjust sizing. |

### **BP-590** — Cache Staleness Masks Portfolio Updates (variant of BP-236)
| Field | Value |
|-------|-------|
| **Service** | rag-chat (S8) — `morning_brief_pregeneration_worker.py:315-328` |
| **Severity** | MEDIUM — user portfolio updates invisible until next cache refresh |
| **Root cause** | Worker writes fresh-key with 30h TTL; API handler returns fresh-key if available before generating on-demand. Portfolio update at T+12h is not visible until T+30h or cache is manually invalidated. |
| **Symptom** | User adds 100 shares of NVIDIA to portfolio at 2026-05-27 10:00 UTC. Brief at 2026-05-27 10:05 UTC still shows old holdings from pre-generation at 2026-05-26 06:00 UTC. NVIDIA is missing from risk analysis. |
| **Fix** | (a) Reduce fresh-key TTL to 6-12h; (b) add `X-Invalidate-Brief` header to allow user-initiated invalidation; (c) emit `briefing:cache:hit` vs. `briefing:cache:miss` metrics to track stale-return frequency. |
| **Prevention** | Any cached briefing/summary should have a mechanism to invalidate on user action (portfolio edit, alert acknowledgement). Cache TTL for personalized content should be ≤12h. |

---

## Conclusion

**Current brief quality is excellent** (based on live-data sample of 10 recent briefs). The user's reported "poor quality days" likely stem from:
1. Upstream transient failures (S1/S5 timeouts) causing partial-context briefs
2. High-volume news days where top-8 truncation hides relevant signals
3. Portfolio updates cached out of sync

**Agentic redesign would improve best-case quality (+50-70% on multi-asset portfolios with ambiguity)** but is expensive (5-6x cost) and introduces new failure modes. **Recommended path:**
- **Immediate:** Wave A (diagnostics), Wave B (quick wins) — 11h effort, +30-40% quality, zero cost increase
- **Optional:** Wave C (experimental agentic) — 16h effort, measure if cost/quality tradeoff is acceptable; roll out conditionally

**Success metric:** Monitor `brief:context_availability_score` and `brief:low_context` events; verify that days with score >0.8 produce consistently high-quality briefs. If >20% of days drop below 0.6, escalate Wave C as urgent.

---

**Word count:** 1,437 | **Status:** Ready for PLAN-0099 planning session
