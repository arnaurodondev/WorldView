"""Application-layer port interfaces."""

from content_ingestion.application.ports.metrics import MetricsPort
from content_ingestion.application.ports.repositories import (
    AdapterStatePort,
    BronzeStoragePort,
    DLQPort,
    FetchLogPort,
    OutboxPort,
    SourcePort,
    TaskPort,
)
from content_ingestion.application.ports.source_adapter import SourceAdapterPort

__all__ = [
    "AdapterStatePort",
    "BronzeStoragePort",
    "DLQPort",
    "FetchLogPort",
    "MetricsPort",
    "OutboxPort",
    "SourceAdapterPort",
    "SourcePort",
    "TaskPort",
]
