import AccountBalanceIcon from "@mui/icons-material/AccountBalance";
import BarChartIcon from "@mui/icons-material/BarChart";
import Diversity3Icon from "@mui/icons-material/Diversity3";
import QueryStatsIcon from "@mui/icons-material/QueryStats";
import TollIcon from "@mui/icons-material/Toll";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { filterByRole, useRoles, type RoleGatedItem } from "@shared/auth";
import { useTenant } from "@hooks/index";
import SidebarShell from "./SidebarShell";

interface MembersSidebarProps {
  collapsed?: boolean;
  openKeys?: string[];
  onOpenChange?: (keys: string[]) => void;
}

export default function MembersSidebar({
  openKeys,
  onOpenChange,
}: MembersSidebarProps) {
  const { getSetting } = useTenant();
  const { t } = useTranslation();
  const flags = useRoles();
  const uses_member_loans = getSetting("uses_member_loans", false);

  const items = [
    {
      key: "members-members",

      requireRole: "isOffice",
      icon: <Diversity3Icon />,
      label: <Link to="/members/members">{t("members.members")}</Link>,
    },

    ...(uses_member_loans
      ? [
          {
            key: "members-loans",

            requireRole: "isOffice",
            icon: <TollIcon />,
            label: <Link to="/members/loans">{t("members.loans")}</Link>,
          },
        ]
      : []),
    {
      key: "members-overview",

      requireRole: "isOffice",
      icon: <BarChartIcon />,
      label: (
        <Link to="/members/overview-members">{t("members.overview")}</Link>
      ),
    },
    {
      key: "members-statistics",

      requireRole: "isOffice",
      icon: <QueryStatsIcon />,
      label: <Link to="/members/statistics">{t("statistics.title")}</Link>,
    },
    {
      key: "members-sepa-mandates",

      requireRole: "isOffice",
      icon: <AccountBalanceIcon />,
      label: (
        <Link to="/members/sepa-mandates">{t("members.sepa_mandates")}</Link>
      ),
    },
  ];

  return (
    <SidebarShell
      header={t("nav.members")}
      items={filterByRole(items as unknown as RoleGatedItem[], flags)}
      openKeys={openKeys}
      onOpenChange={onOpenChange}
    />
  );
}
