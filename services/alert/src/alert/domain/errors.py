"""Domain error hierarchy for the Alert service (S10).

Convention: ``DomainError`` is the root (R21).  Subclasses are grouped by
concern.  ``# noqa: N818`` is applied where the name deliberately omits
the ``Error`` suffix for readability.
"""

from __future__ import annotations


class DomainError(Exception):
    """Base error for all S10 domain exceptions."""


# ---------------------------------------------------------------------------
# Alert errors
# ---------------------------------------------------------------------------


class AlertNotFoundError(DomainError):
    """Raised when an alert cannot be found by ID."""


class DuplicateAlertError(DomainError):
    """Raised when a dedup_key collision is detected (expected during dedup)."""


# ---------------------------------------------------------------------------
# Alert rule errors (PLAN-0113)
# ---------------------------------------------------------------------------


class RuleNotFoundError(DomainError):
    """Raised when a rule cannot be found / is not owned by the caller."""


class RuleLimitExceededError(DomainError):
    """Raised when a user has reached the per-user rule cap (PRD §9)."""


# ---------------------------------------------------------------------------
# Delivery errors
# ---------------------------------------------------------------------------


class DeliveryError(DomainError):
    """Base for alert delivery errors."""


class UserNotConnectedError(DeliveryError):
    """Raised when a WebSocket push targets a user with no active connection."""


# ---------------------------------------------------------------------------
# S1 client errors
# ---------------------------------------------------------------------------


class S1ClientError(DomainError):
    """Base for S1 Portfolio service client errors."""


class S1UnavailableError(S1ClientError):
    """Raised when S1 is unreachable — callers should degrade gracefully."""
