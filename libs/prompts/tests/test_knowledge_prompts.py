"""Unit tests for prompts.knowledge — summary, entity profile, alias prompts."""

from __future__ import annotations

import pytest
from prompts.knowledge.alias import ALIAS_GENERATION
from prompts.knowledge.entity_profile import ENTITY_PROFILE
from prompts.knowledge.summary import RELATION_SUMMARY


class TestRelationSummary:
    def test_render(self) -> None:
        evidence = "- Evidence A\n- Evidence B"
        result = RELATION_SUMMARY.render(evidence_statements=evidence)
        assert "Evidence A" in result
        assert "Evidence B" in result

    def test_contains_instructions(self) -> None:
        result = RELATION_SUMMARY.render(evidence_statements="test")
        assert "2-3 sentence summary" in result
        assert "key facts" in result

    def test_missing_param_raises(self) -> None:
        with pytest.raises(ValueError, match="evidence_statements"):
            RELATION_SUMMARY.render()


class TestEntityProfile:
    def test_render(self) -> None:
        result = ENTITY_PROFILE.render(name="Apple Inc", entity_class="company")
        assert "Apple Inc" in result
        assert "company" in result

    def test_contains_json_fields(self) -> None:
        result = ENTITY_PROFILE.render(name="Test", entity_class="person")
        assert "canonical_name" in result
        assert "ticker" in result
        assert "aliases" in result

    def test_missing_name_raises(self) -> None:
        with pytest.raises(ValueError, match="name"):
            ENTITY_PROFILE.render(entity_class="company")

    def test_missing_entity_class_raises(self) -> None:
        with pytest.raises(ValueError, match="entity_class"):
            ENTITY_PROFILE.render(name="Test")

    def test_v21_has_exchange_type(self) -> None:
        # FR-12: 'exchange' must be an explicit allowed type so NYSE/NASDAQ are
        # not forced into financial_instrument/index.
        result = ENTITY_PROFILE.render(name="NYSE", entity_class="organization")
        assert "exchange" in result
        assert "NYSE" in result and "LSE" in result  # exchange exemplars present

    def test_v21_index_no_longer_lists_nasdaq(self) -> None:
        # FR-12: the old prompt used "Nasdaq" as an `index` exemplar, teaching the
        # model to conflate the exchange with the Composite index. It must be gone.
        result = ENTITY_PROFILE.render(name="x", entity_class="y")
        # The 'index' definition line should reference baskets, not the venue name.
        assert "index=market indices (the S&P 500, Dow Jones, FTSE 100" in result

    def test_v21_country_abbrev_is_place(self) -> None:
        # FR-12: 'U.S.' must be steered to place, not currency.
        result = ENTITY_PROFILE.render(name="U.S.", entity_class="location")
        assert "are 'place', NEVER 'currency'" in result

    def test_v21_generic_phrase_rule(self) -> None:
        # FR-12: 'Nvidia shares' / 'Microsoft Stock' are not distinct instruments.
        result = ENTITY_PROFILE.render(name="Nvidia shares", entity_class="company")
        assert "generic market PHRASE is NOT a distinct entity" in result

    def test_v22_has_organization_type(self) -> None:
        # FR-12 (v2.2): 'organization' must be an explicit allowed type so private
        # companies / agencies / non-profits are not forced into financial_instrument.
        result = ENTITY_PROFILE.render(name="SpaceX", entity_class="company")
        assert "organization" in result
        # The enum line must list organization between exchange and currency.
        assert "exchange |" in result and "organization" in result and "currency |" in result
        # organization exemplars present (private co, agency, university, foundation).
        assert "SpaceX" in result and "Anthropic" in result and "Foundation" in result

    def test_v22_financial_instrument_requires_ticker(self) -> None:
        # FR-12 (v2.2): financial_instrument is tightened to TRADEABLE-with-ticker;
        # a private company with no ticker is organization, not financial_instrument.
        result = ENTITY_PROFILE.render(name="SpaceX", entity_class="company")
        assert "NEVER 'financial_instrument'" in result
        assert "almost certainly 'organization'" in result

    def test_v22_company_no_longer_in_do_not_use_excludes_organization(self) -> None:
        # 'organization' was removed from the "Do NOT use" list (now canonical).
        result = ENTITY_PROFILE.render(name="x", entity_class="y")
        # The "Do NOT use" line must NOT forbid 'organization' anymore.
        assert "Do NOT use 'company', 'country'," in result


class TestAliasGeneration:
    """ALIAS_GENERATION v2.0 (PLAN-0057 Wave C-4 / F-MAJOR-09).

    The v2.0 prompt requires four parameters — ``name``, ``ticker``,
    ``description`` and ``aliases_so_far`` — and bakes four worked examples
    into the template so the LLM has a precision-over-recall demonstration.
    """

    def test_render(self) -> None:
        result = ALIAS_GENERATION.render(
            name="Apple Inc",
            ticker="AAPL",
            description="A consumer electronics company.",
            aliases_so_far="Apple Inc., AAPL",
        )
        assert "Apple Inc" in result
        assert "AAPL" in result
        assert "A consumer electronics company." in result
        assert "Apple Inc., AAPL" in result

    def test_contains_json_instruction(self) -> None:
        result = ALIAS_GENERATION.render(
            name="Test",
            ticker="TST",
            description="",
            aliases_so_far="",
        )
        assert '"aliases"' in result
        assert "5 common alternative names" in result

    def test_v20_includes_all_four_worked_examples(self) -> None:
        """Each of the 4 examples (Apple, Meta, NVIDIA, Foreward) must appear."""
        result = ALIAS_GENERATION.render(
            name="Test",
            ticker="TST",
            description="",
            aliases_so_far="",
        )
        # Apple Inc — former name "Apple Computer"
        assert "Apple Computer" in result
        assert "Apple Inc." in result
        # Meta — former name "Facebook"
        assert "Facebook" in result
        assert "Meta Platforms" in result
        # NVIDIA — casing variants
        assert "NVIDIA" in result
        assert "nVidia" in result
        # Foreward — empty list precision-over-recall demo
        assert "Foreward" in result
        assert '"aliases": []' in result

    def test_missing_name_raises(self) -> None:
        with pytest.raises(ValueError, match="name"):
            ALIAS_GENERATION.render(
                ticker="AAPL",
                description="",
                aliases_so_far="",
            )

    def test_missing_ticker_raises(self) -> None:
        with pytest.raises(ValueError, match="ticker"):
            ALIAS_GENERATION.render(
                name="Apple Inc",
                description="",
                aliases_so_far="",
            )

    def test_missing_description_raises(self) -> None:
        """v2.0 added description as a required parameter."""
        with pytest.raises(ValueError, match="description"):
            ALIAS_GENERATION.render(
                name="Apple Inc",
                ticker="AAPL",
                aliases_so_far="",
            )

    def test_missing_aliases_so_far_raises(self) -> None:
        """v2.0 added aliases_so_far as a required parameter."""
        with pytest.raises(ValueError, match="aliases_so_far"):
            ALIAS_GENERATION.render(
                name="Apple Inc",
                ticker="AAPL",
                description="",
            )

    def test_version_is_v20(self) -> None:
        assert ALIAS_GENERATION.version == "2.0"


class TestVersions:
    def test_all_versions_are_semver(self) -> None:
        # RELATION_SUMMARY at v1.0; ENTITY_PROFILE bumped to v2.2 in FR-12 (added
        # 'organization' type for tickerless private companies/agencies/non-profits,
        # on top of the v2.1 'exchange' type + disambiguation rules);
        # ALIAS_GENERATION bumped to v2.0 in PLAN-0057 Wave C-4.
        assert RELATION_SUMMARY.version == "1.0"
        assert ENTITY_PROFILE.version == "2.2"
        assert ALIAS_GENERATION.version == "2.0"
