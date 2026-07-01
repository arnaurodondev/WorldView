"""Prometheus metrics for the Content Ingestion service (S4).

Counters and histograms track fetch operations, outbox pending, and DLQ.
"""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

# ── Counters ─────────────────────────────────────────────────────────────────

s4_fetches_total = Counter(
    "s4_fetches_total",
    "Total fetch operations by source and status",
    ["source", "status"],
)

# ── Histograms ───────────────────────────────────────────────────────────────

s4_fetch_duration_seconds = Histogram(
    "s4_fetch_duration_seconds",
    "Duration of fetch-and-write cycles in seconds",
    ["source"],
    buckets=(0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0),
)

# ── Gauges ───────────────────────────────────────────────────────────────────

s4_outbox_pending_total = Gauge(
    "s4_outbox_pending_total",
    "Number of pending outbox events",
)

s4_dlq_total = Gauge(
    "s4_dlq_total",
    "Number of open DLQ entries",
)

# ── EODHD quota accounting (blind-spot fix, 2026-07-01) ───────────────────────
# S4 is the LARGEST EODHD consumer (per-ticker news, ~520 fetches/hour) yet
# historically wrote NO shared quota counters, so the account-wide monthly total
# (and its dashboards/alerts) undercounted true usage and exhaustion fired with
# no freshness alert.  These metrics make S4's spend + threshold crossings
# observable so the next exhaustion is loud, not silent.

# Total EODHD credits S4 recorded into the shared cross-service counter.
s4_eodhd_credits_recorded_total = Counter(
    "s4_eodhd_credits_recorded_total",
    "EODHD credits recorded by content-ingestion into the shared Valkey quota counter",
    ["endpoint"],
)

# Threshold/exhaustion events — fires on the shared 80% soft limit, the 100%
# hard limit, or an auth/quota HTTP rejection (401/402/403/429).  Alert on any
# increase of this counter so exhaustion is caught before ingestion silently
# halts.
s4_eodhd_quota_alerts_total = Counter(
    "s4_eodhd_quota_alerts_total",
    "EODHD quota safeguard events seen by content-ingestion (soft/hard limit or auth/quota rejection)",
    ["reason"],
)


# ── General-news firehose (SHADOW STAGE, 2026-07-01) ──────────────────────────
# The general /api/news firehose polls at high frequency with EARLY-EXIT on the
# first already-stored url_hash so each steady-state poll costs exactly ONE
# request. These metrics make that credit-efficiency observable and provide the
# SHADOW-MODE coverage signal (new articles + symbol tags captured) so the
# shadow-diff tool can prove general coverage >= per-ticker before cutover.

# Requests (pages) issued per firehose sweep, labelled by the reason the sweep
# stopped: ``early_exit`` (hit an already-stored article — the steady-state 1
# request/poll case), ``drained`` (partial page — no more data), or ``page_cap``
# (defensive backstop hit). Alert if ``early_exit`` is NOT the dominant outcome
# at 60s cadence — that would mean each poll is burning more than 5 credits.
s4_general_firehose_requests_total = Counter(
    "s4_general_firehose_requests_total",
    "HTTP page requests issued by the general-news firehose sweep, by stop reason",
    ["outcome"],
)

# New (non-duplicate) articles captured by the firehose across all sweeps.
s4_general_firehose_new_articles_total = Counter(
    "s4_general_firehose_new_articles_total",
    "New (non-duplicate) articles captured by the general-news firehose",
)

# Symbol-tag occurrences observed on firehose articles — the coverage signal
# proving the general feed is a symbol-tagged superset of the per-ticker feeds.
s4_general_firehose_symbol_tags_total = Counter(
    "s4_general_firehose_symbol_tags_total",
    "Symbol tags observed on general-firehose articles (SHADOW coverage signal)",
)


def record_general_firehose_sweep(
    *,
    requests: int,
    outcome: str,
    new_articles: int,
    symbol_tags: int,
) -> None:
    """Record the outcome of one general-news firehose sweep.

    Args:
        requests: Number of HTTP page requests the sweep issued (each = 5 EODHD
            credits). Steady-state early-exit sweeps should report ``1``.
        outcome: Why the sweep stopped — ``"early_exit"`` (hit an already-stored
            article), ``"drained"`` (partial page), or ``"page_cap"`` (backstop).
        new_articles: New (non-duplicate) articles captured this sweep.
        symbol_tags: Total symbol-tag occurrences across the new articles (the
            SHADOW coverage signal).
    """
    # Attribute every request in the sweep to its stop reason so the ratio of
    # early_exit vs drained/page_cap requests is directly the credit-efficiency.
    if requests > 0:
        s4_general_firehose_requests_total.labels(outcome=outcome).inc(requests)
    if new_articles > 0:
        s4_general_firehose_new_articles_total.inc(new_articles)
    if symbol_tags > 0:
        s4_general_firehose_symbol_tags_total.inc(symbol_tags)


def record_fetch(source: str, *, fetched: int, skipped: int, failed: int, duration: float) -> None:
    """Record metrics for a completed fetch cycle."""
    if fetched > 0:
        s4_fetches_total.labels(source=source, status="fetched").inc(fetched)
    if skipped > 0:
        s4_fetches_total.labels(source=source, status="skipped").inc(skipped)
    if failed > 0:
        s4_fetches_total.labels(source=source, status="failed").inc(failed)
    s4_fetch_duration_seconds.labels(source=source).observe(duration)


def record_fetch_attempt(source: str, status: str, duration: float) -> None:
    """Record a single HTTP fetch attempt (per-call instrumentation).

    Distinct from :func:`record_fetch` (cycle-level aggregate). This is fired
    from inside the adapter clients (EODHD / NewsAPI / etc.) on each HTTP call.

    Args:
        source: Adapter identifier — e.g. ``"eodhd"``, ``"newsapi"``.
        status: One of ``"success"``, ``"error"``, ``"rate_limited"``.
        duration: Wall-clock seconds the HTTP call took.
    """
    s4_fetches_total.labels(source=source, status=status).inc()
    s4_fetch_duration_seconds.labels(source=source).observe(duration)


def record_eodhd_credits(endpoint: str, credit_cost: int) -> None:
    """Record EODHD credits attributed to S4 for a single request.

    Args:
        endpoint: EODHD endpoint identifier — e.g. ``"news"`` (general feed)
            or ``"ticker_news"`` (per-symbol feed).
        credit_cost: Credit cost of the request (news = 5/request).
    """
    if credit_cost > 0:
        s4_eodhd_credits_recorded_total.labels(endpoint=endpoint).inc(credit_cost)


def record_eodhd_quota_alert(reason: str) -> None:
    """Record an EODHD quota safeguard event so alerts fire loudly.

    Args:
        reason: One of ``"soft_limit"`` (≥80% monthly), ``"hard_limit"``
            (≥100% monthly), or ``"auth_or_quota_rejected"`` (HTTP 401/402/403/429).
    """
    s4_eodhd_quota_alerts_total.labels(reason=reason).inc()
