"""ml-clients — ML model client protocols and adapters."""

from ml_clients.adapters.gemini_description import GeminiDescriptionAdapter
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
from ml_clients.description_client import EntityDescriptionClient, NullDescriptionAdapter
from ml_clients.errors import FatalError, RetryableError
from ml_clients.protocols import EmbeddingClient, ExtractionClient, NERClient

__all__ = [
    "EmbeddingClient",
    "EmbeddingInput",
    "EmbeddingOutput",
    "EntityDescriptionClient",
    "EntityMention",
    "ExtractionClient",
    "ExtractionInput",
    "ExtractionOutput",
    "FatalError",
    "GeminiDescriptionAdapter",
    "MLClientsSettings",
    "NERClient",
    "NERInput",
    "NEROutput",
    "NullDescriptionAdapter",
    "RetryableError",
]
