"""Locate ``infra/kafka/schemas/`` Avro schema files.

The schema dir is repo-relative in development (``<repo>/infra/kafka/schemas/``)
and absolute in Docker (``/app/infra/kafka/schemas/``).  This helper walks up
from the caller's location to find it, falling back to a deterministic path
if no parent contains the directory.

Why: 29+ files used to duplicate this 8-line walker, with a fragile
``Path(__file__).parents[7]`` magic-number fallback.  PLAN-0062 audit F-007
consolidates the helper here so the magic-number is in one place and the
schema-discovery contract is testable.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

_SCHEMA_REL = Path("infra") / "kafka" / "schemas"


def find_schema_dir(*, start: Path | None = None) -> Path:
    """Return the absolute path to ``infra/kafka/schemas/``.

    Walks up from *start* (defaults to this module's directory) looking for
    a directory containing ``infra/kafka/schemas/``.  Falls back to
    ``Path(__file__).parents[5] / infra / kafka / schemas`` if no parent
    matches.  Result is independent of the caller's CWD.

    Args:
        start: Optional override for the walk root.  Tests pass ``tmp_path``;
            production callers should leave this as ``None`` so discovery
            uses this module's location and benefits from ``lru_cache``.
    """
    if start is None:
        return _cached_default_schema_dir()
    return _walk_up(start)


@lru_cache(maxsize=1)
def _cached_default_schema_dir() -> Path:
    return _walk_up(Path(__file__).resolve().parent)


def _walk_up(start: Path) -> Path:
    for base in [start, *start.parents]:
        candidate = base / _SCHEMA_REL
        if candidate.is_dir():
            return candidate
    # Fallback for environments where the walk doesn't reach the repo root
    # (e.g. some Docker layouts).  This mirrors the historical
    # ``Path(__file__).parents[5]`` magic from the duplicated copies — if
    # that path is also wrong, the caller will get a missing-file error
    # later, which is loud enough.
    return Path(__file__).resolve().parents[5] / _SCHEMA_REL


def get_schema_path(filename: str) -> str:
    """Return the absolute path to ``<schema-dir>/<filename>`` as a str.

    *filename* should include the ``.avsc`` extension.  No existence check —
    callers receive a path even if the file is missing, so the failure
    surfaces at deserialise time rather than import time.
    """
    return str(find_schema_dir() / filename)
