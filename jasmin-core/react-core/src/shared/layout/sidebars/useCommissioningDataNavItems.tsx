import { useTenant } from "@hooks/index";
import type { RoleGatedItem } from "@shared/auth";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { useDeliveryStationNavItems } from "./useDeliveryStationNavItems";
import { usePurchaseNavItems } from "./usePurchaseNavItems";

/**
 * Commissioning's data lists: the articles, the default quantities, the
 * crates, the storages, the delivery stations, the resellers, the sellers and
 * the plots. They are a group of the commissioning sidebar, or a section of
 * their own where the configuration isn't one (``configuration_section``).
 * Every link leads to one of ``COMMISSIONING_DATA_PATHS``.
 */
export function useCommissioningDataNavItems(): RoleGatedItem[] {
  const { t } = useTranslation();
  const { getSetting } = useTenant();
  const sellsToResellers = getSetting("sells_to_resellers", true);
  const { deliveryStationListItems } = useDeliveryStationNavItems();
  const purchaseItems = usePurchaseNavItems();

  return [
    {
      key: "commissioning-list-harvest-shares-articles",
      requireRole: "isStaff",
      label: (
        <Link to="/commissioning/list-harvest-share-articles">
          {t("commissioning.list_harvest_shares_articles")}
        </Link>
      ),
    },
    {
      key: "commissioning-default-share-articles-in-share",
      requireRole: "isOffice",
      label: (
        <Link to="/commissioning/default-share-articles-in-share">
          {t("commissioning.default_share_articles_in_share")}
        </Link>
      ),
    },
    {
      key: "commissioning-list-crates",
      requireRole: "isStaff",
      label: (
        <Link to="/commissioning/list-crates">
          {t("commissioning.list_crates")}
        </Link>
      ),
    },
    // Extra articles are sold to resellers only.
    ...(sellsToResellers
      ? [
          {
            key: "commissioning-list-extra-articles",
            requireRole: "isOffice" as const,
            label: (
              <Link to="/commissioning/list-extra-articles">
                {t("commissioning.list_extra_articles")}
              </Link>
            ),
          },
        ]
      : []),
    {
      key: "commissioning-list-storages",
      requireRole: "isOffice",
      label: (
        <Link to="/commissioning/list-storages">
          {t("commissioning.list_storages")}
        </Link>
      ),
    },
    ...deliveryStationListItems,
    ...(sellsToResellers
      ? [
          {
            key: "commissioning-list-resellers",
            requireRole: "isOffice" as const,
            label: (
              <Link to="/commissioning/list-resellers">
                {t("commissioning.list_resellers")}
              </Link>
            ),
          },
          {
            key: "commissioning-list-offer-groups",
            requireRole: "isOffice" as const,
            label: (
              <Link to="/commissioning/list-offer-groups">
                {t("commissioning.list_offer_groups")}
              </Link>
            ),
          },
        ]
      : []),
    ...purchaseItems.dataItems,
    {
      key: "commissioning-list-plots",
      requireRole: "isStaff",
      label: (
        <Link to="/commissioning/list-plots">
          {t("commissioning.list_plots")}
        </Link>
      ),
    },
  ];
}
