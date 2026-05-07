"""LLMJudgePort — application-layer port for the citation LLM judge.

A-001: Extracted from ``score_citation_accuracy.py`` into its own module so the
port ABC lives in ``application/ports/`` (the canonical location for all port
interfaces) rather than being co-located with the use-case implementation.

Infrastructure rule: NO infrastructure imports allowed in this module.
Domain rule: NO domain model imports required — the port operates on plain strings.
"""

from __future__ import annotations

from typing import Protocol


class LLMJudgePort(Protocol):
    """Minimal interface for the LLM judge used by ScoreCitationAccuracyUseCase.

    Implementations (e.g. ``CitationJudgeAdapter``) delegate to an existing
    completion-provider client and enforce per-call timeouts.

    A-002: ``snippet`` parameter removed — the use case pre-assembles the full
    rubric prompt and passes it as ``claim``.  The adapter's job is purely
    transport + timeout enforcement; it does not need the raw snippet separately.
    """

    async def score_citation(self, *, claim: str) -> str:
        """Return a single-digit string '0', '1', '2', or '3'.

        Args:
            claim: The full pre-assembled prompt text (rubric + fenced claim +
                fenced snippet) built by ``ScoreCitationAccuracyUseCase``.
                The adapter passes this verbatim to the underlying LLM provider.

        Returns:
            Raw LLM response string.  Callers parse the digit themselves.

        Raises:
            LLMJudgeTimeoutError: When the provider call exceeds the configured
                per-call timeout.
            Any provider-specific exception: Propagated unchanged so the caller
                can classify and count them.
        """
        ...


__all__ = ["LLMJudgePort"]
