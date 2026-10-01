import { OwnerShell } from "@/components/owner/OwnerShell";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const push = vi.fn();
vi.mock("next/navigation", () => ({
  usePathname: () => "/owner/dashboard",
  useRouter: () => ({ push }),
}));

describe("OwnerShell", () => {
  beforeEach(() => {
    window.localStorage.clear();
    push.mockReset();
  });

  it("shows sign-in when no token", () => {
    render(
      <OwnerShell title="Dashboard">
        <p>Secret</p>
      </OwnerShell>,
    );
    expect(screen.getByRole("heading", { name: /Owner sign in/i })).toBeInTheDocument();
    expect(screen.queryByText("Secret")).not.toBeInTheDocument();
  });

  it("renders navigation after token is present", async () => {
    window.localStorage.setItem("ba_access_token", "test-token");
    render(
      <OwnerShell title="Dashboard" businessName="KSN Salon">
        <p>Dashboard body</p>
      </OwnerShell>,
    );
    expect(await screen.findByText("Dashboard body")).toBeInTheDocument();
    expect(screen.getByText("KSN Salon")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Bookings" })).toHaveAttribute(
      "href",
      "/owner/bookings",
    );
  });

  it("signs out and clears token", async () => {
    const user = userEvent.setup();
    window.localStorage.setItem("ba_access_token", "test-token");
    render(
      <OwnerShell>
        <p>Inside</p>
      </OwnerShell>,
    );
    await screen.findByText("Inside");
    await user.click(screen.getByRole("button", { name: /Sign out/i }));
    expect(window.localStorage.getItem("ba_access_token")).toBeNull();
    expect(await screen.findByRole("heading", { name: /Owner sign in/i })).toBeInTheDocument();
  });
});
