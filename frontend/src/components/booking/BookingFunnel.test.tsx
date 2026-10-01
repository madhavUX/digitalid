import { BookingFunnel } from "@/components/booking/BookingFunnel";
import { ApiError } from "@/lib/api/client";
import type { PublicLocation, PublicService, PublicStaff } from "@/lib/api/types";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const location: PublicLocation = {
  id: "loc-1",
  slug: "downtown",
  name: "Downtown",
  timezone: "Asia/Kolkata",
  phone: "+918012345678",
  email: "",
  address: {
    line1: "12 MG Road",
    line2: "",
    city: "Bengaluru",
    state: "KA",
    postal_code: "",
    country: "IN",
  },
  business: {
    name: "Ada Salon",
    slug: "ada-salon",
    vertical: "SALON",
    description: "",
    logo_url: "",
  },
};

const services: PublicService[] = [
  {
    id: "svc-1",
    slug: "haircut",
    name: "Haircut",
    description: "Classic cut",
    duration_minutes: 45,
    price: "499.00",
    currency: "INR",
    is_bookable_online: true,
    category: { slug: "hair", name: "Hair" },
  },
];

const staff: PublicStaff[] = [
  {
    id: "staff-1",
    display_name: "Priya",
    title: "Stylist",
    bio: "Cuts and color",
    photo_url: "",
    services: [
      {
        id: "svc-1",
        slug: "haircut",
        name: "Haircut",
        duration_minutes: 45,
        price: "499.00",
        currency: "INR",
      },
    ],
  },
];

const getPublicAvailability = vi.fn();
const createPublicAppointment = vi.fn();
const push = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
}));

vi.mock("@/lib/api/publicBooking", () => ({
  getPublicAvailability: (...args: unknown[]) => getPublicAvailability(...args),
  createPublicAppointment: (...args: unknown[]) =>
    createPublicAppointment(...args),
  createPublicBookingPlan: vi.fn(),
}));

async function advanceToConfirm(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole("button", { name: /Haircut/i }));
  await user.click(screen.getByRole("button", { name: /Any staff/i }));
  const slotButton = await screen.findByRole("button", { name: /10:00/i });
  await user.click(slotButton);
  await user.click(screen.getByRole("button", { name: /Continue/i }));
  // Booking type defaults to Book once
  await user.click(screen.getByRole("button", { name: /^Continue$/i }));
  await user.type(screen.getByLabelText(/Full name/i), "Rahul");
  await user.type(screen.getByLabelText(/Mobile number/i), "9876543210");
  await user.click(screen.getByRole("button", { name: /Review booking/i }));
}

describe("BookingFunnel", () => {
  afterEach(() => {
    cleanup();
  });

  beforeEach(() => {
    push.mockReset();
    getPublicAvailability.mockReset();
    createPublicAppointment.mockReset();
    getPublicAvailability.mockResolvedValue({
      location: { id: "loc-1", name: "Downtown", timezone: "Asia/Kolkata" },
      service: {
        id: "svc-1",
        name: "Haircut",
        duration_minutes: 45,
        price: "499.00",
        currency: "INR",
      },
      date: "2026-09-10",
      slot_grid_minutes: 15,
      slots: [
        {
          start: "2026-09-10T10:00:00+05:30",
          end: "2026-09-10T10:45:00+05:30",
          starts_at: "2026-09-10T04:30:00Z",
          ends_at: "2026-09-10T05:15:00Z",
          staff_id: null,
          staff_options: ["staff-1"],
        },
      ],
    });
  });

  it("loads location branding, selects service/staff/slot, and sends Idempotency-Key", async () => {
    const user = userEvent.setup();
    createPublicAppointment.mockResolvedValue({
      public_reference: "BK-TEST",
      status: "CONFIRMED",
      service: "Haircut",
      location: "Downtown",
      staff: "Priya",
      start: "2026-09-10T10:00:00+05:30",
      end: "2026-09-10T10:45:00+05:30",
      total: "499.00",
      currency: "INR",
      manage_token: "secure-manage-token",
    });

    render(
      <BookingFunnel
        location={location}
        locationSlug="downtown"
        initialServices={services}
        initialStaff={staff}
      />,
    );

    expect(screen.getByRole("heading", { name: "Ada Salon" })).toBeInTheDocument();
    await advanceToConfirm(user);

    expect(getPublicAvailability).toHaveBeenCalled();
    expect(getPublicAvailability.mock.calls[0][0]).toMatchObject({
      location_id: "loc-1",
      service_id: "svc-1",
      staff_id: null,
    });

    await user.click(screen.getByRole("button", { name: /Confirm booking/i }));

    await waitFor(() => {
      expect(createPublicAppointment).toHaveBeenCalled();
    });
    const [payload, key] = createPublicAppointment.mock.calls[0];
    expect(payload.customer.name).toBe("Rahul");
    expect(payload.customer.phone).toBe("9876543210");
    expect(key).toBeTruthy();
    expect(payload.attribution_source).toBeUndefined();
    await waitFor(() => {
      expect(push).toHaveBeenCalledWith(
        expect.stringContaining("/book/downtown/success?ref=BK-TEST"),
      );
      expect(push).toHaveBeenCalledWith(
        expect.stringContaining("manage=secure-manage-token"),
      );
    });
  });

  it("keeps QuickCard attribution through confirm", async () => {
    const user = userEvent.setup();
    createPublicAppointment.mockResolvedValue({
      public_reference: "BK-QC",
      status: "CONFIRMED",
      service: "Haircut",
      location: "Downtown",
      staff: "Priya",
      start: "2026-09-10T10:00:00+05:30",
      end: "2026-09-10T10:45:00+05:30",
      total: "499.00",
      currency: "INR",
      manage_token: "secure-manage-token",
    });
    render(
      <BookingFunnel
        location={location}
        locationSlug="downtown"
        initialServices={services}
        initialStaff={staff}
        attribution={{ source: "quickcard", ref: "ksn-salon" }}
      />,
    );
    await advanceToConfirm(user);
    await user.click(screen.getByRole("button", { name: /Confirm booking/i }));
    await waitFor(() => expect(createPublicAppointment).toHaveBeenCalled());
    expect(createPublicAppointment.mock.calls[0][0]).toMatchObject({
      attribution_source: "quickcard",
      attribution_ref: "ksn-salon",
    });
  });

  it("keeps retention attribution through confirm", async () => {
    const user = userEvent.setup();
    createPublicAppointment.mockResolvedValue({
      public_reference: "BK-RET",
      status: "CONFIRMED",
      service: "Haircut",
      location: "Downtown",
      staff: "Priya",
      start: "2026-09-10T10:00:00+05:30",
      end: "2026-09-10T10:45:00+05:30",
      total: "499.00",
      currency: "INR",
      manage_token: "secure-manage-token",
    });
    render(
      <BookingFunnel
        location={location}
        locationSlug="downtown"
        initialServices={services}
        initialStaff={staff}
        attribution={{ source: "retention", ref: "ret-opaque-ref" }}
      />,
    );
    await advanceToConfirm(user);
    await user.click(screen.getByRole("button", { name: /Confirm booking/i }));
    await waitFor(() => expect(createPublicAppointment).toHaveBeenCalled());
    expect(createPublicAppointment.mock.calls[0][0]).toMatchObject({
      attribution_source: "retention",
      attribution_ref: "ret-opaque-ref",
    });
  });

  it("prefills service and staff from Book Again query params", async () => {
    getPublicAvailability.mockResolvedValue({
      location: { id: "loc-1", name: "Downtown", timezone: "Asia/Kolkata" },
      service: {
        id: "svc-1",
        name: "Haircut",
        duration_minutes: 45,
        price: "499.00",
        currency: "INR",
      },
      date: "2026-09-15",
      slot_grid_minutes: 15,
      slots: [
        {
          start: "2026-09-15T10:00:00+05:30",
          end: "2026-09-15T10:45:00+05:30",
          starts_at: "2026-09-15T04:30:00Z",
          ends_at: "2026-09-15T05:15:00Z",
          staff_id: "staff-1",
        },
      ],
    });

    render(
      <BookingFunnel
        location={location}
        locationSlug="downtown"
        initialServices={services}
        initialStaff={staff}
        prefillServiceId="svc-1"
        prefillStaffId="staff-1"
      />,
    );

    await waitFor(() => {
      expect(screen.getByRole("heading", { name: /Date & time/i })).toBeInTheDocument();
    });
    await waitFor(() => {
      expect(getPublicAvailability).toHaveBeenCalledWith(
        expect.objectContaining({
          service_id: "svc-1",
          staff_id: "staff-1",
        }),
      );
    });
  });

  it("handles stale-slot 409 by returning to datetime with a friendly message", async () => {
    const user = userEvent.setup();
    createPublicAppointment.mockRejectedValue(
      new ApiError(409, {
        error: "slot taken",
        status_code: 409,
        code: "SLOT_UNAVAILABLE",
      }),
    );

    render(
      <BookingFunnel
        location={location}
        locationSlug="downtown"
        initialServices={services}
        initialStaff={staff}
      />,
    );

    await advanceToConfirm(user);
    await user.click(screen.getByRole("button", { name: /Confirm booking/i }));

    await waitFor(() => {
      expect(screen.getByText(/just booked/i)).toBeInTheDocument();
    });
    expect(screen.getByRole("heading", { name: /Pick a date/i })).toBeInTheDocument();
  });

  it("shows 429 message on throttle", async () => {
    const user = userEvent.setup();
    createPublicAppointment.mockRejectedValue(
      new ApiError(429, { error: "throttled", status_code: 429 }),
    );

    render(
      <BookingFunnel
        location={location}
        locationSlug="downtown"
        initialServices={services}
        initialStaff={staff}
      />,
    );

    await advanceToConfirm(user);
    await user.click(screen.getByRole("button", { name: /Confirm booking/i }));

    await waitFor(() => {
      expect(screen.getByText(/Too many requests/i)).toBeInTheDocument();
    });
  });

  it("offers Book regularly and shows frequency options", async () => {
    const user = userEvent.setup();
    render(
      <BookingFunnel
        location={location}
        locationSlug="downtown"
        initialServices={services}
        initialStaff={staff}
      />,
    );
    await user.click(screen.getByRole("button", { name: /Haircut/i }));
    await user.click(screen.getByRole("button", { name: /Any staff/i }));
    const slotButton = await screen.findByRole("button", { name: /10:00/i });
    await user.click(slotButton);
    await user.click(screen.getByRole("button", { name: /Continue/i }));
    expect(screen.getByTestId("book-regularly-option")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Book once/i })).toBeInTheDocument();
    await user.click(screen.getByTestId("book-regularly-option"));
    await user.click(screen.getByRole("button", { name: /^Continue$/i }));
    expect(screen.getByRole("button", { name: /Every month/i })).toBeInTheDocument();
  });
});
