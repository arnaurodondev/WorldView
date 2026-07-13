"""Domain enumerations for the Knowledge Graph service (S7)."""

from __future__ import annotations

from enum import StrEnum


class SemanticMode(StrEnum):
    """Two semantic modes that govern how evidence ages and contradictions resolve (PRD §6.7 Block 11).

    RELATION_STATE — active/inactive; event-triggered invalidation; decay via decay_class_config.
    TEMPORAL_CLAIM — historically anchored; not validity-gated; decay via decay_class_config.
    """

    RELATION_STATE = "RELATION_STATE"
    TEMPORAL_CLAIM = "TEMPORAL_CLAIM"


class DecayClass(StrEnum):
    """Meta decay class used in the confidence formula.

    STANDARD — use the decay_alpha from the relation's decay_class_config row.
    TEMPORAL — override with 0.02310 (30-day half-life, regardless of relation type).

    Note: The underlying DB stores fine-grained decay classes (PERMANENT, DURABLE, SLOW,
    MEDIUM, FAST, EPHEMERAL).  This enum captures the *formula-level* distinction.
    """

    STANDARD = "STANDARD"
    TEMPORAL = "TEMPORAL"


class RelationType(StrEnum):
    """16 well-known relation types for typed application code.

    The full registry lives in ``relation_type_registry`` (32 rows after migration 0041).
    These are the most commonly referenced types in domain logic.

    Original 8 (PRD §6.7 Block 11) + 3 new from PRD-0018 §6.4
    + 5 new from PLAN-0089 taxonomy expansion (migration 0041).
    """

    EMPLOYS = "employs"
    BOARD_MEMBER_OF = "board_member_of"
    SUBSIDIARY_OF = "subsidiary_of"
    ACQUIRED_BY = "acquired_by"
    LISTED_ON = "listed_on"
    SUPPLIER_OF = "supplier_of"
    PARTNER_OF = "partner_of"
    COMPETES_WITH = "competes_with"
    # PRD-0018 §6.4 — seeded in migration 0004
    HAS_EXECUTIVE = "has_executive"
    REVENUE_FROM_COUNTRY = "revenue_from_country"
    OPERATES_IN_COUNTRY = "operates_in_country"
    # PLAN-0089 Lever-4 financial taxonomy expansion — seeded in migration 0041
    APPOINTED_AS = "appointed_as"
    DIVESTED_FROM = "divested_from"
    DOWNGRADED_BY = "downgraded_by"
    FILED_LAWSUIT_AGAINST = "filed_lawsuit_against"
    REPORTED_REVENUE_OF = "reported_revenue_of"


# ---------------------------------------------------------------------------
# Temporal event enums (PRD-0018 §6.6)
# ---------------------------------------------------------------------------


class EventScope(StrEnum):
    """Scope of a temporal event's market impact (PRD-0018 §6.6).

    Values are uppercase to match the DB CHECK constraint on temporal_events.scope.

    LOCAL    — affects a specific company or small group (entity_event_exposures rows per company)
    REGIONAL — affects a geographic region e.g. EU, ASEAN (entity_event_exposures for country entities)
    NATIONAL — affects a country's economy (entity_event_exposures for country entity)
    GLOBAL   — affects entire sectors/industries; entity_event_exposures for sector entities ONLY;
               company exposure inferred at query time via is_in_sector traversal (PRD-0018 §6.2)
    """

    LOCAL = "LOCAL"
    REGIONAL = "REGIONAL"
    NATIONAL = "NATIONAL"
    GLOBAL = "GLOBAL"


class EventType(StrEnum):
    """Category of a temporal event (PRD-0018 §6.6).

    Values are lowercase to match the DB CHECK constraint and the Avro schema field
    ``temporal_event_type``.  Use ``EventType.MACRO`` (not ``"MACRO"``) in all code.

    CORPORATE — added by PLAN-0068 Wave A-1 for earnings calendar events ingested
    from Finnhub via the EarningsCalendarDatasetConsumer (consumer 13D-9).
    Requires intelligence-migrations 0018 (adds 'corporate' to the CHECK constraint).

    PREDICTION — added by PLAN-0056 Wave C2 (PRD-0033) for prediction-market
    events (e.g. Polymarket) ingested via the PredictionEnrichedConsumer. Each
    NER-enriched Polymarket synthetic document becomes one temporal event with
    ``event_type='prediction'`` and one exposure per resolved entity. Requires
    intelligence-migrations 0066 (adds 'prediction' to the CHECK constraint).
    """

    GEOPOLITICAL = "geopolitical"
    REGULATORY = "regulatory"
    MACRO = "macro"
    SANCTIONS = "sanctions"
    NATURAL_DISASTER = "natural_disaster"
    OTHER = "other"
    CORPORATE = "corporate"
    PREDICTION = "prediction"


class ExposureType(StrEnum):
    """How a canonical entity is exposed to a temporal event (PRD-0018 §6.6).

    Values are lowercase to match the DB CHECK constraint on entity_event_exposures.exposure_type
    and the Avro ExposedEntity.exposure_type field.
    """

    DIRECTLY_AFFECTED = "directly_affected"
    OPERATIONALLY_IMPACTED = "operationally_impacted"
    SUPPLY_CHAIN = "supply_chain"
    REVENUE_GEOGRAPHY = "revenue_geography"
    SECTOR_EXPOSURE = "sector_exposure"
