"""Backward-compatibility re-export — canonical settings live in rag_chat.config."""

from __future__ import annotations

from rag_chat.config import Settings as RagChatSettings

__all__ = ["RagChatSettings"]
