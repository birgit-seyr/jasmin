import { describe, expect, it } from "vitest";

import { isSmallerShareSize } from "../useShareTypeVariationSizeOptions";

describe("isSmallerShareSize", () => {
  it.each([
    ["XS", "S"],
    ["S", "M"],
    ["S", "L"],
    ["XL", "XXL"],
    ["HALF", "FULL"],
  ])("finds %s smaller than %s", (size, than) => {
    expect(isSmallerShareSize(size, than)).toBe(true);
  });

  it.each([
    ["M", "S"],
    ["M", "M"],
    ["FULL", "HALF"],
    ["HALF", "L"],
    ["S", "FULL"],
    ["ONE_SIZE", "L"],
    ["S", "ONE_SIZE"],
    [null, "L"],
    ["S", undefined],
  ])("doesn't find %s smaller than %s", (size, than) => {
    expect(isSmallerShareSize(size, than)).toBe(false);
  });
});
