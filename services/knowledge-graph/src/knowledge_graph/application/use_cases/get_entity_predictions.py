"""GetEntityPredictionsUseCase — prediction markets referencing an entity (PLAN-0056 Wave C4).

Read-only use case: the keystone read side of the KG linkage built in Waves
C2/C2b/C3.  Returns, for a given entity, every prediction market that references
it together with the directional polarity recorded on the exposure.

R25 compliance: wraps the exposure repository so API route files never import
from the infrastructure layer.
R27 compliance: read-only — the repository is bound to the read-replica session.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

if TYPE_CHECKING:
    from knowledge_graph.application.ports.temporal_event_repository import (
        EntityEventExposureRepositoryPort,
    )


class GetEntityPredictionsUseCase:
    """Return the prediction markets that reference an entity, with polarity.

    Args:
        exposure_repo: EntityEventExposureRepository bound to a read-only session.
    """

    def __init__(self, exposure_repo: EntityEventExposureRepositoryPort) -> None:
        self._exposure_repo = exposure_repo

    async def execute(
        self,
        entity_id: UUID,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[dict[str, object]], int]:
        """Return matching prediction-market exposure rows and the total count.

        Delegates to
        ``EntityEventExposureRepository.list_prediction_exposures_for_entity``,
        which filters to ``event_type = 'prediction'`` exposures for the entity.
        An entity with no linked prediction markets yields ``([], 0)`` — the API
        layer maps that to an empty list (not a 404).

        Args:
        ----
            entity_id: canonical_entities.entity_id to look up.
            limit:     Page size (the API layer clamps to 1-200).
            offset:    Pagination offset (>= 0).

        Returns:
        -------
            Tuple of (rows, total_count).  See the repository port for the row
            dict shape; the API layer maps rows to the wire-format schema (R12).

        """
        return await self._exposure_repo.list_prediction_exposures_for_entity(
            entity_id=entity_id,
            limit=limit,
            offset=offset,
        )
