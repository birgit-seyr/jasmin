import {
  LogoutOutlined,
  IdcardOutlined,
  UserOutlined,
} from "@ant-design/icons";
import { Button, Dropdown } from "antd";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { useAuth } from "@shared/contexts/AuthContext";
import { useRoles } from "@shared/auth/useRoles";
import { useIsMobile } from "@hooks/index";
import UserProfileModal from "./UserProfileModal";

export default function LoginButton() {
  const { user, isAuthenticated, logout } = useAuth();
  const navigate = useNavigate();
  const isMobile = useIsMobile();
  const { t } = useTranslation();
  const { member } = useRoles();
  const [profileOpen, setProfileOpen] = useState(false);
  const u = user as {
    first_name?: string;
    firstName?: string;
    username?: string;
    member_id?: string | number | null;
  } | null;
  const displayName = u?.first_name || u?.firstName || u?.username;
  const memberId = u?.member_id;

  const items = [
    {
      key: "profile",
      icon: <UserOutlined />,
      label: t("profile.title"),
      onClick: () => setProfileOpen(true),
    },
    ...(member && memberId
      ? [
          {
            key: "member-page",
            icon: <IdcardOutlined />,
            label: t("profile.my_member_page"),
            onClick: () => navigate(`/members/members/${memberId}`),
          },
        ]
      : []),
    {
      key: "logout",
      icon: <LogoutOutlined />,
      label: t("common.logout"),
      onClick: logout,
      danger: true,
    },
  ];

  return isAuthenticated ? (
    <>
      <Dropdown menu={{ items }} placement="bottomRight" trigger={["click"]}>
        <Button
          className="login-button"
          style={
            isMobile
              ? { width: "32px", height: "32px", padding: 0 }
              : { width: "auto", minWidth: "fit-content" }
          }
          icon={isMobile ? <UserOutlined /> : undefined}
        >
          {!isMobile && displayName}
        </Button>
      </Dropdown>
      <UserProfileModal
        open={profileOpen}
        onClose={() => setProfileOpen(false)}
      />
    </>
  ) : (
    <Button type="primary" onClick={() => navigate("/login")}>
      Login
    </Button>
  );
}
