import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  commissioningOrderContentsCreate,
  commissioningOrderContentsPartialUpdate,
} from "@shared/api/generated/commissioning/commissioning";
import type { OrderContent, UnitEnum } from "@shared/api/generated/models";
import type { Writable } from "@shared/api/typeHelpers";
import { notify, pickTierPrice } from "@shared/utils";
import {
  getErrorCode,
  getErrorDetails,
  getErrorMessage,
} from "@shared/utils/apiError";
import type { TierPrices } from "@shared/utils/tierPrice";
import type {
  CustomerOrderTableRow,
  StockError,
} from "@features/customer/types";

interface Params {
  resellerId: string | undefined;
  selectedYear: number;
  selectedWeek: number;
  selectedDay: number;
  finalTiers: number[];
  invalidateOrders: () => void;
}

export function useCustomerOrderMutations({
  resellerId,
  selectedYear,
  selectedWeek,
  selectedDay,
  finalTiers,
  invalidateOrders,
}: Params) {
  const { t } = useTranslation();
  // Pending amounts the reseller has typed but not yet saved, keyed by offer id.
  const [orderAmounts, setOrderAmounts] = useState<Record<string, number>>({});
  // The order-amount column is a single edit surface: ``editMode`` flips the
  // whole column between read-only tags and inputs; ``saving`` covers the one
  // bulk save that persists every touched row at once.
  const [editMode, setEditMode] = useState(false);
  const [saving, setSaving] = useState(false);
  // Rows a save rejected for insufficient stock, keyed by offer id. Surfaced
  // inline (red input + a tiny tag) instead of as a toast, so the reseller
  // sees exactly which row is over-ordered and by how much.
  const [stockErrors, setStockErrors] = useState<Record<string, StockError>>(
    {},
  );

  // Leaving the current reseller/week/day discards any in-progress edit — stale
  // pending amounts / errors must never carry across to a different order.
  useEffect(() => {
    setEditMode(false);
    setSaving(false);
    setOrderAmounts({});
    setStockErrors({});
  }, [resellerId, selectedYear, selectedWeek, selectedDay]);

  const calculatePricePerUnit = useCallback(
    (amount: number, record: TierPrices) =>
      // CustomerOrderPage convention: the typed amount IS already PU,
      // so no ``amount_per_pu`` division needed — pass through to the
      // pure tier picker. See ``utils/tierPrice.ts``.
      pickTierPrice(amount, record, finalTiers),
    [finalTiers],
  );

  const handleAmountChange = useCallback(
    (offerId: string, value: number | null) => {
      setOrderAmounts((prev) => ({ ...prev, [offerId]: value ?? 0 }));
      // Editing the amount clears its stale over-order flag so the red state
      // disappears as the reseller corrects it.
      setStockErrors((prev) => {
        if (!(offerId in prev)) return prev;
        const next = { ...prev };
        delete next[offerId];
        return next;
      });
    },
    [],
  );

  const enterEditMode = useCallback(() => setEditMode(true), []);

  const cancelEditMode = useCallback(() => {
    setEditMode(false);
    setOrderAmounts({});
    setStockErrors({});
  }, []);

  // Persist a single row: PATCH when it already has an OrderContent, POST
  // otherwise. Reads the row's pending amount; a row with no pending amount is
  // a no-op (the caller filters those out).
  const persistRow = useCallback(
    async (record: CustomerOrderTableRow) => {
      const offerId = record.id as string;
      const amount = orderAmounts[offerId];
      if (amount == null) return;

      const amountPerPu = Number(record.amount_per_pu) || 1;
      const price = calculatePricePerUnit(amount > 0 ? amount : 0, record);
      const computedAmount = (amount * amountPerPu).toFixed(3);

      if (record.order_content_id) {
        const patch: Partial<Writable<OrderContent>> = {
          amount: computedAmount,
          price_per_unit: String(price),
        };
        await commissioningOrderContentsPartialUpdate(
          record.order_content_id,
          // PATCH sends a partial body against the generated full-model
          // signature — single directional cast at the orval boundary.
          patch as OrderContent,
        );
        return;
      }

      if (!resellerId) return;
      const payload: Writable<OrderContent> = {
        offer: offerId,
        year: selectedYear,
        delivery_week: selectedWeek,
        day_number: selectedDay,
        reseller: resellerId,
        amount: computedAmount,
        price_per_unit: String(price),
        // List rows carry the unit as a plain string; the values are
        // the backend's UnitEnum members.
        unit: record.unit as UnitEnum,
      };
      await commissioningOrderContentsCreate(payload);
    },
    [
      orderAmounts,
      calculatePricePerUnit,
      resellerId,
      selectedYear,
      selectedWeek,
      selectedDay,
    ],
  );

  // Bulk save: persist every row the reseller actually touched (finalized rows
  // are frozen and skipped). All rows go in parallel; we only leave edit mode
  // and clear pending state when the whole batch succeeded.
  const handleSaveAll = useCallback(
    async (rows: CustomerOrderTableRow[]) => {
      const dirty = rows.filter(
        (row) =>
          (row.id as string) in orderAmounts && !row.order_is_finalized,
      );
      if (dirty.length === 0) {
        setEditMode(false);
        return;
      }

      setSaving(true);
      const results = await Promise.allSettled(dirty.map(persistRow));
      setSaving(false);

      // ``allSettled`` keeps order, so results[i] pairs with dirty[i]. An
      // insufficient-stock rejection is surfaced INLINE (red input + tag) via
      // ``stockErrors`` rather than a toast; any other failure still toasts.
      const nextStockErrors = { ...stockErrors };
      const nextAmounts = { ...orderAmounts };
      let hadError = false;

      results.forEach((result, index) => {
        const offerId = dirty[index].id as string;
        if (result.status === "fulfilled") {
          delete nextStockErrors[offerId];
          delete nextAmounts[offerId];
          return;
        }
        hadError = true;
        console.error("Save failed:", result.reason);
        if (getErrorCode(result.reason) === "order_content.insufficient_stock") {
          const details = getErrorDetails(result.reason);
          nextStockErrors[offerId] = {
            available: Number(details?.available ?? 0),
            requested: Number(details?.requested ?? 0),
          };
        } else {
          delete nextStockErrors[offerId];
          notify.error(
            getErrorMessage(result.reason, t("customer.order_error")),
          );
        }
      });

      setStockErrors(nextStockErrors);
      setOrderAmounts(nextAmounts);
      if (!hadError) {
        notify.success(t("customer.order_success"));
        setEditMode(false);
      }
      invalidateOrders();
    },
    [orderAmounts, stockErrors, persistRow, t, invalidateOrders],
  );

  return {
    orderAmounts,
    editMode,
    saving,
    stockErrors,
    handleAmountChange,
    enterEditMode,
    cancelEditMode,
    handleSaveAll,
    calculatePricePerUnit,
  };
}
