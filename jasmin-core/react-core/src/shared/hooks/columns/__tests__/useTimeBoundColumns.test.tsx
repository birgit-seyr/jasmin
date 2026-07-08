import { renderHook } from "@testing-library/react";
import dayjs from "dayjs";
import type { Dayjs } from "dayjs";
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

vi.mock("@shared/hooks/configuration/useTenant", () => ({
  useTenant: () => ({ getSetting: () => "DD.MM.YYYY" }),
}));

import { useTimeBoundColumns } from "../useTimeBoundColumns";

/**
 * The valid_from / valid_until columns gate the picker to Mondays / Sundays
 * via a ``disabledDate`` predicate. That predicate crashed the picker in
 * production when it depended on the ``isoWeek`` plugin's ``isoWeekday()``
 * but no chunk had run ``dayjs.extend(isoWeek)`` yet. It must therefore use
 * only *core* dayjs (``day()``) and never call a plugin method.
 *
 * The key guard uses a stub that exposes ONLY ``day()`` (no ``isoWeekday``):
 * if the predicate ever reverts to a plugin method it throws on the stub and
 * this test goes red — regardless of what plugins the test process loaded.
 */
describe("useTimeBoundColumns disabledDate — plugin-independent weekday gating", () => {
  const getPredicates = () => {
    const { result } = renderHook(() => useTimeBoundColumns());
    // The declared type is (current: Dayjs) => boolean — what AntD passes —
    // but the runtime contract this suite pins includes tolerating EMPTY
    // cells (null/undefined) without throwing. Widen locally so the
    // null-safety assertions below stay compilable.
    type NullTolerantPredicate = (current: Dayjs | null | undefined) => boolean;
    const validFrom = result.current.validFromColumn
      .disabledDate! as NullTolerantPredicate;
    const validUntil = result.current.validUntilColumn
      .disabledDate! as NullTolerantPredicate;
    return { validFrom, validUntil };
  };

  it("valid_from allows Mondays and disables other days (real dayjs)", () => {
    const { validFrom } = getPredicates();
    expect(validFrom(dayjs("2026-01-05"))).toBe(false); // Monday
    expect(validFrom(dayjs("2026-01-06"))).toBe(true); // Tuesday
    expect(validFrom(dayjs("2026-01-11"))).toBe(true); // Sunday
  });

  it("valid_until allows Sundays and disables other days (real dayjs)", () => {
    const { validUntil } = getPredicates();
    expect(validUntil(dayjs("2026-01-11"))).toBe(false); // Sunday
    expect(validUntil(dayjs("2026-01-05"))).toBe(true); // Monday
  });

  it("treats null/undefined as not-disabled (empty cell), never throwing", () => {
    const { validFrom, validUntil } = getPredicates();
    expect(validFrom(null)).toBe(false);
    expect(validFrom(undefined)).toBe(false);
    expect(validUntil(null)).toBe(false);
  });

  it("does not depend on the isoWeek plugin — works on a core-only stub", () => {
    const { validFrom, validUntil } = getPredicates();
    // This stub has NO isoWeekday(); a plugin-based impl would throw here.
    const asDay = (n: number) => ({ day: () => n }) as unknown as Dayjs;

    expect(() => validFrom(asDay(1))).not.toThrow();
    expect(validFrom(asDay(1))).toBe(false); // Monday allowed
    expect(validFrom(asDay(3))).toBe(true); // Wednesday disabled

    expect(() => validUntil(asDay(0))).not.toThrow();
    expect(validUntil(asDay(0))).toBe(false); // Sunday allowed
    expect(validUntil(asDay(4))).toBe(true); // Thursday disabled
  });
});

describe("useTimeBoundColumns validUntilFloor — per-row lower bound", () => {
  const getValidUntil = (
    floor: (record: Record<string, unknown>) => {
      minDate?: Dayjs | null;
      blockAll?: boolean;
    },
  ) => {
    const { result } = renderHook(() =>
      useTimeBoundColumns({
        validUntilFloor: floor as never,
      }),
    );
    return result.current.validUntilColumn.disabledDate! as (
      current: Dayjs,
      record?: Record<string, unknown>,
    ) => boolean;
  };

  it("disables Sundays before the row's minDate, allows minDate and later", () => {
    const minDate = dayjs("2026-09-13"); // Sunday
    const disabledDate = getValidUntil(() => ({ minDate }));
    const record = {};
    expect(disabledDate(dayjs("2026-09-06"), record)).toBe(true); // earlier Sunday
    expect(disabledDate(dayjs("2026-09-13"), record)).toBe(false); // the floor
    expect(disabledDate(dayjs("2026-09-20"), record)).toBe(false); // later Sunday
    expect(disabledDate(dayjs("2026-09-14"), record)).toBe(true); // Monday (not Sunday)
  });

  it("blockAll disables every date (open-ended child)", () => {
    const disabledDate = getValidUntil(() => ({ blockAll: true }));
    const record = {};
    expect(disabledDate(dayjs("2026-09-13"), record)).toBe(true); // even a Sunday
    expect(disabledDate(dayjs("2099-12-27"), record)).toBe(true); // far-future Sunday
  });

  it("no floor (null minDate) → only the Sunday rule applies", () => {
    const disabledDate = getValidUntil(() => ({ minDate: null }));
    const record = {};
    expect(disabledDate(dayjs("2026-09-13"), record)).toBe(false); // any Sunday ok
    expect(disabledDate(dayjs("2026-09-14"), record)).toBe(true); // Monday
  });
});
