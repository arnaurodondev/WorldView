"""ml-clients — ML model client protocols and adapters."""

from ml_clients.adapters.embeddinggemma_router import EmbeddingGemmaRouterAdapter
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
from ml_clients.pricing import MODEL_PRICING, ModelPricing, compute_cost
from ml_clients.protocols import EmbeddingClient, ExtractionClient, NERClient
from ml_clients.text_budget import estimate_bert_tokens, truncate_for_bge
from ml_clients.usage_log import LlmCallUsage, LlmUsageLogProtocol

__all__ = [
    "MODEL_PRICING",
    "EmbeddingClient",
    "EmbeddingGemmaRouterAdapter",
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
    "MODEL_PRICING",
    "LlmCallUsage",
    "LlmUsageLogProtocol",
    "MLClientsSettings",
    "ModelPricing",
    "NERClient",
    "NERInput",
    "NEROutput",
    "NullDescriptionAdapter",
    "RetryableError",
    "compute_cost",
    "estimate_bert_tokens",
    "estimate_cost",
    "estimate_tokens_from_text",
    "truncate_for_bge",
]
