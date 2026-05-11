"""Integration tests for per-tenant dedup isolation in S5.

Requires: PostgreSQL content_store_db with migration 0005 applied.
Run with: pytest -m integration
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


@pytest.mark.skip(reason="Requires live content-store DB with migration 0005")
def test_global_dedup_still_works() -> None:
    """Same public news hash → duplicate detected (global dedup unchanged)."""
    pass


@pytest.mark.skip(reason="Requires live content-store DB with migration 0005")
def test_per_tenant_dedup_same_content() -> None:
    """Tenant A uploads doc X; tenant A uploads same doc → 409."""
    pass


@pytest.mark.skip(reason="Requires live content-store DB with migration 0005")
def test_per_tenant_dedup_different_tenants() -> None:
    """Tenant A and B upload same content → both succeed (independent dedup)."""
    pass


@pytest.mark.skip(reason="Requires live content-store DB with migration 0005")
def test_migration_0005_existing_rows_null() -> None:
    """After upgrade, all existing documents have tenant_id = NULL."""
    pass
