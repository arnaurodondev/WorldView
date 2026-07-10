"""Alert fan-out use case.

Resolves watchers for an incoming intelligence event, writes alert +
pending rows + outbox event in a single DB transaction, then pushes via
WebSocket *after* commit.

Backfill suppression rules (PRD AD-10):
- nlp.signal.detected.v1 / graph.state.changed.v1: suppress ALL backfill.
- intelligence.contradiction.v1: suppress only if is_backfill AND the event
  is older than 30 days (recent-impact contradictions are still useful).

Dedup key (PRD AD-9): sha256(entity_id:alert_type:window_bucket)
where window_bucket = epoch_seconds // dedup_window_seconds.
source_event_id is intentionally excluded so that multiple events about
the same entity+type within one window are collapsed into one alert.

Severity (PRD-0021 §6.5):
- nlp.signal.detected.v1: severity = SeverityThresholds.classify(market_impact_score)
- graph.state.changed.v1 / intelligence.contradiction.v1: severity = MEDIUM (F-13 override)
- market.prediction.signal.v1 (PLAN-0056 D3): severity = classify(market_impact_score);
  the score is already adverse-boosted by S7 (D2), so bearish moves land higher.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import UUID

import fastavro  # type: ignore[import-untyped]
import fastavro.schema  # type: ignore[import-untyped]

from alert.application.ports.metrics import IAlertMetrics, NoOpAlertMetrics
from alert.domain.entities import Alert, OutboxEvent, PendingAlert, SeverityThresholds
from alert.domain.enums import AlertSeverity, AlertType
from alert.domain.errors import DuplicateAlertError
from common.ids import new_uuid7  # type: ignore[import-untyped]
from common.time import utc_now  # type: ignore[import-untyped]
from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from alert.application.ports.entity_resolver import EntityNameResolverPort
    from alert.application.ports.notification import INotificationPublisher
    from alert.application.ports.repositories import (
        AlertSaveRepositoryPort,
        DedupRepositoryPort,
        OutboxRepositoryPort,
        PendingAlertRepositoryPort,
    )
    from alert.application.ports.watchlist import IWatchlistCache

    class RepoFactory:
        """Protocol for constructing repos from a session."""

        def __call__(
            self,
            session: AsyncSession,
        ) -> tuple[
            AlertSaveRepositoryPort,
            PendingAlertRepositoryPort,
            DedupRepositoryPort,
            OutboxRepositoryPort,
        ]: ...


logger = get_logger(__name__)  # type: ignore[no-any-return]

# ── Constants ──────────────────────────────────────────────────────────────────

_BACKFILL_MAX_AGE = timedelta(days=30)

TOPIC_ALERT_TYPE: dict[str, AlertType] = {
    "nlp.signal.detected.v1": AlertType.SIGNAL,
    "graph.state.changed.v1": AlertType.GRAPH_CHANGE,
    "intelligence.contradiction.v1": AlertType.CONTRADICTION,
    # PLAN-0056 Wave D3: prediction-market signals fan out like SIGNAL events —
    # severity from market_impact_score (NOT in the MEDIUM-override set below).
    "market.prediction.signal.v1": AlertType.PREDICTION,
}

# Topics that always get MEDIUM severity regardless of market_impact_score (PRD-0021 F-13)
_MEDIUM_OVERRIDE_TOPICS: frozenset[str] = frozenset({"graph.state.changed.v1", "intelligence.contradiction.v1"})

# ── Signal-label derivation table (PLAN-0048 Wave B-1) ─────────────────────────
# WHY a static dict (no LLM): the (claim_type, polarity) tuple → label is a
# deterministic 8-row mapping. Calling an LLM here would add latency, cost,
# and a new failure mode — all to produce strings the product team has fixed
# in the spec. Rule-based + lowercase-normalised inputs is the right shape.
#
# Fallback when claim_type or polarity is missing or unknown: render
# ``"<SEVERITY> signal"`` so the row still has actionable text instead of
# the bare alert_type ``"SIGNAL"`` (the BP-263 root cause).
_SIGNAL_LABEL_TABLE: dict[tuple[str, str], str] = {
    ("forward_guidance", "positive"): "Bullish guidance",
    ("forward_guidance", "negative"): "Bearish guidance",
    ("factual", "positive"): "Positive factual",
    ("factual", "negative"): "Negative factual",
    ("projection", "positive"): "Bullish projection",
    ("projection", "negative"): "Bearish projection",
    ("opinion", "positive"): "Bullish opinion",
    ("opinion", "negative"): "Bearish opinion",
}


def _derive_signal_label(event: dict[str, Any], severity: AlertSeverity) -> tuple[str, bool]:
    """Compute a human-readable signal label from the event payload.

    Returns ``(label, is_fallback)``. ``is_fallback`` is True when the
    (claim_type, polarity) lookup missed and we degraded to ``"<SEVERITY> signal"``.

    Callers use the flag to (a) compose a friendlier alert title from
    entity_name / ticker rather than emitting ``"LOW signal"``-style labels
    in the UI, and (b) emit a structured warning so we can quantify how
    often upstream events lack the fields we need.
    """
    claim_type_raw = event.get("claim_type")
    polarity_raw = event.get("polarity")
    # Defensive str() — JSON deserialisation could in theory hand us None or int.
    claim_type = str(claim_type_raw).lower() if claim_type_raw else ""
    polarity = str(polarity_raw).lower() if polarity_raw else ""
    label = _SIGNAL_LABEL_TABLE.get((claim_type, polarity))
    if label:
        return label, False
    # Fallback: severity.upper() always yields LOW/MEDIUM/HIGH/CRITICAL.
    return f"{str(severity).upper()} signal", True


# ── Graph-change humanisation (PLAN, Wave 4 alert-title clarity) ───────────────
# WHY this table: graph.state.changed.v1 events carry NO claim_type/polarity, so
# the signal-label path always degraded them to the bare "Graph pattern change".
# But the payload is actually rich — `canonical_types` lists every relation that
# changed (e.g. ["supplier_of", "supplier_of", "competes_with"]). Mapping each
# canonical relation type to a short human noun lets us compose
# "AAPL — 3 new graph links (2 supplier, 1 competitor)" instead of an opaque
# "Graph pattern change". The mapping is deterministic (no LLM) because the KG
# relation taxonomy is a fixed, small enum owned by S7.
#
# Keys are the lowercase canonical relation-type strings emitted by S7 in
# `graph.state.changed.v1.canonical_types`. Unknown types fall back to the
# generic word "link" so we never crash on an unmapped relation.
_RELATION_TYPE_NOUN: dict[str, str] = {
    "has_executive": "executive",
    "appointed_as": "executive",
    "board_member_of": "board",
    "employs": "hiring",
    "owns_stake_in": "ownership",
    "investment_in": "investment",
    "acquired_by": "acquisition",
    "supplier_of": "supplier",
    "competes_with": "competitor",
    "partner_of": "partnership",
    "produces": "product",
    "listed_on": "listing",
    "headquartered_in": "location",
    "operates_in_country": "location",
    "is_in_industry": "industry",
    "regulates": "regulatory",
    "analyst_rating": "analyst rating",
    "sentiment_signal": "sentiment",
}

# WHY this table: the `change_type` field tells us WHAT happened to the graph
# (new evidence arrived, a relation was created/removed, a contradiction surfaced).
# We turn it into a short human verb-phrase so the title reads naturally. Unknown
# change types fall back to the generic "graph update".
_CHANGE_TYPE_PHRASE: dict[str, str] = {
    "new_evidence": "graph update",
    "new_relation": "new connections",
    "relation_created": "new connections",
    "relation_removed": "removed connections",
    "relation_updated": "updated connections",
    "node_created": "new entity links",
    "contradiction": "conflicting evidence",
}


def _humanise_relation_counts(canonical_types: list[str]) -> str:
    """Turn a list of canonical relation types into a compact human breakdown.

    Example: ``["supplier_of", "supplier_of", "competes_with"]`` →
    ``"2 supplier, 1 competitor"``. Returns ``""`` when the list is empty so
    callers can decide whether to append a parenthetical breakdown at all.

    Categories are ordered by descending count (most-changed relation first)
    so the most salient change leads. Ties keep first-seen order for stability.
    """
    if not canonical_types:
        return ""
    # Count by humanised noun (collapses synonyms, e.g. has_executive +
    # appointed_as both → "executive").
    counts: dict[str, int] = {}
    for raw in canonical_types:
        noun = _RELATION_TYPE_NOUN.get(str(raw).lower(), "link")
        counts[noun] = counts.get(noun, 0) + 1
    # Sort by count desc, then by first-appearance order (dict preserves it).
    ordered = sorted(counts.items(), key=lambda kv: -kv[1])
    # Cap at the top 3 categories so the title stays scannable; collapse the
    # remainder into "+N more" if there are more than 3 distinct categories.
    parts = [f"{n} {noun}" for noun, n in ordered[:3]]
    if len(ordered) > 3:
        remaining = sum(n for _, n in ordered[3:])
        parts.append(f"+{remaining} more")
    return ", ".join(parts)


def _compose_graph_change_detail(event: dict[str, Any]) -> str:
    """Compose the descriptive tail for a GRAPH_CHANGE alert from its payload.

    Reads `change_type`, `canonical_types`, and `relation_ids` to produce text
    like ``"3 new graph links (2 supplier, 1 competitor)"``. Falls back
    gracefully as fields go missing:
      - full:  "graph update: 3 new links (2 supplier, 1 competitor)"
      - count only (no canonical_types): "graph update: 3 new links"
      - nothing usable: "graph pattern change"

    This is the single highest-leverage clarity fix: live data shows graph
    events make up ~95% of alerts and ALWAYS carried the bare template, even
    though every one of them ships a populated `canonical_types` list.
    """
    change_type = str(event.get("change_type") or "").lower()
    phrase = _CHANGE_TYPE_PHRASE.get(change_type, "graph update")

    canonical_types_raw = event.get("canonical_types")
    canonical_types: list[str] = [str(t) for t in canonical_types_raw] if isinstance(canonical_types_raw, list) else []

    # Prefer the count of changed relations; canonical_types length is the most
    # reliable counter (relation_ids can be empty even when types are present —
    # see live event 019eb7d5 with [] relation_ids but ["produces"] types).
    relation_ids_raw = event.get("relation_ids")
    relation_ids = relation_ids_raw if isinstance(relation_ids_raw, list) else []
    link_count = len(canonical_types) or len(relation_ids)

    if link_count == 0:
        # No structural detail available — return the bare humanised phrase.
        return phrase

    noun = "link" if link_count == 1 else "links"
    breakdown = _humanise_relation_counts(canonical_types)
    head = f"{phrase}: {link_count} new {noun}"
    if breakdown:
        return f"{head} ({breakdown})"
    return head


# ── Prediction-market humanisation (PLAN-0056 Wave D3) ─────────────────────────
# market.prediction.signal.v1 carries (trigger, polarity, question, market_id,
# url). We turn (trigger, polarity) into a short human phrase so the alert reads
# "a prediction is moving against <entity>" for adverse (bearish) moves and
# neutrally for favorable ones. Deterministic (no LLM) — the S7 vocabulary is a
# fixed 3x3 set. Severity is NOT touched here: it comes from market_impact_score
# (which S7 D2 already boosts for adverse moves), keeping the SeverityThresholds
# model the single source of magnitude.
_PREDICTION_TRIGGER_PHRASE: dict[str, str] = {
    "new_market": "new prediction market",
    "material_move": "prediction market moving",
    "resolution": "prediction market resolved",
}

# Direction the market is priced FOR the subject entity. ``bearish`` = a
# bad-for-the-entity outcome is being priced up → risk framing ("against").
_PREDICTION_POLARITY_DIRECTION: dict[str, str] = {
    "bearish": "against",
    "bullish": "in favor of",
    "neutral": "",
}

# Cap the market-question tail so the composed title stays scannable in the UI.
_PREDICTION_QUESTION_MAX = 80


def _compose_prediction_detail(event: dict[str, Any]) -> str:
    """Compose the descriptive tail for a PREDICTION alert from its payload.

    Reads ``trigger``, ``polarity``, and ``question`` to produce text like
    ``"prediction market moving against: Will <X> miss guidance?"``. Falls back
    gracefully as fields go missing:
      - full:    "prediction market moving against: <question>"
      - no dir:  "prediction market moving: <question>"  (neutral polarity)
      - no q:    "prediction market moving against"
      - nothing: "prediction market update"
    """
    trigger = str(event.get("trigger") or "").lower()
    phrase = _PREDICTION_TRIGGER_PHRASE.get(trigger, "prediction market update")

    polarity = str(event.get("polarity") or "").lower()
    direction = _PREDICTION_POLARITY_DIRECTION.get(polarity, "")
    head = f"{phrase} {direction}".strip() if direction else phrase

    question = str(event.get("question") or "").strip()
    if question:
        if len(question) > _PREDICTION_QUESTION_MAX:
            question = question[: _PREDICTION_QUESTION_MAX - 3] + "..."
        return f"{head}: {question}"
    return head


def _compose_alert_title(
    *,
    signal_label: str,
    entity_name: str | None,
    ticker: str | None,
    alert_type: AlertType,
    is_signal_label_fallback: bool,
    event: dict[str, Any] | None = None,
) -> str:
    """Compose a user-friendly alert subject.

    PLAN-0053 T-A-1-06 — per-type templates ensure no alert ever shows the bare
    ``"<EnumName> alert"`` (e.g. "Graph Change alert"). Each AlertType has an
    explicit template so users always see actionable text.

    Priority by alert_type:
      SIGNAL:
        1. ``"<subject>: <signal_label>"`` when label is meaningful and subject exists
        2. ``signal_label`` alone when no subject available
        3. ``"<subject>: Signal"`` fallback when label is bare-severity but subject exists
        4. ``"Signal detected"`` final fallback
      GRAPH_CHANGE:
        - ``"<subject>: Graph pattern change"`` or ``"Graph pattern change"``
      CONTRADICTION:
        - ``"<subject>: Conflicting signals"`` or ``"Conflicting signals"``

    Earlier versions degraded to ``f"{alert_type.title()} alert"`` for non-SIGNAL
    types, producing the user-reported "Graph Change alert" / "Contradiction alert"
    titles. Those types lack ``claim_type``/``polarity`` payload (NLP-only fields)
    so the signal_label lookup always missed; the new templates ignore signal_label
    entirely for graph/contradiction events.

    Wave-4 clarity upgrade: GRAPH_CHANGE titles now compose a descriptive tail
    from the (always-populated) ``change_type`` + ``canonical_types`` payload —
    e.g. ``"AAPL — 3 new graph links (2 supplier, 1 competitor)"`` — instead of
    the opaque ``"Graph pattern change"``. ``event`` is the raw Kafka payload;
    when it is ``None`` (legacy callers / minimal unit tests) we degrade to the
    previous static templates so behaviour is unchanged for those call sites.

    The separator is an em-dash (``—``) between subject and detail, matching the
    target UX ("NVDA — unusual graph activity: ..."). Subject-less events keep a
    leading-capital sentence so they still read as a headline.
    """
    subject = ticker or entity_name

    if alert_type == AlertType.SIGNAL:
        if not is_signal_label_fallback:
            if subject:
                return f"{subject} — {signal_label}"
            return signal_label
        # Severity-only fallback (no claim_type/polarity, e.g. neutral/OTHER).
        # Still better than bare "Signal detected" when we know the subject.
        if subject:
            return f"{subject} — price signal detected"
        return "Signal detected"

    if alert_type == AlertType.GRAPH_CHANGE:
        # Compose rich detail from the payload when available.
        detail = _compose_graph_change_detail(event) if event is not None else "graph pattern change"
        if subject:
            return f"{subject} — {detail}"
        # No subject: capitalise the detail so it reads as a headline.
        return detail[:1].upper() + detail[1:] if detail else "Graph pattern change"

    if alert_type == AlertType.CONTRADICTION:
        detail = "conflicting signals"
        if subject:
            return f"{subject} — {detail}"
        return detail[:1].upper() + detail[1:]

    if alert_type == AlertType.PREDICTION:
        # PLAN-0056 Wave D3: compose from trigger + polarity + question so the
        # row reads "AAPL — prediction market moving against: <question>".
        detail = _compose_prediction_detail(event) if event is not None else "prediction market update"
        if subject:
            return f"{subject} — {detail}"
        return detail[:1].upper() + detail[1:] if detail else "Prediction market update"

    # Defensive: enum extension safety net. Should be unreachable in current code.
    return f"{subject} — alert" if subject else "Alert"


def _find_schema_path(schema_name: str) -> Path:
    """Find Avro schema file by walking up from this file to the repo/container root.

    Works in both development (deep path) and Docker (shallow /app path).
    """
    current = Path(__file__).resolve()
    for parent in current.parents:
        candidate = parent / "infra" / "kafka" / "schemas" / schema_name
        if candidate.is_file():
            return candidate
    msg = f"Cannot locate {schema_name} in any parent of {current}"
    raise FileNotFoundError(msg)


# Schema file path — C-04 / BP-119: load from .avsc, never define inline
_SCHEMA_PATH = _find_schema_path("alert.delivered.v1.avsc")

_PARSED_SCHEMA: dict[str, Any] | None = None


def _get_parsed_schema() -> dict[str, Any]:
    global _PARSED_SCHEMA
    if _PARSED_SCHEMA is None:
        _PARSED_SCHEMA = fastavro.schema.load_schema(_SCHEMA_PATH)  # type: ignore[assignment, arg-type]
    return _PARSED_SCHEMA  # type: ignore[return-value]


# ── Data classes ───────────────────────────────────────────────────────────────


@dataclass
class FanoutResult:
    """Outcome of one :meth:`AlertFanoutUseCase.execute` call."""

    suppressed: bool = False
    suppression_reason: str = ""  # "backfill" | "dedup" | "no_entity_id" | ""
    watchers_count: int = 0
    alert_id: UUID | None = None
    pending_count: int = 0


# ── Private helpers ────────────────────────────────────────────────────────────


def _should_suppress(event: dict[str, Any], topic: str) -> bool:
    """Return ``True`` if the event should be suppressed (PRD AD-10)."""
    is_backfill: bool = bool(event.get("is_backfill", False))
    if not is_backfill:
        return False

    if topic in ("nlp.signal.detected.v1", "graph.state.changed.v1"):
        return True

    if topic == "intelligence.contradiction.v1":
        occurred_at_str: str = str(event.get("occurred_at", ""))
        try:
            occurred_at = datetime.fromisoformat(occurred_at_str)
            if occurred_at.tzinfo is None:
                occurred_at = occurred_at.replace(tzinfo=UTC)
        except (ValueError, AttributeError):
            return True  # malformed date → suppress conservatively
        age: timedelta = utc_now() - occurred_at  # type: ignore[assignment]
        return age > _BACKFILL_MAX_AGE

    return False


def _extract_entity_id(event: dict[str, Any], topic: str) -> str | None:
    """Return the primary entity_id string from the event, or ``None``."""
    if topic == "nlp.signal.detected.v1":
        raw = event.get("subject_entity_id") or event.get("claimer_entity_id")
    elif topic == "graph.state.changed.v1":
        raw = event.get("primary_entity_id")
    elif topic == "intelligence.contradiction.v1":
        raw = event.get("subject_entity_id")
    elif topic == "market.prediction.signal.v1":
        # PLAN-0056 Wave D3: the fanout watchlist key is the referenced entity.
        raw = event.get("subject_entity_id")
    else:
        return None
    return str(raw) if raw else None


def _serialize_alert_delivered(
    alert: Alert,
    user_id: UUID,
    correlation_id: str | None,
) -> bytes:
    """Serialize an ``alert.delivered`` event to Avro bytes (schemaless)."""
    record = {
        "event_id": str(new_uuid7()),
        "event_type": "alert.delivered",
        "schema_version": 2,
        "occurred_at": alert.created_at.isoformat(),
        "alert_id": str(alert.alert_id),
        "user_id": str(user_id),
        "entity_id": str(alert.entity_id),
        "alert_type": str(alert.alert_type),
        "channel": "websocket",
        "correlation_id": correlation_id,
        "severity": str(alert.severity),
    }
    buf = io.BytesIO()
    fastavro.schemaless_writer(buf, _get_parsed_schema(), record)
    return buf.getvalue()


# ── Use case ───────────────────────────────────────────────────────────────────


class AlertFanoutUseCase:
    """Fan-out one intelligence event to all watching users.

    Args:
    ----
        session_factory: SQLAlchemy async session factory for alert_db.
        watchlist_cache: Cache-aside wrapper for S1 watchlist lookups.
        notification_publisher: Real-time notification publisher port (Valkey pub/sub or in-process).
        repo_factory: Factory to build repos from a session.
        dedup_window_seconds: Deduplication window length (default 300 s).
        alert_delivered_topic: Kafka topic for outbox events.
        severity_thresholds: Value object for score→severity classification.
            Defaults to ``SeverityThresholds()`` (PRD-0021 §6.5 defaults).

    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        watchlist_cache: IWatchlistCache,
        notification_publisher: INotificationPublisher,
        repo_factory: RepoFactory,
        dedup_window_seconds: int = 300,
        alert_delivered_topic: str = "alert.delivered.v1",
        severity_thresholds: SeverityThresholds | None = None,
        metrics: IAlertMetrics | None = None,
        entity_resolver: EntityNameResolverPort | None = None,
    ) -> None:
        self._sf = session_factory
        self._cache = watchlist_cache
        self._notification_publisher = notification_publisher
        self._repo_factory = repo_factory
        self._dedup_window = dedup_window_seconds
        self._alert_delivered_topic = alert_delivered_topic
        self._thresholds = severity_thresholds if severity_thresholds is not None else SeverityThresholds()
        self._metrics: IAlertMetrics = metrics if metrics is not None else NoOpAlertMetrics()
        # Optional: when None, payload enrichment is skipped (legacy callers + unit tests
        # that don't care about (entity_name, ticker, signal_label) still work unchanged).
        self._entity_resolver: EntityNameResolverPort | None = entity_resolver

    async def execute(
        self,
        event: dict[str, Any],
        topic: str,
        correlation_id: str | None = None,
        market_impact_score: float = 0.0,
    ) -> FanoutResult:
        """Fan-out one event to all watchers.

        Args:
        ----
            event: Deserialized Kafka message value.
            topic: Source Kafka topic name.
            correlation_id: Optional tracing correlation ID.
            market_impact_score: Market impact score from the event (0.0-1.0).
                Used to compute severity for signal events; ignored for
                graph/contradiction events (F-13 MEDIUM override).

        Returns:
        -------
            :class:`FanoutResult` describing what happened.

        """
        # ── 1. Backfill suppression ──────────────────────────────────────────
        if _should_suppress(event, topic):
            logger.info(  # type: ignore[no-any-return]
                "alert_fanout.suppressed_backfill",
                topic=topic,
                event_id=event.get("event_id"),
            )
            return FanoutResult(suppressed=True, suppression_reason="backfill")

        # ── 2. Extract entity_id ─────────────────────────────────────────────
        entity_id_str = _extract_entity_id(event, topic)
        if not entity_id_str:
            logger.warning(  # type: ignore[no-any-return]
                "alert_fanout.no_entity_id",
                topic=topic,
                event_id=event.get("event_id"),
            )
            return FanoutResult(suppressed=True, suppression_reason="no_entity_id")

        try:
            entity_uuid = UUID(entity_id_str)
        except ValueError:
            logger.warning(  # type: ignore[no-any-return]
                "alert_fanout.invalid_entity_id",
                entity_id=entity_id_str,
            )
            return FanoutResult(suppressed=True, suppression_reason="no_entity_id")

        # ── 3. Resolve alert type ────────────────────────────────────────────
        alert_type = TOPIC_ALERT_TYPE.get(topic, AlertType.SIGNAL)

        # ── 4. Compute severity (PRD-0021 §6.5) ─────────────────────────────
        # Clamp score to [0.0, 1.0] (belt-and-suspenders; consumer also clamps)
        score = max(0.0, min(1.0, market_impact_score))
        # F-13: graph/contradiction always MEDIUM; signal events use score
        severity = AlertSeverity.MEDIUM if topic in _MEDIUM_OVERRIDE_TOPICS else self._thresholds.classify(score)

        # ── 5. Resolve watchers ──────────────────────────────────────────────
        watchers = await self._cache.get_watchers(entity_id_str)
        if not watchers:
            logger.debug(  # type: ignore[no-any-return]
                "alert_fanout.no_watchers",
                entity_id=entity_id_str,
                topic=topic,
            )
            return FanoutResult(suppressed=False, watchers_count=0)

        # ── 6. Dedup check ───────────────────────────────────────────────────
        now = utc_now()
        # Use event's occurred_at for the dedup window bucket (stable across re-deliveries).
        # If re-delivered in a different 300s window, the same event still hashes to the
        # same dedup_key, preventing duplicate alerts.  Fall back to now() on parse failure.
        occurred_at_raw = event.get("occurred_at", "")
        try:
            event_time = datetime.fromisoformat(str(occurred_at_raw))
            if event_time.tzinfo is None:
                event_time = event_time.replace(tzinfo=UTC)
        except (ValueError, AttributeError, TypeError):
            event_time = now
        dedup_key = Alert.compute_dedup_key(entity_uuid, alert_type, event_time, self._dedup_window)

        async with self._sf() as session:
            alert_repo, pending_repo, dedup_repo, outbox_repo = self._repo_factory(session)
            if await dedup_repo.exists(dedup_key):
                logger.debug(  # type: ignore[no-any-return]
                    "alert_fanout.dedup_suppressed",
                    entity_id=entity_id_str,
                    alert_type=str(alert_type),
                    dedup_key=dedup_key,
                )
                return FanoutResult(
                    suppressed=True,
                    suppression_reason="dedup",
                    watchers_count=len(watchers),
                )

            # ── 7. Build alert entity ────────────────────────────────────────
            source_event_id_raw = event.get("event_id", "")
            try:
                source_event_id = UUID(str(source_event_id_raw))
            except (ValueError, AttributeError):
                source_event_id = new_uuid7()

            # Payload enrichment (PLAN-0048 Wave B-1):
            # The persisted payload powers the frontend's RecentAlerts row text
            # and AlertDetailSheet. Inject (entity_name, ticker, signal_label)
            # BEFORE building the Alert so they end up in the DB row + websocket
            # push + outbox event uniformly. Best-effort — resolver returns
            # (None, None) on S7 errors and we still ship the alert.
            enriched_payload: dict[str, Any] = dict(event)
            entity_name: str | None = None
            ticker: str | None = None
            if self._entity_resolver is not None:
                try:
                    entity_name, ticker = await self._entity_resolver.resolve(entity_uuid)
                except Exception:
                    # Defensive: implementations promise not to raise, but a
                    # programming error here MUST NOT block the alert path.
                    logger.warning(  # type: ignore[no-any-return]
                        "alert_fanout.entity_resolve_error",
                        entity_id=str(entity_uuid),
                        exc_info=True,
                    )
            if entity_name:
                enriched_payload["entity_name"] = entity_name
            if ticker:
                enriched_payload["ticker"] = ticker
            # Signal-label is only meaningful for SIGNAL alerts; emit it for
            # all topics anyway because it's a cheap deterministic computation
            # and the frontend always renders ``ticker: signal_label`` so a
            # consistent shape simplifies the UI.
            signal_label, is_fallback = _derive_signal_label(event, severity)
            enriched_payload["signal_label"] = signal_label
            if is_fallback:
                # Surface upstream data-quality gaps. Frequency of this warning is the
                # primary metric for tracking F-D-006 / F-X-201 remediation progress.
                logger.warning(
                    "alert_fanout.signal_label_fallback",
                    claim_type=event.get("claim_type"),
                    polarity=event.get("polarity"),
                    severity=str(severity),
                    topic=topic,
                )
            # Compose the persistent ``title`` so RecentAlerts / AlarmsPanel never
            # need to fall back to bare severity in the UI (F-D-006 / F-X-201).
            alert_title = _compose_alert_title(
                signal_label=signal_label,
                entity_name=entity_name,
                ticker=ticker,
                alert_type=alert_type,
                is_signal_label_fallback=is_fallback,
                event=event,
            )

            alert = Alert(
                entity_id=entity_uuid,
                alert_type=alert_type,
                severity=severity,
                source_event_id=source_event_id,
                source_topic=topic,
                payload=enriched_payload,
                dedup_key=dedup_key,
                created_at=now,
                title=alert_title,
                ticker=ticker,
                entity_name=entity_name,
                signal_label=signal_label,
            )

            # ── 8. Single transaction: alert + pending rows + outbox ─────────
            try:
                await alert_repo.save(alert)
            except DuplicateAlertError:
                # Race condition: another worker wrote same dedup_key first.
                # Explicitly rollback before returning — the DB-level unique constraint
                # violation leaves the asyncpg connection in an aborted state, which
                # would corrupt subsequent queries if the session is returned to the pool
                # without a ROLLBACK (BP-137).
                await session.rollback()
                logger.info("alert_fanout.dedup_race", dedup_key=dedup_key)  # type: ignore[no-any-return]
                return FanoutResult(
                    suppressed=True,
                    suppression_reason="dedup",
                    watchers_count=len(watchers),
                )

            watcher_user_ids: list[UUID] = []
            for watcher in watchers:
                try:
                    user_uuid = UUID(str(watcher.user_id))
                except (ValueError, AttributeError):
                    continue

                await pending_repo.save(PendingAlert(user_id=user_uuid, alert_id=alert.alert_id))

                payload_avro = _serialize_alert_delivered(alert, user_uuid, correlation_id)
                await outbox_repo.append(
                    OutboxEvent(
                        topic=self._alert_delivered_topic,
                        partition_key=str(user_uuid),
                        payload_avro=payload_avro,
                    ),
                )
                watcher_user_ids.append(user_uuid)

            await session.commit()

        # ── 9. Post-commit WebSocket push (never inside transaction) ─────────
        ws_payload = {
            "alert_id": str(alert.alert_id),
            "entity_id": entity_id_str,
            "alert_type": str(alert_type),
            "severity": str(severity),
            "topic": topic,
            "occurred_at": now.isoformat(),
        }
        for user_uuid in watcher_user_ids:
            await self._notification_publisher.send_to_user(user_uuid, ws_payload)

        # ── 10. Metrics ──────────────────────────────────────────────────────
        # Metrics are fire-and-forget: must never affect the correctness path.
        try:
            self._metrics.record_alert_fanned_out(severity, alert_type, len(watcher_user_ids))
            if severity == AlertSeverity.CRITICAL and watcher_user_ids:
                self._metrics.record_flash_overlay()
        except Exception:
            logger.warning("alert_fanout.metrics_error", exc_info=True)  # type: ignore[no-any-return]

        logger.info(  # type: ignore[no-any-return]
            "alert_fanout.completed",
            alert_id=str(alert.alert_id),
            entity_id=entity_id_str,
            topic=topic,
            severity=str(severity),
            watchers=len(watcher_user_ids),
        )
        return FanoutResult(
            suppressed=False,
            watchers_count=len(watcher_user_ids),
            alert_id=alert.alert_id,
            pending_count=len(watcher_user_ids),
        )
