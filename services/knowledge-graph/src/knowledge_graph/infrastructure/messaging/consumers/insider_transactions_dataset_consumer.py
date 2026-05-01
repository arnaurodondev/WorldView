"""Consumer 13D-8: Insider Transactions dataset → has_executive Relations via Kafka.

Consumer group: ``kg-insider-transactions-dataset-group``.
Consumes: ``market.dataset.fetched`` WHERE dataset_type='insider_transactions'.

Processing:
  1. Filter messages to dataset_type='insider_transactions'.
  2. Download canonical NDJSON envelope from MinIO (claim-check pattern).
  3. Parse the passthrough envelope to extract the list of SEC Form 4 transactions.
  4. Apply the same executive filtering + relation upsert logic as the former
     InsiderTransactionsWorker (13D-8):
     - Filter by ``is_executive_title()`` whitelist (CEO, CFO, Director, VP, …).
     - Deduplicate by officer name (``seen_officers`` dict).
     - Upsert ``has_executive`` (company → person) relations in the knowledge graph.

Symbol format from S2: the ticker symbol (e.g. ``"AAPL"`` or ``"AAPL.US"``).
The base ticker is extracted by stripping any ``.US`` suffix.

Prometheus metrics:
- ``s7_insider_transactions_relations_total{ticker}`` — relations upserted.
- ``s7_insider_transactions_skipped_total{reason}`` — transactions skipped.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from knowledge_graph.infrastructure.metrics.prometheus import (
    s7_insider_transactions_relations_total,
    s7_insider_transactions_skipped_total,
)
from messaging.kafka.consumer.base import (  # type: ignore[import-untyped]
    BaseKafkaConsumer,
    ConsumerConfig,
    FailureInfo,
    UnitOfWorkProtocol,
)
from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

logger = get_logger(__name__)  # type: ignore[no-any-return]


# Walk up the directory tree to find infra/kafka/schemas/ — works both in development
# (repo root is a few levels up) and in Docker (schemas copied to /app/infra/kafka/schemas/).
def _find_schema_dir() -> Path:
    relative = Path("infra") / "kafka" / "schemas"
    for base in Path(__file__).resolve().parents:
        candidate = base / relative
        if candidate.is_dir():
            return candidate
    return Path(__file__).parents[7] / "infra" / "kafka" / "schemas"


_SCHEMA_DIR = _find_schema_dir()
_DATASET_FETCHED_SCHEMA_PATH = str(_SCHEMA_DIR / "market.dataset.fetched.avsc")

# Confidence weight for SEC Form 4 filings (regulatory filing — high trust)
_SEC_FILING_WEIGHT = 0.90

# Executive title keywords (replicated from the former InsiderTransactionsWorker)
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

    Replicated 1:1 from the former InsiderTransactionsWorker.

    Args:
    ----
        title: Insider's reported title from the EODHD Form 4 filing.

    Returns:
    -------
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


class _NoOpUoW:
    """Minimal UoW shim — insider transactions consumer manages sessions directly."""

    async def __aenter__(self) -> _NoOpUoW:
        return self

    async def __aexit__(self, *args: object) -> None:
        pass

    async def commit(self) -> None:
        pass

    async def rollback(self) -> None:
        pass


class InsiderTransactionsDatasetConsumer(BaseKafkaConsumer[None]):
    """Consumer 13D-8: Create has_executive relations from insider transaction data.

    Replaces the former APScheduler-based InsiderTransactionsWorker.  Instead of
    calling EODHD directly, this consumer receives pre-fetched SEC Form 4 data
    from S2 (market-ingestion) via the claim-check pattern and applies identical
    executive-filtering + relation-upsert logic.

    Processing per message:
    1. Filter: only ``dataset_type='insider_transactions'`` is processed.
    2. Download canonical NDJSON envelope from MinIO.
    3. Filter transactions by ``is_executive_title()`` whitelist.
    4. Deduplicate officers (one relation per unique name).
    5. Find instrument entity by ticker; upsert ``has_executive`` (company → person).

    Args:
    ----
        config:          Consumer configuration.
        session_factory: async_sessionmaker for intelligence_db (read/write).
        storage_client:  Object storage client for MinIO claim-check downloads.
        dedup_client:    Optional Valkey dedup client.

    """

    def __init__(
        self,
        config: ConsumerConfig,
        session_factory: async_sessionmaker[AsyncSession],
        storage_client: Any | None = None,
        *,
        dedup_client: Any | None = None,
    ) -> None:
        super().__init__(config)
        self._sf = session_factory
        self._storage = storage_client
        self._dedup_client = dedup_client
        self._dedup_prefix = f"kg:insider:{config.group_id}"

    # ------------------------------------------------------------------
    # Core processing
    # ------------------------------------------------------------------

    async def process_message(
        self,
        key: str | None,
        value: dict[str, Any],
        headers: dict[str, str],
    ) -> None:
        """Process a market.dataset.fetched event for insider transactions data."""
        dataset_type = str(value.get("dataset_type", ""))
        if dataset_type != "insider_transactions":
            return  # Not an insider transactions message — skip silently

        symbol = str(value.get("symbol", ""))
        bucket = value.get("canonical_ref_bucket")
        object_key = value.get("canonical_ref_key")

        # Download the canonical NDJSON envelope from MinIO
        envelope = await self._download_envelope(bucket, object_key, symbol=symbol)
        if envelope is None:
            return

        # envelope["payload"] is the raw EODHD insider transactions list
        transactions = envelope.get("payload")
        if not isinstance(transactions, list) or not transactions:
            logger.debug(  # type: ignore[no-any-return]
                "insider_transactions_consumer_empty_payload",
                symbol=symbol,
            )
            return

        # Normalise ticker: strip exchange suffix (e.g. "AAPL.US" → "AAPL")
        ticker = symbol.split(".")[0]

        await self._process_instrument(ticker, transactions, symbol)

    async def _process_instrument(
        self,
        ticker: str,
        transactions: list[dict[str, Any]],
        symbol: str,
    ) -> None:
        """Create has_executive relations for one instrument.

        Replicates the logic from the former InsiderTransactionsWorker._process_instrument().
        """
        from knowledge_graph.infrastructure.intelligence_db.repositories.entity_repository import (
            EntityRepository,
        )
        from knowledge_graph.infrastructure.intelligence_db.repositories.relation import (
            RelationRepository,
        )

        # Deduplicate: same officer may appear in multiple transactions.
        # Keep the first encountered title for each unique name.
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
                "insider_transactions_consumer_no_executives",
                ticker=ticker,
                transactions_count=len(transactions),
                skipped=skipped,
            )
            return

        relations_upserted = 0

        async with self._sf() as session:
            entity_repo = EntityRepository(session)
            relation_repo = RelationRepository(session)

            # Look up the instrument entity by ticker to get canonical_name + entity_id
            instrument = await entity_repo.find_instrument_by_ticker(ticker)
            if instrument is None:
                logger.debug(  # type: ignore[no-any-return]
                    "insider_transactions_consumer_instrument_not_found",
                    ticker=ticker,
                    symbol=symbol,
                )
                return

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
                    f"{officer_name} ({officer_title}) recently {direction} shares in {instrument.canonical_name}"
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
                    "insider_transactions_consumer_relation_upserted",
                    ticker=ticker,
                    officer=officer_name,
                    title=officer_title,
                    direction=direction,
                )

            await session.commit()

        logger.info(  # type: ignore[no-any-return]
            "insider_transactions_consumer_processed",
            ticker=ticker,
            symbol=symbol,
            relations_upserted=relations_upserted,
            skipped=skipped,
        )

    async def _download_envelope(
        self,
        bucket: str | None,
        object_key: str | None,
        *,
        symbol: str = "",
    ) -> dict[str, Any] | None:
        """Download and parse the canonical NDJSON passthrough envelope from MinIO."""
        if not bucket or not object_key or not self._storage:
            return None
        try:
            raw: bytes = await self._storage.get_bytes(bucket, object_key)
            line = raw.decode("utf-8").strip()
            if not line:
                return None
            envelope: dict[str, Any] = json.loads(line)
            return envelope
        except json.JSONDecodeError as exc:
            # Malformed JSON is a data quality issue — log and skip (non-retryable).
            logger.warning(  # type: ignore[no-any-return]
                "insider_transactions_consumer_malformed_envelope",
                bucket=bucket,
                object_key=object_key,
                symbol=symbol,
                error=str(exc),
            )
            return None
        except Exception as exc:
            # Transient storage errors (network, timeout) — re-raise so BaseKafkaConsumer
            # does NOT commit the offset.  The message will be redelivered on restart.
            logger.warning(  # type: ignore[no-any-return]
                "insider_transactions_consumer_storage_error",
                bucket=bucket,
                object_key=object_key,
                symbol=symbol,
                error=str(exc),
            )
            raise

    # ------------------------------------------------------------------
    # Idempotency
    # ------------------------------------------------------------------

    async def is_duplicate(self, event_id: str) -> bool:
        if self._dedup_client is None:
            return False
        key = f"{self._dedup_prefix}:{event_id}"
        return bool(await self._dedup_client.exists(key))

    async def mark_processed(self, event_id: str) -> None:
        if self._dedup_client is None:
            return
        key = f"{self._dedup_prefix}:{event_id}"
        # TTL = 7 days (604,800 s) — matches the insider_transactions polling interval
        # so a dedup key never expires before the next identical message could arrive.
        await self._dedup_client.set(key, "1", ex=7 * 86400)

    # ------------------------------------------------------------------
    # Failure tracking
    # ------------------------------------------------------------------

    async def store_failure(self, failure: FailureInfo[None]) -> None:  # type: ignore[override]
        logger.error(  # type: ignore[no-any-return]
            "insider_transactions_consumer_failure",
            event_id=failure.event_id,
            error=str(failure.last_error),
        )

    async def update_failure(self, failure: FailureInfo[None]) -> None:
        logger.warning(  # type: ignore[no-any-return]
            "insider_transactions_consumer_failure_retry",
            event_id=failure.event_id,
            attempt=failure.attempt,
        )

    async def _dead_letter_impl(self, failure: FailureInfo[None]) -> None:
        logger.error(  # type: ignore[no-any-return]
            "insider_transactions_consumer_dead_lettered",
            event_id=failure.event_id,
            attempts=failure.attempt,
        )

    async def get_pending_retries(self) -> list[FailureInfo[None]]:
        return []

    async def process_message_from_failure(self, failure: FailureInfo[None]) -> None:
        logger.warning(  # type: ignore[no-any-return]
            "insider_transactions_consumer_retry_not_supported",
            event_id=failure.event_id,
        )

    async def get_unit_of_work(self) -> UnitOfWorkProtocol:
        return _NoOpUoW()  # type: ignore[return-value]

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def deserialize_value(self, raw: bytes, schema_path: str | None = None) -> dict[str, Any]:
        """Deserialise Confluent Avro wire-format or fall back to JSON (BP-122)."""
        if raw and raw[0:1] == b"\x00" and schema_path:
            from messaging.kafka.serialization_utils import deserialize_confluent_avro  # type: ignore[import-untyped]

            return deserialize_confluent_avro(schema_path, raw)  # type: ignore[no-any-return]
        return json.loads(raw)  # type: ignore[no-any-return]

    def get_schema_path(self, topic: str) -> str | None:
        if topic == "market.dataset.fetched":
            return _DATASET_FETCHED_SCHEMA_PATH
        return None

    def extract_event_id(self, value: dict[str, Any]) -> str:
        return str(value.get("event_id", ""))
