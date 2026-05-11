/**
 * lib/workspace-share.ts — Encode/decode a workspace config for URL sharing
 *
 * WHY THIS EXISTS: Traders frequently want to share their workspace setup with
 * a colleague — "look at how I'm watching $AAPL", "use this layout for daily
 * scans". The classic web pattern for sharing arbitrary state is a URL with a
 * `?config=<token>` query parameter. This module is the encoder/decoder for
 * that token.
 *
 * WHY base64url (not regular base64): URLs can't safely contain `+`, `/`, or
 * `=` characters. base64url replaces `+`→`-`, `/`→`_`, and strips `=` padding.
 * This is the same encoding used by JWTs, OAuth, and most modern APIs that
 * embed binary data in URLs.
 *
 * WHY 4096-char cap: most browsers reliably handle URLs up to ~8KB total, but
 * shared platforms (Slack, Discord, email clients) often truncate links above
 * 4KB. Capping at 4096 chars for the encoded token leaves headroom for the
 * full URL (`https://app.worldview.com/workspace?config=` ≈ 50 chars + token).
 * Any user with a workspace too large to share via URL will need an export-to-
 * JSON path (deferred to a future wave).
 *
 * SECURITY NOTE: the token is NOT signed or encrypted — it's just transparent
 * encoding. Anyone who decodes a token can see the workspace shape. That's
 * fine: the workspace contains no secrets (it's just panel types + sizes), no
 * symbols (those are stored in SymbolLinkingContext, not WorkspaceConfig), and
 * no auth state. If the data model gains sensitive fields, this encoder must
 * be revisited — see the README in this file for instructions.
 *
 * WHO USES IT:
 *   - components/workspace/ShareWorkspaceDialog.tsx — encode + display URL
 *   - app/(app)/workspace/page.tsx — decode `?config=` on mount + import as tab
 * DESIGN REFERENCE: PLAN-0051 §T-C-3-07 (share-via-URL)
 */

import type { WorkspaceConfig } from "@/contexts/WorkspaceContext";

// ── Constants ────────────────────────────────────────────────────────────────

/**
 * MAX_TOKEN_CHARS — soft cap on encoded token length.
 *
 * WHY 4096: reliable URL length for Slack/Discord/email; reserves ~3.5KB for
 * the encoded payload (the rest covers `?config=` query keys + protocol +
 * host). Browsers can technically handle longer, but shared platforms
 * frequently truncate above this. Keeping the limit explicit lets us surface
 * a user-friendly error rather than producing a broken link.
 */
export const MAX_TOKEN_CHARS = 4096;

// ── Internal helpers ────────────────────────────────────────────────────────

/**
 * toBase64Url — convert a regular base64 string to URL-safe base64.
 *
 * WHY a tiny helper (not inline): used by both encode and (potentially) future
 * encoders. Keeps the URL-safe transformation in one place — if base64url
 * conventions ever change (they won't), one edit fixes everything.
 */
function toBase64Url(b64: string): string {
  // WHY string.replace with /[+/]/g: simple two-char swap. Chained replace
  // calls would also work but the single regex is one pass over the string.
  // The `=` strip is also safe because base64url decoders re-pad before
  // calling atob.
  return b64.replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

/**
 * fromBase64Url — restore standard base64 from URL-safe base64.
 *
 * WHY pad with `=`: atob() requires the input to have its `=` padding present.
 * URL-safe base64 strips it; we restore it before decoding.
 */
function fromBase64Url(b64url: string): string {
  // WHY (4 - len % 4) % 4: base64 length is always a multiple of 4. If the
  // length mod 4 is 0, no padding needed; otherwise add `=` chars to make it
  // a multiple of 4. The outer `% 4` handles the 0-case (4 - 0 = 4, but we
  // want 0 padding chars).
  const padding = (4 - (b64url.length % 4)) % 4;
  return b64url.replace(/-/g, "+").replace(/_/g, "/") + "=".repeat(padding);
}

// ── Public API ──────────────────────────────────────────────────────────────

/**
 * encodeWorkspace — serialize a WorkspaceConfig into a URL-safe base64 token.
 *
 * WHY JSON.stringify (not a custom binary format): WorkspaceConfig is small
 * (typically <2KB JSON) and the structure is shallow. Custom binary encoding
 * would require a versioned schema and decode reverse-engineering — JSON gives
 * us forward-compatibility for free (new fields added to WorkspaceConfig are
 * just preserved across encode/decode without code changes).
 *
 * WHY TextEncoder + btoa (not Buffer.from): browsers don't have Node's Buffer.
 * The TextEncoder→Uint8Array→base64 path is the canonical browser-safe way.
 *
 * WHY String.fromCharCode.apply over a chunk: btoa expects a binary string
 * (each char's code point is a byte). For typical workspace JSON (<10KB), the
 * single .apply() call is fine; for larger payloads we'd need to chunk.
 *
 * @param config The workspace to encode
 * @returns A URL-safe base64 token (no padding, no `+/` chars)
 */
export function encodeWorkspace(config: WorkspaceConfig): string {
  // WHY JSON.stringify with no replacer/space: minimum byte count. A pretty-
  // printed JSON would inflate the token by 10-30%.
  const json = JSON.stringify(config);
  const bytes = new TextEncoder().encode(json);
  // WHY String.fromCharCode.apply: btoa expects a binary string where each
  // char's code unit IS the byte value. For < 65k bytes (Function.apply
  // argument count limit on older browsers) this works. WorkspaceConfig is
  // way under that limit (typically <2KB).
  const binary = String.fromCharCode.apply(null, Array.from(bytes));
  // WHY btoa wrapped in toBase64Url: btoa produces standard base64 (with
  // `+/=`), then we apply the URL-safe transform.
  return toBase64Url(btoa(binary));
}

/**
 * decodeWorkspace — restore a WorkspaceConfig from a URL token.
 *
 * WHY returns null (not throws): the caller (workspace/page.tsx on mount)
 * receives a `?config=` value from search params. That value could be:
 *   - missing (no `?config=` in URL) → handled before calling this fn
 *   - corrupted (user manually mangled the URL) → returns null
 *   - tampered (different version of the encoder) → returns null
 *   - valid but malformed (extra fields, missing required) → returns the
 *     parsed object as-is; runtime callers (WorkspaceContext) validate shape
 *
 * The null path lets the caller show a "couldn't import workspace" toast
 * without unwrapping a try/catch around every decode call.
 *
 * @param token URL-safe base64 string from `?config=…`
 * @returns Parsed WorkspaceConfig, or null on any decode failure
 */
export function decodeWorkspace(token: string): WorkspaceConfig | null {
  try {
    // WHY check empty/very-short tokens first: atob on empty input returns
    // empty string which JSON.parse rejects — clearer to bail early.
    if (!token || token.length < 4) return null;

    const b64 = fromBase64Url(token);
    const binary = atob(b64);
    // WHY Uint8Array reconstruction: TextDecoder needs bytes, not chars.
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i++) {
      bytes[i] = binary.charCodeAt(i);
    }
    const json = new TextDecoder().decode(bytes);
    const parsed = JSON.parse(json) as unknown;

    // WHY shallow shape validation: we don't want to commit to a heavyweight
    // runtime validator (zod/io-ts) for a tiny shared object. The minimum
    // sane check: it's an object with `name` and `rows` arrays. Anything
    // beyond that is enforced at runtime when the workspace is rendered.
    if (
      typeof parsed !== "object" ||
      parsed === null ||
      !("name" in parsed) ||
      !("rows" in parsed) ||
      !Array.isArray((parsed as { rows: unknown }).rows)
    ) {
      return null;
    }

    return parsed as WorkspaceConfig;
  } catch {
    // WHY swallow all errors: any thrown error in the chain (atob,
    // JSON.parse, TextDecoder) means the input wasn't a valid encoded
    // workspace. Returning null is the right signal to the caller.
    return null;
  }
}
