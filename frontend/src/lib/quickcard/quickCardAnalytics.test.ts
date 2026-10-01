import {
  resetQuickCardAnalyticsForTests,
  trackCta,
  trackPageView,
} from "@/lib/quickcard/quickCardAnalytics";
import { afterEach, describe, expect, it, vi } from "vitest";

describe("quickCardAnalytics", () => {
  afterEach(() => {
    resetQuickCardAnalyticsForTests();
    vi.unstubAllGlobals();
  });

  it("records one page view and ignores a second call for the same card", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true });
    vi.stubGlobal("fetch", fetchMock);
    trackPageView("ksn-salon");
    trackPageView("ksn-salon");
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const body = JSON.parse(String(fetchMock.mock.calls[0][1].body));
    expect(body).toEqual({ event_type: "PAGE_VIEW" });
    expect(JSON.stringify(body)).not.toMatch(/phone|email|customer/i);
  });

  it("sends every CTA and ignores unknown values", () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true });
    vi.stubGlobal("fetch", fetchMock);
    for (const cta of ["book", "whatsapp", "call", "directions", "review", "share"]) {
      trackCta("ksn-salon", cta);
    }
    trackCta("ksn-salon", "checkout");
    expect(fetchMock).toHaveBeenCalledTimes(6);
  });

  it("swallows a failed request", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("offline")));
    expect(() => trackCta("ksn-salon", "book")).not.toThrow();
  });
});
