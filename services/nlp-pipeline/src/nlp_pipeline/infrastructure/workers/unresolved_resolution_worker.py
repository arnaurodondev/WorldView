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
from dataclasses import dataclass
from typing import TYPE_CHECKING

from nlp_pipeline.domain.enums import MentionClass, ResolutionOutcome
from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from ml_clients.usage_log import LlmUsageLogProtocol  # type: ignore[import-untyped]
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from nlp_pipeline.config import Settings
    from nlp_pipeline.infrastructure.nlp_db.models import EntityMentionModel

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

_CLASSIFICATION_PROMPT_TEMPLATE = (
    "Classify whether the following mention refers to a real-world entity "
    "(organization, person, government, or product) that would have its own "
    'Wikipedia article. Surface: "{surface}". '
    'Respond with JSON: {{"is_entity": true/false, "reason": "..."}}.'
)


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
    ) -> None:
        self._nlp_sf = nlp_session_factory
        self._settings = settings
        self._intel_sf = intel_session_factory
        self._usage_logger = usage_logger

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
        async with self._nlp_sf() as session:
            repo = _em.EntityMentionRepository(session)
            mentions = await repo.get_unresolved_batch(
                batch_size=batch_size,
                lookback_days=lookback_days,
            )
            if not mentions:
                return WorkerStats(processed=0, auto_resolved=0, entity_created=0, noise=0, errors=0)

            mention_ids = [m.mention_id for m in mentions]
            await repo.mark_batch_escalated(mention_ids)
            await session.commit()

        # ── Step 2: process each mention ─────────────────────────────────────
        stats = _BatchStats()
        for mention in mentions:
            await self._process_mention(mention, stats)

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
    ) -> None:
        """Process a single mention through Phase 1 and Phase 2."""
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

        # Eligible class → call Qwen2.5:3b via Ollama
        outcome, noise_reason = await self._phase2_llm_classify(mention)

        if outcome == ResolutionOutcome.ENTITY_CREATED:
            mention.resolution_outcome = ResolutionOutcome.ENTITY_CREATED.value
            async with self._nlp_sf() as session:
                repo = _em.EntityMentionRepository(session)
                await repo.update_resolution_outcome(
                    mention.mention_id,
                    ResolutionOutcome.ENTITY_CREATED.value,
                )
                await session.commit()
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
        """Attempt cascade re-resolution. Returns True if resolved."""
        # Phase 1 cascade re-resolution is a best-effort, no-cost operation.
        # Full cascade integration requires S7 intelligence_db access and is
        # deferred to a follow-up task. Return False (not resolved) for now.
        return False

    async def _phase2_llm_classify(
        self,
        mention: EntityMentionModel,
    ) -> tuple[ResolutionOutcome, str | None]:
        """Call Qwen2.5:3b to classify the mention as entity or noise.

        Returns (ResolutionOutcome, noise_reason | None).
        Returns (UNRESOLVED, None) on JSON parse failure or Ollama error.
        """
        import httpx

        ollama_url = self._settings.unresolved_resolution_ollama_base_url
        model_id = self._settings.unresolved_resolution_classification_model
        timeout_s = self._settings.unresolved_resolution_llm_timeout_s

        surface = getattr(mention, "mention_text", "") or ""
        prompt = _CLASSIFICATION_PROMPT_TEMPLATE.format(surface=surface[:200])

        payload = {
            "model": model_id,
            "prompt": prompt,
            "stream": False,
            # BP-231: qwen3 thinking mode adds 90-146s on CPU; think=False disables it.
            "think": False,
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
                parsed = json.loads(raw)
                is_entity = bool(parsed.get("is_entity", False))
                reason: str | None = str(parsed.get("reason", "")) or None
            except (json.JSONDecodeError, KeyError, ValueError):
                logger.warning(
                    "unresolved_resolution_json_parse_failure",
                    mention_id=str(mention.mention_id),
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


@dataclass
class _BatchStats:
    """Mutable accumulator for a single run_once() cycle."""

    processed: int = 0
    auto_resolved: int = 0
    entity_created: int = 0
    noise: int = 0
    errors: int = 0
