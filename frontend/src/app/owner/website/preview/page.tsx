import { OwnerWebsitePreviewClient } from "./OwnerWebsitePreviewClient";
import { Suspense } from "react";

export default function OwnerWebsitePreviewPage() {
  return (
    <Suspense fallback={<p className="muted">Loading…</p>}>
      <OwnerWebsitePreviewClient />
    </Suspense>
  );
}
