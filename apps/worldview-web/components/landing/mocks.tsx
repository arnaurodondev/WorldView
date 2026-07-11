/**
 * components/landing/mocks.tsx — hand-built product illustrations (2026-07 rework)
 *
 * WHY THIS EXISTS: The landing page frames every product visual in a
 * ProductShot window chrome. The real screenshots are produced by a Playwright
 * capture pipeline (capture-landing-shots.mjs) that hasn't run against
 * production yet — and until it does, the page rendered a literal
 * "screenshot pending capture" text panel to real visitors. That is a
 * launch-blocking defect: the #1 job of the visuals is to prove the product
 * is real.
 *
 * WHY PURE CSS/SVG (not images, not client JS): these are Server Components
 * built only from Tailwind utilities + the design-system tokens, so they
 *   (a) ship ZERO JavaScript to the client (landing stays static + fast),
 *   (b) render crisply at any DPR (no blurry PNG scaling),
 *   (c) automatically track the Midnight Pro palette if tokens change, and
 *   (d) are honest — every number shown is representative sample data, and
 *       the surrounding alt text (on the ProductShot wrapper) says so.
 *
 * WHY aria-hidden ON EVERY ROOT: the ProductShot `mock` wrapper carries
 * role="img" + aria-label describing the illustration. Screen readers should
 * get that ONE coherent sentence — not forty individual ticker fragments —
 * so each mock's internals are hidden from the a11y tree.
 *
 * WHY EVERYTHING IS text-[10px]/text-[9px] MONO: the app itself is a dense
 * finance terminal (see DESIGN_SYSTEM.md); the illustrations must read as
 * crops of that terminal, not as marketing cartoons. Small mono + tabular-nums
 * is the app's own idiom.
 *
 * SCALING NOTE: each mock fills the width of its ProductShot frame and is
 * clipped to the frame's aspect-ratio box (overflow-hidden on the wrapper).
 * Slightly overshooting vertically (e.g. a table row half-cut at the bottom)
 * is intentional — real screenshots crop mid-content too, and it reinforces
 * "this is a window onto a bigger app".
 */

/* ─────────────────────────────────────────────────────────────────────────────
 * Shared primitives
 * ────────────────────────────────────────────────────────────────────────── */

/**
 * MockStat — tiny label/value pair used in headers of several mocks.
 * WHY a component: keeps the mocks' JSX scannable; the styling is identical
 * everywhere (mono label in muted, tabular value in foreground).
 */
function MockStat({
  label,
  value,
  tone = "default",
}: {
  label: string;
  value: string;
  /** Color the value as a gain (positive), loss (negative), or neutral. */
  tone?: "default" | "positive" | "negative";
}) {
  const valueClass =
    tone === "positive"
      ? "text-positive"
      : tone === "negative"
        ? "text-negative"
        : "text-foreground";
  return (
    <div className="flex flex-col gap-0.5">
      <span className="font-mono text-[8px] uppercase tracking-[0.14em] text-muted-foreground/60">
        {label}
      </span>
      <span className={`font-mono text-[11px] tabular-nums ${valueClass}`}>
        {value}
      </span>
    </div>
  );
}

/* ─────────────────────────────────────────────────────────────────────────────
 * 1. Knowledge graph — shared SVG scene
 * ────────────────────────────────────────────────────────────────────────── */

/**
 * Node/edge layout for the graph scene, hand-placed on a 320×220 viewBox.
 * WHY hand-placed (not force-directed): a static, art-directed layout is
 * deterministic, renders identically on every build, and lets us guarantee
 * the highlighted AAPL→TSMC→ASML path reads left-to-right — the one thing
 * this illustration must communicate.
 */
const GRAPH_NODES = [
  // The signature path (highlighted): Apple → TSMC → ASML.
  { id: "AAPL", x: 52, y: 118, r: 13, hot: true },
  { id: "TSMC", x: 158, y: 88, r: 11, hot: true },
  { id: "ASML", x: 262, y: 62, r: 10, hot: true },
  // Context neighborhood — real relation types from the extraction vocabulary.
  { id: "FOXCONN", x: 96, y: 186, r: 8, hot: false },
  { id: "QCOM", x: 128, y: 40, r: 8, hot: false },
  { id: "SEC", x: 216, y: 156, r: 7, hot: false },
  { id: "NVDA", x: 232, y: 20, r: 8, hot: false },
  { id: "SAMSUNG", x: 288, y: 142, r: 8, hot: false },
] as const;

const GRAPH_EDGES: Array<{
  from: (typeof GRAPH_NODES)[number]["id"];
  to: (typeof GRAPH_NODES)[number]["id"];
  label?: string;
  hot?: boolean;
}> = [
  // Highlighted 2-hop discovery path with its typed-edge labels.
  { from: "AAPL", to: "TSMC", label: "supplied_by", hot: true },
  { from: "TSMC", to: "ASML", label: "equipment_from", hot: true },
  // Dim context edges — enough to read as "a real graph", not a diagram.
  { from: "AAPL", to: "FOXCONN" },
  { from: "AAPL", to: "QCOM" },
  { from: "QCOM", to: "TSMC" },
  { from: "TSMC", to: "NVDA" },
  { from: "TSMC", to: "SAMSUNG" },
  { from: "AAPL", to: "SEC" },
  { from: "SEC", to: "SAMSUNG" },
];

/** Look up a node's coordinates by id (layout table above is tiny; O(n) fine). */
function nodeById(id: string) {
  const n = GRAPH_NODES.find((g) => g.id === id);
  // The ids are compile-time constants from the same file — this cannot miss.
  return n ?? GRAPH_NODES[0];
}

/**
 * GraphScene — the shared SVG knowledge-graph rendering.
 * Used by both the hero (inside IntelligenceTabMock) and the KG spotlight
 * (ConnectionsGraphMock) so the two flagship visuals are visibly the same
 * product surface.
 */
function GraphScene() {
  return (
    <svg
      viewBox="0 0 320 220"
      // WHY preserveAspectRatio + h/w-full: the scene letterboxes gracefully
      // into whatever aspect box the parent mock gives it.
      preserveAspectRatio="xMidYMid meet"
      className="h-full w-full"
    >
      {/* Dim context edges first (painted under the hot path). */}
      {GRAPH_EDGES.filter((e) => !e.hot).map((e) => {
        const a = nodeById(e.from);
        const b = nodeById(e.to);
        return (
          <line
            key={`${e.from}-${e.to}`}
            x1={a.x}
            y1={a.y}
            x2={b.x}
            y2={b.y}
            className="stroke-border"
            strokeWidth="1"
          />
        );
      })}

      {/* Highlighted path edges — primary (trading yellow) + typed-edge label. */}
      {GRAPH_EDGES.filter((e) => e.hot).map((e) => {
        const a = nodeById(e.from);
        const b = nodeById(e.to);
        // Midpoint for the relation label, nudged above the line.
        const mx = (a.x + b.x) / 2;
        const my = (a.y + b.y) / 2 - 6;
        return (
          <g key={`${e.from}-${e.to}`}>
            <line
              x1={a.x}
              y1={a.y}
              x2={b.x}
              y2={b.y}
              className="stroke-primary"
              strokeWidth="1.5"
            />
            <text
              x={mx}
              y={my}
              textAnchor="middle"
              className="fill-primary font-mono"
              fontSize="7"
            >
              {e.label}
            </text>
          </g>
        );
      })}

      {/* Nodes — hot nodes get a primary ring + brighter label. */}
      {GRAPH_NODES.map((n) => (
        <g key={n.id}>
          <circle
            cx={n.x}
            cy={n.y}
            r={n.r}
            className={
              n.hot
                ? "fill-primary/15 stroke-primary"
                : "fill-muted stroke-border"
            }
            strokeWidth={n.hot ? 1.5 : 1}
          />
          <text
            x={n.x}
            y={n.y + n.r + 9}
            textAnchor="middle"
            className={
              n.hot
                ? "fill-foreground font-mono"
                : "fill-muted-foreground font-mono"
            }
            fontSize="7.5"
          >
            {n.id}
          </text>
        </g>
      ))}
    </svg>
  );
}

/**
 * IntelligenceTabMock — hero visual: the instrument "Intelligence" tab.
 * Graph on the left, "related entities" panel on the right — mirrors the real
 * two-pane layout of /instrument/[symbol] → Intelligence.
 */
export function IntelligenceTabMock() {
  // Representative related-entity rows (entity · relation · edge count).
  const RELATED = [
    { entity: "TSMC", rel: "supplied_by", n: 42, tone: "positive" as const },
    { entity: "Foxconn", rel: "manufactured_by", n: 31, tone: "default" as const },
    { entity: "Qualcomm", rel: "licenses_from", n: 18, tone: "default" as const },
    { entity: "ASML", rel: "2-hop exposure", n: 9, tone: "negative" as const },
  ];

  return (
    <div aria-hidden className="flex h-full w-full bg-background">
      {/* Left pane: the graph itself (60% of the frame). */}
      <div className="min-w-0 flex-[3] border-r border-border/50 p-2">
        <GraphScene />
      </div>

      {/* Right pane: related-entities list, like the app's side panel. */}
      <div className="flex min-w-0 flex-[2] flex-col gap-0 p-3">
        <p className="mb-2 font-mono text-[8px] uppercase tracking-[0.16em] text-muted-foreground/60">
          AAPL · related entities
        </p>
        {RELATED.map((r) => (
          <div
            key={r.entity}
            className="flex items-baseline justify-between gap-2 border-b border-border/30 py-1.5"
          >
            <div className="min-w-0">
              <p className="truncate text-[10px] font-medium text-foreground">
                {r.entity}
              </p>
              <p className="truncate font-mono text-[8px] text-muted-foreground/70">
                {r.rel}
              </p>
            </div>
            <span className="shrink-0 font-mono text-[9px] tabular-nums text-muted-foreground">
              {r.n} edges
            </span>
          </div>
        ))}
        {/* Path-discovery affordance — teases the spotlight section below. */}
        <div className="mt-2.5 rounded-[2px] border border-primary/30 bg-primary/5 px-2 py-1.5">
          <p className="font-mono text-[8px] text-primary">
            /path AAPL ASML → 2 hops · weirdness 0.72
          </p>
        </div>
      </div>
    </div>
  );
}

/**
 * ConnectionsGraphMock — KG spotlight visual: full-bleed graph with the
 * highlighted discovery path and a query bar on top (reads as the
 * /intelligence connections view).
 */
export function ConnectionsGraphMock() {
  return (
    <div aria-hidden className="flex h-full w-full flex-col bg-background">
      {/* Query bar — the actual interaction that produces the highlight. */}
      <div className="flex items-center gap-2 border-b border-border/50 px-3 py-1.5">
        <span className="font-mono text-[9px] text-primary">/path</span>
        <span className="font-mono text-[9px] text-foreground">AAPL ASML</span>
        <span className="ml-auto font-mono text-[8px] text-muted-foreground/60">
          2 hops · 60–800ms VLE search
        </span>
      </div>
      <div className="min-h-0 flex-1 p-2">
        <GraphScene />
      </div>
    </div>
  );
}

/* ─────────────────────────────────────────────────────────────────────────────
 * 2. Grounded AI chat
 * ────────────────────────────────────────────────────────────────────────── */

/**
 * ChatMock — one grounded question/answer exchange with citation chips and
 * the per-source confidence bar. The violet accent is the app's canonical
 * AI-assistant color (--accent-ai); it has no Tailwind alias so we use the
 * arbitrary-value form of the SAME token (no new colors introduced).
 */
export function ChatMock() {
  return (
    <div aria-hidden className="flex h-full w-full flex-col gap-2 bg-background p-3">
      {/* User turn — right-aligned like the real chat surface. */}
      <div className="ml-auto max-w-[80%] rounded-[2px] bg-muted px-2.5 py-1.5">
        <p className="text-[10px] leading-relaxed text-foreground">
          Why is Apple exposed to EUV lithography?
        </p>
      </div>

      {/* Assistant turn — cited claims, each with an inline [n] chip. */}
      <div className="max-w-[92%] rounded-[2px] border border-[hsl(var(--accent-ai))]/25 bg-card px-2.5 py-2">
        <p className="text-[10px] leading-relaxed text-muted-foreground">
          <span className="text-foreground">
            Apple&apos;s leading-edge chips are fabricated by TSMC
          </span>
          <span className="font-mono text-[8px] text-[hsl(var(--accent-ai))]">
            {" "}[1]
          </span>
          , and TSMC&apos;s sub-3nm nodes depend on ASML&apos;s EUV machines
          <span className="font-mono text-[8px] text-[hsl(var(--accent-ai))]">
            {" "}[2]
          </span>
          {" "}— a two-hop supply-chain exposure surfaced by the knowledge
          graph
          <span className="font-mono text-[8px] text-[hsl(var(--accent-ai))]">
            {" "}[3]
          </span>
          .
        </p>

        {/* Citation-confidence bar — the trust feature, shown not told. */}
        <div className="mt-2 border-t border-border/40 pt-1.5">
          <div className="mb-1 flex items-center justify-between">
            <span className="font-mono text-[8px] uppercase tracking-[0.12em] text-muted-foreground/60">
              citation confidence
            </span>
            <span className="font-mono text-[8px] tabular-nums text-positive">
              0.91
            </span>
          </div>
          {/* WHY a plain div bar (not <progress>): the mock is aria-hidden
              decoration; native <progress> would add pointless a11y noise. */}
          <div className="h-1 w-full rounded-full bg-muted">
            <div className="h-1 w-[91%] rounded-full bg-positive" />
          </div>
          <div className="mt-1.5 flex flex-wrap gap-1">
            {["10-K 2025 · AAPL", "TSMC Q2 call", "KG path #4821"].map((c, i) => (
              <span
                key={c}
                className="rounded-[2px] border border-border/50 bg-muted/40 px-1.5 py-0.5 font-mono text-[7.5px] text-muted-foreground"
              >
                [{i + 1}] {c}
              </span>
            ))}
          </div>
        </div>
      </div>

      {/* Composer with slash-command hint — signals power-user affordances. */}
      <div className="mt-auto flex items-center gap-2 rounded-[2px] border border-border/50 bg-card px-2.5 py-1.5">
        <span className="font-mono text-[9px] text-muted-foreground/50">
          /compare AAPL MSFT margins…
        </span>
        <span className="ml-auto rounded-[2px] bg-[hsl(var(--accent-ai))]/15 px-1.5 py-0.5 font-mono text-[8px] text-[hsl(var(--accent-ai))]">
          ⏎
        </span>
      </div>
    </div>
  );
}

/* ─────────────────────────────────────────────────────────────────────────────
 * 3. Portfolio analytics
 * ────────────────────────────────────────────────────────────────────────── */

/**
 * Equity-curve polyline points on a 300×90 viewBox. Hand-tuned to read as a
 * realistic "up and to the right with drawdowns" curve — a straight line
 * reads as fake, a random walk reads as noise.
 */
const EQUITY_POINTS =
  "0,74 20,70 40,72 60,63 80,66 100,58 120,60 140,50 160,54 180,44 " +
  "200,47 220,38 240,42 260,30 280,26 300,20";

export function PortfolioMock() {
  const ALLOC = [
    { label: "Tech", pct: 42 },
    { label: "Energy", pct: 23 },
    { label: "Health", pct: 18 },
    { label: "Cash", pct: 17 },
  ];

  return (
    <div aria-hidden className="flex h-full w-full flex-col bg-background p-3">
      {/* Header stat row — the numbers a portfolio page leads with. */}
      <div className="mb-2 flex items-start justify-between gap-3">
        <MockStat label="Total value" value="$128,431.20" />
        <MockStat label="Day" value="+$1,204 (+0.95%)" tone="positive" />
        <MockStat label="Realized P&L" value="+$9,318" tone="positive" />
      </div>

      {/* Equity curve — area fill under a polyline, token-colored. */}
      <div className="min-h-0 flex-1">
        <svg viewBox="0 0 300 90" preserveAspectRatio="none" className="h-full w-full">
          {/* Faint horizontal gridlines ground the chart like the real one. */}
          {[22, 45, 68].map((y) => (
            <line
              key={y}
              x1="0"
              y1={y}
              x2="300"
              y2={y}
              className="stroke-border/60"
              strokeWidth="0.5"
            />
          ))}
          {/* Area fill: close the polyline down to the baseline. */}
          <polygon
            points={`${EQUITY_POINTS} 300,90 0,90`}
            className="fill-positive/10"
          />
          <polyline
            points={EQUITY_POINTS}
            fill="none"
            className="stroke-positive"
            strokeWidth="1.5"
          />
        </svg>
      </div>

      {/* Sector allocation — proportional horizontal bars. */}
      <div className="mt-2 space-y-1">
        {ALLOC.map((a) => (
          <div key={a.label} className="flex items-center gap-2">
            <span className="w-12 shrink-0 font-mono text-[8px] uppercase text-muted-foreground/70">
              {a.label}
            </span>
            <div className="h-1.5 flex-1 rounded-full bg-muted">
              <div
                className="h-1.5 rounded-full bg-primary/70"
                style={{ width: `${a.pct}%` }}
              />
            </div>
            <span className="w-7 shrink-0 text-right font-mono text-[8px] tabular-nums text-muted-foreground">
              {a.pct}%
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ─────────────────────────────────────────────────────────────────────────────
 * 4. Fundamentals screener
 * ────────────────────────────────────────────────────────────────────────── */

export function ScreenerMock() {
  // Representative screen result rows — plausible magnitudes, sample values.
  const ROWS = [
    { t: "NVDA", cap: "3.42T", pe: "62.1", margin: "55.8%", chg: +2.14 },
    { t: "MSFT", cap: "3.18T", pe: "35.4", margin: "36.7%", chg: +0.42 },
    { t: "AAPL", cap: "2.96T", pe: "29.8", margin: "26.3%", chg: -0.31 },
    { t: "AVGO", cap: "812B", pe: "38.2", margin: "39.1%", chg: +1.05 },
    { t: "ASML", cap: "364B", pe: "41.7", margin: "28.4%", chg: -0.88 },
    { t: "AMD", cap: "289B", pe: "48.9", margin: "22.6%", chg: +0.67 },
  ];

  return (
    <div aria-hidden className="flex h-full w-full flex-col bg-background">
      {/* Active filter chips — communicates "faceted screening" instantly. */}
      <div className="flex flex-wrap items-center gap-1 border-b border-border/50 px-3 py-1.5">
        {["mktcap > $250B", "net margin > 20%", "sector: semis+software"].map((f) => (
          <span
            key={f}
            className="rounded-[2px] border border-primary/30 bg-primary/10 px-1.5 py-0.5 font-mono text-[7.5px] text-primary"
          >
            {f}
          </span>
        ))}
        <span className="ml-auto font-mono text-[8px] text-muted-foreground/60">
          6 of 8,214
        </span>
      </div>

      {/* Result table — mono, tabular-nums, gain/loss coloring: the app idiom. */}
      <div className="grid grid-cols-[1fr_1fr_1fr_1fr_1fr] gap-x-2 px-3 pt-1.5 font-mono text-[8px] uppercase tracking-wider text-muted-foreground/50">
        <span>Ticker</span>
        <span className="text-right">Mkt cap</span>
        <span className="text-right">P/E</span>
        <span className="text-right">Margin</span>
        <span className="text-right">Chg</span>
      </div>
      {ROWS.map((r) => (
        <div
          key={r.t}
          className="grid grid-cols-[1fr_1fr_1fr_1fr_1fr] gap-x-2 border-b border-border/30 px-3 py-1 font-mono text-[9px] tabular-nums"
        >
          <span className="text-foreground">{r.t}</span>
          <span className="text-right text-muted-foreground">{r.cap}</span>
          <span className="text-right text-muted-foreground">{r.pe}</span>
          <span className="text-right text-muted-foreground">{r.margin}</span>
          <span className={`text-right ${r.chg >= 0 ? "text-positive" : "text-negative"}`}>
            {r.chg >= 0 ? "+" : ""}
            {r.chg.toFixed(2)}%
          </span>
        </div>
      ))}
    </div>
  );
}

/* ─────────────────────────────────────────────────────────────────────────────
 * 5. News intelligence
 * ────────────────────────────────────────────────────────────────────────── */

export function NewsMock() {
  const ITEMS = [
    {
      h: "TSMC guides Q3 capex above consensus on 2nm ramp",
      meta: "TSM · 12m ago",
      impact: 0.82,
      tone: "positive" as const,
    },
    {
      h: "FTC opens inquiry into cloud AI partnerships",
      meta: "MSFT +2 · 41m ago",
      impact: 0.64,
      tone: "negative" as const,
    },
    {
      h: "Apple supplier Foxconn reports record June revenue",
      meta: "AAPL · 1h ago",
      impact: 0.47,
      tone: "positive" as const,
    },
    {
      h: "Treasury yields ease ahead of CPI print",
      meta: "Macro · 2h ago",
      impact: 0.21,
      tone: "positive" as const,
    },
  ];

  return (
    <div aria-hidden className="flex h-full w-full flex-col bg-background">
      <div className="flex items-center justify-between border-b border-border/50 px-3 py-1.5">
        <span className="font-mono text-[8px] uppercase tracking-[0.14em] text-muted-foreground/60">
          Top today · impact-ranked
        </span>
        <span className="font-mono text-[8px] text-muted-foreground/50">
          t0 / t1 / t2 / t5 windows
        </span>
      </div>
      {ITEMS.map((n) => (
        <div key={n.h} className="border-b border-border/30 px-3 py-1.5">
          <p className="truncate text-[10px] font-medium leading-snug text-foreground">
            {n.h}
          </p>
          <div className="mt-1 flex items-center gap-2">
            <span className="font-mono text-[8px] text-muted-foreground/60">
              {n.meta}
            </span>
            {/* Impact meter — width encodes the score, color the direction. */}
            <div className="ml-auto h-1 w-16 rounded-full bg-muted">
              <div
                className={`h-1 rounded-full ${n.tone === "positive" ? "bg-positive" : "bg-negative"}`}
                style={{ width: `${Math.round(n.impact * 100)}%` }}
              />
            </div>
            <span
              className={`w-8 text-right font-mono text-[8px] tabular-nums ${
                n.tone === "positive" ? "text-positive" : "text-negative"
              }`}
            >
              {n.impact.toFixed(2)}
            </span>
          </div>
        </div>
      ))}
    </div>
  );
}

/* ─────────────────────────────────────────────────────────────────────────────
 * 6. Instrument detail
 * ────────────────────────────────────────────────────────────────────────── */

/**
 * Candlestick bars for the instrument mock, on a 300×100 viewBox.
 * Each tuple: [x, wickTop, bodyTop, bodyBottom, wickBottom, up?].
 * Hand-tuned so the tape trends up with believable pullbacks.
 */
const CANDLES: Array<[number, number, number, number, number, boolean]> = [
  [10, 62, 66, 78, 84, false],
  [30, 58, 60, 72, 76, true],
  [50, 50, 54, 64, 70, true],
  [70, 52, 56, 66, 72, false],
  [90, 44, 48, 60, 66, true],
  [110, 40, 44, 54, 60, true],
  [130, 46, 50, 58, 64, false],
  [150, 36, 40, 52, 58, true],
  [170, 32, 36, 46, 52, true],
  [190, 38, 42, 50, 56, false],
  [210, 28, 32, 44, 50, true],
  [230, 24, 28, 38, 46, true],
  [250, 30, 34, 42, 48, false],
  [270, 20, 24, 36, 42, true],
  [290, 16, 20, 30, 38, true],
];

export function InstrumentMock() {
  return (
    <div aria-hidden className="flex h-full w-full flex-col bg-background p-3">
      {/* Quote header — symbol, price, day change, 52-wk range. */}
      <div className="mb-1.5 flex items-start justify-between gap-3">
        <div>
          <p className="font-mono text-[11px] font-semibold text-foreground">
            AAPL{" "}
            <span className="text-[8px] font-normal text-muted-foreground/60">
              Apple Inc · NASDAQ
            </span>
          </p>
          <p className="font-mono text-[13px] tabular-nums text-foreground">
            227.48{" "}
            <span className="text-[9px] text-positive">+1.87 (+0.83%)</span>
          </p>
        </div>
        <MockStat label="52-wk range" value="164.08 – 237.23" />
      </div>

      {/* Candlestick chart — token-colored up/down candles + wicks. */}
      <div className="min-h-0 flex-1">
        <svg viewBox="0 0 300 100" preserveAspectRatio="none" className="h-full w-full">
          {[25, 50, 75].map((y) => (
            <line
              key={y}
              x1="0"
              y1={y}
              x2="300"
              y2={y}
              className="stroke-border/60"
              strokeWidth="0.5"
            />
          ))}
          {CANDLES.map(([x, wt, bt, bb, wb, up]) => (
            <g key={x} className={up ? "text-positive" : "text-negative"}>
              {/* Wick — full high-low range. */}
              <line
                x1={x}
                y1={wt}
                x2={x}
                y2={wb}
                stroke="currentColor"
                strokeWidth="1"
              />
              {/* Body — open/close range, 8px wide centered on the wick. */}
              <rect
                x={x - 4}
                y={bt}
                width="8"
                height={Math.max(bb - bt, 2)}
                fill="currentColor"
              />
            </g>
          ))}
        </svg>
      </div>

      {/* Tab strip — the 3-tab structure the copy above the tile references. */}
      <div className="mt-1.5 flex gap-3 border-t border-border/40 pt-1.5 font-mono text-[8px] uppercase tracking-wider">
        <span className="text-primary">Quote</span>
        <span className="text-muted-foreground/50">Financials</span>
        <span className="text-muted-foreground/50">Intelligence</span>
      </div>
    </div>
  );
}
