# Execution Prompt 0013 — Ingestion Pipeline v1: S6+S7+S10 Wave 03

**Wave:** 03 of 13
**Service:** S6 NLP Pipeline
**Focus:** S6 Blocks 7–9 — Embedding Generation, Novelty Gate, Entity Resolution Cascade
**Tasks:** T-S6-008, T-S6-009, T-S6-010
**Date:** 2026-03-22

---

## Context (read first)

- Planning response: `docs/ai-interactions/agent-responses/0013-response-20260322-ingestion-pipeline-v1-s6-s7-s10.md`
- Service doc: `docs/services/nlp-pipeline.md`
- ml-clients: `docs/libs/ml-clients.md`

---

## Assigned agent profile(s)

- **machine-learning-lead** — T-S6-008 (embedding, chunk strategy), T-S6-009 (MinHash/LSH novelty)
- **backend-engineer** — T-S6-010 (entity resolution cascade, DB queries)

Both agents work in parallel; T-S6-009 has a soft dependency on T-S6-008 (MinHash structures).

---

## Mandatory pre-read

1. `docs/agents/AGENTS.md`
2. `docs/CLAUDE.md`
3. `docs/services/nlp-pipeline.md`
4. `docs/libs/ml-clients.md` — EmbeddingClient protocol
5. Wave 01 output: `services/nlp-pipeline/src/nlp_pipeline/domain/` and `infrastructure/nlp_db/`
6. Wave 02 output: `services/nlp-pipeline/src/nlp_pipeline/application/blocks/block04_ner.py` (EntityMention output)
7. `docs/ai-interactions/agent-responses/0013-response-20260322-ingestion-pipeline-v1-s6-s7-s10.md` — task details T-S6-008, T-S6-009, T-S6-010
8. `docs/libs/common.md` — UUIDv7 (`new_uuid7`), UTC time (`utc_now`), cross-service types (`DocumentId`, `EntityId`, `UrlHash`, `MinIOKey`)
9. **`docs/STANDARDS.md`** — engineering standards and anti-patterns: canonical library usage, config conventions, observability setup, testing rules

---

## Objective

Implement Blocks 7–9 of S6:
- **Block 7** (T-S6-008): Sentence-aware chunking + embedding generation via EmbeddingClient; 512-token chunks with 64-token overlap; never split mid-sentence; write `chunk_embeddings` + `section_embeddings`; pending queue on failure
- **Block 8** (T-S6-009): Two-stage novelty gate using MinHash + Valkey LSH (Stage 1) and per-entity embedding similarity (Stage 2); downgrade DEEP→LIGHT if all entities near-duplicate
- **Block 9** (T-S6-010): 4-step entity resolution cascade (exact alias → ticker/ISIN → fuzzy trigram → ANN HNSW); auto-resolve and provisional paths

Prerequisites: Wave 01 (config, domain, repos) + Wave 02 (NER output — entity mentions are the input to resolution).

---

## Task scope for this wave

### Parallel group (T-S6-008 and T-S6-010 fully parallel; T-S6-009 needs MinHash from T-S6-008)

**T-S6-008: Block 7 — Embedding Generation**
- `services/nlp-pipeline/src/nlp_pipeline/application/blocks/block07_embedding.py`
- `services/nlp-pipeline/src/nlp_pipeline/application/chunking.py`

**T-S6-009: Block 8 — Novelty Gate** (start after T-S6-008 MinHash utility is available)
- `services/nlp-pipeline/src/nlp_pipeline/application/blocks/block08_novelty.py`

**T-S6-010: Block 9 — Entity Resolution Cascade**
- `services/nlp-pipeline/src/nlp_pipeline/application/blocks/block09_entity_resolution.py`

---

## Why this chunk

Blocks 7–9 form the second processing layer, gated by the routing tier from Block 5 (Wave 02). Block 7 must precede Block 8 (MinHash is computed from chunks) but both can be developed in parallel. Block 9 (entity resolution) is completely independent of Blocks 7–8 and can be written simultaneously. All three are required before Wave 04 (Block 10 deep extraction needs resolved entity IDs; Kafka consumer orchestration needs all blocks available).

---

## Implementation instructions

### T-S6-008: Block 7 — Embedding Generation

#### Chunking utility (sentence-aware, never split mid-sentence)

```python
# services/nlp-pipeline/src/nlp_pipeline/application/chunking.py
import re
from uuid import uuid4
from nlp_pipeline.domain.models import Section, Chunk
from nlp_pipeline.config import settings

_SENTENCE_END = re.compile(r'(?<=[.!?])\s+')

def _estimate_tokens(text: str) -> int:
    """Approximate token count using char/4 heuristic with 20% safety margin."""
    return int(len(text) / 4 * 0.8)

def _split_sentences(text: str) -> list[str]:
    """Split text into sentences at punctuation boundaries."""
    parts = _SENTENCE_END.split(text.strip())
    return [p.strip() for p in parts if p.strip()]

def chunk_section(section: Section, chunk_size: int = None, overlap: int = None) -> list[Chunk]:
    """
    Create sentence-aware chunks.
    - Max chunk_size tokens (default from settings)
    - overlap tokens shared between adjacent chunks
    - NEVER split mid-sentence
    """
    chunk_size = chunk_size or settings.EMBEDDING_CHUNK_SIZE
    overlap = overlap or settings.EMBEDDING_CHUNK_OVERLAP

    sentences = _split_sentences(section.text)
    chunks: list[Chunk] = []
    current_sentences: list[str] = []
    current_tokens = 0
    chunk_index = 0

    for sentence in sentences:
        sent_tokens = _estimate_tokens(sentence)

        if current_tokens + sent_tokens > chunk_size and current_sentences:
            # Emit current chunk
            chunk_text = " ".join(current_sentences)
            chunks.append(Chunk(
                id=uuid4(),
                section_id=section.id,
                chunk_index=chunk_index,
                text=chunk_text,
                token_count=current_tokens,
            ))
            chunk_index += 1

            # Overlap: keep last N tokens worth of sentences
            overlap_sentences = []
            overlap_tokens = 0
            for s in reversed(current_sentences):
                t = _estimate_tokens(s)
                if overlap_tokens + t <= overlap:
                    overlap_sentences.insert(0, s)
                    overlap_tokens += t
                else:
                    break
            current_sentences = overlap_sentences
            current_tokens = overlap_tokens

        current_sentences.append(sentence)
        current_tokens += sent_tokens

    # Final chunk
    if current_sentences:
        chunk_text = " ".join(current_sentences)
        chunks.append(Chunk(
            id=uuid4(),
            section_id=section.id,
            chunk_index=chunk_index,
            text=chunk_text,
            token_count=current_tokens,
        ))

    return chunks
```

#### EmbeddingBlock

```python
# services/nlp-pipeline/src/nlp_pipeline/application/blocks/block07_embedding.py
import structlog
from typing import Protocol
from nlp_pipeline.domain.models import Section, Chunk, EmbeddingPendingEntry
from nlp_pipeline.domain.enums import RoutingTier
from nlp_pipeline.application.chunking import chunk_section
from nlp_pipeline.infrastructure.nlp_db.repositories.chunk_repository import ChunkRepository
from nlp_pipeline.infrastructure.metrics import s6_embeddings_created_total
from uuid import uuid4

logger = structlog.get_logger(__name__)

class EmbeddingClient(Protocol):
    """Protocol from libs/ml-clients — do NOT instantiate directly."""
    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Returns list of 1024-dim embedding vectors."""
        ...

class EmbeddingBlock:
    def __init__(
        self,
        embedding_client: EmbeddingClient,
        chunk_repo: ChunkRepository,
        session,  # nlp_db session for section_embeddings and pending queue
    ) -> None:
        self.embedding_client = embedding_client
        self.chunk_repo = chunk_repo
        self.session = session

    async def process(self, sections: list[Section], tier: RoutingTier) -> list[Chunk]:
        """
        LIGHT tier: section embeddings only, no chunk embeddings.
        MEDIUM/DEEP: both section and chunk embeddings.
        """
        all_chunks: list[Chunk] = []

        # Section embeddings (all non-suppress tiers)
        await self._embed_sections(sections)

        if tier == RoutingTier.LIGHT:
            logger.info("embedding_light_tier_section_only", section_count=len(sections))
            return []

        # Chunk embeddings (MEDIUM and DEEP)
        for section in sections:
            chunks = chunk_section(section)
            embedded_chunks = await self._embed_chunks(chunks)
            all_chunks.extend(embedded_chunks)

        if all_chunks:
            await self.chunk_repo.insert_batch(all_chunks)
            s6_embeddings_created_total.inc(len(all_chunks) + len(sections))

        return all_chunks

    async def _embed_sections(self, sections: list[Section]) -> None:
        from sqlalchemy import text
        texts = [s.text for s in sections]
        try:
            embeddings = await self.embedding_client.embed(texts)
            for section, embedding in zip(sections, embeddings):
                await self.session.execute(
                    text("INSERT INTO section_embeddings (section_id, embedding) VALUES (:section_id, :embedding::vector) ON CONFLICT (section_id) DO UPDATE SET embedding = EXCLUDED.embedding"),
                    {"section_id": str(section.id), "embedding": str(embedding)}
                )
            await self.session.commit()
        except Exception as e:
            logger.error("section_embedding_failed", error=str(e))
            await self._write_pending(sections, "section")

    async def _embed_chunks(self, chunks: list[Chunk]) -> list[Chunk]:
        texts = [c.text for c in chunks]
        try:
            embeddings = await self.embedding_client.embed(texts)
            return [
                Chunk(id=c.id, section_id=c.section_id, chunk_index=c.chunk_index,
                      text=c.text, token_count=c.token_count, embedding=emb)
                for c, emb in zip(chunks, embeddings)
            ]
        except Exception as e:
            logger.error("chunk_embedding_failed", error=str(e))
            await self._write_pending(chunks, "chunk")
            return [Chunk(id=c.id, section_id=c.section_id, chunk_index=c.chunk_index,
                          text=c.text, token_count=c.token_count) for c in chunks]

    async def _write_pending(self, items, ref_type: str) -> None:
        from sqlalchemy import text
        for item in items:
            await self.session.execute(
                text("INSERT INTO embedding_pending_queue (id, ref_type, ref_id, retry_count, created_at) VALUES (gen_random_uuid(), :ref_type, :ref_id, 0, NOW())"),
                {"ref_type": ref_type, "ref_id": str(item.id)}
            )
        await self.session.commit()
```

### T-S6-009: Block 8 — Novelty Gate

```python
# services/nlp-pipeline/src/nlp_pipeline/application/blocks/block08_novelty.py
import structlog
from datasketch import MinHash, MinHashLSH
from uuid import UUID
from nlp_pipeline.domain.models import NLPDocument, Chunk, EntityMention
from nlp_pipeline.domain.enums import RoutingTier
from nlp_pipeline.config import settings

logger = structlog.get_logger(__name__)

def _shingles(text: str, k: int = 4) -> set[bytes]:
    """k-gram character shingles."""
    normalized = text.lower().replace(" ", "")
    return {normalized[i:i+k].encode() for i in range(max(len(normalized) - k + 1, 1))}

class NoveltyDecision:
    def __init__(self, is_novel: bool, stage: str, jaccard: float, action: str):
        self.is_novel = is_novel
        self.stage = stage
        self.jaccard = jaccard
        self.action = action  # 'pass', 'downgrade', 'suppress'

class NoveltyBlock:
    def __init__(self, valkey_client, session) -> None:
        self.valkey = valkey_client
        self.session = session

    async def process(
        self,
        doc: NLPDocument,
        chunks: list[Chunk],
        mentions: list[EntityMention],
        current_tier: RoutingTier,
    ) -> tuple[RoutingTier, NoveltyDecision]:
        """
        Returns updated tier (may downgrade DEEP→LIGHT) and decision.
        """
        # Stage 1: MinHash LSH pre-resolution check
        minhash = MinHash(num_perm=settings.MINHASH_NUM_PERM)
        for shingle in _shingles(doc.raw_content):
            minhash.update(shingle)

        stage1_jaccard = await self._check_lsh(str(doc.article_id), minhash)
        if stage1_jaccard >= settings.LSH_THRESHOLD:
            logger.info("novelty_stage1_near_duplicate",
                       article_id=str(doc.article_id), jaccard=stage1_jaccard)
            decision = NoveltyDecision(
                is_novel=False, stage="stage1", jaccard=stage1_jaccard, action="downgrade"
            )
            await self._log_decision(doc.article_id, decision)
            new_tier = RoutingTier.LIGHT if current_tier == RoutingTier.DEEP else current_tier
            return new_tier, decision

        # Stage 2: per-entity embedding similarity (post-resolution)
        if current_tier == RoutingTier.DEEP and mentions:
            stage2_result = await self._check_entity_similarity(mentions, chunks)
            if stage2_result >= settings.LSH_THRESHOLD:
                logger.info("novelty_stage2_all_entities_duplicate",
                           article_id=str(doc.article_id), jaccard=stage2_result)
                decision = NoveltyDecision(
                    is_novel=False, stage="stage2", jaccard=stage2_result, action="downgrade"
                )
                await self._log_decision(doc.article_id, decision)
                return RoutingTier.LIGHT, decision

        # Novel document — store in LSH window
        await self._store_lsh(str(doc.article_id), minhash)

        decision = NoveltyDecision(is_novel=True, stage="none", jaccard=0.0, action="pass")
        await self._log_decision(doc.article_id, decision)
        return current_tier, decision

    async def _check_lsh(self, doc_id: str, minhash: MinHash) -> float:
        """Check Valkey LSH window for near-duplicates. Return max Jaccard found."""
        try:
            # Retrieve stored MinHash signatures from Valkey content_store_db
            stored_keys = await self.valkey.smembers("nlp:lsh:doc_keys")
            max_jaccard = 0.0
            current_sig = minhash.hashvalues.tolist()
            for key in list(stored_keys)[:1000]:  # limit scan
                sig_bytes = await self.valkey.get(f"nlp:lsh:sig:{key.decode()}")
                if sig_bytes:
                    import struct, numpy as np
                    stored_sig = struct.unpack(f"{settings.MINHASH_NUM_PERM}I", sig_bytes)
                    matches = sum(a == b for a, b in zip(current_sig, stored_sig))
                    jaccard = matches / settings.MINHASH_NUM_PERM
                    max_jaccard = max(max_jaccard, jaccard)
            return max_jaccard
        except Exception as e:
            logger.warning("lsh_check_failed", error=str(e))
            return 0.0  # On failure, assume novel

    async def _store_lsh(self, doc_id: str, minhash: MinHash) -> None:
        """Store MinHash in Valkey LSH window."""
        try:
            import struct
            sig_bytes = struct.pack(f"{settings.MINHASH_NUM_PERM}I", *minhash.hashvalues.tolist())
            await self.valkey.set(f"nlp:lsh:sig:{doc_id}", sig_bytes, ex=86400 * 7)  # 7-day TTL
            await self.valkey.sadd("nlp:lsh:doc_keys", doc_id)
        except Exception as e:
            logger.warning("lsh_store_failed", error=str(e))

    async def _check_entity_similarity(self, mentions: list[EntityMention], chunks: list[Chunk]) -> float:
        """Stage 2: check if all resolved entities have near-duplicate content recently."""
        resolved = [m for m in mentions if m.resolved_entity_id]
        if not resolved:
            return 0.0
        from sqlalchemy import text
        entity_jaccards = []
        for mention in resolved[:10]:  # limit to 10 entities
            # Query chunk_embeddings for recent articles mentioning same entity
            # Compute Jaccard proxy via cosine similarity threshold
            # For now: use a simplified check via Valkey entity similarity store
            result = await self.valkey.get(f"nlp:entity:recent:{mention.resolved_entity_id}")
            if result:
                entity_jaccards.append(float(result))
        if not entity_jaccards:
            return 0.0
        return min(entity_jaccards)  # If ALL entities are near-duplicate

    async def _log_decision(self, article_id: UUID, decision: NoveltyDecision) -> None:
        from sqlalchemy import text
        await self.session.execute(
            text("""
                INSERT INTO nlp_processing_log (id, article_id, novelty_stage, novelty_result, novelty_jaccard, created_at)
                VALUES (gen_random_uuid(), :article_id, :stage, :result, :jaccard, NOW())
            """),
            {
                "article_id": str(article_id),
                "stage": decision.stage,
                "result": decision.action,
                "jaccard": decision.jaccard,
            }
        )
        await self.session.commit()
```

### T-S6-010: Block 9 — Entity Resolution Cascade

```python
# services/nlp-pipeline/src/nlp_pipeline/application/blocks/block09_entity_resolution.py
import structlog
from uuid import UUID
from typing import Optional
from sqlalchemy import text
from nlp_pipeline.domain.models import EntityMention
from nlp_pipeline.domain.enums import ResolutionMethod
from nlp_pipeline.infrastructure.intelligence_db.repositories.entity_alias_repository import EntityAliasRepository
from nlp_pipeline.infrastructure.intelligence_db.repositories.entity_profile_embedding_repository import EntityProfileEmbeddingRepository
from nlp_pipeline.infrastructure.metrics import s6_entity_resolved_total
from nlp_pipeline.config import settings

logger = structlog.get_logger(__name__)

class EntityResolutionBlock:
    def __init__(
        self,
        alias_repo: EntityAliasRepository,
        profile_embedding_repo: EntityProfileEmbeddingRepository,
        embedding_client,  # EmbeddingClient protocol
        write_session,     # intelligence_db write session for entity_resolution_queue
        readonly_session,  # intelligence_db read session for trigram queries
    ) -> None:
        self.alias_repo = alias_repo
        self.profile_embedding_repo = profile_embedding_repo
        self.embedding_client = embedding_client
        self.write_session = write_session
        self.readonly_session = readonly_session

    async def process(self, mentions: list[EntityMention]) -> list[EntityMention]:
        """
        Resolve each mention through 4-step cascade.
        Unresolved mentions are returned with resolved_entity_id=None — never discarded.
        """
        resolved_mentions = []
        for mention in mentions:
            updated = await self._resolve_mention(mention)
            resolved_mentions.append(updated)
        return resolved_mentions

    async def _resolve_mention(self, mention: EntityMention) -> EntityMention:
        # Step 1: Exact alias match
        entity_id = await self.alias_repo.find_by_text(mention.text)
        if entity_id:
            return self._apply_resolution(mention, entity_id, ResolutionMethod.EXACT_ALIAS, 1.0)

        # Step 2: Ticker/ISIN match (only if mention text looks like a ticker/ISIN)
        if self._looks_like_ticker(mention.text):
            entity_id = await self.alias_repo.find_by_ticker(mention.text)
            if entity_id:
                return self._apply_resolution(mention, entity_id, ResolutionMethod.TICKER_ISIN, 0.95)
        if self._looks_like_isin(mention.text):
            entity_id = await self.alias_repo.find_by_isin(mention.text)
            if entity_id:
                return self._apply_resolution(mention, entity_id, ResolutionMethod.TICKER_ISIN, 0.95)

        # Step 3: Fuzzy trigram similarity
        trigram_result = await self._fuzzy_trigram_search(mention.text)
        if trigram_result:
            entity_id, similarity = trigram_result
            if similarity >= 0.6:
                return self._apply_resolution(mention, entity_id, ResolutionMethod.FUZZY_TRIGRAM, similarity)

        # Step 4: ANN HNSW search on entity profile embeddings
        context_text = self._build_context_text(mention)
        ann_result = await self._ann_search(context_text)
        if ann_result:
            entity_id, distance = ann_result
            confidence = max(0.0, 1.0 - distance)  # cosine distance → confidence
            if confidence >= settings.PROVISIONAL_THRESHOLD:
                updated = self._apply_resolution(mention, entity_id, ResolutionMethod.ANN_HNSW, confidence)
                if confidence < settings.AUTO_RESOLVE_THRESHOLD:
                    # Provisional: write to entity_resolution_queue
                    await self._write_provisional_queue(mention, entity_id, confidence)
                    updated.resolved_entity_id = None  # Not auto-resolved
                return updated

        # Unresolved: return as-is (never discard)
        logger.debug("entity_unresolved", mention_text=mention.text, entity_class=mention.entity_class.value)
        return mention

    def _apply_resolution(
        self,
        mention: EntityMention,
        entity_id: UUID,
        method: ResolutionMethod,
        confidence: float,
    ) -> EntityMention:
        mention.resolved_entity_id = entity_id
        mention.resolution_method = method
        mention.resolution_confidence = confidence
        s6_entity_resolved_total.labels(method=method.value).inc()
        logger.debug("entity_resolved", mention_text=mention.text, method=method.value, confidence=confidence)
        return mention

    async def _fuzzy_trigram_search(self, text: str) -> Optional[tuple[UUID, float]]:
        """pg_trgm similarity search on entity_aliases.alias."""
        try:
            result = await self.readonly_session.execute(
                text("""
                    SELECT entity_id, similarity(alias, :text) AS sim
                    FROM entity_aliases
                    WHERE similarity(alias, :text) >= 0.6
                    ORDER BY sim DESC
                    LIMIT 1
                """),
                {"text": text}
            )
            row = result.fetchone()
            if row:
                return row.entity_id, float(row.sim)
        except Exception as e:
            logger.warning("trigram_search_failed", error=str(e))
        return None

    def _build_context_text(self, mention: EntityMention) -> str:
        """Build context for ANN search with sentence-boundary guard."""
        # 10-char window around mention for context
        return f"{mention.entity_class.value}: {mention.text}"

    async def _ann_search(self, context_text: str) -> Optional[tuple[UUID, float]]:
        """Step 4: ANN HNSW search on entity_profile_embeddings."""
        try:
            embeddings = await self.embedding_client.embed([context_text])
            if not embeddings:
                return None
            results = await self.profile_embedding_repo.find_nearest(embeddings[0], limit=1)
            if results:
                return results[0]
        except Exception as e:
            logger.warning("ann_search_failed", error=str(e))
        return None

    async def _write_provisional_queue(self, mention: EntityMention, candidate_id: UUID, confidence: float) -> None:
        await self.write_session.execute(
            text("""
                INSERT INTO entity_resolution_queue
                    (id, mention_text, entity_class, candidate_entity_id, confidence, created_at)
                VALUES
                    (gen_random_uuid(), :text, :class, :candidate, :confidence, NOW())
            """),
            {
                "text": mention.text,
                "class": mention.entity_class.value,
                "candidate": str(candidate_id),
                "confidence": confidence,
            }
        )
        await self.write_session.commit()

    @staticmethod
    def _looks_like_ticker(text: str) -> bool:
        """Heuristic: 1–5 uppercase letters, optionally followed by exchange suffix."""
        import re
        return bool(re.match(r'^[A-Z]{1,5}(\.[A-Z]{1,4})?$', text))

    @staticmethod
    def _looks_like_isin(text: str) -> bool:
        """Heuristic: 2-letter country + 9 alphanum + 1 check digit."""
        import re
        return bool(re.match(r'^[A-Z]{2}[A-Z0-9]{9}[0-9]$', text))
```

---

## Constraints

- Do NOT implement Block 10 (LLM extraction) in this wave
- EmbeddingClient and NERClient MUST be used via Protocol — never instantiate Ollama directly
- Chunking MUST NEVER split mid-sentence — sentence boundary is enforced before emitting a chunk
- Token counting uses char/4 with 20% safety margin — no tiktoken dependency required
- Novelty gate failures (Valkey errors) MUST return 0.0 / `is_novel=True` — never raise
- Entity resolution unresolved mentions MUST be returned (not discarded)
- `AUTO_RESOLVE_THRESHOLD` governs whether `resolved_entity_id` is set; below this but above `PROVISIONAL_THRESHOLD`, write to `entity_resolution_queue` and set `resolved_entity_id=None`
- Fuzzy trigram requires `pg_trgm` extension — if not installed, catch exception and skip Step 3
- **`common.ids.new_uuid7()` mandatory** — all entity, section, chunk, relation, and outbox primary keys must use `common.ids.new_uuid7()`. Never call `common.ids.new_uuid7()` directly in service code.
- **`common.time.utc_now()` mandatory** — all timestamp generation uses `common.time.utc_now()`. Never call `datetime.now(UTC)` or `datetime.utcnow()` directly in service code.
- **`common.types` for cross-service IDs** — use `EntityId` (from `common.types`) for canonical entity references across S6, S7; use `DocumentId` for document references; use `MinIOKey` for MinIO key strings.

---

## Scope & token budget

**Write paths:**
```
services/nlp-pipeline/src/nlp_pipeline/application/chunking.py
services/nlp-pipeline/src/nlp_pipeline/application/blocks/block07_embedding.py
services/nlp-pipeline/src/nlp_pipeline/application/blocks/block08_novelty.py
services/nlp-pipeline/src/nlp_pipeline/application/blocks/block09_entity_resolution.py
services/nlp-pipeline/tests/unit/blocks/test_block07_embedding.py
services/nlp-pipeline/tests/unit/blocks/test_block08_novelty.py
services/nlp-pipeline/tests/unit/blocks/test_block09_entity_resolution.py
services/nlp-pipeline/tests/unit/test_chunking.py
```

**Max exploration:** Wave 01+02 outputs, `docs/libs/ml-clients.md`. Do not explore S7/S10.

**Stop condition:** All 3 blocks implemented, unit tests pass, ruff+mypy pass.

---

## Required tests

```bash
cd services/nlp-pipeline && pytest tests/unit/blocks/test_block07_embedding.py tests/unit/blocks/test_block08_novelty.py tests/unit/blocks/test_block09_entity_resolution.py tests/unit/test_chunking.py -v
ruff check services/nlp-pipeline/src/nlp_pipeline/application/
mypy services/nlp-pipeline/src/nlp_pipeline/application/
```

**Pass criteria:**
- `test_chunk_never_exceeds_512_tokens`: chunker produces no chunk with token_count > 512
- `test_chunk_sentence_boundary_respected`: no chunk ends mid-sentence (last char is `.`, `!`, or `?`)
- `test_embedding_failure_writes_pending_queue`: when EmbeddingClient.embed raises, pending queue entry created
- `test_novelty_near_duplicate_downgrades_deep_to_light`: Stage 1 Jaccard >= 0.80 → tier downgraded from DEEP to LIGHT
- `test_novelty_failure_returns_novel`: Valkey exception → returns is_novel=True
- `test_entity_resolution_unresolved_not_discarded`: no match at any step → mention returned with resolved_entity_id=None
- `test_entity_resolution_exact_alias_priority`: exact alias match → method=EXACT_ALIAS, confidence=1.0
- `test_entity_resolution_provisional_below_auto_threshold`: confidence between PROVISIONAL and AUTO → entity_resolution_queue written, resolved_entity_id=None

---

## Incremental quality gates (mandatory)

1. **T-S6-008:**
   ```bash
   pytest tests/unit/test_chunking.py tests/unit/blocks/test_block07_embedding.py -v
   ruff check src/nlp_pipeline/application/chunking.py src/nlp_pipeline/application/blocks/block07_embedding.py
   mypy src/nlp_pipeline/application/chunking.py src/nlp_pipeline/application/blocks/block07_embedding.py
   ```

2. **T-S6-009:**
   ```bash
   pytest tests/unit/blocks/test_block08_novelty.py -v
   ruff check src/nlp_pipeline/application/blocks/block08_novelty.py
   mypy src/nlp_pipeline/application/blocks/block08_novelty.py
   ```

3. **T-S6-010:**
   ```bash
   pytest tests/unit/blocks/test_block09_entity_resolution.py -v
   ruff check src/nlp_pipeline/application/blocks/block09_entity_resolution.py
   mypy src/nlp_pipeline/application/blocks/block09_entity_resolution.py
   ```

No deferred fixes.

---

## Documentation requirements

| File | Update | Action |
|------|--------|--------|
| `docs/services/nlp-pipeline.md` | Block 7 chunking | Add sentence-aware chunking description; token estimate formula |
| `docs/services/nlp-pipeline.md` | Block 8 novelty | Add 2-stage novelty gate description; Valkey LSH TTL=7 days |
| `docs/services/nlp-pipeline.md` | Block 9 resolution | Add 4-step cascade table (step, method, confidence, threshold) |
| `docs/libs/ml-clients.md` | EmbeddingClient usage | N/A if already documented; add S6 usage note if missing |

**Common pitfalls to add in nlp-pipeline.md:**
1. Chunking: if sentence splitter regex does not fire on text without punctuation, entire text becomes one chunk — acceptable but log a warning
2. Novelty Stage 1 LSH window grows unbounded without TTL — enforce 7-day TTL on all Valkey keys
3. Entity resolution Step 3 requires pg_trgm — always catch `sqlalchemy.exc.OperationalError` and skip Step 3 gracefully if extension absent

---

## Required handoff evidence

### Validation ledger

| Command | Scope | Exit code | Result |
|---------|-------|-----------|--------|
| `pytest tests/unit/test_chunking.py::test_chunk_never_exceeds_512_tokens` | chunking | 0 | Pass |
| `pytest tests/unit/blocks/test_block07_embedding.py::test_embedding_failure_writes_pending_queue` | T-S6-008 | 0 | Pass |
| `pytest tests/unit/blocks/test_block08_novelty.py::test_novelty_near_duplicate_downgrades_deep_to_light` | T-S6-009 | 0 | Pass |
| `pytest tests/unit/blocks/test_block09_entity_resolution.py::test_entity_resolution_unresolved_not_discarded` | T-S6-010 | 0 | Pass |
| `pytest tests/unit/ -v` | All wave 03 | 0 | All pass |
| `ruff check src/nlp_pipeline/application/` | Wave 03 code | 0 | No violations |
| `mypy src/nlp_pipeline/application/` | Wave 03 code | 0 | No errors |

### Commit message
```
feat(s6): implement blocks 7-9 — embeddings, novelty gate, entity resolution

Add sentence-aware 512-token chunking with 64-token overlap (never mid-sentence
split), EmbeddingClient-backed section+chunk embeddings with pending queue on
failure, two-stage MinHash/Valkey LSH novelty gate (DEEP→LIGHT on duplicate),
and 4-step entity resolution cascade (exact/ticker/trigram/ANN-HNSW).
```

---

## Definition of done

- [ ] Chunking: max 512 tokens per chunk; sentence boundary respected; 64-token overlap
- [ ] Embedding: failure writes to `embedding_pending_queue`; LIGHT tier → section embeddings only
- [ ] Novelty Stage 1: MinHash + Valkey LSH window checked; Valkey error → novel=True
- [ ] Novelty Stage 2: per-entity similarity check; all entities duplicate → DEEP→LIGHT downgrade
- [ ] Novelty: decision logged to `nlp_processing_log`
- [ ] Entity resolution: all 4 steps implemented in order
- [ ] Entity resolution: unresolved mentions returned with `resolved_entity_id=None` (never discarded)
- [ ] Entity resolution: provisional path writes `entity_resolution_queue`
- [ ] All unit tests pass
- [ ] ruff exits 0; mypy exits 0
- [ ] `docs/services/nlp-pipeline.md` updated with Blocks 7–9, chunking formula, resolution cascade table
