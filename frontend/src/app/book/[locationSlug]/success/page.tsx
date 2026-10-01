import { BookingSuccessView } from "@/components/booking/BookingFunnel";
import { ApiError } from "@/lib/api/client";
import { getPublicAppointment } from "@/lib/api/publicBooking";
import { getPublicLocation } from "@/lib/api/publicLocation";
import type { Metadata } from "next";
import { notFound } from "next/navigation";

type PageProps = {
  params: Promise<{ locationSlug: string }>;
  searchParams: Promise<{ ref?: string; manage?: string }>;
};

export async function generateMetadata({
  params,
}: PageProps): Promise<Metadata> {
  const { locationSlug } = await params;
  try {
    const location = await getPublicLocation(locationSlug);
    return {
      title: `Booking confirmed · ${location.business.name}`,
      description: "Your appointment has been confirmed.",
      robots: { index: false, follow: false },
    };
  } catch {
    return { title: "Booking confirmed", robots: { index: false, follow: false } };
  }
}

export default async function BookingSuccessPage({
  params,
  searchParams,
}: PageProps) {
  const { locationSlug } = await params;
  const { ref, manage } = await searchParams;
  if (!ref) notFound();

  let appointment;
  try {
    appointment = await getPublicAppointment(ref);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) notFound();
    throw error;
  }

  return (
    <BookingSuccessView
      locationSlug={locationSlug}
      appointment={appointment}
      manageToken={manage || null}
    />
  );
}
