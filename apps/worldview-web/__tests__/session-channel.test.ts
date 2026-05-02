/**
 * __tests__/session-channel.test.ts — Unit tests for the cross-tab session
 * BroadcastChannel helper.
 *
 * Coverage:
 *   - broadcastSignout posts a `{type:"signout"}` message peers can observe
 *   - subscribeSignout filters: only signout-typed payloads invoke the handler
 *   - subscribe is a no-op when BroadcastChannel is unsupported (returns
 *     a no-op teardown so the call site need not branch)
 *   - broadcastSignout is a no-op when BroadcastChannel is unsupported
 *
 * NOTE: tests use REAL timers — BroadcastChannel posts asynchronously via
 * the event loop, and fake timers interfere with that scheduling.
 */

import { describe, expect, it, vi } from "vitest";
import {
  broadcastSignout,
  subscribeSignout,
} from "@/lib/auth/session-channel";

const HAS_BROADCAST_CHANNEL = typeof BroadcastChannel !== "undefined";

// Helper: wait for a peer-message round-trip. BroadcastChannel delivers via
// the macrotask queue, so a setTimeout(0) is enough to flush.
const flushChannel = () => new Promise<void>((r) => setTimeout(r, 10));

describe("session-channel", () => {
  it.skipIf(!HAS_BROADCAST_CHANNEL)(
    "broadcastSignout delivers a signout message to peer subscribers",
    async () => {
      const handler = vi.fn();
      const teardown = subscribeSignout(handler);

      broadcastSignout();
      await flushChannel();

      expect(handler).toHaveBeenCalledTimes(1);
      teardown();
    },
  );

  it.skipIf(!HAS_BROADCAST_CHANNEL)(
    "subscribeSignout ignores messages whose type is not 'signout'",
    async () => {
      const handler = vi.fn();
      const teardown = subscribeSignout(handler);

      // Post foreign-shaped payloads through a separate handle on the same
      // logical channel; the subscriber's handle must filter them out.
      const ch = new BroadcastChannel("worldview.session");
      ch.postMessage({ type: "activity" });
      ch.postMessage({ type: "totally-other" });
      ch.postMessage("not-an-object");
      await flushChannel();

      expect(handler).not.toHaveBeenCalled();

      ch.close();
      teardown();
    },
  );

  it("subscribeSignout returns a no-op teardown when BroadcastChannel is undefined", () => {
    const original = globalThis.BroadcastChannel;
    // @ts-expect-error simulate unsupported environment
    globalThis.BroadcastChannel = undefined;

    const teardown = subscribeSignout(() => {
      throw new Error("should never fire — channel unsupported");
    });
    expect(() => teardown()).not.toThrow();

    globalThis.BroadcastChannel = original;
  });

  it("broadcastSignout is a no-op when BroadcastChannel is undefined", () => {
    const original = globalThis.BroadcastChannel;
    // @ts-expect-error simulate unsupported environment
    globalThis.BroadcastChannel = undefined;

    expect(() => broadcastSignout()).not.toThrow();

    globalThis.BroadcastChannel = original;
  });
});
