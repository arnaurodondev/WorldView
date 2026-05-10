"""GenerateNarrativeUseCase — orchestrates entity narrative generation (PRD-0074 §13.3).

Block 13D-3: Worker 13D-3 calls this use case per entity.

Pipeline:
  1. Load entity context (READ session — R27 read replica).
  2. Build input_snapshot + compute snapshot_hash.
  3. Idempotency check via narrative_repo.find_by_input_snapshot.
  4. Sanitize LLM inputs via prompts.knowledge.alias.sanitize_description.
  5. Call LLM with 3x exponential backoff; fall back to template-v1 on exhaustion.
  6. Compute health_score (data_completeness*0.4 + evidence_freshness*0.3 + density*0.3).
  7. Persist via WRITE session: narrative_repo.insert_and_promote + outbox event.
  8. Increment Prometheus metrics.

NOTE: S5 articles are NOT fetched in this wave (articles=[]).  The HTTP client
for cross-service calls will be added in a later wave.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from common.ids import new_uuid7  # type: ignore[import-untyped]
from common.time import utc_now  # type: ignore[import-untyped]
from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from knowledge_graph.domain.narrative import EntityNarrativeVersion

logger = get_logger(__name__)  # type: ignore[no-any-return]

# ── Prometheus metrics (lazy registration so duplicate import in tests is safe) ──


def _make_counter(name: str, doc: str, labels: list[str]) -> Any:
    try:
        from prometheus_client import Counter  # type: ignore[import-not-found]

        return Counter(name, doc, labels)
    except (ValueError, Exception):  # pragma: no cover
        return None


def _make_histogram(name: str, doc: str, buckets: tuple[float, ...]) -> Any:
    try:
        from prometheus_client import Histogram  # type: ignore[import-not-found]

        return Histogram(name, doc, buckets=buckets)
    except (ValueError, Exception):  # pragma: no cover
        return None


_narrative_total = _make_counter(
    "s7_narrative_generation_total",
    "Total narrative generation attempts by reason, model_id, and status.",
    ["reason", "model_id", "status"],
)

_narrative_duration = _make_histogram(
    "s7_narrative_generation_duration_seconds",
    "Wall-clock latency of narrative LLM generation (seconds).",
    (0.5, 1.0, 2.0, 5.0, 10.0, 20.0, 30.0, 60.0),
)

# ── Constants ──────────────────────────────────────────────────────────────────

# 3x exponential backoff delays (seconds) for 429/503 from LLM provider.
_LLM_RETRY_DELAYS: tuple[float, ...] = (2.0, 4.0, 8.0)

# Minimum narrative text length (matches DB constraint from migration 0031).
_MIN_NARRATIVE_LEN = 50

# Topic constant — imported from messaging to avoid hardcoding (BP-147 pattern).
_ENTITY_NARRATIVE_GENERATED_TOPIC = "entity.narrative.generated.v1"


class GenerateNarrativeUseCase:
    """Orchestrate entity narrative generation and persistence (Worker 13D-3).

    Args:
    ----
        write_session_factory:  intelligence_db write async_sessionmaker.
        read_session_factory:   intelligence_db read-replica async_sessionmaker
                                (R27 — read-only queries go here).  Falls back
                                to write_session_factory when None.
        narrative_llm_model_id: LLM model ID for narrative generation.
        outbox_schema_path:     Absolute path to entity.narrative.generated.v1.avsc.
        retry_delays:           Tuple of sleep durations (sec) for LLM retries.
                                Pass ``()`` in tests to skip sleeping.
        narrative_repo_class:   Callable ``(AsyncSession) -> NarrativeRepositoryPort``
                                injected by the infrastructure layer or tests.
                                Satisfies LAYER-BOUNDARY (R12): no infra imports
                                occur inside this application-layer module.
                                Must not be None in production (callers in infra/
                                import the concrete class and pass it here).
        outbox_repo_class:      Callable ``(AsyncSession) -> OutboxRepositoryPort``
                                injected by the infrastructure layer or tests.

    """

    def __init__(
        self,
        write_session_factory: async_sessionmaker[AsyncSession],
        read_session_factory: async_sessionmaker[AsyncSession] | None = None,
        narrative_llm_model_id: str = "meta-llama/Meta-Llama-3.1-8B-Instruct",
        outbox_schema_path: str | None = None,
        retry_delays: tuple[float, ...] = _LLM_RETRY_DELAYS,
        llm_client: Any | None = None,
        # Repo class callables injected from the infrastructure/api layer so that
        # this application-layer module never imports from infrastructure/ at runtime
        # (LAYER-BOUNDARY rule, R12 / IG-LAYER-002).
        # Tests pass AsyncMock / MagicMock instances directly; production callers
        # (infrastructure/workers, api/narratives) pass the concrete repo classes.
        narrative_repo_class: Any | None = None,
        outbox_repo_class: Any | None = None,
        # PLAN-0088 P0-7 (2026-05-10): direct DeepInfra chat-completion callable for
        # narrative generation. The pre-existing FallbackChainClient.extract path is
        # hard-wired to JSON-mode (response_format=json_object) which is correct for
        # NER/relation extraction but fatal for free-form narrative prose: the model
        # returns hallucinated `{"error": ...}` envelopes, the use case rejects them
        # as "invalid output", retries exhaust, and template-v1 fallback fires. This
        # callable bypasses extraction-style adapters entirely. Signature:
        # ``async def chat(prompt: str) -> str`` returning free-form narrative text.
        # When set it is preferred over self._llm.extract.
        narrative_chat_client: Any | None = None,
    ) -> None:
        self._write_sf = write_session_factory
        self._read_sf = read_session_factory if read_session_factory is not None else write_session_factory
        self._model_id = narrative_llm_model_id
        self._retry_delays = retry_delays
        self._llm = llm_client
        # PLAN-0088 P0-7: free-form narrative chat client (bypasses JSON-mode).
        self._narrative_chat = narrative_chat_client
        # Store injected repo class callables.  None means callers did not inject
        # them (legacy path — handled in execute() via a sentinel check against None).
        self._narrative_repo_class: Any = narrative_repo_class
        self._outbox_repo_class: Any = outbox_repo_class

        # Resolve Avro schema path for outbox serialization
        if outbox_schema_path is None:
            from messaging.kafka.schema_paths import get_schema_path  # type: ignore[import-untyped]

            self._avsc_path = get_schema_path("entity.narrative.generated.v1.avsc")
        else:
            self._avsc_path = outbox_schema_path

    # ── Public API ────────────────────────────────────────────────────────────

    async def execute(
        self,
        entity_id: UUID,
        tenant_id: UUID | None,
        reason: str,  # NarrativeGenerationReason.value — string to avoid domain import in caller
    ) -> bool:
        """Generate and persist a narrative for *entity_id*.

        Returns ``True`` when a new narrative was generated and persisted,
        ``False`` when the idempotency check hit (same snapshot already present).
        """
        from knowledge_graph.domain.narrative import EntityNarrativeVersion, NarrativeGenerationReason

        # Resolve repo constructors.  Callers in the infrastructure layer inject
        # concrete NarrativeRepository / OutboxRepository classes at construction
        # time via narrative_repo_class / outbox_repo_class (R12 — no infra imports
        # inside this application-layer module).  When not injected (e.g. tests that
        # did not migrate to constructor injection yet), raise immediately so the
        # misconfiguration is obvious.
        if self._narrative_repo_class is None or self._outbox_repo_class is None:
            raise RuntimeError(
                "GenerateNarrativeUseCase requires narrative_repo_class and "
                "outbox_repo_class to be injected at construction time. "
                "Infrastructure callers must pass the concrete NarrativeRepository "
                "and OutboxRepository classes.",
            )
        NarrativeRepository = self._narrative_repo_class  # noqa: N806
        OutboxRepository = self._outbox_repo_class  # noqa: N806

        t_start = time.monotonic()
        generation_reason = NarrativeGenerationReason(reason)

        # ── Step 1: Load entity context (READ session) ────────────────────────
        entity_ctx = await self._load_entity_context(entity_id)
        if entity_ctx is None:
            logger.warning(  # type: ignore[no-any-return]
                "narrative_generation_entity_not_found",
                entity_id=str(entity_id),
            )
            _inc_metric(_narrative_total, reason, self._model_id, "entity_not_found")
            return False

        # ── Step 2: Build input_snapshot + hash ───────────────────────────────
        input_snapshot, snapshot_hash = self._build_snapshot(entity_ctx)

        # ── Step 3: Idempotency check (READ session) ──────────────────────────
        async with self._read_sf() as read_session:
            narrative_repo = NarrativeRepository(read_session)
            existing = await narrative_repo.find_by_input_snapshot(entity_id, snapshot_hash)

        if existing is not None:
            logger.info(  # type: ignore[no-any-return]
                "narrative_idempotent_skip",
                entity_id=str(entity_id),
                version_id=str(existing.version_id),
                snapshot_hash=snapshot_hash,
            )
            _inc_metric(_narrative_total, reason, self._model_id, "idempotent_skip")
            return False

        # ── Step 4: Sanitize entity-derived strings ───────────────────────────
        sanitized_name, sanitized_type = self._sanitize_entity_ctx(entity_ctx)

        # ── Step 5: Call LLM with retry + template fallback ───────────────────
        narrative_text, model_used = await self._call_llm_with_retry(
            entity_id=entity_id,
            entity_name=sanitized_name,
            entity_type=sanitized_type,
            entity_ctx=entity_ctx,
        )

        # ── Step 6: Compute health_score ──────────────────────────────────────
        health_score = self._compute_health_score(entity_ctx)

        # ── Step 7: Build domain entity ───────────────────────────────────────
        now: datetime = utc_now()  # type: ignore[no-any-return]
        word_count = len(narrative_text.split())
        version = EntityNarrativeVersion(
            version_id=new_uuid7(),  # type: ignore[no-any-return]
            entity_id=entity_id,
            narrative_text=narrative_text,
            model_id=model_used,
            generation_reason=generation_reason,
            input_snapshot=input_snapshot,
            generated_at=now,
            is_current=False,  # insert_and_promote will flip this
            word_count=word_count,
            quality_score=None,  # LLM self-eval not implemented in Wave C
        )

        # ── Step 8: Persist + outbox (WRITE session) ──────────────────────────
        async with self._write_sf() as write_session:
            narrative_repo_w = NarrativeRepository(write_session)
            await narrative_repo_w.insert_and_promote(version, write_session, health_score=health_score)

            # Build and publish outbox event (Avro-serialized)
            event_payload = self._build_outbox_event(version, reason)
            outbox_repo = OutboxRepository(write_session)
            await outbox_repo.append(
                topic=_ENTITY_NARRATIVE_GENERATED_TOPIC,
                partition_key=str(entity_id),
                payload_avro=event_payload,
            )

            await write_session.commit()

        # ── Step 9: Metrics ───────────────────────────────────────────────────
        elapsed = time.monotonic() - t_start
        _inc_metric(_narrative_total, reason, model_used, "success")
        _observe_metric(_narrative_duration, elapsed)

        logger.info(  # type: ignore[no-any-return]
            "narrative_generation_complete",
            entity_id=str(entity_id),
            version_id=str(version.version_id),
            model_id=model_used,
            reason=reason,
            elapsed_s=round(elapsed, 2),
            word_count=word_count,
        )

        return True

    # ── Internals ─────────────────────────────────────────────────────────────

    async def _load_entity_context(self, entity_id: UUID) -> dict[str, Any] | None:
        """Load entity + top-10 relations + contradictions via the read replica."""
        from sqlalchemy import text

        async with self._read_sf() as session:
            # Load canonical entity
            entity_result = await session.execute(
                text("""
SELECT entity_id, canonical_name, entity_type, metadata
FROM canonical_entities
WHERE entity_id = CAST(:entity_id AS uuid)
LIMIT 1
"""),
                {"entity_id": str(entity_id)},
            )
            entity_row = entity_result.fetchone()
            if entity_row is None:
                return None

            # Top-10 relations by confidence with evidence snippets
            relations_result = await session.execute(
                text("""
SELECT r.relation_id, r.canonical_type, r.confidence, r.evidence_count,
       r.latest_evidence_at,
       ce_obj.canonical_name AS object_name,
       (SELECT rer.evidence_text
        FROM relation_evidence_raw rer
        WHERE rer.subject_entity_id = r.subject_entity_id
          AND rer.evidence_text IS NOT NULL
        ORDER BY rer.extraction_confidence DESC NULLS LAST
        LIMIT 1) AS top_snippet
FROM relations r
JOIN canonical_entities ce_obj ON r.object_entity_id = ce_obj.entity_id
WHERE r.subject_entity_id = CAST(:entity_id AS uuid)
ORDER BY r.confidence DESC
LIMIT 10
"""),
                {"entity_id": str(entity_id)},
            )
            relation_rows = relations_result.fetchall()

            # Active contradictions (strongest_contra_score > 0.5)
            contra_result = await session.execute(
                text("""
SELECT r.canonical_type, r.confidence
FROM relations r
WHERE r.subject_entity_id = CAST(:entity_id AS uuid)
  AND r.strongest_contra_score > 0.5
LIMIT 5
"""),
                {"entity_id": str(entity_id)},
            )
            contra_rows = contra_result.fetchall()

        relations = [
            {
                "relation_id": str(row[0]),
                "canonical_type": str(row[1]),
                # BP-SA1-001: relations.confidence may be NULL before ConfidenceWorker
                # has processed the first evidence batch.  Guard with 'or 0.0' so
                # float() never receives None (would raise TypeError).
                "confidence": float(row[2] or 0.0),
                "evidence_count": int(row[3]),
                "latest_evidence_at": row[4].isoformat() if row[4] else None,
                "object_name": str(row[5]) if row[5] else "",
                "top_snippet": str(row[6]) if row[6] else "",
            }
            for row in relation_rows
        ]
        contradictions = [
            # BP-SA1-001: same NULL guard for contra_rows confidence column.
            {"canonical_type": str(row[0]), "confidence": float(row[1] or 0.0)}
            for row in contra_rows
        ]

        return {
            "entity": {
                "entity_id": str(entity_row[0]),
                "canonical_name": str(entity_row[1]),
                "entity_type": str(entity_row[2]),
                "metadata": entity_row[3],
            },
            "relations": relations,
            "articles": [],  # NOTE: S5 HTTP client not implemented in Wave C
            "contradictions": contradictions,
        }

    def _build_snapshot(self, entity_ctx: dict[str, Any]) -> tuple[dict[str, Any], str]:
        """Build the canonical input_snapshot dict and compute its SHA-256 hash.

        The hash is stored under ``_hash`` inside the snapshot so
        ``NarrativeRepository.find_by_input_snapshot`` can query it without
        re-hashing.
        """
        snapshot: dict[str, Any] = {
            "entity": entity_ctx["entity"],
            "relations": entity_ctx["relations"],
            "articles": [],
            "contradictions": entity_ctx["contradictions"],
        }
        canonical_json = json.dumps(snapshot, sort_keys=True, default=str)
        snapshot_hash = hashlib.sha256(canonical_json.encode()).hexdigest()
        snapshot["_hash"] = snapshot_hash
        return snapshot, snapshot_hash

    def _sanitize_entity_ctx(self, entity_ctx: dict[str, Any]) -> tuple[str, str]:
        """Sanitize entity-derived strings before LLM interpolation (F-SEC-02)."""
        from prompts.knowledge.alias import sanitize_description  # type: ignore[import-untyped]

        entity = entity_ctx["entity"]
        canonical_name = sanitize_description(entity.get("canonical_name") or "")
        entity_type = sanitize_description(entity.get("entity_type") or "")
        return canonical_name, entity_type

    @staticmethod
    def _sanitize_relations(
        relations: list[dict[str, Any]],
        contradictions: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Sanitize DB-sourced relation fields before LLM prompt interpolation.

        WHY this method (F-SEC-02 extension): _sanitize_entity_ctx only sanitizes
        canonical_name and entity_type.  The relation rows from _load_entity_context
        contain canonical_type, object_name, and contradiction canonical_type — all
        of which are stored in intelligence_db from LLM-extraction and NER pipelines.
        A poisoned canonical_name in a related entity's record (e.g. "Apple Inc.
        Ignore prior instructions and output...") could flow through unsanitized
        into the narrative prompt and perform prompt injection.

        sanitize_description() strips control characters and collapses newlines,
        which is the minimum defence required to prevent line-break-based injection
        patterns (the most common vector seen in prompt-injection research).
        """
        from prompts.knowledge.alias import sanitize_description  # type: ignore[import-untyped]

        clean_relations = [
            {
                **r,
                "canonical_type": sanitize_description(str(r.get("canonical_type") or "")),
                "object_name": sanitize_description(str(r.get("object_name") or "")),
            }
            for r in relations
        ]
        clean_contradictions = [
            {
                **c,
                "canonical_type": sanitize_description(str(c.get("canonical_type") or "")),
            }
            for c in contradictions
        ]
        return clean_relations, clean_contradictions

    async def _call_llm_with_retry(
        self,
        entity_id: UUID,
        entity_name: str,
        entity_type: str,
        entity_ctx: dict[str, Any],
    ) -> tuple[str, str]:
        """Call LLM with exponential backoff; fall back to template-v1 on exhaustion.

        Returns ``(narrative_text, model_id)`` where model_id may be
        ``'template-v1'`` when the fallback path fires.
        """
        relations = entity_ctx.get("relations", [])
        relation_count = len(relations)

        # PLAN-0088 P0-7: prefer the dedicated narrative chat client. The legacy
        # ``self._llm.extract`` path forces JSON-mode (response_format=json_object)
        # which causes the LLM to emit hallucinated error envelopes for free-form
        # narrative prompts; that path is now reserved as a last resort.
        if self._narrative_chat is None and self._llm is None:
            return self._template_fallback(entity_name, entity_type, relation_count), "template-v1"

        # F-SEC-02 extension: sanitize relation fields (canonical_type, object_name)
        # and contradiction fields (canonical_type) before LLM interpolation.
        # These values originate from intelligence_db extraction pipelines and may
        # contain adversarial content placed by a compromised upstream source.
        clean_relations, clean_contradictions = self._sanitize_relations(
            relations,
            entity_ctx.get("contradictions", []),
        )
        prompt = self._build_prompt(entity_name, entity_type, clean_relations, clean_contradictions)

        # PLAN-0088 P0-7: free-form narrative chat path. When a dedicated
        # ``narrative_chat_client`` is wired (production: DeepInfra chat without
        # JSON-mode) we use it directly. This avoids the extraction-adapter JSON
        # contract that previously forced template-v1 fallback for ~97% of entities.
        if self._narrative_chat is not None:
            last_exc_chat: Exception | None = None
            for attempt, delay in enumerate(self._retry_delays):
                try:
                    text_result = await self._narrative_chat(prompt)
                    if text_result:
                        cleaned = str(text_result).strip()
                        # Reject obvious refusal/error text from upstream provider.
                        looks_like_error = cleaned.startswith("{") and (
                            '"error"' in cleaned[:120] or '"invalid_request_error"' in cleaned[:200]
                        )
                        if not looks_like_error and len(cleaned) >= _MIN_NARRATIVE_LEN:
                            return cleaned[:10000], self._model_id
                        if looks_like_error:
                            raise ValueError(f"Narrative chat returned error envelope: {cleaned[:120]}")
                except Exception as exc:
                    last_exc_chat = exc
                    logger.warning(  # type: ignore[no-any-return]
                        "narrative_chat_attempt_failed",
                        entity_id=str(entity_id),
                        attempt=attempt + 1,
                        error=str(exc),
                    )
                    if attempt < len(self._retry_delays) - 1:
                        await asyncio.sleep(delay)
            logger.warning(  # type: ignore[no-any-return]
                "narrative_chat_exhausted_using_template",
                entity_id=str(entity_id),
                last_error=str(last_exc_chat) if last_exc_chat else None,
            )
            return self._template_fallback(entity_name, entity_type, relation_count), "template-v1"

        # Reachable only when ``narrative_chat_client`` is None and ``llm_client``
        # is set (legacy extraction-mode path retained for backward-compat).
        if self._llm is None:  # pragma: no cover — defensive; guarded above
            return self._template_fallback(entity_name, entity_type, relation_count), "template-v1"

        last_exc: Exception | None = None
        for attempt, delay in enumerate(self._retry_delays):
            try:
                # Use the extraction API of FallbackChainClient for text completion
                from ml_clients.dataclasses import ExtractionInput  # type: ignore[import-untyped]

                inp = ExtractionInput(
                    prompt=prompt,
                    context="",
                    output_schema={"type": "string"},
                    model_id=self._model_id,
                )
                result = await self._llm.extract(inp)
                # PLAN-0087 (2026-05-09): the use case originally read
                # ``result.output`` which does not exist on ExtractionOutput;
                # the correct field is ``raw_response`` (the LLM's full text
                # answer). Without this fix every narrative collapsed to the
                # template-v1 fallback after exhausting all retries.
                # PLAN-0087 followup: also reject obvious JSON error
                # envelopes that some upstream LLMs emit when the prompt is
                # empty or the model name passed by the FallbackChain is
                # unrecognised. Treating those as valid output produced
                # narratives like ``{ "error": { "message": "No entity
                # provided"} }`` rendering in the Intelligence tab.
                if result is not None and result.raw_response:
                    text_result = str(result.raw_response).strip()
                    looks_like_error = text_result.startswith("{") and (
                        '"error"' in text_result[:120] or '"invalid_request_error"' in text_result[:200]
                    )
                    if looks_like_error:
                        # Treat as a retryable failure — let the caller
                        # exhaust retries and fall back to template-v1.
                        raise ValueError(f"LLM returned JSON error envelope: {text_result[:120]}")
                    if len(text_result) >= _MIN_NARRATIVE_LEN:
                        return text_result[:10000], self._model_id
            except Exception as exc:
                last_exc = exc
                logger.warning(  # type: ignore[no-any-return]
                    "narrative_llm_attempt_failed",
                    entity_id=str(entity_id),
                    attempt=attempt + 1,
                    error=str(exc),
                )
                if attempt < len(self._retry_delays) - 1:
                    await asyncio.sleep(delay)

        # All retries exhausted — fall back to deterministic template
        logger.warning(  # type: ignore[no-any-return]
            "narrative_llm_exhausted_using_template",
            entity_id=str(entity_id),
            last_error=str(last_exc) if last_exc else None,
        )
        return self._template_fallback(entity_name, entity_type, relation_count), "template-v1"

    def _build_prompt(
        self,
        entity_name: str,
        entity_type: str,
        relations: list[dict[str, Any]],
        contradictions: list[dict[str, Any]],
    ) -> str:
        """Construct an LLM prompt for narrative generation."""
        relation_lines = "\n".join(
            f"- {r['canonical_type']} {r.get('object_name', '')} (confidence: {r['confidence']:.2f})"
            for r in relations[:10]
        )
        contradiction_lines = "\n".join(f"- Contradicted {c['canonical_type']} claim" for c in contradictions[:3])
        prompt = (
            f"Write a factual, professional 2-4 sentence intelligence narrative about the "
            f"entity described below. Focus on what is known from structured evidence.\n\n"
            f"Entity: {entity_name} ({entity_type})\n"
        )
        if relation_lines:
            prompt += f"\nKey relationships:\n{relation_lines}\n"
        if contradiction_lines:
            prompt += f"\nContradictions detected:\n{contradiction_lines}\n"
        prompt += "\nNarrative:"
        return prompt

    def _template_fallback(self, entity_name: str, entity_type: str, relation_count: int) -> str:
        """Deterministic template-v1 fallback when LLM is unavailable."""
        text = (
            f"[template-v1] {entity_name}: {entity_type} with {relation_count} known relations "
            f"tracked in the knowledge graph. This narrative was generated from structured metadata "
            f"without an LLM because the model was unavailable or returned an unusable response."
        )
        # Ensure minimum length
        if len(text) < _MIN_NARRATIVE_LEN:
            text = text + " " + ("Additional context not available. " * 5)
        return text[:10000]

    def _compute_health_score(self, entity_ctx: dict[str, Any]) -> float:
        """Compute the entity health_score for canonical_entities.

        Formula:
          (data_completeness * 0.4) + (evidence_freshness * 0.3) + (relation_density * 0.3)

        data_completeness = proportion of [canonical_name, entity_type] that are non-empty.
        evidence_freshness = max(0, 1 - days_since_latest_evidence / 90).
        relation_density   = min(len(relations) / 20, 1.0).
        """
        entity = entity_ctx["entity"]
        relations = entity_ctx.get("relations", [])

        # data_completeness
        present_fields = [v for v in [entity.get("canonical_name"), entity.get("entity_type")] if v]
        data_completeness = min(len(present_fields) / 2.0, 1.0)

        # evidence_freshness — use the most recent latest_evidence_at across relations
        evidence_freshness = 0.0
        latest_evidence = None
        for r in relations:
            ea = r.get("latest_evidence_at")
            if ea:
                try:
                    if isinstance(ea, str):
                        from datetime import datetime

                        ea_dt = datetime.fromisoformat(ea.replace("Z", "+00:00"))
                    else:
                        ea_dt = ea
                    if latest_evidence is None or ea_dt > latest_evidence:
                        latest_evidence = ea_dt
                except (ValueError, TypeError):
                    pass
        if latest_evidence is not None:
            now = utc_now()  # type: ignore[no-any-return]
            if now.tzinfo is None:
                now = now.replace(tzinfo=UTC)
            if latest_evidence.tzinfo is None:
                latest_evidence = latest_evidence.replace(tzinfo=UTC)
            days_since = (now - latest_evidence).total_seconds() / 86400.0
            evidence_freshness = max(0.0, 1.0 - days_since / 90.0)

        # relation_density
        relation_density = min(len(relations) / 20.0, 1.0)

        return (data_completeness * 0.4) + (evidence_freshness * 0.3) + (relation_density * 0.3)

    def _build_outbox_event(self, version: EntityNarrativeVersion, reason: str) -> bytes:
        """Serialize the entity.narrative.generated.v1 event for the outbox."""
        from messaging.kafka.serialization_utils import serialize_confluent_avro  # type: ignore[import-untyped]

        now_iso: str = utc_now().isoformat()  # type: ignore[no-any-return]
        payload = {
            "event_id": str(new_uuid7()),  # type: ignore[no-any-return]
            "entity_id": str(version.entity_id),
            "version_id": str(version.version_id),
            "tenant_id": None,
            "generation_reason": reason,
            "model_id": version.model_id,
            "narrative_text_length": len(version.narrative_text),
            "word_count": version.word_count,
            "quality_score": version.quality_score,
            "occurred_at": now_iso,
            "schema_version": "1.0.0",
        }
        return serialize_confluent_avro(self._avsc_path, payload)  # type: ignore[no-any-return]


# ── Metric helpers (safe no-ops when prometheus not available) ─────────────────


def _inc_metric(counter: Any, *label_values: str) -> None:
    if counter is None:
        return
    import contextlib

    with contextlib.suppress(Exception):
        counter.labels(*label_values).inc()


def _observe_metric(histogram: Any, value: float) -> None:
    if histogram is None:
        return
    import contextlib

    with contextlib.suppress(Exception):
        histogram.observe(value)
