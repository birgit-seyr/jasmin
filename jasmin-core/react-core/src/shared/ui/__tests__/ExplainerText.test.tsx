import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import ExplainerText from "../ExplainerText";

function styleOf(el: HTMLElement | null): CSSStyleDeclaration {
  if (!el) throw new Error("element not found");
  return el.style;
}

describe("ExplainerText", () => {
  it("renders the children inside the panel", () => {
    render(<ExplainerText>Be careful!</ExplainerText>);
    expect(screen.getByText("Be careful!")).toBeInTheDocument();
  });

  it("renders the optional title above the body", () => {
    render(<ExplainerText title="Heads up">Body text</ExplainerText>);
    expect(screen.getByText("Heads up")).toBeInTheDocument();
    expect(screen.getByText("Body text")).toBeInTheDocument();
  });

  it("uses the warning preset's background colour when type='warning'", () => {
    const { container } = render(
      <ExplainerText type="warning">heads up</ExplainerText>,
    );
    const panel = container.firstChild as HTMLElement;
    expect(styleOf(panel).backgroundColor).toBe("var(--color-highlight)");
  });

  it("falls back to the supplied background/border when no type is given", () => {
    const { container } = render(
      <ExplainerText backgroundColor="rgb(1, 2, 3)" borderColor="rgb(4, 5, 6)">
        plain
      </ExplainerText>,
    );
    const panel = container.firstChild as HTMLElement;
    expect(styleOf(panel).backgroundColor).toBe("rgb(1, 2, 3)");
    expect(styleOf(panel).border).toContain("rgb(4, 5, 6)");
  });

  it("renders the default 💡 emoji icon when no type and no icon is given", () => {
    render(<ExplainerText>tip</ExplainerText>);
    expect(screen.getByText("💡")).toBeInTheDocument();
  });
});
