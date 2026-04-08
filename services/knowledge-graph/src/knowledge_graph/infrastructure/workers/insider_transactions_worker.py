"""Worker 13D-8: EODHD Insider Transactions → has_executive Relations (PRD-0018 §6 Worker 13D-8).

APScheduler weekly job at 02:00 UTC on Mondays.

Fetches SEC Form 4 insider transactions for each US-listed instrument via
``GET /insider-transactions?code={ticker}.US&limit=100&fmt=json``, filters
for executive-level insiders (C-suite, Board, significant owners), and
upserts ``has_executive`` relations (company → person entity) in the
knowledge graph.

Insider transaction direction (bought/sold) is stored as evidence text,
providing an insider sentiment signal for downstream analysis.

**Coverage**: US-listed instruments only (EODHD Insider Transactions API
covers SEC Form 4 filers on US exchanges).

**Idempotency**: The advisory-lock upsert in :class:`RelationRepository`
prevents duplicate relation rows.  Re-processing the same transactions
for the same ticker produces the same set of relations.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from knowledge_graph.infrastructure.metrics.prometheus import (
    s7_insider_transactions_relations_total,
    s7_insider_transactions_skipped_total,
)
from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from knowledge_graph.infrastructure.eodhd.client import EodhDClient
    from knowledge_graph.infrastructure.intelligence_db.repositories.entity_repository import (
        InstrumentRecord,
    )

logger = get_logger(__name__)  # type: ignore[no-any-return]

# Maximum insider transactions to fetch per ticker (EODHD default cap: 500)
_TRANSACTIONS_LIMIT = 100

# Confidence weight for SEC Form 4 filings (regulatory filing — high trust)
_SEC_FILING_WEIGHT = 0.90

# Executive title keywords — exact match or comma-qualified prefix only.
# Examples that match: "CEO", "Director", "VP", "VP, Finance", "General Counsel".
# Examples that do NOT match: "VP Sales" (space-qualified → department head, not C-suite).
_EXECUTIVE_KEYWORDS: tuple[str, ...] = (
    "CEO",
    "CFO",
    "COO",
    "CTO",
    "Director",
    "President",
    "Chairman",
    "VP",
    "General Counsel",
    "10% Owner",
)


def is_executive_title(title: str) -> bool:
    """Return True when *title* is an executive or board-level role.

    Checks for exact case-insensitive match or comma-qualified prefix
    (e.g. ``"VP, Finance"`` matches keyword ``"VP"``).  Space-qualified
    titles like ``"VP Sales"`` are excluded — the space qualifier implies
    a department head, not a C-suite executive (PRD-0018 §6 Worker 13D-8).

    Args:
        title: Insider's reported title from the EODHD Form 4 filing.

    Returns:
        ``True`` when the title is on the executive whitelist.
    """
    normalized_upper = title.strip().upper()

    for keyword in _EXECUTIVE_KEYWORDS:
        kw_upper = keyword.upper()
        # Exact match: "CEO", "Director", "VP"
        if normalized_upper == kw_upper:
            return True
        # Comma-qualified prefix: "VP, Finance" → prefix "VP"
        if normalized_upper.startswith(kw_upper + ","):
            return True

    return False


class InsiderTransactionsWorker:
    """Worker 13D-8: Create has_executive relations from EODHD Insider Transactions.

    Runs weekly on Monday at 02:00 UTC.  For each US-listed instrument,
    fetches recent SEC Form 4 filings, deduplicates officers by name
    (``seen_officers`` dict), and upserts ``has_executive`` (company → person)
    relations in the knowledge graph.

    Prometheus metrics:
    - ``s7_insider_transactions_relations_total{ticker}`` — relations upserted
    - ``s7_insider_transactions_skipped_total{reason}`` — transactions skipped

    Args:
        session_factory: async_sessionmaker for intelligence_db (read/write).
        eodhd_client:    Initialised :class:`EodhDClient` instance.
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        eodhd_client: EodhDClient,
    ) -> None:
        self._sf = session_factory
        self._eodhd = eodhd_client

    async def run(self) -> None:
        """Execute one full weekly insider transaction enrichment cycle."""
        async with self._sf() as session:
            from knowledge_graph.infrastructure.intelligence_db.repositories.entity_repository import (
                EntityRepository,
            )

            instruments = await EntityRepository(session).list_us_instruments()

        logger.info(  # type: ignore[no-any-return]
            "insider_transactions_worker_start",
            instrument_count=len(instruments),
        )

        total_relations = 0
        total_skipped = 0

        for instrument in instruments:
            relations, skipped = await self._process_instrument(instrument)
            total_relations += relations
            total_skipped += skipped

        logger.info(  # type: ignore[no-any-return]
            "insider_transactions_worker_complete",
            total_relations=total_relations,
            total_skipped=total_skipped,
        )

    # ── Per-instrument processing ─────────────────────────────────────────────

    async def _process_instrument(self, instrument: InstrumentRecord) -> tuple[int, int]:
        """Process insider transactions for one instrument.

        Returns:
            Tuple of ``(relations_upserted, transactions_skipped)``.
        """
        ticker = instrument.ticker
        eodhd_code = f"{ticker}.US"

        transactions = await self._eodhd.get_insider_transactions(
            code=eodhd_code,
            limit=_TRANSACTIONS_LIMIT,
        )

        if not transactions:
            logger.debug(  # type: ignore[no-any-return]
                "insider_transactions_worker_no_transactions",
                ticker=ticker,
            )
            return 0, 0

        # Deduplicate: same officer may appear in multiple transactions.
        # Keep the most recently encountered title for each unique name.
        seen_officers: dict[str, str] = {}  # ownerName → ownerTitle
        skipped = 0

        for txn in transactions:
            name = txn.get("ownerName", "").strip()
            title = txn.get("ownerTitle", "").strip()

            if not name:
                s7_insider_transactions_skipped_total.labels(reason="no_name").inc()
                skipped += 1
                continue

            if not is_executive_title(title):
                s7_insider_transactions_skipped_total.labels(reason="non_executive_title").inc()
                skipped += 1
                continue

            if name not in seen_officers:
                seen_officers[name] = title

        if not seen_officers:
            logger.debug(  # type: ignore[no-any-return]
                "insider_transactions_worker_no_executives",
                ticker=ticker,
                transactions_count=len(transactions),
            )
            return 0, skipped

        relations_upserted = 0

        async with self._sf() as session:
            from knowledge_graph.infrastructure.intelligence_db.repositories.entity_repository import (
                EntityRepository,
            )
            from knowledge_graph.infrastructure.intelligence_db.repositories.relation import (
                RelationRepository,
            )

            entity_repo = EntityRepository(session)
            relation_repo = RelationRepository(session)

            for officer_name, officer_title in seen_officers.items():
                person_entity_id = await entity_repo.find_or_create_person(
                    name=officer_name,
                    context_ticker=ticker,
                )

                # Transaction direction conveys insider sentiment signal
                recent_txn: dict[str, Any] = next(
                    (t for t in transactions if t.get("ownerName", "").strip() == officer_name),
                    {},
                )
                direction = "bought" if recent_txn.get("transactionAcquiredDisposed") == "A" else "sold"
                evidence_text = (
                    f"{officer_name} ({officer_title}) recently {direction} shares" f" in {instrument.canonical_name}"
                )

                await relation_repo.upsert_relation(
                    subject_entity_id=instrument.entity_id,
                    object_entity_id=person_entity_id,
                    canonical_type="has_executive",
                    evidence_text=evidence_text,
                    source_weight=_SEC_FILING_WEIGHT,
                    is_backfill=True,
                )

                s7_insider_transactions_relations_total.labels(ticker=ticker).inc()
                relations_upserted += 1

                logger.debug(  # type: ignore[no-any-return]
                    "insider_transactions_worker_relation_upserted",
                    ticker=ticker,
                    officer=officer_name,
                    title=officer_title,
                    direction=direction,
                )

            await session.commit()

        return relations_upserted, skipped
