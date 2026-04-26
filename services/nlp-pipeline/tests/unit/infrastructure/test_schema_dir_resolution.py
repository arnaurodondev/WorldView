"""Regression tests for BP-224: _find_schema_dir() walk-up path resolution."""

from pathlib import Path

import pytest


@pytest.mark.unit
def test_find_schema_dir_returns_path() -> None:
    from nlp_pipeline.infrastructure.messaging.consumers.article_consumer import _SCHEMA_DIR

    assert isinstance(_SCHEMA_DIR, Path)


@pytest.mark.unit
def test_find_schema_dir_finds_avsc_files() -> None:
    from nlp_pipeline.infrastructure.messaging.consumers.article_consumer import _SCHEMA_DIR

    avsc_files = list(_SCHEMA_DIR.glob("*.avsc"))
    assert len(avsc_files) > 0, f"No .avsc files found in {_SCHEMA_DIR}"
