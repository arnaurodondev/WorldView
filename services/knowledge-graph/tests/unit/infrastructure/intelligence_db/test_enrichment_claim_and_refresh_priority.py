"""Unit tests for PLAN-0093 Wave C-4 — atomic enrichment claim + NULL-priority refresh.

Covers the SQL contracts of:
  - ``EntityEnrichmentAdapter.claim_for_enrichment``  (T-C-4-01)
  - ``EntityEnrichmentAdapter.decrement_attempts``    (T-C-4-01 rollback path)
  - ``EntityEmbeddingStateRepository.get_due_for_refresh`` ORDER BY (T-C-4-02)
  - ``EntityEmbeddingStateRepository.get_due_for_refresh`` entity_type filter (T-C-4-03)

The tests inspect the generated SQL text rather than running it against a real
Postgres — the live behaviour is exercised separately in the worker integration
suite. Reading the SQL gives us a regression-grade contract test without
needing a TestContainers DB on the unit-test path.
"""

from __future__ import annotations

import inspect

import pytest
from knowledge_graph.infrastructure.intelligence_db.adapters.entity_enrichment_adapter import (
    EntityEnrichmentAdapter,
)
from knowledge_graph.infrastructure.intelligence_db.repositories.entity_embedding_state import (
    EntityEmbeddingStateRepository,
)

pytestmark = pytest.mark.unit


# ── T-C-4-01: atomic claim_for_enrichment ────────────────────────────────────


def test_claim_for_enrichment_method_exists() -> None:
    """PLAN-0093 T-C-4-01: the new atomic claim method is present on the adapter."""
    assert hasattr(EntityEnrichmentAdapter, "claim_for_enrichment")


def test_claim_uses_for_update_skip_locked() -> None:
    """The CTE must lock rows with FOR UPDATE SKIP LOCKED so two workers
    never claim the same entity. Without SKIP LOCKED the second worker would
    block on the first worker's lock instead of moving to the next entity.
    """
    src = inspect.getsource(EntityEnrichmentAdapter.claim_for_enrichment)
    assert "FOR UPDATE SKIP LOCKED" in src


def test_claim_increments_attempts_in_same_statement() -> None:
    """The UPDATE must increment enrichment_attempts in the same SQL — that's
    the whole point of the atomic claim. A separate UPDATE would re-open the
    race condition the plan is trying to close.
    """
    src = inspect.getsource(EntityEnrichmentAdapter.claim_for_enrichment)
    assert "enrichment_attempts = ce.enrichment_attempts + 1" in src


def test_claim_returns_claimed_rows() -> None:
    """The UPDATE must use RETURNING so the worker gets exactly the rows it claimed.

    If RETURNING is missing the worker would need a second SELECT, re-opening
    the race with another concurrent claim.
    """
    src = inspect.getsource(EntityEnrichmentAdapter.claim_for_enrichment)
    assert "RETURNING" in src


def test_claim_respects_3_attempt_cap() -> None:
    """Rows that already hit attempts >= 3 must be excluded (matches the
    partial-index condition on ix_canonical_entities_enrichment_sweep).
    """
    src = inspect.getsource(EntityEnrichmentAdapter.claim_for_enrichment)
    assert "enrichment_attempts < 3" in src


def test_claim_orders_by_index_friendly_columns() -> None:
    """ORDER BY must match the partial-index leading column so Postgres can
    walk the index. F-D04 / F-P2-01 documented this for list_unenriched and
    the same rule applies here.
    """
    src = inspect.getsource(EntityEnrichmentAdapter.claim_for_enrichment)
    assert "ORDER BY enrichment_attempts ASC" in src


def test_decrement_attempts_method_exists() -> None:
    """PLAN-0093 T-C-4-01: the rollback method for retryable errors is present."""
    assert hasattr(EntityEnrichmentAdapter, "decrement_attempts")


def test_decrement_clamps_at_zero() -> None:
    """GREATEST(... - 1, 0) prevents the counter from going negative — defensive
    floor in case a claim path is ever bypassed (e.g. one-off remediation script).
    """
    src = inspect.getsource(EntityEnrichmentAdapter.decrement_attempts)
    assert "GREATEST(enrichment_attempts - 1, 0)" in src


# ── T-C-4-02 + T-C-4-03: refresh-queue ordering + entity_type filter ─────────


def test_get_due_for_refresh_prioritizes_null_embeddings() -> None:
    """PLAN-0093 T-C-4-02 (F-REF-004 / F-REF-005): rows with NULL embedding
    must sort BEFORE rows with a populated embedding so stuck refreshes
    eventually drain. The boolean ``IS NULL`` DESC trick puts TRUE (=1)
    first.
    """
    src = inspect.getsource(EntityEmbeddingStateRepository.get_due_for_refresh)
    assert "(ees.embedding IS NULL) DESC" in src


def test_get_due_for_refresh_still_falls_back_to_next_refresh_at() -> None:
    """Within an embedding-IS-NULL bucket the worker must still drain in
    age-of-schedule order so the oldest stale entities go first.
    """
    src = inspect.getsource(EntityEmbeddingStateRepository.get_due_for_refresh)
    assert "next_refresh_at" in src


def test_get_due_for_refresh_filters_non_equity_for_fundamentals() -> None:
    """PLAN-0093 T-C-4-03 (F-REF-003 / F-DB-005): fundamentals_ohlcv view rows
    for non-equity entity types can never be embedded (no OHLCV data exists).
    The query must skip them via entity_type='financial_instrument' so the
    worker doesn't burn cycles on rows that will permanently stay NULL.
    """
    src = inspect.getsource(EntityEmbeddingStateRepository.get_due_for_refresh)
    # The filter is built conditionally on the view_type — assert both the
    # condition and the SQL fragment are present.
    assert "VIEW_FUNDAMENTALS" in src
    assert "entity_type = 'financial_instrument'" in src


# ── Empty-description backfill (2026-07-15 RC) ────────────────────────────────


def test_get_due_for_refresh_accepts_backfill_flag() -> None:
    """The empty-description backfill is opt-in via a keyword-only flag so the
    narrative/fundamentals callers (which do NOT want to re-claim already
    non-due rows) keep their existing behaviour unchanged.
    """
    sig = inspect.signature(EntityEmbeddingStateRepository.get_due_for_refresh)
    param = sig.parameters.get("backfill_missing_description")
    assert param is not None
    assert param.default is False
    assert param.kind is inspect.Parameter.KEYWORD_ONLY


def test_get_due_for_refresh_backfill_selects_undescribed_rows() -> None:
    """When the flag is set the query must widen the WHERE to also claim rows
    whose canonical_entities.description is NULL/empty — regardless of
    next_refresh_at. This unblocks the ~1500 entities the provisional-enrichment
    path seeds with a bare-name source_text and a +90d next_refresh_at, which
    the plain "due" predicate can never select.
    """
    src = inspect.getsource(EntityEmbeddingStateRepository.get_due_for_refresh)
    assert "backfill_missing_description" in src
    # The description-missing OR branch must reference the joined table column.
    assert "ce.description IS NULL" in src
    assert "btrim(ce.description) = ''" in src


def test_get_due_for_refresh_backfill_is_gated_off_by_default() -> None:
    """The description OR branch must be built conditionally, not baked
    unconditionally into the SQL — otherwise narrative/fundamentals refreshes
    would start re-claiming rows they should leave alone.
    """
    src = inspect.getsource(EntityEmbeddingStateRepository.get_due_for_refresh)
    # The OR branch is appended only inside the `if backfill_missing_description`
    # guard, so the guard keyword must appear before the description predicate.
    assert src.index("if backfill_missing_description") < src.index("ce.description IS NULL")
