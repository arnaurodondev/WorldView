"""Bootstrap helpers shared between the API process and standalone workers.

PLAN-0057 QA A-004 / Wave-D-followup: extracted to single-source provider-
selection logic so app.py and embedding_retry_worker_main.py cannot drift
when a new embedding provider is added.
"""
