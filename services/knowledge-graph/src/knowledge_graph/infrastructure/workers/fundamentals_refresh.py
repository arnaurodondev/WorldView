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
from enum import StrEnum
from typing import TYPE_CHECKING, Any
from uuid import UUID

import jwt

from common.ids import new_uuid7  # type: ignore[import-untyped]
from common.time import utc_now  # type: ignore[import-untyped]
from knowledge_graph.application.metrics import fundamentals_refresh_failed_total
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
    from messaging.valkey.client import ValkeyClient  # type: ignore[import-untyped]

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

# ── PLAN-0093 D-2 (T-D-2-01): per-ticker exponential backoff ─────────────────
#
# When market-data returns persistent HTTP errors (404 missing fundamentals,
# 5xx provider outage), hammering the same ticker every 30-day refresh cycle
# wastes upstream quota.  We back off in Valkey and skip the entity until the
# backoff window elapses.
#
# Key  : s7:fundamentals:backoff:{ticker} (TTL == current backoff seconds)
# Value: current backoff in seconds (string-encoded int).
#
# Schedule:
#   First error           → 3600   s (1h)
#   Second error          → 86400  s (1d)
#   Third + later errors  → 604800 s (7d)
#   Success               → DELETE the key (resume normal 30-day cadence).
_BACKOFF_KEY_PREFIX = "s7:fundamentals:backoff"
_BACKOFF_STAGE_1H_S = 3600
_BACKOFF_STAGE_1D_S = 86400
_BACKOFF_STAGE_7D_S = 604800

# ── 2026-06-14 (empty-entity-descriptions P0): instrument-lookup-miss long-defer ──
#
# RC1: KG holds ~2,202 ticker'd FI entities but market-data only has ~646
# instruments, so ~1,268 entities fail ``_resolve_instrument_id`` (no symbol
# match) on EVERY 5-min cycle. Previously a lookup miss returned a
# ``narrative=None`` result with ``failure_reason="instrument_lookup_failed"``
# which (a) escalated the Valkey backoff one stage (1h→1d→7d) and (b) hit the
# ``narrative is None`` Phase-3 branch that ``continue``s WITHOUT advancing
# ``next_refresh_at`` — so the row stayed due and re-failed forever, producing
# ``refreshed: 0, backoff_escalations: 1268`` every cycle.
#
# A missing market-data instrument is a DATA-AVAILABILITY gap, not a transient
# error: it will not self-heal within the 1h-7d backoff window. So instead of
# escalating, we push ``next_refresh_at`` 30 days forward (same cadence as a
# successful refresh). If the instrument is later ingested into market-data, the
# row becomes due again in ≤30 days and succeeds. Transient/other failures
# (HTTP 4xx/5xx, transport, missing sections) keep the existing
# escalate-and-retry-sooner behaviour.
_INSTRUMENT_LOOKUP_MISS_DEFER_DAYS = 30


# ── F-DB-005 (2026-05-28): structured error classes ──────────────────────────
#
# Replaces the silent ``reason or "unknown"`` fallback that previously hid a
# months-old schema mismatch (488 of 811 entities classified as ``unknown``
# actually meant ``fundamentals_missing_sections``). Every code path that
# returns ``narrative=None`` MUST set ``failure_reason`` to one of these values.
# The worker bumps ``fundamentals_refresh_failed_total{error_kind=...}`` so
# ops dashboards can spot contract drift between market-data and the narrative
# builder immediately — this is the F-DB-005 bug class.
class FundamentalsRefreshError(StrEnum):
    """Structured failure reasons for FundamentalsRefreshWorker.

    Members:
        EMPTY_PAYLOAD      — market-data returned 200 with empty body.
        SCHEMA_UNPARSABLE  — body parsed but lacks the canonical ``records`` key
                             (contract drift — market-data shape changed).
        MISSING_SECTIONS   — ``records`` present but no usable section payloads
                             (every metric resolved to None — the F-DB-005 bug).
        DESERIALIZATION_ERROR — JSON decode raised.
        TRANSPORT_ERROR    — HTTP connect/read failed before a status arrived.
        HTTP_4XX, HTTP_5XX — market-data returned a non-2xx status (the granular
                             code is still in the per-call log).
    """

    EMPTY_PAYLOAD = "fundamentals_empty_payload"
    SCHEMA_UNPARSABLE = "fundamentals_schema_unparsable"
    MISSING_SECTIONS = "fundamentals_missing_sections"
    DESERIALIZATION_ERROR = "fundamentals_json_decode_failed"
    TRANSPORT_ERROR = "fundamentals_transport_error"
    HTTP_4XX = "fundamentals_http_4xx"
    HTTP_5XX = "fundamentals_http_5xx"


# Sections we need to walk on the canonical ``records[]`` shape returned by
# market-data ``GET /api/v1/fundamentals/{id}``. See
# ``docs/audits/2026-05-28-fundamentals-shape-audit.md`` Stages 3-4.
_SECTION_HIGHLIGHTS = "highlights"
_SECTION_INCOME_STATEMENT = "income_statement"
_SECTION_TECHNICALS = "technicals_snapshot"
_SECTION_COMPANY_PROFILE = "company_profile"


def _backoff_key(ticker: str) -> str:
    """Build the Valkey key for *ticker*'s backoff state."""
    # Lower-case so AAPL == aapl (DB stores symbols case-sensitive but
    # backoff is a quota-protection signal — collapsing case is safe).
    return f"{_BACKOFF_KEY_PREFIX}:{ticker.lower()}"


def _next_backoff_seconds(current: int | None) -> int:
    """Return the next backoff value given the current one (None = first error).

    Pure function — easy to unit-test without Valkey.
    """
    if current is None or current < _BACKOFF_STAGE_1H_S:
        return _BACKOFF_STAGE_1H_S
    if current < _BACKOFF_STAGE_1D_S:
        return _BACKOFF_STAGE_1D_S
    return _BACKOFF_STAGE_7D_S


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
        valkey_client: ValkeyClient | None = None,
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
        # PLAN-0093 D-2 (T-D-2-01): Valkey client for per-ticker exponential
        # backoff.  Optional: when ``None`` the worker behaves exactly as
        # before — no skip, no escalation — so unit tests that do not wire
        # Valkey keep working.
        self._valkey = valkey_client

    # ── PLAN-0093 D-2 backoff helpers ────────────────────────────────────────

    async def _get_backoff_seconds(self, ticker: str) -> int | None:
        """Return current backoff in seconds, or None if no backoff active.

        Best-effort: any Valkey failure is treated as "no backoff" so a
        transient Valkey outage does not silently halt fundamentals
        refresh entirely.
        """
        if self._valkey is None:
            return None
        try:
            raw = await self._valkey.get(_backoff_key(ticker))
        except Exception as exc:
            logger.warning(  # type: ignore[no-any-return]
                "fundamentals_refresh_backoff_get_failed",
                ticker=ticker,
                error=str(exc),
            )
            return None
        if raw is None:
            return None
        try:
            return int(raw)
        except (TypeError, ValueError):
            return None

    async def _escalate_backoff(self, ticker: str) -> int:
        """Move *ticker* to the next backoff stage; returns new backoff seconds.

        First call → 1h, then 1d, then 7d (terminal).  Key TTL is set to the
        new backoff value so it expires naturally and we can detect "first
        error" by absence of the key.
        """
        current = await self._get_backoff_seconds(ticker)
        new_seconds = _next_backoff_seconds(current)
        if self._valkey is None:
            return new_seconds
        try:
            await self._valkey.set(_backoff_key(ticker), str(new_seconds), ex=new_seconds)
        except Exception as exc:
            logger.warning(  # type: ignore[no-any-return]
                "fundamentals_refresh_backoff_set_failed",
                ticker=ticker,
                error=str(exc),
            )
        return new_seconds

    async def _reset_backoff(self, ticker: str) -> None:
        """Clear the backoff key on a successful refresh."""
        if self._valkey is None:
            return
        try:
            await self._valkey.delete(_backoff_key(ticker))
        except Exception as exc:
            logger.warning(  # type: ignore[no-any-return]
                "fundamentals_refresh_backoff_reset_failed",
                ticker=ticker,
                error=str(exc),
            )

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
        # PLAN-0093 D-2: per-cycle counters for backoff observability.
        # Initialised at top so the final `complete` log always renders these
        # fields even when the cycle has zero due entities.
        backoff_escalations = 0
        backoff_resets = 0
        # FIX-LIVE-G (2026-05-24): per-reason failure counter so the
        # ``fundamentals_refresh_worker_complete`` summary reveals whether the
        # cycle's losses were caused by missing instruments (data-availability
        # gap), missing fundamentals (ingestion gap), auth (401/403), or
        # transport errors. Previously all four collapsed into a single
        # generic ``market_data_unavailable`` warning, costing INV-LIVE-E ~1h
        # chasing a JWT hypothesis that turned out to be wrong.
        failure_counts: dict[str, int] = {}

        try:
            # ── Phase 1: Read due entities, then release the session ──
            # DEF-034 (Wave B-5): Phase 1 fetch uses the read replica when
            # configured. Phase 3 writes still go through ``self._sf``.
            due_entities: list[dict[str, Any]] = []
            no_ticker_ids: list[UUID] = []
            async with self._read_session_factory() as session:
                emb_repo = EntityEmbeddingStateRepository(session)
                # 0 = unlimited (drain full queue); see EntityEmbeddingStateRepository.get_due_for_refresh
                due = await emb_repo.get_due_for_refresh(VIEW_FUNDAMENTALS, 0)
                for row in due:
                    ticker: str | None = row.get("ticker")  # type: ignore[assignment]
                    if not ticker:
                        skipped += 1
                        # Collect for Phase 3 tombstone so they are not re-queued
                        # every cycle forever (next_refresh_at stays in the past).
                        no_ticker_ids.append(row["entity_id"])  # type: ignore[arg-type]
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
                """Fetch all HTTP data for one entity; returns result dict (no embed yet).

                PLAN-0093 D-2 (T-D-2-01): when a backoff is active for this
                ticker, skip all HTTP calls and return a marker so Phase 3
                pushes ``next_refresh_at`` forward by the backoff window.
                """
                async with semaphore:
                    _entity_id: UUID = ent["entity_id"]
                    _ticker_str: str = str(ent["ticker"])

                    # ── Backoff guard (PLAN-0093 D-2) ────────────────────────
                    _backoff_s = await self._get_backoff_seconds(_ticker_str)
                    if _backoff_s is not None:
                        logger.info(  # type: ignore[no-any-return]
                            "fundamentals_refresh_backoff_skip",
                            entity_id=str(_entity_id),
                            ticker=_ticker_str,
                            backoff_seconds=_backoff_s,
                        )
                        return {
                            "entity_id": _entity_id,
                            "ticker": _ticker_str,
                            "canonical_name": ent["canonical_name"],
                            "earnings_data": None,
                            "profile_data": None,
                            "narrative": None,
                            "backoff_active_seconds": _backoff_s,
                        }

                    # Resolve ticker → market-data instrument_id.
                    # 2026-06-14 P0: distinguish a GENUINE miss (no instrument in
                    # market-data — a stable data-availability gap) from a
                    # TRANSIENT lookup failure (transport error / 5xx). Only a
                    # genuine miss triggers the 30-day long-defer; transient
                    # failures keep the existing escalate-and-retry-sooner path
                    # so a brief market-data outage does not defer everything.
                    _instrument_id, _lookup_transient = await self._resolve_instrument_id_with_status(http, _ticker_str)
                    if _instrument_id is None:
                        logger.debug(  # type: ignore[no-any-return]
                            "fundamentals_refresh_instrument_not_found",
                            entity_id=str(_entity_id),
                            ticker=_ticker_str,
                            transient=_lookup_transient,
                        )
                        return {
                            "entity_id": _entity_id,
                            "ticker": _ticker_str,
                            "canonical_name": ent["canonical_name"],
                            "earnings_data": None,
                            "profile_data": None,
                            "narrative": None,
                            # FIX-LIVE-G (2026-05-24): structured failure
                            # reason — distinguishes the "no instrument
                            # ingested" case (~99% of dev failures) from a
                            # downstream fundamentals failure.
                            "failure_reason": "instrument_lookup_failed",
                            # 2026-06-14 P0: only a GENUINE miss (not a transient
                            # transport/5xx error) marks the row for the 30-day
                            # long-defer. A genuine miss is a data-availability
                            # gap that won't self-heal in 1h — escalating it
                            # churned 1,268 entities every cycle (RC1). A
                            # transient lookup error leaves this False so the
                            # existing backoff-escalation path still retries soon.
                            "instrument_lookup_miss": not _lookup_transient,
                        }

                    # Fetch earnings, profile, and fundamentals narrative in parallel.
                    # FIX-LIVE-G (2026-05-24): _build_fundamentals_narrative
                    # now returns a (narrative, failure_reason) tuple so we
                    # can attribute the failure precisely.
                    _earnings_data, _profile_data, _narrative_result = await asyncio.gather(
                        self._fetch_earnings_data(http, _instrument_id, _ticker_str),
                        self._fetch_company_profile_data(http, _instrument_id),
                        self._build_fundamentals_narrative(_entity_id, _ticker_str, ent["row"], http, _instrument_id),
                    )
                    _narrative, _narrative_failure_reason = _narrative_result

                    return {
                        "entity_id": _entity_id,
                        "ticker": _ticker_str,
                        "canonical_name": ent["canonical_name"],
                        "earnings_data": _earnings_data,
                        "profile_data": _profile_data,
                        "narrative": _narrative,
                        "failure_reason": _narrative_failure_reason,
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
                        # PLAN-0093 D-2: propagate the backoff marker so Phase 3
                        # can defer next_refresh_at by the backoff window.
                        "backoff_active_seconds": res.get("backoff_active_seconds"),
                        # FIX-LIVE-G (2026-05-24): propagate the specific
                        # market-data failure category to Phase 3 so the
                        # warning event names the actual cause.
                        "failure_reason": res.get("failure_reason"),
                        # 2026-06-14 P0: propagate the lookup-miss marker so
                        # Phase 3 long-defers (30d) instead of leaving the row
                        # due, and the post-commit step skips backoff escalation.
                        "instrument_lookup_miss": res.get("instrument_lookup_miss", False),
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
                    _ticker_for_backoff = str(result["ticker"])

                    # --- PLAN-0093 D-2: backoff-skipped entity ───────────────
                    # No HTTP calls were issued — just push next_refresh_at
                    # forward so the row is not re-queued before the backoff
                    # window expires.  Skip embedding/earnings/sector writes.
                    if result.get("backoff_active_seconds"):
                        _bo_seconds = int(result["backoff_active_seconds"])
                        await emb_repo.upsert(
                            entity_id,
                            VIEW_FUNDAMENTALS,
                            embedding=None,
                            model_id=None,
                            source_text=None,
                            source_hash=None,
                            next_refresh_at=utc_now() + timedelta(seconds=_bo_seconds),
                        )
                        continue

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
                        # FIX-LIVE-G (2026-05-24): include the precise
                        # failure_reason so ops/QA can grep on the actual
                        # cause (e.g. ``instrument_lookup_failed``,
                        # ``fundamentals_http_404``, ``fundamentals_http_401``)
                        # without re-reading every per-call log line. Also
                        # bumps an aggregate counter that is surfaced in the
                        # worker_complete event.
                        # F-DB-005 (2026-05-28): the prior ``or "unknown"``
                        # fallback hid a months-old schema mismatch (488/811
                        # entities classified as ``unknown`` actually meant
                        # ``fundamentals_missing_sections``). The structured
                        # error classes in ``FundamentalsRefreshError`` are
                        # now MANDATORY — any code path that returns
                        # ``narrative=None`` MUST also return a non-empty
                        # failure_reason. We loud-fail if not, so a future
                        # regression cannot reintroduce the silent class.
                        reason = result.get("failure_reason")
                        if not reason:
                            reason = "fundamentals_unclassified_failure"
                            logger.error(  # type: ignore[no-any-return]
                                "fundamentals_refresh_unclassified_none_narrative",
                                entity_id=str(entity_id),
                                ticker=result["ticker"],
                            )
                        failure_counts[reason] = failure_counts.get(reason, 0) + 1
                        # Per-error-class Prometheus counter (F-DB-005). Makes
                        # the "unknown 488" class of bug impossible to ignore
                        # in future — it will show up as a non-zero series for
                        # ``fundamentals_schema_unparsable`` or similar. We
                        # bucket granular HTTP statuses (``fundamentals_http_404``,
                        # ``..._http_401``, ...) into ``http_4xx``/``http_5xx``
                        # for the counter label so cardinality stays bounded;
                        # the granular code is still in the structured warning
                        # log line below.
                        metric_label = reason
                        if reason.startswith("fundamentals_http_"):
                            try:
                                _code = int(reason.rsplit("_", 1)[-1])
                                metric_label = (
                                    FundamentalsRefreshError.HTTP_4XX.value
                                    if 400 <= _code < 500
                                    else FundamentalsRefreshError.HTTP_5XX.value
                                )
                            except ValueError:
                                metric_label = FundamentalsRefreshError.HTTP_5XX.value
                        fundamentals_refresh_failed_total.labels(error_kind=metric_label).inc()
                        logger.warning(  # type: ignore[no-any-return]
                            "fundamentals_refresh_market_data_unavailable",
                            entity_id=str(entity_id),
                            ticker=result["ticker"],
                            failure_reason=reason,
                        )

                        # ── 2026-06-14 P0: instrument-lookup miss → long defer ──
                        # The ticker resolved to no market-data instrument. This
                        # is a data-availability gap, not a transient error, so
                        # push next_refresh_at 30 days forward instead of leaving
                        # the row due (which previously re-failed every 5-min
                        # cycle for ~1,268 entities — RC1). Idempotent: the upsert
                        # just rewrites next_refresh_at; source_text/embedding stay
                        # untouched. The post-commit step skips escalation for
                        # these (see ``instrument_lookup_miss`` guard below).
                        if result.get("instrument_lookup_miss"):
                            await emb_repo.upsert(
                                entity_id,
                                VIEW_FUNDAMENTALS,
                                embedding=None,
                                model_id=None,
                                source_text=None,
                                source_hash=None,
                                next_refresh_at=utc_now() + timedelta(days=_INSTRUMENT_LOOKUP_MISS_DEFER_DAYS),
                            )
                            logger.info(  # type: ignore[no-any-return]
                                "fundamentals_refresh_instrument_lookup_long_defer",
                                entity_id=str(entity_id),
                                ticker=result["ticker"],
                                reason="instrument_not_in_market_data",
                                defer_days=_INSTRUMENT_LOOKUP_MISS_DEFER_DAYS,
                            )
                            continue
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

            # ── PLAN-0093 D-2: post-commit backoff escalation / reset ──────
            # Outside the DB session — the Valkey hops are short but we still
            # do not want to hold a Postgres connection across them.  An
            # entity that was backoff-skipped (no HTTP issued) is left alone;
            # an entity whose HTTP succeeded resets; an entity whose narrative
            # came back None (all 3 HTTP calls failed) escalates one stage.
            for result in entity_io_results:
                _ticker_for_backoff = str(result["ticker"])
                if result.get("backoff_active_seconds"):
                    # Skipped this cycle — backoff already in flight, do nothing.
                    continue
                if result.get("instrument_lookup_miss"):
                    # 2026-06-14 P0: ticker has no market-data instrument. We
                    # already pushed next_refresh_at 30 days forward in Phase 3,
                    # so do NOT escalate the Valkey backoff (the 1h→1d→7d ladder
                    # is for transient errors; escalating here is what produced
                    # the perpetual 1,268-per-cycle storm — RC1). Leave any
                    # existing backoff key to expire on its own TTL.
                    continue
                if result["narrative"] is None:
                    new_seconds = await self._escalate_backoff(_ticker_for_backoff)
                    logger.warning(  # type: ignore[no-any-return]
                        "fundamentals_refresh_backoff_escalated",
                        ticker=_ticker_for_backoff,
                        new_backoff_seconds=new_seconds,
                    )
                    backoff_escalations += 1
                else:
                    # narrative is not None → at least the fundamentals fetch
                    # was OK; clear any lingering backoff so the next cycle
                    # resumes the normal 30-day cadence.
                    await self._reset_backoff(_ticker_for_backoff)
                    backoff_resets += 1

            # Tombstone no-ticker entities in a dedicated session so they are
            # not re-queued on every worker cycle (next_refresh_at +365 days).
            if no_ticker_ids:
                from sqlalchemy import text as _sa_text

                far_future = utc_now() + timedelta(days=365)
                async with self._sf() as _ts_session:
                    for _no_ticker_id in no_ticker_ids:
                        await _ts_session.execute(
                            _sa_text(
                                "UPDATE entity_embedding_state"
                                " SET next_refresh_at = :far_future"
                                " WHERE entity_id = :entity_id"
                                " AND view_type = :view_type"
                            ),
                            {
                                "far_future": far_future,
                                "entity_id": str(_no_ticker_id),
                                "view_type": VIEW_FUNDAMENTALS,
                            },
                        )
                    await _ts_session.commit()
                logger.info(  # type: ignore[no-any-return]
                    "fundamentals_refresh_no_ticker_tombstoned",
                    count=len(no_ticker_ids),
                    retry_in_days=365,
                )
        finally:
            if own_http:
                await http.aclose()

        logger.info(  # type: ignore[no-any-return]
            "fundamentals_refresh_worker_complete",
            refreshed=refreshed,
            skipped_non_ticker=skipped,
            earnings_events_inserted=earnings_inserted,
            relations_upserted=relations_upserted,
            # PLAN-0093 D-2 backoff observability:
            backoff_escalations=backoff_escalations,
            backoff_resets=backoff_resets,
            # FIX-LIVE-G (2026-05-24): aggregate per-reason failure breakdown
            # so the single complete-event log answers "which class of failure
            # dominated this cycle?" without scanning per-entity warnings.
            failure_breakdown=failure_counts,
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

        # ── PLAN-0103 W19 / BP-637: mirror EODHD sector + industry into the
        # ``canonical_entities.metadata`` JSONB column alongside the existing
        # relation upsert. The risk_summary aggregator (rag-chat) and the
        # ``/internal/v1/sectors`` endpoint both read ``metadata->>'sector'``
        # — not the graph relation — so historically 683/1108 instruments
        # had a working ``is_in_sector`` edge but a NULL metadata.sector,
        # causing the morning brief to silently report ``Unknown`` for the
        # majority of tracked equities. We patch BEFORE the relation upsert
        # so a relation_repo failure does not roll back the metadata write
        # (they live in the same transaction — both succeed or both abort,
        # which is the intended invariant).
        metadata_patch: dict[str, object] = {}
        if sector_name:
            metadata_patch["sector"] = str(sector_name)
        if industry_name:
            metadata_patch["industry"] = str(industry_name)
        if metadata_patch:
            # ``asset_class="Equity"`` lets the rag-chat ETF fallback skip
            # this row: only rows tagged ``ETF`` get the synthetic "Equity
            # ETF" bucket, so an equity with a real GICS sector is always
            # bucketed under that sector, never under the ETF catch-all.
            metadata_patch["asset_class"] = "Equity"
            await entity_repo.patch_metadata(entity_id, metadata_patch)

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
                    evidence_text=f"EODHD fundamentals: {sector_name} sector classification.",
                    source_name="eodhd",
                    source_type="eodhd",
                    # PLAN-0093 B-3 T-B-3-02: claim_id + chunk_id are NOT NULL on
                    # relation_evidence_raw (migration 0047).  Fundamentals
                    # evidence is structured (EODHD API) and has no real
                    # claim/chunk — synthesise both per-relation so each row
                    # still satisfies the NOT NULL constraint and downstream
                    # joins simply find no matching claim/chunk (intended).
                    claim_id=new_uuid7(),
                    chunk_id=new_uuid7(),
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
                    evidence_text=f"EODHD fundamentals: {industry_name} industry classification.",
                    source_name="eodhd",
                    source_type="eodhd",
                    # PLAN-0093 B-3 T-B-3-02: synthesise claim_id + chunk_id —
                    # structured EODHD evidence has no real claim/chunk;
                    # both columns are NOT NULL on relation_evidence_raw.
                    claim_id=new_uuid7(),
                    chunk_id=new_uuid7(),
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
    ) -> tuple[str | None, str | None]:
        """Fetch market data and build the narrative string.

        FIX-LIVE-G (2026-05-24): now returns a ``(narrative, failure_reason)``
        tuple. ``failure_reason`` is ``None`` on success or a precise string
        like ``"fundamentals_http_404"``, ``"fundamentals_http_401"`` (auth
        regression — the hypothesis INV-LIVE-E chased that turned out to be
        wrong), or ``"fundamentals_transport_error"`` on failure. The caller
        uses it for the structured Phase 3 warning + aggregate counter so
        future investigations see the actual failure category immediately.

        Note: this method uses ``_fetch_json`` which already emits a
        per-call log line (``market_data_call_client_error`` / ``_server_error``)
        with HTTP status, URL, ticker, and latency. The tuple is the
        aggregate signal; the per-call logs are the detail.
        """
        import time as _time

        lookup_id = instrument_id or entity_id
        url = f"{self._market_data_url}/api/v1/fundamentals/{lookup_id}"
        _t0 = _time.monotonic()
        try:
            resp = await http.get(url)
        except Exception as exc:
            _latency_ms = int((_time.monotonic() - _t0) * 1000)
            logger.error(  # type: ignore[no-any-return]
                "market_data_call_exception",
                url=url,
                ticker=ticker,
                status_code=-1,
                latency_ms=_latency_ms,
                error=str(exc),
            )
            logger.warning(  # type: ignore[no-any-return]
                "fundamentals_refresh_http_error",
                entity_id=str(entity_id),
                ticker=ticker,
                error_type=type(exc).__name__,
                error=str(exc),
            )
            return None, FundamentalsRefreshError.TRANSPORT_ERROR.value

        # Mirror the per-call observability from _fetch_json so this code
        # path is not less-observable than the resolve/earnings/profile
        # paths.
        _latency_ms = int((_time.monotonic() - _t0) * 1000)
        _body_len = len(resp.content) if hasattr(resp, "content") and resp.content is not None else 0
        _log_fields = {
            "url": url,
            "ticker": ticker,
            "status_code": resp.status_code,
            "latency_ms": _latency_ms,
            "body_len": _body_len,
        }
        if 200 <= resp.status_code < 300:
            logger.info("market_data_call_ok", **_log_fields)  # type: ignore[no-any-return]
        elif 400 <= resp.status_code < 500:
            logger.warning("market_data_call_client_error", **_log_fields)  # type: ignore[no-any-return]
        else:
            logger.error("market_data_call_server_error", **_log_fields)  # type: ignore[no-any-return]

        if resp.status_code != 200:
            # Preserve the granular status_code in the structured failure_reason
            # (kept verbatim from the pre-F-DB-005 contract — tests at
            # test_fundamentals_refresh_worker.py:967, 1016 assert on the exact
            # ``fundamentals_http_404`` and ``..._http_401`` strings so ops
            # dashboards can distinguish missing-fundamentals from auth-failure
            # without parsing the log payload). The Prometheus counter buckets
            # by 4xx/5xx so the label cardinality stays bounded.
            return None, f"fundamentals_http_{resp.status_code}"

        try:
            fundamentals: dict[str, Any] = resp.json()
        except Exception as exc:
            logger.warning(  # type: ignore[no-any-return]
                "fundamentals_refresh_json_decode_failed",
                entity_id=str(entity_id),
                ticker=ticker,
                error=str(exc),
            )
            return None, FundamentalsRefreshError.DESERIALIZATION_ERROR.value

        # ── F-DB-005 FIX (2026-05-28): walk records[] by section ──────────────
        # The endpoint returns ``{security_id, records: [{section, data, ...}]}``
        # NOT the flat ``{revenue_usd_millions, pe_ratio, ...}`` shape the old
        # code read. See docs/audits/2026-05-28-fundamentals-shape-audit.md
        # Stage 3 for the canonical schema (anchored to
        # market_data/api/schemas/fundamentals.py:24-28).
        if not fundamentals:
            return None, FundamentalsRefreshError.EMPTY_PAYLOAD.value
        records = fundamentals.get("records")
        if records is None or not isinstance(records, list):
            return None, FundamentalsRefreshError.SCHEMA_UNPARSABLE.value

        # Index records by section. Multiple records per section (one per
        # period) are possible — we keep ALL rows so we can pick the newest
        # one for income_statement margins.
        sections: dict[str, list[dict[str, Any]]] = {}
        for rec in records:
            if not isinstance(rec, dict):
                continue
            section = rec.get("section")
            if not isinstance(section, str):
                continue
            sections.setdefault(section, []).append(rec)

        def _latest_data(section_name: str) -> dict[str, Any]:
            """Return the ``data`` payload of the newest ``period_end`` row for
            *section_name*, or {} if no row present. period_end is the ISO
            timestamp string returned by market-data; lexical sort is correct
            for ISO-8601 (newest = max)."""
            rows = sections.get(section_name) or []
            if not rows:
                return {}
            rows_sorted = sorted(rows, key=lambda r: str(r.get("period_end", "")), reverse=True)
            top = rows_sorted[0]
            data = top.get("data")
            return data if isinstance(data, dict) else {}

        highlights = _latest_data(_SECTION_HIGHLIGHTS)
        income_latest = _latest_data(_SECTION_INCOME_STATEMENT)
        technicals = _latest_data(_SECTION_TECHNICALS)
        profile = _latest_data(_SECTION_COMPANY_PROFILE)

        # Revenue: prefer Highlights.RevenueTTM (USD raw → millions); fall back
        # to income_statement latest totalRevenue (already a quarterly figure;
        # the narrative buckets by size, so quarterly vs TTM is acceptable for
        # the embedding even if not strictly TTM).
        revenue_raw = _safe_float(highlights, "RevenueTTM")
        revenue_usd_millions: float | None = (revenue_raw / 1e6) if revenue_raw is not None else None
        if revenue_usd_millions is None:
            inc_rev = _get_float(income_latest, "totalRevenue", "total_revenue", "TotalRevenue")
            if inc_rev is not None:
                revenue_usd_millions = inc_rev / 1e6

        # Margins computed from latest income_statement row.
        total_revenue = _get_float(income_latest, "totalRevenue", "total_revenue", "TotalRevenue")
        gross_profit = _get_float(income_latest, "grossProfit", "gross_profit", "GrossProfit")
        net_income = _get_float(income_latest, "netIncome", "net_income", "NetIncome")
        gross_margin_pct: float | None = None
        net_margin_pct: float | None = None
        if total_revenue and total_revenue != 0.0:
            if gross_profit is not None:
                gross_margin_pct = 100.0 * gross_profit / total_revenue
            if net_income is not None:
                net_margin_pct = 100.0 * net_income / total_revenue

        # P/E from Highlights.
        pe_ratio = _get_float(highlights, "PERatio", "peRatio")

        # Price + 52W from technicals (preferred); fall back to highlights for
        # tickers where market-data hasn't ingested the technicals snapshot.
        price = _get_float(technicals, "Price") or _get_float(highlights, "Price")
        week_52_high = _get_float(technicals, "52WeekHigh", "WeekHigh52") or _get_float(
            highlights, "52WeekHigh", "WeekHigh52"
        )
        week_52_low = _get_float(technicals, "52WeekLow", "WeekLow52") or _get_float(
            highlights, "52WeekLow", "WeekLow52"
        )

        description_val = profile.get("Description") if isinstance(profile.get("Description"), str) else None

        narrative = build_fundamentals_narrative(
            canonical_name=str(entity_row.get("canonical_name", ticker)),
            entity_type=str(entity_row.get("entity_type", "financial_instrument")),
            revenue_usd_millions=revenue_usd_millions,
            gross_margin_pct=gross_margin_pct,
            net_margin_pct=net_margin_pct,
            pe_ratio=pe_ratio,
            price=price,
            week_52_high=week_52_high,
            week_52_low=week_52_low,
            description=description_val,
        )
        if narrative is None:
            # Records present but every section payload yielded None for the
            # narrative inputs (e.g. ETF with no Highlights / Technicals).
            # This is the structural class the old code mis-labelled "unknown".
            return None, FundamentalsRefreshError.MISSING_SECTIONS.value
        return narrative, None

    async def _resolve_instrument_id(self, http: httpx.AsyncClient, ticker: str) -> UUID | None:
        """Resolve ticker → market-data instrument_id via /api/v1/instruments/lookup?symbol=.

        KG entity_id ≠ market-data instrument_id — must look up by symbol before fetching data.
        Returns None if the ticker is not found in market-data.

        SA-3 fix (2026-05-10): the endpoint is a query-param lookup, not a path-param route.
        Old (broken):  /api/v1/instruments/symbol/{ticker}  → 404 always
        New (correct): /api/v1/instruments/lookup?symbol={ticker}
        """
        instrument_id, _transient = await self._resolve_instrument_id_with_status(http, ticker)
        return instrument_id

    async def _resolve_instrument_id_with_status(
        self,
        http: httpx.AsyncClient,
        ticker: str,
    ) -> tuple[UUID | None, bool]:
        """Resolve ticker → instrument_id, distinguishing *genuine miss* from *transient error*.

        2026-06-14 P0 (RC1): the 30-day long-defer must only apply when the
        ticker GENUINELY has no market-data instrument (a stable data-availability
        gap), NOT when the lookup itself failed transiently (transport error,
        5xx). Otherwise a brief market-data outage would silently defer every
        entity by 30 days.

        Returns:
            (instrument_id, transient):
              - (UUID, False)  — resolved successfully.
              - (None, False)  — genuine miss: lookup returned a payload (HTTP 200)
                                 with no usable ``id``, or market-data answered 4xx.
              - (None, True)   — transient: transport error or 5xx; caller should
                                 keep the existing escalate-and-retry-sooner path.
        """
        url = f"{self._market_data_url}/api/v1/instruments/lookup?symbol={ticker}"
        try:
            resp = await http.get(url)
        except Exception as exc:
            logger.warning(  # type: ignore[no-any-return]
                "fundamentals_refresh_instrument_lookup_transport_error",
                ticker=ticker,
                error=str(exc),
            )
            return None, True  # transient — do NOT long-defer

        status = resp.status_code
        if status == 200:
            try:
                data = resp.json()
            except Exception:
                # 200 but unparsable body → treat as a genuine miss (not retryable).
                return None, False
            try:
                return UUID(str(data["id"])), False
            except (KeyError, ValueError, TypeError):
                return None, False  # genuine miss — no usable id in the payload
        if 500 <= status < 600:
            # Server-side problem — transient, keep retrying on the backoff ladder.
            return None, True
        # 4xx (incl. 404): market-data positively has no such instrument → genuine miss.
        return None, False

    @staticmethod
    async def _fetch_json(http: httpx.AsyncClient, url: str, ticker: str | None = None) -> dict[str, Any] | None:
        """GET *url* and parse JSON; log status code on every call (T-D-2-02).

        Logging policy (PLAN-0093 D-2):
          - 2xx → INFO with status_code, url, ticker, latency_ms, body_len.
          - 4xx → WARNING with same fields.
          - 5xx → ERROR with same fields.
          - exception (TCP error, timeout) → ERROR with status_code=-1.

        Returns parsed JSON dict on 200, None otherwise (preserves the
        existing contract so call sites do not need to change).
        """
        import time as _time

        _t0 = _time.monotonic()
        try:
            resp = await http.get(url)
        except Exception as exc:
            _latency_ms = int((_time.monotonic() - _t0) * 1000)
            logger.error(  # type: ignore[no-any-return]
                "market_data_call_exception",
                url=url,
                ticker=ticker,
                status_code=-1,
                latency_ms=_latency_ms,
                error=str(exc),
            )
            return None

        _latency_ms = int((_time.monotonic() - _t0) * 1000)
        _body_len = len(resp.content) if hasattr(resp, "content") and resp.content is not None else 0
        _log_fields = {
            "url": url,
            "ticker": ticker,
            "status_code": resp.status_code,
            "latency_ms": _latency_ms,
            "body_len": _body_len,
        }
        if 200 <= resp.status_code < 300:
            logger.info("market_data_call_ok", **_log_fields)  # type: ignore[no-any-return]
        elif 400 <= resp.status_code < 500:
            logger.warning("market_data_call_client_error", **_log_fields)  # type: ignore[no-any-return]
        else:
            logger.error("market_data_call_server_error", **_log_fields)  # type: ignore[no-any-return]

        if resp.status_code != 200:
            return None
        try:
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
