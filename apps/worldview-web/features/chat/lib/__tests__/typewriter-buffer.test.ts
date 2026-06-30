/**
 * features/chat/lib/__tests__/typewriter-buffer.test.ts — F2 (2026-06-30).
 *
 * WHAT THESE GUARD:
 *   1. The buffer reveals text GRADUALLY over multiple frames (it must NOT
 *      paint a whole burst in one frame — that is the jumpiness we fixed).
 *   2. `flush()` paints all remaining text immediately (instant settle on done,
 *      with no trailing trickle).
 *   3. `reset()` discards queued text WITHOUT painting it (new turn / unmount).
 *   4. The catch-up factor drains a large burst faster than the per-frame
 *      minimum so the reveal never falls hopelessly behind a fast stream.
 *   5. At most ONE frame is scheduled regardless of how many push() calls land
 *      between frames (no rAF storm / leak).
 *
 * We inject a FAKE requestAnimationFrame so the loop is fully deterministic:
 * pushed frame callbacks queue up and we "advance" them one at a time.
 */

import { describe, it, expect, beforeEach } from "vitest";

import { createTypewriterBuffer } from "../typewriter-buffer";

/**
 * A controllable rAF stand-in. `requestFrame` records the callback; `step()`
 * runs the next pending callback (simulating one browser paint). This lets a
 * test reveal exactly N frames and inspect the output between each.
 */
function makeFakeRaf() {
  let nextHandle = 1;
  const callbacks = new Map<number, () => void>();
  return {
    requestFrame(cb: () => void): number {
      const handle = nextHandle++;
      callbacks.set(handle, cb);
      return handle;
    },
    cancelFrame(handle: number): void {
      callbacks.delete(handle);
    },
    /** Run the oldest pending frame callback. Returns false if none pending. */
    step(): boolean {
      const entry = callbacks.entries().next();
      if (entry.done) return false;
      const [handle, cb] = entry.value;
      callbacks.delete(handle);
      cb();
      return true;
    },
    /** Drain ALL frames until the loop stops scheduling new ones. */
    runToIdle(maxSteps = 1000): number {
      let steps = 0;
      while (this.step()) {
        steps += 1;
        if (steps > maxSteps) throw new Error("rAF loop did not terminate");
      }
      return steps;
    },
    get pendingFrames(): number {
      return callbacks.size;
    },
  };
}

describe("createTypewriterBuffer", () => {
  let raf: ReturnType<typeof makeFakeRaf>;
  let revealed: string;

  beforeEach(() => {
    raf = makeFakeRaf();
    revealed = "";
  });

  function makeBuffer(opts?: { charsPerFrame?: number; catchUpFraction?: number }) {
    return createTypewriterBuffer({
      onReveal: (chars) => {
        revealed += chars;
      },
      charsPerFrame: opts?.charsPerFrame ?? 3,
      catchUpFraction: opts?.catchUpFraction ?? 0,
      requestFrame: raf.requestFrame,
      cancelFrame: raf.cancelFrame,
    });
  }

  it("reveals text gradually over multiple frames, not all at once", () => {
    const buf = makeBuffer({ charsPerFrame: 3, catchUpFraction: 0 });
    buf.push("abcdefghij"); // 10 chars, 3 per frame -> needs 4 frames

    // Nothing is painted until the first frame fires.
    expect(revealed).toBe("");

    raf.step();
    expect(revealed).toBe("abc"); // first 3
    expect(buf.pending).toBe(7);

    raf.step();
    expect(revealed).toBe("abcdef"); // next 3
    expect(buf.pending).toBe(4);

    raf.step();
    expect(revealed).toBe("abcdefghi"); // next 3

    raf.step();
    expect(revealed).toBe("abcdefghij"); // final char
    expect(buf.pending).toBe(0);

    // Loop stops scheduling once drained.
    expect(raf.pendingFrames).toBe(0);
  });

  it("flush() paints everything remaining immediately and stops the loop", () => {
    const buf = makeBuffer({ charsPerFrame: 2, catchUpFraction: 0 });
    buf.push("hello world"); // 11 chars

    raf.step(); // reveal first 2 -> "he"
    expect(revealed).toBe("he");
    expect(buf.pending).toBe(9);

    buf.flush(); // simulate `done` arriving mid-reveal
    expect(revealed).toBe("hello world"); // all remaining painted at once
    expect(buf.pending).toBe(0);
    // No pending frame left after flush — the loop is fully stopped.
    expect(raf.pendingFrames).toBe(0);
  });

  it("reset() discards queued text WITHOUT painting it", () => {
    const buf = makeBuffer({ charsPerFrame: 2, catchUpFraction: 0 });
    buf.push("abcdef");

    raf.step(); // "ab"
    expect(revealed).toBe("ab");

    buf.reset(); // new turn / unmount — drop the rest
    expect(buf.pending).toBe(0);
    expect(raf.pendingFrames).toBe(0);

    // Stepping further must NOT paint the discarded tail.
    raf.runToIdle();
    expect(revealed).toBe("ab");
  });

  it("catch-up factor drains a large burst faster than the per-frame minimum", () => {
    // 1000-char burst (the J1 one-shot arrival). With only charsPerFrame=3 this
    // would take ~334 frames; the catch-up factor must finish far sooner.
    const slow = makeFakeRaf();
    let slowOut = "";
    const slowBuf = createTypewriterBuffer({
      onReveal: (c) => {
        slowOut += c;
      },
      charsPerFrame: 3,
      catchUpFraction: 0, // no catch-up
      requestFrame: slow.requestFrame,
      cancelFrame: slow.cancelFrame,
    });
    slowBuf.push("x".repeat(1000));
    const slowFrames = slow.runToIdle(5000);

    const fast = makeFakeRaf();
    let fastOut = "";
    const fastBuf = createTypewriterBuffer({
      onReveal: (c) => {
        fastOut += c;
      },
      charsPerFrame: 3,
      catchUpFraction: 0.08, // reveal ~8% of backlog each frame
      requestFrame: fast.requestFrame,
      cancelFrame: fast.cancelFrame,
    });
    fastBuf.push("x".repeat(1000));
    const fastFrames = fast.runToIdle(5000);

    // Same total text revealed, but the catch-up variant uses far fewer frames.
    expect(slowOut).toBe("x".repeat(1000));
    expect(fastOut).toBe("x".repeat(1000));
    expect(fastFrames).toBeLessThan(slowFrames);
    expect(fastFrames).toBeLessThan(100); // bounded, not ~334
  });

  it("schedules at most one frame regardless of push count (no rAF storm)", () => {
    const buf = makeBuffer({ charsPerFrame: 1, catchUpFraction: 0 });
    buf.push("a");
    buf.push("b");
    buf.push("c");
    // Three pushes before any frame fires -> still exactly one pending frame.
    expect(raf.pendingFrames).toBe(1);
    expect(buf.pending).toBe(3);

    raf.runToIdle();
    expect(revealed).toBe("abc");
  });

  it("ignores empty pushes (no frame scheduled for empty text)", () => {
    const buf = makeBuffer();
    buf.push("");
    expect(raf.pendingFrames).toBe(0);
    expect(buf.pending).toBe(0);
  });
});
