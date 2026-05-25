"""Test that ALEMBIC_ENABLED=true raises RuntimeError (BP: intelligence_db DDL guard)."""

from __future__ import annotations

import os

import pytest


@pytest.mark.integration()
def test_alembic_enabled_raises() -> None:
    """Setting ALEMBIC_ENABLED=true must raise IntelligenceDbAlembicError."""
    from knowledge_graph.domain.errors import IntelligenceDbAlembicError
    from knowledge_graph.infrastructure.intelligence_db.session import (
        create_intelligence_session_factory,
    )

    original = os.environ.get("ALEMBIC_ENABLED")
    os.environ["ALEMBIC_ENABLED"] = "true"
    try:
        with pytest.raises(IntelligenceDbAlembicError):
            create_intelligence_session_factory("postgresql+asyncpg://x:x@localhost/db")
    finally:
        if original is None:
            os.environ.pop("ALEMBIC_ENABLED", None)
        else:
            os.environ["ALEMBIC_ENABLED"] = original


@pytest.mark.integration()
def test_alembic_disabled_does_not_raise() -> None:
    """ALEMBIC_ENABLED=false (default) must NOT raise."""
    from knowledge_graph.infrastructure.intelligence_db.session import (
        create_intelligence_session_factory,
    )

    original = os.environ.get("ALEMBIC_ENABLED")
    os.environ["ALEMBIC_ENABLED"] = "false"
    try:
        # Just constructing the engine — no network call
        engine, _ = create_intelligence_session_factory(
            "postgresql+asyncpg://postgres:postgres@localhost:5432/intelligence_db",
        )
        engine.sync_engine.dispose()
    finally:
        if original is None:
            os.environ.pop("ALEMBIC_ENABLED", None)
        else:
            os.environ["ALEMBIC_ENABLED"] = original
