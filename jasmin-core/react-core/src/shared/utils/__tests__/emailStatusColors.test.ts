// Tag colors of the email log statuses, including the neutral color of a send
// suppressed in onboarding mode.

import { describe, expect, it } from "vitest";

import { getEmailStatusColor } from "../emailStatusColors";

describe("getEmailStatusColor", () => {
  it.each([
    ["failed", "red"],
    ["bounced", "red"],
    ["pending", "orange"],
    ["deferred", "orange"],
    ["delivered", "green"],
    ["sent", "blue"],
    ["suppressed", "default"],
  ])("colors %s as %s", (status, color) => {
    expect(getEmailStatusColor(status)).toBe(color);
  });
});
