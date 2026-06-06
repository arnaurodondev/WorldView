# PLAN-0100 — Q2 MSTR Bitcoin Entity-Drift Deep Dive

**Date**: 2026-05-27
**Severity**: P0 — wrong-entity citations presented as answer-grounding = HARMFUL fabrication class.
**Canary**: MSTR. Same fault hits any low-coverage ticker.

## Executive Summary

The LLM answered "What's the latest news on MSTR's Bitcoin position?" with a confident response **entirely about ON Semiconductor Corporation** — a different ticker — using fabricated KG citations. Root cause is a **three-layer failure stack**:

1. **BP-603 — Entity-mention lineage gap.** 25 chunks contain MSTR entity_mentions in `chunks.entity_mentions` JSONB, but the normalised `entity_mentions` table is empty for MSTR. S6 `search_chunks` filters by joining the normalised table → returns zero results despite the data existing.
2. **BP-604 — Fallback tool drift.** After two empty `search_documents(entity_tickers=["MSTR"])` calls, the LLM generated `search_claims(entity_name="ON Semiconductor Corporation")` — a different entity. Orchestrator faithfully executed without detecting the entity change.
3. **BP-605 — Missing synthesis guardrail.** The synthesis step produced a confident answer with KG citations, never flagging that retrieved-item entity (ON Semi) ≠ question entity (MSTR).

## §1 Failure path reproduction

Artifact `tests/validation/chat_eval/runs/20260527T184650Z/agg_q2.json`:

1. `search_documents(entity_tickers=["MSTR"], date_from="2026-05-20", date_to="2026-05-27")` → `item_count: 0`
2. `search_documents(entity_tickers=["MSTR"], date_from="2026-02-19", date_to="2026-08-25")` → `item_count: 0`
3. `search_claims(entity_name="ON Semiconductor Corporation")` → `item_count: 3` ✗ **DRIFT**

Final answer: 100% about ON Semiconductor with zero mention of MSTR. Citations attributed to KG claims about ON Semi.

## §2 BP-603 — entity-mention lineage gap

Live DB state:
- `nlp_db.chunks`: 31 bitcoin chunks in 14-day window, 25 with MSTR in `chunks.entity_mentions` JSONB.
- `nlp_db.entity_mentions` table: **0 rows for MSTR**.
- `intelligence_db.canonical_entities`: MSTR → `019e0db6-2e39-7e04-aaf8-9ec675797470` ✓.

S6 `search_chunks` SQL (paraphrased):
```sql
SELECT c.* FROM chunks c
LEFT JOIN entity_mentions em ON em.doc_id = c.doc_id
WHERE em.resolved_entity_id = $1  -- 0 rows when em table empty
```

The denormalised `chunks.entity_mentions` JSONB is populated (per the consumer's write-time enrichment) but the normalised `entity_mentions` table — which the search SQL filters on — was never backfilled. This is the BP-575 / BP-586 lineage family resurfacing.

**Fix sketch**: extend S6 `search_chunks` to also filter via JSONB containment when `entity_ids` is specified:
```sql
WHERE em.resolved_entity_id = $1
   OR c.entity_mentions @> jsonb_build_array(jsonb_build_object('resolved_entity_id', $1::text))
```
Or: backfill `entity_mentions` table from `chunks.entity_mentions` JSONB. The query change is the lower-risk delivery.

## §3 BP-604 — fallback tool drift without guardrails

After two empty results the LLM decided on its own to call `search_claims` with a different entity. **The orchestrator has no validation that fallback tool calls preserve entity identity.**

This is pure LLM hallucination — no prompt instruction says "fallback to a different entity". The model is generating out-of-spec tool calls and the orchestrator forwards them blindly.

**Fix sketch**: `_validate_fallback_tool_call()` in the orchestrator's iteration loop:
- Extract entity identifiers from prior turns' tool_calls (ticker, entity_name, entity_id).
- If a later turn's tool_call mentions an entity that wasn't in the question's resolved entities AND wasn't in any prior tool_call input, REJECT the call with a structured error to the LLM ("entity drift detected; refusing"). The LLM should then either refuse honestly or pick the right entity.

## §4 BP-605 — synthesis grounding gap

The OutputProcessor synthesised a confident answer from retrieved items whose `citation_meta.entity_name == "ON Semiconductor"` even though the question was about MSTR. There is no entity-grounding check between the retrieved item set and the question entities.

**Fix sketch**: `_check_entity_grounding()` in the synthesis step:
- Collect entity_name / entity_id from every retrieved item used in citations.
- Cross-check against the question's resolved entities.
- If ZERO overlap, raise `EntityGroundingError` and refuse the answer ("I cannot find information about <question entity> in the retrieved sources").

## §5 Why HARMFUL, not MARGINAL

The W3 audit re-classified Q2 from MARGINAL to HARMFUL. Rationale:
- **MARGINAL** = "model didn't call the right tool" — annoying but recoverable.
- **HARMFUL** = "model presented wrong-entity information with fabricated citations" — a user asking about MSTR's Bitcoin position gets a confident answer about ON Semi data-center revenue with KG citations. Zero indication the answer is about a different company. A user could act on it.

## §6 Broader impact — MSTR is the canary

MSTR is low-coverage (no KG claims, no normalised entity_mentions). The same failure path triggers for ANY ticker with the denormalised-but-not-normalised entity_mentions shape. Likely affected: small-caps, recent IPOs, non-US tickers, anything that joined the universe after the last entity_mentions backfill.

## §7 Recommended fix path (PLAN-0100)

| Bug | Layer | Fix scope | Files |
|---|---|---|---|
| **BP-603** | Retrieval | extend `search_chunks` JSONB-containment fallback | `services/nlp-pipeline/.../news_query.py` + `chunk_search.py` |
| **BP-604** | Orchestrator | `_validate_fallback_tool_call()` entity-identity guard | `services/rag-chat/.../use_cases/chat_orchestrator.py` |
| **BP-605** | Synthesis | `_check_entity_grounding()` answer-vs-retrieved cross-check | same orchestrator file or new `output_processor.py` |

Combined: ~200 LOC across 3 files; ~15 regression tests; no schema changes (JSONB shape already exists). Re-run Q2 chat-eval after — expect: `search_documents(entity_tickers=["MSTR"])` finds ≥5 chunks, no fallback needed, answer about MSTR.

## Summary — pain point + solution

**Pain point**: The agent silently substitutes wrong entities when its first retrieval calls return empty, then writes confident citation-backed answers about the substituted entity. Caused by a three-layer failure: empty results due to a JSONB-vs-normalised-table join gap (BP-603), no orchestrator-level entity-drift guard (BP-604), no synthesis-level entity-grounding check (BP-605). MSTR is the canary; any low-coverage ticker has the same exposure. Severity P0 — produces HARMFUL fabrications indistinguishable from valid answers.

**Solution**: ship three layered fixes — extend `search_chunks` to fall back on `chunks.entity_mentions` JSONB containment, add an entity-identity validator in the orchestrator's iteration loop that rejects tool calls naming entities not in the question or prior turns, and add a synthesis-step grounding check that refuses to cite retrieved items whose entity doesn't overlap with the question's resolved entities. ~200 LOC, 15 tests, no schema migration. Re-test Q2 to confirm the answer is about MSTR.
