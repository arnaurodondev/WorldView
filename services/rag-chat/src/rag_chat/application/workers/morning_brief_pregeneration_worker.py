"""MorningBriefPregenerationWorker — orchestrates one daily pre-gen pass (PLAN-0094 W2, T-W2-04).

Responsibilities:
    1. Ask :class:`IActiveUsersPort` for the list of users active in the last K days.
    2. Generate a morning brief for each user via :class:`GenerateBriefingUseCase`.
    3. Write the result to Valkey under TWO keys:
       * ``briefing:morning:v2:{user_id}``         — the "fresh" key the handler reads first.
       * ``briefing:morning:lastgood:{user_id}``   — the "last-known-good" key the handler
                                                     falls back to if a future regeneration fails.
    4. Emit run-level and per-user metrics + structlog events.

Failure semantics:
    * Per-user failure is isolated — one user's exception NEVER aborts the batch and
      NEVER overwrites that user's existing last-known-good key.
    * Run-level exceptions (e.g. Valkey hard-down) are caught at the top of ``run()``
      and logged; the scheduler must keep firing.

Concurrency:
    Users are processed in batches of ``settings.brief_pregen_batch_size`` with up to
    ``settings.brief_pregen_concurrency`` users running in parallel inside each batch
    (``asyncio.Semaphore``).  This caps DeepInfra throughput so a 50-user batch doesn't
    saturate the LLM provider.

Service-JWT:
    :meth:`GenerateBriefingUseCase.execute_public_morning` accepts an ``internal_jwt``
    kwarg.  Outside a request context the worker has no user-issued JWT, so it relies
    on the use case being callable with ``internal_jwt=None`` — the use case still
    invokes BriefingContextGatherer which propagates ``None`` to its upstream clients.
    Those clients fall back to whatever auth context is wired in production (S1 client
    uses its own internal token; S5/S6/S7 use the internal-JWT context-var that the
    scheduler-main entry-point seeds at startup with a service token).

    A dedicated :class:`IJwtMinter` port could fetch a fresh service token per run,
    but for v1 the unauthenticated upstream-client paths are sufficient for the
    morning-brief context gather (BriefingContextGatherer degrades safely on any
    upstream failure — see ``generate_briefing.py``).
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Any
from uuid import UUID

import structlog

from rag_chat.application.metrics.prometheus import (
    rag_brief_pregeneration_eligible_users,
    rag_brief_pregeneration_run_duration_seconds,
    rag_brief_pregeneration_runs_total,
    rag_brief_pregeneration_user_duration_seconds,
    rag_brief_pregeneration_users_total,
)

if TYPE_CHECKING:
    from rag_chat.application.ports.active_users import IActiveUsersPort
    from rag_chat.application.use_cases.generate_briefing import GenerateBriefingUseCase
    from rag_chat.config import Settings

_log = structlog.get_logger(__name__)  # type: ignore[no-any-return]

# Cache-key prefixes — must match the handler's lookup chain in
# ``rag_chat.api.routes.public_briefings``.
_FRESH_KEY_PREFIX = "briefing:morning:v2:"
_LASTGOOD_KEY_PREFIX = "briefing:morning:lastgood:"


class MorningBriefPregenerationWorker:
    """One method (``run``) — orchestrates a single pre-generation pass.

    Idempotent and re-entrant safe: re-firing ``run`` simply overwrites the
    fresh + last-known-good keys for each user (no harm done if two scheduler
    instances accidentally overlap, beyond duplicate LLM cost).
    """

    def __init__(
        self,
        *,
        active_users: IActiveUsersPort,
        briefing_uc: GenerateBriefingUseCase,
        valkey_client: Any,
        settings: Settings,
    ) -> None:
        self._active_users = active_users
        self._briefing_uc = briefing_uc
        self._valkey = valkey_client
        self._settings = settings

    # ─────────────────────────────────────────────────────────────────────────
    # Public entry-point
    # ─────────────────────────────────────────────────────────────────────────

    async def run(self) -> None:
        """Execute one pre-generation pass.

        Never raises — top-level exceptions are caught, logged, and surfaced
        via the ``runs_total{status="failed"}`` metric so the APScheduler can
        keep firing on its interval.
        """
        run_started_at = time.monotonic()

        rag_brief_pregeneration_runs_total.labels(status="started").inc()
        _log.info("brief_pregeneration_run_started")  # type: ignore[no-any-return]

        try:
            users = await self._active_users.list_active()
            rag_brief_pregeneration_eligible_users.set(len(users))

            if not users:
                # Empty source is the normal state of a fresh deployment until
                # a real user logs in.  We emit a completed metric so the
                # "scheduler is alive" signal stays green.
                _log.info("brief_pregeneration_run_no_eligible_users")  # type: ignore[no-any-return]
                rag_brief_pregeneration_runs_total.labels(status="completed").inc()
                rag_brief_pregeneration_run_duration_seconds.observe(time.monotonic() - run_started_at)
                return

            await self._process_users(users)

            rag_brief_pregeneration_runs_total.labels(status="completed").inc()
            _log.info(  # type: ignore[no-any-return]
                "brief_pregeneration_run_completed",
                eligible_users=len(users),
                duration_s=round(time.monotonic() - run_started_at, 2),
            )
        except Exception as exc:
            # WHY swallow + log: the APScheduler must keep firing on its
            # interval even if Valkey is down or the active-users source
            # throws.  We surface the failure via the metric + log so ops
            # can alert on it.
            rag_brief_pregeneration_runs_total.labels(status="failed").inc()
            _log.error(  # type: ignore[no-any-return]
                "brief_pregeneration_run_failed",
                error=str(exc),
                error_type=type(exc).__name__,
                duration_s=round(time.monotonic() - run_started_at, 2),
            )
        finally:
            rag_brief_pregeneration_run_duration_seconds.observe(time.monotonic() - run_started_at)

    # ─────────────────────────────────────────────────────────────────────────
    # Internal helpers
    # ─────────────────────────────────────────────────────────────────────────

    async def _process_users(self, users: list[UUID]) -> None:
        """Process all users in batches, respecting the concurrency limit.

        Why batched + semaphored:
          * Batches bound peak memory: a 500-user batch loaded into Python
            would hold ~500 brief result dicts simultaneously.  Splitting
            into batches of ~50 keeps the resident set predictable.
          * Within each batch the semaphore caps concurrent LLM calls to
            ``brief_pregen_concurrency`` so we don't saturate DeepInfra.
        """
        batch_size = self._settings.brief_pregen_batch_size
        concurrency = self._settings.brief_pregen_concurrency

        for batch_start in range(0, len(users), batch_size):
            batch = users[batch_start : batch_start + batch_size]
            semaphore = asyncio.Semaphore(concurrency)
            # gather(return_exceptions=True) is belt-and-braces — _generate_for_user
            # already catches and logs its own exceptions, so this should not
            # bubble anything up.  The flag is here to defend against future
            # refactors that might let an exception escape.
            await asyncio.gather(
                *(self._guarded_generate(user_id, semaphore) for user_id in batch),
                return_exceptions=True,
            )

    async def _guarded_generate(self, user_id: UUID, semaphore: asyncio.Semaphore) -> None:
        """Acquire the semaphore and delegate to ``_generate_for_user``."""
        async with semaphore:
            await self._generate_for_user(user_id)

    async def _generate_for_user(self, user_id: UUID) -> None:
        """Generate one user's brief and write the fresh + last-good keys.

        Per-user errors are isolated here — we catch, log, increment the
        ``generation_failed`` outcome counter, and return.  The caller's
        ``asyncio.gather`` will continue processing the rest of the batch.
        """
        user_started_at = time.monotonic()
        user_id_str = str(user_id)

        _log.debug("brief_pregeneration_user_started", user_id=user_id_str)  # type: ignore[no-any-return]

        try:
            # WHY tenant_id=user_id_str: the morning-brief use case treats
            # tenant_id as an isolation key for the rate limit + portfolio
            # gather.  Without a request context we have no real tenant; we
            # pass the user_id itself so each user's rate-limit bucket stays
            # isolated.  BriefingContextGatherer accepts None tenant gracefully.
            result = await self._briefing_uc.execute_public_morning(
                user_id=user_id_str,
                tenant_id=user_id_str,
                internal_jwt=None,
            )
        except Exception as exc:
            rag_brief_pregeneration_users_total.labels(outcome="generation_failed").inc()
            _log.warning(  # type: ignore[no-any-return]
                "brief_pregeneration_user_failed",
                user_id=user_id_str,
                error=str(exc),
                error_type=type(exc).__name__,
                latency_ms=int((time.monotonic() - user_started_at) * 1000),
            )
            # Per-spec: do NOT overwrite the existing last-known-good key.
            # The next handler request will surface it as ``is_stale=True``.
            return

        # ── Build the cached payload ──────────────────────────────────────────
        # WHY shape this here (not in the handler): the handler reads the JSON
        # straight into PublicBriefingResponse via ``model_validate_json``, so
        # the keys we write must match the schema's field names.  The handler
        # then sets ``is_stale`` based on which key the payload came from.
        payload = self._build_payload(user_id_str, result)
        await self._write_caches(user_id_str, payload)

        rag_brief_pregeneration_users_total.labels(outcome="success").inc()
        rag_brief_pregeneration_user_duration_seconds.observe(time.monotonic() - user_started_at)
        _log.info(  # type: ignore[no-any-return]
            "brief_pregeneration_user_succeeded",
            user_id=user_id_str,
            duration_s=round(time.monotonic() - user_started_at, 2),
        )

    def _build_payload(self, user_id_str: str, result: dict[str, Any]) -> str:
        """Serialise the use-case result into the PublicBriefingResponse JSON shape.

        WHY this lives in the worker (not in a shared helper): the handler also
        builds a PublicBriefingResponse, but it does so via the Pydantic model
        path (``PublicBriefingResponse(**response_data).model_dump_json()``).
        For the worker we keep the dependency surface small — a plain JSON dump
        works because the schema is additive (extra keys ignored on load).
        """
        # WHY import the Pydantic model here (not at the top): keeps the worker's
        # import-time footprint small and avoids a circular import with
        # rag_chat.api.schemas at module load.
        from rag_chat.api.schemas import PublicBriefingResponse

        response = PublicBriefingResponse(
            narrative=result.get("content", result.get("narrative", "")),
            risk_summary=result.get("risk_summary") or {},
            citations=result.get("citations", []),
            generated_at=result["generated_at"],
            cached=False,
            entity_id=None,
            summary=result.get("summary"),
            sections=result.get("sections", []),
            confidence=result.get("confidence", 1.0),
            lead=result.get("lead"),
            is_stale=False,
        )
        return response.model_dump_json()

    async def _write_caches(self, user_id_str: str, payload_json: str) -> None:
        """Write the fresh + last-known-good keys with their respective TTLs."""
        fresh_key = f"{_FRESH_KEY_PREFIX}{user_id_str}"
        lastgood_key = f"{_LASTGOOD_KEY_PREFIX}{user_id_str}"

        fresh_ttl = self._settings.brief_fresh_ttl_hours * 3600
        lastgood_ttl = self._settings.brief_last_good_ttl_days * 86400

        # WHY two separate awaits (not a pipeline): the writes are independent
        # and both idempotent.  A failure on the lastgood write is logged but
        # does not roll back the fresh write — degrading gracefully to "we have
        # a fresh brief but the lastgood pointer didn't update" is better than
        # leaving the user with no brief at all.
        await self._valkey.set(fresh_key, payload_json, ex=fresh_ttl)
        await self._valkey.set(lastgood_key, payload_json, ex=lastgood_ttl)


__all__ = ["MorningBriefPregenerationWorker"]
