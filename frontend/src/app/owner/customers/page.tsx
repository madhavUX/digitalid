import { OwnerCustomersClient } from "./OwnerCustomersClient";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Customers",
  robots: { index: false, follow: false },
};

export default function OwnerCustomersPage() {
  return <OwnerCustomersClient />;
}
