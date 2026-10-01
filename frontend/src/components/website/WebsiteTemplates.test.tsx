import {
  SalonClassicTemplate,
  SalonLuxuryTemplate,
  SalonModernTemplate,
} from "@/components/website/WebsiteTemplates";
import type { PublicSalonSite } from "@/lib/api/types";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

const baseSite: PublicSalonSite = {
  template: "SALON_MODERN",
  preview: false,
  published: true,
  business: {
    name: "KSN Salon",
    slug: "ksn-salon",
    category: "Salon",
    vertical: "SALON",
    description: "Cuts and colour in Visakhapatnam.",
    logo_url: null,
  },
  location: {
    name: "MVP Colony",
    slug: "mvp-colony",
    timezone: "Asia/Kolkata",
    address: "MVP Colony, Visakhapatnam",
    address_parts: {
      line1: "MVP Colony",
      line2: "",
      city: "Visakhapatnam",
      state: "AP",
      postal_code: "",
      country: "IN",
    },
    city: "Visakhapatnam",
    phone: "+919999000111",
  },
  hero: {
    headline: "KSN Salon",
    tagline: "Style starts here",
    description: "Cuts and colour in Visakhapatnam.",
    cover_image_url: null,
  },
  contact: {
    phone: "+919999000111",
    whatsapp: "+919999000111",
    email: null,
  },
  social: {
    website: null,
    instagram: "https://instagram.com/ksn",
    facebook: null,
    google_maps: "https://maps.google.com/?q=MVP",
  },
  services: [
    {
      id: "1",
      slug: "haircut",
      name: "Haircut",
      description: "",
      duration_minutes: 30,
      price: "400.00",
      currency: "INR",
    },
  ],
  staff: [
    {
      id: "s1",
      display_name: "Ravi",
      title: "Stylist",
      bio: "",
      photo_url: null,
      services: [{ name: "Haircut", duration_minutes: 30 }],
    },
  ],
  hours: [
    {
      weekday: 0,
      label: "Monday",
      closed: false,
      opens_at: "09:00",
      closes_at: "18:00",
    },
  ],
  images: [],
  booking: { path: "/book/mvp-colony", url: "http://localhost:3000/book/mvp-colony" },
  quickcard: {
    slug: "ksn",
    path: "/q/ksn",
    url: "http://localhost:3000/q/ksn",
    is_published: true,
  },
  site: {
    path: "/site/mvp-colony",
    url: "http://localhost:3000/site/mvp-colony",
    subdomain: "ksnsalon",
    subdomain_hostname: "ksnsalon.bookanything.in",
  },
  seo: {
    title: "KSN Salon — Book an Appointment",
    description: "Cuts and colour in Visakhapatnam.",
    canonical_path: "/site/mvp-colony",
    og_image: null,
  },
};

describe("Salon website templates", () => {
  it("Modern renders hero, services, team, and booking CTA", () => {
    render(<SalonModernTemplate data={baseSite} />);
    expect(screen.getByRole("heading", { level: 1, name: /KSN Salon/i })).toBeInTheDocument();
    expect(screen.getByText("Haircut")).toBeInTheDocument();
    expect(screen.getByText("Ravi")).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: /Book a Slot/i })[0]).toHaveAttribute(
      "href",
      "/book/mvp-colony",
    );
    expect(screen.getByRole("link", { name: /^Call$/i })).toHaveAttribute(
      "href",
      "tel:+919999000111",
    );
  });

  it("Classic uses the same booking path", () => {
    render(<SalonClassicTemplate data={{ ...baseSite, template: "SALON_CLASSIC" }} />);
    expect(screen.getByText("Haircut")).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: /Book a Slot/i })[0]).toHaveAttribute(
      "href",
      "/book/mvp-colony",
    );
  });

  it("Luxury hides empty team gracefully when staff missing", () => {
    render(
      <SalonLuxuryTemplate
        data={{ ...baseSite, template: "SALON_LUXURY", staff: [] }}
      />,
    );
    expect(screen.queryByRole("heading", { name: /Our team/i })).not.toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: /Book a Slot/i })[0]).toHaveAttribute(
      "href",
      "/book/mvp-colony",
    );
  });

  it("preview mode shows banner", () => {
    render(<SalonModernTemplate data={baseSite} preview />);
    expect(screen.getByText(/Preview — not public/i)).toBeInTheDocument();
  });
});
