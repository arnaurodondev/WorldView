"""Unit tests for the evaluator registry seam (PLAN-0113 T-1-06).

The registry (``EVALUATOR_REGISTRY``) is a module-level global mutated by
``register_default_evaluators``. These tests snapshot+restore it around each
case so they are order-independent — earlier tests (poller/consumer wiring)
that call ``register_default_evaluators`` must not leak the populated registry
into the assertions here (test-isolation; BP-590 shared-global family).
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from alert.application.rules import registry as registry_mod
from alert.application.rules.registry import (
    EVALUATOR_REGISTRY,
    get_evaluator,
    register_default_evaluators,
)
from alert.domain.enums import RuleType


@pytest.fixture(autouse=True)
def _isolate_registry() -> Iterator[None]:
    """Snapshot and restore the global registry around each test.

    Without this, registration performed by sibling test modules (or by an
    earlier test in this module) leaks across boundaries because the registry
    is a single mutable module global.
    """
    saved = dict(registry_mod.EVALUATOR_REGISTRY)
    registry_mod.EVALUATOR_REGISTRY.clear()
    try:
        yield
    finally:
        registry_mod.EVALUATOR_REGISTRY.clear()
        registry_mod.EVALUATOR_REGISTRY.update(saved)


def test_registry_empty_before_registration() -> None:
    """A freshly-cleared registry resolves nothing until evaluators register."""
    assert EVALUATOR_REGISTRY == {}
    assert get_evaluator(RuleType.PRICE_CROSS) is None


def test_register_default_evaluators_populates_all_five() -> None:
    """``register_default_evaluators`` wires one evaluator per RuleType."""
    register_default_evaluators()
    assert set(EVALUATOR_REGISTRY) == set(RuleType)
    for rule_type in RuleType:
        assert get_evaluator(rule_type) is not None


def test_register_default_evaluators_is_idempotent() -> None:
    """Re-registration replaces in place — no duplicate keys, stable size."""
    register_default_evaluators()
    first = dict(EVALUATOR_REGISTRY)
    register_default_evaluators()
    assert set(EVALUATOR_REGISTRY) == set(first)
    assert len(EVALUATOR_REGISTRY) == len(RuleType)
