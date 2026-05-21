"""ml-clients — ML model client protocols and adapters."""

from ml_clients.adapters.gemini_description import GeminiDescriptionAdapter
from ml_clients.config import MLClientsSettings
from ml_clients.cost import estimate_cost, estimate_tokens_from_text
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
from ml_clients.fallback import (
    FallbackEmbeddingClient,
    FallbackExtractionClient,
    FallbackNERClient,
)
from ml_clients.protocols import EmbeddingClient, ExtractionClient, NERClient
from ml_clients.usage_log import LlmCallUsage, LlmUsageLogProtocol

__all__ = [
    "EmbeddingClient",
    "EmbeddingInput",
    "EmbeddingOutput",
    "EntityDescriptionClient",
    "EntityMention",
    "ExtractionClient",
    "ExtractionInput",
    "ExtractionOutput",
    "FallbackEmbeddingClient",
    "FallbackExtractionClient",
    "FallbackNERClient",
    "FatalError",
    "GeminiDescriptionAdapter",
    "LlmCallUsage",
    "LlmUsageLogProtocol",
    "MLClientsSettings",
    "NERClient",
    "NERInput",
    "NEROutput",
    "NullDescriptionAdapter",
    "RetryableError",
    "estimate_cost",
    "estimate_tokens_from_text",
]
