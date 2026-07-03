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
  collapsed?: boolean;
  openKeys?: string[];
  onOpenChange?: (keys: string[]) => void;
}

export default function CultivationSidebar({
  collapsed: _collapsed = false,
  openKeys = [],
  onOpenChange,
}: CultivationSidebarProps) {
  const { t } = useTranslation();
  const flags = useRoles();

  const baseMenuItems = [
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
    {
      key: "cultivation-data",

      requireRole: "isGardener",
      icon: <BubbleChartIcon />,
      label: (
        <div className="sidebar-section-header">{t("cultivation.data")}</div>
      ),
      children: [
        {
          key: "cultivation-vegetable-families",

          requireRole: "isGardener",
          label: (
            <Link to="/cultivation/vegetable-families">
              {t("cultivation.vegetable_families")}
            </Link>
          ),
        },
        {
          key: "cultivation-plant-families",

          requireRole: "isGardener",
          label: (
            <Link to="/cultivation/plant-families">
              {t("cultivation.plant_families")}
            </Link>
          ),
        },
        {
          key: "cultivation-seller-seedlings",

          requireRole: "isGardener",
          label: (
            <Link to="/cultivation/seller-seedlings">
              {t("cultivation.seller_seedlings")}
            </Link>
          ),
        },
        {
          key: "cultivation-seller-seeds",

          requireRole: "isGardener",
          label: (
            <Link to="/cultivation/seller-seeds">
              {t("cultivation.seller_seeds")}
            </Link>
          ),
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
