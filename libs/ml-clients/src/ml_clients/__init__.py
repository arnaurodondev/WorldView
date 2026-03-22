"""ml-clients — ML model client protocols and adapters."""

from ml_clients.config import MLClientsSettings
from ml_clients.dataclasses import (
    EmbeddingInput,
    EmbeddingOutput,
    EntityMention,
    ExtractionInput,
    ExtractionOutput,
    NERInput,
    NEROutput,
)
from ml_clients.errors import FatalError, RetryableError
from ml_clients.protocols import EmbeddingClient, ExtractionClient, NERClient

__all__ = [
    # Protocols
    "EmbeddingClient",
    "NERClient",
    "ExtractionClient",
    # Dataclasses
    "EmbeddingInput",
    "EmbeddingOutput",
    "NERInput",
    "NEROutput",
    "EntityMention",
    "ExtractionInput",
    "ExtractionOutput",
    # Errors
    "RetryableError",
    "FatalError",
    # Config
    "MLClientsSettings",
]
