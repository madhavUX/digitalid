import { OwnerGoogleBusinessCard } from "@/components/owner/OwnerGoogleBusinessCard";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const getStatus = vi.fn();
const startConnect = vi.fn();
const disconnect = vi.fn();
const sync = vi.fn();
const getAccounts = vi.fn();
const selectAccount = vi.fn();
const getLocations = vi.fn();
const selectLocation = vi.fn();

vi.mock("@/lib/api/ownerApi", () => ({
  getGoogleBusinessStatus: (...args: unknown[]) => getStatus(...args),
  startGoogleBusinessConnect: (...args: unknown[]) => startConnect(...args),
  disconnectGoogleBusiness: (...args: unknown[]) => disconnect(...args),
  syncGoogleBookingUrl: (...args: unknown[]) => sync(...args),
  getGoogleBusinessAccounts: (...args: unknown[]) => getAccounts(...args),
  selectGoogleBusinessAccount: (...args: unknown[]) => selectAccount(...args),
  getGoogleBusinessLocations: (...args: unknown[]) => getLocations(...args),
  selectGoogleBusinessLocation: (...args: unknown[]) => selectLocation(...args),
}));

const baseStatus = {
  connected: false,
  status: "NOT_CONNECTED",
  oauth_available: true,
  google_account: { id: null, email: null },
  google_business_account: { name: null, selected: false },
  google_location: { id: null, display_name: null, selected: false },
  location_selected: false,
  website_sync_available: false,
  selection_required: false,
  synced: false,
  sync_block_reason: null,
  booking_url: "https://bookanything.in/book/downtown",
};

describe("OwnerGoogleBusinessCard", () => {
  beforeEach(() => {
    getStatus.mockReset();
    startConnect.mockReset();
    disconnect.mockReset();
    sync.mockReset();
    getAccounts.mockReset();
    selectAccount.mockReset();
    getLocations.mockReset();
    selectLocation.mockReset();
  });

  it("shows disconnected state and connect CTA", async () => {
    getStatus.mockResolvedValue({ ...baseStatus });
    render(
      <OwnerGoogleBusinessCard token="tok" businessId="biz" locationId="loc" />,
    );
    expect(await screen.findByText("Not connected")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Connect Google/i })).toBeEnabled();
  });

  it("shows location selection when connected without mapping", async () => {
    getStatus.mockResolvedValue({
      ...baseStatus,
      connected: true,
      status: "LOCATION_SELECTION_REQUIRED",
      selection_required: true,
      google_account: { id: "acct", email: "owner@example.com" },
    });
    getAccounts.mockResolvedValue({
      accounts: [
        {
          name: "accounts/primary",
          display_name: "Primary GBP",
          account_type: "PERSONAL",
        },
      ],
      count: 1,
      selected_account_name: "accounts/primary",
      account_selection_required: false,
      auto_selected: true,
      connection: {
        ...baseStatus,
        connected: true,
        status: "LOCATION_SELECTION_REQUIRED",
        selection_required: true,
        google_business_account: { name: "accounts/primary", selected: true },
      },
    });
    getLocations.mockResolvedValue({
      account_name: "accounts/primary",
      locations: [
        {
          id: "accounts/primary/locations/main",
          name: "accounts/primary/locations/main",
          title: "Main Street Salon",
          store_code: "MAIN",
          address: "12 Main St",
          phone: null,
          website_uri: null,
        },
      ],
      count: 1,
      selected_location_id: null,
      location_selection_required: true,
      connection: {
        ...baseStatus,
        connected: true,
        status: "LOCATION_SELECTION_REQUIRED",
        selection_required: true,
      },
    });
    render(
      <OwnerGoogleBusinessCard token="tok" businessId="biz" locationId="loc" />,
    );
    expect(await screen.findByText(/✓ Connected/i)).toBeInTheDocument();
    expect(
      await screen.findByRole("combobox", { name: /Google Business location/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /Map this location/i }),
    ).toBeInTheDocument();
  });

  it("maps selected location and shows sync when mapped", async () => {
    const user = userEvent.setup();
    getStatus.mockResolvedValue({
      ...baseStatus,
      connected: true,
      status: "LOCATION_SELECTION_REQUIRED",
      selection_required: true,
      google_account: { id: "acct", email: "owner@example.com" },
    });
    getAccounts.mockResolvedValue({
      accounts: [
        {
          name: "accounts/primary",
          display_name: "Primary GBP",
          account_type: "PERSONAL",
        },
      ],
      count: 1,
      selected_account_name: "accounts/primary",
      account_selection_required: false,
      auto_selected: true,
      connection: {
        ...baseStatus,
        connected: true,
        status: "LOCATION_SELECTION_REQUIRED",
        google_business_account: { name: "accounts/primary", selected: true },
      },
    });
    getLocations.mockResolvedValue({
      account_name: "accounts/primary",
      locations: [
        {
          id: "accounts/primary/locations/main",
          name: "accounts/primary/locations/main",
          title: "Main Street Salon",
          store_code: null,
          address: "12 Main St",
          phone: null,
          website_uri: null,
        },
      ],
      count: 1,
      selected_location_id: "accounts/primary/locations/main",
      location_selection_required: true,
      connection: {
        ...baseStatus,
        connected: true,
        status: "LOCATION_SELECTION_REQUIRED",
      },
    });
    selectLocation.mockResolvedValue({
      selected_location: {
        id: "accounts/primary/locations/main",
        name: "accounts/primary/locations/main",
        title: "Main Street Salon",
        store_code: null,
        address: "12 Main St",
        phone: null,
        website_uri: null,
      },
      connection: {
        ...baseStatus,
        connected: true,
        status: "CONNECTED",
        location_selected: true,
        mapped: true,
        website_sync_available: true,
        google_location: {
          id: "accounts/primary/locations/main",
          display_name: "Main Street Salon",
          selected: true,
        },
        google_location_display_name: "Main Street Salon",
      },
    });
    render(
      <OwnerGoogleBusinessCard token="tok" businessId="biz" locationId="loc" />,
    );
    await screen.findByRole("button", { name: /Map this location/i });
    await user.click(screen.getByRole("button", { name: /Map this location/i }));
    await waitFor(() => {
      expect(selectLocation).toHaveBeenCalled();
    });
    expect(await screen.findByText(/Mapped profile/i)).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /Sync Website & Booking URL/i }),
    ).toBeEnabled();
  });

  it("shows reauth CTA", async () => {
    getStatus.mockResolvedValue({
      ...baseStatus,
      status: "REAUTH_REQUIRED",
      connected: false,
    });
    render(
      <OwnerGoogleBusinessCard token="tok" businessId="biz" locationId="loc" />,
    );
    expect(await screen.findByText(/Authorization expired/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Reconnect Google/i })).toBeInTheDocument();
  });

  it("navigates to authorization URL when provided", async () => {
    const user = userEvent.setup();
    getStatus.mockResolvedValue({ ...baseStatus });
    startConnect.mockResolvedValue({
      authorization_url: "https://accounts.google.com/o/oauth2/v2/auth?x=1",
    });
    const assign = vi.fn();
    const locationStub = {
      _href: "",
      get href() {
        return this._href;
      },
      set href(v: string) {
        this._href = v;
        assign(v);
      },
    };
    Object.defineProperty(window, "location", {
      configurable: true,
      value: locationStub,
    });
    render(
      <OwnerGoogleBusinessCard token="tok" businessId="biz" locationId="loc" />,
    );
    await screen.findByText("Not connected");
    await user.click(screen.getByRole("button", { name: /Connect Google/i }));
    await waitFor(() => {
      expect(startConnect).toHaveBeenCalled();
      expect(assign).toHaveBeenCalledWith(
        "https://accounts.google.com/o/oauth2/v2/auth?x=1",
      );
    });
  });
});
