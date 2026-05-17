# ruff: noqa: S311
#!/usr/bin/env python3
"""Apply 6 design fixes to worldview-mvp_v2.pen — State A Overview Tab redesign."""

import json
import random
import shutil
from pathlib import Path

random.seed(42)

# ─── Tokens ──────────────────────────────────────────────────────────────────
BG = "#080A0E"
CARD = "#10141C"
ELEVATED = "#181D28"
BORDER = "#232A36"
FG = "#D1D4DC"
MFG = "#787B86"  # muted-foreground
DIM = "#4C5260"
PRIMARY = "#0EA5E9"
PDIM = "#0EA5E920"  # primary-dim
AMBER = "#F0C040"
ADIM = "#F0C04018"  # amber-dim
POS = "#26A69A"  # positive
NEG = "#EF5350"  # negative
WARN = "#F59E0B"  # warning

FILE = Path(__file__).parent.parent / "apps/worldview-web/designs/worldview-mvp_v2.pen"

# ─── Load & backup ────────────────────────────────────────────────────────────
with open(FILE) as f:
    data = json.load(f)
shutil.copy(FILE, FILE.with_suffix(".pen.bak"))
print("Backed up to .pen.bak")


# ─── Utilities ────────────────────────────────────────────────────────────────
def find_node(node, tid):
    if isinstance(node, dict):
        if node.get("id") == tid:
            return node
        for v in node.values():
            if isinstance(v, list):
                for c in v:
                    r = find_node(c, tid)
                    if r:
                        return r
    return None


_ctr = [0]


def nid(prefix="N"):
    _ctr[0] += 1
    return f"{prefix}{_ctr[0]:04d}"


def stroke(side="all", color=BORDER, thickness=1):
    t = thickness if side == "all" else {side: thickness}
    return {"align": "inside", "thickness": t, "fill": color}


def txt(name, content, fill, family, size, weight, x=None, y=None, ls=None):
    n = {
        "type": "text",
        "id": nid(),
        "name": name,
        "fill": fill,
        "content": content,
        "fontFamily": family,
        "fontSize": size,
        "fontWeight": weight,
    }
    if x is not None:
        n["x"] = x
    if y is not None:
        n["y"] = y
    if ls is not None:
        n["letterSpacing"] = ls
    return n


def icon(name, icon_name, w=16, h=16, fill=MFG, x=None, y=None):
    n = {
        "type": "icon_font",
        "id": nid(),
        "name": name,
        "iconFontName": icon_name,
        "iconFontFamily": "lucide",
        "width": w,
        "height": h,
        "fill": fill,
    }
    if x is not None:
        n["x"] = x
    if y is not None:
        n["y"] = y
    return n


def ellipse(name, w, h, fill, x=None, y=None, stk=None):
    n = {"type": "ellipse", "id": nid(), "name": name, "fill": fill, "width": w, "height": h}
    if x is not None:
        n["x"] = x
    if y is not None:
        n["y"] = y
    if stk:
        n["stroke"] = stk
    return n


def rect(name, w, h, fill=BORDER, x=None, y=None, stk=None, cr=None):
    n = {"type": "rectangle", "id": nid(), "name": name, "width": w, "height": h}
    if fill is not None:
        n["fill"] = fill
    if x is not None:
        n["x"] = x
    if y is not None:
        n["y"] = y
    if stk:
        n["stroke"] = stk
    if cr:
        n["cornerRadius"] = cr
    return n


def frame(
    name,
    w,
    h,
    fill=None,
    x=None,
    y=None,
    layout=None,
    gap=None,
    pad=None,
    ai=None,
    jc=None,
    cr=None,
    stk=None,
    children=None,
):
    n = {"type": "frame", "id": nid(), "name": name, "width": w, "height": h}
    if fill is not None:
        n["fill"] = fill
    if x is not None:
        n["x"] = x
    if y is not None:
        n["y"] = y
    if layout is not None:
        n["layout"] = layout
    if gap is not None:
        n["gap"] = gap
    if pad is not None:
        n["padding"] = pad
    if ai is not None:
        n["alignItems"] = ai
    if jc is not None:
        n["justifyContent"] = jc
    if cr is not None:
        n["cornerRadius"] = cr
    if stk is not None:
        n["stroke"] = stk
    n["children"] = children or []
    return n


def spacer():
    return {"type": "frame", "id": nid(), "name": "spacer", "width": "fill_container", "height": 1}


def chip(label, bg, fg_color, stk_color=None):
    n = frame(f"chip_{label[:4]}", None, 22, bg, cr=3, pad=[0, 6], ai="center")
    if stk_color:
        n["stroke"] = {"align": "inside", "thickness": 0.5, "fill": stk_color}
    n["children"] = [txt(f"chip_{label[:4]}_t", label, fg_color, "IBM Plex Mono", 10, "500")]
    return n


def path_node(name, geometry, vb_w, vb_h, stk_fill, stk_thick=1.0, fill=None, opacity=None):
    n = {
        "type": "path",
        "id": nid(),
        "name": name,
        "x": 0,
        "y": 0,
        "geometry": geometry,
        "viewBox": [0, 0, vb_w, vb_h],
        "width": vb_w,
        "height": vb_h,
        "stroke": {"align": "center", "thickness": stk_thick, "fill": stk_fill},
    }
    if fill:
        n["fill"] = fill
    if opacity is not None:
        n["opacity"] = opacity
    return n


def line_node(name, x, y, w, stk_fill, stk_thick=1.0, opacity=None):
    n = {
        "type": "line",
        "id": nid(),
        "name": name,
        "x": x,
        "y": y,
        "width": w,
        "height": 1,
        "stroke": {"align": "center", "thickness": stk_thick, "fill": stk_fill},
    }
    if opacity is not None:
        n["opacity"] = opacity
    return n


# ═══════════════════════════════════════════════════════════════════════════════
# FIX 1 — TopBar (Skz8Y)
# ═══════════════════════════════════════════════════════════════════════════════
topbar = find_node(data, "Skz8Y")
topbar["fill"] = CARD
topbar["stroke"] = stroke("bottom", BORDER, 1)

# Remove old right elements
remove_ids = {"GE2OF", "ksmg4", "O5L8B"}
topbar["children"] = [c for c in topbar["children"] if c["id"] not in remove_ids]

# Update logo to use PRIMARY + IBM Plex Mono
logo = find_node(topbar, "wI1eR")
if logo:
    logo["fill"] = PRIMARY
    logo["fontFamily"] = "IBM Plex Mono"

# Update mktStatus colors
mkt = find_node(topbar, "BVUqK")
if mkt:
    for c in mkt.get("children", []):
        if c.get("name") == "greenDot":
            c["fill"] = POS
            c["width"] = 8
            c["height"] = 8
        elif c.get("name") == "mktText":
            c["fill"] = MFG
            c["fontFamily"] = "IBM Plex Sans"

# TopBar w=1440, h=48. Positions from right (16px padding):
# avatar: x=1396 (1440-16-28), y=10; bell: x=1368 (1396-12-16), y=16; vsep: x=1359

vsep_r = rect("vsepRight", 1, 20, BORDER, x=1359, y=14)
bell_ic = icon("bellIcon", "bell", 16, 16, MFG, x=1368, y=16)
avatar = frame(
    "avatarFrame",
    28,
    28,
    PDIM,
    x=1396,
    y=10,
    cr=14,
    jc="center",
    ai="center",
    children=[txt("avatarAR", "AR", PRIMARY, "IBM Plex Mono", 11, "600")],
)

topbar["children"].extend([vsep_r, bell_ic, avatar])
print("FIX 1 TopBar done")


# ═══════════════════════════════════════════════════════════════════════════════
# FIX 2 — Sidebar (VUjGx)
# ═══════════════════════════════════════════════════════════════════════════════
sidebar = find_node(data, "VUjGx")
sidebar["fill"] = CARD
sidebar["stroke"] = stroke("right", BORDER, 1)
sidebar["layout"] = "none"


def nav_item(icon_name, label, active=False, y=0):
    bg = PDIM if active else None
    tf = PRIMARY if active else MFG
    icf = PRIMARY if active else MFG
    n = frame(f"nav_{label[:4]}", 200, 36, bg, x=0, y=y, cr=4 if active else None, gap=8, pad=[0, 12], ai="center")
    n["children"] = [
        icon(f"nav_{label[:4]}_i", icon_name, 16, 16, icf),
        txt(f"nav_{label[:4]}_t", label, tf, "IBM Plex Sans", 13, "500" if active else "400"),
    ]
    return n


def wl_row(ticker, price, change, y):
    n = frame(f"wl_{ticker}", 200, 32, x=0, y=y, pad=[0, 12], jc="space_between", ai="center")
    n["children"] = [
        txt(f"wl_{ticker}_t", ticker, FG, "IBM Plex Mono", 12, "600"),
        txt(f"wl_{ticker}_p", price, MFG, "IBM Plex Mono", 11, "400"),
        txt(f"wl_{ticker}_c", change, POS, "IBM Plex Mono", 10, "400"),
    ]
    return n


def alert_row(dot_color, text, time_str, y):
    n = frame(f"al_{text[:4]}", 200, 28, x=0, y=y, gap=6, pad=[0, 12], ai="center")
    n["children"] = [
        ellipse(f"al_{text[:4]}_d", 6, 6, dot_color),
        txt(f"al_{text[:4]}_tx", text, FG, "IBM Plex Sans", 11, "400"),
        txt(f"al_{text[:4]}_tm", time_str, DIM, "IBM Plex Mono", 10, "400"),
    ]
    return n


def setting_row(icon_name, label, y):
    n = frame(f"st_{label[:4]}", 200, 32, x=0, y=y, gap=8, pad=[0, 12], ai="center")
    n["children"] = [
        icon(f"st_{label[:4]}_i", icon_name, 16, 16, DIM),
        txt(f"st_{label[:4]}_t", label, MFG, "IBM Plex Sans", 13, "400"),
    ]
    return n


# Logo row (y=0, h=44, border-bottom)
logo_row = frame(
    "logoRow",
    200,
    44,
    CARD,
    x=0,
    y=0,
    gap=8,
    pad=[0, 16],
    ai="center",
    jc="space_between",
    stk=stroke("bottom", BORDER, 1),
)
logo_row["children"] = [
    ellipse("logoDot", 6, 6, PRIMARY),
    txt("logoTxt", "WORLDVIEW", PRIMARY, "IBM Plex Mono", 13, "600"),
    icon("collapseI", "chevron-left", 16, 16, DIM),
]

sidebar["children"] = [
    logo_row,
    # Section label WORLDVIEW at y=52 (44+8 top padding)
    txt("wvSectLbl", "WORLDVIEW", MFG, "IBM Plex Sans", 10, "600", x=12, y=52, ls=0.8),
    nav_item("layout-dashboard", "Dashboard", False, 68),
    nav_item("chart-candlestick", "Instr. Detail", True, 104),
    nav_item("bar-chart-2", "Markets", False, 140),
    nav_item("zap", "Intelligence", False, 176),
    nav_item("filter", "Screener", False, 212),
    nav_item("briefcase", "Portfolio", False, 248),
    nav_item("network", "Graph", False, 284),
    rect("navDiv", 200, 1, BORDER, x=0, y=320),
    txt("wlSectLbl", "WATCHLIST", MFG, "IBM Plex Sans", 10, "600", x=12, y=329, ls=0.8),
    wl_row("NVDA", "$875.40", "+0.58%", 345),
    wl_row("AAPL", "$173.42", "+1.37%", 377),
    wl_row("MSFT", "$419.28", "+0.82%", 409),
    wl_row("META", "$521.33", "+2.81%", 441),
    txt("addWlTxt", "+ Add to watchlist", DIM, "IBM Plex Sans", 11, "400", x=12, y=479),
    rect("wlDiv", 200, 1, BORDER, x=0, y=497),
    txt("alSectLbl", "RECENT ALERTS", MFG, "IBM Plex Sans", 10, "600", x=12, y=505, ls=0.8),
    alert_row(NEG, "AAPL options spike", "1m", 521),
    alert_row(WARN, "NVDA RSI overbought", "4m", 549),
    rect("botDiv", 200, 1, BORDER, x=0, y=787),
    setting_row("settings", "Settings", 788),
    setting_row("help-circle", "Help", 820),
]
print("FIX 2 Sidebar done")


# ═══════════════════════════════════════════════════════════════════════════════
# FIX 3 — Chart (Skhpg + WHzSW + kQ6X6 + QZlxv)
# ═══════════════════════════════════════════════════════════════════════════════

# --- Skhpg (ChartControls): rebuild as horizontal auto-layout, h=36 ---
skhpg = find_node(data, "Skhpg")
skhpg["height"] = 36
skhpg["fill"] = CARD
skhpg["stroke"] = stroke("bottom", BORDER, 1)
skhpg.pop("layout", None)  # default horizontal
skhpg["gap"] = 8
skhpg["padding"] = [0, 16]
skhpg["alignItems"] = "center"


def tool_btn(icon_name):
    return frame(
        f"tool_{icon_name[:4]}",
        24,
        24,
        ELEVATED,
        cr=3,
        jc="center",
        ai="center",
        children=[icon(f"ti_{icon_name[:4]}", icon_name, 14, 14, DIM)],
    )


def tf_btn(label, active=False):
    n = frame(f"tf_{label}", None, 24, ELEVATED if active else None, cr=3, pad=[0, 8], ai="center")
    n["children"] = [
        txt(f"tf_{label}_t", label, FG if active else DIM, "IBM Plex Mono", 11, "500" if active else "400")
    ]
    return n


tool_group = frame(
    "toolGroup",
    None,
    None,
    gap=4,
    ai="center",
    children=[
        tool_btn("crosshair"),
        tool_btn("pencil"),
        tool_btn("eraser"),
    ],
)
vsep_a = rect("vsepToolTf", 1, 20, BORDER)
tf_group = frame(
    "tfGroup",
    None,
    None,
    gap=2,
    ai="center",
    children=[
        tf_btn("1D", True),
        tf_btn("5D"),
        tf_btn("1M"),
        tf_btn("3M"),
        tf_btn("6M"),
        tf_btn("1Y"),
        tf_btn("All"),
    ],
)
vsep_b = rect("vsepTfInd", 1, 20, BORDER)
ind_btn = frame(
    "indBtn",
    None,
    24,
    ELEVATED,
    cr=3,
    pad=[0, 8],
    ai="center",
    children=[txt("indBtnT", "Indicators ▾", MFG, "IBM Plex Sans", 11, "400")],
)
chips_grp = frame(
    "chipsGroup",
    None,
    None,
    gap=4,
    ai="center",
    children=[
        chip("MA50", PDIM, PRIMARY),
        chip("MA200", ADIM, AMBER),
        chip("Vol", ELEVATED, MFG),
        chip("RSI", ELEVATED, MFG),
        chip("MACD", None, DIM, BORDER),
    ],
)

skhpg["children"] = [tool_group, vsep_a, tf_group, vsep_b, ind_btn, spacer(), chips_grp]

# --- WHzSW (ChartArea): update position and rebuild with 3 stacked panes ---
whzsw = find_node(data, "WHzSW")
whzsw["y"] = 296  # skhpg y=260 + h=36
whzsw["height"] = 508  # 380+72+56
whzsw["fill"] = CARD
whzsw["layout"] = "vertical"

# Generate candlestick data (20 candles, upward trend)
PW, PH = 778, 380
PMIN, PMAX = 800, 960
DRAW_H = PH - 40  # 20px top/bottom padding


def price_y(p):
    return PH - 20 - (p - PMIN) / (PMAX - PMIN) * DRAW_H


N_C = 20
CW = 8
X0 = 18
X_STEP = int((660 - X0) / (N_C - 1))

candles = []
close = 840.0
for i in range(N_C):
    op = close
    close = max(PMIN + 4, min(PMAX - 4, op + random.gauss(0.6, 7)))
    hi = max(op, close) + random.uniform(2, 6)
    lo = min(op, close) - random.uniform(2, 6)
    cx = X0 + i * X_STEP
    candles.append((cx, op, hi, lo, close))


def make_ohlcv():
    ch = []
    # Grid lines (5)
    for i in range(1, 6):
        yg = i * PH // 6
        ch.append(rect(f"grid{i}", PW - 40, 1, BORDER + "80", x=0, y=yg))

    # Candles
    for ci, (cx, op, hi, lo, cl) in enumerate(candles):
        is_bull = cl >= op
        color = POS if is_bull else NEG
        by = int(price_y(max(op, cl)))
        bh = max(2, int(price_y(min(op, cl))) - by)
        ch.append(rect(f"cbody{ci}", CW, bh, color, x=cx, y=by))
        wy = int(price_y(hi))
        wh = max(1, int(price_y(lo)) - wy)
        ch.append(rect(f"cwick{ci}", 1, wh, color, x=cx + CW // 2, y=wy))

    # MA50 line
    pts50 = [(18, 292), (100, 268), (200, 252), (300, 232), (420, 210), (540, 192), (635, 178)]
    d50 = "M " + " L ".join(f"{x} {y}" for x, y in pts50)
    ch.append(path_node("ma50Line", d50, PW, PH, PRIMARY, 1.2, opacity=0.85))

    # MA200 line
    pts200 = [(18, 322), (100, 312), (200, 296), (300, 278), (420, 258), (540, 240), (635, 226)]
    d200 = "M " + " L ".join(f"{x} {y}" for x, y in pts200)
    ch.append(path_node("ma200Line", d200, PW, PH, AMBER, 1.2, opacity=0.85))

    # Price callout (last close)
    last_cl = int(candles[-1][4])
    callout_y = int(price_y(last_cl)) - 8
    ch.append(
        frame(
            "priceCallout",
            38,
            16,
            PDIM,
            x=700,
            y=callout_y,
            cr=2,
            jc="center",
            ai="center",
            children=[txt("priceTxt", f"${last_cl}", PRIMARY, "IBM Plex Mono", 10, "600")],
        )
    )

    # Y-axis labels (inside pane, right side)
    for pl in [800, 840, 880, 920, 960]:
        yp = int(price_y(pl)) - 5
        ch.append(txt(f"yax{pl}", str(pl), DIM, "IBM Plex Mono", 10, "400", x=742, y=yp))

    return frame("OHLCVPane", PW, 380, CARD, x=0, y=0, layout="none", stk=stroke("bottom", BORDER, 1), children=ch)


def make_volume():
    ch = []
    ch.append(txt("volLbl", "VOL", DIM, "IBM Plex Mono", 9, "400", x=4, y=4))
    ch.append(txt("volVal", "52.1M", DIM, "IBM Plex Mono", 9, "400", x=700, y=4))
    ch.append(txt("volYax", "50M", DIM, "IBM Plex Mono", 9, "400", x=742, y=16))
    MAX_VH = 56  # 72 - 16
    for i in range(N_C):
        vh = int(random.uniform(18, MAX_VH))
        is_up = random.random() > 0.35
        color = POS + "CC" if is_up else NEG + "CC"
        bx = X0 + i * X_STEP
        ch.append(rect(f"volb{i}", CW, vh, color, x=bx, y=72 - 4 - vh))
    return frame("VolumePane", PW, 72, CARD, x=0, y=0, layout="none", stk=stroke("bottom", BORDER, 1), children=ch)


def make_rsi():
    ch = []
    ch.append(txt("rsiLbl", "RSI(14) 63.4", PRIMARY, "IBM Plex Mono", 9, "500", x=4, y=4))
    # Overbought at y=17
    ch.append(line_node("rsiOB", 0, 17, PW - 40, NEG, 0.5, opacity=0.45))
    ch.append(txt("rsi70", "70", DIM, "IBM Plex Mono", 8, "400", x=742, y=13))
    # Oversold at y=42
    ch.append(line_node("rsiOS", 0, 42, PW - 40, POS, 0.5, opacity=0.45))
    ch.append(txt("rsi30", "30", DIM, "IBM Plex Mono", 8, "400", x=742, y=38))
    # RSI area fill
    pts = "M 18 38 L 120 32 L 200 29 L 300 25 L 420 21 L 540 18 L 635 20"
    area_d = pts + " L 635 56 L 18 56 Z"
    ch.append(path_node("rsiArea", area_d, PW, 56, "#00000000", 0, fill=PRIMARY + "1F"))
    # RSI line
    ch.append(path_node("rsiLine", pts, PW, 56, PRIMARY, 1.2))
    return frame("RSIPane", PW, 56, CARD, x=0, y=0, layout="none", stk=stroke("bottom", BORDER, 1), children=ch)


whzsw["children"] = [make_ohlcv(), make_volume(), make_rsi()]

# Update LeftToolbar position
ltb = find_node(data, "mvNVk")
if ltb:
    ltb["y"] = 296
    ltb["height"] = 508

# Update YAxis — reposition + update children colors
yaxis = find_node(data, "kQ6X6")
if yaxis:
    yaxis["y"] = 296
    yaxis["height"] = 380
    for c in yaxis.get("children", []):
        if c.get("type") == "text":
            c["fill"] = DIM
            c["fontFamily"] = "IBM Plex Mono"
            c["fontSize"] = 10

# Rebuild XAxisLabels
xaxis = find_node(data, "QZlxv")
if xaxis:
    xaxis["y"] = 804  # 296 + 508
    xaxis["height"] = 20
    xaxis["fill"] = CARD
    xaxis["layout"] = "none"
    x_labels = ["Oct '25", "Nov '25", "Dec '25", "Jan '26", "Feb '26", "Mar '26", "Apr '26"]
    sp = PW / (len(x_labels) + 1)
    xaxis["children"] = [
        txt(f"xax{i}", lbl, DIM, "IBM Plex Mono", 9, "400", x=int(sp * (i + 1)), y=4) for i, lbl in enumerate(x_labels)
    ]

print("FIX 3 Chart done")


# ═══════════════════════════════════════════════════════════════════════════════
# FIX 4 — OverviewBottom (ihGiy): 3 flat rows replacing 7 rounded cards
# ═══════════════════════════════════════════════════════════════════════════════
ihgiy = find_node(data, "ihGiy")
ihgiy["y"] = 824  # 296 + 508 + 20
ihgiy["height"] = 232
ihgiy["fill"] = CARD
ihgiy["stroke"] = stroke("top", BORDER, 1)
ihgiy["layout"] = "none"

# --- ROW 1 KEY STATS (h=80, layout:none with 3 absolute panels) ---
panel_a = frame(
    "panelEarnings", 287, 80, CARD, x=0, y=0, layout="vertical", gap=4, pad=[10, 16], stk=stroke("right", BORDER, 1)
)
panel_a["children"] = [
    txt("neHdr", "NEXT EARNINGS", MFG, "IBM Plex Sans", 10, "600", ls=0.08),
    txt("neDate", "July 24  ·  23 days", FG, "IBM Plex Mono", 12, "600"),
    frame(
        "neStats",
        None,
        None,
        gap=12,
        ai="center",
        children=[
            txt("neEps", "EPS est $0.64", DIM, "IBM Plex Mono", 10, "400"),
            txt("neRev", "Rev est $36.8B", DIM, "IBM Plex Mono", 10, "400"),
            txt("neWhisp", "Whisper $0.71", POS, "IBM Plex Mono", 10, "400"),
        ],
    ),
]

# Analyst bar (absolute rects within 255px usable width: 287-16-16)
analyst_bar = frame("analystBar", 255, 10, None, x=0, y=0, layout="none", cr=2)
analyst_bar["children"] = [
    rect("buyBar", 211, 10, POS, x=0, y=0, cr=2),
    rect("holdBar", 36, 10, ELEVATED, x=211, y=0),
    rect("sellBar", 8, 10, NEG, x=247, y=0, cr=2),
]
panel_b = frame(
    "panelAnalyst", 287, 80, CARD, x=287, y=0, layout="vertical", gap=6, pad=[10, 16], stk=stroke("right", BORDER, 1)
)
panel_b["children"] = [
    txt("acHdr", "ANALYST CONSENSUS · 36", MFG, "IBM Plex Sans", 10, "600", ls=0.08),
    analyst_bar,
    txt("acTgt", "Avg Target $220.50  +12.3% upside", MFG, "IBM Plex Mono", 10, "400"),
]

panel_c = frame("panelShort", 286, 80, CARD, x=574, y=0, layout="vertical", gap=4, pad=[10, 16])
panel_c["children"] = [
    txt("siHdr", "SHORT INTEREST", MFG, "IBM Plex Sans", 10, "600", ls=0.08),
    txt("siVal", "0.8%  float", FG, "IBM Plex Mono", 12, "600"),
    frame(
        "siStats",
        None,
        None,
        gap=12,
        ai="center",
        children=[
            txt("siDtc", "Days to Cover 1.2", DIM, "IBM Plex Mono", 10, "400"),
            txt("siBorrow", "Borrow 0.4%", DIM, "IBM Plex Mono", 10, "400"),
        ],
    ),
]

row1 = frame("keyStatsRow", 860, 80, CARD, x=0, y=0, layout="none", stk=stroke("bottom", BORDER, 1))
row1["children"] = [panel_a, panel_b, panel_c]

# --- ROW 2 TECHNICAL SIGNALS (h=48, horizontal layout) ---
row2 = frame("technicalRow", 860, 48, CARD, x=0, y=80, pad=[0, 16], gap=8, ai="center", stk=stroke("bottom", BORDER, 1))
row2["children"] = [
    txt("techLbl", "TECHNICAL", MFG, "IBM Plex Sans", 10, "600", ls=0.08),
    rect("techVsep", 1, 28, BORDER),
    chip("BETA 1.68", ELEVATED, FG),
    chip("MA50 ▲", "#0D2926", POS),
    chip("MA200 ▲", "#0D2926", POS),
    chip("RSI 63.4 ●", ELEVATED, FG),
    chip("BB EXPANDING", "#1A160A", WARN),
    chip("SHORT 0.8%", ELEVATED, DIM),
]

# --- ROW 3 INSIDER ACTIVITY (h=104, vertical: header + 3 rows) ---
ins_header = frame("insiderHdr", 860, 28, None, pad=[0, 16], gap=8, ai="center", stk=stroke("bottom", BORDER, 1))
ins_header["children"] = [
    txt("insLbl", "INSIDER ACTIVITY", MFG, "IBM Plex Sans", 10, "600", ls=0.08),
    txt("insDays", "30 days", DIM, "IBM Plex Mono", 10, "400"),
    spacer(),
    txt("insSeeAll", "See all →", PRIMARY, "IBM Plex Sans", 11, "400"),
]


def insider_row(name, title, action, amount, date, ac):
    badge_bg = "#0D2926" if action == "BOUGHT" else "#2D1010"
    badge = frame(
        f"badge_{action}",
        44,
        16,
        badge_bg,
        cr=2,
        jc="center",
        ai="center",
        children=[txt(f"badgeTxt_{action}", action, ac, "IBM Plex Sans", 9, "600")],
    )
    row = frame(f"ir_{name[:4]}", 860, 25, None, pad=[0, 16], gap=8, ai="center", stk=stroke("bottom", BORDER, 1))
    row["children"] = [
        txt(f"irN_{name[:4]}", name, FG, "IBM Plex Sans", 11, "400"),
        txt(f"irT_{name[:4]}", title, DIM, "IBM Plex Sans", 9, "400"),
        badge,
        spacer(),
        txt(f"irA_{name[:4]}", amount, ac, "IBM Plex Mono", 10, "400"),
        txt(f"irD_{name[:4]}", date, DIM, "IBM Plex Mono", 10, "400"),
    ]
    return row


row3 = frame("insiderRow", 860, 104, CARD, x=0, y=128, layout="vertical")
row3["children"] = [
    ins_header,
    insider_row("Jensen Huang", "CEO", "SOLD", "$43.7M", "Jan 8", NEG),
    insider_row("Mark Stevens", "Dir", "BOUGHT", "+$4.4M", "Feb 12", POS),
    insider_row("Colette Kress", "CFO", "SOLD", "$17.5M", "Mar 3", NEG),
]

ihgiy["children"] = [row1, row2, row3]
print("FIX 4 OverviewBottom done")


# ═══════════════════════════════════════════════════════════════════════════════
# FIX 5 & 6 — RightPanel (92l9k): EntityGraph (h=420) + RelatedContent (h=388)
# ═══════════════════════════════════════════════════════════════════════════════
rp = find_node(data, "92l9k")
rp["height"] = 808
rp["fill"] = CARD
rp["stroke"] = stroke("left", BORDER, 1)
rp["layout"] = "vertical"

# ── FIX 5: Entity Graph (h=420) ───────────────────────────────────────────────
eg_header = frame("egHeader", 380, 32, None, pad=[0, 16], ai="center", stk=stroke("bottom", BORDER, 1))
eg_header["children"] = [
    txt("egLbl", "ENTITY GRAPH", MFG, "IBM Plex Sans", 10, "600", ls=0.08),
    spacer(),
    txt("egExp", "Expand →", PRIMARY, "IBM Plex Sans", 11, "400"),
]


def graph_edge(x1, y1, x2, y2, color, opacity=1.0, label=None):
    nodes = []
    d = f"M {x1} {y1} L {x2} {y2}"
    nodes.append(
        {
            "type": "path",
            "id": nid(),
            "name": f"edge_{label or 'e'}",
            "x": 0,
            "y": 0,
            "geometry": d,
            "viewBox": [0, 0, 380, 364],
            "width": 380,
            "height": 364,
            "opacity": opacity,
            "stroke": {"align": "center", "thickness": 0.8, "fill": color},
        }
    )
    if label:
        mx, my = (x1 + x2) // 2 + 4, (y1 + y2) // 2
        nodes.append(txt(f"edgeLbl_{label}", label, DIM, "IBM Plex Sans", 8, "400", x=mx, y=my))
    return nodes


# Node centers (used for edges):
# NVDA(170,160) center=(196,186); MSFT(72,88) center=(90,106)
# AMD(268,96) center=(285,113); TSMC(278,210) center=(292,224)
# Jensen(96,252) center=(109,265); SoftBank(168,282) center=(179,293)

graph_canvas = frame("graphCanvas", 380, 364, BG, x=0, y=0, layout="none")
graph_canvas_children = []

# Edges first (behind nodes)
graph_canvas_children += graph_edge(196, 186, 90, 106, MFG, label="partner")
graph_canvas_children += graph_edge(196, 186, 285, 113, NEG, label="rival")
graph_canvas_children += graph_edge(196, 186, 292, 224, DIM, label="supplier")
graph_canvas_children += graph_edge(196, 186, 109, 265, MFG, label="CEO")
graph_canvas_children += graph_edge(196, 186, 179, 293, AMBER, opacity=0.5, label="investor")

# NVDA (roundrectangle = frame with cornerRadius)
nvda = frame(
    "nvdaNode",
    52,
    52,
    CARD,
    x=170,
    y=160,
    cr=8,
    jc="center",
    ai="center",
    stk={"align": "inside", "thickness": 2, "fill": PRIMARY},
    children=[txt("nvdaTxt", "NVDA", PRIMARY, "IBM Plex Mono", 12, "600")],
)

# MSFT
msft_e = ellipse("msftNode", 36, 36, PDIM, x=72, y=88, stk={"align": "inside", "thickness": 1, "fill": PRIMARY})
msft_l = txt("msftLbl", "MSFT", FG, "IBM Plex Sans", 10, "400", x=66, y=128)

# AMD
amd_e = ellipse("amdNode", 34, 34, "#2D1515", x=268, y=96, stk={"align": "inside", "thickness": 1, "fill": NEG})
amd_l = txt("amdLbl", "AMD", FG, "IBM Plex Sans", 10, "400", x=265, y=134)

# TSMC
tsmc_e = ellipse("tsmcNode", 28, 28, ELEVATED, x=278, y=210, stk={"align": "inside", "thickness": 0.5, "fill": MFG})
tsmc_l = txt("tsmcLbl", "TSMC", MFG, "IBM Plex Sans", 9, "400", x=272, y=242)

# Jensen H.
jh_e = ellipse("jensNode", 26, 26, ELEVATED, x=96, y=252, stk={"align": "inside", "thickness": 1, "fill": WARN})
jh_l = txt("jensLbl", "Jensen H.", MFG, "IBM Plex Sans", 9, "400", x=80, y=282)

# SoftBank
sb_e = ellipse("sbNode", 22, 22, ADIM, x=168, y=282, stk={"align": "inside", "thickness": 0.5, "fill": AMBER})
sb_l = txt("sbLbl", "SoftBank", DIM, "IBM Plex Sans", 9, "400", x=155, y=308)

graph_canvas_children += [nvda, msft_e, msft_l, amd_e, amd_l, tsmc_e, tsmc_l, jh_e, jh_l, sb_e, sb_l]
graph_canvas["children"] = graph_canvas_children

# Legend (h=24)
legend = frame("egLegend", 380, 24, CARD, pad=[4, 12], gap=10, ai="center", stk=stroke("top", BORDER, 1))
legend["children"] = [
    rect("lgInstrBox", 8, 8, PRIMARY),
    txt("lgInstrT", "Instrument", DIM, "IBM Plex Sans", 8, "400"),
    ellipse("lgCompDot", 6, 6, PRIMARY),
    txt("lgCompT", "Company", DIM, "IBM Plex Sans", 8, "400"),
    ellipse("lgPersDot", 6, 6, WARN),
    txt("lgPersT", "Person", DIM, "IBM Plex Sans", 8, "400"),
    line_node("lgPartnerLine", 0, 0, 12, MFG, 1.0),
    txt("lgPartnerT", "Partner", DIM, "IBM Plex Sans", 8, "400"),
    line_node("lgRivalLine", 0, 0, 12, NEG, 1.0, opacity=0.7),
    txt("lgRivalT", "Rival", DIM, "IBM Plex Sans", 8, "400"),
]

entity_graph_card = frame(
    "EntityGraphCard", 380, 420, CARD, x=0, y=0, layout="vertical", stk=stroke("bottom", BORDER, 1)
)
entity_graph_card["children"] = [eg_header, graph_canvas, legend]

# ── FIX 6: Related Content (h=388) ────────────────────────────────────────────
rc_header = frame("rcHeader", 380, 32, None, pad=[0, 16], ai="center", stk=stroke("bottom", BORDER, 1))
rc_header["children"] = [
    txt("rcLbl", "RELATED CONTENT", MFG, "IBM Plex Sans", 10, "600", ls=0.08),
    spacer(),
    txt("rcSeeAll", "See all →", PRIMARY, "IBM Plex Sans", 11, "400"),
]

ARTICLES = [
    ("DEEP", PDIM, PRIMARY, "Reuters · 2h", "NVIDIA H100 Demand Surge Drives Record Data Center Revenue"),
    ("MED", "#2A1F00", WARN, "Bloomberg · 5h", "China Chip Export Restrictions Could Weigh on NVDA Q3 Outlook"),
    ("LIGHT", ELEVATED, MFG, "WSJ · 8h", "Analysts Raise NVDA Price Targets Ahead of Blackwell Architecture Launch"),
    ("MED", "#2A1F00", WARN, "FT · 12h", "NVDA Supply Chain Analysis: Samsung Foundry Deal Strengthens Packaging"),
    (
        "BUY",
        "#0D2926",
        POS,
        "Morgan Stanley · 14h",
        "Morgan Stanley Upgrades NVDA to Overweight, Raises Target to $1,100",
    ),
    ("LGT", ELEVATED, DIM, "Reuters · 1d", "NVIDIA Joins NVIDIA-Azure Cloud Alliance for AI Chip"),
]

news_rows = []
for i, (tier, tbg, tfg, source, headline) in enumerate(ARTICLES):
    badge = frame(
        f"nbadge{i}",
        36,
        18,
        tbg,
        cr=2,
        jc="center",
        ai="center",
        children=[txt(f"nbadgeT{i}", tier, tfg, "IBM Plex Sans", 9, "600")],
    )
    content = frame(
        f"ncontent{i}",
        None,
        None,
        layout="vertical",
        gap=3,
        children=[
            txt(f"nsrc{i}", source, DIM, "IBM Plex Sans", 10, "400"),
            txt(f"nhdl{i}", headline, FG, "IBM Plex Sans", 12, "400"),
        ],
    )
    row = frame(
        f"newsRow{i}", 380, 56, None, pad=[8, 16, 8, 12], gap=10, ai="flex-start", stk=stroke("bottom", BORDER, 1)
    )
    row["children"] = [badge, content]
    news_rows.append(row)

related_content = frame(
    "RelatedContent",
    380,
    388,
    CARD,
    x=0,
    y=420,
    layout="vertical",
    stk={"align": "inside", "thickness": {"top": 1}, "fill": BORDER},
)
related_content["children"] = [rc_header, *news_rows]

rp["children"] = [entity_graph_card, related_content]
print("FIX 5+6 RightPanel done")


# ═══════════════════════════════════════════════════════════════════════════════
# Update b8vqT canvas dimensions
# ═══════════════════════════════════════════════════════════════════════════════
b8 = find_node(data, "b8vqT")
b8["height"] = 1068  # max(OverviewBottom 824+232=1056, RightPanel 260+808=1068)
b8["fill"] = BG

# ═══════════════════════════════════════════════════════════════════════════════
# Save
# ═══════════════════════════════════════════════════════════════════════════════
with open(FILE, "w") as f:
    json.dump(data, f, indent=2)
print(f"\nSaved {FILE}")
print(f"File size: {FILE.stat().st_size / 1024:.0f} KB")
