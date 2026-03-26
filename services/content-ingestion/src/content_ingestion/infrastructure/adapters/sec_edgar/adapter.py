"""SEC EDGAR source adapter — fetches filings via EFTS search.

Rate limit: asyncio.Semaphore(8) for 8 concurrent requests.
Dedup: sha256(accession_number + filename).
Retry: 3x with 1s/2s/4s exponential backoff.
User-Agent: Required by SEC policy (ConfigurationError if missing).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import common.ids
import common.time
from content_ingestion.domain.entities import FetchResult
from content_ingestion.infrastructure.adapters.base import RetryConfig, SourceAdapter, url_hash
from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from content_ingestion.domain.entities import Source
    from content_ingestion.infrastructure.adapters.sec_edgar.client import SECEdgarClient

logger = get_logger(__name__)  # type: ignore[no-any-return]


def _parse_published_at(filing: dict[str, Any]) -> datetime | None:
    """Extract published_at from ``period_of_report`` or ``file_date``."""
    source = filing.get("_source", filing)
    for field in ("period_of_report", "file_date"):
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
    """

    def __init__(
        self,
        client: SECEdgarClient,
        exists_fn: Any = None,
        retry_config: RetryConfig | None = None,
    ) -> None:
        self._client = client
        self._exists_fn = exists_fn
        self._retry_config = retry_config or RetryConfig()

    async def fetch(self, source: Source, *, is_backfill: bool = False) -> list[FetchResult]:
        """Fetch and deduplicate SEC EDGAR filings.

        For each filing:
        1. Compute ``url_hash = sha256(accession_number + filename)``
        2. Skip if exists_fn returns True
        3. Fetch filing HTML/XBRL document
        4. Build FetchResult with raw document bytes
        """
        config = source.config
        from_date = config.get("from_date", "")
        to_date = config.get("to_date", "")
        forms = config.get("forms", "10-K,10-Q,8-K,DEF14A")

        filings = await self._retry_request(
            lambda: self._client.search_filings(from_date=from_date, to_date=to_date, forms=forms),
            retry_config=self._retry_config,
            context="sec_edgar:search",
        )
        if not isinstance(filings, list):
            return []

        results: list[FetchResult] = []
        for filing in filings:
            source_data = filing.get("_source", filing)
            accession_no = source_data.get("accession_no", "")
            file_name = source_data.get("file_name", "")
            if not accession_no:
                continue

            filing_hash = url_hash(f"{accession_no}{file_name}")

            if self._exists_fn is not None and await self._exists_fn(filing_hash):
                logger.debug("sec_edgar_dedup_skip", url_hash=filing_hash[:12])
                continue

            cik = str(source_data.get("cik", ""))
            filing_url = (
                f"https://www.sec.gov/Archives/edgar/data/" f"{cik}/{accession_no.replace('-', '')}/{file_name}"
            )

            try:
                raw_bytes = await self._retry_request(
                    lambda _an=accession_no, _fn=file_name, _cik=cik: (
                        self._client.fetch_filing_document(cik=_cik, accession_no=_an, filename=_fn)
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
                )
            )

        logger.info("sec_edgar_fetch_complete", total_filings=len(filings), new=len(results))
        return results
