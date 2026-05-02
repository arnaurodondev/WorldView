/**
 * lib/auth/session-channel.ts — Cross-tab session-event bus
 *
 * WHY THIS EXISTS (PLAN-0059 B-6): trader workflows commonly span 4–8 browser
 * tabs (one per portfolio / watchlist / instrument deep-link). When the user
 * signs out from one tab, every other tab must drop the in-memory access
 * token immediately — otherwise a tab the user forgot about is still
 * "authenticated" until its silent-refresh fails (up to 15 minutes later).
 * That is exactly the kind of unattended-session leak that institutional
 * security audits flag as a finding.
 *
 * SCOPE: this module deliberately owns its own `BroadcastChannel` separate
 * from `useIdleLock` (`worldview.idle-lock`). Idle-lock broadcasts *activity*
 * pings that should always reset peer timers; this channel broadcasts
 * *session events* (signout) that should clear peer state. Mixing the two
 * would tie peer-timer-reset to peer-signout, which is the wrong shape.
 *
 * WHO USES IT:
 *   - `AuthContext` — `broadcastSignout()` after a successful logout, and
 *     `subscribeSignout(handler)` on mount to react to peer signouts.
 *
 * BROWSER SUPPORT: BroadcastChannel is unavailable in some embedded browsers
 * and locked-down enterprise IE shims. All call sites short-circuit when
 * `BroadcastChannel` is undefined; the local-only signout path still works.
 */

// Channel name kept stable — changing it would silently break tabs running
// older code during a rolling deploy. Versioning is via the `version` field
// in the message payload instead.
const CHANNEL_NAME = "worldview.session";

interface SignoutMessage {
  type: "signout";
  /** Wall-clock timestamp the originating tab posted the message. */
  ts: number;
}

type SessionMessage = SignoutMessage;

/**
 * isBroadcastChannelSupported — feature-detect once, reuse.
 *
 * WHY a function (not a const): the module is imported during SSR where
 * `BroadcastChannel` is undefined; reading it at module-eval time would
 * crash. Reading inside a function defers the check to call time.
 */
function isBroadcastChannelSupported(): boolean {
  return typeof BroadcastChannel !== "undefined";
}

/**
 * broadcastSignout — tell every other tab the user signed out.
 *
 * Best-effort: silent-failure on unsupported browsers and on closed channels
 * (the browser may close BroadcastChannels during page unload).
 */
export function broadcastSignout(): void {
  if (!isBroadcastChannelSupported()) return;
  try {
    const ch = new BroadcastChannel(CHANNEL_NAME);
    const msg: SignoutMessage = { type: "signout", ts: Date.now() };
    ch.postMessage(msg);
    // Close immediately — we only needed it for this single post.
    // Keeping it open would leak across hot-reload cycles in dev.
    ch.close();
  } catch {
    // No-op: posting to a closed channel during page unload throws; the
    // peer-tab path is best-effort only and the local logout already ran.
  }
}

/**
 * subscribeSignout — fire `handler` when any other tab broadcasts signout.
 *
 * Returns a teardown function the caller MUST invoke on unmount, or the
 * channel will leak across React Strict-Mode mount/unmount cycles.
 *
 * The handler runs only for `type: "signout"` messages — future event types
 * (e.g. "session.refresh") will be filtered here as the union grows.
 */
export function subscribeSignout(handler: () => void): () => void {
  if (!isBroadcastChannelSupported()) {
    // Return a no-op teardown so callers can `useEffect(() => sub(), [])`
    // unconditionally without branching.
    return () => {};
  }

  let channel: BroadcastChannel | null = null;
  try {
    channel = new BroadcastChannel(CHANNEL_NAME);
  } catch {
    return () => {};
  }

  const onMessage = (event: MessageEvent<SessionMessage>) => {
    // Defensive type guard: BroadcastChannel will faithfully deliver any
    // message a peer posts, including a hostile `{type: "..."}`. Narrow
    // before invoking the handler.
    if (
      event.data &&
      typeof event.data === "object" &&
      event.data.type === "signout"
    ) {
      handler();
    }
  };

  channel.addEventListener("message", onMessage);

  return () => {
    channel?.removeEventListener("message", onMessage);
    try {
      channel?.close();
    } catch {
      // Channel may be already closed by browser during teardown.
    }
  };
}
