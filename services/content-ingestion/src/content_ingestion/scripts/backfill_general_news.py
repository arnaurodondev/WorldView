"""Multi-year historical backfill of the EODHD **general** news feed.

WHY THIS EXISTS
===============
The forward-incremental ``EODHDAdapter`` firehose (``_fetch_firehose``) only ever
walks the general ``/api/news`` feed **newest-first with EARLY-EXIT** — it stops
the moment it hits an already-stored article. That is exactly right for a 60s
steady-state poll (one request, 5 credits) but it can *never* reach the deep
historical archive: the newest article is always already stored, so the sweep
exits immediately and never pages backward in time.

This standalone backfill fills that gap. It walks the general feed **BACKWARD**
in bounded, contiguous date windows, pages each window **fully** (no early-exit,
so the whole window is captured), and dedup-writes every new article through the
SAME ``FetchAndWriteUseCase`` → outbox → ``content.article.raw.v1`` pipeline as
the live poller. Downstream (S5/S6/S7) is entirely source-agnostic: NER + entity
linking re-run from the article body, so a backfilled article yields the same
knowledge as a live-polled one.

DESIGN GUARANTEES
=================
* **Bounded**    — each window pages at most ``max_pages_per_window`` pages; the
  run stops as soon as a per-invocation credit budget is spent.
* **Idempotent** — every article dedups on ``url_hash`` (``article_fetch_log``
  UNIQUE + ``FetchAndWriteUseCase`` per-article skip). Re-running any window is a
  no-op; a crash mid-window re-processes only that window.
* **Resumable**  — a Valkey cursor (``s4:v1:news_backfill:cursor``) records the
  ``from`` date of the oldest window completed. ``--resume`` continues from there,
  so a daily CronJob drains a multi-year archive across many days.
* **Budget-safe** — before every window the run checks the SHARED per-UTC-day
  EODHD counter and stops before ``eodhd_daily_quota - backfill_daily_headroom``;
  it also enforces a per-invocation ``backfill_max_credits_per_run`` cap. It can
  never blow the 100k/day account cap the live firehose shares.

INVOCATION (run IN-CLUSTER, not via port-forward)::

    # dry-run: print the window plan + credit estimate, fetch nothing
    kubectl exec -n worldview deploy/content-ingestion-worker -- \
        python -m content_ingestion.scripts.backfill_general_news --years 3 --dry-run

    # real backfill, resumable (safe to re-run daily as a CronJob)
    kubectl exec -n worldview deploy/content-ingestion-worker -- \
        python -m content_ingestion.scripts.backfill_general_news --years 3 --resume

    # explicit window + custom per-run budget
    kubectl exec -n worldview deploy/content-ingestion-worker -- \
        python -m content_ingestion.scripts.backfill_general_news \
        --from 2023-01-01 --to 2023-12-31 --max-credits 8000 --resume

CREDIT / TIME ESTIMATE (verified against the live API 2026-07-15)
=================================================================
General feed ≈ **2.7k articles/day** → at page_size 1000 that is ~3 pages/day →
~5 credits/page. For **3 years** (~1095 days): ~2.95M articles ≈ ~2,950 page
requests ≈ **~14.8k credits total** — well under a single day's 100k budget.
Wall-clock is dominated by the ~0.5s inter-window delay + HTTP latency, not
credits: ~150 windows (7d each), a few pages each, ≈ tens of minutes for 3 years.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

import common.time
from content_ingestion.application.use_cases.fetch_and_write import FetchAndWriteUseCase
from content_ingestion.config import Settings
from content_ingestion.domain.entities import FetchResult, Source, SourceType
from content_ingestion.infrastructure.adapters.base import url_hash
from content_ingestion.infrastructure.adapters.eodhd.adapter import _parse_published_at
from content_ingestion.infrastructure.adapters.eodhd.client import EODHDClient
from content_ingestion.infrastructure.db.repositories.fetch_log import FetchLogRepository
from content_ingestion.infrastructure.db.repositories.outbox import OutboxRepository
from content_ingestion.infrastructure.db.repositories.source import SourceRepository
from content_ingestion.infrastructure.db.session import _build_factories
from content_ingestion.infrastructure.storage.minio_bronze import MinioBronzeAdapter
from messaging.eodhd_quota.quota_service import EodhdQuotaService  # type: ignore[import-untyped]
from messaging.pg.advisory_lock import pg_advisory_lock  # type: ignore[import-untyped]
from messaging.valkey import create_valkey_client_from_url  # type: ignore[import-untyped]
from observability import configure_logging, get_logger  # type: ignore[import-untyped]
from storage.factory import build_object_storage  # type: ignore[import-untyped]
from storage.settings import StorageSettings  # type: ignore[import-untyped]

logger = get_logger(__name__)  # type: ignore[no-any-return]

# Valkey keys — SEPARATE from the forward firehose's ``source_adapter_state``
# watermark so the backfill cursor never interferes with live incremental polling.
CURSOR_KEY = "s4:v1:news_backfill:cursor"
DONE_KEY = "s4:v1:news_backfill:done"

# Distinct advisory lock so a running backfill never blocks the live 60s firehose
# (which locks ``s4:fetch:<source_name>``). Correctness is guaranteed by the
# ``article_fetch_log.url_hash`` UNIQUE constraint + per-article dedup, not by a
# shared lock; this lock only prevents two concurrent backfill runs colliding.
BACKFILL_LOCK = "s4:news_backfill"


# ────────────────────────── pure, unit-testable helpers ──────────────────────


def backward_windows(from_date: date, to_date: date, window_days: int) -> list[tuple[date, date]]:
    """Contiguous, inclusive date windows covering ``[from_date, to_date]``.

    Returned **newest-first** (matching the general feed's ordering) so the
    backfill walks toward the past. Each window spans at most ``window_days``
    days; the last (oldest) window is clamped to ``from_date``.

    Raises:
        ValueError: if ``window_days < 1``.
    """
    if window_days < 1:
        msg = "window_days must be >= 1"
        raise ValueError(msg)
    if from_date > to_date:
        return []
    windows: list[tuple[date, date]] = []
    end = to_date
    while end >= from_date:
        start = max(from_date, end - timedelta(days=window_days - 1))
        windows.append((start, end))
        # Step to the day immediately before this window's start.
        end = start - timedelta(days=1)
    return windows


def remaining_windows(
    windows: list[tuple[date, date]],
    cursor: date | None,
) -> list[tuple[date, date]]:
    """Drop windows already completed on a prior (resumable) run.

    ``cursor`` is the ``from`` (start) date of the OLDEST window completed so
    far. Because the walk is newest→oldest, a completed window always has
    ``start >= cursor``; the work still to do is every window strictly older
    than the cursor (i.e. ``window_end < cursor``).
    """
    if cursor is None:
        return list(windows)
    return [w for w in windows if w[1] < cursor]


@dataclass
class RunBudget:
    """Tracks per-invocation credit spend and enforces both budget ceilings."""

    max_credits: int
    daily_cap: int
    daily_headroom: int
    credits_per_request: int
    page_size: int
    max_pages_per_window: int
    spent: int = 0

    def estimate_window_credits(self) -> int:
        """Worst-case credits for one window (pages all the way to the cap)."""
        return self.max_pages_per_window * self.credits_per_request

    def run_budget_exhausted(self, next_estimate: int) -> bool:
        """True when spending ``next_estimate`` more would exceed the run cap."""
        return self.spent + next_estimate > self.max_credits

    def daily_budget_exhausted(self, daily_used: int, next_estimate: int) -> bool:
        """True when the next window would breach the shared daily headroom."""
        return daily_used + next_estimate > self.daily_cap - self.daily_headroom

    def record_articles(self, article_count: int) -> int:
        """Attribute credits for a completed window from its article count.

        The ``EODHDClient`` already records exact per-page credits into the
        shared Valkey counter; this local estimate only enforces the per-run
        cap. Pages = ceil(articles / page_size), min 1 (an empty window still
        cost one request).
        """
        pages = max(1, math.ceil(article_count / self.page_size)) if article_count else 1
        window_credits = pages * self.credits_per_request
        self.spent += window_credits
        return window_credits


def articles_to_fetch_results(articles: list[dict[str, Any]], source_id: Any) -> list[FetchResult]:
    """Map raw EODHD article dicts → deduped ``FetchResult`` rows (``is_backfill=True``)."""
    out: list[FetchResult] = []
    seen: set[str] = set()
    for article in articles:
        if not isinstance(article, dict):
            continue
        link = str(article.get("link") or "").strip()
        if not link:
            continue
        article_hash = url_hash(link)
        if article_hash in seen:
            continue
        seen.add(article_hash)
        out.append(
            FetchResult(
                source_id=source_id,
                url=link,
                url_hash=article_hash,
                raw_bytes=json.dumps(article).encode("utf-8"),
                fetched_at=common.time.utc_now(),
                http_status=200,
                content_type="application/json",
                published_at=_parse_published_at(article),
                is_backfill=True,
                title=article.get("title") or None,
            ),
        )
    return out


class _PrefetchedAdapter:
    """No-op adapter passed to ``FetchAndWriteUseCase`` when results are prefetched.

    ``FetchAndWriteUseCase`` only calls ``adapter.fetch`` when
    ``prefetched_results`` is ``None``; the backfill always prefetches, so this
    is never invoked. It exists to satisfy the constructor's structural type.
    """

    async def fetch(self, *_args: Any, **_kwargs: Any) -> list[FetchResult]:  # pragma: no cover
        msg = "prefetched-only adapter: fetch() must not be called"
        raise NotImplementedError(msg)


# ─────────────────────────────── runner ──────────────────────────────────────


def _parse_cli(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backfill the EODHD general news feed backward in time.")
    parser.add_argument("--years", type=int, default=None, help="Horizon in years (default: settings.backfill_years).")
    parser.add_argument("--from", dest="from_date", default=None, help="Start date YYYY-MM-DD (overrides --years).")
    parser.add_argument("--to", dest="to_date", default=None, help="Explicit end date YYYY-MM-DD (default: today UTC).")
    parser.add_argument("--window-days", type=int, default=None, help="Window size (default: provider config).")
    parser.add_argument("--max-credits", type=int, default=None, help="Per-run credit budget (default: settings).")
    parser.add_argument("--sleep", type=float, default=None, help="Seconds slept between windows (default: settings).")
    parser.add_argument("--resume", action="store_true", help="Resume from the persisted Valkey cursor.")
    parser.add_argument("--dry-run", action="store_true", help="Print the window plan + estimate; fetch nothing.")
    return parser.parse_args(argv)


def _resolve_window(args: argparse.Namespace, settings: Settings) -> tuple[date, date, int]:
    """Resolve the [from, to] horizon + window size from CLI args / settings."""
    today = common.time.utc_now().date()
    to_date = datetime.strptime(args.to_date, "%Y-%m-%d").replace(tzinfo=UTC).date() if args.to_date else today
    if args.from_date:
        from_date = datetime.strptime(args.from_date, "%Y-%m-%d").replace(tzinfo=UTC).date()
    else:
        years = args.years if args.years is not None else settings.backfill_years
        from_date = to_date - timedelta(days=max(1, years) * 365)
    window_days = args.window_days if args.window_days is not None else settings.eodhd.general_news_backfill_window_days
    return from_date, to_date, window_days


async def _load_cursor(valkey: Any, *, resume: bool) -> date | None:
    """Read the persisted backfill cursor when resuming."""
    if not resume:
        return None
    raw = await valkey.get(CURSOR_KEY)
    if not raw:
        return None
    try:
        return datetime.strptime(str(raw), "%Y-%m-%d").replace(tzinfo=UTC).date()
    except ValueError:
        logger.warning("news_backfill_bad_cursor", raw=str(raw))
        return None


async def _find_general_source(session: Any) -> Source | None:
    """Locate the enabled general (filter-less) ``eodhd`` source row."""
    repo = SourceRepository(session)
    for model in await repo.list_enabled():
        source_type = getattr(model.source_type, "value", model.source_type)
        if str(source_type) != "eodhd":
            continue
        config = model.config or {}
        # The general feed carries no ``ticker``/``symbol`` filter.
        if config.get("ticker") or config.get("symbol"):
            continue
        return Source(
            id=model.id,
            name=model.name,
            source_type=SourceType.EODHD,
            enabled=True,
            config=config,
        )
    return None


async def run_backfill(settings: Settings, args: argparse.Namespace) -> int:
    """Execute the backfill. Returns the number of new articles written."""
    from_date, to_date, window_days = _resolve_window(args, settings)
    all_windows = backward_windows(from_date, to_date, window_days)

    _, _, write_factory, _read_factory = _build_factories(settings)
    valkey = create_valkey_client_from_url(settings.valkey_url)

    cursor = await _load_cursor(valkey, resume=args.resume)
    todo = remaining_windows(all_windows, cursor)

    logger.info(
        "news_backfill_plan",
        from_date=from_date.isoformat(),
        to_date=to_date.isoformat(),
        window_days=window_days,
        total_windows=len(all_windows),
        remaining_windows=len(todo),
        resumed_from=cursor.isoformat() if cursor else None,
        dry_run=args.dry_run,
    )
    if args.dry_run:
        est_credits = len(todo) * settings.eodhd.credits_per_request  # ≈1 request/window in practice
        logger.info("news_backfill_dry_run_estimate", windows=len(todo), min_credits=est_credits)
        await valkey.close()
        return 0

    budget = RunBudget(
        max_credits=args.max_credits if args.max_credits is not None else settings.backfill_max_credits_per_run,
        daily_cap=settings.eodhd_daily_quota,
        daily_headroom=settings.backfill_daily_headroom,
        credits_per_request=settings.eodhd.credits_per_request,
        page_size=settings.eodhd.news_page_limit,
        max_pages_per_window=settings.eodhd.general_news_backfill_max_pages_per_window,
    )
    sleep_between = args.sleep if args.sleep is not None else settings.backfill_batch_delay_seconds

    quota_service = EodhdQuotaService(
        valkey=valkey,
        hard_limit=settings.eodhd_monthly_quota,
        daily_hard_limit=settings.eodhd_daily_quota,
    )
    storage = build_object_storage(
        settings=StorageSettings(
            endpoint=_normalize_endpoint(settings.minio_endpoint),
            access_key=settings.minio_access_key,
            secret_key=settings.minio_secret_key,
            use_ssl=settings.minio_secure,
            default_bucket=settings.minio_bucket,
        )
    )
    bronze = MinioBronzeAdapter(storage)

    total_written = 0
    import httpx

    from content_ingestion.infrastructure.http.ssrf_transport import SSRFSafeTransport

    async with httpx.AsyncClient(
        transport=SSRFSafeTransport(),
        timeout=httpx.Timeout(
            settings.http_client.timeout_seconds,
            connect=settings.http_client.connect_timeout_seconds,
        ),
    ) as http_client:
        client = EODHDClient(
            http_client=http_client,
            api_key=settings.eodhd_api_key,
            provider_cfg=settings.eodhd,
            quota_service=quota_service,
        )

        # Resolve the general source once (short read session).
        async with write_factory() as sess:
            try:
                source = await _find_general_source(sess)
            finally:
                await sess.rollback()
        if source is None:
            logger.error("news_backfill_no_general_source")
            await valkey.close()
            return 0

        for window_start, window_end in todo:
            # ── Budget guards (checkpoint-and-exit, resumable) ────────────────
            est = budget.estimate_window_credits()
            if budget.run_budget_exhausted(est):
                logger.info("news_backfill_run_budget_reached", spent=budget.spent, max_credits=budget.max_credits)
                break
            daily_used = await quota_service.get_daily_credits_used()
            if budget.daily_budget_exhausted(daily_used, est):
                logger.info(
                    "news_backfill_daily_budget_reached",
                    daily_used=daily_used,
                    daily_cap=budget.daily_cap,
                    headroom=budget.daily_headroom,
                )
                break

            # ── Fetch the WHOLE window (full paging, no early-exit) ───────────
            articles = await client.fetch_all_pages(
                ticker="",
                from_date=window_start.isoformat(),
                to_date=window_end.isoformat(),
                max_pages=budget.max_pages_per_window,
            )
            budget.record_articles(len(articles))
            results = articles_to_fetch_results(articles, source.id)

            written = 0
            if results:
                async with (
                    write_factory() as session,
                    pg_advisory_lock(session, BACKFILL_LOCK) as acquired,
                ):
                    if not acquired:
                        logger.warning("news_backfill_lock_busy")
                        await valkey.close()
                        return total_written
                    try:
                        use_case = FetchAndWriteUseCase(
                            adapter=_PrefetchedAdapter(),  # type: ignore[arg-type]
                            bronze=bronze,
                            fetch_log_repo=FetchLogRepository(session),
                            outbox_repo=OutboxRepository(session),
                            commit_fn=session.commit,
                            rollback_fn=session.rollback,
                        )
                        summary = await use_case.execute(
                            source,
                            is_backfill=True,
                            prefetched_results=results,
                        )
                        written = summary.fetched
                    except Exception:
                        await session.rollback()
                        raise

            total_written += written

            # ── Checkpoint the cursor to this window's start (resumable) ──────
            await valkey.set(CURSOR_KEY, window_start.isoformat())
            logger.info(
                "news_backfill_window_done",
                window_start=window_start.isoformat(),
                window_end=window_end.isoformat(),
                fetched_from_api=len(articles),
                new_articles=written,
                credits_spent=budget.spent,
            )
            if sleep_between > 0:
                await asyncio.sleep(sleep_between)
        else:
            # Loop completed without ``break`` → the whole horizon is drained.
            await valkey.set(DONE_KEY, common.time.utc_now().date().isoformat())
            logger.info("news_backfill_complete", total_written=total_written)

    await valkey.close()
    return total_written


def _normalize_endpoint(endpoint: str) -> str:
    """Mirror ``worker._normalize_endpoint`` — ensure a scheme for MinIO."""
    if endpoint.startswith(("http://", "https://")):
        return endpoint
    return f"http://{endpoint}"


def main(argv: list[str] | None = None) -> None:
    """CLI entry point (``python -m content_ingestion.scripts.backfill_general_news``)."""
    settings = Settings()  # type: ignore[call-arg]
    configure_logging(
        service_name="content-ingestion-news-backfill",
        level=getattr(settings, "log_level", "INFO"),
        json=getattr(settings, "log_json", True),
    )
    args = _parse_cli(argv)
    written = asyncio.run(run_backfill(settings, args))
    logger.info("news_backfill_exit", total_written=written)


if __name__ == "__main__":
    main()
