"""PLAN-0089 Wave L-5b — add intelligence rollup columns to instrument_fundamentals_snapshot.

WHY THIS MIGRATION EXISTS:
  The L-5b nightly sync worker (``SyncIntelligenceRollupUseCase``) pulls 6
  intelligence fields from 4 upstream services (S6/S7/S10/S8) and
  materialises them into ``instrument_fundamentals_snapshot``.  Before this
  migration those 7 columns do not exist, so the worker cannot write to them.

COLUMNS ADDED (all nullable — R11 forward-compat; no existing row disturbed):
  * ``news_count_7d``                 INTEGER — S6 article count, trailing 7 d
  * ``llm_relevance_7d_max``          FLOAT   — S6 max LLM relevance, 7 d
  * ``display_relevance_7d_weighted`` FLOAT   — S6 display relevance weighted, 7 d
  * ``recent_contradiction_count``    INTEGER — S7 contradiction count, 7 d
  * ``has_active_alert``              BOOLEAN — S10 active alert flag
  * ``has_ai_brief``                  BOOLEAN — S8 AI brief flag
  * ``intelligence_rollup_synced_at`` TIMESTAMPTZ — worker freshness timestamp

IDEMPOTENCY: every ``ALTER TABLE`` uses ``ADD COLUMN IF NOT EXISTS`` so
re-running on an already-migrated DB is a no-op (matching the R11 pattern
used by migrations 028 / 030 / 031 / 032).

Chains from migration 034 (``034_clear_macro_stray_sector``).
"""

from __future__ import annotations

from alembic import op

revision = "035"
down_revision = "034"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add 7 nullable intelligence-rollup columns to instrument_fundamentals_snapshot."""
    # Use raw SQL for IF NOT EXISTS — SQLAlchemy's op.add_column() does not
    # support the idiom natively (it raises if the column already exists).
    op.execute("ALTER TABLE instrument_fundamentals_snapshot " "ADD COLUMN IF NOT EXISTS news_count_7d INTEGER")
    op.execute(
        "ALTER TABLE instrument_fundamentals_snapshot " "ADD COLUMN IF NOT EXISTS llm_relevance_7d_max DOUBLE PRECISION"
    )
    op.execute(
        "ALTER TABLE instrument_fundamentals_snapshot "
        "ADD COLUMN IF NOT EXISTS display_relevance_7d_weighted DOUBLE PRECISION"
    )
    op.execute(
        "ALTER TABLE instrument_fundamentals_snapshot " "ADD COLUMN IF NOT EXISTS recent_contradiction_count INTEGER"
    )
    op.execute("ALTER TABLE instrument_fundamentals_snapshot " "ADD COLUMN IF NOT EXISTS has_active_alert BOOLEAN")
    op.execute("ALTER TABLE instrument_fundamentals_snapshot " "ADD COLUMN IF NOT EXISTS has_ai_brief BOOLEAN")
    op.execute(
        "ALTER TABLE instrument_fundamentals_snapshot "
        "ADD COLUMN IF NOT EXISTS intelligence_rollup_synced_at TIMESTAMPTZ"
    )

    # ── Seed screen_field_metadata rows for the 6 intelligence filter fields ──
    # LOCK-STEP with ``_get_static_screen_fields()`` in ``app.py``.
    # The 6-hour refresh loop will UPSERT from the in-memory list; the values
    # below must be byte-identical to those entries or the loop silently
    # overwrites the seeded rows on first tick.
    l5b_fields = [
        (
            "news_count_7d",
            "NEWS 7D",
            "numeric",
            "count",
            "Number of news articles mentioning this instrument in the past 7 days",
        ),
        (
            "llm_relevance_7d_max",
            "LLM REL MAX",
            "numeric",
            "score_1",
            "Maximum LLM relevance score across all news articles in the past 7 days (0-1)",
        ),
        (
            "display_relevance_7d_weighted",
            "DISP REL 7D",
            "numeric",
            "score_1",
            "Weighted display relevance score across all news articles in the past 7 days (0-1)",
        ),
        (
            "recent_contradiction_count",
            "CONTRADICTIONS",
            "numeric",
            "count",
            "Number of intelligence contradictions detected in the past 7 days",
        ),
        ("has_active_alert", "HAS ALERT", "numeric", None, "Instrument has at least one active flash alert"),
        ("has_ai_brief", "HAS BRIEF", "numeric", None, "Instrument has a current AI-generated intelligence brief"),
    ]
    for field_name, label, field_type, unit, description in l5b_fields:
        op.execute(
            f"""
            INSERT INTO screen_field_metadata
                (field_name, label, field_type, unit, description, observed_min, observed_max, null_fraction, updated_at)
            VALUES
                ('{field_name}', '{label}', '{field_type}',
                 {'NULL' if unit is None else f"'{unit}'"}, '{description}',
                 NULL, NULL, 0.0, now())
            ON CONFLICT (field_name) DO UPDATE
                SET label        = EXCLUDED.label,
                    field_type   = EXCLUDED.field_type,
                    unit         = EXCLUDED.unit,
                    description  = EXCLUDED.description,
                    updated_at   = now()
            """
        )


def downgrade() -> None:
    """Drop the 7 intelligence-rollup columns and their screen_field_metadata rows."""
    # Remove screen_field_metadata rows first (no FK, so order is arbitrary)
    op.execute(
        "DELETE FROM screen_field_metadata "
        "WHERE field_name IN ("
        "    'news_count_7d', 'llm_relevance_7d_max', 'display_relevance_7d_weighted',"
        "    'recent_contradiction_count', 'has_active_alert', 'has_ai_brief'"
        ")"
    )
    # Drop snapshot columns
    for col in (
        "news_count_7d",
        "llm_relevance_7d_max",
        "display_relevance_7d_weighted",
        "recent_contradiction_count",
        "has_active_alert",
        "has_ai_brief",
        "intelligence_rollup_synced_at",
    ):
        op.execute(f"ALTER TABLE instrument_fundamentals_snapshot DROP COLUMN IF EXISTS {col}")
