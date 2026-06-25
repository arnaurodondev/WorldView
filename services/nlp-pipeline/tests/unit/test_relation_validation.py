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
    SUPPRESSED_PREDICATES,
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


# ══════════════════════════════════════════════════════════════════════════════
# Enhancement #3 — entity-type guard
# ══════════════════════════════════════════════════════════════════════════════
# A {entity_name: mention_class} map is threaded in. The guard drops relations whose
# KNOWN endpoint class is structurally invalid for the predicate; it NEVER drops when a
# class is unknown (absent from the map). It is a complete no-op when entity_classes=None.


def test_type_guard_noop_without_entity_classes() -> None:
    # Same defect the guard would catch, but no map passed → behaviour unchanged.
    rels = [_rel("American Express", "competes_with", "Dow Jones")]
    kept, drops = validate_relations(rels)
    assert kept == rels
    assert drops == {}


def test_type_guard_drops_index_as_competitor() -> None:
    # "American Express competes_with Dow Jones" — index as a competitor (audited defect).
    rels = [_rel("American Express", "competes_with", "Dow Jones")]
    classes = {"American Express": "financial_institution", "Dow Jones": "index"}
    kept, drops = validate_relations(rels, entity_classes=classes)
    assert kept == []
    assert drops == {"entity_type_mismatch": 1}


@pytest.mark.parametrize(
    "bad_class",
    ["index", "currency", "commodity", "macroeconomic_indicator", "financial_instrument"],
)
def test_type_guard_drops_all_non_company_object_classes(bad_class: str) -> None:
    rels = [_rel("Apple", "partner_of", "BadThing")]
    classes = {"Apple": "organization", "BadThing": bad_class}
    kept, drops = validate_relations(rels, entity_classes=classes)
    assert kept == []
    assert drops == {"entity_type_mismatch": 1}


def test_type_guard_drops_firm_as_analyst_rating_subject() -> None:
    # analyst_rating subject MUST be the issuer (company), object the firm. A PERSON (or a
    # market-object class) as subject is invalid. "Brian Nowak appointed_as ..." class.
    rels = [_rel("Wedbush Person", "analyst_rating", "Amazon")]
    classes = {"Wedbush Person": "person", "Amazon": "organization"}
    kept, drops = validate_relations(rels, entity_classes=classes)
    assert kept == []
    assert drops == {"entity_type_mismatch": 1}


def test_type_guard_drops_listed_on_index_object_by_type() -> None:
    # listed_on object typed as an index is dropped by the type guard. (Note: "S&P 500"
    # would already be caught by the name-based exchange allow-list; this asserts the
    # *type* signal also fires when the name slips through but the class is known.)
    rels = [_rel("UPS", "listed_on", "SomeIndexName")]
    classes = {"UPS": "organization", "SomeIndexName": "index"}
    kept, drops = validate_relations(rels, entity_classes=classes)
    assert kept == []
    # invalid_listed_on (name-based) fires first since the name isn't a known exchange.
    assert drops == {"invalid_listed_on": 1}


def test_type_guard_no_false_drop_when_endpoint_class_unknown() -> None:
    # CRITICAL conservatism property: object class is NOT in the map → unknown → never drop.
    rels = [_rel("American Express", "competes_with", "Mystery Co")]
    classes = {"American Express": "financial_institution"}  # Mystery Co absent
    kept, drops = validate_relations(rels, entity_classes=classes)
    assert kept == rels
    assert drops == {}


def test_type_guard_no_false_drop_when_both_classes_unknown() -> None:
    rels = [_rel("Foo", "competes_with", "Bar")]
    kept, drops = validate_relations(rels, entity_classes={"Unrelated": "index"})
    assert kept == rels
    assert drops == {}


def test_type_guard_keeps_valid_company_to_company() -> None:
    rels = [_rel("Nvidia", "competes_with", "AMD")]
    classes = {"Nvidia": "organization", "AMD": "organization"}
    kept, drops = validate_relations(rels, entity_classes=classes)
    assert kept == rels
    assert drops == {}


def test_type_guard_empty_map_is_noop() -> None:
    # An empty (falsy) map disables the type/direction gates, like None.
    rels = [_rel("American Express", "competes_with", "Dow Jones")]
    kept, drops = validate_relations(rels, entity_classes={})
    assert kept == rels
    assert drops == {}


# ══════════════════════════════════════════════════════════════════════════════
# Enhancement #4 — direction auto-swap
# ══════════════════════════════════════════════════════════════════════════════
# For person-company predicates with a fixed convention, when the endpoints' KNOWN
# classes are unambiguously reversed, swap subject/object (KEEP the relation) and count
# ``direction_swapped``. Never swap when a class is unknown or the predicate is symmetric.


def test_direction_swap_has_executive_person_subject() -> None:
    # "Brian Nowak appointed_as Morgan Stanley" shape: convention is subject=company,
    # object=person. Here they're reversed → swap.
    rels = [_rel("Tim Cook", "has_executive", "Apple")]
    classes = {"Tim Cook": "person", "Apple": "organization"}
    kept, drops = validate_relations(rels, entity_classes=classes)
    assert len(kept) == 1
    # Swapped IN PLACE: company is now subject, person now object.
    assert kept[0]["subject_ref"] == "Apple"
    assert kept[0]["object_ref"] == "Tim Cook"
    assert drops == {"direction_swapped": 1}


def test_direction_swap_appointed_as_reversed() -> None:
    rels = [_rel("Brian Nowak", "appointed_as", "Morgan Stanley")]
    classes = {"Brian Nowak": "person", "Morgan Stanley": "financial_institution"}
    kept, drops = validate_relations(rels, entity_classes=classes)
    assert kept[0]["subject_ref"] == "Morgan Stanley"
    assert kept[0]["object_ref"] == "Brian Nowak"
    assert drops == {"direction_swapped": 1}


def test_direction_swap_board_member_of_reversed() -> None:
    # board_member_of convention is subject=person, object=company. Reversed here → swap.
    rels = [_rel("Apple", "board_member_of", "Jane Doe")]
    classes = {"Apple": "organization", "Jane Doe": "person"}
    kept, drops = validate_relations(rels, entity_classes=classes)
    assert kept[0]["subject_ref"] == "Jane Doe"
    assert kept[0]["object_ref"] == "Apple"
    assert drops == {"direction_swapped": 1}


def test_direction_correct_order_not_swapped() -> None:
    # Already-correct direction is left untouched and produces no swap event.
    rels = [_rel("Apple", "has_executive", "Tim Cook")]
    classes = {"Apple": "organization", "Tim Cook": "person"}
    kept, drops = validate_relations(rels, entity_classes=classes)
    assert kept[0]["subject_ref"] == "Apple"
    assert kept[0]["object_ref"] == "Tim Cook"
    assert drops == {}


def test_direction_swap_not_applied_when_object_class_unknown() -> None:
    # Subject company known + correct, object (person) unknown → no swap needed, and the
    # subject is a valid company so the type guard does not drop. Relation untouched.
    rels = [_rel("Apple", "has_executive", "Mystery Person")]
    classes = {"Apple": "organization"}  # Mystery Person absent
    kept, drops = validate_relations(rels, entity_classes=classes)
    assert kept[0]["subject_ref"] == "Apple"  # untouched
    assert kept[0]["object_ref"] == "Mystery Person"
    assert drops == {}


def test_swap_subject_unknown_no_swap_no_drop() -> None:
    # Subject class unknown, object is a person → cannot prove reversal (subject role
    # unknown), and the subject's class is unknown so the type guard cannot drop it.
    # The relation passes through untouched (full conservatism on unknown subject).
    rels = [_rel("Mystery Co", "has_executive", "Tim Cook")]
    classes = {"Tim Cook": "person"}  # Mystery Co absent
    kept, drops = validate_relations(rels, entity_classes=classes)
    assert kept[0]["subject_ref"] == "Mystery Co"  # untouched
    assert kept[0]["object_ref"] == "Tim Cook"
    assert drops == {}


def test_person_subject_dropped_when_object_unknown() -> None:
    # Subtle but correct: a PERSON as has_executive subject is an independent type
    # violation; even though the object is unknown (so no swap is possible), the known
    # person-subject is dropped by the type guard. This is desirable — the edge is wrong.
    rels = [_rel("Tim Cook", "has_executive", "Apple")]
    classes = {"Tim Cook": "person"}  # Apple absent → cannot swap
    kept, drops = validate_relations(rels, entity_classes=classes)
    assert kept == []
    assert drops == {"entity_type_mismatch": 1}


def test_direction_swap_then_type_guard_sees_corrected_endpoints() -> None:
    # After swapping a reversed has_executive, the corrected subject (company) is valid,
    # so the type guard does NOT additionally drop it.
    rels = [_rel("Tim Cook", "has_executive", "Apple")]
    classes = {"Tim Cook": "person", "Apple": "organization"}
    kept, drops = validate_relations(rels, entity_classes=classes)
    assert len(kept) == 1
    assert drops == {"direction_swapped": 1}
    assert "entity_type_mismatch" not in drops


def test_symmetric_predicate_never_swapped() -> None:
    # competes_with has no fixed convention → even with two distinct classes, no swap.
    rels = [_rel("AMD", "competes_with", "Nvidia")]
    classes = {"AMD": "organization", "Nvidia": "organization"}
    kept, drops = validate_relations(rels, entity_classes=classes)
    assert kept == rels
    assert "direction_swapped" not in drops


# ══════════════════════════════════════════════════════════════════════════════
# Enhancement #5 — predicate suppression
# ══════════════════════════════════════════════════════════════════════════════


def test_suppressed_predicates_default_set() -> None:
    # The audited near-zero-support predicates are suppressed by default.
    assert "credit_rating" in SUPPRESSED_PREDICATES
    assert "earnings_released" in SUPPRESSED_PREDICATES
    assert "corporate_action" in SUPPRESSED_PREDICATES
    # Conservatism: low-but-recoverable predicates are NOT suppressed.
    assert "price_target" not in SUPPRESSED_PREDICATES
    assert "downgraded_by" not in SUPPRESSED_PREDICATES


@pytest.mark.parametrize("pred", ["credit_rating", "earnings_released", "corporate_action"])
def test_suppressed_predicate_dropped(pred: str) -> None:
    rels = [_rel("Salesforce", pred, "Simply Wall St.")]
    kept, drops = validate_relations(rels)
    assert kept == []
    assert drops == {"suppressed_predicate": 1}


def test_suppression_fires_even_without_entity_classes() -> None:
    # #5 is independent of the NER map (unlike #3/#4).
    rels = [_rel("Apple", "credit_rating", "Moody's")]
    kept, drops = validate_relations(rels)
    assert kept == []
    assert drops == {"suppressed_predicate": 1}


def test_non_suppressed_predicate_survives() -> None:
    rels = [_rel("Apple", "supplier_of", "Foxconn")]
    kept, drops = validate_relations(rels)
    assert kept == rels
    assert drops == {}


# ══════════════════════════════════════════════════════════════════════════════
# Combined: a realistic mixed batch exercising #3/#4/#5 together
# ══════════════════════════════════════════════════════════════════════════════


def test_combined_batch_with_entity_classes() -> None:
    rels = [
        _rel("Apple", "supplier_of", "Foxconn"),  # keep
        _rel("Tim Cook", "has_executive", "Apple"),  # #4 swap → keep
        _rel("American Express", "competes_with", "Dow Jones"),  # #3 drop
        _rel("Salesforce", "credit_rating", "Moody's"),  # #5 drop
        _rel("Nvidia", "competes_with", "Mystery Co"),  # unknown obj → keep (no false drop)
    ]
    classes = {
        "Apple": "organization",
        "Foxconn": "organization",
        "Tim Cook": "person",
        "American Express": "financial_institution",
        "Dow Jones": "index",
        "Salesforce": "organization",
        "Moody's": "financial_institution",
        "Nvidia": "organization",
        # "Mystery Co" deliberately absent → unknown class
    }
    kept, drops = validate_relations(rels, entity_classes=classes)
    kept_subjects = {r["subject_ref"] for r in kept}
    assert kept_subjects == {"Apple", "Nvidia"}
    assert any(r["object_ref"] == "Tim Cook" and r["subject_ref"] == "Apple" for r in kept)
    assert drops == {
        "direction_swapped": 1,
        "entity_type_mismatch": 1,
        "suppressed_predicate": 1,
    }
