"""Unit tests for API dependencies (T-B-2-05)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

pytestmark = pytest.mark.unit


def _mock_request(factory: MagicMock, *, attr: str = "write_factory") -> MagicMock:
    """Create a mock Request with app.state.<attr> set to factory."""
    request = MagicMock()
    setattr(request.app.state, attr, factory)
    return request


class TestGetDbSession:
    async def test_get_db_session_yields_session(self) -> None:
        """Dependency yields a valid AsyncSession from write factory."""
        from content_ingestion.api.dependencies import get_db_session

        session = AsyncMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=None)

        factory = MagicMock()
        factory.return_value = session

        request = _mock_request(factory, attr="write_factory")

        yielded = None
        async for s in get_db_session(request):
            yielded = s

        assert yielded is session


class TestGetReadSession:
    async def test_get_read_session_yields_session(self) -> None:
        """Read dependency yields from read factory."""
        from content_ingestion.api.dependencies import get_read_session

        session = AsyncMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=None)

        factory = MagicMock()
        factory.return_value = session

        request = _mock_request(factory, attr="read_factory")

        yielded = None
        async for s in get_read_session(request):
            yielded = s

        assert yielded is session
