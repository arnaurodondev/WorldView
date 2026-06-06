# Investigation Report — `GraphEnricher` invoked with empty `relation_results`

**Date filed**: 2026-05-24
**Owner**: TBD
**Severity**: Medium — feature dormant, no data corruption, but a documented design goal of the platform is currently unrealised at runtime
**Linked thesis claim**: Chapter 4, §4.5 (RAG–KG coupling, fifth level)

---

## 1. Summary

The `GraphEnricher` class in `services/rag-chat/src/rag_chat/application/pipeline/fusion.py` is designed to attach each retrieved document chunk to the top-N knowledge-graph relations involving the chunk's mentioned entities. The infrastructure is fully implemented. The call site in `chat_pipeline.py`, however, invokes the enricher with a hard-coded empty `relation_results` list, so the in-place chunk-with-adjacent-relations co-presentation is never produced at runtime.

Concretely:

```python
# services/rag-chat/src/rag_chat/application/pipeline/chat_pipeline.py:408
enriched = self.graph_enricher.enrich(items, [])  # relation_results always [] here
```

The inline comment was left during development. The thesis describes this co-presentation as one of five levels of RAG–KG coupling (the other four — schema linkage, three-view entity embeddings, tool-mediated access, parallel retrieval orchestration — are active in production).

## 2. Why this matters

Without enrichment, every chunk presented to the LLM stands alone. Relation context for the same entities is still available to the LLM via separate `RetrievedItem` entries (the orchestrator does fetch relations in parallel — `retrieval_orchestrator.py:135`), but the model has to do the work of linking "this chunk mentions Apple" to "this relation says Apple acquired X". Co-presenting the two in the same prompt context would let the LLM produce citations of the form *"according to article A (chunk), as corroborated by graph edge E (relation evidence)"* directly, rather than reconstructing the link probabilistically.

The omission does not affect correctness — answers can still cite both chunks and relations — but it weakens the grounding signal and the citation-accuracy KPI.

## 3. Evidence

### 3.1 The enricher is fully implemented

`services/rag-chat/src/rag_chat/application/pipeline/fusion.py`:

```python
class GraphEnricher:
    """Attach top-3 relation summaries to chunk items that reference entities.

    For each chunk with entities[], find that entity's top-3 relations from
    the relation_results (ranked by summary_authority) and attach them as
    graph_enrichment on the frozen RetrievedItem (creates a new instance).
    """

    def enrich(
        self,
        items: list[RetrievedItem],
        relation_results: list[RelationResult],
    ) -> list[RetrievedItem]:
        # ... builds entity → sorted relations lookup ...
        # ... iterates items, attaches graph_enrichment to chunks with mentioned entities ...
```

### 3.2 The orchestrator does fetch relations

`services/rag-chat/src/rag_chat/application/pipeline/retrieval_orchestrator.py:135`:

```python
if plan.use_relations and query_embedding:
    tasks.append(self._with_cb("relations", self._fetch_relations(query_embedding, entity_ids)))
```

So `relation_results` *is* available in the orchestrator. The orchestrator absorbs them into the general `items` list as their own `RetrievedItem`s.

### 3.3 The call site discards the relations input

`services/rag-chat/src/rag_chat/application/pipeline/chat_pipeline.py:408`:

```python
def enrich_and_fuse(self, items: list[RetrievedItem]) -> list[RetrievedItem]:
    # Step 6 (GraphEnricher): injects top-3 relation summaries adjacent to ...
    enriched = self.graph_enricher.enrich(items, [])  # relation_results always [] here
    # ...
```

The signature accepts only `items`. Relations were never plumbed through.

## 4. Hypotheses to investigate

H1 — **The split was intentional during PLAN-0067 (tool-use loop migration)** and the enrichment path was deferred because the new tool-mediated retrieval was expected to subsume it. Verify by checking the PLAN-0067 spec and PR history. If true, the right action may be to delete `GraphEnricher` rather than re-enable it.

H2 — **The enricher was developed for the legacy fixed pipeline and not migrated**. Verify by checking the deleted modules (`intent_classifier.py`, `retrieval_plan_builder.py`) for the original wiring. If true, re-enabling means plumbing `relation_results` from the orchestrator into `enrich_and_fuse`.

H3 — **The enrichment is performance-prohibitive at the planned scale** and was disabled deliberately. Verify by estimating per-chunk cost: for each chunk with K mentioned entities, fetch top-3 relations each — roughly $K times 3$ extra rows per chunk, with a dictionary lookup that's already O(1) once `entity_relations` is built. Unlikely to be the blocker.

H4 — **The `RetrievedItem.entities` field is not populated by current retrievers**, so even if `relation_results` were passed in, the enricher would have no entity keys to look up. Verify by inspecting `search_documents` and `ParallelRetrievalOrchestrator._fetch_chunks` output.

## 5. Proposed fix outline (assuming H2 confirmed)

1. **Plumb `relation_results` into `enrich_and_fuse`.** Change the signature in `ChatPipeline.enrich_and_fuse` to accept the parallel relation hits separately from the unified items list.
2. **Update the call site in `ChatPipeline.run`** (the orchestrator step) to pass the partition of `items` whose `item_type == ItemType.relation` as the second argument.
3. **Verify `RetrievedItem.entities` is populated** on chunk items returned by `search_documents`. If not, populate from `chunks.entity_mentions` join in the S6 retrieval path.
4. **Add an integration test** in `tests/integration/test_chat_graph_enrichment.py`: seed two articles plus a relation between two entities they both mention, issue a chat query, assert the resulting context includes `graph_enrichment` on the matching chunks.
5. **Add a metric** `rag_chat.graph_enrichment.chunks_enriched_total` to track the runtime impact.
6. **Document the change in `docs/services/rag-chat.md`** and update the thesis Chapter 4 §4.5 "fifth-level coupling" paragraph from "wired but dormant" to "active".

## 6. Tests to add

- Unit: `tests/unit/application/test_graph_enricher_with_relations.py` — passes a synthetic `items` list with `entities` populated and a synthetic `relation_results` list; asserts `graph_enrichment` is attached to the correct chunks with the top-3 relations.
- Integration: `tests/integration/test_chat_pipeline_graph_enrichment.py` — exercises the full `ChatPipeline.run` against a seeded `intelligence_db` and asserts the LLM context includes graph context for chunks whose entities match retrieved relations.
- E2E (optional): run a real chat query against the live stack and inspect the assembled prompt for graph context.

## 7. Estimated complexity

Small to medium. The data is already retrieved; the change is one signature change and one call-site plumbing fix, plus tests. Estimated effort: half a day including review and documentation update.

## 8. Open questions to resolve before implementing

- Q1: Is the legacy `intent_classifier` / `retrieval_plan_builder` deletion (PLAN-0067) fully complete, or are there stale code paths still referencing `GraphEnricher` with non-empty relations elsewhere?
- Q2: Does the tool-use loop's prompt-assembly stage already include graph context in some other form (e.g., the LLM's first turn already receives relation summaries as tool results)? If yes, enrichment may be redundant duplication and the right action is deletion, not re-enabling.
- Q3: What is the current citation-accuracy KPI baseline (per `LLMJudgePort` cron), and is there a hypothesis that enrichment would improve it?

## 9. Suggested follow-up session

`/investigate` skill should be the entry point. Read PLAN-0067 spec, trace the deletion PR for the legacy pipeline, then decide between H1, H2, H3, H4. After the decision: either delete `GraphEnricher` and the dormant call site (with thesis-text update reverting the "fifth-level" claim), or implement the plumbing fix above with the test plan in §6.
