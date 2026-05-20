# AI Architecture Enhancement ROI Analysis

**Date**: 2026-05-10
**Investigator**: Claude (investigation skill)
**Scope**: 12 enhancements from `2026-05-10-ai-architecture-investigation.md` — validated against live codebase
**Status**: Complete — cost estimates revised, build order defined

---

## Executive Summary

The original report's priority matrix was validated by reading the actual S6, S7, and S8 service code. **Three cost estimates changed materially**:

- **E-8 cost drops to TRIVIAL** — Layer 1 injection guard already exists in `input_validator.py` (7 regex patterns + PII detection + XML token wrapping). Only Layer 2 LLM classifier is missing.
- **E-4 cost rises to HIGH** — `path_insights` tables exist but are scoped to investment opportunity paths (different schema, wrong purpose). A structural BFS worker needs either new tables or a full repurpose; PathInsightWorker Wave E1 is still deferred.
- **E-3 cost drops to LOW** — `relation_evidence_promoter.py` is small and well-scoped; adding a confidence threshold + evidence density counter is a 60-line change.

The net result: **5 enhancements sit in the ideal quadrant (HIGH impact, LOW cost)** and should be implemented as a single wave before tackling the medium-cost P1 items.

---

## Part I — Validated Cost Assessment

### Actual Codebase State per Service

**S8 — `chat_orchestrator.py` (lines 114–481)**
- No dedicated `AgentLoop` class — orchestration lives in `ChatOrchestratorUseCase.execute_streaming()`
- Hard cap: `_MAX_TOOL_TURNS = 2` (line 67) — one tool round + one final answer
- No token budget, no cumulative latency budget, no consecutive error counter
- Tools: `get_entity_graph` (1-hop, text output), `traverse_graph` (multi-hop BFS, text output)
- `input_validator.py`: Layer 1 **already complete** (7 injection patterns + PII + XML token wrapping)
- Citations: extracted post-LLM in `process_output()` (line 437); no fabrication scrubbing

**S6 — `entity_resolution.py` (Block 9)**
- 4-stage + Stage 2.5 cascade fully implemented
- `AUTO_RESOLVE_THRESHOLD = 0.62`, `PROVISIONAL_THRESHOLD = 0.45`
- `canonical_entities` schema: NO `resolution_role`, NO `lookup_columns` JSONB
- Audit list created per mention but not persisted (no `mention_resolutions` writes)

**S7 — Block 12 promoter + workers**
- `relation_evidence_promoter.py` (lines 53–112): zero quality gate; promotes on `entity_provisional=false` + dedup only
- `path_insight_jobs` + `path_insights` tables exist (migration 0032) but scoped to investment opportunity paths (composite/harmonic/diversity scores) — NOT structural BFS paths
- `ProvisionalEnrichmentWorker`: Layer 1 noise blocklist + Layer 2 LLM classifier; no cross-entity similarity deduplication pass

---

## Part II — Revised Quadrant Map

```
                    HIGH IMPACT
                         │
        E-6 ●  E-8 ●     │     E-3 ●
        E-1 ●            │     E-11 ●   E-9 ●
─────────────────────────┼─────────────────────────
    LOW COST             │              HIGH COST
─────────────────────────┼─────────────────────────
        E-7 ●  E-12 ●    │
        E-2 ●  E-5 ●     │     E-4 ●
        E-10 ●           │
                         │
                    LOW IMPACT
```

**Quadrant I (High Impact × Low Cost) — Build first:**
E-6, E-8, E-1, E-3, E-7, E-12

**Quadrant II (High Impact × Higher Cost) — Plan separately:**
E-11, E-9, E-4

**Quadrant III (Medium Impact × Low Cost) — Fill-in work:**
E-2, E-5, E-10

---

## Part III — Enhancement-by-Enhancement Verdicts

### E-8: Two-Layer Injection Detection in S8
**Revised cost: TRIVIAL (was LOW)**
Layer 1 is done. `services/rag-chat/src/rag_chat/application/security/input_validator.py` already implements:
- 7 blocklist regex patterns
- PII detection (4 patterns: phone, email, SSN, credit card)
- XML wrapping with random token pair to prevent prompt bleed

**Only missing:** Layer 2 LLM semantic classifier (~50-line class using existing `ExtractionClient` protocol from `libs/ml-clients`). Use cheapest available model (Qwen 0.5B) with fail-closed semantics on all error paths.

**Recommendation**: Implement Layer 2 standalone. ~2 hours.

---

### E-6: Multi-Budget Agent Loop Governance in S8
**Revised cost: LOW (confirmed)**
The orchestrator is clean and well-structured at `chat_orchestrator.py`. Changes are purely additive: introduce `AgentBudget` dataclass, thread 3 counters through the existing loop, add a surrender path that injects one final system message.

Current state misses:
1. Cumulative token counter (across both tool turns)
2. Wall-clock latency budget (prevent hanging on slow AGE Cypher queries)
3. Consecutive error counter (currently swallows tool errors silently)

**Key pain point this fixes**: AGE Cypher queries on `traverse_graph` can exceed 60s and currently block the entire SSE stream.

**Recommendation**: Implement alongside E-8 in the same wave. ~4 hours.

---

### E-1: Role Taxonomy for Entity Resolution in S6
**Revised cost: LOW (was LOW, priority should move from P2 → P1)**
Adding `resolution_role ENUM('ENTITY','DIMENSION','MEASURE','ASSOCIATION')` to `canonical_entities` is a one-migration addition. Classification maps cleanly from existing `entity_type` values:
- `financial_instrument` → ENTITY
- `macroeconomic_indicator` → MEASURE
- `economic_event` → DIMENSION
- `organization` → ENTITY
- `person` → ENTITY
- `commodity` → DIMENSION
- Index composites → ASSOCIATION

The classification lives in `S3CanonicalEntityCreatedConsumer` (one conditional block) or as a migration backfill via SQL CASE.

**Downstream multiplier**: Every downstream improvement — E-3 (BFS skip MEASURE nodes), E-4 (BFS filtering), E-9 (graph resolution), E-5 (weighted lookup) — is more precise once role taxonomy exists.

**Recommendation**: Implement in Wave 1 as a prerequisite for E-3 and E-5. ~4 hours including migration.

---

### E-3: Evidence Quality Gating in S7 Block 12
**Revised cost: LOW (was MEDIUM)**
`relation_evidence_promoter.py` is small and well-scoped. The quality gate adds:
1. Join to `relation_evidence_raw` to count evidence rows per triple
2. Compute `evidence_count / total_docs_mentioning_both_entities` as density
3. If `density < 0.05 AND extraction_confidence < 0.70` → route to `provisional_entity_queue` instead of promoting

This is a ~60-line modification to one file. No new tables required — the existing `provisional_entity_queue` is the sink for uncertain triples.

**Impact**: Directly reduces the most common S7 quality failure — low-confidence phantom relations inflating path counts and polluting S8 graph neighborhood queries.

**Recommendation**: Wave 1 alongside E-1. ~3 hours.

---

### E-7: Citation Chip Egress Allowlist in S8
**Revised cost: LOW (confirmed)**
Pure string processing in `_build_answer_event()` / `process_output()`. `RetrievedItem.item_id` already exists; need only:
1. Collect `seen_entity_ids` / `seen_article_ids` during tool execution (add to existing tool result loop)
2. Regex scan + replace fabricated IDs in the final answer string before emitting `AnswerEvent`

No schema changes, no model changes.

**Recommendation**: Include in Wave 1. ~2 hours.

---

### E-12: Per-Turn Audit Log in S8
**Revised cost: LOW (confirmed)**
New `chat_audit_log` table + `ChatAuditLogger` class initialized at route entry and finalized in SSE cleanup. The SSE emitter already emits `tool_call` / `tool_result` events; the logger piggybacks on those events rather than adding new instrumentation.

**Recommendation**: Include in Wave 1. ~3 hours including migration.

---

### E-11: Org-Level Entity Deduplication Worker in S7
**Revised cost: MEDIUM (confirmed)**
Pass 1 (SequenceMatcher + alias Jaccard overlap) is straightforward. The complexity is the FK merge cascade:
- `entity_mentions.resolved_entity_id`
- `relations.subject_entity_id`, `relations.object_entity_id`
- `relation_evidence_raw.subject_entity_id`, `.object_entity_id`
- `claims.entity_id`
- `events.entity_id` (where applicable)
- `provisional_entity_queue.entity_id`

For financial entities, ISIN/ticker exact-mismatch overrides all similarity — this is the critical guard that prevents the LLM from merging distinct instruments with similar names.

**Recommendation**: Wave 2. Plan as a background scheduled worker, not a synchronous path. Emit a `kg.entity.dedup.v1` Kafka event per merge so downstream services can update their own FK references independently.

---

### E-4: BFS Path Pre-computation in S7
**Revised cost: HIGH (was MEDIUM)**
`path_insight_jobs` / `path_insights` tables exist (migration 0032) but are investment-opportunity paths (composite/harmonic/diversity/surprise scores), not structural BFS graph traversal paths. Options:
1. Repurpose `path_insights` — requires schema change, FK logic rewrite, semantics collision
2. New `relation_paths` table — adds migration, no collision

Either way, the PathInsightWorker implementing BFS is still listed as deferred Wave E1 in TRACKING.md. This is a substantial independent worker (~400 lines).

**Recommendation**: Wave 3 or separate PRD. Unblock with a new `relation_paths` table rather than repurposing `path_insights`. Before this, E-3 (quality gating) is a prerequisite — BFS over noisy relations produces noisy paths.

---

### E-9: Graph-Enriched Entity Resolution in S6/S8
**Revised cost: MEDIUM-HIGH (was MEDIUM)**
`get_entity_graph` currently returns formatted text, not structured node/edge data. Enriching entity resolution to return 1-hop neighbors requires:
1. S7 API: new structured endpoint (or extend existing) returning `list[NeighborRef]` instead of text
2. S8 tool: extend `S8FindEntitiesResult` to include `one_hop_neighbors`
3. Optional BFS paths: depends on E-4 being done first

**Recommendation**: Wave 3, after E-4 tables are in place. The value multiplies significantly once E-4 pre-computes the paths.

---

### E-2: Lookup Column Strategy per Entity Type in S6
**Revised cost: LOW (confirmed)**
JSONB column `lookup_columns` on `canonical_entities` + classification at entity creation. Standalone value is MEDIUM (targeted improvement to specific entity classes), but it's also a prerequisite for E-5.

**Recommendation**: Wave 2, alongside E-5.

---

### E-5: Weighted Alternate Entity Lookup in S6/S8
**Revised cost: LOW (confirmed, depends on E-2)**
Once `lookup_columns` JSONB exists, the S8 alias lookup multiplies `base_similarity * column_weight` — a 10-line change to the existing lookup path.

**Recommendation**: Wave 2 immediately after E-2.

---

### E-10: Streaming JSON Completion for S7 Narratives
**Revised cost: LOW (confirmed), impact LOW-MEDIUM**
Additive adapter method in `libs/ml-clients`. Block 13C processes 20-relation batches (~3k token responses) — below the OOM threshold but margin is thin. Adopt as a defensive measure.

**Recommendation**: Wave 2, low-risk filler task.

---

## Part IV — Definitive Build Order

### Wave 1 — P0 Quick Wins (5 enhancements, ~14 hours total)
All HIGH impact, LOW cost. No inter-dependencies (except E-1 before E-3 is ideal but not required).

| # | Enhancement | File(s) | Hours |
|---|-------------|---------|-------|
| E-8 Layer 2 | LLM injection classifier in S8 | `security/input_validator.py` | 2h |
| E-6 | Multi-budget governance in S8 | `application/use_cases/chat_orchestrator.py` | 4h |
| E-1 | Role taxonomy column + classification | `intelligence-migrations/` + `canonical_entities` | 4h |
| E-3 | Evidence quality gate in Block 12 | `workers/relation_evidence_promoter.py` | 3h |
| E-7 | Citation egress allowlist in S8 | `application/use_cases/chat_orchestrator.py` | 2h |
| E-12 | Per-turn audit log in S8 | New table + `ChatAuditLogger` class | 3h |

**Deliverable**: A PRD or implementation plan targeting these 6 changes as one wave.

---

### Wave 2 — P1 Follow-On (4 items, ~12 hours)
Moderate impact. Some depend on Wave 1 foundations (E-1 enables cleaner E-5).

| # | Enhancement | Depends On | Hours |
|---|-------------|------------|-------|
| E-11 | Entity dedup worker in S7 | E-1 (role taxonomy helps classify merge candidates) | 6h |
| E-2 | Lookup column JSONB in S6 | — | 3h |
| E-5 | Weighted lookup in S6/S8 | E-2 | 1h |
| E-10 | Streaming JSON in ml-clients | — | 2h |

---

### Wave 3 — P2 Infrastructure (after E-3 quality gate is live)
BFS path computation requires clean relation data. Do not implement before E-3.

| # | Enhancement | Depends On | Hours |
|---|-------------|------------|-------|
| E-4 | BFS path pre-computation, S7 | E-3 (quality gate), new `relation_paths` table | 12h |
| E-9 | Graph-enriched entity resolution | E-4 (pre-computed paths) | 8h |

---

## Part V — Answering the Original Question

**Highest return, lowest cost — in strict order:**

1. **E-8** (2h) — Layer 1 already done; add LLM Layer 2. Closes a real attack surface. Trivial effort.
2. **E-6** (4h) — Fixes the most painful operational issue (hanging AGE chat turns). Single-class change.
3. **E-3** (3h) — Eliminates the #1 S7 quality failure (phantom relations). Small promoter change.
4. **E-1** (4h) — Foundation that improves every downstream: BFS filtering, S8 routing, E-5 precision. One migration.
5. **E-7** (2h) — Prevents citation trust erosion. Pure string processing.

These five sit firmly in Quadrant I and together represent ~15 hours of work for four HIGH-impact improvements + one MEDIUM-impact security fix.

**Deprioritize for now:**
- **E-4** (BFS paths) — higher cost than stated, blocked by deferred PathInsightWorker. Wait until E-3 produces clean relation data.
- **E-9** (graph-enriched resolution) — value multiplies with E-4; implement after E-4.

---

## Part VI — Compounding Updates

### HIGH_RISK_PATTERNS.md — New Entry HR-056
**Pattern**: Agent loop tool parameter accepts tenant/user scope from LLM message payload.
Any tool call handler that accepts `tenant_id`, `user_id`, or `organization_id` as an LLM-supplied argument (rather than dispatch-injecting from the validated JWT) creates a prompt-injection privilege-escalation path. Confirmed in O-1 cross-cutting observation.
**Reference**: O-1 (this report).

### HIGH_RISK_PATTERNS.md — New Entry HR-057
**Pattern**: Evidence quality gate absent from relation promotion path.
Promoting relation evidence without a confidence threshold or evidence density check allows phantom triples from single-document LLM hallucinations to enter the knowledge graph and inflate path confidence. All relation evidence promotion paths must gate on `(evidence_density >= 0.05 OR extraction_confidence >= 0.70)`.
**Reference**: E-3 (this report).

### REVIEW_CHECKLIST.md — New Item
**Check**: "Agent loop: are citations verified against the current turn's tool result set before inclusion in the final answer?"
**When**: Any PR touching S8 `chat_orchestrator.py` or tool dispatch.
**Reference**: E-7 (this report).

### STANDARDS.md — New Entry
**Standard**: Agent loop budget defaults.
Any future agent loop implementation must enforce: `max_tokens=8_000` (soft), `max_tool_latency_s=30.0` (soft → surrender path), `max_per_tool_s=30.0` (hard via `asyncio.wait_for`), `max_iterations=6`, `max_consecutive_errors=2`. These values are derived from the Reference System and validated against worldview's query patterns.
**Reference**: E-6 (this report).
