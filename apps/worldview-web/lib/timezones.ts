/**
 * lib/timezones.ts — Shared timezone constants and option builder
 *
 * WHY THIS EXISTS: Two distinct consumers need the same curated timezone list:
 *   1. settings/preferences/page.tsx — the full preferences form
 *   2. components/ui/time-picker.tsx — the optional inline TZ selector
 * Keeping the list here (rather than in each consumer) ensures they never
 * diverge silently when a new market centre is added.
 *
 * WHO USES IT: Any component that displays or edits timezone selection.
 *
 * DESIGN: The curated fallback covers all major financial market timezones
 * (NYSE/NASDAQ, CME, LSE, EUREX, SGX, TSE, ASX). The dynamic builder
 * uses Intl.supportedValuesOf on modern browsers for a complete list.
 */

export interface TimezoneOption {
  value: string;
  label: string;
}

/**
 * CURATED_FALLBACK — hand-picked finance-relevant timezones with human labels.
 *
 * WHY hand-picked: Intl.supportedValuesOf("timeZone") returns hundreds of
 * IANA zones with machine names like "America/Indiana/Indianapolis". For a
 * compact dropdown in a dialog, institutional users want the 15 zones where
 * they actually operate, labeled by market (e.g. "New York (ET)").
 *
 * Exported so TimePicker and other compact selectors can use just this list
 * without the full runtime-zone expansion (which adds ~200 items).
 */
export const CURATED_FALLBACK: ReadonlyArray<TimezoneOption> = [
  { value: "auto", label: "Auto (use browser timezone)" },
  { value: "UTC", label: "UTC" },
  { value: "America/New_York", label: "New York (ET)" },
  { value: "America/Chicago", label: "Chicago (CT)" },
  { value: "America/Los_Angeles", label: "Los Angeles (PT)" },
  { value: "America/Toronto", label: "Toronto (ET)" },
  { value: "America/Sao_Paulo", label: "São Paulo (BRT)" },
  { value: "Europe/London", label: "London (GMT/BST)" },
  { value: "Europe/Paris", label: "Paris (CET/CEST)" },
  { value: "Europe/Zurich", label: "Zurich (CET/CEST)" },
  { value: "Europe/Berlin", label: "Berlin / Frankfurt (CET/CEST)" },
  { value: "Asia/Dubai", label: "Dubai (GST)" },
  { value: "Asia/Kolkata", label: "Mumbai / Kolkata (IST)" },
  { value: "Asia/Singapore", label: "Singapore (SGT)" },
  { value: "Asia/Hong_Kong", label: "Hong Kong (HKT)" },
  { value: "Asia/Tokyo", label: "Tokyo (JST)" },
  { value: "Australia/Sydney", label: "Sydney (AEDT/AEST)" },
];

/**
 * buildTimezoneOptions — returns the full option list for a timezone selector.
 *
 * WHY dynamic expansion: modern browsers expose Intl.supportedValuesOf("timeZone")
 * (Chrome 99+, Firefox 106+, Safari 15.4+). On those runtimes we offer the
 * complete zone list so users in less common markets can find their zone. On
 * older runtimes or SSR (where Intl extensions aren't available) we fall back
 * to the curated list.
 *
 * WHY "auto" + "UTC" always pinned first: these are the two most common picks
 * and should never be buried alphabetically inside a 200-item list.
 */
export function buildTimezoneOptions(): ReadonlyArray<TimezoneOption> {
  const pinned: TimezoneOption[] = [
    { value: "auto", label: "Auto (use browser timezone)" },
    { value: "UTC", label: "UTC" },
  ];

  const intlAny = Intl as unknown as {
    supportedValuesOf?: (key: string) => string[];
  };
  if (typeof intlAny.supportedValuesOf !== "function") {
    return CURATED_FALLBACK;
  }

  let zones: string[];
  try {
    zones = intlAny.supportedValuesOf("timeZone");
  } catch {
    return CURATED_FALLBACK;
  }
  if (!Array.isArray(zones) || zones.length === 0) {
    return CURATED_FALLBACK;
  }

  // Build a label map from the curated list so known zones get their
  // human-friendly name; everything else falls back to the IANA string.
  const curatedLabels = new Map(CURATED_FALLBACK.map((t) => [t.value, t.label]));

  const rest = zones
    .filter((z) => z !== "UTC")
    .sort((a, b) => a.localeCompare(b))
    .map((z) => ({ value: z, label: curatedLabels.get(z) ?? z }));

  return [...pinned, ...rest];
}
