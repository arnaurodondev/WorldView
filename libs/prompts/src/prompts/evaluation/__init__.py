"""evaluation — Prompts used by LLM-as-judge evaluation harnesses.

Members:
- ``CHAT_QUALITY_JUDGE`` — 4-dim rubric grading chat-agent answers
  (used by ``scripts/chat_quality_judge.py``).
- ``CITATION_JUDGE`` — 0-3 claim/snippet faithfulness scorer
  (used by ``rag-chat`` ``ScoreCitationAccuracyUseCase``).
"""

from __future__ import annotations

from prompts.evaluation.chat_quality_judge import CHAT_QUALITY_JUDGE
from prompts.evaluation.citation_judge import CITATION_JUDGE

__all__ = ["CHAT_QUALITY_JUDGE", "CITATION_JUDGE"]
