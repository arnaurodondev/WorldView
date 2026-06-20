"""Unit tests for the evaluator registry seam (PLAN-0113 T-1-06)."""

from __future__ import annotations

from alert.application.rules.registry import EVALUATOR_REGISTRY, get_evaluator
from alert.domain.enums import RuleType


def test_registry_empty_in_wave_1() -> None:
    """Wave 1 ships the registry empty — evaluators land in W2/W3."""
    assert EVALUATOR_REGISTRY == {}


def test_registry_lookup_returns_none_for_unregistered() -> None:
    assert get_evaluator(RuleType.PRICE_CROSS) is None
