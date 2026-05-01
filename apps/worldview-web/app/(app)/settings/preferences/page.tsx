/**
 * app/(app)/settings/preferences/page.tsx — User preferences (PLAN-0059 I-4)
 *
 * Three preferences: display density, default currency, default timezone.
 * Today persisted in localStorage via PreferencesProvider; the S1 backend
 * endpoint that will own canonical persistence is a deferred follow-up.
 */

"use client";

import * as React from "react";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  usePreferences,
  type CurrencyCode,
  type Density,
} from "@/contexts/PreferencesContext";

const DENSITIES: ReadonlyArray<{ value: Density; label: string; hint: string }> = [
  { value: "compact", label: "Compact", hint: "22px rows · 11px text · institutional" },
  { value: "default", label: "Default", hint: "32px rows · standard density" },
  { value: "comfortable", label: "Comfortable", hint: "40px rows · readable for marketing pages" },
];

const CURRENCIES: ReadonlyArray<{ code: CurrencyCode; label: string }> = [
  { code: "USD", label: "USD — US Dollar ($)" },
  { code: "EUR", label: "EUR — Euro (€)" },
  { code: "GBP", label: "GBP — Pound Sterling (£)" },
  { code: "JPY", label: "JPY — Japanese Yen (¥)" },
  { code: "CHF", label: "CHF — Swiss Franc" },
  { code: "CAD", label: "CAD — Canadian Dollar" },
  { code: "AUD", label: "AUD — Australian Dollar" },
  { code: "CNY", label: "CNY — Chinese Yuan" },
  { code: "HKD", label: "HKD — Hong Kong Dollar" },
  { code: "KRW", label: "KRW — Korean Won" },
  { code: "BTC", label: "BTC — Bitcoin (₿)" },
  { code: "ETH", label: "ETH — Ether" },
];

// Curated short list of common IANA zones; user can also pick "auto".
const TIMEZONES = [
  { value: "auto", label: "Auto (use browser timezone)" },
  { value: "UTC", label: "UTC" },
  { value: "America/New_York", label: "New York (ET)" },
  { value: "America/Chicago", label: "Chicago (CT)" },
  { value: "America/Los_Angeles", label: "Los Angeles (PT)" },
  { value: "Europe/London", label: "London (GMT/BST)" },
  { value: "Europe/Paris", label: "Paris (CET/CEST)" },
  { value: "Europe/Zurich", label: "Zurich (CET/CEST)" },
  { value: "Asia/Tokyo", label: "Tokyo (JST)" },
  { value: "Asia/Hong_Kong", label: "Hong Kong (HKT)" },
  { value: "Asia/Singapore", label: "Singapore (SGT)" },
  { value: "Australia/Sydney", label: "Sydney (AEDT/AEST)" },
];

export default function SettingsPreferencesPage() {
  const {
    density,
    currency,
    timezone,
    resolvedTimezone,
    setDensity,
    setCurrency,
    setTimezone,
    reset,
  } = usePreferences();

  return (
    <div className="space-y-4">
      {/* Density */}
      <Card className="border-border/60 bg-card">
        <CardHeader className="pb-3">
          <CardTitle className="text-sm font-medium text-foreground">
            Display density
          </CardTitle>
          <CardDescription className="text-xs">
            Controls the row height and text size of data-dense surfaces
            (tables, panels, charts). Chrome elements (TopBar, sidebar) are
            unaffected.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div role="radiogroup" aria-label="Display density" className="space-y-1.5">
            {DENSITIES.map((d) => (
              <label
                key={d.value}
                className="flex cursor-pointer items-center gap-3 rounded-[2px] border border-border/40 bg-background px-3 py-2 transition-colors hover:bg-muted/30 has-[:checked]:border-primary has-[:checked]:bg-primary/5"
              >
                <input
                  type="radio"
                  name="density"
                  value={d.value}
                  checked={density === d.value}
                  onChange={() => setDensity(d.value)}
                  aria-describedby={`density-${d.value}-hint`}
                  className="h-3 w-3 cursor-pointer accent-primary"
                />
                <div className="flex-1">
                  <span className="text-sm font-medium text-foreground">{d.label}</span>
                  <span
                    id={`density-${d.value}-hint`}
                    className="ml-2 text-[11px] text-muted-foreground"
                  >
                    {d.hint}
                  </span>
                </div>
              </label>
            ))}
          </div>
        </CardContent>
      </Card>

      {/* Currency */}
      <Card className="border-border/60 bg-card">
        <CardHeader className="pb-3">
          <CardTitle className="text-sm font-medium text-foreground">
            Default currency
          </CardTitle>
          <CardDescription className="text-xs">
            Used for value displays where the underlying instrument has no
            native currency context. Original currency of priced instruments
            is preserved.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="flex items-center gap-3">
            <Label htmlFor="pref-currency" className="text-sm text-foreground">
              Currency
            </Label>
            <Select
              value={currency}
              onValueChange={(v) => setCurrency(v as CurrencyCode)}
            >
              <SelectTrigger id="pref-currency" className="h-7 w-72 text-[11px]">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {CURRENCIES.map((c) => (
                  <SelectItem key={c.code} value={c.code} className="text-[11px]">
                    {c.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </CardContent>
      </Card>

      {/* Timezone */}
      <Card className="border-border/60 bg-card">
        <CardHeader className="pb-3">
          <CardTitle className="text-sm font-medium text-foreground">
            Default timezone
          </CardTitle>
          <CardDescription className="text-xs">
            Used for timestamp displays across the app. Market schedules and
            chart x-axes always remain in the source exchange&apos;s local time.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-2">
          <div className="flex items-center gap-3">
            <Label htmlFor="pref-timezone" className="text-sm text-foreground">
              Timezone
            </Label>
            <Select value={timezone} onValueChange={setTimezone}>
              <SelectTrigger id="pref-timezone" className="h-7 w-72 text-[11px]">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {TIMEZONES.map((t) => (
                  <SelectItem key={t.value} value={t.value} className="text-[11px]">
                    {t.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <p className="text-[11px] text-muted-foreground">
            Resolved to: <span className="font-mono">{resolvedTimezone}</span>
          </p>
        </CardContent>
      </Card>

      {/* Reset */}
      <Card className="border-border/60 bg-card">
        <CardHeader className="pb-3">
          <CardTitle className="text-sm font-medium text-foreground">
            Reset preferences
          </CardTitle>
          <CardDescription className="text-xs">
            Restores density, currency, and timezone to their defaults. Does
            not affect other settings (notifications, appearance, security).
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Button density="compact" variant="outline" onClick={reset}>
            Reset to defaults
          </Button>
        </CardContent>
      </Card>

      {/* Backend follow-up note */}
      <p
        role="note"
        className="rounded-[2px] border border-border/40 bg-muted/20 px-3 py-2 text-[11px] text-muted-foreground"
      >
        Preferences are saved locally in this browser. Cross-device sync ships
        in a follow-up wave (S1 user-preferences endpoint) — the same UI will
        switch to API-backed persistence with no consumer changes.
      </p>
    </div>
  );
}
