import { OwnerDashboardClient } from "@/app/owner/dashboard/OwnerDashboardClient";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  usePathname: () => "/owner/dashboard",
  useRouter: () => ({ push: vi.fn() }),
}));

vi.mock("@/lib/api/ownerApi", () => ({
  listBusinesses: vi.fn(async () => ({
    results: [{ id: "biz-1", name: "KSN Salon", vertical: "SALON" }],
  })),
  getBusinessDashboard: vi.fn(async () => ({
    business: { id: "biz-1", name: "KSN Salon", vertical: "SALON" },
    location: {
      id: "loc-1",
      name: "MVP Colony",
      slug: "mvp-colony",
      timezone: "Asia/Kolkata",
      is_primary: true,
    },
    locations: [
      {
        id: "loc-1",
        name: "MVP Colony",
        slug: "mvp-colony",
        timezone: "Asia/Kolkata",
        is_primary: true,
      },
    ],
    setup: {
      ready: true,
      progress: 100,
      completed_steps: 7,
      total_steps: 7,
      blocking_reasons: [],
      steps: {
        business: true,
        location: true,
        services: true,
        staff: true,
        availability: true,
        quickcard: true,
        publish: true,
      },
    },
    launch: {
      ready: false,
      progress: 75,
      completed_steps: 6,
      total_steps: 8,
      remaining_blocking: 2,
      launch_status: "DRAFT",
      checklist: {
        business: true,
        location: true,
        services: true,
        staff: true,
        availability: true,
        quickcard: true,
        booking: true,
        template: false,
        domain: true,
        google_business: false,
        whatsapp: true,
        website: false,
      },
      blocking_reasons: ["Select a website template."],
      template: { selected: false, key: null, options: [] },
      domain: {
        configured: true,
        status: "SUBDOMAIN_ACTIVE",
        subdomain: "ksn",
        subdomain_hostname: "ksn.bookanything.in",
        custom_domain: null,
        site_root_domain: "bookanything.in",
      },
      whatsapp: { configured: true, status: "ACTIVE", platform_status: "ACTIVE" },
      website: { status: "NOT_STARTED" },
      quickcard: { created: true, published: true },
      booking: { ready: true },
    },
    today: { bookings: 0, upcoming: 0, regular_bookings: 0 },
    appointments: [],
    quickcard: null,
    booking_path: "/book/mvp-colony",
    booking_url: "http://localhost:3000/book/mvp-colony",
  })),
}));

describe("OwnerDashboardClient", () => {
  beforeEach(() => {
    window.localStorage.clear();
    window.localStorage.setItem("ba_access_token", "test-token");
  });

  it("shows launch setup warning when booking ready but launch incomplete", async () => {
    render(<OwnerDashboardClient />);
    expect(
      await screen.findByRole("heading", { name: /Finish your launch setup/i }),
    ).toBeInTheDocument();
    expect(screen.getByText(/2 items remaining/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Continue Setup/i })).toHaveAttribute(
      "href",
      "/owner/onboarding",
    );
  });
});
