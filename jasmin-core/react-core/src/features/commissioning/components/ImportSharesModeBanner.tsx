import { Alert } from "antd";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { useTenant } from "@hooks/index";

interface ImportSharesModeBannerProps {
  /**
   * i18n key for the banner text. Defaults to the generic "demand comes from
   * the CSV import" note (abos/members areas). Pages where a feature is simply
   * unavailable under import mode (e.g. pickup lists) pass their own message.
   */
  messageKey?: string;
}

/**
 * Mode banner for the abos + members areas (and, with a custom ``messageKey``,
 * any page that needs to explain import-shares behaviour).
 *
 * When the tenant sources weekly share demand from the CSV import
 * (``uploads_weekly_share_amount``), member subscriptions / deliveries do
 * NOT drive planning demand or delivery-station capacity — those come from
 * the imported amounts (``ExternalShareDemand``). Renders nothing when the
 * tenant runs the normal subscription-driven flow.
 */
export default function ImportSharesModeBanner({
  messageKey = "common.import_shares_mode_banner",
}: ImportSharesModeBannerProps) {
  const { t } = useTranslation();
  const { getSetting } = useTenant();
  const usesExternalDemand = getSetting(
    "uploads_weekly_share_amount",
    false,
  ) as boolean;

  if (!usesExternalDemand) return null;

  return (
    <Alert
      type="info"
      banner
      showIcon
      message={
        <>
          {t(messageKey)}{" "}
          <Link to="/commissioning/import-shares">
            {t("common.import_shares_mode_banner_link")}
          </Link>
        </>
      }
    />
  );
}
