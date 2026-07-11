/**
 * app/docs/[[...slug]]/page.tsx — dynamic docs route (T-B-2-02)
 *
 * WHY THIS EXISTS: The optional catch-all segment `[[...slug]]` matches:
 *   /docs                              → slug = undefined
 *   /docs/getting-started              → slug = ["getting-started"]
 *   /docs/api-reference/quotes         → slug = ["api-reference", "quotes"]
 *
 * WHY a single dynamic route (not many static page.tsx files): the docs
 * structure changes weekly. A file-system-driven loader means authors
 * only touch MDX files — no Next.js routing edits required to publish a
 * new page.
 *
 * WHY MDXRemote/RSC (not next/mdx): MDXRemote runs at request/build time
 * on the server, supports passing components dynamically, and works with
 * App Router Server Components. next/mdx requires a separate loader
 * config and statically wires every MDX file at build time.
 */

import { notFound } from "next/navigation";
import { MDXRemote } from "next-mdx-remote/rsc";
import rehypePrettyCode from "rehype-pretty-code";
import remarkGfm from "remark-gfm";

import {
  getDocBySlug,
  getDocSlugs,
  extractHeadings,
  isSafeSlugSegment,
} from "@/lib/docs";
import { mdxComponents } from "@/components/docs/mdx/components";
import { DocsBreadcrumb } from "@/components/docs/DocsBreadcrumb";
import { DocsFooter } from "@/components/docs/DocsFooter";
import { DocsFeedback } from "@/components/docs/DocsFeedback";
import { DocsTableOfContents } from "@/components/docs/DocsTableOfContents";

interface PageProps {
  params: Promise<{ slug?: string[] }>;
}

/**
 * generateStaticParams — pre-render every MDX page at build time.
 *
 * WHY pre-render all: docs is publicly indexable + small (~50 pages),
 * so SSG produces fastest TTFB and best SEO. No need for ISR.
 *
 * QA iter-1 (architecture M-AR4): always return `{ slug: [] }` for the
 * root rather than `{ slug: undefined }`. Next 15 catch-all contract is
 * the empty-array form; the undefined form was undefined behaviour.
 */
export async function generateStaticParams() {
  const slugs = getDocSlugs();
  return slugs.map((slug) => ({ slug }));
}

/**
 * generateMetadata — per-page <title> + description + canonical URL +
 * Open Graph from frontmatter. Falls back gracefully when a page omits
 * fields.
 *
 * QA iter-1 (SEO M-8): added canonical + per-page OG. Without canonical
 * tags, /docs/getting-started and /docs/getting-started/ are seen as
 * duplicate content by search engines.
 */
export async function generateMetadata({ params }: PageProps) {
  const { slug } = await params;
  const doc = getDocBySlug(slug);
  if (!doc) {
    return { title: "Not found" };
  }
  return {
    title: doc.frontmatter.title,
    description: doc.frontmatter.description,
    alternates: { canonical: doc.url },
    openGraph: {
      title: doc.frontmatter.title,
      description: doc.frontmatter.description,
      url: doc.url,
      type: "article",
    },
  };
}

/**
 * editUrl — derive a "Edit this page on GitHub" link from the on-disk
 * file path. Skips emission when the repo URL is unset.
 */
function editUrl(filePath: string): string | undefined {
  // We only want the path inside the repo — chop off everything before
  // "apps/worldview-web/...".
  const repoBase = process.env.NEXT_PUBLIC_REPO_URL;
  if (!repoBase) return undefined;
  const idx = filePath.indexOf("apps/worldview-web/");
  if (idx < 0) return undefined;
  const repoPath = filePath.slice(idx);
  return `${repoBase.replace(/\/$/, "")}/edit/main/${repoPath}`;
}

export default async function DocsPage({ params }: PageProps) {
  const { slug } = await params;
  // QA iter-1 (bugs M-2, security M-1): defense-in-depth slug validator.
  // Catches malformed segments before the loader. Today's loader does
  // membership-test only (no fs.join with user input), so this is belt-
  // and-suspenders, not gating real exploitable behaviour.
  if (slug && !slug.every(isSafeSlugSegment)) {
    notFound();
  }
  const doc = getDocBySlug(slug);
  if (!doc) {
    notFound();
  }

  // Headings come from the raw MDX source — same logic the search index
  // uses, so the IDs match what the MDX components emit at render.
  const headings = extractHeadings(doc.body);

  // rehype-pretty-code config: Shiki highlight with the "github-dark"
  // theme so token colors stay legible against our zinc-near-black bg.
  // grid: true gives every line its own row (helpful for line-numbers
  // and line-highlighting features future content might use).
  const rehypePrettyCodeOptions = {
    theme: "github-dark",
    keepBackground: false,
    defaultLang: "plaintext",
  };

  return (
    <article>
      <DocsBreadcrumb slug={doc.slug} title={doc.frontmatter.title} />

      <header className="mb-6">
        <h1 className="mb-2 text-3xl font-semibold tracking-tight text-foreground sm:text-4xl">
          {doc.frontmatter.title}
        </h1>
        {doc.frontmatter.description ? (
          <p className="text-base text-muted-foreground">
            {doc.frontmatter.description}
          </p>
        ) : null}
      </header>

      {/* Mobile / tablet (md-lg): collapsed "On this page" disclosure
          above the body so users on small viewports still get an in-page
          TOC. QA iter-1 (a11y/responsive M-A8). */}
      {headings.length > 0 ? (
        <details className="mb-6 rounded-[2px] border border-border/40 bg-card/30 px-3 py-2 xl:hidden">
          <summary className="cursor-pointer font-mono text-[10px] uppercase tracking-[0.16em] text-muted-foreground">
            On this page ({headings.length})
          </summary>
          <ul className="mt-2 space-y-1 border-l border-border/30 text-xs">
            {headings.map((h) => (
              <li key={h.slug} className={h.level === 3 ? "pl-2" : ""}>
                <a
                  href={`#${h.slug}`}
                  className="-ml-px block border-l-2 border-transparent py-0.5 pl-3 text-muted-foreground hover:border-border/60 hover:text-foreground"
                >
                  {h.text}
                </a>
              </li>
            ))}
          </ul>
        </details>
      ) : null}

      {/* Right-rail TOC — visible only at xl widths since the layout
          allocates the third column conditionally. Empty-headings case
          handled inside the component. QA iter-1 (a11y m-AR-TOC):
          xl:sticky inside the grid cell instead of xl:fixed so the
          reserved column actually holds the TOC and there's no overlap
          risk at the breakpoint boundary. */}
      <div className="hidden xl:absolute xl:right-8 xl:top-24 xl:block xl:w-44">
        <DocsTableOfContents headings={headings} />
      </div>

      {/* MDX body — components map applies our themed renderers + custom
          callout/codeblock/tabs/steps. Compile happens server-side. */}
      <div className="prose-docs">
        <MDXRemote
          source={doc.body}
          components={mdxComponents}
          options={{
            // WHY blockJS: false — ROOT CAUSE FIX for the next-mdx-remote
            // 5→6 bump (MDX v3). v6 added a NEW security default, blockJS:
            // true, which injects a remark plugin (removeJavaScriptExpressions)
            // that STRIPS every MDX JavaScript expression before compile —
            // including JSX *expression attributes* like
            //   <DocsTabs items={["curl", "Python", "TypeScript"]}>
            // The plugin deletes any attribute whose value is an expression
            // (mdxJsxAttributeValueExpression) while KEEPING plain string
            // literals. That is exactly why string props survived
            // (Callout type="tip", CodeBlock filename="x.ts") but `items`
            // arrived at DocsTabs as `undefined` — the whole `items={...}`
            // attribute was removed from the tree, so `items.map()` crashed
            // the static build of /docs/api-reference.
            //
            // Setting blockJS: false disables that stripper so expression
            // attributes compile through normally and reach our components.
            //
            // WHY THIS IS SAFE HERE: our MDX is FIRST-PARTY, trusted content
            // authored in-repo under content/docs/ and reviewed via PR — it
            // is never user-submitted. The blockJS shield exists to defend
            // against untrusted MDX, which is not our threat model. We keep
            // blockDangerousJS at its default (true) as defense-in-depth: it
            // still blocks eval/Function/process and other dangerous globals
            // even with JS expressions enabled.
            blockJS: false,
            mdxOptions: {
              remarkPlugins: [remarkGfm],
              rehypePlugins: [[rehypePrettyCode, rehypePrettyCodeOptions]],
            },
          }}
        />
      </div>

      <DocsFeedback pageUrl={doc.url} />
      <DocsFooter
        updated={doc.frontmatter.updated}
        editUrl={editUrl(doc.filePath)}
      />
    </article>
  );
}

/**
 * Force static export so /docs and every /docs/[slug] route is
 * pre-rendered at build time — see file-level WHY comment.
 *
 * `dynamicParams: false` would 404 any request whose slug isn't in
 * generateStaticParams, but we want a soft 404 page instead, so we
 * leave it default (true) and rely on notFound() above.
 *
 * QA iter-1 (architecture m-AR3): explicitly request the Node runtime —
 * lib/docs.ts uses node:fs which is incompatible with Edge. Pinning
 * `runtime = "nodejs"` defends against future config drift.
 */
export const dynamic = "force-static";
export const runtime = "nodejs";
