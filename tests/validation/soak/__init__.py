"""PLAN-0093 Wave G-2 — Soak tests.

Long-running tests intended for nightly CI, not the default pytest run.
Each test in this package self-skips unless ``SOAK_TEST_ENABLED=1`` so they
don't slow the regular feedback loop.
"""
