import { ApiError, friendlyApiMessage } from "@/lib/api/client";
import { createIdempotencyKey } from "@/lib/booking/idempotency";
import {
  formatDuration,
  formatMoney,
  normalizePhoneInput,
} from "@/lib/booking/format";
import { describe, expect, it } from "vitest";

describe("format helpers", () => {
  it("formats INR money and duration", () => {
    expect(formatMoney("499.00", "INR")).toContain("499");
    expect(formatDuration(45)).toBe("45 min");
    expect(formatDuration(90)).toBe("1h 30m");
  });

  it("normalizes phone input without inventing country logic beyond digit cleanup", () => {
    expect(normalizePhoneInput("98765 43210")).toBe("9876543210");
    expect(normalizePhoneInput("+91 98765-43210")).toBe("+919876543210");
  });
});

describe("idempotency", () => {
  it("generates a non-empty key", () => {
    const key = createIdempotencyKey();
    expect(key.length).toBeGreaterThan(8);
  });
});

describe("friendlyApiMessage", () => {
  it("maps 409 and 429", () => {
    expect(
      friendlyApiMessage(
        new ApiError(409, { error: "conflict", status_code: 409, code: "SLOT_UNAVAILABLE" }),
      ),
    ).toMatch(/just booked/i);
    expect(
      friendlyApiMessage(new ApiError(429, { error: "slow down", status_code: 429 })),
    ).toMatch(/too many requests/i);
  });
});
