"""Unit tests for the resumable prediction-polarity backfill (PLAN-0056 C3)."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest

# The backfill lives under ``scripts/`` (run via ``python -m scripts.…``), which is
# not on the pytest sys.path — load it directly by file path.
_MOD_PATH = Path(__file__).resolve().parents[2] / "scripts" / "backfill_prediction_polarity.py"
_spec = importlib.util.spec_from_file_location("backfill_prediction_polarity", _MOD_PATH)
assert _spec is not None and _spec.loader is not None
_bp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_bp)
_env_bool = _bp._env_bool
_env_int = _bp._env_int
_process_batch = _bp._process_batch

pytestmark = pytest.mark.unit


class _Result:
    def __init__(self, rows: list[Any] | None = None, rowcount: int = 0) -> None:
        self._rows = rows or []
        self.rowcount = rowcount

    def fetchall(self) -> list[Any]:
        return self._rows


class _Session:
    """Async-context session returning queued execute() results in order."""

    def __init__(self, results: list[_Result]) -> None:
        self._results = results
        self._i = 0
        self.commit = AsyncMock()

    async def __aenter__(self) -> _Session:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def execute(self, *_a: object, **_k: object) -> _Result:
        res = self._results[self._i]
        self._i += 1
        return res


def _factory(sessions: list[_Session]):
    it = iter(sessions)
    return lambda: next(it)


class TestEnvHelpers:
    def test_env_int_and_bool_defaults(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("X_INT", raising=False)
        assert _env_int("X_INT", 7) == 7
        monkeypatch.setenv("X_INT", "not-a-number")
        assert _env_int("X_INT", 7) == 7
        monkeypatch.setenv("X_BOOL", "YES")
        assert _env_bool("X_BOOL", False) is True


class TestProcessBatch:
    @pytest.mark.asyncio
    async def test_classifies_and_updates_advancing_cursor(self) -> None:
        # Phase-1 read session returns two candidate rows.
        read_session = _Session(
            [
                _Result(
                    rows=[
                        # (exposure_id, entity_id, question, condition_id, canonical_name)
                        (
                            "01900000-0000-7000-8000-00000000aaaa",
                            "01900000-0000-7000-8000-0000000000e1",
                            "Will X win?",
                            "0xcond",
                            "Acme Corp",
                        ),
                        (
                            "01900000-0000-7000-8000-00000000bbbb",
                            "01900000-0000-7000-8000-0000000000e2",
                            "Will X win?",
                            "0xcond",
                            "Beta Inc",
                        ),
                    ]
                )
            ]
        )
        # Phase-3 update session: one execute per verdict + commit.
        update_session = _Session([_Result(rowcount=1), _Result(rowcount=1)])
        factory = _factory([read_session, update_session])

        classifier = AsyncMock()
        classifier.classify = AsyncMock(return_value=("bullish", 0.9))

        cursor, visited, updated = await _process_batch(factory, classifier, "0" * 32, 200)

        assert visited == 2
        assert updated == 2
        # Cursor advances to the LAST row's exposure_id.
        assert cursor == "01900000-0000-7000-8000-00000000bbbb"
        assert classifier.classify.await_count == 2

    @pytest.mark.asyncio
    async def test_row_without_entity_name_skipped_but_cursor_advances(self) -> None:
        read_session = _Session(
            [
                _Result(
                    rows=[
                        # no canonical_name → unclassifiable, must skip
                        (
                            "01900000-0000-7000-8000-00000000cccc",
                            "01900000-0000-7000-8000-0000000000e3",
                            "Q?",
                            "0xc",
                            None,
                        ),
                    ]
                )
            ]
        )
        factory = _factory([read_session])  # no update session — nothing to update
        classifier = AsyncMock()
        classifier.classify = AsyncMock()

        cursor, visited, updated = await _process_batch(factory, classifier, "0" * 32, 200)

        assert visited == 1
        assert updated == 0
        classifier.classify.assert_not_awaited()
        # Unclassifiable row must NOT wedge the loop — cursor still moves past it.
        assert cursor == "01900000-0000-7000-8000-00000000cccc"

    @pytest.mark.asyncio
    async def test_empty_page_returns_zero_visited(self) -> None:
        factory = _factory([_Session([_Result(rows=[])])])
        classifier = AsyncMock()
        cursor, visited, updated = await _process_batch(factory, classifier, "abc", 200)
        assert (cursor, visited, updated) == ("abc", 0, 0)
