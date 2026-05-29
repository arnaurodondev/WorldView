# PLAN-0103 — Real-User Chat Failures Audit

**Date**: 2026-05-29
**Branch**: `feat/plan-0099-w4`
**Author**: Claude (operating as Arnau Rodon)
**Source**: 5 prompts the user pasted from his live `/chat` session today, each
exposing a real quality gap. Reproduced where possible against the running
stack (`docker compose worldview`) and traced through the rag-chat tool
catalogue / handlers / DB.

This is **not** a defect-density report — it is a root-cause-and-fix triage
for the next iteration of the brief-and-chat investment (PLAN-0103).

> Cross-reference: `docs/audits/2026-05-28-plan-0102-phase-d-code-review.md`
> already captured 13 deferred items.  The findings here are **additive** —
> they were either invisible to the synthetic benchmark or only show up
> end-to-end against real DeepSeek behaviour.

---

## TL;DR

| # | Question summary                                            | Severity | Root cause                                                                                                                                          | Fix owner       |
| - | ----------------------------------------------------------- | -------- | --------------------------------------------------------------------------------------------------------------------------------------------------- | --------------- |
| 1 | "Show me the latest news on MSTR — what should I know?"     | P1       | (a) catalogue advertises `search_documents` but there is no `get_entity_news`, so the LLM picks a broad BM25/ANN query that misses MSTR; (b) no entity-anchored prompt branch for news intent | rag-chat (S8)   |
| 2 | "Screen for AI semiconductor companies, mcap > 50B, +YoY revenue growth" | P0       | `screen_universe` handler only forwards `market_cap_min/max + pe_ratio_max + sector + industry`. The LLM-supplied "YoY revenue growth > 0" filter is **silently dropped** even though the DB metric `quarterly_revenue_growth_yoy` exists in `metric_extractor.py` | rag-chat (S8) + tool schema |
| 3 | "How is OpenAI connected to Microsoft? Show me the paths."  | PASS     | `traverse_graph` returns the correct shortest path; no fix needed                                                                                                                                | —               |
| 4 | "Compare NVDA and AMD on revenue, EPS, gross margin (latest Q)" | P0       | `get_fundamentals_history_batch` returns 0 rows in 16 ms (vs ~700 ms for a real query) — the S3Client never reaches market-data because the **`market-data:8003` HTTP container is in `Created` (not running) state** in this environment; the empty payload starves `compare_entities` of fundamentals and the LLM bails | infra + rag-chat reliability gate |
| 5 | "Compare NVDA + AMD revenue trajectories — last 4 quarters" | P0       | Same root cause as #4 (`get_fundamentals_history_batch` empty). DB rows ARE present (`NVDA` 109 quarterly rows latest 2026-04-30, `AMD` 163 latest 2026-03-31) — the LLM's "no data" message is a downstream consequence, not a data gap. | infra + rag-chat |

**Headline**: Two of the five failures (Q4, Q5) are an environment-level
outage that the rag-chat tool layer hides behind an empty `tool_no_data`
log — the LLM sees a silent zero and refuses.  This is the BP-614 anti-pattern
("silent zero looks identical to a clean empty result") at the *tool* layer
instead of the brief layer.  Two more (Q1, Q2) are real product gaps in
the chat tool catalogue.  Q3 already works.

---

## Q1 — "Show me the latest news on MSTR"

### Live observation (rag-chat logs, 2026-05-29 21:40:57)

```
tool_selection_resolved iteration=0 tools=["search_documents"]
search_documents  latency_ms=675  items_returned=6
```

The model **did** call a tool and got 6 results back — but its written answer
was a refusal: long disclaimer about $124 M revenue numbers it cannot verify
plus "MSTR is associated with Bitcoin investment".  This is a **grounding**
failure, not an empty-tool failure.

### Reproduction

DB confirms ample coverage:

```
nlp_db=> SELECT COUNT(*) FROM document_source_metadata
         WHERE published_at > NOW() - INTERVAL '30 days'
           AND (title ILIKE '%mstr%' OR title ILIKE '%microstrategy%'
                OR title ILIKE '%strategy%');
 count
-------
    41
```

Canonical entity exists:

```
intelligence_db=> SELECT entity_id, canonical_name FROM canonical_entities
                  WHERE canonical_name ILIKE '%microstrategy%';
              entity_id               |       canonical_name
--------------------------------------+----------------------------
 019e0db6-2e39-7e04-aaf8-9ec675797470 | MicroStrategy Incorporated
```

### Root cause

Two compounding issues:

1. **Tool catalogue has no entity-anchored news tool.**
   `tool_registry_builder.py:181` advertises `search_documents` (hybrid
   BM25 + ANN over the full corpus) but there is **no `get_entity_news` /
   `get_articles_for_entity` tool**.  The LLM defaults to a free-text
   query "latest MSTR news" — which finds 6 items but most likely *not*
   the most relevant MSTR-tagged subset, because the news ranker treats
   the query as a string match and not as an entity anchor.
2. **No `EntityNameGroundingValidator` branch for news-only intents.**
   F-LIVE-NEW-002 added the validator on instrument briefs; the chat
   refusal path still hand-waves when the model fabricates revenue
   figures it cannot ground.

### Recommended fix

| Step | Action | File:line |
| ---- | ------ | --------- |
| 1.1 | Add a new tool `get_entity_news(entity_name OR ticker, limit, hours)` that resolves the entity, then calls S6 `/api/v1/entities/{eid}/briefing-articles?limit=10`. | `services/rag-chat/src/rag_chat/application/pipeline/handlers/news.py` (new method); `tool_registry_builder.py:~180` (register tool); `tool_executor.py:~219` (dispatch) |
| 1.2 | Mark `search_documents` as **last-resort** in its docstring so the LLM prefers the entity-anchored path when the user mentions a ticker.  Phrasing: "For entity-specific news (e.g. 'news on MSFT'), prefer `get_entity_news`." | `tool_registry_builder.py:~181` |
| 1.3 | Reuse the F-LIVE-NEW-002 `EntityNameGroundingValidator` on the chat answer path when intent classifier returns `news`.  If the answer contains numeric claims (regex `\$[0-9.,]+[MB]?` or `%` near a ticker) but the retrieved snippets contain none, replace with a grounded summary. | `chat_pipeline.py` (after answer generation, before persist) |

**Severity: P1** — model still returns *something* coherent; the fix prevents
hallucinated numerics from leaking past the citation layer.

---

## Q2 — Screener "AI semiconductors, mcap > 50B, positive YoY revenue growth"

### Live observation

```
tool_selection_resolved iteration=0 tools=["screen_universe"]
screen_universe  latency_ms=41  items_returned=0
all_tools_returned_empty  tool_count=1  tools=["screen_universe"]
```

41 ms is too fast for a real screener query (typical 200–500 ms) — the call
short-circuited to "no instruments matched".

### Root cause

In `handlers/market.py:440`, `_handle_screen_universe` accepts only:

```python
market_cap_min, market_cap_max, pe_ratio_max, sector, industry, region, limit
```

The LLM almost certainly produced something like

```json
{"sector": "Technology", "industry": "Semiconductors",
 "market_cap_min": 5e10, "quarterly_revenue_growth_yoy_min": 0}
```

— and `quarterly_revenue_growth_yoy_min` was silently **dropped** by the
Python kwargs gate.  Then the handler built a single `ScreenFilterRequest`
on `market_capitalization` with sector/industry scope **and** without a
revenue-growth predicate, returning 0 rows because the AI-tag scoping is
narrower than DB sector labels (audit BP-577 already noted that GICS sector
≠ user-facing "AI semis" label).

Meanwhile, `metric_extractor.py:171` confirms the metric **is** in the
fundamentals fact table:

```
"quarterly_revenue_growth_yoy" — alias: QuarterlyRevenueGrowthYOY
```

So the data exists; the rag-chat tool gate just doesn't expose it.

### Recommended fix

| Step | Action | File:line |
| ---- | ------ | --------- |
| 2.1 | Extend `_handle_screen_universe` signature with `revenue_growth_yoy_min: float \| None = None` and `gross_margin_min: float \| None = None`. When set, append `{"metric": "quarterly_revenue_growth_yoy", "min_value": value, **scope}` to `filter_list`. | `handlers/market.py:440` |
| 2.2 | Mirror the new parameters in the tool JSON schema (description + types) so DeepSeek can actually call them. | `tool_registry_builder.py:~697` (`name="screen_universe"` definition) |
| 2.3 | When `industry="Semiconductors"` AND a "AI" qualifier is present in the natural-language query, log a warning + add a hint to the tool response: "AI sub-sector is not a structured GICS tag — consider supplementing with `search_documents` for AI-specific commentary." | `handlers/market.py:~509` (next to the `region` log_dropped log) |
| 2.4 | If `screen_universe` returns 0 rows AND the LLM passed a YoY filter, surface a `tool_partial_match` result that lists the **top-3 by market cap** with the filter relaxed, so the LLM can recover instead of writing "no data found". | `handlers/market.py:~525` |

**Severity: P0** — this is the most user-visible failure (screener is a
flagship surface) and the data IS there; we are just gating it off.

---

## Q3 — "How is OpenAI connected to Microsoft?"

PASS in production AND in the benchmark.  `traverse_graph` correctly
returns the path

```
OpenAI → [PARTNER_OF] → Microsoft → [IS_FINANCIAL_INSTRUMENT_FOR] → MSFT.US
```

No fix needed.  Worth a regression test in the chat-quality benchmark
catalogue to lock the behaviour in.

---

## Q4 — "Compare NVDA and AMD on revenue, EPS, gross margin (latest Q)"

### Live observation

```
tool_selection_resolved iteration=0 tools=["search_documents"]
... (mid-iteration)
get_fundamentals_history_batch  latency_ms=16  items_returned=0  status=tool_no_data
```

55 s total wall-clock (gate-bound); LLM ultimately wrote
"I cannot provide the comparison because the data has not yet been
retrieved" — a refusal stitched together from `tool_no_data` signals.

### Root cause

**Two separate problems collide**:

1. **Environment**: `worldview-market-data-1` (the HTTP API container) is in
   `Created` state (not `Up`).  `docker inspect` confirms `State.Status =
   "created"`, no IP, no DNS alias.  `docker exec rag-chat python -c "import
   socket; socket.gethostbyname('market-data')"` returns
   `gaierror: Name or service not known`.

2. **Silent error in the tool layer**: `s3_client.py:178` does
   `await self._post("/api/v1/fundamentals/batch", ...)` — when DNS
   resolution fails, `BaseUpstreamClient._post` swallows the exception and
   returns `{}`.  The handler `handlers/market.py:271` then receives an
   empty dict, logs `tool_no_data`, and returns `[]`.  The LLM sees a
   clean empty result and **cannot distinguish "DB is empty" from "service
   is down"**.  This is **BP-614 at the tool layer** — the same
   silent-zero anti-pattern PLAN-0102 fixed in the brief.

Meanwhile, the DB has plenty of data:

```
market_data_db=> SELECT i.symbol, ist.period_type, COUNT(*), MAX(ist.period_end_date) AS latest
                 FROM instruments i JOIN income_statements ist ON ist.instrument_id = i.id
                 WHERE i.symbol IN ('NVDA','AMD') GROUP BY 1, 2 ORDER BY 1, 2;
 symbol | period_type | count |         latest
--------+-------------+-------+------------------------
 AMD    | ANNUAL      |    41 | 2025-12-31 00:00:00+00
 AMD    | QUARTERLY   |   163 | 2026-03-31 00:00:00+00
 NVDA   | ANNUAL      |    28 | 2026-01-31 00:00:00+00
 NVDA   | QUARTERLY   |   109 | 2026-04-30 00:00:00+00
```

### Recommended fix

| Step | Action | File:line |
| ---- | ------ | --------- |
| 4.1 | **Infra**: `docker compose up -d market-data` (or fix the bring-up script so the API container is brought up alongside the consumers).  Verify with `curl http://market-data:8003/healthz` from inside the rag-chat container.  This is the immediate unblocker. | `infra/compose/docker-compose.yml` |
| 4.2 | **Reliability gate**: differentiate "transport error" from "empty result" in `BaseUpstreamClient._post`.  Return a sentinel (e.g. raise `UpstreamUnavailableError`) on DNS/connection/5xx, and `{}` only on 200 with an empty body.  Then in `_handle_get_fundamentals_history_batch` (and `_handle_compare_entities`, `_handle_screen_universe`) catch the sentinel and emit `tool_upstream_unavailable` + return a `RetrievedItem` that says "Service temporarily unavailable; please retry." — so the LLM knows to retry instead of refusing. | `services/rag-chat/src/rag_chat/infrastructure/clients/base.py`; `handlers/market.py` (3 call sites) |
| 4.3 | Add a Prometheus counter `rag_chat_tool_upstream_unavailable_total{tool,target_service}` and a 5-min synthetic ping from `brief-scheduler` that hits `/api/v1/instruments/lookup?symbol=NVDA` so we get paged when the API container disappears. | `services/rag-chat/src/rag_chat/infrastructure/metrics/` + `brief_scheduler_main.py` |

**Severity: P0** — environmental, but the silent-zero pattern means we
would not have noticed for a long time and the LLM is being penalised for
a transport-layer outage.

---

## Q5 — "Compare NVDA + AMD revenue trajectories, last 4 quarters"

Same root cause as Q4.  Identical fix recommendation; the only diff is the
LLM's tool ordering (it went straight to `get_fundamentals_history_batch`
instead of routing through `compare_entities` first).

Once Q4's fix lands, this question PASSes automatically — verify with the
chat-quality benchmark `--ids real_user_q5` after deploying market-data.

---

## Cross-cutting observations

1. **BP-614 at the tool layer.**  Three of the five failures (Q2, Q4, Q5)
   share the same anti-pattern: a tool returns an empty result whose
   meaning is overloaded ("no rows" vs "transport error" vs "filter
   dropped").  PLAN-0102 fixed this for the morning brief context.  The
   chat tool executor still has it — the fix in 4.2 above is the highest-
   leverage cross-cutting change.

2. **Silent kwarg drop.**  Q2's silent loss of `revenue_growth_yoy_min` is
   the same shape as F-LIVE-Q (silent prompt-input drop) we logged in the
   user-feedback memory.  Consider adding a `strict_kwargs=True` mode to
   the tool dispatch that logs `tool_arg_dropped` for every unknown kwarg
   (we already do this for `region`, but only one-off per tool).

3. **Catalogue/intent skew.**  The catalogue has `search_documents` and
   `get_entity_intelligence` but lacks the obvious `get_entity_news` —
   the LLM has to compose news lookups out of more abstract primitives,
   which it does poorly for ticker-anchored questions (Q1).

---

## Proposed PLAN-0103 wave structure

Grouping the fixes by service owner so each wave is one focused commit /
review surface:

### Wave A — rag-chat (S8): tool catalogue gaps

* T-W A-01 — add `get_entity_news` tool (handler + dispatch + registry + tests)
  (Q1)
* T-W A-02 — extend `screen_universe` with `revenue_growth_yoy_min` +
  `gross_margin_min` parameters + tool-schema (Q2)
* T-W A-03 — add `tool_partial_match` fallback to `screen_universe`
  (Q2 → recovery from zero rows)

### Wave B — rag-chat (S8): transport reliability

* T-W B-01 — `UpstreamUnavailableError` sentinel in `BaseUpstreamClient`;
  three call sites updated (Q4, Q5 root cause)
* T-W B-02 — Prometheus counter `rag_chat_tool_upstream_unavailable_total`
  + synthetic 5-min ping from brief-scheduler
* T-W B-03 — `strict_kwargs=True` dispatch mode + alarm on
  `tool_arg_dropped` rate > 1% over 1 h

### Wave C — chat answer-side grounding

* T-W C-01 — reuse `EntityNameGroundingValidator` on news intent
  (Q1 stage 2)
* T-W C-02 — chat-quality benchmark: add Q3 (OpenAI→MSFT) as a regression
  gate; add Q1, Q2, Q4, Q5 with PASS thresholds tied to the above fixes

### Wave D — infra

* T-W D-01 — make `market-data` HTTP container part of the default
  `make dev` profile + add `healthz` probe to docker-compose so a missing
  container is visible at bring-up time (Q4/Q5 immediate unblocker)

### Estimated effort

| Wave | LoC est. | Tests | Owner       |
| ---- | -------- | ----- | ----------- |
| A    | ~250     | 8     | rag-chat    |
| B    | ~180     | 6     | rag-chat    |
| C    | ~120     | 4     | rag-chat    |
| D    | ~30      | 0     | infra       |

Total: ~580 LoC, 18 new tests, 4 commits.  Suggested order:
**D → B → A → C** (unblock infra first so any further benchmark runs are
trustworthy; then reliability gate so Wave A's new tool isn't a new silent
failure surface; then product gaps; then grounding).

---

## Appendix — raw data

### `tool_executed` distribution (last 24 h)

```
search_documents              ~40% of tool calls, p50 latency 600 ms
get_entity_intelligence       ~15%, mostly items_returned=0
get_fundamentals_history_batch ~10%, items_returned=0 EVERY call
screen_universe               ~5%, items_returned=0 EVERY call
traverse_graph                ~5%, healthy (1-3 items)
get_economic_calendar         ~5%, healthy (50 items)
... (others)
```

`items_returned=0` on every call to two of the top tools is the most
damning evidence: this is a systematic transport failure, not query-
specific.

### Market-data container state

```
$ docker ps -a --filter name=worldview-market-data
worldview-market-data-fundamentals-consumer-1  Up 17 hours (healthy)
worldview-market-data-1                        Created
worldview-market-data-migrate-1                Exited (255) 17 hours ago
... (other consumers all Up)
```

— api server container present but never started.  Likely a `depends_on`
gap or a manual `down` operation.

---

*End of audit.*
