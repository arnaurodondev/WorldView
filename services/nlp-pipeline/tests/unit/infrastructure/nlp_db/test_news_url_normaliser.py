"""Regression test for D-F1-009 (PLAN-0087) — Finnhub API URL normalization.

The Finnhub /company-news endpoint returns ``https://finnhub.io/api/news?id=<hash>``
for free / lower-tier plans.  That URL returns raw JSON when followed,
breaking citations on every news surface.  ``_normalise_finnhub_api_url``
rewrites it to ``https://finnhub.io/news/<hash>`` (the public web view).
"""

from __future__ import annotations

from nlp_pipeline.infrastructure.nlp_db.repositories.news_query import _normalise_finnhub_api_url


def test_finnhub_api_url_rewritten_to_public_path() -> None:
    api_url = "https://finnhub.io/api/news?id=ef7e441b3159ee4b611333a8a7c2b5bc2d44f4621dacc92aba1f11c0283b9ff7"
    expected = "https://finnhub.io/news/ef7e441b3159ee4b611333a8a7c2b5bc2d44f4621dacc92aba1f11c0283b9ff7"
    assert _normalise_finnhub_api_url(api_url) == expected


def test_finnhub_api_url_with_extra_query_params_strips_them() -> None:
    api_url = "https://finnhub.io/api/news?id=abc123&utm=foo"
    assert _normalise_finnhub_api_url(api_url) == "https://finnhub.io/news/abc123"


def test_non_finnhub_url_passes_through_unchanged() -> None:
    raw = "https://reuters.com/markets/companies/apple-quarterly-earnings"
    assert _normalise_finnhub_api_url(raw) == raw


def test_already_public_finnhub_url_passes_through_unchanged() -> None:
    public = "https://finnhub.io/news/abc123"
    # The /news/ pattern is the target shape; should not be re-rewritten.
    assert _normalise_finnhub_api_url(public) == public


def test_none_url_passes_through() -> None:
    assert _normalise_finnhub_api_url(None) is None


def test_empty_url_passes_through() -> None:
    assert _normalise_finnhub_api_url("") == ""
