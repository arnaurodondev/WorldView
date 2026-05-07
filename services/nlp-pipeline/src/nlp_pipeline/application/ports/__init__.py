"""Application port interfaces for the NLP Pipeline service."""

from nlp_pipeline.application.ports.canonical_entity import CanonicalEntityPort
from nlp_pipeline.application.ports.chunk_search import ChunkSearchPort

__all__ = [
    "CanonicalEntityPort",
    "ChunkSearchPort",
]
