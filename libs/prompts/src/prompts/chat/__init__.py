"""Chat prompt templates — intent-specific system prompts for RAG-Chat."""

from prompts.chat.tool_use import (
    TOOL_USE_SYSTEM_PROMPT_TEMPLATE,
    get_tool_use_system_prompt,
)

__all__ = [
    "TOOL_USE_SYSTEM_PROMPT_TEMPLATE",
    "get_tool_use_system_prompt",
]
