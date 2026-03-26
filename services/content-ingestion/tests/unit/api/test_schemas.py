"""Unit tests for Pydantic API schemas (T-R1-5-03)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

pytestmark = pytest.mark.unit


class TestSourceSchemas:
    def test_empty_name_rejected(self) -> None:
        from content_ingestion.api.schemas import SourceCreateRequest

        with pytest.raises(ValidationError):
            SourceCreateRequest(name="", source_type="eodhd")

    def test_name_too_long_rejected(self) -> None:
        from content_ingestion.api.schemas import SourceCreateRequest

        # Names should have a reasonable limit
        with pytest.raises(ValidationError):
            SourceCreateRequest(name="x" * 300, source_type="eodhd")

    def test_valid_source_create(self) -> None:
        from content_ingestion.api.schemas import SourceCreateRequest

        req = SourceCreateRequest(name="test-source", source_type="eodhd", config={"key": "val"})
        assert req.name == "test-source"
        assert req.config == {"key": "val"}


class TestIngestSubmitSchema:
    def test_valid_url_accepted(self) -> None:
        from content_ingestion.api.schemas import IngestSubmitRequest

        req = IngestSubmitRequest(source_type="eodhd", url="https://example.com/article")
        assert req.url == "https://example.com/article"

    def test_private_ip_rejected(self) -> None:
        from content_ingestion.api.schemas import IngestSubmitRequest

        with pytest.raises(ValidationError, match="private"):
            IngestSubmitRequest(source_type="eodhd", url="http://192.168.1.1/secret")

    def test_localhost_rejected(self) -> None:
        from content_ingestion.api.schemas import IngestSubmitRequest

        with pytest.raises(ValidationError, match="private"):
            IngestSubmitRequest(source_type="eodhd", url="http://127.0.0.1/secret")

    def test_non_http_scheme_rejected(self) -> None:
        from content_ingestion.api.schemas import IngestSubmitRequest

        with pytest.raises(ValidationError, match="http"):
            IngestSubmitRequest(source_type="eodhd", url="ftp://example.com/file")

    def test_raw_content_at_5mb_boundary(self) -> None:
        from content_ingestion.api.schemas import IngestSubmitRequest

        # Exactly at 5MB should be accepted
        content = "x" * (5 * 1024 * 1024)
        req = IngestSubmitRequest(source_type="eodhd", raw_content=content)
        assert len(req.raw_content) == 5 * 1024 * 1024
