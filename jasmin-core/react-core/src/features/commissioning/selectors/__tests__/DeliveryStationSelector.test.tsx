/**
 * DeliveryStationSelector: lists the active stations of a delivery day (or
 * every active station) and, when asked to, keeps the page's pick one of them.
 * Rendered inside a small page that holds the pick in state. The generated
 * commissioning client is the mocking boundary: its stations hook is a real
 * TanStack query around a spy that answers with the stations of each day.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { DeliveryStation } from "@shared/api/generated/models";
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

const api = vi.hoisted(() => ({ stations: vi.fn() }));

vi.mock("@shared/api/generated/commissioning/commissioning", async () => {
  const { useQuery } = await import("@tanstack/react-query");
  return {
    useCommissioningDeliveryStationsList: function useStationsQuery(
      params: unknown,
      options?: { query?: { enabled?: boolean } },
    ) {
      return useQuery({
        queryKey: ["/api/commissioning/delivery_stations/", params],
        queryFn: async () => api.stations(params),
        enabled: options?.query?.enabled,
      });
    },
    getCommissioningDeliveryStationsListQueryOptions: () => ({}),
  };
});

import DeliveryStationSelector from "../DeliveryStationSelector";

// ── Fixtures ────────────────────────────────────────────────────────────────

const station = (id: string, shortName: string | null, companyName: string | null = null) =>
  ({ id, short_name: shortName, company_name: companyName }) as DeliveryStation;

const MARKT = station("ds-markt", "Markt");
const HOF = station("ds-hof", "Hof");
// A station without a short name goes by its company name.
const LADEN = station("ds-laden", null, "Bioladen GmbH");
const NAMELESS = station("ds-nameless", null, null);

/** The stations of each delivery day; the list of every station under "". */
let stationsByDay: Record<string, DeliveryStation[]>;

type StationParams = { is_active?: boolean; delivery_day?: string };

const answerFromDays = async (params: StationParams) => [...(stationsByDay[params.delivery_day ?? ""] ?? [])];

// ── Helpers ─────────────────────────────────────────────────────────────────

let picked: string | null = null;
const onStationChange = vi.fn();

type PageProps = {
  day?: string | null;
  initialStation?: string | null;
  includeNone?: boolean;
  preserveSelection?: boolean;
  allStations?: boolean;
};

function Page({ day = null, initialStation = null, includeNone, preserveSelection, allStations }: PageProps) {
  const [picks, setPick] = useState<string | null>(initialStation);
  picked = picks;
  return (
    <DeliveryStationSelector
      selectedDeliveryStation={picks}
      setSelectedDeliveryStation={setPick}
      onDeliveryStationChange={onStationChange}
      delivery_day={day}
      include_null_option={includeNone}
      preserveSelection={preserveSelection}
      allStations={allStations}
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
  return { showDay: (day: string | null) => view.rerender(tree({ ...props, day })) };
}

const PLACEHOLDER = "placeholder.delivery_station_selector";

const stationSelect = () => screen.getByRole("combobox", { name: PLACEHOLDER });
const selectRoot = () => stationSelect().closest(".ant-select") as HTMLElement;
const shownStation = () => selectRoot().querySelector(".ant-select-selection-item")?.textContent ?? "";
const placeholderShown = () =>
  selectRoot().querySelector(".ant-select-selection-placeholder")?.textContent ?? "";

function openDropdown(): HTMLElement {
  const open = document.querySelectorAll<HTMLElement>(".ant-select-dropdown:not(.ant-select-dropdown-hidden)");
  if (open.length === 0) throw new Error("No select dropdown is open");
  return open[open.length - 1];
}

const listedStations = () =>
  Array.from(openDropdown().querySelectorAll(".ant-select-item-option-content")).map((o) => o.textContent);

async function chooseStation(label: string) {
  await userEvent.click(stationSelect());
  const option = Array.from(openDropdown().querySelectorAll(".ant-select-item-option-content")).find(
    (content) => content.textContent === label,
  );
  if (!option) throw new Error(`No station ${label}`);
  await userEvent.click(option);
}

const settle = () => act(() => flushMicrotasks());

beforeEach(() => {
  picked = null;
  onStationChange.mockReset();
  stationsByDay = {
    "day-tue": [MARKT, HOF, LADEN],
    "day-fri": [HOF],
    "day-sun": [],
    "": [MARKT, HOF, LADEN, NAMELESS],
  };
  api.stations.mockReset().mockImplementation(answerFromDays);
});

// ── Fetch scope and options ─────────────────────────────────────────────────

describe("DeliveryStationSelector options", () => {
  it("lists the active stations of the day, by short name or else company name", async () => {
    renderPage({ day: "day-tue" });

    await waitFor(() => expect(api.stations).toHaveBeenCalledWith({ is_active: true, delivery_day: "day-tue" }));
    await userEvent.click(stationSelect());
    await waitFor(() => expect(listedStations()).toEqual(["Markt", "Hof", "Bioladen GmbH"]));
  });

  it("waits for a delivery day before asking for stations", async () => {
    renderPage({ day: null });
    await settle();

    expect(api.stations).not.toHaveBeenCalled();
    expect(placeholderShown()).toBe(PLACEHOLDER);
  });

  it("lists every active station without a day when asked for all stations", async () => {
    renderPage({ allStations: true });

    await waitFor(() => expect(api.stations).toHaveBeenCalledTimes(1));
    expect(api.stations.mock.calls[0][0]).toEqual({ is_active: true });
    await userEvent.click(stationSelect());
    await waitFor(() => expect(listedStations()).toHaveLength(4));
  });

  it("puts a '-' entry first when asked to, and sends 'none' for it", async () => {
    renderPage({ day: "day-tue", includeNone: true });
    await waitFor(() => expect(api.stations).toHaveBeenCalled());
    await userEvent.click(stationSelect());
    await waitFor(() => expect(listedStations()).toEqual(["-", "Markt", "Hof", "Bioladen GmbH"]));

    const noneOption = Array.from(openDropdown().querySelectorAll(".ant-select-item-option-content")).find(
      (content) => content.textContent === "-",
    );
    await userEvent.click(noneOption as Element);

    expect(picked).toBe("none");
    expect(onStationChange).toHaveBeenCalledWith("none");
  });

  it("is named by its placeholder", () => {
    renderPage({ day: "day-tue" });

    expect(stationSelect()).toHaveAccessibleName(PLACEHOLDER);
  });

  it("takes its width and spacing from the stylesheet", () => {
    renderPage({ day: "day-tue" });

    expect(selectRoot()).toHaveClass("bold-select", "week-selector-select", "delivery-station-selector");
    expect(selectRoot()).not.toHaveAttribute("style");
  });

  it("shows the placeholder when the stations fail to load", async () => {
    api.stations.mockRejectedValue(Object.assign(new Error("Network Error"), { isAxiosError: true }));
    renderPage({ day: "day-tue", preserveSelection: true });
    await waitFor(() => expect(api.stations).toHaveBeenCalled());
    await settle();

    expect(picked).toBeNull();
    expect(placeholderShown()).toBe(PLACEHOLDER);
  });
});

// ── The pick ────────────────────────────────────────────────────────────────

describe("DeliveryStationSelector picks", () => {
  it("sends the chosen station's id to the page and to the change callback", async () => {
    renderPage({ day: "day-tue" });
    await waitFor(() => expect(api.stations).toHaveBeenCalled());

    await chooseStation("Hof");

    expect(picked).toBe(HOF.id);
    expect(onStationChange).toHaveBeenCalledTimes(1);
    expect(onStationChange).toHaveBeenCalledWith(HOF.id);
    expect(shownStation()).toBe("Hof");
  });

  it("leaves 'no station' alone unless asked to keep a station picked", async () => {
    renderPage({ day: "day-tue" });
    await waitFor(() => expect(api.stations).toHaveBeenCalled());
    await settle();

    expect(picked).toBeNull();
    expect(placeholderShown()).toBe(PLACEHOLDER);
  });

  it("picks the first station on mount when keeping a station picked", async () => {
    renderPage({ day: "day-tue", preserveSelection: true });

    await waitFor(() => expect(picked).toBe(MARKT.id));
    expect(shownStation()).toBe("Markt");
    expect(onStationChange).not.toHaveBeenCalled();
  });

  it("keeps a station the next day also serves and falls back to its first one otherwise", async () => {
    const page = renderPage({ day: "day-tue", preserveSelection: true });
    await waitFor(() => expect(picked).toBe(MARKT.id));
    await chooseStation("Hof");

    page.showDay("day-fri");
    await waitFor(() => expect(api.stations).toHaveBeenCalledWith({ is_active: true, delivery_day: "day-fri" }));
    await settle();
    expect(picked).toBe(HOF.id);

    page.showDay("day-tue");
    await settle();
    await chooseStation("Bioladen GmbH");
    page.showDay("day-fri");
    await waitFor(() => expect(picked).toBe(HOF.id));
  });

  it("lets a kept station go when the next day serves none", async () => {
    const page = renderPage({ day: "day-tue", preserveSelection: true, initialStation: MARKT.id });
    await waitFor(() => expect(shownStation()).toBe("Markt"));

    page.showDay("day-sun");
    await waitFor(() => expect(api.stations).toHaveBeenCalledWith({ is_active: true, delivery_day: "day-sun" }));
    await settle();

    expect(picked).toBeNull();
    expect(shownStation()).toBe("");
    expect(placeholderShown()).toBe(PLACEHOLDER);
  });
});
