/**
 * The documentation pages' shared scaffold: one summary query off the
 * year/week/[day] selectors, the save body every page builds on, and the
 * table's remount key. The storage-scoped variant adds the page-level storage:
 * it gates the query, filters the rows and is stamped on every save.
 *
 * The clock is frozen on Wednesday 2026-10-14 (ISO week 42): the selected day
 * starts on today's weekday, and "past" is measured from today.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const state = vi.hoisted(() => ({
  week: 42 as number | null,
  rows: undefined as unknown[] | undefined,
  summaryRetrieve: vi.fn(),
}));

vi.mock("@shared/api/generated/commissioning/commissioning", () => ({
  useCommissioningDocumentationSummarySummaryRetrieve: state.summaryRetrieve,
  getCommissioningDocumentationSummarySummaryRetrieveQueryKey: (params: unknown) => [
    "summary",
    params,
  ],
}));

vi.mock("@hooks/useYearWeekState", () => ({
  useYearWeekState: () => ({
    selectedYear: 2026,
    setSelectedYear: vi.fn(),
    selectedWeek: state.week,
    setSelectedWeek: vi.fn(),
    currentYear: 2026,
    currentWeek: 42,
  }),
}));

vi.mock("../useStorages", () => ({
  useStorages: () => ({ storages: [{ value: "cellar", label: "Cellar" }] }),
}));

import {
  useDocumentationSummaryPage,
  type DocumentationSummaryRecord,
} from "../useDocumentationSummaryPage";
import { useStorageDocumentationPage } from "../useStorageDocumentationPage";

let queryClient: QueryClient;
const wrapper = ({ children }: { children: ReactNode }) => (
  <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
);

const lastQuery = () =>
  state.summaryRetrieve.mock.calls.at(-1) as [Record<string, unknown>, { query: { enabled: boolean } }];

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date(2026, 9, 14, 12, 0));
  queryClient = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  state.week = 42;
  state.rows = undefined;
  state.summaryRetrieve.mockReset();
  state.summaryRetrieve.mockImplementation(() => ({ data: state.rows, isFetching: false }));
});

afterEach(() => {
  vi.useRealTimers();
});

describe("useDocumentationSummaryPage", () => {
  it("queries the selected week and today's weekday for a day-scoped page", () => {
    const { result } = renderHook(() => useDocumentationSummaryPage({ model: "washamount" }), {
      wrapper,
    });
    expect(result.current.selectedDay).toBe(2);
    expect(lastQuery()[0]).toEqual({
      year: 2026,
      delivery_week: 42,
      is_past: false,
      day_number: 2,
      model: "washamount",
    });
    expect(lastQuery()[1]).toEqual({ query: { enabled: true } });
    expect(result.current.customSaveBase).toEqual({
      year: 2026,
      delivery_week: 42,
      day_number: 2,
      model: "washamount",
    });
    expect(result.current.tableKey).toBe("2026-42-2");
  });

  it("leaves the day out of a week-scoped page and merges the extra params", () => {
    const extraListParams = { is_preparation_lists: true };
    const { result } = renderHook(
      () => useDocumentationSummaryPage({ model: "purchase", withDay: false, extraListParams }),
      { wrapper },
    );
    expect(result.current.selectedDay).toBeNull();
    expect(lastQuery()[0]).toEqual({
      year: 2026,
      delivery_week: 42,
      is_past: false,
      model: "purchase",
      is_preparation_lists: true,
    });
    expect(result.current.customSaveBase).not.toHaveProperty("day_number");
    expect(result.current.tableKey).toBe("2026-42");
  });

  it("marks a week more than a week back as past", () => {
    state.week = 40;
    const { result } = renderHook(() => useDocumentationSummaryPage({ model: "harvest" }), {
      wrapper,
    });
    expect(result.current.isPast).toBe(true);
    expect(lastQuery()[0].is_past).toBe(true);
  });

  it("follows a changed day in the query, the save body and the key", () => {
    const { result } = renderHook(() => useDocumentationSummaryPage({ model: "harvest" }), {
      wrapper,
    });
    act(() => result.current.setSelectedDay(4));
    expect(lastQuery()[0].day_number).toBe(4);
    expect(result.current.customSaveBase.day_number).toBe(4);
    expect(result.current.tableKey).toBe("2026-42-4");
  });

  it("invalidates exactly its own summary query", () => {
    const invalidate = vi.spyOn(queryClient, "invalidateQueries");
    const { result } = renderHook(() => useDocumentationSummaryPage({ model: "harvest" }), {
      wrapper,
    });
    act(() => result.current.invalidateData());
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["summary", result.current.listParams] });
  });

  it("passes the gate on to the query", () => {
    renderHook(() => useDocumentationSummaryPage({ model: "harvest", queryEnabled: false }), {
      wrapper,
    });
    expect(lastQuery()[1]).toEqual({ query: { enabled: false } });
  });
});

describe("useStorageDocumentationPage", () => {
  const hasAmount = (row: DocumentationSummaryRecord) => !!row.amount;

  it("waits for a storage before it queries", () => {
    const { result } = renderHook(
      () => useStorageDocumentationPage({ model: "harvest", rowHasData: hasAmount }),
      { wrapper },
    );
    expect(lastQuery()[1]).toEqual({ query: { enabled: false } });
    expect(result.current.storages).toEqual([{ value: "cellar", label: "Cellar" }]);
    expect(result.current.tableKey).toBe("2026-42-2-null");
  });

  it("shows only the selected storage's rows that carry data, keyed by id", () => {
    state.rows = [
      { id: "a", storage_cellar: true, amount: 3 },
      { id: "b", storage_cellar: true, amount: 0 },
      { id: "c", storage_barn: true, amount: 5 },
    ];
    const { result } = renderHook(
      () => useStorageDocumentationPage({ model: "harvest", rowHasData: hasAmount }),
      { wrapper },
    );
    act(() => result.current.setSelectedStorage("cellar"));

    expect(lastQuery()[1]).toEqual({ query: { enabled: true } });
    expect(result.current.data.map((row) => [row.id, row.key])).toEqual([["a", "a"]]);
    expect(result.current.tableKey).toBe("2026-42-2-cellar");
  });

  it("stamps the storage and the week on a save and turns a blank amount into 0", () => {
    const { result } = renderHook(
      () => useStorageDocumentationPage({ model: "harvest", rowHasData: hasAmount }),
      { wrapper },
    );
    act(() => result.current.setSelectedStorage("cellar"));

    expect(result.current.customSave({ share_article: "carrot", amount: "" })).toEqual({
      share_article: "carrot",
      storage: "cellar",
      year: 2026,
      delivery_week: 42,
      day_number: 2,
      amount: 0,
    });
    expect(result.current.customSave({ amount: 4 }).amount).toBe(4);
  });

  it("falls back to the current week and leaves the day out of a week-scoped page", () => {
    state.week = null;
    const { result } = renderHook(
      () =>
        useStorageDocumentationPage({ model: "purchase", withDay: false, rowHasData: hasAmount }),
      { wrapper },
    );
    const saved = result.current.customSave({ amount: null });
    expect(saved.delivery_week).toBe(42);
    expect(saved).not.toHaveProperty("day_number");
    expect(saved.amount).toBe(0);
  });
});
