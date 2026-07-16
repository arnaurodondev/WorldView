"""News and content tool handlers — document search, morning brief, entity news.

Covers tools backed by S6Port and BriefArchivePort:
  - search_documents   (S6Port — hybrid BM25+ANN document search)
  - get_morning_brief  (BriefArchivePort — DB-archived morning brief)
  - get_entity_news    (S6Port — entity-anchored news feed, PLAN-0103 W2)
  - get_filings        (S6Port — SEC EDGAR filings with clickable EDGAR citation URLs)
"""

from __future__ import annotations

import asyncio
import re
import time
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any
from uuid import UUID

import structlog

from rag_chat.domain.entities.chat import CitationMeta, RetrievedItem
from rag_chat.domain.enums import ItemType

from .base import ToolHandler, filter_kwargs_to_signature

if TYPE_CHECKING:
    from rag_chat.application.pipeline.tool_executor import EntityContext, ToolUseBlock
    from rag_chat.application.ports.brief_archive import BriefArchivePort
    from rag_chat.application.ports.upstream_clients import S6Port

log = structlog.get_logger(__name__)  # type: ignore[no-any-return]

# Maximum characters for tool result text injected into LLM context.
_TOOL_RESULT_MAX_CHARS = 4000


# Fix ③ (2026-07-04): the filing BODY text is injected per row — sec_edgar chunks
# carry no structured filer/company field (title/source_name are null), so the
# filer name lives ONLY in the chunk text.
#
# R1 depth fix (2026-07-06, docs/audits/2026-07-05-r1-sec-filings-reqa.md §Final):
# the previous single-best-chunk + 400-char snippet surfaced only the filing's
# cover / section-listing header, NEVER the numeric-table chunk — so the model
# could identify + attribute the filing but could not quote revenue/segment
# figures. The three knobs below (env-tunable, RAG_CHAT_FILING_*) control how much
# of a filing reaches the LLM: how many chunks per filing, the per-chunk body cap,
# and the per-filing total-text ceiling (token-budget bound).
def _load_filing_settings() -> tuple[int, int, int, int]:
    """Load get_filings retrieval-depth knobs from ``rag_chat.config.Settings``.

    Lazy + best-effort (mirrors ``intelligence._load_resolver_settings``): when
    Settings cannot be instantiated (minimal unit-test harness with no env) we
    fall back to hard-coded defaults that mirror the Settings field defaults so
    the tuning surface is identical across both code paths.

    Returns ``(chunks_per_filing, snippet_max_chars, result_max_chars,
    filer_header_chars)``.
    """
    try:
        from rag_chat.config import Settings  # local import to keep test imports cheap

        s = Settings()  # type: ignore[call-arg]
        return (
            int(s.filing_chunks_per_filing),
            int(s.filing_snippet_max_chars),
            int(s.filing_result_max_chars),
            int(s.filing_filer_header_chars),
        )
    except Exception:  # pragma: no cover — defensive fallback (mirrors field defaults)
        return 3, 1200, 6000, 400


# Module-level cache (computed once on import). Tests / callers override via the
# NewsHandler constructor kwargs, which fall back to these when not supplied.
(
    _FILING_CHUNKS_PER_FILING,
    _FILING_SNIPPET_MAX_CHARS,
    _FILING_RESULT_MAX_CHARS,
    _FILING_FILER_HEADER_CHARS,
) = _load_filing_settings()

# Currency / number tokens ("$391,035", "1,234.5", "27.6") — a proxy for a
# financial-statement chunk. The income-statement / segment-revenue chunk of a
# filing is dense with these; the cover / section-listing header is not. Used to
# BIAS which chunks of a filing we inject when we can only afford a few.
_NUMERIC_TOKEN_RE = re.compile(r"\$?\d[\d,]*(?:\.\d+)?")

# Recognises the common SEC form types embedded in a filing's title or body text.
# All SEC EDGAR filings are stored under the single generic source_type
# ``sec_edgar`` (the per-form type — 10-K / 10-Q / 8-K — is NOT persisted as a
# structured column anywhere downstream of content-ingestion). We therefore
# recover the human-facing form label best-effort by scanning the chunk text /
# title. Pattern mirrors nlp_pipeline.application.blocks.rare_token._RE_FILING_TYPE
# plus a few proxy / registration forms that show up in the corpus.
_RE_FILING_FORM = re.compile(
    r"\b(10-K(?:/A)?|10-Q(?:/A)?|8-K(?:/A)?|DEF\s*14A|DEFA?14A|S-1(?:/A)?|" r"20-F|6-K|424B[0-9]?|13[DFG])\b",
    re.IGNORECASE,
)

# NEW-1 refinement (2026-07-06, docs/audits/2026-07-06-r1-final-exhaustive-qa.md):
# SEC filing FILER identity lives on the cover page — the registrant name sits
# immediately BEFORE "(Exact name of registrant as specified in its charter)"
# and appears in the EDGAR-provided title. A competitor mention ("we compete with
# NVIDIA") lives deep in the body. The old body-substring filer match let an AMD
# 10-Q (41 chunks name "nvidia") corroborate an NVIDIA query and win the date
# sort. These two markers let us restrict corroboration to the AUTHORITATIVE
# cover/registrant region instead of an arbitrary body mention.
_RE_FILING_REGISTRANT = re.compile(r"exact\s+name\s+of\s+(?:the\s+)?registrant", re.IGNORECASE)
_RE_SEC_COVER = re.compile(r"securities\s+and\s+exchange\s+commission|commission\s+file\s+number", re.IGNORECASE)

# Stored source_type for every SEC EDGAR filing document (content-ingestion's
# ``sec_edgar`` Source row → content-store → document_source_metadata.source_type).
# The NLP chunk-search endpoint filters ``dsm.source_type = ANY(:source_types)``
# verbatim, so this exact literal is what selects filings (and ONLY filings).
_SEC_EDGAR_SOURCE_TYPE = "sec_edgar"


class NewsHandler(ToolHandler):
    """Handles document search and morning brief tools.

    search_documents calls S6Port (content-store / NLP pipeline).
    get_morning_brief calls BriefArchivePort (local DB read — R27 compliance).
    """

    _HANDLED_TOOLS = frozenset({"search_documents", "get_morning_brief", "get_entity_news", "get_filings"})

    def __init__(
        self,
        s6: S6Port | None = None,
        brief_archive: BriefArchivePort | None = None,
        entity_context: EntityContext | None = None,
        user_id: UUID | None = None,
        tenant_id: UUID | None = None,
        timeout: float = 5.0,
        filing_chunks_per_filing: int | None = None,
        filing_snippet_max_chars: int | None = None,
        filing_result_max_chars: int | None = None,
        filing_filer_header_chars: int | None = None,
    ) -> None:
        self._s6 = s6
        self._brief_archive = brief_archive
        self._entity_context = entity_context
        self._user_id = user_id
        self._tenant_id = tenant_id
        self._timeout = timeout
        # R1 depth fix: get_filings retrieval-depth knobs. None → the module-level
        # cache loaded from Settings (env-tunable in prod); explicit values let
        # tests pin a deterministic depth without touching the environment.
        self._filing_chunks_per_filing = (
            filing_chunks_per_filing if filing_chunks_per_filing is not None else _FILING_CHUNKS_PER_FILING
        )
        self._filing_snippet_max_chars = (
            filing_snippet_max_chars if filing_snippet_max_chars is not None else _FILING_SNIPPET_MAX_CHARS
        )
        self._filing_result_max_chars = (
            filing_result_max_chars if filing_result_max_chars is not None else _FILING_RESULT_MAX_CHARS
        )
        # NEW-1 refinement: cover/header window used by ``_filing_names_company``
        # to corroborate the FILER (not a body competitor mention).
        self._filing_filer_header_chars = (
            filing_filer_header_chars if filing_filer_header_chars is not None else _FILING_FILER_HEADER_CHARS
        )

    def can_handle(self, tool_name: str) -> bool:
        return tool_name in self._HANDLED_TOOLS

    async def execute(self, tool_name: str, args: dict[str, Any]) -> Any:
        from rag_chat.application.pipeline.tool_executor import ToolUseBlock

        _stub = ToolUseBlock(name=tool_name, input=args)

        if tool_name == "search_documents":
            # Normalize to_date → date_to: LLM occasionally uses the wrong param name.
            if "to_date" in args and "date_to" not in args:
                args = {**args, "date_to": args.pop("to_date")}
            # BP-622 systemic fix (PLAN-0103 W1): drop unknown kwargs.
            known, _ = filter_kwargs_to_signature(self._handle_search_documents, tool_name, args)
            return await self._handle_search_documents(_stub, **known)
        if tool_name == "get_morning_brief":
            filter_kwargs_to_signature(self._handle_get_morning_brief, tool_name, args)
            return await self._handle_get_morning_brief(_stub)
        if tool_name == "get_entity_news":
            # PLAN-0103 W2: entity-anchored news feed (Q1 follow-up).
            known, _ = filter_kwargs_to_signature(self._handle_get_entity_news, tool_name, args)
            return await self._handle_get_entity_news(**known)
        if tool_name == "get_filings":
            # SEC EDGAR filing retrieval — each result carries a clickable
            # citation_meta.url pointing at the EDGAR filing index page.
            # Normalize the common to_date → date_to alias (mirrors search_documents).
            if "to_date" in args and "date_to" not in args:
                args = {**args, "date_to": args.pop("to_date")}
            if "from_date" in args and "date_from" not in args:
                args = {**args, "date_from": args.pop("from_date")}
            known, _ = filter_kwargs_to_signature(self._handle_get_filings, tool_name, args)
            return await self._handle_get_filings(**known)
        raise ValueError(f"NewsHandler cannot handle tool: {tool_name}")

    # ── S6 handler (document search) ───────────────────────────────────────────

    async def _handle_search_documents(
        self,
        tool_call: ToolUseBlock,
        query: str,
        entity_tickers: list[str] | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        source_types: list[str] | None = None,
    ) -> list[RetrievedItem]:
        """Search document corpus via S6 hybrid BM25+ANN retrieval.

        entity_tickers is accepted from the LLM but not yet forwarded to S6 —
        entity resolution by ticker is PLAN-0078. A TODO comment marks the gap.

        Returns up to 20 RetrievedItem objects, each truncated to _TOOL_RESULT_MAX_CHARS.
        Returns [] if S6 port is absent or any error occurs (graceful degradation).
        """
        if self._s6 is None:
            log.warning("tool_handler_missing_port", tool="search_documents", port="s6")
            return []

        # BUG-2 FIX: ToolUseBlock from libs/tools/types.py uses `.id`; the LOCAL
        # ToolUseBlock (defined in this file) uses `.tool_use_id`.  Use getattr
        # with fallback to handle both variants without breaking existing tests.
        _call_id = getattr(tool_call, "id", None) or getattr(tool_call, "tool_use_id", "") or ""

        # Build provenance record for citation audit (PLAN-0067 §0 I-6)
        from rag_chat.application.pipeline.tool_executor import ToolCallProvenance

        _provenance = ToolCallProvenance(  # — created for audit log, consumed downstream
            tool_name="search_documents",
            tool_input=tool_call.input,
            call_id=_call_id,
        )

        # Parse optional date strings into datetime objects (S6 expects datetime | None)
        from datetime import datetime

        from rag_chat.application.ports.upstream_clients import ChunkSearchRequest

        def _parse_dt(s: str | None) -> datetime | None:
            if s is None:
                return None
            try:
                return datetime.fromisoformat(s).replace(tzinfo=UTC)
            except ValueError:
                log.warning("tool_invalid_date", tool="search_documents", value=s)
                return None

        # PLAN-0093 E-4 T-E-4-02: resolve entity_tickers → UUIDs.
        # The LLM passes entity_tickers=["AAPL","MSFT"] for multi-entity
        # comparison queries; before this fix the field was silently ignored
        # and S6 returned generic results filtered only by entity_context.
        # Each ticker is now resolved via S6.resolve_entity_by_ticker and
        # added to entity_ids alongside any scoped entity_context.
        _entity_ids: list[UUID] = []
        if self._entity_context is not None:
            _entity_ids.append(self._entity_context.entity_id)
        if entity_tickers:
            valid_tickers = [t for t in entity_tickers if isinstance(t, str) and t.strip()]
            if valid_tickers:
                # Resolve all tickers concurrently (one NLP call per ticker, fanned out).
                resolved_ids = await asyncio.gather(*[self._s6.resolve_entity_by_ticker(t) for t in valid_tickers])
                for ticker, resolved in zip(valid_tickers, resolved_ids, strict=False):
                    if resolved is not None and resolved not in _entity_ids:
                        _entity_ids.append(resolved)
                    elif resolved is None:
                        log.warning("entity_ticker_unresolved", tool="search_documents", ticker=ticker)

        request = ChunkSearchRequest(
            query_text=query,
            top_k=20,
            search_type="hybrid",
            date_from=_parse_dt(date_from),
            date_to=_parse_dt(date_to),
            source_types=source_types or [],
            entity_ids=_entity_ids or None,  # None preserves "any entity" semantics
        )

        try:
            results = await asyncio.wait_for(
                self._s6.search_chunks(request),
                timeout=self._timeout,
            )
        except Exception as e:
            log.warning("tool_failed", tool="search_documents", error=str(e))
            return []

        items: list[RetrievedItem] = []
        for result in results[:20]:
            items.append(
                RetrievedItem.create(
                    item_id=f"tool:chunk:{result.chunk_id}",
                    item_type=ItemType.chunk,
                    text=result.text[:_TOOL_RESULT_MAX_CHARS],
                    score=result.score,
                    trust_weight=0.80,
                    source_type=result.source_type,
                    published_at=result.published_at,
                    citation_meta=CitationMeta(
                        title=result.title,
                        url=result.url,
                        source_name=result.source_name,
                        published_at=result.published_at,
                        entity_name=None,
                    ),
                )
            )

        # BUG-5 FIX: do NOT emit tool_executed here — the outer execute() dispatcher
        # already emits tool_executed after the handler returns.  Double-logging this
        # event produced two identical log lines per search_documents call.
        return items

    # ── BriefArchive handler (morning brief) ───────────────────────────────────

    async def _handle_get_morning_brief(
        self,
        tool_call: ToolUseBlock,
    ) -> list[RetrievedItem]:
        """Return the user's latest morning brief from the DB archive (PLAN-0081 Wave A).

        R27: no UnitOfWork — uses BriefArchivePort.get_latest() via read adapter.
        R9: returns [] on any error or missing data.
        PRIVACY: headline and lead are passed to LLM context; sections_json may contain
        sensitive portfolio context — no special filtering needed here (already curated).
        """
        if self._brief_archive is None:
            log.warning("tool_handler_missing_port", tool="get_morning_brief", port="brief_archive")
            return []
        if self._user_id is None or self._tenant_id is None:
            log.warning("tool_no_auth_context", tool="get_morning_brief")
            return []

        # M-1: start timer before the async call so latency_ms reflects actual wait time.
        t0 = time.monotonic()
        try:
            records = await asyncio.wait_for(
                self._brief_archive.get_latest(
                    user_id=self._user_id,
                    tenant_id=self._tenant_id,
                    brief_type="morning",
                    limit=1,
                ),
                timeout=self._timeout,
            )
        except Exception as e:
            log.warning("tool_failed", tool="get_morning_brief", error=str(e))
            return []

        if not records:
            log.info("tool_no_data", tool="get_morning_brief", user_id=str(self._user_id))
            return []

        brief = records[0]
        lines = [f"**Morning Brief** — {brief.headline}"]
        if brief.lead:
            lines.append(brief.lead)
        for section in brief.sections_json:
            title = section.get("title", "")
            content = section.get("content", "")
            if title:
                lines.append(f"\n### {title}")
            if content:
                lines.append(content)
        text = "\n".join(lines)

        log.info(
            "tool_executed",
            tool="get_morning_brief",
            latency_ms=round((time.monotonic() - t0) * 1000),
            sections=len(brief.sections_json),
        )
        return [
            RetrievedItem.create(
                item_id=f"tool:brief:{brief.id}",
                item_type=ItemType.financial,
                text=text[:_TOOL_RESULT_MAX_CHARS],
                score=0.95,
                trust_weight=0.92,  # platform-curated brief — high authority
                citation_meta=CitationMeta(
                    title=brief.headline,
                    url=None,
                    source_name="morning_brief",
                    published_at=brief.generated_at,
                    entity_name=None,
                ),
            )
        ]

    # ── Entity-anchored news feed (PLAN-0103 W2 — Q1 follow-up) ────────────────

    async def _handle_get_entity_news(
        self,
        entity_id: str | None = None,
        ticker: str | None = None,
        days_back: int = 14,
        max_results: int = 10,
    ) -> list[RetrievedItem]:
        """Latest news articles mentioning a specific entity (PLAN-0103 W2).

        Why a dedicated tool (not just ``search_documents``): the chat
        catalogue previously only exposed broad BM25/ANN ``search_documents``
        for news lookups. Real-user audit (2026-05-29) showed the LLM
        defaulting to a free-text query "latest MSTR news" which then matched
        6 mostly-irrelevant chunks. An entity-anchored fetch routes through
        the same S6 endpoint the morning brief uses
        (``/api/v1/entities/{eid}/briefing-articles``) which returns
        newest-first per-entity, with relevance scoring already applied.

        Resolution order:
          1. ``entity_id`` wins when provided (UUID string).
          2. else ``ticker`` is resolved via S6 (same path search_documents
             uses for ``entity_tickers``).

        ``days_back`` filters client-side (the upstream endpoint takes only
        ``limit``, but it returns newest-first so we trim by published_at).
        """
        if self._s6 is None:
            log.warning("tool_handler_missing_port", tool="get_entity_news", port="s6")
            return []

        # Resolve to a single canonical entity UUID.
        resolved_id: UUID | None = None
        if entity_id:
            try:
                resolved_id = UUID(entity_id)
            except ValueError:
                log.warning("tool_invalid_entity_id", tool="get_entity_news", entity_id=entity_id)
        if resolved_id is None and ticker:
            try:
                resolved_id = await self._s6.resolve_entity_by_ticker(ticker)
            except Exception as exc:
                log.warning("tool_failed", tool="get_entity_news", phase="resolve_ticker", error=str(exc))
                return []
            if resolved_id is None:
                log.warning("entity_ticker_unresolved", tool="get_entity_news", ticker=ticker)
                return []
        if resolved_id is None:
            log.warning("tool_no_entity_id", tool="get_entity_news")
            return []

        # Clamp inputs to safe ranges. The upstream caps at 50 server-side
        # so we never request more than that even if the LLM asks for it.
        capped_results = max(1, min(int(max_results), 20))
        capped_days = max(1, min(int(days_back), 90))

        t0 = time.monotonic()
        try:
            # We ask the upstream for a slightly bigger window than the LLM-
            # requested ``max_results`` so the client-side date filter still
            # leaves enough rows when older articles get dropped.
            upstream_limit = min(50, capped_results * 3)
            # ``_get`` is a BaseUpstreamClient method exposed on every concrete
            # client (S6Client). It is intentionally not on the S6Port Protocol
            # because only this tool needs the raw path; the morning brief
            # calls the same private method.
            raw = await asyncio.wait_for(
                self._s6._get(  # type: ignore[attr-defined]
                    f"/api/v1/entities/{resolved_id}/briefing-articles",
                    params={"limit": upstream_limit},
                ),
                timeout=self._timeout,
            )
        except Exception as exc:
            log.warning("tool_failed", tool="get_entity_news", error=str(exc))
            return []

        raw_articles = raw.get("articles", []) if isinstance(raw, dict) else []
        if not raw_articles:
            log.info("tool_no_data", tool="get_entity_news", entity_id=str(resolved_id))
            return []

        cutoff = datetime.now(tz=UTC) - timedelta(days=capped_days)
        # BP-670: bind the requested entity onto every item's citation_meta.
        # The BP-605 grounding gate and the entity-name validator both read
        # ``citation_meta.entity_name``; leaving it None forced them onto
        # text-scan fallbacks (article titles frequently lead with OTHER
        # companies — "AI Boom Sends TSMC Sales Soaring..." is a valid
        # Apple-tagged article whose title never says Apple).
        _entity_label = ticker.strip().upper() if isinstance(ticker, str) and ticker.strip() else None
        items: list[RetrievedItem] = []
        for a in raw_articles:
            if not isinstance(a, dict):
                continue
            # Parse published_at; skip rows where we cannot tell the date —
            # the days_back filter is a positive contract, not best-effort.
            published_at_raw = a.get("published_at")
            published_at: datetime | None = None
            if published_at_raw:
                try:
                    published_at = datetime.fromisoformat(str(published_at_raw).replace("Z", "+00:00"))
                    if published_at.tzinfo is None:
                        published_at = published_at.replace(tzinfo=UTC)
                except (ValueError, TypeError):
                    published_at = None
            if published_at is None or published_at < cutoff:
                continue

            article_id = a.get("article_id") or a.get("id") or a.get("doc_id") or ""
            title = str(a.get("title") or "(untitled)")
            source_name = a.get("source_name") or "news"
            # 2026-07-15 prod-review (empty source-links): the /briefing-articles
            # feed carries the article link under ``url`` but coerces a missing
            # value to "" (documented in output_processor._clean_optional_str);
            # some upstreams also key it as ``link`` / ``article_url`` /
            # ``canonical_url``. Read the first NON-EMPTY of those aliases so a
            # real source link is never dropped just because it arrived under a
            # different key (an "" here still normalises to None downstream, which
            # is correct — we only recover a link that genuinely exists).
            url = a.get("url") or a.get("link") or a.get("article_url") or a.get("canonical_url") or None
            display_score = float(a.get("display_relevance_score") or 0.0)
            # The briefing-articles endpoint does not return a snippet; the
            # title carries most of the recall signal for chat answers, and
            # adding the source/date gives the LLM enough surface to cite.
            text_lines = [title]
            if published_at:
                text_lines.append(f"  Source: {source_name} | Published: {published_at.isoformat()}")
            if url:
                text_lines.append(f"  URL: {url}")
            text = "\n".join(text_lines)

            items.append(
                RetrievedItem.create(
                    item_id=f"tool:entity_news:{article_id}",
                    item_type=ItemType.chunk,
                    # BP-670: stamp the REQUESTED entity UUID on every item.
                    # The briefing-articles endpoint is entity-anchored by
                    # construction; when the LLM calls this tool with
                    # entity_id=<question entity> the BP-605 gate matches
                    # item.entity_id against the question id set directly —
                    # article titles often never name the company verbatim
                    # ("Apple's AI Push..." does not contain "apple inc").
                    entity_id=resolved_id,
                    text=text[:_TOOL_RESULT_MAX_CHARS],
                    # Use display_score directly so the orchestrator's
                    # downstream ranking sees the same number the brief uses.
                    # Floor at 0.5 so a 0.0 score (no relevance signal) still
                    # ranks above a generic search_documents hit but below a
                    # high-signal one.
                    score=max(0.5, display_score),
                    trust_weight=0.85,
                    source_type=a.get("source_type") or "news",
                    published_at=published_at,
                    citation_meta=CitationMeta(
                        title=title,
                        url=url,
                        source_name=source_name,
                        published_at=published_at,
                        entity_name=_entity_label,
                    ),
                )
            )
            if len(items) >= capped_results:
                break

        log.info(
            "tool_executed",
            tool="get_entity_news",
            latency_ms=round((time.monotonic() - t0) * 1000),
            entity_id=str(resolved_id),
            items_returned=len(items),
        )
        return items

    # ── SEC EDGAR filings (clickable EDGAR citation URLs) ──────────────────────

    @staticmethod
    def _numeric_density(text: str | None) -> int:
        """Count currency/number tokens in a chunk — proxy for a financial table.

        R1 depth fix: when we can inject only a few chunks per filing we bias
        toward the numeric-dense ones. The income-statement / segment-revenue
        chunk is packed with "$391,035"-style tokens; the cover / section-listing
        header (which the generic filings query ranks FIRST) is not — so numeric
        density is what surfaces the revenue figures the model needs to quote.
        """
        if not text:
            return 0
        return len(_NUMERIC_TOKEN_RE.findall(text))

    @staticmethod
    def _detect_form_type(*texts: str | None) -> str | None:
        """Best-effort recover the SEC form label (10-K, 8-K, …) from text.

        All filings share the generic ``sec_edgar`` source_type — the per-form
        type is never persisted structurally — so we scan the title/body. The
        FIRST matched token wins (titles lead with the form type when present).
        Returns the normalised upper-case label (whitespace collapsed) or None.
        """
        for text in texts:
            if not text:
                continue
            m = _RE_FILING_FORM.search(text)
            if m:
                # Collapse internal whitespace ("DEF  14A" → "DEF 14A") + upper-case.
                return re.sub(r"\s+", " ", m.group(1)).upper()
        return None

    @staticmethod
    def _region_names_company(
        region: str | None,
        company_name: str | None,
        ticker: str | None,
    ) -> bool:
        """True when ``region`` names the queried company (full name / lead token / ticker).

        The match is deliberately restricted to a caller-chosen AUTHORITATIVE
        region (an EDGAR title, a registrant-charter window, or a cover/header
        slice) — never the whole body — so a competitor mention cannot corroborate
        the filer. Matches (case-insensitive):
          * the resolved legal company name as a substring ("apple inc."), OR
          * its distinctive leading token as a whole word ("nvidia" ≥4 chars —
            word-boundary, so "nvidia" does not match "nvidias"), OR
          * the ticker as a standalone token ("nvda").
        """
        if not region:
            return False
        hay = region.lower()
        if not hay.strip():
            return False
        if company_name:
            cn = company_name.strip().lower()
            if cn and cn in hay:
                return True
            # Distinctive leading token (≥4 chars avoids generic short words),
            # anchored on word boundaries so it is a NAME, not a fragment.
            lead = cn.split()[0] if cn.split() else ""
            if len(lead) >= 4 and re.search(rf"\b{re.escape(lead)}\b", hay):
                return True
        if ticker:
            tk = ticker.strip().lower()
            if tk and re.search(rf"\b{re.escape(tk)}\b", hay):
                return True
        return False

    @staticmethod
    def _filing_names_company(
        doc_chunks: list[Any],
        primary_title: str | None,
        company_name: str | None,
        ticker: str | None,
        header_chars: int,
    ) -> bool:
        """True only when the QUERIED company is the actual FILER of this filing.

        Fix ③ (2026-07-04) first added a filer check, but it matched the queried
        name ANYWHERE in the chunk body. NEW-1 refinement (2026-07-06): that is a
        false-positive machine — 41 AMD chunks mention "nvidia" as a competitor,
        so an AMD 10-Q corroborated an NVIDIA query and, being newer + numeric-
        dense, won the date sort (wrong-company citation). We now corroborate the
        filer ONLY via an AUTHORITATIVE region where the FILER identity lives —
        never an arbitrary body mention:

          1. the EDGAR-provided title (``primary_title``) — when EDGAR titles a
             filing it is with the filer's own name;
          2. a registrant-charter declaration — the legal filer name sits just
             BEFORE "(Exact name of registrant as specified in its charter)";
          3. a cover/header slice — the first ``header_chars`` of a chunk that
             reads like a filing cover (a form-type token or SEC cover boilerplate
             present in that slice), where the registrant name leads the page.

        A competitor mention lives in a mid-body chunk with no cover markers and
        past the header window, so it never corroborates. When none of the three
        authoritative regions name the company we return False — the caller then
        treats the filing as NOT this company's (honest miss over wrong company).
        """
        if not (company_name or ticker):
            return False
        # 1. EDGAR-provided title — authoritative filer identity when present.
        if NewsHandler._region_names_company(primary_title, company_name, ticker):
            return True
        for c in doc_chunks:
            text = getattr(c, "text", None) or ""
            if not text:
                continue
            low = text.lower()
            # 2. Registrant-charter declaration: check the window ENDING at the
            #    "(exact name of registrant …)" phrase (the legal name precedes it).
            for m in _RE_FILING_REGISTRANT.finditer(low):
                start = max(0, m.start() - header_chars)
                if NewsHandler._region_names_company(text[start : m.start()], company_name, ticker):
                    return True
            # 3. Cover/header slice: only counts when the slice reads like a filing
            #    cover (a form-type token or SEC cover boilerplate) — a GPU-
            #    competition body chunk has neither, so its "nvidia" cannot match.
            head = text[:header_chars]
            if (_RE_FILING_FORM.search(head) or _RE_SEC_COVER.search(head)) and NewsHandler._region_names_company(
                head, company_name, ticker
            ):
                return True
        return False

    async def _resolve_company_name_for_filings(
        self,
        ticker: str | None,
        entity_id: str | None,
    ) -> str | None:
        """Best-effort resolve a ticker/entity to its human company NAME.

        BUG-3: SEC filings render the full company name ("NVIDIA Corporation"),
        so the name is the strongest retrieval signal when we anchor the company
        into the chunk-search ``query_text`` (there is no reliable entity-mention
        link on sec_edgar chunks to filter by). Resolution order:

          1. the active EntityContext scope name (the page the user is on), when
             the caller did not pass a DIFFERENT explicit ticker;
          2. else S6 mention resolution of the ticker → canonical_name.

        Always degrades to ``None`` (the ticker itself is still added to the query
        text by the caller) — never raises, never blocks retrieval.
        """
        # 1. Scoped entity name wins UNLESS the LLM passed a specific ticker that
        #    differs from the scope (trust the explicit request over the page).
        ctx = self._entity_context
        if ctx is not None and ctx.name:
            ctx_ticker = (ctx.ticker or "").strip().upper()
            req_ticker = (ticker or "").strip().upper()
            if not req_ticker or req_ticker == ctx_ticker:
                return str(ctx.name)
        # 2. Resolve the ticker to a canonical company name via S6 mentions.
        if self._s6 is not None and ticker and ticker.strip():
            try:
                resolved = await self._s6.resolve_entities(ticker.strip())
            except Exception as exc:  # R9: never block retrieval on a resolve miss
                log.info("filings_name_resolve_failed", ticker=ticker, error=str(exc))
                resolved = []
            if not isinstance(resolved, list):  # defensive: tolerate odd upstream/mocks
                resolved = []
            for r in resolved:
                name = getattr(r, "canonical_name", None)
                if isinstance(name, str) and name.strip():
                    return name.strip()
        return None

    async def _handle_get_filings(
        self,
        entity_id: str | None = None,
        ticker: str | None = None,
        form_type: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        max_results: int = 10,
    ) -> list[RetrievedItem]:
        """Retrieve SEC EDGAR filings for an entity, each with a clickable EDGAR URL.

        Why a dedicated tool (not just ``search_documents``): ``search_documents``
        advertises a ``source_types`` filter to the LLM but the value taxonomy it
        suggests (``sec_filing``) does NOT match the stored ``sec_edgar`` literal,
        so filing-only retrieval was effectively unreachable. This tool pins the
        correct stored source_type, groups the many chunk hits into ONE result
        per filing — injecting the top-N chunks per filing biased toward the
        numeric-dense financial-statement chunk so the model can quote real
        revenue/segment figures (R1 depth fix) — and stamps ``citation_meta.url``
        with the canonical EDGAR index URL so the answer can link straight to the
        primary source on sec.gov.

        Read path (R9 — rag-chat → S6 direct REST, the existing tool pattern):
        ``S6Port.search_chunks`` with ``source_types=['sec_edgar']`` filters
        ``document_source_metadata.source_type`` verbatim. The returned
        ``EnrichedChunkResult`` already carries ``url`` (EDGAR), ``published_at``
        (filed date), ``title`` and ``source_name``.

        BUG-3 (2026-07-01): the company is anchored via the QUERY TEXT (resolved
        company name + ticker), NOT a hard ``entity_ids`` filter — sec_edgar
        chunks are not entity-mention-linked to canonical ids, so an id filter
        returned 0 filings. The filter-first exact-KNN over the sec_edgar bucket
        ranks the anchored company's filings first; we still stamp the resolved
        ``entity_id``/ticker on each item for citation + grounding.

        Company anchoring / label resolution:
          1. ``ticker`` → resolved company NAME (S6 mentions) + the ticker itself
             are added to the query text; ``ticker`` also becomes the item label.
          2. the active EntityContext scope name is used when no explicit ticker.
          3. ``entity_id`` (UUID) still stamps the item for grounding when given.
          4. with none of the above → recent filings across the corpus.

        ``form_type`` (e.g. "10-K") is a BEST-EFFORT filter: the type is not a
        structured field, so we (a) bias the relevance query toward it and
        (b) prefer results whose detected form label matches. If NO result
        matches the requested form we fall back to returning all filings (logged)
        rather than an empty hand — the EDGAR link still lets the user verify.
        """
        if self._s6 is None:
            log.warning("tool_handler_missing_port", tool="get_filings", port="s6")
            return []

        # Resolve to a single canonical entity UUID (optional — None = any entity).
        resolved_id: UUID | None = None
        if entity_id:
            try:
                resolved_id = UUID(entity_id)
            except ValueError:
                log.warning("tool_invalid_entity_id", tool="get_filings", entity_id=entity_id)
        if resolved_id is None and ticker:
            try:
                resolved_id = await self._s6.resolve_entity_by_ticker(ticker)
            except Exception as exc:
                log.warning("tool_failed", tool="get_filings", phase="resolve_ticker", error=str(exc))
                return []
            if resolved_id is None:
                log.warning("entity_ticker_unresolved", tool="get_filings", ticker=ticker)
        if resolved_id is None and self._entity_context is not None:
            # Fall back to the scoped entity (e.g. the page the user is viewing).
            resolved_id = self._entity_context.entity_id

        # Clamp the requested result count to a safe band.
        capped_results = max(1, min(int(max_results), 20))

        # Parse optional date bounds (the chunk search accepts datetime | None).
        def _parse_dt(s: str | None) -> datetime | None:
            if s is None:
                return None
            try:
                return datetime.fromisoformat(str(s).replace("Z", "+00:00")).replace(tzinfo=UTC)
            except ValueError:
                log.warning("tool_invalid_date", tool="get_filings", value=s)
                return None

        # BUG-3 (2026-07-01): DO NOT hard-filter by entity_ids. SEC EDGAR chunks
        # are NOT entity-mention-linked to canonical entity ids — e.g. NVDA's id
        # has 5914 mentions, ALL in NEWS chunks, ZERO in sec_edgar chunks. So a
        # hard ``entity_ids=[nvda_id]`` filter returned 0 filings even though
        # sec_edgar retrieval now works (25 hybrid results without the filter).
        #
        # Instead we anchor the COMPANY into the QUERY TEXT (name + ticker) and let
        # the filter-first exact-KNN over the sec_edgar bucket rank that company's
        # filings first. Filings render the full company name ("NVIDIA Corporation"),
        # so the name is the strongest retrieval signal — we resolve it best-effort.
        company_name = await self._resolve_company_name_for_filings(ticker, entity_id)
        ticker_upper = ticker.strip().upper() if isinstance(ticker, str) and ticker.strip() else None
        normalised_form = re.sub(r"\s+", " ", form_type).strip().upper() if form_type else None
        # Compose: "<Company> <TICKER> <FORM|report terms>" — drop the None parts.
        query_text = " ".join(
            part
            for part in (
                company_name,
                ticker_upper,
                normalised_form or "annual quarterly report SEC filing",
            )
            if part
        )

        from rag_chat.application.ports.upstream_clients import ChunkSearchRequest

        # Over-fetch: chunk search returns multiple chunks per filing, so request
        # a larger window and group by doc_id down to ``capped_results`` filings.
        # source_types pins the sec_edgar bucket; the company anchoring lives in
        # query_text (NO entity_ids filter — see BUG-3 note above).
        #
        # R1 depth fix: we now surface up to ``_filing_chunks_per_filing`` chunks
        # PER filing (to reach the numeric-table chunk, not just the header), so
        # the window must hold enough chunks even when the LLM asks for only a
        # couple of filings. Floor the over-fetch at chunks-per-filing x 6 so a
        # single-filing query still pulls that filing's numeric chunk. Bounded at
        # 50 (unchanged upper bound → no new S6-latency regression vs. before).
        _over_fetch = max(capped_results * 5, self._filing_chunks_per_filing * 6)
        request = ChunkSearchRequest(
            query_text=query_text,
            top_k=min(50, _over_fetch),
            search_type="hybrid",
            date_from=_parse_dt(date_from),
            date_to=_parse_dt(date_to),
            source_types=[_SEC_EDGAR_SOURCE_TYPE],
            entity_ids=None,
        )

        t0 = time.monotonic()
        try:
            results = await asyncio.wait_for(self._s6.search_chunks(request), timeout=self._timeout)
        except Exception as exc:
            log.warning("tool_failed", tool="get_filings", error=str(exc))
            return []

        if not results:
            log.info("tool_no_data", tool="get_filings", entity_id=str(resolved_id) if resolved_id else None)
            return []

        # Group the flat chunk hits into ONE entry per filing (doc_id). Results
        # are already score-ordered by S6, so the FIRST chunk seen for a doc is
        # its best-ranked chunk (drives the citation title / form / URL). Python
        # dicts preserve insertion order, so ``grouped`` is best-first per doc and
        # docs appear in the order their best chunk ranked.
        grouped: dict[str, list[Any]] = {}
        for result in results:
            doc_id = str(result.doc_id) if result.doc_id else result.chunk_id
            grouped.setdefault(doc_id, []).append(result)

        # NEW-1 (2026-07-06, docs/audits/2026-07-06-r1-final-exhaustive-qa.md):
        # each retained filing is scored on TWO independent axes so we can rank
        # the RIGHT company's filing first without regressing form-type or
        # newest-first ordering:
        #   * ``names_company`` — does this filing actually name the QUERIED
        #     company? (the core partition — see the hard-filter below).
        #   * ``form_ok``       — does its detected form match a requested one?
        # We collect ``(names_company, form_ok, item)`` and partition AFTER the
        # loop, then date-sort WITHIN the retained set. The old code sorted ALL
        # grouped filings by date regardless of filer, so a newer numeric-dense
        # Meta/AMD/Intel filing outranked the target's real 10-Q (wrong-company
        # citation, 4/8 QA runs).
        scored: list[tuple[bool, bool, RetrievedItem]] = []

        # Entity LABEL stamped onto matching rows (drives citation entity_name +
        # the numeric/entity grounding entity_tag). Prefer the explicit ticker;
        # fall back to the scoped-entity ticker so a page-scoped filings query
        # (entity_id / EntityContext, no explicit ticker) still tags its rows —
        # otherwise the filing's tool values carry an EMPTY entity_tag and the
        # numeric-grounding validator cannot scope the answer's figures to them
        # (the over-fire / dropped-citation class in NEW-3 / fix ③).
        _entity_label = ticker_upper
        if _entity_label is None and self._entity_context is not None:
            ctx_ticker = (self._entity_context.ticker or "").strip().upper()
            _entity_label = ctx_ticker or None

        # Does this query TARGET a specific company? Only then do we hard-filter
        # to its filings. company_name/ticker are the inputs ``_filing_names_company``
        # matches on; without either we cannot corroborate a filer, so we must
        # NOT filter (the generic "recent filings across the corpus" path).
        company_targeted = bool(company_name or ticker_upper)

        for doc_id, doc_chunks in grouped.items():
            primary = doc_chunks[0]  # best-ranked chunk — citation title/form/URL/date

            # R1 depth fix: select up to N chunks to inject. Keep the primary
            # (relevance-best, usually the cover/section-listing header) FIRST for
            # context, then add the most NUMERIC-DENSE of the remaining chunks —
            # the income-statement / segment-revenue tables live in a different
            # chunk that ranks below the header for the generic filings query, so
            # a plain top-N-by-relevance would still miss them. Sorting the rest
            # by numeric density pulls the financial-table chunk into the window.
            rest_by_numbers = sorted(
                doc_chunks[1:],
                key=lambda c: self._numeric_density(c.text),
                reverse=True,
            )
            selected = [primary, *rest_by_numbers][: self._filing_chunks_per_filing]

            detected_form = self._detect_form_type(primary.title, primary.text)
            # Compose a human title: "10-K filing — 2026-01-31" when we know both.
            date_label = primary.published_at.date().isoformat() if primary.published_at else "date unknown"

            # Fix ③ (2026-07-04) + NEW-1 refinement (2026-07-06): does THIS filing
            # actually name the queried company as its FILER? We check ALL of the
            # filing's retrieved chunks (not just the injected ones) but only in
            # authoritative regions (title / registrant-charter / cover header) —
            # a competitor mention deep in the body must NOT corroborate the filer.
            names_company = self._filing_names_company(
                doc_chunks, primary.title, company_name, ticker_upper, self._filing_filer_header_chars
            )

            # Fold the filer/company identity into the title when we can confirm
            # it — "10-K filing — NVIDIA Corporation (2026-01-31)" — so the LLM
            # (and the rendered citation) knows WHOSE filing this is. When the
            # row does NOT corroborate the queried company we deliberately keep
            # the neutral form+date title (the body snippets below still carry
            # the real filer), rather than falsely attribute it to the query.
            if detected_form and names_company and company_name:
                title = f"{detected_form} filing — {company_name} ({date_label})"
            elif detected_form:
                title = f"{detected_form} filing — {date_label}"
            elif primary.title:
                title = primary.title
            else:
                title = f"SEC filing — {date_label}"

            # Text injected into the LLM context: title + form + date + link, AND
            # the body of MULTIPLE chunks — the header chunk carries the filer name
            # (Fix ③) while the numeric-dense chunk(s) carry the revenue/segment
            # tables the model must quote (R1 depth fix). Each chunk snippet is
            # whitespace-collapsed and per-chunk capped; the whole row is then
            # bounded by ``_filing_result_max_chars`` to keep the prompt cost sane.
            text_lines = [title]
            text_lines.append(f"  Source: SEC EDGAR | Filed: {date_label}")
            for c in selected:
                snippet = re.sub(r"\s+", " ", c.text).strip() if c.text else ""
                if snippet:
                    text_lines.append(f"  Filer/content: {snippet[: self._filing_snippet_max_chars]}")
            if primary.url:
                text_lines.append(f"  Filing: {primary.url}")

            # Fix ③: only stamp the queried ticker as this row's entity_name when
            # the filing actually names the company — otherwise leave it UNSET so a
            # non-matching filer (e.g. an ADIAL 8-K under an Apple query) is not
            # mislabelled as the query ticker (which would also poison the
            # entity-name grounding allow-list downstream).
            row_entity_name = _entity_label if names_company else None
            item = RetrievedItem.create(
                item_id=f"tool:filing:{doc_id}",
                item_type=ItemType.chunk,
                entity_id=resolved_id,
                text="\n".join(text_lines)[: self._filing_result_max_chars],
                score=max(0.5, float(primary.score)),
                # SEC filings are the highest-authority primary source (mirrors the
                # sec_10k/10q → 0.95 trust weights in the TrustScorer invariant).
                trust_weight=0.95,
                source_type=_SEC_EDGAR_SOURCE_TYPE,
                published_at=primary.published_at,
                citation_meta=CitationMeta(
                    title=title,
                    url=primary.url,  # canonical EDGAR filing index URL
                    source_name="sec_edgar",
                    published_at=primary.published_at,
                    entity_name=row_entity_name,
                ),
            )
            # Record both axes; the partition happens after the loop so the
            # company filter (NEW-1) can dominate the form filter.
            form_ok = normalised_form is None or (detected_form is not None and detected_form == normalised_form)
            scored.append((names_company, form_ok, item))

        # ── NEW-1 company partition (the core fix) ────────────────────────────
        # When the query targets a specific company:
        #   * if ≥1 retrieved filing is FILER-corroborated (title/registrant/cover),
        #     keep ONLY those — a newer but unrelated filer (Meta/AMD/Intel) must
        #     never outrank the target's real 10-Q;
        #   * if NONE corroborate the filer, return an HONEST MISS (empty) rather
        #     than a different company's filing. NEW-1 refinement (2026-07-06): the
        #     old graceful fallback returned the wrong-company filing unlabelled,
        #     but the model still cited it (NVIDIA→AMD). A wrong-company answer is
        #     worse than "no filings found for X", so we drop everything and let
        #     the caller/model report the miss.
        if company_targeted:
            _matched: list[tuple[bool, bool, RetrievedItem]] = [(nc, fo, it) for nc, fo, it in scored if nc]
            if _matched:
                _dropped = len(scored) - len(_matched)
                if _dropped:
                    log.info(
                        "filings_company_filter_applied",
                        tool="get_filings",
                        kept=len(_matched),
                        dropped=_dropped,
                    )
                scored = _matched
            elif company_name:
                # We had a resolved company NAME to corroborate against and NOT ONE
                # retrieved filing named it as its filer (only body/competitor
                # mentions). Return an HONEST MISS rather than a wrong-company
                # filing. (Live queries always resolve a name, so this is the path
                # that kills NVIDIA→AMD.) A bare ticker with no resolved name is a
                # weaker signal — we keep the graceful fallback below for it.
                log.info(
                    "filings_no_corroborated_filer",
                    tool="get_filings",
                    company=company_name,
                    ticker=ticker_upper,
                    candidates=len(scored),
                )
                scored = []

        # ── Form partition (existing behaviour, now over the company-filtered set) ─
        form_matched: list[tuple[bool, bool, RetrievedItem]] = [(nc, fo, it) for nc, fo, it in scored if fo]
        if normalised_form is not None:
            if form_matched:
                scored = form_matched
            else:
                log.info("filings_form_filter_fallback", tool="get_filings", form_type=normalised_form)

        # Newest filing first WITHIN the retained (company/form-filtered) set —
        # chronological ordering is what users expect for a filings list (chunk
        # search ordered by relevance, not date).
        scored.sort(
            key=lambda t: t[2].published_at or datetime.min.replace(tzinfo=UTC),
            reverse=True,
        )
        items = [it for _nc, _fo, it in scored][:capped_results]

        log.info(
            "tool_executed",
            tool="get_filings",
            latency_ms=round((time.monotonic() - t0) * 1000),
            entity_id=str(resolved_id) if resolved_id else None,
            form_type=normalised_form,
            items_returned=len(items),
        )
        return items
