"""Rule-evaluation seam (PLAN-0113).

Wave 1 ships the empty registry + Protocol; Wave 2/3 register the 5 evaluators.
"""

from __future__ import annotations

from alert.application.rules.registry import EVALUATOR_REGISTRY, EvalContext, RuleEvaluator

__all__ = ["EVALUATOR_REGISTRY", "EvalContext", "RuleEvaluator"]
