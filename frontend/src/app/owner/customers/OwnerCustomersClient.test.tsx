import { OwnerCustomersClient } from "@/app/owner/customers/OwnerCustomersClient";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const listBusinesses = vi.fn();
const listCustomers = vi.fn();
const getRetentionSettings = vi.fn();
const updateRetentionSettings = vi.fn();
const getOwnerMe = vi.fn();
const getCustomerRetentionSummary = vi.fn();

vi.mock("next/navigation", () => ({
  usePathname: () => "/owner/customers",
  useRouter: () => ({ push: vi.fn() }),
}));

vi.mock("@/lib/api/ownerApi", () => ({
  listBusinesses: (...args: unknown[]) => listBusinesses(...args),
  listCustomers: (...args: unknown[]) => listCustomers(...args),
  getRetentionSettings: (...args: unknown[]) => getRetentionSettings(...args),
  updateRetentionSettings: (...args: unknown[]) => updateRetentionSettings(...args),
  getOwnerMe: (...args: unknown[]) => getOwnerMe(...args),
  getCustomerRetentionSummary: (...args: unknown[]) =>
    getCustomerRetentionSummary(...args),
}));

describe("OwnerCustomersClient retention settings", () => {
  beforeEach(() => {
    window.localStorage.setItem("ba_access_token", "test-token");
    listBusinesses.mockReset();
    listCustomers.mockReset();
    getRetentionSettings.mockReset();
    updateRetentionSettings.mockReset();
    getOwnerMe.mockReset();
    getCustomerRetentionSummary.mockReset();

    listBusinesses.mockResolvedValue({
      results: [{ id: "biz-1", name: "KSN Salon", vertical: "SALON" }],
    });
    listCustomers.mockResolvedValue({
      results: [
        {
          id: "c1",
          first_name: "Ananya",
          last_name: "Sharma",
          full_name: "Ananya Sharma",
          phone: "+919800000001",
          email: "",
          total_visits: 0,
          first_visit_at: null,
          last_visit_at: null,
        },
      ],
    });
    getRetentionSettings.mockResolvedValue({
      return_after_days: 30,
      inactive_after_days: 90,
      due_message_delay_hours: 24,
      enabled: true,
      updated_at: "2026-01-01T00:00:00Z",
    });
    getCustomerRetentionSummary.mockResolvedValue({
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
    });
  });

  it("shows retention settings and lets owners edit", async () => {
    const user = userEvent.setup();
    getOwnerMe.mockResolvedValue({ membership: { role: "OWNER", is_active: true } });
    updateRetentionSettings.mockResolvedValue({
      return_after_days: 21,
      inactive_after_days: 60,
      due_message_delay_hours: 12,
      enabled: false,
      updated_at: "2026-01-02T00:00:00Z",
    });

    render(<OwnerCustomersClient />);
    expect(await screen.findByText("Retention thresholds")).toBeInTheDocument();
    const returnInput = await screen.findByLabelText(/Return after/i);
    expect(returnInput).toHaveValue(30);
    await user.click(returnInput);
    await user.keyboard("{Control>}a{/Control}{Backspace}21");
    const inactiveInput = screen.getByLabelText(/Inactive after/i);
    await user.click(inactiveInput);
    await user.keyboard("{Control>}a{/Control}{Backspace}60");
    const delayInput = screen.getByLabelText(/Due-for-return delay/i);
    await user.click(delayInput);
    await user.keyboard("{Control>}a{/Control}{Backspace}12");
    await user.selectOptions(screen.getByLabelText(/Retention automation/i), "off");
    await user.click(screen.getByRole("button", { name: /Save thresholds/i }));
    await waitFor(() => {
      expect(updateRetentionSettings).toHaveBeenCalledWith(
        "biz-1",
        "test-token",
        {
          return_after_days: 21,
          inactive_after_days: 60,
          due_message_delay_hours: 12,
          enabled: false,
        },
      );
    });
  });

  it("does not let managers edit thresholds", async () => {
    getOwnerMe.mockResolvedValue({ membership: { role: "MANAGER", is_active: true } });
    render(<OwnerCustomersClient />);
    expect(await screen.findByText(/Only owners can edit thresholds/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Save thresholds/i })).not.toBeInTheDocument();
    expect(await screen.findByLabelText(/Return after/i)).toBeDisabled();
    expect(screen.getByLabelText(/Due-for-return delay/i)).toBeDisabled();
    expect(screen.getByLabelText(/Retention automation/i)).toBeDisabled();
  });

  it("filters customers by segment", async () => {
    const user = userEvent.setup();
    getOwnerMe.mockResolvedValue({ membership: { role: "OWNER", is_active: true } });
    render(<OwnerCustomersClient />);
    await screen.findByText("Ananya Sharma");
    await user.selectOptions(screen.getByLabelText(/^Segment$/i), "DUE_FOR_RETURN");
    await waitFor(() => {
      expect(listCustomers).toHaveBeenCalledWith(
        "biz-1",
        "test-token",
        expect.objectContaining({ segment: "DUE_FOR_RETURN" }),
      );
    });
  });
});
