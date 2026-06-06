# PLAN-0099 W3 — Q1 (Apple competitors) + Q2 (MSTR Bitcoin) MARGINAL investigation

**Date**: 2026-05-27
**Plan**: PLAN-0099 W3-T01 + W3-T02
**Source run**: `tests/validation/chat_eval/runs/20260527T184650Z/agg_q1.json` + `agg_q2.json`
**Verdict (both)**: **Branch B — KG / ingestion / entity-resolution gap; defer to PLAN-0100.** No Branch-A prompt tweak ships from this audit.

---

## Q1 — "Who are Apple's main competitors?"

### Reproduction (from `agg_q1.json`)

The agent issued exactly one tool call:

```json
{"name": "get_entity_intelligence", "arguments": {"entity_id": "aapl"}}
```

Tool result:

```json
{"item_count": 0, "status": "empty", "tool": "get_entity_intelligence"}
```

Answer text (verbatim):

> "I searched for Apple's main competitors using the entity intelligence tool, but no data was returned. The system did not provide any information on competitors or related entities for Apple."

### Database state

`intelligence_db.canonical_entities` has Apple Inc. (`01900000-0000-7000-8000-000000001001`, ticker `AAPL`) plus a stray `52a92aa8-…` "AAPL Stock" duplicate. So the entity exists. The `get_entity_intelligence` tool resolved the canonical entity but returned `item_count: 0` — meaning the **intelligence bundle itself was empty** (no narrative, no relations, no claims).

### Verdict

**Branch B — KG gap.** The model never had Samsung/Microsoft/Google/Huawei/Xiaomi to enumerate, because the upstream KG bundle was empty. The MARGINAL grader rubric ("model didn't mention competitors despite calling the tool") is therefore *misattributed*: the failure is upstream of the model. No prompt tweak in `rag-chat` will fix this — the fix lives in `knowledge-graph` (populate `competitor_of` edges and/or include relation summaries in the intelligence bundle response).

The `tool_registry_builder.py:234` description already warns the LLM: *"…is sparse on `competitor_of` edges and will return empty; use `get_entity_intelligence` for narrative."* The agent followed that advice, and the bundle was still empty — so even the documented fallback fails.

**Defer to PLAN-0100 §(c) Branch-B** with the concrete acceptance criterion: *after backfill, `get_entity_intelligence(entity_id=AAPL)` returns ≥3 named competitor entities (Samsung, Microsoft, Google) in the relations or narrative field.*

### Recommended Branch-A — **none ships from this audit**

A prompt change ("when intelligence bundle is empty, name known competitors from training data") would directly violate R39 (no speculative claims) and the grounding-validation gate. The right fix is data, not prompt.

---

## Q2 — "Show me the latest news on MSTR — what should I know?"

### Reproduction (from `agg_q2.json`)

Tool-call sequence:

1. `search_documents(entity_tickers=["MSTR"], date_from=2026-05-20, date_to=2026-05-27)` → `item_count: 0`
2. Fallback `search_documents(entity_tickers=["MSTR"], date_from=2026-02-19, date_to=2026-08-25)` → `item_count: 0`
3. Fallback `search_claims(entity_name="ON Semiconductor Corporation")` → `item_count: 3`

The final answer is entirely about **ON Semiconductor Corporation (ticker `ON`)** — Treo platform, AI data-center revenue, cyclical trough — with three KG claim citations. The user asked about **MicroStrategy** (`MSTR`).

### Database state

- `intelligence_db.canonical_entities`: `MSTR` resolves correctly to `MicroStrategy Incorporated` (`019e0db6-…`). The S6 resolver does not have an MSTR→ON mapping bug.
- `nlp_db.chunks`: **31 chunks in the last 14 days** match `ILIKE '%bitcoin%' OR '%MSTR%' OR '%MicroStrategy%'`. The data exists in the corpus.
- Run 1 of `search_documents(entity_tickers=["MSTR"])` returned zero. Either (a) the MSTR canonical entity is not linked to those 31 chunks via `entity_mentions`, or (b) the `news_query` filter is dropping them. This is the BP-583 / entity-mention lineage issue PLAN-0098 W2 left tail-work on.

### The smoking gun

The third tool call substitutes `entity_name="ON Semiconductor Corporation"` — a different ticker entirely. This is **LLM hallucination during fallback args generation**: with two empty MSTR results, the model decided to ask about a different company without acknowledging the empty result. The orchestrator faithfully executed it, got 3 hits, and the synthesis step wrote a confident answer with KG-claim citations — never flagging that the entity drifted from the user's question.

### Verdict

**Combined Branch B — ingestion/lineage gap + Branch A — fallback guardrail gap.**

- **Ingestion/lineage (Branch B, deferred to PLAN-0100)**: 31 MSTR-related chunks exist in `nlp_db.chunks` but `search_documents(entity_tickers=["MSTR"])` returns zero. Most likely: `entity_mentions.canonical_entity_id` was not populated for MSTR rows, so the join in `news_query` filters them out. This is the same family as BP-575/586 (PUBLIC_TENANT_ID + tenant lineage) — investigate alongside PLAN-0100 §(a).
- **Fallback guardrail (Branch A — also deferred)**: the orchestrator should NEVER substitute a different entity name in a fallback. After two empty `search_documents` calls for ticker `MSTR`, the synthesis step should produce: *"No recent news found for MSTR over the past week."* The current behaviour — silently pivoting to ON Semi — is harmful, not marginal. A one-line prompt tweak in `tool_registry_builder.py` ("never substitute a different entity in a fallback call; always echo the original entity") is plausible, but the right fix is harness-level: detect entity-name drift between the user's question and the answer's citations, and refuse. This is non-trivial and intersects with the rag-chat grounding-validation gate — **does not meet the "trivial, one-line, obviously correct" bar** for shipping in this audit. Defer to PLAN-0100 with verdict re-classification request: this Q2 is HARMFUL, not MARGINAL.

### Recommended Branch-A — **does not ship from this audit**

The pattern is real and important enough that it needs its own test fixture before any prompt change. File as PLAN-0100 W-X — *"Reject fallback tool calls whose entity arguments differ from the original tool call's entity arguments."*

---

## Combined recommendation

| Question | Verdict re-classification | Path | PLAN-0100 task |
|---|---|---|---|
| Q1 | MARGINAL stands (sparse KG) | KG backfill | §(c) Branch-B: AAPL `competitor_of` edges + intelligence-bundle relation expansion |
| Q2 | **HARMFUL** (entity drift not flagged) | NLP lineage + orchestrator guardrail | §(a) BP-575 family follow-on (entity_mentions link) + new task §(d): fallback-entity-drift refusal |

Neither yields a Branch-A patch in PLAN-0099. W3 closes as "investigation complete, no fix shipped, two PLAN-0100 inputs added."
