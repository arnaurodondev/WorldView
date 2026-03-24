"""Unit tests for common.types module."""

from __future__ import annotations

import uuid

from common.types import (
    DocumentId,
    EntityId,
    EventId,
    InstrumentId,
    JsonDict,
    MinIOKey,
    TenantId,
    TopicName,
    TransactionId,
    UrlHash,
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


class TestIngestionUUIDTypes:
    """DocumentId and EntityId are distinct NewType wrappers around UUID."""

    def test_document_id_wraps_uuid(self) -> None:
        raw = uuid.uuid4()
        doc_id = DocumentId(raw)
        assert isinstance(doc_id, uuid.UUID)
        assert doc_id == raw

    def test_entity_id_wraps_uuid(self) -> None:
        raw = uuid.uuid4()
        ent_id = EntityId(raw)
        assert isinstance(ent_id, uuid.UUID)
        assert ent_id == raw

    def test_document_id_and_entity_id_are_distinct(self) -> None:
        raw = uuid.uuid4()
        doc_id = DocumentId(raw)
        ent_id = EntityId(raw)
        # Both hold the same underlying UUID value, but are distinct NewType aliases
        assert doc_id == ent_id  # equal at runtime (identity function)
        assert type(doc_id) is type(ent_id)  # both are uuid.UUID at runtime


class TestIngestionStrTypes:
    """UrlHash and MinIOKey are distinct NewType wrappers around str."""

    def test_url_hash_wraps_str(self) -> None:
        raw = "a3f1e2d4" * 8  # 64-char hex digest
        url_hash = UrlHash(raw)
        assert isinstance(url_hash, str)
        assert url_hash == raw

    def test_minio_key_wraps_str(self) -> None:
        raw = "bronze/2026/03/23/abc123.json"
        minio_key = MinIOKey(raw)
        assert isinstance(minio_key, str)
        assert minio_key == raw

    def test_url_hash_and_minio_key_are_distinct(self) -> None:
        raw = "some-string"
        url_hash = UrlHash(raw)
        minio_key = MinIOKey(raw)
        # Equal at runtime; distinct types for the type-checker
        assert url_hash == minio_key
        assert type(url_hash) is type(minio_key)  # both are str at runtime


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
