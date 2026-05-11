"""Concrete ML client adapters."""

from ml_clients.adapters.anthropic_extraction import AnthropicExtractionAdapter
from ml_clients.adapters.chatgpt_extraction import ChatGPTExtractionAdapter
from ml_clients.adapters.deepinfra_embedding import DeepInfraEmbeddingAdapter
from ml_clients.adapters.deepseek_extraction import DeepSeekExtractionAdapter
from ml_clients.adapters.gemini_description import GeminiDescriptionAdapter
from ml_clients.adapters.gemini_extraction import GeminiExtractionAdapter
from ml_clients.adapters.gliner_adaptive import AdaptiveGLiNERHTTPAdapter
from ml_clients.adapters.gliner_local import GLiNERLocalAdapter
from ml_clients.adapters.jina_embedding import JinaEmbeddingAdapter
from ml_clients.adapters.ollama_embedding import OllamaEmbeddingAdapter
from ml_clients.adapters.ollama_extraction import OllamaExtractionAdapter

__all__ = [
    "AdaptiveGLiNERHTTPAdapter",
    "AnthropicExtractionAdapter",
    "ChatGPTExtractionAdapter",
    "DeepInfraEmbeddingAdapter",
    "DeepSeekExtractionAdapter",
    "GLiNERLocalAdapter",
    "GeminiDescriptionAdapter",
    "GeminiExtractionAdapter",
    "JinaEmbeddingAdapter",
    "OllamaEmbeddingAdapter",
    "OllamaExtractionAdapter",
]
