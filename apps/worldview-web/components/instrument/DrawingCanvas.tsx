/**
 * components/instrument/DrawingCanvas.tsx — SVG annotation overlay for OHLCVChart
 *
 * WHY THIS EXISTS: lightweight-charts manages its own WebGL canvas and does not
 * expose a native drawing primitive API for arbitrary user annotations. We solve
 * this by rendering a sibling absolutely-positioned SVG layer that covers the
 * same pixel area as the chart canvas. The SVG coordinates are mapped from
 * price/time space to pixel space using lightweight-charts' coordinate conversion
 * APIs (`series.priceToCoordinate()` and `chart.timeScale().timeToCoordinate()`).
 *
 * WHY SVG (not Canvas 2D): SVG elements are part of the DOM — they support
 * pointer events (click, mousemove, contextmenu) and can be styled with CSS.
 * A second Canvas 2D layer would require manual hit-testing for selection and
 * erasing, which is significantly more complex. At chart dimensions (≤1920px wide,
 * ≤800px tall), SVG rendering is fast enough.
 *
 * WHY SIBLING (not child) of the chart div: lightweight-charts' chart container
 * renders a WebGL <canvas> with position:relative. Any absolutely-positioned child
 * of the chart container would be clipped by the chart's overflow. Instead, both
 * the chart container and the SVG overlay are siblings inside a wrapper div with
 * position:relative — the SVG is absolutely positioned to `inset-0` to exactly
 * cover the chart.
 *
 * WHY pointer-events-none except during drawing: when no tool is armed, the SVG
 * overlay must be transparent to mouse events so the user can still pan/zoom the
 * chart underneath. When a tool IS armed, we capture pointer events for click
 * handling.
 *
 * COORDINATE SYSTEM:
 *   - lightweight-charts time scale: Unix seconds (integers)
 *   - lightweight-charts price scale: floating-point price values
 *   - SVG coordinate space: pixel offsets from top-left of the chart container
 *   - Conversion: priceToCoordinate(price) → pixel Y; timeToCoordinate(time) → pixel X
 *
 * WHO USES IT: OHLCVChart (rendered as a sibling of the chart container div)
 * DESIGN REFERENCE: PLAN-0050 §T-C-3-02
 */

"use client";
// WHY "use client": uses useState (in-progress annotation points), useEffect
// (sync annotations → SVG on data change), mouse event handlers.

import { useCallback, useEffect, useId, useRef, useState } from "react";
// WHY useId: generates a stable React-managed unique string for the text-input's
// htmlFor/id pair. This is SSR-safe (unlike Date.now() or Math.random()) and
// survives React StrictMode double-invocation without collision.
import type {
  Annotation,
  DrawingToolId,
  ChartPoint,
  TrendLineAnnotation,
  HorizontalLevelAnnotation,
  RectangleAnnotation,
  ArrowAnnotation,
  TextAnnotation,
} from "@/lib/instrument-context";

// ── Coordinate conversion helpers ─────────────────────────────────────────────

/**
 * CoordinateConverter — lightweight-charts APIs needed for price↔pixel mapping.
 *
 * WHY a separate interface (not importing IChartApi directly): lightweight-charts'
 * TypeScript types are not exported from the package in a way that's easily
 * importable in non-chart files. We define the minimal surface we use so the
 * component doesn't depend on the chart library's internal types.
 *
 * These methods are guaranteed stable in lightweight-charts v4.x:
 *   - series.priceToCoordinate(price) → number | null  (null if price is off-screen)
 *   - chart.timeScale().timeToCoordinate(time) → number | null  (null if off-screen)
 *   - chart.timeScale().coordinateToTime(pixel) → Time | null
 *   - series.coordinateToPrice(pixel) → number | null
 */
export interface CoordinateConverter {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  chart: any;   // IChartApi — full type not exported from lightweight-charts
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  series: any;  // ISeriesApi<"Candlestick"> — used for priceToCoordinate
}

// ── Drawing colors ────────────────────────────────────────────────────────────

/**
 * ANNOTATION_COLOR — default color for new drawings.
 *
 * WHY #FFD60A (brand yellow): annotations are the user's own marks.
 * Using the brand primary color distinguishes them from chart data (teal/red).
 * Future: allow users to pick colors per annotation via a color picker in the
 * palette (tracked as F-I-020 in PLAN-0050 §Wave C, deferred from this wave).
 */
const ANNOTATION_COLOR = "#FFD60A";

// ── Props ─────────────────────────────────────────────────────────────────────

export interface DrawingCanvasProps {
  /** Currently armed drawing tool (null = cursor mode, no interaction) */
  activeTool: DrawingToolId | null;
  /** All persisted annotations to render */
  annotations: Annotation[];
  /** Callback when a new annotation is completed (caller persists to IndexedDB) */
  onAnnotationAdd: (annotation: Annotation) => void;
  /** Callback when an annotation is deleted (right-click → remove) */
  onAnnotationDelete: (id: string) => void;
  /** Coordinate converters from the parent OHLCVChart (set after chart init) */
  converters: CoordinateConverter | null;
  /** Chart height in pixels — SVG must match exactly */
  chartHeight: number;
  /** Palette width offset — SVG left edge starts after the palette */
  paletteWidth: number;
}

// ── In-progress state ─────────────────────────────────────────────────────────

/** Tracks points captured so far for a multi-click drawing operation */
interface InProgressDrawing {
  tool: DrawingToolId;
  /** Points captured so far (in chart price/time space) */
  points: ChartPoint[];
  /** Mouse position for preview line (pixel space, relative to SVG) */
  mousePixel: { x: number; y: number } | null;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

/** How many click points each tool requires before the annotation is committed */
const POINTS_REQUIRED: Record<DrawingToolId, number> = {
  TREND_LINE:       2,
  HORIZONTAL_LEVEL: 1,
  RECTANGLE:        2,
  ARROW:            2,
  FIB_RETRACEMENT:  2,
  PARALLEL_CHANNEL: 3,
  TEXT:             1,
};

/**
 * pixelToChartPoint — convert a pixel position (relative to SVG) to price/time.
 *
 * WHY null guard: if the user clicks outside the visible chart range
 * (e.g., the time scale or price scale area), the converter returns null.
 * We ignore such clicks — they have no valid price/time meaning.
 */
function pixelToChartPoint(
  x: number,
  y: number,
  converters: CoordinateConverter,
): ChartPoint | null {
  const time = converters.chart.timeScale().coordinateToTime(x) as number | null;
  const price = converters.series.coordinateToPrice(y) as number | null;
  if (time === null || price === null) return null;
  return { time, price };
}

/**
 * chartPointToPixel — convert price/time to pixel position.
 *
 * WHY null → fallback to -9999: if the point is off-screen (time before the
 * visible range, or price above/below the visible range), lightweight-charts
 * returns null. We move those SVG elements far off-screen rather than hiding
 * them, to avoid re-rendering the SVG on pan (which would be expensive).
 * Off-screen SVG elements don't affect rendering performance.
 */
function chartPointToPixel(
  point: ChartPoint,
  converters: CoordinateConverter,
): { x: number; y: number } {
  const x = converters.chart.timeScale().timeToCoordinate(point.time) as number | null;
  const y = converters.series.priceToCoordinate(point.price) as number | null;
  return { x: x ?? -9999, y: y ?? -9999 };
}

// ── Component ─────────────────────────────────────────────────────────────────

export function DrawingCanvas({
  activeTool,
  annotations,
  onAnnotationAdd,
  onAnnotationDelete,
  converters,
  chartHeight,
  paletteWidth,
}: DrawingCanvasProps) {
  // In-progress drawing — accumulated points from clicks before the annotation
  // is committed. Reset to null when the annotation is committed or escaped.
  const [inProgress, setInProgress] = useState<InProgressDrawing | null>(null);
  const svgRef = useRef<SVGSVGElement>(null);

  // ── TEXT tool inline input overlay ────────────────────────────────────────
  // WHY NOT inside the SVG: SVG cannot contain HTML <input> elements — only SVG
  // elements are valid children. We render the <input> as a sibling outside the
  // SVG and use absolute positioning to place it at the click point.
  // WHY pending state holds chartPoint: when the user types and commits, we call
  // commitAnnotation("TEXT", [chartPoint], enteredText) — we need the chart
  // coordinates of the original click, not the input's screen position.
  const [pendingTextPixel, setPendingTextPixel] = useState<{
    x: number;
    y: number;
    chartPoint: ChartPoint;
  } | null>(null);
  const textInputRef = useRef<HTMLInputElement>(null);
  // WHY useId: SSR-safe stable ID for the <label>/<input> pair
  const textInputId = useId();

  // WHY reset inProgress when activeTool changes: if the analyst switches tools
  // mid-drawing (e.g., starts a trend line then switches to arrow), we discard
  // the incomplete annotation. This matches TradingView's behaviour.
  useEffect(() => {
    setInProgress(null);
  }, [activeTool]);

  // ── Commit annotation ────────────────────────────────────────────────────
  // WHY defined before handleSvgClick: handleSvgClick calls commitAnnotation inside
  // its useCallback body, so commitAnnotation must exist before that useCallback
  // is defined. Using useCallback here avoids the react-hooks/exhaustive-deps warning
  // about the missing dependency in handleSvgClick.

  const commitAnnotation = useCallback((
    tool: DrawingToolId,
    points: ChartPoint[],
    // WHY optional text param: the TEXT tool collects label text via an inline
    // <input> overlay (see pendingTextPixel state below). The input's commit
    // handler calls commitAnnotation("TEXT", points, enteredText). Other tools
    // never pass text (their annotations have no text field).
    text?: string,
  ) => {
    // WHY crypto.randomUUID(): browser-native UUID v4 generator. Cryptographically
    // random — zero collision risk even for power users with hundreds of annotations.
    // Replaces the former `Date.now() + Math.random()` which had measurable
    // collision probability when multiple annotations were created in rapid succession
    // (same millisecond, same Math.random() seed in some V8 builds).
    const id = crypto.randomUUID();
    const createdAt = new Date().toISOString();
    const color = ANNOTATION_COLOR;

    let annotation: Annotation | null = null;

    switch (tool) {
      case "TREND_LINE":
        annotation = {
          id, tool, createdAt, color,
          points: [points[0], points[1]] as [ChartPoint, ChartPoint],
        } as TrendLineAnnotation;
        break;
      case "HORIZONTAL_LEVEL":
        annotation = {
          id, tool, createdAt, color,
          price: points[0].price,
        } as HorizontalLevelAnnotation;
        break;
      case "RECTANGLE":
        annotation = {
          id, tool, createdAt, color,
          topLeft: points[0],
          bottomRight: points[1],
        } as RectangleAnnotation;
        break;
      case "ARROW":
        annotation = {
          id, tool, createdAt, color,
          points: [points[0], points[1]] as [ChartPoint, ChartPoint],
        } as ArrowAnnotation;
        break;
      case "FIB_RETRACEMENT":
        annotation = {
          id, tool, createdAt, color,
          points: [points[0], points[1]] as [ChartPoint, ChartPoint],
        };
        break;
      case "PARALLEL_CHANNEL":
        annotation = {
          id, tool, createdAt, color,
          points: [points[0], points[1], points[2]] as [ChartPoint, ChartPoint, ChartPoint],
        };
        break;
      case "TEXT": {
        // WHY no window.prompt(): blocking synchronous prompts freeze the browser
        // tab and are a UX anti-pattern. They also break in headless test environments
        // (Playwright must accept/dismiss alerts separately). The inline <input>
        // overlay (rendered below the SVG) provides an equivalent non-blocking UX.
        if (!text) return; // user cancelled (empty commit from blur/Escape)
        annotation = {
          id, tool, createdAt, color,
          anchor: points[0],
          text,
        } as TextAnnotation;
        break;
      }
      default:
        return;
    }

    if (annotation) onAnnotationAdd(annotation);
  }, [onAnnotationAdd]);

  // ── Click handler ────────────────────────────────────────────────────────

  const handleSvgClick = useCallback(
    (e: React.MouseEvent<SVGSVGElement>) => {
      if (!activeTool || !converters) return;

      // WHY svgRef getBoundingClientRect: SVG event coordinates (e.clientX/Y) are
      // in viewport space, but coordinateToTime/coordinateToPrice expect offsets
      // relative to the chart container. The SVG is absolutely positioned over
      // the chart, so its bounding rect gives us the correct base offset.
      const rect = svgRef.current?.getBoundingClientRect();
      if (!rect) return;

      const x = e.clientX - rect.left;
      const y = e.clientY - rect.top;

      const chartPoint = pixelToChartPoint(x, y, converters);
      if (!chartPoint) return;

      // WHY TEXT tool short-circuit: TEXT requires only 1 click point (the anchor),
      // but the text content must be collected via the inline <input> overlay before
      // committing. We store the pending position and return — the input's onBlur /
      // Enter key handler calls commitAnnotation() when the user finishes typing.
      if (activeTool === "TEXT") {
        setPendingTextPixel({ x, y, chartPoint });
        return;
      }

      const currentPoints = inProgress?.points ?? [];
      const newPoints = [...currentPoints, chartPoint];
      const required = POINTS_REQUIRED[activeTool];

      if (newPoints.length < required) {
        // More points needed — update in-progress state
        setInProgress({ tool: activeTool, points: newPoints, mousePixel: { x, y } });
      } else {
        // All points captured — commit the annotation
        commitAnnotation(activeTool, newPoints);
        setInProgress(null);
      }
    },
    [activeTool, converters, inProgress, commitAnnotation],
  );

  // ── TEXT input overlay: focus on appearance ───────────────────────────────
  // WHY useEffect (not autoFocus attr): autoFocus fires on initial mount only.
  // pendingTextPixel changes AFTER mount — we need a side-effect to call focus()
  // each time a new text annotation is started.
  useEffect(() => {
    if (pendingTextPixel) {
      textInputRef.current?.focus();
    }
  }, [pendingTextPixel]);

  // ── TEXT input commit handler ─────────────────────────────────────────────
  // WHY separate commit function: called by both the Enter key handler and the
  // onBlur handler (clicking outside the input should commit if text was entered,
  // or cancel if empty). Centralising the logic avoids duplication.
  const handleTextInputCommit = useCallback(
    (value: string) => {
      if (!pendingTextPixel) return;
      if (value.trim()) {
        // Non-empty text → commit the annotation at the pending chart point
        commitAnnotation("TEXT", [pendingTextPixel.chartPoint], value.trim());
      }
      // Empty text → user cancelled (no annotation created)
      setPendingTextPixel(null);
    },
    [pendingTextPixel, commitAnnotation],
  );

  const handleTextInputKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLInputElement>) => {
      if (e.key === "Enter") {
        e.preventDefault();
        handleTextInputCommit(e.currentTarget.value);
      } else if (e.key === "Escape") {
        // Cancel text annotation — discard without committing
        setPendingTextPixel(null);
      }
    },
    [handleTextInputCommit],
  );

  // ── Mouse move handler (preview line) ───────────────────────────────────

  const handleMouseMove = useCallback(
    (e: React.MouseEvent<SVGSVGElement>) => {
      if (!inProgress || !svgRef.current) return;
      const rect = svgRef.current.getBoundingClientRect();
      setInProgress((prev) =>
        prev
          ? { ...prev, mousePixel: { x: e.clientX - rect.left, y: e.clientY - rect.top } }
          : null,
      );
    },
    [inProgress],
  );

  // ── Right-click to delete ────────────────────────────────────────────────

  const handleContextMenu = useCallback(
    (e: React.MouseEvent, annotationId: string) => {
      e.preventDefault(); // suppress browser context menu
      e.stopPropagation(); // don't bubble to SVG click
      if (window.confirm("Delete this annotation?")) {
        onAnnotationDelete(annotationId);
      }
    },
    [onAnnotationDelete],
  );

  // ── Render ───────────────────────────────────────────────────────────────

  // WHY pointer-events-none when no tool armed: the SVG should be completely
  // transparent to mouse events when the user is in cursor/pan mode.
  // WHY cursor-crosshair when tool armed: standard drawing-mode cursor convention.
  const svgStyle: React.CSSProperties = {
    position: "absolute",
    // WHY left = paletteWidth: the SVG starts at the right edge of the drawing palette.
    // The palette is 28px (w-7). If left=0, the SVG would cover the palette buttons.
    left: paletteWidth,
    top: 0,
    // WHY calc: SVG width = container width - palette width.
    // Using calc avoids needing the container's measured pixel width.
    width: `calc(100% - ${paletteWidth}px)`,
    height: chartHeight,
    pointerEvents: activeTool ? "all" : "none",
    cursor: activeTool ? "crosshair" : "default",
    zIndex: 5, // above chart canvas (z-index ~0), below palette (z-10)
  };

  // WHY React Fragment (not single SVG): the TEXT tool needs an absolutely-positioned
  // <input> HTML element rendered as a sibling to the SVG. HTML inputs cannot be
  // placed inside an SVG element — the browser ignores them. A Fragment lets us
  // return both the SVG and the input without adding a wrapper div (which would
  // affect the absolutely-positioned layout used by OHLCVChart).
  return (
    <>
      <svg
        ref={svgRef}
        style={svgStyle}
        onClick={handleSvgClick}
        onMouseMove={handleMouseMove}
        data-testid="drawing-canvas"
        aria-label="Chart annotation layer"
      >
        {/* ── Persisted annotations ────────────────────────────────────────── */}
        {converters && annotations.map((ann) => (
          <AnnotationShape
            key={ann.id}
            annotation={ann}
            converters={converters}
            onContextMenu={(e) => handleContextMenu(e, ann.id)}
          />
        ))}

        {/* ── In-progress preview ──────────────────────────────────────────── */}
        {/* WHY dashed line: the preview line shows where the annotation will go
            before the user commits it with the second click. Dashed distinguishes
            it from already-committed annotations (solid lines). */}
        {inProgress && inProgress.points.length > 0 && inProgress.mousePixel && converters && (
          <PreviewLine
            startPoint={inProgress.points[0]}
            mousePixel={inProgress.mousePixel}
            converters={converters}
            color={ANNOTATION_COLOR}
          />
        )}
      </svg>

      {/* ── TEXT tool inline label input ────────────────────────────────────
          WHY absolutely positioned sibling: placed at the click pixel so it
          appears inline on the chart, like TradingView's text annotation input.
          WHY z-20: must appear above the SVG canvas (z-5) and palette (z-10).
          WHY min-w-[80px] max-w-[200px]: minimum fits a short ticker symbol;
          maximum prevents the input from overflowing the chart edges.
          WHY font-mono text-[11px]: matches the Terminal Dark data density
          convention. Users annotate with ticker/event names, not prose. */}
      {pendingTextPixel && (
        <input
          id={textInputId}
          ref={textInputRef}
          type="text"
          placeholder="Label…"
          data-testid="text-annotation-input"
          className="absolute z-20 rounded-[2px] px-2 py-0.5 border border-border bg-card text-foreground font-mono text-[11px] tabular-nums min-w-[80px] max-w-[200px] focus:outline focus:outline-1 focus:outline-primary"
          style={{
            // WHY top = y pixel: places the input at the vertical click position.
            top: pendingTextPixel.y,
            // WHY left = x + paletteWidth: the SVG starts at paletteWidth from
            // the wrapper left edge. pendingTextPixel.x is relative to the SVG.
            // Adding paletteWidth converts to wrapper-relative coordinates.
            left: pendingTextPixel.x + paletteWidth,
          }}
          onKeyDown={handleTextInputKeyDown}
          // WHY onBlur commit: clicking outside the input (e.g., clicking another
          // chart area) should commit the typed text rather than discard it.
          // Empty onBlur cancels (no annotation created).
          onBlur={(e) => handleTextInputCommit(e.currentTarget.value)}
        />
      )}
    </>
  );
}

// ── AnnotationShape ───────────────────────────────────────────────────────────

/**
 * AnnotationShape — renders a single annotation as an SVG element.
 *
 * WHY a separate component (not inline in DrawingCanvas): each annotation type
 * (line, rect, fib, etc.) has distinct rendering logic. Separating into a
 * component keeps the parent render function clean and makes each shape testable
 * independently.
 *
 * WHY re-render on converters change: when the user pans or zooms, the chart
 * updates the coordinate converters' internal state. The SVG elements need to
 * re-render to pick up the new pixel positions. We rely on the parent's
 * `converters` prop reference to trigger re-renders.
 *
 * NOTE: lightweight-charts doesn't expose a "viewport changed" event that we can
 * subscribe to for triggering SVG re-renders. As a result, annotations may lag by
 * one frame on pan/zoom. This is an acceptable limitation for Wave C — a full
 * solution would require subscribing to the chart's subscribeVisibleLogicalRangeChange
 * event (tracked as PLAN-0053 deferred work).
 */
function AnnotationShape({
  annotation,
  converters,
  onContextMenu,
}: {
  annotation: Annotation;
  converters: CoordinateConverter;
  onContextMenu: (e: React.MouseEvent) => void;
}) {
  const color = annotation.color;
  // WHY 12px hit area (strokeWidth for pointer events): annotation lines are 1.5px
  // thick. A 1.5px pointer target is impossible to click accurately. We set
  // strokeWidth=12 on a transparent duplicate path for the hit area.
  const hitAreaProps = {
    stroke: "transparent",
    strokeWidth: 12,
    fill: "none",
    style: { cursor: "context-menu" } as React.CSSProperties,
    onContextMenu,
  };

  switch (annotation.tool) {
    case "TREND_LINE":
    case "ARROW":
    case "FIB_RETRACEMENT": {
      const p1 = chartPointToPixel(annotation.points[0], converters);
      const p2 = chartPointToPixel(annotation.points[1], converters);
      const isArrow = annotation.tool === "ARROW";

      if (annotation.tool === "FIB_RETRACEMENT") {
        // Fib retracement: draw horizontal lines at 0%, 23.6%, 38.2%, 50%, 61.8%, 78.6%, 100%
        const levels = [0, 0.236, 0.382, 0.5, 0.618, 0.786, 1.0];
        const priceRange = annotation.points[1].price - annotation.points[0].price;
        return (
          <g data-testid={`annotation-${annotation.id}`}>
            {levels.map((level) => {
              const price = annotation.points[0].price + priceRange * (1 - level);
              const py = converters.series.priceToCoordinate(price) as number | null;
              if (py === null) return null;
              return (
                <g key={level}>
                  <line
                    x1={Math.min(p1.x, p2.x)}
                    y1={py}
                    x2={Math.max(p1.x, p2.x)}
                    y2={py}
                    stroke={level === 0 || level === 1 ? color : `${color}99`}
                    strokeWidth={level === 0 || level === 1 ? 1.5 : 1}
                    strokeDasharray={level === 0.5 ? "4 2" : undefined}
                  />
                  <text
                    x={Math.max(p1.x, p2.x) + 4}
                    y={py + 4}
                    fill={color}
                    fontSize={9}
                    fontFamily="IBM Plex Mono, monospace"
                  >
                    {(level * 100).toFixed(1)}%
                  </text>
                  <line {...hitAreaProps} x1={Math.min(p1.x, p2.x)} y1={py} x2={Math.max(p1.x, p2.x)} y2={py} />
                </g>
              );
            })}
          </g>
        );
      }

      return (
        <g data-testid={`annotation-${annotation.id}`}>
          <line
            x1={p1.x} y1={p1.y} x2={p2.x} y2={p2.y}
            stroke={color}
            strokeWidth={1.5}
            markerEnd={isArrow ? `url(#arrow-${annotation.id})` : undefined}
          />
          {isArrow && (
            // WHY inline marker def: SVG <marker> elements must be in a <defs> block.
            // We use a per-annotation ID to avoid shared marker color conflicts when
            // annotations have different colors.
            <defs>
              <marker
                id={`arrow-${annotation.id}`}
                markerWidth="8"
                markerHeight="8"
                refX="6"
                refY="3"
                orient="auto"
              >
                <path d="M0,0 L0,6 L8,3 z" fill={color} />
              </marker>
            </defs>
          )}
          {/* Invisible wide line for click-to-delete hit area */}
          <line {...hitAreaProps} x1={p1.x} y1={p1.y} x2={p2.x} y2={p2.y} />
        </g>
      );
    }

    case "HORIZONTAL_LEVEL": {
      // WHY 0 to 100%: horizontal levels span the full chart width to show the
      // price level as a global reference — not just between two time points.
      const py = converters.series.priceToCoordinate(annotation.price) as number | null;
      if (py === null) return null;
      return (
        <g data-testid={`annotation-${annotation.id}`}>
          <line
            x1={0} y1={py} x2="100%" y2={py}
            stroke={color}
            strokeWidth={1}
            strokeDasharray="4 3"
          />
          <text
            x={4} y={py - 3}
            fill={color}
            fontSize={9}
            fontFamily="IBM Plex Mono, monospace"
          >
            {annotation.price.toFixed(2)}
          </text>
          <line {...hitAreaProps} x1={0} y1={py} x2="100%" y2={py} />
        </g>
      );
    }

    case "RECTANGLE": {
      const tl = chartPointToPixel(annotation.topLeft, converters);
      const br = chartPointToPixel(annotation.bottomRight, converters);
      const x = Math.min(tl.x, br.x);
      const y = Math.min(tl.y, br.y);
      const w = Math.abs(br.x - tl.x);
      const h = Math.abs(br.y - tl.y);
      return (
        <g data-testid={`annotation-${annotation.id}`}>
          <rect
            x={x} y={y} width={w} height={h}
            stroke={color}
            strokeWidth={1.5}
            fill={`${color}18`} // 10% opacity fill
            onContextMenu={onContextMenu}
            style={{ cursor: "context-menu" }}
          />
        </g>
      );
    }

    case "PARALLEL_CHANNEL": {
      // WHY 3 points: the first two define the direction line, the third defines
      // the parallel offset. The channel is drawn as two parallel lines + a fill.
      const p1 = chartPointToPixel(annotation.points[0], converters);
      const p2 = chartPointToPixel(annotation.points[1], converters);
      const p3 = chartPointToPixel(annotation.points[2], converters);
      // Compute the offset vector from p1 to p3 (perpendicular displacement)
      const dx = p3.x - p1.x;
      const dy = p3.y - p1.y;
      return (
        <g data-testid={`annotation-${annotation.id}`}>
          <line x1={p1.x} y1={p1.y} x2={p2.x} y2={p2.y} stroke={color} strokeWidth={1.5} />
          <line
            x1={p1.x + dx} y1={p1.y + dy}
            x2={p2.x + dx} y2={p2.y + dy}
            stroke={color} strokeWidth={1.5}
          />
          <polygon
            points={`${p1.x},${p1.y} ${p2.x},${p2.y} ${p2.x + dx},${p2.y + dy} ${p1.x + dx},${p1.y + dy}`}
            fill={`${color}14`}
            stroke="none"
            onContextMenu={onContextMenu}
            style={{ cursor: "context-menu" }}
          />
          <line {...hitAreaProps} x1={p1.x} y1={p1.y} x2={p2.x} y2={p2.y} />
        </g>
      );
    }

    case "TEXT": {
      const anchor = chartPointToPixel(annotation.anchor, converters);
      return (
        <g data-testid={`annotation-${annotation.id}`} onContextMenu={onContextMenu} style={{ cursor: "context-menu" }}>
          {/* Small circle marker at the anchor point */}
          <circle cx={anchor.x} cy={anchor.y} r={3} fill={color} />
          <text
            x={anchor.x + 5}
            y={anchor.y - 5}
            fill={color}
            fontSize={10}
            fontFamily="IBM Plex Mono, monospace"
            // WHY stroke + fill: the stroke creates a dark outline that makes
            // the text readable over both light and dark chart candles.
            stroke="#09090B"
            strokeWidth={2}
            paintOrder="stroke"
          >
            {annotation.text}
          </text>
        </g>
      );
    }

    default:
      return null;
  }
}

// ── PreviewLine ───────────────────────────────────────────────────────────────

/**
 * PreviewLine — dashed line from the first click point to the current mouse position.
 *
 * WHY this renders during in-progress drawing: without a preview line, the user has
 * no visual feedback between their first click and their second click. They need to
 * see where the line will go before committing. TradingView uses the same preview.
 */
function PreviewLine({
  startPoint,
  mousePixel,
  converters,
  color,
}: {
  startPoint: ChartPoint;
  mousePixel: { x: number; y: number };
  converters: CoordinateConverter;
  color: string;
}) {
  const start = chartPointToPixel(startPoint, converters);
  if (start.x === -9999 || start.y === -9999) return null;

  return (
    <line
      x1={start.x}
      y1={start.y}
      x2={mousePixel.x}
      y2={mousePixel.y}
      stroke={color}
      strokeWidth={1}
      strokeDasharray="5 3"
      // WHY pointer-events="none": the preview line should never intercept clicks
      // (the SVG element captures them at the root level). If the preview line
      // captured clicks, it would block the second click from registering the
      // endpoint of the annotation.
      pointerEvents="none"
      opacity={0.7}
    />
  );
}
