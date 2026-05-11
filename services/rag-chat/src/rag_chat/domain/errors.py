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
    """Auth failed on the /internal/v1/briefings endpoint (PRD-0025: InternalJWTMiddleware)."""

    error_code = "BRIEFING_AUTH_FAILED"


class ContextGatheringError(DomainError):
    """All upstream context sources failed during briefing generation."""

    error_code = "CONTEXT_GATHERING_FAILED"


class EntityNotFoundError(DomainError):
    """Entity not found in knowledge graph."""

    error_code = "ENTITY_NOT_FOUND"


class ProviderClientError(RagError):
    """Raised when an LLM provider returns a 4xx client error.

    These errors indicate a bad request (bad prompt, invalid params, quota exceeded)
    not a service fault.  The circuit breaker MUST NOT count these as failures —
    only 5xx / network-layer errors indicate the provider itself is unhealthy.

    Args:
        message:     Human-readable description of the error.
        status_code: HTTP status code returned by the provider (4xx).
    """

    error_code = "PROVIDER_CLIENT_ERROR"

    def __init__(self, message: str, status_code: int) -> None:
        super().__init__(message)
        self.status_code = status_code


class LLMJudgeTimeoutError(DomainError):
    """LLM judge call exceeded the per-call timeout budget (PLAN-0084 A-1 T-A-1-02).

    Raised by CitationJudgeAdapter when asyncio.wait_for fires.
    The citation-accuracy cron loop catches this and skips the offending pair
    without crashing the cron task.
    """

    error_code = "LLM_JUDGE_TIMEOUT"


class BriefNotFoundError(DomainError):
    """Brief not found, or does not belong to the requesting user (PLAN-0066 Wave C).

    Raised by BriefFeedbackUseCase when the caller attempts to post feedback to a
    brief that either does not exist or belongs to a different user. The API layer
    converts this to HTTP 404 to prevent IDOR (Insecure Direct Object Reference)
    leakage — callers must not be told whether the brief exists but is owned by
    someone else, or simply does not exist at all.
    """

    error_code = "BRIEF_NOT_FOUND"
