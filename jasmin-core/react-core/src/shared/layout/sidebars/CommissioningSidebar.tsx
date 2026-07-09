import { useShareTypes, useTenant } from "@hooks/index";
import { useCommissioningDeliveryStationsList } from "@shared/api/generated/commissioning/commissioning";
import { filterByRole, useRoles, type RoleGatedItem } from "@shared/auth";
import {
  governingShareType,
  PLANNING_SHARE_OPTIONS,
} from "@shared/planning/planningShareOptions";
import dayjs from "dayjs";
import { toApiDate } from "@shared/utils/apiDate";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import SidebarShell from "./SidebarShell";

import AllInclusiveIcon from "@mui/icons-material/AllInclusive";
import BubbleChartIcon from "@mui/icons-material/BubbleChart";
import DirectionsBikeIcon from "@mui/icons-material/DirectionsBike";
import EggIcon from "@mui/icons-material/Egg";
import FavoriteIcon from "@mui/icons-material/Favorite";
import GrainIcon from "@mui/icons-material/Grain";
import HdrWeakIcon from "@mui/icons-material/HdrWeak";
import StorefrontIcon from "@mui/icons-material/Storefront";
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

  // Planning nav is derived from the currently-active ShareTypes: an option
  // whose active share type is complex-planned gets a per-week (Base) link AND
  // a long-term link; a simple option gets only a long-term link in the
  // "additional" section. Order follows PLANNING_SHARE_OPTIONS.
  const planningToday = toApiDate(dayjs())!;
  const { shareTypes: activePlanningShareTypes } = useShareTypes({
    active_at_date: planningToday,
    // Current + upcoming share types, so an option whose season hasn't started
    // yet still gets its planning nav (the old harvest links were unconditional).
    include_future: true,
  });
  // Group by option, then classify each by its GOVERNING share type (the one
  // active today, else the upcoming one) — a future successor must not change
  // today's section.
  const shareTypesByOption = new Map<string, typeof activePlanningShareTypes>();
  for (const st of activePlanningShareTypes) {
    if (!st.share_option) continue;
    const group = shareTypesByOption.get(st.share_option) ?? [];
    group.push(st);
    shareTypesByOption.set(st.share_option, group);
  }
  const complexByOption = new Map<string, boolean>();
  for (const [option, group] of shareTypesByOption) {
    const governing = governingShareType(group, planningToday);
    complexByOption.set(
      option,
      governing ? (governing.needs_complex_planning ?? true) : true,
    );
  }
  const activePlanningConfigs = PLANNING_SHARE_OPTIONS.filter((c) =>
    complexByOption.has(c.shareOption),
  );
  const complexPlanningOptions = activePlanningConfigs.filter((c) =>
    complexByOption.get(c.shareOption),
  );
  const simplePlanningOptions = activePlanningConfigs.filter(
    (c) => !complexByOption.get(c.shareOption),
  );

  const planningComplexItems: RoleGatedItem[] = complexPlanningOptions.map(
    (c) => ({
      key: `commissioning-planning-${c.slug}`,
      requireRole: "isOffice",
      label: (
        <Link to={`/commissioning/planning/${c.slug}`}>
          {t(c.complexSidebarKey)}
        </Link>
      ),
    }),
  );
  const planningLongTermItems: RoleGatedItem[] = complexPlanningOptions.map(
    (c) => ({
      key: `commissioning-planning-${c.slug}-long-term`,
      requireRole: "isOffice",
      label: (
        <Link to={`/commissioning/planning/${c.slug}/long-term`}>
          {/* When the option has no distinct long-term label (additional
              shares reuse one key for both modes), mark it "long-term" so a
              complex option's two links don't read identically. */}
          {c.complexSidebarKey === c.longTermSidebarKey
            ? t("commissioning.long_term_planning_of", {
                label: t(c.longTermSidebarKey),
              })
            : t(c.longTermSidebarKey)}
        </Link>
      ),
    }),
  );
  const additionalLongTermItems: RoleGatedItem[] = simplePlanningOptions.map(
    (c) => ({
      key: `commissioning-planning-${c.slug}-long-term`,
      requireRole: "isOffice",
      label: (
        <Link to={`/commissioning/planning/${c.slug}/long-term`}>
          {t(c.longTermSidebarKey)}
        </Link>
      ),
    }),
  );

  const has_markets = getSetting("has_markets", true);
  const sells_to_resellers = getSetting("sells_to_resellers", true);
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
      icon: <HdrWeakIcon />,

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
      icon: <DirectionsBikeIcon />,
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
