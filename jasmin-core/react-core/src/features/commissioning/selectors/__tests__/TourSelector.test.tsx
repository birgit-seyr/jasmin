/**
 * TourSelector: lists the tours of the chosen delivery day and keeps the
 * page's pick one of them. Rendered inside a small page that holds the pick in
 * state, as PackingListBoxes does. The generated commissioning client is the
 * mocking boundary: its delivery-days hook is a real TanStack query around a
 * spy that answers with the farm's delivery days.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type {
  CommissioningSharesDeliveryDaysListParams,
  SharesDeliveryDay,
} from "@shared/api/generated/models";
import { flushMicrotasks } from "@/test/profileRenders";

// A `t` that shows the tour number, so the tours tell apart.
const i18nMock = vi.hoisted(() => ({
  t: (key: string, options?: unknown) => {
    if (typeof options === "string") return options;
    const number = (options as { number?: number } | undefined)?.number;
    return number === undefined ? key : `${key} ${number}`;
  },
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

const api = vi.hoisted(() => ({ deliveryDays: vi.fn() }));

vi.mock("@shared/api/generated/commissioning/commissioning", async () => {
  const { useQuery } = await import("@tanstack/react-query");
  return {
    useCommissioningSharesDeliveryDaysList: function useDeliveryDaysQuery(params?: unknown) {
      return useQuery({
        queryKey: ["/api/commissioning/shares_delivery_days/", params],
        queryFn: async () => api.deliveryDays(params),
      });
    },
  };
});

import TourSelector from "../TourSelector";

// ── Fixtures ────────────────────────────────────────────────────────────────

const deliveryDay = (id: string, numberOfTours: number | undefined): SharesDeliveryDay => ({
  id,
  day_number: 1,
  valid_from: "2026-01-05",
  valid_until: null,
  number_of_tours: numberOfTours,
});

const TUESDAY_THREE_TOURS = deliveryDay("day-tue", 3);
const FRIDAY_TWO_TOURS = deliveryDay("day-fri", 2);
const SATURDAY_NO_COUNT = deliveryDay("day-sat", undefined);
const SUNDAY_ZERO_TOURS = deliveryDay("day-sun", 0);

const TOUR = "commissioning.tour_number";
const ALL_TOURS = "commissioning.all_tours";

// ── Helpers ─────────────────────────────────────────────────────────────────

let picked: number | "all" | null = null;
let pageRenders = 0;
const onTourChange = vi.fn();

type PageProps = {
  day?: string | null;
  initialTour?: number | "all" | null;
  includeAll?: boolean;
  preserveSelection?: boolean;
  year?: number | null;
  week?: number | null;
  filters?: CommissioningSharesDeliveryDaysListParams;
};

function Page({ day = null, initialTour = null, includeAll, preserveSelection, year, week, filters }: PageProps) {
  const [tour, setTour] = useState<number | "all" | null>(initialTour);
  picked = tour;
  pageRenders += 1;
  return (
    <TourSelector
      selectedTour={tour}
      setSelectedTour={setTour}
      onTourChange={onTourChange}
      delivery_day={day}
      include_null_option={includeAll}
      preserveSelection={preserveSelection}
      selectedYear={year}
      selectedWeek={week}
      filters={filters}
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
  return {
    showDay: (day: string | null | undefined) => view.rerender(tree({ ...props, day })),
    rerenderWith: (next: Partial<PageProps>) => view.rerender(tree({ ...props, ...next })),
  };
}

const tourSelect = () => screen.getByRole("combobox");
const selectRoot = () => tourSelect().closest(".ant-select") as HTMLElement;
const shownTour = () => selectRoot().querySelector(".ant-select-selection-item")?.textContent ?? "";

function openDropdown(): HTMLElement {
  const open = document.querySelectorAll<HTMLElement>(".ant-select-dropdown:not(.ant-select-dropdown-hidden)");
  if (open.length === 0) throw new Error("No select dropdown is open");
  return open[open.length - 1];
}

const listedTours = () =>
  Array.from(openDropdown().querySelectorAll(".ant-select-item-option-content")).map((o) => o.textContent);

async function chooseTour(label: string) {
  await userEvent.click(tourSelect());
  const option = Array.from(openDropdown().querySelectorAll(".ant-select-item-option-content")).find(
    (content) => content.textContent === label,
  );
  if (!option) throw new Error(`No tour ${label}`);
  await userEvent.click(option);
}

const settle = () => act(() => flushMicrotasks());

beforeEach(() => {
  picked = null;
  pageRenders = 0;
  onTourChange.mockReset();
  api.deliveryDays
    .mockReset()
    .mockResolvedValue([TUESDAY_THREE_TOURS, FRIDAY_TWO_TOURS, SATURDAY_NO_COUNT, SUNDAY_ZERO_TOURS]);
});

// ── Options ─────────────────────────────────────────────────────────────────

describe("TourSelector options", () => {
  it("lists one tour per tour of the chosen day and picks the first", async () => {
    renderPage({ day: TUESDAY_THREE_TOURS.id });

    await waitFor(() => expect(picked).toBe(1));
    expect(shownTour()).toBe(`${TOUR} 1`);
    expect(tourSelect()).toBeEnabled();

    await userEvent.click(tourSelect());
    expect(listedTours()).toEqual([`${TOUR} 1`, `${TOUR} 2`, `${TOUR} 3`]);
  });

  it("puts every tour first when asked to and picks it", async () => {
    renderPage({ day: FRIDAY_TWO_TOURS.id, includeAll: true });

    await waitFor(() => expect(picked).toBe("all"));
    expect(shownTour()).toBe(ALL_TOURS);
    await userEvent.click(tourSelect());
    expect(listedTours()).toEqual([ALL_TOURS, `${TOUR} 1`, `${TOUR} 2`]);
  });

  it.each([
    ["no tour count", SATURDAY_NO_COUNT.id],
    ["a tour count of 0", SUNDAY_ZERO_TOURS.id],
  ])("counts a day with %s as one tour", async (_case, day) => {
    renderPage({ day });

    await waitFor(() => expect(picked).toBe(1));
    await userEvent.click(tourSelect());
    expect(listedTours()).toEqual([`${TOUR} 1`]);
  });

  it("is disabled and lists nothing without a delivery day", async () => {
    renderPage({ day: null });
    await settle();

    expect(tourSelect()).toBeDisabled();
    expect(picked).toBeNull();
  });

  it("is disabled for a day the list doesn't hold", async () => {
    renderPage({ day: "day-gone" });
    await waitFor(() => expect(api.deliveryDays).toHaveBeenCalled());
    await settle();

    expect(tourSelect()).toBeDisabled();
    expect(picked).toBeNull();
  });

  it("is disabled, without a pick, when the days fail to load", async () => {
    api.deliveryDays.mockRejectedValue(Object.assign(new Error("Network Error"), { isAxiosError: true }));
    renderPage({ day: TUESDAY_THREE_TOURS.id });
    await waitFor(() => expect(api.deliveryDays).toHaveBeenCalled());
    await settle();

    expect(tourSelect()).toBeDisabled();
    expect(picked).toBeNull();
  });

  it("names the select for screen readers", async () => {
    renderPage({ day: TUESDAY_THREE_TOURS.id });
    await waitFor(() => expect(picked).toBe(1));

    expect(tourSelect()).toHaveAccessibleName();
  });

  it("takes its width and spacing from the stylesheet", () => {
    renderPage({ day: TUESDAY_THREE_TOURS.id });

    expect(selectRoot()).toHaveClass("bold-select", "week-selector-select", "tour-selector");
    expect(selectRoot()).not.toHaveAttribute("style");
  });
});

// ── Fetch scope ─────────────────────────────────────────────────────────────

describe("TourSelector fetch scope", () => {
  it("asks for the days running on the selected week's Saturday", async () => {
    renderPage({ day: TUESDAY_THREE_TOURS.id, year: 2026, week: 41 });

    await waitFor(() => expect(api.deliveryDays).toHaveBeenCalledWith({ active_at_date: "2026-10-10" }));
  });

  it("asks for every day without a full year and week", async () => {
    renderPage({ day: TUESDAY_THREE_TOURS.id, year: 2026, week: null });

    await waitFor(() => expect(api.deliveryDays).toHaveBeenCalledWith({}));
  });

  it("lets explicit filters win over the week", async () => {
    renderPage({ day: TUESDAY_THREE_TOURS.id, year: 2026, week: 41, filters: { get_delivery_stations: true } });

    await waitFor(() => expect(api.deliveryDays).toHaveBeenCalledWith({ get_delivery_stations: true }));
    expect(api.deliveryDays).not.toHaveBeenCalledWith({ active_at_date: "2026-10-10" });
  });

  it("asks once and renders no more while the page re-renders with the same filters", async () => {
    const filters = { need_info_on_tours: true };
    const page = renderPage({ day: TUESDAY_THREE_TOURS.id, filters });
    await waitFor(() => expect(picked).toBe(1));
    await settle();
    const rendersSettled = pageRenders;

    page.rerenderWith({ filters });
    page.rerenderWith({ filters });
    await settle();

    expect(api.deliveryDays).toHaveBeenCalledTimes(1);
    // The two re-renders the page asked for, and none the selector caused.
    expect(pageRenders).toBe(rendersSettled + 2);
    expect(picked).toBe(1);
  });

  it("asks again when the filters change", async () => {
    const page = renderPage({ day: TUESDAY_THREE_TOURS.id, filters: { need_info_on_tours: true } });
    await waitFor(() => expect(api.deliveryDays).toHaveBeenCalledTimes(1));

    page.rerenderWith({ filters: { future: true } });

    await waitFor(() => expect(api.deliveryDays).toHaveBeenLastCalledWith({ future: true }));
    expect(api.deliveryDays).toHaveBeenCalledTimes(2);
  });
});

// ── The pick ────────────────────────────────────────────────────────────────

describe("TourSelector keeping the pick", () => {
  it("sends a chosen tour to the page and to the change callback", async () => {
    renderPage({ day: TUESDAY_THREE_TOURS.id });
    await waitFor(() => expect(picked).toBe(1));

    await chooseTour(`${TOUR} 3`);

    expect(picked).toBe(3);
    expect(onTourChange).toHaveBeenCalledTimes(1);
    expect(onTourChange).toHaveBeenCalledWith(3);
    expect(shownTour()).toBe(`${TOUR} 3`);
  });

  it("does not call the change callback for its own automatic pick", async () => {
    renderPage({ day: TUESDAY_THREE_TOURS.id });
    await waitFor(() => expect(picked).toBe(1));
    await settle();

    expect(onTourChange).not.toHaveBeenCalled();
  });

  it("keeps a tour the next day also runs and falls back to tour 1 when it doesn't", async () => {
    const page = renderPage({ day: TUESDAY_THREE_TOURS.id });
    await waitFor(() => expect(picked).toBe(1));
    await chooseTour(`${TOUR} 2`);

    page.showDay(FRIDAY_TWO_TOURS.id);
    await settle();
    expect(picked).toBe(2);

    page.showDay(TUESDAY_THREE_TOURS.id);
    await chooseTour(`${TOUR} 3`);
    page.showDay(FRIDAY_TWO_TOURS.id);
    await waitFor(() => expect(picked).toBe(1));
  });

  it("keeps the page's tour on mount when the day runs it", async () => {
    renderPage({ day: TUESDAY_THREE_TOURS.id, initialTour: 3 });
    await waitFor(() => expect(shownTour()).toBe(`${TOUR} 3`));
    await settle();

    expect(picked).toBe(3);
  });

  it("drops a kept tour when the next day isn't in the list", async () => {
    const page = renderPage({ day: TUESDAY_THREE_TOURS.id });
    await waitFor(() => expect(picked).toBe(1));
    await chooseTour(`${TOUR} 3`);

    page.showDay("day-gone");

    await waitFor(() => expect(picked).toBeNull());
    expect(tourSelect()).toBeDisabled();
    expect(onTourChange).toHaveBeenCalledTimes(1);
  });

  it("keeps the tour while no day is chosen and checks it once one is", async () => {
    const page = renderPage({ day: TUESDAY_THREE_TOURS.id });
    await waitFor(() => expect(picked).toBe(1));
    await chooseTour(`${TOUR} 3`);

    page.showDay(null);
    await settle();
    expect(picked).toBe(3);

    page.showDay(FRIDAY_TWO_TOURS.id);
    await waitFor(() => expect(picked).toBe(1));
  });

  it("without preserving, keeps an existing pick even when the day doesn't run it", async () => {
    renderPage({ day: FRIDAY_TWO_TOURS.id, initialTour: 3, preserveSelection: false });
    await waitFor(() => expect(api.deliveryDays).toHaveBeenCalled());
    await settle();

    expect(picked).toBe(3);
  });
});
