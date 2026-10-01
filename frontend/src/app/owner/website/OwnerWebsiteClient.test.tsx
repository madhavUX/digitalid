import { OwnerWebsiteClient } from "@/app/owner/website/OwnerWebsiteClient";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const getWebsiteStatus = vi.fn();
const publishWebsite = vi.fn();
const unpublishWebsite = vi.fn();
const updateBusinessLaunchProfile = vi.fn();
const writeText = vi.fn(async () => undefined);

vi.mock("next/navigation", () => ({
  usePathname: () => "/owner/website",
  useRouter: () => ({ push: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

vi.mock("@/lib/api/ownerApi", () => ({
  listBusinesses: vi.fn(async () => ({
    results: [{ id: "biz-1", name: "KSN Salon", vertical: "SALON" }],
  })),
  listLocations: vi.fn(async () => ({
    results: [{ id: "loc-1", name: "MVP Colony", slug: "mvp-colony" }],
  })),
  getWebsiteStatus: (...args: unknown[]) => getWebsiteStatus(...args),
  publishWebsite: (...args: unknown[]) => publishWebsite(...args),
  unpublishWebsite: (...args: unknown[]) => unpublishWebsite(...args),
  updateBusinessLaunchProfile: (...args: unknown[]) =>
    updateBusinessLaunchProfile(...args),
}));

const unpublished = {
  location_id: "loc-1",
  business_id: "biz-1",
  template_key: "SALON_MODERN",
  website_status: "READY",
  domain_status: "SUBDOMAIN_ACTIVE",
  launch_status: "READY",
  subdomain: "ksnsalon",
  subdomain_hostname: "ksnsalon.bookanything.in",
  public_url: "https://ksnsalon.bookanything.in",
  internal_path: "/site/ksnsalon",
  custom_domain: null,
};

const live = {
  ...unpublished,
  website_status: "PUBLISHED",
  launch_status: "LIVE",
};

describe("OwnerWebsiteClient", () => {
  beforeEach(() => {
    window.localStorage.clear();
    window.localStorage.setItem("ba_access_token", "test-token");
    getWebsiteStatus.mockReset();
    publishWebsite.mockReset();
    unpublishWebsite.mockReset();
    updateBusinessLaunchProfile.mockReset();
    writeText.mockReset();
    writeText.mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText },
    });
  });

  it("shows unpublished status and publish action", async () => {
    getWebsiteStatus.mockResolvedValue(unpublished);
    render(<OwnerWebsiteClient />);
    expect(await screen.findByText("NOT PUBLISHED")).toBeInTheDocument();
    expect(screen.getByText(/Template:\s*Salon Modern/i)).toBeInTheDocument();
    expect(screen.getByText("https://ksnsalon.bookanything.in")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Publish Website/i })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /^Preview$/i })).toHaveAttribute(
      "href",
      expect.stringContaining("/owner/website/preview"),
    );
  });

  it("publishes and shows live URL actions", async () => {
    const user = userEvent.setup();
    getWebsiteStatus.mockResolvedValue(unpublished);
    publishWebsite.mockResolvedValue(live);
    render(<OwnerWebsiteClient />);
    await screen.findByText("NOT PUBLISHED");
    await user.click(screen.getByRole("button", { name: /Publish Website/i }));
    await waitFor(() => {
      expect(publishWebsite).toHaveBeenCalledWith("biz-1", "test-token", "loc-1");
    });
    expect(await screen.findByText("LIVE")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Open Website/i })).toHaveAttribute(
      "href",
      "https://ksnsalon.bookanything.in",
    );
  });

  it("copies public URL", async () => {
    const user = userEvent.setup();
    getWebsiteStatus.mockResolvedValue(live);
    render(<OwnerWebsiteClient />);
    await screen.findByText("LIVE");
    await user.click(screen.getByRole("button", { name: /Copy Website URL/i }));
    expect(await screen.findByText("Copied")).toBeInTheDocument();
  });

  it("unpublishes a live site", async () => {
    const user = userEvent.setup();
    getWebsiteStatus.mockResolvedValue(live);
    unpublishWebsite.mockResolvedValue({
      ...live,
      website_status: "UNPUBLISHED",
      launch_status: "READY",
    });
    render(<OwnerWebsiteClient />);
    await screen.findByText("LIVE");
    await user.click(screen.getByRole("button", { name: /Unpublish/i }));
    await waitFor(() => {
      expect(unpublishWebsite).toHaveBeenCalledWith("biz-1", "test-token", "loc-1");
    });
    expect(await screen.findByText("NOT PUBLISHED")).toBeInTheDocument();
  });

  it("changes template without losing URL", async () => {
    const user = userEvent.setup();
    getWebsiteStatus.mockImplementation(async () => ({
      ...live,
      template_key: "SALON_CLASSIC",
    }));
    updateBusinessLaunchProfile.mockResolvedValue({});
    render(<OwnerWebsiteClient />);
    await screen.findByText("LIVE");
    await user.click(screen.getByRole("button", { name: /Change Template/i }));
    await user.click(screen.getByLabelText(/Salon Classic/i));
    await user.click(screen.getByRole("button", { name: /Save template/i }));
    await waitFor(() => {
      expect(updateBusinessLaunchProfile).toHaveBeenCalledWith(
        "biz-1",
        "test-token",
        { template_key: "SALON_CLASSIC" },
        "loc-1",
      );
    });
    expect(await screen.findByText(/Template:\s*Salon Classic/i)).toBeInTheDocument();
    expect(screen.getByText("https://ksnsalon.bookanything.in")).toBeInTheDocument();
  });

  it("shows failed provisioning state", async () => {
    getWebsiteStatus.mockResolvedValue({
      ...unpublished,
      website_status: "DRAFT",
      domain_status: "FAILED",
      launch_status: "DRAFT",
      public_url: null,
      subdomain: null,
      subdomain_hostname: null,
    });
    render(<OwnerWebsiteClient />);
    expect(await screen.findByText("FAILED")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Publish Website/i })).toBeInTheDocument();
  });
});
