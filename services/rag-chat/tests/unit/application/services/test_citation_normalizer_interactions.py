"""Citation-normalizer INTERACTION regression suite (2026-07-23 bottleneck audit).

See ``docs/audits/2026-07-23-bottleneck-rag-chat-grounding.md`` §1 Recurrence A.

Five separate PRs (``af69dbbaa``, ``fe1d32ad2``, ``3934d26eb``, ``45b658695``,
``36a9df0e0``) each added ONE narrowly-scoped citation-tag normalizer to
``numeric_grounding.py`` — a namespace-prefix strip, a verb-prefix-insensitive
match, a difflib typo tolerance, a fundamentals-family alias, a benign-prose
allowlist. Each fix's own test file (``test_phantom_citation_partition.py``,
``test_numeric_grounding.py``) pins that ONE normalizer against the SPECIFIC
case that motivated it. None of them tests what happens when TWO of these
normalizers are exercised on the SAME tag, or when the resolution helper used
by one call site (:func:`resolve_tool_name`) interacts with the value-gated
check used by another (:func:`partition_phantom_tool_citations`'s
fundamentals-family alias).

This file has two jobs:

1. **Order-independence property tests** — for tag shapes where the CURRENT
   normalizer stack agrees on the classification, assert that classifying the
   raw tag directly (:func:`partition_phantom_tool_citations`) and classifying
   it AFTER :func:`normalize_tool_row_citations` has already rewritten
   resolvable tags to ``[pos]`` markers produce the SAME final decision
   (real / strip / refuse). This is the literal "regardless of which
   normalizer function is invoked first" property the audit asks for, since
   :func:`resolve_tool_name` is invoked from BOTH call sites independently.

2. **Two concrete, EMPIRICALLY VERIFIED interaction gaps** (not hypothetical —
   each was executed against the real functions in this module before being
   encoded below; see the module-level comment on each test). These are
   pinned as CURRENT, documented behavior — not asserted as "correct" — so a
   future session that consolidates the normalizers (HR-065's proposed
   ``CitationResolver``, explicitly OUT OF SCOPE for this test-only pass) has
   a regression harness confirming whether the consolidation fixes them.
   Recorded as BP-741 in ``docs/BUG_PATTERNS.md``.

Scope note: this file only exercises the CITATION-TAG classification layer
(:func:`resolve_tool_name`, :func:`partition_phantom_tool_citations`,
:func:`normalize_tool_row_citations`, and (via ``chat_orchestrator``)
``_strip_non_registered_citation_tags``). It does NOT assert anything about
the broader numeric-VALUE grounding pipeline (``NumericGroundingValidator``,
``material_unsupported_numbers``), which independently cross-checks extracted
numbers against every called tool's value pool and may or may not still catch
a citation-tag misclassification recorded here — that pipeline has its own
dedicated test file (``test_numeric_grounding.py``) and is out of scope here.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable

import pytest
from rag_chat.application.services.numeric_grounding import (
    normalize_tool_row_citations,
    partition_phantom_tool_citations,
    resolve_tool_name,
)
from rag_chat.application.use_cases.chat_orchestrator import (
    _strip_non_registered_citation_tags,
)

pytestmark = pytest.mark.unit

# ── Shared fixtures for the harness ────────────────────────────────────────
#
# TARGET is a real fundamentals-family tool. SIBLING is a DIFFERENT
# fundamentals-family tool (interchangeable rows per the family-alias design).
# OTHER is a non-fundamentals tool used as call-set noise so "called" is never
# accidentally empty.
_TARGET = "get_fundamentals_history_batch"
_SIBLING = "get_fundamentals_history"
_OTHER = "get_entity_news"

# The five name-variant classes named in the audit, all referencing _TARGET.
_NAME_VARIANTS: dict[str, str] = {
    "exact": "get_fundamentals_history_batch",
    "dropped_prefix": "fundamentals_history_batch",  # verb prefix stripped
    "namespaced": "functions.get_fundamentals_history_batch",  # OpenAI ns prefix
    "difflib_typo": "get_fundamentals_histroy_batch",  # transposed "or"->"ro"
}


def _make_resolvers(
    called: list[str],
    row_positions: dict[tuple[str, int], int],
    row_counts: dict[str, int],
) -> tuple[
    Callable[[str, int], int | None],
    Callable[[str], int | None],
    Callable[[str], str | None],
]:
    """Build the three resolver callbacks :func:`normalize_tool_row_citations`
    expects, wired the same way ``chat_orchestrator`` wires them in production
    (``_resolve_row_position`` / ``_resolve_row_count`` / ``_resolve_tool_name``
    around line 5477-5502)."""

    def position_resolver(tool: str, row: int) -> int | None:
        return row_positions.get((tool, row))

    def row_count_resolver(tool: str) -> int | None:
        return row_counts.get(tool)

    def name_resolver(tool: str) -> str | None:
        result: str | None = resolve_tool_name(tool, called)
        return result

    return position_resolver, row_count_resolver, name_resolver


def _classify(
    response: str,
    called: Iterable[str],
    *,
    fundamentals_value_pool: set[float] | None = None,
) -> str:
    """Collapse a :func:`partition_phantom_tool_citations` result to one label."""
    material, benign = partition_phantom_tool_citations(
        response, called, fundamentals_value_pool=fundamentals_value_pool
    )
    if material:
        return "refuse"
    if benign:
        return "strip"
    return "real"


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 1 — Order-independence: resolve_tool_name -> normalize_tool_row_
# citations -> partition_phantom_tool_citations vs. partition run directly.
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize("variant_name", sorted(_NAME_VARIANTS))
@pytest.mark.parametrize("row_class", ["in_range", "out_of_range"])
@pytest.mark.parametrize("adjacency", ["material", "benign"])
def test_order_independence_when_target_tool_ran(variant_name: str, row_class: str, adjacency: str) -> None:
    """When the cited tool actually ran, ALL 4 name variants x both row
    classes x both adjacency classes must classify identically whether
    ``partition_phantom_tool_citations`` runs on the raw text or on the text
    AFTER ``normalize_tool_row_citations`` has already promoted the tag to a
    ``[pos]`` marker.

    Verified empirically (2026-07-23): for every one of these 16 cells, both
    orderings currently agree the tag is a REAL citation (never phantom) —
    ``resolve_tool_name`` conservatively maps all four variants back to
    ``_TARGET`` when ``_TARGET`` is the only called tool in the picture, and
    an out-of-range row clamps to the tool's last real row rather than being
    treated as a citation-shape ambiguity.
    """
    called = [_TARGET, _OTHER]
    row_index = 0 if row_class == "in_range" else 7  # 7 is past the 1-row result
    row_positions = {(_TARGET, 0): 1}
    row_counts = {_TARGET: 1}
    tag = f"[{_NAME_VARIANTS[variant_name]} row {row_index}]"
    adjacent_text = "Revenue was $500B" if adjacency == "material" else "The outlook remains constructive"
    response = f"{adjacent_text} {tag}."

    pos_resolver, count_resolver, name_resolver = _make_resolvers(called, row_positions, row_counts)

    direct = _classify(response, called)
    normalized = normalize_tool_row_citations(response, pos_resolver, count_resolver, name_resolver)
    post_norm = _classify(normalized, called)

    assert (
        direct == "real"
    ), f"a citation to a tool that actually ran must never be phantom ({variant_name}/{row_class}/{adjacency})"
    assert post_norm == direct, (
        f"order-independence violated for {variant_name}/{row_class}/{adjacency}: "
        f"direct={direct!r} vs post-normalize={post_norm!r}"
    )
    # The normalizer must have actually promoted the tag to a numbered marker —
    # otherwise "post_norm == direct == real" would be a vacuous pass because
    # the raw (unresolved) tag text happened to also classify as real. Both
    # in-range and out-of-range rows resolve here: out-of-range clamps to the
    # tool's last real row (count=1 -> clamps row 7 down to row 0) instead of
    # being left as an unresolved `row N` tag.
    assert (
        "row" not in normalized.lower()
    ), f"expected the tag to be rewritten to a [pos] marker for {variant_name}/{row_class}"
    assert "[1]" in normalized


@pytest.mark.parametrize("variant_name", sorted(_NAME_VARIANTS))
@pytest.mark.parametrize("adjacency", ["material", "benign"])
def test_order_independence_when_nothing_family_related_ran(variant_name: str, adjacency: str) -> None:
    """ "never-called tool" row-class: when NEITHER ``_TARGET`` nor ``_SIBLING``
    ran, every name variant converges to the SAME genuinely-phantom outcome
    regardless of ordering — material iff a material number sits adjacent,
    otherwise benign/strip. No normalizer can invent a resolution when
    nothing tool-related to the citation actually executed.
    """
    called = [_OTHER]  # no fundamentals-family tool ran at all
    tag = f"[{_NAME_VARIANTS[variant_name]} row 0]"
    adjacent_text = "Revenue was $500B (unverifiable)" if adjacency == "material" else "Sentiment is broadly positive"
    response = f"{adjacent_text} {tag}."

    pos_resolver, count_resolver, name_resolver = _make_resolvers(called, {}, {})

    direct = _classify(response, called)
    normalized = normalize_tool_row_citations(response, pos_resolver, count_resolver, name_resolver)
    post_norm = _classify(normalized, called)

    expected = "refuse" if adjacency == "material" else "strip"
    assert direct == expected, f"phantom tag adjacency classification wrong for {variant_name}/{adjacency}"
    assert post_norm == direct, (
        f"order-independence violated when nothing ran ({variant_name}/{adjacency}): "
        f"direct={direct!r} vs post-normalize={post_norm!r}"
    )
    # normalize_tool_row_citations cannot resolve anything here (name_resolver
    # returns None for every variant), so the tag must survive UNTOUCHED into
    # the final hard-veto stage, which strips it as a `row N` payload shape
    # regardless of the (never-registered) tool name inside it.
    valid_refs: set[int] = set()
    final_text, stripped_count = _strip_non_registered_citation_tags(normalized, valid_refs)
    assert stripped_count == 1, "the untouched phantom row-tag must be caught by the final hard veto"
    assert tag not in final_text


def test_fundamentals_family_alias_grounded_value_is_real_both_orderings() -> None:
    """Family-alias path (SIBLING ran, tag cites _TARGET's family sibling
    ``query_fundamentals``, cited value IS in the sibling's returned pool):
    classified real regardless of whether normalize or partition runs first.
    """
    called = [_SIBLING, _OTHER]
    pool = {839.25e9}
    response = "Revenue was $839.25B [query_fundamentals row 0]."
    row_positions = {(_SIBLING, 0): 1}
    row_counts = {_SIBLING: 1}
    pos_resolver, count_resolver, name_resolver = _make_resolvers(called, row_positions, row_counts)

    direct = _classify(response, called, fundamentals_value_pool=pool)
    assert direct == "real", "a family-alias citation whose value the sibling actually returned must ground"

    # normalize_tool_row_citations does NOT know about the family-alias pool
    # (it only has resolve_tool_name, which does not bridge distinct family
    # members) — the tag survives normalize untouched. The overall pipeline
    # still calls partition_phantom_tool_citations SEPARATELY on the pre-
    # normalize draft to make the refuse/accept decision (see
    # chat_orchestrator.py lines ~5903-5930), so real-world behavior matches
    # `direct`, not a post-normalize reclassification. We assert that
    # explicitly here so this asymmetry is documented, not silently assumed.
    normalized = normalize_tool_row_citations(response, pos_resolver, count_resolver, name_resolver)
    assert normalized == response, (
        "normalize_tool_row_citations has no family-alias awareness — the tag "
        "is left verbatim for partition_phantom_tool_citations to classify"
    )


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 2 — The audit's named regression case + its mirror-image gap.
# ═══════════════════════════════════════════════════════════════════════════


def test_difflib_typo_of_family_member_is_not_recognised_as_family_alias() -> None:
    """KNOWN GAP #1 (BP-741) — the exact regression the audit asked for.

    ``fundamentls_history`` is a difflib-typo of the REAL fundamentals-family
    tool name ``get_fundamentals_history`` (two character mutations: a
    dropped ``a`` and dropped trailing letters do not apply here — verified
    ratio ~0.97 against the correctly-spelled name). ``_TARGET``
    (``get_fundamentals_history_batch``, a DIFFERENT, sibling family member)
    actually ran this turn and its result pool contains the EXACT cited
    figure.

    Ideally this should resolve via the fundamentals-family alias mechanism
    (the whole point of that mechanism is "any family tool ran + the value is
    in its pool"). It does NOT, because:

    1. :func:`resolve_tool_name` computes a difflib ratio of only ~0.60
       between ``fundamentls_history`` and ``get_fundamentals_history_batch``
       (the ONLY called tool) — below the 0.85 threshold — so it returns
       ``None``.
    2. :func:`partition_phantom_tool_citations`'s family-alias branch gates on
       ``name in _FUNDAMENTALS_FAMILY_TOOLS`` — an EXACT-STRING membership
       check. The misspelled ``fundamentls_history`` is not literally in that
       frozenset (only the correctly-spelled ``get_fundamentals_history`` is),
       so the family-alias branch is never reached at all.

    The tag therefore falls through to the plain proximity-based phantom
    check and is classified ``material`` (refuse) even though the cited
    figure is genuinely grounded in a family sibling's result. This is a
    FALSE REFUSAL of an otherwise-correct answer — the interaction gap
    between the typo-resolver and the family-alias membership check that
    the 2026-07-23 audit predicted would exist (§1 Recurrence A). Pinned as
    CURRENT behavior, not desired behavior — see BP-741.
    """
    called = [_TARGET, _OTHER]  # _TARGET ran; _SIBLING (the typo's target) did NOT
    pool = {839.25e9}  # _TARGET's actual returned value — matches the cited figure
    response = "Revenue was $839.25B [fundamentls_history row 0]."

    assert resolve_tool_name("fundamentls_history", called) is None, (
        "sanity check: the typo resolver must NOT bridge this specific typo to "
        "_TARGET on its own (ratio below the 0.85 threshold) — if this ever "
        "changes, the gap below may already be fixed and this test should be "
        "revisited"
    )

    material, benign = partition_phantom_tool_citations(response, called, fundamentals_value_pool=pool)

    # CURRENT (gap) behavior: wrongly classified material/refuse despite the
    # figure being genuinely grounded in the family sibling's pool.
    assert material == {"fundamentls_history"}, (
        "documents the known interaction gap (BP-741): a difflib-typo of a "
        "family-member name is invisible to the exact-string family-alias "
        "check, so a genuinely-grounded figure is refused"
    )
    assert benign == []


def test_full_name_of_never_called_sibling_bypasses_value_check_via_containment() -> None:
    """KNOWN GAP #2 (BP-741) — mirror-image of GAP #1: resolve_tool_name
    accepts a NEVER-CALLED tool's EXACT name as grounded via pure string
    CONTAINMENT against a different, real, called sibling — with NO value
    verification at all, unlike the dedicated family-alias branch which
    explicitly requires the cited figure to appear in the pool.

    ``_SIBLING`` (``get_fundamentals_history``) ran; ``_TARGET``
    (``get_fundamentals_history_batch``) did NOT. The tag cites ``_TARGET``'s
    FULL, exact name next to a value that is NOT in ``_SIBLING``'s pool at
    all (a fabricated figure). Because ``get_fundamentals_history`` is a
    substring of ``get_fundamentals_history_batch`` (containment step 3 of
    :func:`resolve_tool_name`), ``resolve_tool_name`` resolves the never-
    called ``_TARGET`` name to ``_SIBLING`` — and
    :func:`partition_phantom_tool_citations` treats ANY non-``None``
    resolution as "not phantom" (line ``if name in called or
    resolve_tool_name(...) is not None: continue``) WITHOUT ever checking
    whether the adjacent figure is actually one of ``_SIBLING``'s returned
    values, unlike the family-alias branch a few lines below it.

    This means a tag naming a tool that never ran, next to a number that
    matches NOTHING any tool returned, is classified ``real`` — the
    strictest of the five normalizers (family-alias) is bypassed by the most
    permissive one (containment) reaching the same tag first. Scope note
    (module docstring): this only pins the citation-TAG classification;
    whether the broader numeric-value grounding pipeline separately still
    flags the fabricated figure is out of scope for this file.
    """
    called = [_SIBLING, _OTHER]  # _TARGET (named in the tag) never ran
    pool = {123.0e9}  # _SIBLING's real returned value(s) — does NOT include the cited figure
    response = "Revenue was $999.99B [get_fundamentals_history_batch row 0]."

    resolved = resolve_tool_name("get_fundamentals_history_batch", called)
    assert resolved == _SIBLING, (
        "sanity check: containment-step resolution to the sibling tool — if "
        "this stops resolving, the gap below may already be fixed and this "
        "test should be revisited"
    )

    material, benign = partition_phantom_tool_citations(response, called, fundamentals_value_pool=pool)

    # CURRENT (gap) behavior: accepted as real with zero value verification.
    assert material == set(), (
        "documents the known interaction gap (BP-741): resolve_tool_name's "
        "containment step resolves a never-called tool's exact name to an "
        "unrelated called sibling with NO value check, bypassing the "
        "value-gated family-alias branch entirely"
    )
    assert benign == []
