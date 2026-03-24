# Execution Prompt 0013 — Ingestion Pipeline v1: S6+S7+S10 Wave 08

**Wave:** 08 of 13
**Service:** S7 Knowledge Graph
**Focus:** S7 Async Workers 13A–D — Confidence Recomputation, Contradiction Batch, Summary Generation, Entity Profile Embedding
**Tasks:** T-S7-006, T-S7-007, T-S7-008, T-S7-009 (parallel)
**Date:** 2026-03-22

---

## Context (read first)

- Planning response: `docs/ai-interactions/agent-responses/0013-response-20260322-ingestion-pipeline-v1-s6-s7-s10.md`
- Service doc: `docs/services/knowledge-graph.md`

---

## Assigned agent profile(s)

- **rag-knowledge-graph-engineer** — T-S7-006 (confidence formula), T-S7-007 (contradiction batch), T-S7-008 (summary generation)
- **machine-learning-lead** — T-S7-009 (entity profile embedding: deterministic template, Valkey dedup)

All 4 workers are independent of each other and can be implemented in parallel.

---

## Mandatory pre-read

1. `docs/agents/AGENTS.md`
2. `docs/CLAUDE.md`
3. `docs/services/knowledge-graph.md`
4. `docs/libs/ml-clients.md` — EmbeddingClient, ExtractionClient protocols
5. Wave 06 output: domain models, intelligence_db repos
6. Wave 07 output: scheduler (KnowledgeGraphScheduler), blocks 11–12, co-topology
7. `docs/ai-interactions/agent-responses/0013-response-20260322-ingestion-pipeline-v1-s6-s7-s10.md` — task details T-S7-006, T-S7-007, T-S7-008, T-S7-009
8. `docs/libs/common.md` — UUIDv7 (`new_uuid7`), UTC time (`utc_now`), cross-service types (`DocumentId`, `EntityId`, `UrlHash`, `MinIOKey`)
9. **`docs/STANDARDS.md`** — engineering standards and anti-patterns: canonical library usage, config conventions, observability setup, testing rules

---

## Objective

Implement 4 of the 8 APScheduler workers for S7:
- **T-S7-006** (Block 13A): Confidence recomputation — 15-min interval; 4-step formula: support (normalize by sum(temporal_weight)), corroboration_gain (capped 0.20), contradiction_penalty (top-3, capped 0.60), clamp(final, 0.0, 1.0)
- **T-S7-007** (Block 13B): Contradiction detection batch — 30-min scan of unprocessed claims, same logic as hot path, rate-limited to 1000 claims/run
- **T-S7-008** (Block 13C): Summary generation — 60-min interval; evidence selection ORDER BY temporal_weight/source_weight/date LIMIT 10; change detection via SHA-256 evidence hash
- **T-S7-009** (Block 13D): Entity profile embedding refresh — 60-min; Valkey dedup (30-min TTL); 5-field deterministic profile text; truncate at 512 tokens

Prerequisites: Wave 06 (repos) + Wave 07 (scheduler setup, hot-path writes that workers process).

---

## Task scope for this wave

### Parallel group (all 4 workers independent)

**T-S7-006: Block 13A — Confidence Recomputation Worker**
- `services/knowledge-graph/src/knowledge_graph/application/workers/confidence_recomputation.py`

**T-S7-007: Block 13B — Contradiction Detection Batch Worker**
- `services/knowledge-graph/src/knowledge_graph/application/workers/contradiction_batch.py`

**T-S7-008: Block 13C — Summary Generation Worker**
- `services/knowledge-graph/src/knowledge_graph/application/workers/summary_generation.py`

**T-S7-009: Block 13D — Entity Profile Embedding Refresh Worker**
- `services/knowledge-graph/src/knowledge_graph/application/workers/entity_profile_embedding.py`

---

## Why this chunk

These 4 workers operate on data written by the hot path (Blocks 12a, 12b) from Wave 07. They are independent of each other — confidence recomputation does not depend on summary generation. They share only the scheduler registration point (Wave 07's `KnowledgeGraphScheduler`). After Wave 08, the most time-critical workers (confidence and entity profiles) are operational, enabling M5 milestone readiness.

---

## Implementation instructions

### T-S7-006: Block 13A — Confidence Recomputation Worker

#### CRITICAL: Formula normalization is by sum(temporal_weight) NOT len(active_evidence)

```python
# services/knowledge-graph/src/knowledge_graph/application/workers/confidence_recomputation.py
import structlog
from sqlalchemy import text
from knowledge_graph.domain.models import ConfidenceComponents
from knowledge_graph.infrastructure.intelligence_db.repositories.relation_evidence_raw_repository import RelationEvidenceRawRepository
from knowledge_graph.infrastructure.intelligence_db.repositories.relation_repository import RelationRepository
from knowledge_graph.infrastructure.metrics import s7_confidence_recomputed_total
from knowledge_graph.config import settings

logger = structlog.get_logger(__name__)

class ConfidenceRecomputationWorker:
    def __init__(
        self,
        evidence_repo: RelationEvidenceRawRepository,
        relation_repo: RelationRepository,
        session,
    ) -> None:
        self.evidence_repo = evidence_repo
        self.relation_repo = relation_repo
        self.session = session

    async def run(self) -> None:
        """15-minute interval: process all unprocessed evidence grouped by partition_key."""
        logger.info("confidence_recomputation_started")

        # Get distinct partition_keys with unprocessed evidence
        result = await self.session.execute(
            text("""
                SELECT DISTINCT partition_key, relation_id
                FROM relation_evidence_raw
                WHERE processed = false
                LIMIT 500  -- Process at most 500 partition groups per run
            """)
        )
        groups = result.fetchall()

        for row in groups:
            try:
                await self._recompute_for_relation(row.relation_id, row.partition_key)
            except Exception as e:
                logger.error("confidence_recompute_failed",
                           relation_id=str(row.relation_id), error=str(e))

        logger.info("confidence_recomputation_complete", groups_processed=len(groups))

    async def _recompute_for_relation(self, relation_id, partition_key: str) -> None:
        # Fetch all unprocessed evidence for this partition
        evidence_rows = await self.evidence_repo.get_unprocessed_by_partition(partition_key, limit=1000)
        if not evidence_rows:
            return

        # Also need contradiction links for Step 3
        contradiction_rows = await self._get_top3_contradictions(relation_id)

        # Fetch decay_alpha from relation_type_registry
        decay_alpha = await self._get_decay_alpha(relation_id)

        components = self._compute_confidence(evidence_rows, contradiction_rows, decay_alpha)
        components.validate()  # Assert all invariants

        # Update relation confidence and set summary_stale=true
        await self.relation_repo.set_confidence(relation_id, components.final)
        await self.session.execute(
            text("UPDATE relations SET summary_stale = true WHERE id = :id"),
            {"id": str(relation_id)}
        )

        # Mark evidence as processed
        evidence_ids = [e["id"] for e in evidence_rows]
        await self.session.execute(
            text("UPDATE relation_evidence_raw SET processed = true WHERE id = ANY(:ids)"),
            {"ids": evidence_ids}
        )
        await self.session.commit()
        s7_confidence_recomputed_total.inc()

    def _compute_confidence(
        self,
        evidence_rows: list[dict],
        contradiction_rows: list[dict],
        decay_alpha: float,
    ) -> ConfidenceComponents:
        """
        4-step confidence formula.
        Step 1: sum(w_i * source_weight_i) / sum(temporal_weight_i)
        NOTE: normalize by sum(temporal_weight) NOT len(active_evidence)
        """

        # Step 1: Support (normalized by sum of temporal weights)
        weighted_sum = sum(
            e["temporal_weight"] * e["source_weight"]
            for e in evidence_rows
        )
        temporal_weight_sum = sum(e["temporal_weight"] for e in evidence_rows)
        support = weighted_sum / max(temporal_weight_sum, 1e-9)  # Avoid division by zero
        support = min(support, 1.0)  # Clamp to [0, 1]

        # Step 2: Corroboration gain from distinct (source_type, source_name) pairs
        # Only count sources with temporal_weight >= CORROBORATION_MIN_TEMPORAL_WEIGHT
        distinct_sources = set(
            (e["source_type"], e["source_name"])
            for e in evidence_rows
            if e["temporal_weight"] >= settings.CORROBORATION_MIN_TEMPORAL_WEIGHT
        )
        corroboration_gain = min(
            len(distinct_sources) * 0.05,
            settings.MAX_CORROBORATION_GAIN,  # Capped at 0.20
        )

        # Step 3: Contradiction penalty (top-3 links, computed dynamically)
        # Sum strengths of top-3 contradictions, cap at 0.60
        top3_strength = sum(
            sorted([c["strength"] for c in contradiction_rows], reverse=True)[:3]
        )
        contradiction_penalty = min(top3_strength, settings.MAX_CONTRADICTION_PENALTY)  # Capped at 0.60

        # Step 4: Final confidence — CLAMP is MANDATORY
        final = support + corroboration_gain - contradiction_penalty
        final = max(0.0, min(1.0, final))  # clamp to [0.0, 1.0]

        return ConfidenceComponents(
            support=support,
            corroboration_gain=corroboration_gain,
            contradiction_penalty=contradiction_penalty,
            final=final,
        )

    async def _get_top3_contradictions(self, relation_id) -> list[dict]:
        result = await self.session.execute(
            text("""
                SELECT strength
                FROM relation_contradiction_links
                WHERE relation_id = :rel_id
                ORDER BY strength DESC
                LIMIT 3
            """),
            {"rel_id": str(relation_id)}
        )
        return [dict(row._mapping) for row in result]

    async def _get_decay_alpha(self, relation_id) -> float:
        """Fetch decay_alpha for this relation's type. TEMPORAL_CLAIM uses fixed 0.02310."""
        result = await self.session.execute(
            text("""
                SELECT rtr.decay_alpha, r.semantic_mode
                FROM relations r
                JOIN relation_type_registry rtr ON r.relation_type_id = rtr.id
                WHERE r.id = :rel_id
            """),
            {"rel_id": str(relation_id)}
        )
        row = result.fetchone()
        if not row:
            return 0.02310  # Default: 30-day half-life
        if row.semantic_mode == "TEMPORAL_CLAIM":
            return 0.02310  # Fixed for temporal claims (30-day half-life)
        return float(row.decay_alpha)
```

### T-S7-007: Block 13B — Contradiction Detection Batch Worker

```python
# services/knowledge-graph/src/knowledge_graph/application/workers/contradiction_batch.py
import structlog
from datetime import datetime, timezone, timedelta
from uuid import UUID
from sqlalchemy import text
from knowledge_graph.domain.models import Contradiction
from knowledge_graph.infrastructure.intelligence_db.repositories.contradiction_repository import ContradictionRepository
from knowledge_graph.infrastructure.intelligence_db.repositories.outbox_repository import OutboxRepository
from knowledge_graph.infrastructure.metrics import s7_contradictions_detected_total
from uuid import uuid4

logger = structlog.get_logger(__name__)

OPPOSITE_POLARITIES = {("positive", "negative"), ("negative", "positive")}
MAX_CLAIMS_PER_RUN = 1000

class ContradictionBatchWorker:
    def __init__(
        self,
        contradiction_repo: ContradictionRepository,
        outbox_repo: OutboxRepository,
        session,
    ) -> None:
        self.contradiction_repo = contradiction_repo
        self.outbox_repo = outbox_repo
        self.session = session

    async def run(self) -> None:
        """30-min batch scan for contradictions. Rate-limited to MAX_CLAIMS_PER_RUN."""
        logger.info("contradiction_batch_started")
        since = datetime.now(timezone.utc) - timedelta(days=90)

        # Fetch unprocessed claims using dedicated index
        result = await self.session.execute(
            text("""
                SELECT id, subject_entity_id, claim_type, polarity, confidence
                FROM claims
                WHERE processed_for_contradiction = false
                  AND polarity != 'neutral'
                  AND created_at >= :since
                ORDER BY created_at DESC
                LIMIT :limit
                FOR UPDATE SKIP LOCKED
            """),
            {"since": since, "limit": MAX_CLAIMS_PER_RUN}
        )
        claims = [dict(row._mapping) for row in result]
        logger.info("contradiction_batch_claims_loaded", count=len(claims))

        new_contradictions = 0
        for claim in claims:
            new_contradictions += await self._check_claim_for_contradictions(claim, since)

        # Mark claims as processed
        claim_ids = [str(c["id"]) for c in claims]
        if claim_ids:
            await self.session.execute(
                text("UPDATE claims SET processed_for_contradiction = true WHERE id = ANY(:ids)"),
                {"ids": claim_ids}
            )
            await self.session.commit()

        logger.info("contradiction_batch_complete",
                   claims_processed=len(claims), new_contradictions=new_contradictions)

    async def _check_claim_for_contradictions(self, claim: dict, since: datetime) -> int:
        """Check one claim against all recent same-subject, same-type claims."""
        result = await self.session.execute(
            text("""
                SELECT id, polarity, confidence
                FROM claims
                WHERE subject_entity_id = :subj
                  AND claim_type = :ctype
                  AND polarity != 'neutral'
                  AND created_at >= :since
                  AND id != :claim_id
            """),
            {
                "subj": claim["subject_entity_id"],
                "ctype": claim["claim_type"],
                "since": since,
                "claim_id": claim["id"],
            }
        )
        existing_claims = [dict(row._mapping) for row in result]
        new_count = 0

        for existing in existing_claims:
            if (claim["polarity"], existing["polarity"]) not in OPPOSITE_POLARITIES:
                continue
            if await self.contradiction_repo.exists(UUID(str(claim["id"])), UUID(str(existing["id"]))):
                continue

            strength = float(claim.get("confidence", 0.5)) * float(existing.get("confidence", 0.5))
            contradiction = Contradiction(
                id=uuid4(),
                subject_entity_id=UUID(str(claim["subject_entity_id"])),
                claim_type=claim["claim_type"],
                claim_a_id=UUID(str(claim["id"])),
                claim_b_id=UUID(str(existing["id"])),
                strength=strength,
            )
            async with self.session.begin():
                await self.contradiction_repo.insert(contradiction)
                await self.outbox_repo.insert(
                    event_type="intelligence.contradiction",
                    payload={
                        "contradiction_id": str(contradiction.id),
                        "subject_entity_id": str(contradiction.subject_entity_id),
                        "claim_type": contradiction.claim_type,
                        "strength": strength,
                    }
                )
            s7_contradictions_detected_total.inc()
            new_count += 1

        return new_count
```

### T-S7-008: Block 13C — Summary Generation Worker

```python
# services/knowledge-graph/src/knowledge_graph/application/workers/summary_generation.py
import hashlib
import json
import structlog
from sqlalchemy import text
from knowledge_graph.domain.models import RelationSummary
from knowledge_graph.infrastructure.intelligence_db.repositories.relation_summary_repository import RelationSummaryRepository
from knowledge_graph.infrastructure.intelligence_db.repositories.relation_repository import RelationRepository
from knowledge_graph.infrastructure.metrics import s7_summaries_generated_total
from uuid import uuid4

logger = structlog.get_logger(__name__)

class SummaryGenerationWorker:
    def __init__(
        self,
        summary_repo: RelationSummaryRepository,
        relation_repo: RelationRepository,
        extraction_client,  # ExtractionClient from libs/ml-clients
        session,
    ) -> None:
        self.summary_repo = summary_repo
        self.relation_repo = relation_repo
        self.extraction_client = extraction_client
        self.session = session

    async def run(self) -> None:
        """60-min: process up to 50 stale relation summaries."""
        stale_relations = await self.relation_repo.get_stale_summaries(limit=50)
        logger.info("summary_generation_started", relation_count=len(stale_relations))

        for relation in stale_relations:
            try:
                await self._generate_summary(relation)
            except Exception as e:
                logger.error("summary_generation_failed",
                           relation_id=str(relation["id"]), error=str(e))

    async def _generate_summary(self, relation: dict) -> None:
        relation_id = relation["id"]

        # Select top-10 evidence: temporal_weight DESC, source_weight DESC, evidence_date DESC
        result = await self.session.execute(
            text("""
                SELECT id, evidence_text, temporal_weight, source_weight, evidence_date
                FROM relation_evidence_raw
                WHERE relation_id = :rel_id
                ORDER BY temporal_weight DESC, source_weight DESC, evidence_date DESC
                LIMIT 10
            """),
            {"rel_id": str(relation_id)}
        )
        evidence_rows = [dict(row._mapping) for row in result]
        if not evidence_rows:
            return

        # Change detection via SHA-256 hash of sorted evidence IDs
        sorted_ids = sorted(str(e["id"]) for e in evidence_rows)
        evidence_hash = hashlib.sha256(json.dumps(sorted_ids).encode()).hexdigest()

        # Check if hash matches current summary — skip if unchanged
        current_summary = await self.session.execute(
            text("SELECT evidence_hash FROM relation_summaries WHERE relation_id = :id AND is_current = true"),
            {"id": str(relation_id)}
        )
        current_row = current_summary.fetchone()
        if current_row and current_row.evidence_hash == evidence_hash:
            # Evidence unchanged — mark relation as not stale and skip
            await self.relation_repo.mark_summary_fresh(relation_id)
            await self.session.commit()
            return

        # Fetch versioned prompt template
        prompt_template = await self._fetch_prompt_template()
        if not prompt_template:
            logger.warning("summary_no_prompt_template", relation_id=str(relation_id))
            return

        # Build context from top-10 evidence texts
        context = "\n\n".join(e["evidence_text"] for e in evidence_rows)
        rendered_prompt = prompt_template.format(context=context)

        # Call ExtractionClient (via libs/ml-clients protocol)
        raw_summary = await self._safe_extract(rendered_prompt, context)
        if not raw_summary:
            return  # Leave stale — will retry next run

        # Set old summaries as not current, insert new
        await self.summary_repo.set_not_current(relation_id)
        new_summary = RelationSummary(
            id=uuid4(),
            relation_id=relation_id,
            summary_text=raw_summary,
            is_current=True,
            evidence_hash=evidence_hash,
        )
        await self.summary_repo.insert(new_summary)
        await self.relation_repo.mark_summary_fresh(relation_id)
        await self.session.commit()
        s7_summaries_generated_total.inc()
        logger.info("summary_generated", relation_id=str(relation_id))

    async def _fetch_prompt_template(self) -> str | None:
        try:
            result = await self.session.execute(
                text("SELECT template_text FROM prompt_templates WHERE service = 's7_summary' ORDER BY version DESC LIMIT 1")
            )
            row = result.fetchone()
            return row.template_text if row else None
        except Exception:
            return None

    async def _safe_extract(self, prompt: str, context: str) -> str | None:
        try:
            return await self.extraction_client.extract(prompt=prompt, context=context)
        except Exception as e:
            logger.error("summary_extraction_failed", error=str(e))
            return None
```

### T-S7-009: Block 13D — Entity Profile Embedding Refresh Worker

```python
# services/knowledge-graph/src/knowledge_graph/application/workers/entity_profile_embedding.py
import structlog
from aiokafka import AIOKafkaConsumer
from knowledge_graph.config import settings
from knowledge_graph.infrastructure.metrics import s7_embeddings_refreshed_total

logger = structlog.get_logger(__name__)

ALIAS_TYPE_PRIORITY = {"TICKER": 0, "ISIN": 1, "EXACT": 2, "FUZZY": 3}

class EntityProfileEmbeddingWorker:
    def __init__(
        self,
        embedding_client,  # EmbeddingClient from libs/ml-clients
        valkey_client,
        session,
    ) -> None:
        self.embedding_client = embedding_client
        self.valkey = valkey_client
        self.session = session

    async def run(self) -> None:
        """
        60-min: consume entity.dirtied.v1 compacted topic.
        Dedup via Valkey 30-min TTL lock.
        """
        consumer = AIOKafkaConsumer(
            settings.KAFKA_ENTITY_DIRTIED_TOPIC,
            bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
            group_id="s7-entity-refresh-group",
            enable_auto_commit=True,  # Compacted topic; auto-commit acceptable
            auto_offset_reset="latest",  # Start from latest on each run
        )
        await consumer.start()
        try:
            # Process available messages (poll once per scheduler run)
            from aiokafka.errors import KafkaError
            import asyncio
            deadline = asyncio.get_event_loop().time() + 55  # Leave 5s before next run

            while asyncio.get_event_loop().time() < deadline:
                msgs = await consumer.getmany(timeout_ms=1000, max_records=100)
                if not msgs:
                    break
                for tp, messages in msgs.items():
                    for msg in messages:
                        import json
                        payload = json.loads(msg.value.decode())
                        entity_id = payload.get("entity_id")
                        if entity_id:
                            await self._refresh_entity(entity_id)
        finally:
            await consumer.stop()

    async def _refresh_entity(self, entity_id: str) -> None:
        """Refresh entity profile embedding with Valkey dedup."""
        lock_key = f"entity_refresh_lock:{entity_id}"

        # SET NX (atomic check-and-set) with 30-min TTL
        acquired = await self.valkey.set(
            lock_key, "1",
            nx=True,  # Only set if not exists
            ex=settings.ENTITY_REFRESH_LOCK_TTL_SECONDS,  # 1800 seconds = 30 min
        )
        if not acquired:
            logger.debug("entity_refresh_skipped_lock_held", entity_id=entity_id)
            return

        try:
            profile_text = await self._build_profile_text(entity_id)
            if not profile_text:
                return

            # Truncate at 512 tokens (char/4 approximation)
            max_chars = 512 * 4
            if len(profile_text) > max_chars:
                profile_text = profile_text[:max_chars]

            embeddings = await self.embedding_client.embed([profile_text])
            if not embeddings:
                return

            embedding = embeddings[0]

            # Upsert entity_profile_embeddings
            # expires_at = NULL on active embeddings (expired ones STAY in table — never delete)
            from sqlalchemy import text
            await self.session.execute(
                text("""
                    INSERT INTO entity_profile_embeddings
                        (entity_id, embedding, profile_text, embedded_at, expires_at)
                    VALUES
                        (:entity_id, :embedding::vector, :profile_text, NOW(), NULL)
                    ON CONFLICT (entity_id) DO UPDATE SET
                        embedding = EXCLUDED.embedding,
                        profile_text = EXCLUDED.profile_text,
                        embedded_at = NOW(),
                        expires_at = NULL
                """),
                {
                    "entity_id": entity_id,
                    "embedding": str(embedding),
                    "profile_text": profile_text,
                }
            )
            await self.session.commit()
            s7_embeddings_refreshed_total.labels(worker="entity_profile").inc()
            logger.info("entity_profile_refreshed", entity_id=entity_id)
        except Exception as e:
            logger.error("entity_profile_refresh_failed", entity_id=entity_id, error=str(e))

    async def _build_profile_text(self, entity_id: str) -> str | None:
        """
        5-field deterministic profile text template.
        Fields: canonical_name, entity_type, top-5 aliases (TICKER>ISIN>EXACT>FUZZY),
                top-5 RELATION_STATE relations (confidence DESC),
                top-3 claims (created_at DESC)
        """
        from sqlalchemy import text

        # Field 1+2: canonical name and type
        entity_result = await self.session.execute(
            text("SELECT canonical_name, entity_type FROM canonical_entities WHERE id = :id"),
            {"id": entity_id}
        )
        entity = entity_result.fetchone()
        if not entity:
            return None

        # Field 3: top-5 aliases by priority
        alias_result = await self.session.execute(
            text("""
                SELECT alias, alias_type
                FROM entity_aliases
                WHERE entity_id = :id
                ORDER BY
                    CASE alias_type
                        WHEN 'TICKER' THEN 0
                        WHEN 'ISIN' THEN 1
                        WHEN 'EXACT' THEN 2
                        WHEN 'FUZZY' THEN 3
                        ELSE 4
                    END
                LIMIT 5
            """),
            {"id": entity_id}
        )
        aliases = [row.alias for row in alias_result]

        # Field 4: top-5 RELATION_STATE relations by confidence DESC
        relation_result = await self.session.execute(
            text("""
                SELECT r.confidence, rtr.relation_type_str, ce.canonical_name AS object_name
                FROM relations r
                JOIN relation_type_registry rtr ON r.relation_type_id = rtr.id
                JOIN canonical_entities ce ON r.object_entity_id = ce.id
                WHERE r.subject_entity_id = :id
                  AND r.semantic_mode = 'RELATION_STATE'
                ORDER BY r.confidence DESC
                LIMIT 5
            """),
            {"id": entity_id}
        )
        relations = [f"{row.relation_type_str}({row.object_name}, conf={row.confidence:.2f})"
                    for row in relation_result]

        # Field 5: top-3 claims by created_at DESC
        claims_result = await self.session.execute(
            text("""
                SELECT claim_type, polarity, confidence
                FROM claims
                WHERE subject_entity_id = :id
                ORDER BY created_at DESC
                LIMIT 3
            """),
            {"id": entity_id}
        )
        claims = [f"{row.claim_type}:{row.polarity}({row.confidence:.2f})"
                 for row in claims_result]

        # Assemble deterministic template
        profile_parts = [
            f"Entity: {entity.canonical_name}",
            f"Type: {entity.entity_type}",
            f"Aliases: {', '.join(aliases) if aliases else 'none'}",
            f"Relations: {'; '.join(relations) if relations else 'none'}",
            f"Recent claims: {'; '.join(claims) if claims else 'none'}",
        ]
        return "\n".join(profile_parts)
```

---

## Constraints

- T-S7-006 (confidence formula): normalization MUST be by `sum(temporal_weight)` not `len(active_evidence)` — add comment on this line
- T-S7-006: `clamp(final, 0.0, 1.0)` is MANDATORY — no exceptions
- T-S7-006: corroboration_gain capped at 0.20; contradiction_penalty capped at 0.60
- T-S7-006: TEMPORAL_CLAIM semantic mode uses fixed `decay_alpha=0.02310` regardless of relation_type_registry value
- T-S7-007: rate limit to MAX_CLAIMS_PER_RUN=1000 per run; use `idx_claims_contradiction_detection` index
- T-S7-007: batch logic must match hot-path logic exactly (subject-based, opposite polarity, both non-neutral)
- T-S7-009: Valkey SET NX (atomic) with 30-min TTL — never use GET + SET (race condition)
- T-S7-009: entity profile text template MUST be deterministic (same inputs → same output)
- T-S7-009: expired embeddings STAY in table — never DELETE on expiry; set `expires_at=NULL` on refresh
- All workers: catch all exceptions per-item, log, continue — never crash the worker
- ExtractionClient and EmbeddingClient MUST be used via libs/ml-clients protocol
- **`common.ids.new_uuid7()` mandatory** — all entity, section, chunk, relation, and outbox primary keys must use `common.ids.new_uuid7()`. Never call `common.ids.new_uuid7()` directly in service code.
- **`common.time.utc_now()` mandatory** — all timestamp generation uses `common.time.utc_now()`. Never call `datetime.now(UTC)` or `datetime.utcnow()` directly in service code.
- **`common.types` for cross-service IDs** — use `EntityId` (from `common.types`) for canonical entity references across S6, S7; use `DocumentId` for document references; use `MinIOKey` for MinIO key strings.
- **`EntityId` for cross-service entity references**: S7 graph writes use `common.types.EntityId` for `subject_entity_id`, `object_entity_id`, and `entity_id` columns.

---

## Scope & token budget

**Write paths:**
```
services/knowledge-graph/src/knowledge_graph/application/workers/confidence_recomputation.py
services/knowledge-graph/src/knowledge_graph/application/workers/contradiction_batch.py
services/knowledge-graph/src/knowledge_graph/application/workers/summary_generation.py
services/knowledge-graph/src/knowledge_graph/application/workers/entity_profile_embedding.py
services/knowledge-graph/tests/unit/workers/test_confidence_recomputation.py
services/knowledge-graph/tests/unit/workers/test_contradiction_batch.py
services/knowledge-graph/tests/unit/workers/test_summary_generation.py
services/knowledge-graph/tests/unit/workers/test_entity_profile_embedding.py
```

**Max exploration:** Wave 06 repos, Wave 07 scheduler, `docs/libs/ml-clients.md`. Do not read S6/S10.

**Stop condition:** All 4 workers implemented, unit tests pass, ruff+mypy pass.

---

## Required tests

```bash
cd services/knowledge-graph && pytest tests/unit/workers/ -v
ruff check services/knowledge-graph/src/knowledge_graph/application/workers/
mypy services/knowledge-graph/src/knowledge_graph/application/workers/
```

**Pass criteria:**
- `test_confidence_normalizes_by_sum_temporal_weight`: 3 evidence rows with different temporal_weights → support = sum(w*s)/sum(w)
- `test_confidence_corroboration_capped_at_0_20`: 10 distinct sources → corroboration_gain = 0.20 (not 0.50)
- `test_confidence_contradiction_penalty_capped_at_0_60`: 5 contradictions with strength 0.9 each → penalty = 0.60
- `test_confidence_final_always_in_0_1`: extreme inputs → final ∈ [0.0, 1.0]
- `test_confidence_temporal_claim_uses_fixed_decay`: TEMPORAL_CLAIM relation → decay_alpha = 0.02310
- `test_contradiction_batch_respects_rate_limit`: >1000 claims in DB → only 1000 processed per run
- `test_summary_hash_unchanged_skips_llm`: same evidence hash → extraction_client not called
- `test_entity_profile_valkey_lock_prevents_duplicate_refresh`: SET NX already set → refresh skipped
- `test_entity_profile_expired_embeddings_not_deleted`: expired embedding stays in table after refresh
- `test_entity_profile_template_deterministic`: same entity → same profile_text output

---

## Incremental quality gates (mandatory)

1. **T-S7-006:**
   ```bash
   pytest tests/unit/workers/test_confidence_recomputation.py -v
   ruff check src/knowledge_graph/application/workers/confidence_recomputation.py
   mypy src/knowledge_graph/application/workers/confidence_recomputation.py
   ```

2. **T-S7-007:**
   ```bash
   pytest tests/unit/workers/test_contradiction_batch.py -v
   ruff check src/knowledge_graph/application/workers/contradiction_batch.py
   mypy src/knowledge_graph/application/workers/contradiction_batch.py
   ```

3. **T-S7-008:**
   ```bash
   pytest tests/unit/workers/test_summary_generation.py -v
   ruff check src/knowledge_graph/application/workers/summary_generation.py
   mypy src/knowledge_graph/application/workers/summary_generation.py
   ```

4. **T-S7-009:**
   ```bash
   pytest tests/unit/workers/test_entity_profile_embedding.py -v
   ruff check src/knowledge_graph/application/workers/entity_profile_embedding.py
   mypy src/knowledge_graph/application/workers/entity_profile_embedding.py
   ```

No deferred fixes.

---

## Documentation requirements

| File | Update | Action |
|------|--------|--------|
| `docs/services/knowledge-graph.md` | Confidence formula | Add 4-step formula table with exact calculation per step |
| `docs/services/knowledge-graph.md` | Worker schedule | Add worker interval table (name, interval, trigger) |
| `docs/libs/ml-clients.md` | S7 usage | Add note on ExtractionClient usage in summary worker if not already present |

**Confidence formula documentation (exact, must match code):**
```
Step 1 (support): sum(temporal_weight_i × source_weight_i) / sum(temporal_weight_i)
  - Normalization denominator: sum(temporal_weight) NOT len(evidence)
  - RELATION_STATE: temporal_weight uses relation_type_registry.decay_alpha
  - TEMPORAL_CLAIM: temporal_weight uses fixed decay_alpha=0.02310 (30-day half-life)

Step 2 (corroboration_gain): min(distinct_high_weight_sources × 0.05, 0.20)
  - "high weight" = temporal_weight >= 0.1 (CORROBORATION_MIN_TEMPORAL_WEIGHT)
  - Capped at 0.20

Step 3 (contradiction_penalty): min(top3_contradiction_strengths_sum, 0.60)
  - Only top-3 contradiction links by strength
  - Capped at 0.60

Step 4 (final): clamp(support + corroboration_gain - contradiction_penalty, 0.0, 1.0)
  - MANDATORY clamp — never skip
```

---

## Required handoff evidence

### Validation ledger

| Command | Scope | Exit code | Result |
|---------|-------|-----------|--------|
| `pytest tests/unit/workers/test_confidence_recomputation.py::test_confidence_normalizes_by_sum_temporal_weight` | T-S7-006 formula | 0 | Pass |
| `pytest tests/unit/workers/test_confidence_recomputation.py::test_confidence_final_always_in_0_1` | T-S7-006 clamp | 0 | Pass |
| `pytest tests/unit/workers/test_contradiction_batch.py::test_contradiction_batch_respects_rate_limit` | T-S7-007 | 0 | Pass |
| `pytest tests/unit/workers/test_summary_generation.py::test_summary_hash_unchanged_skips_llm` | T-S7-008 | 0 | Pass |
| `pytest tests/unit/workers/test_entity_profile_embedding.py::test_entity_profile_valkey_lock_prevents_duplicate_refresh` | T-S7-009 | 0 | Pass |
| `pytest tests/unit/workers/ -v` | All wave 08 | 0 | All pass |
| `ruff check src/knowledge_graph/application/workers/` | Wave 08 code | 0 | No violations |
| `mypy src/knowledge_graph/application/workers/` | Wave 08 code | 0 | No errors |

### Commit message
```
feat(s7): implement workers 13A-D — confidence, contradiction batch, summaries, entity embeddings

Add 4 APScheduler workers: confidence recomputation (4-step formula, sum-normalized,
clamped), contradiction batch scanner (1000-claim rate limit, subject-based), summary
generation (evidence-hash change detection, ExtractionClient), and entity profile
embedding refresh (Valkey SET NX dedup, 5-field deterministic template, expired
embeddings preserved).
```

---

## Definition of done

- [ ] Confidence: normalization by sum(temporal_weight) — add code comment on this line
- [ ] Confidence: clamp(final, 0.0, 1.0) mandatory
- [ ] Confidence: corroboration capped at 0.20; contradiction capped at 0.60
- [ ] Confidence: TEMPORAL_CLAIM uses fixed 0.02310
- [ ] Contradiction batch: rate-limited to 1000 claims/run; uses FOR UPDATE SKIP LOCKED
- [ ] Summary: evidence hash change detection prevents redundant LLM calls
- [ ] Summary: old summaries set is_current=false before new insert
- [ ] Entity profile: Valkey SET NX (atomic) with 30-min TTL
- [ ] Entity profile: 5-field deterministic template
- [ ] Entity profile: expired embeddings stay in table (expires_at=NULL on active)
- [ ] All unit tests pass
- [ ] ruff exits 0; mypy exits 0
- [ ] `docs/services/knowledge-graph.md` updated with confidence formula table and worker schedule table
