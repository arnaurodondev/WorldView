"""Morning-brief pre-generation scheduler entry-point (PLAN-0094 W2, T-W2-06).

Runs a standalone async process that fires the
:class:`MorningBriefPregenerationWorker` every ``brief_pregen_interval_hours``
hours via APScheduler.  Mirrors the structure of
``services/alert/src/alert/infrastructure/email/scheduler_main.py`` so operators
have one mental model for "scheduled background process in worldview".

Usage::

    python -m rag_chat.infrastructure.scheduling.brief_scheduler_main

Container: ``rag-chat-brief-scheduler`` in ``infra/compose/docker-compose.yml``.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
from datetime import timedelta
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from rag_chat.application.workers.instrument_brief_pregeneration_worker import (
        InstrumentBriefPregenerationWorker,
    )

from common.time import utc_now  # type: ignore[import-untyped]
from messaging.valkey.client import ValkeyClient  # type: ignore[import-untyped]
from observability import (  # type: ignore[import-untyped]
    configure_logging,
    get_logger,
    log_runtime_banner,
    start_metrics_server,
)
from rag_chat.application.use_cases.briefing_context import BriefingContextGatherer
from rag_chat.application.use_cases.generate_briefing import GenerateBriefingUseCase
from rag_chat.application.workers.morning_brief_pregeneration_worker import (
    MorningBriefPregenerationWorker,
)
from rag_chat.config import Settings
from rag_chat.infrastructure.clients.active_users_reader import ActiveUsersReader
from rag_chat.infrastructure.clients.s1_client import S1Client
from rag_chat.infrastructure.clients.s3_client import S3Client
from rag_chat.infrastructure.clients.s5_client import S5Client
from rag_chat.infrastructure.clients.s6_client import S6Client
from rag_chat.infrastructure.clients.s7_client import S7Client
from rag_chat.infrastructure.llm.ollama_adapter import OllamaCompletionAdapter
from rag_chat.infrastructure.llm.provider_chain import LLMProviderChain


def _build_llm_chain(settings: Settings, valkey: Any) -> LLMProviderChain:
    """Build a minimal LLM provider chain for the scheduler process.

    Mirrors the subset of ``_wire_orchestrator`` in app.py that constructs
    :class:`LLMProviderChain`.  We deliberately skip the per-call usage logger
    (a session-scoped DB writer) because:

      * The scheduler does NOT need to record per-user usage rows — those are
        observability for the interactive chat path.  The pre-gen worker has
        its own metrics covering the same ground.
      * Wiring the usage logger requires a write_factory + SqlAlchemy engine
        — heavy machinery for a process that never touches the DB.

    Provider chain ordering:  DeepInfra → OpenRouter → Ollama (matches app.py).
    """
    providers: list[Any] = []

    deepinfra_api_key = settings.deepinfra_api_key.get_secret_value() if settings.deepinfra_api_key else None
    openrouter_api_key = settings.openrouter_api_key.get_secret_value() if settings.openrouter_api_key else None

    if deepinfra_api_key:
        from rag_chat.infrastructure.llm.deepinfra_adapter import DeepInfraCompletionAdapter

        providers.append(
            DeepInfraCompletionAdapter(
                api_key=deepinfra_api_key,
                model=settings.completion_model,
                chat_with_tools_timeout=settings.deepinfra_tool_call_timeout_seconds,
            )
        )
    if openrouter_api_key:
        from rag_chat.infrastructure.llm.openrouter_adapter import OpenRouterCompletionAdapter

        providers.append(
            OpenRouterCompletionAdapter(
                api_key=openrouter_api_key,
                model=settings.openrouter_completion_model,
            )
        )
    # Ollama is always the emergency fallback (last in chain).
    providers.append(
        OllamaCompletionAdapter(
            base_url=settings.ollama_base_url,
            model=settings.ollama_completion_model,
        )
    )

    return LLMProviderChain(
        providers=providers,
        valkey=valkey,
        usage_logger=None,
        retry_attempts=settings.provider_retry_attempts,
        retry_backoff_base=settings.provider_retry_backoff_base,
    )


async def _run_loop(settings: Settings) -> None:
    """Bootstrap resources, schedule the pre-gen worker, and wait forever.

    WHY a single ``await asyncio.sleep(3600)`` loop instead of
    ``await ap_scheduler.wait()``:  AsyncIOScheduler doesn't expose a clean
    "block until shutdown" API.  An idle sleep keeps the process alive while
    APScheduler fires the job on its interval in the background.
    """
    # Disabled-check first so test invocations (and operator overrides) don't
    # globally reconfigure structlog just to verify the kill-switch works.
    if not settings.brief_pregen_enabled:
        # Use stdlib logging here (not structlog) to avoid the side-effect of
        # calling configure_logging() on import-side test runners — that would
        # globally mutate structlog config and break unrelated tests that rely
        # on stdout capture (capsys + ConsoleRenderer).  A single stderr line
        # is enough signal for an operator running ``docker logs``.
        import logging as _stdlib_logging

        _stdlib_logging.warning("brief_pregeneration_disabled_via_env")
        return

    configure_logging(
        service_name=settings.service_name,
        level=settings.log_level,
        json=settings.log_json,
    )
    log = get_logger("rag_chat.brief_scheduler_main")  # type: ignore[no-any-return]

    # ── Prometheus scrape endpoint ────────────────────────────────────────────
    # PLAN-0094 live-QA #2: pre-gen counters live in this process, not in the
    # main rag-chat container, so Prometheus needs its own scrape target here.
    # PLAN-0107 B-3: migrated from inline ``prometheus_client.start_http_server``
    # to the shared ``observability.start_metrics_server`` helper for parity
    # with the rest of the platform (single shutdown contract via aclose()).
    metrics_handle = start_metrics_server(
        service_name="rag-chat-brief-scheduler",
        port=int(os.environ.get("METRICS_PORT", "9100")),
    )

    # ── Build dependencies ────────────────────────────────────────────────────
    # F-ARCH-003 (IG-MSG-002): use the shared :class:`ValkeyClient` so this
    # scheduler does not import ``redis.asyncio`` directly.  ValkeyClient
    # exposes ``zrangebyscore`` / ``set`` / ``zadd`` with the same semantics
    # as the raw redis client used previously, and all downstream consumers
    # (S1Client, ActiveUsersReader, GenerateBriefingUseCase, LLMProviderChain)
    # already type-hint ``ValkeyClient`` and use only this shared surface.
    valkey = ValkeyClient(url=settings.valkey_url)

    active_users = ActiveUsersReader(
        valkey_client=valkey,
        window_days=settings.brief_pregen_active_window_days,
    )

    # Upstream clients — mirror _wire_briefing_uc in app.py.
    s1 = S1Client(
        base_url=settings.s1_base_url,
        valkey=valkey,
        timeout=settings.upstream_timeout_seconds,
    )
    s3 = S3Client(base_url=settings.s3_base_url, timeout=settings.upstream_timeout_seconds)
    s5 = S5Client(base_url=settings.s5_base_url, timeout=settings.upstream_timeout_seconds)
    s6 = S6Client(base_url=settings.s6_base_url, timeout=settings.upstream_timeout_seconds)
    s7 = S7Client(base_url=settings.s7_base_url, timeout=settings.upstream_timeout_seconds)

    # PLAN-0094 follow-up: worker context — use the S5 service-token endpoint
    # (/internal/v1/users/{user_id}/alerts/pending) so a single service JWT can
    # fetch alerts for any user. The handler path (in app.py) keeps the default
    # ``use_service_endpoint=False`` so live users still go through JWT-sub scoping.
    # PLAN-0102 W3 follow-up (T-W3-FU-01): wire the tape + earnings adapters
    # for the pre-gen worker. The targets are the same market-data host as
    # S3Client, so we re-use ``s3_base_url`` rather than introducing a new
    # config key for a single host.
    from rag_chat.infrastructure.clients.earnings_calendar_client import EarningsCalendarClient
    from rag_chat.infrastructure.clients.market_tape_client import MarketTapeClient

    market_tape_client = MarketTapeClient(base_url=settings.s3_base_url, timeout=settings.upstream_timeout_seconds)
    earnings_calendar_client = EarningsCalendarClient(
        base_url=settings.s3_base_url, timeout=settings.upstream_timeout_seconds
    )

    # PLAN-0107 follow-up (brief vector descriptions, P1): intelligence client for
    # the entity narrative used by instrument briefs. WHY api_gateway_url: the
    # intelligence endpoints are S9-proxied (R14/R7 — auth + rate limiting).
    from rag_chat.infrastructure.clients.s7_intelligence_client import S7IntelligenceClient

    s7_intel = S7IntelligenceClient(
        base_url=settings.api_gateway_url,
        timeout=settings.upstream_timeout_seconds,
    )

    context_gatherer = BriefingContextGatherer(
        s1=s1,
        s3=s3,
        s5=s5,
        s6=s6,
        s7=s7,
        use_service_endpoint=True,
        market_tape=market_tape_client,
        earnings_calendar=earnings_calendar_client,
        s7_intelligence=s7_intel,
    )
    llm_chain = _build_llm_chain(settings, valkey)

    # WHY brief_archive=None: the MORNING worker only writes to Valkey, so the
    # use case tolerates None archive via its NullBriefArchive default.
    briefing_uc = GenerateBriefingUseCase(
        llm_chain=llm_chain,
        valkey=valkey,
        context_gatherer=context_gatherer,
    )

    # ── Instrument-brief pre-gen wiring (AI-brief-flag fix, 2026-06-19) ───────
    # The instrument-brief worker MUST persist ``brief_type='entity'`` rows to
    # ``user_briefs`` (that is the whole point — it populates the screener
    # ``has_ai_brief`` flag), so it needs a DB-backed brief archive, which the
    # Valkey-only morning path deliberately omits. Build a dedicated session
    # factory + write adapter + use case for it. The engines are torn down in
    # the finally block below. Only constructed when the feature is enabled so a
    # disabled deployment opens no DB pool.
    instrument_worker: InstrumentBriefPregenerationWorker | None = None
    instr_write_engine = None
    instr_read_engine = None
    if settings.brief_instrument_pregen_enabled:
        from rag_chat.application.workers.instrument_brief_pregeneration_worker import (
            InstrumentBriefPregenerationWorker,
        )
        from rag_chat.infrastructure.clients.active_instruments_reader import ActiveInstrumentsReader
        from rag_chat.infrastructure.clients.brief_archive_write_adapter import BriefArchiveWriteAdapter
        from rag_chat.infrastructure.db.session import create_rag_session_factory

        instr_write_engine, instr_read_engine, instr_write_factory, _instr_read_factory = create_rag_session_factory(
            settings
        )
        instrument_briefing_uc = GenerateBriefingUseCase(
            llm_chain=llm_chain,
            valkey=valkey,
            context_gatherer=context_gatherer,
            brief_archive=BriefArchiveWriteAdapter(write_factory=instr_write_factory),
        )
        active_instruments = ActiveInstrumentsReader(
            valkey_client=valkey,
            window_days=settings.brief_pregen_active_window_days,
        )

    # PLAN-0094 W2 follow-up (BP-303 variant): mint a short-lived service JWT
    # before each generation so S1/S5/S6/S7 internal endpoints accept us.
    # Without this the briefs come back empty (live-QA round 2 finding).
    # Reuse a single httpx.AsyncClient — the minter caches tokens for ~4 min
    # so this is at most one POST per 4-minute window regardless of batch size.
    import httpx  # type: ignore[import-not-found]

    from rag_chat.infrastructure.clients.s9_service_jwt_minter import S9ServiceJwtMinter

    jwt_minter_http_client = httpx.AsyncClient(timeout=10.0)
    jwt_minter = S9ServiceJwtMinter(
        client=jwt_minter_http_client,
        api_gateway_url=settings.api_gateway_url,
        service_account_token=(
            settings.service_account_token.get_secret_value() if settings.service_account_token else None
        ),
        service_name="rag-chat-brief-scheduler",
    )

    worker = MorningBriefPregenerationWorker(
        active_users=active_users,
        briefing_uc=briefing_uc,
        valkey_client=valkey,
        settings=settings,
        jwt_minter=jwt_minter,
    )

    # Build the instrument-brief worker (only when enabled — the UC + reader were
    # constructed above under the same flag). Reuses the same service-JWT minter
    # so S6/S7 internal calls are authenticated.
    if settings.brief_instrument_pregen_enabled:
        instrument_worker = InstrumentBriefPregenerationWorker(
            active_instruments=active_instruments,
            briefing_uc=instrument_briefing_uc,
            settings=settings,
            jwt_minter=jwt_minter,
        )

    # ── Schedule the recurring job ────────────────────────────────────────────
    # WHY IntervalTrigger (not CronTrigger): the email scheduler uses cron
    # (top of hour) because email digests are time-of-day-aware. The brief
    # pre-gen has no such constraint — any interval works. IntervalTrigger
    # also gives ops a single env var (``BRIEF_PREGEN_INTERVAL_HOURS``) to
    # adjust cadence without redeploying.
    from apscheduler.schedulers.asyncio import AsyncIOScheduler  # type: ignore[import-untyped]
    from apscheduler.triggers.interval import IntervalTrigger  # type: ignore[import-untyped]

    ap_scheduler = AsyncIOScheduler()
    ap_scheduler.add_job(
        worker.run,
        IntervalTrigger(hours=settings.brief_pregen_interval_hours),
        id="brief_pregeneration",
        max_instances=1,  # prevent overlapping runs (long LLM tail latency)
        coalesce=True,  # skip accumulated missed runs after a restart
        # WHY +30s, not "now": gives the container time to finish starting
        # (DB pools warming, dependent service health checks) before the
        # first pre-gen attempts hit them.  Also makes the first run visible
        # during dev without waiting a full ``brief_pregen_interval_hours``.
        # F-ARCH-002 (IG-COMMON-002): use the shared timezone-aware helper.
        # APScheduler accepts tz-aware datetimes and converts internally; no
        # behaviour change vs the previous naive utcnow() since the scheduler
        # interprets naive datetimes as the local timezone of the configured
        # scheduler timezone (which is UTC by default in our containers).
        next_run_time=utc_now() + timedelta(seconds=30),
    )

    # ── Instrument-brief pre-gen job (AI-brief-flag fix, 2026-06-19) ──────────
    # Same interval/window as the morning job (reuses the same knobs). Offset the
    # first run by +60s (vs +30s for morning) so the two cold-start passes do not
    # both hammer the LLM provider at once.
    if settings.brief_instrument_pregen_enabled:
        # ``instrument_worker`` is always constructed when the flag is set (see the
        # build block above); assert for the type-checker since the two guarded
        # blocks are not narrowed together.
        assert instrument_worker is not None
        ap_scheduler.add_job(
            instrument_worker.run,
            IntervalTrigger(hours=settings.brief_pregen_interval_hours),
            id="instrument_brief_pregeneration",
            max_instances=1,
            coalesce=True,
            next_run_time=utc_now() + timedelta(seconds=60),
        )

    ap_scheduler.start()
    log.info(  # type: ignore[no-any-return]
        "brief_scheduler_started",
        interval_hours=settings.brief_pregen_interval_hours,
        window_days=settings.brief_pregen_active_window_days,
        instrument_pregen_enabled=settings.brief_instrument_pregen_enabled,
    )

    # PLAN-0107 B-4: emit single <service>_ready event after deps are wired.
    log_runtime_banner(
        "rag-chat-brief-scheduler",
        dependencies={
            "valkey_url": getattr(settings, "valkey_url", None),
            "api_gateway_url": settings.api_gateway_url,
            "interval_hours": settings.brief_pregen_interval_hours,
            "active_window_days": settings.brief_pregen_active_window_days,
        },
    )

    try:
        while True:
            await asyncio.sleep(3600)
    finally:
        ap_scheduler.shutdown(wait=False)
        # close upstream HTTPX clients to release sockets cleanly. A single
        # client.aclose() failure must not mask the rest of the shutdown.
        for client in (s1, s3, s5, s6, s7):
            with contextlib.suppress(Exception):
                await client.aclose()
        # PLAN-0094 W2 follow-up: the JWT minter owns its own httpx client.
        with contextlib.suppress(Exception):
            await jwt_minter_http_client.aclose()
        with contextlib.suppress(Exception):
            await valkey.close()
        # AI-brief-flag fix (2026-06-19): dispose the instrument-brief DB engines
        # (only created when the feature is enabled).
        for _engine in (instr_write_engine, instr_read_engine):
            if _engine is not None:
                with contextlib.suppress(Exception):
                    await _engine.dispose()
        # PLAN-0107 B-3: tear down the shared metrics HTTP server cleanly.
        with contextlib.suppress(Exception):
            await metrics_handle.aclose()
        log.info("brief_scheduler_stopped")  # type: ignore[no-any-return]


def main() -> None:
    settings = Settings()  # type: ignore[call-arg]
    asyncio.run(_run_loop(settings))


if __name__ == "__main__":
    main()
