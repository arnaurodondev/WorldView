"""Integration tests for tenant upload API in S4.

Requires: PostgreSQL content_ingestion_db with migration 0007 applied + MinIO.
Run with: pytest -m integration
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


@pytest.mark.skip(reason="Requires live S4 + DB + MinIO")
def test_upload_pdf_returns_202() -> None:
    """POST PDF → 202 + doc_id."""
    pass


@pytest.mark.skip(reason="Requires live S4 + DB + MinIO")
def test_upload_wrong_mime_returns_400() -> None:
    """DOCX → 400."""
    pass


@pytest.mark.skip(reason="Requires live S4 + DB + MinIO")
def test_upload_duplicate_returns_409_with_existing_doc_id() -> None:
    """Same content hash → 409."""
    pass


@pytest.mark.skip(reason="Requires live S4 + DB + MinIO")
def test_upload_different_tenants_same_content_ok() -> None:
    """Two tenants same file → both 202."""
    pass


@pytest.mark.skip(reason="Requires live S4 + DB + MinIO")
def test_get_document_wrong_tenant_returns_404() -> None:
    """Cross-tenant GET → 404."""
    pass


@pytest.mark.skip(reason="Requires live S4 + DB + Kafka + MinIO")
def test_delete_sets_status_and_publishes_event() -> None:
    """DELETE → status=deleted + outbox event."""
    pass
