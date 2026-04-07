"""Domain error hierarchy for the RAG-Chat service (S8).

R21: Every service defines DomainError(Exception) as the base class.
Architecture tests assert this class exists in domain/errors.py.
"""

from __future__ import annotations

from typing import Any


class DomainError(Exception):
    """Base class for all domain errors in S8."""

    error_code: str = "DOMAIN_ERROR"

    def __init__(
        self,
        message: str,
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.details: dict[str, Any] = details or {}

    def __str__(self) -> str:
        return f"[{self.error_code}] {self.message}"


class RagError(DomainError):
    """Base class for RAG pipeline domain errors."""

    error_code = "RAG_ERROR"


class InsufficientRetrievalError(RagError):
    """Not enough relevant items retrieved to ground a response."""

    error_code = "INSUFFICIENT_RETRIEVAL"


class ThreadNotFoundError(RagError):
    """Requested conversation thread does not exist."""

    error_code = "THREAD_NOT_FOUND"


class RateLimitExceededError(RagError):
    """Tenant/user has exceeded the request rate limit."""

    error_code = "RATE_LIMIT_EXCEEDED"


class ProviderUnavailableError(RagError):
    """All configured LLM providers are unavailable."""

    error_code = "PROVIDER_UNAVAILABLE"


class PromptInjectionError(RagError):
    """User input contains suspected prompt injection."""

    error_code = "PROMPT_INJECTION"


class PIIDetectedError(RagError):
    """User input contains detected personally identifiable information."""

    error_code = "PII_DETECTED"


class BriefingAuthError(DomainError):
    """X-Internal-Token missing or invalid on the /internal/v1/briefings endpoint."""

    error_code = "BRIEFING_AUTH_FAILED"
