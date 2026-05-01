/**
 * lib/treemap.ts — Squarified treemap algorithm (Bruls/Huijsen/van Wijk 2000)
 *
 * WHY THIS EXISTS: Today MarketHeatmap and SectorHeatmapWidget render two
 * different ad-hoc grid-y layouts that look like "stickers from a different
 * app" (UX agent finding). The Bruls/Huijsen/van Wijk (BHvW) squarified
 * algorithm packs rectangles so their aspect ratio is as close to 1 as
 * possible — every block reads as a *square-ish* tile, scanning becomes
 * predictable, and large blocks visually dominate proportional to weight.
 *
 * PROPERTIES (proven by BHvW paper):
 *   - All cells together exactly fill the rectangle (no gaps).
 *   - Maximum aspect ratio per cell ≤ 2× as long as input is sorted desc by weight.
 *   - O(n log n) — sort dominates; layout itself is linear.
 *
 * REFERENCE: "Squarified Treemaps" Bruls, Huijsen, van Wijk, 2000.
 *   https://www.win.tue.nl/~vanwijk/stm.pdf
 *
 * ALGORITHM (recursive):
 *   1. Sort weights descending.
 *   2. Pick the shorter side of the remaining rectangle as the "row direction".
 *   3. Greedily add weights to a candidate row while the worst aspect ratio
 *      of cells in that row improves; stop when adding another would make it
 *      worse.
 *   4. Lay out the chosen row across the short side, advance the rectangle
 *      origin past the row, recurse on the remaining weights + remainder rect.
 *
 * USED BY: components/dashboard/MarketHeatmap.tsx,
 *          components/dashboard/SectorHeatmapWidget.tsx.
 */

export interface TreemapInput<T> {
  /** The original payload — preserved through layout, attached to each cell. */
  item: T;
  /** Non-negative weight (e.g. market cap). Zero weights are filtered out. */
  weight: number;
}

export interface TreemapCell<T> {
  item: T;
  weight: number;
  /** Cell origin x (relative to the input rectangle origin). */
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface TreemapRect {
  x: number;
  y: number;
  width: number;
  height: number;
}

/** Worst aspect ratio of cells in a row when laid out along `length`. */
function worstAspect(rowWeights: number[], rowSum: number, length: number, scale: number): number {
  if (rowSum === 0 || length === 0) return Infinity;
  // After scaling, the row occupies an area `rowSum * scale`. Laid across
  // `length`, each cell width = (cellWeight * scale) / sideLength,
  // height = sideLength. Aspect ratio = max(w/h, h/w) per cell.
  const sideLength = (rowSum * scale) / length;
  let worst = 0;
  for (const w of rowWeights) {
    const cellLong = (w * scale) / sideLength; // = w * length / rowSum
    const ratio = Math.max(cellLong / sideLength, sideLength / cellLong);
    if (ratio > worst) worst = ratio;
  }
  return worst;
}

/**
 * squarify — Bruls/Huijsen/van Wijk treemap layout.
 *
 * @param items   list of {item, weight}; weights must be ≥ 0.
 * @param rect    the rectangle to subdivide.
 * @returns       cells, all together filling exactly the rect.
 *
 * Empty input returns []. Negative weights are clamped to 0 (filtered out).
 * If the total weight is 0, returns [] (nothing to render).
 */
export function squarify<T>(
  items: TreemapInput<T>[],
  rect: TreemapRect,
): TreemapCell<T>[] {
  // Filter + sort descending. WHY clone: avoid mutating caller's array.
  const sorted = items
    .filter((it) => Number.isFinite(it.weight) && it.weight > 0)
    .slice()
    .sort((a, b) => b.weight - a.weight);

  if (sorted.length === 0) return [];

  const totalArea = rect.width * rect.height;
  const totalWeight = sorted.reduce((s, it) => s + it.weight, 0);
  if (totalWeight === 0 || totalArea === 0) return [];

  // Scale factor: every weight unit → `scale` pixel-area units.
  const scale = totalArea / totalWeight;

  const cells: TreemapCell<T>[] = [];
  // Working rectangle — shrinks each row.
  let cur: TreemapRect = { ...rect };
  let i = 0;

  while (i < sorted.length) {
    const shortSide = Math.min(cur.width, cur.height);
    const row: TreemapInput<T>[] = [];
    let rowSum = 0;
    let bestWorst = Infinity;

    // Greedy: add weights while the worst aspect improves.
    while (i < sorted.length) {
      const candidateRow = [...row, sorted[i]];
      const candidateSum = rowSum + sorted[i].weight;
      const candidateWorst = worstAspect(
        candidateRow.map((c) => c.weight),
        candidateSum,
        shortSide,
        scale,
      );
      if (candidateWorst > bestWorst && row.length > 0) break;
      row.push(sorted[i]);
      rowSum = candidateSum;
      bestWorst = candidateWorst;
      i++;
    }

    // Lay out the row along the short side.
    const rowAreaPx = rowSum * scale;
    const rowDepth = rowAreaPx / shortSide;
    let cursor = 0;
    for (const it of row) {
      const cellLength = (it.weight * scale) / rowDepth;
      if (cur.width <= cur.height) {
        // Row runs horizontally across the top of `cur`.
        cells.push({
          item: it.item,
          weight: it.weight,
          x: cur.x + cursor,
          y: cur.y,
          width: cellLength,
          height: rowDepth,
        });
      } else {
        // Row runs vertically down the left of `cur`.
        cells.push({
          item: it.item,
          weight: it.weight,
          x: cur.x,
          y: cur.y + cursor,
          width: rowDepth,
          height: cellLength,
        });
      }
      cursor += cellLength;
    }

    // Advance the working rectangle past the row we just placed.
    if (cur.width <= cur.height) {
      cur = {
        x: cur.x,
        y: cur.y + rowDepth,
        width: cur.width,
        height: cur.height - rowDepth,
      };
    } else {
      cur = {
        x: cur.x + rowDepth,
        y: cur.y,
        width: cur.width - rowDepth,
        height: cur.height,
      };
    }
  }

  return cells;
}
