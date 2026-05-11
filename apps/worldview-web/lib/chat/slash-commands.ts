/**
 * lib/chat/slash-commands.ts — Inline slash-command parser for the chat input
 *
 * WHY THIS EXISTS (PLAN-0051 T-E-5-01):
 * The Intelligence chat is a research tool. Most LLM round-trips for things
 * like "what is the price of AAPL", "show my portfolio", or "what's in my
 * watchlist" are wasted: the answer comes from existing structured data the
 * gateway already exposes. Forcing every request through a 2-8s LLM stream
 * is slow AND burns provider tokens. Slash commands let the user pull these
 * structured answers in <100ms by short-circuiting the LLM entirely and
 * rendering an inline data card instead.
 *
 * DESIGN PRINCIPLES:
 *  1. Pure parser — no React, no fetching here. Just turns "/quote AAPL"
 *     into { kind: "quote", params: { ticker: "AAPL" } }. The card component
 *     is responsible for fetching with the parsed params. Pure functions are
 *     trivial to unit-test (T-E-5-08).
 *  2. Fail open — when the leading "/" is followed by an unknown verb we
 *     return null and the chat page falls through to the normal LLM stream.
 *     A typo like "/quotee AAPL" must not silently swallow the user's input.
 *  3. Forgiving args — we trim and lowercase the verb but preserve the case
 *     of arguments (tickers are uppercase, watchlist names may be mixed).
 *
 * WHO USES IT:
 *  - app/(app)/chat/page.tsx (handleSend → parseInput before calling LLM)
 *  - components/chat/SlashCommandAutocomplete.tsx (filter command list)
 *  - components/chat/SlashCommandCard.tsx (consumes ParsedCommand)
 *
 * KIND ENUM:
 *  Each card supports a single fetch shape, so the kind is the discriminator
 *  the card switch reads. We keep the kind string identical to the verb name
 *  to avoid an extra mapping layer.
 */

// ── Types ─────────────────────────────────────────────────────────────────────

/**
 * SlashCommand — registry entry describing one invokable verb.
 *
 * WHY a flat array (not a Map): the autocomplete needs to iterate the list
 * to render suggestions. Arrays preserve a deterministic order which is the
 * order shown in the popover.
 */
export interface SlashCommand {
  /** Verb without the leading slash. Lowercase. */
  name: string;
  /** Short human description shown in the autocomplete popover. */
  description: string;
  /** Free-text argument hint, e.g. "<TICKER>" or "[SECTOR=...]". */
  argSpec: string;
  /**
   * Parser for the argument string (everything AFTER the verb, trimmed).
   * Returns the canonical params object or `null` when arguments are
   * malformed (e.g. "/quote" with no ticker). Returning null causes the
   * chat page to fall through to the LLM, which is a reasonable behaviour
   * because the user typed something the inline parser can't satisfy.
   */
  parse: (args: string) => ParsedCommand | null;
}

/**
 * ParsedCommand — the structured shape consumed by SlashCommandCard.
 *
 * `kind` matches the slash command name. `params` is a string-keyed bag
 * because every command's args are user-typed strings; type narrowing is
 * the card's job (it knows what to expect for its own kind).
 */
export interface ParsedCommand {
  kind: string;
  params: Record<string, string>;
}

// ── Individual parsers ────────────────────────────────────────────────────────

/**
 * parseQuote — "/quote AAPL" → { kind: "quote", params: { ticker: "AAPL" } }
 *
 * WHY uppercase: the gateway's getQuote endpoint takes an instrument_id but
 * the user always types the ticker. The card resolves ticker → instrument_id
 * via the search endpoint or by passing the ticker straight to /quotes (S9
 * accepts tickers as well as UUIDs for convenience).
 */
function parseQuote(args: string): ParsedCommand | null {
  const ticker = args.trim().toUpperCase();
  if (!ticker) return null;
  // Reject anything with whitespace — multiple tickers is a future feature.
  if (/\s/.test(ticker)) return null;
  // QA-iter1 NIT-2: tickers MUST start with a letter. Without this guard
  // ``/quote 0`` parses successfully and the gateway 404s on the literal
  // string "0". Falling through to the LLM (return null) gives the user
  // a more helpful response.
  if (!/^[A-Z]/.test(ticker)) return null;
  return { kind: "quote", params: { ticker } };
}

/**
 * parsePortfolio — "/portfolio" → no args; the card uses the user's default
 * portfolio (first in /v1/portfolios). Optional argument is ignored for now.
 */
function parsePortfolio(args: string): ParsedCommand | null {
  // WHY accept any args (silently ignored): keeps the parser permissive so
  // a user typing "/portfolio main" doesn't fall through to the LLM. The
  // card just renders the default portfolio anyway in this MVP.
  return { kind: "portfolio", params: { hint: args.trim() } };
}

/**
 * parseNews — "/news" or "/news SECTOR=tech" → optional sector filter.
 * Format: KEY=VALUE pairs (currently only SECTOR is honoured by the card).
 */
function parseNews(args: string): ParsedCommand | null {
  const trimmed = args.trim();
  const params: Record<string, string> = {};
  if (trimmed) {
    // Split on whitespace; each token may be KEY=VALUE.
    for (const tok of trimmed.split(/\s+/)) {
      const eq = tok.indexOf("=");
      if (eq > 0) {
        const key = tok.slice(0, eq).toLowerCase();
        const val = tok.slice(eq + 1);
        if (key && val) params[key] = val;
      }
    }
  }
  return { kind: "news", params };
}

/**
 * parseWatchlist — "/watchlist Tech Movers" → name preserves original case.
 * Returns null if the user typed just "/watchlist" with no name; we can't
 * disambiguate without a name argument (users may have many lists).
 */
function parseWatchlist(args: string): ParsedCommand | null {
  const name = args.trim();
  if (!name) return null;
  return { kind: "watchlist", params: { name } };
}

/**
 * parseAlerts — "/alerts" → no args; renders top 5 active alerts.
 */
function parseAlerts(_args: string): ParsedCommand | null {
  return { kind: "alerts", params: {} };
}

/**
 * parseScreener — "/screener" → renders a quick-link card to the screener page.
 */
function parseScreener(_args: string): ParsedCommand | null {
  return { kind: "screener", params: {} };
}

// ── Registry ─────────────────────────────────────────────────────────────────

/**
 * SLASH_COMMANDS — the canonical verb list.
 *
 * WHY ordered: the autocomplete renders this list (filtered by prefix), so
 * the order here is the order shown to the user. Keep them grouped by what
 * a trader would reach for first (quote → portfolio → news → watchlist →
 * alerts → screener).
 */
export const SLASH_COMMANDS: SlashCommand[] = [
  {
    name: "quote",
    description: "Show real-time quote",
    argSpec: "<TICKER>",
    parse: parseQuote,
  },
  {
    name: "portfolio",
    description: "Show portfolio summary",
    argSpec: "",
    parse: parsePortfolio,
  },
  {
    name: "news",
    description: "Show recent news",
    argSpec: "[SECTOR=...]",
    parse: parseNews,
  },
  {
    name: "watchlist",
    description: "Show watchlist members",
    argSpec: "<NAME>",
    parse: parseWatchlist,
  },
  {
    name: "alerts",
    description: "Show recent active alerts",
    argSpec: "",
    parse: parseAlerts,
  },
  {
    name: "screener",
    description: "Open screener",
    argSpec: "",
    parse: parseScreener,
  },
];

// ── Public API ────────────────────────────────────────────────────────────────

/**
 * parseInput — top-level dispatcher used by the chat page handleSend.
 *
 * Returns:
 *  - ParsedCommand → render an inline SlashCommandCard, skip the LLM.
 *  - null          → input is not a slash command (or the verb is unknown
 *                    or its args malformed). Caller should send to LLM.
 *
 * Why we do not throw on unknown verbs: the user's intent is unclear when
 * they type "/foo" — silently routing to the LLM (which will say "I don't
 * understand 'foo'") is friendlier than a UI error.
 */
export function parseInput(input: string): ParsedCommand | null {
  const trimmed = input.trim();
  // Quick reject — slash commands must start with "/" and have at least one
  // character following it.
  if (!trimmed.startsWith("/") || trimmed.length < 2) return null;

  // Split on first whitespace to separate verb from arguments.
  const sliceAfterSlash = trimmed.slice(1);
  const firstSpace = sliceAfterSlash.search(/\s/);
  const verbRaw = firstSpace === -1 ? sliceAfterSlash : sliceAfterSlash.slice(0, firstSpace);
  const argString = firstSpace === -1 ? "" : sliceAfterSlash.slice(firstSpace + 1);

  const verb = verbRaw.toLowerCase();
  const cmd = SLASH_COMMANDS.find((c) => c.name === verb);
  if (!cmd) return null;

  return cmd.parse(argString);
}

/**
 * filterCommands — used by the autocomplete popover to narrow the list as
 * the user types after "/". Matches by prefix on the verb.
 */
export function filterCommands(prefix: string): SlashCommand[] {
  const p = prefix.trim().toLowerCase().replace(/^\//, "");
  if (!p) return SLASH_COMMANDS;
  return SLASH_COMMANDS.filter((c) => c.name.startsWith(p));
}
