import AppsIcon from "@mui/icons-material/Apps";
import BarChartIcon from "@mui/icons-material/BarChart";
import BlurCircularIcon from "@mui/icons-material/BlurCircular";
import BrowserNotSupportedIcon from "@mui/icons-material/BrowserNotSupported";
import CreditCardIcon from "@mui/icons-material/CreditCard";
import MailOutlineIcon from "@mui/icons-material/MailOutline";
import UnfoldMoreDoubleIcon from "@mui/icons-material/UnfoldMoreDouble";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { filterByRole, useRoles, type RoleGatedItem } from "@shared/auth";
import { useTenant } from "@hooks/index";
import SidebarShell from "./SidebarShell";

interface AboSidebarProps {
  collapsed?: boolean;
  openKeys?: string[];
  onOpenChange?: (keys: string[]) => void;
}

export default function AboSidebar({
  openKeys,
  onOpenChange,
}: AboSidebarProps) {
  const { t } = useTranslation();
  const flags = useRoles();
  const { getSetting } = useTenant();

  const uses_jokers = getSetting("uses_jokers", true);
  const uses_pledge_round = getSetting("abos.uses_pledge_round", false);
  const allows_waiting_list = getSetting(
    "allows_waiting_list_for_subscriptions",
    true,
  );

  const items = [
    {
      key: "abos-abos",

      requireRole: "isOffice",
      icon: <AppsIcon />,
      label: <Link to="/abos/abos">{t("abos.shares")}</Link>,
    },

    ...(allows_waiting_list
      ? [
          {
            key: "abos-waiting-list",

            requireRole: "isOffice",
            icon: <UnfoldMoreDoubleIcon />,
            label: (
              <Link to="/abos/waiting-list-abos">{t("abos.waiting_list")}</Link>
            ),
          },
        ]
      : []),
    {
      key: "abo-emails",

      requireRole: "isOffice",
      icon: <MailOutlineIcon />,
      label: <Link to="/abos/abos-emails">{t("abos.emails")}</Link>,
    },
    {
      key: "abos-deliveries-overview",

      requireRole: "isOffice",
      icon: <BarChartIcon />,
      label: (
        <Link to="/abos/share-deliveries">{t("abos.share_deliveries")}</Link>
      ),
    },
    ...(uses_jokers
      ? [
          {
            key: "abos-jokers",

            requireRole: "isOffice",
            icon: <BrowserNotSupportedIcon />,
            label: <Link to="/abos/jokers">{t("abos.overview_jokers")}</Link>,
          },
        ]
      : []),
    {
      key: "abos-charges",

      requireRole: "isOffice",
      icon: <CreditCardIcon />,
      label: <Link to="/abos/charges">{t("abos.charges")}</Link>,
    },
    {
      key: "abos-debits",

      requireRole: "isOffice",
      icon: <CreditCardIcon />,
      label: <Link to="/abos/debits-abos">{t("abos.debits")}</Link>,
    },

    ...(uses_pledge_round
      ? [
          {
            key: "abos-pledge-round",

            requireRole: "isOffice",
            icon: <BlurCircularIcon />,
            label: (
              <Link to="/abos/pledge-round">{t("abos.pledge_round")}</Link>
            ),
          },
        ]
      : []),
  ];

  return (
    <SidebarShell
      header={t("nav.abos")}
      items={filterByRole(items as unknown as RoleGatedItem[], flags)}
      openKeys={openKeys}
      onOpenChange={onOpenChange}
    />
  );
}
