"""Unit tests for the intelligence_db ALEMBIC_ENABLED guard."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


class TestAlembicGuard:
    """The session factory must raise IntelligenceDbAlembicError when ALEMBIC_ENABLED is truthy."""

    def _import_guard(self) -> None:
        """Re-import session module with current env to exercise guard at import time."""
        from knowledge_graph.infrastructure.intelligence_db.session import (
            create_intelligence_session_factory,
            create_readonly_session_factory,
        )

        return create_intelligence_session_factory, create_readonly_session_factory  # type: ignore[return-value]

    def test_alembic_enabled_true_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ALEMBIC_ENABLED", "true")
        from knowledge_graph.domain.errors import IntelligenceDbAlembicError
        from knowledge_graph.infrastructure.intelligence_db.session import (
            create_intelligence_session_factory,
        )

        with pytest.raises(IntelligenceDbAlembicError):
            create_intelligence_session_factory("postgresql+asyncpg://localhost/test")

    def test_alembic_enabled_1_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ALEMBIC_ENABLED", "1")
        from knowledge_graph.domain.errors import IntelligenceDbAlembicError
        from knowledge_graph.infrastructure.intelligence_db.session import (
            create_intelligence_session_factory,
        )

        with pytest.raises(IntelligenceDbAlembicError):
            create_intelligence_session_factory("postgresql+asyncpg://localhost/test")

    def test_alembic_enabled_yes_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ALEMBIC_ENABLED", "yes")
        from knowledge_graph.domain.errors import IntelligenceDbAlembicError
        from knowledge_graph.infrastructure.intelligence_db.session import (
            create_intelligence_session_factory,
        )

        with pytest.raises(IntelligenceDbAlembicError):
            create_intelligence_session_factory("postgresql+asyncpg://localhost/test")

    def test_alembic_enabled_false_ok(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ALEMBIC_ENABLED", "false")
        # Should NOT raise
        from knowledge_graph.infrastructure.intelligence_db.session import (
            create_intelligence_session_factory,
        )

        engine, _factory = create_intelligence_session_factory(
            "postgresql+asyncpg://postgres:postgres@localhost/intelligence_db"
        )
        assert engine is not None
        assert _factory is not None

    def test_alembic_enabled_unset_ok(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("ALEMBIC_ENABLED", raising=False)
        from knowledge_graph.infrastructure.intelligence_db.session import (
            create_intelligence_session_factory,
        )

        engine, _factory = create_intelligence_session_factory(
            "postgresql+asyncpg://postgres:postgres@localhost/intelligence_db"
        )
        assert engine is not None

    def test_readonly_factory_also_guards(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ALEMBIC_ENABLED", "true")
        from knowledge_graph.domain.errors import IntelligenceDbAlembicError
        from knowledge_graph.infrastructure.intelligence_db.session import (
            create_readonly_session_factory,
        )

        with pytest.raises(IntelligenceDbAlembicError):
            create_readonly_session_factory("postgresql+asyncpg://localhost/test")

    def test_error_message_mentions_service(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ALEMBIC_ENABLED", "true")
        from knowledge_graph.domain.errors import IntelligenceDbAlembicError
        from knowledge_graph.infrastructure.intelligence_db.session import (
            create_intelligence_session_factory,
        )

        with pytest.raises(IntelligenceDbAlembicError, match="intelligence-migrations"):
            create_intelligence_session_factory("postgresql+asyncpg://localhost/test")
