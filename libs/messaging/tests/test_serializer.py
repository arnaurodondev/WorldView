"""Tests for Avro serializer protocol and configuration (T-032)."""

from __future__ import annotations

from messaging.kafka.serializer import (
    AvroDictable,
    AvroSerializerConfig,
    topic_event_type_subject_name_strategy,
)


class _SampleEvent:
    """Minimal AvroDictable implementation for testing."""

    @property
    def event_type(self) -> str:
        return "market.dataset.fetched"

    def to_dict(self) -> dict:
        return {"event_type": self.event_type, "payload": {}}


class _NotAvroDictable:
    """Object missing the required protocol attributes."""

    def some_method(self) -> None:
        pass


class TestAvroDictableProtocol:
    def test_sample_event_satisfies_protocol(self) -> None:
        event = _SampleEvent()
        assert isinstance(event, AvroDictable)

    def test_missing_event_type_fails_protocol(self) -> None:
        class NoEventType:
            def to_dict(self) -> dict:
                return {}

        obj = NoEventType()
        assert not isinstance(obj, AvroDictable)

    def test_missing_to_dict_fails_protocol(self) -> None:
        class NoToDict:
            @property
            def event_type(self) -> str:
                return "x"

        obj = NoToDict()
        assert not isinstance(obj, AvroDictable)

    def test_unrelated_object_fails_protocol(self) -> None:
        assert not isinstance(_NotAvroDictable(), AvroDictable)

    def test_event_type_property_accessible(self) -> None:
        event = _SampleEvent()
        assert event.event_type == "market.dataset.fetched"


class TestAvroSerializerConfig:
    def test_production_defaults(self) -> None:
        cfg = AvroSerializerConfig()
        assert cfg.auto_register_schemas is False
        assert cfg.use_latest_version is False
        assert cfg.normalize_schemas is False

    def test_to_dict_keys(self) -> None:
        cfg = AvroSerializerConfig()
        d = cfg.to_dict()
        assert d["auto.register.schemas"] is False
        assert d["use.latest.version"] is False
        assert d["normalize.schemas"] is False

    def test_dev_override(self) -> None:
        cfg = AvroSerializerConfig(auto_register_schemas=True)
        assert cfg.to_dict()["auto.register.schemas"] is True


class TestTopicEventTypeSubjectNameStrategy:
    def test_strategy_format(self) -> None:
        class FakeCtx:
            topic = "market.dataset.fetched"

        result = topic_event_type_subject_name_strategy(FakeCtx(), "MarketDatasetFetched")
        assert result == "market.dataset.fetched-MarketDatasetFetched"

    def test_different_topic_and_record(self) -> None:
        class FakeCtx:
            topic = "portfolio.events.v1"

        result = topic_event_type_subject_name_strategy(FakeCtx(), "PortfolioEvent")
        assert result == "portfolio.events.v1-PortfolioEvent"


class TestRootImport:
    def test_import_from_root(self) -> None:
        from messaging import (  # noqa: F401
            AvroDictable,
            AvroSerializerConfig,
            build_avro_serializer,
            topic_event_type_subject_name_strategy,
        )
