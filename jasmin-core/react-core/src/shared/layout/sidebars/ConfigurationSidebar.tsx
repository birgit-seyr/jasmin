import { SettingOutlined } from "@ant-design/icons";
import { filterByRole, useRoles, type RoleGatedItem } from "@shared/auth";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import SidebarShell from "./SidebarShell";

interface ConfigurationSidebarProps {
  openKeys?: string[];
  onOpenChange?: (keys: string[]) => void;
}

export default function ConfigurationSidebar({
  openKeys,
  onOpenChange,
}: ConfigurationSidebarProps) {
  const { t } = useTranslation();
  const flags = useRoles();

  const items = [
    {
      type: "group",
      key: "configuration-group-general",
      label: t("configuration.group.general"),
      children: [
        {
          key: "configuration-app",
          requireRole: "isAdmin",
          icon: <SettingOutlined />,
          label: <Link to="/configuration/app">{t("configuration.app")}</Link>,
        },
        {
          key: "configuration-general",
          requireRole: "isAdmin",
          icon: <SettingOutlined />,
          label: (
            <Link to="/configuration/general">
              {t("configuration.general")}
            </Link>
          ),
        },
        {
          key: "configuration-users",
          requireRole: "isAdmin",
          icon: <SettingOutlined />,
          label: <Link to="/configuration/users">{t("users.title")}</Link>,
        },
        {
          key: "configuration-email",
          requireRole: "isAdmin",
          icon: <SettingOutlined />,
          label: (
            <Link to="/configuration/email">{t("configuration.email")}</Link>
          ),
        },
        {
          key: "configuration-email-templates-general",
          requireRole: "isAdmin",
          icon: <SettingOutlined />,
          label: (
            <Link to="/configuration/email-templates/general">
              {t("configuration.email_templates")}
            </Link>
          ),
        },
      ],
    },

    {
      type: "group",
      key: "configuration-group-members",
      label: t("configuration.group.members"),
      children: [
        {
          key: "configuration-members",
          requireRole: "isAdmin",
          icon: <SettingOutlined />,
          label: (
            <Link to="/configuration/members">
              {t("configuration.members")}
            </Link>
          ),
        },
        {
          key: "configuration-subscriptions",
          requireRole: "isAdmin",
          icon: <SettingOutlined />,
          label: (
            <Link to="/configuration/subscriptions">
              {t("configuration.subscriptions")}
            </Link>
          ),
        },
        {
          key: "configuration-payments",
          requireRole: "isAdmin",
          icon: <SettingOutlined />,
          label: (
            <Link to="/configuration/payments">
              {t("configuration.payments")}
            </Link>
          ),
        },
        {
          key: "configuration-gdpr",
          requireRole: "isAdmin",
          icon: <SettingOutlined />,
          label: (
            <Link to="/configuration/gdpr">
              {t("configuration.data_protection")}
            </Link>
          ),
        },
        {
          key: "configuration-consents",
          requireRole: "isAdmin",
          icon: <SettingOutlined />,
          label: (
            <Link to="/configuration/consents">{t("consent.admin.title")}</Link>
          ),
        },
        {
          key: "configuration-email-templates-members",
          requireRole: "isAdmin",
          icon: <SettingOutlined />,
          label: (
            <Link to="/configuration/email-templates/members">
              {t("configuration.email_templates")}
            </Link>
          ),
        },
      ],
    },
    {
      type: "group",
      key: "configuration-group-commissioning",
      label: t("configuration.group.commissioning"),
      children: [
        {
          key: "configuration-share-type-variations",
          requireRole: "isAdmin",
          icon: <SettingOutlined />,
          label: (
            <Link to="/configuration/share-type-variations">
              {t("configuration.share_type_variations")}
            </Link>
          ),
        },
        {
          key: "configuration-time-management",
          requireRole: "isAdmin",
          icon: <SettingOutlined />,
          label: (
            <Link to="/configuration/time-management">
              {t("configuration.delivery_days")}
            </Link>
          ),
        },
        {
          key: "configuration-delivery-exceptions",
          requireRole: "isAdmin",
          icon: <SettingOutlined />,
          label: (
            <Link to="/configuration/delivery-exceptions">
              {t("commissioning.delivery_exceptions")}
            </Link>
          ),
        },
        {
          key: "configuration-commissioning",
          requireRole: "isAdmin",
          icon: <SettingOutlined />,
          label: (
            <Link to="/configuration/commissioning">
              {t("configuration.commissioning")}
            </Link>
          ),
        },

        {
          key: "configuration-reseller-documents",
          requireRole: "isAdmin",
          icon: <SettingOutlined />,
          label: (
            <Link to="/configuration/reseller-documents">
              {t("configuration.reseller_documents")}
            </Link>
          ),
        },
        {
          key: "configuration-email-templates-resellers",
          requireRole: "isAdmin",
          icon: <SettingOutlined />,
          label: (
            <Link to="/configuration/email-templates/resellers">
              {t("configuration.email_templates")}
            </Link>
          ),
        },
      ],
    },
  ];

  return (
    <SidebarShell
      header={t("configuration.sidebar-header")}
      items={filterByRole(items as unknown as RoleGatedItem[], flags)}
      openKeys={openKeys}
      onOpenChange={onOpenChange}
    />
  );
}
