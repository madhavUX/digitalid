import { OwnerWebsiteClient } from "./OwnerWebsiteClient";
import type { Metadata } from "next";
import { Suspense } from "react";

export const metadata: Metadata = {
  title: "Website",
  robots: { index: false, follow: false },
};

export default function OwnerWebsitePage() {
  return (
    <Suspense fallback={<p className="muted">Loading…</p>}>
      <OwnerWebsiteClient />
    </Suspense>
  );
}
