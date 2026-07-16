"""Granular checks for content ingestion (S4) + content store (S5).

Covers: news/content freshness + volume, ingestion task success ratio, dedup +
title coverage (SEC primary-doc fix), enabled polling sources, and bounded DLQs.
"""

from __future__ import annotations

from .. import harness as H
from .. import thresholds as T
from ..harness import Ctx

SVC = "content"


def run(ctx: Ctx) -> None:
    R = ctx.report

    cs = H.psql_many(
        "content_store_db",
        {
            "docs": "SELECT count(*) FROM documents",
            "docs_24h": "SELECT count(*) FROM documents WHERE ingested_at > now() - interval '24 hours'",
            "fresh_h": "SELECT round(extract(epoch from now()-max(ingested_at))/3600,1) FROM documents",
            "titled": "SELECT count(*) FILTER (WHERE title IS NOT NULL AND length(title)>0) FROM documents",
            "src_types": "SELECT string_agg(source_type||':'||c, ',') FROM (SELECT source_type, count(*) c FROM documents GROUP BY 1) t",
        },
    )
    R.floor(SVC, "content-store documents", H.as_int(cs["docs"]), T.CS_DOCS_FLOOR)
    R.floor(SVC, "documents ingested / 24h", H.as_int(cs["docs_24h"]), T.CS_DOCS_24H_WARN)
    fresh = H.as_float(cs["fresh_h"])
    if fresh == fresh:
        st = H.FAIL if fresh > T.CS_FRESH_FAIL_H else H.WARN if fresh > T.CS_FRESH_WARN_H else H.PASS
        R.add(SVC, "content pipeline freshness (ingest→NER→store)", st, f"newest doc {fresh}h old")
    R.floor(SVC, "document title coverage %", H.pct(cs["titled"], cs["docs"]), T.CS_TITLE_COVERAGE_WARN, unit="%")
    R.ok(SVC, "content-store source mix", cs["src_types"] or "n/a")

    ci = H.psql_many(
        "content_ingestion_db",
        {
            "sources_enabled": "SELECT count(*) FILTER (WHERE enabled) FROM sources",
            "task_total": "SELECT count(*) FROM content_ingestion_tasks",
            "task_failed": "SELECT count(*) FILTER (WHERE status='failed') FROM content_ingestion_tasks",
            "dlq": "SELECT count(*) FROM dead_letter_queue WHERE resolved_at IS NULL",
        },
    )
    R.floor(SVC, "enabled polling sources", H.as_int(ci["sources_enabled"]), T.CI_SOURCES_ENABLED_FLOOR)
    total = H.as_int(ci["task_total"], 0)
    failed = H.as_int(ci["task_failed"], 0)
    ratio = round(failed / total, 3) if total else 0.0
    R.check(
        SVC,
        "ingestion task failure ratio bounded",
        ratio <= T.CI_TASK_FAILED_RATIO_WARN,
        f"{failed}/{total} failed ({ratio})",
        soft=True,
    )
    R.check(
        SVC, "content-ingestion DLQ bounded", H.as_int(ci["dlq"], 0) < T.DLQ_DB_BACKLOG_WARN, f"{ci['dlq']} unresolved"
    )
