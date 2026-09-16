// DisabledReasonTooltip explains an unavailable action on hover, with the light
// custom tooltip, and to assistive technology through aria-describedby.

import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import DisabledReasonTooltip from "../DisabledReasonTooltip";

function renderAction(reason: string | null) {
  render(
    <DisabledReasonTooltip reason={reason}>
      {(reasonId) => (
        <button type="button" disabled={!!reason} aria-describedby={reasonId}>
          Send
        </button>
      )}
    </DisabledReasonTooltip>,
  );
  return screen.getByRole("button", { name: "Send" });
}

describe("DisabledReasonTooltip", () => {
  it("renders the action alone without a reason", () => {
    const button = renderAction(null);

    expect(button).toBeEnabled();
    expect(button).not.toHaveAttribute("aria-describedby");
    expect(button.parentElement).not.toHaveClass("disabled-reason-tooltip");
  });

  it("describes the action with the reason text", () => {
    const button = renderAction("Turn off onboarding mode first.");

    expect(button).toBeDisabled();
    expect(button).toHaveAccessibleDescription(
      "Turn off onboarding mode first.",
    );
  });

  it("shows the reason in the light tooltip on hover", async () => {
    const button = renderAction("Turn off onboarding mode first.");

    await userEvent.hover(button.parentElement!);

    const tooltip = await screen.findByRole("tooltip");
    expect(tooltip).toHaveTextContent("Turn off onboarding mode first.");
    expect(tooltip.closest(".custom-tooltip")).not.toBeNull();
  });
});
