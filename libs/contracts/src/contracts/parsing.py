"""JSONL / JSON / Parquet parsing utilities for canonical OHLCV data.

pyarrow is an optional dependency — Parquet support is silently unavailable
if not installed. Add ``pyarrow`` to your environment to enable Parquet I/O.
"""

from __future__ import annotations

import json
from pathlib import Path

import structlog

from contracts.canonical.ohlcv import CanonicalOHLCVBar

logger = structlog.get_logger()

_PARQUET_AVAILABLE = False
try:
    import pyarrow as _pa  # type: ignore[import-not-found]
    import pyarrow.parquet as _pq  # type: ignore[import-not-found]
    _PARQUET_AVAILABLE = True
except ImportError:
    pass


def parse_ohlcv_from_jsonl(path: str | Path) -> list[CanonicalOHLCVBar]:
    """Parse a JSONL file into a list of ``CanonicalOHLCVBar`` instances.

    Each non-empty line must be a valid JSON object. Blank/whitespace lines
    are silently skipped.
    """
    path = Path(path)
    bars: list[CanonicalOHLCVBar] = []
    with path.open(encoding="utf-8") as fh:
        for lineno, raw in enumerate(fh, start=1):
            line = raw.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except json.JSONDecodeError as exc:
                logger.warning(
                    "ohlcv.parse_jsonl.invalid_line",
                    path=str(path),
                    lineno=lineno,
                    error=str(exc),
                )
                raise
            bars.append(CanonicalOHLCVBar.from_dict(d))
    logger.info(
        "ohlcv.parse_jsonl.complete",
        path=str(path),
        bar_count=len(bars),
    )
    return bars


def parse_ohlcv_from_json(path: str | Path) -> list[CanonicalOHLCVBar]:
    """Parse a JSON file (array at top level) into ``CanonicalOHLCVBar`` instances."""
    path = Path(path)
    with path.open(encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, list):
        raise ValueError(f"Expected a JSON array at top level, got {type(data).__name__}")
    bars = [CanonicalOHLCVBar.from_dict(d) for d in data]
    logger.info(
        "ohlcv.parse_json.complete",
        path=str(path),
        bar_count=len(bars),
    )
    return bars


def parse_ohlcv_from_parquet(path: str | Path) -> list[CanonicalOHLCVBar]:
    """Parse a Parquet file into ``CanonicalOHLCVBar`` instances.

    Requires ``pyarrow`` to be installed. Raises ``ImportError`` if not available.
    """
    if not _PARQUET_AVAILABLE:
        raise ImportError(
            "pyarrow is required for Parquet support. "
            "Install it with: pip install pyarrow"
        )
    path = Path(path)
    table = _pq.read_table(str(path))  # type: ignore[union-attr]
    records = table.to_pylist()
    bars = [CanonicalOHLCVBar.from_dict(d) for d in records]
    logger.info(
        "ohlcv.parse_parquet.complete",
        path=str(path),
        bar_count=len(bars),
    )
    return bars


def to_jsonl(bars: list[CanonicalOHLCVBar], path: str | Path) -> None:
    """Write canonical bars to a JSONL file (one JSON object per line)."""
    path = Path(path)
    with path.open("w", encoding="utf-8") as fh:
        for bar in bars:
            fh.write(json.dumps(bar.to_dict()) + "\n")
    logger.info(
        "ohlcv.write_jsonl.complete",
        path=str(path),
        bar_count=len(bars),
    )


def to_parquet(bars: list[CanonicalOHLCVBar], path: str | Path) -> None:
    """Write canonical bars to a Parquet file.

    Requires ``pyarrow`` to be installed.
    """
    if not _PARQUET_AVAILABLE:
        raise ImportError(
            "pyarrow is required for Parquet support. "
            "Install it with: pip install pyarrow"
        )
    path = Path(path)
    records = [bar.to_dict() for bar in bars]
    table = _pa.Table.from_pylist(records)  # type: ignore[union-attr]
    _pq.write_table(table, str(path))  # type: ignore[union-attr]
    logger.info(
        "ohlcv.write_parquet.complete",
        path=str(path),
        bar_count=len(bars),
    )
