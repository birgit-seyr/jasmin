import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import { useCommissioningPaymentCyclesList } from "@shared/api/generated/commissioning/commissioning";
import type { PaymentCycle } from "@shared/api/generated/models";
import { toOptions, type Option } from "./internal/toOptions";

export type PaymentCycleOption = Option<PaymentCycle>;

export const usePaymentCycles = (options?: { enabled?: boolean }) => {
  const { t } = useTranslation();

  const { data, isLoading, error, refetch } = useCommissioningPaymentCyclesList(
    { is_active: true },
    { query: { enabled: options?.enabled ?? true } },
  );

  const paymentCycles: PaymentCycleOption[] = useMemo(
    () =>
      toOptions(data, (p) =>
        t(`configuration.payment_cycle_${p.choice?.toLowerCase()}`, p.choice ?? ""),
      ),
    [data, t],
  );

  return {
    paymentCycles,
    loading: isLoading,
    error,
    refetch,
  };
};
