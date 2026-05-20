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
# BP-420: phone regex requires at least one separator between groups so that
# bare 10-digit identifiers (e.g. SEC CIK numbers like 0000320193) are not
# falsely flagged. Parenthesised area codes still match: (800) 555-1234.
_PHONE_RE = re.compile(r"\b(\+?1[-.\s])?\(?\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}\b")
_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b")
_SSN_RE = re.compile(r"\b\d{3}[-\s]\d{2}[-\s]\d{4}\b")
# WHY UUID exclusion: UUIDs contain digit groups separated by hyphens which
# can match the card pattern (e.g. "01900000-0000-7000-" matches 13 digits
# with optional hyphens). We use a negative lookahead/lookbehind to exclude
# the UUID format (8-4-4-4-12 hex chars) and require the digit run to be
# surrounded by non-UUID context (no hex letters or extra hyphen-digit groups).
# The exclusion is applied by requiring the first digit group after the
# word-boundary to NOT be followed by hex chars and hyphens in UUID style.
# Simpler and more accurate: require that the match NOT be part of a UUID
# (4 hex groups 8-4-4-4 separated by exactly one hyphen each).
_UUID_RE = re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")
_CARD_RE = re.compile(r"\b(?:\d[ -]?){13,19}\b")

_PII_PATTERNS: list[re.Pattern[str]] = [_PHONE_RE, _EMAIL_RE, _SSN_RE, _CARD_RE]


def _check_pii(message: str) -> bool:
    """Return True if the message contains a PII match that is NOT a UUID.

    The credit card regex can false-positive on UUID strings (which are valid
    in entity-context system prompts). We strip all UUID occurrences before
    checking the card pattern, and then run the other patterns on the full text.

    WHY strip UUIDs first: UUID format (8-4-4-4-12 hex groups) is unambiguous and
    safe to remove before checking for card numbers.  Phone, email, and SSN patterns
    cannot match UUID-format strings so they are checked against the full text.
    """
    # Phone, email, SSN — checked against full text (no UUID conflict)
    for pattern in (_PHONE_RE, _EMAIL_RE, _SSN_RE):
        if pattern.search(message):
            return True
    # Card — checked against UUID-scrubbed text to prevent false positives
    scrubbed = _UUID_RE.sub("", message)
    return bool(_CARD_RE.search(scrubbed))


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
        if _check_pii(message):
            raise PIIDetectedError("Message contains PII")

        # 4. Injection heuristic
        for pattern in _INJECTION_PATTERNS:
            if pattern.search(message):
                raise PromptInjectionError("Potential prompt injection detected")

        # 5. XML-wrap to prevent injection bleed into system prompt
        token = secrets.token_hex(4)
        return f"<Q_{token}>{message}</Q_{token}>"
