import { Tag } from "antd";
import { useTranslation } from "react-i18next";
import { PaymentMethodEnum } from "@shared/api/generated/models";

export interface SepaMandateStatusTagProps {
  /** ``BillingProfile.payment_method`` — SEPA_DD vs. a fallback method. */
  paymentMethod?: string | null;
  /** ``BillingProfile.is_active``. */
  isActive?: boolean | null;
  /** ``BillingProfile.is_sepa_ready`` (== ``SepaMandateStatus.has_active_sepa_mandate``). */
  isSepaReady?: boolean | null;
}

/**
 * Single source of truth for the SEPA-mandate status badge.
 *
 * Both the SEPA-mandates register (rendered from ``BillingProfile`` rows) and
 * the Abos SEPA details modal (rendered from ``mandate_status`` rows) use this,
 * so the same underlying state always shows the same tag + colour. States, in
 * priority order:
 *
 *  - **revoked** (red): a mandate exists but the profile is no longer on SEPA
 *    (Art. 7(3) consent withdrawal switched it to BANK_TRANSFER).
 *  - **inactive** (grey): the SEPA profile was explicitly deactivated.
 *  - **ready** (green): a complete, usable SEPA mandate.
 *  - **incomplete** (orange): on SEPA + active but missing mandate fields.
 */
export default function SepaMandateStatusTag({
  paymentMethod,
  isActive,
  isSepaReady,
}: SepaMandateStatusTagProps) {
  const { t } = useTranslation();

  if (paymentMethod !== PaymentMethodEnum.SEPA_DD) {
    return <Tag color="red">{t("sepa.status_revoked")}</Tag>;
  }
  if (!isActive) {
    return <Tag color="default">{t("sepa.status_inactive")}</Tag>;
  }
  if (isSepaReady) {
    return <Tag color="green">{t("sepa.status_ready")}</Tag>;
  }
  return <Tag color="orange">{t("sepa.status_incomplete")}</Tag>;
}
