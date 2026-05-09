---
id: PLAN-0084
prd: docs/audits/2026-05-07-investigate-w5-5b-and-strategic-direction.md
prd_section: "All sections (this is a /investigate-driven hardening plan; no formal PRD)"
title: "W5-5b — Operating-Table Hardening (PLAN-0063 close-out)"
status: in-progress
created: 2026-05-07
updated: 2026-05-09
waves_done: "A-1, A-2, B-1, B-2, B-3, C-1, D-1, D-2, D-3, E-1, E-2, E-3, F-1, H-1 (2026-05-07); G-1 gated — labelling reached 88.3% (106/120) on 2026-05-09, stack required to run sweep"
plans: 8
waves: 15
tasks: 48
critical_path: "A-1 → B-1 → B-2 → B-3 (consumer idempotency); D-1/D-2/D-3 parallel after A-1; E-3 gated on E-1+E-2; G-1 gated on E-3 + ≥80% labelling"
locked_answers: |
  Q1 (consumer idempotency scope): all 8 consumers — single platform rule, one architecture test, eliminates dialect drift.
  Q2 (CI gate): investigate result-instability BEFORE flipping continue-on-error. Add smoke probe + per-class regression check first.
  Q3 (product sequencing): CLI/multi-panel BEFORE strategy-builder; this plan delivers neither — it delivers the operating-table foundation only.
  Q4 (labelling): single-reviewer accepted for thesis; second-pass labelling tracked as post-MVP work; flag baseline metadata with single_reviewer: true.
---

# PLAN-0084 — W5-5b Operating-Table Hardening

## 0. Pre-Flight Summary

**Source**: 2026-05-07 `/qa` pass on PLAN-0063 surfaced 2 BLOCKING + 5 CRITICAL + 29 MAJOR findings. Two of the BLOCKING items were auto-fixed in the QA close-out commit (F-D01 stale schema names in PLAN-0064; F-D02 BP-403 numbering collision). The remaining items map to behavioural correctness gaps that prevent the platform from operating reliably under any meaningful load. The 2026-05-07 `/investigate` report (`docs/audits/2026-05-07-investigate-w5-5b-and-strategic-direction.md`) traced root causes, confirmed the fix shapes against existing platform conventions, and locked four strategic questions with the user.

**This plan exists** because PLAN-0063 W5-5 was marked DONE on 2026-05-07 with the citation-accuracy cron implemented but never wired in `lifespan` — the W5-5 deliverable is therefore not actually live, and the `rag_citation_accuracy` Prometheus gauge is unreachable. Combined with the circuit-breaker stampede (F-X01), the canonical-tickers cache staleness (F-X02), the consumer idempotency dialect drift (F-X11/F-X12/F-D03), and the fail-open CI gate (F-X09), the platform's "operating-table competence" — the boring discipline that lets you observe and trust the system — is incomplete. This plan closes that gap before any new feature work (W5-6, W6, PLAN-0067 tool catalog) lands on top.

**Why a single plan rather than 8 separate ones**: the fixes are tightly coupled — `ValkeyDedupMixin` (Sub-Plan B) is the right shape because four KG consumers already implement it ad-hoc, and migrating the article consumer to the mixin requires the deterministic-ID changes to be safe under at-least-once fallback. The CI gate hardening (Sub-Plan E) can only flip `continue-on-error: false` once the result-instability investigation closes (E-3), which itself benefits from snapshot-isolation hooks added by Sub-Plan B. The port-ABC extraction (Sub-Plan D) is sequenced before PLAN-0067 begins so the IntentClassifier deletion in PLAN-0067 W11-3 is mechanical instead of a sed-and-pray refactor.

**What this plan does NOT cover**:
- **CLI command palette + multi-panel layout** — these are PLAN-0085 (3-9 month bucket), not this plan. Q3 confirms CLI-before-strategy-builder, but neither lands here.
- **Intelligence-grounded strategy builder + LEAN engine** — PLAN-0086 (6-12 month bucket).
- **Sandbox / signal-discovery / AI strategy editor** — PLAN-0087 (9-18 month bucket).
- **Second-reviewer labelling pass on the 120-query golden set** — Q4 confirms single-reviewer is acceptable for thesis defense; the second-pass wave is tracked as a post-MVP work item but is not a wave in this plan.
- **W5-6 ingestion bench thresholds** — PLAN-0063 W5-6 is a separate wave already on the books; this plan touches only documentation that W5-6 will measure against.

### 0.1 Cross-Plan Decisions (locked 2026-05-07 via /investigate — DO NOT re-litigate during /implement)

| # | Decision | Rationale |
|---|---|---|
| L1 | **All 8 consumers migrate to `ValkeyDedupMixin`**, not just the article + KG consumers. The 3 market-data consumers (`OhlcvConsumer`, `FundamentalsConsumer`, `IntraDayResamplingConsumer`) currently rely on `create_if_not_exists()` natural-key idempotency; they migrate too for consistency, with their docstring noting that the mixin is belt-and-braces over the natural-key guarantee. | Q1 locked — eliminates dialect drift; one architecture test enforces compliance; one failure model. |
| L2 | **Deterministic IDs (`uuid5_from_parts`) in `ArticleProcessingConsumer._run_pipeline`** for every row whose identity is fully determined by the upstream message. Specifically: `routing_decisions.decision_id`, `entity_mentions.mention_id`, `embeddings.embedding_id`, outbox `event_id` for `nlp.article.enriched.v1` and `nlp.signal.detected.v1`. Other consumers' deterministic-ID treatment is **deferred** to a later sub-plan if/when needed — this plan addresses only the article path because that's where the QA finding pointed. | The mixin is the fast-path; deterministic IDs are the safety net. Both are required to make the at-least-once Valkey fallback safe. |
| L3 | **Result-instability investigation BEFORE CI-gate flip.** The W5-3 baseline-capture audit flagged run-to-run NDCG variance incompatible with a 0.03 threshold. Flipping `continue-on-error: false` immediately would create a noisy gate engineers learn to distrust. Sub-Plan E ships smoke probe + per-class regression check now (E-1+E-2), then investigates instability (E-3), then flips the flag. | Q2 locked — gate must fail for *meaningful* regressions, not noise. |
| L4 | **CitationJudgeAdapter wraps an existing LLM provider**, not a new LLM client. Specifically `services/rag-chat/src/rag_chat/infrastructure/llm/` already has provider clients (DeepInfra/Groq/Ollama); the adapter exposes `LLMJudgePort.score_citation` by delegating to one provider with `temperature=0` and `max_tokens=1`. Provider choice is `Settings.citation_judge_provider: Literal["deepinfra", "ollama"] = "deepinfra"` so dev can use Ollama and prod uses DeepInfra. | Reuses existing LLM client wiring; avoids a parallel client class. |
| L5 | **Citation cron disabled by default.** New `Settings.citation_cron_enabled: bool = False` env var. Wave A-1 ships the wiring; production rollout flips the flag in `configs/docker.env`. Avoids unintended ~$0.50/run LLM cost on first deploy. | Pairs with the cron wiring so the BLOCKING gauge-unreachable issue is closed structurally; flag-controlled rollout is the platform convention (e.g. `internal_jwt_skip_verification`). |
| L6 | **Boost sweep gated on E-3 (instability) AND ≥80% labelling.** Currently 61/120 (51%). Sub-Plan G runs after E-3 closes; if labelling is still below 80% at that point, defer G. The placeholder value of 1.5 is documented and acceptable until then. | Locking the optimum against an unstable baseline encodes noise into a config knob. |
| L7 | **3 port-ABCs extracted in parallel (D-1/D-2/D-3 independent)**: `ChunkSearchPort`, `CanonicalEntityPort`, `IntentClassifierPort`. Each is a standalone wave; no cross-port dependencies. | These can run in parallel worktrees — no shared state. Sequencing-after PLAN-0067 starts is OK as long as PLAN-0067 W11-3 begins after D-3. |
| L8 | **Single-reviewer flag added to baseline metadata.** `results/baseline_pre_hybrid.json` and `results/eval_post_hybrid.json` get `"single_reviewer": true` in their metadata header. Wave F-1 ships this. The thesis methodology section documents the limitation. Second-pass labelling is tracked as POST-MVP, not a wave in this plan. | Q4 locked. |

---

## 0.2 Plan Dependency Graph

```
                    ┌────────────────────────────────────────────────────┐
                    │  Sub-Plan A — rag-chat behavioral hardening (2W)  │
                    │  A-1: Citation cron wiring + S1 fence + timeout   │
                    │  A-2: Circuit breaker probe gating + cooldown      │
                    └────────────────┬───────────────────────────────────┘
                                     │
       ┌─────────────────────────────┼─────────────────────────────┐
       │                             │                             │
       ▼                             ▼                             ▼
┌─────────────────────┐   ┌─────────────────────┐   ┌────────────────────────┐
│ Sub-Plan B — Cons.  │   │ Sub-Plan C —        │   │ Sub-Plan D — Port ABCs │
│ idempotency (3W)    │   │ nlp-pipeline cache  │   │ (3 parallel waves)     │
│ B-1: ValkeyDedupMix │   │ C-1: tickers refresh│   │ D-1: ChunkSearchPort   │
│ B-2: Migrate 7 cons │   │     + atomic swap   │   │ D-2: CanonEntityPort   │
│ B-3: ArticleCons +  │   │                     │   │ D-3: IntentClassPort   │
│      uuid5 IDs      │   │                     │   │                        │
└─────────┬───────────┘   └──────────┬──────────┘   └────────────┬───────────┘
          │                          │                            │
          └──────────────────────────┼────────────────────────────┘
                                     ▼
                      ┌──────────────────────────┐
                      │ Sub-Plan E — CI gate (3W)│
                      │ E-1: Smoke probe         │
                      │ E-2: Per-class regress   │
                      │ E-3: Instability invest. │
                      │     → flip continue-on-  │
                      │       error              │
                      └────────────┬─────────────┘
                                   │
       ┌───────────────────────────┼─────────────────────────┐
       ▼                           ▼                          ▼
┌──────────────────┐    ┌──────────────────┐    ┌─────────────────────┐
│ Sub-Plan F (1W)  │    │ Sub-Plan G (1W)  │    │ Sub-Plan H (1W)     │
│ F-1: Migration   │    │ G-1: Boost sweep │    │ H-1: STANDARDS/RULES│
│ LOCK + storage   │    │  (gated on ≥80%  │    │  + new BPs          │
│ doc + single_rev │    │  labelling)      │    │                     │
└──────────────────┘    └──────────────────┘    └─────────────────────┘
```

**Critical path**: A-1 → B-1 → B-2 → B-3 (consumer idempotency is the longest chain; ~2 dev-days).
**Parallel-friendly**: D-1/D-2/D-3 + C-1 + F-1 all independent; can run in parallel worktrees.
**Gates**:
- E-3 (CI flip) gated on E-1 + E-2.
- G-1 (boost sweep) gated on E-3 + labelling ≥80% (currently 51%; this plan does NOT include labelling work — see Q4 lock).
- H-1 should be the last wave; consolidates patterns observed across all earlier waves.

---

## 0.3 Codebase State Verification (Mandatory — Phase 1.3)

| PRD Reference | Type | Service | Actual current state (verified) | Plan expected state | Delta |
|---|---|---|---|---|---|
| `BaseKafkaConsumer.is_duplicate(event_id) -> bool` | abstract method | libs/messaging | Abstract; subclass-owned | NEW `ValkeyDedupMixin` provides default impl | new mixin class |
| `ScoreCitationAccuracyUseCase` | use case | rag-chat | Implemented at `application/use_cases/score_citation_accuracy.py:87`, never instantiated in app.py | Wired in lifespan | new lifespan branch |
| `start_citation_accuracy_cron` | function | rag-chat | Defined at `infrastructure/jobs/citation_accuracy_cron.py:66`, no caller | Called from lifespan | new caller |
| `LLMJudgePort.score_citation` | Protocol method | rag-chat | Defined at `application/use_cases/score_citation_accuracy.py:54`, no impl | NEW `CitationJudgeAdapter` impl | new adapter class |
| `_CITATION_RUBRIC` (template) | constant | rag-chat | Fences only `{snippet}`, not `{claim}` | Fence both with delimiters; cap input length | edit template |
| `SourceCircuitBreaker.is_open()` | method | rag-chat | Returns `state == "open"`; no probe gating | SETNX probe slot before admit | new branch |
| `SourceCircuitBreaker.cool_down_seconds` | field | rag-chat | Default `3600` | Default `120` | constant change |
| `SourceCircuitBreaker.record_success()` | method | rag-chat | DEL+DEL pipeline (transaction=False) | Lua script OR transaction=True OR TTL-driven | edit |
| `CanonicalTickersCache.refresh()` | method | nlp-pipeline | Exists; called once at startup | Call from a 600s background loop | new task in `startup()` |
| `CanonicalTickersCache.refresh()` swap | method body | nlp-pipeline | DEL+SADD `pipeline()` (transaction=False) | `pipeline(transaction=True)` OR Lua | edit |
| `ArticleProcessingConsumer.is_duplicate` | method | nlp-pipeline | Returns `False` hard-coded | Inherited from `ValkeyDedupMixin` | delete + inherit |
| `ArticleProcessingConsumer.routing_decisions.decision_id` | ID generation | nlp-pipeline | `common.ids.new_uuid7()` (line 362) | `uuid5_from_parts(doc_id, "routing_decision")` | replacement |
| Other 7 consumers (Ohlcv, Fundamentals, IntraDay, Enriched, EntityCreated, TemporalEvent, ProvisionalQueued) | classes | various | Mix of hand-rolled Valkey + return False | All inherit `ValkeyDedupMixin` | refactor (no behavior change for the 4 that already do this) |
| `EnhancedChunkSearchUseCase` `chunk_ann_repo` | type annotation | nlp-pipeline | `ChunkANNRepository` (concrete from infra) | `ChunkSearchPort` (NEW ABC) | retype |
| `ChunkANNRepository` | class | nlp-pipeline | `infrastructure/nlp_db/repositories/chunk_search.py:25` | Implements `ChunkSearchPort` | inheritance + decorator |
| `CanonicalEntityRepository` | class | nlp-pipeline | `infrastructure/intelligence_db/repositories/canonical_entity.py:20` | Implements `CanonicalEntityPort` | inheritance |
| `OllamaIntentClassifier` / `DeepInfraIntentClassifier` | classes | rag-chat | Duck-typed; share method signature | Implement `IntentClassifierPort` Protocol | Protocol declaration + retype use case args |
| `.github/workflows/retrieval-eval.yml:137` | workflow flag | infra | `continue-on-error: true` | Removed (after E-3) | edit |
| `scripts/eval_retrieval.py:559` | exit code | scripts | `return 0` on empty per_query | Conditional: 0 if `<50 labelled`, 1 otherwise | edit |
| `eval_retrieval.py` | new flag | scripts | No `--fail-on-regression-per-class` | NEW flag for per-class threshold | new arg + logic |
| Migration `0026_add_canonical_entities_dedup_index.py` | file | intelligence-migrations | DO block; no LOCK at top | Add `LOCK TABLE ... IN ACCESS EXCLUSIVE MODE NOWAIT` | edit |
| Migration `0017_add_chunks_tsv_english_gin.py` | docstring | nlp-pipeline | No storage budget | Append "Forward-compatibility / storage budget" notes | docstring edit |
| `results/baseline_pre_hybrid.json` | metadata | (artifact) | No `single_reviewer` flag | Add `"single_reviewer": true` | JSON edit |
| `results/eval_post_hybrid.json` | metadata | (artifact) | No `single_reviewer` flag | Add `"single_reviewer": true` | JSON edit |

All deltas have a wave covering them.

---

## 0.4 Name Verification (Mandatory — Phase 1.4 / BP-405 guard)

Every name referenced in this plan body has been verified against the repo:

| Name kind | Name | Status |
|---|---|---|
| Class (existing) | `BaseKafkaConsumer`, `ValkeyClient`, `ScoreCitationAccuracyUseCase`, `LLMJudgePort`, `SourceCircuitBreaker`, `CanonicalTickersCache`, `IntelligenceDBCanonicalTickerSource`, `ArticleProcessingConsumer`, `EnrichedArticleConsumer`, `EntityCreatedConsumer`, `TemporalEventConsumer`, `ProvisionalQueuedConsumer`, `OhlcvConsumer`, `FundamentalsConsumer`, `IntraDayResamplingConsumer`, `ChunkANNRepository`, `CanonicalEntityRepository`, `OllamaIntentClassifier`, `DeepInfraIntentClassifier`, `RetrieveOnlyUseCase`, `EnhancedChunkSearchUseCase` | verified — all exist |
| Class (NEW — created in this plan) | `ValkeyDedupMixin`, `CitationJudgeAdapter`, `ChunkSearchPort`, `CanonicalEntityPort`, `IntentClassifierPort` | NEW (tagged below at first mention) |
| Function (existing) | `start_citation_accuracy_cron`, `uuid5_from_parts`, `common.ids.new_uuid7`, `common.time.utc_now` | verified |
| File path (existing) | `services/rag-chat/src/rag_chat/app.py`, `services/rag-chat/src/rag_chat/infrastructure/jobs/citation_accuracy_cron.py`, `services/rag-chat/src/rag_chat/application/pipeline/circuit_breaker.py`, `services/nlp-pipeline/src/nlp_pipeline/infrastructure/cache/canonical_tickers_cache.py`, `services/nlp-pipeline/src/nlp_pipeline/infrastructure/messaging/consumers/article_consumer.py`, `services/intelligence-migrations/alembic/versions/0026_add_canonical_entities_dedup_index.py`, `services/nlp-pipeline/alembic/versions/0017_add_chunks_tsv_english_gin.py`, `.github/workflows/retrieval-eval.yml`, `scripts/eval_retrieval.py`, `libs/common/src/common/ids.py`, `libs/messaging/src/messaging/kafka/consumer/base.py`, `libs/messaging/src/messaging/valkey/client.py` | all verified via `ls` / `git grep` |
| File path (NEW) | `libs/messaging/src/messaging/kafka/consumer/dedup.py`, `services/rag-chat/src/rag_chat/infrastructure/llm/citation_judge_adapter.py`, `services/nlp-pipeline/src/nlp_pipeline/application/ports/chunk_search.py`, `services/nlp-pipeline/src/nlp_pipeline/application/ports/canonical_entity.py`, `services/rag-chat/src/rag_chat/application/ports/intent_classifier.py`, `tests/architecture/test_consumer_dedup_mixin_enforcement.py` | NEW (created by this plan) |
| Env var (existing) | `INTERNAL_JWT_SKIP_VERIFICATION`, `RAG_CHAT_URL`, `EVAL_INTERNAL_JWT`, `DEEPINFRA_API_KEY` | verified |
| Env var (NEW) | `RAG_CHAT_CITATION_CRON_ENABLED`, `RAG_CHAT_CITATION_JUDGE_PROVIDER`, `RAG_CHAT_CITATION_MIN_SAMPLES`, `RAG_CHAT_CB_COOL_DOWN_SECONDS`, `NLP_PIPELINE_CANONICAL_TICKERS_REFRESH_INTERVAL_S` | NEW |

No unverified targets. BP-405 guard satisfied.

---

## Sub-Plans

The remainder of this file decomposes the 8 sub-plans into waves and tasks. Each wave is a single `/implement` session.

> Open the plan section for the wave you intend to run; do not load other sub-plans into context unless explicitly cross-referenced.


---

## Sub-Plan A — rag-chat Behavioural Hardening

**Service**: `services/rag-chat/`
**Waves**: A-1 (citation cron), A-2 (circuit breaker)
**Depends on**: none (root of critical path)
**Estimated effort**: ~half a day total

### Wave A-1: Citation Cron Wiring + Prompt Fence + Timeout + Done-Callback ✅ DONE 2026-05-07

**Goal**: Make the W5-5 citation-accuracy gauge actually report. Wire `ScoreCitationAccuracyUseCase` + `start_citation_accuracy_cron` in the rag-chat lifespan, behind an opt-in flag, with per-call timeout and a crash-surfacing done-callback. Fence the LLM-judge prompt against injection.

**Closes**: F-A01 (BLOCKING), F-X06, F-X07, F-S01.
**Depends on**: none
**Architecture layer**: API + application + infrastructure
**Estimated effort**: 3-4 hours

#### Pre-read
- `services/rag-chat/src/rag_chat/app.py` (full file — lifespan structure)
- `services/rag-chat/src/rag_chat/application/use_cases/score_citation_accuracy.py`
- `services/rag-chat/src/rag_chat/infrastructure/jobs/citation_accuracy_cron.py`
- `services/rag-chat/src/rag_chat/infrastructure/llm/` (existing provider clients)
- `services/rag-chat/src/rag_chat/config.py` (Settings class for env vars)
- `libs/messaging/src/messaging/kafka/consumer/base.py:753-762` (BP-268 done-callback pattern to mirror)

#### Tasks

##### T-A-1-01: Add config knobs to `RagChatSettings`
**Type**: config
**depends_on**: none
**blocks**: T-A-1-02, T-A-1-03
**Target files**:
- `services/rag-chat/src/rag_chat/config.py` (edit `RagChatSettings`)
- `configs/dev.local.env.example` (document new vars)

**What to build**: Add four settings:
- `citation_cron_enabled: bool = False` (env: `RAG_CHAT_CITATION_CRON_ENABLED`)
- `citation_judge_provider: Literal["deepinfra", "ollama"] = "deepinfra"` (env: `RAG_CHAT_CITATION_JUDGE_PROVIDER`)
- `citation_min_samples: int = Field(default=10, ge=1, le=500)` (env: `RAG_CHAT_CITATION_MIN_SAMPLES`)
- `citation_call_timeout_s: float = Field(default=15.0, gt=0.0, le=120.0)` (env: `RAG_CHAT_CITATION_CALL_TIMEOUT_S`)

All defaults preserve backward compatibility — cron stays off by default.

**Tests to write**:
| Test | What it verifies | Type |
|---|---|---|
| `test_citation_settings_defaults` | All four fields default to documented values | unit |
| `test_citation_judge_provider_validates_enum` | Invalid provider raises ValidationError | unit |
| `test_citation_call_timeout_bounds` | Timeout > 0.0 and ≤ 120.0 enforced | unit |

**Acceptance criteria**:
- [ ] `Settings()` constructs with no env vars set (defaults applied)
- [ ] `RAG_CHAT_CITATION_CRON_ENABLED=true` env var flips the bool
- [ ] `configs/dev.local.env.example` documents all four vars with comments

##### T-A-1-02: Implement `CitationJudgeAdapter` (NEW — created in this plan)
**Type**: impl
**depends_on**: T-A-1-01
**blocks**: T-A-1-04
**Target files**:
- `services/rag-chat/src/rag_chat/infrastructure/llm/citation_judge_adapter.py` (NEW)
- `services/rag-chat/tests/unit/infrastructure/llm/test_citation_judge_adapter.py` (NEW)

**What to build**: A class implementing `LLMJudgePort` (defined at `score_citation_accuracy.py:54`). Delegates to an existing LLM provider client (DeepInfra or Ollama, selected by `Settings.citation_judge_provider`). The `score_citation` method:
1. Wraps the underlying provider call in `asyncio.wait_for(..., timeout=settings.citation_call_timeout_s)`.
2. On `asyncio.TimeoutError`, logs `citation_judge_timeout` at WARNING and raises `LLMJudgeTimeoutError` (NEW domain exception). The use case's outer try/except already handles ValueError; extend it to handle this new exception by skipping the pair (see T-A-1-04).
3. Sends the prompt with `temperature=0.0`, `max_tokens=2` (single digit + safety margin).
4. Returns the raw response string for the use case to parse.

**Entities**:
- **Class**: `CitationJudgeAdapter`
- **Constructor**: `__init__(self, provider_client: Any, *, timeout_s: float)`
- **Methods**: `async def score_citation(self, *, claim: str, snippet: str) -> str`
- **Invariants**: never raises beyond `LLMJudgeTimeoutError` and propagated provider errors.

**Tests to write**:
| Test | What it verifies | Type |
|---|---|---|
| `test_score_citation_happy_path` | Provider returns "2", adapter returns "2" | unit |
| `test_score_citation_timeout_raises_LLMJudgeTimeoutError` | Provider stalls 20s, timeout=1s → raises | unit |
| `test_score_citation_propagates_provider_errors` | Provider raises ConnectionError → adapter propagates | unit |
| `test_score_citation_uses_temperature_zero` | Captures provider call kwargs; asserts temp=0.0 | unit |

**Acceptance criteria**:
- [ ] Adapter implements `LLMJudgePort` (mypy verifies)
- [ ] Timeout enforced via `asyncio.wait_for`
- [ ] Provider client resolution via Settings.citation_judge_provider; constructor accepts the resolved client

##### T-A-1-03: Fence `_CITATION_RUBRIC` against prompt injection
**Type**: impl
**depends_on**: none (but parallel-safe with T-A-1-02)
**blocks**: T-A-1-04
**Target files**:
- `services/rag-chat/src/rag_chat/application/use_cases/score_citation_accuracy.py` (edit lines 35-51)
- `services/rag-chat/tests/unit/test_score_citation_accuracy.py` (add tests)

**What to build**: Fix F-S01. The current rubric fences only the snippet:
```
CLAIM: {claim}
<<<SNIPPET START>>>
{snippet}
<<<SNIPPET END>>>
```
Update to fence both, cap input lengths, and reject delimiter strings in input:

```python
_MAX_CLAIM_CHARS = 1024
_MAX_SNIPPET_CHARS = 1024
_INJECTION_TOKENS = ("<<<CLAIM ", "<<<SNIPPET ", ">>>", "Respond with ONLY")

def _sanitise(text: str, max_chars: int) -> str:
    truncated = text[:max_chars]
    for token in _INJECTION_TOKENS:
        if token in truncated:
            # Don't crash — just neutralise. Log so we can detect attacks.
            log.warning("citation_judge_input_contains_delimiter", token=token)
            truncated = truncated.replace(token, "[REDACTED]")
    return truncated
```

Rubric template:
```
CLAIM:
<<<CLAIM START>>>
{claim}
<<<CLAIM END>>>

SNIPPET:
<<<SNIPPET START>>>
{snippet}
<<<SNIPPET END>>>
```

In `execute()`, sanitise both before formatting.

**Tests to write**:
| Test | What it verifies | Type |
|---|---|---|
| `test_sanitise_truncates_long_input` | 5000-char input → 1024 chars | unit |
| `test_sanitise_neutralises_injection_tokens` | Input containing `>>>` is replaced with `[REDACTED]` | unit |
| `test_sanitise_logs_when_token_found` | structlog warning emitted | unit |
| `test_rubric_fences_both_claim_and_snippet` | Generated prompt contains both fence-pairs | unit |

**Acceptance criteria**:
- [ ] Both `{claim}` and `{snippet}` fenced
- [ ] Sanitisation applied before formatting
- [ ] Tests pass; existing happy-path tests still pass

##### T-A-1-04: Update `ScoreCitationAccuracyUseCase.execute` for timeout + error skip
**Type**: impl
**depends_on**: T-A-1-02, T-A-1-03
**blocks**: T-A-1-05
**Target files**:
- `services/rag-chat/src/rag_chat/application/use_cases/score_citation_accuracy.py` (edit `execute`, lines 103-150)
- `services/rag-chat/tests/unit/test_score_citation_accuracy.py` (add tests)

**What to build**: Catch `LLMJudgeTimeoutError` and provider exceptions in the per-claim loop; log + skip the pair, do NOT crash the cron run. Add a Prometheus counter `rag_citation_accuracy_call_failures_total` (label: `reason={"timeout","provider_error","invalid_response"}`) so partial-batch failures are visible.

```python
try:
    raw_response = await self._judge.score_citation(claim=claim_text, snippet=snippet)
except LLMJudgeTimeoutError:
    rag_citation_accuracy_call_failures_total.labels(reason="timeout").inc()
    continue
except Exception:
    rag_citation_accuracy_call_failures_total.labels(reason="provider_error").inc()
    log.warning("citation_judge_call_failed", exc_info=True)
    continue
```

Also enforce an outer wall-clock budget via `asyncio.timeout(settings.citation_run_budget_s = 600)` around the entire scoring loop (one new setting added in T-A-1-01... actually let me put it here for context — *one new field* on Settings: `citation_run_budget_s: float = Field(default=600.0)`).

**Tests to write**:
| Test | What it verifies | Type |
|---|---|---|
| `test_execute_timeout_skips_pair_and_increments_counter` | Judge raises timeout → loop continues, counter+=1 | unit |
| `test_execute_provider_error_skips_pair` | Judge raises ConnectionError → loop continues, counter+=1 | unit |
| `test_execute_run_budget_truncates_loop` | Budget=0.1s with slow judge → loop exits, partial result emitted | unit |

**Acceptance criteria**:
- [ ] Timeout exception caught + counter incremented
- [ ] All existing tests still pass
- [ ] Counter exposed on `/metrics`

##### T-A-1-05: Wire cron in lifespan + done-callback + shutdown
**Type**: impl
**depends_on**: T-A-1-04
**blocks**: T-A-1-06
**Target files**:
- `services/rag-chat/src/rag_chat/app.py` (edit `lifespan` / `_wire_orchestrator`)
- `services/rag-chat/src/rag_chat/infrastructure/jobs/citation_accuracy_cron.py` (add done-callback)
- `services/rag-chat/tests/unit/test_app_lifespan_citation_cron.py` (NEW)

**What to build**: In `lifespan` startup (only if `settings.citation_cron_enabled`):
1. Resolve the LLM provider client per `settings.citation_judge_provider`.
2. Build `CitationJudgeAdapter(provider_client, timeout_s=settings.citation_call_timeout_s)`.
3. Build `SqlAlchemyMessageRepository(read_factory)` — **MUST use read_factory** (R23).
4. Build `ScoreCitationAccuracyUseCase(message_repo, judge, min_samples=settings.citation_min_samples)`.
5. Call `task = start_citation_accuracy_cron(use_case)`; store on `app.state.citation_cron_task`.
6. Register a done-callback (mirror `BaseKafkaConsumer.run` lines 753-762, BP-268):

```python
def _on_done(t: asyncio.Task[None]) -> None:
    if t.cancelled():
        return
    exc = t.exception()
    if exc is not None:
        log.critical("citation_cron_task_crashed", exc_info=exc)
task.add_done_callback(_on_done)
```

In shutdown: `task.cancel(); await asyncio.gather(task, return_exceptions=True)`.

Also wrap `use_case.execute()` inside `_run_citation_accuracy_cron` with `asyncio.timeout(600)` (per-iteration safety net per F-X07). If timeout fires, log + reschedule for next Sunday.

**Tests to write**:
| Test | What it verifies | Type |
|---|---|---|
| `test_lifespan_starts_cron_when_enabled` | citation_cron_enabled=True → `app.state.citation_cron_task` is a non-done Task | unit (TestClient) |
| `test_lifespan_does_not_start_cron_when_disabled` | citation_cron_enabled=False → `app.state.citation_cron_task` is None | unit |
| `test_done_callback_logs_critical_on_crash` | Task raises → `log.critical` called | unit |
| `test_lifespan_shutdown_cancels_task` | Shutdown → task.cancelled() is True | unit |

**Acceptance criteria**:
- [ ] Cron task started in lifespan when flag enabled
- [ ] Done-callback registered
- [ ] Task cancelled on shutdown
- [ ] Read replica used (mypy types `read_factory` correctly)

##### T-A-1-06: Update docs
**Type**: docs
**depends_on**: T-A-1-05
**blocks**: none
**Target files**:
- `docs/services/rag-chat.md` (add "Citation accuracy cron" section)
- `services/rag-chat/.claude-context.md` (add cron + new metrics + new env vars)

**What to build**: Document the cron behaviour, the env-var rollout, the run cadence (weekly Sunday 03:00 UTC + opt-in via `RAG_CHAT_CITATION_CRON_ENABLED=true`), the gauge `rag_citation_accuracy`, the new counter `rag_citation_accuracy_call_failures_total`, and a one-line operator runbook ("if gauge unchanged for >7 days, check the cron task is alive: `curl /healthz` and grep logs for `citation_accuracy_scored`").

**Acceptance criteria**:
- [ ] Doc updated; example metric output shown
- [ ] `.claude-context.md` lists the four new env vars

#### Validation Gate
- [ ] `ruff check` + `ruff format --check` on `services/rag-chat/src/`
- [ ] `mypy services/rag-chat/src --config-file services/rag-chat/mypy.ini`
- [ ] `python -m pytest services/rag-chat/tests/ -m unit -v` — all pass; ≥10 new tests
- [ ] No architecture violations
- [ ] `docker compose build rag-chat && docker compose up -d rag-chat`; verify cron task starts when `RAG_CHAT_CITATION_CRON_ENABLED=true` (R31)

#### Break Impact
| Broken file | Why it breaks | Fix required |
|---|---|---|
| `services/rag-chat/tests/unit/test_score_citation_accuracy.py` | New `_sanitise` helper changes prompt format | Update assertions about prompt content; happy-path scoring tests unchanged |
| `services/rag-chat/tests/unit/test_metrics_emission.py` | New counter `rag_citation_accuracy_call_failures_total` registered | If using global REGISTRY assertions, add `_w55b` suffix to label values per BP-404 |

#### Regression Guardrails
- **BP-404** (Prometheus Counter `_total` suffix): use `s.name` not `m.name` when filtering REGISTRY samples in tests; use unique label values per test.
- **R23 / R27** (read replica): `SqlAlchemyMessageRepository` MUST be built with `read_factory`, not `write_factory`; `sample_recent_with_citations` is read-only.
- **R30** (per-request auth in singleton init): the cron runs as platform operator with no per-request scope; this is intentional, but document the cross-tenant read in §11 of the use case docstring (already partially done; reinforce).
- **BP-268** (done-callback pattern): mirror `BaseKafkaConsumer.run` exactly so crash surfacing is consistent.

---

### Wave A-2: Circuit Breaker SETNX Probe Gating + Lower Cooldown + Symmetric ZSET ✅ DONE 2026-05-07

**Goal**: Eliminate the F-X01 stampede on cooldown expiry; lower the F-X04 1h cooldown to 120s with operator override; fix the F-X05 record_success ZSET race so it's symmetric to the BP-403 record_failure Lua fix.

**Closes**: F-X01, F-X04, F-X05.
**Depends on**: none (parallel-safe with A-1)
**Architecture layer**: application (rag-chat pipeline)
**Estimated effort**: 2-3 hours

#### Pre-read
- `services/rag-chat/src/rag_chat/application/pipeline/circuit_breaker.py` (full file)
- `services/rag-chat/tests/unit/application/test_circuit_breaker.py` (existing tests)
- `libs/messaging/src/messaging/valkey/client.py` (`set_nx`, `execute_lua_script` helpers)
- `docs/BUG_PATTERNS.md` BP-403 (the SQLAlchemy AsyncSession entry — read for context on Lua-script pattern; see also BP-407 for the renumbered Lua/circuit-breaker entry)

#### Tasks

##### T-A-2-01: Add cooldown + probe-TTL settings
**Type**: config
**depends_on**: none
**blocks**: T-A-2-02
**Target files**:
- `services/rag-chat/src/rag_chat/config.py`
- `configs/dev.local.env.example`

**What to build**: Two new settings:
- `cb_cool_down_seconds: int = Field(default=120, ge=10, le=3600)` (env: `RAG_CHAT_CB_COOL_DOWN_SECONDS`)
- `cb_probe_ttl_seconds: int = Field(default=5, ge=1, le=30)` (env: `RAG_CHAT_CB_PROBE_TTL_SECONDS`)

**Acceptance criteria**: Settings parse from env; documented in `dev.local.env.example`.

##### T-A-2-02: Implement SETNX probe gating in `is_open` (F-X01 + F-X04)
**Type**: impl
**depends_on**: T-A-2-01
**blocks**: T-A-2-03, T-A-2-04
**Target files**:
- `services/rag-chat/src/rag_chat/application/pipeline/circuit_breaker.py`
- `services/rag-chat/tests/unit/application/test_circuit_breaker.py`

**What to build**: Modify `SourceCircuitBreaker` to gate HALF_OPEN admissions:
1. Constructor: change default `cool_down_seconds: int = 120` (was 3600); add `probe_ttl_seconds: int = 5` parameter.
2. New private key: `self._probe_key = f"rag:cb:{source}:probe"`.
3. Modify `is_open()`:

```python
async def is_open(self) -> bool:
    state = await self._valkey.get(self._state_key)
    if state == "open":
        # Cooldown still in progress — claim probe slot if expired? No, state=="open" means TTL not yet expired.
        return True
    # state is None — cooldown TTL has expired. Try to claim probe slot.
    won = await self._valkey.set_nx(
        self._probe_key, "1", ex=self._probe_ttl_seconds,
    )
    if won:
        # We are the half-open probe; admit this one request.
        log.info("circuit_breaker_probe_admitted", source=self._source)
        return False
    # Someone else is probing. Stay closed for everyone else.
    return True
```

4. On `record_success`: also delete the probe key (close cleanly).
5. On `record_failure`: if probe was held, the failure-Lua already does the right thing; nothing to add.

**Tests to write** (≥6):
| Test | What it verifies | Type |
|---|---|---|
| `test_is_open_returns_True_when_state_set` | state=open → True regardless of probe | unit |
| `test_is_open_admits_one_probe_after_cooldown` | 50 concurrent calls after expiry → exactly 1 returns False | unit (asyncio.gather) |
| `test_is_open_other_probes_return_True` | 49 of 50 see is_open()=True | unit |
| `test_record_success_clears_probe_key` | After success, probe key gone, breaker fully closed | unit |
| `test_default_cool_down_is_120s` | New constructor default | unit |
| `test_probe_ttl_default_5s` | Probe TTL default | unit |

**Acceptance criteria**:
- [ ] Concurrency test deterministic (use `asyncio.gather` over a fakeredis client)
- [ ] Existing 10 CB tests still pass

##### T-A-2-03: Fix `record_success` ZSET race (F-X05)
**Type**: impl
**depends_on**: T-A-2-02
**blocks**: T-A-2-04
**Target files**: same as T-A-2-02

**What to build**: Make `record_success` symmetric to `record_failure` (which uses Lua script per BP-407). Two viable options:
- **Option A (recommended)**: TTL-driven — only DELETE the state key + probe key; let the failures ZSET expire naturally via its existing TTL. A delayed-arrival failure that races a success then adds to an expired ZSET, which is harmless (count starts at 1, well below threshold). This is the cleanest fix; one method, three lines.
- **Option B**: Lua script for atomicity (overkill given Option A is correct).

Pick Option A. Update method body:

```python
async def record_success(self) -> None:
    # Per F-X05 fix: TTL-driven cleanup. Do NOT delete the failures ZSET — its
    # TTL will expire it naturally. Deleting it creates a race where a delayed
    # in-flight failure-record can re-create the ZSET right after the success.
    # Letting it expire eliminates the race. (BP-NEW: ZSET-driven recovery.)
    await self._valkey.delete(self._state_key)
    await self._valkey.delete(self._probe_key)
```

**Tests to write**:
| Test | What it verifies | Type |
|---|---|---|
| `test_record_success_does_not_delete_failures_zset` | After success, ZSET still exists (TTL-driven) | unit |
| `test_concurrent_failure_after_success_does_not_corrupt` | Success then fast failure record → count==1, breaker closed | unit |

##### T-A-2-04: Add `rag_circuit_breaker_open` Prometheus gauge
**Type**: impl
**depends_on**: T-A-2-02
**blocks**: T-A-2-05
**Target files**:
- `services/rag-chat/src/rag_chat/application/metrics/prometheus.py` (add gauge)
- `services/rag-chat/src/rag_chat/application/pipeline/circuit_breaker.py` (set gauge on state transitions)

**What to build**: Per F-X04 recommendation, expose breaker state for alerting.

```python
rag_circuit_breaker_open = Gauge(
    "rag_circuit_breaker_open",
    "1 if circuit breaker is open for the labelled source, 0 otherwise.",
    labelnames=["source"],
)
```

Set to 1 in `_open_breaker` (the method that writes `state="open"`); set to 0 in `record_success`. Existing tests need a labels-clean fixture per BP-404.

**Tests to write**:
| Test | What it verifies | Type |
|---|---|---|
| `test_gauge_set_to_1_on_open` | Open breaker → gauge.labels(source).get() == 1 | unit |
| `test_gauge_set_to_0_on_recovery` | record_success → gauge == 0 | unit |

##### T-A-2-05: Update docs
**Type**: docs
**depends_on**: T-A-2-04
**blocks**: none
**Target files**:
- `docs/services/rag-chat.md` (add "Circuit breaker" section with new gauge + alert recommendation)
- `services/rag-chat/.claude-context.md`

#### Validation Gate
- [ ] All existing CB tests pass
- [ ] Concurrency test (50 tasks, 1 winner) is deterministic across 10 runs
- [ ] mypy + ruff clean
- [ ] `/metrics` endpoint shows `rag_circuit_breaker_open{source="chunk"}`

#### Break Impact
| Broken file | Why | Fix |
|---|---|---|
| `services/rag-chat/tests/unit/application/test_circuit_breaker.py` | New default cooldown 120 (was 3600) | Update tests that asserted on the old default |
| `services/rag-chat/tests/unit/test_metrics_emission.py` | New gauge registered | Use unique labels per BP-404 |

#### Regression Guardrails
- **BP-407** (Lua atomicity): record_failure already uses Lua; record_success doesn't need it because TTL-driven cleanup is race-free.
- **BP-404** (Prometheus suffix): gauge name has no `_total`; `Sample.name` and `MetricFamily.name` should match.
- **DS-008** (NEW pattern, see Sub-Plan H): "circuit breaker without HALF_OPEN probe gating" — this wave establishes the canonical fix.

---


## Sub-Plan B — Consumer Idempotency Standardisation

**Service**: `libs/messaging/` + 3 services (rag-chat unaffected; nlp-pipeline + market-data + knowledge-graph affected)
**Waves**: B-1 (mixin + arch test), B-2 (migrate 7 consumers — refactor only), B-3 (article + deterministic IDs)
**Depends on**: A-1 (so the rag-chat hardening lands first; not strictly required but reduces merge conflicts)
**Estimated effort**: ~1 dev-day total

### Wave B-1: `ValkeyDedupMixin` in libs/messaging + Architecture Test

**Goal**: Codify the existing KG-consumer Valkey-dedup pattern as a shared mixin in `libs/messaging`. Add an architecture test that asserts every `BaseKafkaConsumer` subclass either inherits the mixin OR is on a documented allowlist.

**Closes**: prerequisite for B-2/B-3.
**Depends on**: none.
**Estimated effort**: 2-3 hours.

#### Pre-read
- `libs/messaging/src/messaging/kafka/consumer/base.py` (BaseKafkaConsumer contract)
- `services/knowledge-graph/src/knowledge_graph/infrastructure/messaging/consumers/enriched_consumer.py:372-398` (the canonical hand-rolled implementation we are codifying)
- `libs/messaging/src/messaging/valkey/client.py` (`exists`, `set` with `ex=` kwarg)
- `tests/architecture/test_consumer_enforcement.py` (pattern for the new arch test)

#### Tasks

##### T-B-1-01: Implement `ValkeyDedupMixin` (NEW — created in this plan)
**Type**: impl
**depends_on**: none
**Target files**:
- `libs/messaging/src/messaging/kafka/consumer/dedup.py` (NEW)
- `libs/messaging/src/messaging/kafka/consumer/__init__.py` (export)
- `libs/messaging/tests/unit/kafka/consumer/test_dedup.py` (NEW)

**Class spec**:
```python
class ValkeyDedupMixin:
    """Standard idempotency mixin for BaseKafkaConsumer subclasses.

    Implements ``is_duplicate`` and ``mark_processed`` against a Valkey set
    with a 24h TTL by default. On Valkey failure, returns False from
    ``is_duplicate`` (at-least-once fallback) and silently swallows from
    ``mark_processed``. The fallback is only safe when the consumer's
    downstream writes use deterministic IDs (uuid5_from_parts) or
    INSERT ON CONFLICT DO NOTHING; subclasses MUST document which.
    """
    _dedup_client: ValkeyClient | None
    _dedup_prefix: str  # e.g. "nlp:dedup:article_consumer"
    _dedup_ttl_seconds: int = 86400

    async def is_duplicate(self, event_id: str) -> bool: ...
    async def mark_processed(self, event_id: str) -> None: ...
```

**Logic**:
- `is_duplicate`: `if self._dedup_client is None: return False`. Else `return bool(await self._dedup_client.exists(f"{self._dedup_prefix}:{event_id}"))`. Catch `Exception`, log `dedup.valkey_check_failed`, return `False`.
- `mark_processed`: same shape; `set` with `ex=self._dedup_ttl_seconds`.

**Tests** (≥10):
| Test | Verifies |
|---|---|
| `test_is_duplicate_returns_True_when_key_exists` | After mark_processed, is_duplicate→True |
| `test_is_duplicate_returns_False_when_key_absent` | Fresh event_id → False |
| `test_is_duplicate_returns_False_when_client_None` | Disabled config → False |
| `test_is_duplicate_returns_False_on_valkey_error` | ConnectionError → False (at-least-once fallback) |
| `test_mark_processed_sets_24h_ttl` | TTL on stored key == 86400 |
| `test_mark_processed_uses_prefix` | Key includes `_dedup_prefix:{event_id}` |
| `test_mark_processed_swallows_valkey_error` | ConnectionError → no raise |
| `test_custom_ttl_seconds_respected` | 3600 TTL configured → key expires in 3600 |
| `test_concurrent_is_duplicate_returns_consistent_result` | 50 parallel checks of same id |
| `test_long_event_id_does_not_overflow` | 256-char event_id handled |

**Acceptance**:
- [ ] mypy clean; mixin types compatible with `BaseKafkaConsumer.is_duplicate`/`mark_processed` signatures
- [ ] All tests pass; uses fakeredis for isolation
- [ ] Exported from `messaging.kafka.consumer.__init__`

##### T-B-1-02: Architecture test enforces mixin on all consumers
**Type**: test
**depends_on**: T-B-1-01
**Target files**:
- `tests/architecture/test_consumer_dedup_mixin_enforcement.py` (NEW)
- `tests/architecture/_consumer_dedup_allowlist.yaml` (NEW — empty initially)

**What to build**: Walk every `BaseKafkaConsumer` subclass; assert one of:
1. `ValkeyDedupMixin` is in MRO, OR
2. The class is on the allowlist with a documented justification.

The allowlist is a YAML with `class_name`, `module_path`, `justification`, `granted_at`. Initially empty; B-2/B-3 will populate the migration. After B-2/B-3 land, the allowlist stays empty (we migrate everyone). B-1 itself ships with the test FAILING because the mixin isn't yet adopted — `pytest.mark.xfail(reason="enforced after B-2/B-3")` until B-3 lands; flip to `xfail_strict=True` then.

Per R19 "MUST NOT delete or skip tests": justify the temporary xfail in a docstring with a clear "remove on B-3 completion" gate.

**Acceptance**:
- [ ] Test discovers all `BaseKafkaConsumer` subclasses across `services/`
- [ ] xfail until B-3; remove xfail in B-3's commit

##### T-B-1-03: Update STANDARDS.md §3 (Kafka consumer convention)
**Type**: docs
**depends_on**: T-B-1-01
**Target files**: `docs/STANDARDS.md` (extend §3.9 "Kafka Consumer Standard (R20)")

Append a new subsection: "§3.11 Consumer Dedup — ALWAYS use `ValkeyDedupMixin`" with the contract, the at-least-once fallback rule, and the deterministic-ID requirement for the fallback to be safe. Include the SQL/Lua-vs-natural-key decision matrix from `/investigate` §1.5.

#### Validation Gate
- [ ] mypy clean
- [ ] `python -m pytest libs/messaging/tests/unit/kafka/consumer/test_dedup.py -v` (≥10 tests pass)
- [ ] `python -m pytest tests/architecture/test_consumer_dedup_mixin_enforcement.py` xfails as expected
- [ ] STANDARDS.md updated

#### Break Impact
None — pure addition. Existing consumers unaffected until B-2.

#### Regression Guardrails
- **R9**: the mixin satisfies the "processed-events check" requirement.
- **R20**: the mixin is meant to be combined with `BaseKafkaConsumer`, not replace it.

---

### Wave B-2: Migrate 7 Consumers (refactor only — no behaviour change)

**Goal**: Switch the 4 KG consumers (already implementing the pattern by hand) and 3 market-data consumers (currently `is_duplicate=False`) to inherit `ValkeyDedupMixin`. No behaviour change for the 4 KG consumers; the 3 market-data consumers gain dedup that complements their natural-key idempotency.

**Closes**: prerequisite for B-3; eliminates dialect drift across 7 of 8 consumers.
**Depends on**: B-1.
**Estimated effort**: 3-4 hours (mostly mechanical).

#### Pre-read
For each consumer, the `is_duplicate` / `mark_processed` block. Then study the constructor wiring in each service's `app.py` / `consumer_main.py` so the Valkey client can be passed in.

#### Tasks

##### T-B-2-01: Migrate 4 KG consumers
**Type**: impl
**depends_on**: T-B-1-01 (B-1)
**Target files**:
- `services/knowledge-graph/src/knowledge_graph/infrastructure/messaging/consumers/enriched_consumer.py`
- `services/knowledge-graph/src/knowledge_graph/infrastructure/messaging/consumers/entity_consumer.py`
- `services/knowledge-graph/src/knowledge_graph/infrastructure/messaging/consumers/temporal_event_consumer.py`
- `services/knowledge-graph/src/knowledge_graph/infrastructure/messaging/consumers/provisional_queued_consumer.py`

**What to build**: For each consumer:
1. Add `ValkeyDedupMixin` to the class MRO before `BaseKafkaConsumer`.
2. Move `_dedup_client`/`_dedup_prefix`/`_dedup_ttl_seconds` to instance attributes set in `__init__`.
3. Delete the hand-rolled `is_duplicate` and `mark_processed` methods (now inherited from mixin).
4. Verify the existing tests (which already exercise the dedup path) still pass.

**Tests**: existing tests must pass unchanged. No new tests required — the mixin's tests cover the contract; the consumer tests cover wiring.

**Acceptance**:
- [ ] All 4 KG consumers inherit `ValkeyDedupMixin`
- [ ] All KG unit tests pass (existing test count maintained)
- [ ] No `is_duplicate`/`mark_processed` methods left in the KG consumer files

##### T-B-2-02: Migrate 3 market-data consumers
**Type**: impl
**depends_on**: T-B-1-01 (B-1)
**Target files**:
- `services/market-data/src/market_data/infrastructure/messaging/consumers/ohlcv_consumer.py`
- `services/market-data/src/market_data/infrastructure/messaging/consumers/fundamentals_consumer.py`
- `services/market-data/src/market_data/infrastructure/messaging/consumers/intraday_resampling_consumer.py`

**What to build**: For each consumer:
1. Mix in `ValkeyDedupMixin`.
2. Add Valkey client wiring in the `consumer_main.py` factory (or wherever the consumer is instantiated).
3. Delete the `is_duplicate`/`mark_processed` no-op overrides.
4. Add a docstring note: "Dedup mixin is belt-and-braces over the consumer's natural-key `create_if_not_exists()` idempotency. The mixin protects against expensive ML/HTTP work on Kafka rebalance re-delivery; the natural key protects rows."

**Tests**: existing market-data unit tests must pass. Add 1 integration test per consumer asserting that `is_duplicate(known_event_id)` returns True after `mark_processed`.

**Acceptance**:
- [ ] All 3 market-data consumers inherit the mixin
- [ ] Market-data unit suite passes
- [ ] +3 integration tests

##### T-B-2-03: Cross-service test run
**Type**: test
**depends_on**: T-B-2-01, T-B-2-02
**Target files**: none (test runner only)

**What to do**: Run the full unit suite for both services + the architecture test.

**Acceptance**:
- [ ] `python -m pytest services/knowledge-graph/tests/ -m unit -v` passes
- [ ] `python -m pytest services/market-data/tests/ -m unit -v` passes
- [ ] Architecture test still xfails (expected; B-3 closes it)

#### Validation Gate
- [ ] mypy clean for both services
- [ ] No new test failures (R33)
- [ ] `git diff` shows only mixin inheritance + constructor changes (no logic changes)

#### Break Impact
| Broken file | Why | Fix |
|---|---|---|
| Constructors of 4 KG + 3 market-data consumers | New required positional/kwarg `dedup_client` parameter | Update `consumer_main.py` factories to pass the Valkey client; matches the B-1 mixin contract |

#### Regression Guardrails
- **R34** (subagent commits): if running B-2 in parallel worktrees per consumer, each worktree commits separately; orchestrator runs full suite after merge.
- **R33** (full test run): run KG + market-data full suites, not just touched files.

---

### Wave B-3: ArticleProcessingConsumer Migration + Deterministic IDs

**Goal**: The big one. Migrate `ArticleProcessingConsumer` to `ValkeyDedupMixin` AND replace `new_uuid7()` with `uuid5_from_parts(...)` for every row whose identity is determined by the upstream message. Once shipped, flip the architecture test from xfail → strict.

**Closes**: F-X11, F-X12, F-D03 (CRITICAL); enables R9 compliance + safe at-least-once fallback.
**Depends on**: B-1, B-2.
**Estimated effort**: 3-4 hours.

#### Pre-read
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/messaging/consumers/article_consumer.py` (full file — ~1600 lines; focus on `process_message`, `_run_pipeline`, `is_duplicate`, `mark_processed`, and `_enqueue_enriched`)
- `libs/common/src/common/ids.py:57-84` (uuid5_from_parts spec)
- `services/knowledge-graph/src/knowledge_graph/application/blocks/graph_write.py:191` (the existing precedent for uuid5 use)
- `services/nlp-pipeline/tests/unit/infrastructure/messaging/consumers/test_d004_dual_db_commit.py` (regression baseline)

#### Tasks

##### T-B-3-01: Mixin + Valkey wiring
**Type**: impl
**depends_on**: B-1, B-2
**Target files**:
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/messaging/consumers/article_consumer.py`
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/messaging/consumers/article_consumer_main.py` (or wherever the factory is)

Steps: same as T-B-2-01 — mix in, delete the no-op methods at lines 796-800, wire the Valkey client at the factory site. Prefix: `nlp:dedup:article_consumer`. TTL: 86400.

##### T-B-3-02: Deterministic IDs in `_run_pipeline`
**Type**: impl
**depends_on**: T-B-3-01
**Target files**: same as T-B-3-01 + tests

**Replacements** (full mapping):

| Current | Replace with |
|---|---|
| `decision_id = common.ids.new_uuid7()` (line 362) | `uuid5_from_parts(str(doc_id), "routing_decision")` |
| `mention_id=common.ids.new_uuid7()` per row | `uuid5_from_parts(str(doc_id), str(mention_index), normalized_surface)` where `mention_index` is the deterministic ordering of mentions extracted from the article (already deterministic per the chunker) |
| `embedding_id=common.ids.new_uuid7()` (lines 887, 904) | `uuid5_from_parts(str(doc_id), str(chunk_or_section_id), settings.embedding_model_id)` |
| Outbox `event_id` `nlp.article.enriched.v1` (line 1054) | `uuid5_from_parts(str(doc_id), "article_enriched_v1")` |
| Outbox `event_id` `nlp.signal.detected.v1` (line 1543) | `uuid5_from_parts(str(doc_id), str(signal_kind), str(signal_index))` |

For each, ensure the corresponding INSERT statement uses `ON CONFLICT (id) DO NOTHING` (verify; some already do).

**Tests** (≥6 new):
| Test | Verifies |
|---|---|
| `test_replay_does_not_duplicate_routing_decision` | Process same event twice → 1 row in routing_decisions |
| `test_replay_does_not_duplicate_mentions` | 1 row per mention regardless of replay count |
| `test_replay_does_not_duplicate_embeddings` | 1 row per chunk per model_id |
| `test_replay_emits_same_outbox_event_id` | Two runs → same nlp.article.enriched.v1 event_id |
| `test_decision_id_stable_across_runs` | Pure determinism (same inputs → same id) |
| `test_decision_id_changes_when_doc_id_changes` | Different doc → different id |

**Acceptance**:
- [ ] All listed `new_uuid7()` calls in `_run_pipeline` replaced
- [ ] `git diff` shows no remaining `new_uuid7()` for these row classes
- [ ] Replay-correctness tests pass
- [ ] D-004 dual-DB commit test still passes (no regression)

##### T-B-3-03: Flip the architecture test from xfail to strict
**Type**: test
**depends_on**: T-B-3-01
**Target files**:
- `tests/architecture/test_consumer_dedup_mixin_enforcement.py`

Remove the xfail; the test should now pass for all 8 consumers.
A-005: 14 grandfathered entries were allowlisted in PLAN-0084 B-2; future consumers must use ValkeyDedupMixin.

##### T-B-3-04: Update STANDARDS.md §11 anti-pattern
**Type**: docs
**depends_on**: T-B-3-03
**Target files**: `docs/STANDARDS.md`

Add row to the §11 anti-pattern table: "Hand-rolled `is_duplicate`/`mark_processed` per consumer → use `ValkeyDedupMixin` from `libs/messaging`". Reference R9 + the new BP entry created in Sub-Plan H.

#### Validation Gate
- [ ] Architecture test passes (no xfail)
- [ ] Full nlp-pipeline unit + integration suite passes
- [ ] Replay correctness test passes
- [ ] mypy + ruff clean
- [ ] Docker rebuild + manual replay smoke test (publish same article twice; verify 1 row in routing_decisions)

#### Break Impact
| Broken file | Why | Fix |
|---|---|---|
| `services/nlp-pipeline/tests/unit/infrastructure/messaging/consumers/test_d004_dual_db_commit.py` | If any test asserted on `new_uuid7()` randomness | Update to assert deterministic ID |
| Any test fixture that constructed mention/embedding objects with hard-coded UUIDs | Fixture IDs no longer match new deterministic derivation | Recompute fixture IDs from the helper, or use `pytest.fixture` to derive them |

#### Regression Guardrails
- **R10** (UUIDv7 for entity IDs): `uuid5_from_parts` returns a string-form UUID5; this is a deliberate exception for replay-stable IDs and is documented in `libs/common/ids.py:57-84` ("`uuid5_from_parts` is the canonical exception to R10 for replay-stable IDs").
- **BP-124** (consumer idempotency check skips embedding on entity replay): the early `routing_decisions.exists()` short-circuit at line 245 stays — but the deterministic IDs make it safe even if it ever bypasses.
- **R31** (rebuild containers): after merge, rebuild `nlp-pipeline` and verify replay behaviour live.

---


## Sub-Plan C — nlp-pipeline Canonical Tickers Cache

**Service**: `services/nlp-pipeline/`
**Waves**: C-1.
**Depends on**: none (parallel-safe with A-1, B-1).
**Estimated effort**: ~2 hours.

### Wave C-1: Background Refresh Loop + Atomic Swap

**Goal**: Close F-X02 (cache never refreshes) and F-X03 (DEL+SADD non-atomic). Add a 600s background refresh loop launched from startup; replace the non-transactional pipeline with `pipeline(transaction=True)` (or a Lua script).

**Closes**: F-X02 (CRITICAL), F-X03 (MAJOR).
**Estimated effort**: 2 hours.

#### Pre-read
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/cache/canonical_tickers_cache.py` (full file)
- `services/rag-chat/src/rag_chat/infrastructure/middleware/internal_jwt.py:121` (the JWT refresh-loop pattern to mirror)
- `libs/messaging/src/messaging/valkey/client.py` (pipeline + transaction support)

#### Tasks

##### T-C-1-01: Add settings + refresh-loop method
**Type**: impl
**depends_on**: none
**Target files**:
- `services/nlp-pipeline/src/nlp_pipeline/config.py`
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/cache/canonical_tickers_cache.py`
- `services/nlp-pipeline/tests/unit/test_canonical_tickers_cache.py`

**What to build**:
1. New setting: `canonical_tickers_refresh_interval_s: int = Field(default=600, ge=60, le=3600)` (env: `NLP_PIPELINE_CANONICAL_TICKERS_REFRESH_INTERVAL_S`).
2. New method `_refresh_loop` on `CanonicalTickersCache`:

```python
async def _refresh_loop(self) -> None:
    while True:
        try:
            await asyncio.sleep(self._refresh_interval_s)
            count = await self.refresh()
            log.info("canonical_tickers.refresh_loop_tick", count=count)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.warning("canonical_tickers.refresh_loop_error", exc_info=True)
            # Don't crash the loop on transient failure; sleep and retry.
            await asyncio.sleep(60)
```

3. New method `start_loop` returns the task; `close()` cancels + awaits.

**Tests** (≥4):
| Test | Verifies |
|---|---|
| `test_refresh_loop_calls_refresh_on_interval` | Mock `asyncio.sleep`; advance time; assert `refresh()` called N times | unit |
| `test_refresh_loop_swallows_transient_error` | First call raises ConnectionError, second succeeds → loop continues | unit |
| `test_refresh_loop_propagates_cancelled_error` | task.cancel() → CancelledError raised | unit |
| `test_close_cancels_loop` | After close(), task.cancelled() is True | unit |

##### T-C-1-02: Atomic DEL+SADD swap
**Type**: impl
**depends_on**: T-C-1-01 (parallel-safe)
**Target files**: same

**What to build**: Replace lines 130-145 in `canonical_tickers_cache.py`:

```python
async def refresh(self) -> int:
    tickers = await self._source.fetch_all()
    normalised = {t.strip().upper() for t in tickers if t and t.strip()}

    # Atomic swap via MULTI/EXEC. The DEL + SADD execute as a single
    # transaction so concurrent `is_known_ticker` callers cannot observe an
    # empty SET in the gap. (BP-NEW-cache-swap.)
    async with self._client.pipeline(transaction=True) as pipe:
        pipe.delete(self._key)
        if normalised:
            pipe.sadd(self._key, *normalised)
        await pipe.execute()

    return len(normalised)
```

Update the docstring on the class to confirm "atomic swap" without the previous "ish".

**Tests** (≥3):
| Test | Verifies |
|---|---|
| `test_refresh_uses_transaction_mode` | Captures pipeline call; asserts `transaction=True` | unit |
| `test_concurrent_is_known_ticker_during_refresh` | 50 concurrent reads during swap; none returns False for an existing ticker | unit |
| `test_refresh_handles_empty_source` | `fetch_all()` returns [] → DEL fires, SADD skipped, key absent | unit |

##### T-C-1-03: Wire refresh loop in `startup()`
**Type**: impl
**depends_on**: T-C-1-01, T-C-1-02
**Target files**:
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/cache/canonical_tickers_cache.py` (`startup` method)
- Wherever the cache is instantiated in nlp-pipeline app (likely `consumer_main.py` or a worker boot script)

**What to build**: In `startup()` after the initial `refresh()`, do `self._refresh_task = asyncio.create_task(self._refresh_loop())` and store it. Add a `close()` method that cancels it.

**Tests** (≥2):
- `test_startup_launches_refresh_loop` (the task is non-done after startup)
- `test_close_cancels_refresh_loop` (the task is cancelled after close)

##### T-C-1-04: Docs
**Type**: docs
**depends_on**: T-C-1-03
**Target files**:
- `docs/services/nlp-pipeline.md`
- `services/nlp-pipeline/.claude-context.md`

Document the refresh interval, the env var, the staleness window guarantee (≤600s by default), and the at-startup vs at-loop semantics.

#### Validation Gate
- [ ] All cache tests pass (≥9 new + existing)
- [ ] mypy + ruff clean
- [ ] Docker rebuild; verify log line `canonical_tickers.refresh_loop_tick` appears within 600s of boot

#### Break Impact
None — the existing `refresh()` API is unchanged; the new loop is opt-in via startup.

#### Regression Guardrails
- **DS-009** (NEW pattern, see Sub-Plan H): "Cache populated once at startup, never refreshed" — this wave establishes the canonical fix.
- **R8** (no dual writes): N/A — this is a read-through cache, no DB writes.

---

## Sub-Plan D — Port-ABC Extraction (parallel waves)

**Service**: `services/nlp-pipeline/` + `services/rag-chat/`
**Waves**: D-1, D-2, D-3 — independent, can run in parallel worktrees.
**Depends on**: none (but should land before PLAN-0067 begins).
**Estimated effort**: ~1.5 hours per wave; ~half a day if serial, ~2 hours if parallel.

### Wave D-1: `ChunkSearchPort` ABC

**Goal**: Extract `ChunkSearchPort(ABC)` from the concrete `ChunkANNRepository`. Re-type the use case dependency.

**Closes**: F-A04 (one of three port gaps).
**Depends on**: none.
**Estimated effort**: 1.5 hours.

#### Pre-read
- `services/nlp-pipeline/src/nlp_pipeline/application/ports/repositories.py` (existing 7 ABCs — pattern to follow)
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/nlp_db/repositories/chunk_search.py` (concrete class)
- `services/nlp-pipeline/src/nlp_pipeline/application/use_cases/enhanced_chunk_search.py:32-37` (TYPE_CHECKING import to remove)

#### Tasks

##### T-D-1-01: Define `ChunkSearchPort` ABC (NEW — created in this plan)
**Type**: impl
**Target files**:
- `services/nlp-pipeline/src/nlp_pipeline/application/ports/chunk_search.py` (NEW)
- `services/nlp-pipeline/src/nlp_pipeline/application/ports/__init__.py` (export)

**ABC spec** (signatures pulled from current `ChunkANNRepository` methods):
```python
class ChunkSearchPort(ABC):
    @abstractmethod
    async def ann_search(self, ...) -> tuple[list[ChunkHit], int]: ...
    @abstractmethod
    async def lexical_search(self, *, query_text: str, top_k: int,
                              mode: Literal["english","simple","both"], ...) -> tuple[list[ChunkHit], int]: ...
    @abstractmethod
    async def fetch_entity_mentions(self, chunk_ids: Sequence[UUID]) -> dict[UUID, list[Mention]]: ...
```

Verify exact method shapes against `chunk_search.py` and copy them precisely (including kwarg-only markers, return types).

##### T-D-1-02: `ChunkANNRepository` declares `ChunkSearchPort` parent
**Type**: impl
**depends_on**: T-D-1-01
**Target files**: `services/nlp-pipeline/src/nlp_pipeline/infrastructure/nlp_db/repositories/chunk_search.py`

Change `class ChunkANNRepository:` → `class ChunkANNRepository(ChunkSearchPort):`. mypy passes because the methods already exist.

##### T-D-1-03: Re-type `EnhancedChunkSearchUseCase` dependency
**Type**: impl
**depends_on**: T-D-1-02
**Target files**: `services/nlp-pipeline/src/nlp_pipeline/application/use_cases/enhanced_chunk_search.py`

Change `chunk_ann_repo: ChunkANNRepository` → `chunk_ann_repo: ChunkSearchPort`. Move the import from `infrastructure/` (TYPE_CHECKING) to `application/ports/`. The TYPE_CHECKING block at lines 32-37 shrinks.

##### T-D-1-04: Add stub port for tests
**Type**: test
**depends_on**: T-D-1-01
**Target files**: `services/nlp-pipeline/tests/unit/application/ports/test_chunk_search_port.py` (NEW)

Add a `StubChunkSearchPort` implementing the ABC; assert mypy treats it as a valid `ChunkSearchPort`. Replace one existing `Mock()`-based use case test with the stub to demonstrate the pattern.

#### Validation Gate
- [ ] mypy clean (concrete repo is a valid `ChunkSearchPort`)
- [ ] All existing nlp-pipeline use case tests still pass
- [ ] +1 stub-based test demonstrates the new pattern

---

### Wave D-2: `CanonicalEntityPort` ABC
**Same shape as D-1** for `CanonicalEntityRepository` (`services/nlp-pipeline/src/nlp_pipeline/infrastructure/intelligence_db/repositories/canonical_entity.py:20`). Methods to lift: `batch_get`, `find_by_name_and_type`, `create`. Note: PLAN-0076 deferred items mention the KG service has a similar `CanonicalEntityRepositoryPort` ABC missing methods — out of scope here; this wave creates the nlp-pipeline-side ABC only. **Effort 1.5h**, same task structure as D-1.

### Wave D-3: `IntentClassifierPort` Protocol
**Service**: `services/rag-chat/`. Different from D-1/D-2 because both `OllamaIntentClassifier` (line 142) and `DeepInfraIntentClassifier` (line 238) already exist and are duck-typed; the Protocol unifies them.

**Tasks**:
- T-D-3-01: Define `IntentClassifierPort(Protocol)` in `services/rag-chat/src/rag_chat/application/ports/intent_classifier.py` (NEW). Single method: `async def classify(self, text: str, history: list[dict[str, str]], entities: list[dict[str, Any]]) -> tuple[str, list[str], str]`.
- T-D-3-02: Re-type `RetrieveOnlyUseCase.classifier: IntentClassifierPort` (currently typed as `OllamaIntentClassifier`). Same change in `ChatOrchestratorUseCase` if it has the same gap.
- T-D-3-03: Add stub.

PLAN-0067 W11-3 deletes the IntentClassifier path entirely; that deletion becomes 1 file removal + 2 import-line removals once D-3 lands. Without D-3, the deletion is a sed-and-pray refactor.

**Effort 1.5h**.

---

## Sub-Plan E — CI Gate Hardening

**Service**: infrastructure (`.github/workflows/`, `scripts/`)
**Waves**: E-1 (smoke probe), E-2 (per-class regression + tighten exit code), E-3 (instability investigation → flip continue-on-error).
**Depends on**: B-3 (so the codebase is stable when the gate is meaningful) — soft dependency.
**Estimated effort**: ~half a day total.

### Wave E-1: Smoke Probe Step Before Full Eval

**Goal**: Add a CI step that does a single curl against `/v1/internal/retrieve` with a known query and asserts a 200 with `n_candidates >= 1`. If the probe fails, the workflow fails immediately with a clear error rather than silently treating "endpoint unreachable" as "no labelled queries match".

**Closes**: part of F-X09.
**Estimated effort**: 30 minutes.

##### T-E-1-01: Add smoke-probe step to workflow
**Type**: config
**Target file**: `.github/workflows/retrieval-eval.yml`

Insert step before "Run eval" (line 155). The probe sends `{"query_text":"Apple Q4 earnings","top_k":5}` and `jq`-extracts `n_candidates`. If <1, exit 1 with diagnostic log.

##### T-E-1-02: Update workflow doc + run on a deliberately-broken URL to verify
**Type**: test
Verify by setting `RAG_CHAT_URL=http://localhost:9999` and confirming the workflow fails red.

---

### Wave E-2: Per-Class Regression Check + Tighten Empty-`per_query` Exit

**Goal**: The current gate compares one global NDCG@10. PRD-0034 §3 FR-T1-2 asks for per-intent (per-class) gating. Add `--fail-on-regression-per-class` flag in `eval_retrieval.py`; flip the empty-`per_query` exit from 0 to "0 if labelled <50 else 1".

**Closes**: rest of F-X09.
**Depends on**: E-1 (parallel-safe but want to land in same PR).
**Estimated effort**: 2 hours.

##### T-E-2-01: Implement `--fail-on-regression-per-class`
**Type**: impl
**Target files**:
- `scripts/eval_retrieval.py` (add arg + per-class compare logic)
- `tests/scripts/test_eval_retrieval.py` (add tests)

`compare_to_baseline` already returns per-class deltas (verified via investigation report). Add a new flag (default 0.05 absolute), iterate per class, fail if any class regresses by more than the threshold.

**Tests**: ≥4 — global pass + per-class pass; global pass + per-class regress (one class) → fails; flag absent → behaviour unchanged; `non_analyst < 6 graded` → emit warning but don't fail.

##### T-E-2-02: Tighten empty-`per_query` exit
**Type**: impl
**Target file**: `scripts/eval_retrieval.py:552-559`

Replace:
```python
if not per_query:
    print("ERROR: ...", file=sys.stderr)
    return 0
```
with:
```python
n_labelled = sum(1 for r in rows if r.get("relevant_doc_ids"))
if not per_query:
    if n_labelled < 50:
        print(f"WARN: {n_labelled} labelled queries, eval skipped (gate informational); exit 0.", file=sys.stderr)
        return 0
    print(f"ERROR: {n_labelled} labelled queries but 0 evaluated — every query failed retrieval. Exit 1.", file=sys.stderr)
    return 1
```

##### T-E-2-03: Update workflow to pass new flag
**Type**: config
**Target file**: `.github/workflows/retrieval-eval.yml`

Add `--fail-on-regression-per-class 0.05` to the eval invocation.

#### Validation Gate
- [ ] Eval-script unit tests pass (≥4 new)
- [ ] Workflow shape reviewable (one PR comment per change)

---

### Wave E-3: Result-Instability Investigation → Flip `continue-on-error`

**Goal**: Investigate why W5-3 baseline-capture flagged run-to-run NDCG variance. Identify root cause (snapshot inconsistency F-X08, query-batching variance, RNG in retrieval, or other). Apply minimal fix. Then remove `continue-on-error: true` from the workflow.

**Closes**: F-X09 (final removal of the fail-open flag).
**Depends on**: E-1, E-2 (smoke probe + per-class gate must already be in place so the gate is meaningful when flipped).
**Estimated effort**: ~half a day (investigation-heavy).

##### T-E-3-01: Run `/investigate` on result-instability
**Type**: investigation
**Target deliverable**: `docs/audits/2026-05-XX-retrieval-eval-instability-investigation.md`

Run the eval against the labelled set 5 times in succession; record per-class NDCG variance. Hypotheses to test:
- H-1: Snapshot inconsistency (F-X08) — ANN + lexical legs see different chunk universes during ingest.
- H-2: Postgres query planner cache effects (first run cold, second warm).
- H-3: RNG seeding in retrieval (e.g. tiebreaker on identical scores).
- H-4: Concurrent ingest racing the eval (cache-state of `chunk_text` Valkey).
- H-5: DeepInfra embedding-model versioning drift.

##### T-E-3-02: Apply fix (one of)
**Type**: impl (depends on T-E-3-01 result)

If H-1: enable REPEATABLE READ snapshot for `/v1/internal/retrieve` per F-X08 fix recommendation. If H-3: pin RNG seed in retrieval. Etc. The fix shape is determined by the investigation; this task placeholder reserves wave-level scope.

##### T-E-3-03: Flip `continue-on-error: false`
**Type**: config
**Target file**: `.github/workflows/retrieval-eval.yml:137`

Remove `continue-on-error: true`. Verify workflow fails red on a deliberately-bad NDCG.

#### Validation Gate
- [ ] Investigation report committed
- [ ] 5 consecutive eval runs produce per-class NDCG within ±0.01
- [ ] CI workflow fails red on a synthetic regression PR

---

## Sub-Plan F — Migration & Data Polish

**Waves**: F-1 (combined polish wave).
**Depends on**: none (parallel-safe with everything except the migration touching the same file).
**Estimated effort**: 1 hour.

### Wave F-1: Migration LOCK + Storage Doc + Single-Reviewer Flag

##### T-F-1-01: Add `LOCK TABLE ... NOWAIT` to migration 0026
**Type**: schema
**Target file**: `services/intelligence-migrations/alembic/versions/0026_add_canonical_entities_dedup_index.py`

Add to the top of the DO block:
```sql
LOCK TABLE canonical_entities, entity_aliases, entity_embedding_state,
           relations, relation_evidence_raw, claims, events, event_entities,
           entity_event_exposures, provisional_entity_queue, relation_summaries
    IN ACCESS EXCLUSIVE MODE NOWAIT;
```
Update docstring with: "expected runtime on dev stack: ~2-5 seconds with 132 dedup groups; production runtime depends on dataset size — measure before applying."

##### T-F-1-02: Storage-budget docstring on migration 0017
**Type**: docs
**Target file**: `services/nlp-pipeline/alembic/versions/0017_add_chunks_tsv_english_gin.py`

Append to module docstring a "Forward-compatibility / storage budget" section: median chunk_text ~3KB; p99 8KB; expected per-row footprint; expected GIN size at 1M rows; autovacuum tuning note for 10M rows; retirement plan reference (PLAN-0064 W6 may render redundant).

##### T-F-1-03: Add `single_reviewer: true` flag to baseline JSON
**Type**: schema
**Target files**:
- `results/baseline_pre_hybrid.json` (edit metadata)
- `results/eval_post_hybrid.json` (edit metadata)
- `scripts/eval_retrieval.py` `write_outputs` (auto-emit going forward)

Add to the metadata dict header: `"single_reviewer": true, "reviewer_id": "claude-agent-1"`.

#### Validation Gate
- [ ] Migration 0026 docstring updated; LOCK TABLE present
- [ ] Migration 0017 docstring updated
- [ ] Baseline JSON files updated; eval_retrieval.py emits the flag in new runs

#### Break Impact
None — purely additive.

---

## Sub-Plan G — Boost Sweep (Gated)

**Waves**: G-1.
**Gated on**: E-3 closing AND golden-set labelling ≥80% (currently 51%; this plan does NOT include labelling work). If labelling is still below 80% after E-3, defer G.

**Gate status (2026-05-09)**: Both gates MET — E-3 complete (commit e39c298a); labelling at 88.3% (106/120). Pending: `make dev` + boost sweep command.
**Estimated effort**: 2 hours.

### Wave G-1: Run `--mode hybrid_boost_sweep` and Lock the Optimum

**Goal**: Close F-A02. Run the boost-sweep mode against the labelled set; pick the value maximising `identifier_lookup` NDCG@10 without regressing other classes by ≥0.02; commit the artifact and update `Settings.hybrid_lexical_boost` default.

##### T-G-1-01: Run sweep
**Type**: ops
**Command**: `python scripts/eval_retrieval.py --mode hybrid_boost_sweep --rag-url $RAG_CHAT_URL --golden tests/eval/golden/queries.jsonl --query-embeddings tests/eval/golden/query_embeddings.parquet --output-dir results/`

Commit the resulting `results/boost_sweep_<ts>.json`.

##### T-G-1-02: Update `Settings.hybrid_lexical_boost` default
**Type**: config
**Target files**:
- `services/nlp-pipeline/src/nlp_pipeline/config.py` (default = chosen value)
- `docs/plans/0063-w5-hybrid-retrieval-eval-gate-plan.md` §0-bis L9 (record the empirical result)

##### T-G-1-03: Update PLAN-0063 status
**Type**: docs
**Target file**: `docs/plans/TRACKING.md` row for PLAN-0063 — add note "F-A02 closed `2026-05-XX`: boost sweep run; chosen value `<X>`; artifact `results/boost_sweep_<ts>.json`."

---

## Sub-Plan H — STANDARDS / RULES / BUG_PATTERNS Compounding

**Waves**: H-1.
**Depends on**: A-1, A-2, B-3, C-1 (all the patterns this wave codifies must have shipped first).
**Estimated effort**: 1 hour.

### Wave H-1: Codify the Patterns Surfaced This Plan

##### T-H-1-01: Add 4 new BPs to `docs/BUG_PATTERNS.md`

Reserved IDs (verified via Phase -1 — next free is BP-412):

- **BP-412 — Use case implemented + tested in isolation but never wired in `app.py` lifespan** → silent metric loss / dead-cron pattern. Reference F-A01.
- **BP-413 — Circuit breaker has no HALF_OPEN probe gating; cooldown expiry → stampede on the recovering source.** Reference F-X01. Detection rule: "any breaker `is_open()` that returns just `state == 'open'` without a SETNX probe is suspect."
- **BP-414 — Cache populated once at startup, never refreshed** → DS-009 stale-replica pattern. Reference F-X02. Detection rule: "any class with a `refresh()` method and no `_refresh_loop` task is suspect; grep for refresh callsites."
- **BP-415 — Hand-rolled `is_duplicate`/`mark_processed` per consumer drifts into multiple dialects** → F-X11/F-X12/F-D03 pattern. Detection: arch test `test_consumer_dedup_mixin_enforcement`.

##### T-H-1-02: Update `docs/STANDARDS.md`

- §3.11 (NEW): Consumer Dedup contract using `ValkeyDedupMixin`. Cross-reference R9.
- §11 anti-pattern table: 2 new rows (hand-rolled dedup; cache-no-refresh-loop).

##### T-H-1-03: Update `RULES.md` R9 wording

R9 currently says "Check `event_id` against a processed-events table before processing". Clarify: "the processed-events check is satisfied by `ValkeyDedupMixin`. Consumers that bypass it must declare a stronger guarantee in their docstring (e.g., atomic create_if_not_exists natural-key idempotency) and the architecture test must allowlist them. The allowlist is currently empty; new entries require ADR justification."

##### T-H-1-04: Update `.claude/review/checklists/REVIEW_CHECKLIST.md`

- New check: "If a use case has an `execute()` that updates a Prometheus metric or returns a value, grep for at least one caller in `app.py` / `lifespan` / `_wire_*`."
- New check: "If a use case introduces a new singleton-cached resource (e.g. `XCache`, `YState`), search for either a refresh loop or a Kafka invalidation consumer."

##### T-H-1-05: Update `.claude/review/heuristics/HIGH_RISK_PATTERNS.md`

- HR-NEW: `is_duplicate(self, event_id) -> bool: return False` is a yellow flag; require either a `ValkeyDedupMixin` or a docstring explaining natural-key idempotency.
- HR-NEW: `cool_down_seconds: int >= 300` (or any breaker cooldown ≥5 min) without a HALF_OPEN probe is a red flag.

#### Validation Gate
- [x] All updated docs committed
- [x] BP grep for collisions: `grep -c "^| BP-41[2-5] " docs/BUG_PATTERNS.md` returns 4 (one per BP)
- [x] No conflicting rule-number assignments

---

## Cross-Cutting Concerns

- **Contract changes**: None. No Avro schema changes; no new Kafka topics; no API contract changes (citation cron is internal-only; CB gauge is metric-only).
- **Migration needs**: Only docstring updates on existing migrations (F-1). No new Alembic revisions.
- **Event flow changes**: None — the article-consumer outbox event_id changes from random to deterministic, but downstream KG dedup uses payload-content uuid5 so the wire-format is unchanged.
- **Configuration changes**: 6 new env vars (rag-chat: 4 citation + 2 CB; nlp-pipeline: 1 cache refresh). All have safe defaults; production rollout flips `RAG_CHAT_CITATION_CRON_ENABLED=true`.
- **Documentation updates**: STANDARDS §3.11 + §11 (H-1); rag-chat + nlp-pipeline service docs (A-1, A-2, C-1); `.claude-context.md` for both services; RULES.md R9 (H-1); REVIEW_CHECKLIST + HIGH_RISK_PATTERNS (H-1); BUG_PATTERNS.md 4 new entries (H-1); PLAN-0063 status row in TRACKING (G-1 closes F-A02).

---

## Risk Assessment

- **Critical path**: A-1 → B-1 → B-2 → B-3 (consumer idempotency chain). If B-3 cannot land cleanly because of replay-correctness test failures, the whole sub-plan B stalls.
- **Highest risk**: B-3 (article consumer). The consumer is ~1600 LOC with the platform's most complex pipeline (D-004 dual-DB, claim-check, blocks 3-10). The deterministic-ID changes touch ~5 separate ID generation sites; getting any one wrong silently breaks downstream dedup.
- **Highest mechanical risk**: B-2 migration of 7 consumers in parallel worktrees — R34 (subagent commit discipline) applies; orchestrator must run full KG + market-data unit suites after merge.
- **Rollback**: A-1, A-2, C-1, D-1/D-2/D-3, F-1 all individually revertable — they're standalone commits with no dependency on each other beyond docs. B-2/B-3 are harder to roll back because the mixin-inheritance change touches consumer constructors; revert by adding `is_duplicate=False; mark_processed=pass` overrides if needed.
- **Testing gaps**: E-3's investigation step (T-E-3-01) is open-ended; if the variance turns out to be DeepInfra non-determinism (H-5), the fix may require pinning a model revision, which has its own risk.

---

## Compounding Updates Inventory

This plan, when executed end-to-end, will produce:

- 4 new BPs (BP-412..415), all in H-1
- 1 new STANDARDS.md section (§3.11), 1 new R9 clarification, 2 new §11 anti-pattern rows
- 1 new architecture test (`test_consumer_dedup_mixin_enforcement.py`)
- 2 new REVIEW_CHECKLIST checks
- 2 new HIGH_RISK_PATTERNS heuristics
- 5 new ports/protocols (`ValkeyDedupMixin`, `CitationJudgeAdapter`, `ChunkSearchPort`, `CanonicalEntityPort`, `IntentClassifierPort`)
- 6 new env vars across rag-chat + nlp-pipeline
- ~25 new tests across unit + integration + architecture layers

---

## Recommended Execution Order

1. **Day 1**: A-1, A-2, C-1 (3 waves; rag-chat + nlp-pipeline cache).
2. **Day 2**: B-1, B-2 (the consumer-mixin foundation + 7-consumer refactor).
3. **Day 3**: B-3 (article consumer + deterministic IDs). Highest-risk wave.
4. **Day 4**: D-1, D-2, D-3 in parallel (port ABCs).
5. **Day 5**: E-1, E-2 (CI gate hardening, parts 1+2). E-3 may slip into Day 6.
6. **Day 6**: F-1 (migration polish), G-1 if labelling ≥80% (otherwise defer), H-1 (compounding).

Total: ~5-6 dev-days for a single engineer; ~3-4 days with two engineers running B + D in parallel.

---

## Workflow Chain

After completing this plan:
1. Re-run `/qa --plan PLAN-0063` to confirm all CRITICAL findings are closed.
2. Re-run `/qa --plan PLAN-0084` to validate this plan's deliverables.
3. Update PLAN-0063 status: 7/7 → "complete (after PLAN-0084 H-1)".
4. Begin PLAN-0085 (CLI command palette + multi-panel layout) per Q3.
