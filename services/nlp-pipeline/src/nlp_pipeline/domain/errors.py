"""Domain error hierarchy for the NLP Pipeline service."""

from __future__ import annotations


class DomainError(Exception):
    """Base class for all NLP pipeline domain errors (R21 canonical name)."""

    error_code: str = "NLP_DOMAIN_ERROR"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message

    def __str__(self) -> str:
        return f"[{self.error_code}] {self.message}"


class NLPDomainError(DomainError):
    """Descriptive alias for NLP pipeline errors, extends DomainError."""


# ── Processing errors ─────────────────────────────────────────────────────────


class ProcessingError(NLPDomainError):
    """Raised when a pipeline block fails to process a document."""

    error_code = "PROCESSING_ERROR"


class RetryableProcessingError(ProcessingError):
    """Transient processing failure — safe to retry."""

    error_code = "RETRYABLE_PROCESSING_ERROR"


class EmbeddingError(ProcessingError):
    """Embedding generation failed."""

    error_code = "EMBEDDING_ERROR"


class RetryableEmbeddingError(EmbeddingError, RetryableProcessingError):
    """Transient embedding failure (e.g. Ollama OOM)."""

    error_code = "RETRYABLE_EMBEDDING_ERROR"


class NERError(ProcessingError):
    """GLiNER NER failed."""

    error_code = "NER_ERROR"


class RetryableNERError(NERError, RetryableProcessingError):
    """Transient NER failure."""

    error_code = "RETRYABLE_NER_ERROR"


class ExtractionError(ProcessingError):
    """LLM deep extraction failed."""

    error_code = "EXTRACTION_ERROR"


class RetryableExtractionError(ExtractionError, RetryableProcessingError):
    """Transient extraction failure."""

    error_code = "RETRYABLE_EXTRACTION_ERROR"


class EntityResolutionError(ProcessingError):
    """Entity resolution cascade failed."""

    error_code = "ENTITY_RESOLUTION_ERROR"


class SectioningError(ProcessingError):
    """Document sectioning failed."""

    error_code = "SECTIONING_ERROR"


# ── Infrastructure errors ─────────────────────────────────────────────────────


class BackpressureError(NLPDomainError):
    """Raised when the Ollama queue is at capacity."""

    error_code = "BACKPRESSURE_ERROR"


class IntelligenceDbAlembicError(NLPDomainError):
    """Raised if ALEMBIC_ENABLED=true is detected for intelligence_db (guard)."""

    error_code = "INTELLIGENCE_DB_ALEMBIC_FORBIDDEN"


# ── Domain integrity errors ───────────────────────────────────────────────────


class DocumentNotFoundError(NLPDomainError):
    """Referenced document could not be found."""

    error_code = "DOCUMENT_NOT_FOUND"


class InvalidRoutingScoreError(NLPDomainError):
    """Routing score computation produced an invalid result."""

    error_code = "INVALID_ROUTING_SCORE"


class PriceImpactError(DomainError):
    """Raised when ArticlePriceImpact validation or computation fails (R21)."""

    error_code = "PRICE_IMPACT_ERROR"
