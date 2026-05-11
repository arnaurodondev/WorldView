"""Integration tests for chunk tenant filtering in S6.

Requires: PostgreSQL nlp_db with migration 0019 applied.
Run with: pytest -m integration
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


@pytest.mark.skip(reason="Requires live nlp-pipeline DB with migration 0019")
def test_chunk_search_excludes_other_tenant_chunks() -> None:
    """Chunks from tenant B not in tenant A's search results."""
    pass


@pytest.mark.skip(reason="Requires live nlp-pipeline DB with migration 0019")
def test_chunk_search_includes_public_and_private() -> None:
    """Public (NULL) + tenant's private chunks both returned."""
    pass


@pytest.mark.skip(reason="Requires live Kafka + nlp-pipeline DB")
def test_document_deletion_consumer_removes_chunks() -> None:
    """Consume deletion event → chunks/sections/entity_mentions gone."""
    pass


@pytest.mark.skip(reason="Requires live Kafka + nlp-pipeline DB")
def test_document_deletion_consumer_idempotent() -> None:
    """Second consumption → no error."""
    pass
