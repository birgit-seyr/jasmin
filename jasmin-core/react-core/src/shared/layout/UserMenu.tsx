import {
  DownOutlined,
  GlobalOutlined,
  IdcardOutlined,
  LockOutlined,
  LogoutOutlined,
  SafetyOutlined,
  UserOutlined,
} from "@ant-design/icons";
import { Avatar, Button, Dropdown, Space } from "antd";
import type { MenuProps } from "antd";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { useCommissioningMembersRetrieve } from "@shared/api/generated/commissioning/commissioning";
import { useRoles } from "@shared/auth/useRoles";
import { useAuth } from "@shared/contexts/AuthContext";
import { useLocale } from "@shared/contexts/LocalContext";
import { useIsMobile } from "@hooks/index";
import UserProfileModal, { type UserProfileTab } from "./UserProfileModal";

export default function UserMenu() {
  const { t } = useTranslation();
  const { user, isAuthenticated, logout } = useAuth();
  const { language, saveLanguage } = useLocale();
  const { member, isStaff, isMemberOnly } = useRoles();
  const navigate = useNavigate();
  const isMobile = useIsMobile();
  const [profileOpen, setProfileOpen] = useState(false);
  const [profileTab, setProfileTab] = useState<UserProfileTab>("profile");

  // Member-id lookup pulled BEFORE the early-return below so the hook
  // call order is stable across renders (react-hooks/rules-of-hooks).
  // ``user`` may be null when unauthenticated — the destructure stays
  // safe via optional chaining, and ``enabled`` gates the actual
  // network call.
  const memberIdRaw = (user as { member_id?: string | number | null } | null)
    ?.member_id;
  const memberIdForGate =
    isMemberOnly && memberIdRaw != null ? String(memberIdRaw) : null;
  // When the viewer is a member-only user whose Member row is NOT
  // yet ``admin_confirmed`` (pending office review) — or already
  // ``admin_rejected_at`` (refused) — we strip the menu down to a
  // single logout option. Same reasoning as the MemberDetail gate:
  // half-rendered profile / data / language items behind a portal
  // they can't use read as broken. One clear "log out" link beats
  // a dozen no-ops.
  //
  // Office / staff viewers always get the full menu, even when their
  // own linked Member is unconfirmed (shouldn't happen, but
  // defensive).
  const { data: ownMember } = useCommissioningMembersRetrieve(
    memberIdForGate ?? "",
    { query: { enabled: !!memberIdForGate } },
  );

  if (!isAuthenticated) {
    return (
      <Button type="primary" onClick={() => navigate("/login")}>
        {t("auth.login")}
      </Button>
    );
  }

  const u = user as {
    first_name?: string;
    firstName?: string;
    last_name?: string;
    username?: string;
    email?: string;
    member_id?: string | number | null;
  } | null;

  const displayName =
    u?.first_name || u?.firstName || u?.username || u?.email || "";
  const initials = displayName
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((s) => s[0]?.toUpperCase() ?? "")
    .join("") || <UserOutlined />;
  const memberId = u?.member_id;

  const openProfile = (tab: UserProfileTab) => {
    setProfileTab(tab);
    setProfileOpen(true);
  };

  const gateMenu = (() => {
    if (!isMemberOnly || !ownMember) return false;
    return !ownMember.admin_confirmed || !!ownMember.admin_rejected_at;
  })();

  // The languages we support end-to-end: UI (i18n bundles), the backend
  // ``user_language`` choices (``LanguageChoices``), and the email-template
  // registry (which falls back to the default when a language has no template).
  const languages: { code: string; flag: string; label: string }[] = [
    { code: "de", flag: "🇩🇪", label: "Deutsch" },
    { code: "en", flag: "🇺🇸", label: "English" },
    { code: "fr", flag: "🇫🇷", label: "Français" },
    { code: "it", flag: "🇮🇹", label: "Italiano" },
  ];

  const items: MenuProps["items"] = gateMenu
    ? [
        {
          key: "logout",
          icon: <LogoutOutlined />,
          label: t("common.logout"),
          onClick: logout,
          danger: true,
        },
      ]
    : [
        {
          key: "profile",
          icon: <UserOutlined />,
          label: t("profile.title"),
          onClick: () => openProfile("profile"),
        },
        {
          key: "language",
          icon: <GlobalOutlined />,
          label: t("profile.menu_language"),
          children: languages.map((lang) => ({
            key: `language-${lang.code}`,
            label: (
              <Space>
                <span aria-hidden>{lang.flag}</span>
                <span>{lang.label}</span>
                {language === lang.code && (
                  <span aria-hidden style={{ marginLeft: "auto" }}>
                    ✓
                  </span>
                )}
              </Space>
            ),
            onClick: () => {
              void saveLanguage(lang.code);
            },
          })),
        },
        ...(isStaff && member && memberId
          ? [
              {
                key: "member-page",
                icon: <IdcardOutlined />,
                label: t("profile.my_member_page"),
                onClick: () => navigate(`/members/members/${memberId}`),
              },
            ]
          : []),
        { type: "divider" as const },
        {
          key: "my-data",
          icon: <SafetyOutlined />,
          label: t("profile.tab_my_data"),
          onClick: () => openProfile("my_data"),
        },
        {
          key: "two-factor",
          icon: <LockOutlined />,
          label: t("profile.tab_two_factor"),
          onClick: () => openProfile("two_factor"),
        },
        { type: "divider" as const },
        {
          key: "logout",
          icon: <LogoutOutlined />,
          label: t("common.logout"),
          onClick: logout,
          danger: true,
        },
      ];

  return (
    <>
      <Dropdown menu={{ items }} placement="bottomLeft" trigger={["click"]}>
        <Button
          type="text"
          className="user-menu-button"
          aria-label={t("profile.menu_aria")}
        >
          <Space>
            <Avatar
              size="small"
              style={{
                background: "var(--color-primary-hover)",
                color: "var(--color-bg-base)",
              }}
            >
              {initials}
            </Avatar>
            {!isMobile && (
              <>
                <span>{displayName}</span>
                <DownOutlined style={{ fontSize: 10 }} />
              </>
            )}
          </Space>
        </Button>
      </Dropdown>
      <UserProfileModal
        open={profileOpen}
        onClose={() => setProfileOpen(false)}
        initialTab={profileTab}
      />
    </>
  );
}
