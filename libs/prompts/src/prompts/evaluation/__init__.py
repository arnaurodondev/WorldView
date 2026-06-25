"""evaluation — Prompts used by LLM-as-judge evaluation harnesses.

Members:
- ``CHAT_QUALITY_JUDGE`` — 4-dim rubric grading chat-agent ANSWERS
  (used by ``scripts/chat_quality_judge.py``).
- ``CHAT_TRAJECTORY_JUDGE`` — 4-dim rubric grading chat-agent TOOL-CHAIN
  trajectory / process (used by ``scripts/chat_trajectory_judge.py``, W2).
- ``CITATION_JUDGE`` — 0-3 claim/snippet faithfulness scorer
  (used by ``rag-chat`` ``ScoreCitationAccuracyUseCase``).
"""

from __future__ import annotations

from prompts.evaluation.chat_quality_judge import CHAT_QUALITY_JUDGE
from prompts.evaluation.chat_trajectory_judge import CHAT_TRAJECTORY_JUDGE
from prompts.evaluation.citation_judge import CITATION_JUDGE

__all__ = ["CHAT_QUALITY_JUDGE", "CHAT_TRAJECTORY_JUDGE", "CITATION_JUDGE"]
