import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { filterByRole, useRoles, type RoleGatedItem } from "@shared/auth";
import { useActiveShareOptions, useTenant } from "@hooks/index";
import { useCommissioningDeliveryStationsList } from "@shared/api/generated/commissioning/commissioning";
import SidebarShell from "./SidebarShell";

import AllInclusiveIcon from "@mui/icons-material/AllInclusive";
import ApiIcon from "@mui/icons-material/Api";
import BubbleChartIcon from "@mui/icons-material/BubbleChart";
import EggIcon from "@mui/icons-material/Egg";
import FavoriteIcon from "@mui/icons-material/Favorite";
import HubIcon from "@mui/icons-material/Hub";
import LocalShippingIcon from "@mui/icons-material/LocalShipping";
import StorefrontIcon from "@mui/icons-material/Storefront";
interface CommissioningSidebarProps {
  collapsed?: boolean;
  openKeys?: string[];
  onOpenChange?: (keys: string[]) => void;
}

export default function CommissioningSidebar({
  collapsed: _collapsed = false,
  openKeys = [],
  onOpenChange,
}: CommissioningSidebarProps) {
  const { getSetting } = useTenant();
  const { t } = useTranslation();
  const flags = useRoles();
  const { activeShareOptions } = useActiveShareOptions();

  const fruit_and_veg_shares_are_separate =
    activeShareOptions.fruit_and_veg_shares_are_separate ?? false;

  const has_chicken_shares = activeShareOptions.CHICKEN_SHARE ?? false;
  const has_honey_shares = activeShareOptions.HONEY_SHARE ?? false;
  const has_grain_shares = activeShareOptions.GRAIN_SHARE ?? false;
  const has_oil_shares = activeShareOptions.OIL_SHARE ?? false;
  const has_bread_shares = activeShareOptions.BREAD_SHARE ?? false;
  const has_markets = getSetting("has_markets", true);
  const sells_to_resellers = getSetting("sells_to_resellers", true);
  const has_additional_shares =
    has_chicken_shares ||
    has_honey_shares ||
    has_grain_shares ||
    has_oil_shares ||
    has_bread_shares;
  const packing_mode = getSetting("packing_mode", "BOXES") as
    | "BOXES"
    | "BULK"
    | "MIXED";
  const show_bulk_packing_list =
    packing_mode === "BULK" || packing_mode === "MIXED";
  const show_boxes_packing_list =
    packing_mode === "BOXES" || packing_mode === "MIXED";
  const weekly_upload = getSetting("uploads_weekly_share_amount", false);

  // The station-fee billing is only relevant for solawis that actually charge
  // pickup-station fees. Fetch stations only for office users (the only ones who
  // could see the entry) and gate on any non-zero net fee.
  const { data: stationsForFeeGate } = useCommissioningDeliveryStationsList(
    {},
    { query: { enabled: flags.isOffice } },
  );
  const has_station_fees = (stationsForFeeGate ?? []).some(
    (station) =>
      Number(station.fee_per_box_net) > 0 ||
      Number(station.fee_per_month_net) > 0 ||
      Number(station.fee_per_year_net) > 0,
  );

  const baseMenuItems = [
    {
      key: "commissioning-amounts",
      requireRole: "isStaff",
      icon: <HubIcon />,
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
        ...(weekly_upload
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
          key: "commissioning-amount-shares",

          requireRole: "isOffice",
          label: (
            <Link to="/commissioning/amount-shares">
              {t("commissioning.amount_shares")}
            </Link>
          ),
        },
        ...(fruit_and_veg_shares_are_separate
          ? [
              {
                key: "commissioning-planning-harvest-shares-only",

                requireRole: "isOffice",
                label: (
                  <Link to="/commissioning/planning-harvest-shares">
                    {t("commissioning.harvest_shares_veg")}
                  </Link>
                ),
              },
              {
                key: "commissioning-planning-harvest-shares-fruits-only",

                requireRole: "isOffice",
                label: (
                  <Link to="/commissioning/planning-harvest-shares-fruits-only">
                    {t("commissioning.harvest_shares_fruits_only")}
                  </Link>
                ),
              },
              {
                key: "commissioning-planning-longterm-harvest-shares-veg-only",

                requireRole: "isOffice",
                label: (
                  <Link to="/commissioning/planning-longterm-harvest-shares-veg-only">
                    {t(
                      "commissioning.planning_longterm_harvest_shares_veg_only",
                    )}
                  </Link>
                ),
              },
              {
                key: "commissioning-planning-longterm-harvest-shares-fruits-only",

                requireRole: "isOffice",
                label: (
                  <Link to="/commissioning/planning-longterm-harvest-shares-fruits-only">
                    {t(
                      "commissioning.planning_longterm_harvest_shares_fruits_only",
                    )}
                  </Link>
                ),
              },
            ]
          : [
              {
                key: "commissioning-planning-harvest-shares-details",

                requireRole: "isOffice",
                label: (
                  <Link to="/commissioning/planning-harvest-shares">
                    {t("commissioning.harvest_shares_veg")}
                  </Link>
                ),
              },
              {
                key: "commissioning-planning-longterm-harvest-shares",

                requireRole: "isOffice",
                label: (
                  <Link to="/commissioning/planning-longterm-harvest-shares">
                    {t("commissioning.planning_longterm_harvest_shares")}
                  </Link>
                ),
              },
            ]),
        {
          key: "commissioning-purchase-list",

          requireRole: "isOffice",
          label: (
            <Link to="/commissioning/purchase-list">
              {t("commissioning.purchase_list")}
            </Link>
          ),
        },
      ],
    },
    ...(has_additional_shares
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
            children: [
              ...(has_chicken_shares
                ? [
                    {
                      key: "commissioning-planning-additional-chicken-shares",

                      requireRole: "isOffice",
                      label: (
                        <Link to="/commissioning/planning-additional-chicken-shares">
                          {t(
                            "commissioning.planning_additional_chicken_shares",
                          )}
                        </Link>
                      ),
                    },
                  ]
                : []),
              ...(has_oil_shares
                ? [
                    {
                      key: "commissioning-planning-additional-oil-shares",

                      requireRole: "isOffice",
                      label: (
                        <Link to="/commissioning/planning-additional-oil-shares">
                          {t("commissioning.planning_additional_oil_shares")}
                        </Link>
                      ),
                    },
                  ]
                : []),
              ...(has_grain_shares
                ? [
                    {
                      key: "commissioning-planning-additional-grain-shares",

                      requireRole: "isOffice",
                      label: (
                        <Link to="/commissioning/planning-additional-grain-shares">
                          {t("commissioning.planning_additional_grain_shares")}
                        </Link>
                      ),
                    },
                  ]
                : []),
              ...(has_honey_shares
                ? [
                    {
                      key: "commissioning-planning-additional-honey-shares",

                      requireRole: "isOffice",
                      label: (
                        <Link to="/commissioning/planning-additional-honey-shares">
                          {t("commissioning.planning_additional_honey_shares")}
                        </Link>
                      ),
                    },
                  ]
                : []),
              ...(has_bread_shares
                ? [
                    {
                      key: "commissioning-planning-additional-bread-shares",

                      requireRole: "isOffice",
                      label: (
                        <Link to="/commissioning/planning-additional-bread-shares">
                          {t("commissioning.planning_additional_bread_shares")}
                        </Link>
                      ),
                    },
                  ]
                : []),
            ],
          },
        ]
      : []),
    ...(sells_to_resellers
      ? [
          {
            key: "commissioning-resellers",

            requireRole: "isOffice",
            icon: <ApiIcon />,
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
                key: "commissioning-labels",

                requireRole: "isOffice",
                label: (
                  <Link to="/commissioning/labels">
                    {t("commissioning.labels")}
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
    ...(has_markets
      ? [
          {
            key: "commissioning-markets",

            requireRole: "isStaff",
            icon: <StorefrontIcon />,
            label: (
              <div className="sidebar-section-header">
                {t("commissioning.markets")}
              </div>
            ),
            children: [],
          },
        ]
      : []),
    {
      key: "commissioning-harvesting-packing",

      requireRole: "isStaff",
      icon: <AllInclusiveIcon />,
      label: (
        <div className="sidebar-section-header">
          {t("commissioning.harvesting_packing")}
        </div>
      ),
      children: [
        {
          key: "commissioning-washing-list",

          requireRole: "isStaff",
          label: (
            <Link to="/commissioning/washing-list">
              {t("commissioning.washing_list")}
            </Link>
          ),
        },
        {
          key: "commissioning-cleaning-list",

          requireRole: "isStaff",
          label: (
            <Link to="/commissioning/cleaning-list">
              {t("commissioning.cleaning_list")}
            </Link>
          ),
        },
        {
          key: "commissioning-harvesting-lists",

          requireRole: "isStaff",
          label: (
            <Link to="/commissioning/harvesting-list">
              {t("commissioning.harvesting_lists")}
            </Link>
          ),
        },
        ...(show_bulk_packing_list
          ? [
              {
                key: "commissioning-packing-list-bulk",

                requireRole: "isStaff",
                label: (
                  <Link to="/commissioning/packing-list-bulk">
                    {packing_mode === "MIXED"
                      ? t("commissioning.packing_list_bulk")
                      : t("commissioning.packing_list")}
                  </Link>
                ),
              },
            ]
          : []),
        ...(show_boxes_packing_list
          ? [
              {
                key: "commissioning-packing-list-boxes",

                requireRole: "isStaff",
                label: (
                  <Link to="/commissioning/packing-list-boxes">
                    {packing_mode === "MIXED"
                      ? t("commissioning.packing_list_boxes")
                      : t("commissioning.packing_list")}
                  </Link>
                ),
              },
              {
                key: "commissioning-share-weights",

                requireRole: "isStaff",
                label: (
                  <Link to="/commissioning/share-weights">
                    {t("commissioning.share_weights")}
                  </Link>
                ),
              },
            ]
          : []),
        {
          key: "commissioning-commissioning-list-packing",

          requireRole: "isStaff",
          label: (
            <Link to="/commissioning/commissioning-list-packing">
              {t("commissioning.commissioning_list_packing")}
            </Link>
          ),
        },
        {
          key: "commissioning-commissioning-list-resellers",

          requireRole: "isStaff",
          label: (
            <Link to="/commissioning/commissioning-list-resellers">
              {t("commissioning.commissioning_list_resellers_short")}
            </Link>
          ),
        },
      ],
    },
    {
      key: "commissioning-delivery-stations",

      requireRole: "isStaff",
      icon: <LocalShippingIcon />,
      label: (
        <div className="sidebar-section-header">
          {t("commissioning.delivery_stations")}
        </div>
      ),
      children: [
        {
          key: "commissioning-delivery-stations-overview",

          requireRole: "isStaff",
          label: (
            <Link to="/commissioning/delivery-stations-overview">
              {t("commissioning.tour_lists")}
            </Link>
          ),
        },
        {
          key: "commissioning-delivery-stations-details",

          requireRole: "isStaff",
          label: (
            <Link to="/commissioning/delivery-stations-details">
              {t("commissioning.pickup_lists")}
            </Link>
          ),
        },
        {
          key: "commissioning-list-delivery-stations",

          requireRole: "isStaff",
          label: (
            <Link to="/commissioning/list-delivery-stations">
              {t("commissioning.list_delivery_stations")}
            </Link>
          ),
        },
        {
          key: "commissioning-delivery-tours",

          requireRole: "isStaff",
          label: (
            <Link to="/commissioning/delivery-tours">
              {t("commissioning.delivery_tours")}
            </Link>
          ),
        },
        {
          key: "commissioning-delivery-exceptions",

          requireRole: "isStaff",
          label: (
            <Link to="/commissioning/delivery-exceptions">
              {t("commissioning.delivery_exceptions")}
            </Link>
          ),
        },
        // Only when at least one station actually charges a fee — most solawis
        // don't, so hide the billing entirely for them.
        ...(has_station_fees
          ? [
              {
                key: "commissioning-delivery-station-fees",

                requireRole: "isOffice",
                label: (
                  <Link to="/commissioning/delivery-station-fees">
                    {t("commissioning.station_fees")}
                  </Link>
                ),
              },
            ]
          : []),
      ],
    },
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

        ...(sells_to_resellers
          ? [
              {
                key: "commissioning-list-offer-groups",

                requireRole: "isOffice",
                label: (
                  <Link to="/commissioning/list-offer-groups">
                    {t("commissioning.list_offer_groups")}
                  </Link>
                ),
              },
              {
                key: "commissioning-list-resellers",

                requireRole: "isOffice",
                label: (
                  <Link to="/commissioning/list-resellers">
                    {t("commissioning.list_resellers")}
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
        ...(has_markets
          ? [
              {
                key: "commissioning-list-markets",

                requireRole: "isOffice",
                label: (
                  <Link to="/commissioning/list-markets">
                    {t("commissioning.list_markets")}
                  </Link>
                ),
              },
            ]
          : []),
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
