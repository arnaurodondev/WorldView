"""HTML/plain-text email template renderer for the weekly portfolio risk digest.

Renders 4 sections (PRD-0016 §7):
  1. Risk Overview       — top risk signals from briefing risk_summary
  2. Portfolio Positions — holdings with concentration + YTD performance
  3. Recent News         — citations from briefing response
  4. Market Fundamentals — key metrics from risk_summary

Design notes:
  - Pure f-string renderer; no external dependencies (no Jinja2).
  - All user-supplied text is XML-escaped to prevent XSS injection.
  - Every section degrades gracefully when data is absent.
  - Returns ``(html_body, text_body)`` tuple for dual-format delivery.
"""

from __future__ import annotations

import html as _html_module
from typing import Any

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def render_digest_email(
    narrative: str,
    risk_summary: dict[str, Any] | None = None,
    positions: list[dict[str, Any]] | None = None,
    citations: list[dict[str, Any]] | None = None,
    fundamentals: list[dict[str, Any]] | None = None,
) -> tuple[str, str]:
    """Render the weekly digest email as (html_body, text_body).

    Args:
    ----
        narrative: AI-generated narrative text from S8.
        risk_summary: Dict with ``top_risk_signals`` list (from S8 briefing).
        positions: List of portfolio position dicts, each with optional keys
            ``ticker``, ``name``, ``weight_pct``, ``ytd_pct``.
        citations: List of citation dicts from S8, each with ``title`` and
            optional ``source``, ``url``.
        fundamentals: List of fundamental metric dicts, each with ``ticker``
            and optional ``pe_ratio``, ``market_cap``, ``revenue_growth``.

    Returns:
    -------
        Tuple of ``(html_body, text_body)``.

    """
    html_body = _render_html(narrative, risk_summary or {}, positions or [], citations or [], fundamentals or [])
    text_body = _render_text(narrative, risk_summary or {}, positions or [], citations or [], fundamentals or [])
    return html_body, text_body


# ---------------------------------------------------------------------------
# HTML renderer
# ---------------------------------------------------------------------------

_HTML_STYLES = """
  body { font-family: Arial, sans-serif; color: #222; max-width: 640px; margin: 0 auto; padding: 20px; }
  h1 { color: #1a3c6e; border-bottom: 2px solid #1a3c6e; padding-bottom: 8px; }
  h2 { color: #2b5cab; margin-top: 28px; }
  table { border-collapse: collapse; width: 100%; margin-top: 8px; }
  th, td { border: 1px solid #ccc; padding: 6px 10px; text-align: left; }
  th { background: #f0f4f8; font-weight: bold; }
  ul { padding-left: 20px; }
  li { margin: 4px 0; }
  .footer { margin-top: 40px; font-size: 12px; color: #888; border-top: 1px solid #ccc; padding-top: 12px; }
  .narrative { background: #f8f9fa; border-left: 4px solid #2b5cab; padding: 12px 16px; margin: 16px 0; }
""".strip()


def _esc(text: Any) -> str:
    """XML-escape arbitrary text to prevent XSS."""
    return _html_module.escape(str(text), quote=True)


def _render_html(
    narrative: str,
    risk_summary: dict[str, Any],
    positions: list[dict[str, Any]],
    citations: list[dict[str, Any]],
    fundamentals: list[dict[str, Any]],
) -> str:
    sections: list[str] = []

    # ── Narrative (from S8) ─────────────────────────────────────────────────
    if narrative:
        sections.append(f'<div class="narrative"><p>{_esc(narrative)}</p></div>')

    # ── Section 1: Risk Overview ─────────────────────────────────────────────
    risk_signals: list[Any] = risk_summary.get("top_risk_signals", [])
    section1_body: str
    if risk_signals:
        items = "".join(f"<li>{_esc(s)}</li>" for s in risk_signals)
        section1_body = f"<ul>{items}</ul>"
    else:
        section1_body = "<p>No risk signals detected this week.</p>"
    sections.append(f"<h2>Risk Overview</h2>\n{section1_body}")

    # ── Section 2: Portfolio Positions ───────────────────────────────────────
    if positions:
        rows = ""
        for pos in positions:
            ticker = _esc(pos.get("ticker", "—"))
            name = _esc(pos.get("name", "—"))
            weight = f"{pos['weight_pct']:.1f}%" if "weight_pct" in pos else "—"
            ytd = f"{pos['ytd_pct']:+.1f}%" if "ytd_pct" in pos else "—"
            rows += f"<tr><td>{ticker}</td><td>{name}</td><td>{weight}</td><td>{ytd}</td></tr>"
        section2_body = f"<table><tr><th>Ticker</th><th>Name</th><th>Weight</th><th>YTD</th></tr>{rows}</table>"
    else:
        section2_body = "<p>No position data available.</p>"
    sections.append(f"<h2>Portfolio Positions</h2>\n{section2_body}")

    # ── Section 3: Recent News ───────────────────────────────────────────────
    if citations:
        items = ""
        for c in citations:
            title = _esc(c.get("title", "Untitled"))
            source = _esc(c.get("source", ""))
            suffix = f" <em>({source})</em>" if source else ""
            items += f"<li>{title}{suffix}</li>"
        section3_body = f"<ul>{items}</ul>"
    else:
        section3_body = "<p>No recent news citations available.</p>"
    sections.append(f"<h2>Recent News</h2>\n{section3_body}")

    # ── Section 4: Market Fundamentals ──────────────────────────────────────
    if fundamentals:
        rows = ""
        for f in fundamentals:
            ticker = _esc(f.get("ticker", "—"))
            pe = _esc(f.get("pe_ratio", "—"))
            mcap = _esc(f.get("market_cap", "—"))
            rev_growth = _esc(f.get("revenue_growth", "—"))
            rows += f"<tr><td>{ticker}</td><td>{pe}</td><td>{mcap}</td><td>{rev_growth}</td></tr>"
        section4_body = f"<table><tr><th>Ticker</th><th>P/E</th><th>Mkt Cap</th><th>Rev. Growth</th></tr>{rows}</table>"
    else:
        section4_body = "<p>No fundamental data available.</p>"
    sections.append(f"<h2>Market Fundamentals</h2>\n{section4_body}")

    body_content = "\n".join(sections)
    return (
        f"<!DOCTYPE html><html><head>"
        f'<meta charset="utf-8">'
        f'<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<style>{_HTML_STYLES}</style>"
        f"</head><body>"
        f"<h1>Your Weekly Portfolio Risk Digest</h1>"
        f"{body_content}"
        f'<div class="footer">You are receiving this because you enabled weekly digests. '
        f"To manage preferences, visit the app settings.</div>"
        f"</body></html>"
    )


# ---------------------------------------------------------------------------
# Plain-text renderer
# ---------------------------------------------------------------------------


def _sanitize(text: str) -> str:
    """Strip CRLF from user-supplied text to prevent header injection (M-03)."""
    return text.replace("\r\n", " ").replace("\r", " ").replace("\n", " ")


def _render_text(
    narrative: str,
    risk_summary: dict[str, Any],
    positions: list[dict[str, Any]],
    citations: list[dict[str, Any]],
    fundamentals: list[dict[str, Any]],
) -> str:
    lines: list[str] = ["YOUR WEEKLY PORTFOLIO RISK DIGEST", "=" * 36, ""]

    if narrative:
        lines += [_sanitize(narrative), ""]

    # Section 1
    lines.append("RISK OVERVIEW")
    lines.append("-" * 13)
    risk_signals = risk_summary.get("top_risk_signals", [])
    if risk_signals:
        for s in risk_signals:
            lines.append(f"• {_sanitize(str(s))}")
    else:
        lines.append("No risk signals detected this week.")
    lines.append("")

    # Section 2
    lines.append("PORTFOLIO POSITIONS")
    lines.append("-" * 19)
    if positions:
        for pos in positions:
            ticker = pos.get("ticker", "—")
            name = pos.get("name", "")
            weight = f"{pos['weight_pct']:.1f}%" if "weight_pct" in pos else ""
            ytd = f"YTD {pos['ytd_pct']:+.1f}%" if "ytd_pct" in pos else ""
            parts = [p for p in [ticker, name, weight, ytd] if p]
            lines.append("  " + " | ".join(parts))
    else:
        lines.append("No position data available.")
    lines.append("")

    # Section 3
    lines.append("RECENT NEWS")
    lines.append("-" * 11)
    if citations:
        for c in citations:
            title = _sanitize(c.get("title", "Untitled"))
            source = _sanitize(c.get("source", ""))
            suffix = f" ({source})" if source else ""
            lines.append(f"• {title}{suffix}")
    else:
        lines.append("No recent news citations available.")
    lines.append("")

    # Section 4
    lines.append("MARKET FUNDAMENTALS")
    lines.append("-" * 19)
    if fundamentals:
        for f in fundamentals:
            ticker = f.get("ticker", "—")
            pe = f.get("pe_ratio", "—")
            mcap = f.get("market_cap", "—")
            rev = f.get("revenue_growth", "—")
            lines.append(f"  {ticker}: P/E={pe} | Mkt Cap={mcap} | Rev Growth={rev}")
    else:
        lines.append("No fundamental data available.")
    lines.append("")

    lines += [
        "---",
        "You are receiving this because you enabled weekly digests.",
        "To manage preferences, visit the app settings.",
    ]
    return "\n".join(lines)
