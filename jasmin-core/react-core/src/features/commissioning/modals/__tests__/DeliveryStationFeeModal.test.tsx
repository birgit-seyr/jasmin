/**
 * DeliveryStationFeeModal: the fee the farm pays one delivery station for every
 * box delivered there, net of VAT, saved with a partial update. Rendered for
 * real — the AntD form, EditFormModal and useModalMutation — with the
 * generated client, the tenant and the toasts mocked. The client answers from
 * an in-memory server that checks a fee the way the backend's serializer does
 * (at most six digits before the decimal point and two after it). A probe
 * beside the dialog holds the delivery station list the way the list page
 * does, so a test sees that list reload.
 *
 * The tenant writes numbers the English way, with a decimal point, and the
 * amounts below are shown and typed in that format — except under the last
 * heading, where the tenant writes them the German way, with a decimal comma.
 */

import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { DeliveryStation } from "@shared/api/generated/models";
import { flushMicrotasks } from "@/test/profileRenders";

// One ``t`` for every call, as the real hook keeps it stable across renders.
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

// The tenant's settings, per test; an unset setting falls back to the caller's default.
const tenantSettings = vi.hoisted(() => ({ values: {} as Record<string, unknown> }));
vi.mock("@hooks/configuration/useTenant", async () => {
  const { makeUseTenantMock } = await import("@/test/tenantMock");
  const tenant = makeUseTenantMock({
    getSetting: (key: string, defaultValue?: unknown) =>
      key in tenantSettings.values ? tenantSettings.values[key] : defaultValue,
  });
  return { useTenant: () => tenant };
});

const notify = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn(), warning: vi.fn(), info: vi.fn() }));
vi.mock("@shared/utils/notify", () => ({ default: notify }));

const api = vi.hoisted(() => ({ updateStation: vi.fn(), listStations: vi.fn() }));

vi.mock("@shared/api/generated/commissioning/commissioning", () => ({
  getCommissioningDeliveryStationsListQueryKey: (params?: unknown) => [
    "/api/commissioning/delivery_stations/",
    ...(params ? [params] : []),
  ],
  commissioningDeliveryStationsPartialUpdate: (id: string, station: unknown) =>
    api.updateStation(id, station),
}));

import { getCommissioningDeliveryStationsListQueryKey } from "@shared/api/generated/commissioning/commissioning";
import DeliveryStationFeeModal from "../DeliveryStationFeeModal";

// ── Fixtures ────────────────────────────────────────────────────────────────

type Row = Record<string, unknown>;

/** A station as the list endpoint carries it, fees as decimal strings. */
function station(overrides: Partial<DeliveryStation> & { id: string }): DeliveryStation {
  return {
    is_active: true, short_name: null, number: null, address: "", zip_code: "", city: "",
    fee_per_box_net: "0.00", fee_per_month_net: "0.00", fee_per_year_net: "0.00", fees_billing_period: null,
    ...overrides,
  };
}

// Paid per box, settled monthly.
const SCHOOL = station({
  id: "st-school", number: 2, short_name: "School", address: "Schulweg 4", zip_code: "4040", city: "Linz",
  fee_per_box_net: "1.50", fees_billing_period: "MONTHLY",
});
const FARM_SHOP = station({
  id: "st-farm-shop", number: 1, short_name: "Farm shop", address: "Dorfstraße 1", zip_code: "4020",
  city: "Linz", fee_per_box_net: "0.80",
});

const FEE_FIELDS = ["fee_per_box_net", "fee_per_month_net", "fee_per_year_net"];

/** What the backend's serializer says about a fee, or null when it takes it. */
function feeRefusal(value: unknown): string | null {
  if (value === null) return "This field may not be null.";
  const text = String(value);
  if (!/^-?\d+(\.\d+)?$/.test(text)) return "A valid number is required.";
  const [whole, fraction = ""] = text.replace("-", "").split(".");
  if (whole.replace(/^0+(?=\d)/, "").length > 6) {
    return "Ensure that there are no more than 6 digits before the decimal point.";
  }
  if (fraction.length > 2) return "Ensure that there are no more than 2 decimal places.";
  return null;
}

/** A rejected request as axios hands it over, carrying the server's body. */
const httpError = (status: number, data: Row) =>
  Object.assign(new Error(`Request failed with status code ${status}`), {
    isAxiosError: true,
    response: { status, data },
  });

// What the server currently holds.
let serverStations: DeliveryStation[] = [];

const stored = (id: string) => serverStations.find((each) => each.id === id);

beforeEach(() => {
  tenantSettings.values = { number_locale: "en-US" };
  Object.values(notify).forEach((fn) => fn.mockReset());
  serverStations = [SCHOOL, FARM_SHOP];
  api.listStations.mockReset().mockImplementation(async () => [...serverStations]);
  api.updateStation.mockReset().mockImplementation(async (id: string, payload: Row) => {
    const current = stored(id);
    if (!current) throw httpError(404, { code: "delivery_station.not_found", message: "Not found." });
    for (const field of FEE_FIELDS.filter((each) => each in payload)) {
      const message = feeRefusal(payload[field]);
      if (message) {
        throw httpError(400, { code: "validation_error", message, field, details: { [field]: [message] } });
      }
    }
    const saved = { ...current, ...payload, id } as DeliveryStation;
    serverStations = serverStations.map((each) => (each.id === id ? saved : each));
    return saved;
  });
});

// ── Helpers ─────────────────────────────────────────────────────────────────

/** Holds the delivery station list the way the list page does. */
function StationListProbe() {
  useQuery({
    queryKey: getCommissioningDeliveryStationsListQueryKey(),
    queryFn: () => api.listStations(),
  });
  return null;
}

function renderModal(deliveryStation: DeliveryStation | null = SCHOOL) {
  const user = userEvent.setup();
  const onClose = vi.fn();
  const onSaved = vi.fn();
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 }, mutations: { retry: false } },
  });
  const modalFor = (opened: DeliveryStation | null) => (
    <QueryClientProvider client={queryClient}>
      <StationListProbe />
      <DeliveryStationFeeModal open deliveryStation={opened} onClose={onClose} onSaved={onSaved} />
    </QueryClientProvider>
  );
  const { rerender } = render(modalFor(deliveryStation));
  return { user, onClose, onSaved, openFor: (opened: DeliveryStation) => rerender(modalFor(opened)) };
}

/** Renders the dialog for ``deliveryStation`` once the probe holds the station list. */
async function renderLoaded(deliveryStation: DeliveryStation = SCHOOL) {
  const rendered = renderModal(deliveryStation);
  await waitFor(() => expect(api.listStations).toHaveBeenCalledTimes(1));
  return rendered;
}

const FEE_PER_BOX = "delivery_stations.fee_per_box_net";

type User = ReturnType<typeof userEvent.setup>;

const dialog = () => screen.getByRole("dialog");
const feeInput = () => within(dialog()).getByLabelText(FEE_PER_BOX);
// The name is matched loosely: while saving, AntD prefixes the label with its
// loading icon.
const saveButton = () => within(dialog()).getByRole("button", { name: /common\.save/ });
const cancelButton = () => within(dialog()).getByRole("button", { name: "common.cancel" });

async function typeFee(user: User, text: string) {
  await user.clear(feeInput());
  await user.type(feeInput(), text);
}

/** The amount the fee field shows, read past any grouping commas. */
const shownAmount = () => Number((feeInput() as HTMLInputElement).value.replace(/,/g, ""));

/** The fee per box the last save sent. */
const sentFee = () => (api.updateStation.mock.lastCall?.[1] as Row | undefined)?.fee_per_box_net;
const savedOnce = () => waitFor(() => expect(api.updateStation).toHaveBeenCalledTimes(1));

// ── Showing a station's fee ─────────────────────────────────────────────────

describe("DeliveryStationFeeModal showing a station's fee", () => {
  it("renders nothing without a delivery station", () => {
    renderModal(null);

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("names the station in its title and says the fees are net", async () => {
    await renderLoaded();

    expect(within(dialog()).getByText("delivery_stations.fee_title — School")).toBeInTheDocument();
    expect(within(dialog()).getByText("delivery_stations.fee_intro")).toBeInTheDocument();
  });

  it.each([
    ["EUR", "€"],
    ["CHF", "CHF"],
  ])("shows the station's fee per box in the tenant's currency, %s", async (currency, symbol) => {
    tenantSettings.values = { ...tenantSettings.values, currency };
    await renderLoaded();

    await waitFor(() => expect(feeInput()).toHaveValue("1.50"));
    const field = feeInput().closest<HTMLElement>(".ant-input-number-affix-wrapper");
    expect(field).not.toBeNull();
    expect(within(field!).getByText(symbol)).toBeInTheDocument();
  });

  it("shows the fee of the station it is opened for", async () => {
    const { openFor } = await renderLoaded(SCHOOL);
    await waitFor(() => expect(feeInput()).toHaveValue("1.50"));

    openFor(FARM_SHOP);

    await waitFor(() => expect(feeInput()).toHaveValue("0.80"));
    expect(within(dialog()).getByText("delivery_stations.fee_title — Farm shop")).toBeInTheDocument();
  });
});

// ── Saving ──────────────────────────────────────────────────────────────────

describe("DeliveryStationFeeModal saving", () => {
  it("saves a changed fee per box as a decimal string under the station's id, keeping its other fees", async () => {
    const { user, onClose, onSaved } = await renderLoaded();

    await typeFee(user, "2.75");
    await user.click(saveButton());

    await savedOnce();
    expect(api.updateStation.mock.calls[0][0]).toBe("st-school");
    expect(sentFee()).toBe("2.75");
    expect(stored("st-school")).toEqual({ ...SCHOOL, fee_per_box_net: "2.75" });
    expect(notify.success).toHaveBeenCalledWith("delivery_stations.fee_saved");
    expect(notify.error).not.toHaveBeenCalled();
    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
    expect(onSaved).toHaveBeenCalledTimes(1);
  });

  it("sends an unchanged fee back as a decimal string of the same amount", async () => {
    const { user } = await renderLoaded();
    await waitFor(() => expect(feeInput()).toHaveValue("1.50"));

    await user.click(saveButton());

    await savedOnce();
    expect(typeof sentFee()).toBe("string");
    expect(Number(sentFee())).toBe(1.5);
    expect(stored("st-school")).toEqual(SCHOOL);
  });

  it("reloads the delivery station list and tells the page only once it is back", async () => {
    const { user, onSaved, onClose } = await renderLoaded();
    let deliver: (stations: DeliveryStation[]) => void = () => {};
    api.listStations.mockImplementation(() => new Promise((resolve) => (deliver = resolve)));

    await typeFee(user, "2");
    await user.click(saveButton());

    await waitFor(() => expect(api.listStations).toHaveBeenCalledTimes(2));
    await flushMicrotasks();
    expect(onSaved).not.toHaveBeenCalled();
    expect(onClose).not.toHaveBeenCalled();

    deliver([...serverStations]);

    await waitFor(() => expect(onSaved).toHaveBeenCalledTimes(1));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("saves on Enter", async () => {
    const { user, onClose } = await renderLoaded();

    await typeFee(user, "3{Enter}");

    await savedOnce();
    expect(sentFee()).toBe("3");
    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
  });

  it("never sends a fee below zero", async () => {
    const { user } = await renderLoaded();

    await typeFee(user, "-2");
    await user.click(saveButton());
    await flushMicrotasks();

    for (const [, payload] of api.updateStation.mock.calls) {
      expect(Number((payload as Row).fee_per_box_net)).toBeGreaterThanOrEqual(0);
    }
    expect(Number(stored("st-school")?.fee_per_box_net)).toBeGreaterThanOrEqual(0);
  });

  it("keeps the dialog open with the typed fee and shows the server's reason when the fee is refused", async () => {
    const { user, onClose, onSaved } = await renderLoaded();

    await typeFee(user, "1234567");
    await user.click(saveButton());

    await waitFor(() =>
      expect(notify.error).toHaveBeenCalledWith(
        "Ensure that there are no more than 6 digits before the decimal point.",
      ),
    );
    expect(notify.success).not.toHaveBeenCalled();
    expect(onSaved).not.toHaveBeenCalled();
    expect(onClose).not.toHaveBeenCalled();
    expect(shownAmount()).toBe(1234567);
    expect(saveButton()).toBeEnabled();
    expect(stored("st-school")).toEqual(SCHOOL);
    expect(api.listStations).toHaveBeenCalledTimes(1);
  });

  it("falls back to its own message when the failure carries none", async () => {
    api.updateStation.mockRejectedValue({ isAxiosError: true, response: {} });
    const { user } = await renderLoaded();

    await typeFee(user, "2");
    await user.click(saveButton());

    await waitFor(() => expect(notify.error).toHaveBeenCalledWith("delivery_stations.fee_save_error"));
    expect(dialog()).toBeInTheDocument();
  });

  it("blocks a second save and the cancel button while a save is in flight", async () => {
    let answer: (saved: DeliveryStation) => void = () => {};
    api.updateStation.mockImplementation(() => new Promise((resolve) => (answer = resolve)));
    const { user, onClose } = await renderLoaded();

    await typeFee(user, "2");
    await user.click(saveButton());

    await waitFor(() => expect(cancelButton()).toBeDisabled());
    await user.click(saveButton());
    answer({ ...SCHOOL, fee_per_box_net: "2.00" });

    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
    expect(api.updateStation).toHaveBeenCalledTimes(1);
  });

  it("saves once when Enter is pressed again while the save runs", async () => {
    let answer: (saved: DeliveryStation) => void = () => {};
    api.updateStation.mockImplementation(() => new Promise((resolve) => (answer = resolve)));
    const { user, onClose } = await renderLoaded();

    await typeFee(user, "2{Enter}");
    await savedOnce();
    await user.type(feeInput(), "{Enter}{Enter}");

    expect(api.updateStation).toHaveBeenCalledTimes(1);
    answer({ ...SCHOOL, fee_per_box_net: "2.00" });
    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
    expect(api.updateStation).toHaveBeenCalledTimes(1);
  });

  it("saves once when Enter follows a click on save while the save runs", async () => {
    let answer: (saved: DeliveryStation) => void = () => {};
    api.updateStation.mockImplementation(() => new Promise((resolve) => (answer = resolve)));
    const { user, onClose } = await renderLoaded();

    await typeFee(user, "2");
    await user.click(saveButton());
    await savedOnce();
    await user.type(feeInput(), "{Enter}");

    expect(api.updateStation).toHaveBeenCalledTimes(1);
    answer({ ...SCHOOL, fee_per_box_net: "2.00" });
    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
    expect(api.updateStation).toHaveBeenCalledTimes(1);
  });

  it("closes without saving on cancel", async () => {
    const { user, onClose, onSaved } = await renderLoaded();

    await typeFee(user, "2");
    await user.click(cancelButton());

    expect(onClose).toHaveBeenCalledTimes(1);
    expect(onSaved).not.toHaveBeenCalled();
    expect(api.updateStation).not.toHaveBeenCalled();
  });
});

// ── A tenant that writes a decimal comma ────────────────────────────────────

describe("DeliveryStationFeeModal on a tenant that writes a decimal comma", () => {
  beforeEach(() => {
    tenantSettings.values = { number_locale: "de-DE" };
  });

  it("shows the station's fee with a decimal comma", async () => {
    await renderLoaded();

    await waitFor(() => expect(feeInput()).toHaveValue("1,50"));
  });

  it("saves a fee typed with a decimal comma as a decimal string", async () => {
    const { user } = await renderLoaded();

    await typeFee(user, "2,50");
    await user.click(saveButton());

    await savedOnce();
    expect(sentFee()).toBe("2.5");
    expect(stored("st-school")).toEqual({ ...SCHOOL, fee_per_box_net: "2.5" });
  });

  it("reads a typed decimal point too, and shows the fee with a comma", async () => {
    const { user } = await renderLoaded();

    await typeFee(user, "2.75");
    await user.tab();
    expect(feeInput()).toHaveValue("2,75");
    await user.click(saveButton());

    await savedOnce();
    expect(sentFee()).toBe("2.75");
  });
});

// ── Monthly and yearly fees ─────────────────────────────────────────────────

describe("DeliveryStationFeeModal monthly and yearly fees", () => {
  // Paid 35.00 a month.
  const CHURCH_HALL = station({
    id: "st-church-hall", number: 3, short_name: "Church hall", fee_per_month_net: "35.00",
  });

  beforeEach(() => {
    serverStations = [SCHOOL, FARM_SHOP, CHURCH_HALL];
  });

  const monthInput = () => within(dialog()).getByLabelText("delivery_stations.fee_per_month_net");
  const yearInput = () => within(dialog()).getByLabelText("delivery_stations.fee_per_year_net");
  const sent = () => api.updateStation.mock.lastCall?.[1] as Row | undefined;

  it("shows a station's fee per month and per year", async () => {
    await renderLoaded(CHURCH_HALL);

    await waitFor(() => expect(monthInput()).toHaveValue("35.00"));
    expect(yearInput()).toHaveValue("0.00");
    expect(feeInput()).toHaveValue("0.00");
  });

  it("saves a changed fee per month as a decimal string", async () => {
    const { user, onClose } = await renderLoaded(CHURCH_HALL);

    await user.clear(monthInput());
    await user.type(monthInput(), "40.50");
    await user.click(saveButton());

    await savedOnce();
    expect(sent()?.fee_per_month_net).toBe("40.5");
    expect(stored("st-church-hall")?.fee_per_month_net).toBe("40.5");
    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
  });

  it("saves a fee per year in place of a cleared fee per month", async () => {
    const { user } = await renderLoaded(CHURCH_HALL);

    await user.clear(monthInput());
    await user.clear(yearInput());
    await user.type(yearInput(), "400");
    await user.click(saveButton());

    await savedOnce();
    expect(stored("st-church-hall")).toEqual({ ...CHURCH_HALL, fee_per_month_net: "0", fee_per_year_net: "400" });
  });

  it("never sends a fee per month or per year below zero", async () => {
    const { user } = await renderLoaded(CHURCH_HALL);

    await user.clear(monthInput());
    await user.type(monthInput(), "-5");
    await user.click(saveButton());
    await flushMicrotasks();

    for (const [, payload] of api.updateStation.mock.calls) {
      expect(Number((payload as Row).fee_per_month_net)).toBeGreaterThanOrEqual(0);
    }
  });

  it("refuses a second fee, as a station is paid in one way only", async () => {
    const { user, onClose } = await renderLoaded(SCHOOL);

    await user.clear(monthInput());
    await user.type(monthInput(), "20");
    await user.click(saveButton());

    expect(await within(dialog()).findAllByText("delivery_stations.fee_only_one")).not.toHaveLength(0);
    await flushMicrotasks();
    expect(api.updateStation).not.toHaveBeenCalled();
    expect(onClose).not.toHaveBeenCalled();
  });
});

// ── Clearing a fee ──────────────────────────────────────────────────────────

describe("DeliveryStationFeeModal clearing a fee", () => {
  it("saves a cleared fee per box as no fee, which the server takes", async () => {
    const { user, onClose } = await renderLoaded();

    await user.clear(feeInput());
    await user.click(saveButton());

    await savedOnce();
    expect(sentFee()).toBe("0");
    expect(stored("st-school")?.fee_per_box_net).toBe("0");
    expect(notify.error).not.toHaveBeenCalled();
    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
  });
});
