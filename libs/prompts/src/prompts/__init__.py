"""prompts — Centralised, versioned prompt templates for LLM interactions."""

from __future__ import annotations

from prompts._base import PromptTemplate
from prompts._safety import SAFETY_FOOTER
from prompts.retrieval.hyde import HYDE_EXPANSION

__all__ = [
    "HYDE_EXPANSION",
    "SAFETY_FOOTER",
    "PromptTemplate",
]
