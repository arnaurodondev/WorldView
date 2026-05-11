"""GLiNER HTTP adapter — NER via the containerised GLiNER server.

Use this adapter when GLiNER runs as a separate container (recommended for
multi-replica NLP pipeline deployments).  The adapter calls the batch endpoint
so all sections in a document are processed in one HTTP round-trip.

Configure via ``NLP_PIPELINE_GLINER_BASE_URL``.  When the env var is empty the
consumer falls back to ``GLiNERLocalAdapter`` (in-process).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from ml_clients.dataclasses import EntityMention, NERInput, NEROutput
from ml_clients.errors import FatalError, RetryableError

if TYPE_CHECKING:
    import asyncio

logger = structlog.get_logger()


class GLiNERHTTPAdapter:
    """Calls the GLiNER server over HTTP (batch endpoint).

    Args:
        base_url: Base URL of the GLiNER server, e.g. ``http://gliner-server:8080``.
        semaphore: Limits concurrent in-flight requests.
        timeout_seconds: Per-request timeout.
    """

    def __init__(
        self,
        base_url: str,
        semaphore: asyncio.Semaphore,  # type: ignore[name-defined]
        timeout_seconds: float = 60.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._semaphore = semaphore
        self._timeout = timeout_seconds

    async def extract_entities(self, inp: NERInput) -> NEROutput:
        results = await self.batch_extract_entities([inp])
        return results[0]

    async def batch_extract_entities(self, inputs: list[NERInput]) -> list[NEROutput]:
        """Send a batch of texts to the GLiNER server in one HTTP call."""
        if not inputs:
            return []

        try:
            import httpx  # type: ignore[import-not-found]
        except ImportError as exc:
            raise FatalError("httpx not installed; add it to ml-clients dependencies") from exc

        payload = {
            "texts": [inp.text for inp in inputs],
            "entity_classes": inputs[0].entity_classes,
            "threshold": inputs[0].threshold,
        }

        async with self._semaphore:
            try:
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    resp = await client.post(f"{self._base_url}/ner/batch", json=payload)

                if resp.status_code == 503:
                    raise RetryableError(f"GLiNER server unavailable: {resp.status_code}")
                if resp.status_code >= 500:
                    raise RetryableError(f"GLiNER server 5xx: {resp.status_code}")
                if resp.status_code >= 400:
                    raise FatalError(f"GLiNER server 4xx: {resp.status_code} — {resp.text}")

                data = resp.json()
                outputs: list[NEROutput] = []
                for section_entities in data["results"]:
                    mentions = [
                        EntityMention(
                            text=str(e["text"]),
                            label=str(e["label"]),
                            start=int(e["start"]),
                            end=int(e["end"]),
                            score=float(e["score"]),
                        )
                        for e in section_entities
                    ]
                    outputs.append(NEROutput(mentions=mentions))

                logger.info(
                    "ner_http_batch_completed",
                    base_url=self._base_url,
                    batch_size=len(inputs),
                    total_entities=sum(len(o.mentions) for o in outputs),
                )
                return outputs

            except (RetryableError, FatalError):
                raise
            except httpx.TimeoutException as exc:
                raise RetryableError(f"GLiNER server timeout: {exc}") from exc
            except httpx.ConnectError as exc:
                raise RetryableError(f"GLiNER server connection error: {exc}") from exc
            except Exception as exc:
                raise FatalError(f"Unexpected GLiNER HTTP error: {exc}") from exc
