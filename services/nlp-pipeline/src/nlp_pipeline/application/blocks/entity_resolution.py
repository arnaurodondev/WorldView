"""Block 9 — Entity resolution cascade (PRD §6.7 Block 9).

4-step cascade per PRD §6.7 Block 9:
  1. Exact alias match (confidence 1.0)
  2. Ticker/ISIN match (confidence 0.95)
  3. Fuzzy trigram similarity > 0.75 (confidence = sim * 0.90)
  4. ANN HNSW on entity_embedding_state WHERE view_type='definition'
     (cosine distance < 0.35, clear margin > 0.10, confidence = (1-dist)*0.95)

Resolution thresholds (PLAN-0052 QA-R6 Option C):
  AUTO_RESOLVE  ≥ 0.62 → write entity_mentions.resolved_entity_id
  PROVISIONAL   ≥ 0.45 → INSERT provisional_entity_queue (UNIQUE on surface+class)
  UNRESOLVED    < 0.45 → preserve mention, NEVER discard

Writes mention_resolutions audit trail for every attempted stage.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

import structlog  # type: ignore[import-untyped]

import common.ids  # type: ignore[import-untyped]
from common.tickers import strip_exchange_qualifier  # type: ignore[import-untyped]
from nlp_pipeline.domain.enums import ResolutionOutcome
from nlp_pipeline.domain.models import EntityMention, MentionResolution

if TYPE_CHECKING:
    from ml_clients.protocols import EmbeddingClient  # type: ignore[import-not-found]

    from nlp_pipeline.application.ports.canonical_entity import CanonicalEntityPort
    from nlp_pipeline.infrastructure.intelligence_db.repositories.entity_alias import EntityAliasRepository
    from nlp_pipeline.infrastructure.intelligence_db.repositories.entity_profile_embedding import (
        EntityProfileEmbeddingRepository,
    )
    from nlp_pipeline.infrastructure.nlp_db.repositories.mention_resolution import MentionResolutionRepository

logger = structlog.get_logger(__name__)  # type: ignore[no-any-return]


# ── Stage-2 class gate (2026-07-01 ticker mis-resolution fix) ────────────────
#
# Stage-2 ticker matching is otherwise CLASS-BLIND: it matches any all-caps
# <=6-char surface against ``canonical_entities.ticker`` regardless of what
# GLiNER classified the mention as.  That produced a large systematic
# mis-resolution class where a surface that is a common word/abbreviation
# collides with an unrelated equity ticker, e.g. (live counts, nlp_db):
#   "US"  (currency, 846x) -> a US-ticker equity
#   "DE"  (location, 326x) -> Deere & Company
#   "CEO" (person,    95x) -> China Petroleum / Cooper etc.
#   "MA"  (location,  50x) -> Mastercard Inc
#   "FTC" (regulatory,37x) -> Filtronic Plc
#   "AI"  (macro,       -) -> C3.ai, Inc.
# GLiNER's own class is a HIGH-confidence signal that these tokens are NOT a
# tradeable security, so we suppress Stage-2 ticker resolution for the
# categorically-non-equity classes below.
#
# WHY A DENYLIST (not "reject organization -> financial_instrument"):
#   The earlier deferred fix (agent D, 2026-06-21) keyed the guard off the
#   (mention_class, entity_type) MISMATCH — it rejected an ``organization``
#   mention resolving to a ``financial_instrument`` canonical.  That BREAKS
#   Apple: GLiNER tags "Apple"/"AAPL" as ``organization`` while its canonical
#   row is ``entity_type='financial_instrument'`` — i.e. the legitimate,
#   overwhelmingly-common case.  The correct axis is the mention_class SEMANTIC
#   CATEGORY, not its relationship to the canonical's entity_type.  A currency /
#   location / person / regulator / government body / macro indicator is NEVER a
#   listed equity, so blocking Stage-2 for those classes cannot drop a real
#   company mention.  ``organization`` / ``financial_instrument`` /
#   ``financial_institution`` / ``index`` / ``commodity`` remain ALLOWED, so
#   Apple, Mastercard-as-org, JPM-as-financial_institution, SPY-as-index and
#   the (mislabelled) AAPL-as-commodity mentions all still resolve.
_TICKER_STAGE_DENIED_CLASSES: frozenset[str] = frozenset(
    {
        "currency",
        "location",
        "person",
        "regulatory_body",
        "government_body",
        "macroeconomic_indicator",
    }
)


def _ticker_class_value(mention_class: object) -> str:
    """Return the lowercase enum value for a mention_class (enum or str)."""
    return str(mention_class.value) if hasattr(mention_class, "value") else str(mention_class)


def _ticker_stage_allowed(mention_class: object) -> bool:
    """Whether Stage-2 ticker resolution may run for this GLiNER class.

    Blocks the categorically-non-equity classes (currency/location/person/
    regulatory_body/government_body/macroeconomic_indicator) whose surfaces
    frequently collide with unrelated equity tickers (US/DE/CEO/MA/FTC/AI).
    Company-compatible classes stay allowed so Apple (organization) and peers
    are never regressed.
    """
    return _ticker_class_value(mention_class) not in _TICKER_STAGE_DENIED_CLASSES


def _ticker_candidate(surface: str) -> str | None:
    """Return the ticker symbol to look up for ``surface``, or None if it is not
    ticker-shaped.

    A ticker is an ALL-UPPERCASE symbol of <=6 chars, after stripping a trailing
    ``.EXCHANGE`` venue qualifier (``AAPL.MX`` -> ``AAPL``).

    The case-sensitivity (``isupper()``) is LOAD-BEARING — it is what stops a
    mixed-case company name/acronym (``xAI``, ``Citi``, ``eBay``) from being
    treated as a ticker and colliding with an unrelated security that happens to
    own that ticker (the 2026-06-20 ``xAI`` -> "XAI Octagon ... Trust" fund
    mis-resolution class). ``strip_exchange_qualifier`` preserves case, so a
    mixed-case surface stays mixed-case here and is correctly rejected. Extracted
    into a single helper (used by both the per-mention and batch Stage-2 paths) so
    the guard is testable and cannot silently regress.
    """
    candidate = strip_exchange_qualifier(surface.strip()) or surface.strip()
    if candidate.isupper() and len(candidate) <= 6:
        return candidate
    return None


# ── Resolution thresholds (PRD §6.7 Block 9) ─────────────────────────────────

# PLAN-0052 QA-R6: Option C (threshold 0.72→0.62, multiplier 0.80→0.95).
# Math: at ANN distance 0.325 (Amazon.com vs Amazon.com Inc) the old formula
# gave (1-0.325)*0.80 = 0.54 < 0.72 → unresolved.  New: (1-0.325)*0.95 = 0.641
# > 0.62 → auto-resolves.  Only Stage-4 ANN hits are affected; Stages 1-3 keep
# their fixed 1.0 / 0.95 / fuzzy*0.90 scores which all exceed 0.62 anyway.
AUTO_RESOLVE_THRESHOLD: float = 0.62
PROVISIONAL_THRESHOLD: float = 0.45

# ── Provisional churn guard ───────────────────────────────────────────────────

# Maximum number of provisional rows allowed for the same (normalized_surface,
# mention_class) pair within a rolling 1-hour window.  Noisy NER output (e.g.
# "the company", "the bank") can produce hundreds of duplicate provisional
# inserts per hour — the UNIQUE ON CONFLICT clause deduplicates them at the
# DB level, but the retry_count counter would still be bumped, and the
# savepoint overhead accumulates.  This guard skips even attempting the INSERT
# once 5 rows already exist in the window, reducing unnecessary DB round-trips.
MAX_PROVISIONAL_PER_HOUR: int = 15

# ── Stage confidences ─────────────────────────────────────────────────────────

CONFIDENCE_EXACT: float = 1.0
CONFIDENCE_TICKER_ISIN: float = 0.95
# Stage 2.5 — class-aware canonical_name match (PLAN-0087 F-LLM-001).  We use
# 0.93 (slightly below ticker/isin) because the match is class-typed but
# operates on the human-readable canonical_name, which is a softer signal
# than a deterministic ticker code.  Still well above AUTO_RESOLVE_THRESHOLD
# (0.62) so a hit auto-resolves without further fuzzy/ANN work.
CONFIDENCE_CLASS_AWARE_CANONICAL: float = 0.93
FUZZY_CONFIDENCE_MULTIPLIER: float = 0.90
ANN_CONFIDENCE_MULTIPLIER: float = 0.95

# ── ANN resolution thresholds (PRD §6.7 Block 9 Stage 4) ─────────────────────

ANN_MAX_DISTANCE: float = 0.35
ANN_CLEAR_MARGIN: float = 0.10

# ── Stage implementations ─────────────────────────────────────────────────────


async def _stage1_exact(
    mention: EntityMention,
    alias_repo: EntityAliasRepository,
    audit: list[MentionResolution],
) -> tuple[UUID | None, float]:
    """Stage 1 — exact alias match."""
    entity_id = await alias_repo.exact_match(mention.mention_text)
    audit.append(
        MentionResolution(
            mention_id=mention.mention_id,
            stage=1,
            score=CONFIDENCE_EXACT if entity_id else 0.0,
            is_winner=entity_id is not None,
            candidate_entity_id=entity_id,
            metadata={"method": "exact_alias"},
        ),
    )
    if entity_id:
        return entity_id, CONFIDENCE_EXACT
    return None, 0.0


async def _stage2_ticker_isin(
    mention: EntityMention,
    alias_repo: EntityAliasRepository,
    audit: list[MentionResolution],
) -> tuple[UUID | None, float]:
    """Stage 2 — ticker/ISIN match against canonical_entities."""
    # Attempt to parse ticker from the mention text (bare uppercase word).
    # _ticker_candidate enforces the case-sensitive gate that keeps mixed-case
    # company acronyms (xAI/Citi) from colliding with unrelated tickers.
    # _ticker_stage_allowed additionally suppresses the whole ticker path for
    # categorically-non-equity GLiNER classes (currency/location/person/...),
    # killing the US/DE/CEO/MA/FTC collision class without touching Apple.
    text = mention.mention_text.strip()
    ticker = _ticker_candidate(text) if _ticker_stage_allowed(mention.mention_class) else None
    isin = text if len(text) == 12 and text[:2].isalpha() and text[2:].isalnum() else None

    entity_id = await alias_repo.ticker_isin_match(ticker=ticker, isin=isin)
    audit.append(
        MentionResolution(
            mention_id=mention.mention_id,
            stage=2,
            score=CONFIDENCE_TICKER_ISIN if entity_id else 0.0,
            is_winner=entity_id is not None,
            candidate_entity_id=entity_id,
            metadata={"method": "ticker_isin", "ticker": ticker, "isin": isin},
        ),
    )
    if entity_id:
        return entity_id, CONFIDENCE_TICKER_ISIN
    return None, 0.0


async def _stage3_fuzzy(
    mention: EntityMention,
    alias_repo: EntityAliasRepository,
    audit: list[MentionResolution],
) -> tuple[UUID | None, float]:
    """Stage 3 — fuzzy trigram similarity via pg_trgm."""
    candidates = await alias_repo.fuzzy_trigram(mention.mention_text, threshold=0.55, top_k=5)

    if not candidates:
        audit.append(
            MentionResolution(
                mention_id=mention.mention_id,
                stage=3,
                score=0.0,
                is_winner=False,
                candidate_entity_id=None,
                metadata={"method": "fuzzy_trigram", "candidates": 0},
            ),
        )
        return None, 0.0

    best_entity_id, best_sim = candidates[0]
    composite = best_sim * FUZZY_CONFIDENCE_MULTIPLIER
    audit.append(
        MentionResolution(
            mention_id=mention.mention_id,
            stage=3,
            score=composite,
            is_winner=True,
            candidate_entity_id=best_entity_id,
            metadata={"method": "fuzzy_trigram", "similarity": best_sim, "candidates": len(candidates)},
        ),
    )
    return best_entity_id, composite


async def _stage4_ann(
    mention: EntityMention,
    embedding_repo: EntityProfileEmbeddingRepository,
    embedding_client: EmbeddingClient,
    model_id: str,
    instruction_prefix: str,
    audit: list[MentionResolution],
) -> tuple[UUID | None, float]:
    """Stage 4 — ANN HNSW on entity_embedding_state (view_type='definition')."""
    from ml_clients.dataclasses import EmbeddingInput  # type: ignore[import-not-found]

    # Embed the mention text
    try:
        inp = EmbeddingInput(
            text=mention.mention_text,
            model_id=model_id,
            instruction_prefix=instruction_prefix,
        )
        outputs = await embedding_client.embed([inp])
        query_vec = outputs[0].embedding if outputs else None
    except Exception:
        audit.append(
            MentionResolution(
                mention_id=mention.mention_id,
                stage=4,
                score=0.0,
                is_winner=False,
                candidate_entity_id=None,
                metadata={"method": "ann_hnsw", "error": "embedding_failed"},
            ),
        )
        return None, 0.0

    if query_vec is None:
        audit.append(
            MentionResolution(
                mention_id=mention.mention_id,
                stage=4,
                score=0.0,
                is_winner=False,
                candidate_entity_id=None,
                metadata={"method": "ann_hnsw", "error": "no_embedding"},
            ),
        )
        return None, 0.0

    candidates = await embedding_repo.ann_search(
        query_vec,
        view_type="definition",
        max_distance=ANN_MAX_DISTANCE,
        top_k=5,
    )

    if not candidates:
        audit.append(
            MentionResolution(
                mention_id=mention.mention_id,
                stage=4,
                score=0.0,
                is_winner=False,
                candidate_entity_id=None,
                metadata={"method": "ann_hnsw", "candidates": 0},
            ),
        )
        return None, 0.0

    best_entity_id, best_dist = candidates[0]
    composite = (1.0 - best_dist) * ANN_CONFIDENCE_MULTIPLIER

    # Require a clear margin between top-1 and top-2 to avoid ambiguity
    if len(candidates) >= 2:
        _, second_dist = candidates[1]
        margin = second_dist - best_dist
        if margin < ANN_CLEAR_MARGIN:
            audit.append(
                MentionResolution(
                    mention_id=mention.mention_id,
                    stage=4,
                    score=composite,
                    is_winner=False,
                    candidate_entity_id=best_entity_id,
                    metadata={"method": "ann_hnsw", "margin": margin, "rejected": "insufficient_margin"},
                ),
            )
            return None, composite

    audit.append(
        MentionResolution(
            mention_id=mention.mention_id,
            stage=4,
            score=composite,
            is_winner=True,
            candidate_entity_id=best_entity_id,
            metadata={"method": "ann_hnsw", "distance": best_dist},
        ),
    )
    return best_entity_id, composite


# ── Provisional queue insert ──────────────────────────────────────────────────

# PLAN-0057 B-2 (F-MAJOR-10): the prior version of this SQL referenced columns
# ``mention_id`` and ``doc_id`` that DO NOT EXIST in the
# ``provisional_entity_queue`` schema (real columns: ``mention_text``,
# ``normalized_surface``, ``mention_class``, ``source_doc_id``, ``context_snippet``,
# ``status``, ``assigned_entity_id``, ``created_at``, ``resolved_at``,
# ``retry_count``). The savepoint+except wrapper at the call site silently
# swallowed the SQL error → ``provisional_entity_queue`` remained empty for all
# of production. This rewrite matches the real schema and uses ``ON CONFLICT
# ... DO UPDATE`` + ``RETURNING queue_id`` so the caller always receives the
# canonical queue_id (whether newly inserted or pre-existing for the same
# (normalized_surface, mention_class) pair). The ``DO UPDATE SET retry_count =
# retry_count`` clause is a no-op solely to enable the RETURNING — without it
# ``ON CONFLICT DO NOTHING`` would skip RETURNING on the conflict path.
_PROVISIONAL_INSERT_SQL = """
INSERT INTO provisional_entity_queue
    (queue_id, mention_text, normalized_surface, mention_class, source_doc_id, context_snippet)
VALUES
    (
        CAST(:queue_id AS uuid),
        CAST(:surface AS varchar(500)),
        lower(trim(CAST(:surface AS varchar(500)))),
        CAST(:mention_class AS varchar(50)),
        CAST(:doc_id AS uuid),
        CAST(:ctx AS text)
    )
ON CONFLICT (normalized_surface, mention_class)
DO NOTHING
RETURNING queue_id
"""


# Lock-convoy fix (2026-06-22, BP-707): the old ``DO UPDATE SET retry_count =
# retry_count`` no-op took a row ExclusiveLock on the hot conflicting tuple
# (``apple``, ``the company`` …) and HELD it across the 12-22s deep-extraction
# LLM call until commit — convoying ~48 concurrent backends into 40-51s waits →
# 10-min statement_timeout → 900s message_processing_timeout → DLQ (silent loss).
# ``DO NOTHING`` acquires NO held write lock; on conflict RETURNING yields no row,
# so the caller falls back to this lock-free MVCC SELECT for the canonical queue_id.
_PROVISIONAL_SELECT_SQL = """
SELECT queue_id
FROM provisional_entity_queue
WHERE normalized_surface = lower(trim(CAST(:surface AS varchar(500))))
  AND mention_class = CAST(:mention_class AS varchar(50))
"""

# Short transaction-local lock_timeout (ms) for provisional inserts. With
# DO NOTHING there is no held conflict lock, but any residual wait now fails FAST
# with lock_not_available (caught by the per-insert SAVEPOINT → mention downgraded
# to UNRESOLVED + re-attempted by the worker) instead of hanging to the 10-min
# statement_timeout that killed whole articles into the DLQ.
_PROVISIONAL_LOCK_TIMEOUT_MS = 2000


async def set_provisional_lock_timeout(intelligence_session: object) -> None:
    """Apply the short provisional-insert ``lock_timeout`` for this transaction.

    Called once at the top of the entity-resolution block (before any provisional
    INSERT). ``SET LOCAL`` scopes it to the current transaction — auto-reverts on
    commit/rollback, so it never leaks to pooled connections or other query paths.
    """
    from sqlalchemy import text  # type: ignore[import-untyped]

    # lock_timeout cannot be parameterised in SET; the value is an int constant
    # (never user input), so direct interpolation is injection-safe.
    await intelligence_session.execute(  # type: ignore[attr-defined]
        text(f"SET LOCAL lock_timeout = {_PROVISIONAL_LOCK_TIMEOUT_MS}"),
    )


async def _insert_provisional_surface(
    *,
    surface: str,
    mention_class_value: str,
    doc_id: UUID,
    intelligence_session: object,
) -> UUID:
    """Insert one row into provisional_entity_queue for a bare *surface*.

    The low-level INSERT shared by ``_insert_provisional`` (mention-backed) and
    ``ensure_provisional_for_ref`` (surface-only, no backing mention). Returns
    the canonical ``queue_id`` for the (normalized_surface, mention_class) pair —
    newly generated on first insert, pre-existing on conflict.
    """
    from sqlalchemy import text  # type: ignore[import-untyped]

    result = await intelligence_session.execute(  # type: ignore[attr-defined]
        text(_PROVISIONAL_INSERT_SQL),
        {
            "queue_id": str(common.ids.new_uuid7()),
            "surface": surface,
            "mention_class": mention_class_value,
            "doc_id": str(doc_id),
            # context_snippet left NULL for now; future work could extract a
            # surrounding-sentence snippet here, but B-3 already does that for
            # the unresolved-resolution-worker prompt and we don't want two
            # parallel implementations.
            "ctx": None,
        },
    )
    # DO NOTHING → RETURNING is empty on conflict; scalar_one_or_none is None
    # exactly then → lock-free SELECT for the canonical pre-existing queue_id
    # (shared by _insert_provisional and ensure_provisional_for_ref).
    queue_id_str = result.scalar_one_or_none()
    if queue_id_str is None:
        select_result = await intelligence_session.execute(  # type: ignore[attr-defined]
            text(_PROVISIONAL_SELECT_SQL),
            {"surface": surface, "mention_class": mention_class_value},
        )
        queue_id_str = select_result.scalar_one()
    return UUID(str(queue_id_str))


async def _provisional_within_churn_limit(
    *,
    surface: str,
    mention_class_value: str,
    intelligence_session: object,
) -> bool:
    """Return True when minting another provisional for (surface, class) is allowed.

    Shared churn-guard: skip the INSERT once ``MAX_PROVISIONAL_PER_HOUR`` rows
    already exist for the same (normalized_surface, mention_class) pair in the
    last rolling hour (noisy NER/LLM tokens like "the company" would otherwise
    hammer the savepoint machinery on every article).
    """
    from sqlalchemy import text as _sql_text  # type: ignore[import-untyped]

    count_result = await intelligence_session.execute(  # type: ignore[attr-defined]
        _sql_text(
            "SELECT COUNT(*) FROM provisional_entity_queue"
            " WHERE normalized_surface = lower(trim(:surface))"
            "   AND mention_class = :mention_class"
            "   AND created_at >= NOW() - INTERVAL '1 hour'"
        ),
        {"surface": surface, "mention_class": mention_class_value},
    )
    hourly_count: int = count_result.scalar_one()
    return hourly_count < MAX_PROVISIONAL_PER_HOUR


async def _insert_provisional(
    mention: EntityMention,
    intelligence_session: object,
) -> UUID:
    """Insert a PROVISIONAL mention into the provisional_entity_queue.

    Returns the canonical ``queue_id`` for the (normalized_surface, mention_class)
    pair — newly generated on first insert, pre-existing on conflict (so two
    mentions of the same surface text in the same class share one queue row).
    The returned id is later stashed on the mention so downstream blocks
    (B-1 ``_build_raw_relations`` etc.) can reference it as a synthetic
    "entity id" while emitting ``entity_provisional=True`` flagged relations.
    """
    # PLAN-0052 platform-QA round 4 (2026-05-01): use `.value` rather than
    # `str(enum)` to send the lowercase enum value the DB CHECK constraint
    # expects. `str(MentionClass.ORGANIZATION)` returns the Python repr
    # `'MentionClass.ORGANIZATION'`, which fails the CHECK and rolls back
    # the SAVEPOINT. Combined with the swallowed-exception pattern at the
    # call site, this was producing 100% silent provisional-insert
    # failures → empty `provisional_entity_queue` → entity_id_by_ref miss
    # → empty `relation_evidence_raw`.
    mention_class_value = (
        mention.mention_class.value  # type: ignore[union-attr]
        if hasattr(mention.mention_class, "value")
        else str(mention.mention_class)
    )
    return await _insert_provisional_surface(
        surface=mention.mention_text,
        mention_class_value=mention_class_value,
        doc_id=mention.doc_id,
        intelligence_session=intelligence_session,
    )


# ── Main block entry point ────────────────────────────────────────────────────


async def run_entity_resolution_block(
    mentions: list[EntityMention],
    *,
    alias_repo: EntityAliasRepository,
    embedding_repo: EntityProfileEmbeddingRepository,
    canonical_entity_repo: CanonicalEntityPort,
    resolution_audit_repo: MentionResolutionRepository,
    embedding_client: EmbeddingClient,
    intelligence_session: object,
    model_id: str,
    instruction_prefix: str,
    auto_resolve_threshold: float = AUTO_RESOLVE_THRESHOLD,
    provisional_threshold: float = PROVISIONAL_THRESHOLD,
) -> tuple[list[EntityMention], list[MentionResolution]]:
    """Run the 4-stage entity resolution cascade for all mentions.

    Stages 1-3 use batch DB queries (1 query per stage for N mentions) to avoid
    O(N*3) round-trips.  Stage 4 (ANN HNSW + embedding) runs per-mention only
    for mentions that did not resolve in the earlier stages.

    Critical invariants (PRD §6.7 Block 9):
      - UNRESOLVED mentions are NEVER discarded — they remain in the output list.
      - AUTO_RESOLVE and PROVISIONAL outcomes write audit trail entries.
      - Provisional mentions are queued in provisional_entity_queue (UNIQUE guard).

    NOTE: This function does NOT commit intelligence_session.
    The caller (article_consumer._run_pipeline) is responsible for committing
    intel_session AFTER nlp_session.commit() to maintain D-004 ordering invariant.

    Args:
        mentions: All EntityMention objects from Block 4.
        alias_repo: Stage 1+2+3 queries against intelligence_db.entity_aliases.
        embedding_repo: Stage 4 ANN search.
        canonical_entity_repo: Entity lookup (unused in cascade but available).
        resolution_audit_repo: Writes MentionResolution audit rows.
        embedding_client: For Stage 4 mention text embedding.
        intelligence_session: Raw AsyncSession for provisional_entity_queue insert.
        model_id: Embedding model ID.
        instruction_prefix: Embedding instruction prefix.

    Returns:
        (resolved_mentions, audit_records)
        All input mentions are returned (potentially with resolved_entity_id set).
    """
    if not mentions:
        return mentions, []

    # Lock-convoy fix (BP-707): bound provisional-insert lock waits for THIS
    # transaction so a hot-tuple conflict fails fast → UNRESOLVED downgrade
    # (re-attempted by UnresolvedResolutionWorker) instead of a 10-min
    # statement_timeout that dead-letters the whole article. SET LOCAL auto-reverts.
    await set_provisional_lock_timeout(intelligence_session)

    all_audit: list[MentionResolution] = []

    # ── Stage 1 batch: exact alias (1 query for all mentions) ─────────────────
    all_texts = [m.mention_text for m in mentions]
    exact_matches: dict[str, UUID] = await alias_repo.batch_exact_match(all_texts)

    # ── Stage 2 batch: ticker/ISIN (1-2 queries for all mentions) ─────────────
    # 2026-06-15 entity-matching fix: a mention like "AAPL.MX" carries an
    # exchange qualifier.  Strip it to the bare symbol BEFORE the all-caps/len
    # ticker gate — ".MX" pushed "AAPL.MX" to length 7, past the <=6 cap, so it
    # never reached the ticker lookup and fell through to fuzzy/ANN or a silent
    # drop.  ``s2_lookup_key`` remembers the value actually queried per mention so
    # the per-mention classification below can map a hit back to the original
    # surface form (the matches dict is keyed by the queried bare ticker).
    #
    # Class gate (2026-07-01): only build a ticker candidate for
    # company-compatible GLiNER classes.  A currency/location/person/regulator/
    # gov/macro surface that happens to equal a ticker (US/DE/CEO/MA/FTC/AI) is
    # never a real equity, so we suppress its Stage-2 lookup entirely.  ISINs are
    # NOT class-gated: an ISIN is an unambiguous 12-char security identifier that
    # cannot collide with a common word.
    tickers: list[str] = []
    isins: list[str] = []
    s2_lookup_key: dict[str, str] = {}  # mention_text.strip() -> ticker/isin value queried
    for m in mentions:
        text_stripped = m.mention_text.strip()
        ticker_candidate = _ticker_candidate(text_stripped) if _ticker_stage_allowed(m.mention_class) else None
        if ticker_candidate is not None:
            tickers.append(ticker_candidate)
            s2_lookup_key[text_stripped] = ticker_candidate
        if len(text_stripped) == 12 and text_stripped[:2].isalpha() and text_stripped[2:].isalnum():
            isins.append(text_stripped)
            s2_lookup_key[text_stripped] = text_stripped
    ticker_isin_matches: dict[str, UUID] = await alias_repo.batch_ticker_isin_match(tickers, isins)

    def _matched_in_stage2(mention: EntityMention) -> UUID | None:
        """Stage-2 entity for ``mention``, resolved via its exchange-stripped key.

        Class-aware: a denied-class mention (currency/location/person/...) never
        matches even if another same-surface mention of an allowed class seeded
        ``s2_lookup_key`` — the gate is re-checked per mention here so a "MA"
        tagged ``location`` is not rescued by a "MA" tagged ``organization``.
        The ISIN path is exempt (unambiguous 12-char identifier).
        """
        text_stripped = mention.mention_text.strip()
        key = s2_lookup_key.get(text_stripped)
        if key is None:
            return None
        # Re-apply the class gate for the ticker path; ISIN keys (12-char) are
        # always allowed regardless of class.
        is_isin_key = len(text_stripped) == 12 and text_stripped == key
        if not is_isin_key and not _ticker_stage_allowed(mention.mention_class):
            return None
        return ticker_isin_matches.get(key)

    # ── Stage 2.5 batch: class-aware canonical_name match (PLAN-0087 F-LLM-001) ─
    # GLiNER tags Apple/Microsoft/Intel as ``mention_class='organization'`` but
    # their canonicals are stored as ``entity_type='financial_instrument'``.
    # Without this stage, those mentions miss every other lookup (no bare
    # "apple" alias, not all-caps for ticker, just below the trigram floor)
    # and get silently dropped at the article-consumer's ``entity_id_by_ref``
    # gate — destroying every relation/event/claim the LLM extracted.
    #
    # Only run on mentions that didn't already resolve via Stage 1 or 2.
    # Resolution is by (surface, mention_class) so the same surface tagged
    # with two different classes gets two independent lookups (correct
    # behaviour: "Apple" as person ≠ "Apple" as organization).
    stage25_pairs: list[tuple[str, str]] = []
    for m in mentions:
        if m.mention_text.lower().strip() in exact_matches:
            continue
        if _matched_in_stage2(m) is not None:
            continue
        mclass_val = m.mention_class.value if hasattr(m.mention_class, "value") else str(m.mention_class)
        stage25_pairs.append((m.mention_text, mclass_val))
    class_aware_matches: dict[tuple[str, str], UUID] = {}
    if stage25_pairs:
        class_aware_matches = await alias_repo.batch_class_aware_canonical_match(stage25_pairs)

    # ── Stage 3 batch: fuzzy trigram (1 LATERAL query for all mentions) ────────
    # Only pass mentions that didn't resolve in stages 1, 2, or 2.5.  We
    # consult ``class_aware_matches`` here so a Stage-2.5 hit short-circuits
    # the fuzzy/ANN work for that mention.
    def _matched_in_stage25(m: EntityMention) -> bool:
        mclass_val = m.mention_class.value if hasattr(m.mention_class, "value") else str(m.mention_class)
        return (m.mention_text, mclass_val) in class_aware_matches

    stage3_candidates = [
        m
        for m in mentions
        if m.mention_text.lower().strip() not in exact_matches
        and _matched_in_stage2(m) is None
        and not _matched_in_stage25(m)
    ]
    fuzzy_matches: dict[str, list[tuple[UUID, float]]] = {}
    if stage3_candidates:
        stage3_texts = [m.mention_text for m in stage3_candidates]
        # PLAN-0052 platform-QA round 4 (2026-05-01): trigram threshold lowered
        # 0.75 → 0.55 (matches Stage 3 single-mention path at line 116). The
        # most common LLM/news pattern is "Microsoft" → "Microsoft Corporation"
        # (sim ~0.65) — under 0.75 it missed and fell through to the brittle
        # Stage 4 ANN. The lower threshold catches partial-name matches where
        # the trigram signal is genuinely strong without inflating false-pos.
        fuzzy_matches = await alias_repo.batch_fuzzy_trigram(stage3_texts, threshold=0.55, top_k_per_mention=5)

    # ── Per-mention classification + Stage 4 for remaining unresolved ─────────
    for mention in mentions:
        audit: list[MentionResolution] = []
        resolved_id: UUID | None = None
        confidence: float = 0.0

        # Stage 1 result — always emit audit entry (hit or miss) for full trail
        norm_text = mention.mention_text.lower().strip()
        s1_entity = exact_matches.get(norm_text)
        if s1_entity is not None:
            resolved_id = s1_entity
            confidence = CONFIDENCE_EXACT
        audit.append(
            MentionResolution(
                mention_id=mention.mention_id,
                stage=1,
                score=CONFIDENCE_EXACT if s1_entity else 0.0,
                is_winner=s1_entity is not None,
                candidate_entity_id=s1_entity,
                metadata={"method": "exact_alias"},
            ),
        )

        # Stage 2 result — always emit audit entry (hit or miss) for full trail
        if resolved_id is None:
            s2_entity = _matched_in_stage2(mention)
            if s2_entity is not None:
                resolved_id = s2_entity
                confidence = CONFIDENCE_TICKER_ISIN
            audit.append(
                MentionResolution(
                    mention_id=mention.mention_id,
                    stage=2,
                    score=CONFIDENCE_TICKER_ISIN if s2_entity else 0.0,
                    is_winner=s2_entity is not None,
                    candidate_entity_id=s2_entity,
                    metadata={"method": "ticker_isin"},
                ),
            )

        # Stage 2.5 result — class-aware canonical_name match (PLAN-0087 F-LLM-001).
        # Resolves the GLiNER class-mismatch silent-drop pattern: a bare
        # "Apple" (organization) → AAPL (financial_instrument) canonical.
        # We always emit an audit row (hit or miss) so observability shows
        # whether the new stage carried its weight on a per-document basis.
        if resolved_id is None:
            mclass_val = (
                mention.mention_class.value if hasattr(mention.mention_class, "value") else str(mention.mention_class)
            )
            s25_entity = class_aware_matches.get((mention.mention_text, mclass_val))
            if s25_entity is not None:
                resolved_id = s25_entity
                confidence = CONFIDENCE_CLASS_AWARE_CANONICAL
            audit.append(
                MentionResolution(
                    mention_id=mention.mention_id,
                    stage=2,  # share stage=2 in the int column to avoid migration; method tag below disambiguates
                    score=CONFIDENCE_CLASS_AWARE_CANONICAL if s25_entity else 0.0,
                    is_winner=s25_entity is not None,
                    candidate_entity_id=s25_entity,
                    metadata={"method": "class_aware_canonical", "mention_class": mclass_val},
                ),
            )

        # Stage 3 result
        if resolved_id is None:
            candidates = fuzzy_matches.get(norm_text, [])
            if candidates:
                best_entity_id, best_sim = candidates[0]
                composite = best_sim * FUZZY_CONFIDENCE_MULTIPLIER
                resolved_id = best_entity_id
                confidence = composite
                audit.append(
                    MentionResolution(
                        mention_id=mention.mention_id,
                        stage=3,
                        score=composite,
                        is_winner=True,
                        candidate_entity_id=resolved_id,
                        metadata={"method": "fuzzy_trigram", "similarity": best_sim, "candidates": len(candidates)},
                    ),
                )
            else:
                audit.append(
                    MentionResolution(
                        mention_id=mention.mention_id,
                        stage=3,
                        score=0.0,
                        is_winner=False,
                        candidate_entity_id=None,
                        metadata={"method": "fuzzy_trigram", "candidates": 0},
                    ),
                )

        # Stage 4: ANN HNSW — only for mentions still unresolved after stages 1-3
        if resolved_id is None:
            resolved_id, confidence = await _stage4_ann(
                mention,
                embedding_repo=embedding_repo,
                embedding_client=embedding_client,
                model_id=model_id,
                instruction_prefix=instruction_prefix,
                audit=audit,
            )

        # ── Resolution classification ──────────────────────────────────────
        if resolved_id is not None and confidence >= auto_resolve_threshold:
            mention.resolved_entity_id = resolved_id
            mention.resolution_confidence = confidence
            mention.resolution_stage = audit[-1].stage if audit else None
            mention.resolution_outcome = ResolutionOutcome.AUTO_RESOLVED

        elif resolved_id is not None and confidence >= provisional_threshold:
            mention.resolution_confidence = confidence
            mention.resolution_outcome = ResolutionOutcome.PROVISIONAL
            try:
                # ── Churn guard: skip INSERT if ≥ MAX_PROVISIONAL_PER_HOUR rows
                # already exist for the same (normalized_surface, mention_class)
                # pair in the last 1 hour.  Noisy NER tokens like "the company"
                # would otherwise hammer the savepoint machinery on every article.
                # Uses raw SQL (consistent with _insert_provisional) so we avoid
                # pulling sqlalchemy.func + datetime.timedelta into the module
                # top-level for a single call site.
                from sqlalchemy import text as _sql_text  # type: ignore[import-untyped]

                _mention_class_val = (
                    mention.mention_class.value  # type: ignore[union-attr]
                    if hasattr(mention.mention_class, "value")
                    else str(mention.mention_class)
                )
                _count_result = await intelligence_session.execute(  # type: ignore[attr-defined]
                    _sql_text(
                        "SELECT COUNT(*) FROM provisional_entity_queue"
                        " WHERE normalized_surface = lower(trim(:surface))"
                        "   AND mention_class = :mention_class"
                        "   AND created_at >= NOW() - INTERVAL '1 hour'"
                    ),
                    {"surface": mention.mention_text, "mention_class": _mention_class_val},
                )
                _hourly_count: int = _count_result.scalar_one()
                if _hourly_count >= MAX_PROVISIONAL_PER_HOUR:
                    # Too many recent entries — skip the INSERT to avoid churn.
                    # Downgrade to UNRESOLVED so the mention is not silently
                    # dropped (resolution_outcome='unresolved' is picked up by
                    # UnresolvedResolutionWorker on the next cycle).
                    mention.resolution_outcome = ResolutionOutcome.UNRESOLVED
                    log = logger.bind(  # type: ignore[no-any-return]
                        surface_form=mention.mention_text,
                        entity_class=_mention_class_val,
                        count=_hourly_count,
                    )
                    log.warning("provisional_churn_guard_skipped")
                    all_audit.extend(audit)
                    continue

                # Use a SAVEPOINT so a UNIQUE-constraint failure on this insert
                # does NOT abort the outer transaction (BP-239: session-transaction
                # poisoning via unguarded INSERT in entity resolution).
                async with intelligence_session.begin_nested():  # type: ignore[attr-defined]
                    queue_id = await _insert_provisional(mention, intelligence_session)
                # PLAN-0057 B-2: stash the canonical queue_id on the domain
                # mention so the article consumer's ``_build_raw_*`` helpers
                # (Wave B-1) can use it as a synthetic entity id when emitting
                # relations/events/claims with ``entity_provisional=True``.
                mention.provisional_queue_id = queue_id
            except Exception as exc:
                # PLAN-0057 QA iter-1 (DS Finding-4 follow-up): on savepoint
                # failure (DB outage, unique constraint race, etc.) the queue
                # row was NOT inserted, so there is no queue_id to stash. If we
                # left ``resolution_outcome=PROVISIONAL`` here, the article
                # consumer's ``_build_raw_*`` helpers would treat the mention
                # as truly-unresolved (no queue_id → not in entity_id_by_ref →
                # silent drop) AND the UnresolvedResolutionWorker would NOT
                # pick it up (it filters on ``resolution_outcome='unresolved'``).
                # Net: the mention would be stuck in a permanent zombie state.
                # Downgrading to UNRESOLVED restores the correct invariant: no
                # queue row → unresolved → next worker cycle re-attempts.
                #
                # PLAN-0052 platform-QA round 4 (2026-05-01): bare `except:`
                # was hiding a ~100% provisional-insert failure rate from
                # `str(mention_class)` returning `MentionClass.X` (Python
                # repr) instead of the lowercase enum value the DB CHECK
                # accepts. We now log `exc_info=True` + the exception type
                # so the next regression of this class doesn't disappear
                # silently for hours.
                mention.resolution_outcome = ResolutionOutcome.UNRESOLVED
                mention.provisional_queue_id = None  # explicit (already None)
                logger.warning(
                    "entity_resolution.provisional_insert_failed",
                    mention_id=str(mention.mention_id),
                    downgraded_to="unresolved",
                    exception_type=type(exc).__name__,
                    exception_message=str(exc),
                    exc_info=True,
                )

        else:
            mention.resolution_outcome = ResolutionOutcome.UNRESOLVED
            logger.debug(
                "entity_resolution.unresolved",
                mention_id=str(mention.mention_id),
                text=mention.mention_text,
            )

        all_audit.extend(audit)

    return mentions, all_audit


# ── Synthetic-provisional-on-demand (PLAN-0052 platform-QA round 9) ──────────


async def ensure_provisional_for_mention(
    mention: EntityMention,
    intelligence_session: object,
) -> UUID | None:
    """Create a provisional_entity_queue row for an UNRESOLVED mention on demand.

    Used by the article-consumer to synthesise a queue row for mentions the
    deep-extraction LLM later references in a relation/event/claim. Without
    this, ``_build_raw_*`` would silently drop those rows because
    ``entity_id_by_ref`` would have no synthetic UUID for the unresolved
    surface.

    Reuses the same SAVEPOINT + churn-guard + INSERT pattern as Block 9's
    own provisional path (lines 514-596 above), but is callable from outside
    the resolution loop. Mutates ``mention`` in place: on success, sets
    ``mention.provisional_queue_id`` and flips ``resolution_outcome`` from
    UNRESOLVED to PROVISIONAL so downstream observability is accurate. On
    churn-guard hit or DB failure, leaves the mention UNRESOLVED.

    Returns the new queue_id (or the pre-existing one on UNIQUE conflict),
    or ``None`` if the row was not inserted.
    """
    from sqlalchemy import text as _sql_text  # type: ignore[import-untyped]

    # Idempotency: if the mention already has a queue_id (Block 9 PROVISIONAL
    # path created one), there's nothing to do.
    if mention.provisional_queue_id is not None:
        return mention.provisional_queue_id

    # Only synthesise for genuinely unresolved mentions; never overwrite an
    # AUTO_RESOLVED resolution.
    if mention.resolved_entity_id is not None:
        return None

    _mention_class_val = (
        mention.mention_class.value  # type: ignore[union-attr]
        if hasattr(mention.mention_class, "value")
        else str(mention.mention_class)
    )

    try:
        # Churn guard — same shape as Block 9: skip if ≥ MAX_PROVISIONAL_PER_HOUR
        # rows already exist for this (surface, class) pair in the last hour.
        _count_result = await intelligence_session.execute(  # type: ignore[attr-defined]
            _sql_text(
                "SELECT COUNT(*) FROM provisional_entity_queue"
                " WHERE normalized_surface = lower(trim(:surface))"
                "   AND mention_class = :mention_class"
                "   AND created_at >= NOW() - INTERVAL '1 hour'"
            ),
            {"surface": mention.mention_text, "mention_class": _mention_class_val},
        )
        _hourly_count: int = _count_result.scalar_one()
        if _hourly_count >= MAX_PROVISIONAL_PER_HOUR:
            logger.warning(  # type: ignore[no-any-return]
                "ensure_provisional.churn_guard_skipped",
                surface_form=mention.mention_text,
                entity_class=_mention_class_val,
                count=_hourly_count,
            )
            return None

        # SAVEPOINT-guarded INSERT (BP-239: a UNIQUE-constraint failure on the
        # outer transaction would otherwise poison the article-consumer's
        # whole transaction).
        async with intelligence_session.begin_nested():  # type: ignore[attr-defined]
            queue_id = await _insert_provisional(mention, intelligence_session)

        mention.provisional_queue_id = queue_id
        # Flip the outcome so observability reflects reality. The MentionResolution
        # audit row was already written by Block 9 with outcome=UNRESOLVED; we do
        # not write a new audit row here (the on-demand promotion is metadata,
        # not a stage-N resolution decision).
        mention.resolution_outcome = ResolutionOutcome.PROVISIONAL
        return queue_id
    except Exception as exc:
        logger.warning(  # type: ignore[no-any-return]
            "ensure_provisional.insert_failed",
            mention_id=str(mention.mention_id),
            surface=mention.mention_text,
            exception_type=type(exc).__name__,
            exception_message=str(exc),
            exc_info=True,
        )
        return None


async def ensure_provisional_for_ref(
    *,
    surface: str,
    mention_class: object,
    doc_id: UUID,
    intelligence_session: object,
) -> UUID | None:
    """Mint a provisional_entity_queue row for a bare LLM endpoint *surface*.

    The non-mention sibling of :func:`ensure_provisional_for_mention`. Used by
    the article-consumer's M2 endpoint-recovery step (2026-06-14 mitigation):
    when the deep-extraction LLM references an entity in a relation/event/claim
    that GLiNER never minted a mention for, there is no ``EntityMention`` to
    promote — but the relation must still PERSIST. This mints a queue row keyed
    on the surface itself so ``_build_raw_*`` can address it with a synthetic id
    and ``entity_provisional=True``; the ``UnresolvedResolutionWorker``
    canonicalizes it later → KG promotion (the proven provisional path that
    already lands thousands of provisional relations).

    Reuses the SAME SAVEPOINT + churn-guard + INSERT machinery as the
    mention-backed path (no parallel implementation). Returns the queue_id (new
    or pre-existing on UNIQUE conflict), or ``None`` on churn-guard hit / DB
    failure (caller then treats the ref as a genuine drop).
    """
    mention_class_value = mention_class.value if hasattr(mention_class, "value") else str(mention_class)

    try:
        if not await _provisional_within_churn_limit(
            surface=surface,
            mention_class_value=mention_class_value,
            intelligence_session=intelligence_session,
        ):
            logger.warning(  # type: ignore[no-any-return]
                "ensure_provisional_for_ref.churn_guard_skipped",
                surface_form=surface,
                entity_class=mention_class_value,
            )
            return None

        # SAVEPOINT-guarded INSERT (BP-239): a UNIQUE-constraint failure must not
        # poison the article-consumer's outer transaction.
        async with intelligence_session.begin_nested():  # type: ignore[attr-defined]
            queue_id = await _insert_provisional_surface(
                surface=surface,
                mention_class_value=mention_class_value,
                doc_id=doc_id,
                intelligence_session=intelligence_session,
            )
        return queue_id
    except Exception as exc:
        logger.warning(  # type: ignore[no-any-return]
            "ensure_provisional_for_ref.insert_failed",
            surface=surface,
            exception_type=type(exc).__name__,
            exception_message=str(exc),
            exc_info=True,
        )
        return None
