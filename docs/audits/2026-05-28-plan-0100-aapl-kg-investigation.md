# PLAN-0100 W3 — AAPL `get_entity_intelligence` Investigation

**Date**: 2026-05-28
**Plan**: PLAN-0100 W3 (T-W3-01)
**Question**: Why does `get_entity_intelligence(AAPL)` return `item_count: 0, status: empty`
in chat-eval Q1 when Apple is one of the most-covered entities in the platform?

## TL;DR

Branch (c) **formatter/field-mapping bug** is the dominant cause; Branch (a) data
gap is a secondary, smaller problem.

The S7 endpoint `GET /v1/entities/{id}/intelligence` returns a *rich* payload for
Apple (96-word narrative naming Microsoft as a competitor, health score 0.73,
breakdown with 90-day trend). The rag-chat client
`S7IntelligenceClient.get_entity_intelligence` silently drops that narrative
because it reads `raw.get("narrative")` from the top level — but the actual
field is nested at `current_narrative.narrative_text`. The same field-mapping
bug also affects `get_narrative` (reads `content`/`narrative`/`text`; endpoint
returns `{versions: [{narrative_text: ...}]}`).

After the drop, the `_handle_get_entity_intelligence` formatter still returns
exactly one `RetrievedItem`, but its body is only `"Intelligence bundle for
Apple Inc.:\n\n## Health Score\n0.73"` — no narrative, no relations summary,
no paths. The agent reads that and cannot name competitors.

## Evidence

### 1. AAPL canonical state (`intelligence_db`)

```
entity_id                            | canonical_name | ticker | has_desc | has_narrative | health
01900000-0000-7000-8000-000000001001 | Apple Inc.     | AAPL   | t        | t             | 0.73
52a92aa8-750e-4b97-8838-521ce2ce9f74 | AAPL Stock     | AAPL   | t        | t             | 0.40
449ab502-9d89-4b47-93b8-206ec788e313 | Apple shares   |        | t        | t             | 0.40
58e88b82-4502-4892-a316-75d46920b32e | OpenAI-Apple   |        | f        | t             | 0.40
```

Canonical Apple Inc. has description, narrative, and a usable health score.
Three duplicate "stub" entities exist (PLAN-0072 dedup follow-up).

### 2. `relations` for Apple Inc.

```
canonical_type | subject                                | object                                  | other
is_in_sector   | 01900000-...-000000001001 (Apple Inc.) | 0195daad-...-000000000008               | Information Technology
```

Only **1 row** — the platform has *no* explicit `competes_with`/`competitor_of`
relation for Apple. This is the data gap (Branch a), and is not fixable inside
this wave (requires re-running the KG extraction with a competitor extractor
prompt + backfill, owned by PLAN-0101 KG/NLP).

### 3. Live `GET /v1/entities/{AAPL}/intelligence` response

```json
{
  "entity_id": "01900000-0000-7000-8000-000000001001",
  "canonical_name": "Apple Inc.",
  "entity_type": "financial_instrument",
  "health_score": 0.7291120333665124,
  "current_narrative": {
    "version_id": "019e4849-...",
    "narrative_text": "Apple Inc. is a leading technology company that competes
      with Microsoft Corporation in the global market for personal computers
      and software. As a major player in the tech industry, Apple is exposed
      to emerging trends in Artificial Intelligence...",
    "model_id": "meta-llama/Meta-Llama-3.1-8B-Instruct",
    "generation_reason": "PERIODIC_REFRESH",
    "generated_at": "2026-05-21T02:06:53Z",
    "word_count": 96
  },
  "confidence_breakdown": {
    "mean_support": 0.95,
    "relation_count": 1,
    "source_distribution": [{"source_type": "eodhd", "count": 4, "pct": 1.0}],
    "confidence_trend": [{"date": "2026-05-28", "avg_confidence": 0.9}, ...]
  },
  "key_metrics": {},
  "data_completeness": 0.5
}
```

The 96-word narrative explicitly mentions Microsoft — which is precisely the
data the chat-eval expected.

### 4. Client field-mapping bug (`s7_intelligence_client.py:60-76`)

```python
return EntityIntelligenceResult(
    entity_id=str(entity_id),
    narrative=raw.get("narrative") or raw.get("summary"),         # ← always None
    health_score=float(raw["health_score"]) if raw.get(...) ...,  # OK
    key_metrics=raw.get("key_metrics") or {},                     # OK
    source_distribution=raw.get("source_distribution") or {},     # ← nested, always {}
    paths=raw.get("paths") or [],                                 # ← not in schema
    relations_summary=raw.get("relations_summary"),               # ← not in schema
)
```

Endpoint payload exposes `current_narrative.narrative_text` and
`confidence_breakdown.source_distribution`; the client looks at the top level
for both → both come back as None / `{}` 100% of the time.

The same bug applies to `get_narrative` (line 35): reads `raw.get("content") or
raw.get("narrative") or raw.get("text")` — but the `/narratives` endpoint
returns `{versions: [{narrative_text: ...}]}`. Always returns the empty-string
fallback `""`, which the handler then drops via `if result is None or not
result.content: return []`.

### 5. Handler downstream effect (`handlers/narrative.py:248-304`)

Builds `sections` conditionally: `if result.narrative`, `if result.health_score
is not None`, `if result.key_metrics`, `if result.paths`, `if
result.relations_summary`. With the bug, only the health-score branch fires,
producing one-item output:

```
Intelligence bundle for Apple Inc.:

## Health Score
0.73
```

The agent cannot extract competitor names from a single health-score number,
so it omits Samsung / Google / Huawei / Microsoft and is graded MARGINAL.

## Classification

* **(c) Data present, query works, formatter drops** — **dominant cause** (fix
  in this wave).
* **(a) Data missing** — applies to the *structured relations* table (Apple
  has no `competes_with` rows); narrative text mentions Microsoft but the
  agent never sees it because of (c). Backfill deferred to PLAN-0101.
* **(b) Use-case / SQL bug** — ruled out: the S7 endpoint returns full data.

## Fix scope for T-W3-02

1. `S7IntelligenceClient.get_entity_intelligence`: read
   `raw["current_narrative"]["narrative_text"]` (with safe None-walks) and
   `raw["confidence_breakdown"]["source_distribution"]`.
2. `S7IntelligenceClient.get_narrative`: read the first item of
   `raw["versions"][0]["narrative_text"]`.
3. Drop the dead `paths` / `relations_summary` reads — they are not part of
   the S7 schema (`EntityIntelligencePublic` does NOT expose them; `paths`
   come from a separate `/paths` endpoint already wired via `get_entity_paths`).

## Regression test (T-W3-03)

`services/rag-chat/tests/unit/infrastructure/clients/test_s7_intelligence_client.py`:
given a payload matching the real S7 schema, asserts
`result.narrative` contains the AAPL narrative text (not None / empty).

## Out of scope (deferred to PLAN-0101)

* Backfilling explicit `competes_with` / `supplies_to` / `partners_with`
  relations for Apple (and other top-50 entities). Requires NLP/KG extraction
  re-run.
* AAPL canonical dedup (three stub entities still present). Tracked under
  PLAN-0072 entity-dedup follow-up.
