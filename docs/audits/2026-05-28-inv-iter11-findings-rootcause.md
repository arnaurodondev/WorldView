---
id: INV-PLAN-0093-ITER-11
title: Root-Cause Investigation of Iter-11 Findings (F-LIVE-NEW-002, F-LIVE-NEW-003, F-DB-005)
date: 2026-05-28
predecessor: docs/audits/2026-05-27-qa-plan-0093-iter-11-report.md
branch: feat/plan-0089-wl-2
agents: 3 (parallel: INV-1, INV-2, INV-3)
verdict: ALL 3 ROOT CAUSES IDENTIFIED — different from iter-11 audit's diagnoses in 2 of 3 cases
---

# Investigation Report: Iter-11 Findings Root Cause Analysis

**Date**: 2026-05-28 05:41 UTC
**Investigator**: 3 parallel sub-agents orchestrated
**Severity**: CRITICAL × 1 (F-DB-005:unknown-488), HIGH × 2 (F-LIVE-NEW-002, F-LIVE-NEW-003)
**Status**: Root causes identified for all three. Mitigations recommended. **No fixes applied** (investigation only).

---

## Headline

The iter-11 chat-eval surfaced 3 findings. After deep investigation, **2 of the 3 audit diagnoses were wrong** — the real bugs are structurally simpler but architecturally more interesting:

| Finding | Iter-11 audit diagnosis | Actual root cause |
|---|---|---|
| F-LIVE-NEW-002 | "Tesla → ServiceNow miscanonicalisation in resolver" | **LLM hallucinated ServiceNow on empty-result path** — resolver was correct |
| F-LIVE-NEW-003 | "Stop-word filter doesn't apply to prompt context" | **Two ungated resolver paths** — orchestrator calls S6 directly bypassing all gates |
| F-DB-005 | "A4's schema change broke worker" | **Pre-PLAN-0093 schema mismatch** hidden by D-2 backoff freeze + lying unit tests; A4 not involved |

Two of the three findings have a common shape: **the symptom (resolver picked wrong / context contaminated / worker failed) was real, but the audit's first hypothesis was a story that fit the surface evidence**. Deeper investigation found different root causes that change the fix scope substantially.

---

## Finding 1 — F-LIVE-NEW-002 (Tesla → ServiceNow)

**Status: Audit diagnosis WRONG. Real bug: LLM hallucination on empty-result path.**

### What's actually happening
- Resolver correctly resolved "Tesla" → "Tesla Inc" (`entity_id=01900000-0000-7000-8000-000000001004`, exact canonical match, verified via live log replay)
- `get_contradictions` was called on Tesla and returned 0 rows
- The string "ServiceNow Inc (NOW)" was **fabricated by the LLM** during empty-result synthesis
- Likely trigger: phrase "right *now*" in the user message + ticker `NOW` (ServiceNow) appearing in the tool-registry system prompt

### Blast radius probe (mandatory)
Trigram probes for tesla / apple / block / square / amazon / visa **all resolve correctly** (or refuse via the 0.75 floor). **Zero misresolutions found.** The resolver is healthy. This is NOT a platform-wide resolver crisis.

### Real root cause
`services/rag-chat/src/rag_chat/application/use_cases/chat_orchestrator.py:1066-1086` — the empty-result branch sends the LLM a sparse generic prompt ("answer honestly that no data was found") that does NOT name the resolved entity. The LLM fills the void by hallucinating an entity. There is no post-generation **entity-name grounding check** (the existing `numeric_grounding_failed` only catches numbers — and indeed fired on this same request, catching the numeric part but not the entity hallucination).

### Recommended mitigation
**Option A (recommended)**:
1. Echo the resolved entity name into the empty-result user prompt: `"No contradictions found for {entity.canonical_name}. Respond accurately stating no contradictions were found for this specific entity."`
2. Add an **EntityNameGroundingValidator** mirroring `NumericGroundingValidator` (from F-CHAT-AGENT-001 / iter-9):
   - Parse all proper-noun entity names from the LLM response
   - Cross-check against the resolved-entity set + tool-result entity references
   - Fail-closed: re-prompt the LLM if it mentions an entity not in the grounded set

Effort: Low (~50 LOC + tests). Risk: Low. Reuses the validator pattern shipped in iter-9.

### Process learning
The audit grader **assumed** resolver-picked-wrong from the surface text. Future chat-eval graders should:
- Read the structured `tool_call` log to verify which entity was resolved
- Cross-check final answer against the resolved entity set
- Distinguish "resolver picked wrong entity" from "LLM mentioned wrong entity name in answer"

---

## Finding 2 — F-LIVE-NEW-003 (SpaceX in prompt context)

**Status: Audit diagnosis partially right ("two consumers, one filtered") but wrong target. Real bug: two ungated RESOLVER paths.**

### What's actually happening
- Rag-chat orchestrator runs entity resolution **TWICE via two independent paths**:
  - Path A (intelligence handler, GATED): `IntelligenceHandler._strip_stop_words` + 0.75 absolute floor + 0.15 delta — used by intelligence-tool fuzzy alias matching
  - Path B (orchestrator → S6, UNGATED): `chat_orchestrator.py:506-507` → `chat_pipeline.py:309-315` → `s6_client.py:28-54` calls S6 NLP-pipeline `/api/v1/entities/resolve` — **no stop-word, no floor, no delta**
- The S6-resolved entities (including SpaceX, `entity_id=ec9c7198-98a9-4593-ade1-9b6826db73fc`) are then written verbatim into the system prompt as an `Entities resolved from this query:` block at `chat_orchestrator.py:549-557`

### Smoking-gun evidence
A fresh (non-cached) Q6 run produced an LLM answer that says verbatim:
> "The entity 'Space X' (entity_id=ec9c7198-…) was resolved, but none of the tool responses … mention Space X"

The tool_result events for Q6 (4 tools) contain **zero** occurrences of "space". The contamination is in the entity-map prompt section, NOT in tool output.

### Blast radius
**NOT SpaceX-specific.** Any generic English token in a query that is a substring of an indexed canonical will leak via Path B:
- `space` → SpaceX
- `delta` → Delta Air Lines
- `shell` → Shell plc
- `block` → Block Inc
- `square` → Square (predecessor)

Probe queries:
- "renewable energy" → clean (no canonical matches "renewable")
- "healthcare companies" → inconclusive (latency timeout)

### Completion-cache amplification
The user-reported Q6 reproduction hits a `cache_hit` SSE event and replays the dirty answer with no tools at all. **Even after a fix, cached entries will keep returning dirty answers until the cache is purged.**

### Recommended mitigation
**Option A (recommended — narrow)**:
- Apply the same stop-word / floor / delta gates on the orchestrator side, **post-S6**, before building `_entity_map_section`
- Symmetric with `IntelligenceHandler`, reuses existing settings (`RAG_CHAT_RESOLVER_TOP_SIMILARITY_MIN`, `RAG_CHAT_RESOLVER_SIMILARITY_DELTA_MIN`, `RAG_CHAT_RESOLVER_STOP_WORDS`)
- ~20-line addition in `chat_orchestrator.py:506-507` + regression test
- Add a completion-cache purge step in the same commit

**Option B (long-term, structurally cleaner)**:
- Push gates into the S6 endpoint itself
- All consumers benefit automatically
- Larger blast radius — needs contract testing across all S6 callers

Effort A: Low. Effort B: Medium. Risk B: Medium (other S6 consumers may rely on the ungated behaviour).

### Key correction to iter-11 audit
The audit's BP-NEW-B described "filtered vs unfiltered LIST read by two consumers". Reality: "**filtered vs unfiltered RESOLVER called by two consumers**". Renderer and tool output were both clean — the bug was upstream in the resolver invocation.

---

## Finding 3 — F-DB-005 (fundamentals worker 0/811)

**Status: Audit diagnosis WRONG. Real bug: pre-PLAN-0093 schema mismatch hidden by D-2 backoff freeze. A4 is NOT the culprit.**

### What's actually happening (3 independent root causes)

**`unknown: 488` (60%) — SCHEMA MISMATCH (the biggest bug)**:
- `services/knowledge-graph/src/knowledge_graph/infrastructure/workers/fundamentals_refresh.py:1049-1061` reads top-level keys: `revenue_usd_millions`, `pe_ratio`, `price`, etc.
- The market-data endpoint `GET /api/v1/fundamentals/{instrument_id}` has **always returned** `{security_id, records: [{section, payload, ...}, ...]}` (see `schemas/fundamentals.py:24-28`)
- Every metric resolves to `None` → `_build_fundamentals_narrative()` falls through "only header built" guard → returns `None`
- Worker's `(None, None)` tuple maps to `failure_reason="unknown"` via the `or "unknown"` fallback at line 543
- **Unit tests have been lying** — they stub the flat shape the worker expects (which never matched production)
- Bug pre-dates PLAN-0093; the D-2 backoff freeze hid it for months

**`instrument_lookup_failed: 312` (38%) — DATA GAP, not a worker bug**:
- 1100 ticker'd FI canonicals in `intelligence_db.canonical_entities` vs only **629** symbols in `market_data_db.instruments`
- S6 enrichment creates canonicals for tickers never imported (delisted / foreign / long-tail)
- 323 × 404 on `/instruments/lookup` confirms

**`http_404: 11` (1%) — LEGITIMATE**: Instruments exist in `instruments` table but EODHD has no fundamentals records.

### What was refuted
- **A4 hypothesis (H1) REFUTED**: A4's `984e7c27` only added optional `period_type` to `/fundamentals/history`. The worker doesn't even hit that endpoint.
- **Connection-pool hypothesis (H4) REFUTED**: HTTP transport is healthy — 987 × 200, 323 × 404, zero 5xx, zero exceptions.

### Recommended mitigation

**For `unknown: 488` (highest priority)**:
- Walk `fundamentals["records"]` by section in `_build_fundamentals_narrative` (HIGHLIGHTS → PE / price / 52w; INCOME_STATEMENT → revenue / margins)
- **Delete the `or "unknown"` fallback at line 543** → replace with explicit `(None, "fundamentals_empty_payload")` so this class of bug screams loudly instead of hiding
- Fix the unit tests to stub the REAL response shape (BP candidate — tests that lie are worse than no tests)

**For `instrument_lookup_failed: 312`**:
- Long-skip rows whose ticker doesn't exist in market-data (`next_refresh_at='9999-01-01'` or new state column)
- Or: import the missing 471 tickers (1100 - 629) into market-data via the standard ingestion path

**For `http_404: 11`**:
- Long-skip after 3 consecutive 404s — don't waste retry cycles on EODHD-empty tickers

**Cross-cutting**:
- Add a contract test that boots market-data with one real instrument and asserts `refreshed >= 1` (the unit tests pass with the wrong shape; only a contract test catches the actual mismatch)
- Add Prometheus metrics per error class so `unknown` is impossible to ignore in future

---

## Cross-Finding Patterns

Two of the three findings share a structural class — **silent failure masking a real bug**:

| Pattern | Where seen | Why it hides | How to fix |
|---|---|---|---|
| **Fallback-to-generic-error** | F-DB-005:488 (`or "unknown"`) + F-LIVE-NEW-002 (empty-result generic prompt) | Failures classify as "unknown" / "no data" instead of the structural cause | Replace fallback with structured error class; metric per class |
| **Two paths, one filtered** | F-LIVE-NEW-003 (resolver-via-handler vs resolver-via-orchestrator) | A fix shipped on one path; the other path still produces unfiltered output | Symmetry test: anytime a filter is added to a function, find ALL callers of equivalent functions |
| **Lying tests** | F-DB-005:488 (unit tests stub wrong shape) | Tests pass green; production hits real shape and fails | Contract tests + canary integration test that uses the actual service, not a mock |
| **Audit narrative bias** | F-LIVE-NEW-002 + F-LIVE-NEW-003 (both misdiagnosed) | The first hypothesis that fits the surface evidence becomes the story | Auditors should ALWAYS verify against structured logs (tool_call sequence, resolver decision logs), not just final-answer text |

These four patterns ladder up to **a single BP-NEW (BP-589): "fallback-to-generic-error masks structural bugs"**.

---

## Recommended Fix Scope

These 3 findings naturally form one focused plan. Suggest **PLAN-0099** with 3 waves:

### Wave 1 — Entity-name grounding (F-LIVE-NEW-002)
- Add `EntityNameGroundingValidator` to `services/rag-chat/src/rag_chat/application/services/`
- Echo resolved entity name in empty-result prompt
- 2-3 regression tests covering Tesla/SpaceX/cached responses
- **Effort: 0.5 day**

### Wave 2 — Symmetric resolver gates (F-LIVE-NEW-003)
- Apply stop-word + floor + delta gates on orchestrator path post-S6
- Purge completion-cache in the same commit
- Add a contract test: 5 queries with stop-word-substring tokens (space, delta, shell, block, square) must not produce contaminated entity-map sections
- **Effort: 0.5 day**

### Wave 3 — Fundamentals worker + lying-test cleanup (F-DB-005)
- Fix `_build_fundamentals_narrative` to walk `records` by section
- Replace `or "unknown"` with explicit `"fundamentals_empty_payload"` + Prometheus counter per error class
- **Update unit tests to stub real response shape** (CRITICAL — lying tests are how this bug hid for months)
- Long-skip the 312 + 11 rows that have legitimate data gaps
- Add a contract test against a live market-data instance
- **Effort: 1 day**

**Total estimated effort**: 2 engineer-days. Could ship as a single feature branch with 3 commits.

---

## Compounding

### BP-NEW Candidate: BP-589 "Fallback-to-generic-error masks structural bugs"

**Pattern**: A function returns `(None, None)` or raises a generic exception when its happy path fails. A higher layer translates this into a generic error string (`"unknown"`, `"no data found"`, `[]`). The actual structural bug (schema mismatch, missing entity, deserialisation error) becomes invisible.

**Detection**: search for `or "unknown"`, `or []`, `except Exception: return None`, `except Exception: return ([], [])`. Any of these mask a class of bugs.

**Fix**: Replace generic fallbacks with **structured error classifications**:
```python
# BAD
result, reason = await build_or_fail()  # tuple of (None, None) on fail
return result or "unknown"

# GOOD
result_or_error = await build_or_fail()  # returns Result | StructuredError
if isinstance(result_or_error, StructuredError):
    metrics.fundamentals_refresh_failed.labels(reason=result_or_error.kind).inc()
    log.warning("fundamentals_refresh_failed", error_kind=result_or_error.kind, ticker=ticker, ...)
    return result_or_error  # propagates kind: "schema_mismatch" / "empty_payload" / "transport"
```

**Add to `docs/BUG_PATTERNS.md`**.

### BP-NEW Candidate: BP-590 "Lying tests stub a shape the production endpoint never returns"

**Pattern**: Unit tests for a worker/client stub the response shape the WORKER expects. The production endpoint returns a DIFFERENT shape. Tests pass; production silently fails.

**Detection**: any test fixture that hard-codes a response shape without referring to the canonical schema (`schemas/*.py`) or running an actual integration call.

**Fix**: Contract test that boots the real upstream service (or a mock generated from the canonical schema) and asserts the consumer can parse it.

### HR-NEW Candidate: HR-056 "Audit narrative bias"

When an auditor sees a symptom (e.g. "Tesla resolves to ServiceNow") the first hypothesis that fits the surface evidence becomes the story. **Always cross-check against structured logs** (tool_call sequence, resolver decision logs, metric values) before declaring a root cause.

**Add to `.claude/review/heuristics/HIGH_RISK_PATTERNS.md`**.

### Skill improvement: `.claude/skills/qa/SKILL.md`

The iter-11 chat-eval grader misdiagnosed 2 of 3 findings. Add:
> When the chat answer mentions an entity that seems wrong, the grader MUST cross-check the structured `tool_call` log to verify which entity was actually resolved by the system. Distinguish "resolver picked wrong entity" from "LLM mentioned wrong entity name in answer". These are different bug classes requiring different fixes.

### Process learning

The "D-2 backoff freeze masked a months-old schema mismatch" is the third recurrence of the **"implementation code is clean but data layer doesn't deliver"** pattern (BP-571 from iter-9). The new evidence strengthens the case for: **every wave's done-definition must include a live SLO query verifying the fix works on real data, not just unit-test green**.

---

## Open Questions

1. **Resolver path B (S6 NLP-pipeline `/api/v1/entities/resolve`)** — how many OTHER rag-chat consumers call this without applying gates? Worth a sweep before deciding between mitigation Option A (orchestrator-side) vs Option B (S6-side).

2. **Completion cache** — what's the cache TTL? Should the cache key include the resolver version so stale answers self-evict when resolver behaviour changes?

3. **`unknown: 488` masked for months** — what other backoff-frozen workers might be hiding similar schema mismatches? Recommend a sweep of every worker that classifies errors as `"unknown"` or returns `None` on fallback paths.

---

## Source Reports

Raw investigation outputs (more detail than this consolidation):
- `/tmp/inv-F-LIVE-NEW-002-report.md`
- `/tmp/inv-F-LIVE-NEW-003-report.md`
- `/tmp/inv-F-DB-005-report.md`

---

**Verdict**: 3/3 root causes identified. **2/3 audit diagnoses corrected**. All findings fit a focused 2-engineer-day plan (suggest PLAN-0099). 2 BP-NEW + 1 HR-NEW + 1 skill improvement added to the compounding catalogue.

**Recommended next step**: `/plan` to scope PLAN-0099 covering Waves 1-3 above. Then `/implement` per wave.
