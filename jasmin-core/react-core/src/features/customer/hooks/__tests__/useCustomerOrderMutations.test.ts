/**
 * Tier-4 seam test for ``useCustomerOrderMutations``.
 *
 * Covers the two branches called out in the frontend test plan:
 *   - create-vs-update routing via ``orderByOfferId``
 *   - on update, ``unit`` is NOT sent client-side (backend falls back to
 *     ``offer.share_article.unit``)
 *
 * Also covers the small surface around it: tier-based pricing, the
 * ``submitting`` flag, the success / error notify hooks, and the
 * ``invalidateOrders`` callback firing on success.
 *
 * Boundary mocked: the generated commissioning API client (vi.mock).
 * We don't use MSW here — the hook is pure logic + two HTTP calls; a
 * boundary mock keeps assertions sharp and the test fast.
 */

import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

// ── Mocks ───────────────────────────────────────────────────────────────────

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, fallback?: unknown) =>
      typeof fallback === "string" ? fallback : key,
    i18n: { language: "de", changeLanguage: () => Promise.resolve() },
  }),
  Trans: ({ children }: { children?: unknown }) => children,
  initReactI18next: { type: "3rdParty", init: () => {} },
}));

const createMock = vi.fn();
const updateMock = vi.fn();

vi.mock("@shared/api/generated/commissioning/commissioning", () => ({
  commissioningOrderContentsCreate: (...args: unknown[]) => createMock(...args),
  commissioningOrderContentsPartialUpdate: (...args: unknown[]) =>
    updateMock(...args),
}));

const notifySuccessMock = vi.fn();
const notifyErrorMock = vi.fn();

// Keep the REAL ``pickTierPrice`` (and any future siblings) — it's a pure
// function and the hook's tier-pricing assertions exercise the real
// algorithm. Only override ``notify`` so we can assert on calls.
vi.mock("@shared/utils", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@shared/utils")>();
  return {
    ...actual,
    notify: {
      success: (...args: unknown[]) => notifySuccessMock(...args),
      error: (...args: unknown[]) => notifyErrorMock(...args),
    },
  };
});

import { useCustomerOrderMutations } from "../useCustomerOrderMutations";
import type { CustomerOrderRow } from "@features/customer/types";

// ── Fixtures ────────────────────────────────────────────────────────────────

const OFFER_ID = "offer-123";
const RESELLER_ID = "reseller-7";
const ORDER_CONTENT_ID = "oc-9";

/** Fixture helper: the hook only reads a handful of row fields. */
const makeRow = (row: Partial<CustomerOrderRow>) => row as CustomerOrderRow;

/** A typical offer row coming from the customer-order grid. */
const offer = makeRow({
  id: OFFER_ID,
  amount_per_pu: "2",
  unit: "kg",
  price_1: "1.50",
  price_2: "1.20",
  price_3: "1.00",
});

function makeParams(
  overrides: Partial<Parameters<typeof useCustomerOrderMutations>[0]> = {},
) {
  return {
    resellerId: RESELLER_ID,
    selectedYear: 2026,
    selectedWeek: 20,
    selectedDay: 3,
    finalTiers: [1, 3, 5],
    invalidateOrders: vi.fn(),
    orderByOfferId: new Map<string, CustomerOrderRow>(),
    ...overrides,
  };
}

beforeEach(() => {
  createMock.mockReset().mockResolvedValue(undefined);
  updateMock.mockReset().mockResolvedValue(undefined);
  notifySuccessMock.mockReset();
  notifyErrorMock.mockReset();
});

// ── calculatePricePerUnit ───────────────────────────────────────────────────

describe("calculatePricePerUnit", () => {
  it("returns price_1 below tier-2 threshold", () => {
    const { result } = renderHook(() => useCustomerOrderMutations(makeParams()));
    expect(result.current.calculatePricePerUnit(2, offer)).toBe(1.5);
  });

  it("returns price_2 at tier-2 threshold (3) but below tier-3 (5)", () => {
    const { result } = renderHook(() => useCustomerOrderMutations(makeParams()));
    expect(result.current.calculatePricePerUnit(3, offer)).toBe(1.2);
    expect(result.current.calculatePricePerUnit(4, offer)).toBe(1.2);
  });

  it("returns price_3 at tier-3 threshold (5) and above", () => {
    const { result } = renderHook(() => useCustomerOrderMutations(makeParams()));
    expect(result.current.calculatePricePerUnit(5, offer)).toBe(1.0);
    expect(result.current.calculatePricePerUnit(100, offer)).toBe(1.0);
  });

  it("falls back to price_1 when higher-tier price is 0 (not configured)", () => {
    const cheapOffer = { ...offer, price_2: "0", price_3: "0" };
    const { result } = renderHook(() => useCustomerOrderMutations(makeParams()));
    expect(result.current.calculatePricePerUnit(10, cheapOffer)).toBe(1.5);
  });
});

// ── handleAmountChange ──────────────────────────────────────────────────────

describe("handleAmountChange", () => {
  it("stores the pending amount for a given offer id", () => {
    const { result } = renderHook(() => useCustomerOrderMutations(makeParams()));
    act(() => {
      result.current.handleAmountChange(OFFER_ID, 4);
    });
    expect(result.current.orderAmounts).toEqual({ [OFFER_ID]: 4 });
  });

  it("treats null as 0 (input cleared)", () => {
    const { result } = renderHook(() => useCustomerOrderMutations(makeParams()));
    act(() => {
      result.current.handleAmountChange(OFFER_ID, null);
    });
    expect(result.current.orderAmounts).toEqual({ [OFFER_ID]: 0 });
  });
});

// ── handleOrder — create branch ─────────────────────────────────────────────

describe("handleOrder — create branch (no existing order)", () => {
  it("POSTs the full create payload including unit + reseller + week", async () => {
    const params = makeParams();
    const { result } = renderHook(() => useCustomerOrderMutations(params));

    act(() => {
      result.current.handleAmountChange(OFFER_ID, 3);
    });
    await act(async () => {
      await result.current.handleOrder(offer);
    });

    expect(createMock).toHaveBeenCalledTimes(1);
    expect(updateMock).not.toHaveBeenCalled();
    expect(createMock).toHaveBeenCalledWith({
      offer: OFFER_ID,
      year: 2026,
      delivery_week: 20,
      day_number: 3,
      reseller: RESELLER_ID,
      // 3 (input) * 2 (amount_per_pu) = 6.000
      amount: "6.000",
      // tier-2 hit at amount=3 → price_2 = 1.20
      price_per_unit: "1.2",
      unit: "kg",
    });
  });

  it("clears the pending amount and calls invalidateOrders on success", async () => {
    const params = makeParams();
    const { result } = renderHook(() => useCustomerOrderMutations(params));

    act(() => {
      result.current.handleAmountChange(OFFER_ID, 2);
    });
    await act(async () => {
      await result.current.handleOrder(offer);
    });

    expect(result.current.orderAmounts[OFFER_ID]).toBeUndefined();
    expect(params.invalidateOrders).toHaveBeenCalledTimes(1);
    expect(notifySuccessMock).toHaveBeenCalledTimes(1);
    expect(notifyErrorMock).not.toHaveBeenCalled();
  });
});

// ── handleOrder — update branch ─────────────────────────────────────────────

describe("handleOrder — update branch (existing order)", () => {
  it("PATCHes the existing order WITHOUT a 'unit' field (server falls back to share_article.unit)", async () => {
    const orderByOfferId = new Map<string, CustomerOrderRow>([
      [OFFER_ID, makeRow({ id: ORDER_CONTENT_ID })],
    ]);
    const params = makeParams({ orderByOfferId });
    const { result } = renderHook(() => useCustomerOrderMutations(params));

    act(() => {
      result.current.handleAmountChange(OFFER_ID, 6);
    });
    await act(async () => {
      await result.current.handleOrder(offer);
    });

    expect(updateMock).toHaveBeenCalledTimes(1);
    expect(createMock).not.toHaveBeenCalled();

    const [orderId, payload] = updateMock.mock.calls[0];
    expect(orderId).toBe(ORDER_CONTENT_ID);
    // The plan's "unit not sent client-side" assertion — backend will
    // fall back to offer.share_article.unit when reading this row.
    expect(payload).not.toHaveProperty("unit");
    expect(payload).toEqual({
      amount: "12.000", // 6 * amount_per_pu(2)
      price_per_unit: "1", // tier-3 hit at amount=6
    });
  });
});

// ── handleOrder — error path ────────────────────────────────────────────────

describe("handleOrder — error path", () => {
  it("notifies error on API failure and resets the submitting flag", async () => {
    createMock.mockRejectedValueOnce(new Error("boom"));
    const params = makeParams();
    const { result } = renderHook(() => useCustomerOrderMutations(params));

    act(() => {
      result.current.handleAmountChange(OFFER_ID, 1);
    });
    await act(async () => {
      await result.current.handleOrder(offer);
    });

    expect(notifyErrorMock).toHaveBeenCalledTimes(1);
    expect(notifySuccessMock).not.toHaveBeenCalled();
    expect(params.invalidateOrders).not.toHaveBeenCalled();
    // amount is left in place so the user can retry without re-typing
    expect(result.current.orderAmounts[OFFER_ID]).toBe(1);
    expect(result.current.submitting[OFFER_ID]).toBe(false);
  });
});

// ── handleUpdateOrder ───────────────────────────────────────────────────────

describe("handleUpdateOrder", () => {
  it("PATCHes via order_content_id, omits unit", async () => {
    const params = makeParams();
    const { result } = renderHook(() => useCustomerOrderMutations(params));

    act(() => {
      result.current.handleAmountChange(OFFER_ID, 4);
    });
    await act(async () => {
      await result.current.handleUpdateOrder(
        makeRow({
          id: OFFER_ID,
          order_content_id: ORDER_CONTENT_ID,
          amount_per_pu: "2",
          price_1: "1.50",
          price_2: "1.20",
          price_3: "1.00",
        }),
      );
    });

    expect(updateMock).toHaveBeenCalledTimes(1);
    const [orderId, payload] = updateMock.mock.calls[0];
    expect(orderId).toBe(ORDER_CONTENT_ID);
    expect(payload).not.toHaveProperty("unit");
    expect(payload).toEqual({
      amount: "8.000", // 4 * 2
      price_per_unit: "1.2", // tier-2 at amount=4
    });
  });

  it("no-ops when amount is missing OR order_content_id is missing", async () => {
    const { result } = renderHook(() => useCustomerOrderMutations(makeParams()));

    // No pending amount set for this offer
    await act(async () => {
      await result.current.handleUpdateOrder(
        makeRow({ id: OFFER_ID, order_content_id: ORDER_CONTENT_ID }),
      );
    });
    expect(updateMock).not.toHaveBeenCalled();

    // Amount set but order_content_id missing
    act(() => {
      result.current.handleAmountChange(OFFER_ID, 3);
    });
    await act(async () => {
      await result.current.handleUpdateOrder(makeRow({ id: OFFER_ID }));
    });
    expect(updateMock).not.toHaveBeenCalled();
  });
});
