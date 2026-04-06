"""Thin re-export shim — canonical settings live in infrastructure/config/settings.py."""

from rag_chat.infrastructure.config.settings import RagChatSettings

# Alias so existing imports of ``from rag_chat.config import Settings`` keep working.
Settings = RagChatSettings

__all__ = ["RagChatSettings", "Settings"]
