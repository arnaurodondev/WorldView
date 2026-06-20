"""Unit tests for the deterministic post-extraction relation precision gates.

Covers the four structural gates in
``nlp_pipeline.application.blocks.relation_validation.validate_relations`` plus a
drift-guard that keeps ``VALID_PREDICATES`` in sync with the DEEP_EXTRACTION prompt's
closed vocabulary (so the code gate never falls out of step with what the model is told
to emit).
"""

from __future__ import annotations

import re

import pytest
from nlp_pipeline.application.blocks.relation_validation import (
    VALID_PREDICATES,
    validate_relations,
)

pytestmark = pytest.mark.unit


def _rel(subject: str, predicate: str, obj: str, **extra: object) -> dict[str, object]:
    """Minimal valid-shaped relation dict."""
    return {
        "subject_ref": subject,
        "predicate": predicate,
        "object_ref": obj,
        "confidence": 0.9,
        "evidence_text": "evidence",
        **extra,
    }


# ── happy path ────────────────────────────────────────────────────────────────


def test_valid_relations_pass_through_unchanged() -> None:
    rels = [
        _rel("Apple", "employs", "Tim Cook"),
        _rel("ARM Holdings", "subsidiary_of", "SoftBank"),
        _rel("Boston Scientific", "listed_on", "NYSE"),
        _rel("Nvidia", "competes_with", "AMD"),
    ]
    kept, drops = validate_relations(rels)
    assert kept == rels
    assert drops == {}


def test_input_order_preserved() -> None:
    rels = [
        _rel("A Corp", "supplier_of", "B Corp"),
        _rel("X", "X", "X"),  # dropped (self-loop + empty handled)
        _rel("C Corp", "partner_of", "D Corp"),
    ]
    kept, _ = validate_relations(rels)
    assert [r["subject_ref"] for r in kept] == ["A Corp", "C Corp"]


# ── Gate #1: self-loops ───────────────────────────────────────────────────────


def test_self_loop_exact_dropped() -> None:
    kept, drops = validate_relations([_rel("Tesla", "earnings_released", "Tesla")])
    assert kept == []
    assert drops == {"self_loop": 1}


def test_self_loop_case_and_punctuation_insensitive() -> None:
    # "Oil produces oil" — the classic common-noun self-loop from the v1.6 audit.
    kept, drops = validate_relations([_rel("Oil", "produces", "oil.")])
    assert kept == []
    # self_loop is checked before the common-noun gate, so it wins here.
    assert drops == {"self_loop": 1}


# ── Gate #2: closed predicate vocabulary ──────────────────────────────────────


@pytest.mark.parametrize("bad_predicate", ["advertises_on", "consulted", "capital_raise", "partnership", ""])
def test_oov_predicate_dropped(bad_predicate: str) -> None:
    kept, drops = validate_relations([_rel("Meta", bad_predicate, "Google")])
    assert kept == []
    # empty predicate is caught earlier as empty_field, not oov_predicate.
    expected = "empty_field" if bad_predicate == "" else "oov_predicate"
    assert drops == {expected: 1}


# ── Gate #3: listed_on exchange validation ────────────────────────────────────


@pytest.mark.parametrize("good_exchange", ["NYSE", "nasdaq", "London Stock Exchange", "TSX", "(NASDAQ)"])
def test_listed_on_valid_exchange_kept(good_exchange: str) -> None:
    kept, drops = validate_relations([_rel("SomeCo", "listed_on", good_exchange)])
    assert len(kept) == 1
    assert drops == {}


@pytest.mark.parametrize(
    "variant_exchange",
    # Real exchanges written with the spelling/punctuation variants that the bare
    # allow-list mis-flagged on the live corpus (2026-06-18) — must be KEPT after
    # alphanumeric normalisation. See _normalize_exchange.
    ["NasdaqGS", "NASDAQ GS", "Nasdaq-GS", "NYSE MKT", "NYSEMKT", "FSE", "CSE", "TSX Venture", "OTC Markets Group"],
)
def test_listed_on_spelling_variants_kept(variant_exchange: str) -> None:
    kept, drops = validate_relations([_rel("SomeCo", "listed_on", variant_exchange)])
    assert len(kept) == 1, f"{variant_exchange!r} is a real exchange and must not be dropped"
    assert drops == {}


@pytest.mark.parametrize("bad_object", ["S&P 500", "Dow", "Nasdaq Composite", "COST", "Russell 2000", "FTSE 100"])
def test_listed_on_index_or_ticker_dropped(bad_object: str) -> None:
    kept, drops = validate_relations([_rel("UPS", "listed_on", bad_object)])
    assert kept == []
    assert drops == {"invalid_listed_on": 1}


# ── Gate #4: common-noun endpoints ────────────────────────────────────────────


@pytest.mark.parametrize("noun", ["stock", "shares", "the company", "oil", "e-commerce", "market"])
def test_common_noun_endpoint_dropped(noun: str) -> None:
    # as object
    kept_obj, drops_obj = validate_relations([_rel("Exxon", "produces", noun)])
    assert kept_obj == []
    assert drops_obj == {"common_noun_endpoint": 1}
    # as subject
    kept_subj, drops_subj = validate_relations([_rel(noun, "competes_with", "Exxon")])
    assert kept_subj == []
    assert drops_subj == {"common_noun_endpoint": 1}


def test_country_endpoints_not_treated_as_common_nouns() -> None:
    # Countries/regions are valid place entities, must NOT be filtered.
    rels = [
        _rel("Apple", "operates_in_country", "China"),
        _rel("Apple", "revenue_from_country", "United States"),
        _rel("TSMC", "headquartered_in", "Taiwan"),
    ]
    kept, drops = validate_relations(rels)
    assert kept == rels
    assert drops == {}


# ── hygiene / robustness ──────────────────────────────────────────────────────


def test_missing_and_blank_fields_dropped_as_empty() -> None:
    rels = [
        {"subject_ref": "", "predicate": "employs", "object_ref": "X", "confidence": 0.9},
        {"subject_ref": "A", "predicate": "employs", "object_ref": None, "confidence": 0.9},
        {"predicate": "employs", "object_ref": "X", "confidence": 0.9},  # no subject_ref
        "not-a-dict",  # type: ignore[list-item]
    ]
    kept, drops = validate_relations(rels)
    assert kept == []
    assert drops == {"empty_field": 4}


def test_mixed_batch_counts_each_reason_once() -> None:
    rels = [
        _rel("Apple", "employs", "Tim Cook"),  # keep
        _rel("Tesla", "earnings_released", "Tesla"),  # self_loop
        _rel("Meta", "advertises_on", "Google"),  # oov
        _rel("UPS", "listed_on", "S&P 500"),  # invalid_listed_on
        _rel("Exxon", "produces", "oil"),  # common_noun
        _rel("Nvidia", "supplier_of", "Dell"),  # keep
    ]
    kept, drops = validate_relations(rels)
    assert len(kept) == 2
    assert drops == {
        "self_loop": 1,
        "oov_predicate": 1,
        "invalid_listed_on": 1,
        "common_noun_endpoint": 1,
    }


def test_empty_input_returns_empty() -> None:
    kept, drops = validate_relations([])
    assert kept == []
    assert drops == {}


# ── drift-guard: code vocabulary must match the prompt vocabulary ─────────────


def test_valid_predicates_match_deep_extraction_prompt() -> None:
    """VALID_PREDICATES must equal the predicate set declared in the v1.6 prompt.

    The prompt lists each predicate as ``    <name>  — <description>``. We parse those
    names back out and assert exact set-equality, so adding/removing a predicate in the
    prompt without updating this gate (or vice-versa) fails loudly here.
    """
    from prompts.extraction.deep import DEEP_EXTRACTION  # type: ignore[import-not-found]

    prompt_text = DEEP_EXTRACTION.template if hasattr(DEEP_EXTRACTION, "template") else str(DEEP_EXTRACTION)

    # The vocabulary lives between the "predicate (relation type" header and the
    # "RELATION ASSERTION TEST" section. Restrict parsing to that slice so unrelated
    # snake_case tokens elsewhere in the prompt don't leak in.
    start = prompt_text.index("predicate (relation type")
    end = prompt_text.index("RELATION ASSERTION TEST")
    vocab_slice = prompt_text[start:end]

    # Each declared predicate is a snake_case token immediately followed by an em-dash
    # description: e.g. "    acquired_by      — A was acquired by B".
    declared = set(re.findall(r"\n\s*([a-z][a-z_]+[a-z])\s+—", vocab_slice))

    assert declared == set(VALID_PREDICATES), (
        f"Prompt/code predicate drift.\n"
        f"  in prompt but not code: {sorted(declared - set(VALID_PREDICATES))}\n"
        f"  in code but not prompt: {sorted(set(VALID_PREDICATES) - declared)}"
    )
