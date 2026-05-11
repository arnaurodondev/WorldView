"""Unit tests for E-7 Citation Egress Allowlist scrubbing.

Tests verify:
- IDs present in tool results are NOT scrubbed from the answer
- Fabricated IDs ARE scrubbed (replaced with [ref:redacted])
- seen_item_ids is accumulated across multiple tool rounds
- The _scrub_unseen_refs helper function directly
- Mixed case handling (IDs are compared case-insensitively)
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit

# A well-formed UUID that looks like it could be a real entity/article ID.
_REAL_ENTITY_UUID = "550e8400-e29b-41d4-a716-446655440000"
_FAKE_ENTITY_UUID = "deadbeef-0000-0000-0000-000000000001"
_REAL_ARTICLE_UUID = "12345678-1234-5678-1234-567812345678"
_FAKE_ARTICLE_UUID = "aaaabbbb-cccc-dddd-eeee-ffffffffffff"


class TestScrubUnseenRefs:
    def test_seen_entity_ref_not_scrubbed(self) -> None:
        """entity:UUID that IS in seen_ids should be left unchanged."""
        from rag_chat.application.use_cases.chat_orchestrator import _scrub_unseen_refs

        seen_ids = {f"entity:{_REAL_ENTITY_UUID}".lower()}
        text = f"Apple Inc (entity:{_REAL_ENTITY_UUID}) reported strong earnings."

        result, count = _scrub_unseen_refs(text, seen_ids)

        assert f"entity:{_REAL_ENTITY_UUID}" in result
        assert "[ref:redacted]" not in result
        assert count == 0

    def test_unseen_entity_ref_is_scrubbed(self) -> None:
        """entity:UUID NOT in seen_ids should be replaced with [ref:redacted]."""
        from rag_chat.application.use_cases.chat_orchestrator import _scrub_unseen_refs

        seen_ids: set[str] = set()  # nothing seen
        text = f"Apple Inc (entity:{_FAKE_ENTITY_UUID}) has good fundamentals."

        result, count = _scrub_unseen_refs(text, seen_ids)

        assert "[ref:redacted]" in result
        assert f"entity:{_FAKE_ENTITY_UUID}" not in result
        assert count == 1

    def test_seen_article_ref_not_scrubbed(self) -> None:
        """article:UUID that IS in seen_ids should be left unchanged."""
        from rag_chat.application.use_cases.chat_orchestrator import _scrub_unseen_refs

        seen_ids = {f"article:{_REAL_ARTICLE_UUID}".lower()}
        text = f"According to this report [article:{_REAL_ARTICLE_UUID}], revenue rose."

        result, count = _scrub_unseen_refs(text, seen_ids)

        assert f"article:{_REAL_ARTICLE_UUID}" in result
        assert "[ref:redacted]" not in result
        assert count == 0

    def test_unseen_article_ref_is_scrubbed(self) -> None:
        """article:UUID NOT in seen_ids → [ref:redacted]."""
        from rag_chat.application.use_cases.chat_orchestrator import _scrub_unseen_refs

        seen_ids: set[str] = set()
        text = f"See article:{_FAKE_ARTICLE_UUID} for details."

        result, count = _scrub_unseen_refs(text, seen_ids)

        assert "[ref:redacted]" in result
        assert count == 1

    def test_mixed_seen_and_unseen_refs(self) -> None:
        """Refs present in seen_ids are kept; refs absent are scrubbed."""
        from rag_chat.application.use_cases.chat_orchestrator import _scrub_unseen_refs

        seen_ids = {f"entity:{_REAL_ENTITY_UUID}".lower()}
        text = (
            f"Apple (entity:{_REAL_ENTITY_UUID}) is great. "
            f"See also entity:{_FAKE_ENTITY_UUID} and article:{_FAKE_ARTICLE_UUID}."
        )

        result, count = _scrub_unseen_refs(text, seen_ids)

        assert f"entity:{_REAL_ENTITY_UUID}" in result  # kept
        assert f"entity:{_FAKE_ENTITY_UUID}" not in result  # scrubbed
        assert f"article:{_FAKE_ARTICLE_UUID}" not in result  # scrubbed
        assert count == 2

    def test_case_insensitive_matching(self) -> None:
        """ID comparison is case-insensitive (seen_ids stored lowercase)."""
        from rag_chat.application.use_cases.chat_orchestrator import _scrub_unseen_refs

        # seen_ids contains lowercase version
        seen_ids = {f"entity:{_REAL_ENTITY_UUID}".lower()}
        # Text uses uppercase UUID
        text_upper = f"Entity:{_REAL_ENTITY_UUID.upper()} reported results."

        result, count = _scrub_unseen_refs(text_upper, seen_ids)

        # The pattern is case-insensitive so it matches the uppercase UUID;
        # and the seen_ids check should also be case-insensitive.
        assert "[ref:redacted]" not in result
        assert count == 0

    def test_no_refs_in_text_returns_unchanged(self) -> None:
        """Text with no entity/article refs is returned unchanged."""
        from rag_chat.application.use_cases.chat_orchestrator import _scrub_unseen_refs

        text = "Apple Inc reported revenue of $94.9 billion in Q4 2024."
        result, count = _scrub_unseen_refs(text, set())

        assert result == text
        assert count == 0

    def test_multiple_occurrences_all_scrubbed(self) -> None:
        """Multiple occurrences of the same unseen ref are all scrubbed."""
        from rag_chat.application.use_cases.chat_orchestrator import _scrub_unseen_refs

        seen_ids: set[str] = set()
        text = f"entity:{_FAKE_ENTITY_UUID} first mention. " f"entity:{_FAKE_ENTITY_UUID} second mention."

        result, count = _scrub_unseen_refs(text, seen_ids)

        assert count == 2
        assert f"entity:{_FAKE_ENTITY_UUID}" not in result


class TestSeenItemIdsAccumulationAcrossRounds:
    """Tests that seen_item_ids accumulates across multiple agent loop iterations.

    We test this by verifying that IDs from different tool rounds (simulated) are
    all present in the seen set before scrubbing occurs.
    """

    def test_seen_ids_from_multiple_rounds(self) -> None:
        """Items from round 1 and round 2 should both be in seen_item_ids."""
        from rag_chat.application.use_cases.chat_orchestrator import _scrub_unseen_refs

        # Simulate items from round 1
        round1_ids = {f"entity:{_REAL_ENTITY_UUID}".lower()}
        # Simulate items from round 2
        round2_ids = {f"article:{_REAL_ARTICLE_UUID}".lower()}

        # Accumulate (as the orchestrator does with seen_item_ids.add())
        seen_ids = round1_ids | round2_ids

        # Answer references both
        text = f"Apple (entity:{_REAL_ENTITY_UUID}) as per " f"article:{_REAL_ARTICLE_UUID}."

        result, count = _scrub_unseen_refs(text, seen_ids)

        # Both refs grounded → neither scrubbed
        assert count == 0
        assert f"entity:{_REAL_ENTITY_UUID}" in result
        assert f"article:{_REAL_ARTICLE_UUID}" in result

    def test_id_not_in_any_round_is_scrubbed(self) -> None:
        """An ID that was never returned by any tool round is scrubbed."""
        from rag_chat.application.use_cases.chat_orchestrator import _scrub_unseen_refs

        # IDs seen in rounds 1 and 2 — but NOT the fabricated one
        seen_ids = {
            f"entity:{_REAL_ENTITY_UUID}".lower(),
            f"article:{_REAL_ARTICLE_UUID}".lower(),
        }

        text = (
            f"Apple (entity:{_REAL_ENTITY_UUID}) as per "
            f"article:{_REAL_ARTICLE_UUID} and entity:{_FAKE_ENTITY_UUID}."
        )

        result, count = _scrub_unseen_refs(text, seen_ids)

        assert count == 1  # only the fabricated entity ID scrubbed
        assert f"entity:{_FAKE_ENTITY_UUID}" not in result
        # The real IDs are preserved
        assert f"entity:{_REAL_ENTITY_UUID}" in result
        assert f"article:{_REAL_ARTICLE_UUID}" in result
