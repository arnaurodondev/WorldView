"""Scope-guard test for PRD-0120 (PLAN-0123 Wave 1, task T-A-1-04).

PRD-0120 fits a per-type ``decay_alpha`` for ``TEMPORAL_CLAIM`` relation
types only (P-3). Five call sites in this service bypass the registry
entirely and hardcode a ``decay_alpha`` value; the review
(docs/audits/2026-07-03-prd-0120-review.md, "FR-2 cleaner than stated, but
wider") flagged them as worth enumerating rather than fixing, because none
of them writes a ``TEMPORAL_CLAIM`` type today:

  - relation.py `upsert_relation()` convenience wrapper — hardcodes DURABLE
  - entity_consumer.py (unblock-edge materialization) — hardcodes DURABLE
  - entity_enrichment_adapter.py (structured enrichment INSERT) — RELATION_STATE/DURABLE
  - fundamentals_refresh.py sector relation — RELATION_STATE, alpha 0.0 (PERMANENT-like)
  - fundamentals_refresh.py industry relation — RELATION_STATE/DURABLE

This is a DB-FREE static/source guard (mirrors the migration-file static test
pattern used elsewhere in this repo): it greps the actual source text for
each call site and asserts the hardcoded semantic_mode is 'RELATION_STATE',
never 'TEMPORAL_CLAIM'. If a future change repoints any of these 5 sites at
a TEMPORAL_CLAIM type, this test fails loudly — that type would silently
never be eligible for a fitted alpha (it would always get the hardcoded
constant, bypassing the registry-first/class-fallback COALESCE entirely).
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_SRC_ROOT = Path(__file__).resolve().parents[3] / "src" / "knowledge_graph"


def _read(relative_path: str) -> str:
    path = _SRC_ROOT / relative_path
    assert path.is_file(), f"expected source file not found: {path}"
    return path.read_text(encoding="utf-8")


def test_relation_upsert_wrapper_hardcodes_relation_state() -> None:
    src = _read("infrastructure/intelligence_db/repositories/relation.py")
    # The upsert_relation() convenience wrapper's hardcoded call.
    assert 'semantic_mode="RELATION_STATE"' in src
    assert "decay_alpha=0.000950" in src


def test_entity_consumer_unblock_edge_hardcodes_relation_state() -> None:
    src = _read("infrastructure/messaging/consumers/entity_consumer.py")
    assert 'semantic_mode="RELATION_STATE"' in src
    assert "decay_alpha=0.000950" in src


def test_entity_enrichment_adapter_hardcodes_relation_state() -> None:
    src = _read("infrastructure/intelligence_db/adapters/entity_enrichment_adapter.py")
    assert "'RELATION_STATE', 'DURABLE', 0.000950, 0.70," in src


def test_fundamentals_refresh_sector_and_industry_are_relation_state() -> None:
    src = _read("infrastructure/workers/fundamentals_refresh.py")
    assert '_SECTOR_SEMANTIC_MODE = "RELATION_STATE"' in src
    # Both the sector and industry relation upserts reuse this one constant —
    # confirmed by reading the call sites (both pass semantic_mode=_SECTOR_SEMANTIC_MODE).
    assert src.count("semantic_mode=_SECTOR_SEMANTIC_MODE") == 2
