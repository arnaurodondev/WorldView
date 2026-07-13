"""Unit tests for _expire_stale_embeddings startup housekeeping (PRE-1 / PLAN-0031 B-2).

Validates that on startup the NLP Pipeline expires chunk_embeddings and
section_embeddings rows whose ``model_id`` is not one of the CURRENTLY configured
model labels — and, critically, that it treats BOTH the logical id
(``embedding_model_id``, e.g. "bge-large") and the provider-API id
(``embedding_api_model_id``, e.g. "BAAI/bge-large-en-v1.5") as current. Comparing
against only the logical id flagged the entire DeepInfra-written corpus as stale
and blew the boot statement_timeout (PRE-1).

Also validates the bounded/batched drain: each UPDATE is capped at
``embedding_expiry_batch_size`` rows and given its own ``SET LOCAL
statement_timeout`` so a large one-time expiry cannot trip the OLTP backstop.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytestmark = pytest.mark.unit


def _make_result(rowcount: int) -> MagicMock:
    """Create a mock CursorResult with the given rowcount."""
    result = MagicMock()
    result.rowcount = rowcount
    return result


def _make_config(
    embedding_model_id: str = "bge-large",
    embedding_api_model_id: str = "BAAI/bge-large-en-v1.5",
    batch_size: int = 200,
    timeout_ms: int = 300_000,
    max_batches: int = 100_000,
) -> MagicMock:
    """Minimal config mock with the fields the expiry reads."""
    config = MagicMock()
    config.embedding_model_id = embedding_model_id
    config.embedding_api_model_id = embedding_api_model_id
    config.embedding_expiry_batch_size = batch_size
    config.embedding_expiry_statement_timeout_ms = timeout_ms
    config.embedding_expiry_max_batches_per_run = max_batches
    return config


def _make_session_factory(execute_side_effect: list[Any]) -> tuple[Any, AsyncMock]:
    """Build an async session factory yielding one shared mock session.

    ``execute_side_effect`` is consumed in call order across ALL batches and both
    tables. SET LOCAL calls (1 positional arg) and UPDATE calls (2 positional
    args) both consume one entry; only UPDATE results have a meaningful rowcount.

    Returns (factory_callable, mock_session).
    """
    session = AsyncMock()
    session.execute = AsyncMock(side_effect=execute_side_effect)
    session.commit = AsyncMock()

    @asynccontextmanager
    async def _factory() -> Any:
        yield session

    return _factory, session


def _update_calls(session: AsyncMock) -> list[Any]:
    """The subset of execute() calls that are UPDATEs (called with a params dict)."""
    return [c for c in session.execute.call_args_list if len(c.args) > 1]


def _set_local_calls(session: AsyncMock) -> list[Any]:
    """The subset of execute() calls that are SET LOCAL (single positional arg)."""
    return [c for c in session.execute.call_args_list if len(c.args) == 1]


class TestCurrentEmbeddingModelIds:
    """The provider-aware current-label helper."""

    def test_returns_both_logical_and_api_labels(self) -> None:
        from nlp_pipeline.bootstrap.embedding import current_embedding_model_ids

        cfg = _make_config("bge-large", "BAAI/bge-large-en-v1.5")
        assert current_embedding_model_ids(cfg) == ["BAAI/bge-large-en-v1.5", "bge-large"]

    def test_dedupes_when_labels_equal(self) -> None:
        from nlp_pipeline.bootstrap.embedding import current_embedding_model_ids

        cfg = _make_config("bge-large", "bge-large")
        assert current_embedding_model_ids(cfg) == ["bge-large"]

    def test_drops_empty_labels(self) -> None:
        from nlp_pipeline.bootstrap.embedding import current_embedding_model_ids

        cfg = _make_config("bge-large", "")
        assert current_embedding_model_ids(cfg) == ["bge-large"]

    def test_empty_when_both_unset(self) -> None:
        from nlp_pipeline.bootstrap.embedding import current_embedding_model_ids

        cfg = _make_config("", "")
        assert current_embedding_model_ids(cfg) == []


class TestExpireStaleEmbeddings:
    """Tests for _expire_stale_embeddings."""

    def test_no_op_when_model_unchanged(self) -> None:
        """0 stale rows in both tables → no warning, one bounded UPDATE per table."""
        from nlp_pipeline.app import _expire_stale_embeddings

        # chunk: SET LOCAL, UPDATE(0) → drained; section: SET LOCAL, UPDATE(0).
        side = [_make_result(0), _make_result(0), _make_result(0), _make_result(0)]
        factory, session = _make_session_factory(side)
        config = _make_config()

        with patch("structlog.get_logger") as mock_get_logger:
            mock_logger = MagicMock()
            mock_get_logger.return_value = mock_logger
            asyncio.run(_expire_stale_embeddings(factory, config))
            mock_logger.warning.assert_not_called()

        # One UPDATE per table (both returned < batch_size → drained immediately).
        assert len(_update_calls(session)) == 2
        assert session.commit.call_count == 2

    def test_predicate_excludes_both_current_labels(self) -> None:
        """The UPDATE binds BOTH the logical and the API model id (PRE-1 fix)."""
        from nlp_pipeline.app import _expire_stale_embeddings

        side = [_make_result(0), _make_result(0), _make_result(0), _make_result(0)]
        factory, session = _make_session_factory(side)
        config = _make_config("bge-large", "BAAI/bge-large-en-v1.5")

        asyncio.run(_expire_stale_embeddings(factory, config))

        for call in _update_calls(session):
            params = call.args[1]
            bound = {v for k, v in params.items() if k.startswith("m")}
            assert bound == {"bge-large", "BAAI/bge-large-en-v1.5"}
            # NOT IN uses one placeholder per current label.
            assert ":m0" in str(call.args[0]) and ":m1" in str(call.args[0])
            assert "NOT IN" in str(call.args[0])

    def test_sets_per_batch_statement_timeout(self) -> None:
        """Each batch issues SET LOCAL statement_timeout before the UPDATE."""
        from nlp_pipeline.app import _expire_stale_embeddings

        side = [_make_result(0), _make_result(0), _make_result(0), _make_result(0)]
        factory, session = _make_session_factory(side)
        config = _make_config(timeout_ms=300_000)

        asyncio.run(_expire_stale_embeddings(factory, config))

        set_calls = _set_local_calls(session)
        assert len(set_calls) == 2  # one per table batch
        for call in set_calls:
            assert "SET LOCAL statement_timeout = 300000" in str(call.args[0])

    def test_no_set_local_when_timeout_disabled(self) -> None:
        """timeout_ms=0 → no SET LOCAL (unbounded, uses connection default)."""
        from nlp_pipeline.app import _expire_stale_embeddings

        side = [_make_result(0), _make_result(0)]
        factory, session = _make_session_factory(side)
        config = _make_config(timeout_ms=0)

        asyncio.run(_expire_stale_embeddings(factory, config))

        assert _set_local_calls(session) == []
        assert len(_update_calls(session)) == 2

    def test_logs_warning_with_counts_when_rows_expired(self) -> None:
        """Stale rows found → single warning with per-table counts and current models."""
        from nlp_pipeline.app import _expire_stale_embeddings

        # chunk: SET LOCAL, UPDATE(10)<batch → drained; section: SET LOCAL, UPDATE(5).
        side = [_make_result(0), _make_result(10), _make_result(0), _make_result(5)]
        factory, _session = _make_session_factory(side)
        config = _make_config("bge-large", "BAAI/bge-large-en-v1.5", batch_size=200)

        with patch("structlog.get_logger") as mock_get_logger:
            mock_logger = MagicMock()
            mock_get_logger.return_value = mock_logger
            asyncio.run(_expire_stale_embeddings(factory, config))
            mock_logger.warning.assert_called_once_with(
                "embedding_model_changed",
                stale_chunk_count=10,
                stale_section_count=5,
                current_models=["BAAI/bge-large-en-v1.5", "bge-large"],
            )

    def test_batches_until_drained(self) -> None:
        """A table with > batch_size stale rows drains over multiple UPDATEs."""
        from nlp_pipeline.app import _expire_stale_embeddings

        # batch_size=2. chunk: full batch (2), full batch (2), partial (1) → stop.
        # section: partial (0) → stop immediately.
        side = [
            _make_result(0),
            _make_result(2),  # chunk batch 1
            _make_result(0),
            _make_result(2),  # chunk batch 2
            _make_result(0),
            _make_result(1),  # chunk batch 3 (partial → drained)
            _make_result(0),
            _make_result(0),  # section batch 1 (drained)
        ]
        factory, session = _make_session_factory(side)
        config = _make_config(batch_size=2)

        with patch("structlog.get_logger") as mock_get_logger:
            mock_logger = MagicMock()
            mock_get_logger.return_value = mock_logger
            asyncio.run(_expire_stale_embeddings(factory, config))
            # chunk expired 2+2+1=5, section 0.
            mock_logger.warning.assert_called_once_with(
                "embedding_model_changed",
                stale_chunk_count=5,
                stale_section_count=0,
                current_models=["BAAI/bge-large-en-v1.5", "bge-large"],
            )

        assert len(_update_calls(session)) == 4  # 3 chunk + 1 section
        assert session.commit.call_count == 4

    def test_respects_max_batches_cap(self) -> None:
        """The per-run batch ceiling stops an otherwise-endless drain."""
        from nlp_pipeline.app import _expire_stale_embeddings

        # timeout_ms=0 → no SET LOCAL, so each execute IS an UPDATE. Every UPDATE
        # returns a full batch (rowcount == batch_size) so the drain never breaks
        # early; the max_batches cap must stop it at 3 per table.
        side = [_make_result(2)] * 100
        factory, session = _make_session_factory(side)
        config = _make_config(batch_size=2, max_batches=3, timeout_ms=0)

        asyncio.run(_expire_stale_embeddings(factory, config))

        # 3 batches per table x 2 tables = 6 UPDATEs, then stops.
        assert len(_update_calls(session)) == 6

    def test_skips_when_no_model_id_configured(self) -> None:
        """Both labels empty → skip (never expire the whole corpus on misconfig)."""
        from nlp_pipeline.app import _expire_stale_embeddings

        factory, session = _make_session_factory([])
        config = _make_config("", "")

        with patch("structlog.get_logger") as mock_get_logger:
            mock_logger = MagicMock()
            mock_get_logger.return_value = mock_logger
            asyncio.run(_expire_stale_embeddings(factory, config))
            mock_logger.warning.assert_called_once_with("expire_stale_embeddings_skipped_no_model_id")

        session.execute.assert_not_called()
