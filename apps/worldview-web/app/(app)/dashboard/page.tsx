/**
 * app/(app)/dashboard/page.tsx — Dashboard route placeholder
 *
 * WHY THIS EXISTS: The protected (app) layout requires at least one route to
 * be functional so the auth guard can be tested in the F-2 wave.
 * Full dashboard implementation is Wave F-5.
 *
 * WHO USES IT: Authenticated users who navigate to / or /dashboard after login.
 * DATA SOURCE: None yet — F-5 adds all 9 dashboard widgets.
 * DESIGN REFERENCE: PRD-0028 §6.3.2 Dashboard Page, canvas State A (SL9kb)
 */

export default function DashboardPage() {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center bg-background">
      <h1 className="text-lg font-semibold text-foreground">Dashboard</h1>
      <p className="mt-2 text-sm text-muted-foreground">
        Full dashboard implementation coming in Wave F-5.
      </p>
    </main>
  );
}
