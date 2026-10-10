import { describe, expect, it } from "vitest";

import { recordText } from "../recordText";

describe("recordText", () => {
  it("reads a text field of the row", () => {
    expect(recordText({ key: 1, note: "wash twice" }, "note")).toBe("wash twice");
  });

  it("gives an empty string for a missing or empty field", () => {
    expect(recordText({ key: 1 }, "note")).toBe("");
    expect(recordText({ key: 1, note: null }, "note")).toBe("");
  });
});
