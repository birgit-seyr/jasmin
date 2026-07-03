import { useCallback, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  commissioningOrderContentsCreate,
  commissioningOrderContentsPartialUpdate,
} from "@shared/api/generated/commissioning/commissioning";
import type { OrderContent, UnitEnum } from "@shared/api/generated/models";
import type { Writable } from "@shared/api/typeHelpers";
import { notify, pickTierPrice } from "@shared/utils";
import type { TierPrices } from "@shared/utils/tierPrice";
import type {
  CustomerOrderRow,
  CustomerOrderTableRow,
} from "@features/customer/types";

interface Params {
  resellerId: string | undefined;
  selectedYear: number;
  selectedWeek: number;
  selectedDay: number;
  finalTiers: number[];
  invalidateOrders: () => void;
  orderByOfferId: Map<string, CustomerOrderRow>;
}

export function useCustomerOrderMutations({
  resellerId,
  selectedYear,
  selectedWeek,
  selectedDay,
  finalTiers,
  invalidateOrders,
  orderByOfferId,
}: Params) {
  const { t } = useTranslation();
  const [orderAmounts, setOrderAmounts] = useState<Record<string, number>>({});
  const [submitting, setSubmitting] = useState<Record<string, boolean>>({});

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
    },
    [],
  );

  const clearAmount = useCallback((offerId: string) => {
    setOrderAmounts((prev) => {
      const next = { ...prev };
      delete next[offerId];
      return next;
    });
  }, []);

  const handleOrder = useCallback(
    async (offer: CustomerOrderTableRow) => {
      const offerId = offer.id as string;
      const amount = orderAmounts[offerId];
      const existingOrder = orderByOfferId.get(offerId);

      setSubmitting((prev) => ({ ...prev, [offerId]: true }));
      try {
        const amountPerPu = Number(offer.amount_per_pu) || 1;
        const price = calculatePricePerUnit(amount, offer);
        const computedAmount = (amount * amountPerPu).toFixed(3);

        if (existingOrder) {
          const patch: Partial<Writable<OrderContent>> = {
            amount: computedAmount,
            price_per_unit: String(price),
          };
          await commissioningOrderContentsPartialUpdate(
            existingOrder.id as string,
            // PATCH sends a partial body against the generated full-model
            // signature — single directional cast at the orval boundary.
            patch as OrderContent,
          );
        } else {
          if (!resellerId) {
            // The page never renders the order table without a reseller;
            // mirror that guard so the create payload is fully typed.
            return;
          }
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
            unit: offer.unit as UnitEnum,
          };
          await commissioningOrderContentsCreate(payload);
        }

        notify.success(t("customer.order_success"));
        clearAmount(offerId);
        invalidateOrders();
      } catch (error) {
        console.error("Operation failed:", error);
        notify.error(t("customer.order_error"));
      } finally {
        setSubmitting((prev) => ({ ...prev, [offerId]: false }));
      }
    },
    [
      orderAmounts,
      orderByOfferId,
      calculatePricePerUnit,
      selectedYear,
      selectedWeek,
      selectedDay,
      resellerId,
      t,
      clearAmount,
      invalidateOrders,
    ],
  );

  const handleUpdateOrder = useCallback(
    async (record: CustomerOrderTableRow) => {
      const offerId = record.id as string;
      const orderContentId = record.order_content_id;
      const newAmount = orderAmounts[offerId];
      if (newAmount == null || !orderContentId) return;

      setSubmitting((prev) => ({ ...prev, [offerId]: true }));
      try {
        const amountPerPu = Number(record.amount_per_pu) || 1;
        const price = calculatePricePerUnit(
          newAmount > 0 ? newAmount : 0,
          record,
        );
        const patch: Partial<Writable<OrderContent>> = {
          amount: (newAmount * amountPerPu).toFixed(3),
          price_per_unit: String(price),
        };
        await commissioningOrderContentsPartialUpdate(
          orderContentId,
          // PATCH sends a partial body against the generated full-model
          // signature — single directional cast at the orval boundary.
          patch as OrderContent,
        );
        notify.success(t("customer.order_success"));
        clearAmount(offerId);
        invalidateOrders();
      } catch (error) {
        console.error("Operation failed:", error);
        notify.error(t("customer.order_error"));
      } finally {
        setSubmitting((prev) => ({ ...prev, [offerId]: false }));
      }
    },
    [
      orderAmounts,
      calculatePricePerUnit,
      t,
      clearAmount,
      invalidateOrders,
    ],
  );

  return {
    orderAmounts,
    submitting,
    handleAmountChange,
    handleOrder,
    handleUpdateOrder,
    calculatePricePerUnit,
  };
}
