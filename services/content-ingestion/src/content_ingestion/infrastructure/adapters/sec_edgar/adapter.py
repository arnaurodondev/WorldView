"""SEC EDGAR source adapter — fetches filings via EFTS search.

Rate limit: asyncio.Semaphore(8) for 8 concurrent requests.
Dedup: sha256(accession_number + filename).
Retry: 3x with 1s/2s/4s exponential backoff.
User-Agent: Required by SEC policy (ConfigurationError if missing).
"""

from __future__ import annotations

import re
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

# XBRL R-viewer files: ``R1.htm``, ``R23.htm`` … — machine-generated financial
# statement viewers, NOT the filing narrative.  Must be excluded from primary-doc
# resolution.
_R_VIEWER_RE = re.compile(r"^R\d+\.htm", re.IGNORECASE)

# XBRL linkbase / taxonomy filename stems: ``…_cal``, ``…_def``, ``…_lab``,
# ``…_pre``, ``…_ref`` (calculation / definition / label / presentation / reference).
_XBRL_STEM_SUFFIXES = ("_cal", "_def", "_lab", "_pre", "_ref")


def _is_xbrl_or_viewer(name: str) -> bool:
    """Return True if *name* is an XBRL/taxonomy/viewer artefact, not the filing body.

    Excludes:
      - ``.xml`` / ``.xsd`` / ``.json`` (XBRL instance, schema, manifest)
      - ``R\\d+.htm`` (financial-statement R-viewer pages)
      - ``*_cal/def/lab/pre/ref.htm`` (XBRL linkbase HTML)
    """
    lower = name.lower()
    if lower.endswith((".xml", ".xsd", ".json")):
        return True
    if _R_VIEWER_RE.match(name):
        return True
    stem = lower.rsplit(".", 1)[0]
    return any(stem.endswith(sfx) for sfx in _XBRL_STEM_SUFFIXES)


def _filing_form(source_data: dict[str, Any]) -> str:
    """Best-effort extraction of the form type (e.g. ``10-K``) from an EFTS hit."""
    raw = source_data.get("form_type") or source_data.get("file_type") or ""
    if not raw:
        roots = source_data.get("root_forms")
        if isinstance(roots, list) and roots:
            raw = str(roots[0])
    return str(raw).strip()


def resolve_primary_document(
    manifest: dict[str, Any],
    *,
    form_type: str,
    accession_no: str,
) -> str | None:
    """Resolve the primary filing document filename from an EDGAR ``index.json`` manifest.

    Selection rules (R1 Fix ①):
      1. Consider only ``.htm``/``.html`` items.
      2. Exclude the ``…-index.htm`` directory page itself.
      3. Exclude XBRL instance/linkbase/viewer artefacts (:func:`_is_xbrl_or_viewer`).
      4. Prefer items whose manifest ``type`` matches the requested ``form_type``
         (e.g. type ``10-K`` for a 10-K filing) — this skips exhibits (EX-*).
      5. Among the preferred pool, pick the LARGEST by ``size`` (the narrative is
         invariably the biggest HTML document); tie-break by name for determinism.

    Returns the filename, or ``None`` when no suitable HTML document exists (e.g. a
    text-only filing) so the caller can skip rather than store boilerplate.
    """
    directory = manifest.get("directory") or {}
    items = directory.get("item") or []
    if not isinstance(items, list):
        return None

    index_name = f"{accession_no}-index.htm".lower()
    form_norm = (form_type or "").strip().upper()

    candidates: list[tuple[str, str, int]] = []  # (name, type, size)
    for item in items:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        if not name or not name.lower().endswith((".htm", ".html")):
            continue
        if name.lower() == index_name:
            continue
        if _is_xbrl_or_viewer(name):
            continue
        try:
            size = int(item.get("size") or 0)
        except (TypeError, ValueError):
            size = 0
        candidates.append((name, str(item.get("type", "")).strip(), size))

    if not candidates:
        return None

    def _type_matches(item_type: str) -> bool:
        t = item_type.strip().upper()
        return bool(form_norm) and (t == form_norm or t.startswith(form_norm))

    typed = [c for c in candidates if _type_matches(c[1])]
    pool = typed or candidates
    # Largest HTML document = the filing narrative. Descending size, then name.
    pool.sort(key=lambda c: (c[2], c[0]), reverse=True)
    return pool[0][0]


def _synthesize_title(source_data: dict[str, Any], form_type: str) -> str | None:
    """Synthesize a citation title ``"{FORM} — {Company} ({Period})"``.

    The EDGAR index page carries no usable title (dsm.title was NULL for 100 % of
    ``sec_edgar`` docs — R1 root cause), so we compose one from fields the EFTS hit
    already provides. ``display_names`` looks like ``"Apple Inc. (AAPL) (CIK 0000320193)"``;
    we strip the trailing ``(TICKER) (CIK …)`` parentheticals to get the company name.
    Falls back to ``entity_name`` / ``entity``. Returns ``None`` only when neither a
    form nor a company name is available.
    """
    company = ""
    display_names = source_data.get("display_names")
    if isinstance(display_names, list) and display_names:
        company = str(display_names[0])
    if not company:
        company = str(source_data.get("entity_name") or source_data.get("entity") or "")
    # Strip "(AAPL) (CIK 0000320193)" style parentheticals from display_names.
    company = re.sub(r"\s*\((?:CIK\s*)?[^)]*\)\s*$", "", company).strip()
    company = re.sub(r"\s*\([^)]*\)\s*$", "", company).strip()

    period = str(source_data.get("period_ending") or source_data.get("file_date") or "").strip()
    form = (form_type or "").strip()

    if not form and not company:
        return None
    head = " — ".join(p for p in (form, company) if p)
    return f"{head} ({period})" if period else head


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

        # Coverage fix (R1 Fix ②): an unscoped EFTS search returns only the most
        # recent filings across ALL filers (date-sorted), so a watched company such
        # as Apple is essentially never ingested — its filings are diluted out. When
        # the source config carries a ``ciks`` watchlist, scope the search PER CIK so
        # every watched company's filings are pulled. ``ciks`` may be a list or a
        # comma-separated string of zero-padded 10-digit CIKs. Empty ⇒ legacy global
        # search (backward compatible).
        watchlist = self._parse_ciks(config.get("ciks"))

        filings: list[dict[str, Any]] = []
        if watchlist:
            for cik_scope in watchlist:
                scoped = await self._retry_request(
                    lambda _c=cik_scope: self._client.search_filings(
                        from_date=effective_from,
                        to_date=to_date,
                        forms=forms,
                        ciks=_c,
                    ),
                    retry_config=self._retry_config,
                    context=f"sec_edgar:search:{cik_scope}",
                )
                if isinstance(scoped, list):
                    filings.extend(scoped)
        else:
            searched = await self._retry_request(
                lambda: self._client.search_filings(from_date=effective_from, to_date=to_date, forms=forms),
                retry_config=self._retry_config,
                context="sec_edgar:search",
            )
            if isinstance(searched, list):
                filings = searched

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

            form_type = _filing_form(source_data)

            try:
                # R1 Fix ①: resolve and fetch the PRIMARY filing document (the actual
                # 10-K/10-Q/8-K narrative) via the filing's index.json manifest — NOT
                # the ~40-word ``…-index.htm`` directory page (the old bug).
                manifest = await self._retry_request(
                    lambda _an=accession_no, _cik=cik: self._client.fetch_filing_manifest(
                        cik=_cik,
                        accession_no=_an,
                    ),
                    retry_config=self._retry_config,
                    context=f"sec_edgar:manifest:{accession_no}",
                )
                primary_filename = resolve_primary_document(
                    manifest if isinstance(manifest, dict) else {},
                    form_type=form_type,
                    accession_no=accession_no,
                )
                if not primary_filename:
                    # No groundable HTML body (e.g. a text-only filing). Skip rather
                    # than store index-page boilerplate that chat cannot ground/cite.
                    logger.warning("sec_edgar_no_primary_doc", accession_no=accession_no, form_type=form_type)
                    continue

                raw_bytes = await self._retry_request(
                    lambda _an=accession_no, _fn=primary_filename, _cik=cik: self._client.fetch_filing_document(
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
            # Synthesize a citation title so dsm.title stops being NULL for sec_edgar.
            title = _synthesize_title(source_data, form_type)

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
                    title=title,
                ),
            )

        logger.info("sec_edgar_fetch_complete", total_filings=len(filings), new=len(results))
        return results

    @staticmethod
    def _parse_ciks(raw: Any) -> list[str]:
        """Normalise a ``ciks`` config value into a list of zero-padded 10-digit CIKs.

        Accepts a list of str/int or a comma-separated string. Each CIK is stripped,
        digit-validated, and left-padded to EDGAR's canonical 10-digit form. Invalid
        or empty entries are dropped.
        """
        if raw is None:
            return []
        items: list[Any]
        if isinstance(raw, str):
            items = raw.split(",")
        elif isinstance(raw, list | tuple):
            items = list(raw)
        else:
            items = [raw]
        out: list[str] = []
        for item in items:
            raw_str = str(item).strip()
            if not raw_str:
                continue
            digits = raw_str.lstrip("0") or "0"
            if not digits.isdigit():
                continue
            out.append(digits.zfill(10))
        return out
