/**
 * features/chat/lib/typewriter-buffer.ts — F2 (2026-06-30 chat streaming fix).
 *
 * WHAT THIS IS
 * ------------
 * A tiny, framework-agnostic "typewriter" buffer that DECOUPLES how fast text
 * is PAINTED to the screen from how fast text ARRIVES off the network.
 *
 * WHY WE NEED IT (the "jumpy streaming" bug)
 * ------------------------------------------
 * The chat answer streams in over Server-Sent Events. The number of characters
 * in each network read is completely unpredictable: a proxy can coalesce many
 * server chunks into one read, the backend can emit text in 8-word groups, or
 * (before the F1 backend fix) the WHOLE answer can land in a single burst. If
 * we append each network chunk straight into React state, the answer "pops in"
 * in lumps — it looks jumpy, and on a one-burst arrival it appears all at once.
 *
 * The fix: instead of painting network chunks directly, we PUSH incoming text
 * into a queue and DRAIN that queue at a steady characters-per-frame rate using
 * requestAnimationFrame (rAF). rAF fires once per browser paint (~60fps), so
 * revealing a fixed slice of characters each frame produces a smooth, even
 * typewriter reveal REGARDLESS of how the bytes were framed on the wire. The
 * network framing no longer drives the paint cadence — the rAF clock does.
 *
 * WHY requestAnimationFrame (and not setInterval)
 * -----------------------------------------------
 * rAF is synced to the display refresh, so each emitted slice corresponds to an
 * actual repaint — no wasted renders between frames, no tearing, and the
 * browser automatically throttles it when the tab is backgrounded (saving CPU).
 *
 * FLUSH-ON-DONE (no trailing lag)
 * -------------------------------
 * When the stream ends (done / cancel / error) we must NOT keep trickling the
 * remaining queued characters out a few-per-frame — that would add a visible
 * lag AFTER the answer is actually complete. `flush()` paints everything left
 * in the queue in one shot and stops the loop, so the settle is instant.
 *
 * CLEANUP (no leaks)
 * ------------------
 * A scheduled rAF callback holds a reference to this buffer. If the component
 * unmounts (user navigates away) or a NEW turn starts while a previous reveal
 * is still draining, the old loop MUST be cancelled or it would call back into
 * stale state. `reset()` cancels the pending frame and discards the queue;
 * callers invoke it on unmount and at the start of every new turn.
 */

/** Options for {@link createTypewriterBuffer}. */
export interface TypewriterBufferOptions {
  /**
   * Called whenever the buffer reveals new characters — the consumer appends
   * `chars` to whatever it is rendering (e.g. the streaming bubble's text).
   * The buffer NEVER stores the full revealed string itself; it only owns the
   * not-yet-painted tail, so the consumer stays the single source of truth.
   */
  onReveal: (chars: string) => void;
  /**
   * Baseline minimum reveal speed (characters per animation frame). At ~60fps
   * a value of N reveals ~N*60 chars/sec when the backlog is small. Kept small
   * so short answers still look like typing rather than appearing instantly.
   */
  charsPerFrame?: number;
  /**
   * Catch-up factor: each frame we reveal AT LEAST `charsPerFrame`, but if a
   * large backlog has built up (a network burst), we also reveal this fraction
   * of the backlog so the reveal never falls hopelessly behind generation. A
   * 2000-char burst therefore drains over a couple dozen smooth frames instead
   * of either one jarring paint OR a multi-second slow crawl.
   */
  catchUpFraction?: number;
  /**
   * Schedule a callback for the next frame. Injectable so tests can drive the
   * loop deterministically; defaults to the browser `requestAnimationFrame`.
   */
  requestFrame?: (cb: () => void) => number;
  /** Cancel a scheduled frame. Defaults to the browser `cancelAnimationFrame`. */
  cancelFrame?: (handle: number) => void;
}

/** Public surface of a typewriter buffer instance. */
export interface TypewriterBuffer {
  /** Enqueue freshly-arrived text and ensure the drain loop is running. */
  push: (text: string) => void;
  /**
   * Paint EVERYTHING still queued immediately and stop the loop. Use on
   * done/cancel/error so the answer settles with no trailing trickle.
   */
  flush: () => void;
  /**
   * Stop the loop and DISCARD any queued text WITHOUT painting it. Use on
   * unmount and at the start of a new turn so a previous turn's leftover
   * characters can never bleed into the next.
   */
  reset: () => void;
  /** Characters still queued (not yet revealed). Exposed for tests/diagnostics. */
  readonly pending: number;
}

/**
 * Fallbacks for non-browser environments (SSR, tests without a DOM). The hook
 * only ever runs the loop in the browser, but defaulting defensively keeps the
 * factory pure and import-safe on the server.
 */
const defaultRequestFrame: (cb: () => void) => number =
  typeof requestAnimationFrame === "function"
    ? (cb) => requestAnimationFrame(cb)
    : // Degrade to a macrotask so logic still advances if rAF is unavailable.
      (cb) => setTimeout(cb, 16) as unknown as number;

const defaultCancelFrame: (handle: number) => void =
  typeof cancelAnimationFrame === "function"
    ? (handle) => cancelAnimationFrame(handle)
    : (handle) => clearTimeout(handle as unknown as ReturnType<typeof setTimeout>);

/**
 * Create a typewriter buffer. Each call returns an isolated instance with its
 * own queue and (at most one) in-flight animation frame.
 */
export function createTypewriterBuffer(
  options: TypewriterBufferOptions,
): TypewriterBuffer {
  const {
    onReveal,
    charsPerFrame = 3,
    catchUpFraction = 0.08,
    requestFrame = defaultRequestFrame,
    cancelFrame = defaultCancelFrame,
  } = options;

  // The not-yet-painted tail. The consumer owns the painted prefix.
  let queue = "";
  // Handle of the currently-scheduled frame, or null when the loop is idle.
  // We keep at most ONE frame in flight so push() can be called many times per
  // frame without spawning a storm of overlapping rAF callbacks.
  let frameHandle: number | null = null;

  /** One animation-frame tick: reveal a slice, reschedule if more remains. */
  const drain = (): void => {
    // This callback has now fired, so clear the handle BEFORE doing work — if
    // onReveal (a React setState) synchronously triggers another push(), that
    // push must be free to schedule the NEXT frame.
    frameHandle = null;
    if (queue.length === 0) return;

    // Reveal at least `charsPerFrame`, more when a backlog has piled up so the
    // typewriter catches up to a burst within a bounded number of frames.
    const sliceLength = Math.max(
      charsPerFrame,
      Math.ceil(queue.length * catchUpFraction),
    );
    const slice = queue.slice(0, sliceLength);
    queue = queue.slice(sliceLength);
    onReveal(slice);

    // Keep draining on subsequent frames until the queue is empty.
    if (queue.length > 0) {
      frameHandle = requestFrame(drain);
    }
  };

  /** Cancel any pending frame so no stale callback fires later. */
  const cancelPendingFrame = (): void => {
    if (frameHandle !== null) {
      cancelFrame(frameHandle);
      frameHandle = null;
    }
  };

  return {
    push(text: string): void {
      if (!text) return;
      queue += text;
      // Start the loop if it is idle. If a frame is already scheduled we do
      // nothing — the in-flight drain() will pick up the newly-appended text.
      if (frameHandle === null) {
        frameHandle = requestFrame(drain);
      }
    },

    flush(): void {
      cancelPendingFrame();
      // Paint whatever is left in one shot so the answer settles instantly.
      if (queue.length > 0) {
        const remaining = queue;
        queue = "";
        onReveal(remaining);
      }
    },

    reset(): void {
      cancelPendingFrame();
      // Discard without painting — used when the content is being thrown away
      // (unmount) or superseded by a fresh turn.
      queue = "";
    },

    get pending(): number {
      return queue.length;
    },
  };
}
