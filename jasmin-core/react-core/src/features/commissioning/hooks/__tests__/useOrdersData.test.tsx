/**
 * useOrdersData: the state behind the Orders page — the order of one
 * reseller's delivery slot with its order lines and crate lines, and the API
 * functions its three tables save through.
 *
 * An order line's deposit crates are crate rows the server derives from the
 * line, and a crate line is a group of crate rows of one crate type, price,
 * discount and VAT rate, named by one of its rows. Saving or deleting an order
 * line therefore changes the crate lines on the server, and so can saving a
 * crate line, which merges with another line priced like it. These tests
 * check that the crate list is read again after each of those, also when the
 * save is the one that creates the order, and that only the crate table waits
 * for it.
 *
 * The generated commissioning client is the mocking boundary: its list hooks
 * are real TanStack queries around spies that answer from an in-memory order,
 * and its writes change that order the way the backend does. The clock is
 * frozen on Wednesday 7 October 2026, which the hook's selected week and day
 * start from.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// One ``t`` for every render, as react-i18next hands out: the note autosave
// restarts its debounce whenever ``t`` changes.
vi.mock("react-i18next", () => {
  const translation = {
    t: (key: string, fallback?: unknown) =>
      typeof fallback === "string" ? fallback : key,
    i18n: { language: "de", changeLanguage: () => Promise.resolve() },
  };
  return {
    useTranslation: () => translation,
    Trans: ({ children }: { children?: React.ReactNode }) => <>{children}</>,
    initReactI18next: { type: "3rdParty", init: () => {} },
  };
});

vi.mock("@hooks/configuration/useTenant", async () => {
  const { makeUseTenantMock } = await import("@/test/tenantMock");
  const tenant = makeUseTenantMock();
  return { useTenant: () => tenant };
});

// Finalizing renders and uploads PDFs.
vi.mock(
  "@features/commissioning/pdfs/forResellers/generateDeliveryNotePDF",
  () => ({ generateAndUploadDeliveryNotePDF: vi.fn() }),
);
vi.mock("@features/commissioning/pdfs/forResellers/generateInvoicePDF", () => ({
  generateAndUploadInvoicePDF: vi.fn(),
}));

const notifyMock = vi.hoisted(() => ({
  error: vi.fn(),
  warning: vi.fn(),
}));
vi.mock("@shared/utils", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@shared/utils")>()),
  notify: notifyMock,
}));

const api = vi.hoisted(() => ({
  orderContents: vi.fn(),
  daysWithOrders: vi.fn(),
  crateContents: vi.fn(),
  createOrderContent: vi.fn(),
  updateOrderContent: vi.fn(),
  destroyOrderContent: vi.fn(),
  createCrateContent: vi.fn(),
  updateCrateContent: vi.fn(),
  destroyCrateContent: vi.fn(),
  setOrderNote: vi.fn(),
}));

vi.mock("@shared/api/generated/commissioning/commissioning", async () => {
  const { useQuery } = await import("@tanstack/react-query");
  const keyOf = (path: string) => (params?: unknown) => [
    path,
    ...(params ? [params] : []),
  ];
  const orderContentsKey = keyOf("/api/commissioning/order_contents/");
  const daysKey = keyOf("/api/commissioning/days_with_orders/");
  const crateContentsKey = keyOf("/api/commissioning/crate_contents/");
  type QueryOptions = { query?: { enabled?: boolean } };
  return {
    getCommissioningOrderContentsListQueryKey: orderContentsKey,
    getCommissioningDaysWithOrdersRetrieveQueryKey: daysKey,
    getCommissioningCrateContentsListQueryKey: crateContentsKey,
    getCommissioningDeliveryNotesRetrieveQueryKey: (id: string) => [
      `/api/commissioning/delivery_notes/${id}/`,
    ],
    getCommissioningInvoicesRetrieveQueryKey: (id: string) => [
      `/api/commissioning/invoices/${id}/`,
    ],
    useCommissioningOrderContentsList: (params: unknown, options?: QueryOptions) =>
      useQuery({
        queryKey: orderContentsKey(params),
        queryFn: async () => api.orderContents(params),
        enabled: options?.query?.enabled,
      }),
    useCommissioningDaysWithOrdersRetrieve: (params: unknown) =>
      useQuery({
        queryKey: daysKey(params),
        queryFn: async () => api.daysWithOrders(params),
      }),
    useCommissioningCrateContentsList: (params: unknown, options?: QueryOptions) =>
      useQuery({
        queryKey: crateContentsKey(params),
        queryFn: async () => api.crateContents(params),
        enabled: options?.query?.enabled,
      }),
    commissioningOrderContentsCreate: (line: unknown) =>
      api.createOrderContent(line),
    commissioningOrderContentsPartialUpdate: (id: string, line: unknown) =>
      api.updateOrderContent(id, line),
    commissioningOrderContentsDestroy: (id: string) => api.destroyOrderContent(id),
    commissioningCrateContentsCreate: (line: unknown) =>
      api.createCrateContent(line),
    commissioningCrateContentsPartialUpdate: (id: string, line: unknown) =>
      api.updateCrateContent(id, line),
    commissioningCrateContentsDestroy: (id: string, params: unknown) =>
      api.destroyCrateContent(id, params),
    commissioningSetOrderNotePartialUpdate: (id: string, note: unknown) =>
      api.setOrderNote(id, note),
  };
});

import { generateAndUploadDeliveryNotePDF } from "@features/commissioning/pdfs/forResellers/generateDeliveryNotePDF";
import { generateAndUploadInvoicePDF } from "@features/commissioning/pdfs/forResellers/generateInvoicePDF";
import { useOrdersData } from "../useOrdersData";

// ── The order on the server ─────────────────────────────────────────────────

const NOW = new Date(2026, 9, 7, 12, 0);

const ORDER = {
  order_id: "order-1",
  order_number: "2026-031",
  order_number_prefix: "BE",
  order_is_finalized: false,
  order_note: "",
  harvesting_day: null,
  packing_day: null,
  washing_day: null,
  cleaning_day: null,
  delivery_note_id: null,
  delivery_note_number: null,
  delivery_note_prefix: null,
  delivery_note_is_finalized: false,
  invoice_id: null,
  invoice_number: null,
  invoice_prefix: null,
  has_invoice: false,
  has_finalized_invoice: false,
};

const NO_DAY_DEFAULTS = {
  default_harvesting_day: null,
  default_packing_day: null,
  default_washing_day: null,
  default_cleaning_day: null,
  default_last_possible_ordering_day: null,
  default_last_possible_ordering_time: null,
};

// 10 kg of carrots from an offer packed in euro crates, one per 2 kg.
const CARROTS = {
  id: "oc-1",
  is_placeholder: false,
  order_id: "order-1",
  order_number: "2026-031",
  order_number_prefix: "BE",
  order_is_finalized: false,
  offer: "offer-carrots",
  offer_name: "Carrots",
  share_article: "art-carrot",
  share_article_name: "Carrots",
  amount: "10.000",
  unit: "KG",
  size: "M",
  price_per_unit: "2.00",
  rabatt: null,
  tax_rate: "7.00",
  note: null,
};

// The same offer before the slot has an order: a placeholder line, which a
// save turns into an order line.
const CARROTS_OFFER = {
  ...CARROTS,
  id: "offer-carrots",
  is_placeholder: true,
  order_id: null,
  order_number: null,
  order_number_prefix: null,
  share_article: null,
  share_article_name: null,
  amount: null,
  price_per_unit: null,
};

type CrateLine = { id: string; crate_type: string; amount: number } & Record<
  string,
  unknown
>;

const crateLine = (
  id: string,
  crateType: string,
  amount: number,
  pricing: { price_per_unit: string; rabatt: number },
): CrateLine => ({
  id,
  crate_type: crateType,
  crate_type_name: crateType === "ct-euro" ? "Euro" : "Small",
  amount,
  ...pricing,
  line_netto: "0.00",
  tax_rate: 19,
});

// The carrots' deposit, and small crates the office added at two prices.
const CARROT_DEPOSIT = crateLine("ct-euro_row-3", "ct-euro", 5, {
  price_per_unit: "1.50",
  rabatt: 0,
});
const SMALL_DISCOUNTED = crateLine("ct-small_row-5", "ct-small", 2, {
  price_per_unit: "1.00",
  rabatt: 10,
});
const SMALL_FULL_PRICE = crateLine("ct-small_row-6", "ct-small", 3, {
  price_per_unit: "1.50",
  rabatt: 0,
});

let serverCrateLines: CrateLine[] = [];

function renderOrders() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0 },
      mutations: { retry: false },
    },
  });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
  return renderHook(() => useOrdersData(), { wrapper });
}

/** The hook for reseller-1's order, once its crate lines are in. */
async function renderLoadedOrder() {
  const view = renderOrders();
  act(() => view.result.current.setSelectedReseller("reseller-1"));
  await waitFor(() =>
    expect(crateLineIds(view.result.current)).toEqual([
      "ct-euro_row-3",
      "ct-small_row-5",
      "ct-small_row-6",
    ]),
  );
  expect(api.crateContents).toHaveBeenCalledWith({
    year: 2026,
    delivery_week: 41,
    day_number: 2,
    reseller: "reseller-1",
  });
  return view;
}

const crateLineIds = (orders: ReturnType<typeof useOrdersData>) =>
  orders.dataCrates.map((line) => line.id);

const spinners = ({
  loading,
  cratesLoading,
}: ReturnType<typeof useOrdersData>) => ({ loading, cratesLoading });

/**
 * Holds the next crate list request open until the returned function
 * answers it.
 */
function holdNextCrateList() {
  let answer = () => {};
  api.crateContents.mockImplementationOnce(
    () =>
      new Promise((resolve) => {
        answer = () => resolve([...serverCrateLines]);
      }),
  );
  return () => answer();
}

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(NOW);
  serverCrateLines = [CARROT_DEPOSIT, SMALL_DISCOUNTED, SMALL_FULL_PRICE];
  Object.values(api).forEach((fn) => fn.mockReset());
  Object.values(notifyMock).forEach((fn) => fn.mockReset());
  vi.mocked(generateAndUploadDeliveryNotePDF).mockReset();
  vi.mocked(generateAndUploadInvoicePDF).mockReset();
  api.orderContents.mockImplementation(async () => ({
    items: [CARROTS],
    order: ORDER,
    orders_delivery_day_defaults: NO_DAY_DEFAULTS,
  }));
  api.daysWithOrders.mockImplementation(async () => ({ days: [2] }));
  api.crateContents.mockImplementation(async () => [...serverCrateLines]);
});

afterEach(() => {
  vi.useRealTimers();
});

describe("useOrdersData crate list", () => {
  it("reads the crate lines again after an order line is saved, which re-creates its deposit crates", async () => {
    const { result } = await renderLoadedOrder();
    api.updateOrderContent.mockImplementation(
      async (id: string, line: Record<string, unknown>) => {
        // 12 kg need six crates, on a crate row created anew.
        serverCrateLines = serverCrateLines.map((crates) =>
          crates === CARROT_DEPOSIT
            ? { ...CARROT_DEPOSIT, id: "ct-euro_row-8", amount: 6 }
            : crates,
        );
        return { ...CARROTS, ...line, id };
      },
    );

    // The order line table saves through these two, in this order.
    await act(async () => {
      await result.current.apiFunctions.update!("oc-1", { amount: "12.000" });
      result.current.handleSaveSuccess();
    });

    await waitFor(() =>
      expect(crateLineIds(result.current)).toEqual([
        "ct-euro_row-8",
        "ct-small_row-5",
        "ct-small_row-6",
      ]),
    );
    expect(result.current.dataCrates[0]).toMatchObject({ amount: 6 });
  });

  it("reads the crate lines again after a crate line is saved into another line of its type", async () => {
    const { result } = await renderLoadedOrder();
    api.updateCrateContent.mockImplementation(
      async (id: string, line: Record<string, unknown>) => {
        // Priced like the full-price line, the discounted one joins it.
        const merged = {
          ...SMALL_FULL_PRICE,
          id: "ct-small_row-5",
          amount: Number(line.amount) + SMALL_FULL_PRICE.amount,
        };
        serverCrateLines = [CARROT_DEPOSIT, merged];
        return { ...merged, id };
      },
    );

    // The crate table saves through these two, in this order.
    await act(async () => {
      await result.current.apiFunctionsCrates.update!("ct-small_row-5", {
        crate_type: "ct-small",
        amount: 2,
        price_per_unit: "1.50",
        rabatt: 0,
      });
      result.current.handleSaveSuccess();
    });

    await waitFor(() =>
      expect(crateLineIds(result.current)).toEqual([
        "ct-euro_row-3",
        "ct-small_row-5",
      ]),
    );
    expect(result.current.dataCrates[1]).toMatchObject({
      amount: 5,
      price_per_unit: "1.50",
      rabatt: 0,
    });
  });

  it("reads the crate lines again after an order line is deleted, which takes its deposit crates along", async () => {
    const { result } = await renderLoadedOrder();
    api.destroyOrderContent.mockImplementation(async () => {
      serverCrateLines = serverCrateLines.filter(
        (crates) => crates !== CARROT_DEPOSIT,
      );
      return { order_deleted: false };
    });

    await act(async () => {
      await result.current.apiFunctions.delete!("oc-1");
    });

    await waitFor(() =>
      expect(crateLineIds(result.current)).toEqual([
        "ct-small_row-5",
        "ct-small_row-6",
      ]),
    );
  });

  it("spins only the crate table while a saved order line's crate lines are read again", async () => {
    const { result } = await renderLoadedOrder();
    const orderListReads = api.orderContents.mock.calls.length;
    api.updateOrderContent.mockImplementation(
      async (id: string, line: Record<string, unknown>) => ({
        ...CARROTS,
        ...line,
        id,
      }),
    );
    const answerCrateList = holdNextCrateList();

    await act(async () => {
      await result.current.apiFunctions.update!("oc-1", { amount: "11.000" });
      result.current.handleSaveSuccess();
    });

    // A spinner over the order-line tables would catch the click on the next
    // line for as long as the crate list takes.
    await waitFor(() =>
      expect(spinners(result.current)).toEqual({
        loading: false,
        cratesLoading: true,
      }),
    );
    expect(api.orderContents).toHaveBeenCalledTimes(orderListReads);

    act(() => answerCrateList());
    await waitFor(() => expect(result.current.cratesLoading).toBe(false));
  });

  it("reads the crate lines once the first save in an empty slot has created the order", async () => {
    let orderCreated = false;
    serverCrateLines = [];
    api.orderContents.mockImplementation(async () => ({
      items: [orderCreated ? CARROTS : CARROTS_OFFER],
      order: orderCreated ? ORDER : null,
      orders_delivery_day_defaults: NO_DAY_DEFAULTS,
    }));
    api.createOrderContent.mockImplementation(
      async (line: Record<string, unknown>) => {
        // Ordering the carrots creates the order and their deposit crates.
        orderCreated = true;
        serverCrateLines = [CARROT_DEPOSIT];
        return { ...CARROTS, ...line };
      },
    );
    const { result } = renderOrders();
    act(() => result.current.setSelectedReseller("reseller-1"));
    await waitFor(() =>
      expect(result.current.data.map((line) => line.id)).toEqual([
        "offer-carrots",
      ]),
    );
    // Without an order there are no crate lines to read.
    expect(api.crateContents).not.toHaveBeenCalled();

    // The offer table saves the placeholder line through these two.
    await act(async () => {
      await result.current.apiFunctions.update!("offer-carrots", {
        offer: "offer-carrots",
        amount: "10.000",
      });
      result.current.handleSaveSuccess();
    });

    await waitFor(() =>
      expect(crateLineIds(result.current)).toEqual(["ct-euro_row-3"]),
    );
    expect(api.createOrderContent).toHaveBeenCalledTimes(1);
    expect(result.current.orderState.orderId).toBe("order-1");
  });
});

describe("useOrdersData order note", () => {
  it("tells the office when the note it typed could not be saved", async () => {
    // A failed request without a message of its own.
    api.setOrderNote.mockRejectedValue({
      isAxiosError: true,
      response: { status: 503, data: {} },
    });
    const { result } = await renderLoadedOrder();

    act(() => result.current.setOrderNote("Leave at the back door"));

    await waitFor(
      () =>
        expect(notifyMock.error).toHaveBeenCalledWith(
          "common.error_saving_data",
        ),
      { timeout: 3000 },
    );
    expect(api.setOrderNote).toHaveBeenCalledWith("order-1", {
      note: "Leave at the back door",
    });
  });

  it("tells the office when the note saved on leaving the page could not be saved", async () => {
    api.setOrderNote.mockRejectedValue({
      isAxiosError: true,
      response: { status: 503, data: {} },
    });
    const { result, unmount } = await renderLoadedOrder();

    // Left before the debounced save ran: the leave flushes the note.
    act(() => result.current.setOrderNote("Leave at the back door"));
    unmount();

    await waitFor(() =>
      expect(notifyMock.error).toHaveBeenCalledWith(
        "commissioning.order_note_save_failed",
      ),
    );
    expect(api.setOrderNote).toHaveBeenCalledTimes(1);
    expect(api.setOrderNote).toHaveBeenCalledWith("order-1", {
      note: "Leave at the back door",
    });
  });
});

describe("useOrdersData PDFs after finalizing", () => {
  it("generates every PDF and says how many failed", async () => {
    vi.mocked(generateAndUploadDeliveryNotePDF).mockRejectedValueOnce(
      new Error("render failed"),
    );
    const { result } = renderOrders();

    await act(async () => {
      await result.current.handleFinalizeInvoicesSuccess({
        results: [
          { success: true, delivery_note_id: "dn-1", invoice_id: "inv-1" },
          { success: true, delivery_note_id: "dn-2", invoice_id: "inv-2" },
        ],
      });
    });

    expect(generateAndUploadDeliveryNotePDF).toHaveBeenCalledTimes(2);
    expect(generateAndUploadInvoicePDF).toHaveBeenCalledTimes(2);
    expect(notifyMock.warning).toHaveBeenCalledTimes(1);
    expect(notifyMock.warning).toHaveBeenCalledWith(
      "commissioning.pdf_generation_failed",
    );
  });

  it("stays quiet when every delivery note PDF is generated", async () => {
    const { result } = renderOrders();

    await act(async () => {
      await result.current.handleFinalizeDeliveryNotesSuccess({
        results: [{ success: true, delivery_note_id: "dn-1" }],
      });
    });

    expect(generateAndUploadDeliveryNotePDF).toHaveBeenCalledTimes(1);
    expect(notifyMock.warning).not.toHaveBeenCalled();
  });
});
