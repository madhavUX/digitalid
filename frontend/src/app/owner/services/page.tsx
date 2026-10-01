import { OwnerServicesClient } from "./OwnerServicesClient";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Services",
  robots: { index: false, follow: false },
};

export default function OwnerServicesPage() {
  return <OwnerServicesClient />;
}
