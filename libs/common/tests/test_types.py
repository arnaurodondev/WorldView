"""Unit tests for common.types module."""

from __future__ import annotations

import uuid

from common.types import (
    EventId,
    InstrumentId,
    JsonDict,
    TenantId,
    TopicName,
    TransactionId,
    UserId,
)


class TestUUIDNewTypes:
    """NewType wrappers around UUID are transparent at runtime (zero-cost)."""

    def test_tenant_id_wraps_uuid(self) -> None:
        raw = uuid.uuid4()
        tid = TenantId(raw)
        assert isinstance(tid, uuid.UUID)
        assert tid == raw

    def test_user_id_wraps_uuid(self) -> None:
        raw = uuid.uuid4()
        uid = UserId(raw)
        assert isinstance(uid, uuid.UUID)
        assert uid == raw

    def test_instrument_id_wraps_uuid(self) -> None:
        raw = uuid.uuid4()
        iid = InstrumentId(raw)
        assert isinstance(iid, uuid.UUID)
        assert iid == raw

    def test_transaction_id_wraps_uuid(self) -> None:
        raw = uuid.uuid4()
        txid = TransactionId(raw)
        assert isinstance(txid, uuid.UUID)
        assert txid == raw


class TestStrNewTypes:
    """NewType wrappers around str are transparent at runtime."""

    def test_event_id_wraps_str(self) -> None:
        raw = "01ABCDEF"
        eid = EventId(raw)
        assert isinstance(eid, str)
        assert eid == raw

    def test_topic_name_wraps_str(self) -> None:
        raw = "market.dataset.fetched"
        tn = TopicName(raw)
        assert isinstance(tn, str)
        assert tn == raw


class TestJsonDict:
    """JsonDict = dict[str, Any] — verify usage patterns."""

    def test_empty_dict(self) -> None:
        d: JsonDict = {}
        assert isinstance(d, dict)

    def test_nested_values(self) -> None:
        d: JsonDict = {
            "string": "value",
            "number": 42,
            "float": 3.14,
            "bool": True,
            "null": None,
            "list": [1, 2, 3],
            "nested": {"key": "val"},
        }
        assert d["string"] == "value"
        assert d["number"] == 42
        assert d["nested"]["key"] == "val"

    def test_json_dict_is_dict(self) -> None:
        d: JsonDict = {"k": "v"}
        assert isinstance(d, dict)

    def test_any_value_type(self) -> None:
        # JsonDict accepts Any values — no runtime restriction
        d: JsonDict = {"anything": object()}
        assert "anything" in d
