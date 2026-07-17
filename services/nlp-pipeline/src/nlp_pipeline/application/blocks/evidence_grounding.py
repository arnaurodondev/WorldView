"""Deterministic evidence-span grounding gate (post-extraction fabrication filter).

Background
----------
The DEEP_EXTRACTION prompt (``libs/prompts/src/prompts/extraction/deep.py``) requires
every claim and relation to carry an ``evidence_text`` that is **copied verbatim** from
the source passage ("FABRICATION IS PROHIBITED. Every value you write must be directly
traceable to a verbatim phrase in the document. … Use evidence_text to quote the exact
sentence."). That instruction is *advisory* — nothing verified it.

The 2026-07-16 extraction model bake-off
(``docs/audits/2026-07-16-extraction-model-bakeoff.md``) measured **fabrication** — a
claim/relation NOT grounded in the source article — as the single largest quality drag:
2.13 fabricated items/article on the live ``Qwen3-235B`` model, 0.83 on the incoming
``DeepSeek-V4-Flash``. The judged fabrications split into two mechanically-distinct kinds:

  1. **Hallucinated / paraphrased evidence** — the model invents an ``evidence_text``
     quote, or rewrites the sentence, so the quote is NOT a substring of the source.
     These are structurally detectable and safe to drop deterministically — a claim whose
     own cited evidence does not appear in the article cannot be grounded, regardless of
     what the article says.
  2. **Mislabelled real evidence** — the quote IS a real sentence but the asserted
     claim_type / predicate is not what the sentence says ("refinancing" → DEBT_CHANGE,
     a résumé enumeration → competes_with). A substring check CANNOT catch these; they
     need semantic entailment (the ``relation_entailment`` gate) or a self-verify LLM pass.

This module enforces class (1): it drops any claim/relation whose ``evidence_text`` is
present but is NOT a normalised substring of the source passage. It is:

  * **deterministic + free** — no LLM call, model-agnostic (helps ANY extractor);
  * **yield-neutral on faithful output** — a verbatim quote (what the prompt demands) is
    always a substring, so a faithfully-extracted item is NEVER dropped. The only items
    it removes are those whose evidence the model could not ground — i.e. fabrications.

It runs AFTER ``validate_relations`` (structural gates) and is complementary: the
relation gate catches structurally-impossible edges (self-loop, OOV predicate, bad type);
this gate catches ungrounded-quote fabrications across BOTH claims and relations. Claims
had no post-extraction guard before this module.

Normalisation
-------------
Verbatim quotes drift from the source in small, mechanical ways that must NOT cause a
false drop:

  * whitespace reflow (newlines/tabs/multiple spaces → single space),
  * unicode punctuation (curly quotes/apostrophes, en/em dashes, non-breaking spaces,
    ellipsis char) normalised to ASCII equivalents,
  * case.

``_normalize`` applies NFKC + those foldings to both sides before an ``in`` test. To
tolerate the model legitimately eliding the middle of a long quote with "…"/"...", an
evidence string containing an ellipsis is split on it and EVERY non-trivial fragment must
be a substring (all fragments present ⇒ grounded). This keeps the gate strict (a
fabricated quote's fragments will not all appear) while not punishing honest elision.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

# Modes -----------------------------------------------------------------------
#: No-op — the gate does nothing (escape hatch / A-B baseline).
MODE_OFF = "off"
#: Drop an item ONLY when it carries a non-empty ``evidence_text`` that is not grounded.
#: Items with a missing/blank quote are KEPT (conservative — relations do not schema-
#: require evidence_text, so a legitimately quote-less relation is not penalised).
MODE_PRESENT_ONLY = "present_only"
#: As ``present_only`` PLUS drop items whose ``evidence_text`` is missing/blank. Use for
#: claims, whose schema REQUIRES evidence_text — a claim with no quote is ungrounded by
#: definition. Stricter; may cost yield on a model that omits quotes.
MODE_REQUIRE = "require"

_VALID_MODES = frozenset({MODE_OFF, MODE_PRESENT_ONLY, MODE_REQUIRE})

#: Fragments shorter than this (after normalisation) are ignored when splitting an
#: elided quote — a stray 1-2 char fragment ("a", "of") carries no grounding signal and
#: would trivially match anything.
_MIN_FRAGMENT_LEN = 4

_ELLIPSIS_SPLIT = re.compile(r"\.\.\.+|…")
_WS = re.compile(r"\s+")
#: Punctuation stripped from the LEADING/TRAILING edge of an evidence fragment before the
#: substring test. Models routinely append a sentence-final "." (or wrap a quote in
#: quotes/parens) that the source does not carry at that exact offset — an edge-only
#: difference that must NOT cause a false drop. Stripping edges cannot make a genuinely
#: fabricated quote match (its interior still has to appear verbatim), so precision holds.
_EDGE_PUNCT = " \t\r\n.,;:!?\"'`()[]{}-\u2013\u2014\u2026"

# Unicode punctuation -> ASCII folding applied before comparison. Keys are written as
# explicit code-point escapes: the module's whole purpose is to fold these ambiguous
# glyphs, so a literal here would trip ruff's ambiguous-character lint (RUF001).
_PUNCT_FOLD = {
    "\u2018": "'",  # left single quote
    "\u2019": "'",  # right single quote / apostrophe
    "\u201a": "'",  # single low-9 quote
    "\u201b": "'",  # single high-reversed-9 quote
    "\u201c": '"',  # left double quote
    "\u201d": '"',  # right double quote
    "\u201e": '"',  # double low-9 quote
    "\u2032": "'",  # prime
    "\u2033": '"',  # double prime
    "\u2013": "-",  # en dash
    "\u2014": "-",  # em dash
    "\u2015": "-",  # horizontal bar
    "\u2212": "-",  # minus sign
    "\u00a0": " ",  # non-breaking space
    "\u200b": "",  # zero-width space
}
_PUNCT_TABLE = {ord(k): v for k, v in _PUNCT_FOLD.items()}


@dataclass(frozen=True)
class EvidenceGroundingConfig:
    """Config for the evidence-span grounding gate.

    Built from ``Settings.evidence_grounding_*``. Separate modes per item kind because
    claims schema-require ``evidence_text`` (so ``require`` is safe) while relations do
    not (so ``present_only`` avoids dropping legitimately quote-less relations).
    """

    #: Mode applied to claims. Claims require evidence_text → ``require`` is defensible,
    #: but ``present_only`` is the safe default to avoid any yield surprise on a model
    #: that emits an empty quote; the operator can tighten to ``require``.
    claims_mode: str = MODE_PRESENT_ONLY
    #: Mode applied to relations. ``present_only`` — never drop a quote-less relation.
    relations_mode: str = MODE_PRESENT_ONLY

    @property
    def enabled(self) -> bool:
        return self.claims_mode != MODE_OFF or self.relations_mode != MODE_OFF


@dataclass
class GroundingReport:
    """Per-run counts of what the gate dropped, for structured logging + metrics."""

    claims_kept: int = 0
    claims_dropped: int = 0
    relations_kept: int = 0
    relations_dropped: int = 0
    #: reason -> count, reasons: ``ungrounded_quote`` | ``missing_evidence``
    drop_reasons: dict[str, int] = field(default_factory=dict)


def _normalize(value: Any) -> str:
    """NFKC + punctuation-fold + lower + whitespace-collapse for substring comparison."""
    if value is None:
        return ""
    text = unicodedata.normalize("NFKC", str(value))
    text = text.translate(_PUNCT_TABLE)
    text = _WS.sub(" ", text)
    return text.strip().lower()


def is_grounded(evidence_text: Any, normalized_source: str) -> bool:
    """Return True when ``evidence_text`` is verbatim-traceable to the source.

    ``normalized_source`` must already be ``_normalize``-d (callers normalise the source
    ONCE per document, not once per item). An empty/blank evidence string returns False
    (the caller decides whether "no evidence" is a drop, per mode). A quote containing an
    ellipsis is grounded iff every non-trivial fragment is a substring.
    """
    ev = _normalize(evidence_text)
    if not ev:
        return False
    fragments = [f.strip(_EDGE_PUNCT) for f in _ELLIPSIS_SPLIT.split(ev)]
    fragments = [f for f in fragments if len(f) >= _MIN_FRAGMENT_LEN]
    if not fragments:
        # Evidence was only punctuation/ellipsis/very short — treat the whole (edge-
        # stripped) string as the single fragment so we still require it to appear.
        return ev.strip(_EDGE_PUNCT) in normalized_source
    return all(f in normalized_source for f in fragments)


def _filter(
    items: list[Any],
    normalized_source: str,
    mode: str,
    report: GroundingReport,
    *,
    is_claim: bool,
) -> list[Any]:
    def _tally_kept() -> None:
        if is_claim:
            report.claims_kept += 1
        else:
            report.relations_kept += 1

    def _tally_dropped() -> None:
        if is_claim:
            report.claims_dropped += 1
        else:
            report.relations_dropped += 1

    if mode == MODE_OFF:
        for _ in items:
            _tally_kept()
        return list(items)

    kept: list[Any] = []
    drops: Counter[str] = Counter()
    for item in items:
        if not isinstance(item, dict):
            # Malformed (non-dict) item — cannot carry a quote; drop as ungrounded.
            drops["malformed_item"] += 1
            _tally_dropped()
            continue
        evidence = item.get("evidence_text")
        norm_ev = _normalize(evidence)
        if not norm_ev:
            # No usable quote. Drop only in REQUIRE mode; else keep (conservative).
            if mode == MODE_REQUIRE:
                drops["missing_evidence"] += 1
                _tally_dropped()
                continue
            kept.append(item)
            _tally_kept()
            continue
        if is_grounded(evidence, normalized_source):
            kept.append(item)
            _tally_kept()
        else:
            drops["ungrounded_quote"] += 1
            _tally_dropped()

    for reason, count in drops.items():
        report.drop_reasons[reason] = report.drop_reasons.get(reason, 0) + count
    return kept


def apply_evidence_grounding(
    claims: list[Any],
    relations: list[Any],
    source_text: str,
    config: EvidenceGroundingConfig,
) -> tuple[list[Any], list[Any], GroundingReport]:
    """Drop claims/relations whose ``evidence_text`` is not grounded in ``source_text``.

    Parameters
    ----------
    claims, relations:
        Extracted item dicts (each may carry an ``evidence_text``).
    source_text:
        The full document passage the items were extracted from (joined chunk text). It
        is normalised ONCE here.
    config:
        Per-kind modes. When ``config.enabled`` is False the inputs pass through unchanged.

    Returns ``(kept_claims, kept_relations, report)``. Input order is preserved.
    """
    report = GroundingReport()
    if not config.enabled:
        report.claims_kept = len(claims)
        report.relations_kept = len(relations)
        return list(claims), list(relations), report

    normalized_source = _normalize(source_text)
    kept_claims = _filter(claims, normalized_source, config.claims_mode, report, is_claim=True)
    kept_relations = _filter(relations, normalized_source, config.relations_mode, report, is_claim=False)
    return kept_claims, kept_relations, report
