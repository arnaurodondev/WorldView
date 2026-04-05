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

from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from uuid import UUID

    from ml_clients.protocols import EmbeddingClient, NERClient  # type: ignore[import-not-found]

    from nlp_pipeline.infrastructure.intelligence_db.repositories.canonical_entity import CanonicalEntityRepository
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
        canonical_repo: CanonicalEntityRepository,
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
        """Run the resolution cascade and return deduped, filtered results."""
        # Accumulate: {entity_id: result_with_highest_confidence}
        best: dict[str, EntityResolutionResult] = {}

        # Stage 1 — exact alias match
        exact = await self._alias_repo.batch_exact_match([normalized])
        for _text, entity_id in exact.items():
            entity_data = await self._canonical_repo.get(entity_id)
            if entity_data:
                r = EntityResolutionResult(
                    entity_id=entity_id,
                    canonical_name=str(entity_data["canonical_name"]),
                    entity_type=str(entity_data["entity_type"]),
                    confidence=_CONF_EXACT,
                    matched_text=normalized,
                    resolution_stage=1,
                    ticker=str(entity_data["ticker"]) if entity_data.get("ticker") else None,
                    isin=str(entity_data["isin"]) if entity_data.get("isin") else None,
                )
                _update_best(best, r)

        # Stage 2 — ticker / ISIN match
        tickers = _TICKER_RE.findall(normalized.upper())
        isins = _ISIN_RE.findall(normalized.upper())
        if tickers or isins:
            ticker_isin_map = await self._alias_repo.batch_ticker_isin_match(tickers, isins)
            for _key, entity_id in ticker_isin_map.items():
                entity_data = await self._canonical_repo.get(entity_id)
                if entity_data:
                    r = EntityResolutionResult(
                        entity_id=entity_id,
                        canonical_name=str(entity_data["canonical_name"]),
                        entity_type=str(entity_data["entity_type"]),
                        confidence=_CONF_TICKER_ISIN,
                        matched_text=_key,
                        resolution_stage=2,
                        ticker=str(entity_data["ticker"]) if entity_data.get("ticker") else None,
                        isin=str(entity_data["isin"]) if entity_data.get("isin") else None,
                    )
                    _update_best(best, r)

        # Stage 3 — fuzzy trigram
        fuzzy = await self._alias_repo.batch_fuzzy_trigram(
            [normalized], threshold=_FUZZY_THRESHOLD, top_k_per_mention=top_k_per_mention
        )
        for _text, matches in fuzzy.items():
            for entity_id, sim in matches:
                confidence = sim * _CONF_FUZZY_SCALE
                entity_data = await self._canonical_repo.get(entity_id)
                if entity_data:
                    r = EntityResolutionResult(
                        entity_id=entity_id,
                        canonical_name=str(entity_data["canonical_name"]),
                        entity_type=str(entity_data["entity_type"]),
                        confidence=confidence,
                        matched_text=normalized,
                        resolution_stage=3,
                        ticker=str(entity_data["ticker"]) if entity_data.get("ticker") else None,
                        isin=str(entity_data["isin"]) if entity_data.get("isin") else None,
                    )
                    _update_best(best, r)

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


def _update_best(best: dict[str, EntityResolutionResult], r: EntityResolutionResult) -> None:
    """Keep the highest-confidence result per entity_id."""
    key = str(r.entity_id)
    existing = best.get(key)
    if existing is None or r.confidence > existing.confidence:
        best[key] = r
