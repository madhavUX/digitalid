import { OwnerStaffClient } from "./OwnerStaffClient";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Staff",
  robots: { index: false, follow: false },
};

export default function OwnerStaffPage() {
  return <OwnerStaffClient />;
}
