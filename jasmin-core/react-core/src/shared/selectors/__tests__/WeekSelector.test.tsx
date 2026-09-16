/**
 * Year/week reconciliation in WeekSelector.
 *
 * Week 53 exists only in a 53-week ISO year, so a year change must clamp a
 * week the new year does not have: without it, stepping from 2026 (53 weeks)
 * to 2027 (52) leaves the page asking the API for week 53 of 2027, which the
 * backend refuses. The antd Select is stubbed down to the one thing under
 * test, its onChange.
 */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

vi.mock("antd", () => ({
  Select: ({ onChange }: { onChange?: (value: number) => void }) => (
    <button data-testid="year-select" onClick={() => onChange?.(2027)}>
      year
    </button>
  ),
  Space: ({ children }: { children?: React.ReactNode }) => <div>{children}</div>,
}));

vi.mock("../SteppedSelect", () => ({ default: () => null }));

vi.mock("@hooks/index", () => ({
  useTenantYearOptions: () => ({
    tenantCreationYear: 2020,
    yearOptions: [
      { label: 2026, value: 2026 },
      { label: 2027, value: 2027 },
    ],
  }),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, fallback?: unknown) =>
      typeof fallback === "string" ? fallback : key,
    i18n: { language: "de", changeLanguage: () => Promise.resolve() },
  }),
  Trans: ({ children }: { children?: React.ReactNode }) => <>{children}</>,
  initReactI18next: { type: "3rdParty", init: () => {} },
}));

import WeekSelector from "../WeekSelector";

const renderSelector = (selectedWeek: number | null) => {
  const setSelectedYear = vi.fn();
  const setSelectedWeek = vi.fn();
  render(
    <WeekSelector
      selectedYear={2026}
      setSelectedYear={setSelectedYear}
      selectedWeek={selectedWeek}
      setSelectedWeek={setSelectedWeek}
    />,
  );
  return { setSelectedYear, setSelectedWeek };
};

describe("WeekSelector — week/year reconciliation", () => {
  it("clamps week 53 to 52 when switching to a 52-week year", async () => {
    const { setSelectedYear, setSelectedWeek } = renderSelector(53);

    await userEvent.click(screen.getByTestId("year-select"));

    expect(setSelectedYear).toHaveBeenCalledWith(2027);
    expect(setSelectedWeek).toHaveBeenCalledWith(52);
  });

  it("leaves a week the new year has alone", async () => {
    const { setSelectedYear, setSelectedWeek } = renderSelector(10);

    await userEvent.click(screen.getByTestId("year-select"));

    expect(setSelectedYear).toHaveBeenCalledWith(2027);
    expect(setSelectedWeek).not.toHaveBeenCalled();
  });

  it("leaves an all-weeks (null) selection alone", async () => {
    const { setSelectedWeek } = renderSelector(null);

    await userEvent.click(screen.getByTestId("year-select"));

    expect(setSelectedWeek).not.toHaveBeenCalled();
  });
});
