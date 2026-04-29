/**
 * lib/instrument-context.ts — Studies & annotations state schema for OHLCVChart
 *
 * WHY THIS EXISTS: The chart toolbar now supports 7+ technical indicators and a
 * drawing palette. We need:
 *   (a) A typed state schema so TypeScript catches config mismatches.
 *   (b) Persistence — analysts expect their indicator selections to survive a
 *       page refresh. Indicators are per-session (localStorage) because they are
 *       display preferences. Annotations are per-instrument (IndexedDB) because
 *       trend lines drawn on AAPL mean nothing on MSFT.
 *
 * WHY IndexedDB (not localStorage) for annotations: Each annotation set can be
 * several KB (many coordinates). IndexedDB is async and quota-managed — localStorage
 * is synchronous and limited to 5MB shared across all origins. IndexedDB also
 * supports atomic put/get per instrument_id without deserialising the whole store.
 *
 * WHY localStorage for indicator config: Indicator on/off toggles are tiny (~200
 * bytes). Sync read avoids a loading flash on chart mount. IndexedDB's async init
 * would require a Suspense boundary or loading state for an insignificant payload.
 *
 * WHO USES IT:
 *   - OHLCVChart.tsx (indicators state + series lifecycle)
 *   - DrawingPalette.tsx (active tool arm)
 *   - DrawingCanvas.tsx (annotation read/write)
 *
 * DESIGN REFERENCE: PLAN-0050 §T-C-3-04
 */

// ── Indicator IDs ─────────────────────────────────────────────────────────────

/**
 * IndicatorId — all supported technical indicators.
 *
 * WHY a string union (not enum): shadcn DropdownMenuCheckboxItem expects string
 * keys for its `checked` attribute comparison. String unions are more portable
 * than enums across JSX props.
 *
 * Indicator inventory:
 *   RSI         — Relative Strength Index (momentum oscillator, 0-100 bound)
 *   MACD        — Moving Average Convergence/Divergence (trend + momentum)
 *   BOLLINGER   — Bollinger Bands (volatility envelope, ±2σ around MA20)
 *   ATR         — Average True Range (volatility measure, absolute $)
 *   STOCHASTIC  — Stochastic Oscillator (%K/%D, 0-100 momentum)
 *   OBV         — On-Balance Volume (volume-driven trend confirmation)
 *   VWAP        — Volume Weighted Average Price (institutional reference price)
 *
 * Volume sub-indicators (controlled via volume submenu):
 *   VOL_MA20       — 20-period MA of raw volume bars
 *   VOL_PROFILE    — Volume Profile (right-side horizontal histogram)
 *   VWAP_LINE      — Anchored-daily VWAP line on main price scale
 */
export type IndicatorId =
  | "RSI"
  | "MACD"
  | "BOLLINGER"
  | "ATR"
  | "STOCHASTIC"
  | "OBV"
  | "VWAP"
  | "VOL_MA20"
  | "VOL_PROFILE"
  | "VWAP_LINE";

// ── Indicator configuration ───────────────────────────────────────────────────

/**
 * IndicatorConfig — per-indicator settings.
 *
 * WHY `enabled` (not just presence in the map): we persist the full map so that
 * toggling an indicator off preserves its `period` config. If we deleted keys on
 * disable, the period would reset to default on next enable — annoying for analysts
 * who customise RSI to 14 (default), MACD to (8,17,9) etc.
 *
 * WHY optional `period` (not required): some indicators don't use a simple period
 * (e.g., MACD uses fast/slow/signal triple, VWAP uses session anchor). We store
 * the extra params in `params` for extensibility.
 */
export interface IndicatorConfig {
  /** Whether the indicator series is currently visible on the chart */
  enabled: boolean;
  /**
   * Primary smoothing period — applies to RSI (14), ATR (14), Stochastic (14),
   * OBV (not used), VWAP (not used). Omit for indicators with custom params.
   */
  period?: number;
  /**
   * Indicator-specific overrides. Examples:
   *   MACD: { fast: 12, slow: 26, signal: 9 }
   *   BOLLINGER: { period: 20, stdDev: 2 }
   *   STOCHASTIC: { kPeriod: 14, dPeriod: 3, smoothing: 3 }
   */
  params?: Record<string, number>;
}

// ── Drawing tool types ────────────────────────────────────────────────────────

/**
 * DrawingToolId — all supported drawing palette tools.
 *
 * WHY these specific tools: they mirror TradingView's "Essential" drawing set.
 * Trend lines, horizontal levels, and rectangles cover 80% of analyst drawings.
 * Fib retracements and parallel channels cover swing trading workflows.
 * Arrows and text annotations cover annotation/note-taking workflows.
 */
export type DrawingToolId =
  | "TREND_LINE"
  | "HORIZONTAL_LEVEL"
  | "RECTANGLE"
  | "ARROW"
  | "FIB_RETRACEMENT"
  | "PARALLEL_CHANNEL"
  | "TEXT";

// ── Annotation data structures ────────────────────────────────────────────────

/** A single 2D point in price/time space */
export interface ChartPoint {
  /** Unix timestamp (seconds) — lightweight-charts time scale unit */
  time: number;
  /** Price at this point (Y axis) */
  price: number;
}

/** Base fields shared by all annotation types */
interface AnnotationBase {
  /** Stable ID — used for IndexedDB upsert key */
  id: string;
  /** Which tool created this annotation */
  tool: DrawingToolId;
  /** When this annotation was created (ISO string) */
  createdAt: string;
  /** Display color — hex string from Midnight Pro palette */
  color: string;
}

/** Trend line: two price+time anchor points */
export interface TrendLineAnnotation extends AnnotationBase {
  tool: "TREND_LINE";
  points: [ChartPoint, ChartPoint];
}

/** Horizontal level: a single price, drawn across the full time scale */
export interface HorizontalLevelAnnotation extends AnnotationBase {
  tool: "HORIZONTAL_LEVEL";
  price: number;
}

/** Rectangle: top-left and bottom-right corners */
export interface RectangleAnnotation extends AnnotationBase {
  tool: "RECTANGLE";
  topLeft: ChartPoint;
  bottomRight: ChartPoint;
}

/** Arrow: start and end points */
export interface ArrowAnnotation extends AnnotationBase {
  tool: "ARROW";
  points: [ChartPoint, ChartPoint];
}

/** Fibonacci retracement: two price+time anchor points (high/low) */
export interface FibRetracementAnnotation extends AnnotationBase {
  tool: "FIB_RETRACEMENT";
  points: [ChartPoint, ChartPoint];
}

/** Parallel channel: three points (two on one line, one on the parallel) */
export interface ParallelChannelAnnotation extends AnnotationBase {
  tool: "PARALLEL_CHANNEL";
  points: [ChartPoint, ChartPoint, ChartPoint];
}

/** Text annotation: a single price+time anchor with a label */
export interface TextAnnotation extends AnnotationBase {
  tool: "TEXT";
  anchor: ChartPoint;
  text: string;
}

/** Union of all annotation types */
export type Annotation =
  | TrendLineAnnotation
  | HorizontalLevelAnnotation
  | RectangleAnnotation
  | ArrowAnnotation
  | FibRetracementAnnotation
  | ParallelChannelAnnotation
  | TextAnnotation;

// ── Top-level state shape ─────────────────────────────────────────────────────

/**
 * InstrumentChartState — full state schema for chart studies and annotations.
 *
 * WHY split into `indicators` + `annotations`:
 *   - `indicators`: per-session preference (persisted in localStorage)
 *   - `annotations`: per-instrument drawings (persisted in IndexedDB by instrument_id)
 *
 * Both are stored on this single interface so OHLCVChart can hold one state atom
 * and pass slices to child components via props.
 */
export interface InstrumentChartState {
  /**
   * Map of indicator ID → config. Contains an entry for every supported indicator
   * (enabled or disabled) to avoid undefined checks in indicator render effects.
   */
  indicators: Record<IndicatorId, IndicatorConfig>;
  /**
   * Drawing annotations for the current instrument. Populated from IndexedDB on
   * mount (async). Empty array while the IndexedDB read is pending.
   */
  annotations: Annotation[];
}

// ── Default state ─────────────────────────────────────────────────────────────

/**
 * DEFAULT_INDICATOR_STATE — factory for the initial indicators map.
 *
 * WHY factory function (not a const): each chart instance must get its own object
 * reference. Sharing a const across multiple charts would cause cross-chart state
 * bleeding (if one chart mutates a nested object — even accidentally via spread).
 *
 * Default periods match TradingView defaults:
 *   RSI=14, ATR=14, Stochastic=14, MACD fast=12/slow=26/signal=9, BB period=20/stdDev=2
 */
export function createDefaultIndicatorState(): Record<IndicatorId, IndicatorConfig> {
  return {
    RSI:        { enabled: false, period: 14 },
    MACD:       { enabled: false, params: { fast: 12, slow: 26, signal: 9 } },
    BOLLINGER:  { enabled: false, params: { period: 20, stdDev: 2 } },
    ATR:        { enabled: false, period: 14 },
    STOCHASTIC: { enabled: false, params: { kPeriod: 14, dPeriod: 3, smoothing: 3 } },
    OBV:        { enabled: false },
    VWAP:       { enabled: false },
    VOL_MA20:   { enabled: false, period: 20 },
    VOL_PROFILE:{ enabled: false },
    VWAP_LINE:  { enabled: false },
  };
}

// ── localStorage persistence for indicator config ─────────────────────────────

const INDICATOR_STORAGE_KEY = "worldview:chart:indicators:v1";

/**
 * loadIndicatorsFromStorage — read saved indicator config from localStorage.
 *
 * WHY try/catch: localStorage can throw SecurityError in private browsing or when
 * storage is full. We fall back to defaults silently — analysts lose their
 * preferences but the chart still works.
 *
 * WHY JSON.parse guard: if the stored JSON is corrupt (truncated write), we fall
 * back to defaults rather than crashing the chart.
 */
export function loadIndicatorsFromStorage(): Record<IndicatorId, IndicatorConfig> {
  const defaults = createDefaultIndicatorState();
  if (typeof window === "undefined") return defaults; // SSR guard
  try {
    const raw = localStorage.getItem(INDICATOR_STORAGE_KEY);
    if (!raw) return defaults;
    const parsed = JSON.parse(raw) as Partial<Record<IndicatorId, IndicatorConfig>>;
    // Merge with defaults so newly added indicators (from future waves) appear
    return { ...defaults, ...parsed };
  } catch {
    return defaults;
  }
}

/**
 * saveIndicatorsToStorage — persist indicator config to localStorage.
 *
 * WHY called on every toggle (not on unmount): if the user closes the tab
 * immediately after toggling, an unmount write may not fire. Eager writes ensure
 * the preference is always saved.
 */
export function saveIndicatorsToStorage(indicators: Record<IndicatorId, IndicatorConfig>): void {
  if (typeof window === "undefined") return;
  try {
    localStorage.setItem(INDICATOR_STORAGE_KEY, JSON.stringify(indicators));
  } catch {
    // Ignore storage quota errors — the in-memory state is still correct
  }
}

// ── IndexedDB persistence for annotations ─────────────────────────────────────

const IDB_DB_NAME = "worldview-chart-annotations";
const IDB_STORE_NAME = "annotations";
const IDB_VERSION = 1;

/**
 * openAnnotationsDB — open (or create) the IndexedDB database.
 *
 * WHY singleton promise: multiple concurrent callers (e.g., load + immediate save)
 * should share the same IDBDatabase instance rather than opening multiple connections.
 * We cache the promise so the second caller awaits the same open operation.
 *
 * WHY `indexed.createObjectStore` with keyPath "id": each annotation has a stable
 * UUID `id` field. Using `id` as the keyPath means put() acts as an upsert (insert
 * or replace) — idempotent, safe to call multiple times with the same annotation.
 */
let _dbPromise: Promise<IDBDatabase> | null = null;

function getAnnotationsDB(): Promise<IDBDatabase> {
  if (typeof window === "undefined") {
    // SSR: return a promise that never resolves (annotations are browser-only)
    return new Promise(() => {});
  }
  if (!_dbPromise) {
    _dbPromise = new Promise((resolve, reject) => {
      const request = indexedDB.open(IDB_DB_NAME, IDB_VERSION);
      request.onupgradeneeded = (event) => {
        const db = (event.target as IDBOpenDBRequest).result;
        if (!db.objectStoreNames.contains(IDB_STORE_NAME)) {
          // WHY keyPath "instrumentId" on the outer store but "id" on individual
          // annotation records: we store ONE record per instrumentId where the
          // value is an array of Annotation[]. This avoids O(n) cursor scans
          // to load all annotations for one instrument.
          const store = db.createObjectStore(IDB_STORE_NAME, { keyPath: "instrumentId" });
          // Index allows querying by instrumentId — currently redundant (keyPath)
          // but future-proofs if we ever move to per-annotation records.
          store.createIndex("instrumentId", "instrumentId", { unique: true });
        }
      };
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
    });
  }
  return _dbPromise;
}

/**
 * loadAnnotationsFromIDB — load all annotations for a specific instrument.
 *
 * WHY returns empty array on any failure: annotations are decorative overlays.
 * If IDB is unavailable (private mode, corrupted DB), the chart still works —
 * the analyst just loses their drawings. A crash here would break the chart.
 *
 * @param instrumentId  The instrument's instrument_id (e.g., "ins-AAPL-001")
 */
export async function loadAnnotationsFromIDB(instrumentId: string): Promise<Annotation[]> {
  try {
    const db = await getAnnotationsDB();
    return new Promise((resolve) => {
      const tx = db.transaction(IDB_STORE_NAME, "readonly");
      const store = tx.objectStore(IDB_STORE_NAME);
      const request = store.get(instrumentId);
      request.onsuccess = () => {
        const record = request.result as { instrumentId: string; annotations: Annotation[] } | undefined;
        resolve(record?.annotations ?? []);
      };
      request.onerror = () => resolve([]);
    });
  } catch {
    return [];
  }
}

/**
 * saveAnnotationsToIDB — persist the full annotation list for an instrument.
 *
 * WHY full replace (not per-annotation upsert): the annotation array is small
 * (typically <50 items). Replacing the whole record on each change is simpler
 * and avoids out-of-order partial writes if the user draws quickly.
 *
 * WHY fire-and-forget (no return value): callers don't need to await the write.
 * The in-memory state is the source of truth; IDB is just the backup store.
 *
 * @param instrumentId  The instrument's instrument_id
 * @param annotations   Full current annotation list
 */
export async function saveAnnotationsToIDB(
  instrumentId: string,
  annotations: Annotation[],
): Promise<void> {
  try {
    const db = await getAnnotationsDB();
    await new Promise<void>((resolve, reject) => {
      const tx = db.transaction(IDB_STORE_NAME, "readwrite");
      const store = tx.objectStore(IDB_STORE_NAME);
      const request = store.put({ instrumentId, annotations });
      request.onsuccess = () => resolve();
      request.onerror = () => reject(request.error);
    });
  } catch {
    // Ignore — in-memory state is still correct
  }
}

// ── Indicator computation helpers ─────────────────────────────────────────────

/**
 * Bar type used internally by all indicator computations.
 * Matches the formatted bars produced by OHLCVChart's useEffect.
 */
export interface FormattedBar {
  time: number;   // Unix seconds
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

/** Output type for oscillator-style indicators (RSI, ATR, STOCHASTIC) */
export interface LinePoint {
  time: number;
  value: number;
}

// ── RSI ───────────────────────────────────────────────────────────────────────

/**
 * computeRSI — Wilder's Relative Strength Index.
 *
 * WHY Wilder's smoothing (not SMA): the industry standard RSI uses Wilder's
 * exponential smoothing for the average gain/loss. SMA-based RSI gives different
 * readings than Bloomberg/TradingView — analysts would notice the discrepancy.
 *
 * Algorithm:
 *   1. Compute daily price changes (close[i] - close[i-1]).
 *   2. Separate into gains (positive changes) and losses (absolute negative changes).
 *   3. Seed the first avgGain/avgLoss as the SMA of the first `period` changes.
 *   4. For subsequent bars: avgGain = (prevAvgGain * (period-1) + gain) / period
 *   5. RS = avgGain / avgLoss; RSI = 100 - (100 / (1 + RS))
 *
 * @param bars    Formatted bars (need at least period+1 bars)
 * @param period  Lookback period (default 14 = industry standard)
 */
export function computeRSI(bars: FormattedBar[], period: number = 14): LinePoint[] {
  if (bars.length < period + 1) return [];

  const changes = bars.slice(1).map((b, i) => b.close - bars[i].close);
  const gains = changes.map((c) => (c > 0 ? c : 0));
  const losses = changes.map((c) => (c < 0 ? Math.abs(c) : 0));

  // Seed: SMA of first `period` gains/losses
  let avgGain = gains.slice(0, period).reduce((s, g) => s + g, 0) / period;
  let avgLoss = losses.slice(0, period).reduce((s, l) => s + l, 0) / period;

  const result: LinePoint[] = [];

  // First RSI value at index `period` (needs period+1 bars)
  const rs0 = avgLoss === 0 ? Infinity : avgGain / avgLoss;
  result.push({ time: bars[period].time, value: avgLoss === 0 ? 100 : 100 - 100 / (1 + rs0) });

  // Wilder's smoothing for subsequent bars
  for (let i = period; i < changes.length; i++) {
    avgGain = (avgGain * (period - 1) + gains[i]) / period;
    avgLoss = (avgLoss * (period - 1) + losses[i]) / period;
    const rs = avgLoss === 0 ? Infinity : avgGain / avgLoss;
    result.push({
      time: bars[i + 1].time,
      value: avgLoss === 0 ? 100 : 100 - 100 / (1 + rs),
    });
  }

  return result;
}

// ── MACD ──────────────────────────────────────────────────────────────────────

/** MACD outputs: MACD line, signal line, and histogram */
export interface MACDPoint {
  time: number;
  macd: number;
  signal: number;
  histogram: number;
}

/**
 * computeEMA — Exponential Moving Average helper for MACD.
 *
 * WHY EMA (not SMA) for MACD: MACD is defined as EMA(fast) - EMA(slow).
 * SMA would give a different result than TradingView/Bloomberg.
 *
 * Seeding: the first EMA value is the SMA of the first `period` closes.
 * WHY SMA seed: Wilder's "warm-up" technique — avoids the first EMA value
 * being equal to just the very first close (which would be noisy).
 */
function computeEMA(closes: number[], period: number): number[] {
  if (closes.length < period) return [];
  const k = 2 / (period + 1); // EMA multiplier
  let ema = closes.slice(0, period).reduce((s, c) => s + c, 0) / period;
  const result: number[] = new Array(period - 1).fill(NaN);
  result.push(ema);
  for (let i = period; i < closes.length; i++) {
    ema = closes[i] * k + ema * (1 - k);
    result.push(ema);
  }
  return result;
}

/**
 * computeMACD — Moving Average Convergence/Divergence.
 *
 * Standard parameters: fast=12, slow=26, signal=9 (industry convention).
 * MACD line = EMA(fast) - EMA(slow)
 * Signal line = EMA(signal) of MACD line
 * Histogram = MACD line - Signal line
 */
export function computeMACD(
  bars: FormattedBar[],
  fast: number = 12,
  slow: number = 26,
  signal: number = 9,
): MACDPoint[] {
  const closes = bars.map((b) => b.close);
  const emaFast = computeEMA(closes, fast);
  const emaSlow = computeEMA(closes, slow);

  // MACD line starts where both EMAs are valid (after slow period)
  const macdLine: number[] = [];
  const macdTimes: number[] = [];
  for (let i = slow - 1; i < bars.length; i++) {
    if (!isNaN(emaFast[i]) && !isNaN(emaSlow[i])) {
      macdLine.push(emaFast[i] - emaSlow[i]);
      macdTimes.push(bars[i].time);
    }
  }

  // Signal line = EMA(signal) of MACD line
  const signalLine = computeEMA(macdLine, signal);

  const result: MACDPoint[] = [];
  for (let i = signal - 1; i < macdLine.length; i++) {
    if (!isNaN(signalLine[i])) {
      result.push({
        time: macdTimes[i],
        macd: macdLine[i],
        signal: signalLine[i],
        histogram: macdLine[i] - signalLine[i],
      });
    }
  }
  return result;
}

// ── Bollinger Bands ───────────────────────────────────────────────────────────

/** Bollinger Bands output: middle (SMA), upper (SMA + 2σ), lower (SMA - 2σ) */
export interface BollingerPoint {
  time: number;
  upper: number;
  middle: number;
  lower: number;
}

/**
 * computeBollinger — Bollinger Bands.
 *
 * Standard parameters: period=20, stdDev=2 (John Bollinger's original formula).
 * Middle = SMA(period); Upper/Lower = Middle ± stdDev * σ(period)
 * σ = population standard deviation (not sample — matches TradingView).
 */
export function computeBollinger(
  bars: FormattedBar[],
  period: number = 20,
  stdDevMultiplier: number = 2,
): BollingerPoint[] {
  if (bars.length < period) return [];
  const result: BollingerPoint[] = [];
  for (let i = period - 1; i < bars.length; i++) {
    const slice = bars.slice(i - period + 1, i + 1).map((b) => b.close);
    const mean = slice.reduce((s, c) => s + c, 0) / period;
    const variance = slice.reduce((s, c) => s + (c - mean) ** 2, 0) / period;
    const sigma = Math.sqrt(variance);
    result.push({
      time: bars[i].time,
      upper: mean + stdDevMultiplier * sigma,
      middle: mean,
      lower: mean - stdDevMultiplier * sigma,
    });
  }
  return result;
}

// ── ATR ───────────────────────────────────────────────────────────────────────

/**
 * computeATR — Average True Range.
 *
 * True Range = max(high-low, |high-prevClose|, |low-prevClose|)
 * ATR = Wilder's EMA of True Range over `period` bars.
 *
 * WHY Wilder's EMA (not SMA): ATR was defined by J. Welles Wilder using his
 * own smoothing. TradingView uses the same. SMA-ATR would diverge.
 */
export function computeATR(bars: FormattedBar[], period: number = 14): LinePoint[] {
  if (bars.length < period + 1) return [];

  const trueRanges = bars.slice(1).map((b, i) => {
    const prevClose = bars[i].close;
    return Math.max(b.high - b.low, Math.abs(b.high - prevClose), Math.abs(b.low - prevClose));
  });

  // Seed: SMA of first `period` true ranges
  let atr = trueRanges.slice(0, period).reduce((s, tr) => s + tr, 0) / period;
  const result: LinePoint[] = [];
  result.push({ time: bars[period].time, value: atr });

  // Wilder's smoothing
  for (let i = period; i < trueRanges.length; i++) {
    atr = (atr * (period - 1) + trueRanges[i]) / period;
    result.push({ time: bars[i + 1].time, value: atr });
  }
  return result;
}

// ── Stochastic ────────────────────────────────────────────────────────────────

/** Stochastic output: %K and %D lines */
export interface StochasticPoint {
  time: number;
  k: number;
  d: number;
}

/**
 * computeStochastic — Stochastic Oscillator (%K and %D).
 *
 * %K = 100 * (close - lowestLow) / (highestHigh - lowestLow) over kPeriod
 * %D = SMA(dPeriod) of %K (known as "slow stochastic")
 * Smoothed %K = SMA(smoothing) of raw %K (optional 3-bar smoothing — "full stochastic")
 *
 * Standard params: kPeriod=14, dPeriod=3, smoothing=3 (matches TradingView "Full Stochastic").
 */
export function computeStochastic(
  bars: FormattedBar[],
  kPeriod: number = 14,
  dPeriod: number = 3,
  smoothing: number = 3,
): StochasticPoint[] {
  if (bars.length < kPeriod + dPeriod) return [];

  // Raw %K
  const rawK: number[] = [];
  for (let i = kPeriod - 1; i < bars.length; i++) {
    const slice = bars.slice(i - kPeriod + 1, i + 1);
    const highest = Math.max(...slice.map((b) => b.high));
    const lowest = Math.min(...slice.map((b) => b.low));
    rawK.push(highest === lowest ? 100 : 100 * (bars[i].close - lowest) / (highest - lowest));
  }

  // Smooth %K (SMA of rawK)
  const smoothedK: number[] = [];
  for (let i = smoothing - 1; i < rawK.length; i++) {
    const s = rawK.slice(i - smoothing + 1, i + 1).reduce((a, v) => a + v, 0) / smoothing;
    smoothedK.push(s);
  }

  // %D = SMA(dPeriod) of smoothed %K
  const result: StochasticPoint[] = [];
  const startIdx = kPeriod - 1 + smoothing - 1;
  for (let i = dPeriod - 1; i < smoothedK.length; i++) {
    const d = smoothedK.slice(i - dPeriod + 1, i + 1).reduce((a, v) => a + v, 0) / dPeriod;
    result.push({
      time: bars[startIdx + i].time,
      k: smoothedK[i],
      d,
    });
  }
  return result;
}

// ── OBV ───────────────────────────────────────────────────────────────────────

/**
 * computeOBV — On-Balance Volume.
 *
 * OBV[i] = OBV[i-1] + volume[i]  if close[i] > close[i-1]
 * OBV[i] = OBV[i-1] - volume[i]  if close[i] < close[i-1]
 * OBV[i] = OBV[i-1]              if close[i] === close[i-1]
 *
 * WHY cumulative sum: OBV measures cumulative buying/selling pressure. Upward
 * OBV trend during a price breakout confirms institutional accumulation.
 */
export function computeOBV(bars: FormattedBar[]): LinePoint[] {
  if (bars.length < 2) return [];
  let obv = 0;
  const result: LinePoint[] = [{ time: bars[0].time, value: 0 }];
  for (let i = 1; i < bars.length; i++) {
    if (bars[i].close > bars[i - 1].close) obv += bars[i].volume;
    else if (bars[i].close < bars[i - 1].close) obv -= bars[i].volume;
    result.push({ time: bars[i].time, value: obv });
  }
  return result;
}

// ── VWAP ──────────────────────────────────────────────────────────────────────

/**
 * computeVWAP — Volume Weighted Average Price.
 *
 * Anchored to the start of the dataset (session-level VWAP). This matches
 * the behaviour most analysts expect when applied to intraday bars — however
 * for daily bars it shows a cumulative VWAP from the first available bar.
 *
 * VWAP[i] = Σ(typicalPrice * volume) / Σ(volume) from bar[0] to bar[i]
 * typicalPrice = (high + low + close) / 3
 *
 * WHY typical price (not close): VWAP convention uses typical price to
 * incorporate the day's range, not just the closing tick.
 */
export function computeVWAP(bars: FormattedBar[]): LinePoint[] {
  let cumTPV = 0; // cumulative (typicalPrice * volume)
  let cumVol = 0; // cumulative volume
  return bars.map((b) => {
    const tp = (b.high + b.low + b.close) / 3;
    cumTPV += tp * b.volume;
    cumVol += b.volume;
    return { time: b.time, value: cumVol === 0 ? b.close : cumTPV / cumVol };
  });
}

// ── Volume MA ─────────────────────────────────────────────────────────────────

/**
 * computeVolumeMA — simple moving average of raw volume.
 *
 * Used for the VOL_MA20 sub-indicator in the volume submenu. Draws a smooth
 * line over the volume histogram bars to show the 20-day average volume level.
 * Bars trading above the MA are "high volume" (conviction moves); below is thin.
 */
export function computeVolumeMA(bars: FormattedBar[], period: number = 20): LinePoint[] {
  if (bars.length < period) return [];
  return bars.slice(period - 1).map((_, i) => ({
    time: bars[i + period - 1].time,
    value: bars.slice(i, i + period).reduce((s, b) => s + b.volume, 0) / period,
  }));
}

// ── Volume Profile ────────────────────────────────────────────────────────────

/** A single price bucket in the volume profile histogram */
export interface VolumeProfileBucket {
  /** Price at the center of this bucket */
  price: number;
  /** Total volume traded within this price bucket */
  volume: number;
  /** Whether this is the Point of Control (highest volume bucket) */
  isPOC: boolean;
}

/**
 * computeVolumeProfile — aggregates volume by price level into histogram buckets.
 *
 * WHY 24 buckets: matches TradingView's default profile resolution. More buckets
 * (>30) become visually noisy at the 280px chart height. Fewer (<15) lose the
 * price clustering signal.
 *
 * Algorithm: divide the [min, max] price range into `numBuckets` equal-width
 * price levels. For each bar, assign its volume to the bucket containing the bar's
 * typical price ((high+low+close)/3).
 *
 * The Point of Control (POC) — the price level with the most volume — is marked
 * separately so the component can highlight it in the SVG overlay.
 */
export function computeVolumeProfile(
  bars: FormattedBar[],
  numBuckets: number = 24,
): VolumeProfileBucket[] {
  if (bars.length === 0) return [];

  const allPrices = bars.flatMap((b) => [b.high, b.low, b.close]);
  const minPrice = Math.min(...allPrices);
  const maxPrice = Math.max(...allPrices);
  const range = maxPrice - minPrice;
  if (range === 0) return [];

  const bucketSize = range / numBuckets;
  const buckets: VolumeProfileBucket[] = Array.from({ length: numBuckets }, (_, i) => ({
    price: minPrice + (i + 0.5) * bucketSize,
    volume: 0,
    isPOC: false,
  }));

  for (const bar of bars) {
    const tp = (bar.high + bar.low + bar.close) / 3;
    const idx = Math.min(Math.floor((tp - minPrice) / bucketSize), numBuckets - 1);
    buckets[idx].volume += bar.volume;
  }

  // Mark the Point of Control
  const maxVol = Math.max(...buckets.map((b) => b.volume));
  for (const bucket of buckets) {
    if (bucket.volume === maxVol) {
      bucket.isPOC = true;
      break;
    }
  }

  return buckets;
}
