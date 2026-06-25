"""Beta calibration of raw confidence -> P(true) (PLAN-0109 W6).

The Beta/subjective-logic posterior (``compute_confidence_beta``) produces a
bounded, well-ordered score, but its absolute level is not guaranteed to match
the empirical hit-rate (a relation at 0.9 should be true ~90% of the time). Beta
calibration maps the raw score ``s`` to a calibrated probability::

    P = sigmoid( a * ln(s) + b * ln(1 - s) + c )

(Kull, Silva Filho & Flach, "Beta calibration", AISTATS 2017.) The identity map
is ``a=1, b=-1, c=0`` (then ``P = s``), so calibration is a no-op until fitted
parameters are supplied — the model ships uncalibrated-but-safe and an operator
fits ``(a, b, c)`` offline from an adjudicated labelled set.

Pure domain module — no DB, no I/O.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

_EPS = 1e-6


def _clip01(x: float) -> float:
    return min(1.0 - _EPS, max(_EPS, x))


@dataclass(frozen=True)
class BetaCalibrator:
    """Three-parameter Beta calibration map. Defaults to the identity."""

    a: float = 1.0
    b: float = -1.0
    c: float = 0.0

    @property
    def is_identity(self) -> bool:
        return self.a == 1.0 and self.b == -1.0 and self.c == 0.0

    def apply(self, s: float) -> float:
        """Map a raw score ``s`` in [0, 1] to a calibrated probability."""
        s = _clip01(s)
        z = self.a * math.log(s) + self.b * math.log(1.0 - s) + self.c
        if z >= 0:
            return 1.0 / (1.0 + math.exp(-z))
        ez = math.exp(z)
        return ez / (1.0 + ez)


def fit_beta_calibrator(
    samples: list[tuple[float, int]],
    *,
    iterations: int = 2000,
    learning_rate: float = 0.05,
) -> BetaCalibrator:
    """Fit ``(a, b, c)`` by gradient descent on logistic loss.

    ``samples`` is a list of ``(raw_score, label)`` with ``label in {0, 1}``.
    Features are ``[ln s, ln(1 - s)]``; the model is logistic regression on those
    two features plus a bias, which is exactly the Beta-calibration family.
    Returns the identity calibrator when there are too few samples to fit.
    """
    if len(samples) < 10:
        return BetaCalibrator()

    a, b, c = 1.0, -1.0, 0.0
    n = float(len(samples))
    feats = [(math.log(_clip01(s)), math.log(1.0 - _clip01(s)), float(y)) for s, y in samples]

    for _ in range(iterations):
        ga = gb = gc = 0.0
        for f1, f2, y in feats:
            z = a * f1 + b * f2 + c
            p = 1.0 / (1.0 + math.exp(-z)) if z >= 0 else math.exp(z) / (1.0 + math.exp(z))
            err = p - y
            ga += err * f1
            gb += err * f2
            gc += err
        a -= learning_rate * ga / n
        b -= learning_rate * gb / n
        c -= learning_rate * gc / n

    return BetaCalibrator(a=a, b=b, c=c)


def expected_calibration_error(
    samples: list[tuple[float, int]],
    *,
    bins: int = 10,
) -> float:
    """Expected Calibration Error: mean |confidence - accuracy| over equal-width bins.

    ``samples`` is ``(confidence, label)``. Lower is better; 0 is perfectly
    calibrated. Empty input returns 0.0.
    """
    if not samples:
        return 0.0
    bin_conf = [0.0] * bins
    bin_acc = [0.0] * bins
    bin_n = [0] * bins
    for s, y in samples:
        idx = min(bins - 1, int(_clip01(s) * bins))
        bin_conf[idx] += s
        bin_acc[idx] += y
        bin_n[idx] += 1
    total = float(len(samples))
    ece = 0.0
    for i in range(bins):
        if bin_n[i] == 0:
            continue
        conf = bin_conf[i] / bin_n[i]
        acc = bin_acc[i] / bin_n[i]
        ece += (bin_n[i] / total) * abs(conf - acc)
    return ece
