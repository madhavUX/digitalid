import { ManageBookingClient } from "@/components/booking/ManageBookingClient";
import { ApiError } from "@/lib/api/client";
import type { ManagedBooking } from "@/lib/api/types";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const getManagedBooking = vi.fn();
const cancelManagedBooking = vi.fn();

vi.mock("next/navigation", () => ({
  useParams: () => ({ token: "tok-abc" }),
}));

vi.mock("@/lib/api/publicBooking", () => ({
  getManagedBooking: (...args: unknown[]) => getManagedBooking(...args),
  cancelManagedBooking: (...args: unknown[]) => cancelManagedBooking(...args),
}));

const confirmedBooking: ManagedBooking = {
  public_reference: "BA-ABC123",
  status: "CONFIRMED",
  location: { name: "Example Salon", slug: "example-salon" },
  service: { name: "Haircut", duration_minutes: 30 },
  staff: { name: "Rahul" },
  starts_at: "2026-09-10T10:00:00+05:30",
  ends_at: "2026-09-10T10:30:00+05:30",
  customer: { name: "Customer" },
  can_cancel: true,
};

describe("ManageBookingClient", () => {
  afterEach(() => {
    cleanup();
  });

  beforeEach(() => {
    getManagedBooking.mockReset();
    cancelManagedBooking.mockReset();
  });

  it("shows a loading state then the booking details", async () => {
    let resolveBooking!: (value: ManagedBooking) => void;
    getManagedBooking.mockReturnValue(
      new Promise<ManagedBooking>((resolve) => {
        resolveBooking = resolve;
      }),
    );

    render(<ManageBookingClient />);
    expect(screen.getByText(/Loading your booking/i)).toBeInTheDocument();

    resolveBooking(confirmedBooking);
    expect(await screen.findByText("Example Salon")).toBeInTheDocument();
    expect(screen.getByText(/Haircut/)).toBeInTheDocument();
    expect(screen.getByText("BA-ABC123")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /Cancel booking/i }),
    ).toBeInTheDocument();
  });

  it("shows invalid state on 404", async () => {
    getManagedBooking.mockRejectedValue(
      new ApiError(404, {
        error: "This booking link is invalid or has expired.",
        status_code: 404,
        code: "BOOKING_NOT_FOUND",
      }),
    );
    render(<ManageBookingClient />);
    expect(
      await screen.findByText(/This booking link is invalid or has expired/i),
    ).toBeInTheDocument();
  });

  it("asks for confirmation then cancels successfully", async () => {
    const user = userEvent.setup();
    getManagedBooking.mockResolvedValue(confirmedBooking);
    cancelManagedBooking.mockResolvedValue({
      public_reference: "BA-ABC123",
      status: "CANCELLED",
      message: "Your booking has been cancelled.",
    });

    render(<ManageBookingClient />);
    await screen.findByText("Example Salon");
    await user.click(screen.getByRole("button", { name: /Cancel booking/i }));
    expect(
      screen.getByText(/Are you sure you want to cancel this booking/i),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /^Cancel booking$/i }));

    await waitFor(() => {
      expect(cancelManagedBooking).toHaveBeenCalledWith("tok-abc");
    });
    expect(
      await screen.findByRole("heading", { name: /Booking cancelled/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Your booking has been cancelled."),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Book again/i })).toHaveAttribute(
      "href",
      "/book/example-salon",
    );
  });

  it("shows cancelled state without cancel button", async () => {
    getManagedBooking.mockResolvedValue({
      ...confirmedBooking,
      status: "CANCELLED",
      can_cancel: false,
    });
    render(<ManageBookingClient />);
    expect(
      await screen.findByRole("heading", { name: /Booking cancelled/i }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /Cancel booking/i }),
    ).not.toBeInTheDocument();
  });

  it("hides cancel for completed appointments", async () => {
    getManagedBooking.mockResolvedValue({
      ...confirmedBooking,
      status: "COMPLETED",
      can_cancel: false,
    });
    render(<ManageBookingClient />);
    expect(await screen.findByText("Example Salon")).toBeInTheDocument();
    expect(
      screen.getByText(/This booking can no longer be cancelled online/i),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /Cancel booking/i }),
    ).not.toBeInTheDocument();
  });

  it("shows friendly message on 429", async () => {
    getManagedBooking.mockRejectedValue(
      new ApiError(429, { error: "slow down", status_code: 429 }),
    );
    render(<ManageBookingClient />);
    expect(
      await screen.findByText(/Too many requests/i),
    ).toBeInTheDocument();
  });

  it("shows friendly message on 5xx", async () => {
    getManagedBooking.mockRejectedValue(
      new ApiError(500, { error: "boom", status_code: 500 }),
    );
    render(<ManageBookingClient />);
    expect(
      await screen.findByText(/servers are having trouble/i),
    ).toBeInTheDocument();
  });

  it("shows friendly message on network failure", async () => {
    getManagedBooking.mockRejectedValue(new Error("network"));
    render(<ManageBookingClient />);
    expect(
      await screen.findByRole("heading", { name: /Something went wrong/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Please try again/i),
    ).toBeInTheDocument();
  });
});
