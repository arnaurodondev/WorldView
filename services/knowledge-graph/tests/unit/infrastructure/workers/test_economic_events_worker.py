"""Tombstone tests — verify that the retired EconomicEventsWorker raises ImportError.

The worker was replaced by EconomicEventsDatasetConsumer (13D-6).
See: tests/unit/infrastructure/consumer/test_economic_events_dataset_consumer.py
"""

import importlib
import sys

import pytest

pytestmark = pytest.mark.unit


@pytest.mark.unit
def test_economic_events_worker_raises_import_error() -> None:
    """Importing the tombstoned worker module must raise ImportError."""
    module_name = "knowledge_graph.infrastructure.workers.economic_events_worker"
    # Evict any cached module so the ImportError fires fresh each time.
    sys.modules.pop(module_name, None)
    with pytest.raises(ImportError, match="has been removed"):
        importlib.import_module(module_name)
