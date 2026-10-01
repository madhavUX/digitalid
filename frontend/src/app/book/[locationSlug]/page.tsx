import { BookingFunnel } from "@/components/booking/BookingFunnel";
import { ApiError } from "@/lib/api/client";
import { listPublicServices } from "@/lib/api/publicCatalog";
import { getPublicLocation } from "@/lib/api/publicLocation";
import { listPublicStaff } from "@/lib/api/publicStaff";
import type { Metadata } from "next";
import { notFound } from "next/navigation";

type PageProps = {
  params: Promise<{ locationSlug: string }>;
  searchParams: Promise<{ service?: string; staff?: string; source?: string; ref?: string }>;
};

export async function generateMetadata({
  params,
}: PageProps): Promise<Metadata> {
  const { locationSlug } = await params;
  try {
    const location = await getPublicLocation(locationSlug);
    const title = `Book at ${location.business.name}`;
    const description = `Book ${location.name} online — ${location.business.name}.`;
    return {
      title,
      description,
      alternates: {
        canonical: `/book/${locationSlug}`,
      },
      openGraph: {
        title,
        description,
      },
    };
  } catch {
    return {
      title: "Location not found",
      description: "This booking page is unavailable.",
    };
  }
}

export default async function BookLocationPage({
  params,
  searchParams,
}: PageProps) {
  const { locationSlug } = await params;
  const query = await searchParams;

  let location;
  try {
    location = await getPublicLocation(locationSlug);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) notFound();
    throw error;
  }

  const [services, staff] = await Promise.all([
    listPublicServices(locationSlug).catch(() => []),
    listPublicStaff(locationSlug).catch(() => []),
  ]);

  return (
    <BookingFunnel
      location={location}
      locationSlug={locationSlug}
      initialServices={services}
      initialStaff={staff}
      prefillServiceId={query.service || null}
      prefillStaffId={query.staff || null}
      attribution={
        (query.source === "quickcard" || query.source === "retention") && query.ref
          ? { source: query.source, ref: query.ref }
          : null
      }
    />
  );
}
