import { OwnerBookingPlansClient } from "./OwnerBookingPlansClient";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Regular bookings",
  robots: { index: false, follow: false },
};

export default function OwnerBookingPlansPage() {
  return <OwnerBookingPlansClient />;
}
