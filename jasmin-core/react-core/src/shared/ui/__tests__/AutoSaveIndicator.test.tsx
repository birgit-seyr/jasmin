import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { render, screen, act } from "@testing-library/react";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (k: string, fallback?: unknown) =>
      typeof fallback === "string" ? fallback : k,
    i18n: { language: "de", changeLanguage: () => Promise.resolve() },
  }),
  Trans: ({ children }: { children?: React.ReactNode }) => <>{children}</>,
  initReactI18next: { type: "3rdParty", init: () => {} },
}));

import AutoSaveIndicator from "../AutoSaveIndicator";

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("AutoSaveIndicator", () => {
  it("renders nothing visible when idle (not saving, no changes, never saved)", () => {
    render(<AutoSaveIndicator saving={false} hasChanges={false} />);
    expect(screen.queryByText("settings.saving")).not.toBeInTheDocument();
    expect(screen.queryByText("settings.saved")).not.toBeInTheDocument();
  });

  it("shows 'Saving...' while saving", () => {
    render(<AutoSaveIndicator saving={true} hasChanges={true} />);
    expect(screen.getByText("settings.saving")).toBeInTheDocument();
    expect(screen.queryByText("settings.saved")).not.toBeInTheDocument();
  });

  it("shows 'Saved' immediately after a save completes (saving→false, hasChanges→false)", () => {
    const { rerender } = render(
      <AutoSaveIndicator saving={true} hasChanges={true} />,
    );
    expect(screen.getByText("settings.saving")).toBeInTheDocument();

    rerender(<AutoSaveIndicator saving={false} hasChanges={false} />);
    expect(screen.getByText("settings.saved")).toBeInTheDocument();
  });

  it("hides the 'Saved' badge after 2s", () => {
    const { rerender } = render(
      <AutoSaveIndicator saving={true} hasChanges={true} />,
    );
    rerender(<AutoSaveIndicator saving={false} hasChanges={false} />);
    expect(screen.getByText("settings.saved")).toBeInTheDocument();

    act(() => {
      vi.advanceTimersByTime(2000);
    });
    expect(screen.queryByText("settings.saved")).not.toBeInTheDocument();
  });

  it("does NOT show 'Saved' if user introduces fresh changes before the timer fires", () => {
    const { rerender } = render(
      <AutoSaveIndicator saving={true} hasChanges={true} />,
    );
    rerender(<AutoSaveIndicator saving={false} hasChanges={false} />);
    expect(screen.getByText("settings.saved")).toBeInTheDocument();

    // User edits → hasChanges flips back to true. The 'Saved' branch hides
    // (its render condition is `showSaved && !hasChanges`).
    rerender(<AutoSaveIndicator saving={false} hasChanges={true} />);
    expect(screen.queryByText("settings.saved")).not.toBeInTheDocument();
  });
});
