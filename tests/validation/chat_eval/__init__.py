"""PLAN-0093 Wave G-3 — Chat regression suite + 75-query weak-point survey.

This package converts the 8 audit questions from
``docs/audits/2026-05-23-qa-intelligence-pipelines-report.md`` into automated
pytest cases that exercise a *live* rag-chat (S8) instance via the S9 API
gateway.

Test layout
-----------
* ``harness.py``      — HTTP client + dev-JWT bootstrap + per-question runner.
* ``grading.py``      — pure rubric scoring: USEFUL / MARGINAL / USELESS / HARMFUL.
* ``conftest.py``     — pytest fixtures (chat HTTP client, dev JWT).
* ``questions.yaml``  — 8 audit questions with ground-truth assertions.
* ``test_q1..q8_*.py`` — one pytest file per audit question.
* ``test_aggregate_score.py`` — gate test: ≥ 6 USEFUL, 0 HARMFUL.
* ``test_weak_point_survey.py`` -- 5 tickers x 5 metric families x 3 variants.
* ``fixtures/``       — YAML ground-truth fixtures for Q4 + the 75-query matrix.
* ``weak_point_report.py`` — markdown report generator for survey results.

Runtime contract
----------------
All tests skip cleanly (``pytest.skip``) when ``RAG_CHAT_BASE_URL`` is unset,
so collection always succeeds in CI without a live platform. Set
``RAG_CHAT_BASE_URL=http://localhost:8009`` (the dev API-gateway port) to
actually fire the questions.
"""
