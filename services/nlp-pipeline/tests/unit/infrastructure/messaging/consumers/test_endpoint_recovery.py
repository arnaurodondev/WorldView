"""Unit tests for the layered M1+M2 endpoint-recovery (2026-06-14 mitigation).

Implements the audit's §C.5 nine-test plan for the relation-drop fix in
``docs/audits/2026-06-14-entity-ref-matching-and-mitigation.md``:

  M1 (canonical-store fall-back):
    1. ref not in entity_id_by_ref but EXACT alias exists → bound to canonical,
       entity_provisional=False.
    2. ref below the gate (no exact/ticker hit, fuzzy not run) → NOT bound.
    3. batched lookup issues ONE exact-match query for N missed refs.
  M2 (provisional minting):
    4. unknown LLM endpoint (no mention, no canonical) → provisional minted,
       relation persists with entity_provisional=True.
    5. junk / common-noun / empty ref → still dropped, no provisional minted.
    6. churn-guard hit → no mint, ref stays dropped.
  Shared:
    7. both endpoints already in doc-local lookup → no extra query, unchanged.
    8. events + claims get the SAME treatment (shared matcher).
    9. metric increments per outcome (m1_recovered / m2_minted / dropped_junk).

Plus regression: M1 + M2 wired through ``_build_raw_relations`` so the recovered
refs actually produce persisted rows, and the existing doc-local resolved +
provisional behaviour (F-CRIT-07) is unchanged.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from nlp_pipeline.infrastructure.messaging.consumers.blocks.endpoint_recovery import (
    _collect_missed_refs,
    _is_junk_ref,
    recover_missed_endpoints,
)
from nlp_pipeline.infrastructure.messaging.consumers.blocks.enriched_event import _build_raw_relations

pytestmark = pytest.mark.unit


# ── Fixtures / mock builders ─────────────────────────────────────────────────


def _alias_repo_mock(
    *,
    exact: dict[str, uuid.UUID] | None = None,
    ticker_isin: dict[str, uuid.UUID] | None = None,
) -> MagicMock:
    """Build an EntityAliasRepository mock.

    ``batch_exact_match`` returns ``{lower(trim(surface)): entity_id}``;
    ``batch_ticker_isin_match`` returns ``{raw_surface: entity_id}``.
    """
    repo = MagicMock()
    repo.batch_exact_match = AsyncMock(return_value=exact or {})
    repo.batch_ticker_isin_match = AsyncMock(return_value=ticker_isin or {})
    return repo


def _intel_session_mint(queue_ids: list[uuid.UUID]) -> MagicMock:
    """Intel-session mock that mints *queue_ids* (one COUNT + one INSERT each)."""
    session = MagicMock()
    side_effects: list[MagicMock] = []
    for qid in queue_ids:
        count_result = MagicMock()
        count_result.scalar_one = MagicMock(return_value=0)  # churn-guard: clear
        insert_result = MagicMock()
        insert_result.scalar_one = MagicMock(return_value=str(qid))
        side_effects.extend([count_result, insert_result])
    session.execute = AsyncMock(side_effect=side_effects)
    nested_cm = AsyncMock()
    nested_cm.__aenter__ = AsyncMock(return_value=None)
    nested_cm.__aexit__ = AsyncMock(return_value=False)
    session.begin_nested = MagicMock(return_value=nested_cm)
    return session


def _intel_session_churn_blocked() -> MagicMock:
    """Intel-session mock whose churn-guard COUNT returns over the limit."""
    session = MagicMock()
    count_result = MagicMock()
    count_result.scalar_one = MagicMock(return_value=999)  # >= MAX_PROVISIONAL_PER_HOUR
    session.execute = AsyncMock(return_value=count_result)
    nested_cm = AsyncMock()
    nested_cm.__aenter__ = AsyncMock(return_value=None)
    nested_cm.__aexit__ = AsyncMock(return_value=False)
    session.begin_nested = MagicMock(return_value=nested_cm)
    return session


# ── _is_junk_ref ─────────────────────────────────────────────────────────────


class TestIsJunkRef:
    def test_empty_and_short(self) -> None:
        assert _is_junk_ref("")
        assert _is_junk_ref("  ")
        assert _is_junk_ref("ab")  # < 3 chars

    def test_common_noun_blocklist(self) -> None:
        assert _is_junk_ref("analysts")
        assert _is_junk_ref("Investors")
        assert _is_junk_ref("the company")
        assert _is_junk_ref("Management")
        # suffix/whitespace variants also caught
        assert _is_junk_ref("The Company.")

    def test_purely_numeric(self) -> None:
        assert _is_junk_ref("2024")
        assert _is_junk_ref("41%")
        assert _is_junk_ref("$505")

    def test_real_entities_not_junk(self) -> None:
        assert not _is_junk_ref("Oklo")
        assert not _is_junk_ref("Kinder Morgan")
        assert not _is_junk_ref("ARMEC")
        assert not _is_junk_ref("CoreWeave Inc.")


# ── _collect_missed_refs ─────────────────────────────────────────────────────


class TestCollectMissedRefs:
    def test_only_returns_refs_absent_from_lookup(self) -> None:
        extraction = {
            "relations": [{"subject_ref": "Oklo", "object_ref": "ARMEC"}],
            "events": [],
            "claims": [],
        }
        # "oklo" is already in the doc-local lookup → only ARMEC is missed.
        lookup = {"oklo": str(uuid.uuid4())}
        missed = _collect_missed_refs(extraction, lookup)
        assert "armec" in missed
        assert "oklo" not in missed
        assert missed["armec"] == "ARMEC"

    def test_test7_both_endpoints_present_returns_empty(self) -> None:
        """§C.5 test 7: both endpoints already in lookup → nothing missed."""
        extraction = {"relations": [{"subject_ref": "Apple", "object_ref": "TSMC"}]}
        lookup = {"apple": str(uuid.uuid4()), "tsmc": str(uuid.uuid4())}
        assert _collect_missed_refs(extraction, lookup) == {}

    def test_dedupes_repeated_refs(self) -> None:
        extraction = {
            "relations": [
                {"subject_ref": "Foo Corp", "object_ref": "Bar"},
                {"subject_ref": "Foo", "object_ref": "Bar"},
            ]
        }
        missed = _collect_missed_refs(extraction, {})
        # "Foo Corp" (variants foo corp, foo) and "Foo" (variant foo) dedup to a
        # single entry plus "Bar" → two missed refs total, not three.
        assert missed["bar"] == "Bar"
        foo_surfaces = [v for k, v in missed.items() if v in ("Foo Corp", "Foo")]
        assert foo_surfaces == ["Foo Corp"]  # first-seen wins
        assert len(missed) == 2

    def test_walks_events_and_claims(self) -> None:
        extraction = {
            "relations": [],
            "events": [{"entity_refs": ["Microsoft", "Activision"]}],
            "claims": [{"entity_ref": "Tesla"}],
        }
        missed = _collect_missed_refs(extraction, {})
        assert {"microsoft", "activision", "tesla"} <= set(missed)


# ── recover_missed_endpoints — M1 ────────────────────────────────────────────


class TestRecoverM1:
    @pytest.mark.asyncio
    async def test_test1_exact_alias_hit_binds_canonical(self) -> None:
        """§C.5 test 1: missed ref with EXACT alias → bound, entity_provisional=False."""
        canonical = uuid.uuid4()
        extraction = {"relations": [{"subject_ref": "Oklo", "object_ref": "ARMEC"}]}
        lookup = {"oklo": str(uuid.uuid4())}  # subject already resolved
        provisional_refs: set[str] = set()
        alias_repo = _alias_repo_mock(exact={"armec": canonical})

        await recover_missed_endpoints(
            extraction_result=extraction,
            entity_id_by_ref=lookup,
            provisional_refs=provisional_refs,
            alias_repo=alias_repo,
            intelligence_session=None,  # M2 path not needed (M1 hits)
            doc_id=uuid.uuid4(),
        )

        # Bound to the real canonical, NOT flagged provisional.
        assert lookup["armec"] == str(canonical)
        assert "armec" not in provisional_refs

    @pytest.mark.asyncio
    async def test_test2_below_gate_not_bound(self) -> None:
        """§C.5 test 2: no exact/ticker hit (fuzzy not run) → ref NOT bound."""
        extraction = {"relations": [{"subject_ref": "Oklo", "object_ref": "Some Unknown Co"}]}
        lookup = {"oklo": str(uuid.uuid4())}
        provisional_refs: set[str] = set()
        alias_repo = _alias_repo_mock(exact={}, ticker_isin={})

        await recover_missed_endpoints(
            extraction_result=extraction,
            entity_id_by_ref=lookup,
            provisional_refs=provisional_refs,
            alias_repo=alias_repo,
            intelligence_session=None,  # no M2 → genuine drop
            doc_id=uuid.uuid4(),
        )

        # Precision-safe: nothing bound for the unresolved endpoint.
        assert "some unknown co" not in lookup

    @pytest.mark.asyncio
    async def test_test3_batched_single_exact_query(self) -> None:
        """§C.5 test 3 (batching): N missed refs → ONE batch_exact_match call."""
        extraction = {
            "relations": [
                {"subject_ref": "Alpha", "object_ref": "Beta"},
                {"subject_ref": "Gamma", "object_ref": "Delta"},
            ]
        }
        alias_repo = _alias_repo_mock(exact={})

        await recover_missed_endpoints(
            extraction_result=extraction,
            entity_id_by_ref={},
            provisional_refs=set(),
            alias_repo=alias_repo,
            intelligence_session=None,
            doc_id=uuid.uuid4(),
        )

        # Exactly one batched exact query for all 4 missed refs.
        assert alias_repo.batch_exact_match.await_count == 1
        passed_surfaces = alias_repo.batch_exact_match.await_args.args[0]
        assert set(passed_surfaces) == {"Alpha", "Beta", "Gamma", "Delta"}

    @pytest.mark.asyncio
    async def test_test7_no_query_when_nothing_missed(self) -> None:
        """§C.5 test 7: both endpoints in lookup → no DB call at all."""
        extraction = {"relations": [{"subject_ref": "Apple", "object_ref": "TSMC"}]}
        lookup = {"apple": str(uuid.uuid4()), "tsmc": str(uuid.uuid4())}
        alias_repo = _alias_repo_mock(exact={})

        await recover_missed_endpoints(
            extraction_result=extraction,
            entity_id_by_ref=lookup,
            provisional_refs=set(),
            alias_repo=alias_repo,
            intelligence_session=None,
            doc_id=uuid.uuid4(),
        )

        alias_repo.batch_exact_match.assert_not_awaited()


# ── recover_missed_endpoints — M2 ────────────────────────────────────────────


class TestRecoverM2:
    @pytest.mark.asyncio
    async def test_test4_unknown_endpoint_mints_provisional(self) -> None:
        """§C.5 test 4: unknown LLM endpoint → provisional minted, flagged provisional."""
        extraction = {"relations": [{"subject_ref": "Oklo", "object_ref": "ARMEC"}]}
        lookup = {"oklo": str(uuid.uuid4())}
        provisional_refs: set[str] = set()
        alias_repo = _alias_repo_mock(exact={})  # M1 misses
        new_qid = uuid.uuid4()
        session = _intel_session_mint([new_qid])

        await recover_missed_endpoints(
            extraction_result=extraction,
            entity_id_by_ref=lookup,
            provisional_refs=provisional_refs,
            alias_repo=alias_repo,
            intelligence_session=session,
            doc_id=uuid.uuid4(),
        )

        assert lookup["armec"] == str(new_qid)
        assert "armec" in provisional_refs

    @pytest.mark.asyncio
    async def test_test5_junk_ref_not_minted(self) -> None:
        """§C.5 test 5: common-noun / empty ref → no provisional, stays dropped."""
        extraction = {
            "relations": [
                {"subject_ref": "Oklo", "object_ref": "analysts"},  # common noun
                {"subject_ref": "Oklo", "object_ref": "ab"},  # too short
            ]
        }
        lookup = {"oklo": str(uuid.uuid4())}
        provisional_refs: set[str] = set()
        alias_repo = _alias_repo_mock(exact={})
        session = _intel_session_mint([])  # no mints expected

        await recover_missed_endpoints(
            extraction_result=extraction,
            entity_id_by_ref=lookup,
            provisional_refs=provisional_refs,
            alias_repo=alias_repo,
            intelligence_session=session,
            doc_id=uuid.uuid4(),
        )

        assert "analysts" not in lookup
        assert "ab" not in lookup
        # No INSERT attempted for junk refs.
        session.execute.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_test6_churn_guard_blocks_mint(self) -> None:
        """§C.5 test 6: churn-guard over limit → no mint, ref stays dropped."""
        extraction = {"relations": [{"subject_ref": "Oklo", "object_ref": "ARMEC"}]}
        lookup = {"oklo": str(uuid.uuid4())}
        provisional_refs: set[str] = set()
        alias_repo = _alias_repo_mock(exact={})
        session = _intel_session_churn_blocked()

        await recover_missed_endpoints(
            extraction_result=extraction,
            entity_id_by_ref=lookup,
            provisional_refs=provisional_refs,
            alias_repo=alias_repo,
            intelligence_session=session,
            doc_id=uuid.uuid4(),
        )

        assert "armec" not in lookup
        assert "armec" not in provisional_refs

    @pytest.mark.asyncio
    async def test_test8_events_and_claims_share_fix(self) -> None:
        """§C.5 test 8: events.entity_refs and claims.entity_ref recover too."""
        extraction = {
            "relations": [],
            "events": [{"entity_refs": ["Belite Bio"]}],
            "claims": [{"entity_ref": "Larry Ellison"}],
        }
        lookup: dict[str, str] = {}
        provisional_refs: set[str] = set()
        canonical = uuid.uuid4()
        # Belite Bio resolves via M1 exact alias; Larry Ellison mints via M2.
        alias_repo = _alias_repo_mock(exact={"belite bio": canonical})
        new_qid = uuid.uuid4()
        session = _intel_session_mint([new_qid])

        await recover_missed_endpoints(
            extraction_result=extraction,
            entity_id_by_ref=lookup,
            provisional_refs=provisional_refs,
            alias_repo=alias_repo,
            intelligence_session=session,
            doc_id=uuid.uuid4(),
        )

        assert lookup["belite bio"] == str(canonical)  # M1
        assert "belite bio" not in provisional_refs
        assert lookup["larry ellison"] == str(new_qid)  # M2
        assert "larry ellison" in provisional_refs


# ── Metric increments (§C.5 test 9) ──────────────────────────────────────────


class TestMetrics:
    @pytest.mark.asyncio
    async def test_test9_metric_increments_per_outcome(self) -> None:
        """§C.5 test 9: m1_recovered / m2_minted / dropped_junk all increment."""
        from nlp_pipeline.infrastructure.metrics.prometheus import (
            s6_extraction_endpoint_recovery_total,
        )

        def _val(outcome: str) -> float:
            return s6_extraction_endpoint_recovery_total.labels(outcome=outcome)._value.get()

        before = {o: _val(o) for o in ("m1_recovered", "m2_minted", "dropped_junk")}

        extraction = {
            "relations": [
                {"subject_ref": "Oklo", "object_ref": "ARMEC"},  # M1
                {"subject_ref": "Oklo", "object_ref": "Mystery Co"},  # M2
                {"subject_ref": "Oklo", "object_ref": "analysts"},  # junk
            ]
        }
        lookup = {"oklo": str(uuid.uuid4())}
        canonical = uuid.uuid4()
        alias_repo = _alias_repo_mock(exact={"armec": canonical})
        session = _intel_session_mint([uuid.uuid4()])

        await recover_missed_endpoints(
            extraction_result=extraction,
            entity_id_by_ref=lookup,
            provisional_refs=set(),
            alias_repo=alias_repo,
            intelligence_session=session,
            doc_id=uuid.uuid4(),
        )

        assert _val("m1_recovered") == before["m1_recovered"] + 1
        assert _val("m2_minted") == before["m2_minted"] + 1
        assert _val("dropped_junk") == before["dropped_junk"] + 1


# ── End-to-end through _build_raw_relations (the actual persist path) ─────────


class TestRecoveryThroughBuildRawRelations:
    @pytest.mark.asyncio
    async def test_m1_recovered_ref_produces_persisted_relation(self) -> None:
        """M1: after recovery, _build_raw_relations emits the row (not dropped)."""
        subject = uuid.uuid4()
        canonical = uuid.uuid4()
        relations = [{"subject_ref": "Oklo", "object_ref": "ARMEC", "predicate": "acquired_by"}]
        lookup = {"oklo": str(subject)}
        provisional_refs: set[str] = set()
        alias_repo = _alias_repo_mock(exact={"armec": canonical})

        await recover_missed_endpoints(
            extraction_result={"relations": relations},
            entity_id_by_ref=lookup,
            provisional_refs=provisional_refs,
            alias_repo=alias_repo,
            intelligence_session=None,
            doc_id=uuid.uuid4(),
        )
        rows = _build_raw_relations(relations, lookup, provisional_refs)

        assert len(rows) == 1
        assert rows[0]["subject_entity_id"] == str(subject)
        assert rows[0]["object_entity_id"] == str(canonical)
        assert rows[0]["entity_provisional"] is False

    @pytest.mark.asyncio
    async def test_m2_minted_ref_produces_provisional_relation(self) -> None:
        """M2: after recovery, _build_raw_relations emits with entity_provisional=True."""
        subject = uuid.uuid4()
        new_qid = uuid.uuid4()
        relations = [{"subject_ref": "Oklo", "object_ref": "ARMEC", "predicate": "acquired_by"}]
        lookup = {"oklo": str(subject)}
        provisional_refs: set[str] = set()
        alias_repo = _alias_repo_mock(exact={})  # M1 misses
        session = _intel_session_mint([new_qid])

        await recover_missed_endpoints(
            extraction_result={"relations": relations},
            entity_id_by_ref=lookup,
            provisional_refs=provisional_refs,
            alias_repo=alias_repo,
            intelligence_session=session,
            doc_id=uuid.uuid4(),
        )
        rows = _build_raw_relations(relations, lookup, provisional_refs)

        assert len(rows) == 1
        assert rows[0]["object_entity_id"] == str(new_qid)
        assert rows[0]["entity_provisional"] is True
        assert rows[0]["provisional_queue_id"] == str(new_qid)

    @pytest.mark.asyncio
    async def test_junk_ref_still_dropped_by_build(self) -> None:
        """Junk endpoint not recovered → _build_raw_relations drops the relation."""
        relations = [{"subject_ref": "Oklo", "object_ref": "analysts", "predicate": "partner_of"}]
        lookup = {"oklo": str(uuid.uuid4())}
        provisional_refs: set[str] = set()
        alias_repo = _alias_repo_mock(exact={})
        session = _intel_session_mint([])

        await recover_missed_endpoints(
            extraction_result={"relations": relations},
            entity_id_by_ref=lookup,
            provisional_refs=provisional_refs,
            alias_repo=alias_repo,
            intelligence_session=session,
            doc_id=uuid.uuid4(),
        )
        rows = _build_raw_relations(relations, lookup, provisional_refs)

        assert rows == []  # genuine drop preserved for true junk


# ── BUG-3 wiring regression ──────────────────────────────────────────────────
#
# The M1/M2 logic above is correct, but commit 2295a4a15 added it as DEAD CODE:
# ``recover_missed_endpoints`` had ZERO production callers — the call site inside
# ``_enqueue_enriched`` (the only place ``entity_id_by_ref`` exists) was never
# wired in, so every non-mention endpoint kept being silently dropped despite the
# mitigation existing. These tests lock in the wiring: ``_enqueue_enriched`` MUST
# invoke recovery (with the injected alias_repo + intel session) AND a recovered
# relation MUST flow into the serialized enriched payload.


class TestEndpointRecoveryWiredIntoEnqueueEnriched:
    @pytest.mark.asyncio
    async def test_enqueue_enriched_invokes_recovery(self) -> None:
        """``_enqueue_enriched`` calls ``recover_missed_endpoints`` (BUG-3 wiring)."""
        from unittest.mock import patch

        import nlp_pipeline.infrastructure.messaging.consumers.blocks.enriched_event as ee
        from nlp_pipeline.domain.enums import RoutingTier
        from nlp_pipeline.domain.models import RoutingDecision

        outbox_repo = AsyncMock()
        settings = MagicMock()
        settings.topic_article_enriched = "nlp.article.enriched.v1"
        doc_id = uuid.uuid4()
        rd = RoutingDecision(
            decision_id=uuid.uuid4(),
            doc_id=doc_id,
            routing_tier=RoutingTier.MEDIUM,
            composite_score=0.5,
            feature_scores={},
        )
        alias_repo = _alias_repo_mock(exact={})
        intel_session = _intel_session_mint([])
        extraction = {"relations": [{"subject_ref": "Oklo", "object_ref": "ARMEC"}], "events": [], "claims": []}

        with patch.object(ee, "recover_missed_endpoints", new=AsyncMock()) as mock_recover:
            await ee._enqueue_enriched(
                outbox_repo=outbox_repo,
                settings=settings,
                doc_id=doc_id,
                source_type="eodhd",
                published_at=None,
                is_backfill=False,
                routing_decision=rd,
                sections=[],
                chunks=[],
                mentions=[],
                extraction_result=extraction,
                correlation_id=None,
                alias_repo=alias_repo,
                intelligence_session=intel_session,
            )

        # The dead-code bug: recovery was NEVER called. Assert the wiring exists
        # and forwards the injected dependencies + the doc-local lookup objects.
        mock_recover.assert_awaited_once()
        kwargs = mock_recover.await_args.kwargs
        assert kwargs["alias_repo"] is alias_repo
        assert kwargs["intelligence_session"] is intel_session
        assert kwargs["doc_id"] == doc_id
        assert kwargs["extraction_result"] is extraction

    @pytest.mark.asyncio
    async def test_m1_recovered_relation_reaches_payload(self) -> None:
        """An M1-recoverable endpoint produces a relation in the enriched payload.

        End-to-end through the REAL ``recover_missed_endpoints``: the object_ref
        ("ARMEC") is NOT a doc-local mention, so without recovery the relation
        would be ``continue``-dropped. With the wiring + an exact-alias hit, it
        binds to the canonical and the row appears in ``raw_relations_json``.
        """
        import nlp_pipeline.infrastructure.messaging.consumers.blocks.enriched_event as ee
        from nlp_pipeline.domain.enums import RoutingTier
        from nlp_pipeline.domain.models import EntityMention, RoutingDecision
        from nlp_pipeline.infrastructure.messaging.consumers.article_consumer import _SCHEMA_DIR

        from messaging.kafka.serialization_utils import deserialize_confluent_avro

        outbox_repo = AsyncMock()
        settings = MagicMock()
        settings.topic_article_enriched = "nlp.article.enriched.v1"
        doc_id = uuid.uuid4()
        subject_canonical = uuid.uuid4()
        object_canonical = uuid.uuid4()

        # Only "Oklo" is a doc-local resolved mention; "ARMEC" is the missing
        # counterparty endpoint the LLM emitted (the silent-drop case).
        oklo_mention = EntityMention(
            mention_id=uuid.uuid4(),
            doc_id=doc_id,
            section_id=uuid.uuid4(),
            mention_text="Oklo",
            mention_class="ORGANIZATION",
            char_start=0,
            char_end=4,
            confidence=0.9,
            resolved_entity_id=subject_canonical,
        )
        rd = RoutingDecision(
            decision_id=uuid.uuid4(),
            doc_id=doc_id,
            routing_tier=RoutingTier.MEDIUM,
            composite_score=0.5,
            feature_scores={},
        )
        alias_repo = _alias_repo_mock(exact={"armec": object_canonical})
        extraction = {
            "relations": [{"subject_ref": "Oklo", "object_ref": "ARMEC", "predicate": "partner_of"}],
            "events": [],
            "claims": [],
        }

        await ee._enqueue_enriched(
            outbox_repo=outbox_repo,
            settings=settings,
            doc_id=doc_id,
            source_type="eodhd",
            published_at=None,
            is_backfill=False,
            routing_decision=rd,
            sections=[],
            chunks=[],
            mentions=[oklo_mention],
            extraction_result=extraction,
            correlation_id=None,
            alias_repo=alias_repo,
            intelligence_session=None,  # M1 hits → no M2 session needed
        )

        outbox_repo.add.assert_awaited_once()
        wire_bytes = outbox_repo.add.await_args.kwargs["payload_avro"]
        schema_path = str(_SCHEMA_DIR / "nlp.article.enriched.v1.avsc")
        payload = deserialize_confluent_avro(schema_path, wire_bytes)

        # Without the wiring this would be None (relation dropped). With it, the
        # recovered relation is serialized with the real canonical endpoints.
        import json

        assert payload["raw_relations_json"] is not None
        rows = json.loads(payload["raw_relations_json"])
        assert len(rows) == 1
        assert rows[0]["subject_entity_id"] == str(subject_canonical)
        assert rows[0]["object_entity_id"] == str(object_canonical)
        assert rows[0]["entity_provisional"] is False  # M1 = real canonical
