/**
 * HarvestingListControls: the office / gardener view switch and the "round up
 * to full PU" checkbox above the harvesting list. The phone shows only the
 * checkbox, as the page forces the gardener view there. The checkbox saves a
 * tenant setting, which only the office may change, so other roles don't see it.
 */

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, fallback?: unknown) =>
      typeof fallback === "string" ? fallback : key,
    i18n: { language: "de", changeLanguage: () => Promise.resolve() },
  }),
  Trans: ({ children }: { children?: ReactNode }) => <>{children}</>,
  initReactI18next: { type: "3rdParty", init: () => {} },
}));

import HarvestingListControls from "../HarvestingListControls";

const renderControls = (
  overrides: Partial<Parameters<typeof HarvestingListControls>[0]> = {},
) => {
  const props = {
    isMobile: false,
    isGardenerView: false,
    onViewChange: vi.fn(),
    roundUpToFullPU: false,
    onRoundUpChange: vi.fn(),
    canChangeRoundUp: true,
    ...overrides,
  };
  render(<HarvestingListControls {...props} />);
  return props;
};

const officeButton = () => screen.getByRole("button", { name: /commissioning\.office_view/ });
const gardenerButton = () => screen.getByRole("button", { name: /commissioning\.gardener_view/ });
const roundUpCheckbox = () =>
  screen.getByRole("checkbox", { name: "commissioning.round_up_to_full_vpe" });

describe("HarvestingListControls on desktop", () => {
  it("highlights the view in use", () => {
    renderControls({ isGardenerView: true });

    expect(gardenerButton()).toHaveClass("ant-btn-primary");
    expect(officeButton()).not.toHaveClass("ant-btn-primary");
  });

  it("switches to the view a button names", async () => {
    const user = userEvent.setup();
    const props = renderControls();

    await user.click(gardenerButton());
    expect(props.onViewChange).toHaveBeenLastCalledWith(true);

    await user.click(officeButton());
    expect(props.onViewChange).toHaveBeenLastCalledWith(false);
  });

  it("reports the round-up checkbox's new state, also when its label is clicked", async () => {
    const user = userEvent.setup();
    const props = renderControls({ roundUpToFullPU: true });

    expect(roundUpCheckbox()).toBeChecked();
    await user.click(roundUpCheckbox());
    expect(props.onRoundUpChange).toHaveBeenCalledTimes(1);
    expect(props.onRoundUpChange).toHaveBeenLastCalledWith(false);

    await user.click(screen.getByText("commissioning.round_up_to_full_vpe"));
    expect(props.onRoundUpChange).toHaveBeenCalledTimes(2);
  });
});

describe("HarvestingListControls on the phone", () => {
  it("shows only the round-up checkbox, which reports its new state", async () => {
    const user = userEvent.setup();
    const props = renderControls({ isMobile: true });

    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    expect(roundUpCheckbox()).not.toBeChecked();

    await user.click(roundUpCheckbox());
    expect(props.onRoundUpChange).toHaveBeenCalledTimes(1);
    expect(props.onRoundUpChange).toHaveBeenLastCalledWith(true);
  });
});

describe("HarvestingListControls for a role that can't change tenant settings", () => {
  const roundUpCheckboxOrNull = () =>
    screen.queryByRole("checkbox", { name: "commissioning.round_up_to_full_vpe" });

  it("keeps the view switch on desktop but offers no round-up checkbox", () => {
    renderControls({ canChangeRoundUp: false });

    expect(officeButton()).toBeInTheDocument();
    expect(gardenerButton()).toBeInTheDocument();
    expect(roundUpCheckboxOrNull()).not.toBeInTheDocument();
  });

  it("offers no round-up checkbox on the phone", () => {
    renderControls({ isMobile: true, canChangeRoundUp: false });

    expect(roundUpCheckboxOrNull()).not.toBeInTheDocument();
  });
});
