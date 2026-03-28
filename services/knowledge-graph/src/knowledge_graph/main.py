"""Uvicorn entry point for the knowledge-graph service (S7).

Usage::

    python -m knowledge_graph.main
    # or
    uvicorn knowledge_graph.app:create_app --factory --host 0.0.0.0 --port 8007
"""

from __future__ import annotations

import uvicorn


def main() -> None:
    """Start the knowledge-graph service."""
    uvicorn.run(
        "knowledge_graph.app:create_app",
        factory=True,
        host="0.0.0.0",  # noqa: S104
        port=8007,
        log_level="info",
    )


if __name__ == "__main__":
    main()
