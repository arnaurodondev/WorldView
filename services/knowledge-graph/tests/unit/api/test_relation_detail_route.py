"""Unit tests for GET /api/v1/relations/{relation_id} (PLAN-0099 edge detail).

Tests:
- 200 with the full relation payload (metadata, summary, subject/object, evidence)
- 200 with no summary / no evidence (nulls + empty list, NOT a 404)
- 404 when the relation does not exist
- 422 for a malformed UUID
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest

pytestmark = [pytest.mark.unit]

_REL_ID = UUID("01900000-0000-7000-8000-00000000aaaa")
_SUBJ_ID = UUID("01900000-0000-7000-8000-000000001001")
_OBJ_ID = UUID("01900000-0000-7000-8000-000000002002")
_DOC_ID = uuid4()
_NOW = datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC)


def _relation_row() -> dict[str, Any]:
    return {
        "relation_id": _REL_ID,
        "subject_entity_id": _SUBJ_ID,
        "object_entity_id": _OBJ_ID,
        "canonical_type": "is_in_sector",
        "semantic_mode": "RELATION_STATE",
        "decay_class": "PERMANENT",
        "confidence": 0.95,
        "confidence_stale": False,
        "evidence_count": 140,
        "first_evidence_at": _NOW,
        "latest_evidence_at": _NOW,
        "valid_from": _NOW,
        "valid_to": None,
        "relation_period_type": "ONGOING",
        "strongest_contra_score": 0.0,
        "latest_contra_at": None,
        "relation_source": None,
        "created_at": _NOW,
        "updated_at": _NOW,
        "summary_authority": 4.701479,
    }


def _entity_row(entity_id: UUID, name: str) -> dict[str, Any]:
    return {
        "entity_id": entity_id,
        "canonical_name": name,
        "entity_type": "financial_instrument",
        "isin": None,
        "ticker": "AAPL" if entity_id == _SUBJ_ID else None,
        "exchange": "US",
        "metadata": {"sector": "Information Technology"},
        "description": f"{name} description.",
        "sector": "Information Technology",
        "industry": None,
    }


def _evidence_row() -> dict[str, Any]:
    return {
        "raw_id": uuid4(),
        "evidence_text": "Apple was classified in the Information Technology sector.",
        "source_document_id": _DOC_ID,
        "source_name": "Reuters",
        "source_type": "rss",
        "polarity": "positive",
        "evidence_date": _NOW,
        "extraction_confidence": 0.9,
        "source_trust_weight": 1.0,
        "is_backfill": False,
        "extracted_at": _NOW,
    }


def _override_uc(api_app: Any, result: Any) -> None:
    """Override the relation-detail use case dependency with a stub."""
    from knowledge_graph.api.dependencies import get_relation_detail_uc

    mock_uc = AsyncMock()
    mock_uc.execute = AsyncMock(return_value=result)
    api_app.dependency_overrides[get_relation_detail_uc] = lambda: mock_uc


class TestRelationDetailEndpoint:
    async def test_relation_detail_200_full_payload(self, api_app: Any, api_client: Any) -> None:
        """All relation fields + summary + subject/object + evidence are mapped."""
        from knowledge_graph.application.use_cases.get_relation_detail import RelationDetailResult

        result = RelationDetailResult(
            relation=_relation_row(),
            summary={
                "summary_id": uuid4(),
                "summary_text": "EODHD classifies the entity in the Information Technology sector.",
                "evidence_count": 140,
                "evidence_hash": "abc",
                "model_id": "meta-llama/Meta-Llama-3.1-8B-Instruct",
                "prompt_template_id": uuid4(),
                "generated_at": _NOW,
                "generation_trigger": "scheduled",
            },
            subject_row=_entity_row(_SUBJ_ID, "Apple Inc."),
            object_row=_entity_row(_OBJ_ID, "Information Technology"),
            evidence=[_evidence_row()],
        )
        _override_uc(api_app, result)

        resp = await api_client.get(f"/api/v1/relations/{_REL_ID}")

        assert resp.status_code == 200
        body = resp.json()
        assert body["relation_id"] == str(_REL_ID)
        assert body["canonical_type"] == "is_in_sector"
        assert body["semantic_mode"] == "RELATION_STATE"
        assert body["decay_class"] == "PERMANENT"
        assert body["confidence"] == 0.95
        assert body["confidence_stale"] is False
        assert body["evidence_count"] == 140
        assert body["summary_authority"] == pytest.approx(4.701479)
        assert body["valid_from"] is not None
        assert body["relation_period_type"] == "ONGOING"
        assert body["created_at"] is not None
        assert body["relation_summary"].startswith("EODHD classifies")
        assert body["summary_model_id"] == "meta-llama/Meta-Llama-3.1-8B-Instruct"
        # Subject / object entity summaries
        assert body["subject"]["canonical_name"] == "Apple Inc."
        assert body["subject"]["ticker"] == "AAPL"
        assert body["subject"]["description"] == "Apple Inc. description."
        assert body["object"]["canonical_name"] == "Information Technology"
        # Evidence list with full provenance
        assert len(body["evidence"]) == 1
        ev = body["evidence"][0]
        assert ev["evidence_text"].startswith("Apple was classified")
        assert ev["document_id"] == str(_DOC_ID)
        assert ev["source_name"] == "Reuters"
        assert ev["source_type"] == "rss"
        assert ev["polarity"] == "positive"
        assert ev["extraction_confidence"] == 0.9
        assert ev["is_backfill"] is False

    async def test_relation_detail_200_no_summary_no_evidence(self, api_app: Any, api_client: Any) -> None:
        """A relation with no summary and no evidence is still a 200 (NOT 404)."""
        from knowledge_graph.application.use_cases.get_relation_detail import RelationDetailResult

        result = RelationDetailResult(
            relation=_relation_row(),
            summary=None,
            subject_row=None,
            object_row=None,
            evidence=[],
        )
        _override_uc(api_app, result)

        resp = await api_client.get(f"/api/v1/relations/{_REL_ID}")

        assert resp.status_code == 200
        body = resp.json()
        assert body["relation_summary"] is None
        assert body["summary_generated_at"] is None
        assert body["subject"] is None
        assert body["object"] is None
        assert body["evidence"] == []

    async def test_relation_detail_404(self, api_app: Any, api_client: Any) -> None:
        """Unknown relation_id returns 404."""
        _override_uc(api_app, None)

        resp = await api_client.get(f"/api/v1/relations/{uuid4()}")

        assert resp.status_code == 404
        assert resp.json()["detail"] == "Relation not found"

    async def test_relation_detail_invalid_uuid(self, api_app: Any, api_client: Any) -> None:
        """Non-UUID relation_id returns 422."""
        _override_uc(api_app, None)

        resp = await api_client.get("/api/v1/relations/not-a-uuid")
        assert resp.status_code == 422

    async def test_relation_detail_evidence_limit_validation(self, api_app: Any, api_client: Any) -> None:
        """evidence_limit outside [1, 100] returns 422."""
        _override_uc(api_app, None)

        resp = await api_client.get(f"/api/v1/relations/{_REL_ID}?evidence_limit=0")
        assert resp.status_code == 422
        resp = await api_client.get(f"/api/v1/relations/{_REL_ID}?evidence_limit=101")
        assert resp.status_code == 422
