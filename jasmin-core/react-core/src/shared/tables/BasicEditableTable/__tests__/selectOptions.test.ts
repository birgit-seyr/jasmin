import { describe, expect, it } from "vitest";
import { withClearOption } from "../selectOptions";
import type { SelectOption } from "../types";

const OPTS: SelectOption[] = [
  { label: "A", value: "a" },
  { label: "B", value: "b" },
];

describe("withClearOption", () => {
  it("prepends a blank clear option when not required (false)", () => {
    const result = withClearOption(OPTS, false);
    expect(result).toHaveLength(3);
    expect(result[0]).toEqual({ label: "", value: "" });
  });

  it("prepends when required is undefined (absent === not required)", () => {
    const result = withClearOption(OPTS, undefined);
    expect(result[0]).toEqual({ label: "", value: "" });
  });

  it("does NOT prepend when required is true", () => {
    expect(withClearOption(OPTS, true)).toEqual(OPTS);
  });

  it("is idempotent when a blank-string clear option already exists", () => {
    const withEmpty: SelectOption[] = [{ label: "", value: "" }, ...OPTS];
    expect(withClearOption(withEmpty, false)).toEqual(withEmpty);
  });

  it("is idempotent when a null-valued clear option already exists (useCrates/usePlots)", () => {
    const withNull = [
      { label: "-", value: null },
      ...OPTS,
    ] as unknown as SelectOption[];
    const result = withClearOption(withNull, false);
    expect(result).toHaveLength(OPTS.length + 1);
    expect(result[0]).toEqual({ label: "-", value: null });
  });
});
