import { OwnerQuickCardClient } from "@/app/owner/quickcard/OwnerQuickCardClient";
import { ApiError } from "@/lib/api/client";
import { apiRequest } from "@/lib/api/client";
import {
  getManagedQuickCard,
  getQuickCardAnalytics,
} from "@/lib/api/managedQuickCard";
import { presetAnalyticsRange } from "@/lib/quickcard/analyticsRange";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useSearchParams: () => ({ get: () => "" }),
}));

vi.mock("@/lib/api/client", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api/client")>(
    "@/lib/api/client",
  );
  return { ...actual, apiRequest: vi.fn() };
});

vi.mock("@/lib/api/managedQuickCard", () => ({
  getQuickCardAnalytics: vi.fn(),
  getManagedQuickCard: vi.fn(),
  createManagedQuickCard: vi.fn(),
  updateManagedQuickCard: vi.fn(),
  publishManagedQuickCard: vi.fn(),
  unpublishManagedQuickCard: vi.fn(),
  managedQuickCardQrUrl: () => "/qr",
}));

const card = {
  id: "card-1",
  location_id: "loc-1",
  slug: "ksn-salon",
  headline: "Book",
  description: "",
  logo_url: "",
  cover_image_url: "",
  phone: "",
  whatsapp: "",
  website_url: "",
  google_maps_url: "",
  instagram_url: "",
  facebook_url: "",
  is_published: true,
  published_at: null,
  public_path: "/q/ksn-salon",
  public_url: "https://example.com/q/ksn-salon",
  booking_url: "/book/downtown",
  location: {
    id: "loc-1",
    name: "Downtown",
    slug: "downtown",
    timezone: "Asia/Kolkata",
  },
};

const analytics = {
  views: 500,
  cta_clicks: {
    book: 100,
    whatsapp: 35,
    call: 12,
    directions: 20,
    review: 8,
    share: 15,
  },
  bookings: 8,
  booking_conversion_rate: 8,
  date_from: "2026-09-01",
  date_to: "2026-09-29",
};

function mockShell() {
  vi.mocked(apiRequest).mockImplementation(async (path: string) => {
    if (path === "/api/v1/businesses/") {
      return { results: [{ id: "biz-1", name: "KSN Salon" }] };
    }
    if (path.includes("/locations/")) {
      return { results: [{ id: "loc-1", name: "Downtown", slug: "downtown" }] };
    }
    return {};
  });
}

describe("Owner QuickCard analytics", () => {
  beforeEach(() => {
    localStorage.setItem("ba_access_token", "token");
    mockShell();
    vi.mocked(getManagedQuickCard).mockResolvedValue(card);
    vi.mocked(getQuickCardAnalytics).mockResolvedValue(analytics);
  });

  afterEach(() => {
    cleanup();
    localStorage.clear();
    vi.clearAllMocks();
  });

  it("shows booking conversion and the existing KPI counts", async () => {
    render(<OwnerQuickCardClient />);
    expect(await screen.findByText("8.0%")).toBeInTheDocument();
    expect(screen.getByText("Booking Conversion")).toBeInTheDocument();
    expect(screen.getByText("Book Now → Booking")).toBeInTheDocument();
    expect(screen.getByText("500")).toBeInTheDocument();
    expect(screen.getByText("100")).toBeInTheDocument();
    expect(screen.getByText("35")).toBeInTheDocument();
    expect(screen.getByText("Bookings")).toBeInTheDocument();
    expect(screen.queryByLabelText("Analytics location")).not.toBeInTheDocument();
  });

  it("shows an em dash when conversion is undefined", async () => {
    vi.mocked(getQuickCardAnalytics).mockResolvedValue({
      ...analytics,
      cta_clicks: { ...analytics.cta_clicks, book: 0 },
      bookings: 0,
      booking_conversion_rate: null,
    });
    render(<OwnerQuickCardClient />);
    expect(await screen.findByText("Booking Conversion")).toBeInTheDocument();
    expect(screen.getByText("—")).toBeInTheDocument();
    expect(screen.queryByText("0%")).not.toBeInTheDocument();
    expect(screen.queryByText("0.0%")).not.toBeInTheDocument();
  });

  it("keeps the analytics block hidden until the response arrives", async () => {
    const resolvers: Array<(value: typeof analytics) => void> = [];
    vi.mocked(getQuickCardAnalytics).mockImplementation(
      () =>
        new Promise((resolve) => {
          resolvers.push(resolve);
        }),
    );
    render(<OwnerQuickCardClient />);
    await waitFor(() => expect(resolvers.length).toBeGreaterThan(0));
    expect(screen.getByText("Loading analytics…")).toBeInTheDocument();
    expect(screen.queryByText("Booking Conversion")).not.toBeInTheDocument();
    resolvers[resolvers.length - 1](analytics);
    expect(await screen.findByText("8.0%")).toBeInTheDocument();
  });

  it("shows the empty QuickCard state when the card is missing", async () => {
    vi.mocked(getManagedQuickCard).mockRejectedValue(new ApiError(404, {}));
    render(<OwnerQuickCardClient />);
    expect(await screen.findByRole("button", { name: "Create QuickCard" })).toBeInTheDocument();
  });

  it("shows the existing error message when the card request fails", async () => {
    vi.mocked(getManagedQuickCard).mockRejectedValue(new ApiError(500, {}));
    render(<OwnerQuickCardClient />);
    expect(
      await screen.findByText("Our servers are having trouble. Please try again shortly."),
    ).toBeInTheDocument();
  });

  it("keeps the date range when analytics fails", async () => {
    vi.mocked(getQuickCardAnalytics).mockRejectedValue(new Error("down"));
    render(<OwnerQuickCardClient />);
    expect(await screen.findByText("Something went wrong. Please try again.")).toBeInTheDocument();
    expect(screen.getByLabelText("Date range")).toHaveValue("30");
    expect(screen.queryByText("Booking Conversion")).not.toBeInTheDocument();
  });

  it("filters analytics by location when the business has more than one", async () => {
    const user = userEvent.setup();
    vi.mocked(apiRequest).mockImplementation(async (path: string) => {
      if (path === "/api/v1/businesses/") {
        return { results: [{ id: "biz-1", name: "KSN Salon" }] };
      }
      if (path.includes("/locations/")) {
        return {
          results: [
            { id: "loc-1", name: "Downtown", slug: "downtown", is_active: true },
            { id: "loc-2", name: "Uptown", slug: "uptown", is_active: true },
          ],
        };
      }
      return {};
    });
    vi.mocked(getQuickCardAnalytics).mockImplementation(async (_business, _token, query) => {
      if (query?.locationId === "loc-2") {
        return { ...analytics, views: 9, bookings: 1, booking_conversion_rate: 10 };
      }
      return analytics;
    });
    render(<OwnerQuickCardClient />);
    const filter = await screen.findByLabelText("Analytics location");
    const range = screen.getByLabelText("Date range");
    expect(filter).toHaveValue("");
    expect(range).toHaveValue("30");
    const last30 = presetAnalyticsRange(30);
    await waitFor(() =>
      expect(getQuickCardAnalytics).toHaveBeenCalledWith("biz-1", "token", {
        locationId: undefined,
        dateFrom: last30.dateFrom,
        dateTo: last30.dateTo,
      }),
    );
    expect(await screen.findByText("8.0%")).toBeInTheDocument();
    await user.selectOptions(filter, "loc-2");
    await waitFor(() =>
      expect(getQuickCardAnalytics).toHaveBeenCalledWith("biz-1", "token", {
        locationId: "loc-2",
        dateFrom: last30.dateFrom,
        dateTo: last30.dateTo,
      }),
    );
    expect(await screen.findByText("9")).toBeInTheDocument();
    expect(screen.getByText("10.0%")).toBeInTheDocument();
    await user.selectOptions(range, "7");
    const last7 = presetAnalyticsRange(7);
    await waitFor(() =>
      expect(getQuickCardAnalytics).toHaveBeenCalledWith("biz-1", "token", {
        locationId: "loc-2",
        dateFrom: last7.dateFrom,
        dateTo: last7.dateTo,
      }),
    );
    expect(filter).toHaveValue("loc-2");
    await user.selectOptions(range, "90");
    const last90 = presetAnalyticsRange(90);
    await waitFor(() =>
      expect(getQuickCardAnalytics).toHaveBeenCalledWith("biz-1", "token", {
        locationId: "loc-2",
        dateFrom: last90.dateFrom,
        dateTo: last90.dateTo,
      }),
    );
    await user.selectOptions(filter, "");
    await waitFor(() =>
      expect(getQuickCardAnalytics).toHaveBeenCalledWith("biz-1", "token", {
        locationId: undefined,
        dateFrom: last90.dateFrom,
        dateTo: last90.dateTo,
      }),
    );
  });

  it("sends a custom range only when the dates are valid", async () => {
    const user = userEvent.setup();
    render(<OwnerQuickCardClient />);
    await screen.findByText("8.0%");
    const callsBeforeCustom = vi.mocked(getQuickCardAnalytics).mock.calls.length;
    await user.selectOptions(screen.getByLabelText("Date range"), "custom");
    expect(screen.getByText("Choose a start date.")).toBeInTheDocument();
    expect(vi.mocked(getQuickCardAnalytics).mock.calls.length).toBe(callsBeforeCustom);
    fireEvent.change(screen.getByLabelText("End date"), { target: { value: "2026-09-10" } });
    expect(screen.getByText("Choose a start date.")).toBeInTheDocument();
    expect(vi.mocked(getQuickCardAnalytics).mock.calls.length).toBe(callsBeforeCustom);
    fireEvent.change(screen.getByLabelText("Start date"), { target: { value: "" } });
    fireEvent.change(screen.getByLabelText("End date"), { target: { value: "" } });
    fireEvent.change(screen.getByLabelText("Start date"), { target: { value: "2026-09-12" } });
    expect(screen.getByText("Choose an end date.")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("End date"), { target: { value: "2026-09-01" } });
    expect(screen.getByText("Start date must be on or before the end date.")).toBeInTheDocument();
    expect(vi.mocked(getQuickCardAnalytics).mock.calls.length).toBe(callsBeforeCustom);
    fireEvent.change(screen.getByLabelText("End date"), { target: { value: "2026-09-20" } });
    await waitFor(() =>
      expect(getQuickCardAnalytics).toHaveBeenCalledWith("biz-1", "token", {
        locationId: undefined,
        dateFrom: "2026-09-12",
        dateTo: "2026-09-20",
      }),
    );
  });

  it("shows the latest analytics response after a quick filter change", async () => {
    const user = userEvent.setup();
    const resolvers: Array<(value: typeof analytics) => void> = [];
    vi.mocked(getQuickCardAnalytics).mockImplementation(
      () =>
        new Promise((resolve) => {
          resolvers.push(resolve);
        }),
    );
    render(<OwnerQuickCardClient />);
    await waitFor(() => expect(resolvers.length).toBeGreaterThan(0));
    await user.selectOptions(screen.getByLabelText("Date range"), "7");
    await waitFor(() => expect(resolvers.length).toBeGreaterThan(1));
    resolvers[0]({ ...analytics, views: 1 });
    resolvers[resolvers.length - 1]({ ...analytics, views: 7 });
    expect(await screen.findByText("7")).toBeInTheDocument();
    expect(screen.queryByText(/^1$/)).not.toBeInTheDocument();
  });

  it("shows zeros and an em dash when the selected range has no Book Now clicks", async () => {
    vi.mocked(getQuickCardAnalytics).mockResolvedValue({
      views: 0,
      cta_clicks: {
        book: 0,
        whatsapp: 0,
        call: 0,
        directions: 0,
        review: 0,
        share: 0,
      },
      bookings: 0,
      booking_conversion_rate: null,
      date_from: "2026-09-01",
      date_to: "2026-09-30",
    });
    render(<OwnerQuickCardClient />);
    expect(await screen.findByText(/Showing data for: Sep 1, 2026 – Sep 30, 2026/)).toBeInTheDocument();
    expect(screen.getAllByText("0").length).toBeGreaterThan(0);
    expect(screen.getByText("—")).toBeInTheDocument();
    expect(screen.queryByText("0%")).not.toBeInTheDocument();
  });
});
