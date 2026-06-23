"""Integration tests for per-tenant dedup isolation in S5 (PLAN-0086 Wave C-1).

Validates that Stage A (raw hash) / Stage B (normalized hash) dedup is scoped by
``tenant_id``: identical content stored under two distinct tenants must be retained
independently, while the same tenant re-submitting identical content is suppressed.

Requires live PostgreSQL + MinIO + Valkey. The shared ``conftest`` fixtures
(``session_factory``, ``minio_storage``, ``lsh_client``) skip automatically when
infra is unavailable, so these are safe to collect in any harness.

Run with: pytest -m integration
"""

from __future__ import annotations

import hashlib
import json
from uuid import UUID

import pytest
from content_store.application.use_cases.process_article import ProcessArticleUseCase, RawArticleEvent
from content_store.infrastructure.db.models import DocumentModel
from content_store.infrastructure.db.repositories.dedup import DedupHashRepository
from content_store.infrastructure.db.repositories.document import DocumentRepository
from content_store.infrastructure.db.repositories.minhash import MinHashRepository
from content_store.infrastructure.db.repositories.outbox import OutboxRepository
from content_store.infrastructure.storage.minio_bronze import BronzeStorageAdapter
from content_store.infrastructure.storage.minio_silver import SilverStorageAdapter
from sqlalchemy import func, select

import common.ids  # type: ignore[import-untyped]

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


# A fixed tenant pair for the isolation assertions. UUIDs are arbitrary but stable.
_TENANT_A = "11111111-1111-1111-1111-111111111111"
_TENANT_B = "22222222-2222-2222-2222-222222222222"


async def _put_bronze(storage, bucket: str, key: str, raw_bytes: bytes) -> None:
    """Write an S4-style raw envelope to the bronze bucket."""
    envelope = json.dumps({"content_type": "text/html", "body": raw_bytes.decode(errors="replace")}).encode()
    await storage.put_bytes(bucket, key, envelope)


async def _process(
    session,
    storage,
    lsh_client,
    bronze_bucket: str,
    silver_bucket: str,
    html: str,
    *,
    tenant_id: str | None,
    source: str = "eodhd",
    url: str = "https://example.com/tenant-dedup",
):
    """Process a single article through the full pipeline under a tenant scope."""
    raw_bytes = html.encode()
    content_hash = hashlib.sha256(raw_bytes).hexdigest()
    # Bronze key includes tenant so two tenants' identical content live at distinct keys.
    key = f"content-ingestion/{source}/{tenant_id or 'public'}/{content_hash}/raw/v1.json"
    await _put_bronze(storage, bronze_bucket, key, raw_bytes)

    article = RawArticleEvent(
        event_id=str(common.ids.new_uuid7()),
        doc_id=str(common.ids.new_uuid7()),
        source_type=source,
        source_url=url,
        minio_bronze_key=key,
        content_hash=content_hash,
        title="Tenant Dedup Test",
        published_at="2026-03-27T10:00:00Z",
        is_backfill=False,
        tenant_id=tenant_id,
    )

    use_case = ProcessArticleUseCase(
        document_repo=DocumentRepository(session),
        dedup_repo=DedupHashRepository(session),
        minhash_repo=MinHashRepository(session),
        outbox_repo=OutboxRepository(session),
        bronze_store=BronzeStorageAdapter(storage, bronze_bucket),
        bronze_bucket=bronze_bucket,
        silver_storage=SilverStorageAdapter(storage, silver_bucket),
        lsh_client=lsh_client,
        num_perm=128,
    )
    return await use_case.execute(article)


async def test_global_dedup_still_works(session_factory, minio_storage, lsh_client):
    """Same public (tenant_id=None) content twice → second suppressed (global dedup intact)."""
    from tests.integration.conftest import TEST_MINIO_BRONZE_BUCKET, TEST_MINIO_SILVER_BUCKET

    html = "<html><body><p>Public market wrap: indices close higher on rate optimism</p></body></html>"
    bb, sb = TEST_MINIO_BRONZE_BUCKET, TEST_MINIO_SILVER_BUCKET

    async with session_factory() as session:
        s1 = await _process(session, minio_storage, lsh_client, bb, sb, html, tenant_id=None)
        await session.commit()
    assert not s1.suppressed

    async with session_factory() as session:
        s2 = await _process(session, minio_storage, lsh_client, bb, sb, html, tenant_id=None)
        await session.commit()
    assert s2.suppressed
    assert "duplicate" in s2.decision.outcome.lower()

    async with session_factory() as session:
        count = await session.execute(select(func.count()).select_from(DocumentModel))
        assert count.scalar() == 1


async def test_per_tenant_dedup_same_content(session_factory, minio_storage, lsh_client):
    """Tenant A stores doc X; tenant A re-submits same content → suppressed within the tenant."""
    from tests.integration.conftest import TEST_MINIO_BRONZE_BUCKET, TEST_MINIO_SILVER_BUCKET

    html = "<html><body><p>Private research note on portfolio rebalancing strategy Q2</p></body></html>"
    bb, sb = TEST_MINIO_BRONZE_BUCKET, TEST_MINIO_SILVER_BUCKET

    async with session_factory() as session:
        s1 = await _process(session, minio_storage, lsh_client, bb, sb, html, tenant_id=_TENANT_A)
        await session.commit()
    assert not s1.suppressed

    async with session_factory() as session:
        s2 = await _process(session, minio_storage, lsh_client, bb, sb, html, tenant_id=_TENANT_A)
        await session.commit()
    assert s2.suppressed

    async with session_factory() as session:
        count = await session.execute(
            select(func.count()).select_from(DocumentModel).where(DocumentModel.tenant_id == UUID(_TENANT_A))
        )
        assert count.scalar() == 1


async def test_per_tenant_dedup_different_tenants(session_factory, minio_storage, lsh_client):
    """Tenant A and tenant B submit byte-identical content → BOTH stored (independent dedup)."""
    from tests.integration.conftest import TEST_MINIO_BRONZE_BUCKET, TEST_MINIO_SILVER_BUCKET

    html = "<html><body><p>Shared headline both tenants ingest about earnings season open</p></body></html>"
    bb, sb = TEST_MINIO_BRONZE_BUCKET, TEST_MINIO_SILVER_BUCKET

    async with session_factory() as session:
        sa = await _process(session, minio_storage, lsh_client, bb, sb, html, tenant_id=_TENANT_A)
        await session.commit()
    assert not sa.suppressed

    async with session_factory() as session:
        sb_summary = await _process(session, minio_storage, lsh_client, bb, sb, html, tenant_id=_TENANT_B)
        await session.commit()
    # Cross-tenant identical content must NOT be suppressed by another tenant's hash.
    assert not sb_summary.suppressed

    async with session_factory() as session:
        total = await session.execute(select(func.count()).select_from(DocumentModel))
        assert total.scalar() == 2
        a_count = await session.execute(
            select(func.count()).select_from(DocumentModel).where(DocumentModel.tenant_id == UUID(_TENANT_A))
        )
        b_count = await session.execute(
            select(func.count()).select_from(DocumentModel).where(DocumentModel.tenant_id == UUID(_TENANT_B))
        )
        assert a_count.scalar() == 1
        assert b_count.scalar() == 1


async def test_existing_rows_null_tenant_isolated_from_tenant_scoped(session_factory, minio_storage, lsh_client):
    """A public (NULL-tenant) doc must not suppress a tenant-scoped near/exact copy and vice-versa.

    Migration 0005 leaves pre-existing rows with tenant_id = NULL; this asserts the
    NULL scope is treated as a distinct dedup partition from any concrete tenant.
    """
    from tests.integration.conftest import TEST_MINIO_BRONZE_BUCKET, TEST_MINIO_SILVER_BUCKET

    html = "<html><body><p>Identical body that exists publicly and privately under tenant A</p></body></html>"
    bb, sb = TEST_MINIO_BRONZE_BUCKET, TEST_MINIO_SILVER_BUCKET

    # Public ingest first (tenant_id = None, mirroring legacy migration-0005 rows).
    async with session_factory() as session:
        s_public = await _process(session, minio_storage, lsh_client, bb, sb, html, tenant_id=None)
        await session.commit()
    assert not s_public.suppressed

    # Same content under a concrete tenant must still be stored (different dedup partition).
    async with session_factory() as session:
        s_tenant = await _process(session, minio_storage, lsh_client, bb, sb, html, tenant_id=_TENANT_A)
        await session.commit()
    assert not s_tenant.suppressed

    async with session_factory() as session:
        total = await session.execute(select(func.count()).select_from(DocumentModel))
        assert total.scalar() == 2
        null_count = await session.execute(
            select(func.count()).select_from(DocumentModel).where(DocumentModel.tenant_id.is_(None))
        )
        assert null_count.scalar() == 1
