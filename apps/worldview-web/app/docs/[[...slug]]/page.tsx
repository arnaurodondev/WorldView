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
  getAllDocs,
  getDocBySlug,
  getDocSlugs,
  extractHeadings,
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
 * Returns an empty-slug entry for the /docs root index page since
 * Next.js requires it to be explicitly listed for the optional catch-all
 * route to pre-render that variant.
 */
export async function generateStaticParams() {
  const slugs = getDocSlugs();
  return slugs.map((slug) => ({ slug: slug.length === 0 ? undefined : slug }));
}

/**
 * generateMetadata — per-page <title> + description from frontmatter.
 * Falls back gracefully when a page omits a description.
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

      {/* Right-rail TOC — visible only at xl widths since the layout
          allocates the third column conditionally. The empty-headings
          case is handled inside the component. */}
      <div className="hidden xl:fixed xl:right-8 xl:top-24 xl:block xl:w-44">
        <DocsTableOfContents headings={headings} />
      </div>

      {/* MDX body — components map applies our themed renderers + custom
          callout/codeblock/tabs/steps. Compile happens server-side. */}
      <div className="prose-docs">
        <MDXRemote
          source={doc.body}
          components={mdxComponents}
          options={{
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
 */
export const dynamic = "force-static";

// Touch the loader at module load so dev-server hot-reloads the index
// without restart. Pure side-effect import — no runtime impact in prod.
void getAllDocs;
