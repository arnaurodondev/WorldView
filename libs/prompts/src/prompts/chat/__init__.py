"""Chat prompt templates — intent-specific system prompts for RAG-Chat."""

from prompts.chat.safety_classifier import INJECTION_SAFETY_CLASSIFIER
from prompts.chat.tool_use import (
    TOOL_USE_SYSTEM_PROMPT_TEMPLATE,
    get_tool_use_system_prompt,
)

__all__ = [
    "INJECTION_SAFETY_CLASSIFIER",
    "TOOL_USE_SYSTEM_PROMPT_TEMPLATE",
    "get_tool_use_system_prompt",
]
