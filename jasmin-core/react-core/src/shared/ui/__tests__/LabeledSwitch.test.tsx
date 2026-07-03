import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (k: string, fallback?: unknown) =>
      typeof fallback === "string" ? fallback : k,
    i18n: { language: "de", changeLanguage: () => Promise.resolve() },
  }),
  Trans: ({ children }: { children?: React.ReactNode }) => <>{children}</>,
  initReactI18next: { type: "3rdParty", init: () => {} },
}));

import LabeledSwitch from "../LabeledSwitch";
import HideInactiveSwitch from "../HideInactiveSwitch";

describe("LabeledSwitch", () => {
  it("invokes onChange with the inverted boolean when toggled", async () => {
    const onChange = vi.fn();
    render(
      <LabeledSwitch value={false} onChange={onChange} label="Show details" />,
    );

    const user = userEvent.setup();
    await user.click(screen.getByRole("switch"));

    expect(onChange).toHaveBeenCalledTimes(1);
    // AntD Switch invokes onChange(checked, event) — assert only the first arg.
    expect(onChange.mock.calls[0][0]).toBe(true);
  });

  it("clicking the label also toggles the switch (htmlFor wiring)", async () => {
    const onChange = vi.fn();
    render(
      <LabeledSwitch
        value={false}
        onChange={onChange}
        label="Show details"
        id="my-switch"
      />,
    );

    const user = userEvent.setup();
    await user.click(screen.getByText("Show details"));

    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange.mock.calls[0][0]).toBe(true);
  });

  it("reflects the controlled `value` in aria-checked", () => {
    const { rerender } = render(
      <LabeledSwitch value={false} onChange={() => {}} label="x" />,
    );
    expect(screen.getByRole("switch")).toHaveAttribute("aria-checked", "false");
    rerender(<LabeledSwitch value={true} onChange={() => {}} label="x" />);
    expect(screen.getByRole("switch")).toHaveAttribute("aria-checked", "true");
  });

  it("does not invoke onChange when disabled", async () => {
    const onChange = vi.fn();
    render(
      <LabeledSwitch value={false} onChange={onChange} label="x" disabled />,
    );

    const user = userEvent.setup();
    await user.click(screen.getByRole("switch"));
    expect(onChange).not.toHaveBeenCalled();
  });
});

describe("HideInactiveSwitch", () => {
  it("renders the translated label and forwards the toggle to onChange", async () => {
    const onChange = vi.fn();
    render(<HideInactiveSwitch value={false} onChange={onChange} />);

    expect(screen.getByText("commissioning.hide_inactive")).toBeInTheDocument();

    const user = userEvent.setup();
    await user.click(screen.getByRole("switch"));
    expect(onChange.mock.calls[0][0]).toBe(true);
  });
});
