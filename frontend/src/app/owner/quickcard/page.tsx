import { OwnerQuickCardClient } from "./OwnerQuickCardClient";
import type { Metadata } from "next";
import { Suspense } from "react";

export const metadata: Metadata = {
  title: "Manage QuickCard",
  robots: { index: false, follow: false },
};

export default function OwnerQuickCardPage() {
  return (
    <Suspense fallback={<main className="qc-owner"><p>Loading…</p></main>}>
      <OwnerQuickCardClient />
    </Suspense>
  );
}
