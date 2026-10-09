/**
 * DeliveryStationDaySelector: lists a week's station days as "<weekday> -
 * <station>" and, when asked to, keeps the page's pick one of them. Without
 * params it asks for the current week, so the clock is pinned to a Wednesday
 * of ISO week 41 of 2026. The generated commissioning client is the mocking
 * boundary: its station-days hook is a real TanStack query around a spy.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { afterAll, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import type {
  CommissioningDeliveryStationsDaysListParams,
  DeliveryStationDay,
} from "@shared/api/generated/models";
import { flushMicrotasks } from "@/test/profileRenders";

const i18nMock = vi.hoisted(() => ({
  t: (key: string, fallback?: unknown) => (typeof fallback === "string" ? fallback : key),
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: i18nMock.t,
    i18n: { language: "de", changeLanguage: () => Promise.resolve() },
  }),
  Trans: ({ children }: { children?: React.ReactNode }) => <>{children}</>,
  initReactI18next: { type: "3rdParty", init: () => {} },
}));

vi.mock("@hooks/configuration/useTenant", async () => {
  const { makeUseTenantMock } = await import("@/test/tenantMock");
  const tenant = makeUseTenantMock();
  return { useTenant: () => tenant };
});

const api = vi.hoisted(() => ({ stationDays: vi.fn() }));

vi.mock("@shared/api/generated/commissioning/commissioning", async () => {
  const { useQuery } = await import("@tanstack/react-query");
  return {
    useCommissioningDeliveryStationsDaysList: function useStationDaysQuery(params?: unknown) {
      return useQuery({
        queryKey: ["/api/commissioning/delivery_stations_days/", params],
        queryFn: async () => api.stationDays(params),
      });
    },
  };
});

import DeliveryStationDaySelector from "../DeliveryStationDaySelector";

// ── Fixtures ────────────────────────────────────────────────────────────────

const stationDay = (id: string, dayNumber: string | undefined, shortName: string) =>
  ({
    id,
    delivery_day_number: dayNumber,
    delivery_station_short_name: shortName,
    delivery_station: `ds-${shortName}`,
    delivery_day: `day-${dayNumber}`,
    valid_from: "2026-01-05",
  }) as DeliveryStationDay;

// Backend day numbers: "0" = Monday … "6" = Sunday.
const MONDAY_HOF = stationDay("sd-mon-hof", "0", "Hof");
const TUESDAY_MARKT = stationDay("sd-tue-markt", "1", "Markt");
const FRIDAY_HOF = stationDay("sd-fri-hof", "4", "Hof");
const UNKNOWN_DAY = stationDay("sd-x", "9", "Laden");

type DaysParams = Partial<CommissioningDeliveryStationsDaysListParams>;

/** The station days of each week, keyed "<year>-<week>". */
let weeks: Record<string, DeliveryStationDay[]>;

const answerFromWeeks = async (params: DaysParams) => [
  ...(weeks[`${params.year}-${params.delivery_week}`] ?? []),
];

// ── Helpers ─────────────────────────────────────────────────────────────────

let picked: string | null = null;
const onDayChange = vi.fn();

type PageProps = {
  params?: DaysParams;
  initialDay?: string | null;
  includeNone?: boolean;
  preserveSelection?: boolean;
};

function Page({ params, initialDay = null, includeNone, preserveSelection }: PageProps) {
  const [day, setDay] = useState<string | null>(initialDay);
  picked = day;
  return (
    <DeliveryStationDaySelector
      selectedDeliveryStationDay={day}
      setSelectedDeliveryStationDay={setDay}
      onDeliveryStationDayChange={onDayChange}
      params={params}
      include_null_option={includeNone}
      preserveSelection={preserveSelection}
    />
  );
}

function renderPage(props: PageProps) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  const tree = (pageProps: PageProps) => (
    <QueryClientProvider client={queryClient}>
      <Page {...pageProps} />
    </QueryClientProvider>
  );
  const view = render(tree(props));
  return { showParams: (params: DaysParams) => view.rerender(tree({ ...props, params })) };
}

const PLACEHOLDER = "placeholder.delivery_station_day_selector";

const daySelect = () => screen.getByRole("combobox", { name: PLACEHOLDER });
const selectRoot = () => daySelect().closest(".ant-select") as HTMLElement;
const shownDay = () => selectRoot().querySelector(".ant-select-selection-item")?.textContent ?? "";
const placeholderShown = () =>
  selectRoot().querySelector(".ant-select-selection-placeholder")?.textContent ?? "";

function openDropdown(): HTMLElement {
  const open = document.querySelectorAll<HTMLElement>(".ant-select-dropdown:not(.ant-select-dropdown-hidden)");
  if (open.length === 0) throw new Error("No select dropdown is open");
  return open[open.length - 1];
}

const listedDays = () =>
  Array.from(openDropdown().querySelectorAll(".ant-select-item-option-content")).map((o) => o.textContent);

async function chooseDay(label: string) {
  await userEvent.click(daySelect());
  const option = Array.from(openDropdown().querySelectorAll(".ant-select-item-option-content")).find(
    (content) => content.textContent === label,
  );
  if (!option) throw new Error(`No station day ${label}`);
  await userEvent.click(option);
}

const settle = () => act(() => flushMicrotasks());

beforeAll(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date(2026, 9, 7, 12, 0));
});

afterAll(() => {
  vi.useRealTimers();
});

beforeEach(() => {
  picked = null;
  onDayChange.mockReset();
  weeks = {
    "2026-41": [MONDAY_HOF, TUESDAY_MARKT, FRIDAY_HOF],
    "2026-42": [TUESDAY_MARKT],
    "2026-43": [],
  };
  api.stationDays.mockReset().mockImplementation(answerFromWeeks);
});

// ── Options ─────────────────────────────────────────────────────────────────

describe("DeliveryStationDaySelector options", () => {
  it("asks for the current week and labels each station day by weekday and station", async () => {
    renderPage({});

    await waitFor(() => expect(api.stationDays).toHaveBeenCalledWith({ year: 2026, delivery_week: 41 }));
    await userEvent.click(daySelect());
    await waitFor(() =>
      expect(listedDays()).toEqual(["delivery.mo - Hof", "delivery.di - Markt", "delivery.fr - Hof"]),
    );
  });

  it("forwards the page's filters and lets them override the week", async () => {
    renderPage({ params: { year: 2026, delivery_week: 42, delivery_station: "ds-Markt" } });

    await waitFor(() =>
      expect(api.stationDays).toHaveBeenCalledWith({ year: 2026, delivery_week: 42, delivery_station: "ds-Markt" }),
    );
  });

  it("shows the raw day number of a day outside the week", async () => {
    weeks["2026-41"] = [UNKNOWN_DAY];
    renderPage({});

    await userEvent.click(daySelect());
    await waitFor(() => expect(listedDays()).toEqual(["9 - Laden"]));
  });

  it("puts a '-' entry first when asked to", async () => {
    renderPage({ includeNone: true });

    await userEvent.click(daySelect());
    await waitFor(() => expect(listedDays()).toHaveLength(4));
    expect(listedDays()[0]).toBe("-");
  });

  it("is named by its placeholder and shows it while nothing is picked", async () => {
    renderPage({});
    await waitFor(() => expect(api.stationDays).toHaveBeenCalled());
    await settle();

    expect(daySelect()).toHaveAccessibleName(PLACEHOLDER);
    expect(placeholderShown()).toBe(PLACEHOLDER);
    expect(picked).toBeNull();
  });

  it("keeps no pick when the station days fail to load", async () => {
    api.stationDays.mockRejectedValue(Object.assign(new Error("Network Error"), { isAxiosError: true }));
    renderPage({ preserveSelection: true });
    await waitFor(() => expect(api.stationDays).toHaveBeenCalled());
    await settle();

    expect(picked).toBeNull();
    expect(placeholderShown()).toBe(PLACEHOLDER);
  });
});

// ── The pick ────────────────────────────────────────────────────────────────

describe("DeliveryStationDaySelector picks", () => {
  it("sends the chosen station day to the page and to the change callback", async () => {
    renderPage({});

    await chooseDay("delivery.fr - Hof");

    expect(picked).toBe(FRIDAY_HOF.id);
    expect(onDayChange).toHaveBeenCalledTimes(1);
    expect(onDayChange).toHaveBeenCalledWith(FRIDAY_HOF.id);
    expect(shownDay()).toBe("delivery.fr - Hof");
  });

  it("sends 'none' for the '-' entry", async () => {
    renderPage({ includeNone: true });

    await chooseDay("-");

    expect(picked).toBe("none");
    expect(onDayChange).toHaveBeenCalledWith("none");
  });

  it("picks nothing by itself unless asked to keep a station day picked", async () => {
    renderPage({});
    await waitFor(() => expect(api.stationDays).toHaveBeenCalled());
    await settle();

    expect(picked).toBeNull();
    expect(onDayChange).not.toHaveBeenCalled();
  });

  it("keeps a station day the next week also has and falls back to its first one otherwise", async () => {
    const page = renderPage({ preserveSelection: true });
    await waitFor(() => expect(picked).toBe(MONDAY_HOF.id));
    expect(onDayChange).not.toHaveBeenCalled();

    await chooseDay("delivery.di - Markt");
    page.showParams({ year: 2026, delivery_week: 42 });
    await waitFor(() => expect(api.stationDays).toHaveBeenCalledWith({ year: 2026, delivery_week: 42 }));
    await settle();
    expect(picked).toBe(TUESDAY_MARKT.id);

    page.showParams({ year: 2026, delivery_week: 41 });
    await settle();
    await chooseDay("delivery.fr - Hof");
    page.showParams({ year: 2026, delivery_week: 42 });
    await waitFor(() => expect(picked).toBe(TUESDAY_MARKT.id));
  });
});
