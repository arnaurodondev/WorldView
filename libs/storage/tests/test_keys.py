"""Tests for storage.key_builder (KeyBuilder + KeyComponents)."""

from __future__ import annotations

import dataclasses

import pytest

from storage.exceptions import InvalidObjectKeyError
from storage.key_builder import KeyBuilder, KeyComponents


class TestKeyBuilderBuild:
    def test_builds_canonical_key(self) -> None:
        key = KeyBuilder.build(
            service="market-ingestion",
            domain="ohlcv",
            resource_id="AAPL.US/2024-01-01_2024-12-31",
            artifact="canonical",
            version="v2",
            extension="parquet",
        )
        assert key == "market-ingestion/ohlcv/AAPL.US/2024-01-01_2024-12-31/canonical/v2.parquet"

    def test_default_version_and_extension(self) -> None:
        key = KeyBuilder.build(
            service="svc",
            domain="dom",
            resource_id="res",
            artifact="art",
        )
        assert key.endswith("/v1.parquet")

    def test_raises_on_uppercase_service(self) -> None:
        with pytest.raises(InvalidObjectKeyError, match="service"):
            KeyBuilder.build("Market-Ingestion", "dom", "res", "art")

    def test_raises_on_invalid_version(self) -> None:
        with pytest.raises(InvalidObjectKeyError, match="version"):
            KeyBuilder.build("svc", "dom", "res", "art", version="1")

    def test_raises_on_invalid_extension(self) -> None:
        with pytest.raises(InvalidObjectKeyError, match="extension"):
            KeyBuilder.build("svc", "dom", "res", "art", extension="par.quet")

    def test_raises_on_empty_resource_id(self) -> None:
        with pytest.raises(InvalidObjectKeyError):
            KeyBuilder.build("svc", "dom", "", "art")

    def test_version_with_number(self) -> None:
        key = KeyBuilder.build("svc", "dom", "res", "art", version="v42")
        assert "/v42." in key

    def test_raises_on_service_starting_with_digit(self) -> None:
        with pytest.raises(InvalidObjectKeyError):
            KeyBuilder.build("1svc", "dom", "res", "art")


class TestKeyBuilderValidate:
    VALID_KEY = "market-ingestion/ohlcv/AAPL.US/2024-01-01/canonical/v1.parquet"

    def test_valid_key_does_not_raise(self) -> None:
        KeyBuilder.validate(self.VALID_KEY)

    def test_empty_key_raises(self) -> None:
        with pytest.raises(InvalidObjectKeyError):
            KeyBuilder.validate("")

    def test_key_without_version_raises(self) -> None:
        with pytest.raises(InvalidObjectKeyError):
            KeyBuilder.validate("svc/dom/res/art/noversion")

    def test_too_few_segments_raises(self) -> None:
        with pytest.raises(InvalidObjectKeyError):
            KeyBuilder.validate("svc/dom/v1.parquet")


class TestKeyBuilderParse:
    def test_parse_simple_key(self) -> None:
        key = "market-ingestion/ohlcv/AAPL.US/canonical/v1.parquet"
        kc = KeyBuilder.parse(key)
        assert kc.service == "market-ingestion"
        assert kc.domain == "ohlcv"
        assert kc.resource_id == "AAPL.US"
        assert kc.artifact == "canonical"
        assert kc.version == "v1"
        assert kc.extension == "parquet"

    def test_parse_key_with_deep_resource_id(self) -> None:
        key = "market-ingestion/ohlcv/AAPL.US/2024-01-01_2024-12-31/canonical/v2.parquet"
        kc = KeyBuilder.parse(key)
        assert kc.resource_id == "AAPL.US/2024-01-01_2024-12-31"
        assert kc.version == "v2"

    def test_parse_roundtrip(self) -> None:
        original = "svc/dom/a/b/c/art/v3.json"
        kc = KeyBuilder.parse(original)
        assert kc.full_key == original

    def test_parse_invalid_key_raises(self) -> None:
        with pytest.raises(InvalidObjectKeyError):
            KeyBuilder.parse("not-a-valid-key")


class TestKeyBuilderBuildPrefix:
    def test_service_only_prefix(self) -> None:
        prefix = KeyBuilder.build_prefix("market-ingestion")
        assert prefix == "market-ingestion/"

    def test_service_and_domain_prefix(self) -> None:
        prefix = KeyBuilder.build_prefix("market-ingestion", "ohlcv")
        assert prefix == "market-ingestion/ohlcv/"

    def test_raises_on_invalid_service_slug(self) -> None:
        with pytest.raises(InvalidObjectKeyError):
            KeyBuilder.build_prefix("Market_Data")


class TestKeyComponents:
    def test_full_key_reconstruction(self) -> None:
        kc = KeyComponents(
            service="svc",
            domain="dom",
            resource_id="res",
            artifact="art",
            version="v1",
            extension="json",
        )
        assert kc.full_key == "svc/dom/res/art/v1.json"

    def test_frozen_dataclass(self) -> None:
        kc = KeyComponents("s", "d", "r", "a", "v1", "bin")
        with pytest.raises(dataclasses.FrozenInstanceError):
            kc.service = "other"  # type: ignore[misc]
