import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { filterByRole, useRoles, type RoleGatedItem } from "@shared/auth";
import SidebarShell from "./SidebarShell";

import BlurOnIcon from "@mui/icons-material/BlurOn";
import BubbleChartIcon from "@mui/icons-material/BubbleChart";
import CloudySnowingIcon from "@mui/icons-material/CloudySnowing";
import EmojiNatureIcon from "@mui/icons-material/EmojiNature";
import FilterVintageIcon from "@mui/icons-material/FilterVintage";
import LightModeIcon from "@mui/icons-material/LightMode";
import LineWeightIcon from "@mui/icons-material/LineWeight";
import LocalFloristIcon from "@mui/icons-material/LocalFlorist";

interface CultivationSidebarProps {
  openKeys?: string[];
  onOpenChange?: (keys: string[]) => void;
}

export default function CultivationSidebar({
  openKeys = [],
  onOpenChange,
}: CultivationSidebarProps) {
  const { t } = useTranslation();
  const flags = useRoles();

  const baseMenuItems = [
    {
      key: "cultivation-planner",
      requireRole: "isGardener",
      icon: <BubbleChartIcon />,
      label: (
        <Link to="/cultivation/planner">{t("cultivation.planner")}</Link>
      ),
    },
    {
      key: "cultivation-amounts-for-cultivation",

      requireRole: "isGardener",
      icon: <LineWeightIcon />,
      label: (
        <Link to="/cultivation/amounts-for-cultivation">
          {t("cultivation.amounts_for_cultivation")}
        </Link>
      ),
    },
    {
      key: "cultivation-outdoors-cultivation",

      requireRole: "isGardener",
      icon: <CloudySnowingIcon />,
      label: (
        <div className="sidebar-section-header">
          {t("cultivation.outdoors_cultivation")}
        </div>
      ),
      children: [
        {
          key: "cultivation-sets-outdoors",

          requireRole: "isGardener",
          label: (
            <Link to="/cultivation/sets-outdoors">
              {t("cultivation.sets_outdoors")}
            </Link>
          ),
        },
        {
          key: "cultivation-sorts-seedlings-outdoors",

          requireRole: "isGardener",
          label: (
            <Link to="/cultivation/sorts-seedlings-outdoors">
              {t("cultivation.sorts_seedlings_outdoors")}
            </Link>
          ),
        },
        {
          key: "cultivation-sorts-seeds-outdoors",

          requireRole: "isGardener",
          label: (
            <Link to="/cultivation/sorts-seeds-outdoors">
              {t("cultivation.sorts_seeds_outdoors")}
            </Link>
          ),
        },
      ],
    },
    {
      key: "cultivation-indoors-cultivation",

      requireRole: "isGardener",
      icon: <LightModeIcon />,
      label: (
        <div className="sidebar-section-header">
          {t("cultivation.indoors_cultivation")}
        </div>
      ),
      children: [
        {
          key: "cultivation-sets-indoors",

          requireRole: "isGardener",
          label: (
            <Link to="/cultivation/sets-indoors">
              {t("cultivation.sets_indoors")}
            </Link>
          ),
        },
        {
          key: "cultivation-sorts-seedlings-indoors",

          requireRole: "isGardener",
          label: (
            <Link to="/cultivation/sorts-seedlings-indoors">
              {t("cultivation.sorts_seedlings_indoors")}
            </Link>
          ),
        },
        {
          key: "cultivation-sorts-seeds-indoors",

          requireRole: "isGardener",
          label: (
            <Link to="/cultivation/sorts-seeds-indoors">
              {t("cultivation.sorts_seeds_indoors")}
            </Link>
          ),
        },
      ],
    },
    {
      key: "cultivation-working-lists",
      requireRole: "isGardener",
      icon: <LightModeIcon />,
      label: (
        <div className="sidebar-section-header">
          {t("cultivation.working_lists")}
        </div>
      ),
      children: [
        {
          key: "cultivation-list-planting",

          requireRole: "isGardener",
          icon: <EmojiNatureIcon />,
          label: (
            <Link to="/cultivation/list-planting">
              {t("cultivation.list_planting")}
            </Link>
          ),
        },
        {
          key: "cultivation-list-sowing",

          requireRole: "isGardener",
          icon: <BlurOnIcon />,
          label: (
            <Link to="/cultivation/list-sowing">
              {t("cultivation.list_sowing")}
            </Link>
          ),
        },
      ],
    },
    {
      key: "cultivation-order-lists",
      requireRole: "isGardener",
      icon: <LightModeIcon />,
      label: (
        <div className="sidebar-section-header">
          {t("cultivation.order_lists")}
        </div>
      ),
      children: [
        {
          key: "cultivation-order-seedlings",

          requireRole: "isGardener",
          icon: <EmojiNatureIcon />,
          label: (
            <Link to="/cultivation/order-seedlings">
              {t("cultivation.order_seedlings")}
            </Link>
          ),
        },
        {
          key: "cultivation-order-seeds",

          requireRole: "isGardener",
          icon: <BlurOnIcon />,
          label: (
            <Link to="/cultivation/order-seeds">
              {t("cultivation.order_seeds")}
            </Link>
          ),
        },
      ],
    },
    {
      key: "cultivation-documentation",
      requireRole: "isGardener",
      icon: <LightModeIcon />,
      label: (
        <div className="sidebar-section-header">
          {t("cultivation.documentation")}
        </div>
      ),
      children: [
        {
          key: "cultivation-fertilizer",

          requireRole: "isGardener",
          icon: <LocalFloristIcon />,
          label: (
            <Link to="/cultivation/documentation-fertilizers">
              {t("cultivation.documentation_fertilizer")}
            </Link>
          ),
        },
        {
          key: "cultivation-pesticides",

          requireRole: "isGardener",
          icon: <FilterVintageIcon />,
          label: (
            <Link to="/cultivation/documentation-pesticides">
              {t("cultivation.documentation_pesticides")}
            </Link>
          ),
        },
      ],
    },
    {
      key: "cultivation-data",
      requireRole: "isGardener",
      icon: <BubbleChartIcon />,
      label: (
        <div className="sidebar-section-header">{t("cultivation.data")}</div>
      ),
      children: [
        {
          key: "cultivation-areas",
          requireRole: "isGardener",
          label: t("cultivation.areas"),
          children: [
            {
              key: "cultivation-plots",
              requireRole: "isGardener",
              label: (
                <Link to="/cultivation/plots">
                  {t("cultivation.list_plots")}
                </Link>
              ),
            },
            {
              key: "cultivation-solver-settings",
              requireRole: "isGardener",
              label: (
                <Link to="/cultivation/solver-settings">
                  {t("cultivation.solver_settings")}
                </Link>
              ),
            },
            {
              key: "cultivation-bed-types",
              requireRole: "isGardener",
              label: (
                <Link to="/cultivation/bed-types">
                  {t("cultivation.list_bed_types")}
                </Link>
              ),
            },
          ],
        },
        {
          key: "cultivation-botanical-data",
          requireRole: "isGardener",
          label: t("cultivation.botanical_data"),
          children: [
            {
              key: "cultivation-vegetables",
              requireRole: "isGardener",
              label: (
                <Link to="/cultivation/list-vegetable-families">
                  {t("cultivation.list_vegetables")}
                </Link>
              ),
            },
            {
              key: "cultivation-vegetable-aggregations",
              requireRole: "isGardener",
              label: (
                <Link to="/cultivation/vegetable-aggregations">
                  {t("cultivation.list_vegetable_aggregations")}
                </Link>
              ),
            },
            {
              key: "cultivation-break-families",
              requireRole: "isGardener",
              label: (
                <Link to="/cultivation/break-families">
                  {t("cultivation.list_break_families")}
                </Link>
              ),
            },
          ],
        },
        {
          key: "cultivation-vendors",
          requireRole: "isGardener",
          label: t("cultivation.vendors"),
          children: [
            {
              key: "cultivation-seedlings-vendors",
              requireRole: "isGardener",
              label: (
                <Link to="/cultivation/seedlings-vendors">
                  {t("cultivation.list_seedlings_vendors")}
                </Link>
              ),
            },
            {
              key: "cultivation-seeds-vendors",
              requireRole: "isGardener",
              label: (
                <Link to="/cultivation/seeds-vendors">
                  {t("cultivation.list_seeds_vendors")}
                </Link>
              ),
            },
          ],
        },
      ],
    },
  ];

  return (
    <SidebarShell
      header={t("nav.cultivation")}
      items={filterByRole(baseMenuItems as unknown as RoleGatedItem[], flags)}
      openKeys={openKeys}
      onOpenChange={onOpenChange}
    />
  );
}
