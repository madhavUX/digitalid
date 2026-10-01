import { WebsiteTemplateRenderer } from "@/components/website/WebsiteTemplates";
import "@/components/website/website.css";
import { localBusinessJsonLd } from "@/components/website/siteUtils";
import { ApiError } from "@/lib/api/client";
import { getPublicSite } from "@/lib/api/publicSite";
import type { Metadata } from "next";
import { notFound } from "next/navigation";

type PageProps = {
  params: Promise<{ slug: string }>;
};

export async function generateMetadata({ params }: PageProps): Promise<Metadata> {
  const { slug } = await params;
  try {
    const data = await getPublicSite(slug);
    return {
      title: data.seo.title,
      description: data.seo.description,
      alternates: { canonical: data.seo.canonical_path },
      openGraph: {
        title: data.seo.title,
        description: data.seo.description,
        ...(data.seo.og_image ? { images: [{ url: data.seo.og_image }] } : {}),
      },
    };
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) {
      return {
        title: "Website unavailable",
        description: "This business website is not available.",
      };
    }
    return { title: "Website" };
  }
}

export default async function PublicSitePage({ params }: PageProps) {
  const { slug } = await params;
  try {
    const data = await getPublicSite(slug);
    const jsonLd = localBusinessJsonLd(data);
    return (
      <>
        <script
          type="application/ld+json"
          dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd) }}
        />
        <WebsiteTemplateRenderer data={data} />
      </>
    );
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) {
      const detail =
        typeof (error.body as { detail?: unknown } | null)?.detail === "string"
          ? String((error.body as { detail: string }).detail)
          : error.message;
      if (detail.toLowerCase().includes("available")) {
        return (
          <main className="ws-unavailable">
            <div>
              <h1>This website isn&apos;t available yet.</h1>
              <p>Please check back soon.</p>
            </div>
          </main>
        );
      }
      notFound();
    }
    throw error;
  }
}
