"""UnresolvedResolutionWorker — two-phase re-resolution of UNRESOLVED entity mentions.

PLAN-0033 T-C-2-01 / PRD-0029 §3.

Phase 1: Cascade re-run (free, uses existing S7 resolution logic).
Phase 2: Qwen2.5:3b LLM classification via Ollama — determines whether an
         unresolved mention is a real entity (→ entity_created) or noise (→ noise).

Key design invariants:
  - FOR UPDATE SKIP LOCKED in get_unresolved_batch() prevents double-processing.
  - Mentions are marked 'escalated' BEFORE releasing the lock.
  - recover_stale_escalated() is called at startup to reset stuck-escalated rows.
  - Non-entity-creating classes (LOCATION, COMMODITY, etc.) skip LLM entirely.
  - JSON parse failure → keep as 'unresolved' (not noise), count as error.
  - run_loop() catches all exceptions from run_once() to prevent crash loops.
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol
from uuid import UUID

import httpx

from nlp_pipeline.domain.enums import MentionClass, ResolutionOutcome
from observability import get_logger  # type: ignore[import-untyped]

# F-103 fix (2026-04-30): tolerant JSON extractor.
# DeepInfra/Ollama models occasionally return JSON wrapped in ```json fences```
# or with leading/trailing prose. ``json.loads(raw)`` then fails and the worker
# previously logged the failure without including ``raw``, so 100% of the
# 43-mention cycle was opaque. This helper:
#   1. Tries ``json.loads`` first (the happy path is unchanged).
#   2. Strips common code-fence wrappers and retries.
#   3. Falls back to extracting the first balanced ``{...}`` substring.
# Any genuine garbage still raises JSONDecodeError so the upstream except
# block can record the raw payload for debugging.
_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*(.+?)\s*```\s*$", re.DOTALL | re.IGNORECASE)


def _extract_json_object(raw: str) -> dict:
    """Parse a JSON object out of a possibly-wrapped LLM response."""
    if not isinstance(raw, str):
        raise json.JSONDecodeError("non-string LLM response", "", 0)
    text = raw.strip()
    # Path 1 — direct parse.
    try:
        result = json.loads(text)
    except json.JSONDecodeError:
        result = None
    if isinstance(result, dict):
        return result
    # Path 2 — strip ```json ... ``` fences.
    fence_match = _FENCE_RE.match(text)
    if fence_match:
        inner = fence_match.group(1).strip()
        try:
            inner_result = json.loads(inner)
        except json.JSONDecodeError:
            inner_result = None
        if isinstance(inner_result, dict):
            return inner_result
    # Path 3 — first balanced { ... } substring.
    start = text.find("{")
    if start != -1:
        depth = 0
        for i in range(start, len(text)):
            ch = text[i]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    candidate = text[start : i + 1]
                    try:
                        cand_result = json.loads(candidate)
                    except json.JSONDecodeError:
                        cand_result = None
                    if isinstance(cand_result, dict):
                        return cand_result
                    break
    raise json.JSONDecodeError("no JSON object found in LLM response", text[:200], 0)


if TYPE_CHECKING:
    from ml_clients.usage_log import LlmUsageLogProtocol  # type: ignore[import-untyped]
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from nlp_pipeline.config import Settings
    from nlp_pipeline.infrastructure.nlp_db.models import EntityMentionModel


class DirectProducerProtocol(Protocol):
    """Structural type for a direct Kafka producer.

    Implemented by the confluent-kafka adapter in the worker main module.
    Structural subtyping (Protocol) so tests can pass any object with a
    matching produce_bytes signature without inheritance.
    """

    def produce_bytes(self, *, topic: str, key: bytes, value: bytes) -> None: ...


logger = get_logger(__name__)  # type: ignore[no-any-return]

# Mention classes eligible for LLM classification (PRD §3, A-8).
# Non-eligible classes are marked 'noise' immediately without Ollama call.
_ELIGIBLE_CLASSES: frozenset[str] = frozenset(
    {
        MentionClass.ORGANIZATION.value,
        MentionClass.PERSON.value,
        MentionClass.FINANCIAL_INSTRUMENT.value,
        MentionClass.FINANCIAL_INSTITUTION.value,
        MentionClass.GOVERNMENT_BODY.value,
        MentionClass.REGULATORY_BODY.value,
    }
)

_NON_ENTITY_NOISE_REASON = "non_entity_creating_class"

# PLAN-0057 Wave B-3 / F-CRIT-05.
#
# The previous prompt asked whether a mention "would have its own Wikipedia
# article", which the LLM interpreted strictly: it rejected legitimate
# financial entities such as subsidiaries, ETFs, lesser-known regulators,
# and central banks of small jurisdictions.  Audit findings showed recall
# on subsidiaries/ETFs/regulators sat around ~40% under the old prompt.
#
# The replacement template is finance-domain specific:
#   • spells out *what counts* as an entity (companies, subsidiaries,
#     business units, funds/ETFs, indices, vehicles, regulators, central
#     banks, government bodies, supra-national institutions, named persons,
#     named financial products);
#   • spells out *what counts as noise* (generic anaphora, calendar
#     fragments, common-noun event words, parser fragments);
#   • shows four worked examples (two positive, two negative) covering
#     the exact failure modes the audit flagged;
#   • takes both ``surface`` (the lexical mention) and ``context`` (the
#     surrounding domain text — pulled from the document/section title via
#     ``EntityMentionRepository.get_unresolved_batch_with_context``) so the
#     LLM can disambiguate ambiguous surfaces (e.g. "MAS" alone is unclear,
#     but "Singapore central bank press release | Rate decision" → MAS is
#     clearly the Monetary Authority of Singapore).
#
# Both Ollama (_phase2_llm_classify_local) and DeepInfra
# (_phase2_llm_classify_external) call sites use this single template.
_CLASSIFICATION_PROMPT_TEMPLATE = (
    "You are classifying a candidate entity mention extracted from a "
    "financial-news or filing pipeline. Decide whether the SURFACE refers "
    "to a real, named entity worth tracking in a market-intelligence "
    "knowledge graph.\n"
    "\n"
    "Treat as ENTITY (is_entity=true) any of:\n"
    "  - public or private company, subsidiary, or business unit\n"
    "  - investable fund, ETF, mutual fund, index, or other named "
    "investable vehicle\n"
    "  - regulator, central bank, government body, ministry, or "
    "supra-national institution (IMF, ECB, BIS, etc.)\n"
    "  - named person (executive, regulator, politician, analyst)\n"
    "  - named financial product (specific bond series, named index, "
    "named option product, etc.)\n"
    "\n"
    "Treat as NOISE (is_entity=false) any of:\n"
    '  - generic noun phrases ("the company", "shares", "investors")\n'
    "  - pure number, date, or ticker fragments without context "
    '("Q3", "10-K", "FY24")\n'
    '  - common-noun event words ("merger", "earnings", "guidance")\n'
    "  - misparsed sentence fragments or partial phrases\n"
    "\n"
    "Worked examples:\n"
    '  - surface="iShares Core S&P 500 ETF", '
    'context="The iShares Core S&P 500 ETF (IVV) saw inflows of $1.2B." '
    '→ {{"is_entity": true, "reason": "named investable fund"}}\n'
    '  - surface="MAS", '
    'context="Singapore\'s MAS raised the benchmark rate by 25bps." '
    '→ {{"is_entity": true, "reason": '
    '"Monetary Authority of Singapore — regulator"}}\n'
    '  - surface="the company", '
    'context="Analysts said the company would miss guidance." '
    '→ {{"is_entity": false, "reason": '
    '"generic anaphora, not a named entity"}}\n'
    '  - surface="Q3", '
    'context="Q3 revenue rose 8% year-over-year." '
    '→ {{"is_entity": false, "reason": '
    '"calendar fragment, not a named entity"}}\n'
    "\n"
    'SURFACE: "{surface}"\n'
    'CONTEXT: "{context}"\n'
    "\n"
    "Respond with a single JSON object ONLY (no prose, no code fences). "
    'Schema: {{"is_entity": <true|false>, "reason": "<short rationale>"}}\n'
    'Concrete examples: {{"is_entity": true, "reason": "named regulator"}} '
    'or {{"is_entity": false, "reason": "generic noun phrase"}}.'
)

# SQL for enqueuing a newly-discovered entity mention into intelligence_db for
# S7 ProvisionalEnrichmentWorker to process. ON CONFLICT DO NOTHING is idempotent:
# same (surface, class) pair shares one queue row.
# RETURNING only fires on a new INSERT (not on conflict), so scalar_one_or_none()
# returns None when the row already existed — the caller skips the Kafka emit in
# that case to avoid duplicate events for already-queued entities (Wave E logic).
_PROVISIONAL_ENQUEUE_SQL = """
INSERT INTO provisional_entity_queue
    (queue_id, mention_text, normalized_surface, mention_class, source_doc_id, context_snippet)
VALUES
    (
        CAST(:queue_id AS uuid),
        CAST(:surface AS varchar(500)),
        lower(trim(CAST(:surface AS varchar(500)))),
        CAST(:mention_class AS varchar(50)),
        CAST(:doc_id AS uuid),
        CAST(:ctx AS text)
    )
ON CONFLICT (normalized_surface, mention_class)
DO NOTHING
RETURNING queue_id
"""


@dataclass(frozen=True)
class WorkerStats:
    """Statistics for a single run_once() cycle."""

    processed: int
    auto_resolved: int
    entity_created: int
    noise: int
    errors: int


class UnresolvedResolutionWorker:
    """Periodic worker that re-resolves UNRESOLVED entity mentions."""

    def __init__(
        self,
        nlp_session_factory: async_sessionmaker[AsyncSession],
        settings: Settings,
        *,
        intel_session_factory: async_sessionmaker[AsyncSession] | None = None,
        usage_logger: LlmUsageLogProtocol | None = None,
        direct_producer: DirectProducerProtocol | None = None,
    ) -> None:
        self._nlp_sf = nlp_session_factory
        self._settings = settings
        self._intel_sf = intel_session_factory
        self._usage_logger = usage_logger
        # Optional Kafka producer for entity.provisional.queued.v1 hot-path events.
        # When None, only the polling sweep picks up new rows (no hot path).
        self._direct_producer = direct_producer

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def recover_stale_escalated(self) -> int:
        """Reset mentions stuck as 'escalated' for > stale_minutes.

        Called once at service startup before run_loop().
        Returns the count of rows reset to 'unresolved'.
        """
        # Late import so tests can patch at the definition-module level.
        import nlp_pipeline.infrastructure.nlp_db.repositories.entity_mention as _em

        stale_minutes = self._settings.unresolved_resolution_stale_escalated_minutes
        async with self._nlp_sf() as session:
            repo = _em.EntityMentionRepository(session)
            count = await repo.recover_stale_escalated(stale_minutes=stale_minutes)
            await session.commit()

        if count:
            logger.info("stale_escalated_recovered", count=count, stale_minutes=stale_minutes)
        return count

    async def run_once(self) -> WorkerStats:
        """Fetch one batch of UNRESOLVED mentions and process them.

        Returns WorkerStats summarising the batch outcomes.
        """
        import nlp_pipeline.infrastructure.nlp_db.repositories.entity_mention as _em

        batch_size = self._settings.unresolved_resolution_batch_size
        lookback_days = self._settings.unresolved_resolution_lookback_days

        # ── Step 1: fetch batch with row-level lock ───────────────────────────
        # PLAN-0057 T-B-3-01: use the *with_context* variant so the LLM prompt
        # gets domain disambiguation (doc title + section title).  Falls back
        # to the plain method when the new symbol isn't on the repo (older
        # mocks in test fixtures expose only ``get_unresolved_batch``).
        async with self._nlp_sf() as session:
            repo = _em.EntityMentionRepository(session)
            bundles: list[_em.UnresolvedMentionWithContext]
            if hasattr(repo, "get_unresolved_batch_with_context"):
                bundles = await repo.get_unresolved_batch_with_context(
                    batch_size=batch_size,
                    lookback_days=lookback_days,
                )
            else:  # pragma: no cover — backwards-compat shim for legacy mocks
                plain = await repo.get_unresolved_batch(
                    batch_size=batch_size,
                    lookback_days=lookback_days,
                )
                bundles = [_em.UnresolvedMentionWithContext(mention=m, context_sentence=None) for m in plain]
            if not bundles:
                return WorkerStats(processed=0, auto_resolved=0, entity_created=0, noise=0, errors=0)

            mention_ids = [b.mention.mention_id for b in bundles]
            await repo.mark_batch_escalated(mention_ids)
            await session.commit()

        # ── Step 2: process each mention ─────────────────────────────────────
        stats = _BatchStats()
        for bundle in bundles:
            await self._process_mention(bundle.mention, stats, context_sentence=bundle.context_sentence)

        logger.info(
            "unresolved_resolution_cycle_done",
            processed=stats.processed,
            auto_resolved=stats.auto_resolved,
            entity_created=stats.entity_created,
            noise=stats.noise,
            errors=stats.errors,
        )
        return WorkerStats(
            processed=stats.processed,
            auto_resolved=stats.auto_resolved,
            entity_created=stats.entity_created,
            noise=stats.noise,
            errors=stats.errors,
        )

    async def run_loop(self) -> None:
        """Run run_once() in an infinite loop, sleeping between cycles.

        Exceptions from run_once() are caught and logged — the loop continues.
        asyncio.CancelledError propagates normally (for graceful shutdown).
        """
        interval_s = self._settings.unresolved_resolution_interval_s
        while True:
            try:
                await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning("unresolved_resolution_cycle_failed", exc_info=True)
            await asyncio.sleep(interval_s)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _process_mention(
        self,
        mention: EntityMentionModel,
        stats: _BatchStats,
        *,
        context_sentence: str | None = None,
    ) -> None:
        """Process a single mention through Phase 1 and Phase 2.

        ``context_sentence`` is the per-mention domain context (PLAN-0057
        T-B-3-01) that gets threaded into the LLM classification prompt.
        Keyword-only with a None default to keep older callers compiling.
        """
        import nlp_pipeline.infrastructure.nlp_db.repositories.entity_mention as _em

        stats.processed += 1

        # Phase 1: free cascade re-run (skipped if no intel_session_factory)
        if self._intel_sf is not None:
            resolved = await self._phase1_cascade(mention)
            if resolved:
                stats.auto_resolved += 1
                async with self._nlp_sf() as session:
                    repo = _em.EntityMentionRepository(session)
                    await repo.update_resolution_outcome(
                        mention.mention_id,
                        ResolutionOutcome.AUTO_RESOLVED.value,
                    )
                    await session.commit()
                return

        # Phase 2: class check + LLM classification
        mention_class_val = str(mention.mention_class)
        if mention_class_val not in _ELIGIBLE_CLASSES:
            # Non-entity-creating class → noise without LLM
            mention.resolution_outcome = ResolutionOutcome.NOISE.value
            mention.resolution_noise_reason = _NON_ENTITY_NOISE_REASON
            async with self._nlp_sf() as session:
                repo = _em.EntityMentionRepository(session)
                await repo.update_resolution_outcome(
                    mention.mention_id,
                    ResolutionOutcome.NOISE.value,
                    noise_reason=_NON_ENTITY_NOISE_REASON,
                )
                await session.commit()
            stats.noise += 1
            return

        # Eligible class → call Qwen2.5:3b via Ollama (or DeepInfra).
        # Pass the document/section context fetched in run_once() so the prompt
        # can disambiguate ambiguous surface forms (PLAN-0057 T-B-3-02).
        outcome, noise_reason = await self._phase2_llm_classify(mention, context_sentence=context_sentence)

        if outcome == ResolutionOutcome.ENTITY_CREATED:
            mention.resolution_outcome = ResolutionOutcome.ENTITY_CREATED.value
            async with self._nlp_sf() as session:
                repo = _em.EntityMentionRepository(session)
                await repo.update_resolution_outcome(
                    mention.mention_id,
                    ResolutionOutcome.ENTITY_CREATED.value,
                )
                await session.commit()
            # T-B-2 (PLAN-0061): enqueue for S7 ProvisionalEnrichmentWorker so
            # this newly-discovered entity gets a canonical entry created.
            await self._enqueue_for_enrichment(mention)
            stats.entity_created += 1
        elif outcome == ResolutionOutcome.NOISE:
            mention.resolution_outcome = ResolutionOutcome.NOISE.value
            mention.resolution_noise_reason = noise_reason
            async with self._nlp_sf() as session:
                repo = _em.EntityMentionRepository(session)
                await repo.update_resolution_outcome(
                    mention.mention_id,
                    ResolutionOutcome.NOISE.value,
                    noise_reason=noise_reason,
                )
                await session.commit()
            stats.noise += 1
        else:
            # JSON parse failure or LLM error → reset to unresolved
            mention.resolution_outcome = ResolutionOutcome.UNRESOLVED.value
            async with self._nlp_sf() as session:
                repo = _em.EntityMentionRepository(session)
                await repo.update_resolution_outcome(
                    mention.mention_id,
                    ResolutionOutcome.UNRESOLVED.value,
                )
                await session.commit()
            stats.errors += 1

    async def _phase1_cascade(self, mention: EntityMentionModel) -> bool:
        """Attempt Stages 1-3 entity resolution cascade. Returns True if resolved.

        Stage 4 (ANN/embedding) is skipped - no embedding client is available
        in this worker. ARCH-003: intel_session released before nlp_session write.
        """
        if self._intel_sf is None:
            return False

        import nlp_pipeline.infrastructure.nlp_db.repositories.entity_mention as _em
        from nlp_pipeline.infrastructure.intelligence_db.repositories.entity_alias import (
            EntityAliasRepository,
        )

        surface = (mention.mention_text or "").strip()
        if not surface:
            return False

        entity_id: UUID | None = None
        confidence: float = 0.0
        stage: int = 0

        async with self._intel_sf() as intel_session:  # type: ignore[misc]
            alias_repo = EntityAliasRepository(intel_session)

            # Stage 1: exact alias match (confidence=1.0)
            entity_id = await alias_repo.exact_match(surface)
            if entity_id is not None:
                confidence = 1.0
                stage = 1

            # Stage 2: ticker/ISIN lookup (confidence=0.95)
            if entity_id is None:
                entity_id = await alias_repo.ticker_isin_match(ticker=surface, isin=None)
                if entity_id is not None:
                    confidence = 0.95
                    stage = 2

            # Stage 3: fuzzy trigram similarity (confidence = sim * 0.90)
            if entity_id is None:
                fuzzy_hits = await alias_repo.fuzzy_trigram(surface)
                if fuzzy_hits:
                    entity_id, sim = fuzzy_hits[0]
                    confidence = sim * 0.90
                    stage = 3

        if entity_id is None:
            return False

        # ARCH-003: intel_session released above; acquire nlp_session for write
        async with self._nlp_sf() as nlp_session:
            repo = _em.EntityMentionRepository(nlp_session)
            await repo.resolve(mention.mention_id, entity_id, confidence, stage)
            await nlp_session.commit()

        logger.debug(
            "unresolved_phase1_resolved",
            mention_id=str(mention.mention_id),
            entity_id=str(entity_id),
            stage=stage,
            confidence=round(confidence, 4),
        )
        return True

    async def _enqueue_for_enrichment(self, mention: EntityMentionModel) -> UUID | None:
        """Insert mention into provisional_entity_queue for S7 KG enrichment.

        Uses intel_session_factory — the queue lives in intelligence_db.
        ON CONFLICT DO NOTHING is idempotent for same (surface, class) pair.

        Returns the queue_id of a NEWLY inserted row, or None if:
          - intel_session_factory is not configured, OR
          - the row already existed (conflict — queue_id returned for existing row
            via scalar_one_or_none returning None).

        When a new row is inserted AND a direct_producer is available, emits
        entity.provisional.queued.v1 so S7 ProvisionalQueuedConsumer can start
        enrichment immediately without waiting for the next polling sweep.
        """
        if self._intel_sf is None:
            return None

        import json

        from sqlalchemy import text as sa_text

        import common.ids  # type: ignore[import-untyped]
        import common.time  # type: ignore[import-untyped]

        mention_class_value = (
            mention.mention_class.value if hasattr(mention.mention_class, "value") else str(mention.mention_class)
        )
        new_queue_id = str(common.ids.new_uuid7())

        async with self._intel_sf() as intel_session:  # type: ignore[misc]
            result = await intel_session.execute(
                sa_text(_PROVISIONAL_ENQUEUE_SQL),
                {
                    "queue_id": new_queue_id,
                    "surface": mention.mention_text,
                    "mention_class": mention_class_value,
                    "doc_id": str(mention.doc_id),
                    "ctx": None,
                },
            )
            # scalar_one_or_none() returns None when ON CONFLICT DO NOTHING fires
            # (no row was inserted → no RETURNING output).  This distinguishes a
            # new insert from a duplicate-surface conflict.
            queue_id_str = result.scalar_one_or_none()
            await intel_session.commit()

        if queue_id_str is None:
            # Row already existed — no event needed (consumer would be a no-op).
            logger.debug(
                "unresolved_enqueue_conflict_skipped",
                mention_id=str(mention.mention_id),
                surface=mention.mention_text,
            )
            return None

        queue_id = UUID(str(queue_id_str))
        logger.debug(
            "unresolved_enqueued_for_enrichment",
            mention_id=str(mention.mention_id),
            queue_id=str(queue_id),
        )

        # Hot-path event: emit entity.provisional.queued.v1 so S7 consumer can
        # start enrichment immediately.  Fire-and-forget — producer failure is
        # non-fatal (polling sweep will still pick up the row).
        if self._direct_producer is not None:
            normalized_surface = (mention.mention_text or "").lower().strip()
            event_payload = json.dumps(
                {
                    "event_id": str(common.ids.new_uuid7()),
                    "event_type": "entity.provisional.queued",
                    "schema_version": 1,
                    "occurred_at": common.time.utc_now().isoformat(),
                    "queue_id": str(queue_id),
                    "normalized_surface": normalized_surface,
                    "mention_class": mention_class_value,
                    "source_doc_id": str(mention.doc_id) if mention.doc_id else None,
                    "correlation_id": None,
                }
            ).encode()
            try:
                self._direct_producer.produce_bytes(
                    topic=self._settings.kafka_topic_provisional_queued,
                    key=normalized_surface.encode(),
                    value=event_payload,
                )
            except Exception:
                logger.warning(
                    "unresolved_provisional_queued_emit_failed",
                    queue_id=str(queue_id),
                    exc_info=True,
                )

        return queue_id

    async def _phase2_llm_classify(
        self,
        mention: EntityMentionModel,
        *,
        context_sentence: str | None = None,
    ) -> tuple[ResolutionOutcome, str | None]:
        """Call LLM to classify the mention as entity or noise.

        When *unresolved_resolution_api_key* is set, delegates to the DeepInfra
        OpenAI-compatible endpoint (_phase2_llm_classify_external).  Otherwise
        falls through to the existing Ollama path.

        ``context_sentence`` is the per-mention domain context (PLAN-0057
        T-B-3-02) — typically the document title concatenated with the
        section title.  When None or empty we substitute a stable
        placeholder so the prompt template still renders cleanly.

        Returns (ResolutionOutcome, noise_reason | None).
        Returns (UNRESOLVED, None) on JSON parse failure or provider error.
        """
        ollama_url = self._settings.unresolved_resolution_ollama_base_url
        model_id = self._settings.unresolved_resolution_classification_model
        api_key = self._settings.unresolved_resolution_api_key
        api_base_url = self._settings.unresolved_resolution_api_base_url
        api_model_id = self._settings.unresolved_resolution_api_model_id
        timeout_s = self._settings.unresolved_resolution_llm_timeout_s

        surface = getattr(mention, "mention_text", "") or ""
        # Cap context at 400 chars so the prompt stays well under the 512-token
        # n_ctx budget configured for the Ollama path.  Longer titles/sections
        # are truncated with an ellipsis-free hard cut — model only needs the
        # leading domain words to disambiguate.
        context_text = (context_sentence or "").strip()[:400] or "(no surrounding context available)"
        prompt = _CLASSIFICATION_PROMPT_TEMPLATE.format(
            surface=surface[:200],
            context=context_text,
        )

        # DeepInfra path: use OpenAI-compatible chat completions when api_key is set.
        if api_key:
            return await self._phase2_llm_classify_external(
                mention, prompt, api_key, api_base_url, api_model_id, timeout_s
            )

        # ── Ollama fallback path (unchanged) ─────────────────────────────────
        payload = {
            "model": model_id,
            "prompt": prompt,
            "stream": False,
            # BP-231: qwen3 thinking mode adds 90-146s on CPU; think=False disables it.
            "think": False,
            # BP-121 variant: set explicit context window to prevent GGML_ASSERT abort.
            # qwen3:0.6b defaults to n_ctx=32768 which exceeds available memory and
            # causes `llama runner terminated: signal: aborted` on CPU-only containers.
            # Classification prompts are always < 200 tokens; 512 is ample.
            "options": {"num_ctx": 512},
        }

        # Pass explicit timeout to httpx so its read-timeout (default 5s) does not
        # fire before asyncio.wait_for's outer deadline.
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout_s)) as client:
            try:
                response = await asyncio.wait_for(
                    client.post(f"{ollama_url}/api/generate", json=payload),
                    timeout=timeout_s,
                )
                response.raise_for_status()
                raw = response.json().get("response", "")
                parsed = _extract_json_object(raw)
                is_entity = bool(parsed.get("is_entity", False))
                reason: str | None = str(parsed.get("reason", "")) or None
            except (json.JSONDecodeError, KeyError, ValueError) as parse_exc:
                # F-103 fix: log the raw LLM response (truncated) so future
                # failures are diagnosable instead of opaque "json_parse_failure".
                # Prior implementation discarded `raw` entirely — see
                # docs/audits/2026-04-30-investigation-platform-stability-followups.md.
                logger.warning(
                    "unresolved_resolution_json_parse_failure",
                    mention_id=str(mention.mention_id),
                    surface=mention.mention_text[:80] if mention.mention_text else None,
                    raw=raw[:500] if isinstance(raw, str) else repr(raw)[:500],
                    error=str(parse_exc),
                    provider="ollama",
                )
                # Log usage (failure)
                if self._usage_logger is not None:
                    asyncio.create_task(  # fire-and-forget  # noqa: RUF006
                        self._usage_logger.log(
                            model_id=model_id,
                            provider="ollama",
                            capability="extraction",
                            tokens_in=0,
                            tokens_out=0,
                            latency_ms=0,
                            estimated_cost_usd=0.0,
                            success=False,
                        )
                    )
                return ResolutionOutcome.UNRESOLVED, None
            except Exception:
                logger.warning(
                    "unresolved_resolution_ollama_error",
                    mention_id=str(mention.mention_id),
                    exc_info=True,
                )
                return ResolutionOutcome.UNRESOLVED, None

        # Log usage (success)
        if self._usage_logger is not None:
            asyncio.create_task(  # fire-and-forget  # noqa: RUF006
                self._usage_logger.log(
                    model_id=model_id,
                    provider="ollama",
                    capability="extraction",
                    tokens_in=0,
                    tokens_out=0,
                    latency_ms=0,
                    estimated_cost_usd=0.0,
                    success=True,
                )
            )

        if is_entity:
            return ResolutionOutcome.ENTITY_CREATED, None
        return ResolutionOutcome.NOISE, reason

    async def _phase2_llm_classify_external(
        self,
        mention: EntityMentionModel,
        prompt: str,
        api_key: str,
        api_base_url: str,
        api_model_id: str,
        timeout_s: float,
    ) -> tuple[ResolutionOutcome, str | None]:
        """Call DeepInfra (OpenAI-compat) for binary entity/noise classification.

        Uses chat/completions with response_format=json_object so the model returns
        a JSON payload directly (no "response" wrapper like Ollama uses).

        Returns (ResolutionOutcome, noise_reason | None).
        """
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout_s)) as client:
            try:
                response = await asyncio.wait_for(
                    client.post(
                        f"{api_base_url.rstrip('/')}/chat/completions",
                        headers={"Authorization": f"Bearer {api_key}"},
                        json={
                            "model": api_model_id,
                            "messages": [{"role": "user", "content": prompt}],
                            # Force JSON output — avoids free-form prose wrapping the result.
                            "response_format": {"type": "json_object"},
                            "temperature": 0.0,
                            "max_tokens": 64,
                        },
                    ),
                    timeout=timeout_s,
                )
                response.raise_for_status()
                raw = response.json()["choices"][0]["message"]["content"]
                parsed = _extract_json_object(raw)
                is_entity = bool(parsed.get("is_entity", False))
                reason: str | None = str(parsed.get("reason", "")) or None
            except (json.JSONDecodeError, KeyError, ValueError) as parse_exc:
                # F-103 fix: surface the raw LLM response so failures are
                # diagnosable. The Llama-3.1-8B-Instruct model occasionally
                # wraps JSON in ```json fences``` or in prose despite
                # response_format=json_object — _extract_json_object handles
                # the common variants; anything still failing here is a real
                # malformed payload worth logging.
                logger.warning(
                    "unresolved_resolution_json_parse_failure",
                    mention_id=str(mention.mention_id),
                    surface=mention.mention_text[:80] if mention.mention_text else None,
                    raw=raw[:500] if isinstance(raw, str) else repr(raw)[:500],
                    error=str(parse_exc),
                    provider="deepinfra",
                )
                if self._usage_logger is not None:
                    asyncio.create_task(  # fire-and-forget  # noqa: RUF006
                        self._usage_logger.log(
                            model_id=api_model_id,
                            provider="deepinfra",
                            capability="extraction",
                            tokens_in=0,
                            tokens_out=0,
                            latency_ms=0,
                            estimated_cost_usd=0.0,
                            success=False,
                        )
                    )
                return ResolutionOutcome.UNRESOLVED, None
            except Exception:
                logger.warning(
                    "unresolved_resolution_external_api_error",
                    mention_id=str(mention.mention_id),
                    exc_info=True,
                )
                return ResolutionOutcome.UNRESOLVED, None

        # Log usage (success)
        if self._usage_logger is not None:
            asyncio.create_task(  # fire-and-forget  # noqa: RUF006
                self._usage_logger.log(
                    model_id=api_model_id,
                    provider="deepinfra",
                    capability="extraction",
                    tokens_in=0,
                    tokens_out=0,
                    latency_ms=0,
                    estimated_cost_usd=0.0,
                    success=True,
                )
            )

        if is_entity:
            return ResolutionOutcome.ENTITY_CREATED, None
        return ResolutionOutcome.NOISE, reason


@dataclass
class _BatchStats:
    """Mutable accumulator for a single run_once() cycle."""

    processed: int = 0
    auto_resolved: int = 0
    entity_created: int = 0
    noise: int = 0
    errors: int = 0
