import { OwnerCalendarClient } from "./OwnerCalendarClient";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Calendar",
  robots: { index: false, follow: false },
};

export default function OwnerCalendarPage() {
  return <OwnerCalendarClient />;
}
