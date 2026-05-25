"""Application services for RAG-Chat (PLAN-0093 Sub-Plan E).

This package hosts pure application-layer helpers that are too small to
warrant a full use case but are reusable across the orchestrator and the
eval harness. Members must not import from ``rag_chat.infrastructure`` —
the orchestrator wires concrete clients in and passes them as arguments.
"""
