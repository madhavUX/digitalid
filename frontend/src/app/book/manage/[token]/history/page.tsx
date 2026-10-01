import { BookingHistoryClient } from "./BookingHistoryClient";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Booking history",
  description: "View your past and upcoming bookings.",
  robots: { index: false, follow: false },
};

export default function BookingHistoryPage() {
  return <BookingHistoryClient />;
}
