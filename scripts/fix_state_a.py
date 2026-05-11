# ruff: noqa: S311, F841
"""
fix_state_a.py — Apply all 6 FIX patches to State A (b8vqT) in worldview-mvp_v2.pen
Run:  python3 scripts/fix_state_a.py
"""

import json
import random
import string

SRC = "apps/frontend/designs/worldview-mvp_v2.pen"
DST = "apps/frontend/designs/worldview-mvp_v2.pen"

# ── colour tokens ────────────────────────────────────────────────────────────
BG = "#080A0E"
CARD = "#10141C"
ELEVATED = "#181D28"
BORDER = "#232A36"
BORDER_STR = "#2E3847"
FG = "#D1D4DC"
MUTED_FG = "#787B86"
DIM = "#4C5260"
PRIMARY = "#0EA5E9"
PRIMARY_DIM = "#0EA5E920"
AMBER = "#F0C040"
AMBER_DIM = "#F0C04018"
POSITIVE = "#26A69A"
NEGATIVE = "#EF5350"
WARNING = "#F59E0B"

_CHARS = string.ascii_letters + string.digits


def nid(n=5):
    return "".join(random.choices(_CHARS, k=n))


def find_node(tree, target_id):
    if isinstance(tree, dict):
        if tree.get("id") == target_id:
            return tree
        for v in tree.values():
            r = find_node(v, target_id)
            if r:
                return r
    elif isinstance(tree, list):
        for item in tree:
            r = find_node(item, target_id)
            if r:
                return r
    return None


def vsep(w=1, h=20, fill=BORDER):
    return {"type": "rectangle", "id": nid(), "name": "vsep", "width": w, "height": h, "fill": fill}


def icon(name, size=16, color=MUTED_FG, family="lucide"):
    return {
        "type": "icon_font",
        "id": nid(),
        "name": name,
        "width": size,
        "height": size,
        "iconFontName": name,
        "iconFontFamily": family,
        "fill": color,
    }


def txt(content, size=11, weight="normal", color=FG, family="IBM Plex Sans"):
    return {
        "type": "text",
        "id": nid(),
        "name": content[:16],
        "content": content,
        "fontFamily": family,
        "fontSize": size,
        "fontWeight": weight,
        "fill": color,
    }


def mono(content, size=11, weight="normal", color=FG):
    return txt(content, size, weight, color, "IBM Plex Mono")


# ════════════════════════════════════════════════════════════════════════════
# FIX 1  — TopBar (Skz8Y)
# ════════════════════════════════════════════════════════════════════════════
def fix_topbar(tb):
    tb["fill"] = CARD
    tb["stroke"] = {"align": "inside", "thickness": {"bottom": 1}, "fill": BORDER}

    children = tb["children"]

    # logo
    logo = next((c for c in children if c.get("name") == "logo"), None)
    if logo:
        logo["fill"] = PRIMARY
        logo["fontFamily"] = "IBM Plex Mono"
        logo["fontWeight"] = "600"

    # search input
    search = next((c for c in children if c.get("name") == "SearchInput"), None)
    if search:
        search["fill"] = ELEVATED
        search["stroke"] = {"align": "inside", "thickness": 1, "fill": BORDER}
        for sc in search.get("children", []):
            if sc.get("type") == "icon_font":
                sc["fill"] = DIM
            elif sc.get("name") in ("searchText", "cmdK"):
                sc["fill"] = DIM

    # market chip colours
    CHIP_NAMES = {"spy", "qqq", "dia", "vix"}
    for c in children:
        if c.get("name") in CHIP_NAMES:
            for sc in c.get("children", []):
                nm = sc.get("name", "")
                if nm.endswith("Tick"):
                    sc["fill"] = MUTED_FG
                elif nm.endswith("Val"):
                    sc["fill"] = MUTED_FG
                elif nm.endswith("Chg"):
                    # positive = ▲, negative = ▼
                    if "▲" in sc.get("content", "") or "+" in sc.get("content", ""):
                        sc["fill"] = POSITIVE
                    else:
                        sc["fill"] = NEGATIVE

    # separators
    for c in children:
        if c.get("type") == "rectangle" and c.get("name", "").startswith("sep"):
            c["fill"] = BORDER

    # delete right-side problem elements: BVUqK, GE2OF, ksmg4, O5L8B
    KILL = {"BVUqK", "GE2OF", "ksmg4", "O5L8B"}
    tb["children"] = [c for c in children if c.get("id") not in KILL]

    # build new right group: dot + text + vsep + bell + avatar
    avatar_frame = {
        "type": "frame",
        "id": nid(),
        "name": "avatar",
        "width": 28,
        "height": 28,
        "cornerRadius": 14,
        "fill": PRIMARY_DIM,
        "justifyContent": "center",
        "alignItems": "center",
        "children": [mono("AR", 11, "600", PRIMARY)],
    }
    right_group = {
        "type": "frame",
        "id": nid(),
        "name": "rightGroup",
        "x": 1100,
        "y": 0,
        "width": 324,
        "height": 48,
        "gap": 12,
        "padding": [0, 16, 0, 0],
        "alignItems": "center",
        "justifyContent": "flex_end",
        "children": [
            {"type": "ellipse", "id": nid(), "name": "mktDot", "width": 8, "height": 8, "fill": POSITIVE},
            txt("14:32 ET · MARKET OPEN", 11, "normal", MUTED_FG),
            vsep(1, 20, BORDER),
            icon("bell", 16, MUTED_FG),
            avatar_frame,
        ],
    }
    tb["children"].append(right_group)


# ════════════════════════════════════════════════════════════════════════════
# FIX 2  — Sidebar (VUjGx)
# ════════════════════════════════════════════════════════════════════════════
def fix_sidebar(sb):
    sb["fill"] = CARD
    sb["stroke"] = {"align": "inside", "thickness": {"right": 1}, "fill": BORDER}

    children = sb["children"]

    # sideTop — logo row
    side_top = next((c for c in children if c.get("name") == "sideTop"), None)
    if side_top:
        for sc in side_top.get("children", []):
            if sc.get("name") == "sideLabel":
                sc["fill"] = PRIMARY
                sc["fontFamily"] = "IBM Plex Mono"
                sc["fontWeight"] = "600"
            elif sc.get("type") == "icon_font":
                sc["fill"] = DIM

    # nav items  — icon + text
    NAV_ICONS = {
        "nav1": ("layout-dashboard", "Dashboard", False),
        "nav2": ("chart-candlestick", "Instr. Detail", True),
        "nav3": ("bar-chart-2", "Markets", False),
        "nav4": ("zap", "Intelligence", False),
        "nav5": ("filter", "Screener", False),
        "nav6": ("briefcase", "Portfolio", False),
        "nav7": ("network", "Graph", False),
    }
    for c in children:
        nav = NAV_ICONS.get(c.get("name"))
        if nav is None:
            continue
        icon_name, label, active = nav
        if active:
            c["fill"] = PRIMARY_DIM
            # remove old left-border stroke
            c.pop("stroke", None)
        else:
            c["fill"] = "#00000000"
            c.pop("stroke", None)

        for sc in c.get("children", []):
            if sc.get("type") == "icon_font":
                sc["iconFontName"] = icon_name
                sc["fill"] = PRIMARY if active else MUTED_FG
            elif sc.get("type") == "text":
                sc["content"] = label
                sc["fill"] = PRIMARY if active else MUTED_FG
                sc["fontWeight"] = "500" if active else "normal"

    # watchlist rows — ticker primary, price muted-fg, change positive
    WL_DATA = {
        "wl1": ("NVDA", "$875.40", "+0.58%"),
        "wl2": ("AAPL", "$173.42", "+1.37%"),
        "wl3": ("MSFT", "$419.28", "+0.82%"),
        "wl4": ("META", "$521.33", "+2.81%"),
    }
    for c in children:
        wl = WL_DATA.get(c.get("name"))
        if wl is None:
            continue
        _ticker, price, chg = wl
        kids = c.get("children", [])
        if len(kids) >= 3:
            kids[0]["fill"] = FG
            kids[0]["fontWeight"] = "600"
            kids[1]["fill"] = MUTED_FG
            kids[1]["content"] = price
            kids[2]["fill"] = POSITIVE
            kids[2]["content"] = chg

    # alert dots
    al1 = next((c for c in children if c.get("name") == "al1"), None)
    if al1:
        kids = al1.get("children", [])
        if kids:
            kids[0]["fill"] = NEGATIVE
        if len(kids) > 1:
            kids[1]["fill"] = FG
    al2 = next((c for c in children if c.get("name") == "al2"), None)
    if al2:
        kids = al2.get("children", [])
        if kids:
            kids[0]["fill"] = WARNING
        if len(kids) > 1:
            kids[1]["fill"] = FG

    # dividers
    for c in children:
        if c.get("type") == "rectangle":
            c["fill"] = BORDER

    # "add to watchlist" text
    add_wl = next((c for c in children if c.get("name") == "addWl"), None)
    if add_wl:
        add_wl["fill"] = DIM

    # alert label
    alert_label = next((c for c in children if c.get("name") == "alertLabel"), None)
    if alert_label:
        alert_label["fill"] = MUTED_FG

    # section labels (wlLabel, nav section, etc.)
    for c in children:
        if c.get("type") == "text" and c.get("name") in ("wlLabel", "navLabel"):
            c["fill"] = MUTED_FG

    # bottom items
    sBottom = next((c for c in children if c.get("name") == "sBottom"), None)
    if sBottom:
        for sc in sBottom.get("children", []):
            sc_type = sc.get("type")
            if sc_type == "icon_font":
                sc["fill"] = MUTED_FG
            elif sc_type == "text":
                sc["fill"] = MUTED_FG


# ════════════════════════════════════════════════════════════════════════════
# FIX 3  — Chart sub-pane architecture
# ════════════════════════════════════════════════════════════════════════════


def _make_chip(label, fill_col, text_col, stroke=None):
    node = {
        "type": "frame",
        "id": nid(),
        "name": f"chip_{label}",
        "height": 22,
        "cornerRadius": 3,
        "padding": [0, 6],
        "alignItems": "center",
    }
    if fill_col:
        node["fill"] = fill_col
    if stroke:
        node["stroke"] = {"align": "inside", "thickness": 0.5, "fill": stroke}
    node["children"] = [mono(label, 10, "500", text_col)]
    return node


def fix_chart_controls(skhpg):
    skhpg["height"] = 36
    skhpg["fill"] = CARD
    skhpg["stroke"] = {"align": "inside", "thickness": {"bottom": 1}, "fill": BORDER}
    skhpg.pop("layout", None)
    skhpg["gap"] = 8
    skhpg["padding"] = [0, 16]
    skhpg["alignItems"] = "center"

    tool_grp = {
        "type": "frame",
        "id": nid(),
        "name": "toolBtns",
        "gap": 4,
        "alignItems": "center",
        "children": [
            {
                "type": "frame",
                "id": nid(),
                "name": "toolBtn1",
                "width": 24,
                "height": 24,
                "fill": ELEVATED,
                "cornerRadius": 3,
                "justifyContent": "center",
                "alignItems": "center",
                "children": [icon("crosshair", 12, DIM)],
            },
            {
                "type": "frame",
                "id": nid(),
                "name": "toolBtn2",
                "width": 24,
                "height": 24,
                "fill": ELEVATED,
                "cornerRadius": 3,
                "justifyContent": "center",
                "alignItems": "center",
                "children": [icon("pencil", 12, DIM)],
            },
            {
                "type": "frame",
                "id": nid(),
                "name": "toolBtn3",
                "width": 24,
                "height": 24,
                "fill": ELEVATED,
                "cornerRadius": 3,
                "justifyContent": "center",
                "alignItems": "center",
                "children": [icon("eraser", 12, DIM)],
            },
            vsep(1, 20, BORDER),
        ],
    }

    TF_LABELS = [
        ("1D", True),
        ("5D", False),
        ("1M", False),
        ("3M", False),
        ("6M", False),
        ("1Y", False),
        ("All", False),
    ]
    tf_chips = []
    for label, active in TF_LABELS:
        chip = {
            "type": "frame",
            "id": nid(),
            "name": f"tf_{label}",
            "cornerRadius": 3,
            "padding": [3, 8],
            "alignItems": "center",
            "children": [mono(label, 11, "500" if active else "normal", FG if active else DIM)],
        }
        if active:
            chip["fill"] = ELEVATED
        tf_chips.append(chip)
    tf_chips.append(vsep(1, 20, BORDER))

    tf_grp = {"type": "frame", "id": nid(), "name": "tfGrp", "gap": 2, "alignItems": "center", "children": tf_chips}

    indicators_btn = {
        "type": "frame",
        "id": nid(),
        "name": "indicatorsBtn",
        "height": 24,
        "fill": ELEVATED,
        "cornerRadius": 3,
        "padding": [0, 8],
        "alignItems": "center",
        "children": [txt("Indicators ▾", 11, "normal", MUTED_FG)],
    }

    spacer = {"type": "frame", "id": nid(), "name": "spacer", "fill": "#00000000", "flex": 1, "children": []}

    chips_grp = {
        "type": "frame",
        "id": nid(),
        "name": "indicatorChips",
        "gap": 4,
        "alignItems": "center",
        "children": [
            _make_chip("MA50", PRIMARY_DIM, PRIMARY),
            _make_chip("MA200", AMBER_DIM, AMBER),
            _make_chip("Vol", ELEVATED, MUTED_FG),
            _make_chip("RSI", ELEVATED, MUTED_FG),
            _make_chip("MACD", None, DIM, stroke=BORDER),
        ],
    }

    skhpg["children"] = [tool_grp, tf_grp, indicators_btn, spacer, chips_grp]


def _h_gridlines(n=5, w=778):
    lines = []
    for i in range(n):
        lines.append(
            {
                "type": "rectangle",
                "id": nid(),
                "name": f"grid{i}",
                "x": 0,
                "y": round(i * 76),
                "width": w,
                "height": 0.5,
                "fill": BORDER,
                "opacity": 0.5,
            }
        )
    return lines


def _candles(n=20, pane_w=778, pane_h=380):
    """Simplified candlestick approximation."""
    candles = []
    cw, gap = 6, (pane_w - n * 6) // n
    x = 8
    for i in range(n):
        is_up = i % 3 != 0  # mix of up/down
        color = POSITIVE if is_up else NEGATIVE
        body_h = random.randint(20, 60)
        body_y = random.randint(80, pane_h - body_h - 40)
        # wick
        candles.append(
            {
                "type": "rectangle",
                "id": nid(),
                "name": f"wick{i}",
                "x": x + cw // 2,
                "y": body_y - 12,
                "width": 1,
                "height": body_h + 20,
                "fill": color,
            }
        )
        # body
        candles.append(
            {
                "type": "rectangle",
                "id": nid(),
                "name": f"body{i}",
                "x": x,
                "y": body_y,
                "width": cw,
                "height": body_h,
                "fill": color,
            }
        )
        x += cw + gap
    return candles


def _ma_curve(label, color, y_start, y_end, pane_w=778, n_pts=8):
    """Approximate an MA as a rectangle path label (placeholder)."""
    return {
        "type": "text",
        "id": nid(),
        "name": f"{label}_label",
        "x": 4,
        "y": y_start,
        "content": label,
        "fontFamily": "IBM Plex Mono",
        "fontSize": 8,
        "fontWeight": "500",
        "fill": color,
    }


def _y_axis_labels(labels, pane_w=40, pane_h=380):
    nodes = []
    step = pane_h // (len(labels) + 1)
    for i, lbl in enumerate(labels):
        nodes.append(mono(lbl, 10, "normal", DIM))
        nodes[-1].update({"type": "text", "id": nid(), "name": f"yL{i}", "x": 2, "y": step * (i + 1) - 6})
    return nodes


def fix_chart_area(whzsw):
    """Rebuild WHzSW as 3 stacked vertical panes."""
    whzsw["layout"] = "vertical"
    whzsw["y"] = 296
    whzsw["height"] = 508  # 380 + 72 + 56

    # ── OHLCV pane ──
    ohlcv_children = (
        _h_gridlines(5, 778)
        + _candles()
        + [
            # MA50 label stub (full curves require vector paths)
            {
                "type": "text",
                "id": nid(),
                "name": "ma50_stub",
                "x": 300,
                "y": 180,
                "content": "── MA50",
                "fontFamily": "IBM Plex Mono",
                "fontSize": 8,
                "fontWeight": "500",
                "fill": PRIMARY,
                "opacity": 0.85,
            },
            {
                "type": "text",
                "id": nid(),
                "name": "ma200_stub",
                "x": 300,
                "y": 220,
                "content": "── MA200",
                "fontFamily": "IBM Plex Mono",
                "fontSize": 8,
                "fontWeight": "500",
                "fill": AMBER,
                "opacity": 0.85,
            },
            # price callout
            {
                "type": "frame",
                "id": nid(),
                "name": "priceCallout",
                "x": 720,
                "y": 155,
                "fill": PRIMARY_DIM,
                "cornerRadius": 2,
                "padding": [2, 4],
                "alignItems": "center",
                "children": [mono("$875", 10, "600", PRIMARY)],
            },
            # y-axis labels (right 40px)
            *[
                {
                    "type": "text",
                    "id": nid(),
                    "name": f"yLbl{i}",
                    "x": 738,
                    "y": 60 + i * 64,
                    "content": str(800 + i * 40),
                    "fontFamily": "IBM Plex Mono",
                    "fontSize": 10,
                    "fontWeight": "normal",
                    "fill": DIM,
                }
                for i in range(5)
            ],
        ]
    )

    ohlcv_pane = {
        "type": "frame",
        "id": nid(),
        "name": "ohlcvPane",
        "width": 778,
        "height": 380,
        "fill": CARD,
        "layout": "none",
        "stroke": {"align": "inside", "thickness": {"bottom": 1}, "fill": BORDER},
        "children": ohlcv_children,
    }

    # ── Volume pane ──
    vol_bars = []
    x = 8
    cw, gap2 = 6, 32
    for i in range(20):
        is_up = i % 3 != 0
        color = POSITIVE if is_up else NEGATIVE
        bh = random.randint(12, 48)
        vol_bars.append(
            {
                "type": "rectangle",
                "id": nid(),
                "name": f"vbar{i}",
                "x": x,
                "y": 68 - bh,
                "width": cw,
                "height": bh,
                "fill": color,
                "opacity": 0.8,
            }
        )
        x += cw + gap2

    vol_pane = {
        "type": "frame",
        "id": nid(),
        "name": "volPane",
        "width": 778,
        "height": 72,
        "fill": CARD,
        "layout": "none",
        "stroke": {"align": "inside", "thickness": {"bottom": 1}, "fill": BORDER},
        "children": [
            {
                "type": "text",
                "id": nid(),
                "name": "volLabel",
                "x": 4,
                "y": 4,
                "content": "VOL",
                "fontFamily": "IBM Plex Mono",
                "fontSize": 9,
                "fontWeight": "normal",
                "fill": DIM,
            },
            {
                "type": "text",
                "id": nid(),
                "name": "volVal",
                "x": 700,
                "y": 4,
                "content": "52.1M",
                "fontFamily": "IBM Plex Mono",
                "fontSize": 9,
                "fontWeight": "normal",
                "fill": DIM,
            },
            {
                "type": "text",
                "id": nid(),
                "name": "volYLabel",
                "x": 740,
                "y": 30,
                "content": "50M",
                "fontFamily": "IBM Plex Mono",
                "fontSize": 9,
                "fontWeight": "normal",
                "fill": DIM,
            },
            *vol_bars,
        ],
    }

    # ── RSI pane ──
    rsi_pane = {
        "type": "frame",
        "id": nid(),
        "name": "rsiPane",
        "width": 778,
        "height": 56,
        "fill": CARD,
        "layout": "none",
        "stroke": {"align": "inside", "thickness": {"bottom": 1}, "fill": BORDER},
        "children": [
            {
                "type": "text",
                "id": nid(),
                "name": "rsiLabel",
                "x": 4,
                "y": 4,
                "content": "RSI(14)  63.4",
                "fontFamily": "IBM Plex Mono",
                "fontSize": 9,
                "fontWeight": "500",
                "fill": PRIMARY,
            },
            # overbought line y=17
            {
                "type": "rectangle",
                "id": nid(),
                "name": "obLine",
                "x": 0,
                "y": 17,
                "width": 738,
                "height": 0.5,
                "fill": NEGATIVE,
                "opacity": 0.45,
            },
            {
                "type": "text",
                "id": nid(),
                "name": "ob70",
                "x": 742,
                "y": 12,
                "content": "70",
                "fontFamily": "IBM Plex Mono",
                "fontSize": 8,
                "fontWeight": "normal",
                "fill": DIM,
            },
            # oversold line y=42
            {
                "type": "rectangle",
                "id": nid(),
                "name": "osLine",
                "x": 0,
                "y": 42,
                "width": 738,
                "height": 0.5,
                "fill": POSITIVE,
                "opacity": 0.45,
            },
            {
                "type": "text",
                "id": nid(),
                "name": "os30",
                "x": 742,
                "y": 38,
                "content": "30",
                "fontFamily": "IBM Plex Mono",
                "fontSize": 8,
                "fontWeight": "normal",
                "fill": DIM,
            },
            # RSI area fill (simplified rectangle)
            {
                "type": "rectangle",
                "id": nid(),
                "name": "rsiArea",
                "x": 0,
                "y": 17,
                "width": 738,
                "height": 18,
                "fill": PRIMARY,
                "opacity": 0.12,
            },
        ],
    }

    whzsw["children"] = [ohlcv_pane, vol_pane, rsi_pane]


def fix_yaxis(kq6x6):
    kq6x6["y"] = 296
    kq6x6["height"] = 380
    kq6x6["fill"] = CARD


def fix_xaxis(qzlxv):
    qzlxv["y"] = 804
    qzlxv["height"] = 20
    qzlxv["fill"] = CARD
    labels = ["Oct '25", "Nov '25", "Dec '25", "Jan '26", "Feb '26", "Mar '26", "Apr '26"]
    step = 778 // len(labels)
    qzlxv["layout"] = "none"
    qzlxv["children"] = [
        {
            "type": "text",
            "id": nid(),
            "name": f"xL{i}",
            "x": step * i + 4,
            "y": 4,
            "content": lbl,
            "fontFamily": "IBM Plex Mono",
            "fontSize": 9,
            "fontWeight": "normal",
            "fill": DIM,
        }
        for i, lbl in enumerate(labels)
    ]


def fix_left_toolbar(mvnvk):
    mvnvk["y"] = 296
    mvnvk["height"] = 508
    mvnvk["fill"] = CARD


# ════════════════════════════════════════════════════════════════════════════
# FIX 4  — OverviewBottom (ihGiy)
# ════════════════════════════════════════════════════════════════════════════


def _badge(text, fill_col, text_col, w=44, h=16):
    return {
        "type": "frame",
        "id": nid(),
        "name": f"badge_{text}",
        "width": w,
        "height": h,
        "cornerRadius": 2,
        "fill": fill_col,
        "justifyContent": "center",
        "alignItems": "center",
        "children": [txt(text, 9, "600", text_col)],
    }


def fix_overview_bottom(ihgiy):
    ihgiy["y"] = 824
    ihgiy["height"] = 236
    ihgiy["fill"] = CARD
    ihgiy["layout"] = "vertical"
    ihgiy["stroke"] = {"align": "inside", "thickness": {"top": 1}, "fill": BORDER}

    # ── ROW 1: KEY STATS (h=80) ──
    panel_a = {
        "type": "frame",
        "id": nid(),
        "name": "panelA_earnings",
        "height": 80,
        "flex": 1,
        "fill": CARD,
        "layout": "vertical",
        "gap": 4,
        "padding": [10, 16],
        "stroke": {"align": "inside", "thickness": {"right": 1}, "fill": BORDER},
        "children": [
            txt("NEXT EARNINGS", 10, "600", MUTED_FG),
            mono("July 24  ·  23 days", 12, "600", FG),
            {
                "type": "frame",
                "id": nid(),
                "name": "earningsRow",
                "gap": 12,
                "alignItems": "center",
                "children": [
                    txt("EPS est $0.64", 10, "normal", DIM),
                    txt("Rev est $36.8B", 10, "normal", DIM),
                    txt("Whisper $0.71", 10, "normal", POSITIVE),
                ],
            },
        ],
    }

    # analyst bar
    consensus_bar = {
        "type": "frame",
        "id": nid(),
        "name": "consensusBar",
        "width": 255,
        "height": 10,
        "cornerRadius": 2,
        "layout": "none",
        "children": [
            {
                "type": "rectangle",
                "id": nid(),
                "name": "barBuy",
                "x": 0,
                "y": 0,
                "width": 212,
                "height": 10,
                "fill": POSITIVE,
                "cornerRadius": 2,
            },
            {
                "type": "rectangle",
                "id": nid(),
                "name": "barHold",
                "x": 212,
                "y": 0,
                "width": 36,
                "height": 10,
                "fill": ELEVATED,
            },
            {
                "type": "rectangle",
                "id": nid(),
                "name": "barSell",
                "x": 248,
                "y": 0,
                "width": 7,
                "height": 10,
                "fill": NEGATIVE,
            },
        ],
    }
    panel_b = {
        "type": "frame",
        "id": nid(),
        "name": "panelB_analyst",
        "height": 80,
        "flex": 1,
        "fill": CARD,
        "layout": "vertical",
        "gap": 6,
        "padding": [10, 16],
        "stroke": {"align": "inside", "thickness": {"right": 1}, "fill": BORDER},
        "children": [
            txt("ANALYST CONSENSUS · 36", 10, "600", MUTED_FG),
            consensus_bar,
            mono("Avg Target $220.50  +12.3% upside", 10, "normal", MUTED_FG),
        ],
    }

    panel_c = {
        "type": "frame",
        "id": nid(),
        "name": "panelC_short",
        "height": 80,
        "flex": 1,
        "fill": CARD,
        "layout": "vertical",
        "gap": 4,
        "padding": [10, 16],
        "children": [
            txt("SHORT INTEREST", 10, "600", MUTED_FG),
            mono("0.8%  float", 12, "600", FG),
            {
                "type": "frame",
                "id": nid(),
                "name": "shortRow",
                "gap": 12,
                "alignItems": "center",
                "children": [
                    txt("Days to Cover 1.2", 10, "normal", DIM),
                    txt("Borrow 0.4%", 10, "normal", DIM),
                ],
            },
        ],
    }

    row1 = {
        "type": "frame",
        "id": nid(),
        "name": "row1KeyStats",
        "height": 80,
        "layout": "horizontal",
        "stroke": {"align": "inside", "thickness": {"bottom": 1}, "fill": BORDER},
        "children": [panel_a, panel_b, panel_c],
    }

    # ── ROW 2: TECHNICAL SIGNALS (h=48) ──
    tech_chips = [
        _badge("BETA 1.68", ELEVATED, FG, w=72),
        _badge("MA50 ▲", "#0D2926", POSITIVE, w=56),
        _badge("MA200 ▲", "#0D2926", POSITIVE, w=60),
        _badge("RSI 63.4 ●", ELEVATED, FG, w=72),
        _badge("BB EXPANDING", "#1A160A", WARNING, w=88),
        _badge("SHORT 0.8%", ELEVATED, DIM, w=72),
    ]
    row2 = {
        "type": "frame",
        "id": nid(),
        "name": "row2Tech",
        "height": 48,
        "layout": "horizontal",
        "padding": [0, 16],
        "gap": 8,
        "alignItems": "center",
        "stroke": {"align": "inside", "thickness": {"bottom": 1}, "fill": BORDER},
        "children": [
            txt("TECHNICAL", 10, "600", MUTED_FG),
            vsep(1, 28, BORDER),
            *tech_chips,
        ],
    }

    # ── ROW 3: INSIDER ACTIVITY (h=108) ──
    def insider_row(name, role, action, amount, date):
        action_fill = NEGATIVE if action == "SOLD" else POSITIVE
        badge = _badge(
            action, "#3D1010" if action == "SOLD" else "#0D2926", NEGATIVE if action == "SOLD" else POSITIVE, w=44, h=16
        )
        return {
            "type": "frame",
            "id": nid(),
            "name": f"insider_{name[:6]}",
            "height": 25,
            "layout": "horizontal",
            "padding": [0, 16],
            "alignItems": "center",
            "gap": 8,
            "stroke": {"align": "inside", "thickness": {"bottom": 1}, "fill": BORDER},
            "children": [
                {
                    "type": "frame",
                    "id": nid(),
                    "name": "insiderName",
                    "width": 108,
                    "children": [txt(name, 11, "normal", FG)],
                },
                txt(role, 9, "normal", DIM),
                badge,
                mono(amount, 10, "normal", NEGATIVE if action == "SOLD" else POSITIVE),
                {
                    "type": "frame",
                    "id": nid(),
                    "name": "insiderDate",
                    "flex": 1,
                    "justifyContent": "flex_end",
                    "children": [txt(date, 10, "normal", DIM)],
                },
            ],
        }

    row3_hdr = {
        "type": "frame",
        "id": nid(),
        "name": "insiderHdr",
        "height": 28,
        "layout": "horizontal",
        "padding": [0, 16],
        "alignItems": "center",
        "stroke": {"align": "inside", "thickness": {"bottom": 1}, "fill": BORDER},
        "children": [
            txt("INSIDER ACTIVITY", 10, "600", MUTED_FG),
            txt("30 days", 10, "normal", DIM),
            {"type": "frame", "id": nid(), "name": "insiderSpacer", "flex": 1, "children": []},
            txt("See all →", 11, "normal", PRIMARY),
        ],
    }

    row3 = {
        "type": "frame",
        "id": nid(),
        "name": "row3Insider",
        "height": 108,
        "layout": "vertical",
        "children": [
            row3_hdr,
            insider_row("Jensen Huang", "CEO", "SOLD", "$43.7M", "Jan 8"),
            insider_row("Mark Stevens", "Dir", "BOUGHT", "+$4.4M", "Feb 12"),
            insider_row("Colette Kress", "CFO", "SOLD", "$17.5M", "Mar 3"),
        ],
    }

    ihgiy["children"] = [row1, row2, row3]


# ════════════════════════════════════════════════════════════════════════════
# FIX 5 & 6  — RightPanel (92l9k)
# ════════════════════════════════════════════════════════════════════════════


def _node_ellipse(x, y, w, fill_col, stroke_col, stroke_w, label, font_size=10, label_color=FG):
    return {
        "type": "frame",
        "id": nid(),
        "name": f"node_{label}",
        "x": x - w // 2,
        "y": y - w // 2,
        "width": w,
        "height": w,
        "fill": fill_col,
        "stroke": {"align": "outside", "thickness": stroke_w, "fill": stroke_col},
        "cornerRadius": w // 2,
        "justifyContent": "center",
        "alignItems": "center",
        "children": [
            mono(label, font_size, "400", label_color) if w > 30 else txt(label, font_size, "400", label_color)
        ],
    }


def _node_below_label(x, y, label, font_size=9, color=MUTED_FG):
    """Float label below node."""
    return {
        "type": "text",
        "id": nid(),
        "name": f"lbl_{label}",
        "x": x - 24,
        "y": y + 16,
        "content": label,
        "fontFamily": "IBM Plex Sans",
        "fontSize": font_size,
        "fontWeight": "normal",
        "fill": color,
    }


def _edge_line(x1, y1, x2, y2, color, opacity=1.0, label="", label_color=DIM):
    """Approximate edge as a horizontal or diagonal rectangle stub."""
    # Use text as placeholder for the edge relationship label
    mid_x = (x1 + x2) // 2
    mid_y = (y1 + y2) // 2
    nodes = []
    if label:
        nodes.append(
            {
                "type": "text",
                "id": nid(),
                "name": f"edge_{label}",
                "x": mid_x - 12,
                "y": mid_y,
                "content": label,
                "fontFamily": "IBM Plex Sans",
                "fontSize": 8,
                "fontWeight": "normal",
                "fill": label_color,
                "opacity": opacity,
            }
        )
    return nodes


def fix_right_panel(rp):
    rp["height"] = 800
    rp["fill"] = CARD
    rp["stroke"] = {"align": "inside", "thickness": {"left": 1}, "fill": BORDER}

    # ── EntityGraphCard (top h=412) ──
    graph_hdr = {
        "type": "frame",
        "id": nid(),
        "name": "egHdr2",
        "width": 380,
        "height": 32,
        "layout": "horizontal",
        "padding": [0, 16],
        "alignItems": "center",
        "stroke": {"align": "inside", "thickness": {"bottom": 1}, "fill": BORDER},
        "children": [
            txt("ENTITY GRAPH", 10, "600", MUTED_FG),
            {"type": "frame", "id": nid(), "name": "egSpacer", "flex": 1, "children": []},
            txt("Expand →", 11, "normal", PRIMARY),
        ],
    }

    # NVDA as roundrectangle (frame with low cornerRadius)
    nvda_node = {
        "type": "frame",
        "id": nid(),
        "name": "nodeNVDA",
        "x": 144,
        "y": 134,
        "width": 52,
        "height": 52,
        "fill": CARD,
        "cornerRadius": 8,
        "stroke": {"align": "outside", "thickness": 2, "fill": PRIMARY},
        "justifyContent": "center",
        "alignItems": "center",
        "children": [mono("NVDA", 12, "600", PRIMARY)],
    }

    graph_nodes = [
        nvda_node,
        # MSFT
        {
            "type": "frame",
            "id": nid(),
            "name": "nodeMSFT",
            "x": 54,
            "y": 70,
            "width": 36,
            "height": 36,
            "cornerRadius": 18,
            "fill": PRIMARY_DIM,
            "stroke": {"align": "outside", "thickness": 1, "fill": PRIMARY},
            "justifyContent": "center",
            "alignItems": "center",
            "children": [txt("MSFT", 9, "normal", FG)],
        },
        # MSFT label
        {
            "type": "text",
            "id": nid(),
            "name": "lblMSFT",
            "x": 52,
            "y": 110,
            "content": "MSFT",
            "fontFamily": "IBM Plex Sans",
            "fontSize": 10,
            "fontWeight": "normal",
            "fill": FG,
        },
        # AMD
        {
            "type": "frame",
            "id": nid(),
            "name": "nodeAMD",
            "x": 251,
            "y": 79,
            "width": 34,
            "height": 34,
            "cornerRadius": 17,
            "fill": "#2D1515",
            "stroke": {"align": "outside", "thickness": 1, "fill": NEGATIVE},
            "justifyContent": "center",
            "alignItems": "center",
            "children": [txt("AMD", 9, "normal", FG)],
        },
        {
            "type": "text",
            "id": nid(),
            "name": "lblAMD",
            "x": 251,
            "y": 117,
            "content": "AMD",
            "fontFamily": "IBM Plex Sans",
            "fontSize": 10,
            "fontWeight": "normal",
            "fill": FG,
        },
        # TSMC
        {
            "type": "frame",
            "id": nid(),
            "name": "nodeTSMC",
            "x": 264,
            "y": 196,
            "width": 28,
            "height": 28,
            "cornerRadius": 14,
            "fill": ELEVATED,
            "stroke": {"align": "outside", "thickness": 0.5, "fill": MUTED_FG},
            "justifyContent": "center",
            "alignItems": "center",
            "children": [txt("TSMC", 8, "normal", MUTED_FG)],
        },
        {
            "type": "text",
            "id": nid(),
            "name": "lblTSMC",
            "x": 258,
            "y": 228,
            "content": "TSMC",
            "fontFamily": "IBM Plex Sans",
            "fontSize": 9,
            "fontWeight": "normal",
            "fill": MUTED_FG,
        },
        # Jensen H
        {
            "type": "frame",
            "id": nid(),
            "name": "nodeJH",
            "x": 83,
            "y": 239,
            "width": 26,
            "height": 26,
            "cornerRadius": 13,
            "fill": ELEVATED,
            "stroke": {"align": "outside", "thickness": 1, "fill": WARNING},
            "justifyContent": "center",
            "alignItems": "center",
            "children": [txt("JH", 8, "normal", MUTED_FG)],
        },
        {
            "type": "text",
            "id": nid(),
            "name": "lblJH",
            "x": 68,
            "y": 270,
            "content": "Jensen H.",
            "fontFamily": "IBM Plex Sans",
            "fontSize": 9,
            "fontWeight": "normal",
            "fill": MUTED_FG,
        },
        # SoftBank
        {
            "type": "frame",
            "id": nid(),
            "name": "nodeSB",
            "x": 157,
            "y": 271,
            "width": 22,
            "height": 22,
            "cornerRadius": 11,
            "fill": AMBER_DIM,
            "stroke": {"align": "outside", "thickness": 0.5, "fill": AMBER},
            "justifyContent": "center",
            "alignItems": "center",
            "children": [txt("SB", 7, "normal", DIM)],
        },
        {
            "type": "text",
            "id": nid(),
            "name": "lblSB",
            "x": 144,
            "y": 297,
            "content": "SoftBank",
            "fontFamily": "IBM Plex Sans",
            "fontSize": 9,
            "fontWeight": "normal",
            "fill": DIM,
        },
        # edge labels
        *_edge_line(170, 160, 72, 88, MUTED_FG, label="partner"),
        *_edge_line(170, 160, 268, 96, NEGATIVE, label="rival", label_color=NEGATIVE),
        *_edge_line(170, 160, 278, 210, DIM, label="supplier"),
        *_edge_line(170, 160, 96, 252, MUTED_FG, label="CEO"),
        *_edge_line(170, 160, 168, 282, AMBER, 0.5, "investor", AMBER),
    ]

    graph_canvas = {
        "type": "frame",
        "id": nid(),
        "name": "egCanvas2",
        "width": 380,
        "height": 356,
        "fill": BG,
        "layout": "none",
        "children": graph_nodes,
    }

    graph_legend = {
        "type": "frame",
        "id": nid(),
        "name": "egLegend2",
        "width": 380,
        "height": 24,
        "fill": CARD,
        "layout": "horizontal",
        "padding": [4, 12],
        "gap": 10,
        "alignItems": "center",
        "stroke": {"align": "inside", "thickness": {"top": 1}, "fill": BORDER},
        "children": [
            {"type": "rectangle", "id": nid(), "name": "lgInstr", "width": 8, "height": 8, "fill": PRIMARY},
            txt("Instrument", 8, "normal", DIM),
            {"type": "ellipse", "id": nid(), "name": "lgCo", "width": 6, "height": 6, "fill": PRIMARY},
            txt("Company", 8, "normal", DIM),
            {"type": "ellipse", "id": nid(), "name": "lgPerson", "width": 6, "height": 6, "fill": WARNING},
            txt("Person", 8, "normal", DIM),
            txt("── Partner", 8, "normal", MUTED_FG),
            txt("╌╌ Rival", 8, "normal", NEGATIVE),
        ],
    }

    eg_card = {
        "type": "frame",
        "id": "fq1Zu",
        "name": "EntityGraphCard",
        "width": 380,
        "height": 412,
        "fill": CARD,
        "layout": "vertical",
        "stroke": {"align": "inside", "thickness": {"left": 1}, "fill": BORDER},
        "children": [graph_hdr, graph_canvas, graph_legend],
    }

    # ── Related Content (bottom h=388) ──
    rc_hdr = {
        "type": "frame",
        "id": nid(),
        "name": "rcHdr2",
        "width": 380,
        "height": 32,
        "layout": "horizontal",
        "padding": [0, 16],
        "alignItems": "center",
        "stroke": {"align": "inside", "thickness": {"bottom": 1}, "fill": BORDER},
        "children": [
            txt("RELATED CONTENT", 10, "600", MUTED_FG),
            {"type": "frame", "id": nid(), "name": "rcSpacer", "flex": 1, "children": []},
            txt("See all →", 11, "normal", PRIMARY),
        ],
    }

    NEWS = [
        ("DEEP", PRIMARY_DIM, PRIMARY, "Reuters · 2h", "NVIDIA H100 Demand Surge Drives Record Data Center Revenue"),
        ("MED", "#2A1F00", WARNING, "Bloomberg · 5h", "China Chip Export Restrictions Could Weigh on NVDA Q3 Outlook"),
        ("LIGHT", ELEVATED, MUTED_FG, "WSJ · 8h", "Analysts Raise NVDA Price Targets Ahead of Blackwell Architecture"),
        ("MED", "#2A1F00", WARNING, "FT · 12h", "NVDA Supply Chain Analysis: Samsung Foundry Deal Strengthens"),
        (
            "BUY",
            "#0D2926",
            POSITIVE,
            "Morgan Stanley · 14h",
            "Morgan Stanley Upgrades NVDA to Overweight, Raises Target $1,100",
        ),
        ("LGT", ELEVATED, DIM, "Reuters · 1d", "NVIDIA Joins NVIDIA-Azure Cloud Alliance for AI Chip"),
    ]

    def news_row(tier, tier_fill, tier_text, source, headline):
        badge = {
            "type": "frame",
            "id": nid(),
            "name": f"tier_{tier}",
            "width": 36,
            "height": 18,
            "cornerRadius": 2,
            "fill": tier_fill,
            "justifyContent": "center",
            "alignItems": "center",
            "children": [txt(tier, 9, "600", tier_text)],
        }
        content = {
            "type": "frame",
            "id": nid(),
            "name": "newsContent",
            "layout": "vertical",
            "gap": 3,
            "flex": 1,
            "children": [
                txt(source, 10, "normal", DIM),
                txt(headline[:60], 12, "normal", FG),
            ],
        }
        return {
            "type": "frame",
            "id": nid(),
            "name": f"newsRow_{tier}",
            "height": 56,
            "layout": "horizontal",
            "padding": [8, 16, 8, 12],
            "gap": 10,
            "alignItems": "flex_start",
            "stroke": {"align": "inside", "thickness": {"bottom": 1}, "fill": BORDER},
            "children": [badge, content],
        }

    rc_card = {
        "type": "frame",
        "id": "fkJw9",
        "name": "RelatedContent",
        "width": 380,
        "height": 388,
        "fill": CARD,
        "layout": "vertical",
        "stroke": {"align": "inside", "thickness": {"top": 1, "left": 1}, "fill": BORDER},
        "children": [rc_hdr, *[news_row(*row) for row in NEWS]],
    }

    rp["children"] = [eg_card, rc_card]


# ════════════════════════════════════════════════════════════════════════════
# MAIN
# ════════════════════════════════════════════════════════════════════════════
def main():
    random.seed(42)

    with open(SRC) as f:
        data = json.load(f)

    state_a = find_node(data, "b8vqT")
    assert state_a, "State A (b8vqT) not found"

    # ── patch State A container ──────────────────────────────────────────────
    state_a["fill"] = BG
    state_a["height"] = 1060

    # ── grow Sidebar height ──────────────────────────────────────────────────
    sidebar = find_node(data, "VUjGx")
    sidebar["height"] = 1012

    fix_topbar(find_node(data, "Skz8Y"))
    fix_sidebar(sidebar)
    fix_chart_controls(find_node(data, "Skhpg"))
    fix_chart_area(find_node(data, "WHzSW"))
    fix_yaxis(find_node(data, "kQ6X6"))
    fix_xaxis(find_node(data, "QZlxv"))
    fix_left_toolbar(find_node(data, "mvNVk"))
    fix_overview_bottom(find_node(data, "ihGiy"))
    fix_right_panel(find_node(data, "92l9k"))

    with open(DST, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print(f"✓ Wrote {DST}")
    print("  State A h=1060, all 6 fixes applied")


if __name__ == "__main__":
    main()
