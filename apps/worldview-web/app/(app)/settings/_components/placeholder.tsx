/**
 * app/(app)/settings/_components/placeholder.tsx — shared placeholder for
 * not-yet-implemented settings sections (PLAN-0059 I-3).
 */

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

interface Props {
  title: string;
  description: string;
  bullets: string[];
}

export function SettingsPlaceholder({ title, description, bullets }: Props) {
  return (
    <Card className="border-border/60 bg-card">
      <CardHeader className="pb-3">
        <CardTitle className="text-sm font-medium text-foreground">{title}</CardTitle>
        <CardDescription className="text-xs">{description}</CardDescription>
      </CardHeader>
      <CardContent>
        <div
          role="note"
          className="rounded-[2px] border border-warning/40 bg-warning/5 px-3 py-2"
        >
          <p className="text-xs font-medium text-warning/90">Coming soon</p>
          <p className="mt-0.5 text-xs text-warning/80">
            This section is part of PLAN-0059 Wave I but ships in a follow-up
            iteration. Planned scope:
          </p>
          <ul className="ml-4 mt-1 list-disc space-y-0.5 text-xs text-warning/70">
            {bullets.map((b) => (
              <li key={b}>{b}</li>
            ))}
          </ul>
        </div>
      </CardContent>
    </Card>
  );
}
