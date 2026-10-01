import { QuickCardView } from "@/components/quickcard/QuickCardView";
import { quickCardJsonLd } from "@/components/quickcard/quickCardJsonLd";
import { ApiError } from "@/lib/api/client";
import { getPublicQuickCard } from "@/lib/api/publicQuickCard";
import type { Metadata } from "next";
import { notFound } from "next/navigation";

type PageProps = {
  params: Promise<{ slug: string }>;
};

export async function generateMetadata({ params }: PageProps): Promise<Metadata> {
  const { slug } = await params;
  try {
    const data = await getPublicQuickCard(slug);
    const image = data.seo.og_image;
    return {
      title: data.seo.title,
      description: data.seo.description,
      alternates: { canonical: data.seo.canonical_path },
      openGraph: {
        title: data.seo.title,
        description: data.seo.description,
        url: data.seo.canonical_path,
        ...(image ? { images: [{ url: image }] } : {}),
      },
    };
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) {
      return {
        title: "QuickCard not found",
        description: "This QuickCard is unavailable.",
      };
    }
    return { title: "QuickCard" };
  }
}

export default async function PublicQuickCardPage({ params }: PageProps) {
  const { slug } = await params;
  try {
    const data = await getPublicQuickCard(slug);
    return (
      <>
        <script
          type="application/ld+json"
          dangerouslySetInnerHTML={{ __html: JSON.stringify(quickCardJsonLd(data)) }}
        />
        <QuickCardView data={data} />
      </>
    );
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) notFound();
    throw error;
  }
}
