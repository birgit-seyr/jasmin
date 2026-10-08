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

  it("lets the caller set the panel's width and spacing", () => {
    const { container } = render(
      <ExplainerText maxWidth="20em" style={{ marginTop: 0 }}>
        plain
      </ExplainerText>,
    );
    const panel = container.firstChild as HTMLElement;
    expect(styleOf(panel).maxWidth).toBe("20em");
    expect(styleOf(panel).marginTop).toBe("0px");
  });

  it("renders the 💡 emoji icon", () => {
    render(<ExplainerText>tip</ExplainerText>);
    expect(screen.getByText("💡")).toBeInTheDocument();
  });

  it.each([
    ["an empty text", ""],
    ["a blank text", "  "],
    ["no text", null],
  ])("renders nothing, not even the title or the icon, for %s", (_label, body) => {
    const { container } = render(<ExplainerText title="Info">{body}</ExplainerText>);

    expect(container).toBeEmptyDOMElement();
  });

  it("renders a body put together from several parts", () => {
    render(
      <ExplainerText title="Info">
        {"First part"}
        <br />
        {""}
      </ExplainerText>,
    );

    expect(screen.getByText("Info")).toBeInTheDocument();
    expect(screen.getByText("First part")).toBeInTheDocument();
  });
});
