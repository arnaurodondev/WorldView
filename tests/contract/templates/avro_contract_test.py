"""Reusable Avro contract test base class."""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any

import fastavro


class AvroContractTestBase:
    """Base helpers for event schema contract tests.

    Subclasses should provide:
    - schema_file: relative path to .avsc file from repository root
    - valid_samples: list[dict[str, Any]]
    - invalid_samples: list[dict[str, Any]]
    """

    schema_file: str = ""
    valid_samples: list[dict[str, Any]] = []
    invalid_samples: list[dict[str, Any]] = []

    @classmethod
    def load_schema(cls) -> dict[str, Any]:
        if not cls.schema_file:
            raise ValueError("schema_file must be set in subclass")

        root = Path(__file__).resolve().parents[3]
        schema_path = root / cls.schema_file
        if not schema_path.exists():
            raise FileNotFoundError(f"Schema file not found: {schema_path}")

        return json.loads(schema_path.read_text(encoding="utf-8"))

    @classmethod
    def assert_schema_parses(cls) -> Any:
        schema = cls.load_schema()
        return fastavro.parse_schema(schema)

    @classmethod
    def assert_valid_sample_roundtrip(cls, sample: dict[str, Any]) -> None:
        parsed = cls.assert_schema_parses()
        buffer = io.BytesIO()
        fastavro.writer(buffer, parsed, [sample])
        buffer.seek(0)
        rows = list(fastavro.reader(buffer))
        assert len(rows) == 1

    @classmethod
    def assert_invalid_sample_rejected(cls, sample: dict[str, Any]) -> None:
        parsed = cls.assert_schema_parses()
        buffer = io.BytesIO()
        fastavro.writer(buffer, parsed, [sample])

    def test_schema_is_valid(self) -> None:
        self.assert_schema_parses()

    def test_all_valid_samples(self) -> None:
        for sample in self.valid_samples:
            self.assert_valid_sample_roundtrip(sample)
