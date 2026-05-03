"""Unit tests for messaging.kafka.schema_paths."""

from __future__ import annotations

from pathlib import Path

import pytest

from messaging.kafka.schema_paths import (
    find_schema_dir,
    get_schema_path,
)

pytestmark = pytest.mark.unit


class TestFindSchemaDir:
    """find_schema_dir() locates infra/kafka/schemas/."""

    def test_find_schema_dir_returns_existing_dir(self) -> None:
        """The default invocation finds the real repo schema dir."""
        result = find_schema_dir()
        assert result.is_dir(), f"{result} is not a directory"
        assert result.name == "schemas"
        # Path ends with infra/kafka/schemas regardless of repo root location.
        assert result.parts[-3:] == ("infra", "kafka", "schemas")

    def test_find_schema_dir_is_cached(self) -> None:
        """Default invocation is memoised (same Path instance across calls)."""
        a = find_schema_dir()
        b = find_schema_dir()
        assert a == b

    def test_walk_up_finds_synthetic_schema_dir(self, tmp_path: Path) -> None:
        """Given a tmp tree containing infra/kafka/schemas/, the helper finds it."""
        # Create the synthetic schema dir at <tmp>/infra/kafka/schemas
        synthetic = tmp_path / "infra" / "kafka" / "schemas"
        synthetic.mkdir(parents=True)

        # Walk start point is several dirs deeper — helper must walk up.
        deep = tmp_path / "deep" / "nested" / "child"
        deep.mkdir(parents=True)

        result = find_schema_dir(start=deep)
        assert result == synthetic

    def test_walk_up_falls_back_when_not_found(self, tmp_path: Path) -> None:
        """When no ancestor contains infra/kafka/schemas, fall back to module-relative."""
        # tmp_path has no infra/kafka/schemas anywhere up the chain — helper falls
        # back to Path(__file__).parents[5] / infra / kafka / schemas of the
        # schema_paths module itself, which IS the real repo schema dir.
        deep = tmp_path / "no" / "schemas" / "anywhere"
        deep.mkdir(parents=True)
        result = find_schema_dir(start=deep)
        # Fallback path ends in infra/kafka/schemas (the helper's own repo).
        assert result.parts[-3:] == ("infra", "kafka", "schemas")


class TestGetSchemaPath:
    """get_schema_path() composes schema dir + filename as a str."""

    def test_get_schema_path_appends_filename(self) -> None:
        """Returned string ends with the requested .avsc filename."""
        result = get_schema_path("foo.avsc")
        assert isinstance(result, str)
        assert result.endswith("/foo.avsc")

    def test_get_schema_path_is_absolute(self) -> None:
        """Returned path is absolute so it works regardless of CWD."""
        result = get_schema_path("any.avsc")
        assert Path(result).is_absolute()

    def test_get_schema_path_real_schema_exists(self) -> None:
        """A known real schema in the repo resolves to an existing file."""
        # Pick any .avsc that is guaranteed to exist in the canonical schema dir.
        schema_dir = find_schema_dir()
        existing_files = list(schema_dir.glob("*.avsc"))
        assert existing_files, f"No .avsc files in {schema_dir}"
        first_filename = existing_files[0].name
        resolved = get_schema_path(first_filename)
        assert Path(resolved).exists()
