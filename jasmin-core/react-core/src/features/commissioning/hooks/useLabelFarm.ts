import { useCallback, useMemo } from "react";
import { useTranslation } from "react-i18next";
import { useNumberFormat, useOrganicGate, useTenant } from "@hooks/index";
import type { LabelFarm } from "@features/commissioning/utils/labelLayout";

/** The fewest decimals, up to three, that show ``amount`` as it is. */
function exactDecimals(amount: number): number {
  return [0, 1, 2].find((decimals) => {
    const scale = 10 ** decimals;
    return Math.abs(Math.round(amount * scale) / scale - amount) < 1e-9;
  }) ?? 3;
}

/**
 * What the farm puts on every label, and how a label words an amount: exactly,
 * to the thousandth the amounts are kept in, without trailing zeros ("5 kg",
 * "0,125 kg").
 */
export function useLabelFarm() {
  const { t } = useTranslation();
  const { tenantName, logoUrl, bioLogoUrl } = useTenant();
  const { enabled, controlNumber } = useOrganicGate();
  const { format } = useNumberFormat();

  const farm = useMemo<LabelFarm>(
    () => ({
      name: tenantName ?? "",
      controlNumber,
      organicEnabled: enabled,
      organicPrefix: t("commissioning.organic.organic"),
    }),
    [tenantName, controlNumber, enabled, t],
  );

  const amountText = useCallback(
    (amount: number, unitLabel: string) =>
      `${format(amount, exactDecimals(amount))} ${unitLabel}`,
    [format],
  );

  return { farm, logoUrl, bioLogoUrl, amountText };
}
