import { OwnerOnboardingClient } from "./OwnerOnboardingClient";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Business setup",
  robots: { index: false, follow: false },
};

export default function OwnerOnboardingPage() {
  return <OwnerOnboardingClient />;
}
