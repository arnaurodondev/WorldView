"""SEC EDGAR source adapter — fetches filings via EFTS search.

Rate limit: asyncio.Semaphore(8) for 8 concurrent requests.
Dedup: sha256(accession_number + filename).
Retry: 3x with 1s/2s/4s exponential backoff.
User-Agent: Required by SEC policy (ConfigurationError if missing).
"""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

import common.ids
import common.time
from content_ingestion.domain.entities import FetchResult
from content_ingestion.infrastructure.adapters.base import RetryConfig, SourceAdapter, url_hash
from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from content_ingestion.config import SECEdgarProviderSettings
    from content_ingestion.domain.entities import Source
    from content_ingestion.infrastructure.adapters.sec_edgar.client import SECEdgarClient

_NY_TZ = ZoneInfo("America/New_York")

logger = get_logger(__name__)  # type: ignore[no-any-return]


def _parse_published_at(filing: dict[str, Any]) -> datetime | None:
    """Extract published_at from ``period_ending`` or ``file_date``.

    BP-460: EFTS search-index API returns ``period_ending`` (not
    ``period_of_report``) and ``file_date``.  The old field name was silently
    missed, so every filing used None for published_at.
    """
    source = filing.get("_source", filing)
    # BP-460: EFTS uses "period_ending", not "period_of_report"
    for field in ("period_ending", "file_date"):
        raw = source.get(field)
        if raw:
            try:
                dt = datetime.fromisoformat(str(raw))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=UTC)
                return dt
            except (ValueError, TypeError):
                continue
    return None


class SECEdgarAdapter(SourceAdapter):
    """Fetches SEC EDGAR filings via EFTS full-text search.

    Args:
        client: HTTP client for SEC EDGAR endpoints.
        exists_fn: Async callable that checks if a url_hash already exists.
        retry_config: Retry parameters.
        provider_cfg: Provider settings (market-hours intervals, etc.).
    """

    def __init__(
        self,
        client: SECEdgarClient,
        exists_fn: Any = None,
        retry_config: RetryConfig | None = None,
        provider_cfg: SECEdgarProviderSettings | None = None,
    ) -> None:
        self._client = client
        self._exists_fn = exists_fn
        self._retry_config = retry_config or RetryConfig()
        self._provider_cfg = provider_cfg

    def _is_market_hours(self, now_utc: datetime) -> bool:
        """Return True if ``now_utc`` falls within NYSE market hours (09:30-16:00 ET, Mon-Fri)."""
        now_ny = now_utc.astimezone(_NY_TZ)
        return now_ny.weekday() < 5 and time(9, 30) <= now_ny.time() <= time(16, 0)

    def calculate_next_run_time(self, now_utc: datetime) -> datetime:
        """Return the next scheduled run time based on market hours.

        Uses ``market_hours_interval_seconds`` (default 60s) during NYSE hours
        and ``off_hours_interval_seconds`` (default 1800s) outside them.
        """
        if self._provider_cfg is not None:
            interval = (
                self._provider_cfg.market_hours_interval_seconds
                if self._is_market_hours(now_utc)
                else self._provider_cfg.off_hours_interval_seconds
            )
        else:
            interval = 60 if self._is_market_hours(now_utc) else 1800
        return now_utc + timedelta(seconds=interval)

    async def fetch(self, source: Source, *, is_backfill: bool = False, from_date: str = "") -> list[FetchResult]:
        """Fetch and deduplicate SEC EDGAR filings.

        For each filing:
        1. Compute ``url_hash = sha256(accession_number + filename)``
        2. Skip if exists_fn returns True
        3. Fetch filing HTML/XBRL document
        4. Build FetchResult with raw document bytes
        """
        config = source.config
        effective_from = from_date or config.get("from_date", "")
        to_date = config.get("to_date", "")
        forms = config.get("forms", "10-K,10-Q,8-K,DEF14A")

        filings = await self._retry_request(
            lambda: self._client.search_filings(from_date=effective_from, to_date=to_date, forms=forms),
            retry_config=self._retry_config,
            context="sec_edgar:search",
        )
        if not isinstance(filings, list):
            return []

        results: list[FetchResult] = []
        for filing in filings:
            source_data = filing.get("_source", filing)

            # BP-460: EFTS returns "adsh" (not "accession_no") as the accession number.
            # Example value: "0001477932-26-002885"
            accession_no = source_data.get("adsh", "")
            if not accession_no:
                continue

            # BP-460: EFTS returns "ciks" as a list of strings with leading zeros.
            # We need the bare numeric CIK (no leading zeros) for the Archives URL.
            # Example: ["0000320193"] → "320193"
            ciks_list = source_data.get("ciks", [])
            cik = str(ciks_list[0]).lstrip("0") if ciks_list else ""

            # Dedup key: accession number alone is sufficient — EFTS has one entry
            # per filing (no per-document entries), so there is no file_name to
            # include in the hash.  The old code concatenated an always-empty
            # file_name, making the hash equivalent to hash(accession_no) anyway.
            filing_hash = url_hash(accession_no)

            if self._exists_fn is not None and await self._exists_fn(filing_hash):
                logger.debug("sec_edgar_dedup_skip", url_hash=filing_hash[:12])
                continue

            # BP-460: Construct the EDGAR filing index URL.
            # Format: https://www.sec.gov/Archives/edgar/data/{cik}/{acc_no_dashes}/{acc_no_dashes}-index.htm
            # where {cik} has no leading zeros and {acc_no_dashes} has no dashes.
            # Example:
            #   CIK 320193, adsh "0001477932-26-002885"
            #   → https://www.sec.gov/Archives/edgar/data/320193/000147793226002885/0001477932-26-002885-index.htm
            acc_no_no_dashes = accession_no.replace("-", "")
            filing_url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc_no_no_dashes}/{accession_no}-index.htm"

            try:
                # Fetch the index page for this filing as the raw document bytes.
                # The filename for the index page follows the standard EDGAR pattern.
                index_filename = f"{accession_no}-index.htm"
                raw_bytes = await self._retry_request(
                    lambda _an=accession_no, _fn=index_filename, _cik=cik: self._client.fetch_filing_document(
                        cik=_cik,
                        accession_no=_an,
                        filename=_fn,
                    ),
                    retry_config=self._retry_config,
                    context=f"sec_edgar:doc:{accession_no}",
                )
            except Exception:
                logger.warning("sec_edgar_doc_fetch_failed", accession_no=accession_no)
                continue

            published_at = _parse_published_at(filing)

            results.append(
                FetchResult(
                    source_id=source.id,
                    url=filing_url,
                    url_hash=filing_hash,
                    raw_bytes=raw_bytes if isinstance(raw_bytes, bytes) else b"",
                    fetched_at=common.time.utc_now(),
                    http_status=200,
                    content_type="text/html",
                    published_at=published_at,
                    is_backfill=is_backfill,
                ),
            )

        logger.info("sec_edgar_fetch_complete", total_filings=len(filings), new=len(results))
        return results
