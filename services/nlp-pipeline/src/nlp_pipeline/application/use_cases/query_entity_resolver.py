"""Query-time entity resolution use case (PLAN-0015-B Wave B-2).

Resolves entity mentions from a short query text using a 5-stage cascade:
  1. Exact alias match         (confidence 1.00)
  2. Ticker/ISIN match         (confidence 0.95)
  3. Fuzzy trigram similarity  (confidence = sim * 0.90)
  4. GLiNER NER mention pass   (if ner_client provided)
  5. ANN HNSW embedding        (if embedding_client provided, clear_margin > 0.10)

Results are cached in Valkey: ``s6:v1:resolve:{sha256(normalised_text)}`` TTL=600s.
Caller passes ``min_confidence`` to filter low-quality matches.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import re
import unicodedata
from typing import TYPE_CHECKING, Any
from uuid import UUID

from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from ml_clients.protocols import EmbeddingClient, NERClient  # type: ignore[import-not-found]

    from nlp_pipeline.application.ports.canonical_entity import CanonicalEntityPort
    from nlp_pipeline.infrastructure.intelligence_db.repositories.entity_alias import EntityAliasRepository
    from nlp_pipeline.infrastructure.intelligence_db.repositories.entity_profile_embedding import (
        EntityProfileEmbeddingRepository,
    )

_log = get_logger(__name__)  # type: ignore[no-any-return]

# Confidence constants (aligned with Block 9)
_CONF_EXACT: float = 1.00
_CONF_TICKER_ISIN: float = 0.95
_CONF_FUZZY_SCALE: float = 0.90  # confidence = sim * 0.90
_FUZZY_THRESHOLD: float = 0.70
_ANN_CLEAR_MARGIN: float = 0.10

# Ticker pattern — 1-5 uppercase letters (US equity pattern)
_TICKER_RE = re.compile(r"\b([A-Z]{1,5})\b")
# ISIN pattern — 2 letter country code + 10 alphanumeric
_ISIN_RE = re.compile(r"\b([A-Z]{2}[A-Z0-9]{10})\b")

_VALKEY_TTL_SECONDS = 600


@dataclasses.dataclass(frozen=True)
class EntityResolutionResult:
    """A single resolved entity from query text (PLAN-0015-B T-B-2-01)."""

    entity_id: UUID
    canonical_name: str
    entity_type: str
    confidence: float
    matched_text: str
    resolution_stage: int  # 1=exact alias, 2=ticker/ISIN, 3=fuzzy, 4=GLiNER, 5=ANN
    ticker: str | None = None
    isin: str | None = None


def _normalize(text: str) -> str:
    """Lowercase + strip punctuation + collapse whitespace."""
    text = unicodedata.normalize("NFKD", text).lower()
    text = re.sub(r"[^\w\s]", " ", text)
    return " ".join(text.split())


# Stop-words that are never entity mentions on their own.
# WHY: when we tokenise a free-text query ("What is the relation between Apple
# and Anthropic?") into candidate mentions, single stop-words like "what",
# "the", "between" would be sent to every cascade stage and waste DB round-trips
# while never matching.  Filtering them out before the batch call keeps the
# query list lean.  The set is intentionally small — we only exclude the most
# common English function words; domain nouns are kept even if short.
_STOP_WORDS: frozenset[str] = frozenset(
    {
        "a",
        "an",
        "the",
        "and",
        "or",
        "but",
        "of",
        "in",
        "on",
        "at",
        "to",
        "for",
        "with",
        "is",
        "it",
        "its",
        "this",
        "that",
        "are",
        "was",
        "were",
        "be",
        "been",
        "by",
        "from",
        "as",
        "into",
        "through",
        "what",
        "which",
        "who",
        "whom",
        "how",
        "when",
        "where",
        "why",
        "have",
        "has",
        "had",
        "do",
        "does",
        "did",
        "will",
        "would",
        "could",
        "should",
        "may",
        "might",
        "can",
        "not",
        "no",
        "so",
        "if",
        "then",
        "than",
        "more",
        "most",
        "between",
        "about",
        "after",
        "before",
        "during",
        "up",
        "down",
        "out",
        "off",
        "over",
        "under",
        "again",
        "further",
        "while",
        "there",
        "these",
        "those",
        "each",
        "both",
        "few",
        "other",
        "such",
        "only",
        "own",
        "same",
        "too",
        "very",
        "relation",
        "relationship",
        "connect",
        "connection",
        "link",
    }
)


def _candidate_mentions(normalized: str) -> list[str]:
    """Extract candidate entity mentions from a normalised query string.

    Strategy (cheapest to most expensive):
      1. The full normalised string — works for short queries like "Apple" or "AAPL".
      2. Individual capitalisable tokens (≥ 2 chars) not in the stop-word list.
      3. 2-gram and 3-gram windows of the non-stop tokens — catches "Apple Inc"
         and "Alphabet Inc Class A" style compound names.

    All candidates are de-duplicated (preserving order) before being returned.
    The full string is always first so exact full-query matches win in Stage 1.

    WHY deduplicate: the same token can appear in multiple windows; sending it
    twice to batch_exact_match is harmless but wastes a DB parameter slot.
    """
    seen: dict[str, None] = {}  # ordered set via dict

    def _add(s: str) -> None:
        s = s.strip()
        if s and s not in seen:
            seen[s] = None

    _add(normalized)

    tokens = [t for t in normalized.split() if len(t) >= 2 and t not in _STOP_WORDS]

    # 1-gram
    for t in tokens:
        _add(t)

    # 2-gram windows
    for i in range(len(tokens) - 1):
        _add(f"{tokens[i]} {tokens[i + 1]}")

    # 3-gram windows
    for i in range(len(tokens) - 2):
        _add(f"{tokens[i]} {tokens[i + 1]} {tokens[i + 2]}")

    return list(seen)


def _cache_key(normalized_text: str) -> str:
    digest = hashlib.sha256(normalized_text.encode()).hexdigest()[:16]
    return f"s6:v1:resolve:{digest}"


class QueryEntityResolverUseCase:
    """Resolve entity mentions in a short query text for S8 RAG retrieval.

    Designed for sub-200-char queries (search terms, entity names).  Stages 4
    and 5 require ML clients and are skipped when those are not available (API
    process has no ML clients; only the consumer process does).
    """

    def __init__(
        self,
        alias_repo: EntityAliasRepository,
        canonical_repo: CanonicalEntityPort,
        valkey: Any,  # redis.asyncio.Redis
        ner_client: NERClient | None = None,
        embedding_client: EmbeddingClient | None = None,
        embedding_repo: EntityProfileEmbeddingRepository | None = None,
    ) -> None:
        self._alias_repo = alias_repo
        self._canonical_repo = canonical_repo
        self._valkey = valkey
        self._ner = ner_client
        self._emb = embedding_client
        self._emb_repo = embedding_repo

    async def execute(
        self,
        query_text: str,
        top_k_per_mention: int = 3,
        min_confidence: float = 0.45,
    ) -> tuple[list[EntityResolutionResult], str]:
        """Resolve entities from *query_text*.

        Returns ``(results, normalized_text)`` — the normalised form is included
        in the API response so callers can confirm how the input was interpreted.
        """
        normalized = _normalize(query_text)

        # ── Cache check ───────────────────────────────────────────────────────
        cache_key = _cache_key(normalized)
        if self._valkey is not None:
            try:
                cached = await self._valkey.get(cache_key)
                if cached:
                    raw: list[dict[str, Any]] = json.loads(cached)
                    results = [
                        EntityResolutionResult(
                            entity_id=__import__("uuid").UUID(r["entity_id"]),
                            canonical_name=r["canonical_name"],
                            entity_type=r["entity_type"],
                            confidence=r["confidence"],
                            matched_text=r["matched_text"],
                            resolution_stage=r["resolution_stage"],
                            ticker=r.get("ticker"),
                            isin=r.get("isin"),
                        )
                        for r in raw
                    ]
                    return results, normalized
            except Exception:
                _log.warning("resolver_cache_read_failed", cache_key=cache_key, exc_info=True)  # type: ignore[no-any-return]

        results = await self._run_cascade(normalized, top_k_per_mention, min_confidence)

        # ── Cache write ───────────────────────────────────────────────────────
        if self._valkey is not None:
            try:
                payload = [
                    {
                        "entity_id": str(r.entity_id),
                        "canonical_name": r.canonical_name,
                        "entity_type": r.entity_type,
                        "confidence": r.confidence,
                        "matched_text": r.matched_text,
                        "resolution_stage": r.resolution_stage,
                        "ticker": r.ticker,
                        "isin": r.isin,
                    }
                    for r in results
                ]
                await self._valkey.set(cache_key, json.dumps(payload), ex=_VALKEY_TTL_SECONDS)
            except Exception:
                _log.warning("resolver_cache_write_failed", cache_key=cache_key, exc_info=True)  # type: ignore[no-any-return]

        return results, normalized

    async def _run_cascade(
        self,
        normalized: str,
        top_k_per_mention: int,
        min_confidence: float,
    ) -> list[EntityResolutionResult]:
        """Run the resolution cascade and return deduped, filtered results.

        Uses _candidate_mentions() to tokenise the query into 1/2/3-gram windows
        before stages 1 and 3.  This lets "What is the relation between Apple and
        Anthropic?" resolve both "apple" (→ Apple Inc.) and "anthropic" instead of
        failing because the full sentence has no alias entry.
        """
        # Accumulate: {entity_id: result_with_highest_confidence}
        best: dict[str, EntityResolutionResult] = {}

        # Build the candidate mention list: full query + 1/2/3-gram windows.
        # Stage 2 (ticker) still uses the full string because _TICKER_RE scans
        # all-caps tokens across the entire query rather than per-window.
        candidates = _candidate_mentions(normalized)

        # ── Stages 1-3: collect candidate matches, defer canonical fetch ──────
        # PERF (2026-06-18, RC-3 follow-up): the previous form did one
        # ``canonical_repo.get(entity_id)`` round-trip *per match* inside each
        # stage loop (an N+1 against canonical_entities).  For a typical chat
        # query the 1/2/3-gram windows yield several Stage-1 + Stage-3 matches,
        # so this was 5-15 sequential DB round-trips on the chat hot path
        # (the ~7.4s entity_resolution phase).  We now collect lightweight
        # ``_PendingMatch`` descriptors from all three batched alias stages,
        # fetch every referenced canonical in ONE ``batch_get`` call, then
        # replay ``_update_best`` in the original stage/iteration order so the
        # highest-confidence-per-entity dedup result is byte-for-byte identical.
        pending: list[_PendingMatch] = []

        # Stage 1 — exact alias match (batch: one query for all candidates)
        exact = await self._alias_repo.batch_exact_match(candidates)
        for _text, entity_id in exact.items():
            pending.append(_PendingMatch(entity_id, _CONF_EXACT, _text, 1))

        # Stage 2 — ticker / ISIN match (scans the full normalised text)
        tickers = _TICKER_RE.findall(normalized.upper())
        isins = _ISIN_RE.findall(normalized.upper())
        if tickers or isins:
            ticker_isin_map = await self._alias_repo.batch_ticker_isin_match(tickers, isins)
            for _key, entity_id in ticker_isin_map.items():
                pending.append(_PendingMatch(entity_id, _CONF_TICKER_ISIN, _key, 2))

        # Stage 3 — fuzzy trigram (batch across all candidate windows)
        # WHY pass all candidates: "apple inc" has higher trigram sim against the
        # alias "apple inc." than the bare token "apple" does; running all windows
        # at once via a single LATERAL query is as cheap as running one.
        fuzzy = await self._alias_repo.batch_fuzzy_trigram(
            candidates, threshold=_FUZZY_THRESHOLD, top_k_per_mention=top_k_per_mention
        )
        for _text, matches in fuzzy.items():
            for entity_id, sim in matches:
                pending.append(_PendingMatch(entity_id, sim * _CONF_FUZZY_SCALE, _text, 3))

        # Single batched canonical fetch for every entity referenced above.
        # Missing IDs are simply absent from the dict (same as a ``get`` miss,
        # which the old per-match loop skipped via ``if entity_data``).
        if pending:
            entity_data_by_id = await self._canonical_repo.batch_get([p.entity_id for p in pending])
            for p in pending:
                entity_data = entity_data_by_id.get(p.entity_id)
                if entity_data:
                    _update_best(best, _result_from(p.entity_id, entity_data, p.confidence, p.matched_text, p.stage))

        # Stage 4 — GLiNER NER (optional — API process has no ML clients)
        if self._ner is not None:
            await self._run_ner_stage(normalized, best, top_k_per_mention)

        # Stage 5 — ANN HNSW embedding fallback (optional)
        if self._emb is not None and self._emb_repo is not None:
            await self._run_ann_stage(normalized, best)

        # Filter by min_confidence and return sorted by confidence desc
        return sorted(
            (r for r in best.values() if r.confidence >= min_confidence),
            key=lambda r: r.confidence,
            reverse=True,
        )

    async def _run_ner_stage(
        self,
        normalized: str,
        best: dict[str, EntityResolutionResult],
        top_k_per_mention: int,
    ) -> None:
        """Stage 4 — run NER on query text, then resolve each mention via stages 1-3."""
        assert self._ner is not None
        try:
            ner_results = await self._ner.batch_extract_entities([normalized])  # type: ignore[attr-defined, list-item]
            for batch_result in ner_results:
                for mention in batch_result:  # type: ignore[attr-defined]
                    mention_text = _normalize(str(mention.get("text", "")))
                    if not mention_text:
                        continue
                    # Re-run stages 1-3 on the extracted mention text
                    sub_exact = await self._alias_repo.batch_exact_match([mention_text])
                    for _t, entity_id in sub_exact.items():
                        entity_data = await self._canonical_repo.get(entity_id)
                        if entity_data:
                            r = EntityResolutionResult(
                                entity_id=entity_id,
                                canonical_name=str(entity_data["canonical_name"]),
                                entity_type=str(entity_data["entity_type"]),
                                confidence=_CONF_EXACT,
                                matched_text=mention_text,
                                resolution_stage=4,
                                ticker=str(entity_data["ticker"]) if entity_data.get("ticker") else None,
                                isin=str(entity_data["isin"]) if entity_data.get("isin") else None,
                            )
                            _update_best(best, r)
        except Exception:
            _log.warning("resolver_ner_stage_failed", exc_info=True)  # type: ignore[no-any-return]

    async def _run_ann_stage(
        self,
        normalized: str,
        best: dict[str, EntityResolutionResult],
    ) -> None:
        """Stage 5 — ANN HNSW embedding fallback (only if clear_margin > 0.10)."""
        assert self._emb is not None
        assert self._emb_repo is not None
        try:
            vec = await self._emb.embed(normalized)  # type: ignore[attr-defined, arg-type]
            candidates = await self._emb_repo.find_nearest(vec, top_k=3)  # type: ignore[attr-defined]
            if not candidates:
                return
            # Require clear margin between 1st and 2nd candidate
            if len(candidates) >= 2:
                margin = candidates[0][1] - candidates[1][1]
                if margin <= _ANN_CLEAR_MARGIN:
                    return
            entity_id, distance = candidates[0]
            confidence = (1.0 - distance) * 0.80
            entity_data = await self._canonical_repo.get(entity_id)
            if entity_data:
                r = EntityResolutionResult(
                    entity_id=entity_id,
                    canonical_name=str(entity_data["canonical_name"]),
                    entity_type=str(entity_data["entity_type"]),
                    confidence=confidence,
                    matched_text=normalized,
                    resolution_stage=5,
                    ticker=str(entity_data["ticker"]) if entity_data.get("ticker") else None,
                    isin=str(entity_data["isin"]) if entity_data.get("isin") else None,
                )
                _update_best(best, r)
        except Exception:
            _log.warning("resolver_ann_stage_failed", exc_info=True)  # type: ignore[no-any-return]


@dataclasses.dataclass(frozen=True)
class _PendingMatch:
    """A stage 1-3 alias hit awaiting its batched canonical-entity fetch.

    Lets ``_run_cascade`` collect every match from the (already-batched) alias
    stages and resolve all their ``canonical_entities`` rows in a single
    ``batch_get`` instead of one ``get`` per match (RC-3 follow-up: removes the
    canonical-lookup N+1 on the chat hot path).
    """

    entity_id: UUID
    confidence: float
    matched_text: str
    stage: int


def _result_from(
    entity_id: UUID,
    entity_data: dict[str, Any],
    confidence: float,
    matched_text: str,
    stage: int,
) -> EntityResolutionResult:
    """Build an :class:`EntityResolutionResult` from a fetched canonical row.

    Shared by stages 1-3 so the field mapping (ticker/isin null-coalescing,
    str-casting) stays identical regardless of which stage produced the hit.
    """
    return EntityResolutionResult(
        entity_id=entity_id,
        canonical_name=str(entity_data["canonical_name"]),
        entity_type=str(entity_data["entity_type"]),
        confidence=confidence,
        matched_text=matched_text,
        resolution_stage=stage,
        ticker=str(entity_data["ticker"]) if entity_data.get("ticker") else None,
        isin=str(entity_data["isin"]) if entity_data.get("isin") else None,
    )


def _update_best(best: dict[str, EntityResolutionResult], r: EntityResolutionResult) -> None:
    """Keep the highest-confidence result per entity_id."""
    key = str(r.entity_id)
    existing = best.get(key)
    if existing is None or r.confidence > existing.confidence:
        best[key] = r
