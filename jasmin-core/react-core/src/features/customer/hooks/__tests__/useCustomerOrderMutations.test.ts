/**
 * Tier-4 seam test for ``useCustomerOrderMutations``.
 *
 * The order-amount column is a single edit surface: one ``editMode`` flag
 * and one bulk ``handleSaveAll`` that persists every touched row at once.
 * Covered here:
 *   - tier-based pricing (real ``pickTierPrice``)
 *   - edit-mode enter / cancel (cancel discards pending edits)
 *   - bulk save routing: POST for a new offer, PATCH (no ``unit``) for an
 *     existing order, both in one batch
 *   - finalized / untouched rows are skipped
 *   - success clears state + leaves edit mode; a failure keeps edit mode
 *     and the typed amounts so the reseller can retry
 *
 * Boundary mocked: the generated commissioning API client (vi.mock).
 * We don't use MSW here — the hook is pure logic + HTTP calls; a boundary
 * mock keeps assertions sharp and the test fast.
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
import type {
  CustomerOrderRow,
  CustomerOrderTableRow,
} from "@features/customer/types";

// ── Fixtures ────────────────────────────────────────────────────────────────

const OFFER_ID = "offer-123";
const RESELLER_ID = "reseller-7";
const ORDER_CONTENT_ID = "oc-9";

/** Fixture helper: the hook only reads a handful of row fields. */
const makeRow = (row: Partial<CustomerOrderRow>) =>
  row as CustomerOrderTableRow;

/** A typical not-yet-ordered offer row coming from the customer-order grid. */
const offer = makeRow({
  id: OFFER_ID,
  amount_per_pu: "2",
  unit: "kg",
  price_1: "1.50",
  price_2: "1.20",
  price_3: "1.00",
});

/** The same offer, but already ordered (carries an OrderContent id). */
const orderedRow = makeRow({
  id: OFFER_ID,
  order_content_id: ORDER_CONTENT_ID,
  amount_per_pu: "2",
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

// ── edit mode enter / cancel ────────────────────────────────────────────────

describe("edit mode", () => {
  it("enterEditMode flips editMode on", () => {
    const { result } = renderHook(() => useCustomerOrderMutations(makeParams()));
    act(() => result.current.enterEditMode());
    expect(result.current.editMode).toBe(true);
  });

  it("cancelEditMode exits edit mode AND discards pending amounts", () => {
    const { result } = renderHook(() => useCustomerOrderMutations(makeParams()));
    act(() => {
      result.current.enterEditMode();
      result.current.handleAmountChange(OFFER_ID, 5);
    });
    expect(result.current.orderAmounts[OFFER_ID]).toBe(5);

    act(() => result.current.cancelEditMode());
    expect(result.current.editMode).toBe(false);
    expect(result.current.orderAmounts).toEqual({});
  });
});

// ── handleSaveAll — routing ─────────────────────────────────────────────────

describe("handleSaveAll — create + update routing", () => {
  it("POSTs the full create payload for a not-yet-ordered offer", async () => {
    const params = makeParams();
    const { result } = renderHook(() => useCustomerOrderMutations(params));

    act(() => result.current.handleAmountChange(OFFER_ID, 3));
    await act(async () => {
      await result.current.handleSaveAll([offer]);
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

  it("PATCHes an existing order WITHOUT a 'unit' field (server falls back to share_article.unit)", async () => {
    const params = makeParams();
    const { result } = renderHook(() => useCustomerOrderMutations(params));

    act(() => result.current.handleAmountChange(OFFER_ID, 6));
    await act(async () => {
      await result.current.handleSaveAll([orderedRow]);
    });

    expect(updateMock).toHaveBeenCalledTimes(1);
    expect(createMock).not.toHaveBeenCalled();
    const [orderId, payload] = updateMock.mock.calls[0];
    expect(orderId).toBe(ORDER_CONTENT_ID);
    expect(payload).not.toHaveProperty("unit");
    expect(payload).toEqual({
      amount: "12.000", // 6 * amount_per_pu(2)
      price_per_unit: "1", // tier-3 hit at amount=6
    });
  });

  it("saves a mix of new + existing rows in one batch", async () => {
    const otherNew = makeRow({
      id: "offer-999",
      amount_per_pu: "1",
      unit: "kg",
      price_1: "2.00",
    });
    const params = makeParams();
    const { result } = renderHook(() => useCustomerOrderMutations(params));

    act(() => {
      result.current.handleAmountChange(OFFER_ID, 6); // existing → PATCH
      result.current.handleAmountChange("offer-999", 1); // new → POST
    });
    await act(async () => {
      await result.current.handleSaveAll([orderedRow, otherNew]);
    });

    expect(updateMock).toHaveBeenCalledTimes(1);
    expect(createMock).toHaveBeenCalledTimes(1);
  });

  it("skips untouched rows and finalized rows", async () => {
    const finalized = makeRow({
      id: "offer-fin",
      order_content_id: "oc-fin",
      order_is_finalized: true,
      amount_per_pu: "1",
      price_1: "1.00",
    });
    const params = makeParams();
    const { result } = renderHook(() => useCustomerOrderMutations(params));

    // touch only the finalized row; the plain offer stays untouched
    act(() => result.current.handleAmountChange("offer-fin", 4));
    await act(async () => {
      await result.current.handleSaveAll([offer, finalized]);
    });

    expect(createMock).not.toHaveBeenCalled();
    expect(updateMock).not.toHaveBeenCalled();
  });
});

// ── handleSaveAll — success / failure state ─────────────────────────────────

describe("handleSaveAll — success + failure", () => {
  it("on success: clears amounts, leaves edit mode, notifies + invalidates", async () => {
    const params = makeParams();
    const { result } = renderHook(() => useCustomerOrderMutations(params));

    act(() => {
      result.current.enterEditMode();
      result.current.handleAmountChange(OFFER_ID, 2);
    });
    await act(async () => {
      await result.current.handleSaveAll([offer]);
    });

    expect(result.current.orderAmounts).toEqual({});
    expect(result.current.editMode).toBe(false);
    expect(result.current.saving).toBe(false);
    expect(notifySuccessMock).toHaveBeenCalledTimes(1);
    expect(params.invalidateOrders).toHaveBeenCalledTimes(1);
  });

  it("on a non-stock failure: toasts the error, keeps edit mode + typed amounts", async () => {
    createMock.mockRejectedValueOnce(new Error("boom"));
    const params = makeParams();
    const { result } = renderHook(() => useCustomerOrderMutations(params));

    act(() => {
      result.current.enterEditMode();
      result.current.handleAmountChange(OFFER_ID, 1);
    });
    await act(async () => {
      await result.current.handleSaveAll([offer]);
    });

    expect(notifyErrorMock).toHaveBeenCalledTimes(1);
    expect(notifySuccessMock).not.toHaveBeenCalled();
    // amount + edit mode preserved so the reseller can retry
    expect(result.current.orderAmounts[OFFER_ID]).toBe(1);
    expect(result.current.editMode).toBe(true);
    expect(result.current.saving).toBe(false);
    expect(result.current.stockErrors).toEqual({});
    expect(params.invalidateOrders).toHaveBeenCalledTimes(1);
  });

  it("on an insufficient-stock failure: records the error INLINE (no toast)", async () => {
    // Canonical Jasmin error body on an axios-shaped rejection.
    createMock.mockRejectedValueOnce({
      isAxiosError: true,
      response: {
        data: {
          code: "order_content.insufficient_stock",
          message: "Not enough stock available. Available: 2.000, Requested: 16.000",
          details: { offer_id: OFFER_ID, available: 2.0, requested: 16.0 },
        },
      },
    });
    const params = makeParams();
    const { result } = renderHook(() => useCustomerOrderMutations(params));

    act(() => {
      result.current.enterEditMode();
      result.current.handleAmountChange(OFFER_ID, 8);
    });
    await act(async () => {
      await result.current.handleSaveAll([offer]);
    });

    // Inline, not a toast
    expect(notifyErrorMock).not.toHaveBeenCalled();
    expect(notifySuccessMock).not.toHaveBeenCalled();
    expect(result.current.stockErrors[OFFER_ID]).toEqual({
      available: 2,
      requested: 16,
    });
    // Stays editable with the over-order still typed in
    expect(result.current.editMode).toBe(true);
    expect(result.current.orderAmounts[OFFER_ID]).toBe(8);
    expect(params.invalidateOrders).toHaveBeenCalledTimes(1);

    // Editing the amount clears the inline error (red state goes away)
    act(() => result.current.handleAmountChange(OFFER_ID, 1));
    expect(result.current.stockErrors[OFFER_ID]).toBeUndefined();
  });
});
