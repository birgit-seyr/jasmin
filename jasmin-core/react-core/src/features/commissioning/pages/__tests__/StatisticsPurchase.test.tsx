/**
 * StatisticsPurchase: the money the farm spent buying in purchased articles,
 * one bar per ISO week over a date range that starts as the tenant's current
 * fiscal year. Rendered through the real range picker and its presets, the
 * currency and date-format hooks and the shared bar chart, whose
 * visually-hidden table carries the per-week figures. The generated
 * commissioning client is the mocking boundary: its query hook is a real
 * TanStack query around a spy that answers per range.
 *
 * The clock is frozen on Wednesday 7 October 2026.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { PurchaseCostByWeek } from "@shared/api/generated/models";
import { flushMicrotasks, profileRenders } from "@/test/profileRenders";

const NOW = vi.hoisted(() => {
  const now = new Date(2026, 9, 7, 12, 0);
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(now);
  return now;
});

// One ``t`` for every call, as the real hook keeps it stable across renders.
// A call with options shows them, so an interpolated total stays readable.
const i18nMock = vi.hoisted(() => ({
  t: (key: string, options?: unknown) =>
    options && typeof options === "object" ? `${key} ${JSON.stringify(options)}` : key,
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: i18nMock.t,
    i18n: { language: "de", changeLanguage: () => Promise.resolve() },
  }),
  Trans: ({ children }: { children?: React.ReactNode }) => <>{children}</>,
  initReactI18next: { type: "3rdParty", init: () => {} },
}));

// The tenant record and settings, per test; an unset setting falls back to the
// caller's default. The hook hands out one object per tenant record, as the
// real context does.
const tenantState = vi.hoisted(() => ({
  record: null as Record<string, unknown> | null,
  settings: {} as Record<string, unknown>,
}));
vi.mock("@hooks/configuration/useTenant", async () => {
  const { makeUseTenantMock } = await import("@/test/tenantMock");
  let current: ReturnType<typeof makeUseTenantMock> | null = null;
  return {
    useTenant: () => {
      if (!current || current.tenant !== tenantState.record) {
        current = makeUseTenantMock({
          tenant: tenantState.record,
          getSetting: (key: string, defaultValue?: unknown) =>
            key in tenantState.settings ? tenantState.settings[key] : defaultValue,
        });
      }
      return current;
    },
  };
});

const api = vi.hoisted(() => ({ purchaseCostByWeek: vi.fn() }));

vi.mock("@shared/api/generated/commissioning/commissioning", async () => {
  const { useQuery } = await import("@tanstack/react-query");
  return {
    useCommissioningPurchaseCostByWeekList: function usePurchaseCostByWeek(
      params: unknown,
      options?: { query?: { enabled?: boolean } },
    ) {
      return useQuery({
        queryKey: ["/api/commissioning/purchase_cost_by_week/", params],
        queryFn: async () => api.purchaseCostByWeek(params),
        enabled: options?.query?.enabled,
      });
    },
  };
});

import StatisticsPurchase from "../StatisticsPurchase";

// ── Fixtures ────────────────────────────────────────────────────────────────

const point = (year: number, week: number, amount: string): PurchaseCostByWeek => ({ year, week, amount });

// Weeks 2–4 of 2026: one with nothing bought in.
const EARLY_2026 = [point(2026, 2, "120.50"), point(2026, 3, "0.00"), point(2026, 4, "1234.10")];

/** A rejected request as axios hands it over, carrying the server's body. */
const httpError = (status: number, data: Record<string, unknown>) =>
  Object.assign(new Error(`Request failed with status code ${status}`), {
    isAxiosError: true,
    response: { status, data },
  });

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(NOW);
  tenantState.record = null;
  tenantState.settings = {};
  api.purchaseCostByWeek.mockReset().mockResolvedValue(EARLY_2026);
});

afterEach(() => {
  vi.useRealTimers();
});

// ── Helpers ─────────────────────────────────────────────────────────────────

function renderPage() {
  const user = userEvent.setup();
  const profiler = profileRenders();
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 }, mutations: { retry: false } },
  });
  const page = () => <QueryClientProvider client={queryClient}>{profiler.wrap(<StatisticsPurchase />)}</QueryClientProvider>;
  const { rerender } = render(page());
  return { user, profiler, rerender: () => rerender(page()) };
}

const TITLE = "commissioning.statistics_purchase";
const CHART = "commissioning.statistics_purchase_chart_title";
const NO_DATA = "commissioning.statistics_purchase_no_data";

const rangeInputs = () => {
  const picker = screen.getAllByLabelText("commissioning.statistics_purchase_date_range")[0].closest<HTMLElement>(".ant-picker");
  if (!picker) throw new Error("No range picker");
  return within(picker).getAllByRole("textbox");
};
const shownRange = () => rangeInputs().map((each) => (each as HTMLInputElement).value);

/** The per-week figures of the chart's screen-reader table, as [week, amount]. */
function chartRows(): string[][] {
  const table = screen.getByRole("table", { name: CHART });
  return Array.from(table.querySelectorAll("tbody > tr")).map((row) =>
    Array.from(row.querySelectorAll("th, td")).map((cell) => cell.textContent ?? ""),
  );
}

const totalText = () => screen.getByText(/^commissioning\.statistics_purchase_total/).textContent;
const spinner = () => document.querySelector(".ant-spin-spinning");

function openPopup(selector: string): HTMLElement {
  const popups = Array.from(document.querySelectorAll<HTMLElement>(selector));
  const popup = popups.filter((each) => !/-hidden\b/.test(each.className)).pop();
  if (!popup) throw new Error(`Nothing open matches ${selector}`);
  return popup;
}

type User = ReturnType<typeof userEvent.setup>;

// The picker sits inside the page's Spin, which blocks pointer events on it
// until the weeks have loaded.
async function pickPreset(user: User, preset: string) {
  await waitFor(() => expect(spinner()).toBeNull());
  await user.click(rangeInputs()[0]);
  await user.click(within(openPopup(".ant-picker-dropdown")).getByText(preset));
}

const requestedRanges = () => api.purchaseCostByWeek.mock.calls.map(([params]) => params);

// ── Loading and layout ──────────────────────────────────────────────────────

describe("StatisticsPurchase loading and layout", () => {
  it("asks for the current calendar year when the tenant keeps no fiscal start month", async () => {
    renderPage();

    await waitFor(() => expect(api.purchaseCostByWeek).toHaveBeenCalledTimes(1));
    expect(requestedRanges()).toEqual([{ start_date: "2026-01-01", end_date: "2026-12-31" }]);
    expect(shownRange()).toEqual(["01.01.2026", "31.12.2026"]);
  });

  it("asks for the fiscal year the tenant's start month opens", async () => {
    tenantState.record = { fiscal_year_start_month: 4 };
    renderPage();

    await waitFor(() => expect(api.purchaseCostByWeek).toHaveBeenCalledTimes(1));
    expect(requestedRanges()).toEqual([{ start_date: "2026-04-01", end_date: "2027-03-31" }]);
  });

  it("starts a fiscal year from November in the year before, as today is still before it", async () => {
    tenantState.record = { fiscal_year_start_month: 11 };
    renderPage();

    await waitFor(() => expect(api.purchaseCostByWeek).toHaveBeenCalled());
    expect(requestedRanges()).toEqual([{ start_date: "2025-11-01", end_date: "2026-10-31" }]);
  });

  it("moves to the fiscal year once the tenant arrives", async () => {
    const { rerender } = renderPage();
    await waitFor(() => expect(api.purchaseCostByWeek).toHaveBeenCalledTimes(1));

    tenantState.record = { fiscal_year_start_month: 7 };
    rerender();

    await waitFor(() => expect(api.purchaseCostByWeek).toHaveBeenCalledTimes(2));
    expect(requestedRanges()[1]).toEqual({ start_date: "2026-07-01", end_date: "2027-06-30" });
    expect(shownRange()).toEqual(["01.07.2026", "30.06.2027"]);
  });

  it("shows the range in the tenant's date format", async () => {
    tenantState.settings = { date_format: "YYYY-MM-DD" };
    renderPage();

    await waitFor(() => expect(api.purchaseCostByWeek).toHaveBeenCalled());
    expect(shownRange()).toEqual(["2026-01-01", "2026-12-31"]);
    expect(requestedRanges()[0]).toEqual({ start_date: "2026-01-01", end_date: "2026-12-31" });
  });

  it("shows the title, the data-quality warning, the chart card and the explainer", async () => {
    renderPage();
    await screen.findByRole("table", { name: CHART });

    expect(screen.getByRole("heading", { level: 1, name: TITLE })).toBeVisible();
    expect(screen.getByText("commissioning.statistics_purchase_data_quality_warning")).toBeInTheDocument();
    expect(screen.getAllByText(CHART).length).toBeGreaterThan(0);
    expect(screen.getByText("explainers.statistics_purchase")).toBeInTheDocument();
  });

  it("shows a spinner while the weeks load", async () => {
    let deliver: (points: PurchaseCostByWeek[]) => void = () => {};
    api.purchaseCostByWeek.mockImplementation(() => new Promise((resolve) => (deliver = resolve)));
    renderPage();

    await waitFor(() => expect(spinner()).toBeInTheDocument());

    deliver(EARLY_2026);

    await screen.findByRole("table", { name: CHART });
    await waitFor(() => expect(spinner()).not.toBeInTheDocument());
  });

  it("settles after mounting instead of re-rendering in a loop", async () => {
    const { profiler } = renderPage();
    await screen.findByRole("table", { name: CHART });
    await flushMicrotasks();

    expect(profiler.onRender.mock.calls.length).toBeLessThan(80);
  });
});

// ── Figures ─────────────────────────────────────────────────────────────────

describe("StatisticsPurchase figures", () => {
  it("lists each week's spending in the tenant's currency, a week without purchases at zero", async () => {
    renderPage();
    await screen.findByRole("table", { name: CHART });

    expect(chartRows()).toEqual([
      ["2", "120,50 €"],
      ["3", "0,00 €"],
      ["4", "1.234,10 €"],
    ]);
  });

  it("totals the range's spending to the cent", async () => {
    api.purchaseCostByWeek.mockResolvedValue([
      point(2026, 10, "0.10"), point(2026, 11, "0.20"), point(2026, 12, "1000.05"),
    ]);
    renderPage();
    await screen.findByRole("table", { name: CHART });

    expect(totalText()).toBe(`commissioning.statistics_purchase_total ${JSON.stringify({ total: "1.000,35 €" })}`);
  });

  it("follows the tenant's currency and number format", async () => {
    tenantState.settings = { currency: "CHF", number_locale: "de-CH" };
    renderPage();
    await screen.findByRole("table", { name: CHART });

    const amounts = chartRows().map(([, amount]) => amount);
    expect(amounts[2]).toMatch(/1.234\.10/);
    expect(amounts[2]).toContain("CHF");
    expect(amounts[2]).not.toContain("€");
  });

  it("says there is nothing to show when the range has no purchases at all", async () => {
    api.purchaseCostByWeek.mockResolvedValue([point(2026, 2, "0.00"), point(2026, 3, "0.00")]);
    renderPage();

    expect(await screen.findByText(NO_DATA)).toBeInTheDocument();
    expect(screen.queryByRole("table", { name: CHART })).not.toBeInTheDocument();
    expect(totalText()).toContain("0,00 €");
  });

  it("says there is nothing to show when the server lists no weeks", async () => {
    api.purchaseCostByWeek.mockResolvedValue([]);
    renderPage();

    expect(await screen.findByText(NO_DATA)).toBeInTheDocument();
  });

  it("keeps the page usable when the figures fail to load", async () => {
    api.purchaseCostByWeek.mockRejectedValue(
      httpError(400, { code: "invalid_query_param", message: "The range must not exceed 5 years.", field: "end_date" }),
    );
    renderPage();

    await waitFor(() => expect(api.purchaseCostByWeek).toHaveBeenCalled());
    await waitFor(() => expect(spinner()).not.toBeInTheDocument());
    expect(await screen.findByText(NO_DATA)).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 1, name: TITLE })).toBeVisible();
    expect(rangeInputs()[0]).toBeEnabled();
  });

  // A calendar year can begin and end in an ISO week 1 (2025 does), so the
  // chart then carries two weeks numbered 1, a year apart.
  it("tells the two weeks numbered 1 of a range across a year's turn apart", async () => {
    const errors = vi.spyOn(console, "error").mockImplementation(() => {});
    api.purchaseCostByWeek.mockResolvedValue([
      point(2025, 1, "10.00"), point(2025, 2, "20.00"), point(2025, 52, "30.00"), point(2026, 1, "40.00"),
    ]);
    renderPage();
    await screen.findByRole("table", { name: CHART });

    const weeks = chartRows().map(([week]) => week);
    expect(new Set(weeks).size).toBe(4);
    expect(errors.mock.calls.flat().join(" ")).not.toMatch(/same key/);
  });
});

// ── Range ───────────────────────────────────────────────────────────────────

describe("StatisticsPurchase range", () => {
  it.each([
    ["common.this_month", { start_date: "2026-10-01", end_date: "2026-10-31" }, ["01.10.2026", "31.10.2026"]],
    ["common.last_month", { start_date: "2026-09-01", end_date: "2026-09-30" }, ["01.09.2026", "30.09.2026"]],
    ["common.last_year", { start_date: "2025-01-01", end_date: "2025-12-31" }, ["01.01.2025", "31.12.2025"]],
  ])("asks for the range of the preset %s", async (preset, params, shown) => {
    const { user } = renderPage();
    await waitFor(() => expect(api.purchaseCostByWeek).toHaveBeenCalledTimes(1));

    await pickPreset(user, preset);

    await waitFor(() => expect(api.purchaseCostByWeek).toHaveBeenCalledTimes(2));
    expect(requestedRanges()[1]).toEqual(params);
    expect(shownRange()).toEqual(shown);
  });

  it("shows the new range's weeks once they arrive", async () => {
    api.purchaseCostByWeek.mockImplementation(async (params: { start_date: string }) =>
      params.start_date === "2026-09-01" ? [point(2026, 36, "75.00"), point(2026, 37, "25.25")] : EARLY_2026,
    );
    const { user } = renderPage();
    await screen.findByRole("table", { name: CHART });

    await pickPreset(user, "common.last_month");

    await waitFor(() => expect(chartRows()).toEqual([["36", "75,00 €"], ["37", "25,25 €"]]));
    expect(totalText()).toContain("100,25 €");
  });

  it("keeps the office's range when the tenant arrives afterwards", async () => {
    const { user, rerender } = renderPage();
    await waitFor(() => expect(api.purchaseCostByWeek).toHaveBeenCalledTimes(1));
    await pickPreset(user, "common.last_month");
    await waitFor(() => expect(api.purchaseCostByWeek).toHaveBeenCalledTimes(2));

    tenantState.record = { fiscal_year_start_month: 4 };
    rerender();
    await flushMicrotasks();

    expect(api.purchaseCostByWeek).toHaveBeenCalledTimes(2);
    expect(shownRange()).toEqual(["01.09.2026", "30.09.2026"]);
  });

  it("offers no way to clear the range, so every request carries both dates", async () => {
    renderPage();
    await waitFor(() => expect(api.purchaseCostByWeek).toHaveBeenCalled());

    expect(document.querySelector(".ant-picker-clear")).not.toBeInTheDocument();
    for (const params of requestedRanges()) {
      expect(params).toEqual({ start_date: expect.stringMatching(/^\d{4}-\d{2}-\d{2}$/), end_date: expect.stringMatching(/^\d{4}-\d{2}-\d{2}$/) });
    }
  });
});
