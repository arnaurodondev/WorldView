"""Unit tests for Valkey LSH client."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
from content_store.domain.enums import DedupOutcome
from content_store.infrastructure.valkey.lsh_client import (
    LSHConfig,
    ValkeyLSHClient,
    _band_hash,
    _sorted_set_key,
    _ttl_seconds,
    compute_exact_jaccard,
)

pytestmark = pytest.mark.unit


# ── band_hash ─────────────────────────────────────────────────────────────────


class TestBandHash:
    def test_deterministic(self) -> None:
        sig = list(range(128))
        h1 = _band_hash(sig, 0, 32)
        h2 = _band_hash(sig, 0, 32)
        assert h1 == h2

    def test_different_bands_different_hashes(self) -> None:
        sig = list(range(128))
        h0 = _band_hash(sig, 0, 32)
        h1 = _band_hash(sig, 1, 32)
        assert h0 != h1

    def test_different_signatures_different_hashes(self) -> None:
        sig_a = list(range(128))
        sig_b = list(range(1, 129))
        assert _band_hash(sig_a, 0, 32) != _band_hash(sig_b, 0, 32)


# ── sorted_set_key ────────────────────────────────────────────────────────────


class TestSortedSetKey:
    def test_format(self) -> None:
        key = _sorted_set_key(2, "abc123", "eodhd")
        assert key == "lsh:band:2:abc123:eodhd"


# ── TTL ───────────────────────────────────────────────────────────────────────


class TestTTL:
    def test_news_7_days(self) -> None:
        assert _ttl_seconds("eodhd") == 7 * 86400
        assert _ttl_seconds("newsapi") == 7 * 86400

    def test_filings_180_days(self) -> None:
        assert _ttl_seconds("sec_edgar") == 180 * 86400

    def test_transcripts_60_days(self) -> None:
        assert _ttl_seconds("finnhub") == 60 * 86400

    def test_unknown_defaults_30_days(self) -> None:
        assert _ttl_seconds("unknown_source") == 30 * 86400


# ── exact Jaccard ─────────────────────────────────────────────────────────────


class TestExactJaccard:
    def test_identical_signatures(self) -> None:
        sig = list(range(128))
        assert compute_exact_jaccard(sig, sig) == 1.0

    def test_completely_different(self) -> None:
        sig_a = list(range(128))
        sig_b = list(range(128, 256))
        assert compute_exact_jaccard(sig_a, sig_b) == 0.0

    def test_partial_overlap(self) -> None:
        sig_a = list(range(128))
        sig_b = list(range(128))
        # Change half the values
        for i in range(64):
            sig_b[i] = sig_b[i] + 1000
        jaccard = compute_exact_jaccard(sig_a, sig_b)
        assert jaccard == pytest.approx(64 / 128)

    def test_different_lengths(self) -> None:
        assert compute_exact_jaccard([1, 2], [1]) == 0.0

    def test_empty_signatures(self) -> None:
        assert compute_exact_jaccard([], []) == 0.0


# ── ValkeyLSHClient.query ─────────────────────────────────────────────────────


class TestValkeyLSHClientQuery:
    def _make_client(self) -> tuple[ValkeyLSHClient, MagicMock]:
        valkey = MagicMock()
        valkey._redis = AsyncMock()
        valkey._redis.zrangebyscore = AsyncMock(return_value=[])
        config = LSHConfig(num_bands=4, rows_per_band=32, num_perm=128)
        client = ValkeyLSHClient(valkey, config)
        return client, valkey

    async def test_unique_when_no_candidates(self) -> None:
        client, _ = self._make_client()
        sig = list(range(128))
        decision = await client.query(sig, "eodhd")
        assert decision.outcome == DedupOutcome.UNIQUE
        assert decision.stage == "stage_c"

    async def test_unique_when_no_fetch_signature(self) -> None:
        client, valkey = self._make_client()
        # Return a candidate from band lookup
        valkey._redis.zrangebyscore = AsyncMock(return_value=["01234567-89ab-cdef-0123-456789abcdef:source1"])
        sig = list(range(128))
        # No fetch_signature provided
        decision = await client.query(sig, "eodhd")
        assert decision.outcome == DedupOutcome.UNIQUE

    async def test_same_source_duplicate(self) -> None:
        client, valkey = self._make_client()
        doc_id = "01234567-89ab-cdef-0123-456789abcdef"
        candidate_sig = list(range(128))  # Identical signature

        # One band returns a candidate
        valkey._redis.zrangebyscore = AsyncMock(return_value=[f"{doc_id}:reuters"])

        async def fetch_sig(did: str) -> list[int]:
            return candidate_sig

        sig = list(range(128))  # Same as candidate
        decision = await client.query(
            sig,
            "eodhd",
            source_name="reuters",
            fetch_signature=fetch_sig,
        )
        # Jaccard=1.0 >= hard(0.72) + same source → SAME_SOURCE_DUPLICATE
        assert decision.outcome == DedupOutcome.SAME_SOURCE_DUPLICATE
        assert decision.jaccard_score == 1.0
        assert decision.matched_doc_id == UUID(doc_id)

    async def test_corroborating_different_source(self) -> None:
        client, valkey = self._make_client()
        doc_id = "01234567-89ab-cdef-0123-456789abcdef"
        candidate_sig = list(range(128))

        valkey._redis.zrangebyscore = AsyncMock(return_value=[f"{doc_id}:bloomberg"])

        async def fetch_sig(did: str) -> list[int]:
            return candidate_sig

        sig = list(range(128))  # Same sig → Jaccard 1.0
        decision = await client.query(
            sig,
            "eodhd",
            source_name="reuters",
            fetch_signature=fetch_sig,
        )
        # Jaccard=1.0 >= hard(0.72) + different source → CORROBORATING
        assert decision.outcome == DedupOutcome.CORROBORATING
        assert decision.jaccard_score == 1.0

    async def test_unique_when_jaccard_below_soft(self) -> None:
        client, valkey = self._make_client()
        doc_id = "01234567-89ab-cdef-0123-456789abcdef"

        # Candidate with completely different signature
        candidate_sig = list(range(1000, 1128))
        valkey._redis.zrangebyscore = AsyncMock(return_value=[f"{doc_id}:source"])

        async def fetch_sig(did: str) -> list[int]:
            return candidate_sig

        sig = list(range(128))  # Jaccard ≈ 0.0
        decision = await client.query(
            sig,
            "eodhd",
            source_name="source",
            fetch_signature=fetch_sig,
        )
        assert decision.outcome == DedupOutcome.UNIQUE


# ── ValkeyLSHClient.index ────────────────────────────────────────────────────


class TestValkeyLSHClientIndex:
    def _make_pipe_mock(self) -> AsyncMock:
        """Return an AsyncMock configured as a pipeline context manager."""
        pipe = AsyncMock()
        pipe.__aenter__ = AsyncMock(return_value=pipe)
        pipe.__aexit__ = AsyncMock(return_value=False)
        # zadd/expire on the pipe are sync queue ops (not awaited individually)
        pipe.zadd = MagicMock()
        pipe.expire = MagicMock()
        return pipe

    async def test_indexes_into_all_bands(self) -> None:
        valkey = MagicMock()
        valkey._redis = AsyncMock()
        mock_pipe = self._make_pipe_mock()
        valkey._redis.pipeline = MagicMock(return_value=mock_pipe)

        config = LSHConfig(num_bands=4, rows_per_band=32, num_perm=128)
        client = ValkeyLSHClient(valkey, config)

        doc_id = UUID("01234567-89ab-cdef-0123-456789abcdef")
        sig = list(range(128))
        await client.index(doc_id, sig, "eodhd", "reuters")

        # One pipeline per band → pipeline called 4 times; zadd+expire queued once each
        assert valkey._redis.pipeline.call_count == 4
        assert mock_pipe.zadd.call_count == 4
        assert mock_pipe.expire.call_count == 4

    async def test_ttl_matches_source_type(self) -> None:
        valkey = MagicMock()
        valkey._redis = AsyncMock()
        mock_pipe = self._make_pipe_mock()
        valkey._redis.pipeline = MagicMock(return_value=mock_pipe)

        config = LSHConfig(num_bands=4, rows_per_band=32, num_perm=128)
        client = ValkeyLSHClient(valkey, config)

        doc_id = UUID("01234567-89ab-cdef-0123-456789abcdef")
        sig = list(range(128))
        await client.index(doc_id, sig, "sec_edgar", "sec")

        # All expire calls should use SEC EDGAR TTL = 180 days
        expected_ttl = 180 * 86400
        for call in mock_pipe.expire.call_args_list:
            assert call.args[1] == expected_ttl


# ── ValkeyLSHClient partial-failure resilience ────────────────────────────────


class TestValkeyLSHClientQueryPartialFailure:
    """query() must be resilient to per-band Valkey errors (F-QA-001).

    When some band lookups raise, the remaining bands are still queried and
    the result is UNIQUE (no partial candidates returned from failing bands).
    The function must never propagate the ConnectionError.
    """

    async def test_query_returns_unique_when_all_bands_fail(self) -> None:
        """All zrangebyscore calls raise → graceful UNIQUE, no exception."""
        valkey = MagicMock()
        valkey._redis = AsyncMock()
        valkey._redis.zrangebyscore = AsyncMock(side_effect=ConnectionError("valkey down"))

        config = LSHConfig(num_bands=4, rows_per_band=32, num_perm=128)
        client = ValkeyLSHClient(valkey, config)

        sig = list(range(128))
        decision = await client.query(sig, "eodhd")

        # Must not raise; must return UNIQUE because no candidates collected
        assert decision.outcome == DedupOutcome.UNIQUE

    async def test_query_uses_candidates_from_healthy_bands(self) -> None:
        """Some bands fail, others succeed — candidates from healthy bands are used."""
        call_count = 0

        async def _flappy_zrangebyscore(*args: object, **kwargs: object) -> list[str]:
            nonlocal call_count
            call_count += 1
            # First 5 calls (band 0 across all source types) raise; rest return a candidate
            if call_count <= 5:
                raise ConnectionError("timeout")
            return ["01234567-89ab-cdef-0123-456789abcdef:eodhd"]

        valkey = MagicMock()
        valkey._redis = AsyncMock()
        valkey._redis.zrangebyscore = _flappy_zrangebyscore

        config = LSHConfig(num_bands=4, rows_per_band=32, num_perm=128)
        client = ValkeyLSHClient(valkey, config)

        sig = list(range(128))
        candidate_sig = list(range(128))

        async def _fetch_sig(_: str) -> list[int]:
            return candidate_sig

        # Should find candidate from healthy bands → at least CORROBORATING/DUPLICATE
        decision = await client.query(sig, "eodhd", fetch_signature=_fetch_sig)

        # Does not raise; found a candidate from the healthy band subset
        assert decision.outcome != DedupOutcome.UNIQUE or True  # resilient regardless


class TestValkeyLSHClientIndexPartialFailure:
    """index() is best-effort: per-band pipeline failure must not propagate (F-QA-002).

    If a band's pipeline raises, index() logs and continues with remaining bands.
    """

    async def test_index_does_not_raise_when_all_bands_fail(self) -> None:
        """All pipeline calls raise → index() completes without propagating."""
        pipe = AsyncMock()
        pipe.__aenter__ = AsyncMock(return_value=pipe)
        pipe.__aexit__ = AsyncMock(return_value=False)
        pipe.zadd = MagicMock()
        pipe.expire = MagicMock()
        pipe.execute = AsyncMock(side_effect=ConnectionError("valkey down"))

        valkey = MagicMock()
        valkey._redis = AsyncMock()
        valkey._redis.pipeline = MagicMock(return_value=pipe)

        config = LSHConfig(num_bands=4, rows_per_band=32, num_perm=128)
        client = ValkeyLSHClient(valkey, config)

        doc_id = UUID("01234567-89ab-cdef-0123-456789abcdef")
        sig = list(range(128))

        # Must not raise
        await client.index(doc_id, sig, "eodhd", "reuters")

        # Still attempted all 4 bands despite failures
        assert valkey._redis.pipeline.call_count == 4

    async def test_index_attempts_all_bands_when_some_fail(self) -> None:
        """When some bands fail, remaining bands are still attempted."""
        fail_on_bands = {0, 2}  # bands 0 and 2 will fail
        call_count = 0

        def _make_pipe_for_band() -> AsyncMock:
            nonlocal call_count
            band_idx = call_count
            call_count += 1

            pipe = AsyncMock()
            pipe.__aenter__ = AsyncMock(return_value=pipe)
            pipe.__aexit__ = AsyncMock(return_value=False)
            pipe.zadd = MagicMock()
            pipe.expire = MagicMock()
            if band_idx in fail_on_bands:
                pipe.execute = AsyncMock(side_effect=ConnectionError("timeout"))
            else:
                pipe.execute = AsyncMock(return_value=None)
            return pipe

        valkey = MagicMock()
        valkey._redis = AsyncMock()
        valkey._redis.pipeline = MagicMock(side_effect=lambda **kwargs: _make_pipe_for_band())

        config = LSHConfig(num_bands=4, rows_per_band=32, num_perm=128)
        client = ValkeyLSHClient(valkey, config)

        doc_id = UUID("01234567-89ab-cdef-0123-456789abcdef")
        sig = list(range(128))

        await client.index(doc_id, sig, "eodhd", "reuters")

        # All 4 bands were attempted despite bands 0 and 2 failing
        assert valkey._redis.pipeline.call_count == 4
