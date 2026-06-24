#!/usr/bin/env python3
"""Bounded single-stream runner for the DeepSeek-V4-Flash FALLBACK measurement.

WHY THIS EXISTS (task #8 fallback eval, 2026-06-16)
---------------------------------------------------
``extraction_quality_eval.py run`` uses a generous 180s read timeout + a 5-step
exponential-backoff retry (5/15/30/45/60s ≈ 155s of added sleep per call). For the
235B *baseline* that was deliberate — it bursts ``engine_overloaded`` 429s and we did
not want the A/B invalidated by all-``api_error``. But for measuring whether
``deepseek-ai/DeepSeek-V4-Flash`` is a viable FAST FALLBACK, that retry logic MASKS
the very thing we are measuring: a saturated model that takes minutes per call is
*disqualified as a fallback*, and the retry would hide that behind a hung 4-hour run
(observed: the combined run sat at 0% CPU for 40min, blocked in backoff sleeps).

So this runner reuses the harness's EXACT prompt/decode/parse path (no drift) but:
  * lowers the read timeout to 60s (a fallback that needs >60s is already unusable), and
  * uses a SINGLE short retry (one 5s backoff) instead of five — a transient 429 gets
    one retry; a saturated endpoint records ``api_error`` FAST instead of hanging.
This yields the decision-relevant numbers for a fallback: true single-stream p50/p95
latency and the api_error/timeout rate under realistic (low-concurrency) fallback load.

Writes its ModelRunResult list to ``<out>/deepseek_runs.json`` (kept separate from the
gpt-oss-20b ``model_runs.json`` so neither clobbers the other); a merge step combines
them before judging.
"""

from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import asdict
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
import extraction_quality_eval as eqe  # noqa: E402

MODEL = "deepseek-ai/DeepSeek-V4-Flash"
READ_TIMEOUT_S = 60.0  # a fallback slower than this is already disqualified
SINGLE_BACKOFF = [5.0]  # one short retry on a transient 429/5xx, then record api_error


def _deepinfra_chat_bounded(
    client: httpx.Client,
    api_key: str,
    base_url: str,
    model_id: str,
    system_prompt: str,
    user_content: str,
) -> tuple[str, int, int]:
    """Same body/decode params as eqe._deepinfra_chat, but bounded retry (1 step)."""
    body = {
        "model": model_id,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        "temperature": eqe._EXTRACTION_TEMPERATURE,
        "max_tokens": eqe._EXTRACTION_MAX_TOKENS,
        "reasoning_effort": "none",  # DeepSeek-V4-Flash is NOT a reasoning model
        "response_format": {"type": "json_object"},
    }
    last_exc: Exception | None = None
    for attempt in range(len(SINGLE_BACKOFF) + 1):
        resp = client.post(
            f"{base_url}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json=body,
        )
        if resp.status_code == 429 or resp.status_code >= 500:
            last_exc = httpx.HTTPStatusError(
                f"transient {resp.status_code}: {resp.text[:200]}", request=resp.request, response=resp
            )
            if attempt < len(SINGLE_BACKOFF):
                time.sleep(SINGLE_BACKOFF[attempt])
                continue
            raise last_exc
        resp.raise_for_status()
        data = resp.json()
        content = data["choices"][0]["message"].get("content") or ""
        usage = data.get("usage") or {}
        return content, int(usage.get("prompt_tokens", 0) or 0), int(usage.get("completion_tokens", 0) or 0)
    raise last_exc if last_exc else RuntimeError("retry loop exited unexpectedly")


def _run_one(client: httpx.Client, api_key: str, base_url: str, article: eqe.GoldenArticle) -> eqe.ModelRunResult:
    eqe._ensure_prompts_importable()
    prompt = eqe._render_extraction_prompt(article.entities, article.text)
    t0 = time.perf_counter()
    try:
        content, tin, tout = _deepinfra_chat_bounded(
            client, api_key, base_url, MODEL, prompt, article.text
        )
    except Exception as exc:
        return eqe.ModelRunResult(
            doc_id=article.doc_id,
            model_id=MODEL,
            status="api_error",
            latency_s=round(time.perf_counter() - t0, 3),
            tokens_in=0,
            tokens_out=0,
            raw_response="",
            parsed=None,
            error=f"{type(exc).__name__}: {exc}",
        )
    latency = round(time.perf_counter() - t0, 3)
    parsed = None
    status = "ok"
    err = None
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        try:
            parsed = json.loads(eqe._strip_json_fences(content))
        except json.JSONDecodeError as exc:
            status, err = "json_error", f"JSONDecodeError: {exc}"
    if parsed is not None and not isinstance(parsed, dict):
        status, parsed, err = "json_error", None, "top-level JSON is not an object"
    n_e = n_c = n_r = None
    if parsed is not None:
        n_e = len(parsed.get("events") or [])
        n_c = len(parsed.get("claims") or [])
        n_r = len(parsed.get("relations") or [])
    return eqe.ModelRunResult(
        doc_id=article.doc_id,
        model_id=MODEL,
        status=status,
        latency_s=latency,
        tokens_in=tin,
        tokens_out=tout,
        raw_response=content,
        parsed=parsed,
        error=err,
        n_events=n_e,
        n_claims=n_c,
        n_relations=n_r,
    )


def main() -> None:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("results/extraction_fallback_eval")
    api_key = os.environ["DEEPINFRA_API_KEY"]
    base_url = os.environ.get("DEEPINFRA_BASE_URL", eqe._DEEPINFRA_BASE_URL)
    articles = eqe._load_golden(out)
    results: list[eqe.ModelRunResult] = []
    with httpx.Client(timeout=httpx.Timeout(connect=10.0, read=READ_TIMEOUT_S, write=30.0, pool=10.0)) as client:
        for i, art in enumerate(articles, 1):
            r = _run_one(client, api_key, base_url, art)
            results.append(r)
            print(
                f"[deepseek] {i}/{len(articles)} doc={art.doc_id[:8]} status={r.status} "
                f"{r.latency_s}s ev/cl/rel={r.n_events}/{r.n_claims}/{r.n_relations}",
                flush=True,
            )
    (out / "deepseek_runs.json").write_text(
        json.dumps([asdict(r) for r in results], indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"Wrote {len(results)} deepseek run results -> {out / 'deepseek_runs.json'}", flush=True)


if __name__ == "__main__":
    main()
