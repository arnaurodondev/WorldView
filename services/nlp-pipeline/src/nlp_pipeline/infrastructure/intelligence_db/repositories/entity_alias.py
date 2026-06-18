"""EntityAlias repository — queries against intelligence_db.entity_aliases.

Uses raw SQL (text()) — S6 does not own intelligence_db DDL.

Batch methods (batch_exact_match, batch_ticker_isin_match, batch_fuzzy_trigram)
execute one query per stage for N mentions, reducing latency from O(N) to O(1)
per stage.  Use these when resolving more than one mention at a time.

PLAN-0087 F-LLM-001 (2026-05-09) — class-aware canonical-name resolver.
GLiNER NER tags listed companies (Apple, Microsoft, Intel, ...) as
``mention_class='organization'`` while their canonical_entities row has
``entity_type='financial_instrument'``.  The four-stage cascade above is
class-blind, but in practice the bottleneck is alias coverage: only
``"Apple Inc."`` lives in entity_aliases — a bare ``"Apple"`` mention
misses Stage-1 exact, fails Stage-2 (not all-caps), and lands just under
the trigram floor at Stage-3.  The fix is a NEW Stage 2.5 that does an
exact-canonical-name match against ``canonical_entities`` constrained to
the candidate ``entity_type`` set for the GLiNER class — i.e. given
``mention_class='organization'`` we also try ``entity_type IN
('financial_instrument', 'organization', 'financial_institution')``.
This single hop unblocks the deep-extractor's ``entity_id_by_ref``
lookup and removes the silent-drop pattern that empties
``relation_evidence_raw``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import text

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


# ── GLiNER class → canonical entity_type fallback table ──────────────────────
#
# Keys are the GLiNER 11-class ontology values (mirror of MentionClass enum).
# Values are the ordered list of ``canonical_entities.entity_type`` candidates
# the resolver should try.  Always start with the matching type so a directly
# typed canonical wins over a fallback type.  The most important entry is
# ``organization`` → tries ``financial_instrument`` FIRST because the
# overwhelming majority of real-world "organization" mentions in financial news
# are listed companies whose canonical row was seeded from EODHD with
# ``entity_type='financial_instrument'``.  Without this, 100% of
# org-tagged GLiNER mentions for tickers fail to resolve and the LLM's
# extracted relations get silently dropped at the article-consumer's
# ``entity_id_by_ref`` filter.
#
# A surface that doesn't match any of the candidate types falls through to
# Stage-3 fuzzy trigram, exactly as before — no regressions for unmapped
# classes.
GLINER_TO_CANONICAL_TYPES: dict[str, list[str]] = {
    # Listed companies dominate "organization" mentions in financial news,
    # so financial_instrument is the highest-yield candidate.
    "organization": ["financial_instrument", "organization", "financial_institution"],
    # Banks/exchanges/brokers — also commonly stored as financial_instrument
    # when they're listed (e.g. JPMorgan = JPM = financial_instrument).
    "financial_institution": ["financial_institution", "financial_instrument", "organization"],
    # Listed financial instruments, ETFs, funds.  Self-only — no fallback
    # to organization, which would just add noise.
    "financial_instrument": ["financial_instrument"],
    # Self-only; no expansion.
    "person": ["person"],
    "location": ["location"],
    "currency": ["currency"],
    "commodity": ["commodity"],
    "index": ["index"],
    "regulatory_body": ["regulatory_body", "government_body", "organization"],
    "government_body": ["government_body", "regulatory_body", "organization"],
    "macroeconomic_indicator": ["macroeconomic_indicator"],
}


def candidate_entity_types_for(mention_class: str) -> list[str]:
    """Return the ordered ``canonical_entities.entity_type`` candidates.

    Forward-compat: an unrecognised mention_class falls back to
    ``[mention_class]`` so any future GLiNER class works as-is without a
    code change here, just with no extra fallback breadth.
    """
    return GLINER_TO_CANONICAL_TYPES.get(mention_class, [mention_class])


class EntityAliasRepository:
    """Lookup entity aliases in intelligence_db (PRD §6.7 Block 9)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ── Single-mention helpers (kept for compatibility) ───────────────────────

    async def exact_match(self, mention_text: str) -> UUID | None:
        """Stage 1 — exact alias match. Confidence: 1.0."""
        result = await self._session.execute(
            text(
                "SELECT entity_id FROM entity_aliases "
                "WHERE normalized_alias_text = lower(trim(:mention_text)) "
                "AND alias_type = 'EXACT' AND is_active = true "
                "LIMIT 1",
            ),
            {"mention_text": mention_text},
        )
        row = result.fetchone()
        return UUID(str(row[0])) if row else None

    async def ticker_isin_match(
        self,
        ticker: str | None,
        isin: str | None,
        exchange: str | None = None,
    ) -> UUID | None:
        """Stage 2 — ticker/ISIN match against canonical_entities. Confidence: 0.95.

        PLAN-0057 Wave C-3-02: when the canonical_entities lookup misses
        (e.g. the canonical was created via the bootstrap seed without a
        ticker, or the EODHD primary ticker hasn't been promoted to the
        ``ticker`` column yet), fall back to ``entity_aliases`` matching
        ``alias_type IN ('TICKER', 'PRIMARY_TICKER', 'ISIN')``.  This lets the
        new PRIMARY_TICKER aliases inserted by the KG instrument_consumer
        participate in Stage-2 resolution.
        """
        if ticker:
            result = await self._session.execute(
                text(
                    "SELECT entity_id FROM canonical_entities "
                    "WHERE ticker = :ticker "
                    "AND (CAST(:exchange AS TEXT) IS NULL OR exchange = :exchange) "
                    "LIMIT 1",
                ),
                {"ticker": ticker, "exchange": exchange},
            )
            row = result.fetchone()
            if row:
                return UUID(str(row[0]))
            # Fallback: check entity_aliases for TICKER or PRIMARY_TICKER.
            result = await self._session.execute(
                text(
                    "SELECT entity_id FROM entity_aliases "
                    "WHERE normalized_alias_text = lower(trim(:ticker)) "
                    "AND alias_type IN ('TICKER', 'PRIMARY_TICKER', 'ISIN') "
                    "AND is_active = true "
                    "LIMIT 1",
                ),
                {"ticker": ticker},
            )
            row = result.fetchone()
            if row:
                return UUID(str(row[0]))
        if isin:
            result = await self._session.execute(
                text("SELECT entity_id FROM canonical_entities WHERE isin = :isin LIMIT 1"),
                {"isin": isin},
            )
            row = result.fetchone()
            if row:
                return UUID(str(row[0]))
            # Fallback: ISIN can also be stored as an alias.
            result = await self._session.execute(
                text(
                    "SELECT entity_id FROM entity_aliases "
                    "WHERE normalized_alias_text = lower(trim(:isin)) "
                    "AND alias_type IN ('TICKER', 'PRIMARY_TICKER', 'ISIN') "
                    "AND is_active = true "
                    "LIMIT 1",
                ),
                {"isin": isin},
            )
            row = result.fetchone()
            if row:
                return UUID(str(row[0]))
        return None

    async def class_aware_canonical_match(
        self,
        mention_text: str,
        mention_class: str,
    ) -> UUID | None:
        """Stage 2.5 — class-aware exact canonical_name match (PLAN-0087 F-LLM-001).

        Looks up ``canonical_entities`` by exact (case-insensitive)
        ``canonical_name`` match constrained to the candidate ``entity_type``
        list returned by :func:`candidate_entity_types_for` for the given
        GLiNER ``mention_class``.

        This is the key fix for the "Apple → AAPL" silent-drop pattern: a
        bare ``"Apple"`` mention tagged ``organization`` would otherwise
        miss every prior stage (no ``apple`` alias, not all-caps, trigram
        below floor) and fail the article-consumer's ``entity_id_by_ref``
        gate.  The class-aware sweep matches ``Apple Inc.`` directly
        because its canonical_name lower-form is ``apple inc.`` and we
        match on a normalized prefix-or-equal of the mention surface.

        Match strategy (cheapest first):
          1. ``lower(canonical_name) = lower(mention_text)``         (exact)
          2. ``lower(canonical_name) LIKE lower(mention_text) || ' %'``  (prefix-with-suffix)

        The second pattern catches "Apple" against "Apple Inc.", "Microsoft"
        against "Microsoft Corporation", etc., without false positives like
        "Apple" matching "Applebee's" (that would require prefix MATCHING
        the surface, not the canonical — which is what we do).  The
        ``LIMIT 1`` keeps the call cheap; tie-breaking is by the candidate
        type ordering in ``GLINER_TO_CANONICAL_TYPES`` (CASE WHEN clause).

        Returns the entity_id of the best candidate or None if no match.
        """
        candidate_types = candidate_entity_types_for(mention_class)
        if not candidate_types:
            return None

        # Build a parameterised IN clause for the entity_type filter.  Using
        # named placeholders (rather than ANY(:list)) keeps the query plan
        # cache-friendly and the SQL strings consistent with the rest of
        # this repo.  CASE WHEN over the same placeholders gives us a
        # deterministic priority ordering so financial_instrument wins
        # over organization for an "Apple" mention.
        type_placeholders = ", ".join(f":t{i}" for i in range(len(candidate_types)))
        case_clauses = " ".join(f"WHEN entity_type = :t{i} THEN {i}" for i in range(len(candidate_types)))

        params: dict[str, str] = {f"t{i}": v for i, v in enumerate(candidate_types)}
        params["surface"] = mention_text

        result = await self._session.execute(
            text(
                "SELECT entity_id FROM canonical_entities "
                f"WHERE entity_type IN ({type_placeholders}) "
                "AND ("
                "  lower(canonical_name) = lower(trim(:surface)) "
                "  OR lower(canonical_name) LIKE lower(trim(:surface)) || ' %'"
                ") "
                f"ORDER BY CASE {case_clauses} ELSE {len(candidate_types)} END, "
                "  length(canonical_name) ASC "
                "LIMIT 1",
            ),
            params,
        )
        row = result.fetchone()
        return UUID(str(row[0])) if row else None

    async def batch_class_aware_canonical_match(
        self,
        surface_class_pairs: list[tuple[str, str]],
    ) -> dict[tuple[str, str], UUID]:
        """Batch variant of :meth:`class_aware_canonical_match` (one query per class).

        Groups input pairs by ``mention_class`` so each class generates a
        single ``IN (...)`` query against ``canonical_entities``.  This
        avoids O(N) round-trips for the common case where a single article
        produces 30+ "organization" mentions at once.

        Returns ``{(surface, mention_class): entity_id}`` for every pair
        that matched.  Surfaces that did not match are simply absent from
        the dict — callers should treat the resolver as optional.
        """
        if not surface_class_pairs:
            return {}

        out: dict[tuple[str, str], UUID] = {}

        # Group by mention_class so we issue one query per class.  We keep
        # the original-cased surfaces in a parallel map so we can return
        # the input key (not the lower-cased lookup key) to the caller.
        by_class: dict[str, list[str]] = {}
        for surface, mclass in surface_class_pairs:
            by_class.setdefault(mclass, []).append(surface)

        for mclass, surfaces in by_class.items():
            candidate_types = candidate_entity_types_for(mclass)
            if not candidate_types:
                continue

            # De-duplicate normalized surfaces inside this class to keep the
            # SQL parameter count down (LLM-extraction often produces the
            # same surface multiple times in one batch).
            lower_to_orig: dict[str, str] = {}
            for s in surfaces:
                lower_to_orig.setdefault(s.lower().strip(), s)

            type_placeholders = ", ".join(f":t{i}" for i in range(len(candidate_types)))
            case_clauses = " ".join(f"WHEN entity_type = :t{i} THEN {i}" for i in range(len(candidate_types)))
            surface_placeholders = ", ".join(f":s{i}" for i in range(len(lower_to_orig)))

            params: dict[str, str] = {f"t{i}": v for i, v in enumerate(candidate_types)}
            for i, lower_surface in enumerate(lower_to_orig):
                params[f"s{i}"] = lower_surface

            # We need to know WHICH input surface produced each row, so we
            # use a CTE that exposes the matched surface alongside the
            # entity_id.  ``DISTINCT ON (search)`` keeps one row per surface,
            # winning by the same priority as the single-surface variant
            # (candidate_type order, then shortest canonical_name).
            sql = (
                "WITH surfaces(search) AS (VALUES " + ", ".join(f"(:s{i})" for i in range(len(lower_to_orig))) + ") "
                "SELECT DISTINCT ON (s.search) s.search, c.entity_id "
                "FROM surfaces s "
                "JOIN canonical_entities c ON ("
                f"  c.entity_type IN ({type_placeholders}) "
                "  AND ("
                "    lower(c.canonical_name) = s.search "
                "    OR lower(c.canonical_name) LIKE s.search || ' %'"
                "  )"
                ") "
                f"ORDER BY s.search, CASE {case_clauses} ELSE {len(candidate_types)} END, "
                "  length(c.canonical_name) ASC"
            )
            # Strip the unused placeholders silently — surface_placeholders
            # is built into the VALUES clause above; mypy hint:
            del surface_placeholders  # silence unused-variable lints

            result = await self._session.execute(text(sql), params)
            for row in result.fetchall():
                lower_surface = str(row[0])
                orig = lower_to_orig.get(lower_surface)
                if orig is not None:
                    out[(orig, mclass)] = UUID(str(row[1]))

        return out

    async def fuzzy_trigram(
        self,
        mention_text: str,
        threshold: float = 0.75,
        top_k: int = 5,
    ) -> list[tuple[UUID, float]]:
        """Stage 3 — fuzzy trigram similarity via pg_trgm. Confidence: sim * 0.90.

        RC-3 latency fix (2026-06-18): the WHERE predicate uses the pg_trgm
        similarity *operator* ``%`` instead of the function form
        ``similarity(col, x) > t``.  The GIN trigram index
        ``idx_entity_aliases_trgm`` can ONLY be probed by the ``%`` operator
        (and the ``<->`` distance operator) — the function-form predicate is
        opaque to the planner and forces a full Seq Scan over every alias row
        (~37k rows, ~1000 heap buffers), which scales linearly with alias-table
        growth and is the contention-sensitive hot spot of the chat pipeline's
        entity-resolution phase.

        Correctness is preserved exactly:

        * ``%`` matches when ``similarity(a, b) >= pg_trgm.similarity_threshold``.
          We set that GUC to the caller's ``:threshold`` via ``set_limit()``
          for the current session/transaction, so the operator's cutoff is
          identical to the old ``> :threshold`` predicate (modulo the
          ``>=`` vs ``>`` boundary — see the outer filter below).
        * The OLD predicate was strict ``> :threshold``; ``%`` is inclusive
          (``>=``).  To keep behaviour byte-for-byte identical we re-apply the
          exact strict ``sim > :threshold`` filter in an outer wrapper, so a
          surface landing exactly ON the threshold is still excluded.
        * Ordering (``sim DESC``) and the ``top_k`` limit are unchanged.

        NOTE: whether the planner actually chooses the GIN index at the current
        table size also depends on ``random_page_cost`` (SSD clusters want
        ~1.1; the PG default of 4 over-prices random index I/O and can keep the
        planner on the Seq Scan until the table grows).  Either way, the
        operator form is what makes the index *usable* — the function form
        never could be — so this is a strict, necessary improvement.
        """
        # Set the pg_trgm cutoff for the ``%`` operator to exactly the caller's
        # threshold, scoped to this session/transaction.  set_limit() persists
        # for the session, but because async sessions are pooled we set it on
        # every call to avoid leaking a stale threshold across checkouts.
        await self._session.execute(text("SELECT set_limit(:threshold)"), {"threshold": threshold})
        result = await self._session.execute(
            text(
                # Inner: GIN-index-usable ``%`` probe (cutoff = set_limit above).
                # Outer: re-impose the strict ``> :threshold`` boundary so the
                # match set is identical to the legacy function-form predicate.
                "SELECT entity_id, sim FROM ("
                "  SELECT entity_id, similarity(normalized_alias_text, lower(:mention_text)) AS sim "
                "  FROM entity_aliases "
                "  WHERE normalized_alias_text % lower(:mention_text) "
                "  AND is_active = true "
                ") AS m "
                "WHERE sim > :threshold "
                "ORDER BY sim DESC "
                "LIMIT :top_k",
            ),
            {"mention_text": mention_text, "threshold": threshold, "top_k": top_k},
        )
        return [(UUID(str(row[0])), float(row[1])) for row in result.fetchall()]

    # ── Batch helpers (1 query for N mentions — use these in production paths) ─

    async def batch_exact_match(
        self,
        mention_texts: list[str],
    ) -> dict[str, UUID]:
        """Stage 1 batch — return {normalized_text: entity_id} for all exact matches.

        One SQL query regardless of how many mentions are passed.
        """
        if not mention_texts:
            return {}
        # Build a VALUES list: (lower(trim(text1)), lower(trim(text2)), ...)
        normalized = [t.lower().strip() for t in mention_texts]
        placeholders = ", ".join(f":t{i}" for i in range(len(normalized)))
        params = {f"t{i}": v for i, v in enumerate(normalized)}
        result = await self._session.execute(
            text(
                f"SELECT normalized_alias_text, entity_id "
                f"FROM entity_aliases "
                f"WHERE normalized_alias_text IN ({placeholders}) "
                f"AND alias_type = 'EXACT' AND is_active = true",
            ),
            params,
        )
        return {str(row[0]): UUID(str(row[1])) for row in result.fetchall()}

    async def batch_ticker_isin_match(
        self,
        tickers: list[str],
        isins: list[str],
    ) -> dict[str, UUID]:
        """Stage 2 batch — return {ticker_or_isin: entity_id} for all matches.

        One SQL query for tickers + one for ISINs (only if non-empty inputs).

        PLAN-0057 Wave C-3-02: after the canonical_entities sweep, any tickers
        / isins that missed are re-tried against ``entity_aliases`` with
        ``alias_type IN ('TICKER', 'PRIMARY_TICKER', 'ISIN')`` so the new
        PRIMARY_TICKER aliases participate in batch resolution.
        """
        out: dict[str, UUID] = {}
        if tickers:
            placeholders = ", ".join(f":tk{i}" for i in range(len(tickers)))
            params = {f"tk{i}": v for i, v in enumerate(tickers)}
            result = await self._session.execute(
                text(
                    f"SELECT ticker, entity_id FROM canonical_entities WHERE ticker IN ({placeholders})",
                ),
                params,
            )
            for row in result.fetchall():
                out[str(row[0])] = UUID(str(row[1]))
            # Fallback: check entity_aliases for any tickers we didn't find in
            # canonical_entities.ticker (covers PRIMARY_TICKER + entries whose
            # canonical row hasn't promoted ticker yet).
            missing_tickers = [t for t in tickers if t not in out]
            if missing_tickers:
                placeholders = ", ".join(f":mtk{i}" for i in range(len(missing_tickers)))
                params = {f"mtk{i}": t.lower().strip() for i, t in enumerate(missing_tickers)}
                # Also need a parallel mapping back to original casing so the
                # caller can index by the input value.
                lower_to_orig = {t.lower().strip(): t for t in missing_tickers}
                result = await self._session.execute(
                    text(
                        "SELECT normalized_alias_text, entity_id "
                        "FROM entity_aliases "
                        f"WHERE normalized_alias_text IN ({placeholders}) "
                        "AND alias_type IN ('TICKER', 'PRIMARY_TICKER', 'ISIN') "
                        "AND is_active = true",
                    ),
                    params,
                )
                for row in result.fetchall():
                    norm_text = str(row[0])
                    orig = lower_to_orig.get(norm_text)
                    if orig is not None:
                        out[orig] = UUID(str(row[1]))
        if isins:
            placeholders = ", ".join(f":is{i}" for i in range(len(isins)))
            params = {f"is{i}": v for i, v in enumerate(isins)}
            result = await self._session.execute(
                text(
                    f"SELECT isin, entity_id FROM canonical_entities WHERE isin IN ({placeholders})",
                ),
                params,
            )
            for row in result.fetchall():
                out[str(row[0])] = UUID(str(row[1]))
            # Fallback to entity_aliases for ISINs missed above.
            missing_isins = [i for i in isins if i not in out]
            if missing_isins:
                placeholders = ", ".join(f":mis{i}" for i in range(len(missing_isins)))
                params = {f"mis{i}": v.lower().strip() for i, v in enumerate(missing_isins)}
                lower_to_orig = {v.lower().strip(): v for v in missing_isins}
                result = await self._session.execute(
                    text(
                        "SELECT normalized_alias_text, entity_id "
                        "FROM entity_aliases "
                        f"WHERE normalized_alias_text IN ({placeholders}) "
                        "AND alias_type IN ('TICKER', 'PRIMARY_TICKER', 'ISIN') "
                        "AND is_active = true",
                    ),
                    params,
                )
                for row in result.fetchall():
                    norm_text = str(row[0])
                    orig = lower_to_orig.get(norm_text)
                    if orig is not None:
                        out[orig] = UUID(str(row[1]))
        return out

    async def batch_fuzzy_trigram(
        self,
        mention_texts: list[str],
        threshold: float = 0.75,
        top_k_per_mention: int = 5,
    ) -> dict[str, list[tuple[UUID, float]]]:
        """Stage 3 batch — return best fuzzy matches per mention text.

        Issues one parameterised LATERAL query for all mentions.
        Returns {normalized_text: [(entity_id, similarity), ...]}.

        RC-3 latency fix (2026-06-18): the previous form joined the term list
        against ``entity_aliases`` on the function predicate
        ``similarity(ea.col, q.term) > :threshold``.  That predicate is opaque
        to the planner, so it ran a **Nested Loop that Seq-Scanned the entire
        ~37k-row alias table once per search term** (EXPLAIN: 112k+ "Rows
        Removed by Join Filter", ~150ms for 3 terms) — cost scaling with
        ``len(terms) * table_rows``.

        The rewrite uses a ``JOIN LATERAL`` per term whose inner query filters
        with the GIN-index-usable ``%`` operator and orders by the ``<->``
        distance operator, so each term probes ``idx_entity_aliases_trgm``
        independently (EXPLAIN: ``Bitmap Index Scan on idx_entity_aliases_trgm``
        per loop) and caps work at ``top_k_per_mention`` rows per term.

        Behaviour is preserved exactly:

        * The ``%`` cutoff is set to the caller's ``:threshold`` via
          ``set_limit()`` (see :meth:`fuzzy_trigram`).
        * ``%`` is inclusive (``>=``); the legacy predicate was strict
          (``>``).  The inner ``WHERE sim > :threshold`` re-imposes the strict
          boundary so the match set is identical.
        * The per-term ``LIMIT :top_k`` and the ``sim DESC`` ordering reproduce
          the old "keep top_k per mention, highest similarity first" semantics
          (previously enforced in Python after the fact).
        * Return shape ``{normalized_text: [(entity_id, sim), ...]}`` and the
          lower/strip normalisation of inputs are unchanged.
        """
        if not mention_texts:
            return {}
        normalized = [t.lower().strip() for t in mention_texts]
        # Set the pg_trgm cutoff for ``%`` to exactly the caller's threshold,
        # scoped to this session/transaction (re-applied per call because the
        # async session is pooled — see fuzzy_trigram()).
        await self._session.execute(text("SELECT set_limit(:threshold)"), {"threshold": threshold})
        # One round-trip: unnest the terms, then LATERAL-probe the GIN index
        # per term.  ``top_k`` lives inside the LATERAL so each term is capped
        # at the index level rather than after a full-table scan.
        result = await self._session.execute(
            text(
                "SELECT q.search_term, m.entity_id, m.sim "
                "FROM unnest(cast(:terms AS text[])) AS q(search_term) "
                "JOIN LATERAL ("
                "  SELECT ea.entity_id, "
                "    similarity(ea.normalized_alias_text, q.search_term) AS sim "
                "  FROM entity_aliases ea "
                "  WHERE ea.normalized_alias_text % q.search_term "
                "  AND ea.is_active = true "
                "  AND similarity(ea.normalized_alias_text, q.search_term) > :threshold "
                "  ORDER BY ea.normalized_alias_text <-> q.search_term "
                "  LIMIT :top_k "
                ") AS m ON true "
                "ORDER BY q.search_term, m.sim DESC",
            ),
            {"terms": normalized, "threshold": threshold, "top_k": top_k_per_mention},
        )
        # Group results by search term, keep top_k per mention
        out: dict[str, list[tuple[UUID, float]]] = {}
        for row in result.fetchall():
            term = str(row[0])
            entries = out.setdefault(term, [])
            if len(entries) < top_k_per_mention:
                entries.append((UUID(str(row[1])), float(row[2])))
        return out
