"""Shared enrichment logic for ProvisionalEnrichmentWorker and ProvisionalQueuedConsumer.

Both the polling sweep worker (provisional_enrichment.py) and the hot-path Kafka
consumer (provisional_queued_consumer.py) need to run the same LLM extraction,
embedding, and DB persistence steps.  This module provides module-level async
functions so both call sites can share logic without circular imports.

ARCH-003 contract: no DB session is held during extract_entity_profile or
compute_embedding — callers acquire a session, release it, do the I/O, then
acquire a new session for persist_enrichment.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID

from common.ids import new_uuid7  # type: ignore[import-untyped]
from common.tickers import strip_exchange_qualifier  # type: ignore[import-untyped]
from common.time import utc_now  # type: ignore[import-untyped]
from knowledge_graph.infrastructure.intelligence_db.repositories.entity_embedding_state import (
    EntityEmbeddingStateRepository,
)
from messaging.kafka.schema_paths import get_schema_path  # type: ignore[import-untyped]
from observability import get_logger  # type: ignore[import-untyped]

# Topic name constant — avoid importing from messaging.topics to sidestep
# version-skew attr-defined errors when the installed package predates the
# ENTITY_CANONICAL_CREATED constant (added in later revision).
_ENTITY_CANONICAL_CREATED_TOPIC = "entity.canonical.created.v1"

_ENTITY_CANONICAL_CREATED_SCHEMA_PATH = get_schema_path("entity.canonical.created.v1.avsc")
_ENTITY_DIRTIED_SCHEMA_PATH = get_schema_path("entity.dirtied.v1.avsc")

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from knowledge_graph.application.ports.market_data_lookup_port import MarketDataLookupPort
    from knowledge_graph.infrastructure.llm.fallback_chain import FallbackChainClient

logger = get_logger(__name__)  # type: ignore[no-any-return]

_EXTRACT_MODEL_ID = "kg-entity-profile-v1"

# Canonical entity types matching the DB CHECK constraint installed by
# migration 0039 (``ck_canonical_entities_entity_type``).  Any value that
# does NOT appear in this frozenset is remapped to ``"unknown"`` below.
_VALID_ENTITY_TYPES: frozenset[str] = frozenset(
    {
        "financial_instrument",
        "person",
        "event",
        "sector",
        "industry",
        "macro_indicator",
        "place",
        "product",
        "index",
        "exchange",  # FR-12: stock exchanges / trading venues (NYSE, NASDAQ, LSE)
        "organization",  # FR-12: tickerless private companies / agencies / non-profits / institutions
        "currency",
        "unknown",
    },
)

# FR-12 — coarse "company-ish" GLiNER/legacy classes that the alias map below
# resolves to ``financial_instrument``.  When such a class arrives on the
# NO-ENRICH fallback path (the LLM omitted ``entity_type`` so we fell back to the
# raw mention_class) and there is NO ticker, the row is almost always NOT a
# tradable instrument — it is an exchange, a private company, a foundation, or a
# generic phrase ("Nvidia shares").  74% of live ``financial_instrument`` rows
# were tickerless mislabels minted exactly this way.  We therefore downgrade
# these tickerless rows to ``unknown`` instead of trusting the FI alias.
_COMPANY_CLASS_ALIASES: frozenset[str] = frozenset(
    {
        "company",
        "corp",
        "corporation",
        "enterprise",
        "firm",
        "business",
        "inst",
        "institution",
    },
)

# Map legacy or LLM-invented aliases to a canonical type.
# Migration 0039 defines the authoritative remap for DB values; this dict
# mirrors that mapping for values that arrive via the LLM extraction path
# before they ever reach the DB.
_ENTITY_TYPE_ALIASES: dict[str, str] = {
    # company → financial_instrument (mirrors migration 0039 "company-with-ticker"
    # path; we don't have ticker availability here so we always use FI as the
    # closest canonical type for a named company).
    "company": "financial_instrument",
    "corp": "financial_instrument",
    "corporation": "financial_instrument",
    "enterprise": "financial_instrument",
    "firm": "financial_instrument",
    "business": "financial_instrument",
    # 'organization'/'organisation' → 'organization' (FR-12 / migration 0055):
    # there is now a dedicated canonical type for tickerless companies, agencies,
    # NGOs, and non-profits, so we map to it directly instead of dumping to
    # 'unknown'. The ENTITY_PROFILE prompt v2.2 also emits 'organization' for these.
    "organization": "organization",
    "organisation": "organization",
    # 'inst'/'institution' → 'organization': an institution (university, research
    # firm, agency) is an organisation, NOT a tradeable instrument (FR-12).
    "inst": "organization",
    "institution": "organization",
    "regulator": "organization",  # regulators (SEC, Fed) are organisations, not instruments
    "agency": "organization",  # government agencies / bodies
    "nonprofit": "organization",
    "non_profit": "organization",
    "foundation": "organization",
    "ngo": "organization",
    "university": "organization",
    # country/location → place (migration 0039 §2b; GLiNER uses 'location' not 'country')
    "country": "place",
    "nation": "place",
    "region": "place",
    "location": "place",
    # other legacy values
    "other": "unknown",
    "concept": "unknown",
    # commodity → product (F-009: commodities like gold/oil are physical products)
    "commodity": "product",
    # fund is a tradable financial product
    "fund": "financial_instrument",
    # macro_indicator is canonical; alias kept for older prompt variants that
    # emitted it as "macro indicator" (with space → underscore normalisation
    # already applied before this dict is consulted).
}


# ── FR-11 — generic finance suffixes for the token-superset dedup fallback ───────
# A ticker-less mention like "SpaceX shares" / "SpaceX stock" / "SpaceX Class A
# common stock" denotes the SAME entity as an existing "SpaceX" canonical, but the
# 0.75 trigram pre-lookup misses (sim 0.54-0.58 < 0.75) and a fresh duplicate is
# minted (root cause of FR-11 / the SpaceX 8-row cluster).  Stripping these
# boilerplate suffixes from the END of the incoming name and retrying an EXACT
# normalised-alias match folds the variant into the existing canonical.  Kept
# conservative — only unambiguous corporate/security boilerplate tokens — and
# longest-first so multi-word suffixes are removed before their single-word parts.
_FR11_GENERIC_SUFFIXES: tuple[str, ...] = (
    "class a common stock",
    "class b common stock",
    "class c common stock",
    "common stock",
    "ordinary shares",
    "preferred stock",
    "class a",
    "class b",
    "class c",
    "shares",
    "stock",
    "equity",
    "holdings",
    "holding",
    "adr",
)


def _strip_generic_suffixes(normalized_name: str) -> str:
    """Iteratively strip trailing generic finance suffixes from a normalised name.

    ``normalized_name`` is expected already lower-cased + whitespace-collapsed.
    Returns the boilerplate-free stem (e.g. "spacex shares" → "spacex").  Never
    strips a suffix that is the WHOLE name (so "shares" alone is preserved).
    """
    s = normalized_name
    changed = True
    while changed:
        changed = False
        for suf in _FR11_GENERIC_SUFFIXES:
            if s != suf and s.endswith(" " + suf):
                s = s[: -(len(suf) + 1)].strip()
                changed = True
                break
    return s


def _build_dirtied_event(entity_id: UUID, dirty_reason: str = "profile_updated", *, event_id: UUID) -> bytes:
    """Build a fully-populated entity.dirtied.v1 Confluent-Avro payload.

    B-3 fix: previously callers emitted ``{"entity_id": "<uuid>"}`` which is
    missing ``event_id``, ``event_type``, ``schema_version``, ``occurred_at``,
    and ``dirty_reason`` — all required by the Avro schema at
    ``infra/kafka/schemas/entity.dirtied.v1.avsc``.

    PLAN-0062 R28 fix: migrated from json.dumps to serialize_confluent_avro so
    that entity.dirtied.v1 uses the Confluent 5-byte wire-format header,
    consistent with all other producer paths.
    """
    from messaging.kafka.serialization_utils import serialize_confluent_avro  # type: ignore[import-untyped]

    return serialize_confluent_avro(
        _ENTITY_DIRTIED_SCHEMA_PATH,
        {
            "event_id": str(event_id),
            "event_type": "entity.dirtied",
            "schema_version": 1,
            "occurred_at": utc_now().isoformat(),
            "entity_id": str(entity_id),
            "dirty_reason": dirty_reason,
            "source_doc_id": None,
            "correlation_id": None,
        },
    )


def resolve_canonical_entity_type(
    raw_type: str | None,
    *,
    ticker: str | None = None,
    tickerless_company_fallback: str = "unknown",
) -> str:
    """Normalise an LLM/GLiNER-emitted type string to a canonical entity_type.

    Shared, side-effect-free type-resolution logic extracted so both the
    provisional-enrichment persist path and the periodic re-typing sweep
    (Worker 13K — ``EntityRetypeWorker``) apply IDENTICAL rules and can never
    diverge on what a raw type maps to.

    Rules (mirrors the inline logic in :func:`persist_enrichment`):
      1. lower/strip/underscore-normalise ``raw_type``.
      2. remap via :data:`_ENTITY_TYPE_ALIASES`.
      3. any value not in :data:`_VALID_ENTITY_TYPES` collapses to ``"unknown"``.
      4. FR-12 tickerless-company hardening: a coarse ``company``-class value
         (company/corp/firm/…) that resolved to ``financial_instrument`` but
         carries NO ticker is almost never a tradable instrument.  In the
         provisional path such rows are downgraded to ``"unknown"``; the
         re-typing sweep passes ``tickerless_company_fallback="organization"``
         because these are already-named entities we are explicitly trying to
         TYPE (leaving them ``unknown`` would be a no-op), and a tickerless
         company IS an ``organization`` (FR-12 canonical type).

    ``ticker`` should already be normalised (bare symbol) by the caller.
    """
    _norm_type = (raw_type or "unknown").lower().strip().replace(" ", "_")
    entity_type = _ENTITY_TYPE_ALIASES.get(_norm_type, _norm_type)
    if entity_type not in _VALID_ENTITY_TYPES:
        entity_type = "unknown"
    if entity_type == "financial_instrument" and not ticker and _norm_type in _COMPANY_CLASS_ALIASES:
        entity_type = tickerless_company_fallback
    return entity_type


async def extract_entity_profile(
    llm_client: FallbackChainClient,
    mention_text: str,
    mention_class: str,
    context_snippet: str,
) -> dict[str, Any] | None:
    """Call the extraction LLM to produce a structured entity profile.

    No DB session needed — pure HTTP call via FallbackChainClient.

    Returns a dict with keys: canonical_name, entity_type, ticker, isin, aliases.
    Returns None if the LLM chain fails or returns an empty result.

    DEF-003/020 (BP-398): context_snippet originates from external article content
    and must be truncated and XML-delimited before reaching the LLM prompt
    constructor.  Without this guard an adversarial headline can inject LLM
    instructions and corrupt entity profiles (indirect prompt injection).
    """
    from ml_clients.dataclasses import ExtractionInput  # type: ignore[import-untyped]
    from prompts.knowledge.entity_profile import ENTITY_PROFILE  # type: ignore[import-untyped]

    # Truncate to 500 chars then wrap in an XML delimiter so the LLM treats
    # this block as data, not as instructions.  The XML tag creates a structural
    # boundary that prevents the external content from "bleeding" into the
    # surrounding prompt text even if it contains injection payloads.
    _safe_context = f"<article_context>{context_snippet[:500]}</article_context>"

    inp = ExtractionInput(
        prompt=ENTITY_PROFILE.render(name=mention_text, entity_class=mention_class),
        context=_safe_context,
        output_schema={
            "canonical_name": "string",
            "entity_type": "string",
            "ticker": "string|null",
            "isin": "string|null",
            "aliases": "list[string]",
        },
        model_id=_EXTRACT_MODEL_ID,
    )
    result = await llm_client.extract(inp, entity_id=None)
    if result is None:
        return None
    return result.result  # type: ignore[return-value]


async def compute_embedding(
    llm_client: FallbackChainClient,
    entity_id: UUID | None,
    source_text: str,
    embed_model_id: str,
) -> list[float] | None:
    """Compute a definition embedding via the LLM chain.

    No DB session needed — pure HTTP call (ARCH-003).
    """
    from ml_clients.dataclasses import EmbeddingInput  # type: ignore[import-untyped]

    inp = EmbeddingInput(text=source_text, model_id=embed_model_id)
    outputs = await llm_client.embed([inp], entity_id=entity_id)
    return outputs[0].embedding if outputs else None


async def persist_enrichment(
    session: AsyncSession,
    queue_id: UUID,
    mention_text: str,
    profile: dict[str, Any],
    embedding: list[float] | None = None,
    embed_model_id: str = "bge-large:latest",
    market_data_lookup: MarketDataLookupPort | None = None,
) -> UUID | None:
    """Persist an LLM-extracted entity profile to intelligence_db.

    Performs all DB writes for a single provisional entity:
      - canonical_entities INSERT
      - entity_aliases INSERTs (mechanical + LLM with collision check)
      - entity_embedding_state rows
      - embedding upsert (if provided)
      - relation_evidence_raw provisional flag clear
      - entity.canonical.created.v1 outbox entry

    Session-only with ONE strictly-bounded exception: when ``market_data_lookup``
    is supplied AND the profile is a tradable instrument (``entity_type ==
    'financial_instrument'`` AND a ticker is present), we issue ONE HTTP GET
    to S2 to discover the existing ``instrument_id``.  This is the M-017
    enforcement point (PRD-0089 F2 §4.3): when S2 already owns an instrument
    row for this ticker the canonical entity MUST share that UUID so the two
    databases stay in lock-step.  When S2 returns 404 we cannot promote yet,
    so we return ``None`` to signal the caller to defer (the worker's
    ``_apply_retry`` then increments retry_count + sets next_retry_at; rows
    that cross ``max_retries`` transition to terminal status='failed').
    The lookup runs BEFORE any DB writes so the deferral path is side-effect
    free.

    ARCH-003 note: persist_enrichment was previously billed as "session-only,
    no external HTTP".  The S2 lookup is the deliberate, narrow exception
    introduced by F2; it is bounded to a sub-second DB-backed call (S2 lookup
    timeout is 5 s) and runs synchronously before the session is touched, so
    no session is held during the HTTP call.
    """
    from sqlalchemy import text

    from knowledge_graph.infrastructure.intelligence_db.repositories.canonical_entity import (
        CanonicalEntityRepository,
    )
    from knowledge_graph.infrastructure.intelligence_db.repositories.entity_alias import (
        EntityAliasRepository,
    )
    from knowledge_graph.infrastructure.intelligence_db.repositories.outbox import (
        OutboxRepository,
    )
    from messaging.kafka.serialization_utils import serialize_confluent_avro  # type: ignore[import-untyped]

    canonical_name: str = profile.get("canonical_name") or mention_text

    # Clamp ticker/isin to DB column widths (varchar(20)); discard if malformed.
    # Qwen3.5-0.8B occasionally returns oversized values despite prompt instructions.
    # NOTE: ticker is parsed BEFORE entity_type so the FR-12 tickerless-company
    # downgrade below can consult it.
    _ticker_raw: str | None = profile.get("ticker")
    # 2026-06-15 entity-matching fix: collapse provider exchange suffixes
    # (e.g. ``AAPL.MX`` / ``NVDA.US``) to the bare symbol BEFORE any lookup or
    # write, so the ticker we query in M-017 anchoring and the BP-459 ticker
    # dedup pre-lookup is the same bare symbol the canonical row already owns.
    # Without this, ``AAPL.MX`` never matched ``AAPL`` and minted a duplicate
    # tickerless canonical.  Share classes (``BRK.A``) and preferred shares
    # (``JPM.PRM``) are deliberately preserved by the allowlist helper.
    _ticker_stripped: str | None = strip_exchange_qualifier(_ticker_raw)
    ticker: str | None = _ticker_stripped[:20] if _ticker_stripped else None

    # ── entity_type resolution + FR-12 tickerless-company hardening ──────────
    # The LLM may omit entity_type; we then fall back to the raw GLiNER
    # mention_class.  ``_norm_type`` is the normalised source value; ``entity_type``
    # is its canonical mapping via the alias table.
    _raw_type: str = profile.get("entity_type") or str(profile.get("mention_class", "unknown"))
    _norm_type = _raw_type.lower().strip().replace(" ", "_")
    entity_type = _ENTITY_TYPE_ALIASES.get(_norm_type, _norm_type)
    if entity_type not in _VALID_ENTITY_TYPES:
        logger.warning(  # type: ignore[no-any-return]
            "provisional_enrichment_invalid_entity_type",
            raw_type=_raw_type,
            mention_text=mention_text,
            defaulting_to="unknown",
        )
        entity_type = "unknown"
    # FR-12: a coarse "company"-class mention (company/corp/firm/...) only maps to
    # ``financial_instrument`` via the alias table.  Without a ticker that mapping
    # is almost always wrong — it is the exact path that minted NYSE, SpaceX,
    # foundations, and "X shares" phrases as instruments (74% of FI rows were
    # tickerless).  Reserve ``financial_instrument`` for rows that carry a ticker
    # (or were explicitly LLM-typed to a non-company canonical value); downgrade
    # tickerless company-class fallbacks to ``unknown``.
    if entity_type == "financial_instrument" and ticker is None and _norm_type in _COMPANY_CLASS_ALIASES:
        logger.info(  # type: ignore[no-any-return]
            "provisional_enrichment_tickerless_company_downgraded",
            raw_type=_raw_type,
            mention_text=mention_text,
            downgraded_to="unknown",
        )
        entity_type = "unknown"
    _isin_raw: str | None = profile.get("isin")
    # Standard ISIN = exactly 12 alphanumeric chars; anything else is a hallucination.
    import re as _re

    isin: str | None = _isin_raw if (_isin_raw and _re.fullmatch(r"[A-Z0-9]{12}", _isin_raw)) else None
    if _isin_raw and isin is None:
        logger.warning(  # type: ignore[no-any-return]
            "provisional_enrichment_isin_discarded",
            isin_raw=_isin_raw,
            entity=canonical_name,
        )

    # ── PRD-0089 F2 §4.3 — M-017 enforcement for tradable provisional entities ──
    # When the LLM has classified this provisional as a tradable instrument AND
    # produced a ticker, we MUST anchor the canonical entity_id on the existing
    # market_data.instruments.id rather than minting a fresh UUID. This is the
    # cross-database invariant the F2 wave introduces:
    #     canonical_entities.entity_id == instruments.id
    # for every row with entity_type='financial_instrument'.
    #
    # When S2 already has the instrument row we capture the UUID and pass it
    # to ``create_or_get`` below. When S2 does NOT have a row yet, we cannot
    # promote without violating M-017, so we return ``None`` to signal the
    # caller to defer (worker's _apply_retry then increments retry_count and
    # writes next_retry_at; rows that cross max_retries transition to terminal
    # status='failed', which is the project's DLQ convention for the queue —
    # we deliberately reuse the existing terminal state rather than adding a
    # new ``provisional_entity_dlq`` Kafka topic because the queue table is
    # already operator-visible via the /admin/dlq endpoints.)
    #
    # Why this position: ticker normalisation has happened above, so the
    # uppercase ticker we look up is the same one we'd write to the canonical
    # row. Why before fuzzy pre-lookup: an existing instrument_id is the
    # strongest possible signal — it short-circuits the trigram match because
    # a successful S2 lookup is an exact-by-construction match.
    forced_entity_id: UUID | None = None
    if market_data_lookup is not None and entity_type == "financial_instrument" and ticker:
        instrument_ref = await market_data_lookup.lookup_instrument_by_ticker(ticker)
        if instrument_ref is None:
            # S2 has no instrument row for this ticker yet. The market-data
            # ingestion pipeline (S4) may still be discovering it (via EODHD,
            # SnapTrade, etc.). Returning None signals the worker to call
            # _apply_retry which:
            #   - increments retry_count (capped at max_retries)
            #   - schedules next_retry_at via exponential backoff
            #   - transitions status='failed' when retry_count reaches max
            # The row stays addressable to ops via the /admin/dlq endpoints
            # so a stuck instrument can be diagnosed and resolved manually.
            logger.info(  # type: ignore[no-any-return]
                "provisional_enrichment_deferred_instrument_absent",
                ticker=ticker,
                canonical_name=canonical_name,
                queue_id=str(queue_id),
                reason="s2_instrument_missing",
            )
            return None
        forced_entity_id = instrument_ref.instrument_id
        logger.info(  # type: ignore[no-any-return]
            "provisional_enrichment_anchored_on_instrument",
            ticker=ticker,
            instrument_id=str(forced_entity_id),
            queue_id=str(queue_id),
        )

    # QA-iter1 (PLAN-0062 SA-005 fix): pre-validate the Avro payload BEFORE any
    # DB writes.  The polling worker (provisional_enrichment.py) commits the
    # batch session in a finally-style block — if serialize_confluent_avro
    # raised AFTER the canonical-entity INSERT it would orphan the entity row
    # without an outbox event (DB committed, no Kafka event ever produced).
    # By serializing first we either fail-fast (no DB writes) or have valid
    # bytes ready when the outbox INSERT runs at the end of this function.
    entity_id_str = str(new_uuid7())
    canonical_created_event_id = new_uuid7()  # type: ignore[no-any-return]
    avro_record: dict[str, Any] = {
        "event_id": str(canonical_created_event_id),
        "event_type": "entity.canonical.created",
        "schema_version": 1,
        "occurred_at": utc_now().isoformat(),
        "entity_id": entity_id_str,
        "canonical_name": canonical_name,
        "entity_type": entity_type,
        "provisional_queue_id": str(queue_id),
        "alias_texts": [canonical_name, *([ticker.upper()] if ticker else []), *([isin.upper()] if isin else [])],
        "correlation_id": None,
    }
    avro_payload_bytes = serialize_confluent_avro(_ENTITY_CANONICAL_CREATED_SCHEMA_PATH, avro_record)

    # ── Ticker-equality pre-lookup — BP-459 hard dedup key (PLAN-0111) ───────
    # ROOT CAUSE (2026-06-12): the news/provisional promotion path and the
    # market-data instrument-seeding path (instrument_consumer) each mint a
    # canonical_entity for the SAME ticker without ever consulting the OTHER's
    # row.  None of the existing guards key on the ticker:
    #   - ``create_or_get``'s ON CONFLICT is ``lower(canonical_name)`` AND its
    #     partial index *excludes* entity_type='financial_instrument' entirely,
    #     so two SHEL instruments never conflict on name.
    #   - the fuzzy pre-lookup below keys on ``canonical_name`` trigram
    #     similarity, so "NYSE:PG" / "Procter and Gamble" / "Shell Plc" never
    #     dedup against "Shell PLC ADR" / "The Procter & Gamble Company".
    #   - M-017 anchoring (above) only fires when ``market_data_lookup`` is
    #     supplied AND S2 already owns the instrument; the historical SHEL
    #     "Shell Plc" was promoted BEFORE the ADR instrument existed, so it
    #     minted a fresh ticker-bearing canonical.
    # Result: 451 tickers with duplicate canonicals / 593 excess rows (live
    # count 2026-06-12).
    #
    # FIX: for a tradable instrument WITH a ticker, the ticker is the single
    # strongest identity key.  Before any name-based work, look up an existing
    # financial_instrument canonical that already owns this exact ticker and
    # REUSE it.  This makes the ticker a hard dedup key across BOTH minting
    # pipelines (the instrument_consumer path gets the symmetric guard).  We
    # run this AFTER M-017 anchoring (a successful S2 lookup is an even stronger,
    # exact-by-construction match) and AFTER ticker normalization so the value
    # we query is the value we'd write.  When ``forced_entity_id`` was already
    # resolved by M-017 we skip this — the anchored UUID wins.
    if forced_entity_id is None and entity_type == "financial_instrument" and ticker:
        existing_by_ticker = await CanonicalEntityRepository(session).find_by_ticker(ticker)
        if existing_by_ticker is not None:
            reused_id = UUID(str(existing_by_ticker["entity_id"]))
            logger.info(  # type: ignore[no-any-return]
                "provisional_entity_deduplicated_by_ticker",
                mention_text=mention_text,
                canonical_name=canonical_name,
                ticker=ticker,
                matched_entity_id=str(reused_id),
                matched_name=existing_by_ticker.get("canonical_name"),
            )
            return reused_id

    # ── ORG→FI fold — resolver leak guard (2026-07 KG dedup audit) ───────────
    # ROOT CAUSE: every FI-dedup guard above is gated on
    # ``entity_type == 'financial_instrument'`` (M-017 anchoring, the BP-459
    # ticker pre-lookup).  GLiNER tags public companies (Apple/Tesla/Nvidia) as
    # ``organization``, and the design intent (nlp-pipeline
    # ``entity_resolution.py``) is that the ``financial_instrument`` row IS the
    # canonical for a public company — an org-class mention must resolve TO it,
    # never mint a second canonical.  But an ``organization``-classed provisional
    # promotes straight past those guards: the fuzzy pre-lookup below scores
    # "Apple" vs alias "apple inc." at ~0.55 (< 0.75), the FR-11 fold only reuses
    # a SAME-``entity_type`` match, and ``create_or_get``'s partial unique index
    # excludes financial_instrument rows — so a fresh ORG canonical is inserted
    # alongside the FI, splitting relations across two nodes (audit: 65 org↔FI
    # duplicates; ~16% of relations hung off the wrong node).
    #
    # FIX: for an ``organization`` provisional, look up the FI that already owns
    # this company by exact ticker OR exact normalized canonical_name and REUSE
    # its entity_id.  This is the symmetric cross-type guard the FI paths never
    # had.  We run it AFTER the FI-only ticker pre-lookup (so a genuine FI still
    # dedups against FIs) and BEFORE the fuzzy/name folds (an FI identity match
    # is stronger than a trigram guess).  Only ``organization`` is folded — the
    # exact duplicate class — so we never collapse a person/place/product/sector
    # into an instrument.  The normalization SQL is shared verbatim with the
    # cleanup migration so the guard and the backfill can never disagree.
    if entity_type == "organization":
        fi_entity_id = await CanonicalEntityRepository(session).find_financial_instrument_for_company(
            ticker=ticker,
            canonical_name=canonical_name,
        )
        if fi_entity_id is not None:
            logger.info(  # type: ignore[no-any-return]
                "provisional_org_folded_into_financial_instrument",
                mention_text=mention_text,
                canonical_name=canonical_name,
                ticker=ticker,
                matched_fi_entity_id=str(fi_entity_id),
            )
            # Reuse the FI canonical — skip all DB writes and return early. The
            # caller updates provisional_entity_queue.assigned_entity_id to the FI.
            return fi_entity_id

    # ── Fuzzy pre-lookup — BP-459 provisional entity deduplication ───────────
    # ``create_or_get`` handles exact-name conflicts atomically via ON CONFLICT,
    # but the unique index only triggers when ``lower(canonical_name)`` matches
    # exactly.  When the LLM returns a slight variation of an already-canonical
    # name (e.g. "Amazon Business" for an entity we already have as "Amazon Inc.")
    # no conflict fires, and a new duplicate row is inserted.
    #
    # The fuzzy pre-lookup uses pg_trgm trigram similarity against the
    # entity_aliases table.  A sim ≥ 0.75 threshold safely separates
    # abbreviation/punctuation differences (e.g. "apple inc." vs "apple inc"
    # scores ~0.95 → reuse) from genuinely different entities (e.g. "amazon
    # business" vs "amazon inc." scores ~0.55 → create new).
    #
    # WHY this position: we run after entity_type normalization so the
    # canonical_name we look up is the name we'd actually write to the DB.
    # WHY not inside create_or_get: fuzzy search crosses table boundaries
    # (entity_aliases) whereas create_or_get is scoped to canonical_entities.
    alias_repo_prelookup = EntityAliasRepository(session)
    lookup_name = canonical_name.lower().strip()
    fuzzy_matches = await alias_repo_prelookup.fuzzy_search(lookup_name, limit=3)

    existing_entity_id: UUID | None = None
    for match in fuzzy_matches:
        sim = float(match["similarity"])  # type: ignore[arg-type]
        if sim >= 0.75:
            existing_entity_id = UUID(str(match["entity_id"]))
            logger.info(  # type: ignore[no-any-return]
                "provisional_entity_deduplicated",
                mention_text=mention_text,
                canonical_name=canonical_name,
                matched_entity_id=str(existing_entity_id),
                similarity=sim,
            )
            break

    if existing_entity_id is not None:
        # Reuse the existing entity — skip all DB writes and return early.
        # The caller (ProvisionalEnrichmentWorker / ProvisionalQueuedConsumer)
        # will update provisional_entity_queue with this entity_id.
        return existing_entity_id

    # ── FR-11 token-superset fallback — close the SpaceX-class miss ───────────
    # The 0.75 trigram pre-lookup above misses ticker-less variants that are an
    # existing canonical's name PLUS a generic finance suffix ("SpaceX shares" /
    # "SpaceX stock" / "SpaceX Class A common stock"): their trigram against
    # "spacex" is 0.54-0.58, below 0.75, so each minted a fresh duplicate (the
    # FR-11 root cause).  Here we strip those suffixes from the incoming name and
    # retry an EXACT normalised-alias match.  We ONLY act when the strip actually
    # shortened the name (so this is a no-op for names without a generic suffix)
    # and when the matched existing canonical is the SAME entity_type — never
    # collapse across types (e.g. a "product" must not fold into a
    # "financial_instrument").  This is a DISTINCT block, intentionally placed
    # AFTER the ticker pre-lookup and the trigram pre-lookup so it only runs on
    # their miss; it adds no new infrastructure (reuses the alias EXACT lookup).
    stripped_name = _strip_generic_suffixes(lookup_name)
    if stripped_name and stripped_name != lookup_name:
        superset_match = await alias_repo_prelookup.find_exact(stripped_name)
        # find_exact returns the matched entity_id; confirm same entity_type via
        # the canonical_entities row before reusing it (cross-type guard).
        if superset_match is not None:
            matched_id = UUID(str(superset_match["entity_id"]))
            matched_row = await CanonicalEntityRepository(session).get_by_id(matched_id)
            if matched_row is not None and matched_row.entity_type == entity_type:
                logger.info(  # type: ignore[no-any-return]
                    "provisional_entity_deduplicated_by_name_superset",
                    mention_text=mention_text,
                    canonical_name=canonical_name,
                    stripped_name=stripped_name,
                    matched_entity_id=str(matched_id),
                    matched_name=matched_row.canonical_name,
                )
                return matched_id

    # ── Atomic dedup INSERT (DEF-014 / BP-384 — replaces find_exact race) ──
    # Migration 0026 added a UNIQUE INDEX on lower(canonical_name).  ``create_or_get``
    # issues an atomic INSERT ... ON CONFLICT DO NOTHING and re-SELECTs on conflict.
    # When ``was_created=False`` we skip alias inserts, embedding, and outbox.
    entity_repo = CanonicalEntityRepository(session)
    # F2 §4.3: when ``forced_entity_id`` is set, S2 already owns an instrument
    # row for this ticker — we MUST reuse that UUID so canonical_entities and
    # market_data.instruments stay aligned (invariant M-017). ``create_or_get``
    # accepts ``entity_id`` directly and routes through an alternate INSERT that
    # explicitly binds the value; on conflict the existing row is fetched, so
    # the (rare) case where the row was independently inserted by another
    # consumer is still idempotent.
    entity_id, was_created = await entity_repo.create_or_get(  # type: ignore[attr-defined]
        canonical_name=canonical_name,
        entity_type=entity_type,
        ticker=ticker,
        isin=isin,
        entity_id=forced_entity_id,
    )
    if not was_created:
        logger.info(  # type: ignore[no-any-return]
            "provisional_enrichment_entity_deduped",
            canonical_name=canonical_name,
            existing_entity_id=str(entity_id),
            entity_deduped=True,
        )
        # Return the existing entity_id; the caller (ProvisionalEnrichmentWorker
        # / ProvisionalQueuedConsumer) will update provisional_entity_queue.
        # No new outbox event needed — entity already exists and is reachable.
        return entity_id
    # The repo generates its own UUIDv7 — re-serialize with the actual entity_id
    # to keep the outbox bytes consistent with the DB row.  This second
    # serialize_confluent_avro call uses an identical record shape, so it is
    # equally safe to fail before any further DB work.
    avro_record["entity_id"] = str(entity_id)
    avro_payload_bytes = serialize_confluent_avro(_ENTITY_CANONICAL_CREATED_SCHEMA_PATH, avro_record)

    alias_repo = EntityAliasRepository(session)
    normalized_name = canonical_name.lower().strip()
    await alias_repo.insert(entity_id, canonical_name, normalized_name, "EXACT", "provisional_enrichment")

    if ticker:
        await alias_repo.insert(entity_id, ticker, ticker.upper(), "TICKER", "provisional_enrichment")
    if isin:
        await alias_repo.insert(entity_id, isin, isin.upper(), "ISIN", "provisional_enrichment")

    llm_aliases: list[str] = profile.get("aliases") or []
    for alias in llm_aliases[:5]:
        normalized = alias.lower().strip()
        existing = await alias_repo.find_exact(normalized)
        if existing and existing["entity_id"] != entity_id:
            logger.warning(  # type: ignore[no-any-return]
                "provisional_enrichment_alias_collision",
                alias=alias,
                existing_entity_id=str(existing["entity_id"]),
                new_entity_id=str(entity_id),
            )
            continue
        await alias_repo.insert(entity_id, alias, normalized, "LLM", "provisional_enrichment")

    emb_repo = EntityEmbeddingStateRepository(session)
    await emb_repo.ensure_rows_exist(entity_id, entity_type)

    if canonical_name and embedding is not None:
        await _write_embedding(entity_id, canonical_name, embedding, emb_repo, embed_model_id)

    # PLAN-0088 Wave I fix: the original DEF-021 patch referenced
    # subject_provisional_id / object_provisional_id columns that do not exist
    # on relation_evidence_raw — only a single provisional_queue_id column was
    # ever shipped (see migration 0038 schema). The dual-column "DEF-021"
    # claim was aspirational; entity_consumer._unblock_provisional_evidence()
    # actually uses the single-column pattern. This worker now mirrors that
    # pattern so promotion no longer crashes with UndefinedColumn at runtime.
    #
    # Trade-off: when both endpoints of an evidence row are provisional, both
    # subject_entity_id and object_entity_id are overwritten with the same
    # canonical id. This is the same behaviour entity_consumer already
    # produces; correcting it requires a schema extension tracked separately.
    await session.execute(
        text("""
UPDATE relation_evidence_raw
SET entity_provisional = false,
    subject_entity_id  = CASE
        WHEN provisional_queue_id = :queue_id THEN :entity_id
        ELSE subject_entity_id
    END,
    object_entity_id   = CASE
        WHEN provisional_queue_id = :queue_id THEN :entity_id
        ELSE object_entity_id
    END
WHERE provisional_queue_id = :queue_id
  AND entity_provisional   = true
"""),
        {"entity_id": str(entity_id), "queue_id": str(queue_id)},
    )

    outbox_repo = OutboxRepository(session)
    # QA-iter1 (PLAN-0062): payload bytes were pre-serialized at the top of
    # this function — the call there fails-fast if the record dict is invalid,
    # preventing partial DB state without an outbox row (BP-313 / SA-005).
    await outbox_repo.append(
        topic=_ENTITY_CANONICAL_CREATED_TOPIC,
        partition_key=str(entity_id),
        payload_avro=avro_payload_bytes,
        event_id=canonical_created_event_id,
    )

    return entity_id  # type: ignore[no-any-return]


async def _write_embedding(
    entity_id: UUID,
    source_text: str,
    embedding: list[float] | None,
    emb_repo: EntityEmbeddingStateRepository,
    embed_model_id: str,
) -> None:
    """Write a pre-computed embedding vector to entity_embedding_state (session-only)."""
    from datetime import timedelta

    from knowledge_graph.infrastructure.intelligence_db.repositories.entity_embedding_state import (
        VIEW_DEFINITION,
        sha256_hex,
    )

    await emb_repo.upsert(
        entity_id,
        VIEW_DEFINITION,
        embedding=embedding,
        model_id=embed_model_id if embedding else None,
        source_text=source_text,
        source_hash=sha256_hex(source_text),
        next_refresh_at=utc_now() + timedelta(days=90),  # type: ignore[no-any-return, operator]
    )


async def apply_retry_transition(
    session: AsyncSession,
    queue_id: UUID,
    max_retries: int,
    base_retry_minutes: int = 2,
    max_retry_minutes: int = 1440,
) -> bool:
    """Atomically increment retry_count and decide terminal state in one SQL round-trip.

    The DB authoritatively reads the current ``retry_count`` and computes the
    new status with a SQL ``CASE`` expression, so we never depend on a stale
    caller-supplied count.  ``RETURNING (status = 'failed')`` exposes the outcome
    to Python so the caller can increment the appropriate Prometheus counter.

    Returns True if the row was transitioned to 'failed' (terminal), False if it
    was reset to 'pending' for another attempt.

    This function does NOT increment ``s7_provisional_enrichment_failed_total`` —
    callers that need the counter (the worker's ``_apply_retry``) must check
    the return value and call ``inc()`` themselves so existing test patch paths
    are preserved.

    DEF-033 — exponential backoff:
      Computes ``next_retry_at = utc_now() +
      min(base_retry_minutes * 2 ** retry_count, max_retry_minutes)`` minutes
      and persists it alongside the retry_count increment.  The Phase-1 SELECT
      filters rows on ``next_retry_at IS NULL OR next_retry_at <= now()`` so
      this row is excluded from ``claim_batch`` until the deadline elapses.

      ``retry_count`` here is the *current* DB value (before the increment) —
      using the post-increment value would make the very first failure wait
      ``2 * 2^1 = 4`` minutes instead of the intended 2 minutes.  We read it
      back from the row inside the CTE so the formula is consistent across
      concurrent workers regardless of which one wins the UPDATE race.

      ``base_retry_minutes`` and ``max_retry_minutes`` default to the worldview
      production values so existing test fixtures (which only pass
      ``max_retries``) keep working without modification.
    """

    from sqlalchemy import text

    # Compute next_retry_at in Python (not SQL) so tests can drive the
    # backoff window deterministically by patching ``common.time.utc_now``
    # and so the value is testable against a known baseline.  We use the
    # SQL CASE on retry_count to derive the backoff multiplier for the
    # *current* row state: this avoids a separate SELECT round-trip while
    # still letting Python clamp the result to ``max_retry_minutes``.
    #
    # Single round-trip pattern: we read retry_count via a CTE, compute the
    # backoff in SQL, and apply both updates atomically.  The Python-side
    # parameters bound below are the base / cap.
    result = await session.execute(
        text("""
WITH current AS (
    SELECT retry_count AS rc
    FROM provisional_entity_queue
    WHERE queue_id = :queue_id
      AND status = 'processing'
)
UPDATE provisional_entity_queue AS q
SET retry_count = LEAST(q.retry_count + 1, :max_retries),
    status = CASE
        WHEN q.retry_count + 1 >= :max_retries THEN 'failed'
        ELSE 'pending'
    END,
    next_retry_at = CASE
        -- Failed terminal rows do not need a retry deadline (they will
        -- never be re-claimed) — leave it NULL for clarity.
        WHEN q.retry_count + 1 >= :max_retries THEN NULL
        -- BP-449 fix: explicit CAST(:base_now AS timestamptz) prevents asyncpg
        -- DatatypeMismatchError — the CASE NULL branch makes asyncpg infer
        -- :base_now as interval type from the +interval context without the cast.
        ELSE CAST(:base_now AS timestamptz)
             + (LEAST(
                    :base_minutes * (2 ^ COALESCE((SELECT rc FROM current), 0))::int,
                    :max_minutes
                ) || ' minutes')::interval
    END
WHERE q.queue_id = :queue_id
  AND q.status = 'processing'
RETURNING (q.status = 'failed') AS is_terminal,
          q.retry_count AS new_retry_count,
          q.next_retry_at AS next_retry_at
"""),
        {
            "queue_id": str(queue_id),
            "max_retries": max_retries,
            "base_minutes": base_retry_minutes,
            "max_minutes": max_retry_minutes,
            "base_now": utc_now(),
        },
    )
    row = result.fetchone()
    if row is None:
        # Row no longer exists or was already resolved/noise — nothing to do.
        return False

    # Surface the backoff decision in structured logs so ops can chart
    # retry-storm shape and confirm the cap is firing during outages.
    is_terminal = bool(row[0])
    next_retry_at = row[2] if len(row) >= 3 else None
    backoff_minutes = None
    if next_retry_at is not None:
        # Compute the effective backoff window from the persisted value so
        # the log matches the DB exactly (including Postgres rounding).
        backoff_minutes = max(0, int((next_retry_at - utc_now()).total_seconds() // 60))
    logger.info(  # type: ignore[no-any-return]
        "provisional_enrichment_retry_transition",
        queue_id=str(queue_id),
        is_terminal=is_terminal,
        backoff_minutes=backoff_minutes,
        next_retry_at=next_retry_at.isoformat() if next_retry_at is not None else None,
    )
    return is_terminal
