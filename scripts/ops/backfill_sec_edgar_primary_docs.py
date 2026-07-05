"""Backfill primary-document text + citation title for existing ``sec_edgar`` docs.

Problem
-------
R1 root cause (docs/audits/2026-07-04-sec-filings-ingestion-storage-gap.md): the
SEC EDGAR adapter historically fetched only the filing's ``…-index.htm`` directory
page (~40 words of filer/form/CIK/SIC boilerplate) instead of the actual filing.
Every one of the ~4,953 stored ``sec_edgar`` documents therefore has:

  - ``word_count`` ≈ 43 (index-page blurb, nothing groundable), and
  - ``title = NULL`` (the index page carries no usable title).

Chat can *find* and *link* these filings but cannot ground or cite them.

The ingestion adapter is now fixed forward (fetches the PRIMARY document via the
``index.json`` manifest and synthesizes a title). This script re-drives the
EXISTING defective docs through the fixed pipeline.

Strategy — re-drive via the outbox (R5-compliant)
-------------------------------------------------
For each defective ``sec_edgar`` document we:

  1. Parse ``{cik, accession}`` from its stored index URL.
  2. Fetch the filing's ``index.json`` manifest and resolve the PRIMARY document
     (largest form-matching ``.htm``, excluding XBRL/viewer/exhibit files) — the
     exact same logic the fixed adapter uses (imported, not duplicated).
  3. Download the primary document HTML.
  4. Synthesize a title ``"{FORM} — {Company} ({Period})"``.
  5. (--apply) Upload the primary HTML to the bronze bucket and INSERT a fresh
     ``content.article.raw.v1`` row into ``outbox_events`` with a NEW ``doc_id``.
     The already-running outbox dispatcher publishes it; content-store →
     nlp-pipeline then produce a correct, groundable, citable document.

The new doc supersedes the old one for retrieval (it carries real narrative and a
non-null title, so the learned router and trust scorer rank it properly). Purging
the old index-page docs is a SEPARATE, operator-controlled step (delete
``sec_edgar`` rows with ``word_count < 200`` across content_store_db / nlp_db once
the backfilled docs are verified) and is intentionally NOT done here.

SEC fair-access
---------------
SEC caps clients at 10 req/s and REQUIRES a descriptive User-Agent. This script
issues at most 2 requests per filing (manifest + primary doc) and throttles to
``--rate`` requests/second (default 5, well under the cap) via an async limiter.
Set ``CONTENT_INGESTION_SEC_EDGAR_USER_AGENT`` (e.g. ``"worldview/1.0 you@example.com"``; unprefixed ``SEC_EDGAR_USER_AGENT`` also accepted).

Idempotency
-----------
``--state-file`` (default ``.sec_backfill_state.json``) records completed
accession numbers. Re-running skips them, so a crashed run resumes safely and a
completed filing is never double-emitted.

Usage
-----
    # Preview: fetch + resolve the primary doc for the first 20 defective docs,
    # print old-vs-new (word count, title) — NO writes:
    python scripts/ops/backfill_sec_edgar_primary_docs.py --limit 20

    # Apply for a bounded batch:
    python scripts/ops/backfill_sec_edgar_primary_docs.py --apply --limit 500

    # Full apply (operator runs after deploy):
    python scripts/ops/backfill_sec_edgar_primary_docs.py --apply

Environment
-----------
    CONTENT_STORE_DB_URL     (default: postgresql+asyncpg://postgres:postgres@localhost:5432/content_store_db)
    CONTENT_INGESTION_DB_URL (default: postgresql+asyncpg://postgres:postgres@localhost:5432/content_ingestion_db)
    CONTENT_INGESTION_SEC_EDGAR_USER_AGENT  (REQUIRED for --apply; unprefixed SEC_EDGAR_USER_AGENT also accepted; SEC rejects requests without it)
    Storage (MinIO/S3) config is read from the standard ``STORAGE_*`` env vars
    used by ``storage.settings.StorageSettings``.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
import re
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import structlog
from content_ingestion.application.use_cases.fetch_and_write import build_raw_article_payload
from content_ingestion.config import SECEdgarProviderSettings
from content_ingestion.infrastructure.adapters.base import url_hash
from content_ingestion.infrastructure.adapters.sec_edgar.adapter import (
    _synthesize_title,
    resolve_primary_document,
)
from content_ingestion.infrastructure.adapters.sec_edgar.client import SECEdgarClient
from content_ingestion.infrastructure.storage.minio_bronze import MinioBronzeAdapter
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import common.ids
import common.time as ct
from storage.factory import build_object_storage  # type: ignore[import-untyped]

log: Any = structlog.get_logger(__name__)  # type: ignore[no-any-return]

_DEFAULT_CS_URL = "postgresql+asyncpg://postgres:postgres@localhost:5432/content_store_db"
_DEFAULT_CI_URL = "postgresql+asyncpg://postgres:postgres@localhost:5432/content_ingestion_db"
_DEFAULT_STATE_FILE = ".sec_backfill_state.json"

# A doc is "defective" (index-page-only) if it has no usable narrative/title.
# 200 words is a conservative floor: real filings run into the thousands, index
# pages ~40. NULL title is the other tell.
_DEFECT_WORD_FLOOR = 200

# Issue #4: the content-ingestion service reads its SEC User-Agent from the
# pydantic-settings-PREFIXED env var (Settings.sec_edgar_user_agent,
# env_prefix="CONTENT_INGESTION_"). This standalone ops script must use the SAME
# source of truth, else SEC's WAF 403s every request. Fall back to the unprefixed
# name for flexibility. NOT reading Settings() directly on purpose: its non-empty
# default would mask the "neither set" case and break the --apply guard.
_UA_ENV_PRIMARY = "CONTENT_INGESTION_SEC_EDGAR_USER_AGENT"
_UA_ENV_FALLBACK = "SEC_EDGAR_USER_AGENT"


def resolve_user_agent(env: Mapping[str, str]) -> str:
    """Return the SEC User-Agent from the prefixed env var, else the unprefixed, else ''."""
    for name in (_UA_ENV_PRIMARY, _UA_ENV_FALLBACK):
        value = env.get(name, "").strip()
        if value:
            return value
    return ""


# Parse CIK + accession from the stored index URL:
#   https://www.sec.gov/Archives/edgar/data/320193/000147793226002885/0001477932-26-002885-index.htm
_URL_RE = re.compile(r"/edgar/data/(\d+)/[0-9]+/([0-9-]+)-index\.htm", re.IGNORECASE)


@dataclass(frozen=True)
class DefectiveDoc:
    doc_id: str
    source_url: str
    cik: str
    accession: str
    published_at: Any  # datetime | None


class _RateLimiter:
    """Simple async rate limiter: at most ``rate`` acquisitions per second."""

    def __init__(self, rate: float) -> None:
        self._min_interval = 1.0 / rate if rate > 0 else 0.0
        self._lock = asyncio.Lock()
        self._last = 0.0

    async def acquire(self) -> None:
        async with self._lock:
            now = time.monotonic()
            wait = self._min_interval - (now - self._last)
            if wait > 0:
                await asyncio.sleep(wait)
            self._last = time.monotonic()


def _load_state(path: Path) -> set[str]:
    if not path.exists():
        return set()
    with contextlib.suppress(json.JSONDecodeError, OSError):
        data = json.loads(path.read_text())
        return set(data.get("completed_accessions", []))
    return set()


def _save_state(path: Path, completed: set[str]) -> None:
    path.write_text(json.dumps({"completed_accessions": sorted(completed)}, indent=0))


async def _load_defective_docs(cs_session: AsyncSession, limit: int | None) -> list[DefectiveDoc]:
    """Load ``sec_edgar`` docs that still carry only the index-page blurb."""
    sql = (
        "SELECT doc_id::text, source_url, published_at, word_count "
        "FROM documents "
        "WHERE source_type = 'sec_edgar' "
        "  AND source_url IS NOT NULL "
        "  AND (title IS NULL OR word_count IS NULL OR word_count < :floor) "
        "ORDER BY published_at DESC NULLS LAST"
    )
    if limit is not None:
        sql += " LIMIT :limit"
    params: dict[str, Any] = {"floor": _DEFECT_WORD_FLOOR}
    if limit is not None:
        params["limit"] = limit

    result = await cs_session.execute(text(sql), params)
    docs: list[DefectiveDoc] = []
    for row in result.fetchall():
        doc_id, source_url, published_at, _wc = row
        match = _URL_RE.search(str(source_url))
        if not match:
            log.warning("backfill.url_unparseable", doc_id=doc_id, url=source_url)
            continue
        cik = match.group(1).lstrip("0") or "0"
        accession = match.group(2)
        docs.append(
            DefectiveDoc(
                doc_id=doc_id,
                source_url=str(source_url),
                cik=cik,
                accession=accession,
                published_at=published_at,
            )
        )
    return docs


def _primary_item_type(manifest: dict[str, Any], primary_name: str) -> str:
    """Look up the manifest ``type`` for the resolved primary filename (for the title)."""
    for item in manifest.get("directory", {}).get("item", []):
        if isinstance(item, dict) and str(item.get("name", "")) == primary_name:
            return str(item.get("type", "")).strip()
    return ""


async def _process_one(
    doc: DefectiveDoc,
    *,
    client: SECEdgarClient,
    limiter: _RateLimiter,
    company_cache: dict[str, str],
    http_client: httpx.AsyncClient,
    user_agent: str,
) -> tuple[bytes, str | None] | None:
    """Fetch the primary doc + synthesize a title. Returns (bytes, title) or None."""
    await limiter.acquire()
    manifest = await client.fetch_filing_manifest(cik=doc.cik, accession_no=doc.accession)
    primary = resolve_primary_document(manifest, form_type="", accession_no=doc.accession)
    if not primary:
        log.warning("backfill.no_primary_doc", accession=doc.accession, cik=doc.cik)
        return None

    await limiter.acquire()
    raw_bytes = await client.fetch_filing_document(cik=doc.cik, accession_no=doc.accession, filename=primary)

    form = _primary_item_type(manifest, primary)
    company = await _resolve_company(doc.cik, company_cache, http_client, user_agent, limiter)
    period = doc.published_at.date().isoformat() if doc.published_at is not None else ""
    synthetic = {"entity_name": company, "period_ending": period}
    title = _synthesize_title(synthetic, form)
    return raw_bytes, title


async def _resolve_company(
    cik: str,
    cache: dict[str, str],
    http_client: httpx.AsyncClient,
    user_agent: str,
    limiter: _RateLimiter,
) -> str:
    """Resolve a filer's company name from the SEC submissions API (cached per CIK)."""
    if cik in cache:
        return cache[cik]
    name = ""
    with contextlib.suppress(Exception):
        await limiter.acquire()
        url = f"https://data.sec.gov/submissions/CIK{cik.zfill(10)}.json"
        resp = await http_client.get(url, headers={"User-Agent": user_agent})
        if resp.status_code < 400:
            name = str(resp.json().get("name", "") or "")
    cache[cik] = name
    return name


async def _apply_one(
    doc: DefectiveDoc,
    raw_bytes: bytes,
    title: str | None,
    *,
    bronze: MinioBronzeAdapter,
    ci_session: AsyncSession,
) -> None:
    """Upload primary HTML to bronze + INSERT a fresh raw-article outbox event."""
    # A distinct url_hash so the backfilled object never collides with the old
    # index-page bronze object or the old fetch_log dedup row.
    new_hash = url_hash(f"{doc.accession}:primary")
    published_iso = ct.to_iso8601(doc.published_at) if doc.published_at is not None else None
    minio_key = await bronze.put_object(
        source_type="sec_edgar",
        url_hash=new_hash,
        raw_bytes=raw_bytes,
        url=doc.source_url,
        fetched_at=ct.to_iso8601(ct.utc_now()),
        published_at=published_iso,
        is_backfill=True,
    )
    new_doc_id = common.ids.new_uuid7()
    payload = build_raw_article_payload(
        doc_id=new_doc_id,
        source_type="sec_edgar",
        source_url=doc.source_url,
        minio_bronze_key=minio_key,
        raw_bytes=raw_bytes,
        fetch_id=common.ids.new_uuid7(),
        published_at=published_iso,
        is_backfill=True,
        title=title,
    )
    await ci_session.execute(
        text(
            "INSERT INTO outbox_events (id, aggregate_type, aggregate_id, event_type, topic, payload, status) "
            "VALUES (:id, 'article', :agg, 'content.article.raw', 'content.article.raw.v1', "
            "CAST(:payload AS JSONB), 'pending')"
        ),
        {
            "id": str(common.ids.new_uuid7()),
            "agg": str(new_doc_id),
            "payload": json.dumps(payload),
        },
    )
    await ci_session.commit()


async def _run(args: argparse.Namespace) -> None:
    user_agent = resolve_user_agent(os.environ)
    if args.apply and not user_agent:
        raise SystemExit(
            "CONTENT_INGESTION_SEC_EDGAR_USER_AGENT (or SEC_EDGAR_USER_AGENT) must be set for "
            "--apply (SEC rejects requests without a compliant User-Agent).",
        )
    # Dry-run still hits SEC; use a placeholder UA if none provided.
    effective_ua = user_agent or "worldview-backfill/1.0 (dry-run)"

    state_path = Path(args.state_file)
    completed = _load_state(state_path)

    cs_engine = create_async_engine(os.environ.get("CONTENT_STORE_DB_URL", _DEFAULT_CS_URL))
    ci_engine = create_async_engine(os.environ.get("CONTENT_INGESTION_DB_URL", _DEFAULT_CI_URL))
    cs_sf = async_sessionmaker(cs_engine, expire_on_commit=False)
    ci_sf = async_sessionmaker(ci_engine, expire_on_commit=False)

    limiter = _RateLimiter(args.rate)
    company_cache: dict[str, str] = {}
    stats = {"scanned": 0, "skipped_done": 0, "no_primary": 0, "fetched": 0, "applied": 0, "errors": 0}

    bronze: MinioBronzeAdapter | None = None
    if args.apply:
        bronze = MinioBronzeAdapter(build_object_storage())

    async with cs_sf() as cs_session:
        docs = await _load_defective_docs(cs_session, args.limit)

    log.info("backfill.loaded", total=len(docs), apply=args.apply, rate=args.rate)

    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=5.0)) as http_client:
        client = SECEdgarClient(
            http_client=http_client,
            user_agent=effective_ua,
            provider_cfg=SECEdgarProviderSettings(),
        )
        for doc in docs:
            stats["scanned"] += 1
            if doc.accession in completed:
                stats["skipped_done"] += 1
                continue
            try:
                outcome = await _process_one(
                    doc,
                    client=client,
                    limiter=limiter,
                    company_cache=company_cache,
                    http_client=http_client,
                    user_agent=effective_ua,
                )
            except Exception as exc:
                stats["errors"] += 1
                log.error("backfill.fetch_failed", accession=doc.accession, error=str(exc))
                continue

            if outcome is None:
                stats["no_primary"] += 1
                continue
            raw_bytes, title = outcome
            stats["fetched"] += 1

            if not args.apply:
                log.info(
                    "backfill.dry_run",
                    accession=doc.accession,
                    cik=doc.cik,
                    new_word_count=len(raw_bytes.split()),
                    new_title=title,
                )
                continue

            try:
                assert bronze is not None
                async with ci_sf() as ci_session:
                    await _apply_one(doc, raw_bytes, title, bronze=bronze, ci_session=ci_session)
                stats["applied"] += 1
                completed.add(doc.accession)
                if stats["applied"] % args.batch_size == 0:
                    _save_state(state_path, completed)
                    log.info("backfill.progress", **stats)
            except Exception as exc:
                stats["errors"] += 1
                log.error("backfill.apply_failed", accession=doc.accession, error=str(exc))

    if args.apply:
        _save_state(state_path, completed)
    await cs_engine.dispose()
    await ci_engine.dispose()
    log.info("backfill.complete", **stats)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--apply", action="store_true", help="Write bronze objects + outbox events (default: dry-run).")
    p.add_argument("--limit", type=int, default=None, help="Process at most N defective docs (default: all).")
    p.add_argument("--rate", type=float, default=5.0, help="Max SEC requests/second (SEC cap is 10; default 5).")
    p.add_argument("--batch-size", type=int, default=50, help="Persist state every N applied docs (default: 50).")
    p.add_argument("--state-file", default=_DEFAULT_STATE_FILE, help="Resume/idempotency state file.")
    return p.parse_args()


if __name__ == "__main__":
    asyncio.run(_run(_parse_args()))
