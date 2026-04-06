"""Uvicorn entry point — run with: ``python -m rag_chat``."""

from __future__ import annotations

import uvicorn

from rag_chat.infrastructure.config.settings import RagChatSettings


def main() -> None:
    settings = RagChatSettings()  # type: ignore[call-arg]
    from rag_chat.app import create_app

    application = create_app(settings)
    uvicorn.run(
        application,
        host=settings.host,
        port=settings.port,
        log_config=None,  # observability lib owns logging
    )


if __name__ == "__main__":
    main()
