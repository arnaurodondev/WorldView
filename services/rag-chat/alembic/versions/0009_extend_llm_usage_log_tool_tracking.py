"""Extend llm_usage_log with tool tracking columns (PLAN-0067 §0 I-2).

Adds 4 nullable columns for tool-use turn metadata tracking.
All columns are nullable/have defaults for forward-compatibility (R11):
- prompt_cache_read_tokens: tokens served from KV cache (provider-reported)
- prompt_cache_creation_tokens: new tokens written to KV cache (provider-reported)
- tool_calls_count: number of tool_use blocks emitted by the LLM in this turn
- tool_names: array of tool names called, for per-tool cost attribution

WHY these columns: PLAN-0067 W11-3 migrates to tool-use as the only path.
Tracking cache tokens lets us measure the cache hit rate improvement from
multi-turn context reuse. Tracking tool names enables per-tool cost breakdowns
in the internal_costs API.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY, TEXT

revision = "0009"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "llm_usage_log",
        sa.Column("prompt_cache_read_tokens", sa.Integer(), nullable=True),
    )
    op.add_column(
        "llm_usage_log",
        sa.Column("prompt_cache_creation_tokens", sa.Integer(), nullable=True),
    )
    op.add_column(
        "llm_usage_log",
        sa.Column("tool_calls_count", sa.Integer(), nullable=True, server_default="0"),
    )
    op.add_column(
        "llm_usage_log",
        sa.Column("tool_names", ARRAY(TEXT), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("llm_usage_log", "tool_names")
    op.drop_column("llm_usage_log", "tool_calls_count")
    op.drop_column("llm_usage_log", "prompt_cache_creation_tokens")
    op.drop_column("llm_usage_log", "prompt_cache_read_tokens")
