"""Worker 13D-3: Fundamentals+OHLCV state embedding refresh (PRD §6.7 Block 13D-3).

30-day schedule.  Only processes ticker entities.

Source text: calls S3 (market-data service) REST API:
  GET /api/v1/fundamentals/{id}
  GET /api/v1/ohlcv/{id}?timeframe=monthly&limit=12
  GET /api/v1/ohlcv/{id}?timeframe=weekly&limit=12

Builds narrative via ``build_fundamentals_narrative()`` (deterministic, no LLM).
S3 down → skip entity (retry next cycle — next_refresh_at not updated).

Wave C-4 additions:
  GET /api/v1/fundamentals/{id}/earnings  → insert earnings events (idempotent)
  GET /api/v1/fundamentals/{id}/company-profile → upsert is_in_sector / is_in_industry
"""

from __future__ import annotations

import asyncio
import json
import time
from datetime import timedelta
from typing import TYPE_CHECKING, Any
from uuid import UUID

import jwt

from common.ids import new_uuid7  # type: ignore[import-untyped]
from common.time import utc_now  # type: ignore[import-untyped]
from knowledge_graph.application.utils.fundamentals_narrative import build_fundamentals_narrative
from knowledge_graph.infrastructure.intelligence_db.repositories.entity_embedding_state import (
    VIEW_FUNDAMENTALS,
    sha256_hex,
)
from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    import httpx
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from knowledge_graph.infrastructure.intelligence_db.repositories.canonical_entity import (
        CanonicalEntityRepository,
    )
    from knowledge_graph.infrastructure.intelligence_db.repositories.relation import RelationRepository
    from knowledge_graph.infrastructure.intelligence_db.repositories.relation_evidence import (
        RelationEvidenceRepository,
    )
    from knowledge_graph.infrastructure.llm.fallback_chain import FallbackChainClient

logger = get_logger(__name__)  # type: ignore[no-any-return]

_REFRESH_INTERVAL_DAYS = 30
_DEFAULT_EMBED_MODEL_ID = "nomic-embed-text"

# Maximum texts to send in a single embed() call.  DeepInfra and most providers
# accept batches of several hundred inputs; 200 is a conservative safe ceiling.
_EMBED_CHUNK_SIZE = 200

# Relation type constants (from relation_type_registry seed in migration 0002)
_IS_IN_SECTOR_TYPE = "is_in_sector"
_IS_IN_INDUSTRY_TYPE = "is_in_industry"
_EARNINGS_EVENT_TYPE = "earnings_release"

# Sector/industry relation metadata (hardcoded from decay_class_config + registry seeds)
# is_in_sector: RELATION_STATE / PERMANENT / alpha=0.0 / base_confidence=0.90
_SECTOR_SEMANTIC_MODE = "RELATION_STATE"
_SECTOR_DECAY_CLASS = "PERMANENT"
_SECTOR_DECAY_ALPHA = 0.000000
_SECTOR_BASE_CONFIDENCE = 0.90
# is_in_industry: RELATION_STATE / DURABLE / alpha=0.000950 / base_confidence=0.85
_INDUSTRY_DECAY_CLASS = "DURABLE"
_INDUSTRY_DECAY_ALPHA = 0.000950
_INDUSTRY_BASE_CONFIDENCE = 0.85

# Signing key for dev: market-data has MARKET_DATA_INTERNAL_JWT_SKIP_VERIFICATION=true
# so any HS256 JWT with a decodable header is accepted in local dev.
# F-015: this is only used as a fallback when no RS256 private key is configured.
_INTERNAL_JWT_DEV_KEY = "dev-skip-verification-key-for-kg-fundamentals"


def _system_jwt_headers(private_key_pem: str = "") -> dict[str, str]:
    """Generate X-Internal-JWT for service-to-service calls to market-data.

    F-015: when ``private_key_pem`` is provided (non-empty), issues an RS256 JWT
    signed with the same key as S9 api-gateway so market-data (and other backends)
    can verify it via the gateway JWKS.  Falls back to the HS256 dev token when
    the key is absent — market-data must have skip_verification=True for this to
    work (acceptable in dev/test; guarded by a production check in market-data config).
    """
    now = int(time.time())
    payload = {
        "iss": "worldview-gateway",
        "sub": "system:kg-fundamentals-refresh",
        "user_id": "00000000-0000-0000-0000-000000000000",
        "tenant_id": "00000000-0000-0000-0000-000000000000",
        "role": "system",
        "iat": now,
        # WHY 1-hour TTL (not 24h HS256 dev token): RS256 tokens are more
        # expensive to issue but cryptographically verifiable, so a shorter TTL
        # is safer. The worker runs every 2h and creates a new client each run.
        "exp": now + 3600,
    }
    if private_key_pem:
        from cryptography.hazmat.primitives.serialization import load_pem_private_key

        private_key = load_pem_private_key(private_key_pem.encode(), password=None)
        token = jwt.encode(payload, private_key, algorithm="RS256")  # type: ignore[arg-type]
    else:
        # Fallback: HS256 dev token — only accepted when skip_verification=True
        token = jwt.encode(payload, _INTERNAL_JWT_DEV_KEY, algorithm="HS256")
    return {"X-Internal-JWT": token}


class FundamentalsRefreshWorker:
    """Refreshes fundamentals+OHLCV embeddings for ticker entities (Worker 13D-3).

    Wave C-4 extensions:
    - Inserts earnings events from S3 /fundamentals/{id}/earnings (idempotent).
    - Upserts is_in_sector / is_in_industry relations from company-profile data.

    Args:
    ----
        session_factory: Read/write sessionmaker for intelligence_db.
        llm_client:      FallbackChainClient (embedding path).
        market_data_base_url: Base URL for market-data service REST API.
        http_client:     Optional httpx.AsyncClient (injected for testing).

    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        llm_client: FallbackChainClient,
        market_data_base_url: str,
        http_client: httpx.AsyncClient | None = None,
        embedding_model_id: str = _DEFAULT_EMBED_MODEL_ID,
        concurrency: int = 5,
        internal_jwt_private_key_pem: str = "",
        read_session_factory: Any = None,
    ) -> None:
        self._sf = session_factory
        # DEF-034 (Wave B-5): Phase 1 due-entity SELECT runs on the read
        # replica.  Phase 3 (earnings + sector relations + embedding upsert)
        # stays on the write factory.
        self._read_session_factory: Any = read_session_factory if read_session_factory is not None else session_factory
        self._llm = llm_client
        self._market_data_url = market_data_base_url.rstrip("/")
        self._http = http_client
        self._embed_model_id = embedding_model_id
        self._concurrency = concurrency
        # F-015: store the RS256 private key PEM (may be empty for HS256 dev fallback)
        self._internal_jwt_private_key_pem = internal_jwt_private_key_pem

    async def run(self) -> None:
        """Refresh fundamentals embeddings due for refresh.

        ARCH-004 fix: read→release→I/O→acquire→write pattern.
        Session is NOT held open during external HTTP calls to market-data
        service or embedding model.

        Per entity (ticker only):
          1. Insert any new earnings events from S3 (idempotent).
          2. Upsert is_in_sector / is_in_industry relations from company profile.
          3. Rebuild fundamentals embedding (existing behaviour — skips on S3 error).
        """
        import httpx as _httpx

        from knowledge_graph.infrastructure.intelligence_db.repositories.entity_embedding_state import (
            EntityEmbeddingStateRepository,
        )

        own_http = self._http is None
        # F-015: pass private key PEM so RS256 JWT is issued when available.
        http = self._http or _httpx.AsyncClient(
            timeout=15.0,
            headers=_system_jwt_headers(self._internal_jwt_private_key_pem),
        )

        refreshed = 0
        skipped = 0
        earnings_inserted = 0
        relations_upserted = 0

        try:
            # ── Phase 1: Read due entities, then release the session ──
            # DEF-034 (Wave B-5): Phase 1 fetch uses the read replica when
            # configured. Phase 3 writes still go through ``self._sf``.
            due_entities: list[dict[str, Any]] = []
            async with self._read_session_factory() as session:
                emb_repo = EntityEmbeddingStateRepository(session)
                # 0 = unlimited (drain full queue); see EntityEmbeddingStateRepository.get_due_for_refresh
                due = await emb_repo.get_due_for_refresh(VIEW_FUNDAMENTALS, 0)
                for row in due:
                    ticker: str | None = row.get("ticker")  # type: ignore[assignment]
                    if not ticker:
                        skipped += 1
                        continue
                    # Materialise the row data we need for Phase 2 HTTP calls
                    due_entities.append(
                        {
                            "entity_id": row["entity_id"],
                            "ticker": ticker,
                            "canonical_name": str(row.get("canonical_name", ticker)),
                            "entity_type": str(row.get("entity_type", "financial_instrument")),
                            "row": dict(row),  # snapshot for _build_fundamentals_narrative
                        },
                    )
            # Session released — no DB connection held during HTTP calls.

            # ── Phase 2: All HTTP calls (no session held, concurrent per entity) ──
            # Entities are processed concurrently up to self._concurrency via a
            # semaphore.  Embed calls are batched AFTER all HTTP fetches complete.
            from ml_clients.dataclasses import EmbeddingInput  # type: ignore[import-untyped]

            semaphore = asyncio.Semaphore(self._concurrency)

            async def _process_entity_io(ent: dict[str, Any]) -> dict[str, Any]:
                """Fetch all HTTP data for one entity; returns result dict (no embed yet)."""
                async with semaphore:
                    _entity_id: UUID = ent["entity_id"]
                    _ticker_str: str = str(ent["ticker"])

                    # Resolve ticker → market-data instrument_id
                    _instrument_id = await self._resolve_instrument_id(http, _ticker_str)
                    if _instrument_id is None:
                        logger.debug(  # type: ignore[no-any-return]
                            "fundamentals_refresh_instrument_not_found",
                            entity_id=str(_entity_id),
                            ticker=_ticker_str,
                        )
                        return {
                            "entity_id": _entity_id,
                            "ticker": _ticker_str,
                            "canonical_name": ent["canonical_name"],
                            "earnings_data": None,
                            "profile_data": None,
                            "narrative": None,
                        }

                    # Fetch earnings, profile, and fundamentals narrative in parallel.
                    _earnings_data, _profile_data, _narrative = await asyncio.gather(
                        self._fetch_earnings_data(http, _instrument_id, _ticker_str),
                        self._fetch_company_profile_data(http, _instrument_id),
                        self._build_fundamentals_narrative(_entity_id, _ticker_str, ent["row"], http, _instrument_id),
                    )

                    return {
                        "entity_id": _entity_id,
                        "ticker": _ticker_str,
                        "canonical_name": ent["canonical_name"],
                        "earnings_data": _earnings_data,
                        "profile_data": _profile_data,
                        "narrative": _narrative,
                    }

            # Run all entity HTTP fetches concurrently.
            raw_results: list[dict[str, Any]] = list(
                await asyncio.gather(*[_process_entity_io(e) for e in due_entities]),
            )

            # ── Batch embed after all HTTP fetches ──
            # Collect narratives that need an embedding, then call embed() ONCE.
            narratives_to_embed: list[tuple[int, str]] = []  # (raw_results index, narrative)
            for idx, res in enumerate(raw_results):
                if res["narrative"] is not None:
                    narratives_to_embed.append((idx, res["narrative"]))

            # Map embed outputs back to raw_results by index.
            embed_map: dict[int, list[float] | None] = {}
            if narratives_to_embed:
                inputs_all = [
                    EmbeddingInput(text=text, model_id=self._embed_model_id) for _, text in narratives_to_embed
                ]
                embed_outputs: list[list[float] | None] = []
                for chunk_start in range(0, len(inputs_all), _EMBED_CHUNK_SIZE):
                    chunk_inputs = inputs_all[chunk_start : chunk_start + _EMBED_CHUNK_SIZE]
                    outputs = await self._llm.embed(chunk_inputs)
                    for i in range(len(chunk_inputs)):
                        if outputs and i < len(outputs):
                            embed_outputs.append(outputs[i].embedding)
                        else:
                            embed_outputs.append(None)
                for (idx, _narrative), embedding in zip(narratives_to_embed, embed_outputs, strict=False):
                    embed_map[idx] = embedding

            # Build final entity_io_results with embedding + source_hash attached.
            entity_io_results: list[dict[str, Any]] = []
            for idx, res in enumerate(raw_results):
                narrative = res["narrative"]
                embedding_out: list[float] | None = None
                source_hash: str | None = None
                if narrative is not None:
                    source_hash = sha256_hex(narrative)
                    embedding_out = embed_map.get(idx)

                entity_io_results.append(
                    {
                        "entity_id": res["entity_id"],
                        "ticker": res["ticker"],
                        "canonical_name": res["canonical_name"],
                        "earnings_data": res["earnings_data"],
                        "profile_data": res["profile_data"],
                        "narrative": narrative,
                        "embedding": embedding_out,
                        "source_hash": source_hash,
                    },
                )

            # ── Phase 3: Write all results in a new session ──
            from knowledge_graph.infrastructure.intelligence_db.repositories.canonical_entity import (
                CanonicalEntityRepository,
            )
            from knowledge_graph.infrastructure.intelligence_db.repositories.relation import RelationRepository
            from knowledge_graph.infrastructure.intelligence_db.repositories.relation_evidence import (
                RelationEvidenceRepository,
            )

            async with self._sf() as session:
                emb_repo = EntityEmbeddingStateRepository(session)
                relation_repo = RelationRepository(session)
                evidence_repo = RelationEvidenceRepository(session)
                entity_repo = CanonicalEntityRepository(session)

                for result in entity_io_results:
                    entity_id = result["entity_id"]

                    # --- Write earnings events (idempotent) ---
                    if result["earnings_data"] is not None:
                        count = await self._write_earnings_events(
                            session,
                            entity_id,
                            entity_id,
                            result["canonical_name"],
                            result["earnings_data"],
                        )
                        earnings_inserted += count

                    # --- Write sector/industry relations ---
                    if result["profile_data"] is not None:
                        count = await self._write_sector_relations(
                            entity_id,
                            entity_id,
                            result["profile_data"],
                            relation_repo,
                            evidence_repo,
                            entity_repo,
                        )
                        relations_upserted += count

                    # --- Write embedding ---
                    if result["narrative"] is None:
                        logger.warning(  # type: ignore[no-any-return]
                            "fundamentals_refresh_market_data_unavailable",
                            entity_id=str(entity_id),
                            ticker=result["ticker"],
                        )
                        continue  # Don't update next_refresh_at — will retry next cycle

                    # When embedding fails (e.g. transient DeepInfra error), retry
                    # in 6 hours instead of deferring 30 days (BP-351).
                    embedding_ok = result["embedding"] is not None
                    next_at = (
                        utc_now() + timedelta(days=_REFRESH_INTERVAL_DAYS)  # type: ignore[no-any-return, operator]
                        if embedding_ok
                        else utc_now() + timedelta(hours=6)  # type: ignore[no-any-return, operator]
                    )
                    if not embedding_ok:
                        logger.warning(  # type: ignore[no-any-return]
                            "fundamentals_refresh_embedding_failed",
                            entity_id=str(entity_id),
                            ticker=result["ticker"],
                            retry_in_hours=6,
                        )
                    await emb_repo.upsert(
                        entity_id,
                        VIEW_FUNDAMENTALS,
                        embedding=result["embedding"],
                        model_id=self._embed_model_id if embedding_ok else None,
                        source_text=result["narrative"],
                        source_hash=result["source_hash"],
                        next_refresh_at=next_at,
                    )
                    refreshed += 1

                await session.commit()
        finally:
            if own_http:
                await http.aclose()

        logger.info(  # type: ignore[no-any-return]
            "fundamentals_refresh_worker_complete",
            refreshed=refreshed,
            skipped_non_ticker=skipped,
            earnings_events_inserted=earnings_inserted,
            relations_upserted=relations_upserted,
        )

    # ── T-C-4-01: Earnings — HTTP fetch (Phase 2) ─────────────────────────────

    async def _fetch_earnings_data(
        self,
        http: httpx.AsyncClient,
        instrument_id: UUID,
        ticker: str,
    ) -> list[dict[str, Any]] | None:
        """Fetch earnings history from market-data service (HTTP only, no DB).

        Returns the list of earnings records, or None on error/404.
        Called in Phase 2 outside any DB session (ARCH-004).
        """
        try:
            resp = await http.get(f"{self._market_data_url}/api/v1/fundamentals/{instrument_id}/earnings")
            if resp.status_code == 404:
                logger.debug(  # type: ignore[no-any-return]
                    "earnings_not_found",
                    instrument_id=str(instrument_id),
                    ticker=ticker,
                )
                return None
            if resp.status_code != 200:
                logger.warning(  # type: ignore[no-any-return]
                    "earnings_fetch_error",
                    instrument_id=str(instrument_id),
                    ticker=ticker,
                    status_code=resp.status_code,
                )
                return None
            resp_data: dict[str, Any] = resp.json()
        except Exception as exc:
            logger.warning(  # type: ignore[no-any-return]
                "earnings_fetch_exception",
                instrument_id=str(instrument_id),
                ticker=ticker,
                error=str(exc),
            )
            return None

        return resp_data.get("records") or []

    # ── T-C-4-01: Earnings — DB write (Phase 3) ─────────────────────────────

    async def _write_earnings_events(
        self,
        session: AsyncSession,
        entity_id: UUID,
        instrument_id: UUID,
        canonical_name: str,
        records: list[dict[str, Any]],
    ) -> int:
        """Insert earnings events into the ``events`` table (DB only, no HTTP).

        Idempotent: checks for existing event by (entity_id, quarter, fiscal_year)
        before inserting.  Returns the count of newly inserted events.
        Called in Phase 3 inside a DB session (ARCH-004).
        """
        from datetime import UTC, datetime

        from sqlalchemy import text

        inserted = 0

        for record in records:
            data: dict[str, Any] = record.get("data") or {}
            period_type_str = str(record.get("period_type", "quarterly"))
            period_end_str = record.get("period_end")

            # Parse period_end date — skip record if unparseable
            try:
                period_end = datetime.fromisoformat(str(period_end_str))
                if period_end.tzinfo is None:
                    period_end = period_end.replace(tzinfo=UTC)
            except (ValueError, TypeError):
                continue

            # Derive quarter and fiscal year from period_end
            quarter_num = (period_end.month - 1) // 3 + 1
            quarter_str = f"Q{quarter_num}"
            fiscal_year = period_end.year

            event_subtype = (
                "annual" if "annual" in period_type_str.lower() or "yearly" in period_type_str.lower() else "quarterly"
            )

            # Idempotency check — skip if event already recorded for this quarter/year
            existing = await session.execute(
                text("""
SELECT 1 FROM events
WHERE subject_entity_id = :entity_id
  AND event_type        = 'earnings_release'
  AND structured_data->>'quarter'      = :quarter
  AND structured_data->>'fiscal_year'  = :fiscal_year
"""),
                {
                    "entity_id": str(entity_id),
                    "quarter": quarter_str,
                    "fiscal_year": str(fiscal_year),
                },
            )
            if existing.fetchone() is not None:
                continue

            # Extract earnings fields (try camelCase first, then snake_case fallback)
            eps_actual = _get_float(data, "epsActual", "eps_actual")
            eps_estimate = _get_float(data, "epsEstimate", "eps_estimate")
            revenue_actual = _get_float(data, "revenueActual", "revenue_actual")
            revenue_estimate = _get_float(data, "revenueEstimate", "revenue_estimate")

            beat: bool | None = None
            if eps_actual is not None and eps_estimate is not None:
                beat = eps_actual >= eps_estimate

            # Build event_text
            if eps_actual is not None and eps_estimate is not None:
                event_text = (
                    f"{canonical_name} reported {quarter_str} FY{fiscal_year} "
                    f"EPS of ${eps_actual:.2f} vs. estimate ${eps_estimate:.2f}"
                )
            else:
                event_text = f"{canonical_name} earnings data for {quarter_str} FY{fiscal_year}"

            structured_data_dict: dict[str, Any] = {
                "eps_actual": eps_actual,
                "eps_estimate": eps_estimate,
                "revenue_actual": revenue_actual,
                "revenue_estimate": revenue_estimate,
                "quarter": quarter_str,
                "fiscal_year": fiscal_year,
                "beat": beat,
            }

            event_id = new_uuid7()
            doc_id = new_uuid7()  # Synthetic document ID (no real document for earnings data)

            await session.execute(
                text("""
INSERT INTO events (
    event_id, doc_id, event_type, event_subtype, subject_entity_id,
    event_date, event_text, structured_data, extraction_confidence, source_type
) VALUES (
    :event_id, :doc_id, 'earnings_release', :event_subtype, :entity_id,
    :event_date, :event_text, :structured_data, 0.95, 'earnings_data'
)
ON CONFLICT DO NOTHING
"""),
                {
                    "event_id": str(event_id),
                    "doc_id": str(doc_id),
                    "event_subtype": event_subtype,
                    "entity_id": str(entity_id),
                    "event_date": period_end,
                    "event_text": event_text,
                    "structured_data": json.dumps(structured_data_dict),
                },
            )
            inserted += 1

        return inserted

    # ── T-C-4-02: Company profile — HTTP fetch (Phase 2) ────────────────────

    async def _fetch_company_profile_data(
        self,
        http: httpx.AsyncClient,
        instrument_id: UUID,
    ) -> dict[str, Any] | None:
        """Fetch company profile from market-data service (HTTP only, no DB).

        Returns the profile data dict, or None on error/404.
        Called in Phase 2 outside any DB session (ARCH-004).
        """
        try:
            resp = await http.get(f"{self._market_data_url}/api/v1/fundamentals/{instrument_id}/company-profile")
            if resp.status_code == 404:
                logger.debug(  # type: ignore[no-any-return]
                    "company_profile_not_found",
                    instrument_id=str(instrument_id),
                )
                return None
            if resp.status_code != 200:
                logger.warning(  # type: ignore[no-any-return]
                    "company_profile_fetch_error",
                    instrument_id=str(instrument_id),
                    status_code=resp.status_code,
                )
                return None
            resp_data: dict[str, Any] = resp.json()
        except Exception as exc:
            logger.warning(  # type: ignore[no-any-return]
                "company_profile_fetch_exception",
                instrument_id=str(instrument_id),
                error=str(exc),
            )
            return None

        records: list[dict[str, Any]] = resp_data.get("records") or []
        if not records:
            return None

        return records[0].get("data") or {}

    # ── T-C-4-02: Sector/industry — DB write (Phase 3) ──────────────────────

    async def _write_sector_relations(
        self,
        entity_id: UUID,
        instrument_id: UUID,
        profile_data: dict[str, Any],
        relation_repo: RelationRepository,
        evidence_repo: RelationEvidenceRepository,
        entity_repo: CanonicalEntityRepository,
    ) -> int:
        """Upsert is_in_sector / is_in_industry relations (DB only, no HTTP).

        Uses the existing advisory-lock upsert path (``RelationRepository.upsert``).
        Returns the count of relation rows upserted (0-2 per entity).
        Called in Phase 3 inside a DB session (ARCH-004).
        """
        # Extract sector/industry — prefer GICS names (GicSector/GicGroup match seed entity names)
        sector_name: str | None = (
            profile_data.get("GicSector") or profile_data.get("Sector") or profile_data.get("sector")
        )
        industry_name: str | None = (
            profile_data.get("GicGroup") or profile_data.get("Industry") or profile_data.get("industry")
        )

        now = utc_now()
        upserted = 0

        # --- is_in_sector ---
        if sector_name:
            sector_entity_id = await entity_repo.find_by_name_and_type(str(sector_name), "sector")
            if sector_entity_id is None:
                logger.warning(  # type: ignore[no-any-return]
                    "sector_entity_not_found",
                    entity_id=str(entity_id),
                    sector_name=str(sector_name),
                )
            else:
                await relation_repo.upsert(
                    subject_entity_id=entity_id,
                    object_entity_id=sector_entity_id,
                    canonical_type=_IS_IN_SECTOR_TYPE,
                    semantic_mode=_SECTOR_SEMANTIC_MODE,
                    decay_class=_SECTOR_DECAY_CLASS,
                    decay_alpha=_SECTOR_DECAY_ALPHA,
                    base_confidence=_SECTOR_BASE_CONFIDENCE,
                )
                await evidence_repo.insert_raw(
                    subject_entity_id=entity_id,
                    object_entity_id=sector_entity_id,
                    source_document_id=new_uuid7(),  # Synthetic doc ID (EODHD fundamentals pull)
                    extraction_confidence=_SECTOR_BASE_CONFIDENCE,
                    source_trust_weight=_SECTOR_BASE_CONFIDENCE,
                    evidence_date=now,
                    canonical_type=_IS_IN_SECTOR_TYPE,
                )
                upserted += 1

        # --- is_in_industry ---
        if industry_name:
            industry_entity_id = await entity_repo.find_by_name_and_type(str(industry_name), "industry_group")
            if industry_entity_id is None:
                logger.warning(  # type: ignore[no-any-return]
                    "industry_entity_not_found",
                    entity_id=str(entity_id),
                    industry_name=str(industry_name),
                )
            else:
                await relation_repo.upsert(
                    subject_entity_id=entity_id,
                    object_entity_id=industry_entity_id,
                    canonical_type=_IS_IN_INDUSTRY_TYPE,
                    semantic_mode=_SECTOR_SEMANTIC_MODE,
                    decay_class=_INDUSTRY_DECAY_CLASS,
                    decay_alpha=_INDUSTRY_DECAY_ALPHA,
                    base_confidence=_INDUSTRY_BASE_CONFIDENCE,
                )
                await evidence_repo.insert_raw(
                    subject_entity_id=entity_id,
                    object_entity_id=industry_entity_id,
                    source_document_id=new_uuid7(),  # Synthetic doc ID
                    extraction_confidence=_INDUSTRY_BASE_CONFIDENCE,
                    source_trust_weight=_INDUSTRY_BASE_CONFIDENCE,
                    evidence_date=now,
                    canonical_type=_IS_IN_INDUSTRY_TYPE,
                )
                upserted += 1

        return upserted

    # ── Embedding helpers ─────────────────────────────────────────────────────

    async def _build_fundamentals_narrative(
        self,
        entity_id: UUID,
        ticker: str,
        entity_row: dict[str, Any],
        http: httpx.AsyncClient,
        instrument_id: UUID | None = None,
    ) -> str | None:
        """Fetch market data and build the narrative string."""
        lookup_id = instrument_id or entity_id
        try:
            fundamentals = await self._fetch_json(http, f"{self._market_data_url}/api/v1/fundamentals/{lookup_id}")
            if fundamentals is None:
                return None

            return build_fundamentals_narrative(
                canonical_name=str(entity_row.get("canonical_name", ticker)),
                entity_type=str(entity_row.get("entity_type", "financial_instrument")),
                revenue_usd_millions=_safe_float(fundamentals, "revenue_usd_millions"),
                gross_margin_pct=_safe_float(fundamentals, "gross_margin_pct"),
                net_margin_pct=_safe_float(fundamentals, "net_margin_pct"),
                pe_ratio=_safe_float(fundamentals, "pe_ratio"),
                price=_safe_float(fundamentals, "price"),
                week_52_high=_safe_float(fundamentals, "week_52_high"),
                week_52_low=_safe_float(fundamentals, "week_52_low"),
                description=fundamentals.get("description"),
            )
        except Exception as exc:
            logger.warning(  # type: ignore[no-any-return]
                "fundamentals_refresh_http_error",
                entity_id=str(entity_id),
                error=str(exc),
            )
            return None

    async def _resolve_instrument_id(self, http: httpx.AsyncClient, ticker: str) -> UUID | None:
        """Resolve ticker → market-data instrument_id via /api/v1/instruments/lookup?symbol=.

        KG entity_id ≠ market-data instrument_id — must look up by symbol before fetching data.
        Returns None if the ticker is not found in market-data.

        SA-3 fix (2026-05-10): the endpoint is a query-param lookup, not a path-param route.
        Old (broken):  /api/v1/instruments/symbol/{ticker}  → 404 always
        New (correct): /api/v1/instruments/lookup?symbol={ticker}
        """
        data = await self._fetch_json(http, f"{self._market_data_url}/api/v1/instruments/lookup?symbol={ticker}")
        if data is None:
            return None
        try:
            return UUID(str(data["id"]))
        except (KeyError, ValueError):
            return None

    @staticmethod
    async def _fetch_json(http: httpx.AsyncClient, url: str) -> dict[str, Any] | None:
        try:
            resp = await http.get(url)
            if resp.status_code != 200:
                return None
            return resp.json()  # type: ignore[no-any-return]
        except Exception:
            return None


def _safe_float(d: dict[str, Any], key: str) -> float | None:
    val = d.get(key)
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _get_float(d: dict[str, Any], *keys: str) -> float | None:
    """Try multiple key names in order, returning the first non-None float found."""
    for key in keys:
        val = _safe_float(d, key)
        if val is not None:
            return val
    return None
