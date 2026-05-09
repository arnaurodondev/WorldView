# Audit R4 — Brief Intelligence (PLAN-0087, VA-8)

- **Auditor**: R4 audit subagent (PRD-0087 §6.2, T-B-R4)
- **Surfaces**: A2 (dashboard morning brief) + A4 (instrument News tab → instrument brief)
- **Plans covered**: PLAN-0066 (Brief Intelligence + Temporal RAG) + PLAN-0062-W4 (BriefBullet schema)
- **Time spent**: ~75 min
- **Live stack**: 56 containers healthy, dev-login JWT used (`sub=01900000-0000-7000-8000-000000000010`).
- **Severity legend**: HF-* = hard fail (block demo); SF-* = soft fail; INFO = informational.

> **Headline**: morning brief works *intermittently* — when news ingestion has fresh, well-scored articles in the last 24h. When the pipeline lags or all `display_relevance_score = 0.0`, the API silently returns a placeholder ("Portfolio data is being synchronized with upstream services…") and caches it for 24 h. Fresh briefs render acceptably via `StructuredBrief`, but several quality defects leak through (raw `[relationships_context]` placeholder, irrelevant clickbait citation, `lead`/`summary` parser failures on instrument briefs, brief archive permanently empty by construction, portfolio-context proxy 401, `/api/v1/instruments/symbol/AAPL` 404 inside the gatherer).

---

## 1. Morning Brief

### 1.1 Cached "synchronizing" placeholder (HF-8 candidate / HF-4)

The very first call returned an instant (`time=0.024 s`) placeholder cached for 24 h:

```json
{
  "narrative": "Portfolio data is being synchronized with upstream services. Your morning briefing will be available shortly — please refresh in a few minutes.",
  "risk_summary": {"concentration_score": 0.0, "sector_breakdown": {}},
  "citations": [],
  "sections": [],
  "summary": null,
  "lead": null,
  "confidence": 1.0,
  "cached": true
}
```

Root cause (verified via code + logs):
1. `BriefingContextGatherer.gather_morning_context()` calls `_fetch_top_news` with `min_display_score=0.15`
   — `services/rag-chat/src/rag_chat/application/use_cases/briefing_context.py:356`.
2. The S6 article ingestion lag pushed `display_relevance_score` to `0.0` for every article in the last 24 h
   (verified: `GET /v1/news/top?hours=24&min_display_score=0.15` returned `count=0`).
3. Portfolio context call to S1 returned **401** (`upstream_http_error path=/internal/v1/users/{id}/portfolio/context status=401`),
   so portfolio is empty.
4. Alerts are empty (demo user has no alerts), events empty (no resolvable entity_ids), quotes empty (no instruments).
5. `generate_briefing.py:881-895` sets `all_sections_empty=True` → returns the placeholder string and **caches it for 24 h**
   (`briefing:morning:v2:{user_id}` TTL=86400). The route stores `cached=False` initially but the same content is read back as `cached=True`.

The placeholder is **not gibberish** but it is HF-4 territory: a tile that says "please refresh in a few minutes" is a stuck loading state. The director will see this on a cold dashboard if the pipeline lag aligns with his demo window.

### 1.2 Fresh-generation morning brief (after deleting the cache)

After `valkey-cli del briefing:morning:v2:01900000-...` and waiting for fresher news ingest:

```http
GET /v1/briefings/morning  → HTTP 200, time=12.4 s
```

Render grade: **WARN** (not HF, but not Bloomberg-grade).

```json
{
  "narrative": "### Corporate Developments\n- Intel (INTC) rose 16.0% ... [c1]\n- The deal underscores Intel's renewed role in advanced semiconductor manufacturing [c1][c4]\n- Apple's partnership with Intel highlights strategic diversification in chip supply chain [c6]\n\n### Market Implications\n- Intel's foundry prospects gain credibility despite ongoing execution risks [c4][c1]\n- MP Materials also benefited from an Apple-related supply deal, signaling supplier momentum [c5]\n\n### Company Performance\n- Apple Inc. (NASDAQ:AAPL) demonstrates strong financial health with 83% ROIC [c2]",
  "summary": "Intel (INTC) surged 16.0% following news of a preliminary chip manufacturing pact with Apple, marking a pivotal shift in its foundry ambitions .",
  "lead": "Intel (INTC) surged 16.0% following news of a preliminary chip manufacturing pact with Apple, marking a pivotal shift in its foundry ambitions [c1][c6].",
  "sections": [
    {"title": "Corporate Developments", "bullets": [{"text": "Intel (INTC) rose 16.0% ...", "citations": [...]}]},
    {"title": "Market Implications", ...},
    {"title": "Company Performance", ...}
  ],
  "citations": [<6 article objects with document_id, url, title, snippet>],
  "confidence": 1.0
}
```

**Good**:
- `sections` are well-formed `BriefBullet` objects (text + citation list).
- `[cN]` markers stripped from `bullet.text` (only present in lead, where `LeadProse` strips them client-side via `.replace(/\[c\d+\]/g, "")`).
- 6 article citations all resolve to real `documents` rows (see §1.3).
- `confidence=1.0`, `lead` populated, `summary` populated.

**Defects**:
- `narrative` field still contains raw `[c1][c4][c5][c6]` markers. The dashboard `MorningBriefCard` only rendered narrative directly when `sections.length === 0` (legacy fallback) — but the field is *also* used in the `linkifyEntities` flow. Less risky than instrument brief's `narrative` path, but a future cache-fallback render would expose `[cN]` to the user.
- `summary` ends with a stray space-period (`"...foundry ambitions ."`). Trailing-space polish bug.
- Citation **`019e0dbb-a9b6-7eca-a2d3-addc133b15ef` = "$5,000 Monthly Passive Income For Financial Freedom"** appears in `citations` but is never referenced in any `[cN]` marker in the bullets. The brief retrieved an irrelevant clickbait article into the context window — survives because `display_relevance_score` was high. Director-facing risk: a citation chip linking to clickbait is a quality stain.
- The brief never names the demo user's holdings (because portfolio fetch 401'd) — the entire brief is "what's hot in news" rather than "what's relevant to your portfolio". Defensible (no holdings exist on the demo user) but worth flagging.

### 1.3 Citation walk

All 6 `document_id`s resolve in `content_store_db.documents`:

| document_id | published_at | source | title | resolves? |
|-------------|--------------|--------|-------|-----------|
| 019e0dbb-a98c-... | 2026-05-09 05:17 | finnhub | Intel (INTC) Is Up 16.0% After Securing Preliminary Apple Chip Manufacturing Pact | YES |
| 019e0dbb-a9e3-... | 2026-05-09 10:00 | finnhub | Apple Inc. (NASDAQ:AAPL) Shines in Caviar Cruise … 83% ROIC | YES |
| 019e0dbb-a9b6-... | 2026-05-09 08:15 | finnhub | $5,000 Monthly Passive Income For Financial Freedom | YES (but unrelated) |
| 019e0dbb-be10-... | 2026-05-08 22:10 | finnhub | Intel Apple Chip Deal Puts Foundry Ambitions And Risks In Focus | YES |
| 019e0dbb-aa4b-... | 2026-05-09 10:13 | finnhub | MP Materials Apple Deal Recasts Rare Earth Miner | YES |
| 019e0dbb-ba1f-... | 2026-05-08 21:39 | finnhub | Apple reaches chipmaking deal with Intel, pushing its stock to new record | YES |

**Temporal RAG**: every cited article was published within the last 24 h ✓ (PLAN-0066 W2 date_filter behaving correctly here).

URL field on each citation is a `https://finnhub.io/api/news?id=...` href — these resolve to the upstream Finnhub raw-article API, not a publisher landing page. Click-through opens a JSON blob, not the article. **A6 quality bar requires "click opens article in side panel or new tab"** — finnhub.io API URLs do not satisfy this.

### 1.4 Brief history archive — permanently empty

`GET /v1/briefings/morning/history` returns `{"items":[],"total":0}` even after a successful fresh generation. `user_briefs` row count stays at 0.

Root cause (verified): `_wire_briefing_uc()` in `services/rag-chat/src/rag_chat/app.py:506-541` constructs `GenerateBriefingUseCase` *without* passing `brief_archive`. The constructor (`generate_briefing.py:618-631`) defaults `brief_archive` to a `NullBriefArchive()` whose `.save()` is a silent no-op. The `BriefArchiveReadAdapter` instance is built and wired into `ToolExecutorFactory` (`app.py:455, 479`) but NOT into the briefing use case.

**Effect**:
- `GET /v1/briefings/morning/history` always empty → "history" tab in dashboard is dead.
- `GET /v1/briefings/morning/diff` always returns `"no_diff_available"` → `BriefDiffBadge` never lights up.
- `POST /v1/briefings/feedback/brief` and `/bullet` will succeed only when `brief.id != null`, but `id` is also tied to persistence — never returned to the frontend (response has `"id": null` even on fresh gen). PLAN-0066 Wave F feedback features are functionally dark.

This is HF on the demo path because PLAN-0066 was a top-level plan and the entire Wave B/C/F surface is non-functional.

---

## 2. Per-instrument briefs (5 entities)

| Entity | endpoint status | length (chars) | citations | render quality | notes |
|--------|------------------|----------------|-----------|----------------|-------|
| AAPL `11111111-0001-7000-8000-000000000001` | HTTP 200, ~24 s first / ~9 s warm | 1,290 narrative + 2 sections | 4 | **WARN** | `[relationships_context]` placeholder leaks into bullet text (HF-8); `Not available in retrieved context` boilerplate left in narrative; `_fetch_top_news` 0.15 floor caused initial cache miss |
| MSFT `11111111-0002-7000-8000-000000000001` | HTTP 200, ~9 s | 1,440 | 0 (cached pre-fix) | **FAIL (cached)** | Cached version had string-bullet sections, lead=null, summary=null, citations=[] — see §2.1 |
| NVDA `11111111-0003-7000-8000-000000000001` | HTTP 200, ~16 s | 990 | 0 (cached pre-fix) | **FAIL (cached)** | Same as MSFT |
| META `11111111-0007-7000-8000-000000000001` | HTTP 200, ~16 s | 1,150 | 0 (cached pre-fix) | **FAIL (cached)** | Same as MSFT |
| OPENAI | n/a | n/a | n/a | n/a | **No `OpenAI` row in `canonical_entities` (307 total)** — instrument brief returns 404. Dashboard "search Apple → AAPL" works but director typing "OpenAI" will hit a dead end. |

### 2.1 The "cached pre-fix" instrument briefs — string bullets + parser failure

For MSFT/NVDA/META, the first call returned cached responses generated when the live pipeline state had fewer relevant news articles. Sections in those responses are **strings** not `BriefBullet` objects:

```json
{
  "title": "Entity Overview",
  "bullets": [
    "Microsoft Corporation operates as a financial instrument under ticker MSFT [c1]",
    "Primary thematic exposure includes artificial intelligence at 95% confidence [c2]",
    ...
  ]
}
```

Front-end type contract says `bullets: BriefBullet[]` (`apps/worldview-web/types/api.ts:1449-1453`). Renderer reads `bullet.text` (`StructuredBrief.tsx:484`) — on a plain string, `bullet.text` is `undefined` → empty `<li>` rendered. Combined with raw `[c0][c1][c2]` text and "Not available in retrieved context [c0]" boilerplate filling the bullets, the **expanded view of an instrument brief shows blank bullets and `[cN]` markers**.

Root cause: `execute_public_instrument()` at `generate_briefing.py:1118-1119`:

```python
if not sections:
    sections = _parse_sections_from_markdown(content)  # legacy: list[dict] with string bullets
```

When `_parse_sections_with_citations` + `_backfill_uncited_bullets` strip every bullet (because the LLM emitted `[c0]` which is out-of-range, or no in-range citations attached), the use case falls back to the legacy parser that produces string bullets. The cached response then violates the API contract and HF-8 fires (raw `[cN]` survives in `bullet.text`).

### 2.2 Fresh AAPL instrument brief — `[relationships_context]` placeholder leak

After `valkey-cli del briefing:instrument:v2:11111111-0001-7000-8000-000000000001:...`, AAPL re-generated cleanly (proper `BriefBullet` objects, lead+summary populated, 4 citations). However the LLM produced bullet text:

```
"The firm operates in the technology sector with significant exposure to artificial intelligence themes [relationships_context]"
"Apple competes directly with Microsoft Corporation in multiple product segments [relationships_context]"
"Apple is exposed to the artificial intelligence thematic investment trend with high confidence [relationships_context]"
"Apple has a supplier relationship with an unnamed entity at 75% confidence level [relationships_context]"
```

The literal placeholder `[relationships_context]` (a Jinja-style template variable name from the prompt) leaks into `bullet.text` because:

1. `_parse_detail_sections_with_citations` strips only `[c\d+]` markers via `_CN_CITATION_RE` — it does not strip non-numeric bracketed tokens.
2. The `INSTRUMENT_BRIEFING` prompt template references `{{relationships_context}}` and the LLM is mis-quoting the variable name as a citation marker.

This is HF-8 territory: the user sees `[relationships_context]` rendered as plain text inside the structured bullets on the instrument-page News tab. AAPL also still has "Not available in retrieved context" boilerplate in `narrative` (but not in `sections`, so `StructuredBrief` hides it).

### 2.3 Confidence scores on instrument briefs are inconsistent

- AAPL fresh: `confidence=0.625` (computed by `_compute_confidence`).
- MSFT/NVDA/META (cached pre-fix): `confidence=0.0` — would render `<ConfidenceIndicator>` "Low confidence" badge, which is at least honest.

The fix to `bullets: BriefBullet[]` will surface confidence scores to the front-end correctly; until then the badge is suppressed because the cached path doesn't carry the field.

---

## 3. Empty-context behaviour

**Cold/unknown entity → graceful 404** ✓:

```http
GET /v1/briefings/instrument/00000000-0000-0000-0000-000000000000
→ 404 {"detail":"[ENTITY_NOT_FOUND] Entity ... not found in knowledge graph"}

GET /v1/briefings/instrument/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee
→ 404 {"detail":"[ENTITY_NOT_FOUND] Entity ... not found in knowledge graph"}
```

The error string contains a square-bracketed code (`[ENTITY_NOT_FOUND]`) that the frontend currently surfaces verbatim. Acceptable — "Entity not found" is honest and not a stack trace.

**Cold morning brief (no portfolio, no news, no alerts, no events)** → §1.1 placeholder. Honest copy ("being synchronized") but caches for 24 h, so the dashboard is locked to that string for the rest of the demo day if the pipeline lag persists.

**OpenAI cold-start**: not in `canonical_entities` (only 307 total entities seeded). Director-typed "OpenAI" → instrument page 404 → cold-start risk flagged in PRD-0087 §13. PLAN-0087-C is the candidate fix.

---

## 4. Other findings (non-brief, surfaced during audit)

- **Internal JWT propagation broken to S1**: 7+ recent `/internal/v1/users/{id}/portfolio/context status=401` log lines. Brief context-gatherer's portfolio fetch is permanently degraded — `portfolio_failed=True` for every demo-user request. The S1 portfolio context endpoint exists but the rag-chat → S1 internal-JWT chain returns 401. Distinct from Auth Foundation; affects A2 portfolio tile + briefs.
- **`/api/v1/instruments/symbol/AAPL` returns 404** inside the brief context-gatherer (`status=404 path=/api/v1/instruments/symbol/AAPL`). Likely the ticker→instrument resolver in S3 was renamed but the gatherer client wasn't updated. Quote/fundamentals fetches in instrument briefs silently fall back to empty.
- **API base path inconsistency**: openapi-served paths use `/v1/...`; many internal docs/routes use `/api/v1/...`. The S9 gateway proxies `GET /v1/briefings/morning` to S8 `GET /api/v1/briefings/morning` (verified). User-facing paths must be `/v1/...` (the `/api/v1/...` returned 404 in my first attempt).

---

## 5. Defect rows (PRD §11.1)

```yaml
- id: D-R4-001
  va: VA-8
  surface: A2
  severity: HF-8
  status: open
  agent: R4
  found_at: 2026-05-09T17:20Z
  reproduce: |
    1. Cold dashboard, no recent fresh news with display_relevance_score >= 0.15
    2. GET /v1/briefings/morning
    3. Response: 24-h-cached "Portfolio data is being synchronized..." placeholder
       with sections=[], summary=null, lead=null
  evidence:
    - log: morning_briefing_empty_context (rag-chat container, request 01KR6VM55...)
    - cache_key: briefing:morning:v2:01900000-0000-7000-8000-000000000010 (TTL=86400)
    - news_top_filter: GET /v1/news/top?hours=24&min_display_score=0.15 → count=0
  root_cause: |
    BriefingContextGatherer._fetch_top_news (briefing_context.py:343-359) hard-codes
    min_display_score=0.15. When the pipeline produces articles with display_relevance_score=0.0
    (current state for older 13F/Walmart articles), every news article is filtered out.
    Combined with portfolio fetch returning 401 (D-R4-005), all four context sources are
    empty → generate_briefing.py:881-895 returns the placeholder, route caches it for 24 h.
  fix_decision: spawn-subagent
  spawned_plan: PLAN-0087-F (already pre-flagged; expand scope)

- id: D-R4-002
  va: VA-8
  surface: A2 / A4-news
  severity: HF-8
  status: open
  agent: R4
  found_at: 2026-05-09T17:25Z
  reproduce: |
    1. valkey-cli del briefing:instrument:v2:11111111-0001-7000-8000-000000000001:01900000-...
    2. GET /v1/briefings/instrument/11111111-0001-7000-8000-000000000001
    3. Inspect .sections[0].bullets[1].text
  evidence:
    - response: bullet.text contains literal "[relationships_context]" (4 occurrences for AAPL)
    - file: services/rag-chat/src/rag_chat/application/use_cases/generate_briefing.py:319-395
      (_parse_sections_with_citations only strips _CN_CITATION_RE = r"\[c(\d+)\]")
  root_cause: |
    INSTRUMENT_BRIEFING prompt uses {{relationships_context}} as a Jinja variable;
    the LLM occasionally echoes the variable name as a bracketed marker, which the
    citation-stripper does not match (matches only digits). Bullet text leaks the
    literal placeholder to MorningBriefCard / instrument News tab.
  fix_decision: fix-now
  fix_owner: rag-chat agent
  estimated_effort: 1h (extend cleanup regex + prompt-side directive + targeted test)

- id: D-R4-003
  va: VA-8
  surface: A4-news
  severity: HF-8
  status: open
  agent: R4
  found_at: 2026-05-09T17:00Z
  reproduce: |
    1. GET /v1/briefings/instrument/11111111-0002-7000-8000-000000000001 (MSFT cached)
    2. typeof .sections[0].bullets[0] === "string"
  evidence:
    - response: sections[*].bullets are PLAIN STRINGS (e.g. "MSFT operates as ... [c1]")
    - file: generate_briefing.py:1118-1119 (legacy fallback: _parse_sections_from_markdown)
    - file: apps/worldview-web/types/api.ts:1449-1453 (frontend declares bullets: BriefBullet[])
    - render: StructuredBrief.tsx:484 reads bullet.text → undefined on string bullet
  root_cause: |
    When _parse_sections_with_citations + _backfill_uncited_bullets drop every bullet
    (out-of-range [c0] markers in LLM output, or no successful citation match), the
    fallback parser returns list[dict] with string bullets. Sections-shape API contract
    is violated; frontend renderer prints empty <li> + raw "[cN]" markers because
    bullet.text is undefined. HF-8 trigger.
  fix_decision: fix-now
  fix_owner: rag-chat agent
  estimated_effort: 2h (legacy fallback must construct BriefBullet objects with at
    least one fallback citation, OR drop the section entirely; targeted regression test
    on instrument brief for AAPL/MSFT/NVDA)

- id: D-R4-004
  va: VA-8
  surface: A2
  severity: HF-3 (CRITICAL — the entire PLAN-0066 history/diff/feedback feature is dark)
  status: open
  agent: R4
  found_at: 2026-05-09T17:21Z
  reproduce: |
    1. Trigger fresh morning brief (delete cache + GET)
    2. SELECT count(*) FROM rag_db.user_briefs;  → 0
    3. GET /v1/briefings/morning/history → {"items":[], "total":0}
    4. GET /v1/briefings/morning/diff → "no_diff_available"
    5. Response.id always null
  evidence:
    - file: services/rag-chat/src/rag_chat/app.py:506-541 (_wire_briefing_uc does NOT
      pass brief_archive to GenerateBriefingUseCase)
    - file: generate_briefing.py:618-631 (constructor defaults to NullBriefArchive())
    - file: brief_archive.py:130-167 (NullBriefArchive.save is silent no-op)
    - log: zero brief_persist_failed lines after 5+ successful generations
  root_cause: |
    BriefArchiveReadAdapter is built (app.py:455) and wired into ToolExecutorFactory
    only (app.py:479). _wire_briefing_uc never passes it to GenerateBriefingUseCase,
    which silently falls back to NullBriefArchive — no row is ever written to user_briefs.
    PLAN-0066 Wave B/C/F (history, diff, feedback, brief_id) is functionally dead.
  fix_decision: fix-now
  fix_owner: rag-chat agent
  estimated_effort: 1h (pass brief_archive to _wire_briefing_uc, add startup test that
    POST→DB row count increments by 1)

- id: D-R4-005
  va: VA-8 (overlaps VA-6, VA-11)
  surface: A2
  severity: SF-3
  status: open
  agent: R4
  found_at: 2026-05-09T17:18Z
  reproduce: |
    1. Trigger fresh morning brief
    2. docker logs worldview-rag-chat-1 | grep portfolio/context
  evidence:
    - log: 7+ "upstream_http_error path=/internal/v1/users/{user_id}/portfolio/context
      status=401" entries during morning-brief request lifecycle
    - file: rag-chat S1Client.get_portfolio_context (s1_client.py:51-89)
  root_cause: |
    rag-chat → S1 internal-JWT propagation (auth_context.py ContextVar pattern from PRD-0025)
    is failing for the briefing path — S1 InternalJWTMiddleware rejects the request as 401.
    Likely a missing X-Internal-JWT injection on the briefing-use-case S1Client (different
    instance from the orchestrator's S1Client; constructed inside _wire_briefing_uc).
  fix_decision: fix-now (root-cause auth chain; do NOT mask)
  fix_owner: backend agent (overlaps D-R4-006)
  estimated_effort: 2h

- id: D-R4-006
  va: VA-8
  surface: A4-news (instrument brief context)
  severity: SF-3
  status: open
  agent: R4
  found_at: 2026-05-09T17:20Z
  reproduce: |
    1. Trigger fresh AAPL instrument brief
    2. docker logs worldview-rag-chat-1 | grep instruments/symbol
  evidence:
    - log: "upstream_http_error path=/api/v1/instruments/symbol/AAPL status=404"
  root_cause: |
    BriefingContextGatherer._s3.find_instrument_by_ticker hits an S3/market-data route
    that returns 404 even for known tickers — likely path renamed (suspect PLAN-0070
    BFF reorg) or S9 proxy missing. Result: instrument brief gets no quote/fundamentals.
  fix_decision: fix-now
  fix_owner: backend agent
  estimated_effort: 1h

- id: D-R4-007
  va: VA-8
  surface: A2
  severity: SF-1
  status: open
  agent: R4
  found_at: 2026-05-09T17:19Z
  reproduce: |
    1. Fresh morning brief
    2. .citations[].title contains "$5,000 Monthly Passive Income For Financial Freedom"
       even though the brief is about Apple/Intel/MP Materials
  evidence:
    - file: morning brief response /tmp/morning.json (citation document_id 019e0dbb-a9b6-7eca-...)
    - article_id: 019e0dbb-a9b6-7eca-a2d3-addc133b15ef in content_store_db.documents
  root_cause: |
    The /v1/news/top endpoint returned a high-score clickbait article that the
    BriefingContextGatherer included in context. The LLM correctly omitted it from
    bullet citations, but it surfaces in the citations[] array (and would appear as a
    "Top Stories" chip on the dashboard). Either the relevance scorer over-rates
    clickbait-style passive-income content, or the /top endpoint lacks a quality gate.
  fix_decision: defer (post-demo); record in news-quality follow-up
  estimated_effort: post-demo

- id: D-R4-008
  va: VA-8
  surface: A2 / A4-news
  severity: SF-1
  status: open
  agent: R4
  found_at: 2026-05-09T17:19Z
  reproduce: |
    1. Fresh morning brief; click any "Top Stories" chip
    2. URL is "https://finnhub.io/api/news?id=..." → JSON blob, not article
  evidence:
    - file: morning brief .citations[].url
    - PRD-0087 §3.3 quality bar: "click opens article in side panel or new tab"
  root_cause: |
    Citation URLs are the upstream Finnhub news API URL (raw JSON), not the publisher
    landing-page URL. Either S6 ingestion is storing the API URL instead of the
    canonical article URL, or the brief response is exposing the wrong URL field.
  fix_decision: fix-now (HF-3 risk if director clicks)
  fix_owner: data-platform agent
  estimated_effort: 2h (audit document.url provenance + content_store_db schema)

- id: D-R4-009
  va: VA-8
  surface: A2
  severity: SF-1
  status: open
  agent: R4
  found_at: 2026-05-09T17:19Z
  reproduce: |
    1. Fresh morning brief
    2. .summary string ends with " ." (trailing space + period)
  evidence: |
    "summary": "Intel (INTC) surged 16.0% following news of a preliminary chip
    manufacturing pact with Apple, marking a pivotal shift in its foundry ambitions ."
  root_cause: |
    _split_summary_and_details or the LLM-truncation step inserts a stray space before
    the closing period. Cosmetic but visible on the dashboard collapsed view.
  fix_decision: fix-now
  estimated_effort: 30 min

- id: D-R4-010
  va: VA-8
  surface: A4-news (cold-start)
  severity: SF-4
  status: open
  agent: R4
  found_at: 2026-05-09T17:00Z
  reproduce: |
    1. canonical_entities only seeds 307 entities; OpenAI is NOT among them
    2. SELECT * FROM canonical_entities WHERE canonical_name ILIKE 'OpenAI%' → 0 rows
  evidence:
    - psql output above
  root_cause: |
    Demo path PRD-0087 §2.1 A7 says "Show me the entity graph around OpenAI" — but the
    KG has no OpenAI canonical entity. Pre-flagged in PLAN-0087 §8.4 (PLAN-0087-C
    cold-start enrichment). The instrument-brief 404 path is at least graceful.
  fix_decision: spawn-subagent (PLAN-0087-C)
  estimated_effort: 6-8h
```

---

## 6. Summary table — render-grade per surface

| Surface | Cached state | Fresh state | Verdict |
|---------|--------------|-------------|---------|
| Dashboard `MorningBriefCard` (A2) | **FAIL — placeholder, no sections, no diff badge, no rating** | **WARN — sections OK, lead/summary OK, but `[cN]` in narrative + clickbait citation + ` .` polish bug** | demo-day risk if cache cold |
| Instrument News tab brief (A4) — AAPL | **FAIL (string bullets, raw `[c0]` markers, "Not available" boilerplate)** | **WARN (`[relationships_context]` literal leaks)** | HF-8 in both states |
| Instrument News tab brief (A4) — MSFT/NVDA/META | **FAIL (same as AAPL cached)** | unverified (rate-limited) | HF-8 |
| Instrument News tab brief (A4) — OPENAI | n/a (entity missing) | n/a | A4 cold-start broken |
| Brief history endpoint | empty by construction (NullBriefArchive) | still empty | HF-3 / D-R4-004 |
| Brief diff endpoint | "no_diff_available" forever | same | HF-3 / D-R4-004 |
| Brief feedback (bullet/brief) | unreachable (`brief.id == null`) | same | HF-3 / D-R4-004 |

---

## 7. Recommended fix order (for triage in PRD §7)

1. **D-R4-004** (1 h) — wire `brief_archive` into `_wire_briefing_uc`. Unlocks history, diff, feedback, brief_id. Highest leverage per hour.
2. **D-R4-005** (2 h) — fix internal-JWT propagation on the briefing-use-case S1Client. Restores portfolio context. Reduces D-R4-001 frequency.
3. **D-R4-001** (3-4 h, escalate to PLAN-0087-F) — kill the 24-h placeholder cache + lower `min_display_score` floor or skip news on empty rather than bailing the whole brief.
4. **D-R4-002** (1 h) — extend the citation-stripping regex to `\[[a-z_]+\]` and add a prompt-side guard "do not echo template variable names". Add a regression test that asserts `bullet.text` contains no bracketed tokens.
5. **D-R4-003** (2 h) — make the legacy fallback construct `BriefBullet` objects (or drop the section entirely). Add a contract test on the response schema.
6. **D-R4-006** (1 h) — fix `/api/v1/instruments/symbol/{ticker}` 404; restores quote+fundamentals in instrument briefs.
7. **D-R4-008** (2 h) — audit citation URLs so chips link to publisher landing pages, not Finnhub API JSON.
8. **D-R4-009** (30 min) — strip trailing whitespace before period in summary.
9. **D-R4-007** (defer) — relevance-scorer clickbait gate.
10. **D-R4-010** (PLAN-0087-C, 6-8 h) — cold-start KG enrichment for OpenAI etc.

If only D-R4-002 + D-R4-003 + D-R4-004 + D-R4-005 are fixed, the demo-day risk on A2/A4-news drops from "high" to "low".

---

**End of R4 audit.**
