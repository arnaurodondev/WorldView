"""InstrumentBriefPregenerationWorker — pre-generates + persists entity briefs (AI-brief-flag fix, 2026-06-19).

Responsibilities:
    1. Ask :class:`IActiveInstrumentsPort` for the entity_ids viewed in the last K days.
    2. For each, call :class:`GenerateBriefingUseCase.execute_public_instrument`
       with ``persist=True, skip_if_fresh=True`` so a ``brief_type='entity'`` row
       is written to ``user_briefs`` (keyed to the resolved market-data
       instrument_id), and fresh instruments are skipped without an LLM call.
    3. Emit run-level + per-instrument metrics and structlog events.

WHY this worker exists:
    The screener ``has_ai_brief`` flag is True only when an entity brief row
    exists. Before this fix the only producer was the on-demand route, so an
    instrument's flag stayed false until a user happened to open it. This worker
    populates coverage proactively for the active set — mirroring how
    :class:`MorningBriefPregenerationWorker` pre-generates morning briefs for
    active users.

Failure semantics:
    * Per-instrument failure is isolated — one instrument's exception never
      aborts the batch.
    * Run-level exceptions are caught at the top of ``run()`` so the scheduler
      keeps firing.

Concurrency:
    Instruments are processed in batches of ``settings.brief_pregen_batch_size``
    with up to ``settings.brief_pregen_concurrency`` running in parallel inside
    each batch (``asyncio.Semaphore``) — reusing the existing morning-brief
    pre-gen knobs so operators have a single set of tuning dials.

Service-JWT:
    Outside a request context the worker has no user JWT, so it depends on
    :class:`IJwtMinter` to mint a short-lived service JWT (and set it on the
    auth ContextVar) before each generation — otherwise S6/S7 internal calls
    return 401 and the brief degrades to empty content. The minter is optional
    (``None`` → unauthenticated, handy in unit tests where the UC is mocked).
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING

import structlog

from rag_chat.application.metrics.prometheus import (
    rag_instrument_brief_pregeneration_eligible_total,
    rag_instrument_brief_pregeneration_instruments_total,
    rag_instrument_brief_pregeneration_run_duration_seconds,
    rag_instrument_brief_pregeneration_runs_total,
)

if TYPE_CHECKING:
    from rag_chat.application.ports.active_instruments import IActiveInstrumentsPort
    from rag_chat.application.ports.jwt_minter import IJwtMinter
    from rag_chat.application.use_cases.generate_briefing import GenerateBriefingUseCase
    from rag_chat.config import Settings

_log = structlog.get_logger(__name__)  # type: ignore[no-any-return]


class InstrumentBriefPregenerationWorker:
    """One method (``run``) — orchestrates a single instrument-brief pre-gen pass."""

    def __init__(
        self,
        *,
        active_instruments: IActiveInstrumentsPort,
        briefing_uc: GenerateBriefingUseCase,
        settings: Settings,
        jwt_minter: IJwtMinter | None = None,
    ) -> None:
        self._active_instruments = active_instruments
        self._briefing_uc = briefing_uc
        self._settings = settings
        self._jwt_minter = jwt_minter

    async def run(self) -> None:
        """Execute one pre-generation pass. Never raises."""
        run_started_at = time.monotonic()
        rag_instrument_brief_pregeneration_runs_total.labels(status="started").inc()
        _log.info("instrument_brief_pregeneration_run_started")  # type: ignore[no-any-return]

        try:
            instruments = await self._active_instruments.list_active()
            rag_instrument_brief_pregeneration_eligible_total.set(len(instruments))

            if not instruments:
                _log.info("instrument_brief_pregeneration_no_eligible")  # type: ignore[no-any-return]
                rag_instrument_brief_pregeneration_runs_total.labels(status="completed").inc()
                rag_instrument_brief_pregeneration_run_duration_seconds.observe(time.monotonic() - run_started_at)
                return

            await self._process_instruments(instruments)

            rag_instrument_brief_pregeneration_runs_total.labels(status="completed").inc()
            _log.info(  # type: ignore[no-any-return]
                "instrument_brief_pregeneration_run_completed",
                eligible=len(instruments),
                duration_s=round(time.monotonic() - run_started_at, 2),
            )
        except Exception as exc:
            rag_instrument_brief_pregeneration_runs_total.labels(status="failed").inc()
            _log.error(  # type: ignore[no-any-return]
                "instrument_brief_pregeneration_run_failed",
                error=str(exc),
                error_type=type(exc).__name__,
            )
        finally:
            rag_instrument_brief_pregeneration_run_duration_seconds.observe(time.monotonic() - run_started_at)

    async def _process_instruments(self, instruments: list[str]) -> None:
        """Process all instruments in batches, respecting the concurrency limit."""
        batch_size = self._settings.brief_pregen_batch_size
        concurrency = self._settings.brief_pregen_concurrency

        for batch_start in range(0, len(instruments), batch_size):
            batch = instruments[batch_start : batch_start + batch_size]
            semaphore = asyncio.Semaphore(concurrency)
            await asyncio.gather(
                *(self._guarded_generate(entity_id, semaphore) for entity_id in batch),
                return_exceptions=True,
            )

    async def _guarded_generate(self, entity_id: str, semaphore: asyncio.Semaphore) -> None:
        async with semaphore:
            await self._generate_for_instrument(entity_id)

    async def _generate_for_instrument(self, entity_id: str) -> None:
        """Generate + persist one instrument's brief. Per-instrument errors are isolated."""
        started_at = time.monotonic()

        # Mint + set a service JWT so S6/S7 internal calls accept us. Mirrors the
        # morning worker's ContextVar pattern.
        from rag_chat.application.auth_context import get_current_jwt, set_current_jwt

        internal_jwt: str | None = None
        if self._jwt_minter is not None:
            internal_jwt = await self._jwt_minter.mint()

        try:
            previous_jwt = get_current_jwt()
        except Exception:
            previous_jwt = None

        if internal_jwt is not None:
            set_current_jwt(internal_jwt)

        try:
            result = await self._briefing_uc.execute_public_instrument(
                entity_id,
                persist=True,
                skip_if_fresh=True,
            )
        except Exception as exc:
            rag_instrument_brief_pregeneration_instruments_total.labels(outcome="failed").inc()
            _log.warning(  # type: ignore[no-any-return]
                "instrument_brief_pregeneration_failed",
                entity_id=entity_id,
                error=str(exc),
                error_type=type(exc).__name__,
                latency_ms=int((time.monotonic() - started_at) * 1000),
            )
            return
        finally:
            set_current_jwt(previous_jwt)

        outcome = "skipped_fresh" if result.get("skipped_fresh") else "generated"
        rag_instrument_brief_pregeneration_instruments_total.labels(outcome=outcome).inc()
        _log.info(  # type: ignore[no-any-return]
            "instrument_brief_pregeneration_succeeded",
            entity_id=entity_id,
            outcome=outcome,
            duration_s=round(time.monotonic() - started_at, 2),
        )


__all__ = ["InstrumentBriefPregenerationWorker"]
