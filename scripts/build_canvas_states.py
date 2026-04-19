# ruff: noqa: RUF001, RUF002
#!/usr/bin/env python3
"""
build_canvas_states.py
======================
Rebuilds two canvas states in worldview-mvp_v2.pen:

  Pass 1 — State B "Fundamentals" (frame lJVwH inside VEVln)
  Pass 2 — State C "Intelligence / Graph" (frame vlN6E inside M1GXQ)

The script replaces ONLY the children of the two target Body frames.
All other frames (Header, AIBrief, TabBar on State B; Header, TabBar on
State C) are left untouched.

Usage:
    python3 scripts/build_canvas_states.py
"""

from __future__ import annotations

import json
import math
import string
from pathlib import Path

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

PEN_PATH = Path(__file__).parent.parent / "apps/frontend/designs/worldview-mvp_v2.pen"

# ID generator — 5-char alphanumeric strings not already present in the file
_CHARSET = string.ascii_letters + string.digits
_USED_IDS: set[str] = set()
_COUNTER = 0


def _load_existing_ids(data: dict) -> None:
    """Populate _USED_IDS with every id present in the file."""
    stack = [data]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            if "id" in node:
                _USED_IDS.add(node["id"])
            stack.extend(node.values())
        elif isinstance(node, list):
            stack.extend(node)


def new_id() -> str:
    """Return a unique 5-char alphanumeric ID."""
    global _COUNTER
    while True:
        _COUNTER += 1
        # Base-62 encode the counter
        n = _COUNTER
        chars: list[str] = []
        for _ in range(5):
            chars.append(_CHARSET[n % 62])
            n //= 62
        uid = "".join(reversed(chars))
        if uid not in _USED_IDS:
            _USED_IDS.add(uid)
            return uid


def find_frame(node: dict | list, target_id: str) -> dict | None:
    """Recursively find a node with the given id."""
    if isinstance(node, dict):
        if node.get("id") == target_id:
            return node
        for v in node.values():
            result = find_frame(v, target_id)
            if result is not None:
                return result
    elif isinstance(node, list):
        for item in node:
            result = find_frame(item, target_id)
            if result is not None:
                return result
    return None


# ---------------------------------------------------------------------------
# Stroke helpers
# ---------------------------------------------------------------------------


def stroke_bottom(fill: str = "$border") -> dict:
    return {"align": "inside", "thickness": {"bottom": 1}, "fill": fill}


def stroke_top(fill: str = "$border") -> dict:
    return {"align": "inside", "thickness": {"top": 1}, "fill": fill}


def stroke_top_bottom(fill: str = "$border") -> dict:
    return {"align": "inside", "thickness": {"top": 1, "bottom": 1}, "fill": fill}


def stroke_right(fill: str = "$border") -> dict:
    return {"align": "inside", "thickness": {"right": 1}, "fill": fill}


def stroke_left(fill: str = "$border") -> dict:
    return {"align": "inside", "thickness": {"left": 1}, "fill": fill}


def stroke_all(fill: str = "$border") -> dict:
    return {"align": "inside", "thickness": {"all": 1}, "fill": fill}


# ---------------------------------------------------------------------------
# Node factory helpers
# ---------------------------------------------------------------------------


def frame(
    name: str,
    *,
    x: int | None = None,
    y: int | None = None,
    width: int | str | None = None,
    height: int | str | None = None,
    fill: str | None = None,
    stroke: dict | None = None,
    layout: str | None = None,
    gap: int | None = None,
    padding: list | int | None = None,
    align_items: str | None = None,
    justify_content: str | None = None,
    corner_radius: int | None = None,
    opacity: float | None = None,
    rotation: int | None = None,
    children: list | None = None,
    **extra,
) -> dict:
    node: dict = {"type": "frame", "id": new_id(), "name": name}
    if x is not None:
        node["x"] = x
    if y is not None:
        node["y"] = y
    if width is not None:
        node["width"] = width
    if height is not None:
        node["height"] = height
    if fill is not None:
        node["fill"] = fill
    if stroke is not None:
        node["stroke"] = stroke
    if layout is not None:
        node["layout"] = layout
    if gap is not None:
        node["gap"] = gap
    if padding is not None:
        node["padding"] = padding
    if align_items is not None:
        node["alignItems"] = align_items
    if justify_content is not None:
        node["justifyContent"] = justify_content
    if corner_radius is not None:
        node["cornerRadius"] = corner_radius
    if opacity is not None:
        node["opacity"] = opacity
    if rotation is not None:
        node["rotation"] = rotation
    for k, v in extra.items():
        node[k] = v
    node["children"] = children or []
    return node


def text(
    content: str,
    *,
    name: str | None = None,
    fill: str = "$foreground",
    font_family: str = "IBM Plex Sans",
    font_size: int = 12,
    font_weight: str | int | None = None,
    letter_spacing: float | None = None,
    x: int | None = None,
    y: int | None = None,
    width: int | str | None = None,
) -> dict:
    node: dict = {
        "type": "text",
        "id": new_id(),
        "name": name or content[:20].replace(" ", "_"),
        "fill": fill,
        "content": content,
        "fontFamily": font_family,
        "fontSize": font_size,
    }
    if font_weight is not None:
        node["fontWeight"] = font_weight
    if letter_spacing is not None:
        node["letterSpacing"] = letter_spacing
    if x is not None:
        node["x"] = x
    if y is not None:
        node["y"] = y
    if width is not None:
        node["width"] = width
    return node


def mono(
    content: str,
    *,
    name: str | None = None,
    fill: str = "$foreground",
    font_size: int = 12,
    font_weight: str | int | None = None,
    letter_spacing: float | None = None,
    x: int | None = None,
    y: int | None = None,
    width: int | str | None = None,
) -> dict:
    return text(
        content,
        name=name,
        fill=fill,
        font_family="IBM Plex Mono",
        font_size=font_size,
        font_weight=font_weight,
        letter_spacing=letter_spacing,
        x=x,
        y=y,
        width=width,
    )


def sans(
    content: str,
    *,
    name: str | None = None,
    fill: str = "$foreground",
    font_size: int = 12,
    font_weight: str | int | None = None,
    letter_spacing: float | None = None,
    x: int | None = None,
    y: int | None = None,
    width: int | str | None = None,
) -> dict:
    return text(
        content,
        name=name,
        fill=fill,
        font_family="IBM Plex Sans",
        font_size=font_size,
        font_weight=font_weight,
        letter_spacing=letter_spacing,
        x=x,
        y=y,
        width=width,
    )


def spacer() -> dict:
    """A 1px fill_container spacer to push siblings apart."""
    return frame("spacer", width=1, fill="none", height=1)


# ---------------------------------------------------------------------------
# Pass 1 — State B Fundamentals  (lJVwH children)
# ---------------------------------------------------------------------------

ROW_H = 28
GRP_H = 28


def group_header(label: str) -> dict:
    """Dark group header row used in the snapshot table."""
    return frame(
        f"grpHdr_{label[:6]}",
        width=860,
        height=GRP_H,
        fill="$elevated",
        stroke=stroke_top_bottom(),
        padding=[0, 12],
        align_items="center",
        layout="horizontal",
        children=[
            sans(label, fill="$muted-foreground", font_size=10, font_weight="600", letter_spacing=0.08),
        ],
    )


def data_row(
    label1: str,
    val1: str,
    label2: str,
    val2: str,
    row_fill: str = "$card",
    val1_fill: str = "$foreground",
    val2_fill: str = "$foreground",
) -> dict:
    """Two-pair data row: [label1 130px][val1 85px][label2 130px][val2 85px] rest-fill:gap."""
    # We build a 4-column horizontal row at width 860
    # Pair1: label(130) + val(85), Pair2: label(130) + val(85), middle gap handled by gutter frame
    return frame(
        f"dRow_{label1[:8]}",
        width=860,
        height=ROW_H,
        fill=row_fill,
        stroke=stroke_bottom(),
        layout="horizontal",
        padding=[0, 12],
        align_items="center",
        children=[
            sans(label1, fill="$muted-foreground", font_size=11, width=130),
            mono(val1, fill=val1_fill, font_size=12, width=85),
            sans(label2, fill="$muted-foreground", font_size=11, width=130),
            mono(val2, fill=val2_fill, font_size=12),
        ],
    )


def build_snapshot_metrics() -> dict:
    """Section 1 — Snapshot Metrics Table (h:504)."""
    rows: list[dict] = []

    # VALUATION
    rows.append(group_header("VALUATION"))
    vals = [
        ("P/E Ratio", "28.4×", "Fwd P/E", "24.1×"),
        ("PEG Ratio", "1.42", "P/S Ratio", "8.2×"),
        ("EV/EBITDA", "22.1×", "P/FCF", "31.2×"),
    ]
    for i, (l1, v1, l2, v2) in enumerate(vals):
        fill = "$card" if i % 2 == 0 else "$elevated"
        rows.append(data_row(l1, v1, l2, v2, row_fill=fill))

    # EARNINGS & GROWTH
    rows.append(group_header("EARNINGS & GROWTH"))
    eg_rows = [
        ("EPS (ttm)", "$4.81", "$foreground", "EPS Next Y", "$5.23E", "$dim"),
        ("Rev. (ttm)", "$61.2B", "$foreground", "Rev. Next Y", "$69.1BE", "$dim"),
        ("EPS Q/Q", "+18.3%", "$positive", "Sales Q/Q", "+14.2%", "$positive"),
    ]
    for i, (l1, v1, c1, l2, v2, c2) in enumerate(eg_rows):
        fill = "$card" if i % 2 == 0 else "$elevated"
        rows.append(data_row(l1, v1, l2, v2, row_fill=fill, val1_fill=c1, val2_fill=c2))

    # PROFITABILITY
    rows.append(group_header("PROFITABILITY"))
    prof_rows = [
        ("Gross Margin", "58.3%", "Oper. Margin", "34.1%"),
        ("Net Margin", "29.2%", "EBITDA Margin", "38.4%"),
        ("ROE", "42.1%", "ROA", "18.3%"),
    ]
    for i, (l1, v1, l2, v2) in enumerate(prof_rows):
        fill = "$card" if i % 2 == 0 else "$elevated"
        rows.append(data_row(l1, v1, l2, v2, row_fill=fill))

    # RISK & CAPITAL
    rows.append(group_header("RISK & CAPITAL"))
    risk_rows = [
        ("Beta", "1.68", "Short Float", "0.8%"),
        ("Debt/Equity", "0.42", "Current Ratio", "4.3"),
    ]
    for i, (l1, v1, l2, v2) in enumerate(risk_rows):
        fill = "$card" if i % 2 == 0 else "$elevated"
        rows.append(data_row(l1, v1, l2, v2, row_fill=fill))

    # SIZE & SHARES
    rows.append(group_header("SIZE & SHARES"))
    size_rows = [
        ("Market Cap", "$2.42T", "Enterprise Val", "$2.38T"),
        ("Shares Out.", "24.5B", "Avg Volume", "42.1M"),
    ]
    for i, (l1, v1, l2, v2) in enumerate(size_rows):
        fill = "$card" if i % 2 == 0 else "$elevated"
        rows.append(data_row(l1, v1, l2, v2, row_fill=fill))

    return frame(
        "SnapMetrics",
        width=860,
        height=504,
        fill="$card",
        layout="vertical",
        gap=0,
        children=rows,
    )


def build_analyst_consensus() -> dict:
    """Section 2 — Analyst Consensus Bar (h:72)."""
    row1 = frame(
        "consensusHdr",
        width=860,
        height=28,
        fill="$elevated",
        stroke=stroke_bottom(),
        layout="horizontal",
        padding=[0, 12],
        gap=8,
        align_items="center",
        children=[
            sans("ANALYST CONSENSUS", fill="$muted-foreground", font_size=10, font_weight="600"),
            mono("(36 analysts)", fill="$dim", font_size=10),
            spacer(),
            mono("AVG TARGET  $220.50  ·  +12.3% upside", fill="$positive", font_size=11),
        ],
    )

    bar = frame(
        "consensusBar",
        width=600,
        height=20,
        corner_radius=3,
        layout="horizontal",
        children=[
            frame("segStrongBuy", width=300, height=20, fill="$positive"),
            frame("segBuy", width=198, height=20, fill="#1A6E69"),
            frame("segHold", width=84, height=20, fill="$elevated", stroke=stroke_all()),
            frame("segSell", width=18, height=20, fill="#9B3B3B"),
        ],
    )

    labels_row = frame(
        "barLabels",
        width=600,
        height=14,
        layout="horizontal",
        children=[
            mono("STRONG BUY 50%", fill="$muted-foreground", font_size=9, width=300),
            mono("BUY 33%", fill="$muted-foreground", font_size=9, width=198),
            mono("HOLD 14%", fill="$muted-foreground", font_size=9, width=84),
            mono("SELL 3%", fill="$muted-foreground", font_size=9, width=18),
        ],
    )

    row2 = frame(
        "consensusBarRow",
        width=860,
        height=44,
        layout="horizontal",
        padding=[8, 12],
        gap=0,
        align_items="center",
        children=[
            frame(
                "barGroup",
                layout="vertical",
                gap=2,
                children=[bar, labels_row],
            ),
        ],
    )

    return frame(
        "AnalystConsensus",
        width=860,
        height=72,
        fill="$card",
        stroke=stroke_top(),
        layout="vertical",
        gap=0,
        children=[row1, row2],
    )


def qfin_col(content: str, w: int, fill: str = "$foreground") -> dict:
    return mono(content, fill=fill, font_size=12, width=w)


def build_quarterly_financials() -> dict:
    """Section 3 — Quarterly Financials (h:256)."""
    sec_hdr = frame(
        "qfinHdr",
        width=860,
        height=28,
        fill="$elevated",
        stroke=stroke_top_bottom(),
        layout="horizontal",
        padding=[0, 12],
        align_items="center",
        children=[
            sans("QUARTERLY FINANCIALS", fill="$muted-foreground", font_size=10, font_weight="600"),
            spacer(),
            mono("A = ACTUAL   E = ESTIMATE", fill="$dim", font_size=9),
        ],
    )

    col_hdr = frame(
        "qfinColHdr",
        width=860,
        height=28,
        fill="$elevated",
        stroke=stroke_bottom(),
        layout="horizontal",
        padding=[0, 12],
        align_items="center",
        children=[
            sans("METRIC", fill="$muted-foreground", font_size=10, font_weight="600", width=160),
            sans("TTM", fill="$muted-foreground", font_size=10, font_weight="600", width=100),
            sans("Q1'25E", fill="$muted-foreground", font_size=10, font_weight="600", width=120),
            sans("Q4'24A", fill="$muted-foreground", font_size=10, font_weight="600", width=120),
            sans("Q3'24A", fill="$muted-foreground", font_size=10, font_weight="600", width=120),
            sans("Q2'24A", fill="$muted-foreground", font_size=10, font_weight="600", width=120),
        ],
    )

    income_label = frame(
        "incomeLabel",
        width=860,
        height=20,
        fill="$background",
        stroke=stroke_bottom(),
        padding=[0, 12],
        align_items="center",
        children=[
            sans("INCOME", fill="$dim", font_size=10),
        ],
    )

    rev_row = frame(
        "revRow",
        width=860,
        height=32,
        fill="$card",
        stroke=stroke_bottom(),
        layout="horizontal",
        padding=[0, 12],
        align_items="center",
        children=[
            sans("Revenue", fill="$foreground", font_size=12, width=160),
            qfin_col("$61.2B", 100),
            qfin_col("$43.5B", 120, "$dim"),
            qfin_col("$39.3B", 120),
            qfin_col("$35.1B", 120),
            qfin_col("$30.0B", 120),
        ],
    )

    yoy_row = frame(
        "yoyRow",
        width=860,
        height=20,
        fill="$background",
        stroke=stroke_bottom(),
        layout="horizontal",
        padding=[0, 12],
        align_items="center",
        children=[
            sans("↳ YoY %", fill="$dim", font_size=10, width=160),
            mono("—", fill="$dim", font_size=10, width=100),
            mono("+97%E", fill="$positive", font_size=10, width=120),
            mono("+265%", fill="$positive", font_size=10, width=120),
            mono("+94%", fill="$positive", font_size=10, width=120),
            mono("+122%", fill="$positive", font_size=10, width=120),
        ],
    )

    eps_row = frame(
        "epsRow",
        width=860,
        height=32,
        fill="$elevated",
        stroke=stroke_bottom(),
        layout="horizontal",
        padding=[0, 12],
        align_items="center",
        children=[
            sans("EPS (diluted)", fill="$foreground", font_size=12, width=160),
            qfin_col("$4.81", 100),
            qfin_col("$5.59E", 120, "$dim"),
            qfin_col("$5.16", 120),
            qfin_col("$4.02", 120),
            qfin_col("$2.70", 120),
        ],
    )

    est_row = frame(
        "vsEstRow",
        width=860,
        height=20,
        fill="$background",
        stroke=stroke_bottom(),
        layout="horizontal",
        padding=[0, 12],
        align_items="center",
        children=[
            sans("↳ vs Estimate", fill="$dim", font_size=10, width=160),
            mono("—", fill="$dim", font_size=10, width=100),
            mono("(est)", fill="$dim", font_size=10, width=120),
            mono("▲ +21%", fill="$positive", font_size=10, width=120),
            mono("▲ +9%", fill="$positive", font_size=10, width=120),
            mono("▲ +18%", fill="$positive", font_size=10, width=120),
        ],
    )

    # Padding to reach ~256px total
    # 28+28+20+32+20+32+20 = 180, need 256 → add 76 as a filler or another label+row
    ebitda_label = frame(
        "ebitdaLabel",
        width=860,
        height=20,
        fill="$background",
        stroke=stroke_bottom(),
        padding=[0, 12],
        align_items="center",
        children=[
            sans("MARGINS", fill="$dim", font_size=10),
        ],
    )

    gm_row = frame(
        "gmRow",
        width=860,
        height=28,
        fill="$card",
        stroke=stroke_bottom(),
        layout="horizontal",
        padding=[0, 12],
        align_items="center",
        children=[
            sans("Gross Margin", fill="$foreground", font_size=11, width=160),
            mono("58.3%", fill="$foreground", font_size=11, width=100),
            mono("57.2%", fill="$dim", font_size=11, width=120),
            mono("74.6%", fill="$foreground", font_size=11, width=120),
            mono("74.9%", fill="$foreground", font_size=11, width=120),
            mono("70.1%", fill="$foreground", font_size=11, width=120),
        ],
    )

    op_row = frame(
        "opRow",
        width=860,
        height=28,
        fill="$elevated",
        stroke=stroke_bottom(),
        layout="horizontal",
        padding=[0, 12],
        align_items="center",
        children=[
            sans("Oper. Margin", fill="$foreground", font_size=11, width=160),
            mono("34.1%", fill="$foreground", font_size=11, width=100),
            mono("33.5%E", fill="$dim", font_size=11, width=120),
            mono("55.0%", fill="$foreground", font_size=11, width=120),
            mono("54.2%", fill="$foreground", font_size=11, width=120),
            mono("45.8%", fill="$foreground", font_size=11, width=120),
        ],
    )

    return frame(
        "QuarterlyFinancials",
        width=860,
        height=256,
        fill="$card",
        stroke=stroke_top(),
        layout="vertical",
        gap=0,
        children=[
            sec_hdr,
            col_hdr,
            income_label,
            rev_row,
            yoy_row,
            eps_row,
            est_row,
            ebitda_label,
            gm_row,
            op_row,
        ],
    )


def build_annual_accordion() -> dict:
    """Section 4 — Annual Financials collapsed accordion (h:28)."""
    return frame(
        "AnnualAccordion",
        width=860,
        height=28,
        fill="$elevated",
        stroke=stroke_top_bottom(),
        layout="horizontal",
        padding=[0, 12],
        align_items="center",
        children=[
            mono("▶", fill="$dim", font_size=12),
            sans("ANNUAL FINANCIALS", fill="$muted-foreground", font_size=10, font_weight="600"),
            spacer(),
            mono("FY2024 · FY2023 · FY2022 · FY2021", fill="$dim", font_size=9),
        ],
    )


def build_fundamentals_content() -> dict:
    """Left column — FundamentalsContent (w:860, scrollable)."""
    snap = build_snapshot_metrics()
    consensus = build_analyst_consensus()
    quarterly = build_quarterly_financials()
    annual = build_annual_accordion()

    return frame(
        "FundamentalsContent",
        x=0,
        y=0,
        width=860,
        height=1052,
        fill="$card",
        layout="vertical",
        gap=0,
        children=[snap, consensus, quarterly, annual],
    )


# ---- Right panel helpers ----


def build_52w_range() -> dict:
    """52-Week Range (h:80)."""
    track = frame(
        "rangeTrack",
        width=340,
        height=4,
        fill="$border",
        corner_radius=2,
        layout="none",
        children=[
            frame("rangeDot", x=289, y=-3, width=10, height=10, fill="$primary", corner_radius=5),
        ],
    )
    labels = frame(
        "rangeLabels",
        width=340,
        height=14,
        layout="horizontal",
        justify_content="space_between",
        children=[
            mono("$461.86", fill="$dim", font_size=10),
            mono("CURRENT: $875.40", fill="$primary", font_size=11),
            mono("$974.00", fill="$dim", font_size=10),
        ],
    )
    return frame(
        "Range52W",
        width=380,
        height=80,
        padding=[12, 16],
        layout="vertical",
        gap=8,
        stroke=stroke_bottom(),
        children=[
            sans("52-WEEK RANGE", fill="$muted-foreground", font_size=10, font_weight="600"),
            track,
            labels,
        ],
    )


def build_earnings_history() -> dict:
    """Earnings History (h:132 = 28 hdr + 4×26)."""
    hdr = frame(
        "earningsHdr",
        width=380,
        height=28,
        fill="$elevated",
        stroke=stroke_bottom(),
        layout="horizontal",
        padding=[0, 12],
        align_items="center",
        children=[
            sans("EARNINGS HISTORY", fill="$muted-foreground", font_size=10, font_weight="600"),
            spacer(),
            mono("(last 4 quarters)", fill="$dim", font_size=9),
        ],
    )
    rows_data = [
        ("Q1'25A", "Est: $4.57", "Act: $5.59", "▲ +21% BEAT", "$positive"),
        ("Q4'24A", "Est: $4.59", "Act: $5.16", "▲ +12% BEAT", "$positive"),
        ("Q3'24A", "Est: $3.36", "Act: $4.02", "▲ +20% BEAT", "$positive"),
        (None, None, None, "NEXT: Q2 2025 · est. May 28", "$dim"),
    ]
    row_nodes = []
    for qtr, est, act, beat, beat_fill in rows_data:
        if qtr is None:
            row_nodes.append(
                frame(
                    "earningsNext",
                    width=380,
                    height=26,
                    stroke=stroke_bottom(),
                    layout="horizontal",
                    padding=[0, 12],
                    align_items="center",
                    children=[
                        mono(beat, fill=beat_fill, font_size=10),
                    ],
                )
            )
        else:
            row_nodes.append(
                frame(
                    f"earningsRow{qtr}",
                    width=380,
                    height=26,
                    stroke=stroke_bottom(),
                    layout="horizontal",
                    padding=[0, 12],
                    gap=4,
                    align_items="center",
                    children=[
                        mono(qtr, fill="$foreground", font_size=11),
                        spacer(),
                        mono(est, fill="$muted-foreground", font_size=11),
                        mono(act, fill="$foreground", font_size=11),
                        mono(beat, fill=beat_fill, font_size=11),
                    ],
                )
            )
    return frame(
        "EarningsHistory",
        width=380,
        height=132,
        layout="vertical",
        gap=0,
        stroke=stroke_bottom(),
        children=[hdr, *row_nodes],
    )


def build_technical_snapshot() -> dict:
    """Technical Snapshot (h:80)."""
    chips_data = [
        ("BETA 1.68", "$elevated", "$foreground"),
        ("MA50 ↑", "#0D2926", "$positive"),
        ("MA200 ↑", "#0D2926", "$positive"),
        ("RSI 62.3", "$elevated", "$foreground"),
        ("SHORT 0.8%", "$elevated", "$foreground"),
    ]
    chips = [
        frame(
            f"techChip{lbl[:5]}",
            height=24,
            corner_radius=4,
            padding=[0, 8],
            align_items="center",
            fill=bg,
            children=[mono(lbl, fill=tc, font_size=10)],
        )
        for lbl, bg, tc in chips_data
    ]
    chips_row = frame(
        "techChips",
        layout="horizontal",
        gap=8,
        height=24,
        children=chips,
    )
    return frame(
        "TechnicalSnapshot",
        width=380,
        height=80,
        padding=[12, 16],
        layout="vertical",
        gap=8,
        stroke=stroke_bottom(),
        children=[
            sans("TECHNICAL", fill="$muted-foreground", font_size=10, font_weight="600"),
            chips_row,
        ],
    )


def build_analyst_actions() -> dict:
    """Recent Analyst Actions (h:160)."""
    hdr = frame(
        "actionsHdr",
        width=380,
        height=28,
        fill="$elevated",
        stroke=stroke_bottom(),
        padding=[0, 12],
        align_items="center",
        children=[
            sans("ANALYST ACTIONS", fill="$muted-foreground", font_size=10, font_weight="600"),
        ],
    )

    rows_data = [
        ("Goldman Sachs", "UPGRADE", "#0D2926", "$positive", "$190→$220", "$positive"),
        ("Morgan Stanley", "REITERATE", "$elevated", "$muted-foreground", "$210", "$muted-foreground"),
        ("JPMorgan", "UPGRADE", "#0D2926", "$positive", "$200→$230", "$positive"),
        ("Bernstein", "DOWNGRADE", "#2D1515", "$negative", "$250→$210", "$negative"),
    ]
    row_nodes = []
    for firm, action, badge_fill, badge_text, target, target_fill in rows_data:
        badge = frame(
            f"badge{action[:6]}",
            height=18,
            corner_radius=3,
            padding=[2, 6],
            fill=badge_fill,
            stroke={"align": "inside", "thickness": {"all": 1}, "fill": badge_text},
            align_items="center",
            children=[mono(action, fill=badge_text, font_size=9, font_weight="600")],
        )
        row_nodes.append(
            frame(
                f"actionRow{firm[:6]}",
                width=380,
                height=33,
                stroke=stroke_bottom(),
                layout="horizontal",
                padding=[0, 12],
                gap=6,
                align_items="center",
                children=[
                    sans(firm, fill="$foreground", font_size=11, width="fill_container"),
                    badge,
                    mono(target, fill=target_fill, font_size=10),
                ],
            )
        )

    return frame(
        "AnalystActions",
        width=380,
        height=160,
        layout="vertical",
        gap=0,
        stroke=stroke_bottom(),
        children=[hdr, *row_nodes],
    )


def build_insider_activity() -> dict:
    """Insider Activity (h:100)."""
    net_bar = frame(
        "insiderBar",
        width=340,
        height=6,
        fill="$border",
        corner_radius=2,
        layout="none",
        children=[
            frame("insiderSell", x=0, y=0, width=220, height=6, fill="$negative", corner_radius=2),
        ],
    )
    tx1 = frame(
        "insiderTx1",
        height=24,
        layout="horizontal",
        gap=4,
        align_items="center",
        children=[
            sans("J. Huang (CEO) — ", fill="$muted-foreground", font_size=10),
            sans("SELL", fill="$negative", font_size=10, font_weight="600"),
            sans(" 50,000 sh @ $880 · Apr 11", fill="$muted-foreground", font_size=10),
        ],
    )
    tx2 = frame(
        "insiderTx2",
        height=24,
        layout="horizontal",
        gap=4,
        align_items="center",
        children=[
            sans("C. Kress (CFO) — ", fill="$muted-foreground", font_size=10),
            sans("SELL", fill="$negative", font_size=10, font_weight="600"),
            sans(" 25,000 sh @ $850 · Apr 8", fill="$muted-foreground", font_size=10),
        ],
    )
    return frame(
        "InsiderActivity",
        width=380,
        height=100,
        padding=[12, 16],
        layout="vertical",
        gap=8,
        children=[
            sans("INSIDER ACTIVITY (90 DAYS)", fill="$muted-foreground", font_size=10, font_weight="600"),
            net_bar,
            tx1,
            tx2,
        ],
    )


def build_right_panel_b() -> dict:
    """Right panel B (w:380, h:768, sticky)."""
    return frame(
        "RightPanelB",
        x=860,
        y=0,
        width=380,
        height=768,
        fill="$card",
        stroke={"align": "inside", "thickness": {"left": 1}, "fill": "$border"},
        layout="vertical",
        gap=0,
        children=[
            build_52w_range(),
            build_earnings_history(),
            build_technical_snapshot(),
            build_analyst_actions(),
            build_insider_activity(),
        ],
    )


def build_state_b_body() -> list[dict]:
    """
    Returns new children for lJVwH (the Body frame in State B).
    Preserves the existing TabBar (miUBU) by keeping it in place;
    only FundamentalsContent and RightPanelB are regenerated.
    The caller replaces lJVwH.children entirely, so we must include TabBar.
    But TabBar is already in the file — we return NEW nodes for
    FundamentalsContent and RightPanelB only, keeping TabBar from the
    original. Actually per instructions we replace all children, so we
    keep TabBar by passing it through. We do a rebuild of only the two
    non-TabBar children.
    """
    left = build_fundamentals_content()
    left["x"] = 0
    left["y"] = 36  # below TabBar
    right = build_right_panel_b()
    return [left, right]


# ---------------------------------------------------------------------------
# Pass 2 — State C Intelligence  (vlN6E children)
# ---------------------------------------------------------------------------


def build_graph_controls() -> dict:
    """Graph Controls Bar (h:40, w:1240)."""

    def inactive_chip(label: str) -> dict:
        return frame(
            f"chip{label[:6]}",
            height=28,
            corner_radius=4,
            padding=[0, 8],
            fill="$elevated",
            stroke=stroke_all(),
            align_items="center",
            children=[mono(label, fill="$muted-foreground", font_size=11)],
        )

    def active_chip(label: str) -> dict:
        return frame(
            f"chipA{label[:6]}",
            height=28,
            corner_radius=4,
            padding=[0, 8],
            fill="$primary-dim",
            stroke=stroke_all("$primary"),
            align_items="center",
            children=[mono(label, fill="$primary", font_size=11)],
        )

    def sep() -> dict:
        return frame("sep", width=1, height=20, fill="$border")

    filter_active = frame(
        "filterChipActive",
        height=28,
        corner_radius=4,
        padding=[0, 8],
        fill="$primary-dim",
        stroke=stroke_all("$primary"),
        align_items="center",
        children=[sans("◉ COMPANY ✓", fill="$primary", font_size=11)],
    )
    filter_person = frame(
        "filterPerson",
        height=28,
        corner_radius=4,
        padding=[0, 8],
        fill="$primary-dim",
        stroke=stroke_all("$primary"),
        align_items="center",
        children=[sans("◉ PERSON ✓", fill="$primary", font_size=11)],
    )
    filter_event = frame(
        "filterEvent",
        height=28,
        corner_radius=4,
        padding=[0, 8],
        fill="$primary-dim",
        stroke=stroke_all("$primary"),
        align_items="center",
        children=[sans("◆ EVENT ✓", fill="$primary", font_size=11)],
    )
    filter_reg = frame(
        "filterReg",
        height=28,
        corner_radius=4,
        padding=[0, 8],
        fill="$primary-dim",
        stroke=stroke_all("$primary"),
        align_items="center",
        children=[sans("▪ REGULATORY ✓", fill="$primary", font_size=11)],
    )

    count_chip = frame(
        "countChip",
        height=28,
        corner_radius=4,
        padding=[0, 8],
        fill="$elevated",
        stroke=stroke_all(),
        align_items="center",
        children=[mono("47 nodes · 89 edges", fill="$muted-foreground", font_size=10)],
    )

    search_input = frame(
        "searchInput",
        width=160,
        height=28,
        fill="$background",
        stroke=stroke_all(),
        corner_radius=4,
        align_items="center",
        padding=[0, 8],
        children=[mono("Filter entities...", fill="$dim", font_size=10)],
    )

    return frame(
        "GraphControls",
        width=1240,
        height=40,
        fill="$elevated",
        stroke=stroke_bottom(),
        layout="horizontal",
        padding=[0, 12],
        gap=8,
        align_items="center",
        children=[
            sans("DEPTH", fill="$dim", font_size=10, letter_spacing=0.8),
            inactive_chip("1"),
            active_chip("2●"),
            inactive_chip("3"),
            sep(),
            active_chip("Force●"),
            inactive_chip("Radial"),
            inactive_chip("Tree"),
            sep(),
            sans("TYPES", fill="$dim", font_size=10),
            filter_active,
            filter_person,
            filter_event,
            filter_reg,
            spacer(),
            count_chip,
            sep(),
            search_input,
        ],
    )


def edge_line(x1: int, y1: int, x2: int, y2: int, fill: str, opacity: float, name: str) -> dict:
    """Create an approximated edge line between two points."""
    dx = x2 - x1
    dy = y2 - y1
    length = max(1, int(math.sqrt(dx * dx + dy * dy)))
    mx = (x1 + x2) // 2
    my = (y1 + y2) // 2
    angle = math.degrees(math.atan2(dy, dx))
    return frame(
        name,
        x=mx - length // 2,
        y=my,
        width=length,
        height=1,
        fill=fill,
        opacity=opacity,
        rotation=int(angle),
    )


def build_graph_canvas() -> dict:
    """Graph Canvas (w:860, h:580)."""
    # Node positions (center x, y)
    P_NVDA = (426, 286)
    P_AAPL = (638, 158)
    P_ARM = (218, 158)
    P_TSMC = (658, 378)
    P_HUANG = (575, 75)
    P_SOFT = (154, 274)
    P_FOMC = (412, 452)

    def company_node(nid: str, label: str, sublabel: str, cx: int, cy: int, is_central: bool = False) -> list[dict]:
        if is_central:
            sz, cr = 52, 6
            stroke_cfg = {"align": "inside", "thickness": {"all": 2}, "fill": "$primary"}
            node_fill = "$card"
            txt_fill = "$foreground"
            subtxt_fill = "$muted-foreground"
        else:
            sz, cr = 36, 18
            stroke_cfg = stroke_all("$primary")
            node_fill = "$primary-dim"
            txt_fill = "$primary"
            subtxt_fill = "$primary"

        nx = cx - sz // 2
        ny = cy - sz // 2
        nodes = [
            frame(
                f"node{nid}",
                x=nx,
                y=ny,
                width=sz,
                height=sz,
                fill=node_fill,
                stroke=stroke_cfg,
                corner_radius=cr,
                layout="vertical",
                justify_content="center",
                align_items="center",
                children=[
                    mono(label, fill=txt_fill, font_size=12, font_weight="600"),
                ]
                + ([sans(sublabel, fill=subtxt_fill, font_size=9)] if is_central else []),
            ),
        ]
        if not is_central:
            nodes.append(
                text(
                    label,
                    name=f"lbl{nid}",
                    fill=txt_fill,
                    font_family="IBM Plex Mono",
                    font_size=11,
                    x=nx,
                    y=cy + sz // 2 + 4,
                )
            )
        return nodes

    def person_node(nid: str, label: str, cx: int, cy: int) -> list[dict]:
        sz = 30
        return [
            frame(
                f"node{nid}",
                x=cx - sz // 2,
                y=cy - sz // 2,
                width=sz,
                height=sz,
                fill="#1F1A0A",
                stroke=stroke_all("$warning"),
                corner_radius=15,
                layout="none",
            ),
            mono(label, name=f"lbl{nid}", fill="$warning", font_size=10, x=cx - 20, y=cy + sz // 2 + 4),
        ]

    def fund_node(nid: str, label: str, cx: int, cy: int) -> list[dict]:
        sz = 28
        return [
            frame(
                f"node{nid}",
                x=cx - sz // 2,
                y=cy - sz // 2,
                width=sz,
                height=sz,
                fill="$amber-dim",
                stroke=stroke_all("$amber"),
                corner_radius=14,
                layout="none",
            ),
            mono(label, name=f"lbl{nid}", fill="$amber", font_size=10, x=cx - 25, y=cy + sz // 2 + 4),
        ]

    def event_node(nid: str, label: str, cx: int, cy: int) -> list[dict]:
        sz = 24
        return [
            frame(
                f"node{nid}",
                x=cx - sz // 2,
                y=cy - sz // 2,
                width=sz,
                height=sz,
                fill="$elevated",
                stroke=stroke_all("$warning"),
                corner_radius=4,
                layout="none",
            ),
            mono(label, name=f"lbl{nid}", fill="$warning", font_size=9, x=cx - 15, y=cy + sz // 2 + 4),
        ]

    def edge_label(content: str, x: int, y: int) -> dict:
        return mono(content, name=f"eLbl{content[:6]}", fill="$dim", font_size=8, x=x, y=y)

    # Build all nodes
    all_children: list[dict] = []

    # Edges first (drawn behind nodes)
    all_children.append(edge_line(*P_NVDA, *P_AAPL, "$primary", 0.4, "edgeNVDA_AAPL"))
    all_children.append(edge_line(*P_NVDA, *P_ARM, "$primary", 0.4, "edgeNVDA_ARM"))
    all_children.append(edge_line(*P_NVDA, *P_TSMC, "$positive", 0.4, "edgeNVDA_TSMC"))
    all_children.append(edge_line(*P_NVDA, *P_HUANG, "$warning", 0.4, "edgeNVDA_HUANG"))
    all_children.append(edge_line(*P_NVDA, *P_FOMC, "$border", 0.6, "edgeNVDA_FOMC"))
    all_children.append(edge_line(*P_NVDA, *P_SOFT, "$amber", 0.4, "edgeNVDA_SOFT"))

    # Edge labels
    def mid(p1, p2):
        return ((p1[0] + p2[0]) // 2 + 6, (p1[1] + p2[1]) // 2 - 8)

    all_children.append(edge_label("customer", *mid(P_NVDA, P_AAPL)))
    all_children.append(edge_label("CEO", *mid(P_NVDA, P_HUANG)))
    all_children.append(edge_label("key supplier", *mid(P_NVDA, P_TSMC)))
    all_children.append(edge_label("investor", *mid(P_NVDA, P_SOFT)))

    # Nodes (drawn on top of edges)
    all_children.extend(company_node("NVDA", "NVDA", "NVIDIA Corp", *P_NVDA, is_central=True))
    all_children.extend(company_node("AAPL", "AAPL", "Apple Inc.", *P_AAPL))
    all_children.extend(company_node("ARM", "ARM", "ARM Holdings", *P_ARM))
    all_children.extend(company_node("TSMC", "TSMC", "TSMC", *P_TSMC))
    all_children.extend(person_node("HUANG", "J. HUANG", *P_HUANG))
    all_children.extend(fund_node("SOFT", "SOFTBANK", *P_SOFT))
    all_children.extend(event_node("FOMC", "FOMC", *P_FOMC))

    # Minimap
    minimap = frame(
        "minimap",
        x=732,
        y=500,
        width=120,
        height=72,
        fill="$card",
        stroke=stroke_all(),
        corner_radius=4,
        layout="none",
        children=[
            mono("MAP", fill="$dim", font_size=8, x=8, y=4),
            frame("mmDot1", x=30, y=20, width=4, height=4, fill="$primary", corner_radius=2),
            frame("mmDot2", x=50, y=32, width=4, height=4, fill="$primary", corner_radius=2),
            frame("mmDot3", x=70, y=18, width=4, height=4, fill="$primary", corner_radius=2),
            frame("mmDot4", x=90, y=40, width=4, height=4, fill="$primary", corner_radius=2),
            frame("mmDotW1", x=45, y=52, width=4, height=4, fill="$warning", corner_radius=2),
            frame("mmDotW2", x=25, y=44, width=4, height=4, fill="$warning", corner_radius=2),
            frame("mmViewport", x=20, y=16, width=60, height=40, fill="none", stroke=stroke_all("$primary")),
        ],
    )
    all_children.append(minimap)

    # Zoom controls
    zoom = frame(
        "zoomCtrl",
        x=820,
        y=8,
        width=32,
        height=88,
        fill="$card",
        stroke=stroke_all(),
        corner_radius=4,
        layout="vertical",
        gap=0,
        children=[
            frame(
                "zoomPlus",
                height=28,
                layout="horizontal",
                justify_content="center",
                align_items="center",
                stroke=stroke_bottom(),
                children=[mono("+", fill="$muted-foreground", font_size=14)],
            ),
            frame(
                "zoomMinus",
                height=28,
                layout="horizontal",
                justify_content="center",
                align_items="center",
                stroke=stroke_bottom(),
                children=[mono("−", fill="$muted-foreground", font_size=14)],
            ),
            frame(
                "zoomReset",
                height=28,
                layout="horizontal",
                justify_content="center",
                align_items="center",
                children=[mono("↺", fill="$muted-foreground", font_size=14)],
            ),
        ],
    )
    all_children.append(zoom)

    # Legend
    def legend_dot(color: str, label: str, sz: int = 6, cr: int = 3) -> list[dict]:
        return [
            frame(f"legDot{label[:4]}", width=sz, height=sz, fill=color, corner_radius=cr),
            sans(label, fill="$muted-foreground", font_size=9),
        ]

    leg_children: list[dict] = []
    for c in legend_dot("$primary", "COMPANY"):
        leg_children.append(c)
    for c in legend_dot("$warning", "PERSON"):
        leg_children.append(c)
    for c in legend_dot("$warning", "EVENT", cr=0):
        leg_children.append(c)
    for c in legend_dot("$negative", "REGULATORY", cr=0):
        leg_children.append(c)

    legend = frame(
        "legend",
        x=8,
        y=548,
        width=260,
        height=24,
        fill="$card",
        stroke=stroke_all(),
        corner_radius=4,
        layout="horizontal",
        gap=10,
        padding=[0, 8],
        align_items="center",
        children=leg_children,
    )
    all_children.append(legend)

    return frame(
        "GraphCanvas",
        width=860,
        height=580,
        fill="$background",
        stroke=stroke_right(),
        layout="none",
        children=all_children,
    )


def build_context_panel() -> dict:
    """Context Panel (w:380, h:580) — shown in selected-AAPL state."""
    sel_hdr = frame(
        "ctxSelHdr",
        width=380,
        height=56,
        fill="$elevated",
        stroke=stroke_bottom(),
        layout="none",
        padding=[0, 12],
        children=[
            frame(
                "ctxBadge",
                x=0,
                y=8,
                height=18,
                corner_radius=3,
                padding=[2, 6],
                fill="$primary-dim",
                stroke={"align": "inside", "thickness": {"all": 1}, "fill": "$primary"},
                align_items="center",
                children=[mono("COMPANY", fill="$primary", font_size=9, font_weight="600")],
            ),
            text(
                "APPLE INC.",
                name="ctxTitle",
                fill="$foreground",
                font_family="IBM Plex Sans",
                font_size=13,
                font_weight="600",
                x=72,
                y=6,
            ),
            text(
                "Technology · Consumer Electronics · NASDAQ",
                name="ctxSub",
                fill="$dim",
                font_family="IBM Plex Sans",
                font_size=10,
                x=0,
                y=32,
            ),
        ],
    )

    signal_track = frame(
        "sigTrack",
        width=120,
        height=6,
        fill="$border",
        corner_radius=2,
        layout="none",
        children=[
            frame("sigFill", x=0, y=0, width=85, height=6, fill="$warning", corner_radius=2),
        ],
    )
    med_badge = frame(
        "medBadge",
        height=18,
        corner_radius=3,
        padding=[2, 6],
        fill="#1F1A0A",
        stroke={"align": "inside", "thickness": {"all": 1}, "fill": "$warning"},
        align_items="center",
        children=[mono("MEDIUM", fill="$warning", font_size=9)],
    )
    signal_row = frame(
        "ctxSignalRow",
        width=380,
        height=40,
        stroke=stroke_bottom(),
        layout="horizontal",
        padding=[0, 12],
        gap=8,
        align_items="center",
        children=[
            sans("SIGNAL SCORE", fill="$muted-foreground", font_size=10, font_weight="600", width=80),
            signal_track,
            mono("0.71", fill="$warning", font_size=12),
            med_badge,
        ],
    )

    # Connections
    conn_hdr = frame(
        "connHdr",
        width=380,
        height=28,
        fill="$elevated",
        stroke=stroke_bottom(),
        padding=[0, 12],
        align_items="center",
        children=[sans("TOP CONNECTIONS (5)", fill="$muted-foreground", font_size=10, font_weight="600")],
    )
    conn_rows_data = [
        ("NVIDIA Corp", "competitor", "0.91"),
        ("Samsung", "supply chain", "0.84"),
        ("Qualcomm", "competitor", "0.78"),
        ("TSMC", "fab partner", "0.95"),
        ("ARM Holdings", "IP licensee", "0.82"),
    ]
    conn_rows = []
    for entity, rel, score in conn_rows_data:
        score_chip = frame(
            f"scoreChip{entity[:5]}",
            height=18,
            corner_radius=3,
            padding=[2, 6],
            fill="$primary-dim",
            stroke=stroke_all("$primary"),
            align_items="center",
            children=[mono(score, fill="$primary", font_size=9)],
        )
        conn_rows.append(
            frame(
                f"connRow{entity[:6]}",
                width=380,
                height=32,
                stroke=stroke_bottom(),
                layout="horizontal",
                padding=[0, 12],
                gap=8,
                align_items="center",
                children=[
                    sans(entity, fill="$foreground", font_size=12, width="fill_container"),
                    sans(rel, fill="$dim", font_size=10),
                    score_chip,
                ],
            )
        )

    connections_section = frame(
        "ctxConnections",
        width=380,
        height=188,
        layout="vertical",
        gap=0,
        children=[conn_hdr, *conn_rows],
    )

    # Recent Claims
    claims_hdr = frame(
        "claimsHdr",
        width=380,
        height=28,
        fill="$elevated",
        stroke=stroke_bottom(),
        padding=[0, 12],
        align_items="center",
        children=[sans("RECENT CLAIMS (3)", fill="$muted-foreground", font_size=10, font_weight="600")],
    )
    claims_data = [
        (
            "Apple and NVIDIA discuss AI chip integration for next-gen Mac Pro series",
            "Reuters · 3h ago · confidence 0.87",
        ),
        (
            "Tim Cook confirms supply chain diversification away from TSMC for mature nodes",
            "Bloomberg · 8h ago · confidence 0.74",
        ),
        (
            "AAPL services revenue expected to reach $120B, driven by AI integration",
            "FT · 1d ago · confidence 0.91",
        ),
    ]
    claim_rows = []
    for claim_txt, source in claims_data:
        claim_rows.append(
            frame(
                f"claim{claim_txt[:10].replace(' ', '')}",
                width=380,
                height=48,
                stroke=stroke_bottom(),
                padding=[8, 12],
                layout="vertical",
                gap=4,
                children=[
                    sans(claim_txt, fill="$foreground", font_size=11),
                    mono(source, fill="$muted-foreground", font_size=9),
                ],
            )
        )

    claims_section = frame(
        "ctxClaims",
        width=380,
        height=172,
        layout="vertical",
        gap=0,
        children=[claims_hdr, *claim_rows],
    )

    return frame(
        "ContextPanel",
        width=380,
        height=580,
        fill="$card",
        stroke={"align": "inside", "thickness": {"left": 1}, "fill": "$border"},
        layout="vertical",
        gap=0,
        children=[sel_hdr, signal_row, connections_section, claims_section],
    )


def build_main_area() -> dict:
    """Main Area row (h:580, w:1240)."""
    return frame(
        "IntelMainArea",
        width=1240,
        height=580,
        layout="horizontal",
        gap=0,
        children=[build_graph_canvas(), build_context_panel()],
    )


def _claim_cell(
    badge_label: str, badge_fill: str, badge_stroke: str, badge_text: str, claim_text: str, score: str
) -> dict:
    badge = frame(
        f"claimBadge{badge_label[:6]}",
        height=18,
        corner_radius=3,
        padding=[2, 6],
        fill=badge_fill,
        stroke={"align": "inside", "thickness": {"all": 1}, "fill": badge_stroke},
        align_items="center",
        children=[mono(badge_label, fill=badge_text, font_size=9)],
    )
    return frame(
        f"claimCell{claim_text[:10].replace(' ', '')}",
        width=360,
        height=40,
        stroke=stroke_right(),
        layout="horizontal",
        padding=[0, 12],
        gap=8,
        align_items="center",
        children=[
            badge,
            sans(claim_text, fill="$foreground", font_size=11, width="fill_container"),
            mono(score, fill="$dim", font_size=10),
        ],
    )


def build_claims_strip() -> dict:
    """Claims Strip (h:40, w:1240)."""
    hdr_chip = frame(
        "claimsHdrChip",
        width=100,
        height=40,
        stroke=stroke_right(),
        layout="horizontal",
        justify_content="center",
        align_items="center",
        children=[sans("CLAIMS (10)", fill="$muted-foreground", font_size=10, font_weight="600")],
    )
    cell1 = _claim_cell("POSITIVE", "#0D2926", "$positive", "$positive", "NVDA to supply AI chips to Apple", "0.87")
    cell2 = _claim_cell(
        "NEUTRAL",
        "$elevated",
        "$muted-foreground",
        "$muted-foreground",
        "ARM IP licensing renewal under negotiation",
        "0.74",
    )
    cell3 = _claim_cell("POSITIVE", "#0D2926", "$positive", "$positive", "Softbank increases NVDA stake by 12%", "0.91")
    see_all = frame(
        "claimsSeeAll",
        height=40,
        padding=[0, 12],
        align_items="center",
        children=[sans("See all →", fill="$primary", font_size=10)],
    )
    return frame(
        "ClaimsStrip",
        width=1240,
        height=40,
        fill="$card",
        stroke=stroke_top(),
        layout="horizontal",
        gap=0,
        children=[hdr_chip, cell1, cell2, cell3, spacer(), see_all],
    )


def _event_cell(
    badge_label: str, badge_fill: str, badge_stroke: str, badge_text: str, event_text: str, date_str: str
) -> dict:
    badge = frame(
        f"evtBadge{badge_label[:6]}",
        height=18,
        corner_radius=3,
        padding=[2, 6],
        fill=badge_fill,
        stroke={"align": "inside", "thickness": {"all": 1}, "fill": badge_stroke},
        align_items="center",
        children=[mono(badge_label, fill=badge_text, font_size=9)],
    )
    return frame(
        f"evtCell{event_text[:10].replace(' ', '')}",
        width=360,
        height=40,
        stroke=stroke_right(),
        layout="horizontal",
        padding=[0, 12],
        gap=8,
        align_items="center",
        children=[
            badge,
            sans(event_text, fill="$foreground", font_size=11, width="fill_container"),
            mono(date_str, fill="$dim", font_size=10),
        ],
    )


def build_temporal_strip() -> dict:
    """Temporal Events Strip (h:40, w:1240)."""
    hdr_chip = frame(
        "eventsHdrChip",
        width=100,
        height=40,
        stroke=stroke_right(),
        layout="horizontal",
        justify_content="center",
        align_items="center",
        children=[sans("EVENTS (8)", fill="$muted-foreground", font_size=10, font_weight="600")],
    )
    cell1 = _event_cell("EARNINGS", "$primary-dim", "$primary", "$primary", "NVDA Q1 2025 Earnings Report", "May 28")
    cell2 = _event_cell("MACRO", "#1F1A0A", "$warning", "$warning", "FOMC Rate Decision", "Jun 12")
    cell3 = _event_cell("REGULATORY", "#2D1515", "$negative", "$negative", "EU AI Act enforcement begins", "Jul 1")
    return frame(
        "TemporalStrip",
        width=1240,
        height=40,
        fill="$card",
        stroke=stroke_top(),
        layout="horizontal",
        gap=0,
        children=[hdr_chip, cell1, cell2, cell3],
    )


def build_state_c_body() -> list[dict]:
    """New children for vlN6E (State C Body)."""
    return [
        build_graph_controls(),
        build_main_area(),
        build_claims_strip(),
        build_temporal_strip(),
    ]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def count_nodes(node: dict | list) -> int:
    """Count total frame/text nodes recursively."""
    total = 0
    if isinstance(node, dict):
        if node.get("type") in ("frame", "text"):
            total += 1
        for v in node.values():
            total += count_nodes(v)
    elif isinstance(node, list):
        for item in node:
            total += count_nodes(item)
    return total


def main() -> None:
    with open(PEN_PATH) as f:
        data = json.load(f)

    _load_existing_ids(data)
    print(f"Loaded pen file: {PEN_PATH}")
    print(f"Existing unique IDs: {len(_USED_IDS)}")

    # ---- Pass 1: State B (lJVwH) ----
    target_b = find_frame(data, "lJVwH")
    if target_b is None:
        raise RuntimeError("Frame lJVwH not found")

    # Preserve TabBar (miUBU) as-is; rebuild the two layout panels
    tab_bar_b = find_frame(data, "miUBU")
    new_b_panels = build_state_b_body()
    new_children_b = ([tab_bar_b] if tab_bar_b else []) + new_b_panels
    node_count_b = sum(count_nodes(n) for n in new_b_panels)

    target_b["children"] = new_children_b
    print("\nPass 1 — lJVwH (State B Fundamentals)")
    print("  Old children count: preserved TabBar + 2 new panels")
    print(f"  New nodes added (FundamentalsContent + RightPanelB): {node_count_b}")

    # ---- Pass 2: State C (vlN6E) ----
    target_c = find_frame(data, "vlN6E")
    if target_c is None:
        raise RuntimeError("Frame vlN6E not found")

    # Preserve TabBar (cqTjE) as-is
    tab_bar_c = find_frame(data, "cqTjE")
    new_c_sections = build_state_c_body()
    new_children_c = ([tab_bar_c] if tab_bar_c else []) + new_c_sections
    node_count_c = sum(count_nodes(n) for n in new_c_sections)

    target_c["children"] = new_children_c
    print("\nPass 2 — vlN6E (State C Intelligence)")
    print("  Old children count: preserved TabBar + 4 new sections")
    print(f"  New nodes added (Controls + MainArea + Claims + Events): {node_count_c}")

    # Write back
    with open(PEN_PATH, "w") as f:
        json.dump(data, f, separators=(",", ":"))

    print(f"\nDone. Written to: {PEN_PATH}")
    total = node_count_b + node_count_c
    print(f"Total new nodes added across both passes: {total}")


if __name__ == "__main__":
    main()
