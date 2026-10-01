import { CustomerRetentionProfile } from "@/components/owner/CustomerRetentionProfile";
import type { RetentionSummary } from "@/lib/api/types";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

const emptySummary: RetentionSummary = {
  customer_id: "c1",
  total_visits: 0,
  completed_appointments: 0,
  first_visit_at: null,
  last_visit_at: null,
  days_since_last_visit: null,
  average_days_between_visits: null,
  segment: "NO_VISITS",
  return_after_days: 30,
  inactive_after_days: 90,
  automation: null,
  visits: [],
  service_history: [],
  staff_history: [],
  location_history: [],
};

const populated: RetentionSummary = {
  customer_id: "c1",
  total_visits: 2,
  completed_appointments: 2,
  first_visit_at: "2026-01-01T10:00:00Z",
  last_visit_at: "2026-01-31T10:00:00Z",
  days_since_last_visit: 12,
  average_days_between_visits: 30,
  segment: "RETURNING",
  return_after_days: 30,
  inactive_after_days: 90,
  automation: { status: "PENDING", scheduled_for: "2026-02-01T00:00:00Z", sent_at: null, skip_reason: null },
  visits: [
    {
      appointment_reference: "ref-2",
      completed_at: "2026-01-31T10:00:00Z",
      location: "Banjara Hills",
      staff: "Priya",
      service: "Haircut",
      price_snapshot: "499.00",
      currency: "INR",
    },
  ],
  service_history: [
    {
      service_name: "Haircut",
      visit_count: 2,
      last_visit_at: "2026-01-31T10:00:00Z",
    },
  ],
  staff_history: [
    {
      staff_name: "Priya",
      visit_count: 2,
      last_visit_at: "2026-01-31T10:00:00Z",
    },
  ],
  location_history: [
    {
      location_name: "Banjara Hills",
      visit_count: 2,
      last_visit_at: "2026-01-31T10:00:00Z",
    },
  ],
};

describe("CustomerRetentionProfile", () => {
  it("shows loading state", () => {
    render(<CustomerRetentionProfile summary={null} loading />);
    expect(screen.getByText(/Loading visit history/i)).toBeInTheDocument();
  });

  it("shows API error state", () => {
    render(
      <CustomerRetentionProfile summary={null} error="Could not load history." />,
    );
    expect(screen.getByRole("alert")).toHaveTextContent("Could not load history.");
  });

  it("shows empty history placeholders and No Visits Yet", () => {
    render(<CustomerRetentionProfile summary={emptySummary} />);
    expect(screen.getByText("Total visits").closest(".owner-metric")).toHaveTextContent(
      "0",
    );
    expect(screen.getAllByText("—").length).toBeGreaterThanOrEqual(4);
    expect(screen.getByText("No Visits Yet")).toBeInTheDocument();
    expect(screen.getByText("No completed visits yet.")).toBeInTheDocument();
    expect(screen.getAllByText("No visit history yet.")).toHaveLength(3);
  });

  it("renders visit history and returning segment", () => {
    render(
      <CustomerRetentionProfile summary={populated} customerName="Ananya Sharma" />,
    );
    expect(screen.getByText(/Visit history · Ananya Sharma/i)).toBeInTheDocument();
    expect(screen.getAllByText("Haircut").length).toBeGreaterThan(0);
    expect(screen.getByText(/ref-2/i)).toBeInTheDocument();
    expect(screen.getByText("Returning")).toBeInTheDocument();
    expect(screen.getByText(/Automation: Scheduled/i)).toBeInTheDocument();
    expect(screen.getByText("12")).toBeInTheDocument();
  });

  it("shows dash for undefined average days between visits", () => {
    render(
      <CustomerRetentionProfile
        summary={{
          ...populated,
          average_days_between_visits: null,
          total_visits: 1,
          segment: "NEW",
        }}
      />,
    );
    const avg = screen.getByText("Avg days between visits").closest(".owner-metric");
    expect(avg).toHaveTextContent("—");
    expect(screen.getByText("New")).toBeInTheDocument();
  });

  it("shows Due for Return explanation", () => {
    render(
      <CustomerRetentionProfile
        summary={{
          ...populated,
          segment: "DUE_FOR_RETURN",
          days_since_last_visit: 42,
          return_after_days: 30,
        }}
      />,
    );
    expect(screen.getByText("Due for Return")).toBeInTheDocument();
    expect(
      screen.getByText(/has not visited in 42 days/i),
    ).toBeInTheDocument();
  });

  it("shows Inactive explanation", () => {
    render(
      <CustomerRetentionProfile
        summary={{
          ...populated,
          segment: "INACTIVE",
          days_since_last_visit: 95,
          inactive_after_days: 90,
        }}
      />,
    );
    expect(screen.getByText("Inactive")).toBeInTheDocument();
    expect(
      screen.getByText(/inactive threshold is 90 days/i),
    ).toBeInTheDocument();
  });

  it("shows automation status without internal ids", () => {
    render(
      <CustomerRetentionProfile
        summary={{
          ...populated,
          segment: "DUE_FOR_RETURN",
          automation: {
            status: "SENT",
            scheduled_for: "2026-02-01T00:00:00Z",
            sent_at: "2026-02-01T01:00:00Z",
            skip_reason: null,
          },
        }}
      />,
    );
    expect(screen.getByText(/Automation: Sent/i)).toBeInTheDocument();
    expect(screen.queryByText(/idempotency/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/wamid/i)).not.toBeInTheDocument();
  });
});
