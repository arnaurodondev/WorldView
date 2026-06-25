"""Unit tests for libs/prompts — PromptTemplate base, briefing prompts, safety."""

from __future__ import annotations

import re

import pytest
from prompts import SAFETY_FOOTER, PromptTemplate
from prompts.briefing.instrument import INSTRUMENT_BRIEFING
from prompts.briefing.morning import MORNING_BRIEFING


class TestPromptTemplate:
    def test_render_valid(self) -> None:
        pt = PromptTemplate(
            name="test", version="1.0", description="t", template="Hello {name}!", parameters=frozenset({"name"})
        )
        assert pt.render(name="World") == "Hello World!"

    def test_render_missing_param(self) -> None:
        pt = PromptTemplate(
            name="test", version="1.0", description="t", template="Hello {name}!", parameters=frozenset({"name"})
        )
        with pytest.raises(ValueError, match="name"):
            pt.render()

    def test_render_extra_params_ok(self) -> None:
        pt = PromptTemplate(
            name="test", version="1.0", description="t", template="Hello {name}!", parameters=frozenset({"name"})
        )
        result = pt.render(name="World", extra="ignored")
        assert result == "Hello World!"

    def test_frozen(self) -> None:
        pt = PromptTemplate(name="test", version="1.0", description="t", template="t", parameters=frozenset())
        with pytest.raises(AttributeError):
            pt.name = "changed"  # type: ignore[misc]


class TestMorningBriefing:
    def test_render(self) -> None:
        result = MORNING_BRIEFING.render(
            portfolio_context="holdings data",
            news_context="news data",
            alerts_context="alerts data",
            market_overview="market data",
            events_context="events data",
            safety=SAFETY_FOOTER,
            current_date="2026-04-26",  # required after v2.1 — date context for LLM
        )
        assert "holdings data" in result
        assert "news data" in result

    def test_contains_safety(self) -> None:
        result = MORNING_BRIEFING.render(
            portfolio_context="",
            news_context="",
            alerts_context="",
            market_overview="",
            events_context="",
            safety=SAFETY_FOOTER,
            current_date="2026-04-26",  # required after v2.1 — date context for LLM
        )
        assert "Never speculate beyond the evidence provided" in result

    def test_v45_six_section_spec(self) -> None:
        """Prompt must instruct the LLM to emit the v4.5 six-section investor brief.

        VERSION HISTORY (test):
          - PLAN-0048 Wave A (v2.2): ## SUMMARY + --- + ## DETAILS.
          - PLAN-0062-W4 (v3.0): ## SUMMARY renamed to ## LEAD, divider unchanged.
          - PLAN-0102 W1 (v4.0): added 6-section spec ABOVE the legacy LEAD/DETAILS
            template — the two contradicted each other; live brief followed the 6-
            section spec but the LLM was given conflicting instructions.
          - PLAN-0103 W2 (v4.1): DELETED the legacy LEAD/DETAILS template and the
            "max 4 sections, max 4 bullets" caps. The 6-section spec is now the
            single source of truth.
          - PLAN-0103 W3 (v4.2): added the leading ``## Summary`` paragraph block
            for the dashboard collapsed view AND promoted all 6 sections to
            MANDATORY (placeholder lines on quiet sections) so the LLM cannot
            drop Risks + Opportunities / Bonus context on quiet news days (FQA-01).
          - PLAN-0103 W9 (v4.4): SPLIT the single ``250 words`` cap into a 50-word
            Summary cap + a 700-word Details cap with per-section guidance.
            The 250-word global cap was too restrictive for 6 sections.
          - PLAN-0103 W11 (v4.5): ADAPTIVE Summary length — the fixed 50-word
            cap from v4.4 was OK for a 10-position book on a quiet day but
            truncated useful synthesis on large books / very active days.
            v4.5 replaces it with a ~100-word target + size bands
            (30-60w small+quiet, 80-150w medium+normal, up to 200w large/
            very active). Parser cap raised 300 → 1500 chars.

        WHY update (not delete): R19 — the prompt is still mandating a structural
        contract, only its shape has changed. We assert the new contract.
        """
        result = MORNING_BRIEFING.render(
            portfolio_context="",
            news_context="",
            alerts_context="",
            market_overview="",
            events_context="",
            safety=SAFETY_FOOTER,
            current_date="2026-04-26",
        )
        # v4.2/v4.6 — the 6 named sections in the exact spec order
        # (v4.6 renamed "Tape" → "Market Snapshot" for clarity to non-floor-trader users).
        assert "**Market Snapshot**" in result
        assert "**Your Portfolio Today**" in result
        assert "**Macro Today**" in result
        assert "**News That Matters To You**" in result
        assert "**Risks + Opportunities**" in result
        assert "**Bonus context**" in result
        # v4.4 — the single 250-word cap is GONE; replaced by the split caps below.
        # We assert its absence so a future regression cannot silently re-introduce
        # the restrictive global cap.
        assert "250 words" not in result, "v4.4 deleted the 250-word global cap"
        assert "Cap total brief" not in result, "v4.4 deleted the single 'cap total brief' directive"
        # v4.5 — Summary cap is ADAPTIVE (target ~100w; 30-200w bands);
        # Details cap unchanged from v4.4 at ≤700w.
        # (a) Summary block: target wording + adaptive size bands.
        assert "Summary block: target ~100 words" in result
        assert "adapt to portfolio breadth + market activity" in result
        # The three size bands must all be present verbatim so the LLM can
        # cite the matching one for the current portfolio + market state.
        assert "Small portfolio (≤10 positions)" in result
        assert "Medium portfolio (10-30 positions)" in result
        assert "Large portfolio (30+ positions)" in result
        assert "Hard cap: 200 words" in result
        # v4.4 fixed "Summary block: ≤ 50 words" wording MUST be gone — a
        # regression would silently re-introduce the truncation problem.
        assert (
            "Summary block: ≤ 50 words" not in result
        ), "v4.5 replaced the fixed 50-word Summary cap with adaptive guidance"
        # (b) Details block: ≤ 1200 words across all 6 sections combined (v4.6 raised from 700w).
        assert "Details block: ≤ 1200 words" in result
        # Per-section guidance signposts — at least the two highest-signal
        # sections must carry an explicit budget so the LLM can stop
        # truncating News and Portfolio bullets at 250 words.
        assert "Your Portfolio Today 3-6 bullets" in result
        assert "News That Matters To You 3-5 bullets" in result
        # Citations must use [cN] form (PRD-0030 v4.7): the only marker form the
        # backend resolver maps to a source; the prior [N#] form was orphaned.
        assert "[c1]" in result and "[c2]" in result
        # v4.1 deletions: the legacy LEAD/DETAILS template + 4/4 caps must be gone.
        # Negative assertions guard against accidental v4.0 regression.
        assert "## LEAD" not in result, "v4.2 must not re-introduce the legacy ## LEAD block"
        # v4.2 uses ``## Summary`` + ``## Details`` (lowercase second word) for the
        # new two-block structure — the all-caps legacy ``## DETAILS`` must stay gone.
        assert "## DETAILS" not in result, "v4.2 must not re-introduce the all-caps legacy ## DETAILS"
        assert "Maximum 4 sections" not in result, "v4.1 deleted the 4-section cap"
        assert "literal `---` divider" not in result, "v4.1 deleted the divider mandate"
        # Must still forbid the redundant Morning Briefing header in the body.
        assert "Morning Briefing" in result  # appears in the forbid clause
        # v4.2 additions — the new structure headings + MANDATORY language.
        assert "## Summary" in result
        assert "## Details" in result
        assert "MANDATORY" in result
        # Version constant must reflect the v4.8 release: brief-quality eval
        # BUG 4 (sentiment-sign + same-holding attribution gate) + BUG 5
        # (no [cN] on the tape line; singular markers only).
        assert MORNING_BRIEFING.version == "4.8"

    def test_v45_few_shot_examples_present(self) -> None:
        """v4.3 must embed BOTH few-shot examples (rich + quiet day).

        WHY: the v4.2 imperative prompt alone failed in production (FQA-01
        documented the LLM dropping 2 of 6 sections + skipping ``## Summary``
        even though the prompt mandated them). Few-shot demonstration is the
        most reliable lever for teaching structural conformance — the LLM
        imitates Example A's shape on busy days and Example B's placeholder
        pattern on quiet days. Both example markers MUST be present in the
        rendered prompt; regression would indicate accidental v4.2 revert.
        """
        result = MORNING_BRIEFING.render(
            portfolio_context="",
            news_context="",
            alerts_context="",
            market_overview="",
            events_context="",
            safety=SAFETY_FOOTER,
            current_date="2026-05-30",
        )
        # Both example markers must appear verbatim.
        assert "Example A — Rich day" in result
        assert "Example B — Quiet day" in result
        # Rich-day Example A must show populated bullets in every section.
        # PLAN-0103 W11 (v4.5): Example A's Summary was re-shot at ~150 words
        # mentioning top-3 holdings by P&L impact; the original bullets
        # (Dell +40%, Vision Pro shipment beat) are unchanged.
        assert "Dell +40%" in result
        assert "Vision Pro" in result
        # v4.5 Summary must reference top holdings by P&L impact (the new
        # "Mention top 1-3 holdings ... when summary > 50 words" guidance).
        assert "**MSFT**" in result and "**AAPL**" in result and "**NVDA**" in result
        # Quiet-day Example B must show the placeholder pattern in action.
        assert "Quiet pre-mkt session" in result
        assert "No major economic releases scheduled" in result
        assert "No notable risk signals identified today" in result
        # The tightened output-contract heading must be present (sits above
        # the examples and reinforces the MANDATORY contract).
        assert "Output Contract" in result


class TestInstrumentBriefing:
    def test_render(self) -> None:
        result = INSTRUMENT_BRIEFING.render(
            entity_context="entity data",
            fundamentals_context="fundamentals data",
            news_context="news data",
            events_context="events data",
            relationships_context="relationships data",
            safety=SAFETY_FOOTER,
        )
        assert "entity data" in result
        assert "fundamentals data" in result

    def test_contains_safety(self) -> None:
        result = INSTRUMENT_BRIEFING.render(
            entity_context="",
            fundamentals_context="",
            news_context="",
            events_context="",
            relationships_context="",
            safety=SAFETY_FOOTER,
        )
        assert "Never speculate beyond the evidence provided" in result


class TestPromptVersions:
    def test_versions_are_semver(self) -> None:
        for pt in [MORNING_BRIEFING, INSTRUMENT_BRIEFING]:
            assert re.match(r"\d+\.\d+", pt.version), f"{pt.name} version is not semver-like: {pt.version}"


# --------------------------------------------------------------------------
# MN-4 / QA F-005 — base-class enhancement tests (PLAN-0099-W4).
#
# Three new contracts on PromptTemplate that are NOT exercised by the older
# happy-path tests above:
#   1) Semver validation rejects malformed version strings at import time.
#   2) content_hash changes when the template body changes by even one char.
#   3) The brace guard rejects undeclared {placeholder} slots so a literal
#      JSON example can never silently swallow a parameter substitution.
# --------------------------------------------------------------------------


class TestSemverValidation:
    """Constructor rejects non-semver version strings (fail-loud at import)."""

    @pytest.mark.parametrize(
        "bad_version",
        [
            "v1",  # leading 'v' — common typo but not semver
            "1",  # missing MINOR
            "1.0.0-rc1",  # pre-release suffix explicitly disallowed
            "1.x",  # placeholder digit
            "",  # empty string
        ],
    )
    def test_invalid_semver_rejected(self, bad_version: str) -> None:
        # WHY: a version typo in a prompt definition file would only surface
        # at the first LLM call site. Failing at import time prevents broken
        # rubrics from making it into a long-running judge run.
        with pytest.raises(ValueError, match="semver"):
            PromptTemplate(
                name="bad",
                version=bad_version,
                description="d",
                template="ok",
                parameters=frozenset(),
            )

    def test_valid_semver_accepted(self) -> None:
        # Both MAJOR.MINOR and MAJOR.MINOR.PATCH must work — the regex
        # explicitly opts into both forms.
        for good in ("1.0", "1.2.3", "10.20", "0.1.0"):
            pt = PromptTemplate(
                name="ok",
                version=good,
                description="d",
                template="t",
                parameters=frozenset(),
            )
            assert pt.version == good


class TestContentHash:
    """A single-character edit to the template body must flip content_hash."""

    def test_content_hash_changes_when_body_edited(self) -> None:
        # Build two templates identical in every field EXCEPT one char in the
        # body. If content_hash collides, the eval pipeline cannot detect
        # silent prompt drift between two judge runs of the same name+version.
        pt_a = PromptTemplate(
            name="drift",
            version="1.0",
            description="d",
            template="Hello world.",
            parameters=frozenset(),
        )
        pt_b = PromptTemplate(
            name="drift",
            version="1.0",
            description="d",
            template="Hello world!",  # ← single-char diff (period -> exclamation)
            parameters=frozenset(),
        )
        assert pt_a.content_hash != pt_b.content_hash
        # And both must be the expected 12-char sha256 prefix length.
        assert len(pt_a.content_hash) == 12
        assert len(pt_b.content_hash) == 12

    def test_content_hash_stable_for_identical_body(self) -> None:
        # Sanity floor — two byte-equal templates produce the same hash even
        # when the wrapping metadata (name, version) differs.
        pt_a = PromptTemplate(
            name="a",
            version="1.0",
            description="d1",
            template="same body",
            parameters=frozenset(),
        )
        pt_b = PromptTemplate(
            name="b",
            version="2.5",
            description="d2",
            template="same body",
            parameters=frozenset(),
        )
        assert pt_a.content_hash == pt_b.content_hash


class TestBraceGuard:
    """MN-5 — undeclared {placeholder} slots and unescaped braces are rejected."""

    def test_undeclared_placeholder_rejected(self) -> None:
        # ``{name}`` is a slot but ``parameters`` is empty — must fail at
        # construction with a clear "undeclared placeholder" message.
        with pytest.raises(ValueError, match="undeclared placeholder"):
            PromptTemplate(
                name="guard",
                version="1.0",
                description="d",
                template="Hello {name}!",
                parameters=frozenset(),  # ← intentionally missing 'name'
            )

    def test_declared_placeholder_accepted(self) -> None:
        # Mirror of the test above — the SAME template with the correct
        # parameter set must construct + render cleanly. Guards against an
        # over-eager guard rejecting legitimate templates.
        pt = PromptTemplate(
            name="guard",
            version="1.0",
            description="d",
            template="Hello {name}!",
            parameters=frozenset({"name"}),
        )
        assert pt.render(name="Alice") == "Hello Alice!"

    def test_escaped_braces_accepted(self) -> None:
        # Doubled braces represent literal { / } in str.format_map. A JSON
        # example block in a prompt body uses this form — must be accepted
        # with NO declared parameters, and .render() must collapse them.
        pt = PromptTemplate(
            name="json_example",
            version="1.0",
            description="d",
            template='Reply: {{"score": 25}}',
            parameters=frozenset(),
        )
        assert pt.render() == 'Reply: {"score": 25}'

    def test_unbalanced_single_brace_rejected(self) -> None:
        # A lone ``{`` or ``}`` makes string.Formatter().parse raise
        # ValueError; the guard wraps it in a guidance message that points
        # the author at the escape syntax. We accept either the wrapped
        # "unescaped brace" message OR the inner parser message.
        with pytest.raises(ValueError, match="brace|Single"):
            PromptTemplate(
                name="bad_brace",
                version="1.0",
                description="d",
                template="Stray { brace.",
                parameters=frozenset(),
            )

    def test_positional_placeholder_rejected(self) -> None:
        # Positional ``{}`` slots are forbidden — named placeholders only,
        # so the substitution intent is always explicit + grep-able.
        with pytest.raises(ValueError, match="positional|undeclared|brace"):
            PromptTemplate(
                name="pos",
                version="1.0",
                description="d",
                template="Hello {}!",
                parameters=frozenset(),
            )
