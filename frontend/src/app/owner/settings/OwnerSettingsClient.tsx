"use client";

import { OwnerShell, useOwnerToken } from "@/components/owner/OwnerShell";
import Link from "next/link";

export function OwnerSettingsClient() {
  const token = useOwnerToken();
  return (
    <OwnerShell title="Settings">
      {!token ? null : (
        <section className="owner-card">
          <h2>Business settings</h2>
          <p className="muted">
            Use setup to update business profile, location, services, and staff.
          </p>
          <div className="actions">
            <Link className="primary" href="/owner/onboarding">
              Open setup
            </Link>
            <Link className="ghost" href="/owner/quickcard">
              QuickCard
            </Link>
            <Link className="ghost" href="/owner/dashboard">
              Dashboard
            </Link>
          </div>
        </section>
      )}
    </OwnerShell>
  );
}
