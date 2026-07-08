import { useTenant } from "@hooks/index";
import AccountBalanceIcon from "@mui/icons-material/AccountBalance";
import Diversity3Icon from "@mui/icons-material/Diversity3";
import MailOutlineIcon from "@mui/icons-material/MailOutline";
import PrivacyTipIcon from "@mui/icons-material/PrivacyTip";
import TollIcon from "@mui/icons-material/Toll";
import { filterByRole, useRoles, type RoleGatedItem } from "@shared/auth";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
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
      key: "members-sepa-mandates",

      requireRole: "isOffice",
      icon: <AccountBalanceIcon />,
      label: (
        <Link to="/members/sepa-mandates">{t("members.sepa_mandates")}</Link>
      ),
    },
    {
      key: "members-email-log",

      requireRole: "isOffice",
      icon: <MailOutlineIcon />,
      label: (
        <Link to="/members/email-log">{t("configuration.email_log")}</Link>
      ),
    },
    {
      key: "members-data-protection",

      requireRole: "isAdmin",
      icon: <PrivacyTipIcon />,
      label: (
        <Link to="/members/data-protection">{t("members.dsgvo_deletion")}</Link>
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
