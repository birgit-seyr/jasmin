import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import DiffCell from "../DiffCell";

describe("DiffCell", () => {
  it("renders only the current value when nothing differs", () => {
    const { container } = render(<DiffCell value="10.00 €/KG" />);
    expect(screen.getByText("10.00 €/KG")).toBeInTheDocument();
    expect(container.querySelector(".jasmin-diff-cell__original")).toBeNull();
    // Without `differs`, the value MUST NOT carry the changed modifier class.
    expect(
      container.querySelector(".jasmin-diff-cell__value--changed"),
    ).toBeNull();
  });

  it("marks the value with the 'changed' modifier when differs is true", () => {
    const { container } = render(
      <DiffCell value="10.00 €/KG" differs original="9.50" />,
    );
    expect(
      container.querySelector(".jasmin-diff-cell__value--changed"),
    ).not.toBeNull();
  });

  it("renders the original under the value with a suffix when differs", () => {
    render(
      <DiffCell
        value="10.00 €/KG"
        differs
        original={9.5}
        originalSuffix=" €"
      />,
    );
    // Suffix is concatenated onto the stringified original.
    expect(screen.getByText("9.5 €")).toBeInTheDocument();
  });

  it("delegates to formatOriginal when provided (suffix is ignored)", () => {
    render(
      <DiffCell
        value="10.00 €/KG"
        differs
        original={9.5}
        originalSuffix=" €"
        formatOriginal={(o) => `was ${(o as number).toFixed(2)}`}
      />,
    );
    expect(screen.getByText("was 9.50")).toBeInTheDocument();
    // The suffix-built variant must NOT appear.
    expect(screen.queryByText("9.5 €")).not.toBeInTheDocument();
  });

  it.each([
    ["null", null],
    ["undefined", undefined],
    ["empty string", ""],
  ])(
    "does NOT render the original block when differs but original is %s",
    (_label, original) => {
      const { container } = render(
        <DiffCell value="x" differs original={original} />,
      );
      expect(container.querySelector(".jasmin-diff-cell__original")).toBeNull();
    },
  );

  it("treats the number 0 as a valid original (not 'empty')", () => {
    render(
      <DiffCell
        value="x"
        differs
        original={0}
        formatOriginal={(o) => `was ${o}`}
      />,
    );
    expect(screen.getByText("was 0")).toBeInTheDocument();
  });
});
