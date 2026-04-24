"""Tombstone tests — verify that the retired InsiderTransactionsWorker raises ImportError.

The worker was replaced by InsiderTransactionsDatasetConsumer (13D-8).
See: tests/unit/infrastructure/consumer/test_insider_transactions_dataset_consumer.py
"""

import importlib
import sys

import pytest


@pytest.mark.unit
def test_insider_transactions_worker_raises_import_error() -> None:
    """Importing the tombstoned worker module must raise ImportError."""
    module_name = "knowledge_graph.infrastructure.workers.insider_transactions_worker"
    sys.modules.pop(module_name, None)
    with pytest.raises(ImportError, match="has been removed"):
        importlib.import_module(module_name)
