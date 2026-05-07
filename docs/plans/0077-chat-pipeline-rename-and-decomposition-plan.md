---
id: PLAN-0077
prd: derived from /investigate 2026-05-07 (issues C-1, A-5)
status: completed
created: 2026-05-07
updated: 2026-05-07
owner: TBD
estimated_effort: ~2 dev-days (3 waves, 10 tasks)
critical_path: Wave A → Wave B → Wave C
hard_dependencies: none
blocks: PLAN-0066 Wave H, PLAN-0067 W11-3, PLAN-0074 Wave F
---

# PLAN-0077 — Chat Pipeline Rename + Decomposition

---

## §0 Why this plan exists

Three concurrent plans (PLAN-0066, 0067, 0074) reference `ChatOrchestratorUseCase` / `RunChatUseCase` — neither exists. The actual class is `ChatOrchestrator` (no `UseCase` suffix; defined at `services/rag-chat/src/rag_chat/application/use_cases/chat_orchestrator.py:140`). Beyond the naming, `execute_streaming` is a 13-step monolith that cannot be re-entered or composed. PLAN-0074 Wave F's "compose existing chat use case" instruction is unimplementable without a refactor first.

This plan does two things — both behaviour-preserving:

1. **Rename** `ChatOrchestrator` → `ChatOrchestratorUseCase` (consistent with other use cases in this layer: `GenerateBriefingUseCase`, `ChatPersistenceUseCase`, `ListThreadsUseCase`, etc.).
2. **Decompose** the monolithic `execute_streaming` into a `ChatPipeline` value object with composable steps so PLAN-0074 Wave F (entity-context chat) and PLAN-0067 W11-3 (tool-use loop) can both reuse the same pipeline pieces without duplicating logic.

---

## 1. Scope

| Wave | Title | Layer | Effort |
|------|-------|-------|--------|
| A | Rename `ChatOrchestrator` → `ChatOrchestratorUseCase` (+ all references) | application | 2 hours |
| B | Extract `ChatPipeline` value object (input validation, history load, retrieval, enrichment, fusion, rerank, prompt build, llm stream, output processing, persistence as composable steps) | application | 1 day |
| C | Migrate `ChatOrchestratorUseCase` to delegate to `ChatPipeline`; update tests to reflect new architecture | application + tests | ~4 hours |

## 2. Hard Constraints

- **Behaviour preserving**. Existing tests must all pass. No observable behavior change.
- **No new dependencies, no new env vars.** This is a pure refactor.
- **`ChatPipeline` is a value object, not a class with mutable state.** It composes injected collaborators (S6 client, S7 client, retrieval orchestrator, fusion, rerank, LLM chain) but holds no per-request state. Per-request state (auth, conversation_id, query) is passed to each step method as arguments.
- **Re-entrant.** `ChatPipeline` must support partial composition: PLAN-0074 Wave F needs to inject a system-prompt prefix between "history load" and "retrieval"; PLAN-0067 W11-3 needs to skip "intent classification" entirely (since it's being deleted) and substitute a tool-use loop.
- **Backwards-compatible during transition.** The route handlers in `services/rag-chat/src/rag_chat/api/routes/` are not changed — they continue calling `orchestrator.execute_streaming()` and `orchestrator.execute_sync()`.

## 3. Cross-cutting

- All references in PLAN-0066, PLAN-0067, PLAN-0074 are validated against `git grep "ChatOrchestratorUseCase"` after Wave A — if any plan mentions the old name `ChatOrchestrator`, it gets a §0 revision-log entry pointing here.
- Compounding: this plan is the proof-of-need for the `git grep` verification step added to `.claude/skills/plan/SKILL.md` (see BUG_PATTERNS.md BP-stale-class-name-in-plan).

## 4. Out of scope

- Hard-deleting the classical pipeline — that's PLAN-0067 W11-3.
- Adding tool-use — that's PLAN-0066 Wave H + PLAN-0067.
- Adding entity-context chat — that's PLAN-0074 Wave F.

---

## Wave A ✅ — Rename `ChatOrchestrator` → `ChatOrchestratorUseCase`

**Estimated effort**: 2 hours
**Status**: **DONE** — 2026-05-07 · 586 tests pass · ruff + mypy clean
**Depends on**: none

### Tasks

#### T-A-1: Rename class in chat_orchestrator.py
- **File scope**: `services/rag-chat/src/rag_chat/application/use_cases/chat_orchestrator.py`
- **Change**:
  - `class ChatOrchestrator:` → `class ChatOrchestratorUseCase:`
  - Update module-level docstring to reference `ChatOrchestratorUseCase`
- **Acceptance criteria**: Class defined as `ChatOrchestratorUseCase` at line ~140

#### T-A-2: Update all import + usage sites
- **File scope**:
  - `services/rag-chat/src/rag_chat/app.py` (lines 132, 151, 368, 385, 405-433 comments)
  - `services/rag-chat/src/rag_chat/api/routes/chat.py` (line 34 comment)
  - `services/rag-chat/tests/unit/application/test_general_intent.py` (lines 151, 161, 207)
- **Change**: Replace every occurrence of `ChatOrchestrator` with `ChatOrchestratorUseCase`
  - `app.py:132`: docstring `_wire_orchestrator` — update comment
  - `app.py:151`: import
  - `app.py:368`: instantiation
  - `app.py:405-433`: inline comments referencing the orchestrator
  - `chat.py:34`: docstring in `_get_orchestrator`
  - `test_general_intent.py:151`: import
  - `test_general_intent.py:161`: instantiation in fixture
  - `test_general_intent.py:207`: assertion message string
- **Acceptance criteria**: `git grep "ChatOrchestrator\b"` returns ZERO results (no bare `ChatOrchestrator` without `UseCase` suffix)

#### T-A-3: Export from use_cases __init__
- **File scope**: `services/rag-chat/src/rag_chat/application/use_cases/__init__.py`
- **Change**: Add `ChatOrchestratorUseCase` to exports if not already present (currently the __init__ only exports thread use cases)
- **Acceptance criteria**: `from rag_chat.application.use_cases import ChatOrchestratorUseCase` works

#### T-A-4: Validate
- **Commands**:
  ```bash
  cd services/rag-chat && ruff check src tests
  cd services/rag-chat && ruff format --check src tests
  cd services/rag-chat && python -m mypy src --config-file ../../mypy.ini
  cd services/rag-chat && python -m pytest tests/unit -v -x
  ```
- **Acceptance criteria**: All pass, zero errors

**Validation gate**:
- [x] `git grep "ChatOrchestrator\b"` returns 0 results
- [x] ruff check clean
- [x] mypy clean
- [x] All unit tests pass (target ~549 tests)

---

## Wave B ✅ — Extract `ChatPipeline` value object

**Estimated effort**: 1 day
**Status**: **DONE** — 2026-05-07 · 615 tests pass · ruff + mypy clean
**Depends on**: Wave A ✅

### Design

`ChatPipeline` is a frozen dataclass that holds all collaborators (validator, cache, rate limiter, etc.) and exposes each of the 13 pipeline steps as a named async/sync method. Per-request state (validated message, conversation history, intent, entities, etc.) is passed as arguments to each method and returned as the output of that method.

The `ChatOrchestratorUseCase` is NOT changed in this wave — it still calls `execute_streaming` internally. Wave C will wire the delegation.

```python
@dataclasses.dataclass(frozen=True)
class ChatPipeline:
    """Composable pipeline value object. Holds collaborators; all state is per-call."""

    # Collaborators (required)
    validator: InputValidator
    rate_limiter: RateLimiter
    cache: CompletionCache
    get_thread: GetThreadUseCase
    s6_client: S6Port
    classifier: Any  # OllamaIntentClassifier | DeepInfraIntentClassifier
    plan_builder: RetrievalPlanBuilder
    hyde: HydeExpander
    embedder: EmbeddingPort
    retrieval: ParallelRetrievalOrchestrator
    graph_enricher: GraphEnricher
    fusion: FusionPipeline
    reranker: Any  # BGEReranker | DeepInfraReranker | CohereReranker
    llm_chain: LLMProviderChain
    persistence: ChatPersistenceUseCase

    # Stateless helpers (default instantiated)
    context_assembler: ContextAssembler = dataclasses.field(default_factory=ContextAssembler)
    contradiction_assembler: ContradictionAssembler = dataclasses.field(default_factory=ContradictionAssembler)
    prompt_builder: PromptBuilder = dataclasses.field(default_factory=PromptBuilder)
    output_processor: OutputProcessor = dataclasses.field(default_factory=OutputProcessor)
    emitter: SSEEmitter = dataclasses.field(default_factory=SSEEmitter)
```

Step methods (all receive per-request state as args, return result):

| Method | Step | Returns |
|--------|------|---------|
| `validate_input(message)` | 0 | `str` (validated message) |
| `check_cache(message, thread_id)` | 1 | `dict \| None` |
| `check_rate_limit(tenant_id)` | 2 | `None` |
| `load_history(thread_id, user_id, tenant_id, uow)` | 3 | `list[ChatMessage]` |
| `resolve_entities(message)` | 4 | `list[ResolvedEntity]` |
| `classify_and_plan(message, history, entities, date_range)` | 5 | `tuple[QueryIntent, list[str], str \| None, RetrievalPlan]` |
| `expand_query(message, intent)` | 5bis | `tuple[str \| None, list[float] \| None]` |
| `embed_query(text)` | 5bis | `list[float]` |
| `retrieve(plan, resolved_query, request, embedding)` | 5A-5I | `list[RetrievedItem]` |
| `enrich_and_fuse(items)` | 6-7 | `list[RetrievedItem]` (sync) |
| `rerank_items(query, items)` | 8 | `list[RetrievedItem]` |
| `build_prompt(reranked, history, query, sub_questions, intent, type_counts)` | 9-10 | `tuple[str, list, str]` (prompt, contradiction_refs, context_block) |
| `stream_llm(prompt)` | 11 | `AsyncGenerator[tuple[str, str], None]` (filtered_chunk, raw_chunk) |
| `process_output(full_text, reranked)` | 12 | `tuple[str, list]` (answer, citations) |
| `persist_chat(...)` | 13 | `tuple[UUID, UUID]` |
| `write_completion_cache(message, thread_id, answer, citations)` | post-13 | `None` |

### Tasks

#### T-B-1: Create ChatPipeline frozen dataclass
- **File scope**: `services/rag-chat/src/rag_chat/application/pipeline/chat_pipeline.py` (new file)
- **Change**: Create `ChatPipeline` frozen dataclass with all 16 step methods listed above
  - Move `_ThinkBlockFilter` from `chat_orchestrator.py` to this module (keep reference in `chat_orchestrator.py` via import)
  - Each method encapsulates exactly the logic that is currently inline in `execute_streaming`
  - Preserve ALL existing metric emissions (rag_injection_blocked, rag_cache_hits, etc.) within the appropriate step methods
  - `build_prompt` emits `rag_contradiction_surfaced` per contradiction ref
  - `stream_llm` emits nothing (metric recorded by caller for full pipeline latency)
  - `retrieve` emits `rag_retrieval_items` after retrieving
  - Error handling: `validate_input` re-raises with injection block counter; `load_history` swallows and returns []; `persist_chat` swallows with structlog error; `write_completion_cache` swallows silently
- **Acceptance criteria**:
  - `ChatPipeline` importable from `rag_chat.application.pipeline.chat_pipeline`
  - All 16 step methods present with correct signatures
  - `frozen=True` on the dataclass
  - `_ThinkBlockFilter` defined in this module

#### T-B-2: Write unit tests for ChatPipeline steps
- **File scope**: `services/rag-chat/tests/unit/application/test_chat_pipeline.py` (new file)
- **Change**: Write unit tests for each step method (16 tests minimum)
  - Test happy path for each step
  - Test error handling: validate_input injection rejection, load_history swallows exception, persist_chat swallows exception, write_completion_cache swallows exception
  - Mock all collaborators at port boundaries (AsyncMock for async, MagicMock for sync)
  - Use `@pytest.mark.unit`
- **Acceptance criteria**: ≥16 tests, all pass

#### T-B-3: Validate
- **Commands**:
  ```bash
  cd services/rag-chat && ruff check src tests
  cd services/rag-chat && ruff format --check src tests
  cd services/rag-chat && python -m mypy src --config-file ../../mypy.ini
  cd services/rag-chat && python -m pytest tests/unit -v -x
  ```
- **Acceptance criteria**: All pass, zero errors, new tests green

**Validation gate**:
- [x] `ChatPipeline` has 16 step methods
- [x] `frozen=True` on the dataclass
- [x] `_ThinkBlockFilter` in `chat_pipeline.py`
- [x] ≥16 new unit tests in `test_chat_pipeline.py` (29 tests added)
- [x] ruff + mypy + all unit tests pass (615 total)

---

## Wave C ✅ — Migrate `ChatOrchestratorUseCase` to delegate to `ChatPipeline`

**Estimated effort**: ~4 hours
**Status**: **DONE** — 2026-05-07 · 615 tests pass · ruff + mypy clean
**Depends on**: Wave B ✅

### Design

`ChatOrchestratorUseCase` gets a new constructor that accepts `ChatPipeline` instead of 15 individual collaborators. The `execute_streaming` method is rewritten as a composition of `ChatPipeline` step calls with SSE emission interspersed. The `execute_sync` wrapper is unchanged. Routes are NOT changed.

```python
class ChatOrchestratorUseCase:
    def __init__(self, pipeline: ChatPipeline) -> None:
        self._pipeline = pipeline

    async def execute_streaming(self, request: ChatRequest, uow: RagUnitOfWorkPort) -> AsyncGenerator:
        start = datetime.now(tz=UTC)
        thread_id = request.thread_id or _new_thread_id()

        # Step 0 — validates + counts injections
        validated_message = await self._pipeline.validate_input(request.message)

        # Step 1 — cache check
        cached = await self._pipeline.check_cache(request.message, request.thread_id)
        if cached:
            rag_cache_hits.labels(cache_type="completion").inc()
            yield self._pipeline.emitter.emit_status("cache_hit")
            ...
            return

        # Step 2 — rate limit
        await self._pipeline.check_rate_limit(request.tenant_id)
        yield self._pipeline.emitter.emit_status("loading_context")

        # Step 3 — history
        history = await self._pipeline.load_history(request.thread_id, request.user_id, request.tenant_id, uow)
        yield self._pipeline.emitter.emit_status("entity_resolution")

        # Step 4 — entities
        entities = await self._pipeline.resolve_entities(validated_message)
        yield self._pipeline.emitter.emit_status("intent_classification")

        # Step 5 — intent + plan
        intent, sub_questions, rephrased, plan = await self._pipeline.classify_and_plan(
            validated_message, history, entities, request.context.date_range
        )
        effective_query = rephrased or validated_message
        yield self._pipeline.emitter.emit_status("query_expansion")

        # Step 5bis — HyDE + embed
        _hypothesis, hyde_embedding = await self._pipeline.expand_query(effective_query, intent)
        query_embedding = hyde_embedding or await self._pipeline.embed_query(effective_query)
        resolved_query = ResolvedQuery(
            intent=intent,
            rephrased_query=effective_query,
            sub_questions=tuple(sub_questions),
            resolved_entities=tuple(entities),
            hyde_hypothesis=_hypothesis,
        )
        yield self._pipeline.emitter.emit_status("parallel_retrieval")

        # Steps 5A-5I — retrieval (emits rag_retrieval_items inside)
        raw_items = await self._pipeline.retrieve(plan, resolved_query, request, query_embedding)
        _type_counts = Counter(item.item_type.value for item in raw_items)

        # Steps 6-7 — enrich + fuse
        fused = self._pipeline.enrich_and_fuse(raw_items)
        yield self._pipeline.emitter.emit_status("ranking_evidence")

        # Step 8 — rerank
        reranked = await self._pipeline.rerank_items(effective_query, fused)
        if fused and reranked:
            record_reranker_position_change(fused[0].item_id != reranked[0].item_id)

        # Steps 9-10 — build prompt (emits contradiction metrics inside)
        prompt, contradiction_refs, _ctx = await self._pipeline.build_prompt(
            reranked, history, effective_query, tuple(sub_questions), intent, _type_counts
        )

        # Step 11 — LLM stream
        full_text = ""
        provider_name = "unknown"
        async for filtered, raw in self._pipeline.stream_llm(prompt):
            full_text += raw
            if filtered:
                yield self._pipeline.emitter.emit_token(filtered)
        provider_name = self._pipeline.llm_chain.last_provider_name

        # Step 12 — output processing
        answer, citations = self._pipeline.process_output(full_text, reranked)
        latency_ms = int((datetime.now(tz=UTC) - start).total_seconds() * 1000)

        yield self._pipeline.emitter.emit_citations(citations)
        yield self._pipeline.emitter.emit_contradictions(contradiction_refs)

        _model_id = _resolve_model_id(self._pipeline.llm_chain, provider_name)
        token_count_in_est = len(prompt) // 4

        # Step 13 — persist (best-effort, swallows inside pipeline)
        asst_msg_id = _new_thread_id()
        try:
            _user_msg_id, asst_msg_id = await self._pipeline.persist_chat(
                thread_id=thread_id, user_message=request.message,
                assistant_response=AssistantResponse(
                    content=answer, intent=intent, resolved_entities=tuple(entities),
                    retrieval_plan=plan, citations=tuple(citations),
                    contradiction_refs=tuple(contradiction_refs),
                    provider=provider_name, model=_model_id,
                    token_count_in=token_count_in_est, token_count_out=len(full_text.split()),
                    latency_ms=latency_ms,
                ),
                uow=uow, tenant_id=request.tenant_id, user_id=request.user_id,
            )
        except Exception as exc:
            log.error("chat_persistence_failed", error=str(exc))

        # Cache write (best-effort)
        await self._pipeline.write_completion_cache(request.message, request.thread_id, answer, citations)

        # Emit metrics
        _total_latency_s = (datetime.now(tz=UTC) - start).total_seconds()
        rag_queries_total.labels(intent=intent.value, provider=provider_name, tenant_id=str(request.tenant_id)).inc()
        rag_latency.labels(intent=intent.value, step="total").observe(_total_latency_s)

        yield self._pipeline.emitter.emit_metadata(thread_id, asst_msg_id, intent.value, provider_name, latency_ms)
        yield self._pipeline.emitter.emit_done()
```

`app.py` wiring change: construct `ChatPipeline` first, then pass to `ChatOrchestratorUseCase(pipeline=pipeline)`.

### Tasks

#### T-C-1: Rewrite ChatOrchestratorUseCase to delegate to ChatPipeline
- **File scope**: `services/rag-chat/src/rag_chat/application/use_cases/chat_orchestrator.py`
- **Change**:
  - Replace 15-arg `__init__` with single `pipeline: ChatPipeline` arg
  - Rewrite `execute_streaming` as composition of step calls (as designed above)
  - Keep `execute_sync` unchanged (still iterates `execute_streaming`)
  - Remove `_ThinkBlockFilter` from this module (it's now in `chat_pipeline.py`) — import it from there
  - Add `_resolve_model_id(llm_chain, provider_name) -> str` helper (extracted from inline block in original)
- **Acceptance criteria**:
  - `ChatOrchestratorUseCase.__init__` accepts only `pipeline: ChatPipeline`
  - `execute_streaming` calls step methods; no inline logic (all logic in `ChatPipeline`)
  - `execute_sync` unchanged

#### T-C-2: Update app.py to wire ChatPipeline
- **File scope**: `services/rag-chat/src/rag_chat/app.py`
- **Change**:
  - In `_wire_orchestrator`: construct `ChatPipeline(validator=..., rate_limiter=..., ...)` with all 15 collaborators
  - Then construct `ChatOrchestratorUseCase(pipeline=pipeline)`
  - Store `app.state.chat_orchestrator = orchestrator` (unchanged key)
  - Import `ChatPipeline` from `rag_chat.application.pipeline.chat_pipeline`
- **Acceptance criteria**: App starts; `_wire_orchestrator` uses `ChatPipeline`

#### T-C-3: Update test_general_intent.py to use new constructor
- **File scope**: `services/rag-chat/tests/unit/application/test_general_intent.py`
- **Change**:
  - `test_orchestrator_passes_intent_to_prompt_builder`: construct `ChatPipeline` with mocked deps, then `ChatOrchestratorUseCase(pipeline=pipeline)`
  - Update `orch._prompt_builder` → `orch._pipeline.prompt_builder` (now lives in pipeline)
  - Assertion string update if needed
- **Acceptance criteria**: Test passes without modification to the assertion intent

#### T-C-4: Validate
- **Commands**:
  ```bash
  cd services/rag-chat && ruff check src tests
  cd services/rag-chat && ruff format --check src tests
  cd services/rag-chat && python -m mypy src --config-file ../../mypy.ini
  cd services/rag-chat && python -m pytest tests/unit -v -x
  ```
- **Acceptance criteria**: All pass; no tests deleted or weakened

**Validation gate**:
- [x] `ChatOrchestratorUseCase.__init__` has single `pipeline: ChatPipeline` arg
- [x] `execute_streaming` delegates to pipeline step methods (no inline logic)
- [x] `app.py` constructs `ChatPipeline` before `ChatOrchestratorUseCase`
- [x] `test_orchestrator_passes_intent_to_prompt_builder` uses new constructor style
- [x] ruff + mypy + all unit tests pass (no tests deleted or weakened — 615 total)

---

## Regression Guardrails

- BP-023: ruff format version pinned — use `~/.cache/pre-commit/` ruff, not uvx
- BP-065: fix ruff before `git add`
- R19: no test deletion

## Plan References

- `services/rag-chat/src/rag_chat/application/use_cases/chat_orchestrator.py` — main file
- `services/rag-chat/src/rag_chat/app.py` — wiring
- `services/rag-chat/src/rag_chat/api/routes/chat.py` — routes (NOT changed)
- `services/rag-chat/tests/unit/application/test_general_intent.py` — test update needed
- `services/rag-chat/tests/unit/api/test_chat.py` — NOT changed (mocks orchestrator generically)
