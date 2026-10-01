import { OwnerDashboardClient } from "./OwnerDashboardClient";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Owner dashboard",
  robots: { index: false, follow: false },
};

export default function OwnerDashboardPage() {
  return <OwnerDashboardClient />;
}
