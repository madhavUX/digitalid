import Loading from "@/app/q/[slug]/loading";
import NotFound from "@/app/q/[slug]/not-found";
import { QuickCardView } from "@/components/quickcard/QuickCardView";
import { quickCardJsonLd } from "@/components/quickcard/quickCardJsonLd";
import type { PublicQuickCard } from "@/lib/api/types";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const trackPageView = vi.hoisted(() => vi.fn());
const trackCta = vi.hoisted(() => vi.fn());

vi.mock("@/lib/quickcard/quickCardAnalytics", () => ({
  trackPageView,
  trackCta,
}));

const sample: PublicQuickCard = {
  slug: "ksn-salon",
  business: {
    name: "KSN Salon",
    description: "Premium cuts",
    address: "12 MG Road, Bengaluru",
    timezone: "Asia/Kolkata",
    vertical: "SALON",
  },
  location: {
    name: "Downtown",
    slug: "downtown",
    timezone: "Asia/Kolkata",
    phone: "+918012345678",
    address: {
      line1: "12 MG Road",
      line2: "",
      city: "Bengaluru",
      state: "KA",
      postal_code: "",
      country: "IN",
    },
  },
  quickcard: {
    headline: "Look your best",
    description: "Walk-ins welcome",
    logo_url: "",
    cover_image_url: "",
    phone: "+918012345678",
    whatsapp: "+918012345678",
    website_url: "https://example.com",
    google_maps_url: "https://maps.example.com",
    instagram_url: "https://instagram.com/ksn",
    facebook_url: "",
  },
  services: [
    {
      id: "svc-1",
      slug: "haircut",
      name: "Haircut",
      description: "",
      duration_minutes: 30,
      price: "400.00",
      currency: "INR",
      is_bookable_online: true,
      category: null,
    },
  ],
  staff: [
    {
      id: "staff-1",
      display_name: "Priya",
      title: "Stylist",
      bio: "",
      photo_url: "",
      services: [],
    },
  ],
  hours: [
    {
      weekday: 0,
      label: "Monday",
      closed: false,
      opens_at: "09:00",
      closes_at: "17:00",
    },
  ],
  booking: {
    location_slug: "downtown",
    location_id: "loc-1",
    booking_url: "https://book.example.com/book/downtown",
    booking_path: "/book/downtown",
  },
  reviews: null,
  actions: {
    booking_url: "/book/downtown?source=quickcard&ref=ksn-salon",
    whatsapp_url: "https://wa.me/918012345678",
    call_url: "tel:+918012345678",
    directions_url: "https://maps.example.com",
    review_url: "https://search.google.com/local/writereview?placeid=abc",
    share_url: "https://book.example.com/q/ksn-salon",
  },
  seo: {
    title: "KSN Salon — Book now",
    description: "Look your best",
    canonical_path: "/q/ksn-salon",
    og_image: null,
  },
};

describe("QuickCardView", () => {
  beforeEach(() => {
    trackPageView.mockReset();
    trackCta.mockReset();
  });

  it("renders business info, services, contact, and Book Now", () => {
    trackPageView.mockClear();
    trackCta.mockClear();
    render(<QuickCardView data={sample} />);
    expect(screen.getByRole("heading", { name: "KSN Salon" })).toBeInTheDocument();
    expect(screen.getByText("Look your best")).toBeInTheDocument();
    expect(screen.getByText("Haircut")).toBeInTheDocument();
    expect(screen.getByText("Priya")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "WhatsApp" })).toHaveAttribute(
      "href",
      "https://wa.me/918012345678",
    );
    expect(screen.getByRole("link", { name: "Call" })).toHaveAttribute(
      "href",
      "tel:+918012345678",
    );
    expect(screen.getByRole("link", { name: "Directions" })).toBeInTheDocument();
    const cta = screen.getByTestId("book-slot-cta");
    expect(cta).toHaveAttribute("href", "/book/downtown?source=quickcard&ref=ksn-salon");
    expect(cta).toHaveAttribute("data-cta", "book");
    expect(cta).toHaveTextContent("Book Now");
    expect(screen.getByRole("link", { name: "Leave a Google Review" })).toHaveAttribute(
      "href",
      sample.actions.review_url!,
    );
    expect(document.querySelector(".qc-sticky")).not.toBeNull();
    const schema = quickCardJsonLd(sample) as Record<string, unknown>;
    expect(schema["@type"]).toBe("LocalBusiness");
    expect(schema).not.toHaveProperty("aggregateRating");
    expect(trackPageView).toHaveBeenCalledWith("ksn-salon");
  });

  it("hides contact buttons when not configured", async () => {
    const user = userEvent.setup();
    render(
      <QuickCardView
        data={{
          ...sample,
          actions: {
            ...sample.actions,
            whatsapp_url: null,
            call_url: null,
            directions_url: null,
            review_url: null,
          },
        }}
      />,
    );
    expect(screen.queryByRole("link", { name: "WhatsApp" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Call" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Directions" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Leave a Google Review" })).not.toBeInTheDocument();
    trackCta.mockClear();
    await user.click(screen.getByTestId("book-slot-cta"));
    expect(trackCta).toHaveBeenCalledTimes(1);
    expect(trackCta).toHaveBeenCalledWith("ksn-salon", "book");
  });

  it("copies the public link when Web Share is unavailable", async () => {
    const user = userEvent.setup();
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText },
    });
    Object.defineProperty(navigator, "share", { configurable: true, value: undefined });
    render(<QuickCardView data={sample} />);
    await user.click(screen.getByRole("button", { name: "Share" }));
    expect(writeText).toHaveBeenCalled();
    expect(String(writeText.mock.calls[0][0])).toContain("KSN Salon");
    expect(screen.getByRole("button", { name: "Link copied" })).toBeInTheDocument();
  });

  it("tracks visible CTAs and still navigates when analytics throws", async () => {
    trackCta.mockImplementation(() => {
      throw new Error("analytics down");
    });
    const user = userEvent.setup();
    render(<QuickCardView data={sample} />);
    const book = screen.getByTestId("book-slot-cta");
    await user.click(book);
    expect(book).toHaveAttribute("href", "/book/downtown?source=quickcard&ref=ksn-salon");
    expect(trackCta).toHaveBeenCalledWith("ksn-salon", "book");
    trackCta.mockReset();
    await user.click(screen.getByRole("link", { name: "WhatsApp" }));
    await user.click(screen.getByRole("link", { name: "Call" }));
    await user.click(screen.getByRole("link", { name: "Directions" }));
    await user.click(screen.getByRole("link", { name: "Leave a Google Review" }));
    await user.click(screen.getByRole("button", { name: "Share" }));
    expect(trackCta.mock.calls.map((call) => call[1])).toEqual([
      "whatsapp",
      "call",
      "directions",
      "review",
      "share",
    ]);
  });

  it("renders loading and unavailable states", () => {
    render(<Loading />);
    expect(screen.getByText(/Loading QuickCard/)).toBeInTheDocument();
    render(<NotFound />);
    expect(screen.getByRole("heading", { name: "QuickCard not found" })).toBeInTheDocument();
  });
});
