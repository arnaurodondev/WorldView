"""Unit tests for security hardening + port abstractions (Wave 4)."""

from __future__ import annotations

import socket
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from content_ingestion.api.schemas import IngestSubmitRequest, SourceCreateRequest, SourceUpdateRequest
from content_ingestion.application.ports import BronzeStoragePort, FetchLogPort, OutboxPort, SourceAdapterPort
from content_ingestion.infrastructure.adapters.base import SourceAdapter
from pydantic import ValidationError

pytestmark = pytest.mark.unit


class TestURLValidation:
    def test_http_url_accepted(self) -> None:
        req = IngestSubmitRequest(url="http://example.com/article", source_type="manual")
        assert req.url == "http://example.com/article"

    def test_https_url_accepted(self) -> None:
        req = IngestSubmitRequest(url="https://example.com/article", source_type="manual")
        assert req.url == "https://example.com/article"

    def test_ftp_scheme_rejected(self) -> None:
        with pytest.raises(ValidationError, match="http or https"):
            IngestSubmitRequest(url="ftp://example.com/file", source_type="manual")

    def test_no_scheme_rejected(self) -> None:
        with pytest.raises(ValidationError, match="http or https"):
            IngestSubmitRequest(url="example.com/article", source_type="manual")

    def test_private_ip_127_rejected(self) -> None:
        with pytest.raises(ValidationError, match="private IP"):
            IngestSubmitRequest(url="http://127.0.0.1/admin", source_type="manual")

    def test_private_ip_10_rejected(self) -> None:
        with pytest.raises(ValidationError, match="private IP"):
            IngestSubmitRequest(url="http://10.0.0.5/internal", source_type="manual")

    def test_private_ip_192_168_rejected(self) -> None:
        with pytest.raises(ValidationError, match="private IP"):
            IngestSubmitRequest(url="http://192.168.1.1/admin", source_type="manual")

    def test_private_ip_169_254_rejected(self) -> None:
        with pytest.raises(ValidationError, match="private IP"):
            IngestSubmitRequest(url="http://169.254.169.254/metadata", source_type="manual")

    def test_public_ip_accepted(self) -> None:
        req = IngestSubmitRequest(url="http://8.8.8.8/dns", source_type="manual")
        assert req.url is not None

    def test_hostname_accepted(self) -> None:
        # Mock DNS to return a public IP (test env may not resolve example.com)
        public_addr = [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("93.184.216.34", 0))]
        with patch("content_ingestion.api.schemas.socket.getaddrinfo", return_value=public_addr):
            req = IngestSubmitRequest(url="https://api.example.com/v1/data", source_type="manual")
        assert req.url is not None

    def test_none_url_accepted(self) -> None:
        req = IngestSubmitRequest(url=None, raw_content="data", source_type="manual")
        assert req.url is None


class TestConfigDictConstraint:
    def test_valid_config_types(self) -> None:
        req = SourceCreateRequest(
            name="test",
            source_type="eodhd",
            config={"key": "value", "count": 5, "enabled": True},
        )
        assert req.config == {"key": "value", "count": 5, "enabled": True}

    def test_nested_dict_rejected(self) -> None:
        with pytest.raises(ValidationError):
            SourceCreateRequest(
                name="test",
                source_type="eodhd",
                config={"nested": {"bad": "value"}},  # type: ignore[dict-item]
            )

    def test_list_value_rejected(self) -> None:
        with pytest.raises(ValidationError):
            SourceCreateRequest(
                name="test",
                source_type="eodhd",
                config={"items": [1, 2, 3]},  # type: ignore[dict-item]
            )

    def test_update_config_same_constraint(self) -> None:
        req = SourceUpdateRequest(config={"api_key": "xyz"})
        assert req.config == {"api_key": "xyz"}


class TestSourceRepositoryAllowlist:
    async def test_mutable_field_accepted(self) -> None:
        from content_ingestion.infrastructure.db.repositories.source import SourceRepository

        # Verify the allowlist contains expected fields
        assert "name" in SourceRepository._MUTABLE_FIELDS
        assert "enabled" in SourceRepository._MUTABLE_FIELDS
        assert "config" in SourceRepository._MUTABLE_FIELDS

    async def test_immutable_field_rejected(self) -> None:
        from content_ingestion.infrastructure.db.repositories.source import SourceRepository

        session = AsyncMock()
        repo = SourceRepository(session)

        # Mock get_by_id to return a mock source
        mock_source = MagicMock()
        repo.get_by_id = AsyncMock(return_value=mock_source)  # type: ignore[method-assign]

        with pytest.raises(ValueError, match="not mutable"):
            await repo.update(MagicMock(), source_type="hacked")

    async def test_id_field_not_mutable(self) -> None:
        from content_ingestion.infrastructure.db.repositories.source import SourceRepository

        assert "id" not in SourceRepository._MUTABLE_FIELDS
        assert "source_type" not in SourceRepository._MUTABLE_FIELDS
        assert "created_at" not in SourceRepository._MUTABLE_FIELDS


class TestPortAbstractions:
    def test_source_adapter_inherits_port(self) -> None:
        """Infrastructure SourceAdapter ABC inherits from SourceAdapterPort."""
        assert issubclass(SourceAdapter, SourceAdapterPort)

    def test_fetch_log_port_is_runtime_checkable(self) -> None:
        """FetchLogPort is a runtime-checkable Protocol."""
        mock = AsyncMock()
        mock.exists_by_url_hash = AsyncMock()
        mock.create = AsyncMock()
        assert isinstance(mock, FetchLogPort)

    def test_outbox_port_is_runtime_checkable(self) -> None:
        """OutboxPort is a runtime-checkable Protocol."""
        mock = AsyncMock()
        mock.append = AsyncMock()
        assert isinstance(mock, OutboxPort)

    def test_bronze_storage_port_is_runtime_checkable(self) -> None:
        """BronzeStoragePort is a runtime-checkable Protocol."""
        mock = AsyncMock()
        mock.put_object = AsyncMock()
        assert isinstance(mock, BronzeStoragePort)

    def test_use_case_has_no_infrastructure_imports(self) -> None:
        """The use case module must not import from infrastructure layer."""
        import inspect

        from content_ingestion.application.use_cases import fetch_and_write

        source = inspect.getsource(fetch_and_write)
        # Check runtime imports (not TYPE_CHECKING)
        # TYPE_CHECKING imports are fine since they don't execute at runtime
        lines = source.split("\n")
        in_type_checking = False
        for line in lines:
            stripped = line.strip()
            if stripped == "if TYPE_CHECKING:":
                in_type_checking = True
                continue
            if in_type_checking and not stripped.startswith(("from ", "import ", "#", "")):
                in_type_checking = False
            if not in_type_checking and "from content_ingestion.infrastructure" in stripped:
                pytest.fail(f"Infrastructure import found in use case: {stripped}")
