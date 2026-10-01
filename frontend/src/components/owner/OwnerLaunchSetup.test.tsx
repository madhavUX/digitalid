import { OwnerLaunchSetup } from "@/components/owner/OwnerLaunchSetup";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const getLaunch = vi.fn();
const updateLaunch = vi.fn();

vi.mock("@/lib/api/ownerApi", () => ({
  getBusinessLaunchProfile: (...args: unknown[]) => getLaunch(...args),
  updateBusinessLaunchProfile: (...args: unknown[]) => updateLaunch(...args),
  publishWebsite: vi.fn(async () => ({
    website_status: "PUBLISHED",
    launch_status: "LIVE",
    public_url: "https://ksnsalon.bookanything.in",
  })),
  getGoogleBusinessStatus: vi.fn(async () => ({
    connected: false,
    status: "NOT_CONNECTED",
    oauth_available: false,
    google_account: { id: null, email: null },
    google_business_account: { name: null, selected: false },
    google_location: { id: null, display_name: null, selected: false },
    location_selected: false,
    website_sync_available: false,
    selection_required: false,
  })),
  startGoogleBusinessConnect: vi.fn(),
  disconnectGoogleBusiness: vi.fn(),
  syncGoogleBookingUrl: vi.fn(),
  getGoogleBusinessAccounts: vi.fn(),
  selectGoogleBusinessAccount: vi.fn(),
  getGoogleBusinessLocations: vi.fn(),
  selectGoogleBusinessLocation: vi.fn(),
  getWhatsAppConnection: vi.fn(async () => ({
    id: "wa",
    business_id: "biz",
    connected: false,
    status: "DISCONNECTED",
    phone_number_id: null,
    business_account_id: null,
    display_phone_number: null,
    verified_name: null,
    connected_at: null,
    disconnected_at: null,
    last_error_code: null,
    last_error_message: null,
    provider: "deferred",
    connect_available: false,
  })),
  connectWhatsApp: vi.fn(),
  disconnectWhatsApp: vi.fn(),
  listWhatsAppTemplates: vi.fn(async () => ({
    count: 0,
    limit: 25,
    offset: 0,
    next: null,
    previous: null,
    results: [],
  })),
  createWhatsAppTemplate: vi.fn(),
  deleteWhatsAppTemplate: vi.fn(),
}));

const launchFixture = {
  ready: false,
  progress: 75,
  completed_steps: 6,
  total_steps: 8,
  remaining_blocking: 2,
  launch_status: "DRAFT" as const,
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
  template: {
    selected: false,
    key: null,
    options: [
      {
        key: "SALON_MODERN",
        label: "Modern",
        description: "Clean, contemporary salon layout.",
      },
      {
        key: "SALON_CLASSIC",
        label: "Classic",
        description: "Timeless salon presentation.",
      },
      {
        key: "SALON_LUXURY",
        label: "Luxury",
        description: "Elevated, premium salon look.",
      },
    ],
  },
  domain: {
    configured: true,
    status: "SUBDOMAIN_ACTIVE",
    subdomain: "ksnsalon",
    subdomain_hostname: "ksnsalon.bookanything.in",
    custom_domain: null,
    site_root_domain: "bookanything.in",
  },
  google_business: {
    configured: false,
    status: "NOT_STARTED",
    url: null,
  },
  whatsapp: {
    configured: true,
    status: "ACTIVE",
    platform_status: "ACTIVE",
  },
  website: { status: "NOT_STARTED" },
  quickcard: { created: true, published: true },
  booking: { ready: true },
  profile: null,
};

describe("OwnerLaunchSetup", () => {
  beforeEach(() => {
    getLaunch.mockReset();
    updateLaunch.mockReset();
    getLaunch.mockResolvedValue(launchFixture);
    updateLaunch.mockResolvedValue({
      profile: null,
      launch: {
        ...launchFixture,
        ready: true,
        progress: 100,
        remaining_blocking: 0,
        launch_status: "READY",
        checklist: { ...launchFixture.checklist, template: true, website: true },
        blocking_reasons: [],
        template: { ...launchFixture.template, selected: true, key: "SALON_MODERN" },
      },
    });
  });

  it("renders template, domain, google, whatsapp, and checklist", async () => {
    render(
      <OwnerLaunchSetup
        token="tok"
        businessId="biz"
        locationId="loc"
        showFinish
      />,
    );
    expect(await screen.findByText(/Choose your website design/i)).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: /^Modern$/i })).toBeInTheDocument();
    expect(screen.getByText("ksnsalon.bookanything.in")).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: /^Google Business Profile URL$/i }),
    ).toBeInTheDocument();
    expect(
      await screen.findByRole("heading", { name: /^Google Business$/i }),
    ).toBeInTheDocument();
    expect(await screen.findByText(/Not connected/i)).toBeInTheDocument();
    expect(screen.getByText(/✓ Connected/i)).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: /^Launch checklist$/i }),
    ).toBeInTheDocument();
    expect(screen.getByText("IN PROGRESS")).toBeInTheDocument();
    expect(screen.getByText(/Select a website template/i)).toBeInTheDocument();
  });

  it("saves template selection", async () => {
    const user = userEvent.setup();
    render(<OwnerLaunchSetup token="tok" businessId="biz" locationId="loc" />);
    await screen.findByText(/Choose your website design/i);
    await user.click(screen.getByLabelText(/Modern/i));
    await user.click(screen.getByRole("button", { name: /Save template/i }));
    await waitFor(() => {
      expect(updateLaunch).toHaveBeenCalledWith(
        "biz",
        "tok",
        { template_key: "SALON_MODERN" },
        "loc",
      );
    });
  });
});
