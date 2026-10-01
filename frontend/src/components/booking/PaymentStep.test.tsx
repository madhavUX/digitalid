import { PaymentFailure, PaymentStatus, PaymentSuccess } from "@/components/booking/PaymentStep";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api/publicBooking", () => ({
  createPublicPaymentOrder: vi.fn(),
  verifyPublicPayment: vi.fn(),
}));

describe("PaymentStep statuses", () => {
  it("renders status, failure, and success messages", () => {
    const { rerender } = render(<PaymentStatus message="Verifying payment…" />);
    expect(screen.getByRole("status")).toHaveTextContent("Verifying payment…");
    rerender(<PaymentFailure message="Checkout closed" />);
    expect(screen.getByRole("alert")).toHaveTextContent("Checkout closed");
    rerender(<PaymentSuccess message="Payment confirmed" />);
    expect(screen.getByRole("status")).toHaveTextContent("Payment confirmed");
  });
});
