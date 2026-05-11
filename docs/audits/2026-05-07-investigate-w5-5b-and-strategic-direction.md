# Investigation Report: W5-5b QA Findings + Strategic Direction

**Date**: 2026-05-07
**Investigator**: Claude (`/investigate` skill)
**Severity**: HIGH (4 findings touch production correctness; rest are architectural debt)
**Status**: Root causes identified, recommendations ready, hand-off to `/plan` for the deferred items

---

## Issues Investigated

This report covers the BLOCKING/CRITICAL/MAJOR findings from the 2026-05-07 QA pass on PLAN-0063 that were **not** auto-fixed in the QA close-out commit:

1. **F-X11 / F-X12 / F-D03** — Article consumer idempotency gap (R9 compliance, deterministic IDs vs dedup table).
2. **F-X09** — CI eval gate fails open (`continue-on-error: true`, empty per_query → exit 0).
3. **F-A04 / F-A05** — Missing port-ABCs for `ChunkANNRepository`, `CanonicalEntityRepository`, `IntentClassifier*`.
4. **F-A02** — Adaptive lexical boost sweep plumbed but never run.
5. **F-D04** — `chunks.chunk_text` storage budget undocumented.
6. **F-D06** — Migration `0026` lacks `LOCK TABLE ... NOWAIT`.
7. **F-D08** — All 120 golden queries reviewed by a single agent; second-reviewer pass deferred.

Plus a strategic recommendation on the long-term competitive direction (Bloomberg / Lona / Godel positioning, sandbox-and-AI-strategy ecosystem).

---

## 1. Article Consumer Idempotency (F-X11 / F-X12 / F-D03)

### 1.1 What the code actually does today

`services/nlp-pipeline/src/nlp_pipeline/infrastructure/messaging/consumers/article_consumer.py:796-800`:

```python
async def is_duplicate(self, event_id: str) -> bool:
    return False  # At-least-once; idempotency via DB-level constraints

async def mark_processed(self, event_id: str) -> None:
    pass
```

The consumer's docstring claims "idempotency via DB-level constraints", but on inspection only **a subset** of the writes are in fact deterministic:

| Write target | ID generation | Deterministic on replay? |
|---|---|---|
| `routing_decisions.decision_id` | `common.ids.new_uuid7()` (line 362) | NO |
| `routing_decisions.doc_id` | from inbound event | YES — early-skip at line 245 catches replay if commit already happened |
| `sections.section_id` | from chunker (deterministic per `(doc_id, ord)`) | YES (`ON CONFLICT DO NOTHING` would catch it) |
| `chunks.chunk_id` | from chunker | YES |
| `entity_mentions.mention_id` | `new_uuid7()` per row | **NO — duplicates on replay** |
| `embeddings.embedding_id` | `new_uuid7()` per row (lines 887, 904) | **NO — duplicates on replay** |
| `outbox.event_id` (`nlp.article.enriched.v1`) | `new_uuid7()` (line 1054) | **NO — duplicates downstream** |
| `outbox.event_id` (`nlp.signal.detected.v1`) | `new_uuid7()` (line 1543) | **NO** |
| `provisional_entity_queue` rows (intel_db) | natural key `(normalized_surface, mention_class)` | YES (UNIQUE constraint) |

The early-skip at line 245 (`routing_decision.exists()`) protects the **happy path** — a re-delivered message after a successful commit returns immediately. But **three failure modes bypass the skip**:

1. **Concurrent rebalance**: Kafka rebalances the partition mid-processing; another worker picks up the same `event_id`. Both see `routing_decision is None` (the first hasn't committed yet); both run the full pipeline; both attempt to commit. The second loses on routing_decisions PK but only **after** committing fresh `mention_id`s, fresh `embedding_id`s, and a fresh outbound `nlp.article.enriched.v1` event with a different `event_id`.
2. **Intel-commit failure** (D-004 split-brain at line 689-699): NLP commits, intel commit fails and is swallowed, the next re-delivery is skipped because routing_decision exists, **intel writes are never retried**. The class docstring on line 686-688 claims "idempotent on retry" but the early-skip prevents the retry from happening.
3. **Worker crash between intel commit and outbox dispatch**: same shape — outbox event is queued in nlp_db but the message offset is not committed; on restart, the message replays, routing_decisions exists, **the outbox is now duplicated** because the outbox row from the first run still sits in `pending` state and a fresh outbox row from the second run cannot be added (the first run's nlp_session was already committed). Wait — actually on inspection, the second run's early-skip at line 245 fires before the outbox row is written. But the **first** run's outbox event is non-deterministic (`new_uuid7()`), so once delivered to KG, KG sees it as net-new; that's fine. The downstream KG consumer DOES use deterministic event_ids inside the payload via `uuid5_from_parts(doc_id, subject_entity_id, event_type)` (`services/knowledge-graph/src/knowledge_graph/application/blocks/graph_write.py:191`) so the inner-event ON CONFLICT DO NOTHING works. **The wrapper event_id mismatch is benign for KG** because KG's dedup is per-event-content, not per-Kafka-event-id.

### 1.2 What R9 says vs what the platform actually does

**R9** (`RULES.md:90-94`):
> Every consumer must:
> - Check `event_id` against a processed-events table before processing
> - Use upsert (INSERT ON CONFLICT) for materializations
> - Be safe to re-run on the same event

The "check event_id against a processed-events table" clause is unambiguous. The `Explore` survey of 8 representative consumers found:

- **4 consumers comply via Valkey** (KG `enriched_consumer.py`, `entity_consumer.py`, `temporal_event_consumer.py`, `provisional_queued_consumer.py`):
  ```python
  async def is_duplicate(self, event_id: str) -> bool:
      key = f"{self._dedup_prefix}:{event_id}"
      return bool(await self._dedup_client.exists(key))

  async def mark_processed(self, event_id: str) -> None:
      await self._dedup_client.set(key, "1", ex=86400)  # 24h TTL
  ```
- **4 consumers do not** (`article_consumer.py`, `ohlcv_consumer.py`, `fundamentals_consumer.py`, `intraday_resampling_consumer.py`) — they all return `False` from `is_duplicate` and rely on DB-level PK / UNIQUE constraints.

**The platform is therefore split into two consumer-idempotency dialects.** R9 is enforced by half the consumers and openly violated by the other half. This is a documented-pattern drift (the kind that compounds).

### 1.3 The user's question: outbox-pattern equivalent for consumers, or derived UUIDs?

The right answer is **both, with a clear contract** — they solve different problems:

| Mechanism | What it protects against | Cost | Where it fits |
|---|---|---|---|
| **Valkey-backed `processed_events` (or DB table)** | Re-delivery storms, rebalance double-processing, between-commit-and-offset crashes | One Valkey hit per message; one Valkey set per success (~0.5ms) | At the **consumer boundary** — protects expensive ML work from re-running |
| **Deterministic UUIDs (`uuid5_from_parts`)** | Insertion-level duplicate rows when the message DOES re-run for any reason (network blip during dedup-check, Valkey unavailable, etc.) | Compute one hash per row; ON CONFLICT DO NOTHING handles collisions | At the **DB write boundary** — protects rows from duplicating |

The mature pattern is:

1. **`is_duplicate` + `mark_processed` via Valkey** with a 24h TTL (matches the existing KG-consumer convention so consumers behave identically across the platform).
2. **All generated IDs deterministic via `uuid5_from_parts`** for any row whose identity is fully determined by the upstream message — `(doc_id, mention_seq, normalized_surface)` for mentions, `(doc_id, chunk_id, model_id)` for embeddings, `(doc_id, event_kind)` for outbox events.
3. **The producer-side outbox pattern (R8) is unchanged** — that's about transactional dual-writes from a single service, not about cross-service Kafka delivery.

The Valkey check is the cheap fast-path; the deterministic UUIDs are the slow-path safety net. **The slow-path is what lets you remove the Valkey check for cost reasons later, or tolerate Valkey outages without data corruption.**

### 1.4 Why I don't recommend a `processed_events` table in nlp_db

Three reasons:

1. **Two services already do Valkey-only dedup** (KG service). Pivoting nlp-pipeline to a DB table fragments the pattern further.
2. **Volume**: at design throughput (50K articles/day × 8 consumer groups = 400K events/day), a DB table grows by 11M rows/month. You'd need partitioning and a retention policy. Valkey's 24h TTL gets you the same correctness guarantee for free.
3. **Latency**: a DB hit per message before processing adds 5-15ms vs <1ms for Valkey. At 100 articles/sec sustained ingest that's 1.5s of pure dedup overhead per second, half the budget for Block 5 NER.

**The only argument for the DB table is "Valkey is unavailable"** — and the existing KG consumers handle that by returning `False` (at-least-once fallback) and logging `enriched_consumer.valkey_check_failed`. With deterministic IDs in place, the at-least-once fallback is safe.

### 1.5 Recommendation: a single platform standard, encoded in `BaseKafkaConsumer`

Promote the existing Valkey pattern from "individual KG-consumer convention" to **a `BaseKafkaConsumer` mixin** that ships in `libs/messaging`. Two new classes:

```python
# libs/messaging/src/messaging/kafka/consumer/dedup.py

class ValkeyDedupMixin:
    """Standard idempotency mixin for BaseKafkaConsumer.

    Implements `is_duplicate` and `mark_processed` against a Valkey set with
    a 24h TTL. Subclasses pass in a Valkey client and a key prefix at
    construction. On Valkey failure, returns False (at-least-once fallback).
    """
    _dedup_client: ValkeyClient | None
    _dedup_prefix: str
    _dedup_ttl_seconds: int = 86400

    async def is_duplicate(self, event_id: str) -> bool:
        if self._dedup_client is None:
            return False
        try:
            return bool(await self._dedup_client.exists(
                f"{self._dedup_prefix}:{event_id}"
            ))
        except Exception:
            logger.warning("dedup.valkey_check_failed", event_id=event_id, exc_info=True)
            return False

    async def mark_processed(self, event_id: str) -> None:
        if self._dedup_client is None:
            return
        try:
            await self._dedup_client.set(
                f"{self._dedup_prefix}:{event_id}", "1", ex=self._dedup_ttl_seconds
            )
        except Exception:
            logger.warning("dedup.valkey_mark_failed", event_id=event_id, exc_info=True)
```

Then:

- **Every consumer that currently uses the Valkey pattern** switches to inheriting `ValkeyDedupMixin` and deletes its hand-rolled copy. ~4 consumers, ~80 LOC removed.
- **`ArticleProcessingConsumer`** mixes in `ValkeyDedupMixin` (lines 796-800 deleted) and gains R9 compliance for free.
- **The 3 market-data consumers** (`ohlcv_consumer`, `fundamentals_consumer`, `intraday_resampling_consumer`) — these write to atomic `create_if_not_exists()` patterns and could either (a) adopt the mixin too for consistency, or (b) document explicitly that their DB-level idempotency is a deliberate exception. Recommend (a) — consistency wins.

In parallel:

- **Replace `new_uuid7()` with `uuid5_from_parts()` for every row whose identity is fully determined by the upstream message** in `_run_pipeline`. The hashes are:
  - `routing_decisions.decision_id` → `uuid5_from_parts(doc_id, "routing_decision")`
  - `entity_mentions.mention_id` → `uuid5_from_parts(doc_id, str(mention_index), normalized_surface)` — `mention_index` is the position in the deterministic ordering of mentions extracted from the article, which is reproducible.
  - `embeddings.embedding_id` → `uuid5_from_parts(doc_id, chunk_id_or_section_id, model_id)`
  - Outbox `event_id` for `nlp.article.enriched.v1` → `uuid5_from_parts(doc_id, "article_enriched_v1")`
  - Outbox `event_id` for `nlp.signal.detected.v1` → `uuid5_from_parts(doc_id, signal_kind, str(signal_index))`

This is a ~50 LOC change in `article_consumer.py` plus a migration to add `ON CONFLICT DO NOTHING` clauses to the relevant inserts (most already have them; verify each). No schema changes, no new tables.

### 1.6 STANDARDS.md changes

Promote the pattern explicitly:

- New §11 anti-pattern row: "Hand-rolled `is_duplicate`/`mark_processed` per consumer → use `ValkeyDedupMixin` from `libs/messaging`."
- New §3 subsection "3.11 Consumer Dedup — ALWAYS use `ValkeyDedupMixin`" with the rationale and the mixin contract.
- Update R9 wording to clarify: "the processed-events check is satisfied by `ValkeyDedupMixin` for the standard at-least-once contract; consumers that bypass it must document a stronger guarantee in their docstring (e.g. atomic `create_if_not_exists` natural-key idempotency) and the architecture test must allowlist them."

### 1.7 Recommended fix sequence

1. Ship `ValkeyDedupMixin` in `libs/messaging` with tests.
2. Migrate the 4 KG consumers (no behavior change; refactor only).
3. Migrate `ArticleProcessingConsumer`. Pair with the deterministic-ID changes for `_run_pipeline`. Run the full nlp-pipeline + KG integration test.
4. Migrate the 3 market-data consumers (or add a one-line allowlist + docstring claim).
5. Update STANDARDS.md and add an architecture test asserting either (a) the mixin is in MRO, or (b) the consumer is on the allowlist.
6. Update `docs/BUG_PATTERNS.md` — new BP for "Hand-rolled is_duplicate dialect drift".

**Effort estimate**: ~250 LOC for the mixin + tests + 7 consumer migrations + 1 architecture test + STANDARDS update. ~half a day.
**Risk**: Low. Pure refactor on the 4 already-Valkey consumers. The article-consumer migration is the only behavior change; the deterministic IDs only matter on replay, which is the failure mode we're trying to fix. Unit tests verify the IDs are stable; integration tests verify full re-delivery is a no-op.

---

## 2. F-X09 — CI Eval Gate Fails Open

### 2.1 What's happening

Two compounding issues:

**(a)** `.github/workflows/retrieval-eval.yml:137` — `continue-on-error: true` is set on the `full-eval-disabled-gate` job. Even if the eval script exits non-zero, the workflow step succeeds. The comment at line 137 says this was retained per L3 (gate to enable in W5-3) but slipped through W5-3, W5-4, and W5-5.

**(b)** `scripts/eval_retrieval.py:552-559`:

```python
if not per_query:
    print("ERROR: no queries evaluated (all rows skipped or failed)...", file=sys.stderr)
    # Exit 0 because in W5-1 the labelling is in flight; the CI gate is
    # disabled during this period.
    return 0
```

So if the labelled subset is zero (network failure mid-run that drops every query, misconfigured RAG_CHAT_URL pointing at a 404 endpoint, JWT minting throwing 500 on every query), the script exits 0 and the workflow passes.

**(c)** No smoke probe verifies that `/v1/internal/retrieve` is actually reachable from CI before the eval run starts. A misconfigured `RAG_CHAT_URL` is silently treated as "no labelled queries match".

### 2.2 What "fix this" actually means in the long run

The user is right that the CI gate is the load-bearing piece for retrieval quality. The long-term plan needs three things, in this order:

#### 2.2.1 Pre-flight smoke probe

Add a CI step **before** the full eval that does a single curl against `/v1/internal/retrieve` with one well-known query and asserts a 200 with `n_candidates >= 1`. If the probe fails, the workflow fails immediately with a clear error. This is 10 lines of YAML.

```yaml
- name: Smoke probe — verify /v1/internal/retrieve reachable
  run: |
    payload='{"query_text":"Apple Q4 earnings","top_k":5}'
    response=$(curl -sS -X POST "${RAG_CHAT_URL}/v1/internal/retrieve" \
      -H "Content-Type: application/json" \
      -H "X-Internal-JWT: ${EVAL_INTERNAL_JWT}" \
      -d "$payload")
    n=$(echo "$response" | jq -r '.n_candidates // 0')
    if [ "$n" -lt 1 ]; then
      echo "ERROR: smoke probe returned $n candidates: $response"
      exit 1
    fi
    echo "OK: smoke probe returned $n candidates"
```

#### 2.2.2 Tighten the empty-`per_query` exit code

Once the labelling is at 100% (and the platform's first-class regression gate is the eval), `eval_retrieval.py` returning 0 on empty `per_query` is no longer defensive — it's a hole. Replace lines 552-559:

```python
if not per_query:
    print("ERROR: no queries evaluated (all rows skipped or failed). "
          "Either the golden set is empty or every query failed retrieval.", file=sys.stderr)
    return 1  # Hard fail — the gate is meaningful only if it requires evidence.
```

But this is gated on completing the labelling (F-D08, ~59 queries remaining). Currently 61/120 are graded; per the v2 stratification, the gate runs against whatever has `relevant_doc_ids` populated. Reasonable next step: continue graceful exit until ≥80% labelled, then flip.

#### 2.2.3 Remove `continue-on-error: true`

Once (a) and (b) above are in place, the line just gets deleted. The workflow then truly fails the PR on regression.

#### 2.2.4 The deeper question — what should the gate measure?

Right now the gate is a single global NDCG@10 number with a 0.03 absolute regression threshold. PRD-0034 §3 FR-T1-2 originally asked for **per-intent** NDCG. The L3 lock recommends **per-class** NDCG with a per-class regression threshold. This is implemented in `aggregate()` in `scripts/eval_retrieval.py` but the CI gate currently only checks the global number. **A single PR could improve global NDCG by +0.05 while regressing the `identifier_lookup` class by -0.10 — and the gate would pass.**

The long-term gate needs:

1. **Per-class NDCG@10** — already computed; needs to be the unit the gate checks.
2. **Per-class regression threshold** — currently a single global `--fail-on-regression 0.03`; should be `--fail-on-regression-per-class 0.03 --fail-on-regression-global 0.02`.
3. **A "no class can have <X queries" sanity** — if `non_analyst` falls below 6 graded queries, the gate output is statistically noise; surface a clear warning.
4. **Result-instability investigation** flagged by the W5-3 capture audit (`docs/audits/2026-05-07-w5-3-baseline-capture.md`) — the labelling subagent saw NDCG variance run-to-run that is incompatible with a 0.03 threshold. Either snapshot-isolation (F-X08) or query-batching variance is the cause; needs a follow-up investigation.

### 2.3 Recommended fix sequence

Wave W5-6 (or a parallel hardening wave):
1. Smoke probe step (5 min).
2. Per-class regression check + threshold flag (~30 min in `eval_retrieval.py`).
3. Investigate result-instability — likely a 1-2 hour dive (use `/investigate` on the W5-3 audit's evidence).
4. Once instability is closed and ≥80% labelled, flip `continue-on-error: true` and the empty-`per_query` exit code.

**Net effect**: the gate becomes the kind of safety net that lets you change the retrieval substrate aggressively without fear of silent regressions.

---

## 3. Port-ABC Extraction (F-A04 / F-A05)

### 3.1 What ABCs already exist vs. what's missing

The nlp-pipeline application layer already defines several ports in `services/nlp-pipeline/src/nlp_pipeline/application/ports/repositories.py`:

- `DLQRepositoryPort` (line 45)
- `SignalsQueryPort` (line 67)
- `ChunkTextStorePort` (line 139)
- `DocumentSourceMetadataRepository` (line 168)
- `PriceImpactRepositoryPort` (line 189)
- `NewsQueryPort` (line 288)
- `ArticleImpactWindowRepositoryPort` (line 352)

So the convention exists. What's missing:

- **`ChunkSearchPort`** — would wrap `ChunkANNRepository`. Methods: `ann_search`, `lexical_search` (NEW from W5-2), `fetch_entity_mentions`. Currently `EnhancedChunkSearchUseCase` types `chunk_ann_repo: ChunkANNRepository` directly (`enhanced_chunk_search.py:32-37`) — a TYPE_CHECKING import from `infrastructure/`, which is the smell. Runtime works; architectural integrity does not.
- **`CanonicalEntityPort`** — would wrap `CanonicalEntityRepository`. Methods: `batch_get`, `find_by_name_and_type`, `create`. The KG service already has a similar ABC named `CanonicalEntityRepositoryPort` (mentioned in PLAN-0076 deferred items as "missing get_by_id/find_by_name_and_type/create"). nlp-pipeline currently imports the concrete class.
- **`IntentClassifierPort`** — `OllamaIntentClassifier` and `DeepInfraIntentClassifier` are duck-typed today. `RetrieveOnlyUseCase` advertises `OllamaIntentClassifier` in its constructor signature, which is wrong half the time (production runs DeepInfra). A `Protocol` with a single `classify(text, history, entities) -> tuple[str, list[str], str]` is enough.

### 3.2 Why the ABCs matter (not academic)

Three concrete benefits:

1. **PLAN-0067 W11-3 will hard-delete the IntentClassifier path entirely** (per PLAN-0067 §0 A-1). The work-in-progress code that surrounds it will be churned. Having `IntentClassifierPort` makes the surgical removal of one implementation cleaner — you delete one adapter, not nine import sites. Without the ABC, the deletion turns into a sed-and-pray refactor.
2. **Testing**: `EnhancedChunkSearchUseCase` is currently tested with `chunk_ann_repo=Mock()`. Once `ChunkSearchPort` exists, you get type-checked stub repositories (`StubChunkSearchPort` implementing the ABC) and mypy enforces method-signature parity between the stub and the real implementation. The `search_type` wire-forwarding bug in `S6Client` (F-Q06 from QA) would have been caught by a port-conformant fake.
3. **Multiple back-ends**: when PLAN-0067 introduces a tool-calling alternative path or PLAN-0064 introduces a documents-search path that may want a different backing store (full-text vs hybrid), having `ChunkSearchPort` lets both implementations coexist behind one port. Without it, every branch in the codebase has to know which concrete class is wired in which deployment.

### 3.3 Recommended approach

**Phase 1 — Define ports in their service's `application/ports/`** (no behavior change):

```python
# services/nlp-pipeline/src/nlp_pipeline/application/ports/chunk_search.py
class ChunkSearchPort(ABC):
    @abstractmethod
    async def ann_search(self, *, query_embedding: list[float], top_k: int,
                          filters: ChunkFilters) -> tuple[list[ChunkHit], int]: ...

    @abstractmethod
    async def lexical_search(self, *, query_text: str, top_k: int,
                              mode: Literal["english", "simple", "both"],
                              filters: ChunkFilters) -> tuple[list[ChunkHit], int]: ...

    @abstractmethod
    async def fetch_entity_mentions(self, chunk_ids: Sequence[UUID]) -> dict[UUID, list[Mention]]: ...
```

**Phase 2 — Make `ChunkANNRepository` register as the ABC** (existing class implements the same methods; just add inheritance + decorator). No call-site changes.

**Phase 3 — Re-type the use case dependencies** from the concrete class to the ABC. Mypy passes because the concrete class is a subtype.

**Phase 4 — In tests, replace `Mock()` with a `StubChunkSearchPort` derived from the ABC**. This is where the test-quality benefit lands.

Same recipe for `CanonicalEntityPort` and `IntentClassifierPort`.

**Effort**: ~150 LOC per port + ~50 LOC of test updates. Low risk because behavior doesn't change. **Total ~3-4 hours.**

**Sequencing**: do this BEFORE PLAN-0067 begins (PLAN-0067 W11-3 hard-deletes the classifier and reshapes the chunk-search call sites; introducing ports beforehand makes the eventual deletion mechanical).

---

## 4. F-A02 — Adaptive Lexical Boost Sweep Never Run

### 4.1 What's pending

PLAN-0063 §0-bis L9 specified "adaptive lexical boost factor TUNED by `--mode hybrid_boost_sweep`". The infrastructure shipped in W5-3:
- `scripts/eval_retrieval.py:601` — `select_optimal_boost(...)` function.
- `Settings.hybrid_lexical_boost: float = 1.5` — the placeholder.
- `enhanced_chunk_search.py:124-135` — boost factor is wired into the RRF fusion path.

What didn't ship: the actual sweep run + value commit. `results/` contains baseline + post-hybrid eval but no `boost_sweep_*.json`.

### 4.2 What it actually takes to run

The `--mode hybrid_boost_sweep` runs the eval N times across boost factors `[1.0, 1.25, 1.5, 1.75, 2.0, 2.5]` (typical), picks the value that maximises `identifier_lookup` NDCG@10 without regressing other classes by ≥0.02, and writes `results/boost_sweep_<ts>.json`. With 61 graded queries and ~3-second per-query latency, each sweep iteration is ~3 minutes; the full sweep is ~20 minutes against the live dev stack.

The blocker is **(a)** the dev stack must be up with DeepInfra credentials, **(b)** the labelled set should be ≥80% complete to make the optimum statistically meaningful (currently 51%), and **(c)** the result-instability flagged by W5-3 audit means the same boost factor may produce different NDCG numbers across sweep runs.

### 4.3 Recommendation

Do not run the sweep yet. Sequence:

1. Resolve result-instability (W5-3 audit follow-up; see §2.2.4).
2. Complete labelling to ≥80% (target 96+ queries).
3. Then run the sweep, commit the artifact, update `Settings.hybrid_lexical_boost` default from 1.5 to the chosen value, update PLAN-0063 §0-bis L9 to record the empirical result.

**Until then, the placeholder value of 1.5 is documented and acceptable.** The remaining QA finding (F-A02) should be re-classified from MAJOR to "tracked work item, gated on result-instability close-out".

---

## 5. F-D04 — `chunks.chunk_text` Storage Budget

### 5.1 What's pending

Migration `0017_add_chunks_tsv_english_gin.py` adds `chunk_text TEXT` (denormalised body) to `chunks`. At target scale (≥10K chunks/day from PLAN-0064 W6 + universe expansion), this column dominates per-row size.

### 5.2 What good looks like

The migration's docstring should specify:
- Expected median chunk_text size (currently ~3KB based on chunker target).
- Expected p99 chunk_text size (currently ~8KB; cap at 8192 with a `CHECK` constraint).
- Expected `chunks` table size at 1M rows (~3-4 GB on disk including TOAST).
- Expected GIN index size (`tsv_english`) at 1M rows (~500MB-1GB).
- Autovacuum tuning for the `chunks` table (default settings will struggle past 10M rows).
- Retirement plan: when does this column go away? PLAN-0064 W6 may render it redundant if W6 adopts external snippet rendering.

This is **documentation, not code**. The migration ships; the docstring grows. ~30 minutes.

### 5.3 The bigger question

W5-6 (ingestion bench) is supposed to measure exactly this — single-row insert p99, retrieval p95 during ingest, autovacuum frequency. The L10 thresholds are encoded; what's missing is **a "table size growth" line item** in W5-6's bench report. Add it.

---

## 6. F-D06 — Migration `0026` Lacks `LOCK TABLE ... NOWAIT`

### 6.1 What's pending

`services/intelligence-migrations/alembic/versions/0026_add_canonical_entities_dedup_index.py` runs a 132-group dedup across 11 tables inside a single anonymous DO block. No explicit `LOCK TABLE ... ACCESS EXCLUSIVE NOWAIT` at the top — so on a populated DB the migration acquires locks lazily and can deadlock or queue indefinitely behind a concurrent writer.

R26 says no production instance currently exists, so this is acceptable for the dev stack. But the migration is still in `services/intelligence-migrations/` and will be replayed against the first production instance verbatim.

### 6.2 Recommendation

Add a single line at the top of the DO block:

```sql
LOCK TABLE canonical_entities, entity_aliases, entity_embedding_state,
           relations, relation_evidence_raw, claims, events, event_entities,
           entity_event_exposures, provisional_entity_queue, relation_summaries
    IN ACCESS EXCLUSIVE MODE NOWAIT;
```

If contention exists, the migration fails immediately with a clear error rather than hanging. Add a docstring note: "expected runtime on dev stack: ~2-5 seconds with 132 dedup groups; production runtime depends on dataset size — measure before applying." 5-minute change.

This is the kind of polish that costs nothing now and saves a Saturday-night incident later. Apply.

---

## 7. F-D08 — Single-Reviewer Labelling

### 7.1 What's pending

Every row in `tests/eval/golden/queries.jsonl` has `reviewer_id_a == reviewer_id_b == "claude-agent-1"`. The plan §0-bis.4-v2 maintenance discipline mandates 2-reviewer review and quarterly 10% blind re-grade; neither has happened.

### 7.2 Why this matters

The CI gate's NDCG numbers anchor on a single agent's grading bias. Two specific risks:
1. **Systematic bias** — if the labeller had a consistent mistake (e.g. always rated relation-derived results lower), the gate optimises against that bias forever.
2. **No drift detection** — without a second reviewer, the quarterly re-grade can't surface "this label was correct then, but the corpus has evolved and it's wrong now".

### 7.3 Recommendation

Three things, in this order:

1. **Ship as-is for now**, but add `single_reviewer: true` to the W5-3 baseline capture file metadata so downstream consumers know the gate's stability is bounded.
2. **Schedule a second-pass labelling wave** as a tracked item — not technical work, just labelling. Could be done by a different agent persona (different prompt, different temperature) or eventually by a human reviewer. Target: 100% second-reviewer coverage within 1 quarter.
3. **Once 2-reviewer coverage is in place**, compute Cohen's κ between reviewers per row. Rows where the two reviewers disagree are removed from the gate or re-graded by a third reviewer until consensus. This is the standard ML labelling pipeline.

This is post-MVP work. **For thesis acceptance the single-reviewer gate is fine** — document the limitation in the thesis methodology section.

---

## 8. Strategic Direction — Long-Term Competitive Path

### 8.1 The user's working hypothesis

> "Synthesis depth at narrow scope, knowledge-graph traversal as a tool, modern cost structure, and in the long term sandboxes/strategy-builder for traders/investors with AI-driven strategy generation, to compete against Lona too."

This matches the analysis in `docs/references/competitive-analysis-lona-godel.md` and is the right direction. Three observations.

### 8.2 The gap is real and well-positioned

Three-axis competitive map:

```
                         Real-time data depth
                                ↑
                                │
      Bloomberg ($31,980/yr) ●  │  ● Worldview (proposed: $99-149/mo)
                                │
                                │
                  Godel ($996/yr) ●
                                │
                                │
                           ───────────────→  AI / synthesis depth
                                │
                                │  ● Lona ($0-50/mo, retail algos)
                                ↓
                         Trading workflow depth
```

- **Bloomberg** wins on data + asset-class breadth; loses on AI and price.
- **Godel** wins on price + Bloomberg-like UX; has zero AI.
- **Lona** wins on AI strategy generation but has no proprietary data and is commoditising as LLMs improve.
- **Worldview's gap** is the cell at the intersection — the platform that has Worldview's intelligence layer + Godel's UX patterns + a sandbox/strategy layer that Lona wishes it had but cannot build without proprietary KG/NLP.

### 8.3 The 3 priorities that the QA debt actually maps to

The architectural debt from the QA pass is **exactly the moat-erosion patterns** that prevent the platform from ever existing in that gap. Specifically:

1. **F-X02 — cache staleness** prevents trust in real-time signals. A trading product whose ticker universe drifts silently is unfit for any audience that values data correctness.
2. **F-X12 / F-D03 — consumer idempotency** means the KG (the differentiator) silently amplifies under load. At Bloomberg-class throughput, the KG would have 5x the actual relations within a quarter; ranking quality collapses; the moat erodes; users leave.
3. **F-A01 — silent metric loss** means you can't operate the product. You can't tell when retrieval quality regresses; you can't tune; you can't sell to enterprise.
4. **F-X09 — fail-open CI gate** is the meta-version of (3) — you can't even tell when you're regressing in development.

These are not "polish before MVP" items. **They're the operating-table competence that lets a small team compete with Bloomberg at all.**

### 8.4 What the strategy-builder direction adds

Reading `competitive-analysis-lona-godel.md` Part V Priority 1 ("Intelligence-Grounded Strategy Builder"), the path is clear and tractable:

- **Don't compete with Lona on commodity NL→Pine Script** — that converges to GPT-5+ baseline.
- **Compete on intelligence-grounded strategies** that use Worldview's KG and signals as input. *"Buy when KG sentiment confidence on AAPL exceeds threshold AND a novel positive claim was extracted in the last 48h not yet priced in"* is structurally non-replicable without the KG/NLP pipeline.
- **Use LEAN engine (QuantConnect open source) for backtesting** — don't rebuild time-series infrastructure.
- **Defer live trading entirely** — regulatory, no moat, distraction.

The sandbox layer the user mentioned should be **structured around the intelligence layer, not the trading-strategy generator**. Concretely:

- A backtesting sandbox that lets users overlay Worldview's signals on their existing strategies and see what the KG/NLP said on each historical trigger date. ("Your strategy triggered 14 times. On 3 of those, our sentiment model had flagged a negative trend 2 days earlier.")
- A signal-discovery sandbox that lets users visualise KG patterns (e.g. "show me every time our pipeline detected a novel claim about AAPL within 24h of a >2% move"). This is research-as-a-product, which is the actual Bloomberg differentiator that Godel lacks.
- An AI-assisted strategy editor where the user describes a thesis in natural language, the system queries the KG for historically-similar setups, and proposes entry/exit conditions grounded in proprietary signal definitions. This is where the user's "AI in the workflow" vision intersects with the moat.

### 8.5 Sequencing the long term

Three horizons:

**0-3 months** — finish the operating-table:
- W5-5b hardening (this report's items 1, 2, 3).
- Complete labelling + flip the CI gate.
- Land PLAN-0067 (full tool catalog) — this is the prerequisite for AI-driven strategy generation, because the strategy LLM needs to call retrieval/KG tools.
- Land PLAN-0078/0079/0080/0081/0082 (chunk-entity filter, trust scorer, intelligence-layer tools, catalog tools, action tools) — these are the LLM-facing primitives.

**3-9 months** — build the differentiation layer:
- CLI command palette (Godel's UX, applied to Worldview's intelligence) — `news TSLA`, `kg MSFT relations`, `sentiment NVDA 30d`, `ask <question>`.
- Multi-panel layout (Godel parity).
- MCP endpoint exposure (Lona's distribution insight, applied to Worldview's intelligence layer). `worldview_news`, `worldview_kg_events`, `worldview_chat`, `worldview_strategy` exposed as MCP tools.
- First version of the **strategy-builder** that uses LEAN for backtesting and Worldview's KG/signals as input. Limit to long-only equity backtesting initially.

**9-18 months** — sandbox + ecosystem:
- **Strategy intelligence overlay** (run user strategies, annotate triggers with KG/NLP context).
- **Signal discovery sandbox** (KG pattern visualisation, with ML-driven anomaly highlighting).
- **AI-assisted strategy editor** (natural-language thesis → KG-grounded conditions → backtest → iterate).
- Marketplace / community layer (deferred but should be designed for now).

### 8.6 What NOT to build

From the competitive doc + this analysis:

- **No live trading / order routing.** Regulatory, no moat. Same answer as the doc.
- **No expert-network clone** (Godel's 20K contacts). Multi-year build to critical mass.
- **No mobile app yet.** Web terminal first.
- **No generic NL→Pine Script generator without KG grounding.** Commoditising fast.
- **No "AI assistant" that just wraps GPT-5 around generic financial Q&A.** Differentiation is the proprietary KG/NLP layer; vanilla LLM is table stakes that everyone has.

### 8.7 The thesis framing

For the thesis, the contribution is:

> *A retrieval substrate (W5) and tool catalog (W11) that together let a small open-source LLM produce institutional-grade synthesis answers grounded in a proprietary knowledge graph (W6/W7), at unit costs 30-300× lower than Bloomberg's terminal — and a sandboxed strategy-builder layer that turns that intelligence into actionable, backtested trading signals.*

The QA findings are the engineering rigor that makes the claim defensible. Without them — without idempotent consumers, without a real CI gate, without observable retrieval quality — the demo works once and never works again. **The audit's "boring fixes" are the foundation of every interesting demo.**

---

## 9. Recommended Execution Plan

### 9.1 PLAN-0084 — W5-5b Hardening + Bloomberg-Path Foundation

A new tracked plan covering items 1-7 of this report. Suggested wave structure:

- **Wave A — Citation cron + circuit-breaker hardening** (F-A01 + F-X06 + F-X07 + F-S01 + F-X01 + F-X04 + F-X05). One coherent commit in rag-chat. ~400 LOC. ~half a day.
- **Wave B — Canonical tickers refresh loop + atomic swap** (F-X02 + F-X03). One commit in nlp-pipeline. ~150 LOC. ~2 hours.
- **Wave C — `ValkeyDedupMixin` + consumer migration + deterministic IDs in article_consumer** (F-X11 + F-X12 + F-D03). One commit in libs/messaging + nlp-pipeline + KG (refactor only) + integration test. ~400 LOC. ~half a day.
- **Wave D — Port-ABC extraction** (F-A04 + F-A05 + nlp-pipeline `CanonicalEntityPort`). Three commits, one per port. ~450 LOC. ~half a day.
- **Wave E — CI gate hardening** (F-X09): smoke probe, per-class regression, post-instability `continue-on-error` removal. One commit. ~100 LOC. ~2 hours.
- **Wave F — Migration polish** (F-D06 LOCK + F-D04 docstring + F-D08 single-reviewer flag). One commit. ~50 LOC. ~1 hour.
- **Wave G — Result-instability investigation** (W5-3 audit follow-up). `/investigate` skill. ~half a day.
- **Wave H — Boost-sweep run** (F-A02). After W5-3 instability is closed and ≥80% labelled. ~2 hours.
- **Wave I — STANDARDS.md + R9 update + new BPs** (one BP for each new pattern surfaced — dead-cron wiring, CB stampede, cache-staleness, dialect-drift). ~1 hour.

Total: ~3-4 dev-days. This is the realistic close-out for PLAN-0063 before W5-6 begins.

### 9.2 PLAN-0085 — CLI command palette + multi-panel layout (3-9 month bucket)
Front-end-heavy plan; reads Godel's UX patterns and applies them to Worldview's intelligence layer. Depends on PLAN-0067 (tool catalog) for the `ask <question>` and `worldview_*` MCP tools.

### 9.3 PLAN-0086 — MCP endpoint + intelligence-grounded strategy builder (6-12 month bucket)
Lona's distribution insight, applied to Worldview's intelligence layer. LEAN engine integration. First version is long-only equity backtesting against KG-grounded conditions.

### 9.4 PLAN-0087 — Sandbox / signal-discovery / strategy-overlay (9-18 month bucket)
The differentiation layer. Strategy intelligence overlay first, then signal discovery sandbox, then AI-assisted strategy editor.

---

## 10. Compounding Updates

### 10.1 BUG_PATTERNS.md — new patterns
- **BP-NEW-1**: "Use case implemented + tested in isolation but never wired in `app.py` lifespan" → silent metric loss (F-A01).
- **BP-NEW-2**: "Circuit breaker has no HALF_OPEN probe gating; cooldown expiry → stampede" (F-X01).
- **BP-NEW-3**: "Cache populated once at startup, never refreshed" → DS-009 stale-replica (F-X02).
- **BP-NEW-4**: "Hand-rolled `is_duplicate`/`mark_processed` per consumer drifts into two dialects" → standardise via `ValkeyDedupMixin`.
- **BP-NEW-5**: "CI gate `continue-on-error: true` retained two waves past lock; script returns 0 on empty per_query" → fail-open as design pattern (F-X09).

### 10.2 STANDARDS.md — new sections
- **§3.11 Consumer Dedup — ALWAYS use `ValkeyDedupMixin`** with the contract from §1.5 above.
- **§11 Anti-Pattern row**: "Hand-rolled `is_duplicate`/`mark_processed` per consumer → use `ValkeyDedupMixin`".
- **§17 / R9 update**: clarify the dedup-table-vs-natural-key contract.

### 10.3 RULES.md — clarification
- **R9 update**: "the processed-events check is satisfied by `ValkeyDedupMixin` for the standard at-least-once contract; consumers that bypass it must document a stronger guarantee in their docstring (e.g., atomic create_if_not_exists natural-key idempotency) and the architecture test must allowlist them."

### 10.4 REVIEW_CHECKLIST.md
- **New check**: "If a use case has an `execute()` that updates a Prometheus metric or returns a value, grep for at least one caller in `app.py` / `lifespan` / `_wire_*`."
- **New check**: "If a use case introduces a new singleton-cached resource (e.g. `XCache`, `YState`), search for either a refresh loop or a Kafka invalidation consumer."

### 10.5 HIGH_RISK_PATTERNS.md
- **New pattern HR-NEW**: `is_duplicate(self, event_id) -> bool: return False` is a yellow flag; require either a `ValkeyDedupMixin` or an inline docstring explaining the natural-key idempotency.
- **New pattern HR-NEW**: `cool_down_seconds: int = 3600` (or any breaker cooldown >300s) without a HALF_OPEN probe is a red flag.

---

## 11. Open Questions for the User

1. **F-X12 fix shape**: do you want the `ValkeyDedupMixin` standardisation across all 8 consumers (more refactor, more consistency) or just article_consumer + KG consumers (less refactor)? My recommendation: all 8, because the dialect drift compounds.
2. **CI gate result-instability**: should that be a tracked `/investigate` task before flipping the gate, or do you want to flip the gate now and accept some flakiness?
3. **Strategy-builder sequencing**: do you want PLAN-0086 (intelligence-grounded strategy + LEAN) before or after CLI palette + multi-panel? My recommendation: CLI/multi-panel first (Godel-parity is fast and visible), strategy-builder second (deeper differentiator, takes longer).
4. **Single-reviewer labelling**: acceptable for thesis defense, or do you want to invest in a second-pass labelling wave first?

---

**End of investigation report.**
