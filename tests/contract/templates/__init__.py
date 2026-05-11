"""Reusable contract test templates.

These base classes are intentionally lightweight so services can inherit and
supply concrete schemas, endpoint cases, and integration probes.
"""

from .avro_contract_test import AvroContractTestBase
from .openapi_contract_test import OpenAPIContractTestBase
from .service_integration_contract_test import IntegrationContractTestBase

__all__ = [
    "AvroContractTestBase",
    "IntegrationContractTestBase",
    "OpenAPIContractTestBase",
]
