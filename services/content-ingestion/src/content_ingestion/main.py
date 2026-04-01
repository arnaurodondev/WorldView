"""Uvicorn entry point for the content-ingestion service.

Usage::

    python -m content_ingestion.main
    # or
    uvicorn content_ingestion.app:create_app --factory --host 0.0.0.0 --port 8004
"""

from __future__ import annotations

import uvicorn


def main() -> None:
    """Start the content-ingestion service."""
    uvicorn.run(
        "content_ingestion.app:create_app",
        factory=True,
        host="0.0.0.0",  # noqa: S104
        port=8004,
        log_level="info",
    )


if __name__ == "__main__":
    main()
