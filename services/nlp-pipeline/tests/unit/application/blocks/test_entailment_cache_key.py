"""Unit tests for the entailment verifier cache-key builder.

Invariants under test:
  - Stability: the SAME (kind, model_id, template_id, fields...) always yields
    the SAME key.
  - Uniqueness: changing ANY single field (kind, model_id, template_id, or any
    positional field, including field ORDER/boundary) yields a DIFFERENT key —
    this is what makes the cache "content-addressed" and safe (no false hits
    across distinct verifier inputs).
  - Namespacing: the "claim" and "relation" kinds never collide even when fed
    otherwise-identical field tuples.
  - The key is always prefixed with the documented Valkey namespace.
"""

from __future__ import annotations

import pytest
from nlp_pipeline.application.blocks.entailment_cache_key import build_cache_key

pytestmark = pytest.mark.unit


def test_same_inputs_yield_same_key() -> None:
    a = build_cache_key("claim", "model-x", "claim_entailment_v1", "Acme", "DEBT_CHANGE", "negative", "quote text")
    b = build_cache_key("claim", "model-x", "claim_entailment_v1", "Acme", "DEBT_CHANGE", "negative", "quote text")
    assert a == b


def test_key_has_documented_namespace_and_kind_prefix() -> None:
    key = build_cache_key("claim", "model-x", "v1", "a", "b")
    assert key.startswith("nlp:v1:entailment_cache:claim:")


def test_different_model_id_yields_different_key() -> None:
    a = build_cache_key("claim", "model-x", "v1", "Acme", "DEBT_CHANGE", "", "quote")
    b = build_cache_key("claim", "model-y", "v1", "Acme", "DEBT_CHANGE", "", "quote")
    assert a != b


def test_different_template_version_yields_different_key() -> None:
    # This is the mechanism a prompt-semantics change relies on to auto-evict
    # stale verdicts: bumping template_id must change the key.
    a = build_cache_key("claim", "model-x", "claim_entailment_v1", "Acme", "DEBT_CHANGE", "", "quote")
    b = build_cache_key("claim", "model-x", "claim_entailment_v2", "Acme", "DEBT_CHANGE", "", "quote")
    assert a != b


def test_different_evidence_text_yields_different_key() -> None:
    a = build_cache_key("claim", "model-x", "v1", "Acme", "DEBT_CHANGE", "", "Acme refinanced $2B of debt.")
    b = build_cache_key("claim", "model-x", "v1", "Acme", "DEBT_CHANGE", "", "Acme repaid $2B of debt early.")
    assert a != b


def test_claim_and_relation_kinds_never_collide() -> None:
    # Feed the SAME field tuple under both kinds — the namespace must still
    # disambiguate them.
    a = build_cache_key("claim", "model-x", "v1", "Acme", "Beta", "competes_with", "text")
    b = build_cache_key("relation", "model-x", "v1", "Acme", "Beta", "competes_with", "text")
    assert a != b


def test_field_boundary_shift_does_not_collide() -> None:
    # Without a join separator, ("ab", "c") and ("a", "bc") would hash the same.
    # The unit-separator join must prevent this class of collision.
    a = build_cache_key("claim", "model-x", "v1", "ab", "c")
    b = build_cache_key("claim", "model-x", "v1", "a", "bc")
    assert a != b
