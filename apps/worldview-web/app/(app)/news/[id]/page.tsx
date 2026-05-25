/**
 * app/(app)/news/[id]/page.tsx — article detail stub (W5-T-24)
 *
 * WHY THIS EXISTS (Δ20): RelatedHeadlinesList + WhatsMovingStrip click handlers
 *   route to `/news/{article_id}`. Without this route Next.js 404s the click.
 *   This stub prevents that while a full article detail implementation is deferred.
 *
 * DEFERRED: full article body, related articles, sentiment breakdown.
 *   The `getArticleById` gateway method doesn't exist yet — this stub renders
 *   a "loading / not found" message and a back link so the UX degrades gracefully.
 *
 * When the full implementation lands:
 *   1. Add `getArticleById(id)` to `/lib/api/news.ts`.
 *   2. Replace the stub body below with a proper fetch + render.
 */

import Link from "next/link";

interface ArticlePageProps {
  params: Promise<{ id: string }>;
}

export default async function ArticlePage({ params }: ArticlePageProps) {
  const { id } = await params;

  return (
    <div className="flex flex-col items-center justify-center min-h-[60vh] gap-4 px-6">
      <p className="text-[13px] text-muted-foreground">
        Article detail coming soon.
      </p>
      <p className="text-[11px] text-muted-foreground/50 font-mono">{id}</p>
      <Link
        href="/news"
        className="text-[11px] text-muted-foreground underline-offset-2 hover:underline"
      >
        ← Back to News
      </Link>
    </div>
  );
}
