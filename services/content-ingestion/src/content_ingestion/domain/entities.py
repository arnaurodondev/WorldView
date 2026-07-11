"""Domain entities for the Content Ingestion service."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import common.ids
import common.time
from content_ingestion.domain.exceptions import InvalidStateTransition
from contracts.enums import (  # type: ignore[import-untyped]
    ContentSourceType as SourceType,
)
from contracts.enums import (  # type: ignore[import-untyped]
    IngestionTaskStatus as IngestionTaskStatus,
)


@dataclass
class Source:
    """A configured polling source."""

    name: str
    source_type: SourceType
    enabled: bool
    config: dict[str, Any]
    id: UUID = field(default_factory=common.ids.new_uuid7)
    created_at: datetime = field(default_factory=common.time.utc_now)


@dataclass(frozen=True)
class FetchResult:
    """Raw result of a single HTTP fetch attempt.

    Attributes
    ----------
        published_at: Publication datetime as reported by the source API, or None if not
            available. This is the article's *editorial* date, distinct from ``fetched_at``
            (when our crawler pulled it). Used as ``evidence_date`` when writing
            ``relation_evidence`` rows in S7 — critical for correct temporal decay.
        is_backfill: True when this result was produced during a boot-time historical
            backfill run (i.e. ``BACKFILL_ENABLED=true``).  Propagated through the
            pipeline so that S10 can suppress alert fan-out for historical documents.

    """

    source_id: UUID
    url: str
    url_hash: str
    raw_bytes: bytes
    fetched_at: datetime
    http_status: int
    content_type: str
    published_at: datetime | None = None
    is_backfill: bool = False
    title: str | None = None


@dataclass(frozen=True)
class RawArticle:
    """A raw article ready for storage and Kafka publish.

    Attributes
    ----------
        published_at: Source-reported publication datetime, or None.  When present, S7
            MUST use this as ``relation_evidence.evidence_date`` so the temporal decay
            formula reflects the article's *actual* age, not when it was ingested.
        is_backfill: True for documents ingested during a historical backfill run.
            Propagated through the Kafka event so S10 can suppress alert fan-out.

    """

    source_type: SourceType
    url: str
    url_hash: str
    raw_bytes: bytes
    fetched_at: datetime
    byte_size: int
    published_at: datetime | None = None
    is_backfill: bool = False
    id: UUID = field(default_factory=common.ids.new_uuid7)


# ── Scheduler-Worker task entity ──────────────────────────────────────────────

_CLAIMABLE_STATUSES = frozenset({IngestionTaskStatus.PENDING, IngestionTaskStatus.RETRY})


@dataclass
class ContentIngestionTask:
    """A unit of work representing a single fetch cycle for one content source.

    State machine::

        PENDING ──→ CLAIMED ──→ RUNNING ──→ SUCCEEDED
                                        ├──→ RETRY  (attempt_count < max_attempts)
                                        └──→ FAILED (attempt_count >= max_attempts, or immediate)
    """

    # Identity
    source_id: UUID
    source_name: str
    source_type: SourceType

    # State machine
    status: IngestionTaskStatus = IngestionTaskStatus.PENDING

    # Lease
    worker_id: str | None = None
    leased_at: datetime | None = None
    lease_expires: datetime | None = None

    # Retry
    attempt_count: int = 0
    max_attempts: int = 5
    error_detail: str | None = None

    # Scheduling
    is_backfill: bool = False
    window_start: datetime | None = None

    # Retry backoff — earliest time this task may be picked up by the scheduler.
    # NULL means the task is ready to be claimed immediately.
    next_attempt_at: datetime | None = None

    # Source configuration — carried from the sources table so adapters can
    # read symbol, from_date, to_date, etc. without a second DB round-trip.
    # Populated by TaskRepository.claim_batch via JOIN on sources.
    source_config: dict = field(default_factory=dict)

    # Audit
    id: UUID = field(default_factory=common.ids.new_uuid7)
    created_at: datetime = field(default_factory=common.time.utc_now)
    updated_at: datetime = field(default_factory=common.time.utc_now)

    # ── State transitions ─────────────────────────────────────────────────

    def claim(self, worker_id: str, lease_seconds: int) -> None:
        """Transition PENDING/RETRY → CLAIMED, set worker lease."""
        if self.status not in _CLAIMABLE_STATUSES:
            raise InvalidStateTransition(f"Cannot claim task in status {self.status!r}; must be PENDING or RETRY")
        self.status = IngestionTaskStatus.CLAIMED
        self.worker_id = worker_id
        self.leased_at = common.time.utc_now()
        self.lease_expires = self.leased_at + timedelta(seconds=lease_seconds)
        self.updated_at = common.time.utc_now()

    def start(self) -> None:
        """Transition CLAIMED → RUNNING."""
        if self.status != IngestionTaskStatus.CLAIMED:
            raise InvalidStateTransition(f"Cannot start task in status {self.status!r}; must be CLAIMED")
        self.status = IngestionTaskStatus.RUNNING
        self.attempt_count += 1
        self.updated_at = common.time.utc_now()

    def succeed(self) -> None:
        """Transition RUNNING → SUCCEEDED."""
        if self.status != IngestionTaskStatus.RUNNING:
            raise InvalidStateTransition(f"Cannot succeed task in status {self.status!r}; must be RUNNING")
        self.status = IngestionTaskStatus.SUCCEEDED
        self.worker_id = None
        self.lease_expires = None
        self.updated_at = common.time.utc_now()

    def fail(self, error: str) -> None:
        """Transition RUNNING → FAILED or RETRY depending on attempts remaining."""
        if self.status != IngestionTaskStatus.RUNNING:
            raise InvalidStateTransition(f"Cannot fail task in status {self.status!r}; must be RUNNING")
        self.error_detail = error
        self.worker_id = None
        self.lease_expires = None
        if self.attempt_count >= self.max_attempts:
            self.status = IngestionTaskStatus.FAILED
        else:
            self.status = IngestionTaskStatus.RETRY
        self.updated_at = common.time.utc_now()

    def retry(self, reason: str) -> None:
        """Transition RUNNING → RETRY unconditionally (e.g. advisory lock held).

        Unlike ``fail()``, this always transitions to RETRY regardless of
        ``attempt_count`` vs ``max_attempts``.  The attempt is not counted as
        a true failure — it was pre-empted by contention, not an error.
        """
        if self.status != IngestionTaskStatus.RUNNING:
            raise InvalidStateTransition(f"Cannot retry task in status {self.status!r}; must be RUNNING")
        self.error_detail = reason
        self.worker_id = None
        self.lease_expires = None
        self.status = IngestionTaskStatus.RETRY
        self.updated_at = common.time.utc_now()

    # ── Queries ───────────────────────────────────────────────────────────

    @property
    def is_claimable(self) -> bool:
        """True if the task can be claimed by a worker.

        Returns False if ``next_attempt_at`` is set to a future time, meaning
        the task is in a EODHD 429 backoff window and must not be dispatched.
        The repository's ``claim_batch`` query enforces the same filter at the
        SQL level; this property is here for use-case / unit-test assertions.
        """
        if self.status not in _CLAIMABLE_STATUSES:
            return False
        return not (self.next_attempt_at is not None and self.next_attempt_at > common.time.utc_now())

    def is_lease_expired(self, now: datetime) -> bool:
        """True if the current lease has passed its expiry time."""
        if self.lease_expires is None:
            return False
        return now > self.lease_expires

    # ── Factory ───────────────────────────────────────────────────────────

    @classmethod
    def create_for_source(
        cls,
        source: Source,
        *,
        is_backfill: bool = False,
        window_start: datetime | None = None,
    ) -> ContentIngestionTask:
        """Create a new task from a Source entity."""
        return cls(
            source_id=source.id,
            source_name=source.name,
            source_type=source.source_type,
            is_backfill=is_backfill,
            window_start=window_start,
        )


# ── Prediction Market entities ─────────────────────────────────────────────────


# PLAN-0053 T-C-3-04: category normalization map.
# WHY this lives here (and not on the consumer/adapter): the canonical category
# is part of the domain DTO — a market's category is a property of the data, not
# of any specific provider. Keeping the normalisation pure-domain means consumers,
# tests, and the API layer all see the same buckets without duplication.
#
# Each entry maps a lowercase Polymarket tag/category (the dictionary key) to
# one of our four canonical frontend buckets ("politics" | "crypto" | "sports" |
# "macro").  Tags not appearing here fall through to the title-keyword heuristic.
# Order is irrelevant — lookup is direct dict access.
_CATEGORY_NORMALIZATION_MAP: dict[str, str] = {
    # Politics
    "politics": "politics",
    "pol": "politics",
    "election": "politics",
    "elections": "politics",
    "2024 election": "politics",
    "2024 elections": "politics",
    "us election": "politics",
    "us politics": "politics",
    "president": "politics",
    "presidential": "politics",
    "trump": "politics",
    "biden": "politics",
    # Crypto / DeFi
    "crypto": "crypto",
    "cryptocurrency": "crypto",
    "defi": "crypto",
    "bitcoin": "crypto",
    "btc": "crypto",
    "ethereum": "crypto",
    "eth": "crypto",
    "solana": "crypto",
    "sol": "crypto",
    # Sports — Polymarket tags individual leagues frequently.
    "sports": "sports",
    "nba": "sports",
    "nfl": "sports",
    "nhl": "sports",
    "mlb": "sports",
    "soccer": "sports",
    "football": "sports",
    "champions league": "sports",
    "world cup": "sports",
    "olympics": "sports",
    # Macro / Economy
    "macro": "macro",
    "macroeconomics": "macro",
    "economy": "macro",
    "economics": "macro",
    "fed": "macro",
    "fomc": "macro",
    "inflation": "macro",
    "cpi": "macro",
    "interest rates": "macro",
    "rates": "macro",
    "tariffs": "macro",
    "tariff": "macro",
}


# Title-keyword heuristic — used when no tag maps cleanly. Mirrors the frontend
# ``categorize()`` function so server- and client-side classification agree on
# the same set of titles. Order matters: macro is checked first so a "Fed cuts
# rates AND BTC > 100k" market is tagged macro (correct call for finance UX).
_TITLE_HEURISTIC_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "macro",
        (
            "fed",
            "rate",
            "inflation",
            "gdp",
            "cpi",
            "unemployment",
            "recession",
            "fomc",
            "payroll",
            "pce",
            "treasury",
            "yield",
            "deficit",
            "tariff",
            "economic",
            "fiscal",
            "monetary",
            "pmi",
        ),
    ),
    (
        "politics",
        (
            "election",
            "president",
            "presidential",
            "senate",
            "congress",
            "vote",
            "primary",
            "governor",
            "supreme court",
            "impeach",
        ),
    ),
    (
        "sports",
        (
            "nba",
            "nfl",
            "mlb",
            "nhl",
            "superbowl",
            "super bowl",
            "world cup",
            "olympics",
            "champion",
            "f1",
            "fifa",
            "uefa",
        ),
    ),
    (
        "crypto",
        (
            "bitcoin",
            "ethereum",
            "btc",
            "eth",
            "crypto",
            "solana",
            "sol",
            "altcoin",
        ),
    ),
)


def _normalize_category(raw: str) -> str | None:
    """Map a raw Polymarket tag/category string to a canonical bucket or None.

    PLAN-0053 T-C-3-04. Returns one of {"politics", "crypto", "sports", "macro"}
    when the tag matches our normalisation table, else None to signal "unmapped"
    (caller should fall back to title-keyword heuristics or keep the raw tag).
    """
    key = raw.strip().lower()
    if not key:
        return None
    return _CATEGORY_NORMALIZATION_MAP.get(key)


def _categorize_by_title(title: str) -> str | None:
    """Heuristic: assign a canonical category based on title keywords.

    PLAN-0053 T-C-3-04 — fallback when no tag maps cleanly. Mirrors the
    frontend's ``categorize()`` so client and server stay in sync. Returns
    None when no keyword matches; caller decides what to do (keep raw tag,
    leave NULL, etc).
    """
    text = title.strip().lower()
    if not text:
        return None
    for canonical, keywords in _TITLE_HEURISTIC_RULES:
        if any(kw in text for kw in keywords):
            return canonical
    return None


@dataclass(frozen=True, slots=True)
class OutcomeSnapshot:
    """A single binary outcome of a prediction market (e.g. "Yes" or "No").

    Invariants:
        - ``name`` and ``token_id`` must be non-empty strings.
        - ``price`` must be in the closed interval [0.0, 1.0].
    """

    name: str
    token_id: str
    price: float

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("OutcomeSnapshot.name must not be empty")
        if not self.token_id:
            raise ValueError("OutcomeSnapshot.token_id must not be empty")
        if not (0.0 <= self.price <= 1.0):
            raise ValueError(f"OutcomeSnapshot.price must be in [0.0, 1.0], got {self.price}")


# PLAN-0056 QA — cap for untrusted Polymarket free-text fields (question / title /
# category / name). These strings flow unbounded from the public Gamma / Data-API
# into the synthetic-doc body + Avro payloads; bound them defensively so a
# pathologically long field cannot bloat storage or downstream messages.
_MAX_PREDICTION_TEXT_LEN = 500


def _truncate_text(value: str, *, max_length: int = _MAX_PREDICTION_TEXT_LEN) -> str:
    """Truncate an untrusted free-text field to ``max_length`` characters.

    Returns the input unchanged when already within bounds. Non-str inputs are
    coerced defensively (callers already pass strings, but this keeps the guard
    total).
    """
    text = value if isinstance(value, str) else str(value)
    return text if len(text) <= max_length else text[:max_length]


@dataclass(frozen=True, slots=True)
class PredictionMarketFetchResult:
    """Immutable result of fetching one prediction market from Polymarket.

    This is a pure domain object — no infrastructure imports.  The adapter
    constructs instances via :meth:`from_gamma_response` and may attach the
    MinIO key via ``dataclasses.replace()`` after upload.

    Invariants:
        - ``fetched_at`` must be UTC-aware.
        - ``outcomes`` must contain at least 2 entries.
    """

    source_type: SourceType
    market_id: str
    question: str
    outcomes: list[OutcomeSnapshot]
    raw_bytes: bytes
    fetched_at: datetime
    description: str | None = None
    volume_24h: float | None = None
    liquidity: float | None = None
    close_time: datetime | None = None
    resolution_status: str = "open"
    resolved_answer: str | None = None
    minio_bronze_key: str | None = None
    # WHY market_slug: Polymarket event slug (e.g. "will-bitcoin-reach-100k") used to
    # construct the Polymarket event URL on the frontend. Absent from older Gamma API
    # responses → default "". Forward-compatible: new field with safe default.
    market_slug: str = ""
    # F-DP1-06: high-level Polymarket category (politics, crypto, sports, business, ...).
    # Sourced from Gamma API ``category`` field; falls back to the first ``tags`` entry
    # when ``category`` is absent. ``None`` means "no category provided" — the downstream
    # writer leaves the prediction_markets.category column untouched (COALESCE preserve).
    category: str | None = None
    id: UUID = field(default_factory=common.ids.new_uuid7)

    def __post_init__(self) -> None:
        if self.fetched_at.tzinfo is None:
            raise ValueError("PredictionMarketFetchResult.fetched_at must be UTC-aware")
        if len(self.outcomes) < 2:
            raise ValueError("PredictionMarketFetchResult.outcomes must have at least 2 entries")

    @classmethod
    def from_gamma_response(
        cls,
        raw: dict,
        fetched_at: datetime,
    ) -> PredictionMarketFetchResult:
        """Construct from a Polymarket Gamma API market dict.

        Maps Gamma API field names to domain attributes.  All optional fields
        use defensive ``.get()`` with None defaults to tolerate absent keys.
        """
        # WHY dual-format parsing: The Polymarket Gamma API changed its response schema
        # circa April 2026.  Old format: `tokens` list of {outcome, token_id, price}.
        # New format: `outcomes` (JSON string of names), `outcomePrices` (JSON string of
        # decimal strings), `clobTokenIds` (JSON string of token ID strings).
        # We parse both and prefer the old format when `tokens` is present.
        tokens: list[dict] = raw.get("tokens") or []
        if tokens:
            # Old Gamma API format: tokens is a list of {outcome, token_id, price} dicts
            outcomes = [
                OutcomeSnapshot(
                    name=t.get("outcome", ""),
                    token_id=t.get("token_id", ""),
                    price=float(t.get("price", 0.0)),
                )
                for t in tokens
            ]
        else:
            # New Gamma API format: outcomes/outcomePrices/clobTokenIds are JSON strings
            try:
                outcome_names: list[str] = json.loads(raw.get("outcomes") or "[]")
            except (json.JSONDecodeError, TypeError):
                outcome_names = []
            try:
                outcome_prices_raw: list[str] = json.loads(raw.get("outcomePrices") or "[]")
            except (json.JSONDecodeError, TypeError):
                outcome_prices_raw = []
            try:
                clob_ids: list[str] = json.loads(raw.get("clobTokenIds") or "[]")
            except (json.JSONDecodeError, TypeError):
                clob_ids = []
            # Zip to shortest to avoid IndexError on mismatched lengths
            outcomes = [
                OutcomeSnapshot(
                    name=name,
                    token_id=clob_ids[i] if i < len(clob_ids) else "",
                    price=float(outcome_prices_raw[i]) if i < len(outcome_prices_raw) else 0.0,
                )
                for i, name in enumerate(outcome_names)
            ]

        # Map Gamma "closed" status → domain "cancelled" (R15: stable values)
        raw_status = raw.get("status", "active")
        if raw_status == "closed":
            resolution_status = "cancelled"
        elif raw_status == "resolved":
            resolution_status = "resolved"
        else:
            resolution_status = "open"

        close_time: datetime | None = None
        raw_end_date = raw.get("endDate")
        if raw_end_date:
            try:
                close_time = datetime.fromisoformat(raw_end_date.replace("Z", "+00:00")).astimezone(UTC)
            except (ValueError, AttributeError):
                close_time = None

        # WHY try multiple slug fields: Gamma API uses "slug" on market objects and
        # "groupItemSlug" on grouped markets. The "market_slug" key is used in older
        # snapshots. Prefer whichever is populated; default "" for missing/null values.
        market_slug = raw.get("slug") or raw.get("market_slug") or raw.get("groupItemSlug") or ""

        # F-DP1-06: extract category from Gamma API.  The new Gamma API exposes a
        # top-level ``category`` string (e.g. "Politics", "Crypto", "Sports").  Some
        # market records instead have a ``tags`` list of dicts (``[{"label": "Crypto"}]``)
        # or a ``tags`` list of plain strings.  We accept either shape and fall back to
        # the first non-empty tag when ``category`` is absent.  None preserves existing
        # DB values via the consumer's COALESCE upsert.
        #
        # PLAN-0053 T-C-3-04: extended categorization. The previous logic took the
        # FIRST tag verbatim — which produced 60%+ "other" buckets because Polymarket
        # tags individual events ("NBA", "FOMC", "Bitcoin") rather than coarse buckets.
        # We now:
        #   1. Walk the ENTIRE tag list (not just the first), trying to map any to
        #      one of our 4 canonical buckets via _CATEGORY_NORMALIZATION_MAP.
        #   2. Fall back to title-keyword heuristics when no tag maps cleanly.
        #   3. Last-resort: keep the first non-empty raw tag (preserves backward-
        #      compat for callers querying by raw category names like "elections").
        raw_category: Any = raw.get("category")
        category: str | None = None
        if isinstance(raw_category, str) and raw_category.strip():
            normalized = _normalize_category(raw_category)
            category = normalized if normalized is not None else raw_category.strip().lower()
        else:
            tags_raw = raw.get("tags") or []
            collected_tags: list[str] = []
            if isinstance(tags_raw, list):
                for tag in tags_raw:
                    if isinstance(tag, str) and tag.strip():
                        collected_tags.append(tag.strip())
                    elif isinstance(tag, dict):
                        label = tag.get("label") or tag.get("name") or ""
                        if isinstance(label, str) and label.strip():
                            collected_tags.append(label.strip())

            # First pass: walk every tag looking for one that maps cleanly.
            for tag in collected_tags:
                normalized = _normalize_category(tag)
                if normalized is not None:
                    category = normalized
                    break

            # Second pass: title-keyword heuristic if no tag matched.
            if category is None:
                title_text = raw.get("question") or raw.get("title") or ""
                if isinstance(title_text, str) and title_text:
                    category = _categorize_by_title(title_text)

            # Third pass: keep raw first tag verbatim (existing behaviour).
            if category is None and collected_tags:
                category = collected_tags[0].lower()

        return cls(
            source_type=SourceType.POLYMARKET,
            market_id=raw.get("conditionId", ""),
            # PLAN-0056 QA: bound untrusted free-text before it enters the DTO.
            question=_truncate_text(raw.get("question", "")),
            description=raw.get("description"),
            outcomes=outcomes,
            volume_24h=float(raw["volume24hr"]) if raw.get("volume24hr") is not None else None,
            liquidity=float(raw["liquidity"]) if raw.get("liquidity") is not None else None,
            close_time=close_time,
            resolution_status=resolution_status,
            resolved_answer=raw.get("resolvedAnswer"),
            raw_bytes=json.dumps(raw).encode(),
            fetched_at=fetched_at,
            minio_bronze_key=None,
            market_slug=market_slug,
            category=_truncate_text(category) if category is not None else None,
        )


# ── PLAN-0056 Wave B1 — deeper-stream Polymarket fetch-result entities ─────────
#
# Four immutable domain DTOs, one per new Polymarket ingestion stream (PRD-0033):
#   • PredictionEventFetchResult   — Gamma /events group metadata
#   • PredictionHistoryFetchResult — CLOB /prices-history token price series
#   • PredictionTradeFetchResult   — Data-API /trades individual fills
#   • PredictionOIFetchResult      — Data-API /oi open-interest snapshots
#
# All mirror ``PredictionMarketFetchResult``: pure-domain (no infra imports),
# frozen + slotted, a ``from_*_response`` classmethod that tolerates absent keys
# defensively, a ``fetched_at`` (UTC-aware) and an optional ``minio_bronze_key``
# attached post-upload via ``dataclasses.replace()``.


def _parse_iso_datetime(raw: Any) -> datetime | None:
    """Parse an ISO-8601 string (with optional trailing ``Z``) into UTC, or None.

    Tolerant: returns ``None`` for missing/blank/malformed input rather than
    raising, so a single bad date field never fails an entire parse.
    """
    if not raw or not isinstance(raw, str):
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(UTC)
    except (ValueError, AttributeError):
        return None


def _parse_epoch_seconds(raw: Any) -> datetime | None:
    """Parse a Unix epoch-seconds value (int/float/str) into a UTC datetime, or None."""
    if raw is None:
        return None
    try:
        return datetime.fromtimestamp(float(raw), tz=UTC)
    except (ValueError, TypeError, OSError, OverflowError):
        return None


@dataclass(frozen=True, slots=True)
class PredictionEventFetchResult:
    """Immutable result of fetching one Polymarket *event* (a group of markets).

    A Gamma ``/events`` record groups several related child markets under a
    single question theme (e.g. "2028 US Presidential Election"). We capture the
    group identity + metadata; the child markets themselves flow through the
    existing markets stream.

    Invariants:
        - ``fetched_at`` must be UTC-aware.
        - ``event_id`` must be non-empty.
    """

    source_type: SourceType
    event_id: str
    title: str
    raw_bytes: bytes
    fetched_at: datetime
    category: str | None = None
    start_date: datetime | None = None
    end_date: datetime | None = None
    market_count: int = 0
    minio_bronze_key: str | None = None
    id: UUID = field(default_factory=common.ids.new_uuid7)

    def __post_init__(self) -> None:
        if self.fetched_at.tzinfo is None:
            raise ValueError("PredictionEventFetchResult.fetched_at must be UTC-aware")
        if not self.event_id:
            raise ValueError("PredictionEventFetchResult.event_id must not be empty")

    @classmethod
    def from_gamma_response(cls, raw: dict, fetched_at: datetime) -> PredictionEventFetchResult:
        """Construct from a Polymarket Gamma ``/events`` record.

        Parses group id, title/name, category (or first tag), start/end dates and
        the count of child markets. All optional fields default defensively.
        """
        # WHY category from tags fallback: some event records omit a top-level
        # ``category`` and instead carry a ``tags`` list (of dicts with ``label``/
        # ``name`` or of plain strings). Prefer explicit ``category``; else take the
        # first non-empty tag label; else None (downstream leaves the column untouched).
        raw_category: Any = raw.get("category")
        category: str | None = None
        if isinstance(raw_category, str) and raw_category.strip():
            category = raw_category.strip()
        else:
            tags_raw = raw.get("tags") or []
            if isinstance(tags_raw, list):
                for tag in tags_raw:
                    if isinstance(tag, str) and tag.strip():
                        category = tag.strip()
                        break
                    if isinstance(tag, dict):
                        label = tag.get("label") or tag.get("name") or ""
                        if isinstance(label, str) and label.strip():
                            category = label.strip()
                            break

        child_markets = raw.get("markets")
        market_count = len(child_markets) if isinstance(child_markets, list) else 0

        return cls(
            source_type=SourceType.POLYMARKET_GAMMA_EVENTS,
            event_id=str(raw.get("id") or raw.get("slug") or ""),
            # PLAN-0056 QA: bound untrusted free-text (title / name / category).
            title=_truncate_text(raw.get("title") or raw.get("name") or ""),
            category=_truncate_text(category) if category is not None else None,
            start_date=_parse_iso_datetime(raw.get("startDate")),
            end_date=_parse_iso_datetime(raw.get("endDate")),
            market_count=market_count,
            raw_bytes=json.dumps(raw).encode(),
            fetched_at=fetched_at,
            minio_bronze_key=None,
        )


@dataclass(frozen=True, slots=True)
class PricePoint:
    """A single (timestamp, price) datapoint from the CLOB price-history series."""

    timestamp: datetime
    price: float


@dataclass(frozen=True, slots=True)
class PredictionHistoryFetchResult:
    """Immutable result of fetching a CLOB ``/prices-history`` series for one token.

    Invariants:
        - ``fetched_at`` must be UTC-aware.
        - ``token_id`` must be non-empty.
    """

    source_type: SourceType
    token_id: str
    interval: str
    points: list[PricePoint]
    raw_bytes: bytes
    fetched_at: datetime
    minio_bronze_key: str | None = None
    # PLAN-0056 Wave B4: parent market ``conditionId`` (Gamma /markets key) so the
    # S3 ``prediction_market_prices.market_id`` column JOINs to ``prediction_markets``.
    # ``None`` only for legacy flat-``token_ids`` config with no parent mapping.
    market_id: str | None = None
    id: UUID = field(default_factory=common.ids.new_uuid7)

    def __post_init__(self) -> None:
        if self.fetched_at.tzinfo is None:
            raise ValueError("PredictionHistoryFetchResult.fetched_at must be UTC-aware")
        if not self.token_id:
            raise ValueError("PredictionHistoryFetchResult.token_id must not be empty")

    @classmethod
    def from_api_response(
        cls,
        token_id: str,
        raw: dict,
        fetched_at: datetime,
        *,
        interval: str,
        condition_id: str | None = None,
    ) -> PredictionHistoryFetchResult:
        """Construct from a CLOB ``/prices-history`` response.

        The CLOB response is ``{"history": [{"t": <epoch_s>, "p": <price>}, ...]}``.
        Malformed individual datapoints are skipped rather than failing the parse.

        ``condition_id`` (PLAN-0056 Wave B4) is the PARENT market conditionId that
        owns this ``token_id`` outcome; it is stored as ``market_id`` so downstream
        price rows associate with the parent market, not the per-outcome token.
        """
        history = raw.get("history") if isinstance(raw, dict) else raw
        points: list[PricePoint] = []
        if isinstance(history, list):
            for dp in history:
                if not isinstance(dp, dict):
                    continue
                ts = _parse_epoch_seconds(dp.get("t"))
                if ts is None:
                    continue
                raw_price = dp.get("p")
                if raw_price is None:
                    continue
                try:
                    price = float(raw_price)
                except (TypeError, ValueError):
                    continue
                points.append(PricePoint(timestamp=ts, price=price))

        return cls(
            source_type=SourceType.POLYMARKET_CLOB,
            token_id=token_id,
            interval=interval,
            points=points,
            raw_bytes=json.dumps(raw).encode(),
            fetched_at=fetched_at,
            minio_bronze_key=None,
            market_id=condition_id,
        )


@dataclass(frozen=True, slots=True)
class PredictionTradeFetchResult:
    """Immutable result of fetching one Polymarket Data-API ``/trades`` fill.

    Invariants:
        - ``fetched_at`` must be UTC-aware.
        - ``trade_id`` must be non-empty.
    """

    source_type: SourceType
    trade_id: str
    token_id: str
    price: float
    size_usd: float
    side: str
    traded_at: datetime
    raw_bytes: bytes
    fetched_at: datetime
    minio_bronze_key: str | None = None
    # PLAN-0056 Wave B4: parent market ``conditionId`` (the /trades feed is polled
    # per condition_id) so the S3 ``prediction_market_trades.market_id`` column
    # JOINs to ``prediction_markets``.  ``None`` only for legacy config.
    market_id: str | None = None
    id: UUID = field(default_factory=common.ids.new_uuid7)

    def __post_init__(self) -> None:
        if self.fetched_at.tzinfo is None:
            raise ValueError("PredictionTradeFetchResult.fetched_at must be UTC-aware")
        if not self.trade_id:
            raise ValueError("PredictionTradeFetchResult.trade_id must not be empty")

    @classmethod
    def from_api_response(
        cls,
        raw: dict,
        fetched_at: datetime,
        *,
        condition_id: str | None = None,
    ) -> PredictionTradeFetchResult:
        """Construct from a Data-API ``/trades`` record.

        Field names vary across Data-API versions — we accept the common
        aliases (``transactionHash``/``id`` for the trade id, ``asset``/
        ``token_id`` for the token, ``size``/``usdcSize`` for USD size).

        ``condition_id`` (PLAN-0056 Wave B4) is the PARENT market conditionId that
        the trades feed was polled under; it is stored as ``market_id`` so trade
        rows associate with the parent market, not the per-outcome token.
        """
        traded_at = _parse_epoch_seconds(raw.get("timestamp")) or fetched_at
        return cls(
            source_type=SourceType.POLYMARKET_DATA_TRADES,
            trade_id=str(raw.get("transactionHash") or raw.get("id") or ""),
            token_id=str(raw.get("asset") or raw.get("token_id") or ""),
            price=float(raw["price"]) if raw.get("price") is not None else 0.0,
            size_usd=float(raw["size"])
            if raw.get("size") is not None
            else (float(raw["usdcSize"]) if raw.get("usdcSize") is not None else 0.0),
            side=str(raw.get("side") or ""),
            traded_at=traded_at,
            raw_bytes=json.dumps(raw).encode(),
            fetched_at=fetched_at,
            minio_bronze_key=None,
            market_id=condition_id,
        )


@dataclass(frozen=True, slots=True)
class PredictionOIFetchResult:
    """Immutable result of fetching a Polymarket Data-API open-interest snapshot.

    Invariants:
        - ``fetched_at`` must be UTC-aware.
        - ``market_id`` must be non-empty.
    """

    source_type: SourceType
    market_id: str
    open_interest_usd: float
    snapshot_date: datetime
    raw_bytes: bytes
    fetched_at: datetime
    volume_24h_usd: float | None = None
    minio_bronze_key: str | None = None
    id: UUID = field(default_factory=common.ids.new_uuid7)

    def __post_init__(self) -> None:
        if self.fetched_at.tzinfo is None:
            raise ValueError("PredictionOIFetchResult.fetched_at must be UTC-aware")
        if not self.market_id:
            raise ValueError("PredictionOIFetchResult.market_id must not be empty")

    @classmethod
    def from_api_response(
        cls,
        market_id: str,
        raw: dict,
        fetched_at: datetime,
    ) -> PredictionOIFetchResult:
        """Construct from a Data-API open-interest response.

        Accepts the ``openInterest``/``oi`` alias for total OI (USD) and
        ``volume24hr``/``volume24h`` for the trailing-24h volume. ``market_id``
        is passed in explicitly because the OI response does not always echo it.
        """
        oi_raw = raw.get("openInterest")
        if oi_raw is None:
            oi_raw = raw.get("oi")
        vol_raw = raw.get("volume24hr")
        if vol_raw is None:
            vol_raw = raw.get("volume24h")
        return cls(
            source_type=SourceType.POLYMARKET_DATA_OI,
            market_id=market_id,
            open_interest_usd=float(oi_raw) if oi_raw is not None else 0.0,
            volume_24h_usd=float(vol_raw) if vol_raw is not None else None,
            snapshot_date=fetched_at,
            raw_bytes=json.dumps(raw).encode(),
            fetched_at=fetched_at,
            minio_bronze_key=None,
        )
