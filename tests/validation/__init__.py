"""PLAN-0093 Wave G-1 — Data Quality SLO tests.

Programmatic pytest integration tests that read live ``nlp_db``,
``intelligence_db``, and Apache AGE to assert on the metrics that drove the
BLOCKING findings in ``docs/audits/2026-05-23-qa-intelligence-pipelines-report.md``.

These tests require a live, seeded platform to actually pass. When the relevant
``*_DB_URL_TEST`` env var is absent they skip with a clear reason so they don't
fail CI when run without infra.
"""
