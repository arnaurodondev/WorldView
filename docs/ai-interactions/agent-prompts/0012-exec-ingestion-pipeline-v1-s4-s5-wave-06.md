# Execution Prompt 0012 — Ingestion Pipeline v1: S4+S5 Wave 06

**Wave:** 06 of 07
**Date issued:** 2026-03-22
**Service:** S5 Content Store — LSH, Canonical Write, Kafka Consumer, Outbox Dispatcher
**Execution model:** Sequential group (T-S5-007 → T-S5-008) + parallel group (T-S5-009, T-S5-010)
**Prerequisite:** Wave 05 complete and merged

---

## Context (read first)

- Planning prompt: `docs/ai-interactions/agent-prompts/0012-ingestion-pipeline-v1-s4-s5-plan.md`
- Planning response: `docs/ai-interactions/agent-responses/0012-response-20260322-ingestion-pipeline-v1-s4-s5.md`

---

## Assigned agent profile(s)

- `docs/agents/backend-engineer.md`
- `docs/agents/data-platform-engineer.md`

---

## Mandatory pre-read

1. `AGENTS.md`
2. `CLAUDE.md`
3. `docs/services/content-store.md`
4. `docs/ai-interactions/agent-responses/0014-PRD-v1-final.md`
5. `docs/ai-interactions/agent-responses/0012-response-20260322-ingestion-pipeline-v1-s4-s5.md`
6. Confirm Wave 05 outputs exist:
   - `services/content-store/src/content_store/application/text_cleaning/cleaner.py`
   - `services/content-store/src/content_store/application/deduplication/stage_a_raw.py`
   - `services/content-store/src/content_store/application/deduplication/stage_b_normalized.py`
   - `services/content-store/src/content_store/application/deduplication/minhash_compute.py`
7. `services/content-store/pyproject.toml` — verify `redis[asyncio]` (Valkey), `aiokafka`, `fastavro`, `minio`/`aioboto3` present.
8. `docs/libs/common.md` — UUIDv7 (`new_uuid7`), UTC time (`utc_now`), cross-service types (`DocumentId`, `EntityId`, `UrlHash`, `MinIOKey`)

---

## Objective

Complete the S5 Content Store hot path:

- **T-S5-007:** Implement the Valkey LSH two-tier near-duplicate detector — 4 LSH bands, in-process Jaccard computation, hard/soft thresholds, `CORROBORATING` vs `SAME_SOURCE_DUPLICATE` distinction. This is the most algorithmically complex component in S5.
- **T-S5-008:** Implement the canonical write pipeline — chains all dedup stages and writes to MinIO silver + Postgres in a single all-or-nothing transaction. Depends on T-S5-007 completing first.
- **T-S5-009:** Implement the Kafka consumer for `content.article.raw.v1` with at-least-once delivery and manual offset commit after DB commit.
- **T-S5-010:** Implement the S5 outbox dispatcher that publishes `content.article.stored.v1` to Kafka.

T-S5-009 and T-S5-010 are independent infrastructure components and can be authored in parallel with the T-S5-007/008 sequential chain.

---

## Task scope for this wave

**Sequential group:**

| Task ID | Description | Execution order |
|---------|-------------|----------------|
| T-S5-007 | Valkey LSH two-tier (4 bands, ZRANGEBYSCORE lookup, Jaccard in-process, thresholds) | First |
| T-S5-008 | Canonical write pipeline (MinIO silver write, 4-table atomic DB transaction, dedup chain) | Second — requires T-S5-007 |

**Parallel group (independent, can run simultaneously with T-S5-007/008 chain):**

| Task ID | Description |
|---------|-------------|
| T-S5-009 | Kafka consumer (content.article.raw.v1, group=content-store-group, at-least-once, manual offset commit AFTER DB commit) |
| T-S5-010 | S5 outbox dispatcher (poll content_store_db outbox_events, publish content.article.stored.v1) |

---

## Why this chunk

T-S5-007 (Valkey LSH) depends on T-S5-006 (MinHash computation from Wave 05). T-S5-008 (canonical write) depends on all dedup stages (T-S5-003–007). These form the logical completion of the dedup pipeline. T-S5-009 and T-S5-010 are transport-layer components with no dependency on the dedup logic — they can be developed in parallel. After this wave, the S5 service has all core business logic implemented and is ready for observability + integration testing in Wave 07.

---

## Implementation instructions

### T-S5-007 — Valkey LSH Two-Tier

1. **Create `services/content-store/src/content_store/infrastructure/valkey/__init__.py`** — empty.

2. **Create `services/content-store/src/content_store/infrastructure/valkey/client.py`**:
   ```python
   import redis.asyncio as redis
   from content_store.config import Settings

   class ValkeyClient:
       """Async client for Valkey (Redis-protocol compatible).

       Used for LSH band index storage and (in S4) NewsAPI quota counting.
       """

       def __init__(self, settings: Settings):
           self._client = redis.from_url(settings.VALKEY_URL, decode_responses=True)

       async def zadd(self, key: str, mapping: dict[str, float]) -> int:
           return await self._client.zadd(key, mapping)

       async def zrangebyscore(
           self, key: str, min_score: float, max_score: float
       ) -> list[str]:
           return await self._client.zrangebyscore(key, min_score, max_score)

       async def expire(self, key: str, seconds: int) -> bool:
           return await self._client.expire(key, seconds)

       async def exists(self, *keys: str) -> int:
           return await self._client.exists(*keys)

       async def ping(self) -> bool:
           try:
               return await self._client.ping()
           except Exception:
               return False

       async def flushdb(self) -> None:
           """For testing only — flush the current database."""
           await self._client.flushdb()

       async def close(self) -> None:
           await self._client.aclose()
   ```

3. **Create `services/content-store/src/content_store/application/deduplication/lsh_valkey.py`**:

   ```python
   import hashlib
   from uuid import UUID
   from datetime import datetime, timezone

   import structlog

   from content_store.domain.entities import (
       Article, CanonicalDocument, CorroborationPolicy,
       DeduplicationDecision, DeduplicationStage,
   )
   from content_store.infrastructure.valkey.client import ValkeyClient
   from content_store.infrastructure.db.repositories.minhash import MinHashRepository

   logger = structlog.get_logger(__name__)

   NUM_BANDS = 4
   ROWS_PER_BAND = 32  # 128 / 4 = 32 rows per band
   LSH_KEY_TTL_SECONDS = 30 * 24 * 3600  # 30 days


   class ValkeyLSH:
       """MinHash LSH index using Valkey sorted sets for near-duplicate detection.

       Architecture:
           - 4 LSH bands, each covering 32 hash values from the 128-perm signature.
           - Each band is stored as a Valkey sorted set: key=lsh:band{i}:{band_hash},
             members=doc_ids, scores=Unix timestamps.
           - ZRANGEBYSCORE used for time-window lookups (e.g., last 7 days).
           - Jaccard computed in-process by comparing full signatures.

       Thresholds (from CorroborationPolicy):
           - Jaccard >= hard_threshold (default 0.95) AND same source_type → SAME_SOURCE_DUPLICATE (suppressed).
           - Jaccard >= soft_threshold (default 0.80) AND different source_type → CORROBORATING (written).
           - Jaccard >= hard_threshold (default 0.95) AND different source_type → CORROBORATING (written).
           - Jaccard < soft_threshold → UNIQUE (written).
       """

       def __init__(
           self,
           valkey: ValkeyClient,
           minhash_repo: MinHashRepository,
           policy: CorroborationPolicy,
           num_perm: int = 128,
       ):
           self._valkey = valkey
           self._minhash_repo = minhash_repo
           self._policy = policy
           self._num_perm = num_perm

       def _band_key(self, band_idx: int, band_hash: int) -> str:
           return f"lsh:band{band_idx}:{band_hash}"

       def _compute_band_hash(self, signature: list[int], band_idx: int) -> int:
           """Hash a band slice to a bucket key.

           Uses MD5 of the band slice repr for deterministic, collision-resistant hashing.
           """
           band_slice = signature[band_idx * ROWS_PER_BAND:(band_idx + 1) * ROWS_PER_BAND]
           digest = hashlib.md5(str(band_slice).encode()).hexdigest()
           return int(digest, 16) % (2 ** 31)

       def _jaccard(self, sig_a: list[int], sig_b: list[int]) -> float:
           """Estimate Jaccard similarity from two MinHash signatures.

           Standard MinHash estimator: fraction of matching hash values.
           """
           if len(sig_a) != len(sig_b):
               return 0.0
           matches = sum(1 for a, b in zip(sig_a, sig_b) if a == b)
           return matches / len(sig_a)

       async def query(
           self,
           article: Article,
           signature: list[int],
           time_window_seconds: float = 7 * 24 * 3600,
       ) -> DeduplicationDecision:
           """Query LSH index for near-duplicates of an article.

           Args:
               article: The article being processed (provides source_type for corroboration check).
               signature: MinHash signature as list[int] of length num_perm.
               time_window_seconds: Only compare against documents indexed within this window.

           Returns:
               DeduplicationDecision with stage=NEAR_DUPLICATE.
               - is_duplicate=True + decision="SAME_SOURCE_DUPLICATE" → suppress.
               - is_duplicate=False + decision="CORROBORATING" → write (corroborating coverage).
               - is_duplicate=False + decision="UNIQUE" → write (no near-dup found).
           """
           now_ts = datetime.now(tz=timezone.utc).timestamp()
           min_ts = now_ts - time_window_seconds

           # Collect candidate doc_ids from all band hits
           candidate_ids: set[str] = set()
           for band_idx in range(NUM_BANDS):
               band_hash = self._compute_band_hash(signature, band_idx)
               key = self._band_key(band_idx, band_hash)
               members = await self._valkey.zrangebyscore(key, min_ts, now_ts)
               candidate_ids.update(members)

           if not candidate_ids:
               return DeduplicationDecision(
                   stage=DeduplicationStage.NEAR_DUPLICATE,
                   is_duplicate=False,
                   similarity_score=None,
                   existing_doc_id=None,
                   decision="UNIQUE",
               )

           # Compute Jaccard for each candidate; find best match
           best_jaccard = 0.0
           best_doc_id: UUID | None = None

           for doc_id_str in candidate_ids:
               try:
                   doc_id = UUID(doc_id_str)
               except ValueError:
                   continue
               candidate_sig = await self._minhash_repo.get_signature(doc_id)
               if candidate_sig is None:
                   continue
               jaccard = self._jaccard(signature, candidate_sig)
               if jaccard > best_jaccard:
                   best_jaccard = jaccard
                   best_doc_id = doc_id

           logger.debug(
               "lsh.query_result",
               candidates=len(candidate_ids),
               best_jaccard=round(best_jaccard, 3),
               article_url=article.url,
           )

           # Apply CorroborationPolicy
           if best_jaccard < self._policy.jaccard_soft_threshold:
               return DeduplicationDecision(
                   stage=DeduplicationStage.NEAR_DUPLICATE,
                   is_duplicate=False,
                   similarity_score=best_jaccard,
                   existing_doc_id=best_doc_id,
                   decision="UNIQUE",
               )

           # Determine source type of best candidate — would require DB lookup for full impl.
           # For MVP: classify by threshold alone (source_type_aware=False equivalent):
           # If source_type_aware=True and same source: use hard threshold logic.
           # Simplified: any match >= hard_threshold is SAME_SOURCE_DUPLICATE if source matches.
           # This classification is intentionally conservative — prefer CORROBORATING over suppression.
           decision_str = self._policy.classify(best_jaccard, same_source_type=False)

           return DeduplicationDecision(
               stage=DeduplicationStage.NEAR_DUPLICATE,
               is_duplicate=(decision_str == "SAME_SOURCE_DUPLICATE"),
               similarity_score=best_jaccard,
               existing_doc_id=best_doc_id,
               decision=decision_str,
           )

       async def index(
           self,
           doc_id: UUID,
           signature: list[int],
           source_type: str,
           score: float | None = None,
       ) -> None:
           """Add a document to the LSH index.

           Must be called AFTER the canonical document is written to DB.
           Score defaults to current Unix timestamp for time-window lookups.

           Args:
               doc_id: Canonical document UUID.
               signature: MinHash signature as list[int].
               source_type: Source type string (e.g., 'eodhd', 'finnhub').
               score: Sort score for ZRANGEBYSCORE (default: current Unix timestamp).
           """
           if score is None:
               score = datetime.now(tz=timezone.utc).timestamp()

           member = str(doc_id)
           for band_idx in range(NUM_BANDS):
               band_hash = self._compute_band_hash(signature, band_idx)
               key = self._band_key(band_idx, band_hash)
               await self._valkey.zadd(key, {member: score})
               await self._valkey.expire(key, LSH_KEY_TTL_SECONDS)
   ```

   Note on source_type_aware classification: the MVP implementation above uses `same_source_type=False` (conservative — prefers CORROBORATING). In a future iteration, the LSH index can store `source_type` as a field in the sorted set member (e.g., `{doc_id}:{source_type}`) to enable source-aware comparison. Document this limitation in the service doc.

4. **Write unit tests** at `services/content-store/tests/unit/test_lsh_valkey.py`:
   - `test_band_hash_deterministic` — same signature + band_idx → same hash on two calls.
   - `test_band_key_format` — assert key matches `lsh:band{i}:{hash}` pattern.
   - `test_jaccard_identical_signatures` — assert Jaccard = 1.0.
   - `test_jaccard_disjoint_signatures` — construct two completely different signatures; assert Jaccard ~= 0.0.
   - `test_query_no_candidates_returns_unique` — mock valkey `zrangebyscore` returns empty; assert UNIQUE.
   - `test_query_high_jaccard_returns_same_source_duplicate` — mock candidate with sig that yields Jaccard=0.96; policy hard=0.95; mock `_policy.classify` returns SAME_SOURCE_DUPLICATE; assert `is_duplicate=True`.
   - `test_query_mid_jaccard_cross_source_returns_corroborating` — Jaccard=0.85, policy soft=0.80; assert CORROBORATING, `is_duplicate=False`.
   - `test_query_low_jaccard_returns_unique` — Jaccard=0.65 < 0.80; assert UNIQUE.
   - `test_index_adds_to_all_four_bands` — call `index()`; assert `valkey.zadd` called 4 times (once per band).
   - `test_index_sets_ttl_on_each_band_key` — assert `valkey.expire` called 4 times with 30-day TTL.

5. **Run:** `make test`, `ruff check`, `mypy`.

---

### T-S5-008 — Canonical Write Pipeline

1. **Create `services/content-store/src/content_store/infrastructure/storage/minio_silver.py`**:
   ```python
   import asyncio
   import json
   from content_store.domain.entities import CanonicalDocument
   from content_store.domain.exceptions import StorageError

   class MinioSilverAdapter:
       KEY_PATTERN = "content-store/canonical/{doc_id}/body.json"

       def __init__(self, client, bucket: str):
           self._client = client
           self._bucket = bucket

       def _make_key(self, doc_id) -> str:
           return self.KEY_PATTERN.format(doc_id=str(doc_id))

       async def put_canonical(self, doc: CanonicalDocument, cleaned_text: str) -> str:
           """Write canonical document to MinIO silver tier.

           Returns the MinIO key for the stored object.
           Key pattern: content-store/canonical/{doc_id}/body.json
           """
           key = self._make_key(doc.id)
           payload = json.dumps({
               "doc_id": str(doc.id),
               "source_article_id": str(doc.source_article_id),
               "url": doc.url,
               "source_type": doc.source_type,
               "created_at": doc.created_at.isoformat(),
               "cleaned_text": cleaned_text,
           }).encode("utf-8")
           try:
               import io
               await asyncio.to_thread(
                   self._client.put_object,
                   self._bucket,
                   key,
                   io.BytesIO(payload),
                   length=len(payload),
                   content_type="application/json",
               )
               return key
           except Exception as exc:
               raise StorageError(f"MinIO silver write failed: {exc}") from exc
   ```

2. **Create `services/content-store/src/content_store/application/use_cases/__init__.py`** — empty.

3. **Create `services/content-store/src/content_store/application/use_cases/process_article.py`**:
   ```python
   import uuid6
   from dataclasses import dataclass
   from datetime import datetime, timezone
   from uuid import UUID
   import structlog

   from content_store.domain.entities import (
       Article, CanonicalDocument, DeduplicationDecision, CorroborationPolicy,
   )
   from content_store.domain.exceptions import StorageError
   from content_store.application.text_cleaning.cleaner import TextCleaner
   from content_store.application.deduplication.stage_a_raw import StageARawHashChecker
   from content_store.application.deduplication.stage_b_normalized import StageBNormalizedHashChecker
   from content_store.application.deduplication.minhash_compute import compute_minhash
   from content_store.application.deduplication.lsh_valkey import ValkeyLSH
   from content_store.infrastructure.storage.minio_silver import MinioSilverAdapter
   from content_store.infrastructure.db.session import get_db_session
   from content_store.infrastructure.db.repositories.document import DocumentRepository
   from content_store.infrastructure.db.repositories.minhash import MinHashRepository
   from content_store.infrastructure.db.repositories.outbox import OutboxRepository

   logger = structlog.get_logger(__name__)

   @dataclass
   class ProcessingSummary:
       article_id: UUID
       decision: str
       doc_id: UUID | None
       suppressed: bool

   class ProcessArticleUseCase:
       """Orchestrate the full S5 article processing pipeline.

       Pipeline:
           1. Fetch raw bytes from MinIO bronze.
           2. Clean text (TextCleaner).
           3. Stage A: exact raw SHA-256 dedup check.
           4. Stage B: normalized hash dedup check.
           5. Compute MinHash signature.
           6. Stage C: Valkey LSH near-duplicate check.
           7. If not suppressed: write MinIO silver + atomic DB transaction.
           8. Index in Valkey LSH.
       """

       def __init__(
           self,
           cleaner: TextCleaner,
           stage_a: StageARawHashChecker,
           stage_b: StageBNormalizedHashChecker,
           lsh: ValkeyLSH,
           minio_bronze,  # MinioBronzeAdapter or similar for fetching raw bytes
           minio_silver: MinioSilverAdapter,
           session_factory,
           policy: CorroborationPolicy,
           num_perm: int = 128,
       ):
           self._cleaner = cleaner
           self._stage_a = stage_a
           self._stage_b = stage_b
           self._lsh = lsh
           self._minio_bronze = minio_bronze
           self._minio_silver = minio_silver
           self._session_factory = session_factory
           self._policy = policy
           self._num_perm = num_perm

       async def execute(self, article: Article) -> ProcessingSummary:
           # 1. Fetch raw bytes from MinIO bronze
           raw_bytes = await self._fetch_raw_bytes(article.minio_bronze_key)

           # 2. Clean text
           content_type = self._infer_content_type(article.source_type)
           cleaned_text = self._cleaner.clean(raw_bytes, content_type)

           # 3. Stage A: exact raw hash check
           async with get_db_session(self._session_factory) as session:
               doc_repo = DocumentRepository(session)
               decision_a, raw_sha256 = await self._stage_a.check(article, raw_bytes, doc_repo)

           if decision_a.is_duplicate:
               logger.info("s5.dedup.exact_raw", url=article.url)
               return ProcessingSummary(article_id=article.id, decision=decision_a.decision, doc_id=None, suppressed=True)

           # 4. Stage B: normalized hash check
           async with get_db_session(self._session_factory) as session:
               doc_repo = DocumentRepository(session)
               decision_b, norm_hash = await self._stage_b.check(article, cleaned_text, doc_repo)

           if decision_b.is_duplicate:
               logger.info("s5.dedup.normalized", url=article.url)
               return ProcessingSummary(article_id=article.id, decision=decision_b.decision, doc_id=None, suppressed=True)

           # 5. Compute MinHash
           signature = compute_minhash(cleaned_text, num_perm=self._num_perm)

           # 6. Stage C: LSH near-dup check
           decision_c = await self._lsh.query(article, signature)

           if decision_c.is_duplicate:  # SAME_SOURCE_DUPLICATE only
               logger.info("s5.dedup.near_dup_suppressed", url=article.url, jaccard=decision_c.similarity_score)
               return ProcessingSummary(article_id=article.id, decision=decision_c.decision, doc_id=None, suppressed=True)

           # 7. Write canonical document (UNIQUE or CORROBORATING)
           doc_id = common.ids.new_uuid7()
           doc = CanonicalDocument(
               id=doc_id,
               source_article_id=article.id,
               url=article.url,
               url_hash=article.url_hash,
               normalized_text_hash=norm_hash,
               raw_sha256=raw_sha256,
               minio_silver_key="",  # filled after MinIO write
               source_type=article.source_type,
               created_at=datetime.now(tz=timezone.utc),
           )

           minio_key = await self._minio_silver.put_canonical(doc, cleaned_text)
           doc = CanonicalDocument(**{**vars(doc), "minio_silver_key": minio_key})

           # Single atomic transaction: 4 tables
           async with get_db_session(self._session_factory) as session:
               doc_repo = DocumentRepository(session)
               minhash_repo = MinHashRepository(session)
               outbox_repo = OutboxRepository(session)

               await doc_repo.create(doc)
               # Insert raw + normalized dedup hashes
               await doc_repo.insert_dedup_hash(doc_id, raw_sha256, "raw_sha256")
               await doc_repo.insert_dedup_hash(doc_id, norm_hash, "normalized_sha256")
               await minhash_repo.create_signature(doc_id, signature, self._num_perm)
               await outbox_repo.append(
                   aggregate_type="CanonicalDocument",
                   aggregate_id=doc_id,
                   event_type="content.article.stored.v1",
                   payload={
                       "doc_id": str(doc_id),
                       "source_type": article.source_type,
                       "url": article.url,
                       "minio_silver_key": minio_key,
                       "created_at": doc.created_at.isoformat(),
                   },
               )
               # Commit is automatic via get_db_session context manager

           # 8. Index in Valkey LSH (after DB commit)
           await self._lsh.index(doc_id, signature, article.source_type)

           logger.info(
               "s5.canonical_written",
               url=article.url,
               doc_id=str(doc_id),
               decision=decision_c.decision,
           )
           return ProcessingSummary(
               article_id=article.id,
               decision=decision_c.decision,
               doc_id=doc_id,
               suppressed=False,
           )

       async def _fetch_raw_bytes(self, minio_key: str) -> bytes:
           """Fetch raw bytes from MinIO bronze tier."""
           # Implementation depends on MinIO client in use
           # Return bytes from the JSON envelope's raw_bytes_b64 field
           import asyncio, base64, json
           data = await asyncio.to_thread(
               self._minio_bronze.get_object_bytes, minio_key
           )
           envelope = json.loads(data)
           return base64.b64decode(envelope["raw_bytes_b64"])

       def _infer_content_type(self, source_type: str) -> str:
           """Map source_type to expected content_type for TextCleaner."""
           mapping = {
               "sec_edgar": "text/html",
               "eodhd": "application/json",
               "finnhub": "application/json",
               "newsapi": "application/json",
           }
           return mapping.get(source_type, "text/html")
   ```

   Add `insert_dedup_hash(doc_id, hash_value, hash_type)` method to `DocumentRepository` in the DB infra file created in Wave 04.

4. **Also add `get_object_bytes(key: str) -> bytes`** to `MinioBronzeAdapter` (read path — previously only `put_object` was implemented).

5. **Write unit tests** at `services/content-store/tests/unit/test_process_article_use_case.py`:
   - `test_exact_raw_duplicate_suppressed_at_stage_a` — mock stage_a returns EXACT_DUPLICATE; assert minio_silver.put NOT called; assert `suppressed=True`.
   - `test_normalized_duplicate_suppressed_at_stage_b` — mock stage_a UNIQUE, stage_b NORMALIZED_DUPLICATE; assert minio_silver.put NOT called.
   - `test_same_source_near_dup_suppressed_at_stage_c` — mock stage_a/b UNIQUE, LSH returns SAME_SOURCE_DUPLICATE; assert `suppressed=True`.
   - `test_corroborating_article_is_written` — Jaccard=0.85, cross-source → CORROBORATING; assert minio_silver.put called; assert doc_repo.create called.
   - `test_unique_article_written_to_minio_and_db` — all stages UNIQUE; assert minio_silver.put called; assert db transaction with 4 tables; assert `suppressed=False`.
   - `test_db_transaction_rollback_on_error` — mock doc_repo.create raises; assert outbox_repo.append NOT called (rollback).
   - `test_valkey_index_called_after_db_commit` — assert `lsh.index()` called only after db commit succeeds.
   - `test_outbox_payload_matches_stored_v1_avro_schema` — assert payload keys match S5 Avro schema.

6. **Run:** `make test`, `ruff check`, `mypy`.

---

### T-S5-009 — Kafka Consumer (parallel)

1. **Create `services/content-store/src/content_store/infrastructure/consumer/__init__.py`** — empty.

2. **Create `services/content-store/src/content_store/infrastructure/consumer/article_consumer.py`**:
   ```python
   import asyncio
   import io
   import fastavro
   import structlog
   from aiokafka import AIOKafkaConsumer
   from content_store.domain.entities import Article
   from content_store.domain.exceptions import ConsumerError
   from content_store.config import Settings

   # Import the same Avro schema as S4 outbox dispatcher produces
   ARTICLE_RAW_V1_SCHEMA = {
       "type": "record",
       "name": "ArticleRawV1",
       "namespace": "com.worldview.content",
       "fields": [
           {"name": "article_id", "type": "string"},
           {"name": "source_type", "type": "string"},
           {"name": "url", "type": "string"},
           {"name": "url_hash", "type": "string"},
           {"name": "minio_key", "type": "string"},
           {"name": "fetched_at", "type": "string"},
           {"name": "byte_size", "type": "int"},
       ]
   }

   logger = structlog.get_logger(__name__)

   class ArticleConsumer:
       """Kafka consumer for content.article.raw.v1.

       Delivery guarantee: at-least-once.
       Manual offset commit: ONLY after ProcessArticleUseCase.execute() returns
       (success or handled error). Unhandled exceptions do NOT commit — message redelivered.

       Group ID: settings.KAFKA_CONSUMER_GROUP (default: content-store-group)
       """

       def __init__(self, settings: Settings, use_case_factory):
           self._settings = settings
           self._use_case_factory = use_case_factory  # callable() -> ProcessArticleUseCase
           self._consumer: AIOKafkaConsumer | None = None

       async def start(self) -> None:
           self._consumer = AIOKafkaConsumer(
               self._settings.KAFKA_INPUT_TOPIC,
               bootstrap_servers=self._settings.KAFKA_BOOTSTRAP_SERVERS,
               group_id=self._settings.KAFKA_CONSUMER_GROUP,
               enable_auto_commit=False,
               auto_offset_reset="earliest",
           )
           await self._consumer.start()
           logger.info("consumer.started", topic=self._settings.KAFKA_INPUT_TOPIC)

       async def stop(self) -> None:
           if self._consumer:
               await self._consumer.stop()
               logger.info("consumer.stopped")

       def _deserialize(self, raw_value: bytes) -> dict:
           buf = io.BytesIO(raw_value)
           return fastavro.schemaless_reader(buf, ARTICLE_RAW_V1_SCHEMA)

       def _to_article(self, payload: dict) -> Article:
           from datetime import datetime, timezone
           from uuid import UUID
           return Article(
               id=UUID(payload["article_id"]),
               source_type=payload["source_type"],
               url=payload["url"],
               url_hash=payload["url_hash"],
               minio_bronze_key=payload["minio_key"],
               fetched_at=datetime.fromisoformat(payload["fetched_at"]).replace(tzinfo=timezone.utc),
               byte_size=payload["byte_size"],
           )

       async def run(self) -> None:
           """Main consumer loop — runs indefinitely until cancelled."""
           use_case = self._use_case_factory()
           async for msg in self._consumer:
               try:
                   payload = self._deserialize(msg.value)
                   article = self._to_article(payload)
                   await use_case.execute(article)
                   await self._consumer.commit()
                   logger.info("consumer.committed", offset=msg.offset, url=article.url)
               except Exception as exc:
                   # Do NOT commit — message will be redelivered
                   logger.error(
                       "consumer.processing_error",
                       offset=msg.offset,
                       error=str(exc),
                       exc_info=True,
                   )
   ```

3. **Write unit tests** at `services/content-store/tests/unit/test_article_consumer.py`:
   - `test_offset_committed_after_successful_use_case` — mock consumer + use_case; assert `consumer.commit()` called.
   - `test_offset_not_committed_on_exception` — mock use_case raises; assert `consumer.commit()` NOT called.
   - `test_avro_deserialization_to_article` — serialize dict with ARTICLE_RAW_V1_SCHEMA; call `_deserialize`; assert dict reconstructed; call `_to_article`; assert `Article` fields correct.
   - `test_consumer_start_stop` — assert `AIOKafkaConsumer.start()` called on `consumer.start()`.

4. **Run:** `make test`, `ruff check`, `mypy`.

---

### T-S5-010 — S5 Outbox Dispatcher (parallel)

1. **Create `services/content-store/src/content_store/infrastructure/outbox/avro_schema.py`**:
   ```python
   ARTICLE_STORED_V1_SCHEMA = {
       "type": "record",
       "name": "ArticleStoredV1",
       "namespace": "com.worldview.content",
       "fields": [
           {"name": "doc_id", "type": "string"},
           {"name": "source_type", "type": "string"},
           {"name": "url", "type": "string"},
           {"name": "minio_silver_key", "type": "string"},
           {"name": "created_at", "type": "string"},
       ]
   }
   ```

2. **Create `services/content-store/src/content_store/infrastructure/outbox/dispatcher.py`**:
   - Class `S5OutboxDispatcher` — same structure as S4 `OutboxDispatcher` (from Wave 01).
   - Uses `content_store_db` session factory and `OutboxRepository` from S5.
   - Publishes to `settings.KAFKA_OUTPUT_TOPIC` (`content.article.stored.v1`).
   - Serializes using `fastavro.schemaless_writer` with `ARTICLE_STORED_V1_SCHEMA`.
   - Max retries: `settings.MAX_RETRIES` (default 3).
   - On DLQ: insert to `dlq_events` in `content_store_db`.
   - Loop: `run_once()` then `asyncio.sleep(settings.OUTBOX_POLL_INTERVAL_SECONDS)`.

3. **Write unit tests** at `services/content-store/tests/unit/test_s5_outbox_dispatcher.py`:
   - `test_dispatch_publishes_stored_v1_to_kafka` — mock session + producer; assert `send_and_wait` called with `KAFKA_OUTPUT_TOPIC`.
   - `test_dispatch_marks_dispatched_on_success`.
   - `test_dispatch_moves_to_dlq_after_max_retries`.
   - `test_serialize_stored_v1_roundtrip` — serialize dict → deserialize with schema → assert equal.

4. **Run:** `make test`, `ruff check`, `mypy`.

---

## Constraints

- Do NOT implement observability endpoints (T-S5-011) or integration tests (T-S5-012) in this wave.
- T-S5-007 MUST complete before T-S5-008 starts.
- T-S5-009 and T-S5-010 may run in parallel with T-S5-007/008.
- CRITICAL (canonical write): The DB transaction in `ProcessArticleUseCase` MUST be all-or-nothing. If `doc_repo.create` succeeds but `minhash_repo.create_signature` fails, the entire transaction must roll back — no partial writes.
- CRITICAL (consumer): Offset MUST be committed ONLY after `use_case.execute()` returns — never before. Never use `enable_auto_commit=True`.
- CRITICAL (outbox): Never call Kafka directly from `ProcessArticleUseCase` — only write to `outbox_events`; outbox dispatcher publishes.
- CORROBORATING articles (`is_duplicate=False, decision="CORROBORATING"`) MUST be written — do not suppress them.
- No `print()` — `structlog` only.
- **`common.ids.new_uuid7()` mandatory** — all entity, document, fetch-log, and outbox primary keys must use `common.ids.new_uuid7()`. Never call `common.ids.new_uuid7()` directly in service code; `uuid6` must not appear in service-layer imports.
- **`common.time.utc_now()` mandatory** — all timestamp generation uses `common.time.utc_now()`. Never call `datetime.now(UTC)` or `datetime.utcnow()` directly in service code.
- **`common.types` for cross-service IDs** — use `DocumentId` (from `common.types`) for canonical document primary keys; `UrlHash` for sha256(url) values; `MinIOKey` for MinIO object key strings.

---

## Scope & token budget

**Write paths:**

```
services/content-store/src/content_store/infrastructure/valkey/__init__.py
services/content-store/src/content_store/infrastructure/valkey/client.py
services/content-store/src/content_store/application/deduplication/lsh_valkey.py
services/content-store/src/content_store/application/use_cases/__init__.py
services/content-store/src/content_store/application/use_cases/process_article.py
services/content-store/src/content_store/infrastructure/storage/__init__.py
services/content-store/src/content_store/infrastructure/storage/minio_silver.py
services/content-store/src/content_store/infrastructure/consumer/__init__.py
services/content-store/src/content_store/infrastructure/consumer/article_consumer.py
services/content-store/src/content_store/infrastructure/outbox/__init__.py
services/content-store/src/content_store/infrastructure/outbox/avro_schema.py
services/content-store/src/content_store/infrastructure/outbox/dispatcher.py
services/content-store/tests/unit/test_lsh_valkey.py
services/content-store/tests/unit/test_process_article_use_case.py
services/content-store/tests/unit/test_article_consumer.py
services/content-store/tests/unit/test_s5_outbox_dispatcher.py
services/content-ingestion/pyproject.toml
services/content-store/pyproject.toml
```

**Max exploration:** Read at most 12 files outside write paths.

**Stop condition:** All 4 tasks implemented, tests passing, ruff + mypy clean.

---

## Required tests

```bash
cd services/content-store && make test
ruff check services/content-store/src/
mypy services/content-store/src/
```

**Pass criteria:** All green; ruff exit 0; mypy exit 0.

---

## Incremental quality gates (mandatory)

1. **T-S5-007**: LSH → `make test` → `ruff check` → `mypy` → DONE.
2. **T-S5-008**: canonical write → `make test` → `ruff check` → `mypy` → DONE.
3. **T-S5-009** (parallel): consumer → `make test` → `ruff check` → `mypy` → DONE.
4. **T-S5-010** (parallel): outbox dispatcher → `make test` → `ruff check` → `mypy` → DONE.

No deferred fixes.

---

## Documentation requirements

| File | Update condition | Required update |
|------|-----------------|-----------------|
| `docs/services/content-store.md` | LSH section | Add Mermaid diagram of 4-band LSH index structure; document CORROBORATING vs SAME_SOURCE_DUPLICATE distinction with Jaccard thresholds |
| `docs/services/content-store.md` | Canonical write pipeline | Add Mermaid sequence diagram (6+ steps: MinIO fetch → clean → stage A → stage B → MinHash → LSH → MinIO write → atomic DB tx → Valkey index) |
| `docs/services/content-store.md` | Kafka consumer section | Document at-least-once guarantee; manual offset commit after DB commit; offset not committed on exception |

**Mermaid sequence diagram required** for canonical write pipeline (update/expand the one from Wave 05 if already present).

**Documentation quality criteria:**

1. Accuracy — LSH band count=4, rows=32, thresholds 0.95/0.80, Avro schema fields all accurate. ✓
2. Diagrams — Mermaid for LSH index structure + canonical write sequence. ✓ required.
3. Realistic code examples — show `ProcessArticleUseCase.execute()` invocation; show Valkey band key format. ✓
4. Abstract methods — `ProcessArticleUseCase.execute()` documented (pipeline steps, input, output). ✓
5. Common pitfalls — add: (a) Valkey index called before DB commit causes phantom entries if DB rolls back; (b) MinHash signature stored as bytes breaks Jaccard estimation — must be `INTEGER[]`; (c) committing Kafka offset before DB commit loses messages on crash; (d) CORROBORATING articles suppressed by mistake → intelligence service misses corroborating signals.
6. Lib docs — `datasketch.MinHash` and `ValkeyLSH` band key TTL (30 days) documented. ✓
7. Service docs — `docs/services/content-store.md` updated. ✓
8. No orphan docs. N/A.

---

## Required handoff evidence

1. **Changed files list.**
2. **Test results:** `make test` — all green.
3. **Ruff:** exit 0.
4. **Mypy:** exit 0.
5. **Docs:** LSH section + canonical write sequence + Kafka consumer section added to `docs/services/content-store.md`.
6. **Validation ledger:**

| Task | Tests | Ruff | Mypy | Docs |
|------|-------|------|------|------|
| T-S5-007 | PASS | PASS | PASS | UPDATED |
| T-S5-008 | PASS | PASS | PASS | UPDATED |
| T-S5-009 | PASS | PASS | PASS | UPDATED |
| T-S5-010 | PASS | PASS | PASS | N/A |

7. **Commit message proposal:**

```
feat(s5): add Valkey LSH, canonical write pipeline, Kafka consumer, outbox dispatcher

ValkeyLSH: 4-band MinHash LSH with Jaccard in-process computation; CORROBORATING vs
SAME_SOURCE_DUPLICATE distinction at 0.80/0.95 Jaccard thresholds.
ProcessArticleUseCase: 3-stage dedup chain → MinIO silver write → 4-table atomic DB tx → Valkey index.
ArticleConsumer: at-least-once with manual offset commit after DB commit.
S5OutboxDispatcher: publishes content.article.stored.v1 via outbox pattern.

Co-authored-by: <agent>
```

---

## Definition of done

- [ ] T-S5-007: ValkeyLSH with 4 bands, `_compute_band_hash` deterministic, Jaccard in-process, CORROBORATING/SAME_SOURCE_DUPLICATE/UNIQUE correctly classified, `index()` sets TTL. 10+ tests green. `ruff`/`mypy` clean.
- [ ] T-S5-008: `ProcessArticleUseCase` chains all 3 dedup stages; CORROBORATING articles written; SAME_SOURCE_DUPLICATE suppressed; 4-table atomic DB transaction; Valkey index called after commit; Kafka never called directly. 8+ tests green. `ruff`/`mypy` clean.
- [ ] T-S5-009: `ArticleConsumer` at-least-once; `enable_auto_commit=False`; offset committed only after use_case returns; unhandled exception does not commit. 4+ tests green. `ruff`/`mypy` clean.
- [ ] T-S5-010: `S5OutboxDispatcher` publishes `content.article.stored.v1`; retry/DLQ logic correct; Avro schema valid roundtrip. 4+ tests green. `ruff`/`mypy` clean.
- [ ] `make test` exit 0.
- [ ] `ruff check` exit 0; `mypy` exit 0.
- [ ] `docs/services/content-store.md` updated: LSH diagram + canonical write sequence + consumer section + 4 common pitfalls.
- [ ] Documentation quality gate: all 8 criteria ✓ or N/A justified.
- [ ] Commit message proposal provided.
