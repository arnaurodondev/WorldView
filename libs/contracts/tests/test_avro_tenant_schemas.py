"""Contract tests — PLAN-0086 multi-tenant pipeline Avro schema validation.

Validates that:
  - tenant_id fields exist (with correct defaults) in multi-tenant schemas.
  - New schemas (content.document.deleted.v1, nlp.document.ready.v1) are valid.
  - Canonical event dataclasses align field-for-field with their Avro counterparts.
  - Forward-compat: old events without tenant_id still deserialise (default=null).
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import fastavro

# Path to Avro schemas from the repo root — same resolution pattern as test_avro_alignment.py.
_SCHEMAS_DIR = Path(__file__).parent.parent.parent.parent / "infra" / "kafka" / "schemas"


def _load(name: str) -> dict:
    """Load and parse an Avro schema JSON file."""
    return json.loads((_SCHEMAS_DIR / name).read_text())


# ---------------------------------------------------------------------------
# tenant_id presence tests
# ---------------------------------------------------------------------------


def test_content_article_raw_has_tenant_id_field() -> None:
    """content.article.raw.v1 must have tenant_id (added in PLAN-0086)."""
    schema = fastavro.parse_schema(_load("content.article.raw.v1.avsc"))  # noqa: F841 — validates parse
    field_names = {f["name"] for f in _load("content.article.raw.v1.avsc")["fields"]}
    assert "tenant_id" in field_names


def test_content_article_stored_has_tenant_id_field() -> None:
    """content.article.stored.v1 must have tenant_id (propagated from raw)."""
    schema = fastavro.parse_schema(_load("content.article.stored.v1.avsc"))  # noqa: F841
    field_names = {f["name"] for f in _load("content.article.stored.v1.avsc")["fields"]}
    assert "tenant_id" in field_names


def test_nlp_article_enriched_has_tenant_id_field() -> None:
    """nlp.article.enriched.v1 must have tenant_id (propagated through S5→S6→S7)."""
    field_names = {f["name"] for f in _load("nlp.article.enriched.v1.avsc")["fields"]}
    assert "tenant_id" in field_names


# ---------------------------------------------------------------------------
# New schema validity tests
# ---------------------------------------------------------------------------


def test_content_document_deleted_schema_valid() -> None:
    """content.document.deleted.v1 (new in PLAN-0086) must parse without errors."""
    schema = fastavro.parse_schema(_load("content.document.deleted.v1.avsc"))
    assert schema is not None


def test_nlp_document_ready_schema_valid() -> None:
    """nlp.document.ready.v1 (new in PLAN-0086) must parse without errors."""
    schema = fastavro.parse_schema(_load("nlp.document.ready.v1.avsc"))
    assert schema is not None


# ---------------------------------------------------------------------------
# Forward-compatibility: default=null on tenant_id
# ---------------------------------------------------------------------------


def test_content_article_raw_tenant_id_defaults_to_null() -> None:
    """Forward compat: old events without tenant_id still deserialise (default=null).

    If default were absent or non-null, Schema Registry would reject old events
    as a backward-incompatible change (BP-126).
    """
    raw_schema = _load("content.article.raw.v1.avsc")
    tenant_id_field = next(f for f in raw_schema["fields"] if f["name"] == "tenant_id")
    assert (
        tenant_id_field["default"] is None
    ), "tenant_id default must be null for forward-compatibility with old events"


def test_content_article_stored_tenant_id_defaults_to_null() -> None:
    """Forward compat: content.article.stored.v1 tenant_id default must be null."""
    raw_schema = _load("content.article.stored.v1.avsc")
    tenant_id_field = next(f for f in raw_schema["fields"] if f["name"] == "tenant_id")
    assert tenant_id_field["default"] is None


def test_nlp_article_enriched_tenant_id_defaults_to_null() -> None:
    """Forward compat: nlp.article.enriched.v1 tenant_id default must be null."""
    raw_schema = _load("nlp.article.enriched.v1.avsc")
    tenant_id_field = next(f for f in raw_schema["fields"] if f["name"] == "tenant_id")
    assert tenant_id_field["default"] is None


# ---------------------------------------------------------------------------
# Canonical model ↔ Avro field alignment
# ---------------------------------------------------------------------------


def test_content_document_deleted_canonical_model_fields_match_avro() -> None:
    """ContentDocumentDeleted dataclass must have exactly the same fields as the Avro schema."""
    from contracts.events.content.document_deleted import ContentDocumentDeleted

    avro_fields = {f["name"] for f in _load("content.document.deleted.v1.avsc")["fields"]}
    model_fields = {f.name for f in dataclasses.fields(ContentDocumentDeleted)}
    assert avro_fields == model_fields, (
        f"Avro↔model mismatch. "
        f"In Avro only: {avro_fields - model_fields}. "
        f"In model only: {model_fields - avro_fields}."
    )


def test_nlp_document_ready_canonical_model_fields_match_avro() -> None:
    """NlpDocumentReady dataclass must have exactly the same fields as the Avro schema."""
    from contracts.events.nlp.document_ready import NlpDocumentReady

    avro_fields = {f["name"] for f in _load("nlp.document.ready.v1.avsc")["fields"]}
    model_fields = {f.name for f in dataclasses.fields(NlpDocumentReady)}
    assert avro_fields == model_fields, (
        f"Avro↔model mismatch. "
        f"In Avro only: {avro_fields - model_fields}. "
        f"In model only: {model_fields - avro_fields}."
    )
