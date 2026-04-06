"""Stateless input validator for chat messages (T-E-1-01).

Applied before any LLM or DB interaction (pipeline Step 0).
Performs: HTML strip → truncate → PII check → injection heuristic → XML-wrap.
"""

from __future__ import annotations

import re
import secrets

import bleach  # type: ignore[import-untyped]

from rag_chat.domain.errors import PIIDetectedError, PromptInjectionError

_MAX_LENGTH = 2000

# PII patterns — compiled once at class level
_PHONE_RE = re.compile(r"\b(\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b")
_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b")
_SSN_RE = re.compile(r"\b\d{3}[-\s]?\d{2}[-\s]?\d{4}\b")
_CARD_RE = re.compile(r"\b(?:\d[ -]?){13,19}\b")

_PII_PATTERNS: list[re.Pattern[str]] = [_PHONE_RE, _EMAIL_RE, _SSN_RE, _CARD_RE]

# Prompt injection heuristics — compiled once (case-insensitive)
_INJECTION_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"ignore\s+(previous|prior|all)\s+instructions", re.IGNORECASE),
    re.compile(r"system\s*:", re.IGNORECASE),
    re.compile(r"you\s+are\s+now", re.IGNORECASE),
    re.compile(r"pretend\s+to\s+be", re.IGNORECASE),
    re.compile(r"forget\s+your\s+instructions", re.IGNORECASE),
    re.compile(r"<\s*/?system\s*>", re.IGNORECASE),
    re.compile(r"(?m)^assistant\s*:", re.IGNORECASE),
]


class InputValidator:
    """Sanitise and gate-check a raw user message before pipeline entry.

    All methods are synchronous — no I/O occurs inside this class.
    """

    def validate(self, message: str) -> str:
        """Validate and sanitise *message*.

        Returns the sanitised, XML-wrapped message.

        Raises:
            PIIDetectedError: if a PII pattern is found.
            PromptInjectionError: if an injection heuristic fires.
        """
        # 1. HTML strip
        message = bleach.clean(message, tags=[], strip=True)

        # 2. Truncate to max length
        message = message[:_MAX_LENGTH]

        # 3. PII check
        for pattern in _PII_PATTERNS:
            if pattern.search(message):
                raise PIIDetectedError("Message contains PII")

        # 4. Injection heuristic
        for pattern in _INJECTION_PATTERNS:
            if pattern.search(message):
                raise PromptInjectionError("Potential prompt injection detected")

        # 5. XML-wrap to prevent injection bleed into system prompt
        token = secrets.token_hex(4)
        return f"<Q_{token}>{message}</Q_{token}>"
