import { ManageBookingClient } from "@/components/booking/ManageBookingClient";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Manage booking",
  description: "View or cancel your appointment.",
  robots: { index: false, follow: false },
};

export default function ManageBookingPage() {
  return <ManageBookingClient />;
}
