"""Tombstone tests — verify that the retired MacroIndicatorWorker raises ImportError.

The worker was replaced by MacroIndicatorDatasetConsumer (13D-7).
See: tests/unit/infrastructure/consumer/test_macro_indicator_dataset_consumer.py
"""

import importlib
import sys

import pytest

pytestmark = pytest.mark.unit


@pytest.mark.unit()
def test_macro_indicator_worker_raises_import_error() -> None:
    """Importing the tombstoned worker module must raise ImportError."""
    module_name = "knowledge_graph.infrastructure.workers.macro_indicator_worker"
    sys.modules.pop(module_name, None)
    with pytest.raises(ImportError, match="has been removed"):
        importlib.import_module(module_name)
