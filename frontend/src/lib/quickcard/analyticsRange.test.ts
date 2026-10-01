import { describe, expect, it } from "vitest";

import { presetAnalyticsRange } from "./analyticsRange";

describe("presetAnalyticsRange", () => {
  const now = new Date("2026-09-30T18:00:00Z");

  it("uses inclusive UTC days for 7, 30, and 90", () => {
    expect(presetAnalyticsRange(7, now)).toEqual({
      dateFrom: "2026-09-24",
      dateTo: "2026-09-30",
    });
    expect(presetAnalyticsRange(30, now)).toEqual({
      dateFrom: "2026-09-01",
      dateTo: "2026-09-30",
    });
    expect(presetAnalyticsRange(90, now)).toEqual({
      dateFrom: "2026-07-03",
      dateTo: "2026-09-30",
    });
  });
});
