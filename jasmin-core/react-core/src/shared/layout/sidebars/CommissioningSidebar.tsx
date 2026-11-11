import { useCapability, useTenant } from "@hooks/index";
import { filterByRole, useRoles, type RoleGatedItem } from "@shared/auth";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import SidebarShell from "./SidebarShell";
import { useDeliveryStationNavItems } from "./useDeliveryStationNavItems";
import { useMarketNavItems } from "./useMarketNavItems";
import { usePackingListVisibility } from "./usePackingListVisibility";
import { usePlanningNavItems } from "./usePlanningNavItems";
import { useWorkListNavItems } from "./useWorkListNavItems";

import AllInclusiveIcon from "@mui/icons-material/AllInclusive";
import BubbleChartIcon from "@mui/icons-material/BubbleChart";
import EggIcon from "@mui/icons-material/Egg";
import FavoriteIcon from "@mui/icons-material/Favorite";
import GrainIcon from "@mui/icons-material/Grain";
import HdrWeakIcon from "@mui/icons-material/HdrWeak";
interface CommissioningSidebarProps {
  openKeys?: string[];
  onOpenChange?: (keys: string[]) => void;
}

export default function CommissioningSidebar({
  openKeys = [],
  onOpenChange,
}: CommissioningSidebarProps) {
  const { getSetting } = useTenant();
  const { t } = useTranslation();
  const flags = useRoles();

  const { planningComplexItems, planningLongTermItems, additionalLongTermItems } =
    usePlanningNavItems();

  const sells_to_resellers = getSetting("sells_to_resellers", true);
  const weekly_upload = getSetting("uploads_weekly_share_amount", false);
  const offersManualShareImport = useCapability("manual_share_import");
  const workListItems = useWorkListNavItems();
  const {
    packingMode,
    showBulkPackingList,
    showBoxesPackingList,
    showWeightStatistics,
  } = usePackingListVisibility();
  const { deliveryStationSection, deliveryStationListItems } =
    useDeliveryStationNavItems();
  const marketSection = useMarketNavItems();

  const baseMenuItems = [
    {
      key: "commissioning-amounts",
      requireRole: "isStaff",
      icon: <GrainIcon />,
      label: (
        <div className="sidebar-section-header">
          {t("commissioning.amounts")}
        </div>
      ),
      children: [
        {
          key: "commissioning-forecast",
          requireRole: "isStaff",
          label: (
            <Link to="/commissioning/forecast">
              {t("commissioning.forecast")}
            </Link>
          ),
        },
        {
          key: "commissioning-documentation-current-stock",

          requireRole: "isStaff",
          label: (
            <Link to="/commissioning/documentation-current-stock">
              {t("commissioning.documentation_amounts")}
            </Link>
          ),
        },
        {
          key: "commissioning-documentation-harvest",

          requireRole: "isStaff",
          label: (
            <Link to="/commissioning/documentation-harvest">
              {t("commissioning.documentation_harvest")}
            </Link>
          ),
        },
        {
          key: "commissioning-documentation-purchase",

          requireRole: "isStaff",
          label: (
            <Link to="/commissioning/documentation-purchase">
              {t("commissioning.documentation_purchase")}
            </Link>
          ),
        },
        {
          key: "commissioning-documentation-waste",

          requireRole: "isStaff",
          label: (
            <Link to="/commissioning/documentation-waste">
              {t("commissioning.documentation_waste")}
            </Link>
          ),
        },
        {
          key: "commissioning-documentation-overview",

          requireRole: "isStaff",
          label: (
            <Link to="/commissioning/documentation-overview">
              {t("commissioning.documentation_overview")}
            </Link>
          ),
        },
        {
          key: "commissioning-logging-storage",

          requireRole: "isStaff",
          label: (
            <Link to="/commissioning/logging-storage">
              {t("commissioning.storage_logging")}
            </Link>
          ),
        },
      ],
    },
    {
      key: "commissioning-planning-share-content",

      requireRole: "isOffice",
      icon: <FavoriteIcon />,
      label: (
        <div className="sidebar-section-header">
          {t("commissioning.planning_share_content")}
        </div>
      ),
      children: [
        {
          key: "commissioning-share-days",

          requireRole: "isOffice",
          label: (
            <Link to="/commissioning/share-days">
              {t("commissioning.share_delivery_days")}
            </Link>
          ),
        },
        // The share import exists in the import-shares mode, but not where a
        // host imports the amounts on every visit.
        ...(weekly_upload && offersManualShareImport
          ? [
              {
                key: "commissioning-import-shares",

                requireRole: "isOffice",
                label: (
                  <Link to="/commissioning/import-shares">
                    {t("commissioning.import_shares")}
                  </Link>
                ),
              },
            ]
          : []),

        {
          key: "commissioning-amount-share-type-variations",

          requireRole: "isOffice",
          label: (
            <Link to="/commissioning/amount-share-type-variations">
              {t("commissioning.amount_share_type_variations")}
            </Link>
          ),
        },
        // Complex (per-week) planning links first, then the long-term links —
        // one pair per complex-planned share option.
        ...planningComplexItems,
        {
          key: "commissioning-purchase-list",

          requireRole: "isOffice",
          label: (
            <Link to="/commissioning/purchase-list">
              {t("commissioning.purchase_list")}
            </Link>
          ),
        },
        {
          key: "commissioning-statistics-purchase",

          requireRole: "isOffice",
          label: (
            <Link to="/commissioning/statistics-purchase">
              {t("commissioning.statistics_purchase")}
            </Link>
          ),
        },
        ...(showWeightStatistics
          ? [
              {
                key: "commissioning-statistics-share-weights",

                requireRole: "isOffice",
                label: (
                  <Link to="/commissioning/statistics-share-weights">
                    {t("commissioning.statistics_share_weights")}
                  </Link>
                ),
              },
            ]
          : []),
        ...planningLongTermItems,
      ],
    },
    // "Additional" section: simple (non-complex) share options — long-term
    // planning only.
    ...(additionalLongTermItems.length > 0
      ? [
          {
            key: "commissioning-planning-additional-shares",

            requireRole: "isOffice",
            icon: <EggIcon />,
            label: (
              <div className="sidebar-section-header">
                {t("commissioning.planning_additional_shares")}
              </div>
            ),
            children: additionalLongTermItems,
          },
        ]
      : []),
    ...(sells_to_resellers
      ? [
          {
            key: "commissioning-resellers",

            requireRole: "isOffice",
            icon: <AllInclusiveIcon />,
            label: (
              <div className="sidebar-section-header">
                {t("commissioning.resellers")}
              </div>
            ),
            children: [
              {
                key: "commissioning-offers",

                requireRole: "isOffice",
                label: (
                  <Link to="/commissioning/offers">
                    {t("commissioning.offers")}
                  </Link>
                ),
              },
              {
                key: "commissioning-orders",

                requireRole: "isOffice",
                label: (
                  <Link to="/commissioning/orders">
                    {t("commissioning.orders")}
                  </Link>
                ),
              },
              {
                key: "commissioning-delivery-notes",

                requireRole: "isOffice",
                label: (
                  <Link to="/commissioning/delivery-notes">
                    {t("commissioning.delivery_notes")}
                  </Link>
                ),
              },
              {
                key: "commissioning-invoices",

                requireRole: "isOffice",
                label: (
                  <Link to="/commissioning/invoices">
                    {t("commissioning.invoices")}
                  </Link>
                ),
              },

              {
                key: "commissioning-open-payments-resellers",

                requireRole: "isOffice",
                label: (
                  <Link to="/commissioning/payments-resellers">
                    {t("commissioning.open_payments_resellers")}
                  </Link>
                ),
              },
            ],
          },
        ]
      : []),
    ...marketSection,
    {
      key: "commissioning-harvesting-packing",

      requireRole: "isStaff",
      icon: <HdrWeakIcon />,

      label: (
        <div className="sidebar-section-header">
          {t("commissioning.harvesting_packing")}
        </div>
      ),
      children: [
        ...workListItems,
        {
          key: "commissioning-harvesting-lists",

          requireRole: "isStaff",
          label: (
            <Link to="/commissioning/harvesting-list">
              {t("commissioning.harvesting_lists")}
            </Link>
          ),
        },
        // The commissioning lists come before the packing lists.
        ...(showBoxesPackingList
          ? [
              {
                key: "commissioning-commissioning-list-packing",

                requireRole: "isStaff",
                label: (
                  <Link to="/commissioning/commissioning-list-packing">
                    {t("commissioning.commissioning_list_packing")}
                  </Link>
                ),
              },
            ]
          : []),
        ...(sells_to_resellers
          ? [
              {
                key: "commissioning-commissioning-list-resellers",

                requireRole: "isStaff",
                label: (
                  <Link to="/commissioning/commissioning-list-resellers">
                    {t("commissioning.commissioning_list_resellers_short")}
                  </Link>
                ),
              },
            ]
          : []),
        ...(showBulkPackingList
          ? [
              {
                key: "commissioning-packing-list-bulk",

                requireRole: "isStaff",
                label: (
                  <Link to="/commissioning/packing-list-bulk">
                    {packingMode === "MIXED"
                      ? t("commissioning.packing_list_bulk")
                      : t("commissioning.packing_list")}
                  </Link>
                ),
              },
            ]
          : []),
        ...(showBoxesPackingList
          ? [
              {
                key: "commissioning-packing-list-boxes",

                requireRole: "isStaff",
                label: (
                  <Link to="/commissioning/packing-list-boxes">
                    {packingMode === "MIXED"
                      ? t("commissioning.packing_list_boxes")
                      : t("commissioning.packing_list")}
                  </Link>
                ),
              },
            ]
          : []),
      ],
    },
    ...deliveryStationSection,
    {
      key: "commissioning-data",

      requireRole: "isStaff",
      icon: <BubbleChartIcon />,
      label: (
        <div className="sidebar-section-header">{t("commissioning.data")}</div>
      ),
      children: [
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
        {
          key: "commissioning-list-extra-articles",

          requireRole: "isOffice",
          label: (
            <Link to="/commissioning/list-extra-articles">
              {t("commissioning.list_extra_articles")}
            </Link>
          ),
        },

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

        ...(sells_to_resellers
          ? [
              {
                key: "commissioning-list-resellers",

                requireRole: "isOffice",
                label: (
                  <Link to="/commissioning/list-resellers">
                    {t("commissioning.list_resellers")}
                  </Link>
                ),
              },
              {
                key: "commissioning-list-offer-groups",

                requireRole: "isOffice",
                label: (
                  <Link to="/commissioning/list-offer-groups">
                    {t("commissioning.list_offer_groups")}
                  </Link>
                ),
              },
            ]
          : []),
        {
          key: "commissioning-list-sellers",

          requireRole: "isOffice",
          label: (
            <Link to="/commissioning/list-sellers">
              {t("commissioning.list_sellers")}
            </Link>
          ),
        },
        {
          key: "commissioning-list-plots",
          requireRole: "isStaff",
          label: (
            <Link to="/commissioning/list-plots">
              {t("commissioning.list_plots")}
            </Link>
          ),
        },
      ],
    },
  ];

  return (
    <SidebarShell
      header={t("nav.commissioning")}
      items={filterByRole(baseMenuItems as unknown as RoleGatedItem[], flags)}
      openKeys={Array.isArray(openKeys) ? openKeys : []}
      onOpenChange={onOpenChange}
    />
  );
}
