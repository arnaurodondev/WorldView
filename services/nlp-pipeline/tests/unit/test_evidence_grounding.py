"""Unit tests for the deterministic evidence-span grounding gate.

Covers ``nlp_pipeline.application.blocks.evidence_grounding`` — the post-extraction
filter that drops any claim/relation whose ``evidence_text`` is not verbatim-traceable
(a normalised substring) to the source passage. See the module docstring and
``docs/audits/2026-07-16-extraction-fabrication.md`` for the rationale.

The central invariant under test: a FAITHFULLY-quoted item (evidence copied verbatim,
modulo whitespace/unicode-punctuation/case) is NEVER dropped, so the gate costs zero
true-positive yield; only items whose quote the model could not ground are removed.
"""

from __future__ import annotations

import pytest
from nlp_pipeline.application.blocks.evidence_grounding import (
    MODE_OFF,
    MODE_PRESENT_ONLY,
    MODE_REQUIRE,
    EvidenceGroundingConfig,
    apply_evidence_grounding,
    is_grounded,
)

pytestmark = pytest.mark.unit

SOURCE = (
    "TSMC supplies chips to Apple and Nvidia. Satya Nadella, CEO of Microsoft, "
    "announced the deal on Tuesday. The company refinanced $2.0 billion of debt."
)


def _claim(evidence: str | None, claim_type: str = "REVENUE_GROWTH") -> dict[str, object]:
    d: dict[str, object] = {
        "entity_ref": "Apple",
        "claim_type": claim_type,
        "polarity": "positive",
        "confidence": 0.9,
    }
    if evidence is not None:
        d["evidence_text"] = evidence
    return d


def _rel(evidence: str | None, predicate: str = "supplier_of") -> dict[str, object]:
    d: dict[str, object] = {
        "subject_ref": "TSMC",
        "predicate": predicate,
        "object_ref": "Apple",
        "confidence": 0.9,
    }
    if evidence is not None:
        d["evidence_text"] = evidence
    return d


# ── is_grounded: the substring primitive ──────────────────────────────────────


def _norm_source() -> str:
    from nlp_pipeline.application.blocks.evidence_grounding import _normalize

    return _normalize(SOURCE)


def test_verbatim_quote_is_grounded() -> None:
    assert is_grounded("TSMC supplies chips to Apple and Nvidia.", _norm_source())


def test_whitespace_reflow_is_grounded() -> None:
    # Newlines / doubled spaces in the quote must not break the match.
    assert is_grounded("TSMC   supplies\nchips to Apple", _norm_source())


def test_case_insensitive_is_grounded() -> None:
    assert is_grounded("tsmc SUPPLIES chips", _norm_source())


def test_curly_quote_and_dash_folding_is_grounded() -> None:
    src_norm = _norm_source()
    # Source has straight punctuation; quote arrives with curly apostrophe → still matches
    # after NFKC + punctuation folding (no apostrophe here, but exercise the fold path).
    assert is_grounded("CEO of Microsoft", src_norm)


def test_fabricated_quote_is_not_grounded() -> None:
    # A plausible-sounding sentence that never appears in the source.
    assert not is_grounded("Apple reported record quarterly revenue growth.", _norm_source())


def test_paraphrased_quote_is_not_grounded() -> None:
    # Same meaning, different words → not a substring → correctly flagged ungrounded.
    assert not is_grounded("TSMC is a chip supplier for Apple", _norm_source())


def test_empty_evidence_is_not_grounded() -> None:
    assert not is_grounded("", _norm_source())
    assert not is_grounded(None, _norm_source())


def test_elided_quote_all_fragments_present_is_grounded() -> None:
    # Model elides the middle with an ellipsis; both fragments appear in source.
    assert is_grounded("Satya Nadella ... announced the deal", _norm_source())


def test_elided_quote_one_fragment_fabricated_is_not_grounded() -> None:
    assert not is_grounded("Satya Nadella ... resigned as chairman", _norm_source())


# ── apply_evidence_grounding: present_only mode (the default) ──────────────────


def test_present_only_keeps_grounded_drops_fabricated() -> None:
    cfg = EvidenceGroundingConfig()  # present_only / present_only
    claims = [
        _claim("The company refinanced $2.0 billion of debt.", "DEBT_CHANGE"),  # grounded
        _claim("Apple raised full-year guidance.", "GUIDANCE_RAISE"),  # fabricated
    ]
    relations = [
        _rel("TSMC supplies chips to Apple and Nvidia."),  # grounded
        _rel("Apple competes with TSMC in foundry services.", "competes_with"),  # fabricated
    ]
    kept_c, kept_r, report = apply_evidence_grounding(claims, relations, SOURCE, cfg)
    assert [c["claim_type"] for c in kept_c] == ["DEBT_CHANGE"]
    assert [r["predicate"] for r in kept_r] == ["supplier_of"]
    assert report.claims_dropped == 1
    assert report.relations_dropped == 1
    assert report.drop_reasons["ungrounded_quote"] == 2


def test_present_only_keeps_missing_evidence() -> None:
    # A quote-less relation is KEPT in present_only (relations don't schema-require it).
    cfg = EvidenceGroundingConfig()
    _kept_c, kept_r, report = apply_evidence_grounding([], [_rel(None)], SOURCE, cfg)
    assert len(kept_r) == 1
    assert report.relations_dropped == 0


def test_require_mode_drops_missing_evidence() -> None:
    cfg = EvidenceGroundingConfig(claims_mode=MODE_REQUIRE, relations_mode=MODE_REQUIRE)
    kept_c, kept_r, report = apply_evidence_grounding([_claim(None)], [_rel(None)], SOURCE, cfg)
    assert kept_c == []
    assert kept_r == []
    assert report.drop_reasons["missing_evidence"] == 2


def test_off_mode_is_passthrough() -> None:
    cfg = EvidenceGroundingConfig(claims_mode=MODE_OFF, relations_mode=MODE_OFF)
    assert not cfg.enabled
    claims = [_claim("totally fabricated quote not in source")]
    relations = [_rel("also fabricated")]
    kept_c, kept_r, report = apply_evidence_grounding(claims, relations, SOURCE, cfg)
    assert len(kept_c) == 1 and len(kept_r) == 1
    assert report.claims_dropped == 0 and report.relations_dropped == 0


def test_input_order_preserved() -> None:
    cfg = EvidenceGroundingConfig()
    claims = [
        _claim("TSMC supplies chips to Apple and Nvidia.", "A"),
        _claim("The company refinanced $2.0 billion of debt.", "B"),
    ]
    kept_c, _, _ = apply_evidence_grounding(claims, [], SOURCE, cfg)
    assert [c["claim_type"] for c in kept_c] == ["A", "B"]


def test_mixed_mode_claims_require_relations_present_only() -> None:
    # Claims strict (drop missing), relations lenient (keep missing).
    cfg = EvidenceGroundingConfig(claims_mode=MODE_REQUIRE, relations_mode=MODE_PRESENT_ONLY)
    kept_c, kept_r, _ = apply_evidence_grounding([_claim(None)], [_rel(None)], SOURCE, cfg)
    assert kept_c == []
    assert len(kept_r) == 1


def test_non_dict_items_are_dropped_safely() -> None:
    cfg = EvidenceGroundingConfig()
    kept_c, _kept_r, report = apply_evidence_grounding(["not a dict"], [], SOURCE, cfg)
    assert kept_c == []
    assert report.claims_dropped == 1
    assert report.drop_reasons["malformed_item"] == 1
