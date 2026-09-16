/**
 * ``useCurrentDays`` runs a second shares query one ISO week after the selected
 * one, to pick up the activity days that belong to the current delivery week.
 *
 * Week and year travel to the API as one ISO coordinate, so the derived year
 * has to be the ISO week-year: stepping out of week 52 lands on a January date
 * whose calendar year is already the next one, and the backend refuses week 53
 * of a 52-week ISO year.
 */
import { renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const sharesList = vi.hoisted(() => vi.fn());

vi.mock("@shared/api/generated/commissioning/commissioning", () => ({
  useCommissioningSharesList: sharesList,
}));

import { useCurrentDays } from "../useCurrentDays";

const requestedParams = () =>
  sharesList.mock.calls.map(([params]) => params as Record<string, number>);

describe("useCurrentDays — the next-week query", () => {
  beforeEach(() => {
    sharesList.mockReturnValue({
      data: [],
      isLoading: false,
      isFetched: true,
      error: null,
      refetch: vi.fn(),
    });
    vi.useFakeTimers({ toFake: ["Date"] });
  });

  afterEach(() => {
    vi.useRealTimers();
    sharesList.mockReset();
  });

  it("asks for ISO 2026-W53, not week 53 of the calendar year 2027", () => {
    // The step keeps today's weekday, so a Friday "now" puts the +1 week on
    // Friday 2027-01-01 — ISO 2026-W53, a week ISO 2027 does not have.
    vi.setSystemTime(new Date("2026-03-06T12:00:00Z"));

    renderHook(() => useCurrentDays(52, 2026));

    expect(requestedParams()).toContainEqual({ delivery_week: 52, year: 2026 });
    expect(requestedParams()).toContainEqual({ delivery_week: 53, year: 2026 });
    expect(requestedParams()).not.toContainEqual({
      delivery_week: 53,
      year: 2027,
    });
  });

  it("steps within the year for a week that is not the last", () => {
    vi.setSystemTime(new Date("2026-03-06T12:00:00Z"));

    renderHook(() => useCurrentDays(10, 2026));

    expect(requestedParams()).toContainEqual({ delivery_week: 11, year: 2026 });
  });
});
