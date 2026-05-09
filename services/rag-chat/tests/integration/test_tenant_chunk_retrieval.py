"""Integration tests for tenant-filtered RAG chunk retrieval in S8.

Requires: Live S6 with chunks in DB.
Run with: pytest -m integration
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


@pytest.mark.skip(reason="Requires live S6 + nlp-pipeline DB with tenant chunks")
def test_rag_retrieval_excludes_other_tenant_private_chunks() -> None:
    """Tenant B's private chunk not returned for tenant A's chat request."""
    pass


@pytest.mark.skip(reason="Requires live S6 + nlp-pipeline DB")
def test_rag_retrieval_includes_public_chunks() -> None:
    """Public (NULL tenant_id) chunks returned for all tenants."""
    pass
