// ToolTipIcon is a focusable info icon named by its tooltip text, styled by the
// ``tooltip-icon`` class plus whatever modifier class the caller adds.

import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import ToolTipIcon from "../ToolTipIcon";

describe("ToolTipIcon", () => {
  it("names the icon by its title and carries the default class", () => {
    render(<ToolTipIcon title="Why this matters" />);

    const icon = screen.getByRole("img", { name: "Why this matters" });
    expect(icon).toHaveClass("tooltip-icon");
    expect(icon).toHaveAttribute("tabindex", "0");
    expect(icon).not.toHaveAttribute("style");
  });

  it("adds the caller's modifier class to the default one", () => {
    render(
      <ToolTipIcon title="Beside" className="tooltip-icon-beside-button" />,
    );

    const icon = screen.getByRole("img", { name: "Beside" });
    expect(icon).toHaveClass("tooltip-icon", "tooltip-icon-beside-button");
  });

  it("falls back to its default label without a title", () => {
    render(<ToolTipIcon />);

    expect(
      screen.getByRole("img", { name: "Additional information" }),
    ).toBeInTheDocument();
  });
});
