# Live QA — Chat Features End-to-End (5 shipped features)

**Date:** 2026-06-30 (probes ran 2026-07-01 UTC)
**Scope:** READ-ONLY live verification against the running Docker Compose stack (`project=worldview`).
**Driver:** dev-login user JWT → gateway `POST /v1/chat/stream` (real auth chain, S9 signs the internal JWT). A direct rag-chat path (`:8008`, `INTERNAL_JWT_SKIP_VERIFICATION=true`) was also used for upstream isolation.
**Completion model live:** `openai/gpt-oss-120b` (DeepInfra key confirmed working).
**No code, git, or containers were modified.**

---

## Verdict table

| # | Feature | Verdict | Evidence |
|---|---------|---------|----------|
| 1 | News/doc citations carry clickable `url` + `source_name` + `published_at` (empty→null) | **PASS** | `get_entity_news` → 10 items; citations carried real `finnhub.io`/`finance.yahoo.com` URLs, `source_name`, ISO `published_at`. Empty→null normalization implemented (`output_processor.py:224-227`). |
| 2 | KG claim/event citations carry a source-article `url`; aggregates `url=null` | **PASS (with fragility caveat)** | `search_claims` → `items_source_linked: 20` (content-store `/documents/batch` 200 OK); delivered citations carried real source-article URLs (`finance.yahoo.com`, `nasdaq.com`), `source_name="knowledge_graph"`, `published_at`. Aggregates (`traverse_graph`, `search_entity_relations`) correctly `url=null`. CAVEAT: citations frequently vanish (empty array) on KG answers — see BUG-2. |
| 3 | `get_prediction_markets` → Polymarket URLs | **FAIL** | Tool executes but upstream returns **500** whenever a free-text `query` is present (the LLM always supplies the topic). Pre-existing market-data bug — see BUG-1. No markets/citations ever delivered. |
| 4 | `get_filings` → SEC EDGAR URLs | **FAIL** | Tool executes (`ticker=AAPL`) but returns empty. S6 chunk-search `source_types=['sec_edgar']` returns 0 across ann/hybrid/lexical despite 629 public embedded `sec_edgar` chunks — see BUG-3. EDGAR-URL stamping never reached. |
| 5 | F1 incremental token streaming (DeepInfra adapter) + F2 typewriter | **NOT VERIFIED / LIKELY NOT ACTIVE on common path** | Every representative query took the direct-text path (`llm_direct_text_generation` phase). Token events arrived as a single burst (all within ~10-150 ms) regardless of 4-36 s generation time — post-hoc string chunking, not incremental streaming. See BUG-4. |

---

## Bugs found

### BUG-1 (HIGH, pre-existing, market-data) — prediction-market ILIKE query → 500 `InvalidEscapeSequenceError`
**Impact:** Feature 3 fully broken end-to-end. Any prediction-market chat question 500s because the LLM supplies the topic as the free-text `query` param.

**Reproduction (direct market-data, X-Internal-JWT):**
```
GET /api/v1/prediction-markets?limit=3                 → 200 total=526
GET /api/v1/prediction-markets?query=election&limit=3  → 500 internal server error
GET /api/v1/prediction-markets?query=Obama&limit=3     → 500 internal server error
```

**rag-chat log (gateway path):**
```
GET .../v1/signals/prediction-markets?status=open&limit=5&query=2028%20Democratic%20presidential%20nomination&category=politics "HTTP/1.1 500"
tool_result status=transport_error status_code=500 reason=upstream_5xx
```

**market-data traceback:**
```
asyncpg.exceptions.InvalidEscapeSequenceError: invalid escape string
[SQL: ... WHERE ... AND m.question ILIKE $3::VARCHAR ESCAPE '\\' ...]
```

**Root cause:** `services/market-data/src/market_data/infrastructure/db/repositories/prediction_market_repo.py:208`
```python
predicates.append("m.question ILIKE :query_like ESCAPE '\\\\'")
```
Under Postgres `standard_conforming_strings=on` (default), the SQL literal `'\\'` is **two** backslashes, but `ESCAPE` requires exactly one character → invalid escape. Should be a single-char escape (`ESCAPE '\'` / `ESCAPE E'\\'`) or drop the ESCAPE clause. 526 markets (182 politics), slugs fully populated — data is fine; only the `query` code-path is broken.

Note: the rag-chat side is correct — `_build_polymarket_url` slug logic, safe-degradation to `[]`, and honest "data unavailable" answer all behave properly; it just never receives rows.

**QA-probe artifact (not a bug):** hitting rag-chat `:8008` directly with an `alg=none` token yields a false **401** from S9, because `BaseUpstreamClient` forwards the caller's JWT back to S9 as `Authorization: Bearer` and S9 rejects the unsigned token (`middleware.py` requires a valid RS256 gateway-issued JWT). The real gateway path signs a valid internal JWT, so use the gateway path for representative results.

---

### BUG-2 (HIGH, rag-chat) — citations array frequently emptied on KG-claim/event answers
**Impact:** Feature 2's source-article URLs are computed correctly (`items_source_linked: 20`) but often never reach the user. Two mechanisms empty the `citations` array:

1. **`[tool_name row N]` markers stripped** — the model emits `[search_events row 1]` / `[search_entity_relations row 3]` style refs, but citation assembly keys on numeric `[N]` markers → `out_of_range_tool_citation_stripped` → `citations: []`.
2. **numeric-grounding rewrite** — `numeric_grounding_failed` fires (even on qualitative queries), issues a rewrite turn (`grounding_validation` up to **16.5 s**), replaces the streamed answer with `[row N]`-style text + a "some figures or names could not be matched" banner → citations dropped.

**Evidence:**
- "What recent events and claims about NVIDIA…" → both tools ok (20+20), `items_source_linked: 20` each, **`citations: []`**, log `reason=numeric_grounding_failed`.
- "What partnerships…" → `out_of_range_tool_citation_stripped tags=["[search_entity_relations row 3]","[search_entity_relations row 4]"]`, `citations: []`.
- Only when the model happened to emit `[1] [2]` did the KG source-URL citations survive (the Feature-2 PASS run).

This is a cross-cutting reliability defect: KG-grounded answers deliver clickable source URLs only when the model happens to use `[N]` markers.

---

### BUG-3 (HIGH, nlp-pipeline/S6) — `sec_edgar` chunk search returns 0 despite 629 embedded public chunks
**Impact:** Feature 4 fully broken — `get_filings` always returns empty; the EDGAR-URL feature can't be exercised.

**Reproduction (direct S6 `POST /api/v1/search/chunks`, min_score=0):**
```
source_types=['sec_edgar'] search_type=ann     → 0 results
source_types=['sec_edgar'] search_type=hybrid  → 0 results
source_types=['sec_edgar'] search_type=lexical → 0 results
no source filter, ann, min_score=0, top_k=10   → only 4 results (of total_searched=65805), all source_type=None
source_types=['eodhd']                         → 3 results; other buckets → 0
```

**DB confirms the data qualifies** (`nlp_db`, exact ANN WHERE join):
```
chunk_embeddings ready + tenant NULL + sections join + source_type='sec_edgar' → 629
(control: source_type='eodhd' → 4763)
```
So 629 `sec_edgar` chunks satisfy the exact query predicate, yet the endpoint returns 0. The no-filter ANN returning only ~4 of 65 805 rows indicates a **degenerate ANN retrieval / near-zero recall** (candidate set far too small, then source-type post-filtering yields ~nothing for any less-common bucket). The lexical leg also returns 0 for `sec_edgar`. The response's `source_type` field is always `null` even for returned rows (secondary smell).

The `get_filings` handler itself is correct (resolves ticker, pins `sec_edgar`, dedups per doc, stamps EDGAR URL) — it simply never receives rows. This is upstream in S6 chunk search, not the shipped `get_filings` code.

---

### BUG-4 (MEDIUM) — F1 incremental streaming not active on the common agentic path
**Impact:** Server-side incremental token streaming (F1) is not observable for representative queries; tokens arrive as one burst.

**Observation (all runs):** `token` events arrive within ~10-150 ms of each other while `llm_direct_text_generation` took 4-36 s. Status/tool_call/tool_result events DO arrive incrementally (so this is NOT gateway buffering).

**Root cause (`chat_orchestrator.py:2657-2694`):** when the agent's planning turn returns the final answer as direct text (the common flow: tool → model writes prose next iteration), the orchestrator splits the already-generated string via `_chunk_text_for_streaming(direct_text)` and burst-emits each chunk (`emit_delta`, a wire-alias of `emit_token`). The comment itself notes this is "microseconds of string splitting, not generation." The genuinely-incremental path (`llm_synthesis_streaming`, line 3755: `async for chunk in stream_chat(...): emit_token(chunk)`) only runs when the loop exits with no direct text — which none of the representative queries hit.

**Not verified:** F2 (frontend typewriter) is client-side and out of scope for server probes; it would still animate over the burst, but there is no true server-side trickle to animate on this path.

---

### Secondary observations (lower severity)
- **`get_fundamentals_history` AAPL `periods=1` → misleading error.** market-data returns 200, but the only row (latest quarter `2026-06-30`, not yet reported) is dropped as `all_rows_phantom`, and the user sees "I couldn't find a match for 'AAPL'." (Wrong message class — it's a phantom-row drop, not a resolution failure. Same family as BP-626.)
- **Entity resolution mis-scopes non-entities.** "Apple's recent SEC filings" resolved the entity to "U.S. Securities and Exchange Commission"; a prediction-markets query resolved to "The US"; suggestions then reference odd entities (e.g., "C3.ai, Inc."). Cosmetic but visible in `suggestions`/answer.
- **`source_name="news"`** on all news citations (Feature 1) is a generic label, not the actual publisher (finnhub/yahoo). Populated (spec satisfied) but coarse.

---

## What could NOT be verified and why
- **Feature 3 (prediction-market Polymarket URLs):** blocked by BUG-1 (upstream 500); no market rows ever returned, so `citation_meta.url = https://polymarket.com/event/<slug>` could not be observed live. URL-builder logic verified only by code inspection.
- **Feature 4 (EDGAR URLs):** blocked by BUG-3 (S6 returns 0 sec_edgar rows); EDGAR index URL stamping could not be observed live.
- **Feature 5 / F1 (incremental streaming):** the streaming code path (`llm_synthesis_streaming`) exists and emits per-chunk, but no representative query exercised it — all took the direct-text burst path (BUG-4). F2 (client typewriter) not testable from server probes.

## What passed cleanly
- **Feature 1** — news citations with real clickable URLs + source_name + published_at; empty→null normalization present in code.
- **Feature 2 (mechanism)** — content-store batch resolve (`/documents/batch` 200 OK, `items_source_linked: 20/20`) backfills real source-article URLs onto KG claim citations; verified end-to-end in the run where the model used `[N]` markers. Aggregates correctly emit `url=null`.

---

# Round-2 re-verification (2026-07-01, second fix wave: rag-chat + market-data rebuilt)

Same method (dev-login JWT → gateway `POST /v1/chat/stream`, live `openai/gpt-oss-120b`).

## ROUND-1 → NOW summary

| Item | Round-1 | Now | Verdict |
|------|---------|-----|---------|
| P0 news regression | REFUSED (phantom `[commentary]`) | Not refused; streams; citations carry real finnhub/yahoo URLs when model cites | **FIXED ✅** |
| BUG-2 KG citations | empty on `【row N】` markers | NON-EMPTY with source-article URLs; new `tool_row_citations_normalized` | **FIXED ✅** |
| BUG-1 prediction URLs | 0 URLs (500 → entity_grounding refusal) | markets return (ILIKE tokenized), no entity refusal, `https://polymarket.com/event/<slug>` in citations | **FIXED ✅** |
| BUG-3 filings | empty (tool 0 rows) | `get_filings` returns 5-10 rows; EDGAR `sec.gov/Archives/…-index.htm` URLs in citations | **FIXED ✅** |
| BUG-4 streaming | fixed | still incremental (260 tok/5.4 s; 392 tok/7.4 s) | **PASS ✅** |
| Numeric-fabrication guarantee | holds | still fires (`numeric_grounding_failed` on multiple runs) | **PASS ✅** |

## Evidence

### P0 news regression — FIXED
"latest news on NVIDIA": `get_entity_news` ok (10 items), streamed 260 tokens/5.4 s, **not refused** (no `phantom_citation` in 3 runs). With a "with sources" prompt → citations with real URLs: `https://finnhub.io/api/news?id=…`, `source_name="news"`, ISO `published_at`. The benign-`[commentary]`-no-longer-refuses fix works for the news flow.

### BUG-2 KG citations — FIXED
"events and claims about NVIDIA": `search_events` ok (20), `items_source_linked: 20`, log `tool_row_citations_normalized` (CJK/full-width bracket normalization), final `citations` NON-EMPTY — event citation with `https://finnhub.io/api/news?id=…`, `source_name="knowledge_graph"`. `numeric_grounding_failed` still fires but no longer empties the citations (rewrite gating). "What partnerships does Apple have" → 1 `relation` citation, `url=null` (correct — aggregate).

### BUG-1 prediction markets — FIXED (delivers URLs)
Multi-word "2028 presidential nomination" → `get_prediction_markets` `status=ok` item_count=10 (ILIKE tokenization; was 0), **no** `entity_grounding_failed` (entity_name now set). "Polymarket markets about Nikki Haley, cite as [1][2]" → citations carry `https://polymarket.com/event/will-nikki-haley-win-the-2028-republican-presidential-nomination` + `…-2028-us-presidential-election`, `source_name="polymarket"`.

### BUG-3 get_filings — FIXED (delivers EDGAR URLs)
`get_filings(NVDA/AAPL)` now `status=ok` item_count=5-10 (company-name-anchored query, no hard entity_ids filter; was 0). "List NVIDIA's recent SEC filings, cite [1][2] with EDGAR link" → citations carry canonical EDGAR index URLs: `https://www.sec.gov/Archives/edgar/data/1408100/000114036126025340/0001140361-26-025340-index.htm`.

### BUG-4 streaming — still incremental
`llm_synthesis_streaming` path; 260 tokens/5.4 s and 392 tokens/7.4 s (dozens of >50 ms inter-token gaps). No regression.

### Numeric-fabrication guarantee — intact
`numeric_grounding_failed` fired on the events "92 % YoY" figure, on filings date/number claims, and on prediction runs. `numeric_grounding_phantom_citation_refused` still catches fabricated tool citations. Detection was NOT weakened.

## Residual fragility (NOT a regression; cross-cutting, affects all tools)
Citations still depend on the model emitting mappable markers. When the model uses non-standard provenance markers — `[functions.get_prediction_markets row 0]`, `[get_filings row 10]` (out-of-range) — or emits a phantom `[commentary]` citation, the affected citation is stripped or the answer is refused, so URLs intermittently don't reach the wire. This is the same `[N]`-marker-dependency across news/KG/prediction/filings, not specific to any one feature. With normal `[N]` citing (the common case), all four features now deliver their URLs.

## Net result
All four fixes land: BUG-1 (polymarket URLs), BUG-2 (KG source URLs), BUG-3 (EDGAR URLs), the P0 news regression, plus BUG-4 streaming and the numeric-fabrication guarantee. Remaining fragility is the cross-cutting citation-marker normalization gap (non-`[N]` markers / phantom labels), which intermittently drops individual citations. No code/containers/git modified during this pass.
