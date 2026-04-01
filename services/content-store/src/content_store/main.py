"""Uvicorn entry point for the content-store service (S5).

Usage::

    python -m content_store.main
    # or
    uvicorn content_store.app:create_app --factory --host 0.0.0.0 --port 8005
"""

from __future__ import annotations

import uvicorn


def main() -> None:
    """Start the content-store service."""
    uvicorn.run(
        "content_store.app:create_app",
        factory=True,
        host="0.0.0.0",  # noqa: S104
        port=8005,
        log_level="info",
    )


if __name__ == "__main__":
    main()
