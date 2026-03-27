"""Uvicorn entry point for the NLP Pipeline service (S6).

Usage::

    python -m nlp_pipeline.main
    # or
    uvicorn nlp_pipeline.app:create_app --factory --host 0.0.0.0 --port 8006
"""

from __future__ import annotations

import uvicorn


def main() -> None:
    """Start the NLP Pipeline service."""
    uvicorn.run(
        "nlp_pipeline.app:create_app",
        factory=True,
        host="0.0.0.0",  # noqa: S104
        port=8006,
        log_level="info",
    )


if __name__ == "__main__":
    main()
