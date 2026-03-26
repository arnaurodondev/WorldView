"""Contract test: tenant.created Avro schema."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import fastavro
import pytest
from portfolio.application.messaging.mapper import tenant_created_to_dict
from portfolio.domain.events import TenantCreated

pytestmark = pytest.mark.contract

_SCHEMA_DIR = Path(__file__).parent.parent.parent / "src/portfolio/infrastructure/messaging/schemas"


def _load_schema(filename: str):  # type: ignore[no-untyped-def]
    path = _SCHEMA_DIR / filename
    return fastavro.parse_schema(json.loads(path.read_text()))


def test_tenant_created_valid_schema() -> None:
    """tenant.created mapper output must be valid against its Avro schema."""
    parsed_schema = _load_schema("tenant.created.v1.avsc")

    tenant_id = uuid4()
    event = TenantCreated(tenant_id=tenant_id, tenant_name="ACME Corp")
    output = tenant_created_to_dict(event)

    fastavro.validate(output, parsed_schema)


def test_tenant_created_optional_fields() -> None:
    """tenant.created with null correlation/causation IDs passes validation."""
    parsed_schema = _load_schema("tenant.created.v1.avsc")

    tenant_id = uuid4()
    event = TenantCreated(tenant_id=tenant_id, tenant_name="Test Tenant", correlation_id=None, causation_id=None)
    output = tenant_created_to_dict(event)

    fastavro.validate(output, parsed_schema)
