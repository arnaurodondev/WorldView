"""Unit tests for the SEC EDGAR adapter."""

from __future__ import annotations

from datetime import UTC
from typing import Any
from unittest.mock import AsyncMock

import pytest
from content_ingestion.config import SECEdgarProviderSettings
from content_ingestion.domain.entities import Source, SourceType
from content_ingestion.domain.exceptions import ConfigurationError
from content_ingestion.infrastructure.adapters.base import RetryConfig
from content_ingestion.infrastructure.adapters.sec_edgar.adapter import (
    SECEdgarAdapter,
    _is_xbrl_or_viewer,
    _parse_published_at,
    _synthesize_title,
    resolve_primary_document,
)
from content_ingestion.infrastructure.adapters.sec_edgar.client import SECEdgarClient

pytestmark = pytest.mark.unit


def _make_source(**kwargs: Any) -> Source:
    defaults: dict[str, Any] = {
        "name": "test-edgar",
        "source_type": SourceType.SEC_EDGAR,
        "enabled": True,
        "config": {"from_date": "2026-01-01", "to_date": "2026-03-01"},
    }
    defaults.update(kwargs)
    return Source(**defaults)


def _manifest(primary_name: str, form_type: str = "10-Q") -> dict[str, Any]:
    """Build a realistic EDGAR ``index.json`` manifest with a primary doc + XBRL noise."""
    return {
        "directory": {
            "item": [
                {"name": f"{primary_name}", "type": form_type, "size": "500000"},
                {"name": "R1.htm", "type": "", "size": "12000"},
                {"name": "filing_cal.xml", "type": "EX-101.CAL", "size": "8000"},
                {"name": "exhibit99.htm", "type": "EX-99.1", "size": "3000"},
            ]
        }
    }


def _mock_client_with_primary(primary_name: str = "primary-doc.htm") -> AsyncMock:
    """AsyncMock SECEdgarClient wired so the primary-doc fetch path succeeds."""
    mock_client = AsyncMock(spec=SECEdgarClient)
    mock_client.fetch_filing_manifest.return_value = _manifest(primary_name)
    mock_client.fetch_filing_document.return_value = b"<html>Filing content</html>"
    return mock_client


def _filing(adsh: str, ciks: list[str] | None = None) -> dict[str, Any]:
    """Build a realistic EFTS _source dict using the actual EFTS field names.

    BP-460: EFTS returns ``adsh`` (not ``accession_no``), ``ciks`` as a list
    (not ``cik`` as a string), and ``period_ending`` (not ``period_of_report``).
    There is no ``file_name`` field in the EFTS response.
    """
    return {
        "_source": {
            "adsh": adsh,
            "ciks": ciks if ciks is not None else ["0000012345"],
            "entity_name": "Test Corp",
            "form_type": "10-Q",
            "file_date": "2026-01-20",
            "period_ending": "2026-01-15",
        }
    }


class TestSECEdgarUserAgentValidation:
    def test_raises_on_empty_user_agent(self) -> None:
        mock_http = AsyncMock()
        with pytest.raises(ConfigurationError, match="User-Agent"):
            SECEdgarClient(
                http_client=mock_http,
                user_agent="",
                provider_cfg=SECEdgarProviderSettings(),
            )

    def test_raises_on_whitespace_user_agent(self) -> None:
        mock_http = AsyncMock()
        with pytest.raises(ConfigurationError, match="User-Agent"):
            SECEdgarClient(
                http_client=mock_http,
                user_agent="   ",
                provider_cfg=SECEdgarProviderSettings(),
            )

    def test_accepts_valid_user_agent(self) -> None:
        mock_http = AsyncMock()
        client = SECEdgarClient(
            http_client=mock_http,
            user_agent="worldview/1.0 test@example.com",
            provider_cfg=SECEdgarProviderSettings(),
        )
        assert client._user_agent == "worldview/1.0 test@example.com"


class TestParsePublishedAt:
    def test_period_ending(self) -> None:
        """BP-460: EFTS uses 'period_ending', not 'period_of_report'."""
        result = _parse_published_at({"_source": {"period_ending": "2026-01-15"}})
        assert result is not None
        assert result.day == 15

    def test_old_period_of_report_not_recognised(self) -> None:
        """BP-460 regression: old field name must produce None (so we catch regressions)."""
        result = _parse_published_at({"_source": {"period_of_report": "2026-01-15"}})
        assert result is None

    def test_file_date_fallback(self) -> None:
        result = _parse_published_at({"_source": {"file_date": "2026-02-20"}})
        assert result is not None
        assert result.month == 2

    def test_period_ending_takes_priority_over_file_date(self) -> None:
        """period_ending is primary; file_date is the fallback."""
        result = _parse_published_at({"_source": {"period_ending": "2026-03-31", "file_date": "2026-04-15"}})
        assert result is not None
        assert result.month == 3
        assert result.day == 31

    def test_no_date_fields(self) -> None:
        assert _parse_published_at({"_source": {}}) is None


class TestSECEdgarAdapterFetch:
    async def test_fetches_and_returns_results(self) -> None:
        mock_client = AsyncMock(spec=SECEdgarClient)
        mock_client.search_filings.return_value = [
            # BP-460: use correct EFTS field names (adsh, ciks)
            _filing("0001234567-26-000001"),
        ]
        mock_client.fetch_filing_manifest.return_value = _manifest("primary-doc.htm")
        mock_client.fetch_filing_document.return_value = b"<html>Filing content</html>"

        adapter = SECEdgarAdapter(
            client=mock_client,
            retry_config=RetryConfig(max_retries=1, backoff_factors=(0.0,)),
        )
        results = await adapter.fetch(_make_source())
        assert len(results) == 1
        assert b"Filing content" in results[0].raw_bytes

    async def test_dedup_skips_existing(self) -> None:
        mock_client = AsyncMock(spec=SECEdgarClient)
        mock_client.search_filings.return_value = [_filing("0001234567-26-000002")]
        exists_fn = AsyncMock(return_value=True)

        adapter = SECEdgarAdapter(
            client=mock_client,
            exists_fn=exists_fn,
            retry_config=RetryConfig(max_retries=1, backoff_factors=(0.0,)),
        )
        results = await adapter.fetch(_make_source())
        assert len(results) == 0

    async def test_dedup_hash_uses_accession_number(self) -> None:
        """BP-460: dedup hash is sha256(accession_number) — no file_name suffix."""
        from content_ingestion.infrastructure.adapters.base import url_hash

        # Two different accession numbers must yield different hashes.
        h1 = url_hash("0001234567-26-000001")
        h2 = url_hash("0001234567-26-000002")
        assert h1 != h2

    async def test_is_backfill_propagated(self) -> None:
        mock_client = AsyncMock(spec=SECEdgarClient)
        mock_client.search_filings.return_value = [_filing("0001234567-26-000003")]
        mock_client.fetch_filing_manifest.return_value = _manifest("primary-doc.htm")
        mock_client.fetch_filing_document.return_value = b"<html>content</html>"

        adapter = SECEdgarAdapter(
            client=mock_client,
            retry_config=RetryConfig(max_retries=1, backoff_factors=(0.0,)),
        )
        results = await adapter.fetch(_make_source(), is_backfill=True)
        assert len(results) == 1
        assert results[0].is_backfill is True

    async def test_skips_filing_without_adsh(self) -> None:
        """BP-460: filings missing the adsh field must be silently skipped."""
        mock_client = AsyncMock(spec=SECEdgarClient)
        # A filing with no adsh key — should be skipped
        mock_client.search_filings.return_value = [{"_source": {"entity_name": "No ADSH Corp"}}]

        adapter = SECEdgarAdapter(
            client=mock_client,
            retry_config=RetryConfig(max_retries=1, backoff_factors=(0.0,)),
        )
        results = await adapter.fetch(_make_source())
        assert results == []


class TestSECEdgarFieldMappingBP460:
    """Regression tests for BP-460: EFTS field name mismatch.

    These tests verify the exact field reads and URL construction logic
    that was broken before the fix.
    """

    async def test_reads_adsh_not_accession_no(self) -> None:
        """BP-460: adapter must read 'adsh', not 'accession_no'."""
        mock_client = AsyncMock(spec=SECEdgarClient)
        # Provide only the NEW correct field name; the old name ('accession_no')
        # is absent.  If the adapter still reads the old name, it skips the filing
        # and returns an empty list.
        mock_client.search_filings.return_value = [
            {
                "_source": {
                    "adsh": "0001477932-26-002885",
                    "ciks": ["0000320193"],
                    "entity_name": "Apple Inc.",
                    "form_type": "10-Q",
                    "file_date": "2026-04-15",
                    "period_ending": "2026-03-31",
                }
            }
        ]
        mock_client.fetch_filing_manifest.return_value = _manifest("primary-doc.htm")
        mock_client.fetch_filing_document.return_value = b"<html>index</html>"

        adapter = SECEdgarAdapter(
            client=mock_client,
            retry_config=RetryConfig(max_retries=1, backoff_factors=(0.0,)),
        )
        results = await adapter.fetch(_make_source())
        # Must find exactly 1 result — not 0 (which was the pre-fix behaviour)
        assert len(results) == 1

    async def test_cik_leading_zeros_stripped(self) -> None:
        """BP-460: cik extracted from ciks[0] must have leading zeros removed."""
        mock_client = AsyncMock(spec=SECEdgarClient)
        mock_client.search_filings.return_value = [
            {
                "_source": {
                    "adsh": "0001477932-26-002885",
                    # Apple's CIK with leading zeros, as returned by EFTS
                    "ciks": ["0000320193"],
                    "entity_name": "Apple Inc.",
                    "form_type": "10-Q",
                    "file_date": "2026-04-15",
                    "period_ending": "2026-03-31",
                }
            }
        ]
        mock_client.fetch_filing_manifest.return_value = _manifest("primary-doc.htm")
        mock_client.fetch_filing_document.return_value = b"<html>index</html>"

        adapter = SECEdgarAdapter(
            client=mock_client,
            retry_config=RetryConfig(max_retries=1, backoff_factors=(0.0,)),
        )
        results = await adapter.fetch(_make_source())
        assert len(results) == 1
        # URL must contain the bare CIK without leading zeros
        assert "/320193/" in results[0].url
        assert "/0000320193/" not in results[0].url

    async def test_url_construction_matches_edgar_format(self) -> None:
        """BP-460: URL must follow the EDGAR Archives index page format."""
        mock_client = AsyncMock(spec=SECEdgarClient)
        mock_client.search_filings.return_value = [
            {
                "_source": {
                    "adsh": "0001477932-26-002885",
                    "ciks": ["0000320193"],
                    "entity_name": "Apple Inc.",
                    "form_type": "10-Q",
                    "file_date": "2026-04-15",
                    "period_ending": "2026-03-31",
                }
            }
        ]
        mock_client.fetch_filing_manifest.return_value = _manifest("primary-doc.htm")
        mock_client.fetch_filing_document.return_value = b"<html>index</html>"

        adapter = SECEdgarAdapter(
            client=mock_client,
            retry_config=RetryConfig(max_retries=1, backoff_factors=(0.0,)),
        )
        results = await adapter.fetch(_make_source())
        assert len(results) == 1
        expected_url = (
            "https://www.sec.gov/Archives/edgar/data/320193" "/000147793226002885/0001477932-26-002885-index.htm"
        )
        assert results[0].url == expected_url

    async def test_period_ending_read_for_published_at(self) -> None:
        """BP-460: published_at must come from 'period_ending', not 'period_of_report'."""
        mock_client = AsyncMock(spec=SECEdgarClient)
        mock_client.search_filings.return_value = [
            {
                "_source": {
                    "adsh": "0001234567-26-000001",
                    "ciks": ["0000012345"],
                    "period_ending": "2026-03-31",  # correct EFTS field
                    "file_date": "2026-04-15",
                }
            }
        ]
        mock_client.fetch_filing_manifest.return_value = _manifest("primary-doc.htm")
        mock_client.fetch_filing_document.return_value = b"<html>index</html>"

        adapter = SECEdgarAdapter(
            client=mock_client,
            retry_config=RetryConfig(max_retries=1, backoff_factors=(0.0,)),
        )
        results = await adapter.fetch(_make_source())
        assert len(results) == 1
        assert results[0].published_at is not None
        assert results[0].published_at.month == 3
        assert results[0].published_at.day == 31

    async def test_empty_ciks_list_skips_filing_gracefully(self) -> None:
        """BP-460: a filing with an empty ciks list must produce an empty CIK string."""
        mock_client = AsyncMock(spec=SECEdgarClient)
        mock_client.search_filings.return_value = [
            {
                "_source": {
                    "adsh": "0001234567-26-000001",
                    "ciks": [],  # edge case: empty list
                    "entity_name": "Unknown Corp",
                    "form_type": "8-K",
                    "file_date": "2026-04-15",
                    "period_ending": "2026-03-31",
                }
            }
        ]
        mock_client.fetch_filing_manifest.return_value = _manifest("primary-doc.htm")
        mock_client.fetch_filing_document.return_value = b"<html>index</html>"

        adapter = SECEdgarAdapter(
            client=mock_client,
            retry_config=RetryConfig(max_retries=1, backoff_factors=(0.0,)),
        )
        # Should not raise — produces a result with an empty CIK in the URL
        results = await adapter.fetch(_make_source())
        assert len(results) == 1
        # URL will have an empty CIK segment but must be syntactically valid
        assert "0001234567-26-000001-index.htm" in results[0].url


class TestSECEdgarAdapterMarketHours:
    """Tests for _is_market_hours() and calculate_next_run_time()."""

    def _make_adapter(self) -> SECEdgarAdapter:
        from unittest.mock import MagicMock

        from content_ingestion.infrastructure.adapters.sec_edgar.client import SECEdgarClient

        cfg = SECEdgarProviderSettings(market_hours_interval_seconds=60, off_hours_interval_seconds=1800)
        return SECEdgarAdapter(client=MagicMock(spec=SECEdgarClient), provider_cfg=cfg)

    def _utc(self, iso: str) -> object:
        from datetime import datetime

        return datetime.fromisoformat(iso).replace(tzinfo=UTC)

    def test_is_market_hours_tuesday_10am_et(self) -> None:
        """Tuesday 10:00 ET (15:00 UTC) is within market hours."""
        adapter = self._make_adapter()
        # 2026-04-07 is a Tuesday. 10:00 ET = 14:00 UTC (EDT, UTC-4)
        assert adapter._is_market_hours(self._utc("2026-04-07T14:00:00+00:00")) is True  # type: ignore[arg-type]

    def test_is_market_hours_saturday_noon_et(self) -> None:
        """Saturday noon ET is outside market hours."""
        adapter = self._make_adapter()
        # 2026-04-11 is a Saturday. Noon ET = 16:00 UTC (EDT)
        assert adapter._is_market_hours(self._utc("2026-04-11T16:00:00+00:00")) is False  # type: ignore[arg-type]

    def test_is_market_hours_weekday_before_open(self) -> None:
        """Tuesday 08:00 ET (before 09:30 open) is outside market hours."""
        adapter = self._make_adapter()
        # 2026-04-07 Tuesday 08:00 ET = 12:00 UTC (EDT)
        assert adapter._is_market_hours(self._utc("2026-04-07T12:00:00+00:00")) is False  # type: ignore[arg-type]

    def test_is_market_hours_weekday_after_close(self) -> None:
        """Tuesday 17:00 ET (after 16:00 close) is outside market hours."""
        adapter = self._make_adapter()
        # 2026-04-07 Tuesday 17:00 ET = 21:00 UTC (EDT)
        assert adapter._is_market_hours(self._utc("2026-04-07T21:00:00+00:00")) is False  # type: ignore[arg-type]

    def test_is_market_hours_dst_transition(self) -> None:
        """DST switch day (March 8, 2026) at 10:00 local time → market hours."""
        adapter = self._make_adapter()
        # 2026-03-08 Sunday DST starts; 2026-03-09 Monday 10:00 ET = 14:00 UTC (EDT, UTC-4)
        assert adapter._is_market_hours(self._utc("2026-03-09T14:00:00+00:00")) is True  # type: ignore[arg-type]

    def test_calculate_next_run_market_hours(self) -> None:
        """During market hours → next run = now + 60s."""
        from datetime import timedelta

        adapter = self._make_adapter()
        now_utc = self._utc("2026-04-07T14:00:00+00:00")
        expected = now_utc + timedelta(seconds=60)  # type: ignore[operator]
        assert adapter.calculate_next_run_time(now_utc) == expected  # type: ignore[arg-type]

    def test_calculate_next_run_off_hours(self) -> None:
        """Outside market hours → next run = now + 1800s."""
        from datetime import timedelta

        adapter = self._make_adapter()
        now_utc = self._utc("2026-04-07T21:00:00+00:00")
        expected = now_utc + timedelta(seconds=1800)  # type: ignore[operator]
        assert adapter.calculate_next_run_time(now_utc) == expected  # type: ignore[arg-type]


class TestIsXbrlOrViewer:
    """R1 Fix ①: exclude XBRL/taxonomy/viewer artefacts from primary-doc resolution."""

    def test_xml_excluded(self) -> None:
        assert _is_xbrl_or_viewer("aapl-20230930.xml") is True

    def test_xsd_excluded(self) -> None:
        assert _is_xbrl_or_viewer("aapl-20230930.xsd") is True

    def test_r_viewer_excluded(self) -> None:
        assert _is_xbrl_or_viewer("R1.htm") is True
        assert _is_xbrl_or_viewer("R42.htm") is True

    def test_xbrl_linkbase_html_excluded(self) -> None:
        for suffix in ("_cal", "_def", "_lab", "_pre", "_ref"):
            assert _is_xbrl_or_viewer(f"filing{suffix}.htm") is True

    def test_primary_htm_not_excluded(self) -> None:
        assert _is_xbrl_or_viewer("aapl-20230930.htm") is False

    def test_case_insensitive(self) -> None:
        assert _is_xbrl_or_viewer("FILING.XML") is True
        assert _is_xbrl_or_viewer("r7.HTM") is True


class TestResolvePrimaryDocument:
    """R1 Fix ①: pick the largest form-matching HTML doc, excluding XBRL/viewer/index."""

    def _manifest_items(self, items: list[dict[str, Any]]) -> dict[str, Any]:
        return {"directory": {"item": items}}

    def test_prefers_form_matching_type_over_larger_exhibit(self) -> None:
        # A larger EX-99 exhibit exists, but the 10-K-typed doc must win.
        manifest = self._manifest_items(
            [
                {"name": "primary-10k.htm", "type": "10-K", "size": "200000"},
                {"name": "big-exhibit.htm", "type": "EX-99.1", "size": "900000"},
            ]
        )
        assert resolve_primary_document(manifest, form_type="10-K", accession_no="0001-26-1") == "primary-10k.htm"

    def test_excludes_xbrl_and_viewer_files(self) -> None:
        manifest = self._manifest_items(
            [
                {"name": "R1.htm", "type": "", "size": "999999"},
                {"name": "doc_cal.htm", "type": "", "size": "999999"},
                {"name": "doc.xml", "type": "10-Q", "size": "999999"},
                {"name": "the-real-doc.htm", "type": "10-Q", "size": "50000"},
            ]
        )
        assert resolve_primary_document(manifest, form_type="10-Q", accession_no="0001-26-1") == "the-real-doc.htm"

    def test_excludes_index_page_itself(self) -> None:
        manifest = self._manifest_items(
            [
                {"name": "0001-26-1-index.htm", "type": "", "size": "999999"},
                {"name": "body.htm", "type": "8-K", "size": "10000"},
            ]
        )
        assert resolve_primary_document(manifest, form_type="8-K", accession_no="0001-26-1") == "body.htm"

    def test_largest_html_when_no_type_match(self) -> None:
        # No type matches the form → fall back to largest non-excluded HTML.
        manifest = self._manifest_items(
            [
                {"name": "small.htm", "type": "", "size": "1000"},
                {"name": "large.htm", "type": "", "size": "80000"},
            ]
        )
        assert resolve_primary_document(manifest, form_type="10-K", accession_no="0001-26-1") == "large.htm"

    def test_returns_none_when_no_html(self) -> None:
        manifest = self._manifest_items([{"name": "filing.txt", "type": "10-K", "size": "5000"}])
        assert resolve_primary_document(manifest, form_type="10-K", accession_no="0001-26-1") is None

    def test_returns_none_on_empty_manifest(self) -> None:
        assert resolve_primary_document({}, form_type="10-K", accession_no="0001-26-1") is None

    def test_handles_missing_size_field(self) -> None:
        manifest = self._manifest_items([{"name": "doc.htm", "type": "10-K"}])
        assert resolve_primary_document(manifest, form_type="10-K", accession_no="0001-26-1") == "doc.htm"


class TestSynthesizeTitle:
    """R1 Fix ①: dsm.title must stop being NULL — synthesize '{FORM} — {Company} ({Period})'."""

    def test_full_title_from_entity_name(self) -> None:
        src = {"entity_name": "Apple Inc.", "period_ending": "2026-03-31"}
        assert _synthesize_title(src, "10-Q") == "10-Q — Apple Inc. (2026-03-31)"

    def test_strips_ticker_and_cik_from_display_names(self) -> None:
        src = {"display_names": ["Apple Inc. (AAPL) (CIK 0000320193)"], "period_ending": "2026-03-31"}
        assert _synthesize_title(src, "10-K") == "10-K — Apple Inc. (2026-03-31)"

    def test_falls_back_to_file_date_when_no_period(self) -> None:
        src = {"entity_name": "Test Corp", "file_date": "2026-01-20"}
        assert _synthesize_title(src, "8-K") == "8-K — Test Corp (2026-01-20)"

    def test_no_period_omits_parenthetical(self) -> None:
        src = {"entity_name": "Test Corp"}
        assert _synthesize_title(src, "8-K") == "8-K — Test Corp"

    def test_returns_none_when_no_form_and_no_company(self) -> None:
        assert _synthesize_title({"period_ending": "2026-03-31"}, "") is None


class TestParseCiks:
    """R1 Fix ②: watchlist CIKs normalise to zero-padded 10-digit form."""

    def test_comma_separated_string(self) -> None:
        assert SECEdgarAdapter._parse_ciks("320193, 789019") == ["0000320193", "0000789019"]

    def test_list_of_ints(self) -> None:
        assert SECEdgarAdapter._parse_ciks([320193, 789019]) == ["0000320193", "0000789019"]

    def test_already_padded(self) -> None:
        assert SECEdgarAdapter._parse_ciks(["0000320193"]) == ["0000320193"]

    def test_none_and_empty(self) -> None:
        assert SECEdgarAdapter._parse_ciks(None) == []
        assert SECEdgarAdapter._parse_ciks("") == []

    def test_drops_non_numeric(self) -> None:
        assert SECEdgarAdapter._parse_ciks("320193, abc, 789019") == ["0000320193", "0000789019"]


class TestSECEdgarPrimaryDocFetch:
    """R1 Fix ①/②: adapter fetches the primary doc, sets a title, skips text-only, scopes by CIK."""

    async def test_fetches_primary_doc_not_index_page(self) -> None:
        mock_client = _mock_client_with_primary("aapl-10q.htm")
        mock_client.search_filings.return_value = [_filing("0001234567-26-000001", ciks=["0000320193"])]
        adapter = SECEdgarAdapter(client=mock_client, retry_config=RetryConfig(max_retries=1, backoff_factors=(0.0,)))

        results = await adapter.fetch(_make_source())

        assert len(results) == 1
        # The document fetched must be the resolved primary filename, NOT the -index.htm page.
        _, kwargs = mock_client.fetch_filing_document.call_args
        assert kwargs["filename"] == "aapl-10q.htm"
        assert "-index.htm" not in kwargs["filename"]

    async def test_title_is_synthesized_and_propagated(self) -> None:
        mock_client = _mock_client_with_primary("doc.htm")
        mock_client.search_filings.return_value = [
            {
                "_source": {
                    "adsh": "0001234567-26-000001",
                    "ciks": ["0000320193"],
                    "entity_name": "Apple Inc.",
                    "form_type": "10-Q",
                    "period_ending": "2026-03-31",
                    "file_date": "2026-04-15",
                }
            }
        ]
        adapter = SECEdgarAdapter(client=mock_client, retry_config=RetryConfig(max_retries=1, backoff_factors=(0.0,)))

        results = await adapter.fetch(_make_source())

        assert results[0].title == "10-Q — Apple Inc. (2026-03-31)"

    async def test_skips_filing_with_no_primary_document(self) -> None:
        mock_client = AsyncMock(spec=SECEdgarClient)
        mock_client.search_filings.return_value = [_filing("0001234567-26-000001")]
        # Manifest has only a text file → no groundable HTML → filing skipped.
        mock_client.fetch_filing_manifest.return_value = {
            "directory": {"item": [{"name": "filing.txt", "type": "8-K", "size": "5000"}]}
        }
        adapter = SECEdgarAdapter(client=mock_client, retry_config=RetryConfig(max_retries=1, backoff_factors=(0.0,)))

        results = await adapter.fetch(_make_source())

        assert results == []
        mock_client.fetch_filing_document.assert_not_called()

    async def test_ciks_watchlist_scopes_search_per_cik(self) -> None:
        mock_client = _mock_client_with_primary("doc.htm")
        mock_client.search_filings.return_value = []  # no filings — we only assert scoping calls
        adapter = SECEdgarAdapter(client=mock_client, retry_config=RetryConfig(max_retries=1, backoff_factors=(0.0,)))

        source = _make_source(config={"ciks": ["0000320193", "0000789019"]})
        await adapter.fetch(source)

        # One scoped search per watched CIK, each passing the padded CIK to EFTS.
        passed = {call.kwargs["ciks"] for call in mock_client.search_filings.call_args_list}
        assert passed == {"0000320193", "0000789019"}

    async def test_no_ciks_falls_back_to_global_search(self) -> None:
        mock_client = _mock_client_with_primary("doc.htm")
        mock_client.search_filings.return_value = []
        adapter = SECEdgarAdapter(client=mock_client, retry_config=RetryConfig(max_retries=1, backoff_factors=(0.0,)))

        await adapter.fetch(_make_source())

        # Legacy global search: exactly one call, no ciks kwarg supplied.
        assert mock_client.search_filings.call_count == 1
        assert "ciks" not in mock_client.search_filings.call_args.kwargs
