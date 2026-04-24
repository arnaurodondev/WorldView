"""Tombstone tests — verify that the retired S7 EodhDClient raises ImportError.

The EODHD HTTP client was removed as part of migrating workers 13D-6/7/8 to
Kafka consumers.  S2 (market-ingestion) now owns all EODHD HTTP calls.
"""

import importlib
import sys

import pytest


@pytest.mark.unit
def test_eodhd_client_raises_import_error() -> None:
    """Importing the tombstoned EODHD client module must raise ImportError."""
    module_name = "knowledge_graph.infrastructure.eodhd.client"
    sys.modules.pop(module_name, None)
    with pytest.raises(ImportError, match="has been removed"):
        importlib.import_module(module_name)
