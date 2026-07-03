import { Alert } from "antd";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { useTenant } from "@hooks/index";

/**
 * Mode banner for the abos + members areas.
 *
 * When the tenant sources weekly share demand from the CSV import
 * (``uploads_weekly_share_amount``), member subscriptions / deliveries do
 * NOT drive planning demand or delivery-station capacity — those come from
 * the imported amounts (``ExternalShareDemand``). Without this hint, office
 * staff editing abos here get confused (e.g. station capacity reading 0
 * because occupancy is sourced from the import, not from these
 * subscriptions). Renders nothing when the tenant runs the normal
 * subscription-driven flow.
 */
export default function ImportSharesModeBanner() {
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
          {t("common.import_shares_mode_banner")}{" "}
          <Link to="/commissioning/import-shares">
            {t("common.import_shares_mode_banner_link")}
          </Link>
        </>
      }
    />
  );
}
