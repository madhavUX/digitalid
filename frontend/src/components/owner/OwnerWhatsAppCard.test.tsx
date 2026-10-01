import { OwnerWhatsAppCard } from "@/components/owner/OwnerWhatsAppCard";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const getStatus = vi.fn();
const connect = vi.fn();
const disconnect = vi.fn();
const listTemplates = vi.fn();
const createTemplate = vi.fn();
const deleteTemplate = vi.fn();
const syncTemplates = vi.fn();
const listInbound = vi.fn();

vi.mock("@/lib/api/ownerApi", () => ({
  getWhatsAppConnection: (...args: unknown[]) => getStatus(...args),
  connectWhatsApp: (...args: unknown[]) => connect(...args),
  disconnectWhatsApp: (...args: unknown[]) => disconnect(...args),
  listWhatsAppTemplates: (...args: unknown[]) => listTemplates(...args),
  createWhatsAppTemplate: (...args: unknown[]) => createTemplate(...args),
  deleteWhatsAppTemplate: (...args: unknown[]) => deleteTemplate(...args),
  syncWhatsAppTemplates: (...args: unknown[]) => syncTemplates(...args),
  listWhatsAppInboundMessages: (...args: unknown[]) => listInbound(...args),
}));

const disconnected = {
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
  provider: "mock",
  connect_available: true,
};

describe("OwnerWhatsAppCard", () => {
  beforeEach(() => {
    getStatus.mockReset();
    connect.mockReset();
    disconnect.mockReset();
    listTemplates.mockReset();
    createTemplate.mockReset();
    deleteTemplate.mockReset();
    syncTemplates.mockReset();
    listInbound.mockReset();
    listInbound.mockResolvedValue({ count: 0, results: [] });
    listTemplates.mockResolvedValue({ results: [] });
  });

  it("shows disconnected and connects without echoing the token", async () => {
    const user = userEvent.setup();
    getStatus.mockResolvedValue(disconnected);
    connect.mockResolvedValue({
      ...disconnected,
      connected: true,
      status: "CONNECTED",
      display_phone_number: "+919876543210",
      verified_name: "Salon",
    });
    render(<OwnerWhatsAppCard token="tok" businessId="biz" />);
    expect(await screen.findByText("Disconnected")).toBeInTheDocument();
    await user.type(screen.getByLabelText(/Access token/i), "secret-token");
    await user.type(screen.getByLabelText(/Phone number ID/i), "123");
    await user.type(screen.getByLabelText(/Business account ID/i), "456");
    await user.click(screen.getByRole("button", { name: /Connect WhatsApp/i }));
    await waitFor(() => {
      expect(connect).toHaveBeenCalledWith(
        "biz",
        "tok",
        expect.objectContaining({ access_token: "secret-token" }),
      );
    });
    expect(screen.queryByDisplayValue("secret-token")).not.toBeInTheDocument();
  });

  it("shows connected templates and disconnect", async () => {
    const user = userEvent.setup();
    getStatus.mockResolvedValue({
      ...disconnected,
      connected: true,
      status: "CONNECTED",
    });
    listTemplates.mockResolvedValue({
      results: [
        {
          id: "t1",
          name: "booking_confirmation",
          language: "en",
          category: "CONFIRMATION",
          status: "DRAFT",
          body: "Hi",
          variables: [],
        },
      ],
    });
    disconnect.mockResolvedValue(disconnected);
    render(<OwnerWhatsAppCard token="tok" businessId="biz" />);
    expect(await screen.findByText("Connected")).toBeInTheDocument();
    expect(screen.getByText(/24-hour reminder: Not configured/)).toBeInTheDocument();
    expect(await screen.findByText(/booking_confirmation/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /Disconnect/i }));
    await waitFor(() => expect(disconnect).toHaveBeenCalled());
  });

  it("shows inbound history without a reply action", async () => {
    listInbound.mockResolvedValue({
      count: 1,
      results: [
        {
          id: "in1",
          customer_name: null,
          phone_number: "+91******0001",
          message_type: "TEXT",
          text: "Hi, can I change my appointment?",
          provider_timestamp: "2026-09-29T05:02:00Z",
          processing_status: "RECEIVED",
          created_at: "2026-09-29T05:02:00Z",
        },
      ],
    });
    getStatus.mockResolvedValue({
      ...disconnected,
      connected: true,
      status: "CONNECTED",
    });
    render(<OwnerWhatsAppCard token="tok" businessId="biz" />);
    expect(await screen.findByText("Unknown WhatsApp Contact")).toBeInTheDocument();
    expect(screen.getByText(/Hi, can I change my appointment/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Reply/i })).not.toBeInTheDocument();
  });

  it("shows reauth required", async () => {
    getStatus.mockResolvedValue({
      ...disconnected,
      status: "REAUTH_REQUIRED",
    });
    render(<OwnerWhatsAppCard token="tok" businessId="biz" />);
    expect(await screen.findByText("Reauth required")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /Reconnect WhatsApp/i }),
    ).toBeInTheDocument();
  });
});
