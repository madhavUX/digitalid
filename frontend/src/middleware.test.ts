import { resolveSiteSubdomainRewrite } from "@/middleware";
import { describe, expect, it } from "vitest";

describe("resolveSiteSubdomainRewrite", () => {
  it("rewrites tenant root to /site/{sub}", () => {
    expect(resolveSiteSubdomainRewrite("ksnsalon.bookanything.in", "/")).toBe(
      "/site/ksnsalon",
    );
  });

  it("skips apex application host", () => {
    expect(resolveSiteSubdomainRewrite("bookanything.in", "/")).toBeNull();
    expect(resolveSiteSubdomainRewrite("bookanything.in", "/owner/dashboard")).toBeNull();
  });

  it("skips api, owner, booking, and existing site paths on subdomain", () => {
    expect(resolveSiteSubdomainRewrite("ksnsalon.bookanything.in", "/api/v1/x")).toBeNull();
    expect(resolveSiteSubdomainRewrite("ksnsalon.bookanything.in", "/owner/x")).toBeNull();
    expect(resolveSiteSubdomainRewrite("ksnsalon.bookanything.in", "/book/x")).toBeNull();
    expect(resolveSiteSubdomainRewrite("ksnsalon.bookanything.in", "/site/ksnsalon")).toBeNull();
  });

  it("rejects arbitrary hosts and reserved labels", () => {
    expect(resolveSiteSubdomainRewrite("evil.example", "/")).toBeNull();
    expect(resolveSiteSubdomainRewrite("www.bookanything.in", "/")).toBeNull();
    expect(resolveSiteSubdomainRewrite("api.bookanything.in", "/")).toBeNull();
  });
});
