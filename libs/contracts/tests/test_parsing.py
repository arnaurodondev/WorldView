"""Unit tests for contracts.parsing module."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from contracts.canonical.ohlcv import CanonicalOHLCVBar
from contracts.parsing import (
    parse_ohlcv_from_parquet,
    parse_ohlcv_from_json,
    parse_ohlcv_from_jsonl,
    to_parquet,
    to_jsonl,
)


def _make_bar(symbol: str = "AAPL", close: float = 154.0) -> CanonicalOHLCVBar:
    return CanonicalOHLCVBar(
        symbol=symbol,
        exchange="US",
        date=datetime(2025, 1, 15, tzinfo=UTC),
        open=150.0,
        high=155.0,
        low=149.0,
        close=close,
        volume=1_000_000,
        source="test",
    )


class TestParseOhlcvFromJsonl:
    def test_single_bar(self, tmp_path: Path) -> None:
        bar = _make_bar()
        p = tmp_path / "bars.jsonl"
        p.write_text(json.dumps(bar.to_dict()) + "\n", encoding="utf-8")
        bars = parse_ohlcv_from_jsonl(p)
        assert len(bars) == 1
        assert bars[0].symbol == "AAPL"
        assert bars[0].close == 154.0

    def test_multiple_bars(self, tmp_path: Path) -> None:
        bars = [_make_bar("AAPL", 154.0), _make_bar("MSFT", 300.0)]
        p = tmp_path / "bars.jsonl"
        p.write_text(
            "\n".join(json.dumps(b.to_dict()) for b in bars) + "\n",
            encoding="utf-8",
        )
        result = parse_ohlcv_from_jsonl(p)
        assert len(result) == 2
        assert result[0].symbol == "AAPL"
        assert result[1].symbol == "MSFT"

    def test_empty_file(self, tmp_path: Path) -> None:
        p = tmp_path / "empty.jsonl"
        p.write_text("", encoding="utf-8")
        bars = parse_ohlcv_from_jsonl(p)
        assert bars == []

    def test_blank_lines_skipped(self, tmp_path: Path) -> None:
        bar = _make_bar()
        p = tmp_path / "spaced.jsonl"
        p.write_text(
            "\n" + json.dumps(bar.to_dict()) + "\n\n",
            encoding="utf-8",
        )
        bars = parse_ohlcv_from_jsonl(p)
        assert len(bars) == 1

    def test_invalid_json_raises(self, tmp_path: Path) -> None:
        p = tmp_path / "bad.jsonl"
        p.write_text("not json\n", encoding="utf-8")
        with pytest.raises(json.JSONDecodeError):
            parse_ohlcv_from_jsonl(p)

    def test_accepts_str_path(self, tmp_path: Path) -> None:
        bar = _make_bar()
        p = tmp_path / "bars.jsonl"
        p.write_text(json.dumps(bar.to_dict()) + "\n", encoding="utf-8")
        bars = parse_ohlcv_from_jsonl(str(p))
        assert len(bars) == 1


class TestParseOhlcvFromJson:
    def test_array_of_bars(self, tmp_path: Path) -> None:
        bars = [_make_bar("AAPL"), _make_bar("MSFT")]
        p = tmp_path / "bars.json"
        p.write_text(
            json.dumps([b.to_dict() for b in bars]),
            encoding="utf-8",
        )
        result = parse_ohlcv_from_json(p)
        assert len(result) == 2
        assert result[0].symbol == "AAPL"

    def test_empty_array(self, tmp_path: Path) -> None:
        p = tmp_path / "empty.json"
        p.write_text("[]", encoding="utf-8")
        bars = parse_ohlcv_from_json(p)
        assert bars == []

    def test_non_array_raises(self, tmp_path: Path) -> None:
        p = tmp_path / "obj.json"
        p.write_text(json.dumps({"foo": "bar"}), encoding="utf-8")
        with pytest.raises(ValueError, match="JSON array"):
            parse_ohlcv_from_json(p)


class TestToJsonl:
    def test_write_and_read_back(self, tmp_path: Path) -> None:
        bars = [_make_bar("AAPL"), _make_bar("MSFT")]
        p = tmp_path / "out.jsonl"
        to_jsonl(bars, p)
        result = parse_ohlcv_from_jsonl(p)
        assert len(result) == 2
        assert result[0].symbol == "AAPL"
        assert result[1].symbol == "MSFT"

    def test_empty_list(self, tmp_path: Path) -> None:
        p = tmp_path / "empty.jsonl"
        to_jsonl([], p)
        assert p.read_text() == ""

    def test_one_bar_per_line(self, tmp_path: Path) -> None:
        bars = [_make_bar("AAPL"), _make_bar("MSFT")]
        p = tmp_path / "out.jsonl"
        to_jsonl(bars, p)
        lines = [ln for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()]
        assert len(lines) == 2


class TestParquetSupport:
    def test_write_and_read_back(self, tmp_path: Path) -> None:
        pytest.importorskip("pyarrow")
        bars = [_make_bar("AAPL", 154.0), _make_bar("MSFT", 300.0)]
        p = tmp_path / "bars.parquet"
        to_parquet(bars, p)
        result = parse_ohlcv_from_parquet(p)
        assert len(result) == 2
        assert result[0].symbol == "AAPL"
        assert result[1].symbol == "MSFT"

    def test_accepts_str_path(self, tmp_path: Path) -> None:
        pytest.importorskip("pyarrow")
        p = tmp_path / "bars.parquet"
        to_parquet([_make_bar("AAPL")], str(p))
        result = parse_ohlcv_from_parquet(str(p))
        assert len(result) == 1
        assert result[0].symbol == "AAPL"

    def test_empty_roundtrip(self, tmp_path: Path) -> None:
        pytest.importorskip("pyarrow")
        p = tmp_path / "empty.parquet"
        to_parquet([], p)
        result = parse_ohlcv_from_parquet(p)
        assert result == []

    def test_parse_raises_import_error_without_parquet(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        import contracts.parsing as parsing

        monkeypatch.setattr(parsing, "_PARQUET_AVAILABLE", False)
        with pytest.raises(ImportError, match="pyarrow is required"):
            parse_ohlcv_from_parquet(tmp_path / "bars.parquet")

    def test_write_raises_import_error_without_parquet(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        import contracts.parsing as parsing

        monkeypatch.setattr(parsing, "_PARQUET_AVAILABLE", False)
        with pytest.raises(ImportError, match="pyarrow is required"):
            to_parquet([_make_bar("AAPL")], tmp_path / "bars.parquet")
