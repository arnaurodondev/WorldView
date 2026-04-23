/**
 * app/layout.tsx — Root layout for the entire worldview-web application
 *
 * WHY THIS EXISTS: Next.js App Router requires a root layout that wraps ALL pages.
 * This layout:
 * 1. Loads IBM Plex fonts (Sans + Mono) from Google Fonts via next/font
 * 2. Sets class="dark" permanently on <html> (Bloomberg Dark theme, ADR-F-04)
 * 3. Provides the TanStack Query client for all child components
 * 4. Sets page metadata (title, description, Open Graph)
 *
 * WHY NOT a client component: Root layout should be a Server Component to
 * avoid hydration issues and enable proper metadata generation.
 * Client-side providers (QueryClient, AuthContext) are added via Providers.tsx.
 *
 * WHO USES IT: Every page in the application.
 * DESIGN REFERENCE: docs/ui/DESIGN_SYSTEM.md §3 Typography
 */

import type { Metadata } from "next";
import { IBM_Plex_Sans, IBM_Plex_Mono } from "next/font/google";
import "./globals.css";
import { Providers } from "./providers";

/**
 * IBM Plex Sans — for all UI labels, headings, and prose text
 * WHY IBM Plex Sans: Professional, legible at small sizes, excellent for
 * information-dense displays. Same font family used by IBM's own data tools.
 * variable="--font-sans" maps to tailwind.config.ts fontFamily.sans
 */
const ibmPlexSans = IBM_Plex_Sans({
  subsets: ["latin"],
  weight: ["300", "400", "500", "600", "700"],
  variable: "--font-sans",
  display: "swap",
});

/**
 * IBM Plex Mono — for ALL numeric values: prices, percentages, quantities, dates
 * WHY monospace for numbers: Ensures tabular alignment in tables without
 * needing fixed-width column CSS. Bloomberg Terminal and TradingView both use
 * monospace numbers — our target users expect this.
 * ADR-F-15: This is the single highest-impact visual rule in the design system.
 */
const ibmPlexMono = IBM_Plex_Mono({
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  variable: "--font-mono",
  display: "swap",
});

export const metadata: Metadata = {
  title: {
    template: "%s | Worldview",
    default: "Worldview — Professional Market Intelligence",
  },
  description:
    "Bloomberg-grade market intelligence at $29/month. AI-native research, entity graphs, news intelligence, prediction markets, and real-time alerts.",
  keywords: [
    "market intelligence",
    "stock research",
    "financial data",
    "entity graph",
    "AI finance",
  ],
  // Open Graph for sharing (thesis demo screenshots)
  openGraph: {
    type: "website",
    title: "Worldview — Professional Market Intelligence",
    description: "Bloomberg-grade research without the Bloomberg bill.",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    // class="dark": permanent dark mode — never changes (ADR-F-04)
    // font variables: injected as CSS custom props so Tailwind font-sans/mono work
    <html
      lang="en"
      className={`dark ${ibmPlexSans.variable} ${ibmPlexMono.variable}`}
      // suppressHydrationWarning: prevents hydration mismatch from class="dark"
      // being set server-side (Next.js SSR) vs client-side
      suppressHydrationWarning
    >
      <body className="min-h-screen bg-background font-sans antialiased">
        {/* Providers wraps all client-side context providers:
            - QueryClientProvider for TanStack Query
            - AuthProvider for OIDC token state
            (These are "use client" components, separated to keep layout as Server Component) */}
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
