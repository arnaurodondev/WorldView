"""Unit tests for intelligence_db ALEMBIC_ENABLED=false guard (T-C-1-05)."""

from __future__ import annotations

import pytest
from nlp_pipeline.domain.errors import IntelligenceDbAlembicError
from nlp_pipeline.infrastructure.intelligence_db.session import (
    _check_alembic_guard,
    create_intelligence_session_factory,
)


@pytest.mark.unit
class TestAlembicGuard:
    """Explicit guard: ALEMBIC_ENABLED=true on intelligence_db MUST raise (T-C-1-05)."""

    def test_guard_passes_when_false(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ALEMBIC_ENABLED", "false")
        _check_alembic_guard()  # should not raise

    def test_guard_passes_when_zero(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ALEMBIC_ENABLED", "0")
        _check_alembic_guard()

    def test_guard_passes_when_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("ALEMBIC_ENABLED", raising=False)
        _check_alembic_guard()

    def test_guard_passes_when_off(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ALEMBIC_ENABLED", "off")
        _check_alembic_guard()

    def test_guard_raises_when_true(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Critical: ALEMBIC_ENABLED=true must raise — intelligence_db DDL is NOT ours."""
        monkeypatch.setenv("ALEMBIC_ENABLED", "true")
        with pytest.raises(IntelligenceDbAlembicError, match="intelligence_db"):
            _check_alembic_guard()

    def test_guard_raises_when_True_capitalized(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ALEMBIC_ENABLED", "True")
        with pytest.raises(IntelligenceDbAlembicError):
            _check_alembic_guard()

    def test_guard_raises_when_1(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ALEMBIC_ENABLED", "1")
        with pytest.raises(IntelligenceDbAlembicError):
            _check_alembic_guard()

    def test_factory_raises_on_true(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """create_intelligence_session_factory must propagate the guard error."""
        monkeypatch.setenv("ALEMBIC_ENABLED", "true")
        with pytest.raises(IntelligenceDbAlembicError):
            create_intelligence_session_factory("postgresql+asyncpg://postgres:postgres@localhost:5432/intelligence_db")

    def test_factory_succeeds_on_false(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ALEMBIC_ENABLED", "false")
        engine, factory = create_intelligence_session_factory(
            "postgresql+asyncpg://postgres:postgres@localhost:5432/intelligence_db"
        )
        assert engine is not None
        assert factory is not None
        # Dispose immediately — no real connection attempted in unit test
        import asyncio

        asyncio.run(engine.dispose())
