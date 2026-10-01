import { OwnerBookingsClient } from "./OwnerBookingsClient";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Bookings",
  robots: { index: false, follow: false },
};

export default function OwnerBookingsPage() {
  return <OwnerBookingsClient />;
}
